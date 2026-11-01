"""Unemployment by sex. Off unless ``GRUND_IS_KANG_JOBSEX`` is set.

"Hvert var atvinnuleysi karla" is the men's rate on the labour-force
table, not the both-sexes rate. A change, a quarter, and a headcount stay
on the ordinary list.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "VIN00911"
_BLOCK = ("fjordung", "manud", "milli", "munadi", "haekk", "laekk", "prosent")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_JOBSEX", "0").strip().lower() in {"1", "on", "true", "yes"}


def wants_job_sex(question: str, language: str | None) -> str | None:
    """Icelandic unemployment rate for men or for women, one year, national."""
    if not enabled():
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if language == "en":
        if re.search(r"\b(unemploy\w*|jobless)\b", text) is None or "iceland" not in text:
            return None
        if len(re.findall(r"(?:19|20)\d{2}", question or "")) != 1:
            return None
    else:
        if "atvinnuleys" not in text or "islandi" not in text or "arid" not in text:
            return None
    if any(mark in text for mark in _BLOCK):
        return None
    male = re.search(r"\b(karl\w*|males?|men)\b", text) is not None
    female = re.search(r"\b(konur|konu\w*|kven\w*|wom[ae]n|females?)\b", text) is not None
    if male == female:
        return None
    return "male" if male else "female"


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def labour_sex_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The men's or women's code on an unemployment table, or none."""
    side = wants_job_sex(question, language)
    if side is None or "atvinnuleys" not in fold(title or ""):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "kyn" not in blob and "sex" not in blob:
        return None
    wanted = {"karlar", "karl", "men", "males"} if side == "male" else {"konur", "kona", "women", "females"}
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        if fold(str(label or "")) in wanted:
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


def _asked_year(question: str) -> str | None:
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) == 1:
        return years[0]
    return None


def jobsex_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the ranker's men's or women's unemployment rate."""
    side = wants_job_sex(question, language)
    if side is None:
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    year = _asked_year(question)
    labels = _labels(ranker)
    if year is None or year not in labels:
        return None
    if not any("atvinnuleysi" in label for label in labels):
        return None
    wanted = "karlar" if side == "male" else "konur"
    if wanted not in labels:
        return None
    if "alls" in labels and wanted not in labels:
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_jobsex"] = True
    chosen["source"] = source
    return chosen


def apply_is_jobsex(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Move the labour-force rate table to the front when the sex binds."""
    if wants_job_sex(question, language) is None:
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
    sex = None
    for variable in edition.variables:
        code = labour_sex_code(variable, question, "is", edition.title)
        if code is not None:
            sex = code
            break
    if sex is None:
        return hits
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    if sex not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
