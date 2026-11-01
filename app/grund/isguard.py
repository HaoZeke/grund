"""A kang gate states a figure only when the question's measure matches the table.

``GRUND_IS_KANG_GUARD`` is off unless it is ``1``, ``true``, ``yes``, or ``on``.
When it is on, the counted noun is lemmatized. Deaths, marriages, hotel beds,
and emigrants do not match a population table. GDP of one landshluti does not
match the national accounts total. A question whose measure is the table's
measure is left alone, and so is a question that names no other measure.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_DEATHS = {
    "dainn", "deyja", "death", "die", "dead", "died", "dies", "dying",
    "daudi", "andvana", "fetal",
    # "létust" lemmatises to the broad verb láta. The surface is the death.
    "letust", "letst", "latist",
}
_MARRIAGES = {"hjonavigsla", "marriage", "marriages", "wedding", "weddings"}
_BEDS = {"gistirymi", "gistiryma", "rum", "bed", "beds"}
_EMIGRANTS = {"brottfluttur", "emigrant", "emigrants", "emigration"}
_DENY = {
    "deaths": _DEATHS,
    "marriages": _MARRIAGES,
    "beds": _BEDS,
    "emigrants": _EMIGRANTS,
}
_SKIP = {
    "of", "the", "a", "an", "on", "in", "at", "there", "how", "many",
    "hve", "hversu", "hvad", "og", "eda", "sem", "to", "for",
}
_STOP = {"vera", "be", "do", "have", "hafa", "bua", "live", "spend", "verda"}
_REGION_STEMS = (
    "landshlut",
    "hofudborgarsvaed",
    "sudurnes",
    "vesturland",
    "vestfird",
    "vestfjard",
    "vestfjord",
    "nordurland",
    "austurland",
    "sudurland",
    "westfjord",
    "northwest",
    "northeast",
    "southwest",
    "capital region",
)
_POPULATION = {
    "MAN00000", "MAN00101", "MAN00110", "MAN02001", "MAN02005", "MAN02007",
    "MAN03108", "MAN03200", "MAN03250", "MAN03260", "MAN03270", "MAN03280",
    "MAN04103", "MAN04203", "MAN04208", "MAN12103", "MAN12104", "MAN43000",
}
_DEATH_TABLES = {"MAN05210", "MAN05220", "MAN05221", "MAN05200"}
_MARRIAGE_TABLES = {"MAN06100", "MAN06101", "MAN06102", "MAN06103", "MAN06104", "MAN06105"}
_BED_TABLES = {"SAM01200", "SAM01201", "SAM01202", "SAM01203"}
_EMIGRANT_TABLES = {"MAN01400", "MAN01401", "MAN01402", "MAN01403", "MAN01404", "MAN01405"}
_GDP_TABLES = {"THJ01102", "THJ01103"}


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_GUARD", "").strip().lower() in {"1", "true", "yes", "on"}


def _family(lemma: str, surface: str) -> str | None:
    for name, words in _DENY.items():
        if lemma in words or surface in words:
            return name
    return None


def _phrase_families(tokens) -> set[str]:
    """Measure nouns in the counted phrase, including a death verb such as dóu."""
    found: set[str] = set()
    for tok in tokens:
        lemma = fold(tok.lemma or "")
        surface = fold(tok.surface or "")
        family = _family(lemma, surface)
        if family:
            found.add(family)
            if tok.pos == "verb" or lemma in {"deyja", "die"}:
                break
            continue
        if lemma in _SKIP or surface in _SKIP:
            continue
        if tok.pos in {"verb", "adp"} or lemma in _STOP or surface in _STOP:
            break
    return found


def _families_in(tokens) -> set[str]:
    found: set[str] = set()
    for tok in tokens:
        family = _family(fold(tok.lemma or ""), fold(tok.surface or ""))
        if family:
            found.add(family)
    return found


def _immigrants_too(tokens) -> bool:
    for tok in tokens:
        lemma = fold(tok.lemma or "")
        surface = fold(tok.surface or "")
        if lemma in {"adfluttur", "innflytjandi"} or surface in {"immigrant", "immigrants", "adfluttir", "adfluttar"}:
            return True
    return False


def counted_denies(question: str) -> set[str]:
    """Deny-list measures that are the noun being counted, not a later aside."""
    from grund_lang.lemma import analyze

    tokens = list(analyze(question or "").tokens)
    found: set[str] = set()
    for index, tok in enumerate(tokens):
        lemma = fold(tok.lemma or "")
        surface = fold(tok.surface or "")
        if lemma != "margur" and surface != "many":
            continue
        after = _phrase_families(tokens[index + 1 :])
        if after:
            found |= after
        else:
            found |= _families_in(tokens[:index])
    if "emigrants" in found and _immigrants_too(tokens):
        found.discard("emigrants")
    return found


def asks_regional_gdp(question: str) -> bool:
    """National-accounts GDP named together with one landshluti."""
    text = fold(question or "")
    names = (
        "landsframleid" in text
        or re.search(r"\bvlf\b", text) is not None
        or re.search(r"\bgdp\b", text) is not None
        or re.search(r"gross\s+domes\w*\s+product", text) is not None
    )
    if not names:
        return False
    if any(stem in text for stem in _REGION_STEMS):
        return True
    return re.search(r"\b(east|west|south)\b", text) is not None


def _stem(result: dict) -> str:
    return str(result.get("table_id") or "").split("#", 1)[0].removesuffix(".px")


def table_family(result: dict) -> str | None:
    stem = _stem(result)
    if stem in _POPULATION:
        return "population"
    if stem in _DEATH_TABLES:
        return "deaths"
    if stem in _MARRIAGE_TABLES:
        return "marriages"
    if stem in _BED_TABLES:
        return "beds"
    if stem in _EMIGRANT_TABLES:
        return "emigrants"
    if stem in _GDP_TABLES:
        return "gdp"
    return None


def blocks_population(question: str) -> bool:
    """The counted noun is some other measure, so the population gate stays quiet."""
    if not enabled():
        return False
    return bool(counted_denies(question))


def blocks_national_gdp(question: str) -> bool:
    if not enabled():
        return False
    return asks_regional_gdp(question)


def guard_reason(question: str, result: dict) -> str | None:
    """Refuse a population table for another measure, and national GDP for a region."""
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return None
    denies = counted_denies(question)
    regional = asks_regional_gdp(question)
    if not denies and not regional:
        return None
    family = table_family(result)
    if regional and family in {"gdp", "population"}:
        return "landshluti GDP is not the national total"
    if denies and family == "population":
        return "question measure does not match the table"
    if denies and family is not None and family not in denies:
        return "question measure does not match the table"
    return None
