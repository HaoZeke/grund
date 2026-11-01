"""Parse the numbers a reader would take as figures."""

from __future__ import annotations

import re

_EN = re.compile(
    r"(?<![\w])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)(?![\w])"
)
_IS = re.compile(
    r"(?<![\w])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d+)(?![\w])"
)


def parse_token(token: str, language: str) -> float:
    text = token.replace("%", "").replace(" ", "").strip()
    if language == "is" and re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):
        text = text.replace(".", "").replace(",", ".")
    elif language == "is":
        text = text.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        text = text.replace(",", "")
    return float(text)


_CITATION_TAIL = re.compile(
    r"\s(?:Table\s+[A-Z]{3}\d{4,5}|Tafla\s+[A-Z]{3}\d{4,5}|Calculated by Grund|Reiknað af Grund)\b.*",
    re.DOTALL,
)
_TABLE_ID = re.compile(r"\b[A-Z]{3}\d{4,5}(?:\.px)?\b")
_STAMP = re.compile(r"\b(?:Updated|Uppfært)\s+\d{4}-\d{2}-\d{2}T[\d:.]+")
_URL = re.compile(r"https?://\S+")
# A calendar date and a PxWeb period code are not figures. 2026M09 must not
# become 9, and 2026-09-29T08:59:51 must not become a handful of claims.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:.]+)?")
_PX_PERIOD = re.compile(r"\b(?:19|20)\d{2}[MQmqÁá]\d{1,2}\b")


def strip_citation(text: str) -> str:
    """Drop the source tail. Table codes and the updated stamp are not figures.

    ``VIS01000`` would otherwise be read as 1000, and ``2026-09-29T08:59:51``
    as a handful of extra numbers. The stated value is the part before the
    citation.
    """
    body = _URL.sub(" ", text or "")
    body = _STAMP.sub(" ", body)
    body = _CITATION_TAIL.sub("", body)
    body = _TABLE_ID.sub(" ", body)
    body = _ISO_DATE.sub(" ", body)
    body = _PX_PERIOD.sub(" ", body)
    return body


def stated_figures(text: str, language: str) -> list[float]:
    """Figures in the answer, ignoring table ids and dates in the citation."""
    return find_numbers(strip_citation(text), language)


def find_numbers(text: str, language: str) -> list[float]:
    pattern = _IS if language == "is" else _EN
    values = []
    for match in pattern.finditer(text or ""):
        try:
            values.append(parse_token(match.group(0), language))
        except ValueError:
            continue
    return values


def matches(displayed: float, allowed: float) -> bool:
    scale = max(1.0, abs(allowed))
    return abs(displayed - allowed) <= 1e-6 * scale
