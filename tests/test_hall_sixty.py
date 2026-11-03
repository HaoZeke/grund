"""Ruby and Python on the organisers' 60 and the smoke ten.

Same engine, same catalogue, shipped path-disagreement rule. The Ruby
checker is the only thing that changes between the two passes. They have
to agree question by question, with at least 14 right and no wrong figure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "evalset" / "track3-questions.jsonl"
LOG = Path("/tmp/parity-hall.log")
OUT = Path("data/work/eval/rail-parity.json")

SMOKE_IDS = (
    "births-2024-en",
    "cpi-2026-09-en",
    "unemployment-2026q2-en",
    "wage-index-points-2026-08-en",
    "cpi-and-unemployment-2026-en",
    "births-2024-is",
    "cpi-2026-09-is",
    "unemployment-2026q2-is",
    "wage-index-points-2026-08-is",
)
MARS = "What is the population of Mars according to Statistics Iceland?"

ENV = (
    "GRUND_ABSTAIN_RULE=unset (disagree); GRUND_CALIBRATE=unset; "
    "GRUND_RECALL=unset (fill); GRUND_LEXICON=unset (on); "
    "GRUND_E5=absent; GRUND_INDEX=data/index; GRUND_SUBJECT_CHECK=unset"
)


def _prepare() -> None:
    os.environ["RUBYLIB"] = os.environ.get("RUBYLIB") or "vendor/vangrail/lib"
    for key in (
        "GRUND_CALIBRATE",
        "GRUND_ABSTAIN_RULE",
        "GRUND_RECALL",
        "GRUND_LEXICON",
        "GRUND_JUDGESIM",
        "GRUND_BIND2",
        "GRUND_BIND2_VETO",
        "GRUND_SUBJECT_CHECK",
        "GRUND_E5_DIR",
        "GRUND_E5_SMALL_INDEX",
    ):
        os.environ.pop(key, None)


def _signature(result: dict) -> tuple:
    refused = bool(result.get("refused"))
    raw = result.get("value")
    if raw in (None, ""):
        value = None
    else:
        try:
            value = round(float(raw), 4)
        except (TypeError, ValueError):
            value = str(raw)
    table = str(result.get("table_id") or "").removesuffix(".px") or None
    return refused, value, table


def _reason(result: dict) -> str:
    detail = str(result.get("detail") or "")
    blocked = []
    for item in result.get("rails") or []:
        if isinstance(item, dict) and item.get("status") == "blocked" and item.get("reason"):
            blocked.append(str(item["reason"]))
    extra = blocked[0] if blocked else ""
    return detail or extra


def _ask(engine, text: str, language: str | None, rail: str) -> dict:
    os.environ["GRUND_RAIL"] = rail
    from grund_rails.vangrail_client import reset_checker_cache

    reset_checker_cache()
    return engine.ask(text, language)


def _grade(question: dict, result: dict) -> dict:
    from grund_eval.track3_score import answer_is_right

    tables = list(result.get("tables") or [])
    if not tables and result.get("table_id"):
        tables = [result["table_id"]]
    if question.get("expect") == "refuse":
        correct = bool(result.get("refused")) and result.get("value") in (None, "")
    else:
        _numbers, _tables, correct = answer_is_right(
            question,
            result.get("answer") or "",
            tables,
            claimed=result.get("value"),
        )
    refused, value, table = _signature(result)
    return {
        "id": question["id"],
        "correct": bool(correct),
        "refused": refused,
        "value": value,
        "table_id": table,
        "detail": _reason(result),
    }


@pytest.fixture(scope="module")
def parity():
    _prepare()
    from grund.calibrate import report_block
    from grund.engine import Engine
    from grund_eval.metrics import wilson
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(ROOT / "data" / "index"),
        client=PxWebClient(cache_dir=ROOT / "data" / "cache"),
        planner="deterministic",
    )
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(questions) == 60
    LOG.write_text("", encoding="utf-8")
    rows = []
    for question in questions:
        pair = {}
        for rail in ("python", "ruby"):
            result = _ask(engine, question["question"], question.get("language"), rail)
            graded = _grade(question, result)
            pair[rail] = graded
            with LOG.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{question['id']}\t{rail}\trefused={graded['refused']}\t"
                    f"value={graded['value']}\ttable={graded['table_id']}\t{graded['detail']}\n"
                )
        rows.append(pair)

    mars = {}
    for rail in ("python", "ruby"):
        result = _ask(engine, MARS, "en", rail)
        refused, value, table = _signature(result)
        mars[rail] = {
            "id": "mars",
            "correct": refused and value is None,
            "refused": refused,
            "value": value,
            "table_id": table,
            "detail": _reason(result),
        }
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(
                f"mars\t{rail}\trefused={mars[rail]['refused']}\tvalue={value}\ttable={table}\t{mars[rail]['detail']}\n"
            )

    ruby_rows = [pair["ruby"] for pair in rows]
    python_rows = [pair["python"] for pair in rows]
    ruby_block = report_block(ruby_rows)
    python_block = report_block(python_rows)
    summary = {
        "env": ENV,
        "python": {
            "rail": "python",
            "right": python_block["right"],
            "wrong": python_block["wrong"],
            "stated": python_block["stated"],
            "trustsql": python_block["trustsql"],
            "coverage_wilson95": list(wilson(python_block["stated"], python_block["n"])),
            "error_rate_wilson95": list(wilson(python_block["wrong"], python_block["n"])),
        },
        "ruby": {
            "rail": "ruby",
            "right": ruby_block["right"],
            "wrong": ruby_block["wrong"],
            "stated": ruby_block["stated"],
            "trustsql": ruby_block["trustsql"],
            "coverage_wilson95": list(wilson(ruby_block["stated"], ruby_block["n"])),
            "error_rate_wilson95": list(wilson(ruby_block["wrong"], ruby_block["n"])),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows, "mars": mars}, indent=2) + "\n", encoding="utf-8")
    return {"rows": rows, "mars": mars, "summary": summary}


def test_ruby_matches_python_on_the_sixty_and_the_smoke_ten(parity):
    mismatches = []
    for pair in parity["rows"]:
        ruby = pair["ruby"]
        python = pair["python"]
        if (ruby["refused"], ruby["value"], ruby["table_id"]) != (
            python["refused"],
            python["value"],
            python["table_id"],
        ):
            mismatches.append(
                f"{ruby['id']} python={python['refused']}:{python['value']}:{python['table_id']}"
                f" ({python['detail']}) ruby={ruby['refused']}:{ruby['value']}:{ruby['table_id']}"
                f" ({ruby['detail']})"
            )
    assert mismatches == []
    ruby = parity["summary"]["ruby"]
    assert ruby["right"] >= 14, parity["summary"]
    assert ruby["wrong"] == 0, parity["summary"]
    present = {pair["ruby"]["id"] for pair in parity["rows"]}
    missing = [item for item in SMOKE_IDS if item not in present]
    assert missing == []
    mars = parity["mars"]
    assert mars["python"]["refused"] and mars["python"]["value"] is None
    assert (mars["ruby"]["refused"], mars["ruby"]["value"], mars["ruby"]["table_id"]) == (
        mars["python"]["refused"],
        mars["python"]["value"],
        mars["python"]["table_id"],
    )
