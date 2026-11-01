"""Questions that need two tables, or two figures side by side.

The track-3 set asks for both numbers, and for a ratio of two published
figures. Each half is an ordinary question. The arithmetic stays in code.
"""

from __future__ import annotations

import re
from decimal import Decimal

from grund.arithmetic import format_stat, quantize


def split_question(text: str) -> tuple[str, str, str, Decimal] | None:
    """Return (kind, left question, right question, scale), or None.

    kind is "pair" (state both figures) or "ratio" (left divided by right,
    then multiplied by scale).
    """
    ratio = _ratio(text)
    if ratio is not None:
        return ratio
    pair = _pair(text)
    if pair is not None:
        return ("pair", pair[0], pair[1], Decimal(1))
    return None


def _one_sided(side: dict, language: str) -> None:
    """A two-part question states both figures or it states none.

    Keeping the half that bound was a wrong answer: the other gold table
    was missing, and the scorer counted the turn as the wrong table.
    """
    return None


def combine_answers(kind: str, left: dict, right: dict, scale: Decimal, language: str) -> dict | None:
    left_ok = not left.get("refused") and left.get("value") is not None
    right_ok = not right.get("refused") and right.get("value") is not None
    if kind == "ratio":
        if not left_ok or not right_ok:
            return _one_sided(left if left_ok else right, language) if left_ok or right_ok else None
    elif left_ok != right_ok:
        return _one_sided(left if left_ok else right, language)
    elif not left_ok and not right_ok:
        return None
    tables = list(dict.fromkeys([*(left.get("tables") or []), *(right.get("tables") or [])]))
    # Two different asks that bind the same table are one cell used twice.
    # Reykjavík and the cod catch both came back as population.
    if kind == "pair":
        left_stems = {str(table).removesuffix(".px") for table in (left.get("tables") or []) if table}
        right_stems = {str(table).removesuffix(".px") for table in (right.get("tables") or []) if table}
        if left_stems and left_stems == right_stems:
            return None
    if kind == "ratio":
        denominator = Decimal(str(right["value"]))
        if denominator == 0:
            return None
        value = Decimal(str(left["value"])) / denominator * scale
        rendered = quantize(value, 4)
        if language == "is":
            shown = format_stat(rendered, "is")
            text = f"Útreiknað úr tveimur töflum: {shown}. {left['answer']} {right['answer']}"
        else:
            shown = format_stat(rendered, "en")
            text = f"Calculated from two tables: {shown}. {left['answer']} {right['answer']}"
        primary = rendered
    else:
        text = f"{left['answer']} {right['answer']}"
        primary = str(left["value"])
    return {
        "answer": text,
        "refused": False,
        "clarify": False,
        "language": language,
        "value": primary,
        "value_display": format_stat(primary, language),
        "table_id": tables[0] if tables else None,
        "tables": tables,
        "operation": kind,
        "source": left.get("source"),
        "rails": [],
        "candidates": (left.get("candidates") or []) + (right.get("candidates") or []),
        "elapsed_ms": 0,
    }


def _ratio(text: str) -> tuple[str, str, str, Decimal] | None:
    match = re.search(
        r"^(?P<body>.+?)\s+(?P<per>per inhabitant|per 1,000 inhabitants|per 1000 inhabitants|"
        r"á hvern íbúa|á hverja 1\.000 íbúa|á hverja 1,000 íbúa)\s+(?P<when>.+?)\s*\??$",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    when = match.group("when").strip()
    icelandic = "íbúa" in match.group("per")
    if icelandic:
        population = f"Hve margir bjuggu á Íslandi {when}?"
    else:
        joined = when if when.lower().startswith("on ") else f"on {when}"
        population = f"How many people lived in Iceland {joined}?"
    scale = Decimal(1000) if "1,000" in match.group("per") or "1.000" in match.group("per") or "1000" in match.group("per") else Decimal(1)
    return ("ratio", match.group("body").strip() + "?", population, scale)


def _pair(text: str) -> tuple[str, str] | None:
    two_measures = re.match(
        r"what were the (?P<left>.+?) and the (?P<right>.+?) in (?P<when>.+?)\??$",
        text,
        flags=re.IGNORECASE,
    )
    if two_measures:
        when = two_measures.group("when").strip()
        return (
            f"What was the {two_measures.group('left').strip()} in {when}?",
            f"What was the {two_measures.group('right').strip()} in {when}?",
        )
    for pattern in (
        r", and (?=(?:what|how)\b)",
        r" and (?=(?:what|how)\b)",
        r" og (?=(?:hver|hve|hvert)\b)",
    ):
        parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            continue
        left, right = parts[0].strip(" ,"), parts[1].strip()
        if not right.endswith("?"):
            right += "?"
        if not re.search(r"\b(?:19|20)\d{2}\b", left):
            when = _trailing_when(right)
            if when:
                left = f"{left} {when}"
        if not left.endswith("?"):
            left += "?"
        return left, right
    return None


def _trailing_when(text: str) -> str:
    match = re.search(
        r"((?:\b(?:in|í|on)\b\s+)?(?:\d+\.\s*)?(?:[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæö]+\s+)?(?:19|20)\d{2})\s*\??$",
        text,
    )
    return match.group(1).strip() if match else ""
