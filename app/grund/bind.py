"""Choose a table's variable codes for a parsed question.

Binding fails closed. A variable that is not eliminable and that we cannot
match is a reason to try the next table, not a reason to POST every code.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from grund_index.model import Edition, Variable
from grund_index.textutil import SYNONYMS, fold, icelandic_text, inflections, lemmas, near_token, tokens

from grund.cells import _is_time_variable, refine_selection, top_total
from grund.parse import ParsedQuestion

_TOTAL = {
    "total", "totals", "all", "alls", "iceland", "samtals", "heild", "island",
    "allir", "allar", "oll", "landid", "whole", "allt",
}
# A region codelist's national row. "Allt landið" is that row; "Austurland" is not.
_NATIONAL_TOTAL = {
    "allt landid", "oll landid", "whole country", "entire country", "all regions",
    # The English edition prints "Allt landið" as "Whole county".
    "whole county",
}
_CHANGE = (
    "annual change",
    "yearly change",
    "change from previous year",
    "arbreyting",
    "arsbreyting",
    "breyting fra fyrra ari",
    "population increase",
    "prosentubreyting",
    "monthly change",
)


@dataclass
class Binding:
    edition: Edition
    selections: list[dict]
    operation: str
    score: float
    time_var: str | None
    time_codes: list[str]
    group_var: str | None = None
    part_code: str | None = None
    whole_code: str | None = None
    rebase_code: str | None = None
    target_code: str | None = None
    notes: list[str] = field(default_factory=list)
    official_measure: bool = False


# A row such as "Vessels total" or "Skip alls" is the total of that list.
# A longer label that merely contains the word total ("Percentage of total") is not.
_COLLECTIVE = {
    "vessel", "vessels", "ship", "ships", "skip", "number", "fjoldi",
    "item", "items", "type", "types", "tegund", "all",
    "edition", "editions", "utgafa", "utgafur",
}


def is_total(text: str) -> bool:
    folded = fold(text).strip()
    if folded in _NATIONAL_TOTAL:
        return True
    if folded in _TOTAL or folded in {"0", "-1"}:
        return False if folded in {"0", "-1"} else True
    found = set(tokens(text))
    if not found:
        return False
    if found <= _TOTAL:
        return True
    # "All editions" is the total of that list. "All" is the English "alls".
    if found & {"total", "alls", "samtals", "all"} and found <= (_TOTAL | _COLLECTIVE):
        if "of all" in folded or "of total" in folded:
            return False
        return True
    # "Lok hjúskapar alls" and "Marriages dissolved, total" are the total row.
    # "Percentage of total" is a unit, not that row.
    if re.search(r"(?:^|[\s,])(alls|total|samtals)\s*$", folded):
        if "of total" not in folded and "percentage" not in folded and "hlutfall" not in folded:
            return True
    return False


# A question says "by region" or "eftir tegundum" to name the dimension.
# Those words are not a request for the one row that repeats them.
_DIMENSION = {
    "sex", "gender", "kyn", "age", "aldur", "ages", "municipality", "sveitarfelag",
    "region", "landshluti", "landsvaedi", "country", "land", "citizenship",
    "rikisfang", "year", "ar", "month", "manudur", "quarter", "arsfjordungur",
    "unit", "eining", "type", "tegund", "category", "flokkur", "total", "alls",
    "by", "eftir", "and", "og", "from", "fra",
}
_OF_WHICH_MARK = ("thar af", "of which", "thereof", "whereof", "tharaf", "of whom", "par af")


def _of_which_label(label: str) -> bool:
    folded = fold(label)
    return any(marker in folded for marker in _OF_WHICH_MARK)


def aggregate_label(label: str) -> bool:
    """A total row, including a qualified total such as "Domestic assets, total".

    "Samtals endurunnið" starts with the total word. "Endurnýting alls, þar af"
    is a heading. "Total weight" is a unit, not a total row. "Whole county"
    is the national row.
    """
    if not label or _of_which_label(label):
        return False
    if is_total(label):
        return True
    folded = fold(label).strip(" .:-")
    if "total weight" in folded or "heildarthyngd" in folded or "of total" in folded:
        return False
    if re.search(r"^(?:alls|total|samtals)\b", folded):
        return True
    return bool(re.search(r"(?:^|[\s,])(?:alls|total|samtals)\s*$", folded))


def _forms(token: str, *, icelandic: bool = False) -> set[str]:
    found = {token, *lemmas(token, icelandic=icelandic)}
    for form in list(found):
        found.update(SYNONYMS.get(form, []))
    return {form for form in found if form}


def _title_forms(title: str, variable: Variable | None = None) -> set[str]:
    blob = title or ""
    if variable is not None:
        blob = f"{blob} {variable.text} {variable.code}"
    icelandic = icelandic_text(blob)
    forms: set[str] = set()
    for token in tokens(blob):
        forms.update(_forms(token, icelandic=icelandic))
    return forms


def _query_token_ignored(token: str, title_forms: set[str]) -> bool:
    """A title word or a dimension name does not pick a row.

    "museums" is the title word "museum". It is not a separate category.
    """
    forms = _forms(token)
    if len(token) >= 6 and token.endswith("s"):
        forms.add(token[:-1])
    if forms & _DIMENSION:
        return True
    if forms & title_forms:
        return True
    return False


def _content_tokens(label: str) -> list[str]:
    stop = {"total", "totals", "alls", "samtals", "all", "heild"}
    return [
        token for token in tokens(label)
        if len(token) >= 4 and token not in stop and token not in _DIMENSION
    ]


def _question_mentions(label: str, query: set[str]) -> bool:
    """True when the question uses a content word of this label.

    "Total annual income" is mentioned by "income". "Heildartekjur" is
    mentioned by "tekjur". "Domestic assets, total" is not mentioned by a
    question that only says "deposits and lending".
    """
    if not label or not query:
        return False
    for token in _content_tokens(label):
        if _forms(token) & query or _token_hit(token, query):
            return True
        for form in _forms(token):
            if _token_hit(form, query):
                return True
        for other in query:
            if len(other) >= 5 and (token.endswith(other) or token.startswith(other)):
                return True
    return False


def label_named_by(label: str, query: set[str]) -> bool:
    """True when the question writes this label, in either language.

    Matching uses the label's lemmas, not only the printed inflection.
    A dimension word such as "region" does not count.
    """
    if not label or not query:
        return False
    for token in tokens(label):
        if len(token) < 4 or token in _DIMENSION:
            continue
        forms = _forms(token)
        if forms & _DIMENSION:
            continue
        if forms & query or _token_hit(token, query):
            return True
        for form in forms:
            if _token_hit(form, query):
                return True
    return False


def title_only_label(label: str, title: str, variable_text: str = "") -> bool:
    """True when every content word of the label is already in the table title."""
    forms: set[str] = set()
    for token in tokens(f"{title} {variable_text}"):
        forms.update(_forms(token))
    words = []
    for token in tokens(label):
        if len(token) < 4 or token in _DIMENSION or token in {"total", "totals", "alls", "samtals", "all"}:
            continue
        words.append(token)
    if not words:
        return False
    for token in words:
        if _title_word(token, forms):
            continue
        return False
    return True


def _title_word(token: str, forms: set[str]) -> bool:
    """A title word, including a plural that only adds -s ('book' / 'books')."""
    own = _forms(token)
    if own & forms or own & _DIMENSION:
        return True
    if len(token) > 4 and token.endswith("s") and _forms(token[:-1]) & forms:
        return True
    return False


_PEER_CACHE: dict[str, dict[str, dict[str, str]]] | None = None


def _peer_index() -> dict[str, dict[str, dict[str, str]]]:
    """url → variable code → value code → label. Loaded once from the catalogue."""
    global _PEER_CACHE
    if _PEER_CACHE is not None:
        return _PEER_CACHE
    import gzip
    import json
    import os
    from pathlib import Path

    found: dict[str, dict[str, dict[str, str]]] = {}
    candidates = []
    raw = os.environ.get("GRUND_INDEX", "").strip()
    if raw:
        candidates.append(Path(raw) / "tables.jsonl.gz")
    candidates.append(Path(__file__).resolve().parents[2] / "data" / "index" / "tables.jsonl.gz")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        _PEER_CACHE = {}
        return _PEER_CACHE
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            url = str(payload.get("url") or "")
            if not url:
                continue
            bucket: dict[str, dict[str, str]] = {}
            for variable in payload.get("variables") or []:
                values: dict[str, str] = {}
                for pair in variable.get("values") or []:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        values[str(pair[0])] = str(pair[1])
                bucket[str(variable.get("code"))] = values
            found[url] = bucket
    _PEER_CACHE = found
    return found


def _alias_map(edition: Edition, peer: Edition | None = None) -> dict[str, dict[str, str]]:
    """variable code → value code → the other language's label."""
    if peer is not None:
        mapped: dict[str, dict[str, str]] = {}
        for variable in edition.variables:
            other = peer.variable(variable.code)
            if other is None:
                continue
            mapped[variable.code] = {code: other.label(code) for code, _label in other.values}
        return mapped
    if "hagstofa.is" not in (edition.url or ""):
        return {}
    index = _peer_index()
    mine = edition.url
    name = mine.rstrip("/").rsplit("/", 1)[-1]
    for url, variables in index.items():
        if url == mine:
            continue
        if url.rstrip("/").rsplit("/", 1)[-1] != name:
            continue
        return variables
    return {}


_LOOSE_WORDS = {
    "population", "mannfjoldi", "iceland", "island", "inhabitants", "percentage",
    "hlutfall",     "overnight", "registered", "accommodation", "gistinatt", "gistinaetur",
    "gistinottum", "gististodum", "launavisitalan", "launavisitala",
    "innflytjendum", "innflytjendur",
}


def _covers_specific_words(parsed: ParsedQuestion, edition: Edition, chosen: dict[str, list[str]]) -> bool:
    """A long word such as "immigrants" has to land in the title or in a chosen label."""
    blob = set(tokens(edition.title, expand=True))
    for code, values in chosen.items():
        variable = edition.variable(code)
        if variable is None:
            continue
        for value in values:
            blob.update(tokens(variable.label(value), expand=True))
    surface = set(tokens(parsed.text, expand=False))
    from grund.frame import current_frame

    frame = current_frame()
    place_stem = ""
    if frame is not None and frame.use and frame.municipality:
        place_stem = fold(frame.municipality)[:8]
    for token in parsed.query_tokens:
        if token not in surface or len(token) < 10 or token in _LOOSE_WORDS:
            continue
        if place_stem and place_stem in token:
            continue
        forms = {token, *inflections(token)}
        for form in list(forms):
            forms.update(SYNONYMS.get(form, []))
        if any(form in blob or _token_hit(form, blob) for form in forms):
            continue
        from grund.istown import town_word_covered

        if town_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.isregion import region_word_covered

        if region_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.istrade import trade_kind

        if trade_kind(parsed.text, parsed.language) is not None and fold(getattr(edition, "title", "") or "").find("landsframleid") >= 0:
            if token.startswith(("thjonust", "voru", "utflutn", "innflutn", "goods", "service", "export", "import")):
                continue
        from grund.iscpi import cpi_word_covered

        if cpi_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.iswage import wage_word_covered

        if wage_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.isstays import stays_word_covered

        if stays_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.isquarter import quarter_word_covered

        if quarter_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.ispop import pop_word_covered

        if pop_word_covered(token, parsed.text, parsed.language, edition, chosen):
            continue
        from grund.isjobs import survey_unemployment

        # The annual labour-force survey table does not print that phrase.
        if survey_unemployment(parsed.text, parsed.language) and token.startswith("vinnumarkadsrannsokn"):
            continue
        return False
    return True


def _unwanted_label(label: str, question: str) -> bool:
    folded_bits = fold(label)
    if any(marker in folded_bits for marker in ("first born", "fyrst faedd", "andvana", "stillborn")):
        if not any(marker in question for marker in ("first", "fyrst", "andvana", "stillborn")):
            return True
    return False


def _prefix_len(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _stem_token(token: str) -> str:
    for suffix in ("inum", "inna", "inu", "inn", "ur", "ar", "ir", "um"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 6:
            return token[: -len(suffix)]
    if len(token) >= 8 and token[-1] in "aeiou":
        return token[:-1]
    return token


def _words_outside_title(label: str, title_tokens: set[str]) -> list[str]:
    """Label words that are not already the table title."""
    found = []
    for token in tokens(label):
        if len(token) < 4:
            continue
        if any(token == other or near_token(token, other) for other in title_tokens):
            continue
        found.append(token)
    return found


def _already_named(token: str, hits: set[str]) -> bool:
    """True when this query word is the same stem as one the first label already used."""
    if token in hits:
        return True
    return any(near_token(token, other) or near_token(token, form) for other in hits for form in lemmas(other))


def _token_hit(token: str, others: set[str]) -> bool:
    """A label word matches a question word, including Icelandic compounds.

    "Reykjavík" is the start of "Reykjavíkurborg". A shared prefix that is not
    the whole shorter word does not match: "atvinnuleysi" is not "atvinnuþátttaka".
    """
    if token in others:
        return True
    stems = {_stem_token(token)}
    if len(token) >= 7:
        stems.add(token)
    for other in others:
        other_stem = _stem_token(other)
        for stem in stems:
            if len(stem) < 7 or len(other_stem) < 7:
                continue
            if other.startswith(stem) or stem.startswith(other_stem) or other_stem.startswith(stem):
                return True
            if near_token(stem, other_stem) or near_token(token, other):
                return True
    return False


def _value_score(query: set[str], question: str, label: str) -> tuple[float, int]:
    label_tokens = tokens(label)
    folded_label = fold(label).strip()
    # "Iceland" in the question is the country, not a column to hunt for.
    if folded_label in {"iceland", "island"} or set(label_tokens) <= {"iceland", "island"}:
        return 0.15, 0
    phrase = 1.6 if folded_label and len(folded_label) >= 12 and folded_label in question else 0.0
    if _change_denied(question) and any(
        phrase_text in folded_label for phrase_text in ("annual change", "arsbreyting", "arbreyting")
    ):
        return 0.0, 0
    if not label_tokens:
        return phrase, 0
    if _unwanted_label(label, question):
        return 0.0, 0
    if re.search(r"\b(points?|stig)\b", question):
        folded_bits = fold(label)
        if any(marker in folded_bits for marker in ("change", "breyting", "%", "percent", "prosent")):
            return 0.0, 0
    overlap = [token for token in label_tokens if _token_hit(token, query)]
    if not overlap and not phrase:
        return 0.0, 0
    precision = len(overlap) / len(label_tokens)
    extras = len(label_tokens) - len(overlap)
    score = precision * 2.0 + 0.35 * len(overlap) + phrase - 0.35 * extras
    return score, len(overlap)


def _match_quarter(codes: list[str], year: int, quarter: int) -> str | None:
    wanted = {f"{year}Q{quarter}".upper(), f"{year}A{quarter}".upper()}
    for code in codes:
        folded_code = code.upper().replace("Á", "A").replace("á", "A").replace(" ", "")
        if folded_code in wanted:
            return code
    return None


def _monthly_codes(codes: list[str]) -> list[tuple[int, int]]:
    found = []
    for code in codes:
        match = re.fullmatch(r"(\d{4})M(\d{2})", str(code), re.IGNORECASE)
        if match:
            found.append((int(match.group(1)), int(match.group(2))))
    return found


def _next_month_code(codes: list[str]) -> str | None:
    monthly = _monthly_codes(codes)
    if not monthly:
        return None
    year, month = max(monthly)
    if month == 12:
        return f"{year + 1}M01"
    return f"{year}M{month + 1:02d}"


def acceptable_time_value(variable, code: str) -> bool:
    """True for the one monthly code just after the crawled list."""
    nxt = _next_month_code(variable.codes())
    return bool(nxt) and str(code).upper() == nxt.upper()


def _match_period(codes: list[str], year: int, month: int | None) -> str | None:
    if month:
        patterns = {
            f"{year}M{month:02d}".upper(),
            f"{year}M{month}".upper(),
            f"{year}-{month:02d}",
            f"{year}{month:02d}",
        }
        for code in codes:
            if code.upper() in patterns or code.upper().replace(" ", "") in patterns:
                return code
        return None
    for code in codes:
        if code == str(year):
            return code
    return None


def _previous(codes: list[str], code: str) -> str | None:
    monthly = re.fullmatch(r"(\d{4})M(\d{2})", code, re.IGNORECASE)
    if monthly:
        target = f"{int(monthly.group(1)) - 1}M{monthly.group(2)}".upper()
        for candidate in codes:
            if candidate.upper() == target:
                return candidate
        return None
    if re.fullmatch(r"\d{4}", code):
        target = str(int(code) - 1)
        return target if target in codes else None
    if code in codes:
        index = codes.index(code)
        if index > 0:
            return codes[index - 1]
    return None


def _select_time(variable: Variable, parsed: ParsedQuestion, operation: str) -> list[str] | None:
    from grund.frame import frame_time_codes

    framed = frame_time_codes(variable, parsed)
    if framed is not None:
        return framed
    codes = variable.codes()
    if not codes:
        return None
    periods = list(parsed.periods)
    from grund.iscpi import cpi_periods

    forced_periods = cpi_periods(parsed.text, parsed.language)
    if forced_periods:
        periods = forced_periods
    quarter = parsed.quarter
    if quarter is None:
        from grund.isquarter import quarter_of

        quarter = quarter_of(parsed.text, parsed.language)
    if periods and not (parsed.latest and not parsed.periods):
        chosen: list[str] = []
        for year, month in periods:
            if quarter and quarter[0] == year and month is None:
                match = _match_quarter(codes, quarter[0], quarter[1])
            else:
                from grund.agree_hyb import day_of_month, enabled as agree_hyb

                # "1 January" names the stock date, not January on a monthly table.
                if agree_hyb() and month and day_of_month(parsed.text) and _monthly_codes(codes):
                    match = _match_period(codes, year, None)
                    if match is None:
                        return None
                else:
                    match = _match_period(codes, year, month)
                # Population stock is published for 1 January on a yearly code.
                if match is None and month == 1 and re.search(r"\b1\s*\.?\s*jan", parsed.folded):
                    match = _match_period(codes, year, None)
                # "in December" in a yearly title is not a month code.
                if match is None and month and not _monthly_codes(codes):
                    match = _match_period(codes, year, None)
                # The crawled list can lag the latest published month by one.
                if match is None and month:
                    nxt = _next_month_code(codes)
                    wanted = f"{year}M{month:02d}".upper()
                    if nxt and nxt.upper() == wanted:
                        match = nxt
            if match is None:
                return None
            chosen.append(match)
        if not chosen:
            return None
        deduped = list(dict.fromkeys(chosen))
        if operation == "yoy_pct" and len(deduped) == 1:
            previous = _previous(codes, deduped[0])
            if previous is None:
                return None
            return [previous, deduped[0]]
        if operation == "rebase" and parsed.rebase_year is not None:
            base = _match_period(codes, parsed.rebase_year, None)
            if base and base not in deduped:
                deduped.append(base)
        return deduped
    return [codes[-1]]


_SHARE_QUERY_SKIP = {"percentage", "percent", "proportion", "share", "hlutfall", "hlutdeild"}
_PERCENT_UNIT = re.compile(r"(percentage|percent|hlutfall|prosent|%)")


def _percent_unit(label: str) -> bool:
    return _PERCENT_UNIT.search(fold(label)) is not None


def _person_count_ask(text: str) -> bool:
    if any(word in text for word in ("percent", "prosent", "hlutfall", "rate", "per capita")):
        return False
    return re.search(
        r"\b(population|mannfjold\w*|inhabitants|people|hve marg\w*|how many people|bua|bjuggu|live|lived|lives)\b",
        text,
    ) is not None


def _person_stock(label: str) -> bool:
    folded = fold(label)
    if any(word in folded for word in ("%", "percent", "hlutfall", "rate", "fertility", "frjosemi", "thous", "increase", "fjolgun", "breyting", "change", "immigration", "adjustment", "leidrett")):
        return False
    if "i thus" in folded:
        return False
    return any(word in folded for word in ("population", "mannfjold", "inhabitants", "fjoldi"))


def _gdp_aggregate_label(label: str) -> bool:
    folded = fold(label)
    if "landsframleidsl" not in folded and "gross domestic product" not in folded:
        return False
    blocked = (
        "export", "utflutning", "import", "innflutning", "consumption", "neysl",
        "revenue", "tekjur", "expenditure", "utgjold", "percent", "hlutfall",
        "ratio", "per capita", "a mann", "sparnad", "saving", "thjodartekj",
    )
    return not any(word in folded for word in blocked)


def _measure_value(variable: Variable, parsed: ParsedQuestion) -> str | None:
    """The row that is the asked measure, when the codelist prints it."""
    asked = parsed.folded
    wants_gdp = any(word in asked for word in ("gdp", "landsframleidsl", "thjodarframleidsl", "gross domestic product"))
    names_part = any(word in asked for word in ("export", "utflutning", "import", "innflutning", "consumption", "neysl", "revenue", "tekjur"))
    if wants_gdp and not names_part and "percent" not in asked and "hlutfall" not in asked:
        for code, label in variable.values:
            if _gdp_aggregate_label(label):
                return code
    if _person_count_ask(asked) and len(variable.values) <= 12:
        stocks = [code for code, label in variable.values if _person_stock(label)]
        if stocks:
            return stocks[0]
    return None


def _series_pick_on() -> bool:
    return os.environ.get("GRUND_SERIES_PICK", "").strip().lower() in {"1", "true", "yes"}


def _geo_variable(variable: Variable) -> bool:
    key = fold(f"{variable.text} {variable.code}")
    return any(word in key for word in ("landshluti", "region", "sveitarfelag", "municip"))


def _region_aliases(text: str) -> set[str]:
    """The other language's token for a named region or municipality.

    The English codelist prints "Capital region" and "West". The Icelandic
    question prints the inflected place. Either form should name that row,
    and neither form should name the country total.
    """
    found: set[str] = set()
    pairs = (
        ("hofudborgarsvaed", "capital"),
        ("capital region", "hofudborgarsvaedi"),
        ("capital area", "hofudborgarsvaedi"),
        ("vesturland", "west"),
        ("austurland", "east"),
        ("sudurland", "south"),
        ("nordurlandi eystra", "northeast"),
        ("nordurland vestra", "northwest"),
        ("vestfird", "westfjords"),
        ("westfjord", "vestfirdir"),
        ("hafnarfir", "hafnarfjardarkaupstadur"),
        ("kopavog", "kopavogur"),
        ("akureyr", "akureyri"),
        ("gardabae", "gardabaer"),
        ("reykjanesb", "reykjanesbaer"),
    )
    for stem, alias in pairs:
        if stem in text:
            found.add(alias)
    return found


def _frame_country(variable: Variable, label: str, parsed: ParsedQuestion) -> bool:
    """``in Iceland`` is the country, not the Iceland row of birth or citizenship.

    A question that says born, citizenship, or origin still selects that row.
    """
    key = fold(f"{variable.text} {variable.code}")
    if "type of birth" in key:
        return False
    citizen = any(word in key for word in ("citizen", "rikisfang", "nationalit", "thjoderni"))
    birth = any(word in key for word in ("faeding", "country of birth", "origin", "bakgrunn", "upprun"))
    if "birth" in key and "faedingar" not in key:
        birth = True
    if not citizen and not birth:
        return False
    if fold(label).strip() not in {"iceland", "island", "islandi"}:
        return False
    asked = parsed.folded
    if birth and any(word in asked for word in ("birth", "born", "faed", "origin", "bakgrunn", "upprun")):
        return False
    if citizen and any(word in asked for word in ("citizen", "rikisfang", "rikisborg", "nationalit", "thjoderni", "islensk")):
        return False
    return True


def _postcode_slice(label: str, parsed: ParsedQuestion) -> bool:
    if "reykjavik" not in parsed.folded or re.search(r"\b\d{3}\b", parsed.text):
        return False
    return "reykjavik" in fold(label) and re.search(r"\d{3}", label) is not None


def _named_origin(variable: Variable, parsed: ParsedQuestion) -> str | None:
    """Immigrant stock or the external-migration type. Off unless the flag is on."""
    from grund.isorigin import (
        age_total_code,
        citizenship_code,
        citizenship_total_code,
        enabled,
        flow_code,
        migration_code,
        origin_code,
        sex_code,
        sex_total_code,
    )

    if not enabled():
        return None
    key = fold(f"{variable.text} {variable.code}")
    aged = age_total_code(variable, parsed.text)
    if aged is not None:
        return aged
    citizens = citizenship_total_code(variable, parsed.text)
    if citizens is not None:
        return citizens
    sexes = sex_total_code(variable, parsed.text)
    if sexes is not None:
        return sexes
    if origin_code(parsed.text) and ("bakgrunn" in key or re.search(r"\borigin\b", key) or "background" in key):
        return origin_code(parsed.text)
    code = migration_code(variable, parsed.text)
    if code is None:
        code = flow_code(parsed.text)
    if code and ("flutning" in key or re.search(r"\bmigration\b", key)):
        return code
    if (origin_code(parsed.text) or code) and re.search(r"\b(kyn|sex)\b", key):
        picked = sex_code(parsed.text)
        if picked:
            return picked
    if code and ("rikisfang" in key or "citizenship" in key):
        picked = citizenship_code(parsed.text)
        if picked:
            return picked
    return None


def _named_year_of_age(variable: Variable, parsed: ParsedQuestion) -> str | None:
    """The single year of age the question names, when this variable is age.

    The ordinary total stays in place unless ``GRUND_IS_COVER`` or
    ``GRUND_RC2`` is on. A one-digit age such as 5 does not survive the
    two-digit number rule, so it is matched here only as ``N ára`` against a
    label whose only number is N.
    """
    from grund.iscover import enabled as cover_enabled
    from grund.iscover import wants_national_age

    if not cover_enabled():
        return None

    if not wants_national_age(parsed.text, parsed.language):
        return None
    key = fold(f"{variable.text} {variable.code}")
    if "aldur" not in key and not re.search(r"\bage\b", key):
        return None
    asked = fold(parsed.text)
    if any(mark in asked for mark in ("og eldri", "og yngri", "prosent", "hlutfall", "haekk", "laekk")):
        return None
    match = re.search(r"\b(\d{1,3})\s+ara\b", asked)
    if match is None:
        return None
    number = match.group(1)
    hits = []
    for code, label in variable.values:
        numbers = re.findall(r"\d+", f"{code} {label}")
        if set(numbers) == {number}:
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def _select_category(
    variable: Variable,
    parsed: ParsedQuestion,
    title: str,
    notes: list[str] | None = None,
    aliases: dict[str, str] | None = None,
) -> list[str] | None:
    named_age = _named_year_of_age(variable, parsed)
    if named_age is not None:
        return [named_age]
    named_origin = _named_origin(variable, parsed)
    if named_origin is not None:
        return [named_origin]
    from grund.measure_guard import value_code as measure_value_code

    measured = measure_value_code(variable, parsed.text, parsed.language, title)
    if measured is not None:
        return [measured]
    from grund.isbuilding import item_code

    building_item = item_code(parsed.text)
    item_key = fold(f"{variable.text} {variable.code}")
    if building_item and (item_key.strip() in {"item", "lidur"} or re.search(r"\b(item|lidur)\b", item_key)):
        return [building_item]
    from grund.istown import municipality_code

    pinned = municipality_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isjobsex import labour_sex_code

    pinned = labour_sex_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isbirths import birth_value_code

    pinned = birth_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isregion import region_value_code

    pinned = region_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isgdp import gdp_line_code

    pinned = gdp_line_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.istrade import trade_line_code

    pinned = trade_line_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.iscpi import cpi_value_code

    pinned = cpi_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.iswage import wage_value_code

    pinned = wage_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isstays import stays_value_code

    pinned = stays_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isquarter import quarter_value_code

    pinned = quarter_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.ispop import pop_value_code

    pinned = pop_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isjobs import labour_value_code

    pinned = labour_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    from grund.isshare import share_value_code

    pinned = share_value_code(variable, parsed.text, parsed.language, title)
    if pinned is not None:
        return [pinned]
    query = set(parsed.query_tokens)
    expanded = set(query)
    for token in list(query):
        expanded.update(SYNONYMS.get(token, []))
    query = expanded
    if _change_denied(parsed.folded):
        query -= {"annual", "change", "arsbreyting", "arbreyting", "yearly"}
    if _series_pick_on() and _geo_variable(variable):
        query |= _region_aliases(parsed.folded)
    if parsed.operation == "share":
        query -= _SHARE_QUERY_SKIP
    preferred = _measure_value(variable, parsed)
    if preferred is not None:
        return [preferred]
    pool = list(variable.values)
    if parsed.operation == "share":
        counts = [(code, label) for code, label in pool if not _percent_unit(label)]
        if counts:
            pool = counts
    if _person_count_ask(parsed.folded):
        kept = [(code, label) for code, label in pool if not _percent_unit(label) and "rate" not in fold(label) and "frjosemi" not in fold(label)]
        if kept:
            pool = kept
    ranked: list[tuple[float, int, str, str]] = []
    for code, label in pool:
        if _frame_country(variable, label, parsed) or _postcode_slice(label, parsed):
            score, overlap = 0.0, 0
        else:
            score, overlap = _value_score(query, parsed.folded, label)
            # Words copied from the table title do not name a row.
            # "opening days" is the table, not "No regular opening days".
            if score > 0:
                forms = _title_forms(title, variable)
                distinctive = [
                    token
                    for token in tokens(label)
                    if len(token) >= 4 and _token_hit(token, query) and not _query_token_ignored(token, forms)
                ]
                if not distinctive:
                    score, overlap = 0.0, 0
        ranked.append((score, overlap, code, label))
    title_tokens = set(tokens(title))
    adjusted: list[tuple[float, int, str, str]] = []
    for score, overlap, code, label in ranked:
        # Words that are only in the table title name the table. A row is
        # named when the question uses some other word that the row prints.
        named = 0
        # A label the scorer already rejected (score 0) must not be revived
        # by a later bonus. "First born" is not the birth total.
        if score > 0 and not is_total(label):
            named = sum(
                1
                for token in tokens(label)
                if len(token) >= 4
                and not any(token == title_token or near_token(token, title_token) for title_token in title_tokens)
                and _token_hit(token, query)
            )
        adjusted.append((score + named * 1.5, overlap + named, code, label))
    ranked = adjusted
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    aliases = aliases or {}
    if parsed.operation == "share":
        if ranked and not is_total(ranked[0][3]):
            # A high score from a label the question never names is not a request
            # for that row. Prefer the total, and keep a row whose own words are
            # in the question.
            distinctive = [
                token for token in tokens(ranked[0][3])
                if len(token) >= 4 and _token_hit(token, query)
            ]
            totals = [item for item in ranked if is_total(item[3])]
            if not distinctive and totals:
                ranked = [totals[0], *[item for item in ranked if item[2] != totals[0][2]]]
    elif ranked:
        # "Lending" inside the pasted title is not a request for that row.
        # "Capitol region" written after the title is. A named row stays.
        # Otherwise the total wins, including a total that only the other
        # language labels as samtals or alls.
        covered = _title_forms(title, variable)
        usable = {token for token in query if not _query_token_ignored(token, covered)}

        def _explicit(code: str, label: str) -> bool:
            from grund.agree_hyb import enabled as agree_hyb

            # "In Iceland" is the country. It is not a request for the citizenship row.
            if agree_hyb() and _frame_country(variable, label, parsed):
                return False
            if agree_hyb() and aliases.get(code) and _frame_country(variable, aliases.get(code, ""), parsed):
                return False
            return label_named_by(label, usable) or label_named_by(aliases.get(code, ""), usable)

        explicit = [item for item in ranked if _explicit(item[2], item[3])]
        if explicit:
            explicit_codes = {item[2] for item in explicit}
            ranked = [
                ((item[0] if item[2] in explicit_codes else 0.0), item[1], item[2], item[3])
                for item in ranked
            ]
            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            top = ranked[0]
            ranked[0] = (max(top[0], 2.0), top[1], top[2], top[3])
        else:
            # A component that only repeats the title loses to a total the
            # question did not itself name. Leave the scorer's row when that
            # row is already a total, and when the first total uses a word
            # the question wrote ("income", "marriages dissolved").
            code0, label0 = ranked[0][2], ranked[0][3]
            other0 = aliases.get(code0, "")
            winner_is_total = aggregate_label(label0) or bool(other0 and aggregate_label(other0))
            if not winner_is_total:
                for code, label in pool:
                    other = aliases.get(code, "")
                    # "Total" is the unnamed row. "Samtals úrgangur" is one
                    # measure that happens to start with the total word.
                    # The other language may still mark the headline that way.
                    if other and aggregate_label(other):
                        pass
                    elif not is_total(label):
                        continue
                    texts = [label] + ([other] if other else [])
                    if any(_question_mentions(text, query) for text in texts):
                        break
                    return [code]
    if notes is not None and len(ranked) > 1 and ranked[1][0] >= max(1.0, ranked[0][0] - 0.45):
        notes.append(f"row used: {ranked[0][3]}")
    best = ranked[0][0] if ranked else 0.0
    long_hit = False
    if ranked:
        label_tokens = set(tokens(ranked[0][3]))
        long_hit = any(len(token) >= 10 and token in label_tokens for token in query)
    if best >= 1.15 or (best >= 1.0 and long_hit):
        if parsed.operation in {"difference", "sum"}:
            strong = [
                item for item in ranked if item[0] >= 1.15 and not is_total(item[3])
            ]
            # A second label has to name something the first label does not.
            # "CPI" and "CPI less housing" are one subject. "men" and "women" are two.
            if len(strong) >= 2:
                first_hits = {token for token in query if _token_hit(token, set(tokens(strong[0][3])))}
                picked = [strong[0][2]]
                for _score, _overlap, code, label in strong[1:]:
                    extra = [
                        token for token in query
                        if not _already_named(token, first_hits) and _token_hit(token, set(tokens(label)))
                    ]
                    if extra:
                        picked.append(code)
                if len(picked) >= 2:
                    outside = [
                        code
                        for code in picked
                        if _words_outside_title(variable.label(code), title_tokens)
                    ]
                    inside = [code for code in picked if code not in outside]
                    # "Employed" is the row. "Labour force" is only the title.
                    if outside and inside:
                        return outside[:1]
                    return picked[:2]
        chosen = [ranked[0][2]]
        first_hits = {token for token in query if _token_hit(token, set(tokens(ranked[0][3])))}
        if re.search(r"\b(and|og|versus|vs)\b", parsed.folded):
            for score, _overlap, code, label in ranked[1:]:
                if score < max(1.15, best - 0.35):
                    continue
                # "by region and vessel type" is one phrase, not two values.
                # A second label has to add a query word the first label lacks.
                extra = [
                    token for token in query
                    if not _already_named(token, first_hits) and _token_hit(token, set(tokens(label)))
                ]
                if extra:
                    chosen.append(code)
        return list(dict.fromkeys(chosen))
    named = _category_named_in_question(variable, parsed.text, title)
    if named is not None:
        return [named]
    if _question_forbids_total(variable, parsed.text, title):
        return None
    for code, label in variable.values:
        if is_total(label) or fold(code) in {"total", "samtals"}:
            return [code]
    if len(variable.values) == 1:
        return [variable.values[0][0]]
    if variable.elimination:
        return []
    folded_title = fold(title)
    for code, label in variable.values:
        folded_label = fold(label)
        if folded_label and len(folded_label) >= 8 and folded_label in folded_title:
            return [code]
    # A short codelist with no total (index bases, a handful of measures) still
    # has to resolve. A long codelist must not silently become its first row.
    if 0 < len(variable.values) <= 8:
        usable = [
            (code, label) for code, label in variable.values
            if not _unwanted_label(label, parsed.folded)
        ]
        if usable:
            return [usable[0][0]]
        return [variable.values[0][0]]
    # A long account list often has no single "Alls", only "X, alls" subtotals.
    # The first of those is the top line of the codelist.
    found = top_total([(code, label) for code, label in variable.values])
    if found:
        return [found[0]]
    return None


def _change_denied(folded: str) -> bool:
    """'not the annual change' names the column in order to leave it out."""
    return re.search(
        r"\b(not|ekki|rather than|instead of)\b.{0,48}\b(annual change|arsbreyting|the change)\b"
        r"|"
        r"\b(index level|the level)\b.{0,40}\bnot\b",
        folded or "",
    ) is not None


def _official_change(edition: Edition, parsed: ParsedQuestion) -> tuple[str, str] | None:
    if parsed.operation != "yoy_pct":
        return None
    if _change_denied(parsed.folded):
        return None
    query = set(parsed.query_tokens)
    best: tuple[float, str, str] | None = None
    for variable in edition.variables:
        if variable.time:
            continue
        for code, label in variable.values:
            folded = fold(label)
            if not any(phrase in folded for phrase in _CHANGE):
                continue
            score, _overlap = _value_score(query, parsed.folded, label)
            if best is None or score > best[0]:
                best = (score, variable.code, code)
    if best and best[0] >= 1.4:
        return best[1], best[2]
    # "Over the year" asks for the published annual-change column. The
    # question does not repeat the words "annual change", so the score
    # above stays low and the index level would be cited instead.
    if not re.search(r"over the year|a ari|arsbreyting|annual change", parsed.folded):
        return None
    found: list[tuple[str, str]] = []
    for variable in edition.variables:
        if variable.time:
            continue
        for code, label in variable.values:
            folded = fold(label)
            if any(phrase in folded for phrase in ("annual change", "arsbreyting", "arbreyting", "breyting fra fyrra ari")):
                found.append((variable.code, str(code)))
    if len(found) == 1:
        return found[0]
    return None


def _category_named_in_question(variable: Variable, asked: str, title: str = "") -> str | None:
    """A non-total label the question names, including a town inside a longer name.

    A word of the table title, or the dimension itself ("by region"), is not
    that name. The match may be a lemma of the printed label. A list number
    is not part of the name: ``1. Flug`` is the row ``flugi`` asks for.
    """
    from grund_lang.pxtools import match_value_codes

    named = match_value_codes(variable.values, asked, title)
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        return None
    covered = _title_forms(title, variable)
    words = []
    for word in re.findall(r"[a-z0-9]+", asked):
        if len(word) < 6 or word in {"percentage", "percent", "hlutfall", "hlutdeild", "prosent"}:
            continue
        if _query_token_ignored(word, covered):
            continue
        words.append(word)
    hits: list[str] = []
    for code, label in variable.values:
        if is_total(label):
            continue
        folded = fold(label)
        matched = False
        if re.search(r"\bfyrsta\s+ari", asked) and re.search(r"(1\s*\.\s*ari|0\s*ara|under\s*1)", folded):
            matched = True
        elif re.search(r"\b(erlend\w*|utlending\w*|foreign\w*)\b", asked) and re.search(
            r"\b(erlend\w*|utlending\w*|foreign\w*)\b", folded
        ):
            matched = True
        else:
            for word in words:
                stem = word[:-1] if word.endswith("i") and len(word) > 6 else word
                if len(stem) >= 6 and _stem_names_label(stem, folded):
                    matched = True
                    break
        if matched:
            hits.append(code)
    if len(hits) == 1:
        return hits[0]
    return None


def _stem_names_label(stem: str, folded: str) -> bool:
    """The question stem is this label, not a prefix of a different word."""
    if re.search(rf"\b{re.escape(stem)}\b", folded):
        return True
    if not folded.startswith(stem):
        return False
    rest = folded[len(stem) :]
    return rest in {"", "kaupstadur", "urborg", "borg", "baer"} or rest.startswith("kaupstad")


def _question_forbids_total(variable: Variable, asked: str, title: str = "") -> bool:
    """The question named a category, so Alls on this variable would be a different statistic."""
    from grund.isbirths import specific_age
    from grund_lang.pxtools import match_value_codes

    if match_value_codes(variable.values, asked, title):
        return True
    key = fold(f"{variable.text} {variable.code}")
    if specific_age(asked) and ("aldur" in key or re.search(r"\bage\b", key)):
        return True
    if re.search(r"\bfyrsta\s+ari", asked) and re.search(r"\b(aldur|age)\b", key):
        return True
    if re.search(r"\b(erlend\w*|utlending\w*|foreign\w*)\b", asked) and any(
        word in key for word in ("thjoderni", "nationalit", "citizenship")
    ):
        return True
    if any(word in key for word in ("sveitarfelag", "municipality")):
        words = [
            word
            for word in re.findall(r"[a-z0-9]+", asked)
            if len(word) >= 6 and word not in {"percentage", "percent", "hlutfall", "hlutdeild", "prosent"}
        ]
        for _code, label in variable.values:
            if is_total(label):
                continue
            folded = fold(label)
            for word in words:
                stem = word[:-1] if word.endswith("i") and len(word) > 6 else word
                if len(stem) >= 6 and _stem_names_label(stem, folded):
                    return True
    return False


def _skip_narrow_table(edition: Edition, parsed: ParsedQuestion) -> bool:
    """A sub-series is not the headline the question left unqualified.

    Hotels are not all accommodation. A 1914 ex-housing index is not the
    CPI. GDP per capita is not GDP. Teaching staff are not the labour force.
    """
    from grund_rails.cell_claim import _not_headline_series
    from grund.istrade import trade_kind

    if trade_kind(parsed.text, parsed.language) is not None and (
        "landsframleid" in fold(edition.title) or "domestic product" in fold(edition.title)
    ):
        return False

    title = fold(edition.title)
    asked = parsed.folded
    if _not_headline_series(parsed.text, {"title": edition.title, "labels": {}}):
        return True
    if any(word in asked for word in ("overnight", "gistin", "gestakom")) and not any(
        word in asked for word in ("hotel", "guesthouse", "gistiheimil")
    ):
        if any(word in title for word in ("hotel", "gistiheimil")) and not any(
            word in title for word in ("ollum", "allartegund", "all types", "all accommodation")
        ):
            return True
    if any(word in asked for word in ("exchange rate", "gengi", "solugengi")) and any(
        word in title for word in ("per capita", "a mann", "landsframleidsl", "gross domestic", "gdp")
    ):
        return True
    # A count of women or men is not a labour-force table or a percentage split.
    from grund.agree_hyb import labour_title_for_headcount

    if labour_title_for_headcount(edition.title, parsed.text):
        return True
    return False


def bind(edition: Edition, parsed: ParsedQuestion, peer: Edition | None = None) -> Binding | None:
    if _skip_narrow_table(edition, parsed):
        return None
    operation = parsed.operation
    notes: list[str] = []
    official = _official_change(edition, parsed)
    from grund.iswage import wage_official

    wage = wage_official(edition, parsed)
    if wage is not None:
        official = wage
    if official:
        operation = "level"
        notes.append("used the table's own change column instead of recomputing it")
    from grund.isshare import wants_sex_share
    from grund.iscpi import cpi_kind

    if wants_sex_share(parsed.text, parsed.language) and operation == "level":
        operation = "share"
        notes.append("sex share of the population")
    if cpi_kind(parsed.text, parsed.language) == "change":
        operation = "level"
        notes.append("published annual change of the index")
    chosen: dict[str, list[str]] = {}
    score = 0.0
    time_var = None
    time_codes: list[str] = []
    alias_map = _alias_map(edition, peer)
    for variable in edition.variables:
        if variable.time or _is_time_variable(variable):
            picked = _select_time(variable, parsed, operation if not official else "level")
            if picked is None:
                return None
            time_var = variable.code
            time_codes = picked
            chosen[variable.code] = picked
            score += 1.0
            continue
        if official and variable.code == official[0]:
            chosen[variable.code] = [official[1]]
            score += 2.0
            continue
        picked = _select_category(
            variable, parsed, edition.title, notes, alias_map.get(variable.code) or {}
        )
        if picked is None:
            return None
        if not picked:
            continue
        chosen[variable.code] = picked
        for code in picked:
            score += _value_score(set(parsed.query_tokens), parsed.folded, variable.label(code))[0]

    group_var = None
    part_code = None
    whole_code = None
    if operation == "share":
        for variable in edition.variables:
            if variable.time or variable.code not in chosen:
                continue
            codes = chosen[variable.code]
            if len(codes) != 1 or is_total(variable.label(codes[0])):
                continue
            total = next((code for code, label in variable.values if is_total(label)), None)
            if total is None:
                continue
            if total not in codes:
                codes.append(total)
            group_var = variable.code
            part_code = codes[0]
            whole_code = total
            notes.append("share uses the part and the total on the same variable")
            break
        if group_var is None:
            return None

    if operation in {"difference", "sum"} and len(time_codes) < 2:
        for variable in edition.variables:
            if variable.time or variable.code not in chosen:
                continue
            non_total = [
                code for code in chosen[variable.code] if not is_total(variable.label(code))
            ]
            if len(non_total) < 2:
                continue
            group_var = variable.code
            part_code = non_total[0]
            whole_code = non_total[1]
            notes.append(
                "sum of two categories" if parsed.operation == "sum" else "difference of two categories"
            )
            break
        if group_var is None and operation == "sum":
            return None
        if group_var is None and operation == "difference":
            return None

    rebase_code = None
    target_code = None
    if parsed.operation == "rebase":
        if not time_codes or parsed.rebase_year is None:
            return None
        time_variable = edition.time_variable()
        base = _match_period(time_variable.codes(), parsed.rebase_year, None) if time_variable else None
        if base is None:
            return None
        if base not in time_codes:
            time_codes = time_codes + [base]
            if time_var:
                chosen[time_var] = time_codes
        targets = [code for code in time_codes if code != base]
        if not targets:
            return None
        rebase_code = base
        target_code = targets[-1]

    chosen, operation, cell_notes = refine_selection(edition, parsed, chosen, operation)
    from grund.frame import impose_frame

    imposed = impose_frame(edition, chosen)
    if imposed is None:
        return None
    chosen = imposed
    # The total pass does not see an inflected region name, so it writes Alls.
    # Put the named region back before the cover check, which otherwise
    # rejects the table because the place word is not in that total label.
    _stamp_named_cells(edition, parsed.text, chosen, notes)
    notes.extend(cell_notes)
    if wants_sex_share(parsed.text, parsed.language):
        operation = "share"
    if cpi_kind(parsed.text, parsed.language) == "change" and time_var and chosen.get(time_var):
        operation = "level"
        chosen[time_var] = [chosen[time_var][-1]]
        notes.append("cpi annual change is the published column")
    from grund.iswage import wage_kind

    if wage_kind(parsed.text, parsed.language) == "percent" and time_var and len(chosen.get(time_var) or []) > 1:
        # The annual-change column is already the percent. Do not difference two of them.
        chosen[time_var] = [chosen[time_var][-1]]
        operation = "level"
        notes.append("wage annual change is the published column")
    if time_var:
        time_codes = list(chosen.get(time_var) or time_codes)
    selections = [
        {"code": code, "selection": {"filter": "item", "values": values}}
        for code, values in chosen.items()
        if values
    ]
    if parsed.latest and not parsed.periods:
        notes.append("no period was named, so the latest period in the table is used")
    from grund.isorigin import flow_code, origin_code

    if (
        not _covers_specific_words(parsed, edition, chosen)
        and origin_code(parsed.text) is None
        and not flow_code(parsed.text)
    ):
        return None
    built = Binding(
        edition=edition,
        selections=selections,
        operation=operation,
        score=score,
        time_var=time_var,
        time_codes=time_codes,
        group_var=group_var,
        part_code=part_code,
        whole_code=whole_code,
        rebase_code=rebase_code,
        target_code=target_code,
        notes=notes,
        official_measure=official is not None,
    )
    from grund.bind2 import apply_binding

    updated = apply_binding(edition, parsed, built)
    built = built if updated is None else updated
    return _with_named_region(built, parsed.text)


def _named_note(edition: Edition, variable: str, code: str) -> str:
    for candidate in edition.variables:
        if candidate.code != variable:
            continue
        name = fold(f"{candidate.code} {candidate.text}")
        if re.search(r"\b(kyn|sex|gender)\b", name):
            return f"sex {code}"
    return f"region {code}"


def _stamp_named_cells(edition: Edition, question: str, chosen: dict[str, list[str]], notes: list[str]) -> None:
    """Write the region the question named over the all-regions total.

    Off unless ``GRUND_TOPIC_PRIOR`` is set. A named sex on that region is
    kept as well, so the region's total is not used for a men or women count.
    """
    from grund.topic_prior import named_cells

    for variable, code in named_cells(edition, question):
        if list(chosen.get(variable) or []) == [code]:
            continue
        chosen[variable] = [code]
        notes.append(_named_note(edition, variable, code))


def _with_named_region(binding: Binding, question: str) -> Binding:
    """Same codes on the built query, if a later pass put the total back."""
    from grund.topic_prior import named_cells

    found = named_cells(binding.edition, question)
    if not found:
        return binding
    selections = list(binding.selections)
    notes = list(binding.notes)
    changed = False
    for variable, code in found:
        replaced = False
        updated = []
        for entry in selections:
            values = list(entry.get("selection", {}).get("values") or [])
            if entry.get("code") == variable and values != [code]:
                updated.append({"code": variable, "selection": {"filter": "item", "values": [code]}})
                replaced = True
            else:
                updated.append(entry)
        if not replaced and not any(entry.get("code") == variable for entry in updated):
            updated.append({"code": variable, "selection": {"filter": "item", "values": [code]}})
            replaced = True
        if replaced:
            note = _named_note(binding.edition, variable, code)
            if note not in notes:
                notes.append(note)
            changed = True
        selections = updated
    if not changed:
        return binding
    binding.selections = selections
    binding.notes = notes
    return binding
