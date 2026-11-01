"""Call Grund's cell-claim rail over loopback, with a one-shot Ruby fallback.

A missing or unreachable checker is a startup failure. It is not an
uncertain pass, and it is not a refusal of the question in front of it.
``GRUND_RAIL=python`` is the only opt-in that skips Ruby and uses the
Python rail in this tree.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = os.environ.get("GRUND_VANGRAIL_URL", "http://127.0.0.1:9293")
ROOT = Path(__file__).resolve().parents[2]
ONCE = ROOT / "script" / "grund_guard_once.rb"
RUBYLIB = os.environ.get("RUBYLIB", "")

_READY: dict | None = None


class RailOffline(RuntimeError):
    """The cell-claim checker did not run. Do not score questions in this state."""


def reset_checker_cache() -> None:
    global _READY
    _READY = None


def rail_mode() -> str:
    raw = os.environ.get("GRUND_RAIL", "ruby").strip().lower()
    if raw in {"", "ruby", "vangrail"}:
        return "ruby"
    if raw == "python":
        return "python"
    raise RailOffline(_offline_message(f"GRUND_RAIL={raw!r} is not a rail mode."))


def require_checker() -> dict:
    """Prove the rail can run. Raise RailOffline instead of serving questions."""
    global _READY
    mode = rail_mode()
    if _READY is not None and _READY.get("mode") == mode:
        return _READY
    if mode == "python":
        _READY = _python_ready()
        return _READY
    _READY = _ruby_ready()
    return _READY


def check_output(text: str, user_input: str, context: dict, url: str = DEFAULT_URL) -> dict:
    if rail_mode() == "python":
        return _python_verdict(text, user_input, context)
    payload = {"text": text, "user_input": user_input, "context": context}
    remote = _post(url, payload)
    if remote is not None:
        return _require_certain(remote, "the loopback checker")
    return _require_certain(_once(payload), "ruby script/grund_guard_once.rb")


def _offline_message(detail: str) -> str:
    return (
        "checker offline: the cell-claim rail is missing or unreachable. "
        "Grund will not start. An unchecked pass used to refuse every question.\n"
        f"{detail.strip()}\n"
        "Start the Ruby checker (Ruby 3.1 or newer, vangrail from a checkout, not a gem):\n"
        "  ruby -v\n"
        "  export RUBYLIB=/path/to/vangrail/lib\n"
        "  ruby script/grund_guard_server.rb\n"
        "That listens on 127.0.0.1:9293. GRUND_VANGRAIL_URL overrides the URL.\n"
        "Or opt in to the Python rail. This is not the default:\n"
        "  export GRUND_RAIL=python"
    )


def _require_certain(verdict: dict, source: str) -> dict:
    if not isinstance(verdict, dict) or verdict.get("certain") is False:
        reason = ""
        if isinstance(verdict, dict):
            reason = str(verdict.get("reason") or "")
        detail = f"{source} did not check the claim."
        if reason:
            detail = f"{detail} {reason}"
        raise RailOffline(_offline_message(detail))
    return verdict


def _python_ready() -> dict:
    from grund_rails.cell_claim import CellClaimRail

    CellClaimRail()
    return {"ok": True, "offline": False, "mode": "python", "certain": True}


def _python_verdict(text: str, user_input: str, context: dict) -> dict:
    from grund_rails.cell_claim import CellClaimRail

    ctx = dict(context or {})
    ctx.setdefault("question", user_input)
    claims = ctx.get("claims")
    if isinstance(claims, list) and claims and isinstance(claims[0], dict):
        ctx.setdefault("claim", claims[0])
        cells = claims[0].get("cells")
        if isinstance(cells, list):
            ctx.setdefault("cells", cells)
    result = CellClaimRail().decide(text, ctx)
    return _require_certain(result.to_dict(), "the Python cell-claim rail")


def _ruby_ready() -> dict:
    health = _health(DEFAULT_URL)
    if health is not None:
        return {
            "ok": True,
            "offline": False,
            "mode": "ruby",
            "via": "http",
            "url": DEFAULT_URL,
            "version": health.get("version"),
            "certain": True,
        }
    probe = {
        "text": "probe",
        "user_input": "probe",
        "context": {"claims": []},
    }
    try:
        verdict = _once(probe)
    except RailOffline:
        raise
    except OSError as exc:
        raise RailOffline(_offline_message(str(exc))) from exc
    return {
        "ok": True,
        "offline": False,
        "mode": "ruby",
        "via": "cli",
        "certain": verdict.get("certain") is not False,
    }


def _health(url: str) -> dict | None:
    request = urllib.request.Request(url.rstrip("/") + "/v1/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=0.4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict) and payload.get("ok") is True:
        return payload
    return None


def _post(url: str, payload: dict) -> dict | None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/check_output",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _ruby_env() -> dict:
    env = os.environ.copy()
    vangrail = os.environ.get("VANGRAIL_LIB", "")
    vendored = Path(__file__).resolve().parents[2] / "vendor" / "vangrail" / "lib"
    if not vangrail and vendored.is_dir():
        vangrail = str(vendored)
    if vangrail:
        env["RUBYLIB"] = vangrail if not RUBYLIB else f"{vangrail}:{RUBYLIB}"
    return env


def _once(payload: dict) -> dict:
    import subprocess

    try:
        completed = subprocess.run(
            ["ruby", str(ONCE)],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=20,
            check=False,
            env=_ruby_env(),
            cwd=str(ROOT),
        )
    except FileNotFoundError as exc:
        raise RailOffline(_offline_message("ruby is not installed.")) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RailOffline(_offline_message(str(exc))) from exc
    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:400]
        raise RailOffline(_offline_message(detail or "ruby did not print a rail result.")) from exc
    if not isinstance(parsed, dict):
        raise RailOffline(_offline_message("ruby printed a rail result that is not an object."))
    if parsed.get("certain") is False:
        raise RailOffline(_offline_message(str(parsed.get("reason") or "ruby returned an unchecked pass.")))
    return parsed
