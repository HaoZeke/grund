"""Gross domestic product. Off unless ``GRUND_IS_KANG_GDP`` is set.

"Verg landsframleiðsla" is line 8 on the national-accounts table. An
export or import line is a different total. A misspelled landsframleiðsla
still means that line, not exports.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_CURRENT = "THJ01102"
_CONSTANT = "THJ01103"
_BLOCK = ("utflutn", "innflutn", "voruskipt", "thjodartekj", "hlutfall", "utgjold", "prosent", "percentage", "verdur", "capita", "deflator", "expenditure")


def table_stem(question: str) -> str:
    """Constant prices are the constant-price accounts. Other GDP is current prices."""
    text = fold(question or "").replace("-", " ")
    if any(phrase in text for phrase in ("constant price", "fast verdlag", "fostu verd", "a fostu")):
        return _CONSTANT
    return _CURRENT


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_GDP", "0").strip().lower() in {"1", "on", "true", "yes"}


def _names_gdp(text: str, language: str | None) -> bool:
    icelandic = "landsframleid" in text or re.search(r"\bvlf\b", text) is not None
    english = re.search(r"\bgdp\b", text) is not None or re.search(r"gross\s+domes\w*\s+product", text) is not None
    if language == "en":
        return english
    if language in {"is", ""}:
        return icelandic
    return icelandic or english


def wants_gdp(question: str, language: str | None) -> bool:
    if not enabled():
        return False
    if language not in {None, "", "is", "en"}:
        return False
    from grund.isguard import blocks_national_gdp

    if blocks_national_gdp(question):
        return False
    text = fold(question or "")
    if not _names_gdp(text, language):
        return False
    if any(mark in text for mark in _BLOCK):
        return False
    if re.search(r"\b(will|exports?|imports?)\b", text):
        return False
    if len(re.findall(r"(?:19|20)\d{2}", question or "")) != 1:
        return False
    return True


def _line_is_gdp(label: str) -> bool:
    folded = fold(label or "")
    if "verg landsframleidsla" in folded:
        return True
    if "gross domestic product" in folded and "expenditure" not in folded and "income" not in folded:
        return True
    return False


def _line_is_trade(label: str) -> bool:
    folded = fold(label or "")
    return "utflutn" in folded or "innflutn" in folded or "exports of" in folded or "imports of" in folded


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def gdp_line_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The GDP line, not exports or imports."""
    if not wants_gdp(question, language):
        return None
    folded_title = fold(title or "")
    if "landsframleid" not in folded_title and "domestic product" not in folded_title and "thjodartekj" not in folded_title:
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "skipting" not in blob and "line" not in blob:
        return None
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        if _line_is_gdp(str(label or "")):
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


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


def gdp_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """The GDP line is the cell. The definite article is not printed on it."""
    if not wants_gdp(question, language):
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"}:
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != table_stem(question):
        return False
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    labels: list[str] = []
    for claim in produced.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            raw = cell.get("labels")
            if isinstance(raw, dict):
                labels.extend(fold(str(value)) for value in raw.values())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        labels.append(fold(str(item.get("label") or "")))
    if not years or years[0] not in labels:
        return False
    if any(_line_is_trade(label) for label in labels):
        return False
    return any(_line_is_gdp(label) for label in labels)


def gdp_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    if not wants_gdp(question, language):
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != table_stem(question):
        return None
    labels = _labels(ranker)
    if not any(_line_is_gdp(label) for label in labels):
        return None
    if any(_line_is_trade(label) for label in labels):
        return None
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if not years or years[0] not in labels:
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_gdp"] = True
    chosen["source"] = source
    return chosen


def apply_is_gdp(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if not wants_gdp(question, language):
        return hits
    stem = table_stem(question)
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    from grund.bind import bind
    from grund.parse import parse_question

    edition = table.edition(language or "is") or table.edition("is") or table.edition("en")
    if edition is None:
        return hits
    binding = bind(edition, parse_question(question, language or "is"))
    if binding is None:
        return hits
    line = None
    for variable in edition.variables:
        line = gdp_line_code(variable, question, language, edition.title)
        if line is not None:
            break
    if line is None:
        return hits
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    if line not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
