"""Turn `bind_values` choices into a PxWeb binding.

The language layer picks the codes. This module only fills the operation
fields the arithmetic already understands, and it checks the query against
the edition. A choice list that does not cover the table yields no binding.
"""

from __future__ import annotations

import re

from grund.bind import Binding, _match_period, _previous, _select_time, is_total
from grund.cells import refine_selection
from grund.validator import ValidationError, validate
from grund.parse import ParsedQuestion, parse_question
from grund_index.model import Edition
from grund_index.textutil import fold


class _Choice:
    """The fields of a bind_values choice the query builder reads."""

    def __init__(self, variable_code: str, variable_text: str, value_code: str, value_label: str, role: str, score: float, why: str) -> None:
        self.variable_code = variable_code
        self.variable_text = variable_text
        self.value_code = value_code
        self.value_label = value_label
        self.role = role
        self.score = score
        self.why = why


def _soft(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(text)).split())


def _question_names(label: str, question: str) -> bool:
    """The question repeats this value label, not merely a shorter word inside it."""
    folded = _soft(label)
    if len(folded) < 4 or folded.isdigit():
        return False
    haystack = f" {_soft(question)} "
    needle = f" {folded} "
    if needle in haystack:
        return True
    if any(ch.isdigit() for ch in folded) and folded in haystack:
        return True
    return False


def _mostly_time(variable) -> bool:
    codes = [str(code) for code, _label in variable.values]
    if not codes:
        return False
    marked = sum(1 for code in codes if len(code) == 4 and code.isdigit() or (len(code) > 4 and code[:4].isdigit()))
    return marked >= max(3, len(codes) // 2)


def refine_choices(edition: Edition, parsed: ParsedQuestion, choices: list) -> list:
    """Keep bind_values, but a label the question repeats wins, and an unnamed list stays on its total."""
    by_var: dict[str, list] = {}
    for choice in choices:
        by_var.setdefault(choice.variable_code, []).append(choice)
    refined: list = []
    for variable in edition.variables:
        if variable.time or _mostly_time(variable):
            refined.extend(by_var.get(variable.code, []))
            continue
        named = [
            (len(" ".join(fold(label).split())), str(code), str(label))
            for code, label in variable.values
            if _question_names(str(label), parsed.text)
        ]
        if named:
            _length, code, label = max(named)
            refined.append(_Choice(variable.code, variable.text, code, label, "named", 9.0, "the question names this label"))
            continue
        total = next(((str(code), str(label)) for code, label in variable.values if is_total(label)), None)
        current = by_var.get(variable.code) or []
        if total and (not current or not is_total(current[0].value_label)):
            refined.append(_Choice(variable.code, variable.text, total[0], total[1], "total", 3.0, "no subgroup named"))
            continue
        refined.extend(current)
    return refined


def _present_stock(text: str) -> bool:
    """A present-tense question with no period of its own."""
    folded = fold(text)
    if any(word in folded for word in ("lived", "bjuggu", "bjuggum", "what was", "hver var", "hvert var")):
        return False
    return any(
        word in folded
        for word in (" live", " lives", "bua", " byr", "mannfjoldi", "population", "what is", "hver er", "hvad er")
    )


def _with_latest_year(edition: Edition, parsed: ParsedQuestion) -> ParsedQuestion | None:
    variable = edition.time_variable()
    if variable is not None and variable.values:
        _code, label = variable.values[-1]
        return parse_question(f"{parsed.text} {label}", parsed.language)
    years = sorted(edition.years())
    if not years:
        return None
    return parse_question(f"{parsed.text} {years[-1]}", parsed.language)


def combined_binding(edition: Edition, parsed: ParsedQuestion) -> Binding | None:
    """The language binding, including a share of the part and the total.

    Cell-row heuristics stay off this path. A fresh question is not a dev
    item, and stating a wrong row is worse than refusing.
    """
    from grund_lang.driver import binding_from_values as nlp_bind

    built = nlp_bind(edition, parsed)
    if built is None and not parsed.periods and _present_stock(parsed.text):
        restated = _with_latest_year(edition, parsed)
        if restated is not None:
            built = nlp_bind(edition, restated)
    if built is None:
        return None
    try:
        validate(edition, built.selections)
    except ValidationError:
        return None
    from grund.bind2 import apply_binding

    updated = apply_binding(edition, parsed, built)
    return built if updated is None else updated


def binding_from_values(edition: Edition, parsed: ParsedQuestion, choices: list) -> Binding | None:
    """A binding whose codes are the ones `bind_values` returned, after the named-row check."""
    choices = refine_choices(edition, parsed, choices)
    if not choices:
        return None
    chosen: dict[str, list[str]] = {}
    for choice in choices:
        code = str(choice.value_code)
        bucket = chosen.setdefault(choice.variable_code, [])
        if code not in bucket:
            bucket.append(code)
    for variable in edition.variables:
        if getattr(variable, "elimination", False):
            continue
        if chosen.get(variable.code):
            continue
        # A month or year list the binder left empty still has to be selected,
        # or PxWeb rejects the query and the turn states no figure.
        if variable.time or _mostly_time(variable):
            picked = _select_time(variable, parsed, parsed.operation)
            if picked:
                chosen[variable.code] = picked
                continue
        return None

    chosen, operation, cell_notes = refine_selection(edition, parsed, chosen, parsed.operation)
    notes_prefix = ["codes from bind_values", *cell_notes]

    time_var = None
    time_codes: list[str] = []
    time_variable = edition.time_variable()
    if time_variable is None:
        for variable in edition.variables:
            if chosen.get(variable.code) and (variable.time or _mostly_time(variable)):
                time_variable = variable
                break
    if time_variable is not None:
        time_var = time_variable.code
        time_codes = list(chosen.get(time_variable.code) or [])
        if operation in {"yoy_pct", "difference"} and len(time_codes) == 1:
            previous = _previous(time_variable.codes(), time_codes[0])
            if previous:
                time_codes = [code for code in time_variable.codes() if code in {time_codes[0], previous}]
                chosen[time_variable.code] = time_codes
        if operation in {"yoy_pct", "difference"} and len(time_codes) < 2:
            return None

    group_var = part_code = whole_code = None
    notes = notes_prefix
    if operation == "share":
        for variable in edition.variables:
            if variable.time or variable.code not in chosen:
                continue
            codes = chosen[variable.code]
            non_total = [code for code in codes if not is_total(variable.label(code))]
            total = next((code for code, label in variable.values if is_total(label)), None)
            if len(non_total) != 1 or total is None:
                continue
            if total not in codes:
                codes.append(total)
            group_var = variable.code
            part_code = non_total[0]
            whole_code = total
            notes.append("share uses the part and the total on the same variable")
            break
        if group_var is None:
            # "hlutfall" in a title is the name of the series, not two cells to divide.
            operation = "level"
            notes.append("no part and total were both selected, so the cell is stated")

    rebase_code = None
    target_code = None
    if operation == "rebase":
        if time_variable is None or parsed.rebase_year is None:
            return None
        base = _match_period(time_variable.codes(), parsed.rebase_year, None)
        if base is None:
            return None
        if base not in time_codes:
            time_codes = [code for code in time_variable.codes() if code in set(time_codes + [base])]
            chosen[time_variable.code] = time_codes
        targets = [code for code in time_codes if code != base]
        if not targets:
            return None
        rebase_code = base
        target_code = targets[-1]

    selections = [
        {"code": code, "selection": {"filter": "item", "values": values}}
        for code, values in chosen.items()
        if values
    ]
    return Binding(
        edition=edition,
        selections=selections,
        operation=operation,
        score=0,
        time_var=time_var,
        time_codes=time_codes,
        group_var=group_var,
        part_code=part_code,
        whole_code=whole_code,
        rebase_code=rebase_code,
        target_code=target_code,
        notes=notes,
        official_measure=False,
    )
