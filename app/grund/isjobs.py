"""Icelandic labour-force level. Off unless ``GRUND_IS_KANG_JOBS`` is set.

A national question for the unemployment rate, the participation rate, or
how many people are employed already has that cell on the ranker. The
hybrid path states a different series, and the disagreement abstain drops
the ranker. The ranker cell is kept when its label is the asked measure
and the asked year. A sex, a change, and a quarter stay on the ordinary
gate.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_BLOCK = (
    "karla",
    "kvenna",
    "konur",
    "konum",
    "muni",
    "munadi",
    "milli",
    "haekk",
    "laekk",
    "prosent",
    "fjordung",
    "manud",
)
_TOTAL = {"alls", "total", "samtals", "all"}


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_JOBS", "0").strip().lower() in {"1", "on", "true", "yes"}


def survey_unemployment(question: str, language: str | None) -> bool:
    """The annual labour-force survey, not the quarterly rate.

    A quarter in the question stays on the quarterly table. A year of the
    survey names the annual rate, both sexes, ages 16-74.
    """
    if not enabled():
        return False
    if language not in {None, "", "is", "en"}:
        return False
    text = fold(question or "").replace("-", " ")
    if re.search(r"\b(quarter|arsfjord\w*)\b", text):
        return False
    if (
        "labour force survey" not in text
        and "labor force survey" not in text
        and "vinnumarkadsrannsokn" not in text
    ):
        return False
    if "unemployment" not in text and "atvinnuleys" not in text:
        return False
    return len(re.findall(r"(?:19|20)\d{2}", question or "")) == 1


def _kind(question: str, language: str | None) -> str | None:
    kind = wants_jobs(question, language)
    if kind:
        return kind
    if survey_unemployment(question, language):
        return "unemployment"
    return None


def wants_jobs(question: str, language: str | None) -> str | None:
    """National Icelandic level: unemployment, participation, or employed."""
    if not enabled():
        return None
    if language not in {None, "", "is"}:
        return None
    text = fold(question or "")
    if "islandi" not in text or "arid" not in text:
        return None
    if any(mark in text for mark in _BLOCK):
        return None
    if "atvinnuleys" in text:
        return "unemployment"
    if "atvinnuthatttaka" in text:
        return "participation"
    if "starfandi" in text and any(mark in text for mark in ("margir", "fjoldi")):
        return "employed"
    return None


def _asked_year(question: str) -> str | None:
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) == 1:
        return years[0]
    return None


def _pairs(result: dict) -> list[tuple[str, str, str]]:
    """(title, variable, label) for each cited label."""
    cells: list = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    found: list[tuple[str, str, str]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        title = fold(str(cell.get("title") or ""))
        raw = cell.get("labels")
        if isinstance(raw, dict):
            items = [(str(key), str(value)) for key, value in raw.items()]
        elif isinstance(raw, list):
            items = [
                (str(item.get("variable_text") or item.get("variable") or ""), str(item.get("label") or ""))
                for item in raw
                if isinstance(item, dict)
            ]
        else:
            items = []
        for variable, label in items:
            found.append((title, fold(variable), fold(label)))
    return found


def _cell_is_measure(question: str, kind: str, result: dict) -> bool:
    year = _asked_year(question)
    pairs = _pairs(result)
    if not pairs or year is None:
        return False
    if not any(label == year for _title, _variable, label in pairs):
        return False
    labels = [label for _title, _variable, label in pairs]
    if any(label in {"karlar", "konur", "men", "women"} for label in labels):
        return False
    if kind == "unemployment":
        return any(
            ("atvinnuleysi" in label or "unemployment rate" in label) and "thattaka" not in label
            for label in labels
        )
    if kind == "participation":
        return any("atvinnuthatttaka" in label for label in labels)
    if kind == "employed":
        titles = {title for title, _variable, _label in pairs}
        if not any("starfandi" in title for title in titles):
            return False
        for _title, variable, label in pairs:
            if label == year or "ar" in variable:
                continue
            if label not in _TOTAL:
                return False
        return True
    return False


def _title_ok(title: str, kind: str) -> bool:
    folded = fold(title or "")
    if kind == "employed":
        return "starfandi" in folded and "fjoldi" in folded
    return "atvinnuleys" in folded or "atvinnuthatttaka" in folded or "unemployment" in folded


def labour_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The national annual measure, both sexes, ages 16-74."""
    kind = _kind(question, language)
    if kind is None or not _title_ok(title, kind):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(f"{code} {label}")
        plain = fold(str(label or ""))
        if "hlutfall" in blob or re.search(r"\brate\b", blob):
            rate = "atvinnuleysi" in plain or "unemployment rate" in plain
            if kind == "unemployment" and rate and "thattaka" not in plain:
                hits.append(str(code))
            elif kind == "participation" and "atvinnuthatttaka" in plain:
                hits.append(str(code))
        elif kind == "employed" and "eining" in blob and plain == "starfandi":
            hits.append(str(code))
        elif "kyn" in blob or re.search(r"\bsex\b", blob):
            if plain in {"alls", "total", "karlar og konur"}:
                hits.append(str(code))
        elif "landsvaed" in blob or "region" in blob:
            if plain in {"alls", "total"}:
                hits.append(str(code))
        elif "aldur" in blob or re.search(r"\bage\b", blob):
            if "16-74" in plain:
                hits.append(str(code))
    hits = list(dict.fromkeys(hits))
    if len(hits) == 1:
        return hits[0]
    return None


def apply_is_jobs(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    kind = _kind(question, language)
    if kind is None:
        return hits
    stem = "VIN00931" if kind == "employed" else "VIN00911"
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    kept = [hit for hit in hits if str(hit.table.id).removesuffix(".px") != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    from grund_index.catalogue import Hit as _Hit

    lead = _Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept


def _stem_id(result: dict) -> str:
    return str(result.get("table_id") or "").removesuffix(".px")


def job_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the ranker's labour-force cell when hybrid states another series."""
    kind = wants_jobs(question, language)
    survey = survey_unemployment(question, language)
    if kind is None and survey:
        kind = "unemployment"
    if kind is None:
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if survey and _stem_id(ranker) != "VIN00911":
        return None
    if not _cell_is_measure(question, kind, ranker):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_jobs"] = True
    chosen["source"] = source
    return chosen
