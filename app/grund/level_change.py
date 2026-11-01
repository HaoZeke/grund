"""Refuse a level cell when the question asks for a change, and the reverse.

``GRUND_LEVEL_CHANGE_VETO`` is off unless it is set. A percent, a rate, and
a headcount are levels. A change is a rise, a fall, a difference, or the
published change column. Anything the wording does not settle is left alone.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_CHANGE_OP = frozenset({"yoy_pct", "pct_change", "change", "difference"})
_CHANGE_WORD = re.compile(
    r"\b(?:change|changed|changes|increase|increased|decrease|decreased|"
    r"rise|rising|rose|risen|fall|falling|fell|fallen|growth|grew|difference|"
    r"breyting\w*|haekk\w*|laekk\w*|jokst|faekk\w*|munur)\b"
)
_YEAR_SPAN = re.compile(
    r"\b(?:from|fra)\s+(?:19|20)\d{2}\b.{0,30}\b(?:to|til)\s+(?:19|20)\d{2}\b"
)
_LEVEL_WORD = re.compile(
    r"\b(?:how many|what was|what is|how much was|hversu marg\w*|hve marg\w*|"
    r"hvad var|hvar stod|stood)\b"
)
_CHANGE_CELL = ("annual change", "monthly change", "change", "breyting", "arsbreyt", "manadarbreyting")


def enabled() -> bool:
    return os.environ.get("GRUND_LEVEL_CHANGE_VETO", "").strip().lower() in {"1", "on", "true", "yes"}


def asked(question: str) -> str | None:
    """``change`` or ``level`` when the wording settles it."""
    text = fold(question or "")
    if _CHANGE_WORD.search(text) or _YEAR_SPAN.search(text) or "percentage point" in text or "prosentustig" in text:
        return "change"
    if _LEVEL_WORD.search(text):
        return "level"
    return None


def stated(result: dict) -> str | None:
    """``change`` or ``level`` for the cell that was stated."""
    if result.get("refused") or result.get("value") in (None, ""):
        return None
    operation = str(result.get("operation") or "").lower()
    if operation in _CHANGE_OP:
        return "change"
    blob = _cell_blob(result)
    if any(mark in blob for mark in _CHANGE_CELL):
        return "change"
    if operation in {"", "level", "share", "share_percent"}:
        return "level"
    return None


def _cell_blob(result: dict) -> str:
    parts: list[str] = []
    blobs = []
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            blobs.extend(claim.get("cells") or [])
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    blobs.extend(source.get("cells") or [])
    for cell in blobs:
        if not isinstance(cell, dict):
            continue
        coords = cell.get("coords")
        if isinstance(coords, dict):
            parts.extend(str(value) for value in coords.values())
        labels = cell.get("labels")
        if isinstance(labels, dict):
            parts.extend(str(value) for value in labels.values())
        elif isinstance(labels, list):
            for item in labels:
                if isinstance(item, dict):
                    parts.append(str(item.get("label") or ""))
    return fold(" ".join(parts))


def mismatch(question: str, result: dict) -> bool:
    """True when a level was stated for a change, or a change for a level."""
    if not enabled():
        return False
    want = asked(question)
    got = stated(result)
    if want is None or got is None:
        return False
    return want != got
