"""End-to-end score on the ruby rail with the shipped disagreement rule.

The engine applies the rule. This is not an offline replay. Question text
is not stored. TrustSQL-10 is the signed sum: +1 right or correct
abstention, 0 for refusing a question that has a gold cell, -10 for a
stated wrong figure. Wilson intervals are 95% on right/n and wrong/n.
"""

from __future__ import annotations

import json
import math
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
]

os.environ["RUBYLIB"] = os.environ.get("RUBYLIB") or "vendor/vangrail/lib"
os.environ["GRUND_RAIL"] = "ruby"
os.environ["GRUND_E5_DIR"] = "data/models/small"
os.environ["GRUND_E5_SMALL_INDEX"] = "data/index-e5-small"
for name in (
    "GRUND_ABSTAIN_RULE",
    "GRUND_CALIBRATE",
    "GRUND_RECALL",
    "GRUND_LEXICON",
    "GRUND_JUDGESIM",
    "GRUND_BIND2",
    "GRUND_BIND2_VETO",
    "GRUND_SUBJECT_CHECK",
    "GRUND_SUBJECT",
    "GRUND_RERANK",
):
    os.environ.pop(name, None)

ENV = (
    "GRUND_RAIL=ruby; GRUND_ABSTAIN_RULE=unset (disagree; other-table published "
    "figure kept; closed historical SOG kept); GRUND_CALIBRATE=unset; "
    "GRUND_RECALL=unset (fill); GRUND_LEXICON=unset (on); GRUND_RERANK=unset (on); "
    "GRUND_SUBJECT=unset (on); GRUND_TITLE_ECHO=unset (on); lookalike=on; zero-count=on; loose-gates=on; "
    "GRUND_BIND2_VETO=unset; "
    "GRUND_E5=small; GRUND_E5_DIR=data/models/small; GRUND_E5_SMALL_INDEX=data/index-e5-small; "
    "value-index=chargram rebuilt from data/index; GRUND_INDEX=data/index; vangrail=0.3.0"
)

STORE = Path("/tmp/ruby-keep")
LOG = Path("/tmp/ruby-keep.log")


def _diag() -> list[dict]:
    path = Path("data/work/judgesim/judge-sim.jsonl")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") == "diag":
            rows.append(row)
    return rows


SETS = [
    ("dev-A", Path("data/work/eval/dev-A.jsonl")),
    ("dev2", Path("data/work/eval/is-native-dev2.jsonl")),
    ("dev-B", Path("data/work/eval/dev-B.jsonl")),
    ("dev-C", Path("data/work/eval/dev-C.jsonl")),
    ("org60", ROOT / "evalset" / "track3-questions.jsonl"),
    ("track3-52", Path("/tmp/track3-52-questions.jsonl")),
    ("diag-100", None),
]


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _agreement(result: dict):
    features = result.get("features") if isinstance(result.get("features"), dict) else {}
    try:
        return float(features.get("agreement"))
    except (TypeError, ValueError):
        return None


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
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    pair = result.get("path_pair") if isinstance(result.get("path_pair"), dict) else {}
    return {
        "id": question["id"],
        "expect_refuse": expect_refuse,
        "correct": bool(correct),
        "refused": bool(result.get("refused")),
        "value": result.get("value"),
        "value_display": result.get("value_display"),
        "table_id": result.get("table_id"),
        "operation": result.get("operation"),
        "detail": result.get("detail"),
        "agreement": _agreement(result),
        "gate": source.get("gate"),
        "other_table": source.get("other_table"),
        "other_value": source.get("other_value"),
        "other_detail": source.get("other_detail"),
        "other_refused": source.get("other_refused"),
        "index_table": source.get("index_table"),
        "closed_historical": source.get("closed_historical"),
        "path_pair": pair,
        "rail": "ruby",
        "env": ENV,
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centre - margin, centre + margin


def summarise(name: str, rows: list[dict]) -> dict:
    right = wrong = abstain = 0
    for row in rows:
        if row.get("expect_refuse"):
            if row.get("refused") and row.get("correct"):
                right += 1
            elif row.get("refused"):
                abstain += 1
            else:
                wrong += 1
            continue
        if row.get("refused") or row.get("value") in (None, ""):
            abstain += 1
            continue
        if row.get("correct"):
            right += 1
        else:
            wrong += 1
    n = len(rows)
    trust = right - 10 * wrong
    low_r, high_r = wilson(right, n)
    low_w, high_w = wilson(wrong, n)
    summary = {
        "set": name,
        "n": n,
        "right": right,
        "wrong": wrong,
        "abstain": abstain,
        "trustsql": trust,
        "mean": trust / n if n else 0.0,
        "right_wilson": [low_r, high_r],
        "wrong_wilson": [low_w, high_w],
        "rail": "ruby",
        "env": ENV,
    }
    print(
        f"{name} right {right}/{n} [{low_r:.3f}, {high_r:.3f}] "
        f"wrong {wrong}/{n} [{low_w:.3f}, {high_w:.3f}] "
        f"abstain {abstain} TrustSQL-10 {trust} mean {summary['mean']:.4f} rail=ruby",
        flush=True,
    )
    return summary


def main() -> None:
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(ROOT / "data" / "index"),
        client=PxWebClient(cache_dir=ROOT / "data" / "cache"),
        planner="deterministic",
    )
    STORE.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    summaries = []
    for name, path in SETS:
        questions = _diag() if name == "diag-100" else _load(path)
        dest = STORE / f"{name}.jsonl"
        dest.write_text("", encoding="utf-8")
        rows = []
        for index, question in enumerate(questions, start=1):
            row = _row(engine, question)
            rows.append(row)
            with dest.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            with LOG.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{name}\t{index}/{len(questions)}\t{row['id']}\t"
                    f"refused={row['refused']}\tcorrect={row['correct']}\t"
                    f"value={row['value']}\ttable={row['table_id']}\t"
                    f"ag={row['agreement']}\t{row['detail'] or ''}\n"
                )
        summaries.append(summarise(name, rows))
    (STORE / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
