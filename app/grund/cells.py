"""Choose the PxWeb value codes a question is actually asking for.

The choices come from the table's own metadata: which label is a total,
which code is a time period, which unit the notes and the value list name.
Nothing here is a rule for one question id.

`select_values` returns the same fields as `grund_lang.values.bind_values`:
one choice per variable, with a role such as total, subgroup, time, unit,
annual_average, or index_base. The binder can apply those codes without
knowing which package produced them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from grund.arithmetic import difference, yoy_percent
from grund_index.textutil import fold


def _cell_rule(name: str) -> bool:
    from grund.heuristics import enabled

    return enabled(name)

# Words that name a dimension, not a row. "by municipality" is not Árborg.
_DIMENSION = {
    "sex", "gender", "kyn", "age", "aldur", "ages", "municipality", "sveitarfelag",
    "region", "landshluti", "landsvaedi", "country", "land", "citizenship",
    "rikisfang", "year", "ar", "month", "manudur", "quarter", "arsfjordungur",
    "unit", "eining", "type", "tegund", "category", "flokkur", "total", "alls",
    "by", "eftir", "and", "og", "from", "fra", "the", "of", "in", "for",
}

_EXACT_TOTAL = {
    "total", "totals", "all", "alls", "allt", "allir", "allar", "oll", "samtals",
    "heild", "heildartala", "allt landid", "oll landid", "whole country",
    "entire country", "all regions", "whole county", "both sexes", "karlar og konur",
    "males and females", "all ages",
}

_OF_WHICH = ("thar af", "of which", "thereof", "whereof", "tharaf", "of whom")

# A one-word label that only repeats the series ("Index", "Percentage") is not a row name.
_GENERIC_LABEL = {
    "index", "visitala", "percentage", "percent", "hlutfall", "prosent", "value", "gildi",
}
_MEAN = {"mean", "medaltal", "medalaldur"}
_MEDIAN = {"median", "midaldur", "midgildi"}
_MODE = {"modal", "mode", "tidasti"}


@dataclass(frozen=True)
class ValueChoice:
    """One value code. Field names match grund_lang.types.ValueChoice."""

    variable_code: str
    variable_text: str
    value_code: str
    value_label: str
    role: str
    score: float
    why: str


# A published "per capita" series is already a rate. Dividing it by population
# again turns the cell into a number near zero.
_PER_PERSON = (
    "per capita", "per person", "per inhabitant", "per head",
    "a ibua", "a mann", "a hvern",
)

# Grammatical endings only. "Icelandic" is not the plural of "Iceland".
_INFLECTIONS = (
    "unum", "anna", "inum", "inni", "urnar", "arnar",
    "ing", "ed", "es", "ir", "ar", "ur", "um", "inn", "num",
    "s", "a", "i", "u",
)


def operation_for(question: str, proposed: str, edition=None) -> str:
    """Percent, points, or a plain difference. A verb like 'rose' does not decide.

    A share ("what percentage of") stays a share. "By what percentage did X
    change" is a percent change. "By how much" and "by how many points" are
    a difference of the two cells. A table whose title already says per person
    keeps that published rate, unless the question asks for a change.
    """
    if proposed == "share" and _asks_share(question):
        return "share"
    if proposed == "share" and _cell_rule("count_and_share_is_level"):
        # "Fjöldi og hlutfall" names the table. It is not "what percentage of".
        proposed = "level"
    if (
        proposed == "per_capita"
        and _cell_rule("per_person_is_level")
        and _series_is_already_per_person(edition)
    ):
        proposed = "level"
    text = fold(question)
    if _cell_rule("share_only_when_asked") and _asks_share(question) and not re.search(
        r"\b(by what percent|um hve)\b", text
    ):
        return "share"
    if _cell_rule("points_are_difference") and re.search(
        r"\b(prosentustig|percentage points?|prosentupunkt)\b", text
    ):
        return "difference"
    if _cell_rule("points_are_difference") and re.search(r"\b(stig|points?)\b", text) and re.search(
        r"\b(hve|how many|how much|um hve)\b", text
    ):
        return "difference"
    if _cell_rule("percent_is_change") and re.search(
        r"\b(by what percent|um hve m\w* prosent|what percent\w* did|prosent\w*|percent\w*|percentage)\b", text
    ):
        return "yoy_pct"
    if _cell_rule("magnitude_is_difference") and re.search(
        r"\b(um hve mikid|by how much|by how many)\b", text
    ):
        return "difference"
    return proposed


def select_values(question: str, edition, analysis=None) -> list[ValueChoice]:
    """One code per variable, from this edition's value list."""
    text = fold(question)
    span = _title_span(question, getattr(edition, "title", "") or "")
    bases = _base_years(question, analysis)
    choices: list[ValueChoice] = []
    for variable in edition.variables:
        if _is_time_variable(variable):
            choice = _bind_time(variable, question, text, bases, analysis)
            if choice is not None:
                choices.append(choice)
            continue
        choice = _bind_dimension(variable, text, span, getattr(edition, "title", "") or "")
        if choice is not None:
            choices.append(choice)
    return choices


def derive(operation: str, later: str, earlier: str | None = None) -> Decimal:
    """The figure a level, a difference, or a percent change is.

    `later` and `earlier` are the strings PxWeb returned. A difference is
    later minus earlier. A percent change divides by the earlier cell.
    A level is the published cell, not rescaled: a row labelled thousands
    is already in thousands.
    """
    if operation == "yoy_pct":
        if earlier is None:
            raise ValueError("a percent change needs two cells")
        return yoy_percent(later, earlier)
    if operation == "difference":
        if earlier is None:
            raise ValueError("a difference needs two cells")
        return difference(later, earlier)
    if operation == "sum":
        if earlier is None:
            raise ValueError("a sum needs two cells")
        return difference(later, "0") + difference(earlier, "0")
    return difference(later, "0")


def _asked_gdp_line(question: str, variable, code: str) -> bool:
    """Keep the GDP aggregate the binder already chose. A later total pass
    was replacing it with the exports line, which also ends in 'alls'."""
    from grund.isgdp import wants_gdp

    asked = fold(question)
    if wants_gdp(question, None):
        from grund.isgdp import _line_is_gdp

        label = variable.label(code) if hasattr(variable, "label") else str(code)
        return _line_is_gdp(label)
    if not any(word in asked for word in ("gdp", "landsframleidsl", "gross domestic product", "thjodarframleidsl")):
        return False
    if any(word in asked for word in ("export", "utflutning", "percent", "hlutfall", "per capita")):
        return False
    label = variable.label(code) if hasattr(variable, "label") else str(code)
    folded = fold(label)
    if "landsframleidsl" not in folded and "gross domestic product" not in folded:
        return False
    return not any(word in folded for word in ("export", "utflutning", "visitala", "index", "percent", "hlutfall"))


def refine_selection(edition, parsed, chosen: dict[str, list[str]], operation: str):
    """Replace codes the question did not name with the table's total or unit.

    Returns (chosen, operation, notes). A variable with no metadata choice
    keeps the code the caller already had.
    """
    notes: list[str] = []
    operation = operation_for(parsed.text, operation, edition)
    if operation != parsed.operation:
        notes.append(f"operation {parsed.operation} read as {operation}")
    selected = {choice.variable_code: choice for choice in select_values(parsed.text, edition)}
    refined: dict[str, list[str]] = {}
    for variable in edition.variables:
        current = list(chosen.get(variable.code) or [])
        from grund.bind import _named_origin

        forced = _named_origin(variable, parsed)
        if forced:
            refined[variable.code] = [forced]
            if current != [forced]:
                notes.append(f"{variable.code}: origin {forced}")
            continue
        from grund.measure_guard import value_code as measure_value_code

        measured = measure_value_code(
            variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
        )
        if measured is not None:
            refined[variable.code] = [measured]
            if current != [measured]:
                notes.append(f"{variable.code}: measure {measured}")
            continue
        from grund.isshare import share_value_code

        share_pin = share_value_code(
            variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
        )
        if share_pin is not None and any(str(code) == share_pin for code in current):
            refined[variable.code] = [str(code) for code in current]
            continue
        if len(current) == 1:
            from grund.istown import municipality_code

            pinned = municipality_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isjobsex import labour_sex_code

            pinned = labour_sex_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isbirths import birth_value_code

            pinned = birth_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isregion import region_value_code

            pinned = region_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isgdp import gdp_line_code

            pinned = gdp_line_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.istrade import trade_line_code

            pinned = trade_line_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.iscpi import cpi_value_code

            pinned = cpi_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.iswage import wage_value_code

            pinned = wage_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isstays import stays_value_code

            pinned = stays_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isquarter import quarter_value_code

            pinned = quarter_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.ispop import pop_value_code

            pinned = pop_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isjobs import labour_value_code

            pinned = labour_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
            from grund.isshare import share_value_code

            pinned = share_value_code(
                variable, parsed.text, getattr(parsed, "language", None), getattr(edition, "title", "") or ""
            )
            if pinned is not None and pinned == str(current[0]):
                refined[variable.code] = [str(current[0])]
                continue
        choice = selected.get(variable.code)
        if current and _asked_gdp_line(parsed.text, variable, current[0]):
            refined[variable.code] = [current[0]]
            continue
        if choice is None:
            if current:
                refined[variable.code] = current
            continue
        from grund.agree_hyb import enabled as agree_hyb
        from grund.bind import _frame_country

        # "In Iceland" names the country. It does not replace the citizenship total.
        if agree_hyb() and _frame_country(variable, str(choice.value_label), parsed):
            if current:
                refined[variable.code] = current
            continue
        from grund.agree_hyb import enabled as agree_hyb
        from grund.bind import _frame_country

        # "In Iceland" names the country. It does not replace the citizenship total.
        if agree_hyb() and _frame_country(variable, str(choice.value_label), parsed):
            if current:
                refined[variable.code] = current
            continue
        # The pasted title shares words with a component row ("Lending").
        # That is not a request to leave the total. A word written outside
        # the title still replaces it.
        if current and len(current) == 1 and choice.role == "subgroup":
            from grund.bind import aggregate_label, title_only_label

            current_label = variable.label(current[0]) if hasattr(variable, "label") else current[0]
            if aggregate_label(current_label) and title_only_label(
                choice.value_label, getattr(edition, "title", "") or "", getattr(variable, "text", "") or ""
            ):
                refined[variable.code] = current
                continue
        # A value named outside the pasted title is the row. A title word
        # such as "Kvikmyndahús" or "Labour force" is not, when the question
        # also names "Sætafjöldi" or "Employed".
        if current and _outside_title(choice.value_label, getattr(edition, "title", "") or "") and not _outside_title(
            variable.label(current[0]) if hasattr(variable, "label") else current[0],
            getattr(edition, "title", "") or "",
        ):
            refined[variable.code] = [choice.value_code]
            if choice.value_code not in current:
                notes.append(f"{variable.code}: named {choice.value_label}")
            continue
        if choice.role == "time_span" and choice.why.startswith("two:"):
            refined[variable.code] = choice.why.split(":", 1)[1].split(",")
            notes.append(f"{variable.code}: periods {choice.value_label}")
            continue
        if len(current) >= 2 and not _is_time_variable(variable):
            # A share needs the part and the total. A level needs one row.
            # "Eignir" and "skuldir" are both in the title; the binder's first
            # row is the one it ranked. A longer word is not more specific.
            if operation == "share" or (operation in {"difference", "sum"} and choice.role != "subgroup"):
                refined[variable.code] = current
                continue
            current_label = variable.label(current[0]) if hasattr(variable, "label") else current[0]
            if _cell_rule("after_title") and "after the title" in str(choice.why):
                refined[variable.code] = [choice.value_code]
                if choice.value_code not in current:
                    notes.append(f"{variable.code}: one row {choice.value_label}")
                continue
            if _phrase_names_label(current_label, variable, _raw_tokens(parsed.text)) and not _label_contains(
                choice.value_label, current_label
            ):
                refined[variable.code] = [current[0]]
                if choice.value_code != current[0]:
                    notes.append(f"{variable.code}: one row {current_label}")
                continue
            refined[variable.code] = [choice.value_code]
            if choice.value_code not in current or len(current) != 1:
                notes.append(f"{variable.code}: one row {choice.value_label}")
            continue
        if choice.role == "time":
            refined[variable.code] = [choice.value_code]
            if current != [choice.value_code]:
                notes.append(f"{variable.code}: period {choice.value_label}")
            continue
        if (
            current
            and not str(choice.why).startswith("several values")
            and not (_cell_rule("title_names") and str(choice.why).startswith("title names"))
            and "after the title" not in str(choice.why)
            and _keep_current(variable, current[0], parsed.text)
        ):
            current_label = variable.label(current[0]) if hasattr(variable, "label") else current[0]
            if choice.role in {"total", "sex_age_all", "unit", "annual_average"} or not _full_phrase(choice.value_label, fold(parsed.text)):
                refined[variable.code] = current
                continue
            if _full_phrase(current_label, fold(parsed.text)):
                refined[variable.code] = current
                continue
        current_label = variable.label(current[0]) if current and hasattr(variable, "label") else (current[0] if current else "")
        if (
            current
            and _qualified_total(current_label)
            and _qualified_total(choice.value_label)
            and not _content_words(choice.value_label) > _content_words(current_label)
        ):
            # "Salmon caught, total" stays against a different qualified total.
            # A broader "sectors and households" still replaces the narrower one.
            refined[variable.code] = current
            continue
        if _judgesim_keep(parsed.text, str(current_label or ""), choice):
            refined[variable.code] = current
            continue
        if not current or current != [choice.value_code]:
            notes.append(f"{variable.code}: {choice.role} {choice.value_label}")
        refined[variable.code] = [choice.value_code]
    if _published_change_selected(edition, refined):
        return refined, "level", notes
    if operation in {"yoy_pct", "difference"}:
        time_var = next((variable for variable in edition.variables if _is_time_variable(variable)), None)
        if time_var is not None:
            codes = refined.get(time_var.code) or []
            if len(codes) == 1:
                previous = _previous_code(time_var.codes(), codes[0])
                if previous:
                    refined[time_var.code] = [previous, codes[0]]
                    notes.append(f"{time_var.code}: added the previous period {previous}")
    return refined, operation, notes


def _published_change_selected(edition, refined: dict) -> bool:
    """The annual-change column is already the change. It is not two index levels."""
    for variable in edition.variables:
        if getattr(variable, "time", False) or _is_time_variable(variable):
            continue
        for code in refined.get(variable.code) or []:
            label = fold(variable.label(code) if hasattr(variable, "label") else str(code))
            if any(phrase in label for phrase in ("annual change", "arsbreyting", "arbreyting")):
                return True
    return False


def _bind_dimension(variable, text: str, span: tuple[int, int] | None = None, title: str = "") -> ValueChoice | None:
    values = [(str(code), str(label)) for code, label in variable.values]
    if not values:
        return None
    from grund.bind import _change_denied

    if _change_denied(text):
        kept = [
            (code, label)
            for code, label in values
            if not any(phrase in fold(label) for phrase in ("annual change", "arsbreyting", "arbreyting"))
        ]
        if kept:
            values = kept
    if len(values) == 1:
        code, label = values[0]
        return _choice(variable, code, label, "only", 1.0, "single value")
    named = _named_labels(values, text, variable, span)
    if named:
        code, label, why = named
        role = (
            "total"
            if why.startswith("several values") or (_cell_rule("title_names") and why.startswith("title names"))
            else _named_role(label)
        )
        return _choice(variable, code, label, role, 3.0, why)
    if _asks_annual_average(text):
        found = _annual_average(values)
        if found:
            return _choice(variable, found[0], found[1], "annual_average", 2.5, "question asks for the annual average")
    if _asks_month(text) and not _asks_annual_average(text):
        # A month named in the question is not the annual-average row.
        pass
    from grund.bind import _category_named_in_question, _question_forbids_total

    named_code = _category_named_in_question(variable, text, title)
    if named_code is not None:
        label = variable.label(named_code) if hasattr(variable, "label") else named_code
        return _choice(variable, named_code, label, "subgroup", 3.0, "question names this category")
    if _question_forbids_total(variable, text, title):
        return None
    total = _best_total(values)
    if total and not _dimension_named(variable, text):
        return _choice(variable, total[0], total[1], "total", 2.0, "no value named, total row")
    if _is_sex_or_age(variable) and total:
        return _choice(variable, total[0], total[1], "sex_age_all", 2.0, "sex or age not named")
    unit = _unit_choice(values, text)
    if unit:
        return _choice(variable, unit[0], unit[1], "unit", 2.0, unit[2])
    if total:
        return _choice(variable, total[0], total[1], "total", 1.0, "fallback total")
    if getattr(variable, "elimination", False):
        return None
    return None


def _series_is_already_per_person(edition) -> bool:
    if edition is None:
        return False
    title = fold(getattr(edition, "title", "") or "")
    return any(phrase in title for phrase in _PER_PERSON)


def _raw_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def _outside_title(label: str, title: str) -> list[str]:
    title_tokens = set(_raw_tokens(title))
    found = []
    for token in _raw_tokens(label):
        if len(token) < 4 or token in title_tokens:
            continue
        if any(_same_word(token, other) for other in title_tokens):
            continue
        found.append(token)
    return found


def _same_word(left: str, right: str) -> bool:
    """Whole word, or the same word plus a short grammatical ending."""
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if not longer.startswith(shorter):
        return False
    return longer[len(shorter):] in _INFLECTIONS


def _phrase_tokens(label: str) -> list[str]:
    # Keep short words such as "í". Dropping them makes "vinnu í viðmiðunarviku"
    # fail to line up with the question.
    tokens = _raw_tokens(label)
    if not tokens or all(token in _GENERIC_LABEL for token in tokens):
        return []
    return tokens


def _dimension_word(token: str, variable) -> bool:
    if token in _DIMENSION or token in _GENERIC_LABEL:
        return True
    for other in _dimension_tokens(variable):
        if token == other or _same_word(token, other):
            return True
    return False


def _place_not_a_subgroup(label: str, question: list[str], variable) -> bool:
    """``in Iceland`` names the place, not the Iceland row of a citizenship list.

    A question that says born, citizenship, or origin still selects that row.
    """
    folded = fold(label).strip(" .:-")
    if folded not in {"iceland", "island", "islandi"}:
        return False
    var = fold(f"{getattr(variable, 'text', '')} {getattr(variable, 'code', '')}")
    if not any(
        piece in var
        for piece in ("citizen", "thjoderni", "nationalit", "faeding", "birth", "rikisfang", "origin", "bakgrunn")
    ):
        return False
    text = " ".join(question)
    return not any(
        piece in text
        for piece in ("citizen", "born", "faed", "rikisfang", "origin", "bakgrunn", "upprun", "thjoderni", "islensk")
    )


def _name_tokens(label: str) -> list[str]:
    """Words that have to appear. 'Total' on 'marriages dissolved, total' is not one of them."""
    tokens = _phrase_tokens(label)
    if _totalish(label) and not _is_strict_total(label):
        tokens = [token for token in tokens if token not in {"total", "totals", "alls", "samtals", "all", "heild"}]
    return tokens


def _threshold_age(question: list[str], label: str) -> bool:
    """'16 years and older' is the table's population, not the single year 16."""
    label_tokens = [token for token in _raw_tokens(label) if token.isdigit() or len(token) >= 2]
    if not label_tokens or not label_tokens[0].isdigit():
        return False
    number = label_tokens[0]
    shapes = ([number], [number, "years"], [number, "year"], [number, "ara"], [number, "ar"])
    if label_tokens not in shapes:
        return False
    for index in range(len(question) - 3):
        if question[index] != number:
            continue
        if question[index + 1] in {"years", "year", "ara", "ar"} and question[index + 2] in {"and", "og"} and question[index + 3] in {"older", "eldri"}:
            return True
    return False


def _number_inside_a_range(question: list[str], label: str) -> bool:
    """The 0 in '0-5 years' or '60-63' is not the row whose label is 0."""
    tokens = _name_tokens(label)
    if len(tokens) != 1 or not tokens[0].isdigit():
        return False
    number = tokens[0]
    for index, token in enumerate(question):
        if token != number:
            continue
        neighbor = False
        if index + 1 < len(question) and question[index + 1].isdigit():
            neighbor = True
        if index > 0 and question[index - 1].isdigit():
            neighbor = True
        if not neighbor:
            return False
    return number in question


def _phrase_names_label(label: str, variable, question: list[str]) -> bool:
    """True when the label itself, not a piece of a longer word, is written."""
    if _of_which(label) or _is_strict_total(label):
        return False
    if not _cell_rule("qualified_name") and _totalish(label):
        return False
    if _cell_rule("threshold_age") and _threshold_age(question, label):
        return False
    if _cell_rule("range_number") and _number_inside_a_range(question, label):
        return False
    # "in Iceland" is the place. It is not the Iceland row of a birth or
    # citizenship list, unless the question asks for that list.
    if _place_not_a_subgroup(label, question, variable):
        return False
    phrase = _name_tokens(label) if _cell_rule("qualified_name") else _phrase_tokens(label)
    if not phrase:
        return False
    if phrase and all(_dimension_word(token, variable) for token in phrase if not token.isdigit()):
        return False
    width = len(phrase)
    for start in range(len(question) - width + 1):
        if all(_label_token(phrase[offset], question[start + offset]) for offset in range(width)):
            return True
    return False


def _label_token(left: str, right: str) -> bool:
    """The label word is the question word. Synonyms and -nu apply only when asked."""
    if _same_word(left, right):
        return True
    from grund.agree_hyb import aligns, enabled

    return bool(enabled() and aligns(left, right))


def _total_content(label: str) -> set[str]:
    stop = {
        "total", "totals", "alls", "samtals", "all", "heild", "for", "fyrir",
        "og", "and", "the", "alla", "allir",
    }
    return {token for token in _raw_tokens(label) if len(token) >= 4 and token not in stop}


def _covers_how_many(label: str, others: list[tuple[str, str]]) -> int:
    words = _total_content(label)
    covered = 0
    for _code, other in others:
        other_words = _total_content(other)
        if other_words and other_words < words:
            covered += 1
    return covered


def _joins_other_totals(label: str, others: list[str]) -> bool:
    """A grand total names the parts and joins them with and/og."""
    if not re.search(r"\b(and|og)\b", fold(label)):
        return False
    words = _total_content(label)
    for other in others:
        other_words = _total_content(other)
        if other_words and other_words < words:
            return True
    return False


def _code_is_total(code: str) -> bool:
    return fold(str(code)) in {"alls", "total", "samtals"}


def top_total(values: list[tuple[str, str]]) -> tuple[str, str] | None:
    """The first total-like row in a long codelist. Headers such as "Eignir:" are not it."""
    for code, label in values:
        if _of_which(label):
            continue
        if _totalish(label) or _code_is_total(code):
            return code, label
    return None


def _judgesim_keep(question: str, current_label: str, choice) -> bool:
    from grund.judgesim_fix import keep_binder_row

    return keep_binder_row(question, current_label, choice.role, choice.value_label)


def _asks_share(question: str) -> bool:
    text = fold(question)
    if re.search(r"\b(by what percent|percent change|prosentubreyting|um hve \w* prosent)\b", text):
        return False
    if re.search(r"\b(percentage of|percent of|hlutfall af|hlutdeild af|what share|what proportion)\b", text):
        return True
    if re.search(r"\bhversu\b.{0,30}\b(hlutfall|hlutdeild)\b", text):
        return True
    if re.search(r"\bhve stort hlutfall\b", text):
        return True
    from grund.judgesim_fix import enabled, share_phrase

    return bool(enabled() and share_phrase(question))


def _title_span(question: str, title: str) -> tuple[int, int] | None:
    """The part of the question that copies the table title.

    With the title_prefix rule, a title that ends in 'from 2012' still matches
    the prefix the question actually contains.
    """
    stem = re.sub(r"\b(?:19|20)\d{2}\b", " ", fold(title))
    stem = re.sub(r"\s+", " ", stem).strip(" -")
    folded = fold(question)
    if _cell_rule("title_prefix"):
        best = None
        acc: list[str] = []
        for word in stem.split():
            acc.append(word)
            chunk = " ".join(acc)
            if len(chunk) >= 16 and chunk in folded:
                best = chunk
            elif best is not None and chunk not in folded:
                break
        if best is None:
            return None
        at = folded.find(best)
        return at, at + len(best)
    if len(stem) < 16:
        return None
    at = folded.find(stem)
    if at < 0 and len(stem) > 48:
        at = folded.find(stem[:48])
        if at >= 0:
            return at, at + 48
    if at < 0:
        return None
    return at, at + len(stem)


def _phrase_at(label: str, question_folded: str) -> int | None:
    """Character offset of the label phrase inside the folded question."""
    tokens = _name_tokens(label) if _cell_rule("qualified_name") else _phrase_tokens(label)
    if not tokens:
        return None
    matches = list(re.finditer(r"[a-z0-9]+", question_folded))
    qtokens = [match.group(0) for match in matches]
    width = len(tokens)
    for start in range(len(qtokens) - width + 1):
        if all(_same_word(tokens[offset], qtokens[start + offset]) for offset in range(width)):
            return matches[start].start()
    return None


def _label_contains(longer: str, shorter: str) -> bool:
    wide = fold(longer).strip()
    narrow = fold(shorter).strip()
    return bool(narrow) and narrow != wide and narrow in wide


def _content_words(label: str) -> set[str]:
    stop = {
        "total", "totals", "alls", "samtals", "all", "heild", "for", "fyrir",
        "og", "and", "the", "alla", "allir",
    }
    return {token for token in _raw_tokens(label) if len(token) >= 4 and token not in stop}


def _qualified_total(label: str) -> bool:
    return _totalish(label) and not _is_strict_total(label)


def _totalish(label: str) -> bool:
    if _is_strict_total(label):
        return True
    folded = fold(label)
    return bool(re.search(r"\b(alls|total|samtals)\b", folded))


def _named_labels(values, text: str, variable, span: tuple[int, int] | None = None) -> tuple[str, str, str] | None:
    """The longest label whose own words stand in the question as a phrase.

    A label written again after the table title beats a longer label that
    only appears inside the title. "Iceland" is not inside "Icelandic".
    When the title names both sides of a split and the list has a plain
    total, that total is the row.
    """
    question = _raw_tokens(text)
    found: list[tuple[int, int, str, str]] = []
    for code, label in values:
        if not _phrase_names_label(label, variable, question):
            continue
        at = _phrase_at(label, text)
        outside = 0
        if span is not None and at is not None and not (span[0] <= at < span[1]):
            outside = 1
        found.append((outside, len(fold(label).strip()), code, label))
    if not found:
        return None
    strict = [(code, label) for code, label in values if _is_strict_total(label) and not _of_which(label)]
    if span is not None and len(found) >= 2 and strict and all(item[0] == 0 for item in found):
        strict.sort(key=lambda item: len(fold(item[1])))
        return strict[0][0], strict[0][1], "several values named, so the total"
    # Several "X, total" lines inside the title: the first is the headline total.
    if _cell_rule("title_names") and span is not None and found and all(item[0] == 0 for item in found):
        if all(_totalish(item[3]) for item in found):
            headline = top_total(values)
            if headline is not None:
                return headline[0], headline[1], "title names the table, so the total"
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    outside, _length, code, label = found[0]
    if outside:
        return code, label, "label is written after the title"
    return code, label, "label is written in the question"


def _named_role(label: str) -> str:
    folded = fold(label)
    if re.search(r"\b(arsmedaltal|annual average)\b", folded):
        return "annual_average"
    if any(word in folded.split() for word in _MEDIAN | _MEAN | _MODE):
        return "subgroup"
    return "subgroup"


def _best_total(values: list[tuple[str, str]]) -> tuple[str, str] | None:
    exact = [(code, label) for code, label in values if _is_strict_total(label) and not _of_which(label)]
    if exact:
        exact.sort(key=lambda item: len(fold(item[1])))
        return exact[0]
    tail = []
    for code, label in values:
        if _of_which(label):
            continue
        folded = fold(label).strip()
        words = re.findall(r"[a-z0-9]+", folded)
        # "Samtals úrgangur" names one measure. It is not the unnamed total.
        # "Total - all activities" and a label that ends in "total" still are.
        if (
            words
            and words[0] in {"samtals", "total", "alls"}
            and words[1] not in {"for", "fyrir"}
            and "all" not in words[1:]
            and not folded.endswith((" total", " alls", " samtals"))
            and len(words) > 1
        ):
            continue
        # "Útflutningur alls" is the exports subtotal, not the table total.
        blocked = r"\b(innflut\w*|imported|exports?\w*|utflut\w*|erlend\w*|foreign\w*)\b"
        if re.search(r"\b(alls|total|samtals)\b", folded) and not (
            _cell_rule("export_subtotal") and re.search(blocked, folded)
        ):
            tail.append((code, label))
    if not tail:
        return None
    # "Total for sectors and households" covers the two narrower totals.
    # A shorter "total for households" is that part, not the grand total.
    joiners = [
        (code, label)
        for code, label in tail
        if _joins_other_totals(label, [other for _c, other in tail if other != label])
    ]
    if joiners:
        joiners.sort(
            key=lambda item: (
                _covers_how_many(item[1], tail),
                -tail.index(item),
            ),
            reverse=True,
        )
        return joiners[0]
    # The first total-like row is the series total. A shorter later row
    # such as "Divorces, total" is one component, not the total the question
    # left unnamed.
    return tail[0]


def _is_strict_total(label: str) -> bool:
    folded = fold(label).strip(" .:-")
    if folded in _EXACT_TOTAL:
        return True
    if folded in {"0", "-1"}:
        return False
    return False


def _of_which(label: str) -> bool:
    folded = fold(label)
    return any(marker in folded for marker in _OF_WHICH)


def _dimension_named(variable, text: str) -> bool:
    """True when the question names a real value, not the dimension itself."""
    return _named_labels(list(variable.values), text, variable) is not None


def _dimension_tokens(variable) -> set[str]:
    found = set(fold(variable.text).split())
    found |= {token for token in found if token}
    return found


def _is_sex_or_age(variable) -> bool:
    folded = fold(variable.text)
    return any(word in folded.split() for word in ("kyn", "sex", "gender", "aldur", "age"))


def _asks_annual_average(text: str) -> bool:
    return bool(re.search(r"\b(arsmedaltal|arsfjordungsmedaltal|annual average|quarterly average)\b", text))


def _asks_month(text: str) -> bool:
    return bool(
        re.search(
            r"\b(januar|februar|mars|april|mai|juni|juli|agust|september|oktober|november|desember|"
            r"january|february|march|april|may|june|july|august|october|december)\b",
            text,
        )
    )


def _annual_average(values) -> tuple[str, str] | None:
    for code, label in values:
        if re.search(r"\b(arsmedaltal|annual average)\b", fold(label)):
            return code, label
    return None


def _unit_choice(values, text: str) -> tuple[str, str, str] | None:
    mentioned = []
    for code, label in values:
        folded = fold(label)
        if folded in _GENERIC_LABEL:
            continue
        # "books" is inside "childrenbooks". The unit is named only as its own word.
        if len(folded) >= 5 and re.search(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", text):
            mentioned.append((code, label))
    if len(mentioned) == 1:
        return mentioned[0][0], mentioned[0][1], "unit named in the question"
    if _asks_count(text):
        for code, label in values:
            if re.search(r"\b(fjoldi|number|tolur)\b", fold(label)) and "%" not in label:
                return code, label, "count rather than a percent column"
    return None


def _asks_count(text: str) -> bool:
    return bool(re.search(r"\b(hve marg|how many|fjoldi|number of)\b", text))


def _is_time_variable(variable) -> bool:
    if getattr(variable, "time", False):
        return True
    codes = [str(code) for code, _label in variable.values]
    if len(codes) < 3:
        return False
    hits = sum(1 for code in codes if re.fullmatch(r"A?(?:19|20)\d{2}(?:M\d{2}|Q\d)?", code, re.I))
    return hits >= max(3, len(codes) // 2)


def _base_years(question: str, analysis) -> set[int]:
    years = {int(year) for year in re.findall(r"(?:19|20)\d{2}(?=\s*=\s*100)", question)}
    for match in re.findall(r"(?:grunnur|base)\s*((?:19|20)\d{2})", question, flags=re.I):
        years.add(int(match))
    if analysis is not None:
        for year in getattr(analysis, "bases", []) or []:
            years.add(int(year))
    return years


def _bind_time(variable, question: str, text: str, bases: set[int], analysis) -> ValueChoice | None:
    codes = [str(code) for code, _label in variable.values]
    asked = _asked_periods(question, bases)
    if not asked:
        return None
    matched = []
    for year, month, quarter in asked:
        code = _match_code(codes, year, month, quarter)
        if code and code not in matched:
            matched.append(code)
    if not matched:
        return None
    if len(matched) >= 2:
        # why carries both codes; refine_selection unpacks the "two:" form.
        label = ", ".join(matched[:2])
        return ValueChoice(variable.code, variable.text, matched[-1], label, "time_span", 3.0, "two:" + ",".join(matched[:2]))
    code = matched[-1]
    label = variable.label(code) if hasattr(variable, "label") else code
    return _choice(variable, code, label, "time", 3.0, "period named in the question")


def _asked_periods(question: str, bases: set[int]) -> list[tuple[int, int | None, int | None]]:
    text = question
    found: list[tuple[int, int | None, int | None]] = []
    for match in re.finditer(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"janúar|febrúar|mars|apríl|maí|júní|júlí|ágúst|september|október|nóvember|desember)\s+((?:19|20)\d{2})",
        text,
        flags=re.I,
    ):
        year = int(match.group(2))
        if year in bases:
            continue
        found.append((year, _month_number(match.group(1)), None))
    for match in re.finditer(
        r"\b((?:19|20)\d{2})M(\d{2})\b",
        text,
        flags=re.I,
    ):
        year = int(match.group(1))
        if year not in bases:
            found.append((year, int(match.group(2)), None))
    for match in re.finditer(r"\b((?:19|20)\d{2})\b", text):
        year = int(match.group(1))
        if year in bases:
            continue
        if any(item[0] == year and item[1] for item in found):
            continue
        found.append((year, None, None))
    # Keep order, drop duplicate years that already have a month.
    deduped = []
    for item in found:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _month_number(name: str) -> int:
    folded = fold(name)
    names = {
        "january": 1, "januar": 1, "february": 2, "februar": 2, "march": 3, "mars": 3,
        "april": 4, "may": 5, "mai": 5, "june": 6, "juni": 6, "july": 7, "juli": 7,
        "august": 8, "agust": 8, "september": 9, "october": 10, "oktober": 10,
        "november": 11, "december": 12, "desember": 12,
    }
    return names.get(folded, 0) or 1


def _match_code(codes: list[str], year: int, month: int | None, quarter: int | None) -> str | None:
    if month:
        wanted = {f"{year}M{month:02d}".upper(), f"{year}M{month}".upper()}
        for code in codes:
            if code.upper() in wanted:
                return code
        # The crawled list can be one month behind the question.
        monthly = []
        for code in codes:
            parsed = re.fullmatch(r"(\d{4})M(\d{2})", str(code), re.I)
            if parsed:
                monthly.append((int(parsed.group(1)), int(parsed.group(2))))
        if monthly:
            last_year, last_month = max(monthly)
            nxt = f"{last_year + 1}M01" if last_month == 12 else f"{last_year}M{last_month + 1:02d}"
            if nxt.upper() in wanted:
                return nxt
        return None
    if quarter:
        wanted = {f"{year}Q{quarter}".upper()}
        for code in codes:
            if code.upper().replace("Á", "A") in wanted:
                return code
        return None
    for code in codes:
        if code == str(year) or code.upper() == f"A{year}":
            return code
    return None


def _previous_code(codes: list[str], code: str) -> str | None:
    monthly = re.fullmatch(r"(\d{4})M(\d{2})", code, re.I)
    if monthly:
        target = f"{int(monthly.group(1)) - 1}M{monthly.group(2)}".upper()
        for candidate in codes:
            if candidate.upper() == target:
                return candidate
        return None
    census = re.fullmatch(r"A?(\d{4})", code, re.I)
    if census and not re.search(r"M|Q", code, re.I):
        target_year = str(int(census.group(1)) - 1)
        for candidate in codes:
            if candidate == target_year or candidate.upper() == f"A{target_year}":
                return candidate
    return None


def _full_phrase(label: str, text: str) -> bool:
    folded = fold(label).strip()
    return len(folded) >= 4 and folded in text and folded not in _GENERIC_LABEL


def _keep_current(variable, code: str, question: str) -> bool:
    """The binder's row stays when the question writes that label.

    A total stays when the question writes one of its own words, other than
    the word total and other than the dimension ("by economic sector" does
    not keep "total for economic sectors"). A subgroup stays only when the
    whole label is written. "Foreign" does not keep "Foreign country not
    specified", and "education" does not keep one attainment band.
    """
    label = variable.label(code) if hasattr(variable, "label") else str(code)
    question_tokens = _raw_tokens(question)
    if _phrase_names_label(label, variable, question_tokens):
        return True
    if _of_which(label) or not _totalish(label):
        return False
    qualifiers = []
    for token in _phrase_tokens(label):
        if token in {"total", "totals", "alls", "samtals", "all"} or token.isdigit() or len(token) < 4:
            continue
        if _dimension_word(token, variable):
            continue
        qualifiers.append(token)
    # "Samtals innflutt orka" adds "innflutt". Every such word has to be written.
    if not qualifiers:
        return False
    return all(any(_same_word(token, other) for other in question_tokens) for token in qualifiers)


def _choice(variable, code: str, label: str, role: str, score: float, why: str) -> ValueChoice:
    return ValueChoice(variable.code, getattr(variable, "text", variable.code), code, label, role, score, why)
