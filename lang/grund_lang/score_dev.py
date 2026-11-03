"""Answer a dev set with retrieve() and bind_values(), then use the eval scorer.

The miss categories are the ones in score_heldout.py. A wrong cell is split
further into unit, total-versus-subgroup, or the remaining cell.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient

from grund_lang.driver import LangEngine
from grund_lang.index import load_index

_TOTAL = {"0", "-1", "total", "alls", "allt", "999", "is"}
_UNIT_NAMES = ("eining", "unit", "breyta", "breytur", "maelikvardi", "mælikvarði")


def _load_scorer(path: Path):
    spec = importlib.util.spec_from_file_location("score_heldout", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _posted(result: dict) -> dict[str, list[str]]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    posted: dict[str, list[str]] = {}
    for entry in source.get("query") or []:
        code = str(entry.get("code") or "")
        values = [str(value) for value in ((entry.get("selection") or {}).get("values") or [])]
        if code:
            posted[code] = values
    return posted


def _refine(question: dict, result: dict, category: str | None) -> str | None:
    if category != "wrong cell":
        return category
    posted = _posted(result)
    unit = False
    total = False
    for part in question.get("parts") or []:
        for name, gold in (part.get("categories") or {}).items():
            gold_code = str(gold)
            found = posted.get(str(name))
            if found is None:
                continue
            if gold_code in found:
                continue
            folded = str(name).lower()
            if any(piece in folded for piece in _UNIT_NAMES):
                unit = True
            gold_total = gold_code.lower() in _TOTAL
            posted_total = any(value.lower() in _TOTAL for value in found)
            if gold_total != posted_total:
                total = True
    if unit:
        return "unit"
    if total:
        return "total-versus-subgroup"
    return "wrong cell"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score a dev set with the language retrieval path")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True, help="metadata index the fetcher loads")
    parser.add_argument("--lang-index", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    args = parser.parse_args(argv)
    scorer = _load_scorer(args.scorer)
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]
    catalogue = Catalogue.load(args.index)
    retrieval = load_index(args.lang_index)
    engine = LangEngine(
        catalogue,
        retrieval,
        client=PxWebClient(cache_dir=args.cache),
        planner="deterministic",
    )
    rows = []
    for index, question in enumerate(questions, start=1):
        result = engine.ask(question["question"], question.get("language"))
        tables = list(result.get("tables") or [])
        if not tables and result.get("table_id"):
            tables = [result["table_id"]]
        numbers_right, tables_right, correct = scorer.answer_is_right(question, result.get("answer") or "", tables)
        category = scorer.miss_category(question, result, numbers_right, tables_right)
        detail = _refine(question, result, category)
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        rows.append(
            {
                "id": question["id"],
                "language": question["language"],
                "level": question.get("level") or question.get("tier"),
                "subject": question.get("subject"),
                "correct": correct,
                "numbers_right": numbers_right,
                "tables_right": tables_right,
                "miss": category,
                "miss_detail": detail,
                "refused": bool(result.get("refused")),
                "tables": [str(table).removesuffix(".px") for table in tables],
                "value": result.get("value"),
                "answer": result.get("answer"),
                "elapsed_ms": result.get("elapsed_ms"),
                "query": (source or {}).get("query"),
            }
        )
        mark = "right" if correct else (detail or "WRONG")
        print(f"{index:03d} {mark:<22} {question['id']}", flush=True)
    payload = {"n": len(rows), "correct": sum(row["correct"] for row in rows), "rows": rows}
    payload["summary"] = scorer.summarize(rows)
    # summarize() only knows the original miss names. Recount after the split.
    counts: dict[str, int] = {}
    for row in rows:
        name = row.get("miss_detail")
        if name:
            counts[name] = counts.get(name, 0) + 1
    payload["summary"]["miss_counts"] = counts
    payload["planner"] = "lang"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief = {
        "planner": "lang",
        "all": payload["summary"]["all"],
        "en": payload["summary"]["en"],
        "is": payload["summary"]["is"],
        "by_level": payload["summary"]["by_level"],
        "miss_counts": counts,
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
