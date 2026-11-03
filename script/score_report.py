"""Score one or more dev sets with the frozen calibrator.

The threshold is not changed here. Question text is not printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"),
    str(ROOT / "lang"),
    str(ROOT / "indexer"),
    str(ROOT / "rails"),
    str(ROOT / "evalset"),
    "data/work/eval",
]

_TABLE = re.compile(r"\b[A-Z]{3}\d{4,5}\b")


def _cited(row: dict) -> tuple[bool, bool]:
    answer = row.get("answer") or ""
    stems = [str(table).removesuffix(".px") for table in (row.get("tables") or []) if table]
    has_table = any(stem and stem in answer for stem in stems) or _TABLE.search(answer) is not None
    return has_table, "px.hagstofa.is" in answer


def score_file(engine, path: Path) -> dict:
    from grund.calibrate import report_block
    from score_heldout import run

    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = run(questions, engine)
    rows = []
    for row in payload["rows"]:
        has_table, has_link = _cited(row)
        rows.append(
            {
                "id": row["id"],
                "correct": bool(row["correct"]),
                "refused": bool(row["refused"]),
                "expect_refuse": row.get("expect") == "refuse",
                "miss": row.get("miss"),
                "table_id": (row.get("tables") or [None])[0],
                "cited_table": has_table,
                "cited_link": has_link,
            }
        )
    block = report_block(rows)
    misses = {}
    for row in rows:
        if row["miss"]:
            misses[row["miss"]] = misses.get(row["miss"], 0) + 1
    block["miss_counts"] = misses
    block["strict_cited_right"] = sum(
        1
        for row in rows
        if row["correct"] and (row["expect_refuse"] or (row["cited_table"] and row["cited_link"]))
    )
    return {"summary": block, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", required=True, help="name=path")
    parser.add_argument("--out-dir", default="/tmp/path-scores")
    args = parser.parse_args()
    if os.environ.get("GRUND_CALIBRATE", "").strip().lower() == "collect":
        raise SystemExit("GRUND_CALIBRATE=collect would disable the frozen threshold")

    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in args.set:
        name, raw = item.split("=", 1)
        payload = score_file(engine, Path(raw))
        payload["summary"]["set"] = name
        target = out_dir / f"calib-{name}.json"
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(name, json.dumps(payload["summary"]), flush=True)


if __name__ == "__main__":
    main()
