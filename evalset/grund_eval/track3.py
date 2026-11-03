"""Score Grund on the track-3 questions.

Usage:
    python -m grund_eval.track3 --questions evalset/track3-questions.jsonl --out evalset/results-track3.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from grund.engine import Engine
from grund_eval.metrics import wilson
from grund_eval.track3_score import answer_is_right
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient


def run(questions: list[dict], engine: Engine) -> dict:
    rows = []
    for index, question in enumerate(questions, start=1):
        result = engine.ask(question["question"], question.get("language"))
        tables = list(result.get("tables") or [])
        if not tables and result.get("table_id"):
            tables = [result["table_id"]]
        numbers_right, tables_right, correct = answer_is_right(
            question, result.get("answer") or "", tables
        )
        rows.append(
            {
                "id": question["id"],
                "language": question["language"],
                "level": question["level"],
                "correct": correct,
                "numbers_right": numbers_right,
                "tables_right": tables_right,
                "refused": result.get("refused"),
                "tables": tables,
                "value": result.get("value"),
                "answer": result.get("answer"),
                "elapsed_ms": result.get("elapsed_ms"),
                "planner": result.get("planner"),
            }
        )
        mark = "right" if correct else "WRONG"
        print(f"{index:02d} {mark:<5} {question['id']}", flush=True)
    return {"n": len(rows), "correct": sum(row["correct"] for row in rows), "rows": rows}


def _cell(rows: list[dict]) -> dict:
    successes = sum(row["correct"] for row in rows)
    n = len(rows)
    low, high = wilson(successes, n) if n else (None, None)
    return {"n": n, "successes": successes, "wilson95": [low, high]}


def summarize(payload: dict) -> dict:
    rows = payload["rows"]
    summary = {"all": _cell(rows)}
    for language in ("en", "is"):
        summary[language] = _cell([row for row in rows if row["language"] == language])
    by_level: dict[str, dict] = {}
    levels = defaultdict(list)
    for row in rows:
        levels[row["level"]].append(row)
    for level, group in levels.items():
        by_level[level] = {
            "all": _cell(group),
            "en": _cell([row for row in group if row["language"] == "en"]),
            "is": _cell([row for row in group if row["language"] == "is"]),
        }
    summary["by_level"] = by_level
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score Grund on the track-3 questions")
    parser.add_argument("--questions", type=Path, default=Path("evalset/track3-questions.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/index"))
    parser.add_argument("--out", type=Path, default=Path("evalset/results-track3.json"))
    parser.add_argument("--planner", default="deterministic")
    args = parser.parse_args(argv)
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    catalogue = Catalogue.load(args.index)
    engine = Engine(catalogue, client=PxWebClient(cache_dir=Path("data/cache")), planner=args.planner)
    payload = run(questions, engine)
    payload["summary"] = summarize(payload)
    times = [row["elapsed_ms"] for row in payload["rows"] if isinstance(row.get("elapsed_ms"), int)]
    if times:
        payload["summary"]["latency_ms"] = {
            "mean": round(sum(times) / len(times)),
            "max": max(times),
        }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
