"""Turn a question into a typed tool request. The request has no result figure.

Years belong only in `period`. Measure, filters, and the unit hint are words.
`validate_request` rejects a malformed object and any stray number outside
the period. An external model may emit the same object; it has to pass
this check before a tool runs.
"""

from __future__ import annotations

import re
from typing import Any

from grund_lang.dates import parse_dates
from grund_lang.fold import STOP, fold
from grund_lang.index import _clauses
from grund_lang.lemma import analyze

OPS = ("level", "change", "pct_change", "sum", "share", "compare")
PERIOD_KINDS = ("point", "range", "latest")
KEYS = ("measure", "filters", "period", "op", "unit_hint")

_DIGIT = re.compile(r"\d")


class ParseError(ValueError):
    """The question did not become a schema-valid request."""


def validate_request(payload: Any) -> list[str]:
    """Return a list of schema errors. An empty list means the request may run."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["request is not an object"]
    unknown = sorted(set(payload) - set(KEYS))
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    for key in KEYS:
        if key not in payload:
            errors.append(f"missing {key}")
    if errors:
        return errors
    measure = payload["measure"]
    if not isinstance(measure, str) or not measure.strip():
        errors.append("measure must be a non-empty string")
    elif _DIGIT.search(measure):
        errors.append("measure must not contain a number")
    filters = payload["filters"]
    if not isinstance(filters, dict):
        errors.append("filters must be an object")
    else:
        for dimension, values in filters.items():
            if not isinstance(dimension, str) or _DIGIT.search(dimension):
                errors.append(f"bad filter dimension {dimension!r}")
                continue
            if not isinstance(values, list) or not values:
                errors.append(f"filter {dimension} needs a list of values")
                continue
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"filter {dimension} has a non-string value")
                elif _DIGIT.search(value):
                    errors.append(f"filter {dimension} must not contain a number")
    op = payload["op"]
    if op not in OPS:
        errors.append(f"op must be one of {', '.join(OPS)}")
    unit = payload["unit_hint"]
    if not isinstance(unit, str):
        errors.append("unit_hint must be a string")
    elif _DIGIT.search(unit):
        errors.append("unit_hint must not contain a number")
    errors.extend(_period_errors(payload["period"]))
    return errors


def _period_errors(period: Any) -> list[str]:
    if not isinstance(period, dict):
        return ["period must be an object"]
    kind = period.get("kind")
    if kind not in PERIOD_KINDS:
        return [f"period.kind must be one of {', '.join(PERIOD_KINDS)}"]
    allowed = {"kind", "year", "month", "quarter", "start", "end"}
    errors = []
    if set(period) - allowed:
        errors.append("period has an unknown field")
    if kind == "point":
        if not _year(period.get("year")):
            errors.append("a point period needs a year")
    elif kind == "range":
        if not _year((period.get("start") or {}).get("year") if isinstance(period.get("start"), dict) else None):
            errors.append("a range needs a start year")
        if not _year((period.get("end") or {}).get("year") if isinstance(period.get("end"), dict) else None):
            errors.append("a range needs an end year")
    return errors


def _year(value: Any) -> bool:
    return isinstance(value, int) and 1800 <= value <= 2100


def parse_request(question: str) -> dict:
    """Deterministic parse. Digits from the question land only in `period`."""
    text = question or ""
    folded = fold(text)
    analysis = analyze(text)
    language = analysis.language
    filters = _filters(text, folded, analysis)
    period = _period(text)
    op = _op(folded, text)
    measure = _measure(analysis, filters)
    unit_hint = _unit(folded, op)
    payload = {
        "measure": measure,
        "filters": filters,
        "period": period,
        "op": op,
        "unit_hint": unit_hint,
    }
    payload["_language"] = language  # stripped before validation
    errors = validate_request({key: payload[key] for key in KEYS})
    if errors:
        raise ParseError("; ".join(errors))
    return payload


def _filters(text: str, folded: str, analysis) -> dict[str, list[str]]:
    """Values as they were said, not codes."""
    filters: dict[str, list[str]] = {}
    concepts = set(analysis.concepts)
    if "sex_female" in concepts:
        filters["sex"] = [_surface(text, ("konur", "kona", "stúlkur", "women", "woman", "girls", "female"), "women")]
    elif "sex_male" in concepts:
        filters["sex"] = [_surface(text, ("karlar", "karl", "drengir", "men", "boys", "male"), "men")]
    if any(word in folded for word in ("utlending", "foreigner")):
        filters.setdefault("citizenship", []).append(
            _surface(text, ("útlendinga", "útlendingar", "foreigners", "foreigner"), "foreigners")
        )
    return filters


def _surface(text: str, options: tuple[str, ...], default: str) -> str:
    lowered = text.lower()
    for option in options:
        if option.lower() in lowered:
            return option
    return default


def _period(text: str) -> dict:
    spans = [
        span for span in parse_dates(text)
        if span.year or span.end_year
    ]
    ranged = next((span for span in spans if span.kind == "between_years" and span.year and span.end_year), None)
    if ranged is not None:
        return {"kind": "range", "start": {"year": int(ranged.year)}, "end": {"year": int(ranged.end_year)}}
    point = next((span for span in spans if span.year), None)
    if point is None:
        return {"kind": "latest"}
    payload: dict[str, Any] = {"kind": "point", "year": int(point.year)}
    if getattr(point, "month", None):
        payload["month"] = int(point.month)
    if getattr(point, "quarter", None):
        payload["quarter"] = int(point.quarter)
    return payload


def _op(folded: str, text: str) -> str:
    if len(_clauses(text)) >= 2:
        return "compare"
    if re.search(r"\b(hve|hversu)\s+\S+\s+hlutfall\b", folded) or re.search(
        r"\b(what\s+(share|proportion|percentage|percent)\s+of|percent\s+of)\b", folded
    ):
        return "share"
    if re.search(r"\b(by what percent|um hve m\w+ prosent|percent change|prosentubreyting)\b", folded):
        return "pct_change"
    if re.search(r"\b(by how much|hve mikid|how much did|difference|mismunur)\b", folded) or re.search(
        r"\b(haekk|laekk|rose|fell|increas|decreas)\b", folded
    ):
        return "change" if "percent" not in folded and "prosent" not in folded else "pct_change"
    if re.search(r"\b(together|samtals)\b", folded) and re.search(r"\b(and|og)\b", folded):
        return "sum"
    return "level"


def _measure(analysis, filters: dict[str, list[str]]) -> str:
    skip = set(STOP)
    for values in filters.values():
        for value in values:
            skip.update(fold(value).split())
    words = []
    for term in analysis.terms:
        if term in skip or len(term) <= 2 or any(ch.isdigit() for ch in term):
            continue
        if term not in words:
            words.append(term)
    if not words:
        for concept in analysis.concepts:
            if concept not in words:
                words.append(concept.replace("_", " "))
    return " ".join(words[:8])


def _unit(folded: str, op: str) -> str:
    if op in {"share", "pct_change"}:
        return "percent"
    if "visital" in folded or "index" in folded:
        return "index"
    if any(word in folded for word in ("people", "population", "mannfjold", "born", "death", "danir", "nemend")):
        return "persons"
    return ""
