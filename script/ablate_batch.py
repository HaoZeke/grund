"""Ablate judgesim and fusion. Writes one JSON per run. Does not print questions."""

from __future__ import annotations

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

os.environ.setdefault("GRUND_CALIBRATE", "off")
os.environ.setdefault("GRUND_RAIL", "python")


def main() -> None:
    import score_heldout
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient
    from score_report import score_file

    def _quiet(*_args, **_kwargs):
        return None

    score_heldout.print = _quiet  # type: ignore[attr-defined]
    # run() calls the builtin. Silence it locally.
    import builtins

    real_print = builtins.print

    def quiet_print(*args, **kwargs):
        text = " ".join(str(arg) for arg in args)
        if text.startswith("DONE ") or text.startswith("indexed"):
            real_print(*args, **kwargs)

    builtins.print = quiet_print  # type: ignore[assignment]

    store = Path("data/work/eval")
    jobs = [
        ("org60", "1", "rrf", "evalset/track3-questions.jsonl"),
        ("dev2", "0", "rrf", "data/work/eval/is-native-dev2.jsonl"),
        ("dev2", "1", "rrf", "data/work/eval/is-native-dev2.jsonl"),
        ("devA", "1", "rrf", "data/work/eval/dev-A.jsonl"),
        ("org60", "0", "weighted", "evalset/track3-questions.jsonl"),
        ("dev2", "0", "weighted", "data/work/eval/is-native-dev2.jsonl"),
        ("devA", "0", "weighted", "data/work/eval/dev-A.jsonl"),
    ]
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache"), rate=4.0),
        planner="deterministic",
    )
    for name, judgesim, fusion, questions in jobs:
        os.environ["GRUND_JUDGESIM"] = judgesim
        os.environ["GRUND_FUSION"] = fusion
        payload = score_file(engine, Path(questions))
        summary = payload["summary"]
        summary.update({"set": name, "judgesim": judgesim, "fusion": fusion, "calibrate": "off"})
        out = store / f"ablation-{name}-j{judgesim}-f{fusion}.json"
        out.write_text(json.dumps(summary) + "\n", encoding="utf-8")
        wrong = summary["wrong_when_answering"]
        real_print(
            f"DONE {name} j={judgesim} f={fusion} right={summary['right']} "
            f"stated={summary['stated']} wrong={summary['wrong']} trustsql={summary['trustsql']} "
            f"wwa={wrong['wrong']}/{wrong['stated']}",
            flush=True,
        )
    real_print("ABLATE_DONE", flush=True)


if __name__ == "__main__":
    main()
