"""Wage index from 1989. Off unless ``GRUND_IS_KANG_WAGE`` is set.

The level is the index column. A percent over the year is the table's own
annual-change column, not a recomputed change of the index. A point change
keeps the ranker cell when that cell is already on this table.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "LAU04000"


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_WAGE", "0").strip().lower() in {"1", "on", "true", "yes"}


def _subject(text: str) -> bool:
    return "launavisit" in text or "wage index" in text or "wage indx" in text


def wage_kind(question: str, language: str | None) -> str | None:
    """``percent``, ``points`` or ``level``."""
    if not enabled():
        return None
    from grund.measure_guard import basic_wage

    if basic_wage(question):
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if not _subject(text):
        return None
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if "stig" in text or re.search(r"\bpoints?\b", text):
        return "points" if len(years) == 2 else None
    if any(mark in text for mark in ("prosent", "percent", "haekk", "rise", "rose", "arsbreyt")):
        return "percent" if len(years) == 1 else None
    if len(years) == 1 and not any(mark in text for mark in ("prosent", "percent", "stig")):
        return "level"
    return None


def _title_ok(title: str) -> bool:
    folded = fold(title or "")
    return "1989" in folded and ("launa" in folded or "wage" in folded)


def wage_official(edition, parsed) -> tuple[str, str] | None:
    """The annual-change column, when the question asks the percent."""
    if wage_kind(parsed.text, parsed.language) != "percent":
        return None
    if not _title_ok(getattr(edition, "title", "") or ""):
        return None
    for variable in edition.variables:
        if variable.time:
            continue
        blob = fold(f"{variable.code} {variable.text}")
        if "eining" not in blob and "unit" not in blob:
            continue
        for code, label in variable.values:
            if "arsbreyt" in fold(str(label or "")) or "annual change" in fold(str(label or "")):
                return variable.code, str(code)
    return None


def wage_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    kind = wage_kind(question, language)
    if kind is None or kind == "points" or not _title_ok(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "eining" not in blob and "unit" not in blob:
        return None
    wanted = "change" if kind == "percent" else "index"
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(f"{code} {label}")
        if wanted == "change" and ("arsbreyt" in folded or "annual change" in folded):
            hits.append(str(code))
        elif wanted == "index" and (folded.strip() in {"index", "index visitolugildi"} or fold(str(label or "")) in {"visitolugildi", "value of index"}):
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def wage_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if wage_kind(question, language) is None or edition is None:
        return False
    if not _title_ok(getattr(edition, "title", "") or ""):
        return False
    folded = fold(token)
    return folded.startswith(("launavisit", "visitol", "indx"))


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


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
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if not years or any(year not in blob for year in years):
        return False
    if kind == "percent":
        return "arsbreyt" in blob or "annual change" in blob
    if kind == "level":
        return "visitolugildi" in blob or "value of index" in blob
    return True


def wage_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    kind = wage_kind(question, language)
    if kind is None or kind == "points":
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for", "a change was asked and the cell is one level"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
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


def wage_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    kind = wage_kind(question, language)
    if kind is None or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    if not _cell_ok(kind, _labels(ranker), question):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_wage"] = True
    chosen["source"] = source
    return chosen


def apply_is_wage(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    kind = wage_kind(question, language)
    if kind is None or kind == "points":
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
