"""Icelandic age coverage. Off unless ``GRUND_IS_COVER`` is set.

The hall turns it on. A national "N ára" population question then leads
with the population-by-age table. A municipality, a citizenship, or a
birthplace keeps the ordinary list.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_AGE = re.compile(r"\b(\d{1,3})\s+ara\b")
_POP = ("bjuggu", "bua", "ibua", "mannfjold", "fjoldi", "folk")
_NOT_PLACE = {"arid", "ari", "aldri", "aldrinum", "islandi", "island", "landinu", "landid"}
_EXCLUDE = (
    "sveitarfel",
    "rikisfang",
    "faeding",
    "hverf",
    "byggd",
    "innflytj",
    "manntal",
    "postnum",
    "landsvaed",
    "thjodskra",
)


def _flag(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() in {"1", "on", "true", "yes"}


def enabled() -> bool:
    """Off unless ``GRUND_IS_COVER`` or ``GRUND_RC2`` is 1, on, true, or yes.

    ``GRUND_IS_COVER`` is the agecover stack. ``GRUND_RC2`` is the same gate
    on the refusal-census tree. Either one is enough.
    """
    return _flag("GRUND_IS_COVER") or _flag("GRUND_RC2")


def _other_place(text: str) -> bool:
    for word in re.findall(r"\b(?:i|a)\s+([a-z]{4,})", text):
        if word not in _NOT_PLACE:
            return True
    return False


_BLOCK = ("og eldri", "og yngri", "prosent", "hlutfall", "haekk", "laekk", "breyt", "og hver", "nemend", "skolasokn")


def wants_national_age(question: str, language: str | None) -> bool:
    """Icelandic count of people at one year of age, with no other town named."""
    if language not in {None, "", "is"}:
        return False
    text = fold(question or "")
    if _AGE.search(text) is None:
        return False
    if not any(mark in text for mark in _POP):
        return False
    if any(mark in text for mark in _BLOCK):
        return False
    if _other_place(text):
        return False
    return True


def _national_age_table(catalogue):
    best = None
    best_span = -1
    for table in catalogue.tables:
        edition = table.edition("is") or table.edition("en")
        if edition is None:
            continue
        title = fold(edition.title or "")
        if "mannfjoldi" not in title or "aldr" not in title:
            continue
        if any(mark in title for mark in _EXCLUDE):
            continue
        years = list(getattr(edition, "years", lambda: [])())
        span = (max(years) - min(years)) if len(years) >= 2 else 0
        if span > best_span:
            best = table
            best_span = span
    return best


def _age_is_bound(table, question: str) -> bool:
    """True when the age variable binds to the year of age the question names."""
    from grund_lang.lemma import analyze
    from grund_lang.values import bind_values

    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return False
    match = _AGE.search(fold(question))
    if match is None:
        return False
    number = match.group(1)
    choices = bind_values(question, edition, analyze(question))
    for choice in choices:
        blob = fold(f"{choice.variable_code} {choice.variable_text}")
        if "aldur" not in blob and blob not in {"age"}:
            continue
        if "alls" in fold(choice.value_label) or choice.value_code in {"-1", "Total"}:
            return False
        numbers = re.findall(r"\d+", f"{choice.value_code} {choice.value_label}")
        if number in numbers:
            return True
    return False


def cover_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the ranker's age-specific cell. The hybrid total is a different statistic."""
    if not enabled() or not wants_national_age(question, language):
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if not _result_names_age(question, ranker):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_cover"] = True
    chosen["source"] = source
    return chosen


def _age_pairs(cell: dict) -> list[tuple[str, str, str]]:
    """(variable, code, label) from a source row or a claim cell."""
    found: list[tuple[str, str, str]] = []
    mapping = cell.get("map")
    if isinstance(mapping, dict):
        for key, value in mapping.items():
            found.append((str(key), str(value), str(value)))
    labels = cell.get("labels")
    if isinstance(labels, dict):
        for key, value in labels.items():
            found.append((str(key), str(value), str(value)))
    elif isinstance(labels, list):
        for item in labels:
            if not isinstance(item, dict):
                continue
            key = str(item.get("variable_text") or item.get("variable") or "")
            found.append((key, str(item.get("code") or ""), str(item.get("label") or "")))
    coords = cell.get("coords")
    if isinstance(coords, dict):
        for key, value in coords.items():
            found.append((str(key), str(value), str(value)))
    return found


def _result_names_age(question: str, result: dict) -> bool:
    match = _AGE.search(fold(question))
    if match is None:
        return False
    number = match.group(1)
    cells: list = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        for key, code, label in _age_pairs(cell):
            blob = fold(key)
            if "aldur" not in blob and blob != "age":
                continue
            shown = fold(f"{code} {label}")
            if "alls" in shown or code in {"-1", "Total"} or label in {"-1", "Total"}:
                return False
            numbers = set(re.findall(r"\d+", f"{code} {label}"))
            if numbers == {number}:
                return True
    return False


def apply_is_cover(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Move the national population-by-age table to the front, or leave the list."""
    if not enabled() or not wants_national_age(question, language):
        return hits
    table = _national_age_table(catalogue)
    if table is None or not _age_is_bound(table, question):
        return hits
    kept = [hit for hit in hits if hit.table.id != table.id]
    # The lead has to outscore every other hit. A later hit can outrank the
    # first, and the walker keeps the higher score.
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
