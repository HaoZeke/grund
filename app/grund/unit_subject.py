"""The unit and the subject a question states have to be carried by the stated cell.

Units are read from the catalogue, not from a list. The mirrored json-stat
carries no UNITS or CONTENTS, so a unit is read where PxWeb writes it in a
value label: after the last comma ("Annual generation of energy, GWh") or in
closing parentheses ("Value (1000 ISK)"). A word of those parts is a unit
word unless some table title writes it: a title names what a table
measures, so a word it writes ("persons", "index", "dairy") is a measure or
a subject, not a unit. Units are often shorter than an index token ("MW",
"kg"), so they are read with their own tokenizer.

The stated cell carries a unit word when its own labels (in either
language) or its table's titles write it. When it does not
and exactly one other row of one stated codelist does, that row is the
compatible cell. Otherwise the answer is refused.

The subject is checked only for a cell at the totals of every classification
codelist. It is the set of words of the question's first clause other than
total, period and unit words; when the catalogue does not write one of them
anywhere, nothing is said. When the stated table writes none of them in its
titles, variable names or labels, in either language, the table is about
something else.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from grund_index.textutil import MIN_TOKEN_LEN, fold, tokens

from grund import country_row, row_guard
from grund.sibling_measure import _clauses

_UNITS: dict[int, tuple[object, frozenset]] = {}
_TABLE_WORDS: dict[tuple[int, str], tuple[object, frozenset]] = {}
_ROOTS: dict[int, tuple[frozenset, frozenset, list[str], frozenset]] = {}
_TAIL = re.compile(r",([^,]*)$")
_CLOSING = re.compile(r"\(([^()]*)\)\s*$")


def enabled() -> bool:
    return row_guard.enabled()


def unit_tokens(text: str) -> list[str]:
    """Folded letter runs of any length, with any digits that follow ("m2")."""
    return [token for token in re.findall(r"[a-z][a-z0-9]*", fold(text or "")) if token not in row_guard._GLUE]


def _split(label: str) -> tuple[str, list[str]]:
    """A value label's head and the one-word unit parts after it."""
    head = label
    parts: list[str] = []
    for pattern in (_CLOSING, _TAIL):
        found = pattern.search(head)
        if found:
            words = unit_tokens(found.group(1))
            if len(words) == 1:
                parts.append(words[0])
                head = head[: found.start()]
    return head, parts


def _row_units(variable) -> set[str]:
    """The unit words of one codelist.

    A codelist states units when every row other than its total ends in a
    one-word part and the parts tell rows apart ("..., MW" beside "...,
    GWh"). A part only some rows have describes those rows, and one part
    shared by all qualifies the whole list; neither is a unit choice. A
    codelist named for a period ("2018, August") states periods.

    Unit / Eining codelists are not read here: their labels are measures as
    often as units ("Number of individuals", "Unemployed", "Per 1000
    inhabitants"), and on the earlier sets reading them refused right
    answers for month names and question words.
    """
    if not row_guard._classification(variable):
        return set()
    parts: set[str] = set()
    for _code, label in variable.values:
        label = str(label or "")
        if country_row._aggregate(label):
            continue
        found = _split(label)[1]
        if not found:
            return set()
        parts.update(found)
    return parts if len(parts) > 1 else set()


def units(catalogue) -> frozenset:
    """Unit words of the catalogue's codelists that no table title writes."""
    found = _UNITS.get(id(catalogue))
    if found is not None and found[0] is catalogue:
        return found[1]
    written: set[str] = set()
    titled: set[str] = set()
    for table in catalogue.tables:
        for edition in table.editions.values():
            titled.update(unit_tokens(edition.title))
            for variable in edition.variables:
                if not variable.time:
                    written.update(_row_units(variable))
    from grund.measure_carried import _index

    periods, _measures = _index(catalogue)
    # A single folded letter is an initial or a piece of an abbreviation ("n.e.s."), not a unit a question can write.
    found = frozenset(word for word in written - titled if len(word) > 1 and row_guard._root(word) not in periods)
    _UNITS[id(catalogue)] = (catalogue, found)
    return found


def _same_unit(asked: str, written: str) -> bool:
    if asked == written:
        return True
    if min(len(asked), len(written)) < MIN_TOKEN_LEN:
        return False
    return row_guard._same(written, asked)


def asked_units(question: str, catalogue) -> list[str]:
    vocabulary = units(catalogue)
    asked: list[str] = []
    for token in unit_tokens(question):
        if any(_same_unit(token, unit) for unit in vocabulary) and token not in asked:
            asked.append(token)
    return asked


def _label_pair(edition, peer, item: dict) -> list[str]:
    own = str(item.get("label") or "")
    other = row_guard._peer_label(peer, str(item.get("variable")), str(item.get("code")))
    return [own, other]


def _carries(words: list[str], asked: str) -> bool:
    return any(_same_unit(asked, word) for word in words)


@dataclass(frozen=True)
class UnitDecision:
    action: str
    variable: str = ""
    code: str = ""
    detail: str = ""


def unit_decide(question: str, result: dict, catalogue) -> UnitDecision:
    """keep, switch to one compatible row of the stated table, or refuse."""
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return UnitDecision("keep")
    cells = country_row._cells(result)
    if len(cells) != 1:
        return UnitDecision("keep")
    asked = asked_units(question, catalogue)
    if not asked:
        return UnitDecision("keep")
    edition, peer = row_guard._edition(catalogue, result)
    if edition is None:
        return UnitDecision("keep")
    items = [item for item in cells[0].get("labels") or [] if isinstance(item, dict)]
    shared: list[str] = []
    for side in (edition, peer):
        if side is not None:
            shared.extend(unit_tokens(side.title))
    stated: list[str] = list(shared)
    for item in items:
        for label in _label_pair(edition, peer, item):
            stated.extend(unit_tokens(label))
    missing = [unit for unit in asked if not _carries(stated, unit)]
    if not missing:
        return UnitDecision("keep")
    options: list[tuple[str, str, str]] = []
    for item in items:
        variable = edition.variable(str(item.get("variable")))
        if variable is None or variable.time:
            continue
        rest = list(shared)
        for other in items:
            if other is not item:
                for label in _label_pair(edition, peer, other):
                    rest.extend(unit_tokens(label))
        for code, label in variable.values:
            if str(code) == str(item.get("code")):
                continue
            words = rest + unit_tokens(str(label or "")) + unit_tokens(row_guard._peer_label(peer, variable.code, str(code)))
            if all(_carries(words, unit) for unit in asked):
                options.append((variable.code, str(code), str(label or code)))
    if len(options) == 1:
        variable, code, label = options[0]
        return UnitDecision("switch", variable, code, f"unit: the question asks in {missing[0]!r}; the row {label!r} carries it")
    where = "several rows carry it" if options else "no row of the stated table carries it"
    return UnitDecision("refuse", detail=f"unit: the question asks in {missing[0]!r} and {where}")


def _table_words(catalogue, table_id: str) -> frozenset:
    key = (id(catalogue), table_id)
    found = _TABLE_WORDS.get(key)
    if found is not None and found[0] is catalogue:
        return found[1]
    table = catalogue.by_id.get(table_id + ".px") or catalogue.by_id.get(table_id)
    words: set[str] = set()
    for edition in (table.editions.values() if table is not None else ()):
        words.update(row_guard._words(edition.title))
        for variable in edition.variables:
            words.update(row_guard._words(variable.text or ""))
            if variable.time:
                continue
            for _code, label in variable.values:
                words.update(row_guard._words(str(label or "")))
    found = frozenset(words)
    _TABLE_WORDS[key] = (catalogue, found)
    return found


def _roots(pool: frozenset) -> tuple[frozenset, list[str], frozenset]:
    """The pool's roots, sorted, and the roots that lost an ending."""
    found = _ROOTS.get(id(pool))
    if found is None or found[0] is not pool:
        pairs = [(word, row_guard._umlaut_root(word)) for word in pool]
        roots = frozenset(root for _word, root in pairs)
        stems = frozenset(root for word, root in pairs if root != word and len(root) >= MIN_TOKEN_LEN)
        found = (pool, roots, sorted(roots), stems)
        _ROOTS[id(pool)] = found
    return found[1], found[2], found[3]


def _starts_some(root: str, ordered: list[str]) -> bool:
    at = bisect.bisect_left(ordered, root)
    return at < len(ordered) and ordered[at].startswith(root)


def _forms(word: str) -> list[str]:
    return [word, *tokens(word, expand=True)]


def _written(word: str, pool: frozenset) -> bool:
    """The pool writes the word: a form of it, its compound head, a word that
    starts with it ("Reykjavík" in "Reykjavíkurborg"), or a stem the pool
    writes with an ending that the word writes with another ("fædd-ir",
    "fædd-ust")."""
    roots, ordered, stems = _roots(pool)
    for form in _forms(word):
        root = row_guard._umlaut_root(form)
        if form in pool or root in roots:
            return True
        for cut in range(1, len(root) - MIN_TOKEN_LEN + 1):
            if root[cut:] in roots and row_guard._is_modifier(root[:cut]):
                return True
        if len(root) < MIN_TOKEN_LEN:
            continue
        if _starts_some(root, ordered) or any(root[:end] in stems for end in range(MIN_TOKEN_LEN, len(root))):
            return True
    return False


_ALL_WORDS: dict[int, tuple[object, frozenset]] = {}


def _catalogue_words(catalogue) -> frozenset:
    """Every word a title, variable name or label of the catalogue writes."""
    found = _ALL_WORDS.get(id(catalogue))
    if found is None or found[0] is not catalogue:
        words: set[str] = set()
        for table in catalogue.tables:
            words.update(_table_words(catalogue, table.id.removesuffix(".px")))
        found = (catalogue, frozenset(words))
        _ALL_WORDS[id(catalogue)] = found
    return found[1]


def subject_missing(question: str, result: dict, catalogue) -> str | None:
    """Why the stated table is about something else, or None."""
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return None
    stem = str(result.get("table_id") or "").removesuffix(".px")
    cells = country_row._cells(result)
    if not stem or len(cells) != 1:
        return None
    from grund.measure_carried import _at_totals, _index

    edition, _peer = row_guard._edition(catalogue, result)
    if edition is None or not _at_totals(edition, cells[0]):
        return None

    periods, _measures = _index(catalogue)
    known = _catalogue_words(catalogue)
    vocabulary = units(catalogue)
    clause = _clauses(question)[0]
    subject = [
        word for word in row_guard._words(clause)
        if word not in row_guard._TOTAL_WORD
        and row_guard._root(word) not in periods
        and not any(_same_unit(word, unit) for unit in vocabulary)
    ]
    # A word the catalogue never writes ("emigrated" beside "emigration")
    # leaves part of the subject unread, so nothing can be said about it.
    if not subject or not all(_written(word, known) for word in subject):
        return None
    pool = _table_words(catalogue, stem)
    if any(_written(word, pool) for word in subject):
        return None
    return f"subject: {stem} writes none of {', '.join(repr(word) for word in dict.fromkeys(subject))}"
