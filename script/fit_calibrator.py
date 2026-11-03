"""Fit the refusal calibrator on dev-A plus dev2 and freeze the TrustSQL cut.

The organisers' 60 and the sealed sets are not read while the cut is chosen.
They are scored once, afterwards, with the cut already frozen.
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

# This pass measures the default path with the look-alike stage off.
os.environ["GRUND_CALIBRATE"] = "collect"
os.environ["GRUND_RERANK"] = "0"
os.environ["GRUND_RAIL"] = "python"
os.environ["GRUND_FUSION"] = "rrf"
os.environ.pop("GRUND_JUDGESIM", None)

STORE = Path("data/work/eval")
DEV_A = Path(os.environ.get("GRUND_DEV_A", str(STORE / "dev-A.jsonl")))
DEV2 = Path(os.environ.get("GRUND_DEV2", str(STORE / "is-native-dev2.jsonl")))
ORG = Path("evalset/track3-questions.jsonl")
TRACK = Path("data/work/judgesim/track3-52.json")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    return {
        "id": question["id"],
        "correct": bool(correct),
        "refused": bool(result.get("refused")),
        "expect_refuse": expect_refuse,
        "features": result.get("features"),
        "value": result.get("value"),
        "table_id": result.get("table_id"),
        "cited_table": any(stem and stem in answer for stem in stems),
        "cited_link": "px.hagstofa.is" in answer,
        "miss": result.get("detail") if isinstance(result.get("detail"), str) else None,
    }


def _slim(row: dict) -> dict:
    return {
        "id": row["id"],
        "correct": row["correct"],
        "refused": row["refused"],
        "expect_refuse": row["expect_refuse"],
        "features": row.get("features"),
        "cited_table": row.get("cited_table"),
        "cited_link": row.get("cited_link"),
    }


def main() -> None:
    from grund.calibrate import (
        apply_threshold,
        choose_threshold,
        fit_logistic,
        report_block,
        save_model,
        threshold_curve,
    )
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(Path("data/index")),
        client=PxWebClient(cache_dir=Path("data/cache")),
        planner="deterministic",
    )
    sets = [("dev-A", _load(DEV_A)), ("dev2", _load(DEV2))]
    collected: dict[str, list[dict]] = {}
    for name, questions in sets:
        rows = []
        for index, question in enumerate(questions, start=1):
            row = _row(engine, question)
            rows.append(row)
            mark = "ok" if row["correct"] else "miss"
            print(f"{name} {index:03d} {mark} refused={row['refused']} {question['id']}", flush=True)
        collected[name] = rows

    train = collected["dev-A"] + collected["dev2"]
    answered = [row for row in train if row.get("features") and not row["refused"]]
    if len(answered) < 20:
        raise SystemExit(f"only {len(answered)} answered rows with features")
    model = fit_logistic([row["features"] for row in answered], [int(row["correct"]) for row in answered])
    curve = threshold_curve(train, model)
    threshold, score = choose_threshold(train, model, min_coverage=0.30)
    eligible = [point for point in curve if point["coverage"] + 1e-12 >= 0.30]
    if not eligible:
        raise SystemExit("no cut states 30% of dev-A plus dev2")
    model["threshold"] = threshold
    model["fit_sets"] = ["dev-A", "dev2"]
    model["fit_n"] = len(train)
    model["fit_trustsql"] = score
    model["min_coverage"] = 0.30
    save_model(model)

    dev_a_applied = apply_threshold(collected["dev-A"], model, threshold)
    dev_a_stated = sum(1 for row in dev_a_applied if not row.get("refused"))
    if dev_a_stated / max(len(dev_a_applied), 1) < 0.30:
        raise SystemExit(f"dev-A stated {dev_a_stated}/{len(dev_a_applied)} under the chosen cut")

    fixture = ROOT / "tests" / "fixtures" / "dev-a-calib-rows.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        json.dumps([_slim(row) for row in collected["dev-A"]], indent=2) + "\n",
        encoding="utf-8",
    )
    out_dir = Path("/tmp/path-scores")
    out_dir.mkdir(parents=True, exist_ok=True)
    curve_path = STORE / "calib-curve.json"
    curve_path.write_text(
        json.dumps({"threshold": threshold, "fit_trustsql": score, "curve": curve}, indent=2) + "\n",
        encoding="utf-8",
    )

    summaries = {}
    for name, rows in collected.items():
        block = report_block(apply_threshold(rows, model, threshold))
        raw = report_block(rows)
        block["threshold"] = threshold
        block["set"] = name
        block["selection"] = "threshold chosen on dev-A plus dev2"
        block["uncalibrated"] = {
            "right": raw["right"],
            "stated": raw["stated"],
            "wrong": raw["wrong"],
            "trustsql": raw["trustsql"],
        }
        summaries[name] = block
        print("CUT", name, json.dumps(block), flush=True)

    # Frozen cut. Same process, so this is still the pre-nlp, rerank-off tree.
    os.environ["GRUND_CALIBRATE"] = ""
    heldout_paths = [
        ("org60", ORG, None),
        ("track3-52", ORG, {row["id"] for row in json.loads(TRACK.read_text(encoding="utf-8"))["rows"]}),
    ]
    for name, path, only in heldout_paths:
        questions = _load(path)
        if only is not None:
            questions = [question for question in questions if question["id"] in only]
        rows = []
        for index, question in enumerate(questions, start=1):
            row = _row(engine, question)
            rows.append(row)
            mark = "ok" if row["correct"] else "miss"
            print(f"{name} {index:03d} {mark} refused={row['refused']} {question['id']}", flush=True)
        block = report_block(rows)
        block["threshold"] = threshold
        block["set"] = name
        block["selection"] = "frozen cut from dev-A plus dev2; not used to choose it"
        summaries[name] = block
        (STORE / f"calib-{name}.json").write_text(
            json.dumps({"summary": block, "rows": [_slim(row) for row in rows]}, indent=2) + "\n",
            encoding="utf-8",
        )
        print("CUT", name, json.dumps(block), flush=True)

    (out_dir / "calib-fit.json").write_text(json.dumps({"threshold": threshold, "summaries": summaries, "curve": curve}, indent=2) + "\n")
    print("FIT_DONE", threshold, flush=True)


if __name__ == "__main__":
    main()
