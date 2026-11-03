"""The unit of a stated cell, from the table's own metadata.

PxWeb carries a unit in three places, most specific first: a classification
variable named Unit / Eining whose row is stated, the contents unit of a
JSON-stat or px-json response, and, when neither is published, the measure
the title names ("Population" in "Population by country of citizenship,
sex and age"). The last one is not a unit word such as "persons"; it is
what the table counts, which is all its metadata says.
"""

from __future__ import annotations

import re

from grund_index.textutil import fold, tokens

from grund.bind import aggregate_label, is_total

_UNIT_NAME = re.compile(r"^(unit|eining)$")


def _unit_row(cells: list[dict]) -> str:
    found: list[str] = []
    for cell in cells:
        for item in cell.get("labels") or []:
            if not isinstance(item, dict):
                continue
            name = fold(f"{item.get('variable_text') or ''}").strip() or fold(str(item.get("variable") or "")).strip()
            label = str(item.get("label") or "")
            if _UNIT_NAME.match(name) and label and not (is_total(label) or aggregate_label(label)):
                found.append(label)
    return ", ".join(dict.fromkeys(found))


def _published(payload: dict, cells: list[dict]) -> str:
    """The contents unit the response publishes for the stated content codes."""
    stated = {str(item.get("code")) for cell in cells for item in cell.get("labels") or [] if isinstance(item, dict)}
    found: list[str] = []
    for column in payload.get("columns") or []:
        if isinstance(column, dict) and column.get("type") == "c" and column.get("unit"):
            found.append(str(column["unit"]))
    dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else payload
    for dimension in (dataset.get("dimension") or {}).values() if isinstance(dataset.get("dimension"), dict) else ():
        units = ((dimension or {}).get("category") or {}).get("unit") if isinstance(dimension, dict) else None
        if not isinstance(units, dict):
            continue
        for code, unit in units.items():
            if (not stated or str(code) in stated or len(units) == 1) and isinstance(unit, dict) and unit.get("base"):
                found.append(str(unit["base"]))
    return ", ".join(dict.fromkeys(found))


def title_measure(edition) -> str:
    """The title's leading run of content words: the words before the first
    function word or the first word naming one of the table's variables."""
    from grund import row_guard

    names = [name for variable in edition.variables for name in tokens(variable.text or "")]
    kept: list[str] = []
    for word in re.findall(r"\S+", edition.title or ""):
        folded = re.findall(r"[a-z0-9]+", fold(word))
        if not folded or any(ch.isdigit() for ch in word):
            break
        if any(token in row_guard._GLUE for token in folded):
            break
        if any(row_guard._same(name, token) for name in names for token in folded):
            break
        kept.append(word)
    return " ".join(kept).strip(" ,:;")


def cell_unit(edition, payload: dict, cells: list[dict]) -> dict:
    row = _unit_row(cells)
    if row:
        return {"unit": row, "unit_from": "row"}
    published = _published(payload or {}, cells)
    if published:
        return {"unit": published, "unit_from": "published"}
    measure = title_measure(edition) if edition is not None else ""
    if measure:
        return {"unit": measure, "unit_from": "title"}
    return {"unit": "", "unit_from": ""}
