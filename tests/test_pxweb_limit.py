"""Cache, rate limit, and snapshot behaviour with a local HTTP server."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from grund_index.client import (
    CONCURRENCY_CEILING,
    MAX_CONCURRENCY,
    RATE_LIMIT_MESSAGE,
    FetchInfo,
    PxWebClient,
    PxWebError,
    RateLimiter,
    last_fetch,
    pop_question_budget,
    push_question_budget,
    shared_limiter,
    shared_settings,
)
from grund_index.mirror import Snapshot, chunk_plan, estimate, query_mirror, sync


class _ScriptServer(ThreadingHTTPServer):
    def __init__(self, script):
        self.script = script
        self.hits = 0
        super().__init__(("127.0.0.1", 0), _Handler)

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._serve()

    def _serve(self):
        self.server.hits += 1
        code, headers, body = self.server.script(self)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


@pytest.fixture
def server():
    holder = {}

    def script(handler):
        return holder["script"](handler)

    httpd = _ScriptServer(script)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    holder["httpd"] = httpd
    yield holder
    httpd.shutdown()


def _client(tmp_path: Path, **kwargs) -> PxWebClient:
    limiter = kwargs.pop("limiter", None) or RateLimiter(per_window=1000, window=10, concurrency=4, private=True)
    meta_ttl = kwargs.pop("meta_ttl", 3600)
    data_ttl = kwargs.pop("data_ttl", 3600)
    return PxWebClient(
        cache_dir=tmp_path / "cache",
        timeout=2,
        limiter=limiter,
        meta_ttl=meta_ttl,
        data_ttl=data_ttl,
    )


def test_default_pace_is_one_call_per_ten_seconds():
    limiter = RateLimiter(private=True)
    assert limiter.per_window == 1
    assert limiter.window == 10.0


def test_wait_releases_its_slot_over_many_calls():
    limiter = RateLimiter(per_window=1000, window=10, concurrency=2, private=True)
    done = threading.Event()

    def run():
        for _ in range(6):
            limiter.wait()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(timeout=3)
    assert limiter.acquire(max_wait=0.5)
    limiter.release()


# time.sleep may wake a little early on some kernels, so allow a fifth of the gap.
PACE_TOLERANCE = 0.8


def test_a_configured_rate_sets_the_pace():
    window = 0.5
    limiter = RateLimiter(rate=20, window=window, concurrency=1, private=True)
    assert limiter.per_window == 10
    started = time.monotonic()
    for _ in range(4):
        assert limiter.acquire(max_wait=2)
        limiter.release()
    elapsed = time.monotonic() - started
    gap = window / limiter.per_window
    assert 3 * gap * PACE_TOLERANCE <= elapsed < window


def test_a_failed_request_build_releases_the_slot(tmp_path, server, monkeypatch):
    server["script"] = lambda handler: (200, {"Content-Type": "application/json"}, {"ok": True})
    limiter = RateLimiter(per_window=1000, window=10, concurrency=1, private=True)
    client = _client(tmp_path, limiter=limiter)
    url = server["httpd"].url + "/t"

    def broken(*args, **kwargs):
        raise ValueError("bad request")

    import grund_index.client as client_module

    real = client_module.urllib.request.Request
    monkeypatch.setattr(client_module.urllib.request, "Request", broken)
    with pytest.raises(ValueError):
        client.get_json(url, use_cache=False)
    monkeypatch.setattr(client_module.urllib.request, "Request", real)
    assert limiter.acquire(max_wait=0.5)
    limiter.release()
    assert client.get_json(url, use_cache=False) == {"ok": True}


def test_the_concurrency_cap_has_a_hard_ceiling(monkeypatch):
    monkeypatch.setenv("GRUND_PX_CONCURRENCY_MAX", "1000")
    monkeypatch.setenv("GRUND_PX_CONCURRENCY", "1000")
    assert shared_settings()[2] == CONCURRENCY_CEILING
    monkeypatch.setenv("GRUND_PX_CONCURRENCY_MAX", "3")
    assert shared_settings()[2] == 3
    monkeypatch.delenv("GRUND_PX_CONCURRENCY_MAX")
    assert shared_settings()[2] == MAX_CONCURRENCY


def test_default_client_uses_the_shared_limiter(tmp_path):
    client = PxWebClient(cache_dir=tmp_path / "cache")
    assert client.limiter is shared_limiter()


def test_cache_hit_skips_the_second_get(tmp_path, server):
    calls = {"n": 0}

    def script(handler):
        calls["n"] += 1
        return 200, {"Content-Type": "application/json"}, {"title": "once"}

    server["script"] = script
    client = _client(tmp_path)
    url = server["httpd"].url + "/api/v1/en/Example/T.px"
    assert client.get_json(url)["title"] == "once"
    assert client.get_json(url)["title"] == "once"
    assert calls["n"] == 1
    assert last_fetch().origin == "cache"


def test_a_rejected_query_is_remembered(tmp_path, server):
    calls = {"n": 0}

    def script(handler):
        calls["n"] += 1
        return 400, {"Content-Type": "text/plain"}, b"Bad Request"

    server["script"] = script
    client = _client(tmp_path)
    url = server["httpd"].url + "/api/v1/en/Example/T.px"
    body = {"query": [], "response": {"format": "json"}}
    with pytest.raises(PxWebError) as first:
        client.post_json(url, body)
    with pytest.raises(PxWebError):
        client.post_json(url, body)
    assert first.value.status == 400
    assert calls["n"] == 1


def test_post_cache_ignores_key_order(tmp_path, server):
    calls = {"n": 0}

    def script(handler):
        calls["n"] += 1
        return 200, {"Content-Type": "application/json"}, {"data": [{"key": ["A"], "values": ["1"]}]}

    server["script"] = script
    client = _client(tmp_path)
    url = server["httpd"].url + "/api/v1/en/Example/T.px"
    first = {"query": [{"code": "Year", "selection": {"filter": "item", "values": ["2024"]}}], "response": {"format": "json"}}
    second = {"response": {"format": "json"}, "query": [{"selection": {"values": ["2024"], "filter": "item"}, "code": "Year"}]}
    assert client.post_json(url, first)["data"][0]["values"] == ["1"]
    assert client.post_json(url, second)["data"][0]["values"] == ["1"]
    assert calls["n"] == 1


def test_429_with_retry_after_then_success(tmp_path, server):
    calls = {"n": 0}

    def script(handler):
        calls["n"] += 1
        if calls["n"] == 1:
            return 429, {"Retry-After": "0.15", "Content-Type": "text/plain"}, b"slow"
        return 200, {"Content-Type": "application/json"}, {"ok": True}

    server["script"] = script
    client = _client(tmp_path)
    token = push_question_budget(5)
    try:
        started = time.monotonic()
        payload = client.get_json(server["httpd"].url + "/t")
        elapsed = time.monotonic() - started
    finally:
        pop_question_budget(token)
    assert payload == {"ok": True}
    assert calls["n"] == 2
    assert elapsed >= 0.1


def test_429_without_retry_after_backs_off(tmp_path, server):
    calls = {"n": 0}

    def script(handler):
        calls["n"] += 1
        if calls["n"] < 3:
            return 429, {"Content-Type": "text/plain"}, b"busy"
        return 200, {"Content-Type": "application/json"}, {"ok": calls["n"]}

    server["script"] = script
    client = _client(tmp_path)
    token = push_question_budget(5)
    try:
        payload = client.get_json(server["httpd"].url + "/t")
    finally:
        pop_question_budget(token)
    assert payload["ok"] == 3
    assert calls["n"] == 3


def test_retry_after_past_the_question_cap_returns_quickly(tmp_path, server):
    def script(handler):
        return 429, {"Retry-After": "60", "Content-Type": "text/plain"}, b"later"

    server["script"] = script
    client = _client(tmp_path)
    token = push_question_budget(0.4)
    started = time.monotonic()
    try:
        with pytest.raises(PxWebError) as caught:
            client.get_json(server["httpd"].url + "/t")
        elapsed = time.monotonic() - started
    finally:
        pop_question_budget(token)
    assert caught.value.rate_limited
    assert RATE_LIMIT_MESSAGE in str(caught.value)
    assert elapsed < 1.5


def test_stale_cache_is_served_when_the_cap_is_hit(tmp_path, server):
    def script(handler):
        return 429, {"Retry-After": "60"}, b"later"

    server["script"] = script
    client = _client(tmp_path, data_ttl=1)
    url = server["httpd"].url + "/api/v1/en/Example/T.px"
    body = {"query": [{"code": "Year", "selection": {"filter": "item", "values": ["2020"]}}], "response": {"format": "json"}}
    path = client._post_paths(url, body)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"url": url, "fetched_at": "2020-01-01T00:00:00Z", "body": {"data": [{"values": ["9"]}]}}),
        encoding="utf-8",
    )
    token = push_question_budget(0.4)
    try:
        started = time.monotonic()
        payload = client.post_json(url, body)
        elapsed = time.monotonic() - started
    finally:
        pop_question_budget(token)
    assert payload["data"][0]["values"] == ["9"]
    info = last_fetch()
    assert isinstance(info, FetchInfo)
    assert info.stale is True
    assert info.fetched_at == "2020-01-01T00:00:00Z"
    assert elapsed < 1.5


def test_chunk_plan_stays_under_the_cell_cap():
    variables = [
        {"code": "A", "values": [["x", "x"]] * 4000},
        {"code": "B", "values": [["y", "y"]] * 4000},
    ]
    plans = chunk_plan(variables)
    assert len(plans) > 1
    for plan in plans:
        sizes = [len(item["selection"]["values"]) for item in plan]
        assert max(sizes) <= 5000
        product = 1
        for size in sizes:
            product *= size
        assert product <= 100_000


def test_mirror_answers_a_post_without_calling_the_server(tmp_path, server, monkeypatch):
    def script(handler):
        raise AssertionError("live call")

    server["script"] = script
    dataset = {
        "class": "dataset",
        "label": "Tiny",
        "id": ["Year", "Sex"],
        "size": [2, 2],
        "role": {"time": ["Year"]},
        "dimension": {
            "Year": {"label": "Year", "category": {"index": {"2023": 0, "2024": 1}}},
            "Sex": {"label": "Sex", "category": {"index": {"1": 0, "2": 1}, "label": {"1": "Male", "2": "Female"}}},
        },
        "value": [1, 2, 3, 4],
        "extension": {"px": {"decimals": 0}},
    }
    variables = [
        {"code": "Year", "text": "Year", "time": True, "elimination": False, "values": [["2023", "2023"], ["2024", "2024"]]},
        {"code": "Sex", "text": "Sex", "time": False, "elimination": True, "values": [["1", "Male"], ["2", "Female"]]},
    ]
    mirror = tmp_path / "mirror"
    url = server["httpd"].url + "/api/v1/en/Example/TINY.px"
    snap = Snapshot(mirror)
    snap.store_table(
        url=url,
        table_id="TINY",
        lang="en",
        title="Tiny",
        updated="2026-10-01T00:00:00",
        variables=variables,
        parts=[dataset],
    )
    monkeypatch.setenv("GRUND_MIRROR_DIR", str(mirror))
    body = {"query": [{"code": "Year", "selection": {"filter": "item", "values": ["2024"]}}], "response": {"format": "json"}}
    payload, info = query_mirror(url, body)
    assert info.origin == "mirror"
    assert info.updated == "2026-10-01T00:00:00"
    assert payload["data"] == [{"key": ["2024"], "values": ["3"]}]
    client = _client(tmp_path)
    assert client.post_json(url, body)["data"][0]["values"] == ["3"]
    assert server["httpd"].hits == 0
    saved = json.loads((mirror / "manifest.json").read_text(encoding="utf-8"))
    entry = saved["tables"]["en/TINY"]
    assert entry["sha256"]
    assert entry["fetched_at"]
    assert entry["updated"] == "2026-10-01T00:00:00"


def test_sync_is_resumable_and_survives_a_short_429(tmp_path, server):
    calls = {"post": 0}

    def script(handler):
        if handler.command == "GET":
            return 200, {"Content-Type": "application/json"}, [
                {"id": "AAA.px", "type": "t", "text": "Aaa", "updated": "2026-01-01T00:00:00"},
                {"id": "BBB.px", "type": "t", "text": "Bbb", "updated": "2026-02-01T00:00:00"},
            ]
        calls["post"] += 1
        if calls["post"] == 1:
            return 429, {"Retry-After": "0.05"}, b"busy"
        name = "AAA" if calls["post"] < 4 else "BBB"
        # Both tables share one folder, so the body does not identify the table.
        # The third successful post is BBB. First post is the 429, then AAA, then BBB.
        return 200, {"Content-Type": "application/json"}, {
            "class": "dataset",
            "label": name,
            "id": ["Year"],
            "size": [1],
            "value": [name == "BBB" and 2 or 1],
            "dimension": {"Year": {"category": {"index": {"2024": 0}}}},
            "extension": {"px": {"decimals": 0}},
        }

    server["script"] = script
    base = server["httpd"].url
    index = tmp_path / "index"
    index.mkdir()
    rows = []
    for stem, lang in (("AAA", "en"), ("BBB", "en")):
        rows.append(
            {
                "id": f"{stem}.px",
                "lang": lang,
                "title": stem,
                "url": f"{base}/api/v1/en/Example/{stem}.px",
                "updated": "2020-01-01T00:00:00",
                "variables": [{"code": "Year", "text": "Year", "time": True, "elimination": False, "values": [["2024", "2024"]]}],
            }
        )
    # Same parent folder so one listing covers both.
    (index / "tables.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    mirror = tmp_path / "mirror"
    client = _client(tmp_path)
    token = push_question_budget(5)
    try:
        first = sync(index, mirror, client=client)
    finally:
        pop_question_budget(token)
    assert first["fetched"] == 2
    assert first["failed"] == 0
    calls_after = calls["post"]
    second = sync(index, mirror, client=client)
    assert second["skipped"] == 2
    assert second["fetched"] == 0
    assert calls["post"] == calls_after


def test_estimate_runs_on_the_shipped_index():
    root = Path(__file__).resolve().parents[1]
    summary = estimate(root / "data" / "index")
    assert summary["tables"] == 2104
    assert summary["editions"] > 3000
    assert summary["calls"] > summary["editions"]
    assert summary["json_stat2_bytes_estimate"] > 0


def test_rate_limit_message_does_not_hang(monkeypatch):
    monkeypatch.setenv("GRUND_RAIL", "python")
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.embed import Embedder
    from grund_index.model import Table
    from grund_rails.vangrail_client import reset_checker_cache
    from test_bind import cpi

    reset_checker_cache()

    class Boom:
        def post_json(self, url, body, **kwargs):
            raise PxWebError(RATE_LIMIT_MESSAGE, status=429, url=url, rate_limited=True)

    catalogue = Catalogue([Table(id="VIS01000.px", editions={"en": cpi()})], Embedder(kind="chargram"), None, "none")
    engine = Engine(catalogue, client=Boom(), planner="deterministic")
    started = time.monotonic()
    result = engine.ask("What was the consumer price index in June 2024?")
    elapsed = time.monotonic() - started
    assert result["refused"] is True
    assert "rate-limiting" in result["answer"]
    assert elapsed < 15
