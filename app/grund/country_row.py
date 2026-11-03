"""A country the question names, and the codelist row that carries it.

"How many Indians are in Iceland" names a row of a country codelist. A
cell that does not carry that row (the population total) is not the
answer, and a total is never a stand-in for a country.

Everything here is read from the catalogue:

* A country codelist is a classification variable that lists Iceland as
  one of its rows beside a separate total. Every table of this catalogue
  is about Iceland, so a list where Iceland is only one row is a list of
  countries (citizenship, country of birth, trading partner). A list most
  of whose rows are rows of those lists is a country list too. Iceland
  itself is the catalogue's scope and is never read as a country row.
* Table titles name measures and the variables they are cut by, not
  countries. A word the catalogue writes in a title ("index", "final",
  "children") is not read as a country, and a row whose label is a title
  word ("Other") is not a country either.
* A question word names a row when it is the row's label in either
  language ("India", "Indlandi"). It names it as a derived word
  ("Indian", "indverskir", "Polish") when it starts with the stem the
  row's English and Icelandic labels share ("Ind-ia" / "Ind-land",
  "Pol-and" / "Pól-land"). A stem only two labels agree on is evidence
  of the name; a stem one label has alone is an accident of spelling.
  Failing both, a word names the row it shares the longest start with,
  when that start is longer than it shares with any other row and with
  any other word the catalogue writes outside its country codelists
  ("Filipino" / "Filippseyjar", but not "nights" / "Nigeria"). A word
  the catalogue translates in another codelist ("German" / "Þýska")
  names the country its translation names.
* A codelist whose labels write their own letter codes, and whose codes
  extend the country codes ("DKK" for "DK", "PLN" for "PL"), writes each
  country's derived word in its label ("DKK - Danish Krone"): the word no
  other row of that list writes. A
  question word that is that word, or an inflection of its start
  ("Dan-es", "Pol-es"), names the country when the start is also where
  the derived word and the country's own label agree ("Dan-ish" /
  "Dan-mörk", "Pol-ish" / "Pol-and").
* A title that writes Iceland beside other places ("Ísland, Svíþjóð og
  Danmörk") lists countries, so its words do not make a row a title word.
* The tables that can answer are the ones measuring what the stated cell
  measures. A PxWeb title is the measure followed by the variables it is
  cut by; the measure head is the title up to the first word of one of the
  table's own variables ("Population", "Mannfjöldi").
* Two codelists can carry the country (citizenship and country of
  birth). The question picks one with a word that only that codelist and
  the tables carrying it alone use ("born", "citizens"). A derived word
  with no such word picks the codelist whose own non-country rows write
  Iceland as a derived word ("Icelandic citizenship", "Íslenskir
  ríkisborgarar"): that codelist is the nationality.
* Among the tables of that codelist, the one with the fewest rows in its
  other classification variables is the least cut, and every other
  variable is set to its total.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace

from grund_index.textutil import MIN_TOKEN_LEN, fold, tokens

from grund import row_guard
from grund.bind import aggregate_label, is_total

# Its endings, and the neuter adjective ending (pólsk-t, íslensk-t).
_FORMS = (*row_guard._ENDINGS, "t")


@dataclass(frozen=True)
class CountryDecision:
    action: str
    table: str = ""
    variable: str = ""
    code: str = ""
    label: str = ""
    detail: str = ""


@dataclass
class _Row:
    code: str
    labels: dict
    singles: tuple
    stem: str


@dataclass
class _Lists:
    titles: set
    title_sorted: list
    words_sorted: list
    bridges: dict
    lists: dict
    variables: dict
    concept_cache: dict = field(default_factory=dict)
    demonym_cache: dict = field(default_factory=dict)
    scope_stems: set = field(default_factory=set)
    derived: dict = field(default_factory=dict)


_CACHE: dict[int, _Lists] = {}


def enabled() -> bool:
    return row_guard.enabled()


def _label_words(label: str) -> list[str]:
    return [word for word in tokens(label) if not any(ch.isdigit() for ch in word) and word not in row_guard._GLUE]


def _is_scope(label: str) -> bool:
    return fold(label).strip() in row_guard._SCOPE


def _aggregate(label: str) -> bool:
    return is_total(label) or aggregate_label(label)


def _country_list(variable) -> bool:
    if not row_guard._classification(variable):
        return False
    labels = [str(label or code) for code, label in variable.values]
    if not any(_is_scope(label) for label in labels):
        return False
    return any(_aggregate(label) for label in labels if not _is_scope(label))


def _prefix(left: str, right: str) -> int:
    size = 0
    for a, b in zip(left, right):
        if a != b:
            break
        size += 1
    return size


def _title_word(word: str, lists: _Lists) -> bool:
    return word in lists.titles or row_guard._root(word) in lists.titles


def _inflection(other: str, root: str) -> bool:
    if row_guard._root(other) == root or other == root:
        return True
    return other.startswith(root) and other[len(root):] in _FORMS


def _rivalled(word: str, size: int, ordered: list[str], singles: tuple, *, ties: bool) -> bool:
    """Another word of a sorted list agrees with the word on its first `size`
    letters and is nearer the word than the country label is: "night" for
    "nights" / "Nigeria", "polishing" for "polish" / "Poland". A word nearer
    the label ("filippseysk") is the country's own, and an inflection of the
    word itself ("indversk" for "indverskir") is the same word. With `ties`,
    a word as near the label as the word is also a rival."""
    root = row_guard._root(word)
    start = bisect.bisect_left(ordered, word[:size])
    for index in range(start, len(ordered)):
        other = ordered[index]
        if not other.startswith(word[:size]):
            break
        if other == word or _inflection(other, root):
            continue
        near = _prefix(other, word)
        label = max((_prefix(other, single) for single in singles), default=0)
        if near > label or (ties and near == label):
            return True
    return False


def _lists(catalogue) -> _Lists:
    found = _CACHE.get(id(catalogue))
    if found is not None:
        return found
    titles: set[str] = set()
    measure_titles: set[str] = set()
    for table in catalogue.tables:
        for edition in table.editions.values():
            words = tokens(edition.title)
            lists_places = any(word in row_guard._SCOPE for word in words)
            for word in words:
                titles.add(word)
                titles.add(row_guard._root(word))
                if not lists_places:
                    measure_titles.update((word, row_guard._root(word)))
    keys: set[tuple[str, str]] = set()
    variables: dict = {}
    for table in catalogue.tables:
        for lang, edition in table.editions.items():
            variables[(table.id, lang)] = [variable.code for variable in edition.variables]
            for variable in edition.variables:
                if _country_list(variable):
                    keys.add((table.id, variable.code))
    # A list whose rows are mostly countries is a country list without
    # Iceland in it ("Population born abroad", fishing nations).
    known = {
        fold(str(label or "")).strip()
        for table_id, code in keys
        for edition in catalogue.by_id[table_id].editions.values()
        if edition.variable(code) is not None
        for _value, label in edition.variable(code).values
    }
    for table in catalogue.tables:
        for edition in table.editions.values():
            for variable in edition.variables:
                if (table.id, variable.code) in keys or not row_guard._classification(variable):
                    continue
                rows = [fold(str(label or "")).strip() for _code, label in variable.values if not _aggregate(str(label or ""))]
                if rows and 2 * sum(row in known for row in rows) > len(rows):
                    keys.add((table.id, variable.code))
    words: set[str] = set()
    bridges: dict[str, set[str]] = {}
    for table in catalogue.tables:
        en = table.editions.get("en")
        isl = table.editions.get("is")
        for edition in table.editions.values():
            for variable in edition.variables:
                words.update(tokens(variable.text or ""))
                if variable.time or (table.id, variable.code) in keys:
                    continue
                for _code, label in variable.values:
                    words.update(tokens(str(label or "")))
        if en is None or isl is None:
            continue
        for variable in en.variables:
            other = isl.variable(variable.code)
            if variable.time or other is None or (table.id, variable.code) in keys:
                continue
            for value_code, label in variable.values:
                pair = (fold(str(label or "")).strip(), fold(other.label(value_code) or "").strip())
                if all(len(_label_words(side)) == 1 and " " not in side for side in pair) and pair[0] != pair[1]:
                    bridges.setdefault(pair[0], set()).add(pair[1])
                    bridges.setdefault(pair[1], set()).add(pair[0])
    lists: dict = {}
    for table_id, code in keys:
        table = catalogue.by_id[table_id]
        labels: dict[str, dict[str, str]] = {}
        for lang, edition in table.editions.items():
            variable = edition.variable(code)
            if variable is None:
                continue
            for value_code, label in variable.values:
                labels.setdefault(str(value_code), {})[lang] = str(label or value_code)
        rows = []
        for value_code, by_lang in labels.items():
            if any(_is_scope(label) or _aggregate(label) for label in by_lang.values()):
                continue
            singles = tuple(fold(label) for label in by_lang.values() if len(_label_words(label)) == 1 and " " not in label.strip())
            if any(row_guard._root(word) in measure_titles or word in measure_titles for word in singles):
                continue
            stem = ""
            if len(singles) == 2:
                stem = singles[0][: _prefix(singles[0], singles[1])]
            rows.append(_Row(value_code, by_lang, singles, stem if len(stem) >= MIN_TOKEN_LEN else ""))
        lists[(table_id, code)] = rows
    country_words = {single for rows in lists.values() for row in rows for single in row.singles}
    found = _Lists(titles, sorted(titles), sorted(words - country_words), bridges, lists, variables)
    found.derived = _derived_words(catalogue, keys, lists)
    for (table_id, code) in keys:
        for edition in catalogue.by_id[table_id].editions.values():
            for _value, label in edition.variable(code).values if edition.variable(code) else ():
                if _is_scope(str(label)):
                    found.scope_stems.add(fold(str(label)).strip())
    _CACHE[id(catalogue)] = found
    return found


def _derived_words(catalogue, keys: set, lists: dict) -> dict[str, set[str]]:
    """Derived word -> folded labels of the country it is written for."""
    countries: dict[str, set[str]] = {}
    for rows in lists.values():
        for row in rows:
            if row.code.isalpha():
                countries.setdefault(row.code, set()).update(row.singles)
    sizes = sorted({len(code) for code in countries})
    found: dict[str, set[str]] = {}
    for table in catalogue.tables:
        for edition in table.editions.values():
            for variable in edition.variables:
                if variable.time or (table.id, variable.code) in keys or not variable.values:
                    continue
                linked = []
                for code, label in variable.values:
                    code = str(code)
                    owner = next((code[:size] for size in sizes if size < len(code) and code.isalpha() and code[:size] in countries), None)
                    if owner is not None and fold(code) in tokens(str(label or "")):
                        linked.append((owner, {fold(word) for word in _label_words(str(label or "")) if fold(word) != fold(code)}))
                if 2 * len(linked) <= len(variable.values):
                    continue
                seen: dict[str, int] = {}
                for _owner, own in linked:
                    for word in own:
                        seen[word] = seen.get(word, 0) + 1
                for owner, own in linked:
                    for word in own:
                        if seen[word] == 1:
                            found.setdefault(word, set()).update(countries[owner])
    return found


def _by_derived(folded: str, rows: list[_Row], lists: _Lists) -> tuple[_Row, bool] | None:
    if folded in lists.titles:
        return None
    root = row_guard._root(folded)
    hits = set()
    for derived, labels in lists.derived.items():
        if not (derived.startswith(root) or _inflection(folded, derived)):
            continue
        for row in rows:
            for single in row.singles:
                if single not in labels:
                    continue
                agree = derived[: _prefix(derived, single)]
                if len(agree) >= MIN_TOKEN_LEN and folded.startswith(agree):
                    hits.add(row.code)
    if len(hits) != 1:
        return None
    code = next(iter(hits))
    return next(row for row in rows if row.code == code), True


def match_country(word: str, rows: list[_Row], lists: _Lists, bridge: bool = True) -> tuple[_Row, bool] | None:
    """The row a question word names, and whether it names it as a derived word."""
    hit = _match_country(word, rows, lists, bridge)
    if hit is None and bridge:
        hit = _by_derived(fold(word), rows, lists)
    return hit


def _match_country(word: str, rows: list[_Row], lists: _Lists, bridge: bool = True) -> tuple[_Row, bool] | None:
    folded = fold(word)
    named = [row for row in rows if any(_same_word(single, folded) for single in row.singles)]
    if len(named) == 1:
        return named[0], False
    if named or _title_word(folded, lists):
        return None
    stems = [(len(row.stem), row) for row in rows if row.stem and folded.startswith(row.stem)]
    if stems:
        # Both labels agree on the stem. A catalogue word that agrees with
        # the question word beyond it ("brauðmeti" for "brauð" / Brazil,
        # "framleiðsla" for "framfærsla" / France) says the word is that one.
        best = _unique_longest(stems)
        if best is not None:
            reach = max(_prefix(folded, single) for single in best[0].singles) + 1
            if not _rivalled(folded, reach, lists.words_sorted, best[0].singles, ties=False):
                return best
    else:
        # One label alone: a word as near as the country is enough to doubt it.
        shared = [(max((_prefix(folded, single) for single in row.singles), default=0), row) for row in rows]
        best = _unique_longest(shared)
        if best is not None:
            size = max(_prefix(folded, single) for single in best[0].singles)
            singles = best[0].singles
            if not any(_rivalled(folded, size, ordered, singles, ties=True) for ordered in (lists.title_sorted, lists.words_sorted)):
                return best
    if not bridge:
        return None
    # A word the catalogue translates in another codelist ("German" / "Þýska")
    # names the country its translation names.
    found = {
        hit[0].code: hit
        for other in lists.bridges.get(folded, set()) | lists.bridges.get(row_guard._root(folded), set())
        for hit in [match_country(other, rows, lists, bridge=False)]
        if hit is not None
    }
    if len(found) == 1:
        row, _derived = next(iter(found.values()))
        return row, True
    return None


def _unique_longest(scored: list[tuple[int, _Row]]) -> tuple[_Row, bool] | None:
    if not scored:
        return None
    longest = max(size for size, _row in scored)
    if longest < MIN_TOKEN_LEN:
        return None
    leaders = [row for size, row in scored if size == longest]
    if len(leaders) != 1:
        return None
    return leaders[0], True


def _same_word(label_word: str, asked: str) -> bool:
    return label_word == asked or row_guard._root(label_word) == row_guard._root(asked)


def _multi_named(rows: list[_Row], asked: list[str]) -> list[_Row]:
    """Rows of several words ("United States") whose words are all in the question."""
    found = []
    for row in rows:
        for label in row.labels.values():
            words = _label_words(label)
            if len(words) > 1 and all(any(_same_word(own, word) for word in asked) for own in words):
                found.append(row)
                break
    return found


def _head(edition) -> tuple:
    """The title up to the first word of one of the table's own variables."""
    names: list[str] = []
    for variable in edition.variables:
        names.extend(tokens(variable.text or ""))
    head = []
    for word in tokens(edition.title):
        if any(ch.isdigit() for ch in word):
            break
        if any(row_guard._same(name, word) for name in names):
            break
        if word in row_guard._GLUE:
            continue
        head.append(row_guard._root(word))
    return tuple(head)


def _have(edition, peer, result: dict) -> list[str]:
    have: list[str] = []
    for side in (edition, peer):
        if side is None:
            continue
        have.extend(row_guard._words(side.title))
        for variable in side.variables:
            have.extend(row_guard._words(variable.text or ""))
    for cell in _cells(result):
        for item in cell.get("labels") or []:
            if isinstance(item, dict):
                have.extend(row_guard._words(str(item.get("label") or "")))
                have.extend(row_guard._words(row_guard._peer_label(peer, str(item.get("variable")), str(item.get("code")))))
    return have


def _free_words(question: str, have: list[str]) -> list[str]:
    return [
        word for word in row_guard._words(question)
        if word not in row_guard._TOTAL_WORD and not row_guard._covered(word, have)
    ]


def mentions(question: str, lists: _Lists, have: list[str]) -> list[tuple[str, str]]:
    """(question word, English or first label) for each country the question names outside the stated cell."""
    words = _free_words(question, have)
    seen: dict[str, str] = {}
    for rows in lists.lists.values():
        for row in _multi_named(rows, words):
            key = " ".join(_label_words(row.labels.get("en") or next(iter(row.labels.values()))))
            seen.setdefault(key, row.labels.get("en") or next(iter(row.labels.values())))
        for word in words:
            if word in seen:
                continue
            hit = match_country(word, rows, lists)
            if hit is not None:
                seen[word] = hit[0].labels.get("en") or next(iter(hit[0].labels.values()))
    return list(seen.items())


def _row_for(word: str, rows: list[_Row], lists: _Lists, asked: list[str]) -> tuple[_Row, bool] | None:
    if " " in word:
        multi = [row for row in _multi_named(rows, asked) if " ".join(_label_words(row.labels.get("en") or "")) == word]
        return (multi[0], False) if len(multi) == 1 else None
    return match_country(word, rows, lists)


def _other_totals(edition, code: str) -> bool:
    for variable in edition.variables:
        if variable.code == code or not row_guard._classification(variable):
            continue
        if row_guard._total(row_guard._values(edition, variable)) is None:
            return False
    return True


def _concept_vocab(catalogue, lists: _Lists, concept: str, rivals: frozenset) -> set[str]:
    """Words the catalogue writes beside a codelist: its name, its non-country rows,
    and the rows of the tables that carry it and none of the rivals."""
    key = (concept, rivals)
    if key in lists.concept_cache:
        return lists.concept_cache[key]
    found: set[str] = set()
    for table in catalogue.tables:
        for lang, edition in table.editions.items():
            codes = set(lists.variables.get((table.id, lang), ()))
            if concept not in codes:
                continue
            alone = not (codes & rivals)
            for variable in edition.variables:
                if variable.time:
                    continue
                country = (table.id, variable.code) in lists.lists
                if variable.code == concept:
                    found.update(row_guard._root(word) for word in tokens(variable.text or ""))
                if country or not (variable.code == concept or alone):
                    continue
                for _code, label in variable.values:
                    found.update(row_guard._root(word) for word in tokens(str(label or "")))
    lists.concept_cache[key] = found
    return found


def _writes_demonym(catalogue, lists: _Lists, concept: str) -> bool:
    """A non-country row of this codelist writes Iceland as a derived word ("Icelandic citizenship")."""
    if concept in lists.demonym_cache:
        return lists.demonym_cache[concept]
    found = False
    for table in catalogue.tables:
        for lang, edition in table.editions.items():
            variable = edition.variable(concept)
            if variable is None or variable.time or (table.id, concept) in lists.lists:
                continue
            for _code, label in variable.values:
                for word in _label_words(str(label or "")):
                    if word not in row_guard._SCOPE and any(word.startswith(scope) for scope in lists.scope_stems):
                        found = True
    lists.demonym_cache[concept] = found
    return found


def _touches(word: str, pool: set[str]) -> bool:
    root = row_guard._root(word)
    if word in pool or root in pool:
        return True
    return len(root) >= MIN_TOKEN_LEN and any(other.startswith(root) for other in pool)


def _claimed_cells(result: dict) -> list[dict]:
    """The cited cells of a tool-path result, which carries them on its claims
    as coordinates and labels rather than on its source."""
    out = []
    for claim in result.get("claims") or []:
        for cell in (claim or {}).get("cells") or []:
            if not isinstance(cell, dict) or not isinstance(cell.get("coords"), dict):
                continue
            labels = cell.get("labels") if isinstance(cell.get("labels"), dict) else {}
            out.append({"labels": [
                {"variable": str(variable), "code": str(code), "label": str(labels.get(variable) or code)}
                for variable, code in cell["coords"].items()
            ]})
    return out


def _covers(edition, stem: str, years: set[int], covers) -> bool:
    """A table without a time variable is one period, the one its title
    writes ("31 Dec. 2011"); it covers only the years that title names."""
    if years and not any(variable.time for variable in edition.variables):
        written = {int(year) for year in re.findall(r"(?<!\d)(\d{4})(?!\d)", edition.title or "")}
        return years <= written
    return covers(stem, years)


def _cells(result: dict) -> list[dict]:
    return row_guard._stated(result) or _claimed_cells(result)


def _carriers(catalogue, lists: _Lists, word, label, asked, lang, chosen_id, years, covers, admit):
    """The tables `admit` lets in whose country codelist has the named row."""
    found: list[tuple[str, str, str, str, bool, int]] = []
    uncovered = False
    for (table_id, code), rows in lists.lists.items():
        table = catalogue.by_id[table_id]
        if not admit(table, code):
            continue
        hit = _row_for(word, rows, lists, asked)
        if hit is None:
            continue
        side = table.editions.get(lang) or next(iter(table.editions.values()))
        if side.variable(code) is None or not _other_totals(side, code):
            continue
        stem = table_id.removesuffix(".px")
        if stem != chosen_id and not _covers(side, stem, years, covers):
            uncovered = True
            continue
        size = sum(len(other.values) for other in side.variables if other.code != code and row_guard._classification(other))
        row, derived = hit
        found.append((stem, code, row.code, row.labels.get(side.lang) or label, derived, size))
    return found, uncovered


def _list_named(catalogue, lists: _Lists, asked: list[str], country_word: str) -> str | None:
    """The one country codelist whose own name a question word starts like
    ("fæddir" / "Fæðingarland"), for a stated table that has none."""
    names: dict[str, set[str]] = {}
    for table_id, code in lists.lists:
        for edition in catalogue.by_id[table_id].editions.values():
            variable = edition.variable(code)
            if variable is not None:
                names.setdefault(code, set()).update(fold(word) for word in tokens(variable.text or code))
    scores: dict[str, int] = {}
    for word in asked:
        if word == country_word or word in country_word.split():
            continue
        for code, words in names.items():
            size = max((_prefix(word, name) for name in words), default=0)
            if size >= MIN_TOKEN_LEN:
                scores[code] = max(scores.get(code, 0), size)
    if not scores:
        return None
    best = max(scores.values())
    leaders = [code for code, size in scores.items() if size == best]
    return leaders[0] if len(leaders) == 1 else None


def _home_head(catalogue, lists: _Lists, code: str, lang: str) -> tuple | None:
    """The measure most tables cut by this codelist share ("Mannfjöldi"): what the list counts."""
    heads: dict[tuple, int] = {}
    for table_id, other in lists.lists:
        edition = catalogue.by_id[table_id].editions.get(lang)
        if other == code and edition is not None:
            head = _head(edition)
            heads[head] = heads.get(head, 0) + 1
    if not heads:
        return None
    best = max(heads.values())
    leaders = [head for head, count in heads.items() if count == best]
    return leaders[0] if len(leaders) == 1 and leaders[0] else None


def country_decide(question: str, result: dict, catalogue, years: set[int], covers) -> CountryDecision:
    """Keep the stated cell, switch to the table and row that carry the named country, or refuse."""
    if not enabled() or not result or result.get("refused") or result.get("value") in (None, ""):
        return CountryDecision("keep")
    cells = _cells(result)
    if len(cells) != 1:
        return CountryDecision("keep")
    edition, peer = row_guard._edition(catalogue, result)
    if edition is None:
        return CountryDecision("keep")
    row_guard._load_vocab(catalogue)
    lists = _lists(catalogue)
    table_id = str(result.get("table_id") or "")
    table_id = table_id if table_id.endswith(".px") else table_id + ".px"
    asked_all = row_guard._words(question)
    for item in cells[0].get("labels") or []:
        if not isinstance(item, dict):
            continue
        rows = lists.lists.get((table_id, str(item.get("variable"))))
        if not rows:
            continue
        for word in asked_all:
            hit = match_country(word, rows, lists)
            if hit is not None and hit[0].code == str(item.get("code")):
                return CountryDecision("stated", table_id.removesuffix(".px"), str(item.get("variable")), hit[0].code, str(item.get("label") or ""))
        for row in _multi_named(rows, asked_all):
            if row.code == str(item.get("code")):
                return CountryDecision("stated", table_id.removesuffix(".px"), str(item.get("variable")), row.code, str(item.get("label") or ""))
    have = _have(edition, peer, result)
    named = mentions(question, lists, have)
    if not named:
        return CountryDecision("keep")
    if len({label for _word, label in named}) > 1:
        return CountryDecision("refuse", detail="country: the question names more than one country")
    word, label = named[0]
    asked = _free_words(question, have)
    heads = {side.lang: _head(side) for side in (edition, peer) if side is not None}
    chosen_id = str(result.get("table_id") or "").removesuffix(".px")

    def same_measure(table, _code):
        return any(lang in table.editions and heads[lang] and _head(table.editions[lang]) == heads[lang] for lang in heads)

    found, uncovered = _carriers(catalogue, lists, word, label, asked, edition.lang, chosen_id, years, covers, same_measure)
    stated_has_list = any(
        isinstance(item, dict) and (table_id, str(item.get("variable"))) in lists.lists for item in cells[0].get("labels") or []
    )
    if not found and not stated_has_list:
        named_list = _list_named(catalogue, lists, asked_all, word)
        home = _home_head(catalogue, lists, named_list, edition.lang) if named_list is not None else None
        if home is not None:
            found, uncovered = _carriers(
                catalogue, lists, word, label, asked, edition.lang, chosen_id, years, covers,
                lambda table, code: code == named_list and edition.lang in table.editions and _head(table.editions[edition.lang]) == home,
            )
    measure = f"{chosen_id} ({edition.title})"
    if not found:
        return CountryDecision(
            "refuse",
            label=label,
            detail=f"country: the question names {label}, and no table measuring what {measure} measures has a row for it"
            + (f" in {', '.join(str(year) for year in sorted(years))}" if uncovered else ""),
        )
    concepts = sorted({entry[1] for entry in found})
    if len(concepts) > 1:
        rest = [other for other in asked if other != word and other not in word.split()]
        touched = []
        for concept in concepts:
            rivals = frozenset(set(concepts) - {concept})
            own = _concept_vocab(catalogue, lists, concept, rivals)
            for other in rivals:
                own = own - _concept_vocab(catalogue, lists, other, frozenset({concept}))
            if any(_touches(other, own) for other in rest):
                touched.append(concept)
        if len(touched) == 1:
            concepts = touched
        elif not touched and all(entry[4] for entry in found):
            writers = [concept for concept in concepts if _writes_demonym(catalogue, lists, concept)]
            if len(writers) == 1:
                concepts = writers
    if len(concepts) != 1:
        return CountryDecision(
            "refuse",
            label=label,
            detail=f"country: {label} is a row of {len(concepts)} codelists of tables measuring what {measure} measures, and the question does not say which",
        )
    pool = [entry for entry in found if entry[1] == concepts[0]]
    stem, concept, code, row_label, _derived, _size = min(pool, key=lambda entry: (entry[5], entry[0]))
    stated = {str(item.get("variable")): str(item.get("code")) for item in cells[0].get("labels") or [] if isinstance(item, dict)}
    if stem == chosen_id and stated.get(concept) == code:
        return CountryDecision("keep")
    return CountryDecision("switch", stem, concept, code, row_label)


def with_rows(binding, rows: dict[str, str]):
    """The binding with each pinned variable set to its one row."""
    selections = [item for item in binding.selections if item.get("code") not in rows]
    for code, value in rows.items():
        selections.append({"code": code, "selection": {"filter": "item", "values": [value]}})
    return replace(binding, selections=selections, notes=[*binding.notes, "country row"])


def states_row(result: dict, variable: str, code: str) -> bool:
    if not result or result.get("refused") or result.get("value") in (None, ""):
        return False
    cells = _cells(result)
    return bool(cells) and all(
        any(isinstance(item, dict) and str(item.get("variable")) == variable and str(item.get("code")) == code for item in cell.get("labels") or [])
        for cell in cells
    )


_CLEARED = {"cited cell does not match the question", "breakdown not asked for", "unrequested_breakdown"}


def cell_clears(produced: dict, verdict: dict | None, rows: dict[str, str] | None, language: str | None) -> bool:
    """The pinned country row is what the question named, in a word the claim check does not read."""
    if not rows or str((verdict or {}).get("reason") or "") not in _CLEARED:
        return False
    table = produced.get("table")
    edition = table.edition(language) if table is not None and language else None
    if edition is None and table is not None:
        edition = next(iter(table.editions.values()), None)
    if edition is None:
        return False
    wanted = set()
    for code, value in rows.items():
        variable = edition.variable(code)
        if variable is None:
            return False
        wanted.add(fold(variable.label(value)).strip())
    found: set[str] = set()
    for claim in produced.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            raw = cell.get("labels") if isinstance(cell, dict) else None
            if isinstance(raw, dict):
                found.update(fold(str(value)).strip() for value in raw.values())
            elif isinstance(raw, list):
                found.update(fold(str(item.get("label") or "")).strip() for item in raw if isinstance(item, dict))
    return bool(wanted) and wanted <= found


def country_ranker(result: dict, rows: dict[str, str] | None) -> dict | None:
    """The path that states the pinned country row. The other path never saw the pin."""
    if not rows:
        return None
    if not all(states_row(result, code, value) for code, value in rows.items()):
        return None
    chosen = dict(result)
    source = dict(chosen.get("source") or {})
    source["country_row"] = True
    chosen["source"] = source
    return chosen
