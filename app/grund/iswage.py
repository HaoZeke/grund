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


def _asked(question: str) -> str:
    return fold(question or "").replace("-", " ")


def named_basis(question: str) -> str | None:
    """A wage index whose price basis is written in the question.

    ``constant`` is the constant-price index. ``mortgage`` is the payment-
    adjustment index. A question word does not choose the nominal series
    once the basis is named. Other constant-price statistics are not wages.
    """
    if not enabled():
        return None
    text = _asked(question)
    if not _subject(text):
        return None
    if "constant price" in text or "fast verdlag" in text or "fostu verd" in text:
        return "constant"
    if any(mark in text for mark in ("mortgage", "greidslu", "jofnun")):
        return "mortgage"
    return None


def indices_kind(question: str) -> str | None:
    """``level`` or ``percent`` on the 2015 indices, the wage-index row.

    That table prints "Wage index" / "Launavísitala" as a row, plus the
    value and the annual change. "What was the wage index in August 2026?"
    is the 1989 series. A bare name, a named value, or the annual percent
    is the row on the 2015 table. "Basic wage" without "value" is the
    grunnlaun row, not this one.
    """
    if not enabled():
        return None
    text = _asked(question)
    if not _subject(text):
        return None
    if named_basis(question):
        return None
    if ("basic wage" in text or "grunnlaun" in text) and "value" not in text and "gildi" not in text:
        return None
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) != 1:
        return None
    if "point" in text or re.search(r"\bstig\b", text):
        return None
    if any(mark in text for mark in ("arsbreyt", "over the year", "annual change", "percent", "prosent")):
        return "percent"
    if "gildi" in text or re.search(r"\bvalue\b", text):
        return "level"
    if re.search(r"\b(what|how|which|hver|hvert|hvad|hve|hversu)\b", text):
        return None
    return "level"


def _basic(question: str) -> bool:
    from grund.measure_guard import basic_wage

    return enabled() and basic_wage(question)


def _basic_percent(question: str) -> bool:
    text = fold(question or "")
    return any(mark in text for mark in ("prosent", "percent", "arsbreyt", "over the year"))


def _basic_code(variable, question: str, title: str) -> str | None:
    """Basic wage index on the 2015 indices, not the 1989 wage index."""
    folded_title = fold(title or "")
    if "2015" not in folded_title and "grunn" not in folded_title:
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    percent = _basic_percent(question)
    unit = "eining" in blob or re.search(r"\bunit\b", blob) is not None
    index_dim = not unit and ("visital" in blob or re.search(r"\bindex\b", blob) is not None)
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        plain = fold(str(label or ""))
        packed = fold(f"{code} {label}")
        if index_dim and ("basic" in plain or "grunn" in plain):
            hits.append(str(code))
        elif unit and percent and ("annual change" in packed or "arsbreyt" in packed):
            hits.append(str(code))
        elif unit and not percent and plain in {"value of index", "visitolugildi"}:
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def _indices_code(variable, question: str, title: str) -> str | None:
    """The wage-index row, or its value / annual-change unit. Not grunnlaun."""
    if indices_kind(question) is None:
        return None
    if "2015" not in fold(title or ""):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    percent = indices_kind(question) == "percent"
    unit = "eining" in blob or re.search(r"\bunit\b", blob) is not None
    index_dim = not unit and ("visital" in blob or re.search(r"\bindex\b", blob) is not None)
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        plain = fold(str(label or ""))
        packed = fold(f"{code} {label}")
        if index_dim and ("basic" in plain or "grunn" in plain):
            continue
        if index_dim and (plain in {"wage index", "launavisitala"} or plain.startswith("launavisitala")):
            hits.append(str(code))
        elif unit and percent and ("annual change" in packed or "arsbreyt" in packed):
            hits.append(str(code))
        elif unit and not percent and plain in {"value of index", "visitolugildi"}:
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def wage_kind(question: str, language: str | None) -> str | None:
    """``percent``, ``points`` or ``level``."""
    if not enabled():
        return None
    if indices_kind(question) or named_basis(question):
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
    pinned = _indices_code(variable, question, title)
    if pinned is not None:
        return pinned
    if _basic(question):
        return _basic_code(variable, question, title)
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
    if edition is None:
        return False
    if (
        named_basis(question) is None
        and wage_kind(question, language) is None
        and indices_kind(question) is None
        and not _basic(question)
    ):
        return False
    title = fold(getattr(edition, "title", "") or "")
    if "1989" not in title and "2015" not in title and "launa" not in title and "wage" not in title:
        return False
    folded = fold(token)
    return folded.startswith(("launavisit", "visitol", "indx", "arsbreyt", "gildi", "grunn"))


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


def _wage_stem(question: str) -> str:
    basis = named_basis(question)
    if basis == "constant":
        return "LAU04800"
    if basis == "mortgage":
        return "LAU04802"
    if indices_kind(question) or _basic(question):
        return "LAU04001"
    return _TABLE


def wage_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    kind = indices_kind(question) or wage_kind(question, language)
    if kind is None or kind == "points":
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for", "a change was asked and the cell is one level"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _wage_stem(question):
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
    kind = indices_kind(question) or wage_kind(question, language)
    if kind is None or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _wage_stem(question):
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
    basis = named_basis(question)
    if basis == "constant":
        stem = "LAU04800"
    elif basis == "mortgage":
        stem = "LAU04802"
    else:
        stem = "LAU04001" if indices_kind(question) or _basic(question) else ""
    if not stem:
        kind = wage_kind(question, language)
        if kind is None or kind == "points":
            return hits
        stem = _TABLE
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
