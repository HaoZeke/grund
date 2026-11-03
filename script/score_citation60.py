"""Rerun the organisers' 60 on the Ruby rail after the citation fix.

Abstainer off, so a refusal is the gate or a checker, not the disagreement
policy. Question text is not printed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "script"),
    str(ROOT / "app"),
    str(ROOT / "lang"),
    str(ROOT / "indexer"),
    str(ROOT / "rails"),
    str(ROOT / "evalset"),
]

os.environ["RUBYLIB"] = os.environ.get("RUBYLIB") or "vendor/vangrail/lib"
os.environ.pop("GRUND_JUDGESIM", None)
os.environ.pop("GRUND_BIND2", None)
os.environ.pop("GRUND_BIND2_VETO", None)

from abstain_frontier import _row  # noqa: E402

# abstain_frontier sets the rail to python on import. This run is the Ruby checker.
os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ["GRUND_RAIL"] = "ruby"
from grund.calibrate import report_block  # noqa: E402
from grund.engine import Engine  # noqa: E402
from grund_eval.metrics import wilson  # noqa: E402
from grund_index.catalogue import Catalogue  # noqa: E402
from grund_index.client import PxWebClient  # noqa: E402

OLD = Path("data/work/judgesim/sixty-calibrate-off.json")
ORG = Path("evalset/track3-questions.jsonl")
OUT = Path("data/work/eval/citation-org60.json")


def main() -> None:
    old = {row["id"]: row for row in json.loads(OLD.read_text())["rows"]}
    questions = [json.loads(line) for line in ORG.read_text().splitlines() if line.strip()]
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
        print(f"org60 {index:03d} {mark} refused={row['refused']} {question['id']}", flush=True)
    block = report_block(rows)
    old_right = {key for key, row in old.items() if row.get("correct") and not row.get("refused")}
    old_wrong = {key for key, row in old.items() if not row.get("correct") and not row.get("refused")}
    now = {row["id"]: row for row in rows}
    recovered = sorted(
        key for key in old
        if key not in old_right and now[key]["correct"] and not now[key]["refused"]
    )
    wrongs_back = sorted(key for key in old_wrong if not now[key]["refused"])
    still_wrong = sorted(key for key in old_wrong if not now[key]["correct"] and not now[key]["refused"])
    summary = {
        "right": block["right"],
        "stated": block["stated"],
        "wrong": block["wrong"],
        "trustsql": block["trustsql"],
        "n": block["n"],
        "coverage_wilson95": list(wilson(block["stated"], block["n"])),
        "wrong_when_answering_wilson95": list(wilson(block["wrong"], block["stated"])) if block["stated"] else None,
        "error_rate_wilson95": list(wilson(block["wrong"], block["n"])),
        "recovered_rights": recovered,
        "former_wrongs_still_stated": still_wrong,
        "former_wrongs_stated_again": wrongs_back,
    }
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n", encoding="utf-8")
    print("CITATION60", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
