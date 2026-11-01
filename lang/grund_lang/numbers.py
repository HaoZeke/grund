"""Cardinals, ordinals, and percentages in Icelandic and English grouping."""

from __future__ import annotations

import re

from grund_lang.types import NumberSpan

_IS_GROUP = re.compile(r"\d{1,3}(?:\.\d{3})+")
_IS_DECIMAL = re.compile(r"\d+,\d+")
_EN_GROUP = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_EN_DECIMAL = re.compile(r"\d+\.\d+")
_PLAIN = re.compile(r"\d+")
_PERCENT = re.compile(r"(?:%|pr[oó]sent|percent|percentage)\b", re.IGNORECASE)


def parse_numbers(text: str, language: str) -> list[NumberSpan]:
    """Read the numbers written in `text`.

    Icelandic groups thousands with a dot and writes the decimal with a
    comma: 1.234 and 13,2. English does the opposite.
    """
    spans: list[NumberSpan] = []
    taken: list[tuple[int, int]] = []

    def claim(match: re.Match[str], value: float) -> None:
        start, end = match.span()
        if any(not (end <= a or start >= b) for a, b in taken):
            return
        tail = text[end : end + 16]
        kind = "percent" if _PERCENT.match(tail.lstrip()) else "cardinal"
        spans.append(NumberSpan(value=value, raw=match.group(0), kind=kind))
        taken.append((start, end))

    if language == "is":
        patterns = (
            (_IS_GROUP, lambda raw: float(raw.replace(".", ""))),
            (_IS_DECIMAL, lambda raw: float(raw.replace(",", "."))),
            (_PLAIN, float),
        )
    else:
        patterns = (
            (_EN_GROUP, lambda raw: float(raw.replace(",", ""))),
            (_EN_DECIMAL, float),
            (_PLAIN, float),
        )
    for pattern, convert in patterns:
        for match in pattern.finditer(text):
            try:
                value = convert(match.group(0))
            except ValueError:
                continue
            claim(match, value)
    spans.sort(key=lambda span: text.find(span.raw))
    return spans
