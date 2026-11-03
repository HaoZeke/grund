"""A sibling table that lacks the question's measure does not answer it.

The catalogue index is the comparison. The measure is the question's
content words, with hyphens folded and a short grammatical stem. Another
table is used only when it is the single table that covers more of that
measure than the table already chosen. Several better tables, or a cell
whose unit contradicts the question, are a refusal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from grund_index.textutil import MIN_TOKEN_LEN, fold, near_token

_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "januar", "februar", "mars",
    "mai", "juni", "juli", "agust", "oktober", "desember",
}
_STOP = {
    "what", "which", "were", "was", "from", "with", "that", "this", "their",
    "there", "about", "between", "across", "during", "according", "many",
    "much", "does", "did", "have", "been", "into", "over", "than", "then",
    "them", "they", "your", "iceland", "island", "islandi", "islande",
    "people", "person", "year", "years", "total", "figure", "figures",
    "hvad", "hver", "hvert", "hversu", "voru", "sem", "eftir", "fyrir",
    "arid", "the", "and", "for", "how", "not", "its", "are", "all", "was",
    "were", "been", "being", "this", "that", "hve", "hvad", "med", "vid",
    "landsins", "landinu", "whole", "country",
}
_LEADING = {"changes", "change", "the", "and", "for", "quarterly", "annual", "monthly"}
_ENDINGS = (
    "inum", "unum", "anna", "urnar", "arnar", "inni", "ing",
    "um", "ar", "ir", "ur", "inn", "an", "num", "es", "i", "a", "u", "s",
)


def _stem(token: str) -> str:
    token = fold(token).replace("-", " ").strip()
    token = token.replace("dependancy", "dependency")
    if len(token) >= 5:
        for suffix in _ENDINGS:
            if token.endswith(suffix) and len(token) - len(suffix) >= 5:
                token = token[: -len(suffix)]
                break
    # vísitala / vísitölu, not "visitors"
    if token.startswith("indic") or token in {"index", "indice", "indices"}:
        return "index"
    if token.startswith("visital") or token.startswith("visitol"):
        return "index"
    if token in {"price", "prices"} or token in {"verd", "verds"} or token.startswith("verdlag"):
        return "price"
    if token.startswith("innflut") or token in {"import", "imports"}:
        return "import"
    if token.startswith("utflut") or token in {"export", "exports"}:
        return "export"
    if token in {"average", "averages"} or token.startswith("medal"):
        return "average"
    if token.startswith("maedr") or token in {"modur", "modir", "mother", "mothers"}:
        return "mother"
    if token in {"born", "birth", "births"} or token.startswith("faed"):
        return "birth"
    if token == "live" or token.startswith("lifand"):
        return "live"
    return token


_WEIGHT = {"vog", "vogir", "vogum", "voga", "vaegi", "weight", "weights"}


def _tokens(text: str) -> list[str]:
    found = []
    for raw in re.findall(r"[a-z0-9]+", fold(text or "").replace("-", " ")):
        if raw == "cpi":
            found.extend(["consumer", "price", "index"])
            continue
        if raw in _WEIGHT:
            found.append("weight")
            continue
        if raw.isdigit() or len(raw) < 4 or raw in _STOP or raw in _MONTHS:
            continue
        # "Fastskattavísitala" is "fastskatta" plus "vísitala".
        compound = re.match(r"^([a-z]{4,}?)(visital|visitol)", raw)
        if compound:
            head = _stem(compound.group(1))
            if len(head) >= 4 and head not in _STOP:
                found.append(head)
            found.append("index")
            continue
        stem = _stem(raw)
        if len(stem) < 4 or stem in _STOP or stem in _MONTHS:
            continue
        found.append(stem)
    return found


def measure_tokens(question: str) -> list[str]:
    """Content stems, in order, hyphens already folded."""
    seen: list[str] = []
    for token in _tokens(question):
        if token not in seen:
            seen.append(token)
    return seen


def _covers(stem: str, forms: set[str]) -> bool:
    if stem in forms:
        return True
    if len(stem) < 6:
        return False
    for other in forms:
        if abs(len(other) - len(stem)) <= 3 and (other.startswith(stem) or stem.startswith(other)):
            return True
        if len(stem) >= 8 and len(other) >= 8 and near_token(stem, other):
            return True
    return False


def _title_stems(title: str) -> list[str]:
    stems = list(_tokens(re.sub(r"\d+", " ", title or "")))
    while stems and stems[0] in _LEADING:
        stems.pop(0)
    return stems


@dataclass(frozen=True)
class _Edition:
    lang: str
    stems: tuple
    head: tuple
    tail: tuple
    dated: bool
    # Variable code to the stems of its name and its value labels.
    variables: tuple
    words: str = ""
    printed: tuple | None = None


@dataclass(frozen=True)
class _Profile:
    stem: str
    forms: set[str]
    titles: tuple
    # Title, variable names and value labels. The folder path is left out:
    # sibling tables share it, so it is not the measure.
    body: frozenset
    span: tuple | None = None
    numbers: frozenset = frozenset()
    editions: tuple = ()
    names: frozenset = frozenset()


def _split_title(title: str) -> tuple[tuple, tuple]:
    """Stems before "by"/"eftir" and after it. The tail is the breakdown."""
    text = re.sub(r"\d+", " ", fold(title or "").replace("-", " "))
    parts = re.split(r"\b(?:by|eftir)\b", text, maxsplit=1)
    head = tuple(_title_stems(parts[0]))
    if len(parts) == 1:
        return head, ()
    # "by sex and age" is a breakdown even though its words are short.
    short = {word for word in re.findall(r"[a-z]+", parts[1]) if len(word) >= MIN_TOKEN_LEN} - {"and", "the", "from", "fra"}
    return head, tuple(sorted(set(_tokens(parts[1])) | short))


def _printed(title: str) -> tuple | None:
    """The year range a title prints: "1957-1990", "1998-", "from 2015"."""
    text = fold(title or "")
    found = re.search(r"((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})", text)
    if found:
        return (int(found.group(1)), int(found.group(2)))
    found = re.search(r"((?:19|20)\d{2})\s*-\s*$", text) or re.search(r"\b(?:from|fra)\s+((?:19|20)\d{2})\b", text)
    if found:
        return (int(found.group(1)), 9999)
    return None


def _words(title: str) -> str:
    return " ".join(re.findall(r"[a-z]+", re.sub(r"\d+", " ", fold(title or ""))))


def _span(table) -> tuple | None:
    years: set[int] = set()
    for edition in table.editions.values():
        years |= edition.years()
        if not years:
            for variable in edition.variables:
                if re.search(r"\b(year|ar|time|timi)\b", fold(variable.text or "")):
                    for code, text in variable.values:
                        years |= {int(found) for found in re.findall(r"(?:19|20)\d{2}", f"{code} {text}")}
    if not years:
        return None
    return (min(years), max(years))


_CACHE: dict[int, list[_Profile]] = {}


def _profiles(catalogue) -> list[_Profile]:
    key = id(catalogue)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    built: list[_Profile] = []
    for table in catalogue.tables:
        text_parts: list[str] = []
        body_parts: list[str] = []
        title_parts: list[str] = []
        number_parts: list[str] = []
        editions: list[_Edition] = []
        name_parts: list[str] = []
        for edition in table.editions.values():
            name_parts.extend(variable.text for variable in edition.variables)
            title_parts.append(edition.title)
            text_parts.append(edition.title)
            body_parts.append(edition.title)
            number_parts.append(edition.title)
            text_parts.extend(edition.path_texts or [])
            variables = []
            for variable in edition.variables:
                text_parts.append(variable.text)
                body_parts.append(variable.text)
                if variable.time:
                    continue
                labels = [str(label or "") for _code, label in variable.values]
                text_parts.extend(labels)
                body_parts.extend(labels)
                number_parts.extend(labels)
                variables.append((variable.code, frozenset(_tokens(" ".join([variable.text, *labels])))))
            head, tail = _split_title(edition.title)
            editions.append(
                _Edition(
                    edition.lang,
                    tuple(_title_stems(edition.title)),
                    head,
                    tail,
                    bool(re.search(r"(?:19|20)\d{2}", edition.title or "")),
                    tuple(variables),
                    _words(edition.title),
                    _printed(edition.title),
                )
            )
        forms = set(_tokens(" ".join(text_parts)))
        titles = tuple(_title_stems(part) for part in title_parts)
        built.append(
            _Profile(
                table.id.removesuffix(".px"),
                forms,
                titles,
                frozenset(_tokens(" ".join(body_parts))),
                _span(table),
                frozenset(int(found) for found in re.findall(r"(?:19|20)\d{2}", " ".join(number_parts))),
                tuple(editions),
                frozenset(_tokens(" ".join(name_parts))),
            )
        )
    _CACHE[key] = built
    return built


def _phrase_hits(tokens: list[str], profiles: list[_Profile]) -> set[str]:
    """Tables whose title starts with the longest question phrase any title starts with."""
    best: set[str] = set()
    for length in range(min(4, len(tokens)), 1, -1):
        phrases = [tokens[i : i + length] for i in range(len(tokens) - length + 1)]
        found: set[str] = set()
        for phrase in phrases:
            for profile in profiles:
                if any(title[:length] == phrase for title in profile.titles):
                    found.add(profile.stem)
        if found:
            return found
    return best


_WEIGHT_WORD = r"\b(weights?|vog|vogir|vogum|vaegi)\b"


def _asked_unit(question: str) -> str | None:
    text = fold(question or "").replace("-", " ")
    if re.search(r"\b(points?|stig)\b", text):
        return None
    if re.search(_WEIGHT_WORD, text):
        return "weight"
    if re.search(r"\b(index|indices|indice|visital\w*|visitol\w*)\b", text):
        return "index"
    if re.search(r"\b(ratio|hlutfall)\b", text) or "framfaersl" in text:
        return "ratio"
    if re.search(r"\b(percent|percentage|prosent)\b", text):
        return "percent"
    if re.search(r"\b(how many|hve marg|hversu marg|fjoldi)\b", text):
        return "count"
    return None


def cell_labels(result: dict) -> list[str]:
    """The value labels of the cells the answer states."""
    labels: list[str] = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        if isinstance(cell, dict):
            raw = cell.get("labels") or {}
            if isinstance(raw, dict):
                labels.extend(str(value) for value in raw.values())
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                raw = cell.get("labels") or {}
                if isinstance(raw, dict):
                    labels.extend(str(value) for value in raw.values())
    return labels


def _cell_unit(result: dict) -> str | None:
    blob = fold(" ".join(cell_labels(result))).replace("-", " ")
    if not blob:
        return None
    if re.search(_WEIGHT_WORD, blob):
        return "weight"
    if re.search(r"\b(index|indices|indice|visital\w*|visitol\w*)\b", blob):
        return "index"
    if re.search(r"\b(ratio|hlutfall|percent|percentage|prosent|rate)\b", blob) or "%" in blob:
        return "ratio" if "ratio" in blob or "hlutfall" in blob else "percent"
    if re.search(r"\b(number|fjoldi|population|mannfjold|persons|people)\b", blob):
        return "count"
    return None


_MONTH_WORD = (
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"januar|februar|mars|april|mai|juni|juli|agust|september|oktober|november|desember)\b"
)
# A stock on a date is a yearly figure: "1 January 2026", "1. janúar", "end of 2024".
_STOCK_DATE = r"\b(?:1\.?|31\.?|first of)\s+(?:january|januar|december|desember)\b"


def _frequency_conflict(question: str, result: dict) -> bool:
    """A month asked for is not answered by a year, nor a quarter by a year."""
    text = re.sub(_STOCK_DATE, " ", fold(question or ""))
    blob = " ".join(cell_labels(result))
    folded = fold(blob)
    if not re.search(r"(?:19|20)\d{2}", blob):
        return False
    has_month = bool(re.search(r"(?:19|20)\d{2}M\d{2}", blob)) or bool(re.search(_MONTH_WORD, folded))
    has_quarter = bool(re.search(r"(?:19|20)\d{2}\s*(?:Q|Á|A)\d", blob))
    if re.search(_MONTH_WORD, text) and not has_month and not has_quarter:
        return True
    if re.search(r"\b(quarter|arsfjordung\w*)\b|(?:19|20)\d{2}\s*q\d", text) and not has_quarter and not has_month:
        return True
    return False


def unit_conflict(question: str, result: dict) -> bool:
    """A count is not an index, and an index is not a headcount."""
    if str(result.get("operation") or "") in {"share", "difference", "yoy_pct"}:
        return False
    if _frequency_conflict(question, result):
        return True
    asked = _asked_unit(question)
    cell = _cell_unit(result)
    if asked is None or cell is None or asked == cell:
        return False
    if {asked, cell} <= {"ratio", "percent"}:
        return False
    return True


@dataclass(frozen=True)
class Decision:
    action: str
    table: str = ""


def _title_df(profiles: list[_Profile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for profile in profiles:
        for title in profile.titles:
            for token in set(title):
                counts[token] = counts.get(token, 0) + 1
    return counts


def _contains(phrase: list[str], title: list[str]) -> bool:
    if len(phrase) > len(title):
        return False
    for start in range(len(title) - len(phrase) + 1):
        if title[start : start + len(phrase)] == phrase:
            return True
    return False


def _starts(phrase: list[str], title: list[str]) -> bool:
    return len(phrase) <= len(title) and title[: len(phrase)] == phrase


def _title_set(profile: _Profile) -> set[str]:
    return {token for title in profile.titles for token in title}


def _has_in_any(phrase: list[str], profile: _Profile) -> bool:
    return any(_contains(phrase, title) for title in profile.titles)


def _starts_any(phrase: list[str], profile: _Profile) -> bool:
    return any(_starts(phrase, title) for title in profile.titles)


# Not the statistic being named. Ordinals, comparison, and a sex or a
# place are categories. A residence verb is not a measure either.
_NOT_MEASURE = {
    "second", "third", "fourth", "quarter", "monthly", "annual",
    "percent", "percentage", "rise", "rose", "level", "point", "points",
    "children", "child", "persons", "person",
    "reykjavik", "kopavog", "akureyr", "hafnarfj",
    "more", "fleir", "fewer", "less",
    "lived", "bjugg",
    "women", "woman", "female", "male", "konur", "kona", "karlar", "karl",
    "arsfjordung", "manud",
}

# "the second quarter" and "öðrum ársfjórðungi" are a period. "other
# accommodation" and "öðrum gististöðum" are a measure.
_ORDINAL_PERIOD = re.compile(
    r"\b(?:first|second|third|fourth|fyrsta|fyrsti|odrum|annar|annan|thridja|fjorda)\s+"
    r"(?:quarter|half|arsfjordung\w*|arshelming\w*)"
)


def _measure_list(question: str, df: dict[str, int]) -> list[str]:
    question = _ORDINAL_PERIOD.sub(" ", fold(question or "").replace("-", " "))
    tokens = [token for token in measure_tokens(question) if token not in _NOT_MEASURE]
    tokens = [token for token in tokens if not token.startswith(("reykjav", "kopavog", "akureyr", "hafnarf", "kven"))]
    tokens = [token for token in tokens if not any(other.startswith(token) and other != token for other in tokens)]
    return [token for token in tokens if df.get(token, 0) >= 1]


def measure_words(question: str) -> list[str]:
    """The first clause's measure stems, including words no title carries."""
    clause = _ORDINAL_PERIOD.sub(" ", _clauses(question)[0])
    tokens = [token for token in measure_tokens(clause) if token not in _NOT_MEASURE]
    return [token for token in tokens if not token.startswith(("reykjav", "kopavog", "akureyr", "hafnarf", "kven"))]


def asked_years(question: str) -> set[int]:
    return _years(question, _base_years(question))


def covers(catalogue, stem: str, years: set[int]) -> bool:
    profile = next((item for item in _profiles(catalogue) if item.stem == stem), None)
    return profile is not None and _covers_years(profile, years)


def _clauses(question: str) -> list[str]:
    """A conjunction is two questions. The measure is read from one of them."""
    text = fold(question or "").replace("-", " ")
    parts = [part.strip() for part in re.split(r"\s+(?:and|og)\s+", text) if part.strip()]
    return parts or [text]


def decide(question: str, chosen_id: str, catalogue, labels: list[str] | None = None) -> Decision:
    """``keep``, ``refuse``, or ``switch`` to ``table``.

    A share is computed from counts, so it is not sent to another table.
    Another table is used only when it is the one table that carries the
    measure phrase. A second clause in the same question does not count.
    """
    text = fold(question or "").replace("-", " ")
    if re.search(r"\b(percent|percentage|hlutfall|hlutdeild)\b", text) and re.search(
        r"\b(women|men|konur|karlar|female|male)\b", text
    ):
        return Decision("keep")
    profiles = _profiles(catalogue)
    df = _title_df(profiles)
    # The table already chosen answers the first measure. A later clause
    # names a second statistic and is not a reason to leave that table.
    clause = _clauses(question)[0]
    bases = _base_years(question)
    years = _years(question, bases)
    chosen = str(chosen_id or "").removesuffix(".px")
    chosen_profile = next((profile for profile in profiles if profile.stem == chosen), None)
    if bases and chosen_profile is not None and not bases <= chosen_profile.numbers:
        return Decision("refuse")
    decision = _decide_tokens(_measure_list(clause, df), chosen_id, profiles, df, years, labels)
    if decision.action != "keep" or chosen_profile is None:
        return decision
    if _split_series(chosen_profile, profiles, years):
        return Decision("refuse")
    return _breakdown_sibling(question, chosen_profile, profiles, years)


def _base_years(text: str) -> set[int]:
    """1988 in "base 1988", "1988=100", "on the 1988 base", "grunnur 1988"."""
    text = fold(text or "")
    found = set()
    for pattern in (
        r"\b(?:base|basis|grunn\w*)\s*(?:year\s*)?((?:19|20)\d{2})\b",
        r"\b((?:19|20)\d{2})\s*=\s*100\b",
        r"\b((?:19|20)\d{2})\s+(?:base|grunn\w*)\b",
    ):
        found |= {int(match) for match in re.findall(pattern, text)}
    return found


def _years(text: str, bases: set[int]) -> set[int]:
    return {int(match) for match in re.findall(r"\b((?:19|20)\d{2})\b", fold(text or ""))} - bases


def _covers_years(profile: _Profile, years: set[int]) -> bool:
    if not years or profile.span is None:
        return True
    low, high = profile.span
    return all(low <= year <= high for year in years)


def _split_series(chosen: _Profile, profiles: list[_Profile], years: set[int]) -> bool:
    """One series cut in two at a year that both parts print.

    The titles are the same apart from the years, and the two printed
    ranges meet only at the year asked. Both tables carry that year, often
    with different figures, so neither is the answer.
    """
    if len(years) != 1:
        return False
    year = next(iter(years))
    for edition in chosen.editions:
        if edition.printed is None or not edition.words:
            continue
        for profile in profiles:
            if profile.stem == chosen.stem:
                continue
            for other in profile.editions:
                if other.lang != edition.lang or other.printed is None or other.words != edition.words:
                    continue
                low = max(edition.printed[0], other.printed[0])
                high = min(edition.printed[1], other.printed[1])
                if low == high == year:
                    return True
    return False


def _family_key(stem: str) -> tuple[str, int] | None:
    found = re.match(r"^([A-Z]+)(\d+)", stem)
    return (found.group(1), int(found.group(2))) if found else None


_NOT_A_BREAKDOWN = {"alls", "samtals", "total", "heild", "whole"}


def _names(tokens: set[str], stems) -> bool:
    return any(_family(token, stem) for token in tokens for stem in stems if stem not in _NOT_A_BREAKDOWN)


def _breakdown_sibling(clause: str, chosen: _Profile, profiles: list[_Profile], years: set[int]) -> Decision:
    """Tables that differ only in the breakdown they are cut by.

    The same heading, the same variables but one, and the same years.
    The breakdown the question names wins. When it names none of them,
    the first table of the family is the headline breakdown. Any other
    table is a guess between equals, so the answer is refused.
    """
    asked = {token for token in measure_tokens(clause) if token not in _NOT_A_BREAKDOWN}
    found: list[tuple[_Profile, set, set]] = []
    for edition in chosen.editions:
        if len(edition.head) < 2 or not edition.tail:
            continue
        mine = dict(edition.variables)
        siblings: list[tuple[_Profile, set]] = []
        for profile in profiles:
            if profile.stem == chosen.stem or not _covers_years(profile, years):
                continue
            for other in profile.editions:
                if other.lang != edition.lang or other.head != edition.head or not other.tail:
                    continue
                if other.tail == edition.tail:
                    continue
                theirs = dict(other.variables)
                only_mine = set(mine) - set(theirs)
                only_theirs = set(theirs) - set(mine)
                if len(only_mine) != 1 or len(only_theirs) != 1:
                    continue
                own = set(edition.tail) | set(mine[next(iter(only_mine))])
                their = set(other.tail) | set(theirs[next(iter(only_theirs))])
                siblings.append((profile, own, their))
        found.extend(siblings)
    if not found:
        return Decision("keep")
    tails = {stem for edition in chosen.editions for stem in edition.tail}
    if _names(asked, tails) or any(_names(asked, own) for _profile, own, _their in found):
        return Decision("keep")
    named = {profile.stem for profile, _own, their in found if _names(asked, their)}
    if len(named) == 1:
        return Decision("switch", next(iter(named)))
    if named:
        return Decision("refuse")
    mine = _family_key(chosen.stem)
    family = [_family_key(profile.stem) for profile, _own, _their in found]
    family = [key for key in family if key is not None and mine is not None and key[0] == mine[0]]
    if mine is None or not family or all(mine[1] < key[1] for key in family):
        return Decision("keep")
    return Decision("refuse")


def _family(left: str, right: str) -> bool:
    """The same word, including leysi/laus, but not two different compounds."""
    if left == right:
        return True
    if len(left) >= 6 and len(right) >= 6 and abs(len(left) - len(right)) <= 3 and (
        left.startswith(right) or right.startswith(left)
    ):
        return True
    shared = 0
    for a, b in zip(left, right):
        if a != b:
            break
        shared += 1
    if shared >= 8 and len(left) - shared <= 4 and len(right) - shared <= 4:
        return True
    if len(left) >= 8 and len(right) >= 8 and near_token(left, right):
        return True
    return False


def _title_stems_set(profile: _Profile) -> set[str]:
    return {token for title in profile.titles for token in title}


def _in_stems(token: str, stems: set[str]) -> bool:
    if any(_family(token, stem) for stem in stems):
        return True
    # "Launavísitala" is one word in the question and "Launa-vísitala" in a title.
    for ending in ("visital", "visitol"):
        if token.endswith(ending) and len(token) > len(ending) + 3:
            head = token[: -len(ending)]
            if head in stems and "index" in stems:
                return True
    return False


def _title_hits(tokens: list[str], profile: _Profile) -> set[str]:
    """Tokens that one edition title carries together. Languages are not mixed."""
    found: set[str] = set()
    for title in profile.titles:
        stems = set(title)
        hits = {token for token in tokens if _in_stems(token, stems)}
        if len(hits) > len(found):
            found = hits
    return found


def _covers_token(token: str, profile: _Profile) -> bool:
    """Title, variable or value label. A shared folder path does not count."""
    if token in profile.body:
        return True
    return bool(_title_hits([token], profile))


def _decide_tokens(
    tokens: list[str],
    chosen_id: str,
    profiles: list[_Profile],
    df: dict[str, int],
    years: set[int] | None = None,
    labels: list[str] | None = None,
) -> Decision:
    """Switch only when one title carries a strictly wider measure.

    The chosen table may carry a word in its variables or value labels.
    Another table is better only when a single title of its own contains
    every such word and at least one more. One winner switches. Several
    refuse. A lone short word is not a phrase.
    """
    del df
    if not tokens:
        return Decision("keep")
    chosen = str(chosen_id or "").removesuffix(".px")
    chosen_profile = next((profile for profile in profiles if profile.stem == chosen), None)
    if labels is None or chosen_profile is None:
        chosen_have = {token for token in tokens if chosen_profile is not None and _covers_token(token, chosen_profile)}
    else:
        # A value label only carries the measure when it is on the cell stated.
        stated = set(_tokens(" ".join(labels))) | set(chosen_profile.names)
        chosen_have = {
            token for token in tokens if token in stated or _title_hits([token], chosen_profile)
        }
    better: list[tuple[_Profile, set[str]]] = []
    for profile in profiles:
        if profile.stem == chosen or not _covers_years(profile, years or set()):
            continue
        hits = _title_hits(tokens, profile)
        if not chosen_have < hits:
            continue
        if len(hits) == 1 and len(next(iter(hits))) < 12:
            continue
        better.append((profile, hits))
    if len(better) > 1:
        # A title led by a word the question does not use ("Harmonised
        # index ...") is a different measure from one led by an asked word.
        widest = max(len(hits) for _profile, hits in better)
        better = [(profile, hits) for profile, hits in better if len(hits) == widest]
        led = [
            (profile, hits)
            for profile, hits in better
            if all(title and title[0] in tokens for title in profile.titles)
        ]
        if len(led) == 1:
            better = led
    if len(better) == 1:
        return Decision("switch", better[0][0].stem)
    if len(better) > 1:
        return Decision("refuse")
    if (
        chosen_profile is not None
        and chosen_have == set(tokens)
        and len(tokens) >= 2
        and not _starts_any(tokens, chosen_profile)
    ):
        starters = [
            profile
            for profile in profiles
            if profile.stem != chosen
            and _covers_years(profile, years or set())
            and _starts_any(tokens, profile)
            and _title_hits(tokens, profile) == set(tokens)
        ]
        if len(starters) == 1:
            return Decision("switch", starters[0].stem)
    return Decision("keep")
