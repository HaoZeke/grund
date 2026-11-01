"""Score one file and write a one-line summary. Question text is not printed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "script")]

from score_report import score_file  # noqa: E402
from grund.engine import Engine  # noqa: E402
from grund_index.catalogue import Catalogue  # noqa: E402
from grund_index.client import PxWebClient  # noqa: E402


def main() -> None:
    name, questions, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache"), rate=4.0),
        planner="deterministic",
    )
    payload = score_file(engine, questions)
    summary = payload["summary"]
    summary["set"] = name
    summary["judgesim"] = os.environ.get("GRUND_JUDGESIM", "")
    summary["fusion"] = os.environ.get("GRUND_FUSION", "rrf")
    summary["calibrate"] = os.environ.get("GRUND_CALIBRATE", "")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    wrong = summary["wrong_when_answering"]
    print(
        f"DONE {name} judgesim={summary['judgesim']} fusion={summary['fusion']} "
        f"right={summary['right']} stated={summary['stated']} wrong={summary['wrong']} "
        f"trustsql={summary['trustsql']} wwa={wrong['wrong']}/{wrong['stated']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
