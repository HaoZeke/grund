"""Refuse a stated subgroup the mapper did not select.

GRUND_SUBGROUP_GUARD is off unless set. This never chooses a replacement
cell. A mapper total, or no mapper query, is a disagreement when the
question names a sex, an age band, or a place. The stated table also has
to be that measure: the activity sheet is not the employment-rate table,
avoidable deaths are not plain deaths, and a line-of-study graduation
table is not the matriculation count.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_ON = {"1", "true", "yes", "on"}
_SKIP = re.compile(
    r"(percentage|percent of|prosentubreyting|by how much|rise from|haekk|laekk)"
)
_MALE = re.compile(r"\b(men|males?|boys?|karl|karlar|karla|korlum|dreng)\b")
_FEMALE = re.compile(r"\b(women|woman|females?|girls?|kona|konur|kvenna|stulk)\b")
_AGE = re.compile(
    r"(\byouth\b|\byoung people\b|\bungmenni\b|\baged\b|"
    r"\b\d{1,2}\s*-\s*\d{1,2}\b.{0,24}\b(age|aldur|ara|years?)\b|"
    r"\b(age|aldur|ara|years?)\b.{0,24}\b\d{1,2}\s*-\s*\d{1,2}\b)"
)
_TOTAL = {
    "total", "totals", "alls", "samtals", "all", "allt", "allir",
    "males and females", "karlar og konur", "both sexes", "16-74", "16-74 ara",
}


def enabled() -> bool:
    return os.environ.get("GRUND_SUBGROUP_GUARD", "").strip().lower() in _ON


def guard_reason(engine, parsed, result: dict) -> str | None:
    """A refusal detail, or None to keep the stated figure."""
    if not enabled() or parsed is None or not result:
        return None
    if result.get("refused") or result.get("value") in (None, ""):
        return None
    question = parsed.text or ""
    text = fold(question)
    if not text or _SKIP.search(text):
        return None
    kinds = _named(text)
    edition = _edition(engine, parsed, result)
    if edition is not None:
        kinds = {kind for kind in kinds if _edition_has(edition, kind)}
    if not kinds:
        return None
    if _measure_conflict(text, _title(result)):
        return "subgroup-guard:measure"
    if edition is None:
        return "subgroup-guard:table"
    selected = _mapper_selection(edition, question, text, kinds)
    if selected is None:
        return "subgroup-guard:mapper"
    if not _stated_matches(result, selected, text):
        return "subgroup-guard:cell"
    return None


def _named(text: str) -> set[str]:
    male = bool(_MALE.search(text))
    female = bool(_FEMALE.search(text))
    kinds: set[str] = set()
    if male ^ female:
        kinds.add("sex")
    if _AGE.search(text):
        kinds.add("age")
    if _place(text):
        kinds.add("place")
    return kinds


def _place(text: str) -> bool:
    if "capital region" in text or "hofudborgarsvaed" in text:
        return True
    if re.search(r"\bthe capital\b", text) or "hofudborg" in text:
        return True
    return bool(re.search(
        r"\b(reykjavik|kopavog|akureyri|hafnarfj|sudurland|nordurland|austurland|vesturland|vestfird|"
        r"south|northeast|northwest|southwest|westfjords|east iceland)\b",
        text,
    ))


def _measure_conflict(text: str, title: str) -> bool:
    """The stated title is a different measure from the question."""
    folded = fold(title)
    if not folded:
        return False
    death = bool(re.search(r"\b(died|deaths?|death rate)\b", text) or re.search(r"\b(dou|danir|danartidn)\b", text))
    if death and not re.search(r"(avoidable|premature|otimab)", text):
        if re.search(r"(avoidable|premature|otimab)", folded):
            return True
        if not re.search(r"(death|died|danir|daud|danar)", folded):
            return True
    employment = "employment rate" in text or "hlutfall starfandi" in text
    if employment and not re.search(r"(unemploy|atvinnuleys)", text):
        if re.search(r"(unemploy|atvinnuleys)", folded) and re.search(r"(activit|atvinnuthatt|student|namsmenn|cultur|menning)", folded):
            return True
    matriculation = "matriculation" in text or "studentsprof" in text
    if matriculation and not re.search(r"(line of study|namsleid|type of examination|tegund students)", text):
        if re.search(r"(line of study|namsleid|type of examination|tegund students)", folded):
            return True
    return False


def _mapper_selection(edition, question: str, text: str, kinds: set[str]) -> dict[str, str] | None:
    """Variable label the tool mapper picks for each named subgroup.

    None means the mapper has no query, or it stayed on a total.
    """
    from grund.toolpath import edition_payload
    from grund_lang.pxtools import _best_filter

    variables = _without_totals(edition_payload(edition)["variables"])
    used: set[str] = set()
    chosen: dict[str, str] = {}
    for kind, said in _sayings(text, kinds):
        hit = _best_filter(variables, said, set(used))
        if hit is None:
            return None
        code, value_code = hit
        label = _label(variables, code, value_code)
        if not label or _is_total(label) or not _label_ok(text, kind, label):
            return None
        chosen[code] = label
        used.add(code)
    if len(chosen) < len(kinds):
        return None
    return chosen


def _without_totals(variables: list[dict]) -> list[dict]:
    cleaned = []
    for variable in variables:
        values = [(code, label) for code, label in variable.get("values") or [] if not _is_total(str(label))]
        cleaned.append({**variable, "values": values})
    return cleaned


def _sayings(text: str, kinds: set[str]) -> list[tuple[str, str]]:
    said: list[tuple[str, str]] = []
    if "sex" in kinds:
        said.append(("sex", "women" if _FEMALE.search(text) else "men"))
    if "age" in kinds:
        match = re.search(r"\b(\d{1,2})\s*-\s*(\d{1,2})\b", text)
        if match:
            said.append(("age", f"{match.group(1)}-{match.group(2)}"))
        elif re.search(r"(youth|young people|ungmenni)", text):
            said.append(("age", "16-24"))
        else:
            aged = re.search(r"\baged\s+(\d{1,3})\b|\b(\d{1,3})\s*-\s*year", text)
            if aged:
                number = aged.group(1) or aged.group(2)
                said.append(("age", f"{number} year"))
    if "place" in kinds:
        said.append(("place", _place_saying(text)))
    return said


def _place_saying(text: str) -> str:
    if "capital region" in text or "hofudborgarsvaed" in text:
        return "Capital region"
    if re.search(r"\bthe capital\b", text) or ("hofudborg" in text and "hofudborgarsvaed" not in text):
        return "Reykjavik"
    for name in ("reykjavik", "kopavog", "akureyri", "hafnarfj", "south", "northeast", "northwest", "southwest"):
        if name in text:
            return name
    return text


def _stated_matches(result: dict, selected: dict[str, str], text: str) -> bool:
    """The stated labels are the subgroup the mapper picked.

    English 'Males' and Icelandic 'Karlar' are the same selection.
    """
    blob = " ".join(fold(value) for _key, value in _label_pairs(result))
    for label in selected.values():
        if re.search(r"(female|woman|women|kona|konur|male|man|men|karl|dreng|girl|stulk|boy)", fold(label)):
            if not _label_ok(text, "sex", blob):
                return False
            continue
        folded = fold(label)
        if folded in blob:
            continue
        numbers = re.findall(r"\d{1,2}", folded)
        if numbers and all(re.search(rf"\b{number}\b", blob) for number in numbers):
            continue
        return False
    return True


def _label_ok(text: str, kind: str, label: str) -> bool:
    folded = fold(label)
    if kind == "sex":
        if _FEMALE.search(text):
            return bool(re.search(r"(female|woman|women|kona|konur|stulk|girl)", folded))
        return bool(re.search(r"(male|man|men|karl|dreng|boy)", folded)) and "female" not in folded
    if kind == "age":
        match = re.search(r"\b(\d{1,2})\s*-\s*(\d{1,2})\b", text)
        if match:
            return match.group(1) in folded and match.group(2) in folded
        return True
    return True


def _is_total(label: str) -> bool:
    folded = fold(label).strip()
    if folded in _TOTAL or folded.startswith("total") or folded.startswith("alls"):
        return True
    return False


def _label(variables: list[dict], code: str, value_code: str) -> str:
    for variable in variables:
        if variable["code"] != code:
            continue
        for item, label in variable.get("values") or []:
            if str(item) == str(value_code):
                return str(label)
    return ""


def _edition_has(edition, kind: str) -> bool:
    for variable in edition.variables:
        name = fold(f"{variable.text} {variable.code}")
        if kind == "sex" and any(piece in name for piece in ("kyn", "sex", "gender")):
            return True
        if kind == "age" and any(piece in name for piece in ("aldur", "age")):
            return True
        if kind == "place" and any(piece in name for piece in (
            "sveitarfelag", "municip", "landshlut", "region", "byggd",
        )):
            return True
    return False


def _edition(engine, parsed, result: dict):
    catalogue = getattr(engine, "catalogue", None)
    if catalogue is None:
        return None
    stem = _stem(result.get("table_id"))
    table = None
    by_id = getattr(catalogue, "by_id", {}) or {}
    table = by_id.get(stem + ".px") or by_id.get(stem)
    if table is None:
        return None
    return table.edition(getattr(parsed, "language", None) or "en") or table.edition("en")


def _title(result: dict) -> str:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    if source.get("title"):
        return str(source["title"])
    for claim in result.get("claims") or []:
        for cell in claim.get("cells") or []:
            if cell.get("title"):
                return str(cell["title"])
    return ""


def _label_pairs(result: dict) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for claim in result.get("claims") or []:
        for cell in claim.get("cells") or []:
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                pairs.extend((str(key), str(value)) for key, value in labels.items())
            elif isinstance(labels, list):
                for item in labels:
                    if isinstance(item, dict):
                        pairs.append((str(item.get("variable_text") or item.get("variable") or ""), str(item.get("label") or "")))
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        for item in cell.get("labels") or []:
            if isinstance(item, dict):
                pairs.append((str(item.get("variable_text") or item.get("variable") or ""), str(item.get("label") or "")))
    return pairs


def _stem(table_id) -> str:
    return str(table_id or "").removesuffix(".px")
