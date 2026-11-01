"""Look-alike handling after catalogue search.

The stage is on unless ``GRUND_RERANK=0``. It reorders a catalogue shortlist
when two tables are the same series. A historical copy loses to the current
series when both can answer the year. A percent table wins when the question
asks for a percent. A base year in the question keeps the table that publishes
that base. Period codes are what cover a year. A year printed only in the
title does not.

The language-index shortlist does not call this. On that list the same
reordering knocks gold tables off rank 1.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from grund_index.catalogue import Hit
from grund_index.model import Table
from grund_index.textutil import fold, tokens

_YEAR = re.compile(r"(?:1[6-9]|20)\d{2}")
_SPAN = re.compile(r"((?:1[6-9]|20)\d{2})\s*[-–—]\s*((?:1[6-9]|20)\d{2})")
_BASE = re.compile(
    r"(?:(?:1[6-9]|20)\d{2}\s*=\s*100)|(?:\b(?:base|grunnur|grunni|grunn)\s+(?:1[6-9]|20)\d{2}\b)"
)
_BASE_YEAR = re.compile(r"((?:1[6-9]|20)\d{2})")
_CHANGE = re.compile(r"\b(?:by what percent\w*|um hve \w* prosent\w*|prosentubreyting|percent change)\b")
_PERCENT_Q = re.compile(r"\b(?:percent(?:age)?|hlutfall\w*|hlutdeild\w*)\b")
_PERCENT_TITLE = re.compile(r"\b(?:percent(?:age)?|hlutfall\w*|hlutdeild\w*)\b")
_HISTORICAL_Q = re.compile(r"\b(?:historical|soguleg\w*)\b")


def rerank_enabled() -> bool:
    """Catalogue search uses the stage unless ``GRUND_RERANK=0``."""
    return os.environ.get("GRUND_RERANK", "1").strip() != "0"


def search_k() -> int:
    """Twenty candidates when the stage is on, otherwise the usual twelve."""
    return 20 if rerank_enabled() else 12


def maybe_rerank(catalogue, question: str, hits: list[Hit], years: list[int] | None = None) -> list[Hit]:
    """Reorder look-alike tables on a catalogue shortlist. ``GRUND_RERANK=0`` leaves ``hits``."""
    if not rerank_enabled() or not hits:
        return hits
    return lookalike_rerank(question, hits, years=years)


def _core(title: str) -> set[str]:
    text = _BASE.sub(" ", fold(title or ""))
    text = _YEAR.sub(" ", text)
    return {token for token in tokens(text, expand=False) if not token.isdigit()}


def _same_core(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    inter = len(left & right)
    union = len(left | right)
    if union and inter / union >= 0.72:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if shorter <= longer and len(shorter) >= 2 and len(longer - shorter) <= 4:
        return True
    return False


@dataclass
class _Fact:
    table: Table
    cores: dict[str, set[str]]
    actual: set[int]
    title_years: set[int]
    span: tuple[int, int] | None
    mentioned: set[int]
    historical: bool
    percent_title: bool


def _fact(table: Table) -> _Fact:
    titles = [edition.title for edition in table.editions.values()]
    span, title_years = _title_years(titles)
    cores = {"is": set(), "en": set()}
    for lang, edition in table.editions.items():
        cores[lang] = _core(edition.title)
    mentioned: set[int] = set(title_years)
    for edition in table.editions.values():
        for match in _YEAR.findall(_BASE.sub(" ", edition.title or "")):
            mentioned.add(int(match))
    blob = " ".join(fold(edition.title or "") for edition in table.editions.values())
    historical = False
    for edition in table.editions.values():
        path = fold(" ".join([edition.db, *edition.path_texts]))
        if "soguleg" in path or "historical" in path:
            historical = True
    actual: set[int] = set()
    for edition in table.editions.values():
        actual |= edition.years()
    return _Fact(
        table=table,
        cores=cores,
        actual=actual,
        title_years=title_years,
        span=span,
        mentioned=mentioned,
        historical=historical,
        percent_title=_PERCENT_TITLE.search(blob) is not None,
    )


def _title_years(titles: list[str]) -> tuple[tuple[int, int] | None, set[int]]:
    years: set[int] = set()
    span: tuple[int, int] | None = None
    for title in titles:
        cleaned = _BASE.sub(" ", title or "")
        spans = [(int(start), int(end)) for start, end in _SPAN.findall(cleaned)]
        if spans:
            start, end = max(spans, key=lambda item: item[1] - item[0])
            if 0 <= end - start <= 500:
                years.update(range(start, end + 1))
                if span is None or (end - start) > (span[1] - span[0]):
                    span = (start, end)
            continue
        for match in _YEAR.findall(cleaned):
            years.add(int(match))
    return span, years


def same_series(left: _Fact, right: _Fact) -> bool:
    """True when the titles are one series, compared in each language."""
    pairs: list[tuple[set[str], set[str]]] = []
    for lang in ("is", "en"):
        if left.cores.get(lang) and right.cores.get(lang):
            pairs.append((left.cores[lang], right.cores[lang]))
    if not pairs:
        one = left.cores.get("is") or left.cores.get("en") or set()
        other = right.cores.get("is") or right.cores.get("en") or set()
        pairs.append((one, other))
    return any(_same_core(one, other) for one, other in pairs)


def _covers(fact: _Fact, year: int) -> bool:
    """A year the codes contain. Title years count only when the codes are empty."""
    if fact.actual:
        return year in fact.actual
    if fact.title_years:
        return year in fact.title_years
    return True


def _required_years(question: str, years: list[int] | None) -> set[int]:
    asked = {int(match) for match in _YEAR.findall(question)}
    if years:
        asked.update(int(year) for year in years)
    bases: set[int] = set()
    for match in _BASE.finditer(fold(question)):
        for year in _BASE_YEAR.findall(match.group(0)):
            bases.add(int(year))
    return asked - bases


def _base_years(question: str) -> set[int]:
    found: set[int] = set()
    for match in _BASE.finditer(fold(question)):
        for year in _BASE_YEAR.findall(match.group(0)):
            found.add(int(year))
    return found


def _wants_percent(question: str) -> bool:
    folded = fold(question)
    if _CHANGE.search(folded):
        return False
    return _PERCENT_Q.search(folded) is not None


def _holds_base(fact: _Fact, year: int) -> bool:
    if year in fact.mentioned or year in fact.title_years:
        return True
    return fact.span is not None and fact.span[0] <= year <= fact.span[1]


def _groups(facts: list[_Fact]) -> list[list[int]]:
    parent = list(range(len(facts)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(facts)):
        for right in range(left + 1, len(facts)):
            if same_series(facts[left], facts[right]):
                parent[find(left)] = find(right)
    buckets: dict[int, list[int]] = {}
    for index in range(len(facts)):
        buckets.setdefault(find(index), []).append(index)
    return list(buckets.values())


def _only_historical_covers(historical: list[int], current: list[int], facts: list[_Fact], required: set[int]) -> bool:
    """True when every asked year is in the Sögulegar copy and not in the current series."""
    if not required:
        return False

    def covers(indexes: list[int]) -> bool:
        return all(any(_covers(facts[index], year) for index in indexes) for year in required)

    return covers(historical) and not covers(current)


def _closed_historical_copy(historical: list[int], current: list[int], facts: list[_Fact], required: set[int]) -> bool:
    """The historical series stops, and the question is inside that closed span.

    Ferry passengers through 2017 live in the Sögulegar table that ends in 2017.
    The current table continues to 2023. A later year stays on the current table.
    """
    if not required:
        return False
    hist_ends = [facts[index].span[1] for index in historical if facts[index].span]
    cur_ends = [facts[index].span[1] for index in current if facts[index].span]
    if not hist_ends or not cur_ends:
        return False
    hist_end = max(hist_ends)
    if max(cur_ends) <= hist_end:
        return False
    if any(year > hist_end for year in required):
        return False
    return all(any(_covers(facts[index], year) for index in historical) for year in required)


def _winner(members: list[int], facts: list[_Fact], question: str, required: set[int]) -> int:
    """The member that should stand first inside one look-alike group."""

    def covers(index: int) -> bool:
        if not required:
            return True
        return all(_covers(facts[index], year) for year in required)

    pool = [index for index in members if covers(index)] or list(members)
    bases = _base_years(question)
    if bases:
        holders = [index for index in pool if all(_holds_base(facts[index], year) for year in bases)]
        if holders:
            pool = holders
    if _wants_percent(question):
        marked = [index for index in pool if facts[index].percent_title]
        if marked:
            pool = marked
    historical = [index for index in pool if facts[index].historical]
    current = [index for index in pool if not facts[index].historical]
    folded = fold(question)
    if _HISTORICAL_Q.search(folded) and historical:
        pool = historical
    elif historical and current and _only_historical_covers(historical, current, facts, required):
        pool = historical
    elif historical and current and _closed_historical_copy(historical, current, facts, required):
        pool = historical
    elif _HISTORICAL_Q.search(folded) is None and current:
        pool = current
    return min(pool)


def lookalike_rerank(question: str, hits: list[Hit], years: list[int] | None = None, k: int = 12) -> list[Hit]:
    """Move the preferred look-alike to the front of its group. Other ranks stay."""
    if len(hits) < 2:
        return list(hits)
    window = list(hits[:20])
    facts = [_fact(hit.table) for hit in window]
    required = _required_years(question, years)
    order = list(range(len(window)))
    for group in _groups(facts):
        if len(group) < 2:
            continue
        winner = _winner(group, facts, question, required)
        member_set = set(group)
        first = next(index for index in order if index in member_set)
        if first == winner:
            continue
        rebuilt: list[int] = []
        placed = False
        for index in order:
            if index not in member_set:
                rebuilt.append(index)
                continue
            if not placed:
                rebuilt.append(winner)
                placed = True
            if index != winner:
                rebuilt.append(index)
        order = rebuilt
    ranked = [window[index] for index in order]
    # Keep tables past the window, then cut. Scores follow the new order so a
    # later binder sort does not put the look-alike back.
    tail = list(hits[20:])
    chosen = (ranked + tail)[:k]
    copied: list[Hit] = []
    for place, hit in enumerate(chosen):
        copied.append(
            Hit(
                table=hit.table,
                score=5.0 - place * 0.2,
                bm25=hit.bm25,
                cosine=hit.cosine,
                value_boost=hit.value_boost,
            )
        )
    return copied
