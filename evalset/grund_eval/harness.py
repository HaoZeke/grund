"""Score Grund and the baselines on evalset/questions.jsonl.

Usage:
    python -m grund_eval.harness --questions evalset/questions.jsonl --out evalset/results.json
"""

from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

from grund.arithmetic import ArithmeticError, to_decimal
from grund.engine import Engine
from grund.llm import ChatClient
from grund_eval.baselines import naive_bm25, plain_llm
from grund_eval.metrics import summarise
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient


def close(got, gold) -> bool:
    if got is None or gold is None:
        return False
    try:
        left = to_decimal(str(got))
        right = to_decimal(str(gold))
    except ArithmeticError:
        return False
    return abs(left - right) <= max(Decimal("0.051"), abs(right) * Decimal("0.001"))


def _keys(source: dict | None) -> list[list[str]]:
    if not source:
        return []
    return [list(map(str, cell.get("key") or [])) for cell in source.get("cells") or []]


def score_row(question: dict, result: dict) -> dict:
    expect = question["expect"]
    refused = bool(result.get("refused"))
    clarified = bool(result.get("clarify"))
    if expect == "refuse":
        return {
            "refusal_correct": refused and not result.get("value"),
            "table_correct": None,
            "value_correct": None,
            "citation_correct": None,
        }
    if expect == "clarify":
        clarified_ok = (clarified or refused) and not result.get("value")
        return {
            "refusal_correct": clarified_ok,
            "table_correct": None,
            "value_correct": None,
            "citation_correct": None,
        }
    table_correct = result.get("table_id") == question["table_id"]
    value_correct = close(result.get("value"), question.get("value"))
    source = result.get("source") or {}
    gold_keys = [list(map(str, key)) for key in question.get("cell_keys") or []]
    got_keys = _keys(source)
    keys_ok = all(key in got_keys for key in gold_keys) if gold_keys else False
    preliminary_ok = True
    if question.get("preliminary"):
        preliminary_ok = bool(source.get("preliminary"))
    citation_correct = bool(
        table_correct
        and source.get("api_url")
        and source.get("retrieved_at")
        and keys_ok
        and preliminary_ok
    )
    return {
        "refusal_correct": None,
        "table_correct": table_correct,
        "value_correct": value_correct,
        "citation_correct": citation_correct,
    }


def _bundle(scored: list[dict]) -> dict:
    answerable = [row for row in scored if row["expect"] == "answer"]
    withheld = [row for row in scored if row["expect"] in {"refuse", "clarify"}]
    by_stratum = {}
    strata = sorted({row["stratum"] for row in scored})
    for stratum in strata:
        rows = [row for row in scored if row["stratum"] == stratum]
        by_stratum[stratum] = {
            "table": summarise(rows, "table_correct"),
            "value": summarise(rows, "value_correct"),
            "citation": summarise(rows, "citation_correct"),
            "refusal": summarise(rows, "refusal_correct"),
        }
    def slice_summary(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "table": summarise(rows, "table_correct"),
            "value": summarise(rows, "value_correct"),
            "citation": summarise(rows, "citation_correct"),
            "refusal": summarise(rows, "refusal_correct"),
        }

    return {
        "n": len(scored),
        "answerable": slice_summary(answerable),
        "withheld": slice_summary(withheld),
        "hag_scope": slice_summary([row for row in scored if row.get("hag_scope")]),
        "beyond_hag": slice_summary([row for row in scored if not row.get("hag_scope")]),
        "by_stratum": by_stratum,
    }


def run(questions: list[dict], engine: Engine, client: PxWebClient) -> dict:
    grund_rows = []
    naive_rows = []
    for index, question in enumerate(questions, start=1):
        result = engine.ask(question["question"], question.get("language"))
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        row = {
            **question,
            **score_row(question, result),
            "predicted_table": result.get("table_id"),
            "predicted_value": result.get("value"),
            "refused": result.get("refused"),
            "planner": source.get("planner") or result.get("planner"),
            "planner_notes": source.get("planner_notes"),
        }
        grund_rows.append(row)
        baseline = naive_bm25(engine.catalogue, client, question["question"])
        naive_rows.append({**question, **score_row(question, baseline), "predicted_table": baseline.get("table_id"), "predicted_value": baseline.get("value"), "refused": baseline.get("refused")})
        if index % 10 == 0:
            print(f"scored {index}/{len(questions)}", flush=True)
    plain_summary = None
    chat = ChatClient()
    if chat.settings.enabled():
        plain_rows = []
        for question in questions:
            result = plain_llm(chat, question["question"])
            assert result is not None
            plain_rows.append({**question, **score_row(question, result)})
        plain_summary = _bundle(plain_rows)
    else:
        plain_summary = {"status": "not_run", "reason": "GRUND_LLM_BASE_URL is unset"}
    return {
        "grund": _bundle(grund_rows),
        "naive_bm25": _bundle(naive_rows),
        "plain_llm": plain_summary,
        "cases": [
            {
                "id": row["id"],
                "stratum": row["stratum"],
                "expect": row["expect"],
                "table_correct": row["table_correct"],
                "value_correct": row["value_correct"],
                "citation_correct": row["citation_correct"],
                "refusal_correct": row["refusal_correct"],
                "predicted_table": row["predicted_table"],
                "gold_table": row["table_id"],
                "planner": row.get("planner"),
                "planner_notes": row.get("planner_notes"),
            }
            for row in grund_rows
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Grund eval harness")
    parser.add_argument("--questions", type=Path, default=Path("evalset/questions.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/index"))
    parser.add_argument("--out", type=Path, default=Path("evalset/results.json"))
    parser.add_argument("--planner", choices=["deterministic", "llm", "hybrid", "auto"], default="deterministic")
    args = parser.parse_args(argv)
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    catalogue = Catalogue.load(args.index)
    client = PxWebClient(cache_dir=Path("data/cache"), rate=4.0)
    engine = Engine(catalogue, client=client, planner=args.planner)
    payload = run(questions, engine, client)
    chat = ChatClient()
    payload["llm"] = {
        "enabled": chat.settings.enabled(),
        "base_url": chat.settings.base_url or None,
        "model": os.environ.get("GRUND_LLM_MODEL") if chat.settings.enabled() else None,
        "quantization": os.environ.get("GRUND_LLM_QUANT") or None,
        "weights": os.environ.get("GRUND_LLM_WEIGHTS") or None,
        "runtime": os.environ.get("GRUND_LLM_RUNTIME") or None,
        "planner": args.planner,
        "prose": os.environ.get("GRUND_LLM_PROSE", "").lower() in {"1", "true", "yes"},
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "grund": payload["grund"]["answerable"],
        "withheld": payload["grund"]["withheld"]["refusal"],
        "naive": payload["naive_bm25"]["answerable"],
        "plain_llm": payload["plain_llm"] if isinstance(payload["plain_llm"], dict) and payload["plain_llm"].get("status") == "not_run" else {
            "answerable": (payload["plain_llm"] or {}).get("answerable"),
            "withheld": (payload["plain_llm"] or {}).get("withheld", {}).get("refusal") if isinstance(payload["plain_llm"], dict) else None,
        },
    }, indent=2))


if __name__ == "__main__":
    main()
