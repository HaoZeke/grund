"""Stop the coverage gates from stating a neighbouring figure.

``GRUND_REDTEAM2`` is off unless it is ``1``, ``true``, ``yes``, or ``on``.
The coverage flags stay as they are when this is unset. When it is on, a
stated figure is replaced only in the cases the paraphrase bank showed:

- a population table for a question about jobs, births, or deaths
- current-price GDP when the question says constant prices
- the annual wage-index change when the question says the monthly change
- all-citizenship overnight stays when the question says Icelandic residents
- the national sex total when the question names one town
- a region when the question names a town and sets the region aside
- both sexes when the question names one sex
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_TOWNS = (
    "akureyr", "kopavog", "hafnarfj", "gardaba", "reykjav", "isafj", "reykjanesb",
    "akranes", "arborg", "sudurnesjab", "vestmannaey", "hornafj", "seltjarnarn",
    "grindav",
)
_NOT_POPULATION = (
    "employ", "starfand", "atvinnu", "unemploy", "atvinnulaus", "atvinnuleys",
    "birth", "faed", "faeding", "fetal", "andvana", "death", "danir",
    "gistin", "overnight", "arrival", "gestakom",
    "launavis", "wage index", "neysluverd", "consumer price",
    "landsframleid", "gross domestic",
)
_ONE_SEX = (
    (r"\b(women|woman|females?|konur|konum|kvenna|kven)\b", "female"),
    (r"\b(men|males?|karlar|karla|korlum|dreng)\b", "male"),
)
_BOTH = ("males and females", "karlar og konur", "both sexes", "alls kyn", "total")


def enabled() -> bool:
    return os.environ.get("GRUND_REDTEAM2", "").strip().lower() in {"1", "true", "yes", "on"}


def maybe_correct(engine, parsed, result: dict):
    """A replacement answer, a refusal reason, or None to keep the result."""
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return None
    text = fold(parsed.text)
    if _population_for_something_else(text, result):
        return "population table for a different question"
    if _constant_price(text) and _stem(result) == "THJ01102":
        replaced = _constant_gdp(engine, parsed, result)
        return replaced or "current prices are not constant prices"
    if _monthly_wage(text) and _labels_say(result, ("annual change", "arsbreyting")):
        replaced = _swap_unit(engine, parsed, result, ("monthly change", "manadarbreyting"))
        return replaced or "annual change is not the monthly change"
    if _icelandic_stays(text) and _labels_say(result, ("total", "alls")) and not _labels_say(result, ("iceland", "islend", "foreign", "erlend", "utlend")):
        replaced = _swap_unit(engine, parsed, result, ("iceland",))
        return replaced or "all citizenships are not Icelandic residents"
    if _town_before_not(text) and not _labels_have_town(text, result):
        return "the named town is not the cell"
    if _one_sex(text) and _labels_say(result, _BOTH) and not _labels_have_sex(text, result):
        return "both sexes where one sex was asked"
    return None


def _population_for_something_else(text: str, result: dict) -> bool:
    """A headcount table used for jobs, births, or deaths."""
    if _stem(result) not in {"MAN00101", "MAN00000"}:
        return False
    if any(mark in text for mark in ("mannfjold", "population", "ibuar", "ibuafjold", "bjuggu", "people lived", "people live")):
        return False
    return any(mark in text for mark in _NOT_POPULATION)


def _constant_price(text: str) -> bool:
    return any(mark in text for mark in ("constant price", "fostu verd", "fast verd", "a fostu"))


def _monthly_wage(text: str) -> bool:
    if "launavis" not in text and "wage index" not in text:
        return False
    return "monthly" in text or "manadar" in text


def _icelandic_stays(text: str) -> bool:
    if "gistin" not in text and "overnight" not in text:
        return False
    if any(mark in text for mark in ("foreign", "erlend", "utlend")):
        return False
    return "icelandic" in text or "islending" in text


def _town_before_not(text: str) -> str | None:
    head = re.split(r"\b(?:not|ekki)\b", text, maxsplit=1)[0]
    for stem in _TOWNS:
        if stem in head:
            return stem
    return None


def _one_sex(text: str) -> str | None:
    found = []
    for pattern, side in _ONE_SEX:
        if re.search(pattern, text):
            found.append(side)
    if len(found) == 1:
        return found[0]
    return None


def _stem(result: dict) -> str:
    return str(result.get("table_id") or "").split("#", 1)[0].removesuffix(".px")


def _label_blob(result: dict) -> str:
    parts = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        if isinstance(cell, dict):
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                parts.extend(str(value) for value in labels.values())
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                labels = cell.get("labels") or {}
                if isinstance(labels, dict):
                    parts.extend(str(value) for value in labels.values())
    parts.append(str(result.get("answer") or ""))
    return fold(" ".join(parts))


def _labels_say(result: dict, marks: tuple[str, ...]) -> bool:
    blob = _label_blob(result)
    return any(fold(mark) in blob for mark in marks)


def _labels_have_town(text: str, result: dict) -> bool:
    stem = _town_before_not(text)
    blob = _label_blob(result)
    return bool(stem) and stem in blob


def _labels_have_sex(text: str, result: dict) -> bool:
    side = _one_sex(text)
    blob = _label_blob(result)
    if any(mark in blob for mark in ("males and females", "karlar og konur", "both sexes")):
        return False
    if side == "female":
        return any(mark in blob for mark in ("female", "women", "woman", "konur", "kona", "stulk"))
    if side == "male":
        return any(mark in blob for mark in (" male", " men", "karl", "dreng"))
    return False


def _constant_gdp(engine, parsed, result: dict):
    if engine is None:
        return None
    years = re.findall(r"\b(?:19|20)\d{2}\b", parsed.text)
    if len(years) != 1:
        return None
    table = engine.catalogue.by_id.get("THJ01103.px") or engine.catalogue.by_id.get("THJ01103")
    if table is None:
        return None
    edition = table.edition(parsed.language) or table.edition("en") or table.edition("is")
    if edition is None:
        return None
    line = _value_code(edition, ("verg landsframleidsla", "gross domestic product"), reject=("expenditure", "utgjold"))
    year_var = edition.time_variable()
    if line is None or year_var is None:
        return None
    try:
        from grund.redteam_answer import _accept, _checked_produce
    except Exception:
        return None
    from grund.bind import Binding
    from grund.validator import validate

    selections = [
        {"code": line[0], "selection": {"filter": "item", "values": [line[1]]}},
        {"code": year_var.code, "selection": {"filter": "item", "values": [years[0]]}},
    ]
    try:
        validate(edition, selections)
    except Exception:
        return None
    binding = Binding(
        edition=edition,
        selections=selections,
        operation="level",
        score=0,
        time_var=year_var.code,
        time_codes=[years[0]],
        notes=["constant-price GDP"],
    )
    produced = _checked_produce(engine, parsed, binding, table)
    if produced is None:
        return None
    return _accept(engine, parsed, produced, result)


def _swap_unit(engine, parsed, result: dict, wanted: tuple[str, ...]):
    """Replace one selected label with the sibling the question named."""
    if engine is None:
        return None
    try:
        from grund.redteam_answer import _accept, _base_query, _checked_produce
    except Exception:
        return None
    from grund.bind import Binding
    from grund.validator import validate

    table, edition, selections = _base_query(engine, parsed, result)
    if table is None or edition is None:
        return None
    changed = False
    for entry in selections:
        variable = edition.variable(entry["code"])
        if variable is None or variable.time:
            continue
        chosen = {fold(variable.label(str(code))) for code in entry["selection"]["values"]}
        if any(any(fold(mark) in label for mark in wanted) for label in chosen):
            continue
        code = None
        for value_code, label in variable.values:
            folded = fold(str(label or ""))
            code_fold = fold(str(value_code))
            if wanted == ("iceland",):
                if folded in {"iceland", "islendingar"} or code_fold == "is":
                    code = value_code
                    break
                continue
            if any(fold(mark) in folded for mark in wanted):
                code = value_code
                break
        if code is None:
            continue
        entry["selection"]["values"] = [code]
        changed = True
    if not changed:
        return None
    try:
        validate(edition, selections)
    except Exception:
        return None
    binding = Binding(
        edition=edition,
        selections=selections,
        operation="level",
        score=0,
        time_var=None,
        time_codes=[],
        notes=["redteam2 retarget"],
    )
    produced = _checked_produce(engine, parsed, binding, table)
    if produced is None:
        return None
    return _accept(engine, parsed, produced, result)


def _value_code(edition, wanted: tuple[str, ...], reject: tuple[str, ...] = ()) -> tuple[str, str] | None:
    for variable in edition.variables:
        if variable.time:
            continue
        hits = []
        for code, label in variable.values:
            folded = fold(str(label or ""))
            if any(mark in folded for mark in reject):
                continue
            if any(mark in folded for mark in wanted):
                hits.append((variable.code, str(code)))
        if len(hits) == 1:
            return hits[0]
    return None
