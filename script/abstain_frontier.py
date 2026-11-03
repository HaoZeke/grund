"""Score the four sets with the gates on, then pick an abstain policy.

dev-A and dev2 choose the policy. The organisers' 60 and the Track 3 52
are scored with that choice and are not used to make it. Question text
is not printed.
"""

from __future__ import annotations

import json
import os
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

os.environ["GRUND_CALIBRATE"] = "off"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ["GRUND_RAIL"] = "python"
os.environ["GRUND_FUSION"] = "rrf"
os.environ.pop("GRUND_JUDGESIM", None)
os.environ.pop("GRUND_RERANK", None)

STORE = Path("data/work/eval")
ORG = Path("evalset/track3-questions.jsonl")
TRACK_QUESTIONS = Path("/tmp/track3-52-questions.jsonl")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _class(operation: str | None) -> str:
    op = str(operation or "").lower()
    if op in {"pair", "ratio"}:
        return "pair"
    if op in {"share", "share_percent"}:
        return "share"
    if op in {"yoy_pct", "change", "pct_change"}:
        return "change"
    return op


def _row(engine, question: dict) -> dict:
    from grund_eval.track3_score import answer_is_right

    result = engine.ask(question["question"], question.get("language"))
    tables = list(result.get("tables") or [])
    if not tables and result.get("table_id"):
        tables = [result["table_id"]]
    expect_refuse = question.get("expect") == "refuse"
    if expect_refuse:
        correct = bool(result.get("refused")) and result.get("value") in (None, "")
    else:
        _numbers, _tables, correct = answer_is_right(
            question,
            result.get("answer") or "",
            tables,
            claimed=result.get("value"),
        )
    answer = result.get("answer") or ""
    stems = [str(table).removesuffix(".px") for table in tables if table]
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    return {
        "id": question["id"],
        "correct": bool(correct),
        "refused": bool(result.get("refused")),
        "expect_refuse": expect_refuse,
        "features": result.get("features"),
        "operation": result.get("operation"),
        "gate": source.get("gate"),
        "cited_table": any(stem and stem in answer for stem in stems),
        "cited_link": "px.hagstofa.is" in answer,
    }


def _apply(rows: list[dict], policy: str, model: dict) -> list[dict]:
    from grund.calibrate import probability

    applied = []
    for row in rows:
        if row.get("refused") or not row.get("features"):
            applied.append({**row, "refused": True})
            continue
        features = row["features"]
        chance = probability(features, model)
        op = _class(row.get("operation"))
        drop = False
        if policy == "share" and op == "share" and chance < 0.65:
            drop = True
        elif policy == "derived" and op in {"pair", "share", "change"} and chance < 0.65:
            drop = True
        elif policy == "hybrid70" and row.get("gate") == "hybrid" and chance < 0.70:
            drop = True
        elif policy == "disagree":
            try:
                drop = float(features.get("agreement")) < 0.999
            except (TypeError, ValueError):
                drop = False
        if drop:
            applied.append({**row, "refused": True, "correct": False, "policy_refused": True})
        else:
            applied.append({**row, "policy_refused": False})
    return applied


def main() -> None:
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
        ("dev-A", _load(STORE / "dev-A.jsonl")),
        ("dev2", _load(STORE / "is-native-dev2.jsonl")),
        ("org60", _load(ORG)),
        ("track3-52", _load(TRACK_QUESTIONS)),
    ]
    collected = {}
    for name, questions in jobs:
        rows = []
        for index, question in enumerate(questions, start=1):
            row = _row(engine, question)
            rows.append(row)
            mark = "ok" if row["correct"] else "miss"
            print(f"{name} {index:03d} {mark} refused={row['refused']} {question['id']}", flush=True)
        collected[name] = rows
        (STORE / f"gates-{name}.json").write_text(json.dumps(rows) + "\n", encoding="utf-8")

    model = load_model()
    policies = ("none", "share", "derived", "hybrid70", "disagree")
    frontier = {}
    for name, rows in collected.items():
        frontier[name] = {}
        for policy in policies:
            use = rows if policy == "none" else _apply(rows, policy, model)
            block = report_block(use)
            frontier[name][policy] = {
                "right": block["right"],
                "stated": block["stated"],
                "wrong": block["wrong"],
                "trustsql": block["trustsql"],
                "n": block["n"],
                "mean": block["trustsql"] / block["n"] if block["n"] else None,
            }
    # The choice is the union of dev-A and dev2. Close policies keep more rights.
    union_rows = collected["dev-A"] + collected["dev2"]
    ranking = []
    for policy in policies:
        use = union_rows if policy == "none" else _apply(union_rows, policy, model)
        block = report_block(use)
        ranking.append((block["trustsql"], block["right"], policy, block))
    ranking.sort(key=lambda item: item[0], reverse=True)
    best_score = ranking[0][0]
    # Within five TrustSQL points, keep the policy that states more right answers.
    near = [item for item in ranking if best_score - item[0] <= 5]
    near.sort(key=lambda item: item[1], reverse=True)
    _score, _right, chosen, best_block = near[0]
    close = len(near) > 1 and chosen != ranking[0][2]
    out = {
        "chosen": chosen,
        "close_tie_break": close,
        "union": [
            {"policy": policy, "trustsql": score, "right": right}
            for score, right, policy, _block in ranking
        ],
        "frontier": frontier,
    }
    (STORE / "abstain-frontier.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("FRONTIER", json.dumps(out), flush=True)
    print("CHOSEN", chosen, flush=True)


if __name__ == "__main__":
    main()
