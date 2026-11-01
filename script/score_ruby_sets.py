"""Score dev-A, dev2, the 52, and the 60 on the Ruby rail.

Abstain is off in the engine so the gated figure is kept. The shipped
disagreement rule is applied to those rows afterwards. Question text is
not stored.
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
]

os.environ["RUBYLIB"] = os.environ.get("RUBYLIB") or "vendor/vangrail/lib"
os.environ["GRUND_RAIL"] = "ruby"
os.environ["GRUND_ABSTAIN_RULE"] = "off"
os.environ["GRUND_E5_DIR"] = "data/models/small"
os.environ["GRUND_E5_SMALL_INDEX"] = "data/index-e5-small"
os.environ.pop("GRUND_CALIBRATE", None)
os.environ.pop("GRUND_RECALL", None)
os.environ.pop("GRUND_LEXICON", None)
os.environ.pop("GRUND_JUDGESIM", None)
os.environ.pop("GRUND_BIND2", None)
os.environ.pop("GRUND_BIND2_VETO", None)
os.environ.pop("GRUND_SUBJECT_CHECK", None)
os.environ.pop("GRUND_SUBJECT", None)
os.environ.pop("GRUND_RERANK", None)

ENV = (
    "GRUND_RAIL=ruby; GRUND_ABSTAIN_RULE=off (shipped disagree applied after); "
    "GRUND_CALIBRATE=unset; GRUND_RECALL=unset (fill); GRUND_LEXICON=unset (on); "
    "GRUND_RERANK=unset (on); GRUND_SUBJECT=unset (on); zero-count=on; GRUND_BIND2_VETO=unset; "
    "GRUND_E5=small; GRUND_E5_DIR=data/models/small; GRUND_E5_SMALL_INDEX=data/index-e5-small; "
    "GRUND_INDEX=data/index; vangrail=0.3.0"
)

STORE = Path("data/work/eval")
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
    ("org60", ROOT / "evalset" / "track3-questions.jsonl"),
    ("track3-52", Path("/tmp/track3-52-questions.jsonl")),
    ("diag-100", None),
    ("dev2", Path("data/work/eval/is-native-dev2.jsonl")),
    ("dev-A", Path("data/work/eval/dev-A.jsonl")),
]
LOG = Path("/tmp/ruby-sets.log")


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
        "path_pair": pair,
        "rail": "ruby",
        "env": ENV,
    }


def main() -> None:
    from grund.engine import Engine
    from grund_index.catalogue import Catalogue
    from grund_index.client import PxWebClient

    engine = Engine(
        Catalogue.load(ROOT / "data" / "index"),
        client=PxWebClient(cache_dir=ROOT / "data" / "cache", rate=4.0),
        planner="deterministic",
    )
    LOG.write_text("", encoding="utf-8")
    out_dir = STORE / "ruby-gates"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, path in SETS:
        rows = []
        questions = _diag() if name == "diag-100" else _load(path)
        dest = out_dir / f"{name}.jsonl"
        dest.write_text("", encoding="utf-8")
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
        print(f"{name} {len(rows)}", flush=True)


if __name__ == "__main__":
    main()
