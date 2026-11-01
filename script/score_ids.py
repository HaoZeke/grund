"""Score a question file, optionally restricted to ids. One summary line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT),
    str(ROOT / "script"),
    str(ROOT / "app"),
    str(ROOT / "lang"),
    str(ROOT / "indexer"),
    str(ROOT / "rails"),
    str(ROOT / "evalset"),
    "data/work/eval",
]

import builtins
import score_heldout
from grund.engine import Engine
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient
from score_report import score_file

builtins.print = lambda *a, **k: None  # type: ignore[assignment]
score_heldout.print = builtins.print  # type: ignore[attr-defined]


def main() -> None:
    questions = Path(sys.argv[1])
    out = Path(sys.argv[2])
    only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None
    if only:
        rows = [json.loads(line) for line in questions.read_text().splitlines() if line.strip()]
        rows = [row for row in rows if row["id"] in only]
        tmp = Path("/tmp/score-ids.jsonl")
        tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        questions = tmp
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache"), rate=4.0),
        planner="deterministic",
    )
    payload = score_file(engine, questions)
    summary = payload["summary"]
    out.write_text(json.dumps({"summary": summary, "rows": payload["rows"]}) + "\n", encoding="utf-8")
    wrong = summary["wrong_when_answering"]
    sys.stderr.write(
        f"right={summary['right']} stated={summary['stated']} wrong={summary['wrong']} "
        f"trustsql={summary['trustsql']} wwa={wrong['wrong']}/{wrong['stated']}\n"
    )


if __name__ == "__main__":
    main()
