"""Keep a bare topic question off a breakdown table.

Retrieval may rank "population by country of birth" above "population, key
figures". The question did not name a birthplace, a municipality, or a
component. Those titles wait behind a table that only names the topic.
"""

from __future__ import annotations

import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

# Phrases that name a split. They do not count when the question already says them.
_BREAKDOWN = (
    "country of birth",
    "born abroad",
    "faedd erlend",
    "citizenship",
    "rikisfang",
    "by origin",
    "uppruni",
    "immigrant",
    "innflytj",
    "projection",
    "mannfjoldaspa",
    "overestimation",
    "change of method",
    "census",
    "manntal",
    "fertility",
    "frjosemi",
    "component",
    "forecast",
    "purchasing power",
    "local government",
    "foreign debt",
    "aquaculture",
    "tourism expenditure",
    "tourism consumption",
    "share of gdp",
    "financial assets",
    "hotel",
    "gistiheimil",
    "guesthouse",
    "camping",
    "husnaed",
    "excluding housing",
    "samraemd",
    "harmonised",
    "harmonized",
    "edli og uppruna",
    "nature and origin",
    "1914",
    "yfirvinna",
    "overtime",
    "kennslu",
    "grunnskol",
    "per capita",
    "election",
    "kosning",
    "ozone",
    "women and men",
    "konur og karlar",
)

# A folder named municipalities is not a breakdown when the question names a
# town that the title also names. "By municipality" with no town still is.
_PLACE_SPLIT = ("municipality", "municipalities", "sveitarfelag")

_CURRENCY = {
    "dollar": "usd",
    "dalur": "usd",
    "euro": "eur",
    "pound": "gbp",
}


def _blob(hit: Hit) -> str:
    parts: list[str] = []
    for edition in hit.table.editions.values():
        parts.append(edition.title or "")
        parts.append(edition.db or "")
        parts.extend(edition.path_texts or [])
    return fold(" ".join(parts))


def _content_count(hit: Hit) -> int:
    counts = []
    for edition in hit.table.editions.values():
        words = [word for word in fold(edition.title or "").split() if len(word) > 3 and not word.isdigit()]
        counts.append(len(words))
    return min(counts) if counts else 0


def is_breakdown(hit: Hit, question: str) -> bool:
    text = _blob(hit)
    asked = fold(question)
    if any(word in asked for word in ("landsframleidsl", "gdp", "gross domestic")) and not any(
        word in asked for word in ("a mann", "per capita", "per person")
    ):
        if "a mann" in text or "per capita" in text:
            return True
    if "innanlands" in text and ("til landsins" in asked or "to the country" in asked):
        return True
    if re.search(r"\b1\s*\.?\s*jan", asked) and not any(word in asked for word in ("gistin", "gestakom", "overnight")):
        if any(word in text for word in ("gistin", "gestakom", "overnight", "hotel")):
            return True
    if any(phrase in text and phrase not in asked for phrase in _BREAKDOWN):
        return True
    titles = fold(" ".join(edition.title or "" for edition in hit.table.editions.values()))
    # "by municipalities" in the title is a split. The folder name alone is not,
    # when the question names a town that the title also names.
    if "municipalit" in titles and "municipalit" not in asked:
        return True
    if "sveitarfel" in titles and "sveitarfel" not in asked:
        return True
    words = [word for word in re.sub(r"[^a-z0-9]+", " ", asked).split() if word]
    named_place = any(len(word) >= 8 and word in titles for word in words)
    if named_place:
        return False
    return any(phrase in text and phrase not in asked for phrase in _PLACE_SPLIT)


def prefer_headline(hits: list[Hit], question: str) -> list[Hit]:
    """Stable partition: headline tables first, then breakdowns."""
    if len(hits) < 2:
        return hits
    asked = fold(question)
    plain = [hit for hit in hits if not is_breakdown(hit, question)]
    broken = [hit for hit in hits if is_breakdown(hit, question)]
    # A one-word title such as "Population" is not the key-figures series
    # when a longer title in the same list also names that word.
    if any(_content_count(hit) >= 3 for hit in plain):
        longer = []
        short = []
        for hit in plain:
            if _content_count(hit) <= 1:
                short.append(hit)
            else:
                longer.append(hit)
        if longer:
            plain = longer + short
    for word, code in _CURRENCY.items():
        if word in asked or code in asked:
            named = [hit for hit in plain if code in _blob(hit) or word in _blob(hit)]
            other = [hit for hit in plain if hit not in named]
            if named:
                plain = named + other
            break
    if not plain:
        return hits
    try:
        from grund_rails.cell_claim import _question_places
    except Exception:
        _question_places = lambda _question: []
    if _question_places(question):
        def _local(hit: Hit) -> bool:
            blob = _blob(hit)
            return ("sveitarfel" in blob or "municipalit" in blob) and (
                "mannfjold" in blob or "population" in blob
            )
        local = [hit for hit in plain + broken if _local(hit)]
        rest = [hit for hit in plain + broken if hit not in local]
        if local:
            return local + rest
    return plain + broken
