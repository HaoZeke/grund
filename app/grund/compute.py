"""Turn a PxWeb JSON payload into cells and derived figures."""

from __future__ import annotations

import re
from decimal import Decimal

from grund.arithmetic import (
    ArithmeticError,
    difference,
    format_stat,
    per_capita,
    quantize,
    rebase,
    share_percent,
    to_decimal,
    yoy_percent,
)
from grund.bind import Binding
from grund_index.model import Edition
from grund_index.textutil import fold

_PRELIMINARY = ("preliminary", "provisional", "bradabirg", "oendurskod")
_REVISED = ("revised", "endurskod", "leidrett")


def _input_places(raw: str) -> int:
    """Fractional digits PxWeb sent. A difference keeps that many, not one."""
    text = str(raw).strip()
    if "." not in text:
        return 0
    fraction = text.split(".")[-1]
    return len(fraction) if fraction else 0


def extract_rows(payload: dict, edition: Edition) -> list[dict]:
    from grund.bind2 import is_jsonstat, pxjson_from_jsonstat

    if is_jsonstat(payload):
        payload = pxjson_from_jsonstat(payload)
    columns = [column for column in payload.get("columns") or [] if column.get("type") != "c"]
    rows = []
    for item in payload.get("data") or []:
        key = [str(part) for part in item.get("key") or []]
        mapping = {}
        labels = []
        for column, code in zip(columns, key):
            variable = edition.variable(column.get("code") or "")
            label = variable.label(code) if variable else code
            mapping[str(column.get("code"))] = code
            labels.append(
                {
                    "variable": column.get("code"),
                    "variable_text": column.get("text"),
                    "code": code,
                    "label": label,
                }
            )
        values = item.get("values") or [None]
        rows.append({"key": key, "map": mapping, "value": values[0], "labels": labels})
    return rows


def footnotes(payload: dict) -> list[dict]:
    notes = []
    for comment in payload.get("comments") or []:
        text = (comment.get("comment") or "").strip()
        if text:
            notes.append(
                {
                    "variable": comment.get("variable"),
                    "value": comment.get("value"),
                    "text": text,
                }
            )
    return notes


def release_flags(*chunks: str) -> dict[str, bool]:
    blob = fold(" ".join(chunk for chunk in chunks if chunk))
    return {
        "preliminary": any(marker in blob for marker in _PRELIMINARY),
        "revised": any(marker in blob for marker in _REVISED),
    }


def _usable(row: dict) -> bool:
    try:
        to_decimal(row["value"])
    except (ArithmeticError, TypeError):
        return False
    return True


def _percent_string(value: Decimal) -> str:
    places = 1 if abs(value) >= Decimal("1") else 2
    return quantize(value, places)


def compute(rows: list[dict], binding: Binding, population: dict | None = None) -> dict:
    usable = [row for row in rows if _usable(row)]
    if not usable:
        raise ArithmeticError("the table returned no numeric cells for this selection")
    operation = binding.operation
    derived = None
    used = usable
    primary_raw = usable[0]["value"]

    if operation == "level":
        used = usable[:1] if len(usable) == 1 else _preferred_rows(usable, binding)
        primary_raw = used[0]["value"]
    elif operation == "difference" and binding.group_var and len(binding.time_codes) < 2:
        part, other = _pair(usable, binding)
        used = [part, other]
        value = difference(part["value"], other["value"])
        places = max(_input_places(part["value"]), _input_places(other["value"]), 1)
        rendered = format(value, "f") if value == value.to_integral() else quantize(value, places)
        derived = {
            "name": "difference",
            "value": rendered,
            "formula": "first category minus second category",
            "inputs": [part["value"], other["value"]],
        }
        primary_raw = rendered
    elif operation == "sum":
        part, other = _pair(usable, binding)
        used = [part, other]
        value = to_decimal(part["value"]) + to_decimal(other["value"])
        rendered = quantize(value, 1) if value != value.to_integral() else format(value, "f")
        derived = {
            "name": "sum",
            "value": rendered,
            "formula": "first category plus second category",
            "inputs": [part["value"], other["value"]],
        }
        primary_raw = rendered
    elif operation in {"yoy_pct", "difference"}:
        ordered = _order_by_time(usable, binding)
        if len(ordered) < 2:
            raise ArithmeticError("need two periods to compute a change")
        earlier, later = ordered[0], ordered[-1]
        used = [earlier, later]
        if operation == "yoy_pct":
            value = yoy_percent(later["value"], earlier["value"])
            rendered = _percent_string(value)
            derived = {
                "name": "yoy_pct",
                "value": rendered,
                "formula": "((later - earlier) / earlier) * 100",
                "inputs": [earlier["value"], later["value"]],
            }
            primary_raw = rendered
        else:
            value = difference(later["value"], earlier["value"])
            places = max(_input_places(earlier["value"]), _input_places(later["value"]), 1)
            rendered = format(value, "f") if value == value.to_integral() else quantize(value, places)
            derived = {
                "name": "difference",
                "value": rendered,
                "formula": "later - earlier",
                "inputs": [earlier["value"], later["value"]],
            }
            primary_raw = rendered
    elif operation == "share":
        part, whole = _pair(usable, binding)
        used = [part, whole]
        value = share_percent(part["value"], whole["value"])
        rendered = _percent_string(value)
        derived = {
            "name": "share_percent",
            "value": rendered,
            "formula": "(part / whole) * 100",
            "inputs": [part["value"], whole["value"]],
        }
        primary_raw = rendered
    elif operation == "rebase":
        base_row, target_row = _rebase_rows(usable, binding)
        used = [base_row, target_row]
        value = rebase(target_row["value"], base_row["value"])
        rendered = _percent_string(value)
        derived = {
            "name": "rebase",
            "value": rendered,
            "formula": "(value / base_period) * 100",
            "inputs": [target_row["value"], base_row["value"]],
        }
        primary_raw = rendered
    elif operation == "per_capita":
        if population is None:
            raise ArithmeticError("no population figure was fetched for a per-capita question")
        used = [usable[0], population]
        value = per_capita(usable[0]["value"], population["value"])
        rendered = quantize(value, 4)
        derived = {
            "name": "per_capita",
            "value": rendered,
            "formula": "value / population",
            "inputs": [usable[0]["value"], population["value"]],
        }
        primary_raw = rendered
    else:
        raise ArithmeticError(f"unknown operation {operation}")

    return {"primary_raw": str(primary_raw), "rows": used, "derived": derived}


def _preferred_rows(rows: list[dict], binding: Binding) -> list[dict]:
    """When a query returns several cells, keep the ones named first in each selection."""
    preferred = {
        entry["code"]: entry["selection"]["values"][0]
        for entry in binding.selections
        if entry["selection"]["values"]
    }
    matched = [
        row
        for row in rows
        if all(row["map"].get(code) == value for code, value in preferred.items())
    ]
    return matched or rows[:1]


def _order_by_time(rows: list[dict], binding: Binding) -> list[dict]:
    order = {code: index for index, code in enumerate(binding.time_codes)}
    return sorted(rows, key=lambda row: order.get(row["map"].get(binding.time_var or ""), 0))


def _pair(rows: list[dict], binding: Binding) -> tuple[dict, dict]:
    part = whole = None
    for row in rows:
        code = row["map"].get(binding.group_var or "")
        if code == binding.part_code:
            part = row
        elif code == binding.whole_code:
            whole = row
    if part is None or whole is None:
        raise ArithmeticError("the share query did not return both the part and the total")
    return part, whole


def _rebase_rows(rows: list[dict], binding: Binding) -> tuple[dict, dict]:
    base = target = None
    for row in rows:
        code = row["map"].get(binding.time_var or "")
        if code == binding.rebase_code:
            base = row
        elif code == binding.target_code:
            target = row
    if base is None or target is None:
        raise ArithmeticError("the rebase query did not return both periods")
    return base, target


def allowed_numbers(rows: list[dict], derived: dict | None, population: dict | None = None) -> list[float]:
    allowed: list[float] = []
    pool = list(rows)
    if population is not None:
        pool.append(population)
    for row in pool:
        try:
            value = float(to_decimal(row["value"]))
        except ArithmeticError:
            continue
        allowed.append(value)
        # The prose writes a magnitude. The number finder drops a leading hyphen.
        allowed.append(abs(value))
        for part in row.get("key") or []:
            for year in re.findall(r"(?:17|18|19|20)\d{2}", str(part)):
                allowed.append(float(year))
        for label in row.get("labels") or []:
            text = f"{label.get('label', '')} {label.get('code', '')}"
            for match in re.findall(r"\d+(?:[.,]\d+)?", text):
                try:
                    allowed.append(float(to_decimal(match)))
                except ArithmeticError:
                    continue
    if derived:
        try:
            derived_value = float(to_decimal(derived["value"]))
            allowed.append(derived_value)
            # The prose writes a magnitude. The number finder drops a leading hyphen.
            allowed.append(abs(derived_value))
        except ArithmeticError:
            pass
        for raw in derived.get("inputs") or []:
            try:
                raw_value = float(to_decimal(raw))
            except ArithmeticError:
                continue
            allowed.append(raw_value)
            allowed.append(abs(raw_value))
    return allowed
