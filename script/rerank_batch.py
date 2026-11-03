"""End-to-end rerank ablation. One JSON per run. No question text."""

from __future__ import annotations

import builtins
import json
import os
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
os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_RAIL"] = "python"
os.environ["GRUND_FUSION"] = "rrf"

import score_heldout  # noqa: E402
from grund.engine import Engine  # noqa: E402
from grund_index.catalogue import Catalogue  # noqa: E402
from grund_index.client import PxWebClient  # noqa: E402
from score_report import score_file  # noqa: E402

real_print = builtins.print
builtins.print = lambda *a, **k: None  # type: ignore[assignment]
score_heldout.print = builtins.print  # type: ignore[attr-defined]


def main() -> None:
    store = Path("data/work/eval")
    jobs = [
        ("org60", "0", "evalset/track3-questions.jsonl"),
        ("dev2", "0", "data/work/eval/is-native-dev2.jsonl"),
        ("devA", "0", "data/work/eval/dev-A.jsonl"),
        ("org60", "1", "evalset/track3-questions.jsonl"),
        ("dev2", "1", "data/work/eval/is-native-dev2.jsonl"),
        ("devA", "1", "data/work/eval/dev-A.jsonl"),
    ]
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    for name, flag, questions in jobs:
        os.environ["GRUND_RERANK"] = flag
        summary = score_file(engine, Path(questions))["summary"]
        summary.update({"set": name, "rerank": flag, "calibrate": "off", "rail": "python"})
        out = store / f"rerank-{name}-{flag}.json"
        out.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        wrong = summary["wrong_when_answering"]
        real_print(
            f"DONE {name} rerank={flag} right={summary['right']} stated={summary['stated']} "
            f"wrong={summary['wrong']} trustsql={summary['trustsql']} wwa={wrong['wrong']}/{wrong['stated']}",
            flush=True,
        )
    real_print("RERANK_DONE", flush=True)


if __name__ == "__main__":
    main()
