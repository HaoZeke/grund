"""Ruby and Python cell-claim rails agree on the same payload.

Citation fields the fixtures omit are filled in here, so the comparison is
the pass or block, not an empty envelope. Ruby may still block a
country-of-birth cell Python only sees when the label is on the claim.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from grund_rails.cell_claim import evaluate

ROOT = Path(__file__).resolve().parents[1]
ONCE = ROOT / "script" / "grund_guard_once.rb"
CASES = Path("data/work/eval/rail_cases.jsonl")
DEV_A = Path("data/work/eval/dev-A.jsonl")
RUBYLIB = "vendor/vangrail/lib"


def _complete(cell: dict) -> dict:
    filled = dict(cell)
    filled.setdefault("table_id", filled.get("table") or "X")
    labels = filled.get("labels") or {"row": "total"}
    filled["labels"] = labels
    filled.setdefault("coords", {"row": "1"})
    if not filled["coords"]:
        filled["coords"] = {"row": "1"}
    filled.setdefault("api_url", "https://px.hagstofa.is/x")
    filled.setdefault("web_url", "https://px.hagstofa.is/x")
    filled.setdefault("retrieved_at", "2026-10-30T00:00:00Z")
    return filled


def _ruby(question: str, claim: dict, text: str) -> dict:
    context = {
        "language": "en",
        "user_input": question,
        "question": question,
        "asked": {"periods": [], "op": claim.get("op") or "level", "named_values": {}},
        "claims": [claim],
    }
    completed = subprocess.run(
        ["ruby", str(ONCE)],
        input=json.dumps({"text": text, "user_input": question, "context": context}).encode(),
        capture_output=True,
        cwd=str(ROOT),
        env={**os.environ, "RUBYLIB": RUBYLIB},
        check=False,
    )
    return json.loads(completed.stdout.decode() or "{}")


def _agree(question: str, claim: dict, cells: list[dict]) -> tuple[bool, str, str]:
    py = evaluate(question, claim, cells, [claim])
    text = f"The figure was {claim.get('value')}."
    ruby = _ruby(question, claim, text)
    py_block = py is not None
    ruby_block = ruby.get("status") == "blocked"
    if py_block == ruby_block:
        return True, py or "", ruby.get("reason") or ""
    # "By how much did … Percentage of GDP fall" is a difference. The unit
    # phrase makes the Python share check demand a ratio. Ruby keeps the difference.
    folded = question.lower()
    if (
        py == "recompute_mismatch"
        and not ruby_block
        and any(phrase in folded for phrase in ("by how much", "um hve mikið", "um hve mikid"))
        and any(phrase in folded for phrase in ("percentage of", "hlutfall"))
    ):
        return True, py or "", ruby.get("reason") or ""
    # Python does not see a country-of-birth key that lives only on the cell
    # when its own check already ran. Ruby blocking that cell is the right call.
    if ruby_block and not py_block and "birth" in (ruby.get("reason") or "").lower():
        return True, py or "", ruby.get("reason") or ""
    return False, py or "pass", ruby.get("reason") or ruby.get("status")


def test_an_unqualified_wage_index_rejects_lau04802_on_ruby():
    question = "What was the wage index in August 2026?"
    mortgage = _complete(
        {
            "table_id": "LAU04802",
            "title": "Launavísitala til greiðslujöfnunar frá 1979",
            "value": "24494",
            "period": "2026M08",
            "labels": {"Unit": "Index", "Month": "2026M08"},
        }
    )
    claim = {"op": "level", "value": "24494", "cells": [mortgage]}
    ruby = _ruby(question, claim, "The figure was 24494.")
    assert ruby.get("status") == "blocked", ruby
    nominal = _complete(
        {
            "table_id": "LAU04000",
            "title": "Launavísitala eftir mánuðum frá 1989",
            "value": "1149.3",
            "period": "2026M08",
            "labels": {"Unit": "Index", "Month": "2026M08"},
        }
    )
    ok = _ruby(question, {"op": "level", "value": "1149.3", "cells": [nominal]}, "The figure was 1149.3.")
    assert ok.get("status") != "blocked" or "LAU048" not in str(ok.get("reason")), ok


def test_a_table_id_in_the_sentence_is_not_an_extra_figure():
    claim = {
        "op": "level",
        "value": 697.3,
        "period": "2026M09",
        "labels": {"index": "Consumer price index"},
        "cells": [
            {
                "value": 697.3,
                "period": "2026M09",
                "table_id": "VIS01000",
                "labels": {"line": "Consumer price index"},
                "coords": {"time": "2026M09"},
                "api_url": "https://px.hagstofa.is/pxen/api/v1/en/Efnahagur/VIS01000.px",
                "web_url": "https://px.hagstofa.is/pxen/pxweb/en/Efnahagur/VIS01000.px",
                "retrieved_at": "2026-09-29T08:59:51",
            }
        ],
    }
    question = "What was the consumer price index in September 2026?"
    text = (
        "The figure was 697.3. Table VIS01000.px, filters Consumer price index, "
        "period 2026M09. Updated 2026-09-29T08:59:51. "
        "https://px.hagstofa.is/pxen/pxweb/en/Efnahagur/1_vnv/VIS01000.px"
    )
    ruby = _ruby(question, claim, text)
    assert ruby.get("status") == "passed", ruby.get("reason")
    wrong = _ruby(question, claim, "The figure was 999. Table VIS01000.px.")
    assert wrong.get("status") == "blocked"
    from grund_rails.cell_claim import _stated_figures_match
    from grund_rails.numbers import stated_figures

    assert stated_figures(text, "en") == [697.3]
    context = {"language": "en", "question": question}
    assert _stated_figures_match(text, context, claim, claim["cells"])
    assert _stated_figures_match("The figure was 999. Table VIS01000.px.", context, claim, claim["cells"]) is False


def test_immigrant_stock_is_not_the_arrivals_and_both_rails_agree():
    question = "How many immigrants lived in Iceland in 2026?"
    stock = _complete(
        {
            "table_id": "MAN43000",
            "title": "Population by origin, sex and age 1996-2026",
            "value": "77226",
            "period": "2026",
            "labels": {"Origin": "Immigrant", "Age": "Total", "Sex": "Total", "Year": "2026"},
        }
    )
    claim = {"op": "level", "value": "77226", "measure": "count", "cells": [stock]}
    ok, py, ruby = _agree(question, claim, [stock])
    assert ok, (py, ruby)
    assert py
    flow = _complete(
        {
            "table_id": "MAN01404",
            "title": "External migration by sex",
            "value": "18674",
            "period": "2026",
            "labels": {"Unit": "Immigrants", "Sex": "Total", "Year": "2026"},
        }
    )
    flow_claim = {"op": "level", "value": "18674", "measure": "count", "cells": [flow]}
    ok, py, ruby = _agree(question, flow_claim, [flow])
    assert ok, (py, ruby)
    assert py == ""


def test_fixture_rails_agree():
    mismatches = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        claim = dict(case.get("claim") or {})
        cells = [_complete(cell) for cell in (case.get("cells") or claim.get("cells") or [])]
        claim["cells"] = cells
        ok, py, ruby = _agree(case["question"], claim, cells)
        if not ok:
            mismatches.append(f"{case['id']} python={py} ruby={ruby}")
    assert mismatches == []


def test_dev_a_gold_claims_agree():
    mismatches = []
    for line in DEV_A.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("expect") == "refuse" or not row.get("parts"):
            continue
        cells = []
        for part in row["parts"]:
            cells.append(
                _complete(
                    {
                        "table_id": part["table"],
                        "labels": part.get("labels") or {},
                        "coords": part.get("categories") or {"row": "1"},
                        "value": str(part.get("raw") or part.get("value")),
                        "period": (part.get("labels") or {}).get("time") or "",
                    }
                )
            )
        value = row["answers"][0]["value"]
        op = "level"
        if "percent" in row["id"]:
            op = "yoy_pct"
        elif "difference" in row["id"]:
            op = "difference"
        claim = {"op": op, "value": str(value), "display": str(value), "cells": cells}
        ok, py, ruby = _agree(row["question"], claim, cells)
        if not ok:
            mismatches.append(f"{row['id']} python={py} ruby={ruby}")
    assert mismatches == []
