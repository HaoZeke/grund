"""Record both paths for dev-A and dev2 rows the disagreement rule refuses.

Only ids already known to be right or wrong with agreement below 1. No
question text is printed. Abstainer off.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "lang"), str(ROOT / "indexer"), str(ROOT / "rails"), str(ROOT / "evalset")]

os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ["GRUND_RAIL"] = "python"
os.environ.pop("GRUND_JUDGESIM", None)

STORE = Path("data/work/eval")


def ids_of(name: str) -> list[str]:
    rows = json.loads((STORE / name).read_text())
    found = []
    for row in rows:
        features = row.get("features") or {}
        try:
            agreement = float(features.get("agreement"))
        except (TypeError, ValueError):
            continue
        if row.get("refused") or agreement >= 0.999:
            continue
        if row.get("correct") or not row.get("correct"):
            found.append(row["id"])
    return found


def main() -> None:
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    wanted = {
        "dev-A": set(ids_of("gates-dev-A.json")),
        "dev2": set(ids_of("gates-dev2.json")),
    }
    files = {
        "dev-A": STORE / "dev-A.jsonl",
        "dev2": STORE / "is-native-dev2.jsonl",
    }
    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    out_rows = []
    for name, path in files.items():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            question = json.loads(line)
            if question["id"] not in wanted[name]:
                continue
            result = engine.ask(question["question"], question.get("language"))
            source = result.get("source") if isinstance(result.get("source"), dict) else {}
            features = result.get("features") or {}
            row = {
                "set": name,
                "id": question["id"],
                "refused": bool(result.get("refused")),
                "value": result.get("value"),
                "table": result.get("table_id"),
                "operation": result.get("operation"),
                "other_value": source.get("other_value"),
                "other_table": source.get("other_table"),
                "agreement": features.get("agreement"),
                "detail": result.get("detail") if isinstance(result.get("detail"), str) else None,
            }
            out_rows.append(row)
            print(
                f"{name} {question['id']} refused={row['refused']} table={row['table']} "
                f"other={row['other_table']} ag={row['agreement']}",
                flush=True,
            )
    (STORE / "disagree-pairs.json").write_text(json.dumps(out_rows, indent=2) + "\n")
    print("PROBE_DONE", len(out_rows), flush=True)


if __name__ == "__main__":
    main()
