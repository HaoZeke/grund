"""Live births in Iceland. Off unless ``GRUND_IS_KANG_BIRTHS`` is set.

MAN05104, MAN05100 and MAN05102 publish the same live-birth total for a
year. Stillbirths are a different cell. The gate states the live-birth
total from MAN05100, which already lists every birth, every sex and every
plurality. A stillbirth, a first birth, or one sex stays on the ordinary list.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "MAN05100"
_LIVE = {"lifandi faeddir", "live births"}
_BLOCK = ("andvana", "frumbur", "tvibur", "thribur", "dreng", "stulk", "frjosemi", "faedingartidni")
_ASK = ("faed", "faeding")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_BIRTHS", "0").strip().lower() in {"1", "on", "true", "yes"}


def specific_age(question: str) -> str | None:
    """One year of age, not a band and not a calendar year.

    ``30 ára`` and ``aged 30`` name that year. ``30 to 34`` does not.
    """
    text = fold(question or "").replace("-", " ")
    match = re.search(r"\b(\d{1,3})\s+ara\b", text) or re.search(r"\baged\s+(\d{1,3})\b", text)
    if match is None:
        match = re.search(r"\b(\d{1,3})\s+years?\s+old\b", text)
    if match is None:
        return None
    number = match.group(1)
    if re.search(rf"\b{re.escape(number)}\s+(?:to|til)\b", text):
        return None
    return number


def parent_role(question: str) -> str | None:
    """``mother`` or ``father`` when the question names that parent."""
    text = fold(question or "")
    if re.search(r"\b(mother|mothers|modir|modur|maedr\w*)\b", text):
        return "mother"
    if re.search(r"\b(father|fathers|fodur|fedra|fodr\w*)\b", text):
        return "father"
    return None


def wants_births(question: str, language: str | None) -> bool:
    """How many children were born in Iceland in one named year.

    A named age or a named parent is a breakdown, not this headline total.
    """
    if not enabled():
        return False
    if language not in {None, "", "is", "en"}:
        return False
    if specific_age(question) or parent_role(question):
        return False
    text = fold(question or "")
    if language == "en":
        if re.search(r"\b(births?|born)\b", text) is None:
            return False
    elif not any(mark in text for mark in _ASK):
        return False
    if any(mark in text for mark in _BLOCK):
        return False
    if len(re.findall(r"(?:19|20)\d{2}", question or "")) != 1:
        return False
    return True


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _birth_title(title: str) -> bool:
    folded = fold(title or "")
    return "faed" in folded or "birth" in folded


def _total_code(variable) -> str | None:
    for code, label in getattr(variable, "values", []) or []:
        if fold(str(label or "")) in {"alls", "total", "samtals", "oll born"}:
            return str(code)
    return None


def _age_blob(blob: str) -> bool:
    return blob.strip() in {"aldur", "age"} or blob.startswith("aldur ") or " aldur" in blob or re.search(r"\bage\b", blob) is not None


def birth_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    """Live births, all sexes, all pluralities. Not the stillbirth row.

    A named year of age is that row. It is not the all-ages total.
    """
    if not _birth_title(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    number = specific_age(question)
    if number and _age_blob(blob):
        hits = []
        for code, label in getattr(variable, "values", []) or []:
            # The value code is a list index. The age is the number in the label.
            numbers = re.findall(r"\d+", str(label or ""))
            if set(numbers) == {number}:
                hits.append(str(code))
        if len(hits) == 1:
            return hits[0]
        return None
    if not wants_births(question, language):
        return None
    if "skipting" in blob:
        for code, label in getattr(variable, "values", []) or []:
            if fold(str(label or "")) in _LIVE:
                return str(code)
        return None
    if any(mark in blob for mark in ("kyn", "fjodli barna", "faedingarr", "hjuskap", "eining")):
        return _total_code(variable)
    if blob.strip() in {"aldur", "age"} or blob.startswith("aldur ") or " aldur" in blob:
        # Father's age on MAN05102. The national total is Alls, not one year of age.
        return _total_code(variable)
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


def _live_cell(labels: list[str], year: str) -> bool:
    if year not in labels:
        return False
    if any("andvana" in label for label in labels):
        return False
    if any(label in {"drengir", "stulkur", "boys", "girls"} for label in labels):
        return False
    if any(re.match(r"\d+\. barn", label) for label in labels):
        return False
    return True


def birth_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """The live-birth total is the cell. The word fæddust is not printed on it.

    A named year of a parent's age is that breakdown cell, not the headline total.
    """
    age = specific_age(question)
    parent = parent_role(question)
    if age and parent:
        table = produced.get("table")
        stem = _stem(str(getattr(table, "id", "") or ""))
        if parent == "mother" and stem != "MAN05101":
            return False
        if parent == "father" and stem != "MAN05102":
            return False
        labels: list[str] = []
        for claim in produced.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            for cell in claim.get("cells") or []:
                if isinstance(cell, dict):
                    labels.extend(fold(str(value)) for value in (cell.get("labels") or {}).values())
        return any(set(re.findall(r"\d+", label)) == {age} for label in labels)
    if not wants_births(question, language):
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    stem = _stem(str(getattr(table, "id", "") or ""))
    if stem not in {"MAN05100", "MAN05104", "MAN05102"}:
        return False
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    claims = produced.get("claims") or []
    labels: list[str] = []
    for claim in claims:
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
    if not years or not _live_cell(labels, years[0]):
        return False
    if stem == "MAN05100" and not any("lifandi" in label or "live birth" in label for label in labels):
        return False
    return True


def _keep(ranker: dict) -> dict:
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_births"] = True
    chosen["source"] = source
    return chosen


def births_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the live-birth total. A stillbirth or a slice is a different statistic.

    A named parent and year of age keep that breakdown cell, and only that cell.
    The headline total is a different statistic.
    """
    age = specific_age(question)
    parent = parent_role(question)
    if age or parent:
        if ranker.get("refused") or ranker.get("value") in (None, ""):
            return None
        stem = _stem(str(ranker.get("table_id") or ""))
        if parent == "mother" and stem != "MAN05101":
            return None
        if parent == "father" and stem != "MAN05102":
            return None
        if age:
            labels = _labels(ranker)
            if not any(set(re.findall(r"\d+", label)) == {age} for label in labels):
                return None
        return _keep(ranker)
    if not wants_births(question, language):
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    labels = _labels(ranker)
    if not years or not _live_cell(labels, years[0]):
        return None
    stem = _stem(str(ranker.get("table_id") or ""))
    if stem not in {"MAN05100", "MAN05104", "MAN05102"}:
        return None
    return _keep(ranker)


def _lead(catalogue, hits: list[Hit], stem: str) -> list[Hit]:
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept


def apply_is_births(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Move the live-birth total to the front when that cell binds.

    A named mother's or father's age leads with that breakdown table instead.
    """
    if specific_age(question) and parent_role(question) == "mother":
        return _lead(catalogue, hits, "MAN05101")
    if specific_age(question) and parent_role(question) == "father":
        return _lead(catalogue, hits, "MAN05102")
    if not wants_births(question, language):
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    from grund.bind import bind
    from grund.parse import parse_question

    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return hits
    binding = bind(edition, parse_question(question, "is"))
    if binding is None:
        return hits
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    live = None
    for variable in edition.variables:
        code = birth_value_code(variable, question, "is", edition.title)
        blob = fold(f"{variable.code} {variable.text}")
        if "skipting" in blob:
            live = code
    if live is None or live not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
