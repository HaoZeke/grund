"""Polite client for the Statistics Iceland PxWeb v1 API.

The live configuration is published at
https://px.hagstofa.is/pxen/api/v1/en/?config
and https://px.hagstofa.is/pxis/api/v1/is/?config
(English 100 calls per 10 seconds, Icelandic 300, maxCells 100000, maxValues 5000).

The 429s this API sent while we scored carried Retry-After: 10, so the
steady pace is one call per 10 seconds, far under the published window.
GET metadata and POST data are cached on disk with separate TTLs.
A 429 or 503 honours Retry-After, or else waits with jitter, and a question
stops waiting after QUESTION_WAIT seconds. A dated mirror, when GRUND_MIRROR_DIR
is set, answers the same POST without a live call.

Each tuning number below says where it comes from. A number with no
published or measured source says so and can be changed with a GRUND_PX_*
environment setting.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

USER_AGENT = "Grund/0.1 (GAGNATHON 2026; rgoswami@ieee.org)"

# Published by PxWeb ?config on both endpoints, read 2026-11-03:
# {"maxValues":5000,"maxCells":100000,"maxCalls":100,"timeWindow":10} for
# English, and maxCalls 300 with the same timeWindow for Icelandic.
PX_TIME_WINDOW = 10.0
PX_MAX_CALLS_EN = 100
PX_MAX_CALLS_IS = 300
MAX_CELLS = 100_000
MAX_VALUES = 5_000

# Measured, not published: every 429 seen while scoring carried Retry-After: 10.
OBSERVED_RETRY_AFTER = 10.0

# Reasoning: one call per observed Retry-After never earns a 429 of its own.
DEFAULT_RATE = 1.0 / OBSERVED_RETRY_AFTER
SAFE_WINDOW = PX_TIME_WINDOW
DEFAULT_CALLS = max(1, round(DEFAULT_RATE * SAFE_WINDOW))
# Reasoning: the published limit counts per IP and the demo host shares its
# address, so no setting goes above a tenth of the lower (English) maxCalls.
# The fraction is our margin, not a PxWeb number.
SAFE_CALLS = PX_MAX_CALLS_EN // 10

# No published or measured source for the numbers below. They are our
# choices, each overridable through the named GRUND_PX_* setting.
# Two in flight lets one slow call overlap the next paced call (GRUND_PX_CONCURRENCY).
DEFAULT_CONCURRENCY = 2
# PxWeb publishes no concurrency limit; 4 is a guard against a typo (GRUND_PX_CONCURRENCY_MAX).
MAX_CONCURRENCY = 4
# Reasoning: more calls in flight than SAFE_CALLS allows per window can only
# queue, so no setting raises the concurrency cap past it.
CONCURRENCY_CEILING = SAFE_CALLS
# Metadata changes only when a table is republished (GRUND_PX_META_TTL).
META_TTL = 7 * 24 * 3600
# Data queries may change on any update day, so they expire sooner (GRUND_PX_DATA_TTL).
DATA_TTL = 6 * 3600
# How long one question may wait on the API before it answers (GRUND_PX_QUESTION_WAIT).
QUESTION_WAIT = 15.0
# First 429 backoff without Retry-After, doubled each time up to the max
# (GRUND_PX_BACKOFF, GRUND_PX_BACKOFF_MAX).
BACKOFF_START = 0.4
BACKOFF_MAX = 8.0
# Jitter adds up to this fraction of the backoff.
BACKOFF_JITTER = 0.5
# Longest network-error retry delay (GRUND_PX_NETWORK_RETRY_MAX).
NETWORK_RETRY_MAX = 1.0
# Longest single pause, whatever Retry-After asks (GRUND_PX_PAUSE_MAX).
PAUSE_MAX = 120.0
# Tries per request, retries included (GRUND_PX_ATTEMPTS).
ATTEMPTS = 8
# Seconds one HTTP call may take before it counts as a network error (GRUND_PX_TIMEOUT).
REQUEST_TIMEOUT = 60.0

# Mechanical constants, not tuning: polling and float slack.
_POLL = 0.02
_SLACK = 0.01
# Under 50 ms of question budget is too little to start a call, so the question stops waiting.
_BUDGET_FLOOR = 0.05
# Our choice: a nearly spent budget still gives a call 200 ms, since less fails before most replies arrive.
_MIN_TIMEOUT = 0.2
# Float rounding allowance when a sleep is compared with the budget left.
_EPSILON = 1e-9


def setting(name: str, default: float) -> float:
    """A GRUND_PX_* number from the environment, or the default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return float(default)
    return float(raw)

RATE_LIMIT_MESSAGE = "Statistics Iceland is rate-limiting requests. Try again in a minute."

BASE = {
    "en": "https://px.hagstofa.is/pxen/api/v1/en",
    "is": "https://px.hagstofa.is/pxis/api/v1/is",
}


class PxWebError(RuntimeError):
    def __init__(
        self,
        message: str,
        status: int | None = None,
        url: str | None = None,
        rate_limited: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.url = url
        self.rate_limited = rate_limited or status in {429, 503}


@dataclass
class FetchInfo:
    """Where the last payload came from. The answer card reads this."""

    origin: str = "live"
    stale: bool = False
    fetched_at: str | None = None
    updated: str | None = None
    snapshot: str | None = None


class _Budget:
    def __init__(self, limit: float) -> None:
        self.limit = limit
        self.spent = 0.0

    def remaining(self) -> float:
        return self.limit - self.spent


_budget: ContextVar[_Budget | None] = ContextVar("grund_px_budget", default=None)
_fetch_info: ContextVar[FetchInfo] = ContextVar("grund_px_fetch", default=FetchInfo())


def push_question_budget(seconds: float | None = None) -> object | None:
    """Start the per-question wait cap. Nested calls keep the outer cap."""
    if _budget.get() is not None:
        return None
    if seconds is None:
        seconds = setting("GRUND_PX_QUESTION_WAIT", QUESTION_WAIT)
    return _budget.set(_Budget(seconds))


def pop_question_budget(token: object | None) -> None:
    if token is not None:
        _budget.reset(token)


def budget_remaining() -> float | None:
    budget = _budget.get()
    if budget is None:
        return None
    return budget.remaining()


def charge(seconds: float) -> None:
    budget = _budget.get()
    if budget is not None and seconds > 0:
        budget.spent += seconds


def last_fetch() -> FetchInfo:
    return _fetch_info.get()


def clear_fetch() -> None:
    _fetch_info.set(FetchInfo())


def _remember(info: FetchInfo) -> None:
    _fetch_info.set(info)


def sleep_budget(seconds: float, *, exact: bool) -> bool:
    """Wait, but not past the question cap.

    exact is for Retry-After: if it does not fit, do not sleep at all.
    A backoff may use whatever part of the cap is left, then stop.
    """
    if seconds < 0:
        seconds = 0.0
    remaining = budget_remaining()
    if remaining is None:
        if seconds > 0:
            time.sleep(min(seconds, setting("GRUND_PX_PAUSE_MAX", PAUSE_MAX)))
        return True
    if remaining <= _BUDGET_FLOOR:
        return False
    if seconds > remaining + _EPSILON:
        if exact:
            return False
        seconds = remaining
    started = time.monotonic()
    if seconds > 0:
        time.sleep(seconds)
    charge(time.monotonic() - started)
    if exact:
        return True
    left = budget_remaining()
    return left is None or left > _BUDGET_FLOOR


def canonical_json(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def post_cache_key(url: str, body: Any) -> str:
    path = urllib.parse.urlsplit(url).path
    return path + "\n" + canonical_json(body)


def _now_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _retry_after(header: str | None) -> float | None:
    if header is None:
        return None
    raw = header.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return max(0.0, when.timestamp() - time.time())


_SHARED: "RateLimiter | None" = None
_SHARED_LOCK = threading.Lock()
_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


def _shared_semaphore(concurrency: int) -> threading.BoundedSemaphore:
    with _SHARED_LOCK:
        sem = _SEMAPHORES.get(concurrency)
        if sem is None:
            sem = threading.BoundedSemaphore(max(1, concurrency))
            _SEMAPHORES[concurrency] = sem
        return sem


def shared_settings() -> tuple[int, float, int]:
    """Calls per window, window seconds and concurrency from GRUND_PX_*, clamped."""
    calls = int(setting("GRUND_PX_MAX_CALLS", DEFAULT_CALLS))
    calls = max(1, min(SAFE_CALLS, calls))
    window = setting("GRUND_PX_WINDOW", SAFE_WINDOW)
    cap = min(CONCURRENCY_CEILING, int(setting("GRUND_PX_CONCURRENCY_MAX", MAX_CONCURRENCY)))
    concurrency = int(setting("GRUND_PX_CONCURRENCY", DEFAULT_CONCURRENCY))
    return calls, window, max(1, min(cap, concurrency))


def shared_limiter() -> "RateLimiter":
    """One limiter for every PxWeb call in this process."""
    global _SHARED
    with _SHARED_LOCK:
        existing = _SHARED
    if existing is not None:
        return existing
    calls, window, concurrency = shared_settings()
    created = RateLimiter(per_window=calls, window=window, concurrency=concurrency)
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = created
        return _SHARED


class RateLimiter:
    """At most `per_window` calls in each `window` seconds, and a concurrency cap.

    `rate` is calls per second, turned into a count per window and held
    under SAFE_CALLS. Pass per_window to set the count directly.
    """

    def __init__(
        self,
        rate: float = DEFAULT_RATE,
        *,
        per_window: int | None = None,
        window: float = SAFE_WINDOW,
        concurrency: int = DEFAULT_CONCURRENCY,
        lock_path: Path | None = None,
        private: bool = False,
    ) -> None:
        self.window = window
        if per_window is None:
            requested = max(1, int(round(float(rate) * window)))
            self.per_window = min(SAFE_CALLS, requested)
        else:
            self.per_window = max(1, int(per_window))
        self.lock_path = Path(lock_path) if lock_path else None
        self._times: list[float] = []
        self._paused_until = 0.0
        self._lock = threading.Lock()
        width = max(1, concurrency)
        self._sem = threading.BoundedSemaphore(width) if private else _shared_semaphore(width)

    def acquire(self, max_wait: float | None = None) -> bool:
        """Reserve a slot. False means the wait would pass max_wait."""
        deadline = None if max_wait is None else time.monotonic() + max(0.0, max_wait)
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if not self._sem.acquire(blocking=False):
                time.sleep(_POLL)
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                continue
            delay = self._reserve_or_delay()
            if delay <= 0:
                return True
            self._sem.release()
            # Steady pacing stays outside the question cap. Retry-After does not.
            if deadline is not None and delay > deadline - time.monotonic():
                return False
            if delay > 0:
                time.sleep(delay)

    def release(self) -> None:
        try:
            self._sem.release()
        except ValueError:
            return

    def wait(self) -> None:
        """Pace one call without holding a concurrency slot."""
        if not self.acquire(max_wait=budget_remaining()):
            raise PxWebError(RATE_LIMIT_MESSAGE, status=429, rate_limited=True)
        self.release()

    def pause(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.lock_path is not None:
            self._file_pause(seconds)
            return
        with self._lock:
            until = time.monotonic() + seconds
            if until > self._paused_until:
                self._paused_until = until

    def _reserve_or_delay(self) -> float:
        if self.lock_path is not None:
            return self._file_reserve()
        with self._lock:
            now = time.monotonic()
            if self._paused_until > now:
                return self._paused_until - now
            self._times = [stamp for stamp in self._times if now - stamp < self.window]
            if len(self._times) >= self.per_window:
                return self.window - (now - self._times[0]) + _SLACK
            gap = self.window / self.per_window
            if self._times and now - self._times[-1] < gap:
                return gap - (now - self._times[-1])
            self._times.append(now)
            return 0.0

    def _file_reserve(self) -> float:
        assert self.lock_path is not None
        state = self._with_file(self._take_file_slot)
        return float(state)

    def _take_file_slot(self, payload: dict[str, Any]) -> float:
        now = time.time()
        paused = float(payload.get("paused_until") or 0.0)
        if paused > now:
            return paused - now
        times = [float(item) for item in (payload.get("times") or []) if now - float(item) < self.window]
        if len(times) >= self.per_window:
            payload["times"] = times
            return self.window - (now - times[0]) + _SLACK
        gap = self.window / self.per_window
        if times and now - times[-1] < gap:
            payload["times"] = times
            return gap - (now - times[-1])
        times.append(now)
        payload["times"] = times
        payload["paused_until"] = paused
        return 0.0

    def _file_pause(self, seconds: float) -> None:
        until = time.time() + seconds

        def update(payload: dict[str, Any]) -> float:
            payload["paused_until"] = max(float(payload.get("paused_until") or 0.0), until)
            return 0.0

        self._with_file(update)

    def _with_file(self, fn) -> float:
        assert self.lock_path is not None
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl

        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            raw = handle.read()
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            result = fn(payload)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(payload))
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return result


class PxWebClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout: float | None = None,
        limiter: RateLimiter | None = None,
        meta_ttl: float | None = None,
        data_ttl: float | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = setting("GRUND_PX_TIMEOUT", REQUEST_TIMEOUT) if timeout is None else float(timeout)
        self.meta_ttl = setting("GRUND_PX_META_TTL", META_TTL) if meta_ttl is None else float(meta_ttl)
        self.data_ttl = setting("GRUND_PX_DATA_TTL", DATA_TTL) if data_ttl is None else float(data_ttl)
        if limiter is not None:
            self.limiter = limiter
        else:
            self.limiter = shared_limiter()
            if self.cache_dir is not None and self.limiter.lock_path is None:
                self.limiter.lock_path = self.cache_dir / ".pxweb-rate"
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str, *, use_cache: bool = True) -> Any:
        fresh, stale_body, fetched_at = (None, None, None)
        if use_cache:
            fresh, stale_body, fetched_at = self._lookup(self._cache_path(url), self.meta_ttl)
        if fresh is not None:
            _remember(FetchInfo(origin="cache", stale=False, fetched_at=fetched_at))
            return fresh
        try:
            payload = self._request(url)
        except PxWebError as exc:
            return self._or_stale(exc, stale_body, fetched_at, url)
        self._store(self._cache_path(url), url, payload)
        _remember(FetchInfo(origin="live", stale=False, fetched_at=_now_stamp()))
        return payload

    def post_json(self, url: str, body: dict[str, Any], *, live: bool = False, use_cache: bool = True) -> Any:
        if not live:
            from grund_index.mirror import query_mirror

            mirrored = query_mirror(url, body, allow_stale=False)
            if mirrored is not None:
                payload, info = mirrored
                _remember(info)
                return payload
        fresh, stale_body, fetched_at = (None, None, None)
        if use_cache:
            fresh, stale_body, fetched_at = self._lookup(self._post_paths(url, body), self.data_ttl)
        if fresh is not None:
            _remember(FetchInfo(origin="cache", stale=False, fetched_at=fetched_at))
            return fresh
        raw = canonical_json(body).encode("utf-8")
        try:
            payload = self._request(
                url,
                data=raw,
                headers={"Content-Type": "application/json"},
            )
        except PxWebError as exc:
            if use_cache and exc.status in {400, 404}:
                self._store_error(self._post_paths(url, body)[0], url, exc)
            if not live:
                from grund_index.mirror import query_mirror

                mirrored = query_mirror(url, body, allow_stale=True)
                if mirrored is not None and exc.rate_limited:
                    payload, info = mirrored
                    info.stale = True
                    _remember(info)
                    return payload
            return self._or_stale(exc, stale_body, fetched_at, url)
        if use_cache:
            self._store(self._post_paths(url, body)[0], url, payload)
        _remember(FetchInfo(origin="live", stale=False, fetched_at=_now_stamp()))
        return payload

    def _or_stale(self, exc: PxWebError, stale_body: Any, fetched_at: str | None, url: str) -> Any:
        if exc.rate_limited and stale_body is not None:
            _remember(FetchInfo(origin="cache", stale=True, fetched_at=fetched_at))
            return stale_body
        if exc.rate_limited and RATE_LIMIT_MESSAGE not in str(exc):
            raise PxWebError(RATE_LIMIT_MESSAGE, status=exc.status or 429, url=url, rate_limited=True) from exc
        raise exc

    def _request(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        backoff = setting("GRUND_PX_BACKOFF", BACKOFF_START)
        backoff_max = setting("GRUND_PX_BACKOFF_MAX", BACKOFF_MAX)
        network_max = setting("GRUND_PX_NETWORK_RETRY_MAX", NETWORK_RETRY_MAX)
        pause_max = setting("GRUND_PX_PAUSE_MAX", PAUSE_MAX)
        for _attempt in range(max(1, int(setting("GRUND_PX_ATTEMPTS", ATTEMPTS)))):
            remaining = budget_remaining()
            if remaining is not None and remaining <= _BUDGET_FLOOR:
                break
            if not self.limiter.acquire(max_wait=remaining):
                last_error = PxWebError(RATE_LIMIT_MESSAGE, status=429, url=url, rate_limited=True)
                break
            retry_delay: float | None = None
            retry_exact = False
            try:
                timeout = self.timeout
                if remaining is not None:
                    timeout = min(timeout, max(_MIN_TIMEOUT, budget_remaining() or _MIN_TIMEOUT))
                req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
                if headers:
                    req_headers.update(headers)
                request = urllib.request.Request(url, data=data, headers=req_headers)
                started = time.monotonic()
                try:
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        raw = response.read()
                finally:
                    charge(time.monotonic() - started)
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code in {429, 503}:
                    wait = _retry_after(exc.headers.get("Retry-After"))
                    last_error = PxWebError(
                        f"{exc.code} from {url}: {detail}",
                        status=exc.code,
                        url=url,
                        rate_limited=True,
                    )
                    if wait is None:
                        jitter = random.uniform(0, backoff * BACKOFF_JITTER)
                        retry_delay = backoff + jitter
                        retry_exact = False
                        backoff = min(backoff * 2, backoff_max)
                    else:
                        self.limiter.pause(min(wait, pause_max))
                        retry_delay = wait
                        retry_exact = True
                else:
                    raise PxWebError(f"{exc.code} from {url}: {detail}", status=exc.code, url=url) from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last_error = PxWebError(f"network error for {url}: {exc}", url=url)
                retry_delay = min(network_max, backoff)
                retry_exact = False
                backoff = min(backoff * 2, backoff_max)
            finally:
                self.limiter.release()
            if retry_delay is None:
                continue
            if not sleep_budget(retry_delay, exact=retry_exact):
                last_error = PxWebError(RATE_LIMIT_MESSAGE, status=429, url=url, rate_limited=True)
                break
        if isinstance(last_error, PxWebError):
            if last_error.rate_limited:
                raise PxWebError(RATE_LIMIT_MESSAGE, status=last_error.status or 429, url=url, rate_limited=True)
            raise last_error
        raise PxWebError(RATE_LIMIT_MESSAGE, status=429, url=url, rate_limited=True)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / "get" / digest[:2] / f"{digest}.json"

    def _post_paths(self, url: str, body: dict[str, Any]) -> list[Path]:
        if not self.cache_dir:
            return []
        digest = hashlib.sha256(post_cache_key(url, body).encode("utf-8")).hexdigest()
        paths = [self.cache_dir / "post" / digest[:2] / f"{digest}.json"]
        legacy_raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        legacy = hashlib.sha256(url.encode("utf-8") + b"\n" + legacy_raw).hexdigest()
        paths.append(self.cache_dir / "post" / legacy[:2] / f"{legacy}.json")
        return paths

    def _lookup(self, paths: Path | list[Path] | None, ttl: float) -> tuple[Any | None, Any | None, str | None]:
        if paths is None:
            return None, None, None
        if isinstance(paths, Path):
            paths = [paths]
        stale_body = None
        stale_at = None
        for path in paths:
            if path is None or not path.exists():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            fetched_at = record.get("fetched_at")
            if not fetched_at:
                fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
            age = _age(fetched_at)
            if "error" in record and "body" not in record:
                if age is not None and age <= ttl:
                    err = record["error"] if isinstance(record["error"], dict) else {}
                    raise PxWebError(
                        str(err.get("message") or "cached rejection"),
                        status=err.get("status"),
                        url=record.get("url"),
                    )
                continue
            body = record.get("body")
            if age is not None and age <= ttl:
                return body, None, fetched_at
            if stale_body is None:
                stale_body = body
                stale_at = fetched_at
        return None, stale_body, stale_at

    def _store_error(self, path: Path | None, url: str, exc: PxWebError) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetched_at": _now_stamp(),
                    "error": {"status": exc.status, "message": str(exc)},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _store(self, path: Path | None, url: str, body: Any) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"url": url, "fetched_at": _now_stamp(), "body": body}, ensure_ascii=False),
            encoding="utf-8",
        )


def _age(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        parsed = time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return time.time() - calendar.timegm(parsed)
