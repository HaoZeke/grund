"""All arithmetic lives here. The language model never adds.

Inputs are the strings PxWeb returned. Decimal keeps 630.3 as 630.3 instead
of a binary float. Callers register the formatted result on the allow-list
before it is written into a sentence.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


class ArithmeticError(ValueError):
    pass


def to_decimal(raw: str) -> Decimal:
    text = str(raw).strip().replace(" ", "").replace("\u00a0", "")
    if text in {"", ".", "..", "...", "-", ":", "…"}:
        raise ArithmeticError(f"missing figure {raw!r}")
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    elif text.count(".") > 1 and "," not in text:
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ArithmeticError(f"not a number: {raw!r}") from exc


def difference(current: str, previous: str) -> Decimal:
    return to_decimal(current) - to_decimal(previous)


def yoy_percent(current: str, previous: str) -> Decimal:
    """Percent change. Raises if the base is zero."""
    current_value = to_decimal(current)
    previous_value = to_decimal(previous)
    if previous_value == 0:
        raise ArithmeticError("cannot compute a percent change from zero")
    return (current_value - previous_value) / previous_value * Decimal(100)


def share_percent(part: str, whole: str) -> Decimal:
    """Percent of a partition. A part larger than the whole is not a share.

    Official rates that can exceed 100 (a price index, a participation rate)
    are published cells and must be cited as a level, not passed through here.
    """
    whole_value = to_decimal(whole)
    part_value = to_decimal(part)
    if whole_value == 0:
        raise ArithmeticError("cannot compute a share of zero")
    if part_value < 0 or whole_value < 0:
        raise ArithmeticError("a share needs non-negative counts")
    if part_value > whole_value:
        raise ArithmeticError("the part is larger than the whole, so this is not a share")
    return part_value / whole_value * Decimal(100)


def rebase(value: str, base_value: str, base: str = "100") -> Decimal:
    """Rescale an index so that base_value becomes `base` (usually 100)."""
    base_level = to_decimal(base_value)
    if base_level == 0:
        raise ArithmeticError("cannot rebase from zero")
    return to_decimal(value) / base_level * to_decimal(base)


def per_capita(value: str, population: str, per: str = "1") -> Decimal:
    people = to_decimal(population)
    if people == 0:
        raise ArithmeticError("cannot divide by a population of zero")
    return to_decimal(value) / people * to_decimal(per)


def scale_by_unit(value: str, unit_text: str | None) -> Decimal:
    """Apply a unit only when the label is unambiguous.

    'Thousands' and 'þúsund' multiply by 1000. Anything else, including
    'index' or a label we do not recognise, is left untouched.
    """
    amount = to_decimal(value)
    if not unit_text:
        return amount
    folded = unit_text.lower()
    if any(marker in folded for marker in ("thousand", "þúsund", "thusund", "1000")):
        return amount * Decimal(1000)
    if any(marker in folded for marker in ("million", "milljón", "milljon")):
        return amount * Decimal(1_000_000)
    return amount


def quantize(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    rendered = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return format(rendered, "f")


def format_stat(raw: str, language: str) -> str:
    """Group thousands. Keep every fractional digit PxWeb sent."""
    amount = to_decimal(raw)
    text = format(amount, "f")
    if "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
    else:
        whole, fraction = text, ""
    sign = ""
    if whole.startswith("-"):
        sign = "-"
        whole = whole[1:]
    grouped = f"{int(whole):,}"
    if language == "is":
        grouped = grouped.replace(",", ".")
        if fraction:
            return f"{sign}{grouped},{fraction}"
        return f"{sign}{grouped}"
    if fraction:
        return f"{sign}{grouped}.{fraction}"
    return f"{sign}{grouped}"
