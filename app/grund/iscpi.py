"""Consumer price index. Off unless ``GRUND_IS_KANG_CPI`` is set.

The monthly index and its annual change are on VIS01000. A year with no
month is the annual average on VIS01005. A misspelled month is still that
month. Housing-only and building-cost indexes are different series.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_CHANGE = "VIS01000"
_AVERAGE = "VIS01005"
_TYPO_MONTHS = {"septmber": 9, "janury": 1}
_MONTHS = {
    "january": 1, "januar": 1, "february": 2, "februar": 2, "march": 3, "mars": 3,
    "april": 4, "may": 5, "mai": 5, "june": 6, "juni": 6, "july": 7, "juli": 7,
    "august": 8, "agust": 8, "september": 9, "october": 10, "oktober": 10,
    "november": 11, "december": 12, "desember": 12,
}


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_CPI", "0").strip().lower() in {"1", "on", "true", "yes"}


def _subject(text: str) -> bool:
    if "neysluverd" in text or "consumer price" in text:
        return True
    return re.search(r"\b(cpi|vnv)\b", text) is not None


def _housing(text: str) -> bool:
    return any(mark in text for mark in ("husnaed", "housing", "bygging", "building", "an husnaed"))


def _one_year(question: str) -> str | None:
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) == 1:
        return years[0]
    return None


def _month_number(text: str) -> int | None:
    for word, number in {**_TYPO_MONTHS, **_MONTHS}.items():
        if re.search(rf"\b{word}\b", text):
            return number
    return None


def cpi_kind(question: str, language: str | None) -> str | None:
    """``change``, ``average`` or ``level`` (a misspelled month only)."""
    if not enabled():
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if not _subject(text) or _housing(text):
        return None
    if _one_year(question) is None:
        return None
    if any(mark in text for mark in ("arsbreyt", "annual change", "annualized", "over the year", "a ari")):
        if any(mark in text for mark in ("3 month", "6 month", "sidustu", "latest month")):
            return None
        return "change"
    if _month_number(text) is None:
        return "average"
    return "level"


def cpi_periods(question: str, language: str | None) -> list[tuple[int, int]] | None:
    """The month a typo hid from the ordinary parser."""
    if cpi_kind(question, language) != "level":
        return None
    text = fold(question or "")
    month = None
    for word, number in _TYPO_MONTHS.items():
        if re.search(rf"\b{word}\b", text):
            month = number
    year = _one_year(question)
    if month is None or year is None:
        return None
    return [(int(year), month)]


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _cpi_title(title: str) -> bool:
    folded = fold(title or "")
    return "neysluverd" in folded or "consumer price" in folded or folded.startswith("cpi")


def cpi_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    kind = cpi_kind(question, language)
    if kind is None or not _cpi_title(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    wanted = None
    if blob.strip() in {"visitala", "index"} or blob.startswith("visitala ") or blob.startswith("index "):
        wanted = "cpi"
    elif "lidur" in blob or blob.strip() == "item" or blob.startswith("item "):
        wanted = "change" if kind == "change" else "index"
    elif "grunn" in blob or blob.strip() == "base" or blob.startswith("base "):
        wanted = "1988"
    if wanted is None:
        return None
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(f"{code} {label}")
        if wanted == "cpi" and re.search(r"\bcpi\b", folded) and "husnaed" not in folded and "housing" not in folded:
            hits.append(str(code))
        elif wanted == "change" and ("arsbreyt" in folded or "annual change" in folded):
            hits.append(str(code))
        elif wanted == "index" and fold(str(label or "")) in {"visitola", "index"}:
            hits.append(str(code))
        elif wanted == "1988" and "1988" in folded:
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def cpi_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if cpi_kind(question, language) is None or edition is None:
        return False
    if not _cpi_title(getattr(edition, "title", "") or ""):
        return False
    folded = fold(token)
    return folded.startswith(("neysluverd", "visitl", "consumer", "price", "indx", "septmb", "janur"))


def _labels(result: dict) -> list[str]:
    cells: list = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    found: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        raw = cell.get("labels")
        if isinstance(raw, dict):
            found.extend(fold(str(value)) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    found.append(fold(str(item.get("label") or "")))
    return found


def _cell_ok(kind: str, labels: list[str], question: str) -> bool:
    blob = " ".join(labels)
    if "husnaed" in blob or "housing" in blob:
        return False
    if not re.search(r"\bcpi\b", blob) and "neysluverd" not in blob and "consumer price" not in blob:
        return False
    year = _one_year(question)
    if year is None or year not in labels and year not in blob:
        return False
    if kind == "change":
        month = _month_number(fold(question))
        if month is None or f"m{month:02d}" not in blob:
            return False
        return "arsbreyt" in blob or "annual change" in blob
    if kind == "average":
        return "1988" in blob
    month = _month_number(fold(question))
    return month is not None and f"m{month:02d}" in blob and "arsbreyt" not in blob and "annual change" not in blob


def cpi_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    kind = cpi_kind(question, language)
    if kind is None:
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    stem = _stem(str(getattr(table, "id", "") or ""))
    if stem not in {_CHANGE, _AVERAGE}:
        return False
    labels: list[str] = []
    for claim in produced.get("claims") or []:
        if isinstance(claim, dict):
            for cell in claim.get("cells") or []:
                if isinstance(cell, dict):
                    raw = cell.get("labels")
                    if isinstance(raw, dict):
                        labels.extend(fold(str(value)) for value in raw.values())
                    elif isinstance(raw, list):
                        for item in raw:
                            if isinstance(item, dict):
                                labels.append(fold(str(item.get("label") or "")))
    return _cell_ok(kind, labels, question)


def cpi_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    kind = cpi_kind(question, language)
    if kind is None or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    stem = _stem(str(ranker.get("table_id") or ""))
    if kind == "average" and stem != _AVERAGE:
        return None
    if kind != "average" and stem != _CHANGE:
        return None
    if not _cell_ok(kind, _labels(ranker), question):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_cpi"] = True
    chosen["source"] = source
    return chosen


def apply_is_cpi(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    kind = cpi_kind(question, language)
    if kind is None:
        return hits
    stem = _AVERAGE if kind == "average" else _CHANGE
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
