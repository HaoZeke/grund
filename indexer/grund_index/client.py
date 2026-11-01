"""Polite client for the Statistics Iceland PxWeb v1 API.

The live configuration (queried 2026-10) is:

- English: maxCalls 100 per 10 seconds, maxCells 100000, maxValues 5000
- Icelandic: maxCalls 300 per 10 seconds, same cell and value caps

There is no v2 endpoint. This client stays well under the published window,
caches GET responses on disk, and backs off on HTTP 429.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "Grund/0.1 (GAGNATHON 2026; rgoswami@ieee.org)"
DEFAULT_RATE = 6.0  # requests per second, shared across languages
MAX_CELLS = 100_000
MAX_VALUES = 5_000

BASE = {
    "en": "https://px.hagstofa.is/pxen/api/v1/en",
    "is": "https://px.hagstofa.is/pxis/api/v1/is",
}


class PxWebError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class RateLimiter:
    """Thread-safe spacing. A 429 pauses every caller."""

    def __init__(self, rate: float = DEFAULT_RATE) -> None:
        self.rate = rate
        self._lock = threading.Lock()
        self._next = 0.0
        self._paused_until = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._paused_until, self._next)
            delay = start - now
            self._next = start + 1.0 / self.rate
        if delay > 0:
            time.sleep(delay)

    def pause(self, seconds: float) -> None:
        with self._lock:
            until = time.monotonic() + seconds
            if until > self._paused_until:
                self._paused_until = until


class PxWebClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        rate: float = DEFAULT_RATE,
        timeout: float = 60.0,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout = timeout
        self.limiter = limiter or RateLimiter(rate)
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str, *, use_cache: bool = True) -> Any:
        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                return cached
        payload = self._request(url)
        if use_cache:
            self._write_cache(url, payload)
        return payload

    def post_json(self, url: str, body: dict[str, Any]) -> Any:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        cached = self._read_post_cache(url, raw)
        if cached is not None:
            return cached
        payload = self._request(url, data=raw, headers={"Content-Type": "application/json"})
        self._write_post_cache(url, raw, payload)
        return payload

    def _request(self, url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(6):
            self.limiter.wait()
            req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
            if headers:
                req_headers.update(headers)
            request = urllib.request.Request(url, data=data, headers=req_headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 429:
                    self.limiter.pause(12.0 + attempt * 3)
                    last_error = PxWebError(f"429 from {url}: {detail}", status=429, url=url)
                    continue
                if exc.code in {500, 502, 503, 504} and attempt < 4:
                    time.sleep(1.5 * (attempt + 1))
                    last_error = PxWebError(f"{exc.code} from {url}: {detail}", status=exc.code, url=url)
                    continue
                raise PxWebError(f"{exc.code} from {url}: {detail}", status=exc.code, url=url) from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last_error = PxWebError(f"network error for {url}: {exc}", url=url)
                time.sleep(1.5 * (attempt + 1))
                continue
        raise PxWebError(f"gave up on {url}: {last_error}", url=url)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / "get" / digest[:2] / f"{digest}.json"

    def _post_cache_path(self, url: str, raw: bytes) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8") + b"\n" + raw).hexdigest()
        return self.cache_dir / "post" / digest[:2] / f"{digest}.json"

    def _read_cache(self, url: str) -> Any | None:
        path = self._cache_path(url)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["body"]

    def _write_cache(self, url: str, body: Any) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "body": body}, ensure_ascii=False), encoding="utf-8")

    def _read_post_cache(self, url: str, raw: bytes) -> Any | None:
        path = self._post_cache_path(url, raw)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["body"]

    def _write_post_cache(self, url: str, raw: bytes, body: Any) -> None:
        path = self._post_cache_path(url, raw)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "body": body}, ensure_ascii=False), encoding="utf-8")
