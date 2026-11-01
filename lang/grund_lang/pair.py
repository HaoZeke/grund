"""Two tables for a comparison question.

Hard questions ask for two series. Both gold tables sit in the top 5 of the
whole question. Each half of the question picks a different table from that
pool. ``retrieve`` is unchanged.
"""

from __future__ import annotations

from grund_lang.index import RetrievalIndex, _clauses
from grund_lang.types import Candidate

_MISSING = 10**6


def question_halves(question: str) -> list[str] | None:
    """The two questions inside a comparison, or None when it is one question."""
    try:
        from grund.compound import split_question
    except ImportError:
        split_question = None
    if split_question is not None:
        split = split_question(question)
        if split is not None:
            return [split[1], split[2]]
    parts = _clauses(question)
    if len(parts) >= 2:
        return parts[:2]
    return None


def choose_pair(
    joint: list[Candidate],
    left: list[Candidate],
    right: list[Candidate],
    hits=None,
    detail=None,
) -> list[Candidate]:
    """Assign two different tables from ``joint`` to the two halves.

    ``hits(side, table_id)`` is how many title words that half already uses.
    ``detail(table_id)`` is ``(token_count, coverage_end, historical)``.
    When the half's top table shares no surface token with that half, the
    ranker is kept: overlap cannot see a title it does not literally contain.
    Otherwise the pool table with the most shared title words wins.
    """
    if not joint:
        return []
    if len(joint) == 1:
        return [joint[0]]
    left_rank = {candidate.table_id: index for index, candidate in enumerate(left)}
    right_rank = {candidate.table_id: index for index, candidate in enumerate(right)}

    def hit(side: int, table_id: str) -> int:
        if hits is None:
            return 0
        return int(hits(side, table_id))

    def meta(table_id: str) -> tuple[int, int, bool]:
        if detail is None:
            return 2, 0, False
        tokens, end, historical = detail(table_id)
        return int(tokens), int(end or 0), bool(historical)

    def pick(ranked: list[Candidate], side: int, banned: set[str]) -> Candidate | None:
        in_pool = [candidate for candidate in ranked if candidate.table_id in pool and candidate.table_id not in banned]
        if not in_pool:
            in_pool = [candidate for candidate in joint if candidate.table_id not in banned]
        if not in_pool:
            return None
        top = in_pool[0]
        tokens, _end, _historical = meta(top.table_id)
        # Title overlap is blind when the wording and the title do not share
        # a surface token. The half's own rank already used the lemmas.
        if hit(side, top.table_id) == 0 and tokens >= 2:
            return top
        return max(
            in_pool,
            key=lambda candidate: (
                hit(side, candidate.table_id),
                -left_rank.get(candidate.table_id, _MISSING) if side == 0 else -right_rank.get(candidate.table_id, _MISSING),
            ),
        )

    pool = {candidate.table_id for candidate in joint}
    left_choice = pick(left, 0, set())
    right_choice = pick(right, 1, {left_choice.table_id} if left_choice else set())
    return [candidate for candidate in (left_choice, right_choice) if candidate is not None]


def score_hard_pairs(index: RetrievalIndex, path) -> dict:
    """Both-table hit rate on hard questions only. No question text is kept."""
    import json
    from collections import Counter
    from pathlib import Path

    from grund_lang.eval_recall import gold_tables, wilson

    by_language: dict[str, Counter] = {}
    hits = 0
    ordered = 0
    pooled = 0
    n = 0
    misses: list[str] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("level") != "hard":
                continue
            gold = gold_tables(row)
            if len(gold) != 2:
                continue
            n += 1
            language = row.get("language") or "?"
            bucket = by_language.setdefault(language, Counter())
            pool = [candidate.table_id for candidate in index.search(row["question"], k=5)]
            in_pool = set(gold) <= set(pool)
            pooled += int(in_pool)
            bucket["pool"] += int(in_pool)
            found = [candidate.table_id for candidate in retrieve_pair(index, row["question"])]
            both = set(gold) == set(found)
            same_order = found == gold
            bucket["n"] += 1
            bucket["both"] += int(both)
            bucket["ordered"] += int(same_order)
            hits += int(both)
            ordered += int(same_order)
            if not both:
                misses.append(str(row.get("id") or n))
    languages = {}
    for language, bucket in sorted(by_language.items()):
        count = int(bucket["n"])
        languages[language] = {
            "n": count,
            "both": int(bucket["both"]),
            "ordered": int(bucket["ordered"]),
            "pool": int(bucket["pool"]),
            "both_rate": (bucket["both"] / count) if count else 0.0,
            "wilson95": list(wilson(int(bucket["both"]), count) or []),
        }
    return {
        "file": Path(path).name,
        "level": "hard",
        "n": n,
        "both": hits,
        "ordered": ordered,
        "pool": pooled,
        "both_rate": (hits / n) if n else 0.0,
        "wilson95": list(wilson(hits, n) or []),
        "by_language": languages,
        "miss_ids": misses,
    }


def retrieve_pair(index: RetrievalIndex, question: str, k: int = 5) -> list[Candidate]:
    """The two tables a comparison needs, one for each half of the question.

    ``k`` is the pool taken from the whole question. Five is enough: on the
    dev comparisons both tables are inside that pool.
    """
    halves = question_halves(question)
    joint = index.search(question, k=k)
    if not halves:
        return []
    width = max(k, 10)
    left = index._search_one(halves[0], width)
    right = index._search_one(halves[1], width)
    hits, detail = _title_profile(index, halves)
    return choose_pair(joint, left, right, hits=hits, detail=detail)


def _title_profile(index: RetrievalIndex, halves: list[str]):
    """Title overlap, length, coverage end, and whether the path is an older copy."""
    from grund_lang.index import (
        _content_tokens,
        _coverage_end,
        _known_years,
        _older_series,
        _title_tokens,
        _token_covered,
        _years,
    )

    terms = [_content_tokens(half) for half in halves]
    cache: dict[str, tuple[int, int, int, bool]] = {}

    def profile(table_id: str) -> tuple[int, int, int, bool]:
        if table_id in cache:
            return cache[table_id]
        table = index.by_key.get(table_id)
        if table is None:
            cache[table_id] = (0, 0, 0, False)
            return cache[table_id]
        best_len = 0
        for edition in table.editions.values():
            tokens = _title_tokens(edition.title or "")
            best_len = max(best_len, len(tokens))
        published = _years(table)
        covered_years = _known_years(table, published)
        end = _coverage_end(covered_years, published) or 0
        cache[table_id] = (0, best_len, end, _older_series(table))
        return cache[table_id]

    def hits(side: int, table_id: str) -> int:
        table = index.by_key.get(table_id)
        if table is None:
            return 0
        best = 0
        for edition in table.editions.values():
            tokens = _title_tokens(edition.title or "")
            covered = sum(1 for token in tokens if _token_covered(token, terms[side]))
            best = max(best, covered)
        return best

    def detail(table_id: str):
        _covered, length, end, historical = profile(table_id)
        return length, end, historical

    return hits, detail
