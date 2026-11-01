"""Recall of the gold table, measured and not used to fit the ranker.

A question is scored from the `table` field of each part. The wider
`accepted` list is ignored. Recall at k is the share of those gold table
ids that sit in the top k, averaged over questions. Primary hit at k is
the share of questions whose first gold table is in the top k. That hit
rate is a proportion, so it carries a Wilson 95% interval.
"""

from __future__ import annotations

import math
import json
from collections import defaultdict
from pathlib import Path

from grund_lang.index import RetrievalIndex
from grund_lang.lemma import detect_language

_KS = (1, 5, 10)
_SETS = (
    ("track3", "evalset/track3-questions.jsonl"),
    ("heldout40", "evalset/heldout40.jsonl"),
    ("heldout2", "evalset/heldout2.jsonl"),
)


def gold_tables(row: dict) -> list[str]:
    found: list[str] = []
    for part in row.get("parts") or []:
        table = str(part.get("table") or "")
        if table.endswith(".px"):
            table = table[:-3]
        if table and table not in found:
            found.append(table)
    return found


def recall_at(ranked: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 0.0
    top = set(ranked[:k])
    return sum(1 for table in gold if table in top) / len(gold)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson interval. None when n is 0. Same formula as the eval harness."""
    if n <= 0:
        return None
    proportion = successes / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = (proportion + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / n + z2 / (4 * n * n)) / denominator
    low = 0.0 if successes == 0 else max(0.0, centre - margin)
    high = 1.0 if successes == n else min(1.0, centre + margin)
    return (low, high)


def _blank() -> dict:
    return {
        "n": 0,
        "recall": {k: 0.0 for k in _KS},
        "primary_hit": {k: 0.0 for k in _KS},
        "primary_successes": {k: 0 for k in _KS},
    }


def _add(bucket: dict, ranked: list[str], gold: list[str]) -> None:
    bucket["n"] += 1
    primary = gold[0]
    for k in _KS:
        bucket["recall"][k] += recall_at(ranked, gold, k)
        hit = 1.0 if primary in ranked[:k] else 0.0
        bucket["primary_hit"][k] += hit
        bucket["primary_successes"][k] += int(hit)


def _finish(bucket: dict) -> dict:
    n = bucket["n"] or 1
    return {
        "n": bucket["n"],
        "recall": {str(k): bucket["recall"][k] / n for k in _KS},
        "primary_hit": {str(k): bucket["primary_hit"][k] / n for k in _KS},
        "primary_wilson95": {
            str(k): list(wilson(bucket["primary_successes"][k], bucket["n"]) or [])
            for k in _KS
        },
    }


def score_file(index: RetrievalIndex, path: Path, k: int = 10) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    overall = _blank()
    by_language: dict[str, dict] = defaultdict(_blank)
    by_tier: dict[str, dict] = defaultdict(_blank)
    by_tier_language: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_blank))
    misses = []
    for row in rows:
        gold = gold_tables(row)
        if not gold:
            continue
        language = row.get("language") or detect_language(row.get("question") or "")
        tier = str(row.get("tier") or row.get("level") or "none")
        ranked = [candidate.table_id for candidate in index.search(row["question"], k=max(k, 10))]
        _add(overall, ranked, gold)
        _add(by_language[language], ranked, gold)
        _add(by_tier[tier], ranked, gold)
        _add(by_tier_language[tier][language], ranked, gold)
        if gold[0] not in ranked[:10]:
            misses.append({"id": row.get("id"), "language": language, "tier": tier, "gold": gold, "top": ranked[:5]})
    return {
        "file": path.name,
        "overall": _finish(overall),
        "by_language": {language: _finish(bucket) for language, bucket in sorted(by_language.items())},
        "by_tier": {
            tier: {
                "all": _finish(bucket),
                "by_language": {
                    language: _finish(inner)
                    for language, inner in sorted(by_tier_language[tier].items())
                },
            }
            for tier, bucket in sorted(by_tier.items())
        },
        "primary_misses_at_10": misses,
    }


def score_root(index: RetrievalIndex, root: Path) -> dict:
    report = {}
    for name, relative in _SETS:
        path = root / relative
        if not path.exists():
            report[name] = {"missing": str(path)}
            continue
        report[name] = score_file(index, path)
    return report
