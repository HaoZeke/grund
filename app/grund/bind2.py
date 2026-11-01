"""Typed cell binding. Opt in with GRUND_BIND2=1.

Each PxWeb variable and value is classified from its code and its labels.
Unconstrained dimensions take the total, or are omitted when the variable
carries ``elimination``. ``latest`` is the newest period whose cell is a
number. A measure kind that contradicts the question drops the table.
Period phrases become the codes the table actually publishes.

A derived figure carries a derivation. The sentence names the two cells
and the table. The publisher is not credited for that calculation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from grund_index.textutil import fold

LATEST_WINDOW = 8
MAX_VALUES = 5_000
MAX_CELLS = 100_000
MAX_CALLS_PER_10S = 100
STAT_FORMAT = "json-stat2"

_EXACT_TOTAL = {
    "total", "totals", "all", "alls", "allt", "allir", "allar", "oll", "ollu",
    "samtals", "heild", "heildartala", "whole country", "entire country",
    "all regions", "allt landid", "oll landid", "national", "both sexes",
    "karlar og konur", "males and females", "all ages", "landid allt",
}
_OF_WHICH = ("of which", "thar af", "tharaf", "thereof", "whereof", "of whom")
_DIM_WORDS = {
    "total", "totals", "alls", "samtals", "heild", "year", "years", "month",
    "months", "quarter", "quarters", "sex", "gender", "age", "ages", "kyn",
    "aldur", "municipality", "sveitarfelag", "region", "landshluti", "country",
    "unit", "eining", "index", "visitala", "percent", "percentage", "hlutfall",
    "number", "fjoldi", "type", "tegund", "by", "eftir", "from", "fra",
}


def enabled() -> bool:
    return os.environ.get("GRUND_BIND2", "").strip().lower() in {"1", "true", "yes"}


_REPLACED = ("bind2-total:", "bind2-measure:", "bind2-periods:", "bind2-omit:", "bind2-latest")


def cell_was_replaced(notes) -> bool:
    """True when the retie wrote a different code than the one it was given."""
    if isinstance(notes, str):
        notes = [notes]
    text = " ".join(str(item) for item in (notes or []))
    return any(mark in text for mark in _REPLACED)


def counts_as_path_agreement(chosen: dict) -> bool:
    """A shared query is not a second reader when the retie replaced the cell.

    With the flag unset this is always true, so agreement is unchanged.
    """
    if not enabled():
        return True
    if chosen.get("bind2_replaced"):
        return False
    source = chosen.get("source") if isinstance(chosen.get("source"), dict) else {}
    notes = list(source.get("notes") or [])
    planner_notes = chosen.get("planner_notes")
    if isinstance(planner_notes, list):
        notes.extend(planner_notes)
    return not cell_was_replaced(notes)


# One retie per question. The other answer path posts this query.
_SHARED: dict[str, dict] = {}


def remember_query(question: str, table_id: str, binding) -> None:
    """Store the retied query so both paths fetch the same cells."""
    if not enabled() or binding is None:
        return
    _SHARED[question] = {
        "table_id": str(table_id).removesuffix(".px"),
        "selections": [dict(entry) for entry in binding.selections],
        "operation": binding.operation,
        "time_var": binding.time_var,
        "time_codes": list(binding.time_codes or []),
        "group_var": binding.group_var,
        "part_code": binding.part_code,
        "whole_code": binding.whole_code,
        "rebase_code": binding.rebase_code,
        "target_code": binding.target_code,
        "notes": list(binding.notes or []),
        "official_measure": bool(binding.official_measure),
        "score": binding.score,
    }


def shared_binding(question: str, edition, table_id: str):
    """The binding remembered for this question and table, or None."""
    if not enabled():
        return None
    item = _SHARED.get(question)
    if not item:
        return None
    if str(table_id).removesuffix(".px") != item["table_id"]:
        return None
    from grund.bind import Binding

    selections = []
    for entry in item["selections"]:
        selection = dict(entry.get("selection") or {})
        selection["values"] = list(selection.get("values") or [])
        selections.append({"code": entry.get("code"), "selection": selection})
    return Binding(
        edition=edition,
        selections=selections,
        operation=item["operation"],
        score=item["score"],
        time_var=item["time_var"],
        time_codes=list(item["time_codes"]),
        group_var=item["group_var"],
        part_code=item["part_code"],
        whole_code=item["whole_code"],
        rebase_code=item["rebase_code"],
        target_code=item["target_code"],
        notes=list(item["notes"]),
        official_measure=item["official_measure"],
    )


def response_format() -> str:
    """json-stat2 when the binder is on. The default path stays on PX-JSON."""
    return STAT_FORMAT if enabled() else "json"


def guard_url(url: str) -> None:
    """Hagstofa publishes API v1 only. A v2 path is not a query we send."""
    if "/v2" in (url or "").lower():
        raise ValueError("PxWeb v2 is not served here; use the v1 endpoint")


@dataclass(frozen=True)
class ValueClass:
    """One published value, classified from its label."""

    code: str
    label: str
    is_total: bool
    is_aggregate: bool
    of_which: bool
    measure_kind: str
    unit: str
    geography: str
    period_grain: str
    population: str
    measured_property: str
    stat_type: str
    denominator: str
    stock_flow: str


@dataclass(frozen=True)
class VariableClass:
    code: str
    text: str
    role: str
    elimination: bool
    geography_level: str
    period_grain: str
    values: tuple[ValueClass, ...]


@dataclass(frozen=True)
class AskedMeasure:
    """What the question is asking, in StatisticalVariable fields."""

    population: str
    measured_property: str
    stat_type: str
    denominator: str
    unit: str
    stock_flow: str
    kind: str


@dataclass(frozen=True)
class PeriodQuery:
    """A period phrase, before it is matched to a table's codes."""

    kind: str
    years: tuple[int, ...] = ()
    months: tuple[tuple[int, int], ...] = ()
    quarters: tuple[tuple[int, int], ...] = ()
    start_year: int | None = None
    end_year: int | None = None


@dataclass(frozen=True)
class Derivation:
    """A figure this program calculated from two published cells."""

    op: str
    formula: str
    table_id: str
    cell_a: str
    cell_b: str

    def sentence(self, language: str) -> str:
        if language == "is":
            return (
                f"Reiknað úr reitum {self.cell_a} og {self.cell_b} "
                f"í töflu {self.table_id}."
            )
        return (
            f"Calculated from cells {self.cell_a} and {self.cell_b} "
            f"of table {self.table_id}."
        )


def frequency(codes: list[str]) -> str:
    """Period granularity read from the codes, not from the title."""
    counts: dict[str, int] = {}
    for code in codes:
        grain = grain_of(code)
        if grain == "other":
            continue
        counts[grain] = counts.get(grain, 0) + 1
    if not counts:
        return "other"
    return max(counts, key=lambda name: (counts[name], name))


def grain_of(code: str) -> str:
    text = str(code).upper()
    if re.fullmatch(r"\d{4}M\d{2}", text):
        return "month"
    if re.fullmatch(r"\d{4}[QK]\d", text):
        return "quarter"
    if re.fullmatch(r"\d{4}W\d{2}", text):
        return "week"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "day"
    if re.fullmatch(r"\d{4}", text):
        return "year"
    return "other"


def period_sort_key(code: str) -> tuple[int, int, int]:
    text = str(code).upper()
    match = re.fullmatch(r"(\d{4})M(\d{2})", text)
    if match:
        return (int(match.group(1)), 1, int(match.group(2)))
    match = re.fullmatch(r"(\d{4})[QK](\d)", text)
    if match:
        return (int(match.group(1)), 2, int(match.group(2)))
    match = re.fullmatch(r"(\d{4})W(\d{2})", text)
    if match:
        return (int(match.group(1)), 3, int(match.group(2)))
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return (int(match.group(1)), 4, int(match.group(2)) * 100 + int(match.group(3)))
    match = re.fullmatch(r"(\d{4})", text)
    if match:
        return (int(match.group(1)), 0, 0)
    return (0, 0, 0)


def _of_which(label: str) -> bool:
    folded = fold(label)
    return any(piece in folded for piece in _OF_WHICH)


def _strict_total(code: str, label: str) -> bool:
    if _of_which(label):
        return False
    folded = fold(label).strip(" .:-")
    if "of total" in folded or "percentage of" in folded:
        return False
    if folded in _EXACT_TOTAL or fold(code) in {"total", "alls", "samtals"}:
        return True
    return False


def _aggregate(code: str, label: str) -> bool:
    if _of_which(label):
        return False
    if _strict_total(code, label):
        return True
    folded = fold(label).strip(" .:-")
    if "of total" in folded or "percentage" in folded:
        return False
    if folded.endswith(" total") or folded.endswith(", total") or folded.endswith(" alls"):
        return True
    if folded.endswith(", alls") or folded.endswith(" samtals"):
        return True
    return False


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _kind_of(label: str) -> tuple[str, str, str, str, str, str]:
    """kind, unit, denominator, stock_flow, stat_type, population."""
    folded = fold(label)
    stock_flow = ""
    if any(piece in folded for piece in (
        "arriv", "adflutt", "brottflutt", "komur", "during the year", "a arinu",
        "birth", "faedd", "death", "danir", "emigrat",
    )):
        stock_flow = "flow"
    elif any(piece in folded for piece in (
        "1 januar", "arsbyrjun", "arslok", "stock", "innflytj", "immigrant",
        "busett", "residents",
    )):
        stock_flow = "stock"
    elif any(piece in folded for piece in ("population", "mannfjold", "inhabitants")):
        stock_flow = "stock"

    unit = ""
    denominator = ""
    if any(piece in folded for piece in ("per 1,000", "per 1000", "per 1 000", "a hverja")):
        denominator = "per 1,000"
    elif any(piece in folded for piece in ("per capita", "per person", "per inhabitant", "a ibua", "a mann")):
        denominator = "per capita"
    elif "per woman" in folded or "a hverja konu" in folded:
        denominator = "per woman"
    if "%" in label or any(piece in folded for piece in ("percent", "hlutfall", "prosent")):
        unit = "percent"
    elif any(piece in folded for piece in ("visitala", "index")):
        unit = "index"
    elif any(piece in folded for piece in ("kron", "isk")):
        unit = "isk"
    elif any(piece in folded for piece in ("tonn", "tonnes", "tons")):
        unit = "tonnes"
    elif any(piece in folded for piece in ("population", "mannfjold", "persons", "people", "fjoldi", "inhabitants")):
        unit = "people"

    if any(piece in folded for piece in ("visitala",)) or _has_word(folded, "index"):
        kind = "index"
    elif unit == "percent" or any(piece in folded for piece in ("hlutfall", "percent", "prosent")):
        kind = "percent"
    elif denominator or any(piece in folded for piece in ("rate", "tidni", "frjosemi", "fertility")):
        kind = "rate"
    elif any(piece in folded for piece in (
        "breyting", "change", "increase", "decrease", "haekk", "laekk", "fjolgun", "faekkun",
    )):
        kind = "change"
    elif stock_flow == "flow":
        kind = "flow"
    elif stock_flow == "stock":
        kind = "stock"
    elif any(piece in folded for piece in ("fjoldi", "number", "persons", "people", "population", "mannfjold")):
        kind = "count"
    elif unit:
        kind = "level"
    else:
        kind = ""

    if any(piece in folded for piece in ("median", "midgildi", "midaldur")):
        stat_type = "medianValue"
    elif any(piece in folded for piece in ("mean", "medaltal", "medalaldur", "medal")):
        stat_type = "meanValue"
    elif kind == "change":
        stat_type = "change"
    elif kind == "index":
        stat_type = "index"
    elif kind in {"rate", "percent"}:
        stat_type = "ratio"
    elif kind:
        stat_type = "measuredValue"
    else:
        stat_type = ""

    population = ""
    if "innflytj" in folded or _has_word(folded, "immigrant") or "immigrants" in folded:
        population = "immigrants"
    elif any(piece in folded for piece in ("population", "mannfjold", "inhabitants", "persons")):
        population = "persons"
    return kind, unit, denominator, stock_flow, stat_type, population


def classify_value(code: str, label: str, *, geography: str = "", period_grain: str = "") -> ValueClass:
    kind, unit, denominator, stock_flow, stat_type, population = _kind_of(label)
    grain = period_grain or (grain_of(code) if grain_of(code) != "other" else "")
    if grain == "other":
        grain = ""
    total = _strict_total(code, label)
    aggregate = _aggregate(code, label)
    if total and geography in {"municipality", "region", "locality", "constituency"}:
        geography = "country"
    property_name = kind or fold(label)[:48]
    return ValueClass(
        code=str(code),
        label=str(label),
        is_total=total,
        is_aggregate=aggregate,
        of_which=_of_which(label),
        measure_kind=kind,
        unit=unit,
        geography=geography,
        period_grain=grain,
        population=population,
        measured_property=property_name,
        stat_type=stat_type,
        denominator=denominator,
        stock_flow=stock_flow,
    )


def _geography_level(code: str, text: str) -> str:
    name = fold(f"{code} {text}")
    if any(piece in name for piece in ("sveitarfelag", "municipality", "kommuna")):
        return "municipality"
    if any(piece in name for piece in ("byggdakjarni", "postcode", "postnumer", "locality")):
        return "locality"
    if any(piece in name for piece in ("kjordaemi", "constituency")):
        return "constituency"
    if any(piece in name for piece in ("landshluti", "landsvaedi", "region", "nuts")):
        return "region"
    if _has_word(name, "country") or _has_word(name, "land") or "rikid" in name:
        return "country"
    return ""


def _role(code: str, text: str, time: bool, values: list[tuple[str, str]]) -> tuple[str, str, str]:
    codes = [str(item) for item, _label in values]
    grain = frequency(codes)
    if time or (grain != "other" and grain):
        dated = sum(1 for code in codes if grain_of(code) != "other")
        if time or dated >= max(3, len(codes) // 2):
            return "time", "", grain if grain != "other" else ""
    level = _geography_level(code, text)
    if level:
        return "geography", level, ""
    name = fold(f"{code} {text}")
    if any(piece in name for piece in ("kyn", "sex", "gender")):
        return "sex", "", ""
    if any(piece in name for piece in ("aldur", "age")):
        return "age", "", ""
    if any(piece in name for piece in ("eining", "unit", "measure", "maelikvardi")):
        return "measure", "", ""
    return "other", "", ""


def classify_variable(variable) -> VariableClass:
    code, text, time_flag, elimination, values = _variable_parts(variable)
    role, level, grain = _role(code, text, time_flag, values)
    classified = tuple(
        classify_value(
            value_code,
            value_label,
            geography=level,
            period_grain=grain_of(str(value_code)) if role == "time" else "",
        )
        for value_code, value_label in values
    )
    if role == "other":
        kinds = {item.measure_kind for item in classified if item.measure_kind and item.measure_kind != "level"}
        flows = {item.stock_flow for item in classified if item.stock_flow}
        if len(kinds) >= 2 or len(flows) >= 2:
            role = "measure"
    return VariableClass(
        code=code,
        text=text,
        role=role,
        elimination=elimination,
        geography_level=level,
        period_grain=grain,
        values=classified,
    )


def classify_edition(edition) -> tuple[VariableClass, ...]:
    return tuple(classify_variable(variable) for variable in _variables(edition))


def classify_question(text: str, operation: str = "level") -> AskedMeasure:
    folded = fold(text or "")
    immigrant = bool(re.search(r"\binnflytj\w*\b", folded) or _has_word(folded, "immigrant") or "immigrants" in folded)
    arrival = bool(re.search(
        r"\b(arriv\w*|adflutt\w*|komur|komu|immigrat\w*|emigrat\w*|brottflutt\w*)\b",
        folded,
    ))
    stock_flow = ""
    if arrival:
        stock_flow = "flow"
    elif immigrant or re.search(r"\b(lived|live|lives|bua|bjuggu|population|mannfjold\w*|stock|residents)\b", folded):
        stock_flow = "stock"
    elif re.search(r"\b(births?|deaths?|faedd\w*|danir)\b", folded):
        stock_flow = "flow"

    denominator = ""
    if re.search(r"per\s*1[,.\s]?000|a hverja", folded):
        denominator = "per 1,000"
    elif re.search(r"per capita|per person|a ibua|a mann", folded):
        denominator = "per capita"
    unit = ""
    if operation in {"share", "yoy_pct", "pct_change"}:
        unit = "percent"
    elif re.search(r"\b(visitala|index)\b", folded):
        unit = "index"
    elif re.search(r"\b(kron\w*|isk)\b", folded):
        unit = "isk"
    elif re.search(r"\b(people|persons|population|mannfjold\w*|inhabitants)\b", folded):
        unit = "people"

    if operation in {"yoy_pct", "difference", "pct_change", "change", "sum"}:
        kind = "level"
    elif operation == "share":
        kind = "count"
    elif unit == "index" or re.search(r"\b(visitala|index)\b", folded):
        kind = "index"
    elif denominator or re.search(r"\b(rate|frjosemi|fertility)\b", folded):
        kind = "rate"
    elif operation == "level" and re.search(r"\b(percent\w*|hlutfall|prosent\w*)\b", folded):
        kind = "percent"
    elif stock_flow == "flow":
        kind = "flow"
    elif stock_flow == "stock":
        kind = "stock"
    elif re.search(r"\b(how many|hve marg\w*|hve morg\w*|fjoldi|number)\b", folded):
        kind = "count"
    else:
        kind = "level"

    if re.search(r"\b(median|midgildi)\b", folded):
        stat_type = "medianValue"
    elif re.search(r"\b(mean|medaltal)\b", folded):
        stat_type = "meanValue"
    elif kind == "index":
        stat_type = "index"
    elif kind in {"rate", "percent"}:
        stat_type = "ratio"
    else:
        stat_type = "measuredValue"
    population = "immigrants" if immigrant else ("persons" if unit == "people" or stock_flow == "stock" else "")
    return AskedMeasure(
        population=population,
        measured_property=kind,
        stat_type=stat_type,
        denominator=denominator,
        unit=unit,
        stock_flow=stock_flow,
        kind=kind,
    )


_YEAR = r"(?:19|20)\d{2}"
_ORD = {
    "fyrsta": 1, "fyrsti": 1, "first": 1, "1st": 1, "1": 1,
    "annan": 2, "annar": 2, "odrum": 2, "second": 2, "2nd": 2, "2": 2,
    "thridja": 3, "thridji": 3, "thridju": 3, "third": 3, "3rd": 3, "3": 3,
    "fjorda": 4, "fjordi": 4, "fjordu": 4, "fourth": 4, "4th": 4, "4": 4,
}
_MONTHS = {
    "january": 1, "januar": 1, "jan": 1,
    "february": 2, "februar": 2, "feb": 2,
    "march": 3, "mars": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "juni": 6, "jun": 6,
    "july": 7, "juli": 7, "jul": 7,
    "august": 8, "agust": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oktober": 10, "oct": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "desember": 12, "dec": 12, "des": 12,
}


def parse_period_query(text: str, *, today: date | None = None) -> PeriodQuery:
    """Turn a period phrase into years, quarters, or months. No table codes yet."""
    clock = today or date.today()
    folded = fold(text or "")
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(not (end <= left or start >= right) for left, right in taken)

    def take(start: int, end: int) -> bool:
        if overlaps(start, end):
            return False
        taken.append((start, end))
        return True

    for match in re.finditer(rf"(?:base|grunn\w*)\s+({_YEAR})|({_YEAR})\s*=\s*100", folded):
        take(*match.span())

    if re.search(r"\b(?:last|previous)\s+year\b|\bsidasta\s+ar(?:i|inu|id)?\b|\bi\s+fyrra\b", folded):
        return PeriodQuery(kind="point", years=(clock.year - 1,))

    in_years = [int(match.group(1)) for match in re.finditer(rf"\b(?:in|arid|arinu)\s+({_YEAR})\b", folded)]
    range_match = re.search(
        rf"(?:from|fra|milli|between)\s+({_YEAR})\s+(?:to|til|og|and)\s+({_YEAR})"
        rf"|({_YEAR})\s+(?:to|til)\s+({_YEAR})"
        rf"|({_YEAR})\s*-\s*({_YEAR})",
        folded,
    )
    range_years: tuple[int, int] | None = None
    if range_match and take(*range_match.span()):
        found_years = [int(group) for group in range_match.groups() if group]
        if len(found_years) >= 2:
            range_years = (found_years[0], found_years[1])

    quarters: list[tuple[int, int]] = []
    quarter_re = re.compile(
        rf"\b(fyrsta|fyrsti|annan|annar|odrum|thridja|thridji|thridju|fjorda|fjordi|fjordu|"
        rf"first|second|third|fourth|1st|2nd|3rd|4th|[1-4])\s*\.?\s*"
        rf"(?:quarter|arsfjordung\w*)(?:\D{{0,16}}({_YEAR}))?",
    )
    for match in quarter_re.finditer(folded):
        if not take(*match.span()):
            continue
        quarter = _ORD.get(match.group(1))
        if quarter is None:
            continue
        year = int(match.group(2)) if match.group(2) else None
        if year is None:
            nearby = re.search(rf"\b({_YEAR})\b", folded[match.end(): match.end() + 16])
            if nearby:
                year = int(nearby.group(1))
                take(match.end() + nearby.start(), match.end() + nearby.end())
        if year is not None:
            quarters.append((year, quarter))
    for match in re.finditer(rf"\b({_YEAR})\s*[qk]\s*([1-4])\b|\bq\s*([1-4])\s*({_YEAR})\b", folded):
        if not take(*match.span()):
            continue
        if match.group(1):
            quarters.append((int(match.group(1)), int(match.group(2))))
        else:
            quarters.append((int(match.group(4)), int(match.group(3))))

    months: list[tuple[int, int]] = []
    month_alt = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for match in re.finditer(rf"\b({month_alt})\.?\s+({_YEAR})\b", folded):
        if not take(*match.span()):
            continue
        months.append((int(match.group(2)), _MONTHS[match.group(1)]))
    for match in re.finditer(rf"\b({_YEAR})\s*m\s*(\d{{1,2}})\b", folded):
        if not take(*match.span()):
            continue
        month = int(match.group(2))
        if 1 <= month <= 12:
            months.append((int(match.group(1)), month))

    years: list[int] = []
    for match in re.finditer(rf"\b({_YEAR})\b", folded):
        if not take(*match.span()):
            continue
        years.append(int(match.group(1)))

    if quarters:
        return PeriodQuery(kind="quarters", quarters=tuple(quarters), years=tuple(years))
    if months:
        return PeriodQuery(kind="months", months=tuple(months), years=tuple(years))
    if in_years:
        if len(in_years) >= 2:
            return PeriodQuery(kind="range", start_year=in_years[0], end_year=in_years[-1], years=tuple(in_years))
        return PeriodQuery(kind="point", years=(in_years[0],))
    if range_years is not None:
        return PeriodQuery(kind="range", start_year=range_years[0], end_year=range_years[1], years=range_years)
    if len(years) >= 2:
        return PeriodQuery(kind="range", start_year=years[0], end_year=years[-1], years=tuple(years))
    if len(years) == 1:
        return PeriodQuery(kind="point", years=(years[0],))
    if re.search(r"\b(latest|newest|most recent|nyjast\w*|seinast\w*)\b", folded):
        return PeriodQuery(kind="latest")
    return PeriodQuery(kind="empty")


def explicit_codes(query: PeriodQuery, codes: list[str]) -> list[str]:
    """The published codes the phrase names. Empty when none of them exist."""
    listed = [str(code) for code in codes]
    grain = frequency(listed)

    def year_code(year: int) -> str | None:
        marked = None
        for code in listed:
            if code == str(year):
                return code
            if marked is None and re.fullmatch(rf"A{year}", code, re.I):
                marked = code
        return marked

    def quarter_code(year: int, quarter: int) -> str | None:
        wanted = {f"{year}Q{quarter}".upper(), f"{year}K{quarter}".upper()}
        for code in listed:
            if code.upper() in wanted:
                return code
        return None

    def month_code(year: int, month: int) -> str | None:
        wanted = {f"{year}M{month:02d}".upper(), f"{year}M{month}".upper()}
        for code in listed:
            if code.upper() in wanted:
                return code
        return None

    found: list[str] = []

    def add(code: str | None) -> None:
        if code and code not in found:
            found.append(code)

    if query.kind == "quarters":
        for year, quarter in query.quarters:
            add(quarter_code(year, quarter))
        return found
    if query.kind == "months":
        for year, month in query.months:
            add(month_code(year, month))
        if not found:
            for year, _month in query.months:
                add(year_code(year))
        return found
    if query.kind == "range" and query.start_year and query.end_year:
        start, end = sorted((query.start_year, query.end_year))
        if grain == "year":
            for year in range(start, end + 1):
                add(year_code(year))
            return found
        if grain == "quarter":
            for code in listed:
                match = re.fullmatch(r"(\d{4})[QK](\d)", code.upper())
                if match and start <= int(match.group(1)) <= end:
                    add(code)
            return found
        if grain == "month":
            for code in listed:
                match = re.fullmatch(r"(\d{4})M(\d{2})", code.upper())
                if match and start <= int(match.group(1)) <= end:
                    add(code)
            return found
        add(year_code(start))
        add(year_code(end))
        return found
    if query.kind == "point" and query.years:
        year = query.years[0]
        if grain == "year" or year_code(year):
            add(year_code(year))
            return found
        if grain == "month":
            add(month_code(year, 12) or month_code(year, 1))
        elif grain == "quarter":
            add(quarter_code(year, 4) or quarter_code(year, 1))
        return found
    return found


def _content_tokens(label: str, *, min_len: int = 5) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", fold(label))
    return [token for token in tokens if len(token) >= min_len and token not in _DIM_WORDS]


def _token_in(token: str, question: str) -> bool:
    if re.search(rf"\b{re.escape(token)}\b", question):
        return True
    stem = token[:8] if len(token) >= 8 else token
    if len(stem) >= 7 and stem in question:
        return True
    return False


def label_named(label: str, question: str, code: str = "") -> bool:
    """True when the question writes this value, not the dimension it sits on.

    One distinctive word is enough. A long account label is still the row
    when the question quotes one of its words or its code.
    """
    if code and len(str(code)) >= 4 and str(code).lower() in (question or "").lower():
        return True
    if _strict_total(code, label):
        return False
    folded = fold(question)
    return any(_token_in(token, folded) for token in _content_tokens(label))


def _sex_named(question: str) -> str:
    folded = fold(question)
    if re.search(r"\b(women|woman|females?|girls?|konur|kona|stulkur)\b", folded):
        return "female"
    if re.search(r"\b(men|males?|boys?|karlar|karl|drengir)\b", folded):
        return "male"
    return ""


def _age_named(question: str) -> bool:
    folded = fold(question)
    if re.search(r"\b(age|aldur|eldri|yngri|year old|ara)\b", folded):
        return True
    return bool(re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\b", folded))


def _label_side(label: str) -> str:
    folded = fold(label)
    if re.search(r"\b(women|woman|females?|konur|kona)\b", folded):
        return "female"
    if re.search(r"\b(men|males?|karlar|karl)\b", folded):
        return "male"
    return ""


def _kind_score(value: ValueClass, asked: AskedMeasure) -> int:
    score = 0
    if asked.stock_flow and value.stock_flow == asked.stock_flow:
        score += 5
    if asked.stock_flow and value.stock_flow and value.stock_flow != asked.stock_flow:
        score -= 5
    if asked.kind and value.measure_kind == asked.kind:
        score += 3
    if asked.kind in {"count", "stock", "level"} and value.measure_kind in {"percent", "index", "rate"}:
        score -= 3
    if asked.kind == "index" and value.measure_kind == "index":
        score += 4
    if asked.kind == "rate" and value.measure_kind == "rate":
        score += 3
    if asked.kind == "percent" and value.measure_kind == "percent":
        score += 3
    return score


def _first_total(variable: VariableClass, question: str = "") -> ValueClass | None:
    aggregates = [value for value in variable.values if value.is_aggregate and not value.of_which]
    for value in aggregates:
        if question and label_named(value.label, question):
            return value
    for value in variable.values:
        if value.is_total and not value.of_which:
            return value
    if aggregates:
        return aggregates[0]
    return None


def _variables(edition) -> list:
    if isinstance(edition, dict):
        return list(edition.get("variables") or [])
    return list(edition.variables)


def _variable_parts(variable) -> tuple[str, str, bool, bool, list[tuple[str, str]]]:
    if isinstance(variable, dict):
        values = [(str(code), str(label)) for code, label in variable.get("values") or []]
        return (
            str(variable.get("code") or ""),
            str(variable.get("text") or ""),
            bool(variable.get("time")),
            bool(variable.get("elimination")),
            values,
        )
    values = [(str(code), str(label)) for code, label in variable.values]
    return str(variable.code), str(variable.text), bool(variable.time), bool(variable.elimination), values


def _within_limits(lengths: list[int]) -> bool:
    if any(length > MAX_VALUES for length in lengths):
        return False
    cells = 1
    for length in lengths:
        cells *= max(1, length)
        if cells > MAX_CELLS:
            return False
    return True


def selections_for(chosen: dict[str, list[str]], variables, time_code: str | None = None) -> list[dict]:
    """Item filters, or ``top`` when the time codes are the tail of the list.

    ``top`` returns that same tail. A middle span stays an item filter,
    because those codes are not the tail.
    """
    by_code = {}
    for variable in variables:
        code, _text, _time, _elimination, values = _variable_parts(variable)
        by_code[code] = [str(item) for item, _label in values]
    query = []
    lengths = []
    for code, values in chosen.items():
        if not values:
            continue
        published = by_code.get(code) or []
        use_top = (
            time_code is not None
            and code == time_code
            and published
            and values == published[-len(values):]
        )
        if use_top:
            query.append({"code": code, "selection": {"filter": "top", "values": [str(len(values))]}})
        else:
            query.append({"code": code, "selection": {"filter": "item", "values": list(values)}})
        lengths.append(len(values))
    if not _within_limits(lengths):
        shrunk = []
        for entry in query:
            values = entry["selection"]["values"]
            if entry["code"] == time_code and entry["selection"]["filter"] == "item" and len(values) > 2:
                entry = {
                    "code": entry["code"],
                    "selection": {"filter": "item", "values": [values[0], values[-1]]},
                }
            shrunk.append(entry)
        return shrunk
    return query


def _years_in(codes: list[str]) -> set[str]:
    found: set[str] = set()
    for code in codes:
        found.update(re.findall(r"(?:19|20)\d{2}", str(code)))
    return found


def _period_overlap(current: list[str], explicit: list[str]) -> bool:
    """Leave the period alone when a current code already includes an asked year.

    A selection of 2013 and 2014 is kept for a question that says 2014.
    A selection of 2026 is not kept for a question that says 2024.
    """
    if not current or not explicit:
        return False
    if set(current) & set(explicit):
        return True
    return bool(_years_in(current) & _years_in(explicit))


def _dimension_cue(question: str, info: VariableClass) -> bool:
    """The question names the geography dimension, not one of its places."""
    folded = fold(question)
    if not re.search(r"\b(by|eftir|per)\b", folded):
        return False
    cues = {
        "municipality": ("municipality", "sveitarfelag"),
        "region": ("region", "landshluti", "landsvaedi"),
        "locality": ("locality", "byggdakjarni", "postcode", "postnumer"),
        "constituency": ("constituency", "kjordaemi"),
        "country": ("country",),
    }
    return any(_has_word(folded, word) for word in cues.get(info.geography_level, ()))


def _previous(codes: list[str], code: str) -> str | None:
    if code not in codes:
        return None
    index = codes.index(code)
    if index <= 0:
        return None
    return codes[index - 1]


def _query_codes(full: list[str], operation: str, published: list[str]) -> list[str]:
    if not full:
        return []
    if operation in {"yoy_pct", "difference", "pct_change", "change", "sum"}:
        if len(full) == 1:
            previous = _previous(published, full[0])
            if previous:
                return [previous, full[0]]
        if len(full) > 2:
            return [full[0], full[-1]]
        return list(full)
    if len(full) > 1:
        return [full[-1]]
    return list(full)


def apply_binding(edition, parsed, binding):
    """Return a retied binding, the original when the flag is off, or None on a conflict."""
    if not enabled() or binding is None:
        return binding
    from grund.validator import ValidationError, validate

    updated = _retie(edition, parsed, binding)
    if updated is None:
        return None
    try:
        validate(edition, updated.selections)
    except ValidationError:
        return binding
    return updated


def _retie(edition, parsed, binding):
    from grund.bind import Binding

    asked = classify_question(parsed.text, binding.operation or parsed.operation)
    classified = {item.code: item for item in classify_edition(edition)}
    chosen: dict[str, list[str]] = {}
    for entry in binding.selections:
        values = [str(value) for value in (entry.get("selection") or {}).get("values") or []]
        if values:
            chosen[str(entry.get("code"))] = values
    question = parsed.text or ""
    operation = binding.operation or parsed.operation
    notes = list(binding.notes)
    time_code = binding.time_var
    published_time: list[str] = []
    latest = False

    for variable in _variables(edition):
        code, _text, time_flag, elimination, values = _variable_parts(variable)
        info = classified.get(code)
        if info is None:
            continue
        published = [str(item) for item, _label in values]
        if time_flag or code == time_code:
            time_code = code
            published_time = published
            query = parse_period_query(question)
            if query.kind == "empty" and getattr(parsed, "latest", False) and not getattr(parsed, "periods", None):
                query = PeriodQuery(kind="latest")
            if query.kind == "latest":
                window = published[-min(LATEST_WINDOW, len(published)):] if published else []
                if window:
                    chosen[code] = window
                    latest = True
                continue
            explicit = explicit_codes(query, published)
            current_codes = chosen.get(code) or []
            if explicit and not _period_overlap(current_codes, explicit):
                picked = _query_codes(explicit, operation, published)
                if picked and _within_limits([len(picked)]):
                    chosen[code] = picked
                    notes.append("bind2-periods:" + ",".join(explicit))
            continue

        if binding.group_var and code == binding.group_var and operation in {"share", "difference", "sum"}:
            continue

        current = chosen.get(code) or []
        if current and any(label_named(value.label, question, value.code) for value in info.values if value.code == current[0]):
            continue
        if info.role == "sex":
            side = _sex_named(question)
            sided = [value for value in info.values if _label_side(value.label) == side] if side else []
            if sided:
                chosen[code] = [sided[0].code]
                continue
        # A pasted table title shares words with many rows. Do not leave the
        # current row for one of those. A stock/flow clash is handled below.
        flows = [value for value in info.values if value.stock_flow]
        if (
            info.role == "measure"
            and asked.stock_flow
            and flows
            and all(value.stock_flow != asked.stock_flow for value in flows)
        ):
            return None
        alternative = next((value for value in flows if value.stock_flow == asked.stock_flow), None)
        if alternative is not None and current and alternative.code not in current:
            current_flow = next((value.stock_flow for value in info.values if value.code == current[0]), "")
            if current_flow and current_flow != asked.stock_flow:
                chosen[code] = [alternative.code]
                notes.append(f"bind2-measure:{code}")
                continue
        if info.role not in {"sex", "age", "geography"}:
            continue
        if info.role == "age" and _age_named(question):
            continue
        if info.role == "geography" and not _dimension_cue(question, info):
            continue
        total = next((value for value in info.values if value.is_total and not value.of_which), None)
        if total is None:
            continue
        if elimination:
            chosen.pop(code, None)
            notes.append(f"bind2-omit:{code}")
            continue
        if not current or current != [total.code]:
            notes.append(f"bind2-total:{code}")
        chosen[code] = [total.code]

    if time_code and chosen.get(time_code):
        if latest:
            notes.append("bind2-latest")
        time_codes = list(chosen[time_code])
    else:
        time_codes = list(binding.time_codes)
    selections = selections_for(chosen, _variables(edition), time_code=time_code)
    if not any("bind2" in note for note in notes):
        notes.append("bind2")
    return Binding(
        edition=binding.edition,
        selections=selections,
        operation=operation,
        score=binding.score,
        time_var=time_code,
        time_codes=time_codes if not latest else list(published_time[-min(LATEST_WINDOW, len(published_time)):]),
        group_var=binding.group_var,
        part_code=binding.part_code,
        whole_code=binding.whole_code,
        rebase_code=binding.rebase_code,
        target_code=binding.target_code,
        notes=notes,
        official_measure=binding.official_measure,
    )


def apply_map(edition: dict, request: dict, chosen: dict[str, list[str]] | None):
    """Same total, measure, and period rules for a mapped tool query."""
    if not enabled() or chosen is None:
        return chosen
    text = str(request.get("_text") or "")
    if not text:
        return chosen
    from grund.bind import Binding

    op = {"change": "difference", "pct_change": "yoy_pct"}.get(request.get("op") or "", request.get("op") or "level")
    period = request.get("period") or {}
    latest = period.get("kind") == "latest"

    class _Parsed:
        pass

    parsed = _Parsed()
    parsed.text = text
    parsed.operation = op
    parsed.latest = latest
    parsed.periods = [] if latest else [(0, None)]
    time_code = None
    for variable in _variables(edition):
        code, _text, time_flag, _elimination, _values = _variable_parts(variable)
        if time_flag:
            time_code = code
            break
    binding = Binding(
        edition=edition,
        selections=[
            {"code": code, "selection": {"filter": "item", "values": list(values)}}
            for code, values in chosen.items()
            if values
        ],
        operation=op,
        score=0,
        time_var=time_code,
        time_codes=list(chosen.get(time_code) or []),
        notes=[],
    )
    updated = _retie(edition, parsed, binding)
    if updated is None:
        return chosen
    restored: dict[str, list[str]] = {}
    published = {}
    for variable in _variables(edition):
        code, _text, _time, _elimination, values = _variable_parts(variable)
        published[code] = [str(item) for item, _label in values]
    for entry in updated.selections:
        code = entry["code"]
        selection = entry["selection"]
        if selection.get("filter") == "top":
            count = int(selection["values"][0])
            restored[code] = (published.get(code) or [])[-count:]
        else:
            restored[code] = [str(value) for value in selection.get("values") or []]
    return restored


def _numeric(raw: Any) -> bool:
    if raw in (None, "", ".", "..", "..."):
        return False
    try:
        from grund.arithmetic import to_decimal

        to_decimal(str(raw))
    except Exception:
        return False
    return True


def narrow_latest(rows: list[dict], binding) -> list[dict]:
    """Keep the newest period that has a number. An empty tail is not latest."""
    if binding is None or not any(str(note).startswith("bind2-latest") for note in binding.notes):
        return rows
    time_var = binding.time_var
    if not time_var:
        return rows
    best = None
    best_key = None
    for row in rows:
        code = str((row.get("map") or {}).get(time_var) or "")
        if not code or not _numeric(row.get("value")):
            continue
        key = period_sort_key(code)
        if best_key is None or key > best_key:
            best_key = key
            best = code
    if best is None:
        if binding.time_codes:
            _force_item(binding, time_var, [str(binding.time_codes[-1])])
        return rows
    _force_item(binding, time_var, [best])
    binding.time_codes = [best]
    return [row for row in rows if str((row.get("map") or {}).get(time_var) or "") == best]


def _force_item(binding, code: str, values: list[str]) -> None:
    for entry in binding.selections:
        if entry.get("code") == code:
            entry["selection"] = {"filter": "item", "values": list(values)}
            return
    binding.selections.append({"code": code, "selection": {"filter": "item", "values": list(values)}})


def keep_newest_cells(cells: list[dict], edition: dict) -> list[dict]:
    """Newest numeric cell when a latest window came back from the tool path."""
    if not enabled():
        return cells
    variable = next((item for item in _variables(edition) if item.get("time") or classify_variable(item).role == "time"), None)
    if variable is None:
        return cells
    code = str(variable.get("code") or "")
    best = None
    best_key = None
    for cell in cells:
        period = str((cell.get("coords") or {}).get(code) or cell.get("period") or "")
        if not period or not _numeric(cell.get("value")):
            continue
        key = period_sort_key(period)
        if best_key is None or key > best_key:
            best_key = key
            best = period
    if best is None:
        return cells
    kept = []
    for cell in cells:
        period = str((cell.get("coords") or {}).get(code) or cell.get("period") or "")
        if period != best:
            continue
        cell["period"] = best
        cell["latest_period"] = best
        kept.append(cell)
    return kept or cells


def table_id_of(edition) -> str:
    url = edition.get("url") if isinstance(edition, dict) else getattr(edition, "url", "")
    name = str(url or "").rstrip("/").split("/")[-1]
    if name.endswith(".px"):
        name = name[:-3]
    return name


def attach_derivation(binding, edition, rows: list[dict], derived: dict | None) -> Derivation | None:
    """Attach the calculation to the binding. Levels are not derived."""
    if not enabled() or not derived or len(rows) < 2:
        return None
    item = Derivation(
        op=str(derived.get("name") or binding.operation or ""),
        formula=str(derived.get("formula") or ""),
        table_id=table_id_of(edition),
        cell_a=_cell_tag(rows[0], binding),
        cell_b=_cell_tag(rows[-1], binding),
    )
    binding.derivation = item
    return item


def _cell_tag(row: dict, binding) -> str:
    time_var = getattr(binding, "time_var", None) or ""
    code = str((row.get("map") or {}).get(time_var) or "")
    if code:
        return code
    labels = row.get("labels") or []
    if labels:
        return str(labels[0].get("label") or labels[0].get("code") or "cell")
    return "cell"


def derivation_from_claim(claim: dict) -> Derivation | None:
    raw = claim.get("derivation") if isinstance(claim, dict) else None
    if not isinstance(raw, dict):
        return None
    if not raw.get("cell_a") or not raw.get("cell_b") or not raw.get("table_id"):
        return None
    return Derivation(
        op=str(raw.get("op") or ""),
        formula=str(raw.get("formula") or ""),
        table_id=str(raw["table_id"]),
        cell_a=str(raw["cell_a"]),
        cell_b=str(raw["cell_b"]),
    )


def is_jsonstat(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and "dimension" in payload
        and "value" in payload
        and "columns" not in payload
    )


def pxjson_from_jsonstat(payload: dict) -> dict:
    """The column-and-data shape the row reader already understands."""
    if not is_jsonstat(payload):
        return payload
    ids = [str(item) for item in payload.get("id") or []]
    size = [int(item) for item in payload.get("size") or []]
    if not ids or not size or len(ids) != len(size):
        ids = [str(key) for key in (payload.get("dimension") or {})]
        size = []
        for dim_id in ids:
            category = ((payload.get("dimension") or {}).get(dim_id) or {}).get("category") or {}
            index = category.get("index")
            if isinstance(index, dict):
                size.append(len(index))
            elif isinstance(index, list):
                size.append(len(index))
            else:
                size.append(1)
    dimension = payload.get("dimension") or {}
    role_time = set((payload.get("role") or {}).get("time") or [])
    columns = []
    code_lists: list[list[str]] = []
    for dim_id, count in zip(ids, size):
        dim = dimension.get(dim_id) or {}
        codes = _category_codes(dim.get("category") or {}, count)
        columns.append({
            "code": dim_id,
            "text": dim.get("label") or dim_id,
            "type": "t" if dim_id in role_time else "d",
        })
        code_lists.append(codes)
    total = 1
    for count in size:
        total *= max(1, count)
    values = payload.get("value")
    data = []
    for index in range(total):
        coords = _unravel(index, size)
        key = []
        for dim_index, pos in enumerate(coords):
            codes = code_lists[dim_index]
            key.append(codes[pos] if pos < len(codes) else str(pos))
        raw = _value_at(values, index)
        data.append({"key": key, "values": [raw]})
    return {"columns": columns, "data": data, "extension": payload.get("extension") or {}}


def _category_codes(category: dict, count: int) -> list[str]:
    index = category.get("index")
    if isinstance(index, dict) and index:
        positions = [str(pos) for pos in range(count or len(index))]
        for code, pos in index.items():
            slot = int(pos)
            if slot < len(positions):
                positions[slot] = str(code)
            else:
                positions.append(str(code))
        return positions
    if isinstance(index, list) and index:
        return [str(code) for code in index]
    labels = category.get("label")
    if isinstance(labels, dict) and labels:
        return [str(code) for code in labels]
    return [str(pos) for pos in range(count)]


def _unravel(index: int, size: list[int]) -> list[int]:
    coords = []
    for count in reversed(size or [1]):
        count = max(1, count)
        coords.append(index % count)
        index //= count
    coords.reverse()
    return coords


def _value_at(values: Any, index: int) -> str:
    raw = None
    if isinstance(values, list):
        raw = values[index] if index < len(values) else None
    elif isinstance(values, dict):
        raw = values.get(str(index), values.get(index))
    if raw is None:
        return ".."
    return str(raw)


def veto_enabled() -> bool:
    """Separate from GRUND_BIND2. This flag never replaces a cell."""
    return os.environ.get("GRUND_BIND2_VETO", "").strip().lower() in {"1", "true", "yes"}


_CHANGE_OPS = {"yoy_pct", "difference", "change", "pct_change"}
_GENERIC = {
    "people", "person", "persons", "population", "mannfjoldi", "mannfjolda",
    "iceland", "island", "islandi", "lived", "live", "lives", "bua", "bjuggu",
    "index", "visitala", "price", "prices", "verd", "verdlag", "percent",
    "percentage", "hlutfall", "prosent", "number", "fjoldi", "total", "alls",
    "samtals", "heild", "figure", "value", "gildi", "table", "tafla",
    "statistics", "hagstofa", "year", "years", "arid", "arinu", "month",
    "quarter", "change", "breyting", "increase", "decrease", "fall", "rose",
    "what", "which", "how", "many", "much", "from", "were", "was",
    "first", "second", "third", "fourth", "fyrsta", "fyrsti", "annan",
    "thridja", "thridji", "fjorda", "fjordi", "january", "february",
    "march", "april", "june", "july", "august", "september", "october",
    "november", "december", "januar", "februar", "mai", "juni", "juli",
    "agust", "oktober", "desember",
}
_CONSTANT = (
    "fixed price", "fixed prices", "constant price", "constant prices",
    "fast verdlag", "fostu verdlagi", "fostu verd", "a fostu",
    "chained volume", "kedjuteng",
)
_NOMINAL = (
    "nominal", "current price", "current prices", "nafnvirdi",
    "gangverdi", "a gangverdi",
)


def _cited(result: dict) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Title, (variable, label) pairs, and period codes from the stated cells."""
    titles: list[str] = []
    pairs: list[tuple[str, str]] = []
    periods: list[str] = []
    claims = result.get("claims") or []
    blobs = list(claims)
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        blobs.append({"cells": [cell]})
    for claim in blobs:
        for cell in claim.get("cells") or []:
            if cell.get("title"):
                titles.append(str(cell["title"]))
            if cell.get("period"):
                periods.append(str(cell["period"]))
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                items = labels.items()
            else:
                items = (
                    (item.get("variable_text") or item.get("variable") or "", item.get("label") or "")
                    for item in labels
                )
            for key, value in items:
                text = str(value)
                pairs.append((str(key), text))
                if re.search(r"(?:19|20)\d{2}", text):
                    periods.append(text)
    title = " ".join(titles)
    if not title and isinstance(source, dict):
        title = str(source.get("title") or "")
    return title, pairs, periods


def _stated_operation(result: dict) -> str:
    stated = str(result.get("operation") or "")
    if stated:
        return stated
    claims = result.get("claims") or []
    if claims:
        return str(claims[0].get("op") or "")
    return ""


def _named_category_tokens(question: str, title: str, labels: list[str]) -> list[str]:
    """Words in the question that name a row, not the table and not a bare total."""
    title_forms = set(re.findall(r"[a-z0-9]+", fold(title)))
    covered = set()
    for label in labels:
        if classify_value("", label).is_total:
            continue
        covered.update(_content_tokens(label))
    found = []
    for token in re.findall(r"[a-z0-9]+", fold(question)):
        if len(token) < 5 or token in _GENERIC or token in _DIM_WORDS:
            continue
        if token in title_forms or token in covered:
            continue
        found.append(token)
    return found


def veto_reason(question: str, result: dict) -> str | None:
    """Why the default cell contradicts the question, or None to keep it.

    This never chooses a different cell. The caller refuses instead.
    """
    if not veto_enabled() or result.get("refused"):
        return None
    if not question or result.get("value") in (None, ""):
        return None
    from grund.parse import parse_question

    parsed = parse_question(question)
    asked = classify_question(question, parsed.operation)
    title, pairs, periods = _cited(result)
    labels = [label for _key, label in pairs]
    classes = [classify_value("", label) for label in labels]
    stated = _stated_operation(result)

    if parsed.operation in {"yoy_pct", "difference"} and stated in {"level", "compare", ""}:
        return "bind2-veto:level_against_change"

    if parsed.operation == "level" and asked.kind in {"percent", "rate"}:
        kinds = {item.measure_kind for item in classes if item.measure_kind}
        if kinds and kinds <= {"count", "stock", "level", "flow"} and kinds & {"count", "stock", "flow"}:
            return "bind2-veto:count_where_rate"

    if asked.stock_flow:
        flows = {item.stock_flow for item in classes if item.stock_flow}
        if flows and asked.stock_flow not in flows:
            return "bind2-veto:stock_against_flow"

    query = parse_period_query(question)
    asked_grain = "quarter" if query.quarters or query.kind == "quarters" else ""
    if not asked_grain and (query.months or query.kind == "months"):
        asked_grain = "month"
    if asked_grain:
        grains = {grain_of(code) for code in periods}
        grains.discard("other")
        if grains and asked_grain not in grains:
            return "bind2-veto:period_grain"

    question_folded = fold(question)
    blob = fold(f"{title} {' '.join(labels)}")
    asks_nominal = any(piece in question_folded for piece in _NOMINAL)
    cell_constant = any(piece in blob for piece in _CONSTANT)
    question_constant = any(piece in question_folded for piece in _CONSTANT)
    if asks_nominal and cell_constant and not question_constant:
        return "bind2-veto:constant_where_nominal"

    if any(item.is_total for item in classes) and _named_category_tokens(question, title, labels):
        return "bind2-veto:total_where_named"
    return None


def echo_enabled() -> bool:
    """On unless ``GRUND_TITLE_ECHO=0``. Separate from ``GRUND_BIND2_VETO``.

    The gate refuses a cell. It does not choose a different one.
    """
    return os.environ.get("GRUND_TITLE_ECHO", "1").strip().lower() not in {"0", "off", "none"}


_ECHO_FRAME = {
    "haekkadi", "laekkadi", "fjolgadi", "faekkadi", "haekka", "laekka",
    "rose", "risen", "fell", "fallen", "increased", "decreased", "increase", "decrease",
    "percent", "percentage", "hlutfall", "prosent", "tonnes", "tonn", "number", "fjoldi",
    "hvert", "hvort",
}
_VALUE_CACHE: dict[str, list[list[str]]] | None = None


def _value_lists() -> dict[str, list[list[str]]]:
    """Table URL to the value labels of each variable. Loaded once."""
    global _VALUE_CACHE
    if _VALUE_CACHE is not None:
        return _VALUE_CACHE
    import gzip
    import json
    from pathlib import Path

    found: dict[str, list[list[str]]] = {}
    candidates = []
    raw = os.environ.get("GRUND_INDEX", "").strip()
    if raw:
        candidates.append(Path(raw) / "tables.jsonl.gz")
    candidates.append(Path(__file__).resolve().parents[2] / "data" / "index" / "tables.jsonl.gz")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        _VALUE_CACHE = {}
        return _VALUE_CACHE
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            url = str(payload.get("url") or "")
            if not url:
                continue
            lists = []
            for variable in payload.get("variables") or []:
                labels = []
                for item in variable.get("values") or []:
                    if isinstance(item, dict):
                        labels.append(str(item.get("text") or ""))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        labels.append(str(item[1]))
                lists.append(labels)
            found[url] = lists
    _VALUE_CACHE = found
    return _VALUE_CACHE


def _sibling_values(result: dict, label: str) -> list[str]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    url = str(source.get("api_url") or source.get("web_url") or "")
    lists = _value_lists()
    chosen = lists.get(url)
    if chosen is None and url:
        for key, value in lists.items():
            if url.rstrip("/") == key.rstrip("/"):
                chosen = value
                break
    if not chosen:
        return []
    target = fold(label)
    for labels in chosen:
        if any(fold(item) == target for item in labels):
            return labels
    return []


def _echo_outside(question: str, title: str) -> list[str]:
    """Question words that are not the table title, a dimension, or the question frame."""
    from grund.bind import _DIMENSION, _forms, _title_forms

    covered = _title_forms(title)
    found = []
    for token in __import__("grund_index.textutil", fromlist=["tokens"]).tokens(question):
        if len(token) < 5 or token.isdigit() or token in _ECHO_FRAME:
            continue
        forms = _forms(token)
        if forms & _DIMENSION or forms & covered or forms & _ECHO_FRAME:
            continue
        found.append(token)
    return found


def _word_in(token: str, text: str) -> bool:
    from grund.bind import _forms
    from grund_index.textutil import tokens as word_tokens

    forms = _forms(token)
    if len(token) >= 6 and token.endswith("s"):
        forms.add(token[:-1])
    for other in word_tokens(text):
        other_forms = _forms(other)
        if len(other) >= 6 and other.endswith("s"):
            other_forms.add(other[:-1])
        if forms & other_forms:
            return True
        if len(token) >= 6 and len(other) >= 6 and token[:6] == other[:6]:
            return True
    return False


def _echo_cell(question: str, result: dict) -> str | None:
    """A title-echo cell: the question names no row, and the label is only the title.

    A share of an unnamed part, a total that has an of-which sibling, or a
    total that drops a title noun some other row still carries. A marriage
    total and a hospital-bed total stay.
    """
    from grund.bind import _of_which_label, aggregate_label, title_only_label
    from grund_index.textutil import fold as fold_text
    from grund_index.textutil import tokens as word_tokens

    if not question or result.get("value") in (None, ""):
        return None
    title, pairs, _periods = _cited(result)
    if not title or _echo_outside(question, title):
        return None
    operation = _stated_operation(result)
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    if not operation:
        operation = str(source.get("operation") or "")
    if operation == "share":
        return "bind2-echo:share"
    labels = [label for _key, label in pairs if label]
    for label in labels:
        if not aggregate_label(label) or not title_only_label(label, title):
            continue
        siblings = _sibling_values(result, label)
        if any(_of_which_label(item) for item in siblings):
            return "bind2-echo:of-which"
        folded_title = fold_text(title)
        if " and " in folded_title or " og " in folded_title:
            continue
        for token in word_tokens(title):
            if len(token) < 8 or _word_in(token, label):
                continue
            if any(_word_in(token, other) for other in siblings if fold_text(other) != fold_text(label)):
                return "bind2-echo:title-row"
    return None


def echo_reason(question: str, result: dict) -> str | None:
    """Why this stated cell only repeats the title, or None to keep it."""
    if not echo_enabled() or result.get("refused"):
        return None
    if not question or result.get("value") in (None, ""):
        return None
    from grund.compound import split_question

    split = split_question(question)
    clause = split[1] if split is not None else question
    return _echo_cell(clause, result)
