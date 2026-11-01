"""Icelandic and English time expressions used on statistical questions.

Covers a stock at year end ("árslok 2025"), a quarter
("á fjórða ársfjórðungi"), a comparison across years ("milli ára"),
annual averages, and an index base year ("grunnur 1988", "1988=100").
"""

from __future__ import annotations

import re

from grund_lang.types import DateSpan

_YEAR = r"(?:19|20)\d{2}"
_QUARTER = r"ársfjórðung(?:s|ur|i|um|inn|inum|num|ar)?"
_ORD = (
    r"fyrsta|fyrsti|fyrstan|annan|annar|annars|öðrum|öðru|aðra|"
    r"þriðja|þriðji|þriðju|fjórða|fjórði|fjórðu|"
    r"first|second|third|fourth|1st|2nd|3rd|4th"
)
_ORD_NUM = {
    "fyrsta": 1, "fyrsti": 1, "fyrstan": 1,
    "annan": 2, "annar": 2, "annars": 2, "öðrum": 2, "öðru": 2, "aðra": 2,
    "þriðja": 3, "þriðji": 3, "þriðju": 3,
    "fjórða": 4, "fjórði": 4, "fjórðu": 4,
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
}
_MONTHS = {
    "janúar": 1, "januar": 1, "january": 1,
    "febrúar": 2, "februar": 2, "february": 2,
    "mars": 3, "march": 3,
    "apríl": 4, "april": 4,
    "maí": 5, "mai": 5, "may": 5,
    "júní": 6, "juni": 6, "june": 6,
    "júlí": 7, "juli": 7, "july": 7,
    "ágúst": 8, "agust": 8, "august": 8,
    "september": 9,
    "október": 10, "oktober": 10, "october": 10,
    "nóvember": 11, "november": 11,
    "desember": 12, "december": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

_BASE = re.compile(
    rf"(?:grunn(?:ur|i)?|base)\s*({_YEAR})|({_YEAR})\s*=\s*100",
    re.IGNORECASE,
)
_BETWEEN = re.compile(
    rf"milli\s+áranna\s+({_YEAR})\s+og\s+({_YEAR})"
    rf"|frá\s+({_YEAR})\s+til\s+({_YEAR})"
    rf"|from\s+({_YEAR})\s+to\s+({_YEAR})"
    rf"|between\s+({_YEAR})\s+and\s+({_YEAR})",
    re.IGNORECASE,
)
_BETWEEN_BARE = re.compile(r"milli\s+ára\b", re.IGNORECASE)
_YEAR_END = re.compile(
    rf"árslok(?:um|in)?(?:\s+ársins)?(?:\s+({_YEAR}))?"
    rf"|(?:í|við)\s+lok\s+árs(?:ins)?(?:\s+({_YEAR}))?"
    rf"|year-?end(?:\s+of)?(?:\s+({_YEAR}))?"
    rf"|end\s+of(?:\s+the)?\s+year(?:\s+({_YEAR}))?",
    re.IGNORECASE,
)
_YEAR_START = re.compile(
    rf"ársbyrjun(?:\s+({_YEAR}))?"
    rf"|í\s+byrjun\s+árs(?:ins)?(?:\s+({_YEAR}))?"
    rf"|beginning\s+of(?:\s+the)?\s+year(?:\s+({_YEAR}))?",
    re.IGNORECASE,
)
_QUARTER_IS = re.compile(
    rf"(?:á\s+)?(?:({_ORD})|(\d))\s*\.?\s*{_QUARTER}(?:\s+(?:árið|ársins)?\s*({_YEAR}))?",
    re.IGNORECASE,
)
_QUARTER_EN = re.compile(
    rf"({_ORD})\s+quarter(?:\s+of)?(?:\s+({_YEAR}))?",
    re.IGNORECASE,
)
_QUARTER_CODE = re.compile(
    rf"q\s*([1-4])(?:\s+|/)?({_YEAR})|({_YEAR})\s*q\s*([1-4])",
    re.IGNORECASE,
)
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})\.?\s+({_MONTH_ALT})\.?\s+({_YEAR})\b",
    re.IGNORECASE,
)
_MONTH_YEAR = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+({_YEAR})\b",
    re.IGNORECASE,
)
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eitt": 1, "ein": 1, "eina": 1,
    "tvö": 2, "tvær": 2, "tvo": 2, "tveimur": 2, "tveim": 2,
    "þrjú": 3, "þrjá": 3, "þremur": 3, "þrem": 3,
    "fjögur": 4, "fjóra": 4, "fjórum": 4,
    "fimm": 5, "sex": 6, "sjö": 7, "átta": 8, "níu": 9, "tíu": 10,
}
_RECENT = re.compile(
    r"(?:síðustu|seinustu|undanfarin(?:u|um)?|liðin(?:um)?|"
    r"over the last|over the past|last|past)"
    r"\s+(\d{1,2}|[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöð]+)"
    r"\s+(?:ár(?:in(?:um)?|um|a|unum)?|years?)\b",
    re.IGNORECASE,
)
_ANNUAL_AVG = re.compile(
    rf"ársmeðalt(?:al|öl|alið|als)?(?:\s+({_YEAR}))?|annual\s+averages?(?:\s+of)?(?:\s+({_YEAR}))?|yearly\s+averages?",
    re.IGNORECASE,
)
_BARE_YEAR = re.compile(rf"\b({_YEAR})\b")


def find_bases(text: str) -> list[int]:
    """Index base years named as 'grunnur 1988' or '1988=100'."""
    found: list[int] = []
    for match in _BASE.finditer(text):
        raw = match.group(1) or match.group(2)
        year = int(raw)
        if year not in found:
            found.append(year)
    return found


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(not (end <= left or start >= right) for left, right in spans)


def _recent_count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token.lower())


def _year_from(match: re.Match[str]) -> int | None:
    for group in match.groups():
        if group and re.fullmatch(_YEAR, group):
            return int(group)
    return None


def parse_dates(text: str) -> list[DateSpan]:
    """Time expressions in `text`, most specific first.

    A year that only names an index base is not returned as a data year.
    A year already inside a quarter, a month, or a range is not repeated.
    """
    found: list[DateSpan] = []
    taken: list[tuple[int, int]] = []
    bases = find_bases(text)
    for match in _BASE.finditer(text):
        taken.append(match.span())

    def add(span: DateSpan, start: int, end: int) -> None:
        if _overlaps(start, end, taken):
            return
        found.append(span)
        taken.append((start, end))

    for match in _BETWEEN.finditer(text):
        years = [int(group) for group in match.groups() if group]
        if len(years) >= 2:
            add(
                DateSpan(kind="between_years", year=years[0], end_year=years[1], raw=match.group(0)),
                *match.span(),
            )
    for match in _BETWEEN_BARE.finditer(text):
        add(DateSpan(kind="between_years", raw=match.group(0)), *match.span())
    for match in _YEAR_END.finditer(text):
        add(DateSpan(kind="year_end", year=_year_from(match), raw=match.group(0)), *match.span())
    for match in _YEAR_START.finditer(text):
        add(DateSpan(kind="year_start", year=_year_from(match), raw=match.group(0)), *match.span())
    for match in _QUARTER_IS.finditer(text):
        word, digit, year = match.group(1), match.group(2), match.group(3)
        quarter = int(digit) if digit else _ORD_NUM.get((word or "").lower())
        if quarter is None or not 1 <= quarter <= 4:
            continue
        add(
            DateSpan(
                kind="quarter",
                year=int(year) if year else None,
                quarter=quarter,
                raw=match.group(0),
            ),
            *match.span(),
        )
    for match in _QUARTER_EN.finditer(text):
        quarter = _ORD_NUM.get(match.group(1).lower())
        if quarter is None:
            continue
        year = match.group(2)
        add(
            DateSpan(
                kind="quarter",
                year=int(year) if year else None,
                quarter=quarter,
                raw=match.group(0),
            ),
            *match.span(),
        )
    for match in _QUARTER_CODE.finditer(text):
        quarter = int(match.group(1) or match.group(4))
        year = int(match.group(2) or match.group(3))
        add(DateSpan(kind="quarter", year=year, quarter=quarter, raw=match.group(0)), *match.span())
    for match in _DAY_MONTH.finditer(text):
        day = int(match.group(1))
        month = _MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        add(
            DateSpan(kind="point", year=year, month=month, day=day, raw=match.group(0)),
            *match.span(),
        )
    for match in _MONTH_YEAR.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        year = int(match.group(2))
        add(DateSpan(kind="month", year=year, month=month, raw=match.group(0)), *match.span())
    for match in _RECENT.finditer(text):
        count = _recent_count(match.group(1))
        if count is None or not 1 <= count <= 20:
            continue
        add(DateSpan(kind="recent_years", count=count, raw=match.group(0)), *match.span())
    for match in _ANNUAL_AVG.finditer(text):
        year = _year_from(match)
        add(DateSpan(kind="annual_average", year=year, raw=match.group(0)), *match.span())
    for match in _BARE_YEAR.finditer(text):
        year = int(match.group(1))
        if year in bases and _overlaps(*match.span(), taken):
            continue
        if any(span.year == year or span.end_year == year for span in found):
            continue
        add(DateSpan(kind="year", year=year, raw=match.group(0)), *match.span())
    return found
