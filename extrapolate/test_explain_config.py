import io, json, os, socket, sys, threading, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest
import explain

ANSWER = {"answer": "Population was 389444.", "value": "389444", "table_id": "MAN00101", "refused": False}
USER_KEY = "user-secret-key-not-real-0001"


def _public(monkeypatch, address="93.184.215.14"):
    real = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if str(host).endswith(".example"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(explain.socket, "getaddrinfo", fake)


@pytest.fixture
def server_default(monkeypatch):
    monkeypatch.setattr(explain, "BASE", "https://server.example/v1")
    monkeypatch.setattr(explain, "KEY", "server-key-not-real-0002")
    monkeypatch.setattr(explain, "MODEL", "server-model")


def test_blank_headers_use_server_default(server_default):
    cfg = explain.request_config({})
    assert cfg["base"] == "https://server.example/v1" and cfg["key"] == "server-key-not-real-0002"
    assert not cfg["custom"] and cfg["label"] == "server-model"


def test_no_server_default_and_no_headers_is_503(monkeypatch):
    for name in ("BASE", "KEY", "MODEL"):
        monkeypatch.setattr(explain, name, "")
    with pytest.raises(explain.ConfigError) as err:
        explain.request_config({})
    assert err.value.status == 503


def test_custom_base_never_gets_server_key(server_default, monkeypatch):
    _public(monkeypatch)
    with pytest.raises(explain.ConfigError):
        explain.request_config({"X-Grund-LLM-Base": "https://other.example/v1"})
    cfg = explain.request_config({"X-Grund-LLM-Base": "https://other.example/v1/", "X-Grund-LLM-Key": USER_KEY})
    assert cfg["base"] == "https://other.example/v1" and cfg["key"] == USER_KEY
    assert cfg["model"] == "server-model" and cfg["label"] == "custom"


def test_user_key_alone_goes_to_server_base(server_default):
    cfg = explain.request_config({"X-Grund-LLM-Key": USER_KEY, "X-Grund-LLM-Model": "m"})
    assert cfg["base"] == "https://server.example/v1" and cfg["key"] == USER_KEY and cfg["model"] == "m"


@pytest.mark.parametrize("url", ["http://api.example/v1", "https://user:pw@api.example/v1", "ftp://api.example", "https:///v1"])
def test_custom_base_must_be_plain_https(url, monkeypatch):
    _public(monkeypatch)
    with pytest.raises(explain.ConfigError):
        explain.public_base(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1", "fd00::1"])
def test_custom_base_must_resolve_public(address, monkeypatch):
    _public(monkeypatch, address)
    with pytest.raises(explain.ConfigError):
        explain.public_base("https://api.example/v1")


def test_llm_sends_to_request_endpoint(monkeypatch):
    seen = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_open(req, timeout=None):
        seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
        seen["model"] = json.loads(req.data)["model"]
        return Reply(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr(explain._OPENER, "open", fake_open)
    explain.llm([], cfg={"base": "https://other.example/v1", "key": USER_KEY, "model": "m"})
    assert seen == {"url": "https://other.example/v1/chat/completions", "auth": "Bearer " + USER_KEY, "model": "m"}


def test_redirects_are_not_followed():
    handler = explain._NoRedirect()
    assert handler.redirect_request(None, None, 307, "", {}, "https://elsewhere.example") is None


def test_request_headers_are_neither_logged_nor_echoed(server_default, monkeypatch, tmp_path):
    _public(monkeypatch)
    log = tmp_path / "extrapolate.jsonl"
    monkeypatch.setattr(explain, "LOG", str(log))
    monkeypatch.setattr(explain, "elab_guard", None)
    calls = []

    def fake_llm(messages, model=None, cfg=None):
        calls.append(cfg)
        return json.dumps({"final": {"from_data": [{"text": "Population was 389444, key " + USER_KEY, "source": "MAN00101"}], "beyond": []}})

    monkeypatch.setattr(explain, "llm", fake_llm)
    server = explain.ThreadingHTTPServer(("127.0.0.1", 0), explain.H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/extrapolate"
        body = json.dumps({"question": "How many people live in Iceland?", "language": "en", "answer": ANSWER}).encode()
        headers = {"Content-Type": "application/json", "X-Grund-LLM-Base": "https://other.example/v1", "X-Grund-LLM-Key": USER_KEY, "X-Grund-LLM-Model": "their-model"}
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=10) as r:
            reply = r.read().decode()
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"X-Grund-LLM-Base": "https://other.example/v1"}), timeout=10)
        assert err.value.code == 400
    finally:
        server.shutdown()
    assert calls[0]["base"] == "https://other.example/v1" and calls[0]["key"] == USER_KEY
    assert USER_KEY not in reply and "other.example" not in reply and "their-model" not in reply
    assert json.loads(reply)["model"] == "custom"
    logged = log.read_text()
    assert USER_KEY not in logged and "other.example" not in logged and "their-model" not in logged
    assert json.loads(logged.splitlines()[0])["model"] == "custom"


def test_model_header_on_the_server_key_needs_the_allow_list(server_default, monkeypatch):
    monkeypatch.delenv("GRUND_LLM_MODELS", raising=False)
    cfg = explain.request_config({"X-Grund-LLM-Model": "expensive-model"})
    assert cfg["model"] == "server-model" and cfg["model_ignored"] and cfg["key"] == "server-key-not-real-0002"
    assert cfg["label"] == "server-model"
    monkeypatch.setenv("GRUND_LLM_MODELS", "cheap-model, other-model")
    assert explain.request_config({"X-Grund-LLM-Model": "cheap-model"})["model"] == "cheap-model"
    assert explain.request_config({"X-Grund-LLM-Model": "expensive-model"})["model"] == "server-model"
    assert not explain.request_config({"X-Grund-LLM-Model": "server-model"})["model_ignored"]


def test_any_model_with_the_visitors_own_key(server_default, monkeypatch):
    monkeypatch.delenv("GRUND_LLM_MODELS", raising=False)
    cfg = explain.request_config({"X-Grund-LLM-Key": USER_KEY, "X-Grund-LLM-Model": "expensive-model"})
    assert cfg["model"] == "expensive-model" and not cfg["model_ignored"] and cfg["label"] == "custom"


def test_custom_base_pins_the_checked_address(server_default, monkeypatch):
    _public(monkeypatch, "93.184.215.14")
    cfg = explain.request_config({"X-Grund-LLM-Base": "https://other.example/v1", "X-Grund-LLM-Key": USER_KEY})
    assert cfg["pin"] == "93.184.215.14"
    assert explain.request_config({})["pin"] is None


def test_pinned_request_connects_to_the_checked_address_without_a_second_lookup(monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    class Context:
        def wrap_socket(self, sock, server_hostname=None):
            seen["sni"] = server_hostname
            sock.close()
            raise Stop

    def lookup(*args, **kwargs):
        raise AssertionError("the host was looked up again")

    def connect(address, timeout=None, *args, **kwargs):
        seen["address"] = address
        left, right = socket.socketpair()
        right.close()
        return left

    monkeypatch.setattr(explain.socket, "getaddrinfo", lookup)
    monkeypatch.setattr(explain.socket, "create_connection", connect)
    monkeypatch.setattr(explain.ssl, "create_default_context", lambda *a, **k: Context())
    cfg = {"base": "https://other.example/v1", "key": USER_KEY, "model": "m", "pin": "93.184.215.14"}
    with pytest.raises((Stop, urllib.error.URLError)):
        explain.llm([], cfg=cfg)
    assert seen == {"address": ("93.184.215.14", 443), "sni": "other.example"}
