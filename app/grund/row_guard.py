"""The row of the stated cell, and a subindex the cell does not carry.

Both checks read the catalogue metadata only: the codelists of the stated
table, their value labels, and the subject folder the table sits in.

A codelist's total is the one value whose label is an aggregate ("Total",
"Alls", "Total Pension Schemes"). PxWeb's elimination flag would say the
same, but this catalogue sets it on very few variables, so the label is
the evidence. A codelist with no aggregate label, or with several (a unit
list such as "Total moves", "Total persons"), has no single total and is
left alone.

A value label is named by a question when every word that tells it apart
is in the question. Words of the table title and of the variable name are
shared by every row, so they tell nothing apart and are not counted. Codes
and numbers are not words.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from grund_index.textutil import MIN_TOKEN_LEN, fold, lemmas, tokens

from grund.bind import aggregate_label, is_total

_ON = {"1", "true", "yes", "on"}

# Icelandic case and number endings, and the English plural. One ending is
# removed, longest first, and the root keeps at least three letters.
_ENDINGS = ("unum", "inum", "anna", "arnar", "urnar", "inni", "um", "ur", "ar", "ir", "es", "s", "i", "a", "u")
_GLUE = {
    "and", "og", "the", "of", "for", "in", "on", "at", "by", "eftir", "med", "vid", "til", "fra",
    "from", "per", "excl", "incl", "excluding", "including", "than", "sem", "an", "um",
}
_TOTAL_WORD = {"total", "totals", "alls", "samtals", "all", "heild", "allir", "allar", "oll", "allt"}
# Words that pick the first or the last class of a ranked codelist
# ("1. quartile" ... "4. quartile").
_LOWEST = {"lowest", "bottom", "first", "laegst", "laegsta", "laegsti", "nedst", "nedsta", "fyrst", "fyrsta", "fyrsti"}
_HIGHEST = {"highest", "top", "last", "haest", "haesta", "haesti", "efst", "efsta", "sidast", "sidasta"}
_RANKED = re.compile(r"^\s*(\d{1,2})\s*(?:\.|st\b|nd\b|rd\b|th\b)\s*(\D.*)$")
_TIME_NAME = re.compile(r"\b(year|ar|month|manudur|quarter|arsfjordungur|time|timi|week|vika|day|dagur)\b")


def enabled() -> bool:
    return os.environ.get("GRUND_ROW_GUARD", "").strip().lower() in _ON


def _root(word: str) -> str:
    word = fold(word)
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= MIN_TOKEN_LEN:
            return word[: -len(ending)]
    return word


# Icelandic u-umlaut: an a of the last stem syllable is written ö before an
# ending in u ("vísitala", "vísitölu"; "saga", "sögu"). Folding writes that ö
# as o, so the ending is checked first and the vowel restored.
_U_ENDINGS = tuple(ending for ending in _ENDINGS if ending.startswith("u"))
_LAST_O = re.compile(r"^(.*)o([^aeiouy]+)$")


def _unumlaut(word: str) -> str:
    word = fold(word)
    for ending in _U_ENDINGS:
        if word.endswith(ending):
            found = _LAST_O.match(word[: -len(ending)])
            if found and len(found.group(0)) >= MIN_TOKEN_LEN:
                return f"{found.group(1)}a{found.group(2)}{ending}"
            break
    return word


def _umlaut_root(word: str) -> str:
    return _root(_unumlaut(word))


def _same(label_word: str, asked: str) -> bool:
    if label_word == asked or _root(label_word) == _root(asked):
        return True
    if _umlaut_root(label_word) == _umlaut_root(asked):
        return True
    if set(lemmas(label_word, icelandic=True)) & set(lemmas(asked, icelandic=True)):
        return True
    # An Icelandic compound carries its head last: "tekjufjórðungi" is
    # "tekju" + "fjórðung". The modifier has to be a word of the catalogue,
    # possibly with a genitive link; "sub" in "subindex" is an affix.
    root = _root(label_word)
    other = _root(asked)
    if other == root or not other.endswith(root):
        return False
    return _is_modifier(other[: -len(root)])


_LINKS = ("ar", "u", "a", "s", "i")
_VOCAB: set[str] = set()


# Bound prefixes make a new word, not a compound: a subindex is not the index.
_AFFIXES = {"sub", "non", "un", "re", "pre", "co", "semi", "mis", "o", "for", "tor", "undir", "yfir"}


def _is_modifier(prefix: str) -> bool:
    if prefix in _AFFIXES:
        return False
    if prefix in _VOCAB:
        return True
    return any(prefix.endswith(link) and prefix[: -len(link)] in _VOCAB for link in _LINKS)


_VOCABS: dict[int, set[str]] = {}


def _load_vocab(catalogue) -> None:
    global _VOCAB
    found = _VOCABS.get(id(catalogue))
    if found is None:
        found = set()
        for table in catalogue.tables:
            for edition in table.editions.values():
                found.update(_root(word) for word in tokens(edition.title))
                for variable in edition.variables:
                    if variable.time:
                        continue
                    for _code, label in variable.values:
                        found.update(_root(word) for word in tokens(str(label or "")))
        _VOCABS[id(catalogue)] = found
    _VOCAB = found


# Every table of this catalogue is about Iceland. The country's name in a
# question is that scope, not the row "Iceland" of a citizenship list.
_SCOPE = {"iceland", "island", "islandi", "islands"}


def _words(text: str) -> list[str]:
    return [
        word for word in tokens(text)
        if not any(ch.isdigit() for ch in word) and word not in _GLUE and word not in _SCOPE
    ]


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+", fold(text or ""))


def _covered(word: str, pool: list[str]) -> bool:
    return any(_same(word, other) for other in pool)


@dataclass(frozen=True)
class _Value:
    code: str
    label: str
    words: tuple
    rank: int | None
    noun: tuple
    numbers: tuple = ()


def _values(edition, variable) -> list[_Value]:
    shared = _words(f"{edition.title} {variable.text}")
    found = []
    for code, label in variable.values:
        label = str(label or code)
        ranked = _RANKED.match(fold(label))
        rank = int(ranked.group(1)) if ranked else None
        noun = tuple(_words(ranked.group(2))) if ranked else ()
        words = tuple(word for word in _words(label) if word not in _TOTAL_WORD and not _covered(word, shared))
        found.append(_Value(str(code), label, words, rank, noun, tuple(_numbers(label))))
    return found


def _total(values: list[_Value]) -> _Value | None:
    """The codelist total: the one bare total, else the one aggregate.

    A bare total is an aggregate label with no word beyond the title and the
    variable name: "Alls", "Total", "Total Pension Schemes" under "Pension
    scheme". "Einkaneysla innanlands alls" qualifies the total by a word of
    its own, so it is a subtotal when a bare total sits beside it.
    """
    bare = [value for value in values if (is_total(value.label) or aggregate_label(value.label)) and not value.words]
    if len(bare) == 1:
        return bare[0]
    if bare:
        return None
    aggregates = [value for value in values if aggregate_label(value.label)]
    return aggregates[0] if len(aggregates) == 1 else None


def _named(value: _Value, asked: list[str], ranks: list[int], variable_words: list[str]) -> int:
    """How many distinguishing words of the value the question writes. 0 is not named."""
    if value.rank is not None and ranks:
        wants = set()
        if any(word in _LOWEST for word in asked):
            wants.add(min(ranks))
        if any(word in _HIGHEST for word in asked):
            wants.add(max(ranks))
        if value.rank not in wants:
            return 0
        if not any(_covered(word, asked) for word in (*value.noun, *variable_words)):
            return 0
        return 1
    if not value.words:
        return 0
    if all(_covered(word, asked) for word in value.words):
        return len(value.words)
    return 0


def _touched(value: _Value, asked: list[str], numbers: list[str] = ()) -> bool:
    """The question uses any word or number of the value, or the start of a word.

    "Reykjavík" touches "Reykjavíkurborg"; "aged 30" touches "30 years".
    """
    if any(number in numbers for number in value.numbers):
        return True
    for word in value.words:
        if _covered(word, asked):
            return True
        if any(_root(other) in _VOCAB and word.startswith(_root(other)) for other in asked):
            return True
    return False


def _total_in_both(total: _Value, peer, code: str) -> bool:
    """A total is a total in both editions. The codes are shared, the labels are not."""
    if peer is None:
        return True
    for variable in peer.variables:
        if variable.code == code:
            label = variable.label(total.code)
            return is_total(label) or aggregate_label(label)
    return True


def _stated(result: dict) -> list[dict]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells = [cell for cell in source.get("cells") or [] if isinstance(cell, dict)]
    return cells


def _edition(catalogue, result: dict):
    stem = str(result.get("table_id") or "").removesuffix(".px")
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return None, None
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    lang = str(source.get("language") or result.get("language") or "")
    edition = table.editions.get(lang) or next(iter(table.editions.values()), None)
    peer = next((other for key, other in table.editions.items() if key != lang), None)
    return edition, peer


def _classification(variable) -> bool:
    return not variable.time and not _TIME_NAME.search(fold(variable.text or ""))


def row_reason(question: str, result: dict, catalogue, exempt: tuple = ()) -> str | None:
    """A refusal detail when the stated row is not the row the question names.

    The total is stated but the question names one other row of that
    codelist: the question asked for that row. A row is stated that the
    question does not name, in a codelist that has a total: the cell is a
    restriction nobody asked for, and the total is the answer the table
    gives.
    """
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return None
    cells = _stated(result)
    if len(cells) != 1:
        return None
    edition, peer = _edition(catalogue, result)
    if edition is None:
        return None
    _load_vocab(catalogue)
    asked = _words(question)
    numbers = _numbers(question)
    chosen = {str(item.get("variable")): str(item.get("code")) for item in cells[0].get("labels") or [] if isinstance(item, dict)}
    spent = _spent(edition, chosen, asked)
    for variable in edition.variables:
        if not _classification(variable) or variable.code not in chosen or variable.code in exempt:
            continue
        values = _values(edition, variable)
        total = _total(values)
        if total is None or not _total_in_both(total, peer, variable.code):
            continue
        # Words that already name another variable's stated row are spent.
        free = [word for word in asked if word not in spent.get(variable.code, set())]
        stated = next((value for value in values if value.code == chosen[variable.code]), None)
        if stated is None:
            continue
        ranks = [value.rank for value in values if value.rank is not None]
        variable_words = _words(variable.text)
        scores = [(value, _named(value, free, ranks, variable_words)) for value in values if value.code != total.code]
        best = max((score for _value, score in scores), default=0)
        leaders = [value for value, score in scores if best and score == best]
        if stated.code == total.code:
            if len(leaders) == 1:
                return f"row: the question names {leaders[0].label}, the cell is {total.label}"
            continue
        if any(score for _value, score in scores):
            continue
        if _touched(stated, asked, numbers) or not stated.words:
            continue
        if peer is not None and _peer_touched(peer, variable.code, stated.code, asked, numbers):
            continue
        return f"row: {stated.label} is not named, the codelist total is {total.label}"
    return None


def _peer_touched(peer, code: str, value_code: str, asked: list[str], numbers: list[str]) -> bool:
    for variable in peer.variables:
        if variable.code != code:
            continue
        for value in _values(peer, variable):
            if value.code == value_code:
                return _touched(value, asked, numbers)
    return False


def _spent(edition, chosen: dict[str, str], asked: list[str]) -> dict[str, set[str]]:
    """For each variable, the question words that name the stated rows of the other variables."""
    used: dict[str, set[str]] = {}
    for variable in edition.variables:
        if variable.code not in chosen:
            continue
        for value in _values(edition, variable):
            if value.code == chosen[variable.code]:
                used[variable.code] = {word for word in asked if any(_same(own, word) for own in value.words)}
    return {
        variable.code: set().union(*(words for code, words in used.items() if code != variable.code))
        for variable in edition.variables
    }


@dataclass(frozen=True)
class LabelDecision:
    action: str
    table: str = ""
    label: str = ""


def _folder(edition) -> tuple:
    path = tuple(edition.path or ())
    return path[:-1] if len(path) > 1 else path


def label_decide(question: str, result: dict, catalogue, measure: list[str], years: set[int], covers) -> LabelDecision:
    """A measure word the stated cell does not carry, written as a row label in a sibling table.

    Siblings are the tables of the same subject folder. PxWeb files a
    headline series and its breakdowns side by side there, so a subindex
    such as "rice" or "durable products" is a row of a sibling table and
    not a title word. When the stated cell's own title, variable names and
    labels do not carry that word, the headline is not the answer. One
    sibling that names it and covers the years asked is taken; any other
    count is a refusal.
    """
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return LabelDecision("keep")
    edition, peer = _edition(catalogue, result)
    if edition is None:
        return LabelDecision("keep")
    _load_vocab(catalogue)
    have: list[str] = []
    for side in (edition, peer):
        if side is None:
            continue
        have.extend(_words(side.title))
        for variable in side.variables:
            have.extend(_words(variable.text))
    for cell in _stated(result):
        for item in cell.get("labels") or []:
            if isinstance(item, dict):
                have.extend(_words(str(item.get("label") or "")))
                have.extend(_words(_peer_label(peer, str(item.get("variable")), str(item.get("code")))))
    asked = _words(question)
    if not _headline(edition, result, asked, _numbers(question)):
        return LabelDecision("keep")
    missing = [word for word in asked if any(_same(word, stem) or _same(stem, word) for stem in measure) and not _covered(word, have)]
    if not missing:
        return LabelDecision("keep")
    folder = _folder(edition)
    chosen_id = str(result.get("table_id") or "").removesuffix(".px")
    tables: dict[str, str] = {}
    for table in catalogue.tables:
        for other in table.editions.values():
            if _folder(other) != folder:
                continue
            for variable in other.variables:
                if not _classification(variable):
                    continue
                for value in _values(other, variable):
                    if aggregate_label(value.label) or not value.words:
                        continue
                    if not all(_covered(word, asked) for word in value.words):
                        continue
                    if not any(_same(word, gap) or _same(gap, word) for word in value.words for gap in missing):
                        continue
                    tables.setdefault(table.id.removesuffix(".px"), value.label)
    if not tables:
        return LabelDecision("keep")
    usable = {stem: label for stem, label in tables.items() if stem != chosen_id and covers(stem, years)}
    if len(usable) == 1 and chosen_id not in tables:
        stem, label = next(iter(usable.items()))
        return LabelDecision("switch", stem, label)
    return LabelDecision("refuse", "", next(iter(tables.values())))


def _headline(edition, result: dict, asked: list[str], numbers: list[str]) -> bool:
    """No classification row of the stated cell is touched by the question.

    A cell the question already cuts by one of its rows is a breakdown,
    not the headline series.
    """
    for cell in _stated(result):
        for item in cell.get("labels") or []:
            if not isinstance(item, dict):
                continue
            variable = edition.variable(str(item.get("variable")))
            if variable is None or not _classification(variable):
                continue
            for value in _values(edition, variable):
                if value.code == str(item.get("code")) and _touched(value, asked, numbers):
                    return False
    return True


def _peer_label(peer, code: str, value_code: str) -> str:
    if peer is None:
        return ""
    for variable in peer.variables:
        if variable.code == code:
            return variable.label(value_code)
    return ""
