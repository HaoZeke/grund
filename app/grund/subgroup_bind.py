"""Refuse a stated figure whose cell misses a subgroup the question named.

A sex, an age band, a place, or a nationality has to be the same value on
the chosen cell. A total, or a different breakdown, is not that subgroup.
Table-title echoes ("what was X by sex and age") name dimensions, not values,
and are left to the gate that already handles them.

Off nowhere: this is the statement rule. It only refuses.
"""

from __future__ import annotations

import re

from grund.series_prefer import (
    _FEMALE,
    _MALE,
    _capital_scope,
    _dim_kind,
    _dim_pairs,
    _is_total_value,
    _names_age,
    _names_one_sex,
    _place,
    _stated_values,
)
from grund_index.textutil import fold

_TITLE_ECHO = re.compile(r"(\bwhat was\b|\bhver var\b|\bhvad var\b)")
_BY = re.compile(r"(\bby\b|\beftir\b)")
_NATIONALITY = re.compile(
    r"(citizen|citizenship|nationalit|rikisborg|thjoderni|rikisfang)"
)
_FOREIGN = re.compile(r"(\bforeign\b|\berlend)")
_SEX_MALE = re.compile(r"\b(males?|men|karl|karlar)\b")
_SEX_FEMALE = re.compile(r"\b(females?|women|woman|kona|konur)\b")


def bind_reason(question: str, result: dict) -> str | None:
    """A short reason when the chosen cell does not carry every named subgroup."""
    if not result or result.get("refused") or result.get("value") in (None, ""):
        return None
    text = fold(question or "")
    if _title_echo(text):
        return None
    grouped = _grouped(result)
    if _names_one_sex(text) and not _sex_matches(text, grouped["sex"]):
        return "subgroup-bind:sex"
    if _names_age(text) and _strict_count(text) and not _age_matches(text, grouped["age"]):
        return "subgroup-bind:age"
    if _named_place(text) and _strict_count(text) and not _place_matches(text, grouped["place"]):
        return "subgroup-bind:place"
    if _nationality_token(text) and not _nationality_matches(text, grouped["nationality"]):
        return "subgroup-bind:nationality"
    return None


def _title_echo(text: str) -> bool:
    """A pasted table title. 'By sex' there is the column, not men or women."""
    return bool(_TITLE_ECHO.search(text) and _BY.search(text))


def _grouped(result: dict) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"sex": [], "age": [], "place": [], "nationality": []}
    for key, value in _dim_pairs(result):
        kind = _dim_kind(key)
        if kind in found:
            found[kind].append(value)
        name = fold(key)
        if any(piece in name for piece in ("rikisfang", "thjoderni", "citizen", "nationalit", "faedingarland", "uppruni", "bakgrunn")):
            found["nationality"].append(value)
    return found


def _sex_matches(text: str, values: list[str]) -> bool:
    stated = _stated_values(values)
    if not stated or all(_sex_total(value) for value in stated):
        return False
    blob = fold(" ".join(stated))
    if _MALE.search(text) and not _FEMALE.search(text):
        return bool(_SEX_MALE.search(blob))
    if _FEMALE.search(text) and not _MALE.search(text):
        return bool(_SEX_FEMALE.search(blob))
    return True


def _sex_total(value: str) -> bool:
    folded = fold(value).strip()
    return _is_total_value(value) or folded in {"males and females", "karlar og konur", "both sexes"}


def _asked_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    for match in re.finditer(r"\b(\d{1,3})\s*-\s*(\d{1,3})\b", text):
        numbers.extend(match.groups())
    for match in re.finditer(r"\b(\d{1,3})\s*(?:-\s*)?(?:year|years|ara|ar)\b", text):
        numbers.append(match.group(1))
    if not numbers:
        match = re.search(r"\b(\d{1,3})\b.{0,16}\b(eldri|older|over)\b", text)
        if match:
            numbers.append(match.group(1))
    seen: list[str] = []
    for number in numbers:
        if number not in seen:
            seen.append(number)
    return seen


def _strict_count(text: str) -> bool:
    """A how-many question. A percent or a rise already names its own total."""
    if re.search(r"(prosent|percent|hlutfall|percentage|by how much|rise from|haekk|laekk)", text):
        return False
    return bool(re.search(r"(\bhow many\b|\bhve marg)", text))


def _named_place(text: str) -> bool:
    """A region or the capital. A station name or the word tonnes is not one."""
    return bool(_capital_scope(text) or _place(text))


def _age_matches(text: str, values: list[str]) -> bool:
    numbers = _asked_numbers(text)
    stated = _stated_values(values)
    if not numbers or not stated or all(_is_total_value(value) for value in stated):
        return False
    blob = fold(" ".join(stated))
    return all(re.search(rf"\b{number}\b", blob) for number in numbers)


def _place_matches(text: str, values: list[str]) -> bool:
    if not values:
        return True
    stated = _stated_values(values)
    if not stated or all(_is_total_value(value) for value in stated):
        return False
    blob = fold(" ".join(stated))
    scope = _capital_scope(text)
    if scope == "city":
        return "reykjavik" in blob and "capital region" not in blob and "hofudborgarsvaed" not in blob
    if scope == "region":
        return "capital region" in blob or "hofudborgarsvaed" in blob
    stem = _place(text)
    if stem == "the south":
        return "south" in blob and "southwest" not in blob
    if stem:
        token = stem.replace(" ", "")
        return stem in blob or token in blob
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) >= 6 and token in blob:
            return True
    return False


def _nationality_token(text: str) -> str:
    """A named nationality value. The column name 'citizenship' is not one."""
    if not _NATIONALITY.search(text):
        return ""
    if _FOREIGN.search(text):
        return "foreign"
    # 'Icelandic citizens' names Iceland. 'in Iceland' next to no citizen word does not.
    if re.search(r"\b(icelandic citizens|islenskir rikisborgarar|rikisborgarar islands)\b", text):
        return "iceland"
    return ""


def _nationality_matches(text: str, values: list[str]) -> bool:
    token = _nationality_token(text)
    stated = _stated_values(values)
    if not token or not stated or all(_is_total_value(value) for value in stated):
        return False
    blob = fold(" ".join(stated))
    if token == "foreign":
        return "foreign" in blob or "erlend" in blob
    if token == "iceland":
        return "iceland" in blob or "island" in blob
    return token in blob
