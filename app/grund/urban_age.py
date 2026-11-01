"""Refuse a national single year of age stated from an urbanisation split.

MAN03280 publishes the same age total as the overview table, under
"degree of urbanisation". A question that names one year of age and no
urbanisation is not that split. The flag only refuses. It does not choose
another table.

Off unless ``GRUND_URBAN_AGE`` is 1, on, true, or yes.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_EXACT_AGE = re.compile(
    r"\b(\d{1,3})\s*(?:ara|year-olds?|years old)\b"
)
_OPEN = re.compile(r"og eldri|og yngri|and older|and younger|or older|or younger")
_ASKED_SPLIT = re.compile(
    r"thettbyl|urbanis|degree of urban|urban nuclei|byggdakjarn"
)
_PLACE = re.compile(
    r"sveitarfelag|municipality|landshlut|by region|i reykjav|in reykjav|akureyr"
)


def enabled() -> bool:
    return os.environ.get("GRUND_URBAN_AGE", "").strip().lower() in {"1", "true", "yes", "on"}


def _stem(result: dict) -> str:
    return str(result.get("table_id") or "").removesuffix(".px")


def _title(result: dict) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    parts = [str(source.get("title") or "")]
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                parts.append(str(cell.get("title") or ""))
    return fold(" ".join(parts))


def refuse_reason(question: str, result: dict) -> str | None:
    """A short reason when a national year-of-age is cited from the urbanisation table."""
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return None
    text = fold(question or "")
    if _OPEN.search(text) or _ASKED_SPLIT.search(text) or _PLACE.search(text):
        return None
    if _EXACT_AGE.search(text) is None:
        return None
    title = _title(result)
    stem = _stem(result)
    urban = stem == "MAN03280" or "thettbyl" in title or "degree of urban" in title or "urbanisation" in title
    if not urban:
        return None
    return "urbanisation split is not the national age count"
