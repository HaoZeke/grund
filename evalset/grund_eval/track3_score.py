"""Whether an answer states the expected numbers, from the track-3 scorer.

The comparison is the one in the starter kit: a number counts when it is written
plainly or with thousands separators, in either language's style or with spaces,
rounded to no fewer digits than the written form shows. A sign is ignored.
"""

from __future__ import annotations

import re
from contextlib import suppress

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SPACED_NUMBER = re.compile(r"(?<!\d)\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+(?:[.,]\d+)?(?!\d)")


def states_number(text: str, expected: float) -> bool:
    target = abs(expected)
    spaced = ["".join(number.split()) for number in _SPACED_NUMBER.findall(text)]
    for written in [*_NUMBER.findall(text), *spaced]:
        for value, decimals in _readings(written):
            if abs(value - target) <= 0.5 * 10**-decimals + 1e-9:
                return True
    return False


def _readings(written: str) -> list[tuple[float, int]]:
    readings = []
    for thousands, decimal in ((",", "."), (".", ",")):
        with suppress(ValueError):
            plain = written.replace(thousands, "")
            if plain.endswith(decimal + "0") and plain.count(decimal) == 1:
                plain = plain[: -(len(decimal) + 1)]
            decimals = len(plain.split(decimal)[1]) if decimal in plain else 0
            readings.append((float(plain.replace(decimal, ".")), decimals))
    return readings


_INPUT_CLAUSE = re.compile(
    r"(The part is|Hlutinn er|That is the change from|Það er breyting úr|The calculation takes|Útreikningurinn tekur)\b.*",
    re.IGNORECASE,
)


def stated_answer(text: str) -> str:
    """Drop derived-input clauses. Those numbers are not the claimed figure."""
    return _INPUT_CLAUSE.sub("", text or "")


def _claimed_number(claimed) -> float | None:
    if claimed in (None, ""):
        return None
    try:
        return float(str(claimed).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def answer_is_right(
    question: dict, text: str, tables: list[str], claimed=None
) -> tuple[bool, bool, bool]:
    """Return (numbers_right, tables_right, correct) for one track-3 question.

    The credited figure is the claimed value. A gold number that only appears
    as an input in the same sentence ("the part is 63.7 of 65.3") does not count.
    """
    golds = [float(item["value"]) for item in question.get("answers") or []]
    value = _claimed_number(claimed)
    if value is not None and golds:
        if len(golds) == 1:
            numbers_right = states_number(str(value), golds[0])
        else:
            body = stated_answer(text)
            numbers_right = any(states_number(str(value), gold) for gold in golds) and all(
                states_number(body, gold) for gold in golds
            )
    else:
        numbers_right = all(_expected_stated(stated_answer(text), item) for item in question.get("answers") or [])
    used = {table.removesuffix(".px") for table in tables}
    tables_right = all(used & set(part.get("accepted") or [part["table"]]) for part in question["parts"])
    return numbers_right, tables_right, numbers_right and tables_right


def _expected_stated(text: str, item: dict) -> bool:
    values = [float(item["value"])]
    values.extend(float(other["value"]) for other in item.get("also") or [])
    return any(states_number(text, value) for value in values)
