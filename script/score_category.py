"""Score dev-A, dev2, the organisers' 60 and the Track 3 52 with category binding.

Abstainer off, bind2 off, veto off. Compares previously-right ids to the
gates-only rows. Question text is not printed.
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
    "data/work/eval",
]

os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ.pop("GRUND_BIND2", None)
os.environ.pop("GRUND_BIND2_VETO", None)
os.environ.pop("GRUND_JUDGESIM", None)
os.environ.pop("GRUND_RERANK", None)
os.environ["GRUND_RAIL"] = "python"
os.environ["GRUND_FUSION"] = "rrf"

STORE = Path("data/work/eval")
ORG = Path("evalset/track3-questions.jsonl")
TRACK = Path("/tmp/track3-52-questions.jsonl")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    from abstain_frontier import _apply, _row
    from grund.calibrate import load_model, report_block
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    jobs = [
        ("dev-A", _load(STORE / "dev-A.jsonl"), STORE / "gates-dev-A.json"),
        ("dev2", _load(STORE / "is-native-dev2.jsonl"), STORE / "gates-dev2.json"),
        ("org60", _load(ORG), STORE / "gates-org60.json"),
        ("track3-52", _load(TRACK), STORE / "gates-track3-52.json"),
    ]
    collected = {}
    report = {}
    for name, questions, before_path in jobs:
        rows = []
        for index, question in enumerate(questions, start=1):
            row = _row(engine, question)
            rows.append(row)
            mark = "ok" if row["correct"] else "miss"
            print(f"{name} {index:03d} {mark} refused={row['refused']} {question['id']}", flush=True)
        collected[name] = rows
        (STORE / f"category-{name}.json").write_text(json.dumps(rows) + "\n", encoding="utf-8")
        before = {row["id"]: row for row in json.loads(before_path.read_text())}
        lost = [
            row["id"]
            for row in rows
            if before.get(row["id"], {}).get("correct") and not before.get(row["id"], {}).get("refused")
            and not (row["correct"] and not row["refused"])
        ]
        gained = [
            row["id"]
            for row in rows
            if row["correct"] and not row["refused"]
            and not (before.get(row["id"], {}).get("correct") and not before.get(row["id"], {}).get("refused"))
        ]
        block = report_block(rows)
        report[name] = {
            "right": block["right"],
            "stated": block["stated"],
            "wrong": block["wrong"],
            "trustsql": block["trustsql"],
            "n": block["n"],
            "lost_rights": lost,
            "gained_rights": gained,
        }
        print(
            f"DONE {name} right={block['right']} wrong={block['wrong']} "
            f"lost={len(lost)} gained={len(gained)}",
            flush=True,
        )

    model = load_model()
    policies = ("none", "share", "derived", "hybrid70", "disagree")
    union = collected["dev-A"] + collected["dev2"]
    frontier = {}
    for policy in policies:
        use = union if policy == "none" else _apply(union, policy, model)
        block = report_block(use)
        frontier[policy] = {
            "trustsql": block["trustsql"],
            "right": block["right"],
            "wrong": block["wrong"],
            "stated": block["stated"],
            "mean": block["trustsql"] / block["n"],
        }
    best = max(frontier, key=lambda name: (frontier[name]["trustsql"], frontier[name]["right"]))
    near = [
        name
        for name, row in frontier.items()
        if frontier[best]["trustsql"] - row["trustsql"] <= 5
    ]
    chosen = max(near, key=lambda name: frontier[name]["right"])
    out = {"sets": report, "frontier_union": frontier, "chosen": chosen}
    (STORE / "category-frontier.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("CATEGORY_FRONTIER", json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
