"""Map a question onto the PxWeb value codes of one table edition.

The choices cover the distinctions a published table actually encodes:
a total against a subgroup, citizens against everyone, internal migration
against international, a quarter, an annual average, and an index base.
One edition is enough. The caller picks the language edition.
"""

from __future__ import annotations

import os
import re

from grund_lang.dates import find_bases
from grund_lang.fold import GENERIC, fold
from grund_lang.lemma import analyze, lemmatize_label
from grund_lang.types import Analysis, DateSpan, ValueChoice

_TOTAL = {
    "total", "alls", "samtals", "heild", "all", "allt", "oll", "ollu",
    "allt landid", "whole country", "entire country", "all regions",
    "national", "landid allt",
}
_FEMALE = {"female", "females", "woman", "women", "kona", "konur", "stulka", "stulkur", "girl", "girls"}
_MALE = {"male", "males", "man", "men", "karl", "karlar", "drengur", "drengir", "boy", "boys"}
_CITIZEN = {"citizen", "citizens", "citizenship", "rikisborgari", "rikisfang"}
_ICELANDIC = {"icelandic", "islenskur", "islensk", "islenskt", "islenskir"}
_FOREIGN = {"foreign", "foreigner", "foreigners", "erlendur", "erlend", "erlent", "erlendir"}
_ANNUAL = {"arsmedaltal", "arsmedal", "average"}
_GEO_VAR = ("municipality", "sveitarfelag", "region", "landshluti", "landsvaedi", "nuts", "country", "land", "svaedi")
_SEX_VAR = ("sex", "kyn", "gender")
_BASE_VAR = ("base", "grunnur", "grunn")


def _label_terms(label: str) -> set[str]:
    return set(lemmatize_label(label))


def _is_total(label: str) -> bool:
    folded = fold(label).strip(" .")
    if folded in _TOTAL:
        return True
    if folded.startswith("total ") and "of total" not in folded and "percentage" not in folded:
        return True
    if folded.endswith(" total") or folded.endswith(", total") or folded.endswith(" alls"):
        return True
    return False


def _asked_numbers(analysis: Analysis) -> set[str]:
    """Digits the question uses for a row, not for a year or an index base."""
    skip = {str(year) for year in analysis.bases}
    for span in analysis.dates:
        if span.year:
            skip.add(str(span.year))
        if span.end_year:
            skip.add(str(span.end_year))
    found = set(re.findall(r"\d+", analysis.text))
    return {item for item in found if len(item) >= 2 and item not in skip}


def _has(text: str, *pieces: str) -> bool:
    return any(piece in text for piece in pieces)


def _granularity(values: list[tuple[str, str]]) -> str:
    codes = [code for code, _label in values]
    if any(re.search(r"M\d", code) for code in codes):
        return "month"
    if any("Q" in code.upper() for code in codes):
        return "quarter"
    if any(re.fullmatch(r"(?:19|20)\d{2}", code) for code in codes):
        return "year"
    return "other"


def _find_code(values: list[tuple[str, str]], code: str) -> tuple[str, str] | None:
    for value_code, label in values:
        if value_code == code or fold(label) == fold(code):
            return value_code, label
    return None


def _time_choice(variable, code: str, label: str, role: str, why: str) -> ValueChoice:
    return ValueChoice(variable.code, variable.text, code, label, role, 5.0, why)


def bind_time(variable, dates: list[DateSpan], text: str) -> list[ValueChoice]:
    values = [(str(code), str(label)) for code, label in variable.values]
    grain = _granularity(values)
    wants_average = _has(text, "arsmedaltal", "annual average", "yearly average")
    if wants_average:
        for code, label in values:
            folded = fold(label)
            if "arsmedal" in folded or folded in {"annual average", "average"}:
                return [_time_choice(variable, code, label, "annual_average", "annual average is a value on this list")]
    chosen: list[ValueChoice] = []
    ranged = any(
        (span.kind == "between_years" and span.year and span.end_year)
        or (span.kind == "recent_years" and span.count)
        for span in dates
    )

    def take(code: str, role: str, why: str) -> bool:
        found = _find_code(values, code)
        if found is None:
            return False
        chosen.append(_time_choice(variable, found[0], found[1], role, why))
        return True

    for span in dates:
        if span.kind == "quarter" and span.quarter and span.year and grain in {"quarter", "other"}:
            take(f"{span.year}Q{span.quarter}", "quarter", "quarter code")
        elif span.kind == "month" and span.month and span.year and grain == "month":
            take(f"{span.year}M{span.month:02d}", "month", "month code")
        elif span.kind == "point" and span.year:
            if grain == "year":
                take(str(span.year), "year", "1 January stock is the year code")
            elif grain == "month" and span.day:
                # A day-of-month date is not a month on a monthly table.
                from grund.agree_hyb import enabled as agree_hyb

                if not agree_hyb():
                    take(f"{span.year}M{span.month:02d}", "month", "month of the named day")
            elif grain == "month" and span.month:
                take(f"{span.year}M{span.month:02d}", "month", "named month")
            elif grain == "quarter" and span.month:
                take(f"{span.year}Q{(span.month - 1) // 3 + 1}", "quarter", "quarter of the named day")
        elif span.kind == "year_end" and span.year:
            if grain == "month":
                take(f"{span.year}M12", "year_end", "December of the named year")
            elif grain == "quarter":
                take(f"{span.year}Q4", "year_end", "last quarter of the named year")
            elif grain == "year":
                take(str(span.year), "year_end", "year-end stock uses the year code")
        elif span.kind == "year_start" and span.year:
            if grain == "year":
                take(str(span.year), "year_start", "start of the year")
            elif grain == "month":
                take(f"{span.year}M01", "year_start", "January")
            elif grain == "quarter":
                take(f"{span.year}Q1", "year_start", "first quarter")
        elif span.kind == "annual_average" and span.year and grain == "year":
            take(str(span.year), "annual_average", "annual-average series is yearly")
        elif span.kind == "year" and span.year and grain == "year":
            take(str(span.year), "year", "named year")
        elif span.kind == "recent_years" and span.count and grain == "year":
            codes = sorted({code for code, _label in values if re.fullmatch(r"(?:19|20)\d{2}", code)})
            for code in codes[-span.count :]:
                take(code, "recent_years", "most recent years published in the table")
        elif span.kind == "between_years" and span.year and span.end_year:
            if grain == "year":
                take(str(span.year), "time_range", "first year of the comparison")
                take(str(span.end_year), "time_range", "last year of the comparison")
            elif grain == "quarter" and span.end_quarter:
                take(f"{span.end_year}Q{span.end_quarter}", "time_range", "end of the comparison")
    if not chosen and not ranged:
        for span in dates:
            if span.year and grain == "year":
                if take(str(span.year), "year", "year named with the period"):
                    break
    deduped: list[ValueChoice] = []
    seen: set[str] = set()
    for choice in chosen:
        if choice.value_code in seen:
            continue
        seen.add(choice.value_code)
        deduped.append(choice)
    periods = [
        span for span in dates
        if span.kind in {"quarter", "month", "point", "year", "year_end", "year_start", "between_years"}
        and (span.year or span.end_year)
    ]
    if ranged or len(periods) >= 2:
        return deduped
    return deduped[:1]


def _variable_folded(variable) -> str:
    return fold(f"{variable.code} {variable.text}")


def bind_dimension(variable, analysis: Analysis, edition_title: str) -> ValueChoice | None:
    values = [(str(code), str(label).strip()) for code, label in variable.values]
    if not values:
        return None
    text = fold(analysis.text)
    terms = set(analysis.terms)
    concepts = set(analysis.concepts)
    var_text = _variable_folded(variable)
    asks_icelandic = "citizenship_icelandic" in concepts or (
        _has(text, "islensk", "icelandic") and _has(text, "rikisborg", "rikisfang", "citizen")
    )
    asks_foreign = "citizenship_foreign" in concepts or (
        _has(text, "erlend", "foreign") and _has(text, "rikisborg", "rikisfang", "citizen")
    )
    asks_citizens = asks_icelandic or asks_foreign or _has(text, "rikisborg", "rikisfang", "citizen")
    asks_female = "sex_female" in concepts
    asks_male = "sex_male" in concepts and not asks_female
    asks_foreigners = _has(text, "utlending", "foreigner")
    asks_average = "annual_average" in concepts or any(span.kind == "annual_average" for span in analysis.dates)
    asks_change = "annual_change" in concepts or any(span.kind == "between_years" for span in analysis.dates)
    asks_level = bool(terms & {"visitala", "index", "cpi", "vnv", "neysluverd"}) and not asks_change
    asks_capital = "capital_region" in concepts
    asks_internal = "migration_internal" in concepts or _has(
        text, "innanland", "internal migration", "buferla", "within the municipality",
        "within a municipality", "between region", "between municipal",
    )
    asks_external = "migration_international" in concepts or _has(
        text, "external migration", "international migration", "milli landa", "utlond", "abroad"
    )
    asks_immigration = _has(text, "immigrat", "innflytj", "adflutt", "innflutt", "from abroad", "fra utlond")
    asks_emigration = _has(text, "emigrat", "brottflutt", "utflutt", "fra islandi", "left the country")
    national = _has(text, "island", "iceland", "a islandi", "in iceland") or bool(terms & {"island", "iceland"})
    sex_var = any(piece in var_text for piece in _SEX_VAR)
    geo_var = any(piece in var_text for piece in _GEO_VAR)
    base_var = any(piece in var_text for piece in _BASE_VAR)
    citizen_var = _has(var_text, "citizen", "rikisborg", "rikisfang") or any(
        _has(fold(label), "citizen", "rikisborg") for _code, label in values[:12]
    )
    title_bases = find_bases(edition_title)
    title_terms = _label_terms(edition_title) - GENERIC
    prepared = []
    named_on_variable = False
    town_place = None
    if os.environ.get("GRUND_IS_KANG_TOWN", "0").strip().lower() in {"1", "on", "true", "yes"} and (
        "sveitarfel" in var_text or "municipality" in var_text
    ):
        from grund.istown import wants_town
        from grund_lang.kang_places import named_places

        if wants_town(analysis.text, analysis.language):
            places = named_places(analysis)
            if len(places) == 1:
                town_place = places[0]
    for code, label in values:
        folded = fold(label)
        label_terms = _label_terms(label)
        overlap = (label_terms - GENERIC) & (terms - GENERIC)
        # Words that are only in the table title name the series, not a row.
        # The aggregate line is the exception: "GDP" in the title is also the
        # line the question asked for, so that word is put back when the label
        # is that aggregate and not a different component.
        stripped = overlap & title_terms
        overlap = overlap - title_terms
        extra = label_terms - title_terms - GENERIC
        extra = {term for term in extra if not term.isdigit() and len(term) > 2}
        restricted = any(
            word in folded
            for word in ("without", "excluding", "of which", "thar af", "undansk", "an hus", "minus")
        )
        if stripped and len(extra) <= 2 and not restricted:
            overlap |= stripped
        # A label quoted in full ("Percentage of total") is a row even when
        # its words also occur in the title.
        if (
            len(folded) >= 8
            and folded in text
            and folded not in fold(edition_title)
            and not _is_total(label)
        ):
            score_phrase = 7.0
        else:
            score_phrase = 0.0
        if not asks_icelandic and (_has(folded, "citizen", "rikisborg") and label_terms & {"island", "iceland", "icelandic", "islenskur"}):
            overlap -= {"island", "iceland", "icelandic", "islenskur"}
        if overlap:
            named_on_variable = True
        if town_place is not None:
            from grund.istown import label_is_place

            if label_is_place(label, town_place):
                overlap = set(overlap) | {town_place}
                score_phrase = max(score_phrase, 9.0)
        prepared.append((code, label, folded, label_terms, overlap, score_phrase))
    best: ValueChoice | None = None
    for code, label, folded, label_terms, overlap, score_phrase in prepared:
        score = 2.5 * len(overlap) + score_phrase
        why = []
        if overlap:
            why.append("label shares " + ",".join(sorted(overlap)))
        asked_numbers = _asked_numbers(analysis)
        label_numbers = {item for item in re.findall(r"\d+", f"{code} {label}") if len(item) >= 2}
        if asked_numbers and label_numbers and label_numbers <= asked_numbers and not _is_total(label):
            score += 4.0
            why.append("numbers in the label")
        from grund.iscover import enabled as cover_enabled

        cover = cover_enabled()
        if cover and ("aldur" in var_text or var_text == "age"):
            from grund.iscover import wants_national_age

            cover = wants_national_age(analysis.text, analysis.language)
        if cover and ("aldur" in var_text or var_text == "age"):
            asked_ages = set(re.findall(r"\b(\d{1,3})\s+ara\b", text))
            age_numbers = re.findall(r"\d+", f"{code} {label}")
            if (
                asked_ages
                and set(age_numbers) <= asked_ages
                and len(set(age_numbers)) == 1
                and not _is_total(label)
            ):
                score += 6.0
                why.append("named age")
        if _is_total(label):
            score += 1.0
            why.append("total")
        if asks_icelandic and _has(folded, "icelandic", "islensk") and _has(folded, "citizen", "rikisborg", "rikisfang"):
            score += 8
            why.append("icelandic citizens")
        if asks_foreign and _has(folded, "foreign", "erlend") and _has(folded, "citizen", "rikisborg", "rikisfang", "citizenship"):
            score += 8
            why.append("foreign citizens")
        if asks_foreigners and not _is_total(label):
            bare = folded.strip()
            if bare in {"utlendingar", "utlendingur", "foreigners", "foreigner", "erlendir"}:
                score += 8
                why.append("foreigners")
        if citizen_var and not asks_citizens and _has(folded, "citizen", "rikisborg"):
            score -= 3
            why.append("citizenship row, question asked for everyone")
        if citizen_var and not asks_citizens and _is_total(label):
            score += 3
            why.append("everyone, not a citizenship row")
        if asks_female and label_terms & _FEMALE and not (label_terms & _MALE - _FEMALE):
            score += 6
            why.append("female")
        if asks_male and label_terms & _MALE and not (label_terms & _FEMALE):
            score += 6
            why.append("male")
        if sex_var and not asks_female and not asks_male and _is_total(label):
            score += 2
        if asks_female and label_terms & _MALE and not (label_terms & _FEMALE):
            score -= 2
        asks_first = "first" in text or "fyrst" in text
        if not asks_first and any(word in folded for word in ("first born", "fyrsta barn", "fyrstu")):
            score -= 4
            why.append("first-born row, question asked for all children")
        if any(word in folded for word in ("all children", "oll born", "olls born", "alls lifandi", "all live", "oll lifandi")):
            score += 4
            why.append("all children")
        if asks_average and ("arsmedal" in folded or folded in {"annual average", "average"}):
            score += 8
            why.append("annual average")
        for base in analysis.bases:
            if str(base) in folded or str(base) in code:
                score += 8
                why.append(f"base {base}")
            elif base_var and re.search(r"(?:19|20)\d{2}", folded):
                score -= 3
        if not analysis.bases and base_var and title_bases:
            if any(str(year) in folded or str(year) in code for year in title_bases):
                score += 4
                why.append("base named in the title")
        if asks_level and folded in {"index", "visitala", "vísitala"}:
            score += 5
            why.append("index level")
        if asks_level and _has(folded, "change", "breyting"):
            score -= 3
        if asks_change and _has(folded, "annual change", "arsbreyting", "arleg"):
            score += 6
            why.append("annual change")
        if asks_internal and _has(folded, "within municipality", "innan sveitarfelag") and _has(text, "sveitarfelag", "municipality"):
            score += 6
            why.append("within municipality")
        if asks_internal and _has(folded, "between region", "milli landshlut", "milli landsvaed"):
            score += 5
            why.append("between regions")
        if asks_internal and _has(folded, "immigration", "emigration", "external"):
            score -= 4
        if asks_external and _has(folded, "within ", "innan "):
            score -= 3
        if asks_immigration and _has(folded, "immigration") and not _has(folded, "net"):
            score += 6
            why.append("immigration")
        if asks_emigration and _has(folded, "emigration"):
            score += 6
            why.append("emigration")
        if national and geo_var and not named_on_variable and not overlap and not _is_total(label):
            score -= 1
        if asks_capital and _has(folded, "hofudborgarsvaed", "capital region", "capital area"):
            score += 8
            why.append("capital region")
        if asks_capital and geo_var and _is_total(label) and "hofudborg" not in folded:
            score -= 2
        if national and geo_var and not named_on_variable and (_is_total(label) or folded in {"allt landid", "whole country", "iceland", "island"}):
            score += 4
            why.append("national total")
        # "In Iceland" / "á Íslandi" is where the people live. It is not
        # country of birth, citizenship, or origin unless the question says so.
        _frame = {"island", "islandi", "islande", "iceland"}
        _origin_var = ("faeding", "birth", "rikisfang", "rikisborg", "citizen", "bakgrunn", "origin")
        asks_origin = _has(
            text, "faeding", "born", "rikisfang", "rikisborg", "citizen", "citizenship",
            "bakgrunn", "origin", "uppruni",
        )
        origin_var = any(piece in var_text for piece in _origin_var)
        named_country = label_terms & _frame or any(frame in folded for frame in _frame)
        if asks_origin and origin_var and named_country and not _is_total(label):
            score += 8
            why.append("named country of birth or citizenship")
        if national and origin_var and not asks_origin:
            if _is_total(label):
                score += 6
                why.append("national total, not a birth or citizenship row")
            elif named_country:
                score -= 5
                why.append("country name is where people live, not a subgroup")
        if _has(text, "less housing", "an husnaed", "excluding housing") and _has(folded, "less housing", "an husnaed"):
            score += 5
            why.append("housing excluded")
        elif _has(folded, "less housing", "an husnaed") and not _has(text, "housing", "husnaed"):
            score -= 2
        role = "subgroup" if overlap else "total" if _is_total(label) else "other"
        if any(piece.startswith("base") for piece in why):
            role = "index_base"
        elif any(piece == "annual average" for piece in why):
            role = "annual_average"
        elif any(piece in {"female", "male"} for piece in why):
            role = "sex"
        elif any("citizen" in piece for piece in why):
            role = "citizenship_icelandic" if asks_icelandic else "citizenship_foreign" if asks_foreign else "citizenship_all"
        elif any(piece in {"immigration", "emigration", "between regions", "within municipality"} for piece in why):
            role = "internal_migration" if asks_internal else "international_migration"
        choice = ValueChoice(variable.code, variable.text, code, label, role, score, "; ".join(why) or "fallback")
        if best is None or choice.score > best.score:
            best = choice
    if best is None:
        return None
    if best.score <= 0:
        for code, label in values:
            if _is_total(label):
                return ValueChoice(variable.code, variable.text, code, label, "total", 0.5, "no named subgroup")
    return best


def bind_values(question: str, edition, analysis: Analysis | None = None) -> list[ValueChoice]:
    """Values to send for `edition`, one per variable, or two when a range names both ends."""
    analysis = analysis or analyze(question)
    title = getattr(edition, "title", "") or ""
    text = fold(analysis.text)
    choices: list[ValueChoice] = []
    for variable in edition.variables:
        time_like = bool(getattr(variable, "time", False)) or _granularity(list(variable.values)) in {"month", "quarter", "year"}
        # A list of years is a time list even when the edition forgot the flag.
        # A list that merely contains one year among categories is not.
        codes = [str(code) for code, _label in variable.values]
        mostly_time = bool(codes) and sum(1 for code in codes if re.fullmatch(r"(?:19|20)\d{2}(?:[MQ]\d{1,2})?", code)) >= max(3, len(codes) // 2)
        if time_like and (getattr(variable, "time", False) or mostly_time):
            choices.extend(bind_time(variable, analysis.dates, text))
            continue
        choice = bind_dimension(variable, analysis, title)
        if choice is None:
            total = _total_value(variable)
            if total is not None:
                code, label = total
                choice = ValueChoice(variable.code, variable.text, code, label, "total", 0.5, "unasked variable uses the total")
        if choice is not None:
            choices.append(choice)
    choices = _totals_unless_named(edition, analysis, title, choices)
    choices = _match_measure(edition, analysis, choices)
    if not _question_has_year(analysis.text) and not any(choice.role in {"year", "month", "quarter", "year_end", "year_start", "time_range", "recent_years", "latest"} for choice in choices):
        latest = _latest_period_choice(edition)
        if latest is not None:
            choices.append(latest)
    return choices


_NAME_STOP = {"the", "and", "of", "by", "for", "with", "from", "that", "this", "was", "were", "what", "how"}


def _content_terms(text: str) -> set[str]:
    folded = fold(text)
    return {token for token in re.findall(r"[a-z0-9]{3,}", folded) if token not in _NAME_STOP and not token.isdigit()}


def _question_has_year(text: str) -> bool:
    return bool(re.search(r"(?:19|20)\d{2}", text or ""))


def _same_stem(left: str, right: str) -> bool:
    shared = 0
    for a, b in zip(left, right):
        if a != b:
            break
        shared += 1
    return shared >= 8 and shared >= min(len(left), len(right)) - 3


def _label_is_named(label: str, question: str, title: str) -> bool:
    """A row the question names beyond the words that only title the series."""
    extra = _content_terms(label) - _content_terms(title)
    if not extra:
        return False
    asked = _content_terms(question)
    for term in extra:
        if term in asked:
            continue
        if any(_same_stem(term, other) for other in asked):
            continue
        return False
    return True


def _total_value(variable) -> tuple[str, str] | None:
    for code, label in variable.values:
        if _is_total(str(label)):
            return str(code), str(label)
    return None


def _totals_unless_named(edition, analysis: Analysis, title: str, choices: list[ValueChoice]) -> list[ValueChoice]:
    """Unasked variables take the total. A filter the question names stays."""
    by_code = {choice.variable_code: choice for choice in choices}
    rewritten: list[ValueChoice] = []
    seen: set[str] = set()
    for variable in edition.variables:
        if getattr(variable, "time", False):
            continue
        choice = by_code.get(variable.code)
        if choice is None:
            continue
        seen.add(variable.code)
        if choice.role in {"sex", "citizenship_icelandic", "citizenship_foreign", "internal_migration", "international_migration", "index_base", "annual_average"}:
            rewritten.append(choice)
            continue
        if os.environ.get("GRUND_IS_KANG_TOWN", "0").strip().lower() in {"1", "on", "true", "yes"}:
            from grund.istown import label_is_place, wants_town
            from grund_lang.kang_places import named_places

            if wants_town(analysis.text, analysis.language):
                places = named_places(analysis)
                if len(places) == 1 and label_is_place(choice.value_label, places[0]):
                    rewritten.append(choice)
                    continue
        if _label_is_named(choice.value_label, analysis.text, title):
            rewritten.append(choice)
            continue
        total = _total_value(variable)
        if total is None:
            rewritten.append(choice)
            continue
        code, label = total
        if code == choice.value_code:
            rewritten.append(choice)
            continue
        rewritten.append(
            ValueChoice(variable.code, variable.text, code, label, "total", choice.score, "unasked variable uses the total")
        )
    for choice in choices:
        if choice.variable_code not in seen:
            rewritten.append(choice)
    return rewritten


_RATE_UNIT = ("percent", "hlutfall", "rate", "per capita", "fertility", "frjosemi", "prosent", "index", "visitala", "gengi")
_COUNT_UNIT = ("fjoldi", "number", "persons", "mannfjold", "headcount")
_CURRENCY_UNIT = ("exchange", "gengi", "solugengi", "per usd", "isk")


def _match_measure(edition, analysis: Analysis, choices: list[ValueChoice]) -> list[ValueChoice]:
    """A count question does not take a rate row, and a currency question needs a currency unit."""
    text = fold(analysis.text)
    asked = ""
    if any(word in text for word in ("exchange rate", "gengi", "solugengi")):
        asked = "currency"
    elif any(word in text for word in ("gdp", "landsframleidsl", "gross domestic product")):
        asked = "gdp"
    elif any(word in text for word in ("how many", "hve marg", "fjoldi", "mannfjold", "population", "inhabitants")):
        asked = "count"
    elif any(word in text for word in ("visitala",)) or re.search(r"\bindex\b", text):
        asked = "index"
    if not asked:
        return choices
    by_code = {choice.variable_code: choice for choice in choices}
    rewritten: list[ValueChoice] = []
    replaced: set[str] = set()
    for variable in edition.variables:
        choice = by_code.get(variable.code)
        if choice is None:
            continue
        blob = fold(f"{variable.code} {variable.text} {choice.value_label}")
        conflict = False
        if asked == "count" and any(word in blob for word in _RATE_UNIT):
            conflict = True
        if asked == "currency" and not any(word in blob for word in _CURRENCY_UNIT):
            conflict = any(word in fold(f"{variable.text} {choice.value_label}") for word in ("percent", "hlutfall", "gdp", "debt"))
        if asked == "index" and "index" not in blob and "visitala" not in blob and any(word in blob for word in ("percent", "hlutfall", "fjoldi")):
            conflict = True
        if not conflict:
            continue
        replacement = None
        for code, label in variable.values:
            folded = fold(str(label))
            if asked == "count" and any(word in folded for word in _COUNT_UNIT):
                replacement = (str(code), str(label))
                break
            if asked == "currency" and any(word in folded for word in _CURRENCY_UNIT):
                replacement = (str(code), str(label))
                break
            if asked == "index" and ("index" in folded or "visitala" in folded):
                replacement = (str(code), str(label))
                break
        if replacement is None:
            total = _total_value(variable)
            if total is not None and asked == "count":
                replacement = total
        if replacement is None:
            continue
        code, label = replacement
        by_code[variable.code] = ValueChoice(
            variable.code, variable.text, code, label, "unit", choice.score, f"measure {asked}"
        )
        replaced.add(variable.code)
    for choice in choices:
        rewritten.append(by_code.get(choice.variable_code, choice) if choice.variable_code in replaced else choice)
    return rewritten or choices


def _latest_period_choice(edition) -> ValueChoice | None:
    for variable in edition.variables:
        if not getattr(variable, "time", False) or not variable.values:
            continue
        code, label = variable.values[-1]
        return ValueChoice(variable.code, variable.text, str(code), str(label), "latest", 1.0, "no period was asked; latest period")
    return None
