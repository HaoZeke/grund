"""Quarterly unemployment. Off unless ``GRUND_IS_KANG_QUARTER`` is set.

The rate and the headcount are two units on VIN00920. Women and men are
their own rows. A bare annual rate stays on the ordinary path.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "VIN00920"
_QUARTER_WORDS = {
    "first": 1, "1st": 1, "fyrsta": 1, "fyrsti": 1,
    "second": 2, "2nd": 2, "odrum": 2, "annar": 2, "annars": 2,
    "third": 3, "3rd": 3, "thridja": 3, "thridji": 3,
    "fourth": 4, "4th": 4, "fjorda": 4, "fjordi": 4,
}


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_QUARTER", "0").strip().lower() in {"1", "on", "true", "yes"}


def _marker(text: str) -> bool:
    return (
        re.search(r"\bq\s*[1-4]\b", text) is not None
        or "arsfjordung" in text
        or re.search(r"\bquarter\b", text) is not None
    )


def quarter_kind(question: str, language: str | None) -> str | None:
    """``rate`` or ``count``."""
    if not enabled():
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if not _marker(text):
        return None
    if any(mark in text for mark in ("and what", "og hver", "og hvert", "og hvad")):
        return None
    if "atvinnuleys" not in text and "unemploy" not in text and "atvinnulaus" not in text and "jobless" not in text:
        return None
    if any(mark in text for mark in ("haekk", "laekk", "breyt", "prosent", "percent")):
        return None
    if quarter_of_text(text) is None:
        return None
    from grund.measure_guard import unemployment_is_rate

    if unemployment_is_rate(text):
        return "rate"
    if re.search(r"\b(how many|hve marg\w*)\b", text) or re.search(r"\batvinnulaus(?!i?leys)", text):
        if "rate" not in text and "atvinnuleys" not in text:
            return "count"
    if re.search(r"\batvinnulaus(?!i?leys)", text) and "atvinnuleys" not in text:
        return "count"
    return "rate"


def quarter_of_text(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b((?:19|20)\d{2})\b.{0,24}\bq\s*([1-4])\b", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"\bq\s*([1-4])\b.{0,16}\b((?:19|20)\d{2})\b", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.search(r"\b([1-4])\s*\.?\s*arsfjordung\w*.{0,16}\b((?:19|20)\d{2})\b", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.search(
        r"\b(first|second|third|fourth|1st|2nd|3rd|4th|odrum|fyrsta|fyrsti|annar|annars|thridja|thridji|fjorda|fjordi)\b"
        r".{0,40}\b(?:quarter|arsfjordung\w*)\b.{0,24}\b((?:19|20)\d{2})\b",
        text,
    )
    if match and match.group(1) in _QUARTER_WORDS:
        return int(match.group(2)), _QUARTER_WORDS[match.group(1)]
    return None


def quarter_of(question: str, language: str | None) -> tuple[int, int] | None:
    if quarter_kind(question, language) is None:
        return None
    return quarter_of_text(fold(question or ""))


def _sex(text: str) -> str:
    women = re.search(r"\b(women|woman|females?|konur|konum|kvenna|kven)\b", text) is not None
    men = re.search(r"\b(men|males?|karlar|karla|korlum)\b", text) is not None
    if women and not men:
        return "women"
    if men and not women:
        return "men"
    return "both"


def _title_ok(title: str) -> bool:
    folded = fold(title or "")
    return ("atvinnulaus" in folded or "unemployment" in folded) and ("fjordung" in folded or "quarter" in folded)


def quarter_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    kind = quarter_kind(question, language)
    if kind is None or not _title_ok(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    sex = _sex(fold(question or ""))
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(f"{code} {label}")
        if "kyn" in blob or re.search(r"\bsex\b", blob):
            if sex == "women" and "konur" in folded and "karlar" not in folded:
                hits.append(str(code))
            elif sex == "men" and re.search(r"\bkarlar\b", folded) and "konur" not in folded:
                hits.append(str(code))
            elif sex == "both" and "karlar" in folded and "konur" in folded:
                hits.append(str(code))
        elif "eining" in blob or "unit" in blob:
            if kind == "count" and ("atvinnulausir" in folded or "unemployed" in folded):
                hits.append(str(code))
            elif kind == "rate" and ("atvinnuleysi" in folded or "unemployment rate" in folded):
                hits.append(str(code))
        elif "landsvaed" in blob or blob.strip() == "region" or blob.startswith("region "):
            if fold(str(label or "")) in {"alls", "total"}:
                hits.append(str(code))
        elif "aldur" in blob or re.search(r"\bage\b", blob):
            if "16-74" in folded:
                hits.append(str(code))
    hits = list(dict.fromkeys(hits))
    if len(hits) == 1:
        return hits[0]
    return None


def quarter_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if quarter_kind(question, language) is None or edition is None:
        return False
    if not _title_ok(getattr(edition, "title", "") or ""):
        return False
    folded = fold(token)
    return folded.startswith(("atvinnuleys", "atvinnulaus", "unemploy", "arsfjord"))


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _labels_of(obj: dict) -> list[str]:
    cells: list = []
    source = obj.get("source") if isinstance(obj.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in obj.get("claims") or []:
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
    asked = quarter_of(question, "en") or quarter_of(question, "is")
    if asked is None:
        return False
    year, number = asked
    if str(year) not in blob or (f"q{number}" not in blob and f"a{number}" not in blob):
        return False
    sex = _sex(fold(question or ""))
    both = "karlar og konur" in blob or "males and females" in blob
    if sex == "women" and (both or ("konur" not in blob and "females" not in blob)):
        return False
    if sex == "women" and both:
        return False
    if sex == "men" and (both or (not re.search(r"\b(karlar|males)\b", blob))):
        return False
    if sex == "both" and not both and ("konur" in blob or "karlar" in blob or "females" in blob or "males" in blob):
        return False
    if kind == "count":
        return "atvinnulausir" in blob or "unemployed" in blob
    return "atvinnuleysi" in blob or "unemployment rate" in blob


def quarter_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    kind = quarter_kind(question, language)
    if kind is None:
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
        return False
    return _cell_ok(kind, _labels_of(produced), question)


def quarter_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    kind = quarter_kind(question, language)
    if kind is None or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    if not _cell_ok(kind, _labels_of(ranker), question):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_quarter"] = True
    chosen["source"] = source
    return chosen


def apply_is_quarter(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if quarter_kind(question, language) is None:
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
