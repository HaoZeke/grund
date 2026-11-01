"""Read an operation and the time points out of a question.

The rest of the question is a bag of tokens for the binder. No numbers are
computed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from grund_index.textutil import fold, tokens

_MONTHS = {
    "january": 1, "jan": 1, "januar": 1,
    "february": 2, "feb": 2, "februar": 2,
    "march": 3, "mar": 3, "mars": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8, "agust": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "desember": 12, "des": 12,
}

_ICELANDIC_CHARS = set("áéíóúýþðæöÁÉÍÓÚÝÞÐÆÖ")
_IS_HINTS = ("hvad", "hversu", "hver", "manafjoldi", "visitala", "arinu", "ibu", "konur", "karlar")


@dataclass
class ParsedQuestion:
    text: str
    language: str
    folded: str
    operation: str
    periods: list[tuple[int, int | None]] = field(default_factory=list)
    rebase_year: int | None = None
    latest: bool = False
    query_tokens: list[str] = field(default_factory=list)
    quarter: tuple[int, int] | None = None


def detect_language(text: str) -> str:
    if any(char in _ICELANDIC_CHARS for char in text):
        return "is"
    folded = fold(text)
    if any(hint in folded.split() for hint in _IS_HINTS):
        return "is"
    return "en"


def _change_denied(folded: str) -> bool:
    """The change words exclude the change column. They are not a request for it."""
    return re.search(
        r"\b(not|ekki|rather than|instead of)\b.{0,48}\b(annual change|arsbreyting|the change)\b"
        r"|"
        r"\b(index level|the level)\b.{0,40}\bnot\b",
        folded or "",
    ) is not None


def _operation(folded: str) -> tuple[str, int | None]:
    rebase = re.search(
        r"\b(?:rebas\w*|endurreikn\w*|new base|ny\w* grunn\w*|so that|thannig ad)\b.{0,24}((?:19|20)\d{2})",
        folded,
    )
    if rebase is None:
        rebase = re.search(r"\b((?:19|20)\d{2})\s*=\s*100\b", folded)
        if rebase and re.search(r"\b(?:rebas|endurreikn|so that|thannig|new base|nyr grunn)\b", folded):
            return "rebase", int(rebase.group(1))
        rebase = None
    if rebase:
        return "rebase", int(rebase.group(1))
    if re.search(r"\b(per capita|per person|per inhabitant|a mann|per ibua|a hvern)\b", folded):
        return "per_capita", None
    if re.search(r"\b(together|samtals)\b", folded) and re.search(r"\b(and|og)\b", folded):
        return "sum", None
    if re.search(r"\b(by what percent\w*|um hve m\w+ prosent\w*)\b", folded):
        return "yoy_pct", None
    if re.search(r"\b(percentage of|percent of|hlutfall af|hlutdeild af|what share|what proportion)\b", folded) or re.search(
        r"\bhversu\b.{0,30}\b(hlutfall|hlutdeild)\b", folded
    ) or re.search(r"\bhve stort hlutfall\b", folded):
        return "share", None
    # "By how much" is a difference even when the verb is "rose" or "hækkaði".
    # "Fjöldi og hlutfall" names the table. It is not "what percentage of".
    if re.search(r"\b(by how much|by how many|um hve mikid|um hversu mikid|um hve marg\w*|um hve morg\w*)\b", folded):
        return "difference", None
    if not _change_denied(folded) and re.search(
        r"\b(annual change|yearly change|year on year|yoy|over the year|arleg\w*\s+breyting\w*|arbreyting|"
        r"breyting milli|percent change|prosentubreyting|hjaekk\w*|laekk\w*|"
        r"change from|increased|decreased|risen|rose)\b",
        folded,
    ):
        return "yoy_pct", None
    if re.search(r"\b(difference|how many more|mismunur|fleiri)\b", folded):
        return "difference", None
    return "level", None


_QUARTER_WORDS = {
    "first": 1, "1st": 1, "fyrsta": 1, "fyrsti": 1,
    "second": 2, "2nd": 2, "odrum": 2, "annar": 2, "annars": 2,
    "third": 3, "3rd": 3, "thridja": 3, "thridji": 3,
    "fourth": 4, "4th": 4, "fjorda": 4, "fjordi": 4,
}


def _quarter(folded: str) -> tuple[int, int] | None:
    match = re.search(
        r"\b(first|second|third|fourth|1st|2nd|3rd|4th|odrum|fyrsta|fyrsti|annar|annars|"
        r"thridja|thridji|fjorda|fjordi)\b.{0,30}\b(?:quarter|arsfjordung\w*)\b.{0,24}\b((?:19|20)\d{2})\b",
        folded,
    )
    if match is None:
        match = re.search(
            r"\b((?:19|20)\d{2})\b.{0,16}\b(q\s*([1-4])|([1-4])\s*\.?\s*arsfjordung\w*)\b",
            folded,
        )
        if match is None:
            return None
        number = match.group(3) or match.group(4)
        return int(match.group(1)), int(number)
    number = _QUARTER_WORDS.get(match.group(1))
    if number is None:
        return None
    return int(match.group(2)), number


def _price_base_rule() -> bool:
    from grund.heuristics import enabled

    return enabled("price_base_year")


def _periods(folded: str) -> list[tuple[int, int | None]]:
    explicit = []
    for match in re.finditer(r"\b((?:19|20)\d{2})\s*m\s*(\d{1,2})\b", folded):
        explicit.append((int(match.group(1)), int(match.group(2))))
    if explicit:
        return explicit
    year_marks = []
    for match in re.finditer(r"\b(?:19|20)\d{2}\b", folded):
        # "base 1988" and "1988 base" name an index base, not a period to select.
        window = 40 if _price_base_rule() else 24
        before = folded[max(0, match.start() - window) : match.start()]
        after = folded[match.end() : match.end() + 16]
        if re.search(r"\b(?:base|grunn\w*)\s*$", before) or re.search(r"^\s*(?:base|grunn\w*)\b", after):
            continue
        # "1988 er sett sem 100" names the index base, not the period asked for.
        if re.search(r"^\s*(?:er\s+)?sett\w*\s+sem\s+100\b", after) or re.search(r"=\s*100", after):
            continue
        # "fixed prices of 2006" and "á verðlagi ársins 2006" are a price base.
        if _price_base_rule() and re.search(
            r"(?:fixed prices of|prices of|verdlagi(?:\s+arsins)?|verdlag)\s*$", before
        ):
            continue
        year_marks.append((match.start(), int(match.group(0))))
    years = [year for _position, year in year_marks]
    months = []
    for match in re.finditer(r"[a-z]+", folded):
        number = _MONTHS.get(match.group(0))
        if number:
            months.append((match.start(), number))
    if months and year_marks:
        pairs = []
        used_years = set()
        for position, month in months:
            # "September 2026" puts the year just after the month. A year that
            # sits before the month ("2025 to September") is the previous phrase.
            following = [
                (pos, year) for pos, year in year_marks if 0 <= pos - position <= 16
            ]
            if following:
                year_at, nearest = min(following, key=lambda item: item[0] - position)
            else:
                year_at, nearest = min(year_marks, key=lambda item: abs(item[0] - position))
            # "June 2024" and "January-February" after "In 2005" sit next to the
            # year. "in December" inside a copied table title, with the year
            # much later, is not a month to select.
            if following or abs(year_at - position) <= 40:
                pairs.append((nearest, month))
                used_years.add(nearest)
        for year in years:
            if year not in used_years:
                pairs.append((year, None))
        # Stable, unique, year then month.
        unique = list(dict.fromkeys(pairs))
        return unique
    return [(year, None) for year in dict.fromkeys(years)]


def resolve_references(text: str) -> str:
    """Copy a year or a subject noun onto a later clause that only points back.

    ``sama ár``, ``þeirra``, ``sú hækkun`` and ``hún`` do not name a new
    period or a new subject. The earlier clause already did.
    """
    clauses = re.split(r"(?<=[.?!])\s+", text.strip())
    joiner = " "
    if len(clauses) == 1:
        clauses = re.split(r"\s+\bog\s+(?=hver|hve|hvað|hversu)", text.strip(), maxsplit=1, flags=re.IGNORECASE)
        joiner = " og "
    if len(clauses) < 2:
        return text
    years = re.findall(r"\b(?:19|20)\d{2}\b", clauses[0])
    nouns = [
        word
        for word in re.findall(r"[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöð]+", clauses[0])
        if len(word) >= 6 and fold(word) not in {"hversu", "margir", "margar", "voru", "skradir"}
    ]
    rebuilt = [clauses[0]]
    for clause in clauses[1:]:
        folded = fold(clause)
        extra: list[str] = []
        points_back = bool(
            re.search(r"\b(sama\s+ar\w*|theirra|their|hun|hann|su\s+haekkun\w*|su\s+breyting\w*)\b", folded)
        )
        if points_back and years and not re.search(r"\b(?:19|20)\d{2}\b", clause):
            if re.search(r"haekkun|breyting|increase", folded) and len(years) >= 2:
                extra.extend(years[:2])
            else:
                extra.append(years[-1])
        if points_back and nouns and not any(fold(noun) in folded for noun in nouns):
            extra.append(nouns[-1])
        if extra:
            clause = clause.rstrip(" ?") + " " + " ".join(dict.fromkeys(extra))
            if text.strip().endswith("?") and not clause.endswith("?"):
                clause += "?"
        rebuilt.append(clause)
    return joiner.join(rebuilt)


def parse_question(text: str, language: str | None = None) -> ParsedQuestion:
    chosen = language or detect_language(text)
    folded = fold(text)
    operation, rebase_year = _operation(folded)
    periods = _periods(folded)
    quarter = _quarter(folded)
    if quarter is not None:
        periods = [(quarter[0], None)]
    latest = bool(
        re.search(r"\b(latest|most recent|newest|nyjast\w*|sidast\w*|seinast\w*|nyjasta)\b", folded)
    )
    return ParsedQuestion(
        text=text,
        language=chosen,
        folded=folded,
        operation=operation,
        periods=periods,
        rebase_year=rebase_year,
        latest=latest or not periods,
        query_tokens=tokens(text, expand=True),
        quarter=quarter,
    )
