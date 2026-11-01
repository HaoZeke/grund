"""Reject a PxWeb query that the table's own metadata does not allow.

The check runs before the POST. A model that emits a code the table does
not have is told the legal codes and asked again; it is not given the
benefit of a fuzzy match at request time.
"""

from __future__ import annotations

import math
from typing import Iterable

from grund.bind import acceptable_time_value
from grund_index.client import MAX_CELLS, MAX_VALUES
from grund_index.model import Edition, Variable

FILTERS = {"item", "all", "top", "bottom"}


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _find(edition: Edition, code: str) -> Variable | None:
    for variable in edition.variables:
        if variable.code == code:
            return variable
    return None


def validate(edition: Edition, selections: list[dict]) -> None:
    """selections is a PxWeb `query` list: {code, selection: {filter, values}}."""
    errors: list[str] = []
    seen: set[str] = set()
    sizes: list[int] = []
    for entry in selections:
        code = entry.get("code")
        selection = entry.get("selection") or {}
        filt = selection.get("filter") or "item"
        values = [str(value) for value in selection.get("values") or []]
        if not code:
            errors.append("a selection is missing its variable code")
            continue
        if code in seen:
            errors.append(f"variable {code} is selected twice")
            continue
        seen.add(code)
        variable = _find(edition, code)
        if variable is None:
            legal = ", ".join(item.code for item in edition.variables)
            errors.append(f"unknown variable {code}. Legal codes: {legal}")
            continue
        if filt not in FILTERS:
            errors.append(f"{code}: filter {filt} is not one of {sorted(FILTERS)}")
            continue
        legal_values = set(variable.codes())
        if filt == "item":
            if not values:
                errors.append(f"{code}: item filter needs at least one value")
                continue
            unknown = [
                value
                for value in values
                if value not in legal_values and not acceptable_time_value(variable, value)
            ]
            if unknown:
                sample = ", ".join(list(legal_values)[:12])
                errors.append(f"{code}: unknown values {unknown}. Examples: {sample}")
                continue
            if len(values) > MAX_VALUES:
                errors.append(f"{code}: {len(values)} values exceeds maxValues {MAX_VALUES}")
            sizes.append(len(values))
        elif filt in {"top", "bottom"}:
            if len(values) != 1 or not values[0].isdigit() or int(values[0]) < 1:
                errors.append(f"{code}: {filt} filter takes one positive integer")
                continue
            count = int(values[0])
            if count > len(variable.values):
                errors.append(f"{code}: asked for {count} {filt} values, table has {len(variable.values)}")
                continue
            sizes.append(count)
        elif filt == "all":
            sizes.append(len(variable.values))
    for variable in edition.variables:
        if variable.code in seen:
            continue
        if variable.elimination:
            sizes.append(1)
        else:
            sizes.append(len(variable.values))
            if len(variable.values) > 1:
                errors.append(
                    f"variable {variable.code} is not eliminable and was not selected "
                    f"({len(variable.values)} values). Select it explicitly."
                )
    if sizes:
        cells = math.prod(sizes)
        if cells > MAX_CELLS:
            errors.append(f"query would return about {cells} cells, above maxCells {MAX_CELLS}")
    if errors:
        raise ValidationError(errors)


def query_body(selections: Iterable[dict]) -> dict:
    from grund.bind2 import response_format

    return {"query": list(selections), "response": {"format": response_format()}}
