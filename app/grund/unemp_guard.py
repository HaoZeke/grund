"""Refuse a labour-force cell whose unit or age is not the one asked.

``GRUND_UNEMP_GUARD`` is off unless set. It does not pick another cell.
It applies to every ``VIN`` table, not to one id.

A count marker together with a rate unit is refused, and a rate marker
together with a count unit is refused. A named age band other than 16–74
is refused when the stated age is 16–74 or Total.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_SPAN = re.compile(r"\b(\d{1,2})\s*(?:to|til|-|–|—)\s*(\d{1,2})\b")
_AGE_KEY = re.compile(r"aldur|\bage\b")
_UNIT_KEY = re.compile(r"eining|\bunit\b|hlutfall|\brate\b|percent|prosent")
_TWO = ("and what", "og hver", "og hvert", "og hvad")


def enabled() -> bool:
    return os.environ.get("GRUND_UNEMP_GUARD", "").strip().lower() in {"1", "on", "true", "yes"}


def reason(question: str, result: dict) -> str | None:
    """Why this stated VIN cell should be refused, or None to keep it."""
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return None
    text = fold(question or "")
    if any(mark in text for mark in _TWO):
        return None
    stem, ages, units = _parts(result)
    if not stem.startswith("VIN"):
        return None
    unit = " ".join(units)
    if _asks_count(text) and _rate_unit(unit):
        return "count marker on a rate unit"
    if _asks_rate(text) and _count_unit(unit):
        return "rate marker on a count unit"
    if _other_band(text) and any(_default_age(label) for label in ages):
        return "named age is not 16-74"
    return None


def _asks_count(text: str) -> bool:
    """Headcount wording. ``hve marg`` / ``how many`` inside a percent question is not a headcount."""
    if "headcount" in text or "number of" in text:
        return True
    if re.search(r"\bfjold", text) or re.search(r"\batvinnulausir\b", text):
        return True
    how_many = "how many" in text or "hve marg" in text or "hversu marg" in text
    if not how_many:
        return False
    percentish = (
        "hlutfall" in text
        or "%" in text
        or "prosent" in text
        or re.search(r"\brate\b", text) is not None
        or re.search(r"\bpercent", text) is not None
    )
    return not percentish


def _asks_rate(text: str) -> bool:
    # ``hlutfall`` as its own word. ``hlutfallsleg`` is a distribution, not this marker.
    if re.search(r"\bhlutfall(?:id|i|s)?\b", text) or "%" in text:
        return True
    return re.search(r"\brate\b", text) is not None


def _rate_unit(unit: str) -> bool:
    if not unit:
        return False
    if "%" in unit or "hlutfall" in unit or "atvinnuleysi" in unit:
        return True
    return re.search(r"\brate\b", unit) is not None


def _count_unit(unit: str) -> bool:
    if not unit or _rate_unit(unit):
        return False
    if any(mark in unit for mark in ("atvinnulausir", "fjoldi", "headcount", "estimated number", "starfandi", "mannfjoldi")):
        return True
    return re.search(r"\b(number|persons|employed|unemployed|labour force)\b", unit) is not None


def _spans(text: str) -> list[tuple[int, int]]:
    return [(int(left), int(right)) for left, right in _SPAN.findall(text or "")]


def _other_band(text: str) -> bool:
    return any(pair != (16, 74) for pair in _spans(text))


def _default_age(label: str) -> bool:
    folded = fold(label or "")
    if folded in {"total", "alls", "all", "samtals"}:
        return True
    spans = _spans(folded)
    return bool(spans) and all(pair == (16, 74) for pair in spans)


def _parts(result: dict) -> tuple[str, list[str], list[str]]:
    stem = str(result.get("table_id") or "").split("#", 1)[0].removesuffix(".px")
    ages: list[str] = []
    units: list[str] = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells = list(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if not stem and cell.get("table_id"):
            stem = str(cell.get("table_id")).split("#", 1)[0].removesuffix(".px")
        for key, value in _label_pairs(cell.get("labels")):
            if _AGE_KEY.search(key):
                ages.append(value)
            elif _UNIT_KEY.search(key):
                units.append(value)
    return stem.upper(), ages, [fold(value) for value in units]


def _label_pairs(raw) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        pairs.extend((fold(str(key)), str(value)) for key, value in raw.items())
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("variable") or item.get("code") or item.get("name") or "")
            value = str(item.get("label") or item.get("value") or "")
            pairs.append((fold(key), value))
    return pairs
