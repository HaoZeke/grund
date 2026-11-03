"""The stated cell has to carry the measure the question names.

A word of the question's first clause is carried when the stated table's
title, variable names or the stated cell's labels (in either language)
write it, directly or through the tokenizer's own synonyms and lemmas.
Words that name periods (the labels of time variables and of codelists
named for a period, "Month") are not measures. Two cases are refused:

* A word is not carried by the stated row but is written by another row
  of the same codelist ("GWh" on the generation row beside the MW
  capacity row). The question named that row, not the stated one. When
  exactly one row writes every such word, that row is stated instead;
  otherwise the answer is refused.
* Every codelist of the stated cell is at its total, and the question
  writes the whole measure of another table, the title up to "by" /
  "eftir" ("Moves"), which the stated cell does not carry. A grand total
  of one measure is not a count of another.

Everything is read from the catalogue; there is no word list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from grund_index.textutil import fold, tokens

from grund import country_row, row_guard
from grund.sibling_measure import _clauses

_CACHE: dict[int, tuple[set, dict]] = {}


def enabled() -> bool:
    return row_guard.enabled()


def _measure(title: str) -> tuple:
    part = re.split(r"\b(?:by|eftir)\b", fold(title or ""), maxsplit=1)[0]
    return tuple(dict.fromkeys(row_guard._words(part)))


def _index(catalogue) -> tuple[set, dict]:
    found = _CACHE.get(id(catalogue))
    if found is not None:
        return found
    periods: set[str] = set()
    measures: dict[tuple, str] = {}
    for table in catalogue.tables:
        for edition in table.editions.values():
            measure = _measure(edition.title)
            if measure:
                measures.setdefault(measure, table.id.removesuffix(".px"))
            for variable in edition.variables:
                if variable.time or row_guard._TIME_NAME.search(fold(f"{variable.code} {variable.text or ''}")):
                    periods.update(row_guard._root(word) for word in tokens(variable.text or ""))
                    for _code, label in variable.values:
                        periods.update(row_guard._root(word) for word in tokens(str(label or "")))
    found = (periods, measures)
    _CACHE[id(catalogue)] = found
    return found


def _carried(word: str, have: list[str]) -> bool:
    return any(row_guard._covered(form, have) for form in (word, *tokens(word, expand=True)))


def _at_totals(edition, cell: dict) -> bool:
    for item in cell.get("labels") or []:
        if not isinstance(item, dict):
            continue
        variable = edition.variable(str(item.get("variable")))
        if variable is None or variable.time or not row_guard._classification(variable):
            continue
        if not country_row._aggregate(str(item.get("label") or "")):
            return False
    return True


@dataclass(frozen=True)
class Carried:
    action: str
    variable: str = ""
    code: str = ""
    detail: str = ""


def carried_decide(question: str, result: dict, catalogue) -> Carried:
    """keep; switch to the one row of a stated codelist that writes every
    word the question names there; or refuse."""
    detail = uncarried(question, result, catalogue)
    if not detail:
        return Carried("keep")
    rows = _named_rows(question, result, catalogue)
    if len(rows) == 1:
        variable, code, label = rows[0]
        return Carried("switch", variable, code, f"measure: the question names the row {label!r}")
    return Carried("refuse", detail=detail)


def _free(question: str, result: dict, catalogue):
    cells = country_row._cells(result)
    if len(cells) != 1:
        return None
    edition, peer = row_guard._edition(catalogue, result)
    if edition is None:
        return None
    periods, _measures = _index(catalogue)
    have = country_row._have(edition, peer, result)
    clause = _clauses(question)[0]
    free = [
        word for word in country_row._free_words(clause, have)
        if row_guard._root(word) not in periods and not _carried(word, have)
    ]
    return edition, peer, cells[0], free


def _named_rows(question: str, result: dict, catalogue) -> list[tuple[str, str, str]]:
    found = _free(question, result, catalogue)
    if found is None:
        return []
    edition, peer, cell, free = found
    named: dict[tuple[str, str], set[str]] = {}
    labels: dict[tuple[str, str], str] = {}
    for item in cell.get("labels") or []:
        if not isinstance(item, dict):
            continue
        variable = edition.variable(str(item.get("variable")))
        if variable is None or variable.time:
            continue
        for code, label in variable.values:
            if str(code) == str(item.get("code")):
                continue
            words = row_guard._words(str(label or "")) + row_guard._words(row_guard._peer_label(peer, variable.code, str(code)))
            hit = {word for word in free if row_guard._covered(word, words)}
            if hit:
                named[(variable.code, str(code))] = hit
                labels[(variable.code, str(code))] = str(label or code)
    whole = [key for key, hit in named.items() if hit == set(free)]
    return [(variable, code, labels[(variable, code)]) for variable, code in whole]


def uncarried(question: str, result: dict, catalogue) -> str | None:
    """Why the stated cell does not carry the question's measure, or None."""
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return None
    cells = country_row._cells(result)
    if len(cells) != 1:
        return None
    edition, peer = row_guard._edition(catalogue, result)
    if edition is None:
        return None
    periods, measures = _index(catalogue)
    have = country_row._have(edition, peer, result)
    clause = _clauses(question)[0]
    free = [
        word for word in country_row._free_words(clause, have)
        if row_guard._root(word) not in periods and not _carried(word, have)
    ]
    if not free:
        return None
    cell = cells[0]
    for item in cell.get("labels") or []:
        if not isinstance(item, dict):
            continue
        variable = edition.variable(str(item.get("variable")))
        if variable is None or variable.time:
            continue
        for code, label in variable.values:
            if str(code) == str(item.get("code")):
                continue
            words = row_guard._words(str(label or ""))
            named = [word for word in free if row_guard._covered(word, words)]
            if named:
                return f"measure: the question writes {named[0]!r}, which the row {item.get('label')!r} does not carry and the row {label!r} does"
    if not _at_totals(edition, cell):
        return None
    asked = row_guard._words(clause)
    stated = str(result.get("table_id") or "").removesuffix(".px")
    for measure, table_id in measures.items():
        if table_id == stated or not all(any(row_guard._same(word, other) for other in asked) for word in measure):
            continue
        missing = [word for word in measure if row_guard._root(word) not in periods and not _carried(word, have)]
        if missing:
            return f"measure: the question asks for {' '.join(measure)!r} ({table_id}), which the total of {stated} does not carry"
    return None
