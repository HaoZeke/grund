"""Same published figure, behind GRUND_AGREE_HYB=1.

Two readings agree when they state the same cell value. A different table,
a different unit label, or a stock date written as a month is not a second
figure. A different number is not an agreement.
"""

from __future__ import annotations

import os
import re

_INFLECTION = (
    "unum", "anna", "inum", "inni", "urnar", "arnar",
    "ing", "ed", "es", "ir", "ar", "ur", "um", "inn", "num",
    "s", "a", "i", "u", "nu",
)
_FRAME = {"iceland", "island", "islandi", "islande"}
_MONTHS = {
    "january", "januar", "february", "februar", "march", "mars", "april",
    "may", "mai", "june", "juni", "july", "juli", "august", "agust",
    "september", "october", "oktober", "november", "desember", "december",
}
_NOT_A_PLACE = _FRAME | _MONTHS | {
    "total", "totals", "alls", "samtals", "all", "heild", "people", "person",
    "population", "mannfjoldi", "mannfjolda", "lived", "live", "bjuggu",
    "overnight", "stays", "stay", "registered", "accommodation", "gistinaetur",
    "landsframleidsla", "landsframleidslu", "women", "woman", "konur", "female",
    "females", "january",
}


def enabled() -> bool:
    return os.environ.get("GRUND_AGREE_HYB", "").strip().lower() in {"1", "true", "yes", "on"}


def same_word(left: str, right: str) -> bool:
    """The same word, or that word plus a grammatical ending, including -nu."""
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if not longer.startswith(shorter):
        return False
    return longer[len(shorter) :] in _INFLECTION


def aligns(left: str, right: str) -> bool:
    """Same word, the same word inflected, or a catalogue synonym of it."""
    if same_word(left, right):
        return True
    if not enabled():
        return False
    from grund_index.textutil import SYNONYMS, fold

    a, b = fold(left), fold(right)
    if same_word(a, b):
        return True
    bag = {a, *[fold(item) for item in SYNONYMS.get(a, ())]}
    if b in bag or any(same_word(b, item) for item in bag):
        return True
    bag_b = {b, *[fold(item) for item in SYNONYMS.get(b, ())]}
    return a in bag_b


_MONTH_NAMES = (
    "january|januar|february|februar|march|mars|april|may|mai|june|juni|"
    "july|juli|august|agust|september|october|oktober|november|desember|december"
)


def day_of_month(text: str) -> bool:
    """A day and a month name, such as 1 January or 1. janúar.

    That is a stock date. It is not the monthly code of a monthly table.
    """
    from grund_index.textutil import fold

    return bool(re.search(rf"\b\d{{1,2}}\s*\.?\s*(?:{_MONTH_NAMES})\b", fold(text or "")))


def stock_january(text: str) -> bool:
    """1 January is the population stock date, not a monthly series."""
    return day_of_month(text)


_WORK = re.compile(
    r"\b(vinnu\w*|atvinnu\w*|labour|employ\w*|hours|starfandi|atvinnuleys\w*)\b"
)
_SHARE = re.compile(r"\b(hlutfall\w*|hlutdeild\w*|percentage|percent)\b")
_FEMALE_WORD = re.compile(
    r"\b(konur|kona|kvenn\w*|women|woman|females|female|stulkur|stulka)\b"
)
_MALE_WORD = re.compile(r"\b(karlar|karlmenn\w*|men|males|male)\b")
_COUNT_WORD = re.compile(r"\b(marg\w*|how many|fjold\w*)\b")


def sex_headcount(question: str) -> bool:
    """One sex, asked as a count. A job, a rate, or a share is not that count."""
    from grund_index.textutil import fold

    text = fold(question or "")
    if _WORK.search(text) or _SHARE.search(text):
        return False
    if _COUNT_WORD.search(text) is None:
        return False
    female = _FEMALE_WORD.search(text) is not None
    male = _MALE_WORD.search(text) is not None
    return female != male


def labour_title_for_headcount(title: str, question: str) -> bool:
    """A labour-force or percentage table is not a count of women or men."""
    if not sex_headcount(question):
        return False
    from grund_index.textutil import fold

    folded = fold(title or "")
    return any(
        word in folded
        for word in (
            "vinnuafl",
            "labour force",
            "labour market",
            "vinnumarkad",
            "vinnustund",
            "hours",
            "starfandi",
            "employed",
            "hlutfalls",
            "percentage distribution",
            "prosentuskip",
        )
    )


def quarterly_gdp_title(title: str, question: str) -> bool:
    """A plain GDP question is the annual series, not the quarterly one."""
    from grund_index.textutil import fold

    asked = fold(question or "")
    if not any(mark in asked for mark in ("gdp", "landsframleidsl", "thjodarframleidsl", "gross domestic")):
        return False
    if any(mark in asked for mark in ("arsfjord", "quarter", "fjordung")):
        return False
    folded = fold(title or "")
    return any(word in folded for word in ("arsfjord", "quarterly", "by quarter"))


def constant_price_title(title: str, question: str) -> bool:
    """A constant-price table is not the current-price figure."""
    if not enabled():
        return False
    from grund_index.textutil import fold

    asked = fold(question or "")
    # Only a product question should skip the constant-price copy.
    # Other questions keep the reading they already had.
    if not any(mark in asked for mark in ("gdp", "landsframleidsl", "thjodarframleidsl", "gross domestic")):
        return False
    if any(mark in asked for mark in ("constant price", "fostu verd", "fast verd")):
        return False
    folded = fold(title or "")
    return "constant price" in folded or "fostu verd" in folded


def label_named(label: str, question: str) -> bool:
    """The question writes this value, not merely the country or a month name."""
    if not enabled() or not label or not question:
        return False
    from grund_index.textutil import fold

    lab = re.findall(r"[a-z0-9]+", fold(label))
    lab = [token for token in lab if token not in {"total", "totals", "alls", "samtals", "all", "heild"}]
    if not lab or all(token in _MONTHS or token.isdigit() for token in lab):
        return False
    if set(lab) <= _FRAME:
        return False
    question_tokens = re.findall(r"[a-z0-9]+", fold(question))
    width = len(lab)
    if width > len(question_tokens):
        return False
    for start in range(len(question_tokens) - width + 1):
        if all(aligns(lab[offset], question_tokens[start + offset]) for offset in range(width)):
            return True
    return False


# Current municipalities (MAN02005) and regions (MAN03250). A question that
# names one of these has named a place. Historical parishes are not places.
_PLACE_TABLES = {"MAN02005", "MAN03250"}
_PLACE_GENERIC = {"sveitarfelagid", "sveitarfelag", "municipality", "municipalities"}
_PLACE_SUFFIX = re.compile(
    r"^(?:ar|s)?(?:kaupstadur|kaupstad|urborg|hreppur|baer|borg)?$"
)
_PLACE_SKIP = _FRAME | {
    "total", "totals", "alls", "samtals", "all", "heild", "allt",
}
_DERIVED_OPS = {"difference", "yoy_pct", "change", "pct_change", "share", "sum", "pair"}
_PLACE_CACHE: tuple[tuple[str, ...], ...] | None = None


def _place_token(question_token: str, label_token: str) -> bool:
    """The question word is this place, or that place plus bær/borg/hreppur."""
    if question_token == label_token or aligns(question_token, label_token):
        return True
    limit = min(len(question_token), len(label_token))
    shared = 0
    while shared < limit and question_token[shared] == label_token[shared]:
        shared += 1
    if shared < 6:
        return False
    qrest = question_token[shared:]
    lrest = label_token[shared:]
    if qrest not in _INFLECTION and qrest != "":
        return False
    if not lrest:
        return True
    return _PLACE_SUFFIX.fullmatch(lrest) is not None


def _content_tokens(text: str) -> list[str]:
    from grund_index.textutil import tokens

    return [token for token in tokens(text or "") if token not in _PLACE_SKIP and not token.isdigit()]


def _geo_variable_text(text: str) -> bool:
    """A municipality or region list. Sex and age on the same table are not places."""
    from grund_index.textutil import fold, tokens

    folded = fold(text)
    if any(mark in folded for mark in ("sex", "kyn", "age", "aldur")):
        return False
    words = tokens(folded)
    if not words:
        return False
    head = words[0]
    if head in {"region", "regions"}:
        return True
    # "Landshlutar" and "Sveitarfélög" are the plural headings.
    return any(head.startswith(mark) for mark in ("municip", "sveitarfel", "landshlut", "landsvaed"))


def _place_phrases() -> tuple[tuple[str, ...], ...]:
    """Folded place names from the current municipality and region tables."""
    global _PLACE_CACHE
    if _PLACE_CACHE is not None:
        return _PLACE_CACHE
    import gzip
    import json
    import os
    from pathlib import Path

    found: set[tuple[str, ...]] = set()
    candidates = []
    raw = os.environ.get("GRUND_INDEX", "").strip()
    if raw:
        candidates.append(Path(raw) / "tables.jsonl.gz")
    candidates.append(Path(__file__).resolve().parents[2] / "data" / "index" / "tables.jsonl.gz")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        _PLACE_CACHE = ()
        return _PLACE_CACHE
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            table_id = str(row.get("id") or "").replace(".px", "")
            if table_id not in _PLACE_TABLES:
                continue
            for variable in row.get("variables") or []:
                if not _geo_variable_text(str(variable.get("text") or "")):
                    continue
                for item in variable.get("values") or []:
                    if not (isinstance(item, (list, tuple)) and len(item) >= 2):
                        continue
                    phrase = tuple(_content_tokens(str(item[1])))
                    if not phrase or len(phrase) > 4:
                        continue
                    if len(phrase) == 1 and len(phrase[0]) < 4:
                        continue
                    found.add(phrase)
    _PLACE_CACHE = tuple(sorted(found, key=lambda item: (-len(item), item)))
    return _PLACE_CACHE


def _phrase_named(phrase: tuple[str, ...], question_tokens: list[str]) -> bool:
    width = len(phrase)
    if width and width <= len(question_tokens):
        for start in range(len(question_tokens) - width + 1):
            if all(
                _place_token(question_tokens[start + offset], phrase[offset])
                for offset in range(width)
            ):
                return True
    # "Sveitarfélagið Árborg" is the place Árborg.
    if phrase and phrase[0] in _PLACE_GENERIC:
        for token in phrase[1:]:
            if len(token) < 6 or token in _PLACE_GENERIC:
                continue
            if any(_place_token(question_token, token) for question_token in question_tokens):
                return True
    return False


def _contained(phrase: tuple[str, ...], other: tuple[str, ...]) -> bool:
    if len(phrase) >= len(other):
        return False
    width = len(phrase)
    return any(other[start : start + width] == phrase for start in range(len(other) - width + 1))


def named_places(question: str) -> list[tuple[str, ...]]:
    """Place names the question writes, longest first."""
    if not enabled() or not question:
        return []
    question_tokens = _content_tokens(question)
    found = [phrase for phrase in _place_phrases() if _phrase_named(phrase, question_tokens)]
    return [phrase for phrase in found if not any(_contained(phrase, other) for other in found)]


def _label_is_phrase(label_tokens: list[str], phrase: tuple[str, ...]) -> bool:
    """The value is this place, not a longer label that merely contains it."""
    if len(label_tokens) != len(phrase):
        return False
    return all(
        label_tokens[offset] == phrase[offset] or _place_token(label_tokens[offset], phrase[offset])
        for offset in range(len(phrase))
    )


def place_selection(
    question: str,
    variables: list,
    operation: str = "level",
) -> dict[str, list[str]] | None:
    """The place filter for this table.

    An empty dict means the question names no place, or a derived question
    whose place rows the binder already chooses. None means the question
    names a place this table does not publish, so the hybrid path abstains.
    """
    if not enabled():
        return {}
    named = named_places(question)
    if not named:
        return {}
    hits: list[tuple[int, int, str, str, tuple[str, ...]]] = []
    for variable in variables or []:
        if variable.get("time"):
            continue
        for code, label in variable.get("values") or []:
            label_tokens = _content_tokens(str(label))
            if not label_tokens:
                continue
            for phrase in named:
                if _label_is_phrase(label_tokens, phrase):
                    hits.append(
                        (
                            len(phrase),
                            sum(len(token) for token in phrase),
                            str(variable.get("code")),
                            str(code),
                            phrase,
                        )
                    )
                    break
    if not hits:
        return None
    present = {hit[4] for hit in hits}
    if str(operation or "level") in _DERIVED_OPS:
        if any(phrase not in present for phrase in named):
            return None
        return {}
    hits.sort(reverse=True)
    _length, _chars, variable_code, value_code, _phrase = hits[0]
    return {variable_code: [value_code]}


def place_missing(question: str, variables: list) -> bool:
    """A place named in the question is not a value this table publishes."""
    if not enabled():
        return False
    return place_selection(question, variables) is None
