"""Score the ten Track 3 questions that are not in the organisers' 60."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "script"), str(ROOT / "app"), str(ROOT / "lang"), str(ROOT / "indexer"), str(ROOT / "rails"), str(ROOT / "evalset")]

os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ["GRUND_RAIL"] = "python"
os.environ["GRUND_FUSION"] = "rrf"
os.environ.pop("GRUND_JUDGESIM", None)
os.environ.pop("GRUND_RERANK", None)

from abstain_frontier import _row  # noqa: E402
from grund.engine import Engine  # noqa: E402
from grund_index.catalogue import Catalogue  # noqa: E402
from grund_index.client import PxWebClient  # noqa: E402

WANT = {
    "women-iceland-2025-en",
    "women-iceland-2025-is",
    "population-akureyri-2025-en",
    "population-akureyri-2025-is",
    "cod-catch-2026-09-en",
    "cod-catch-2026-09-is",
    "building-cost-index-2024-en",
    "building-cost-index-2024-is",
    "reykjavik-people-and-cod-en",
    "reykjavik-people-and-cod-is",
}


def main() -> None:
    questions = [
        json.loads(line)
        for line in Path("/tmp/track3-52-questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["id"] in WANT
    ]
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    rows = []
    for index, question in enumerate(questions, start=1):
        row = _row(engine, question)
        rows.append(row)
        mark = "ok" if row["correct"] else "miss"
        print(f"extra {index:02d} {mark} refused={row['refused']} {question['id']}", flush=True)
    out = Path("data/work/eval/gates-track3-extra.json")
    out.write_text(json.dumps(rows) + "\n", encoding="utf-8")
    print("EXTRA_DONE", len(rows), flush=True)


if __name__ == "__main__":
    main()
