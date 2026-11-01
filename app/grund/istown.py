"""Icelandic municipality headcount. Off unless ``GRUND_IS_KANG_TOWN`` is set.

A question that asks how many people live in one town leads with the
population-by-municipality table. A year of age, a share, a change, and a
national total stay on the ordinary list. The age cover owns ``N ára``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_CATALOGUE = None


def _catalogue():
    global _CATALOGUE
    if _CATALOGUE is None:
        from grund_index.catalogue import Catalogue

        _CATALOGUE = Catalogue.load(Path(os.environ.get("GRUND_INDEX", "data/index")))
    return _CATALOGUE

_COUNT = ("bjuggu", "bua", "ibuafjoldi", "ibuar", "mannfjoldi")
_BLOCK = (
    "ara",
    "hlutfall",
    "prosent",
    "munadi",
    "milli",
    "haekk",
    "laekk",
    "atvinnu",
    "faedist",
    "fyrirtaek",
    "visital",
    "manntal",
    "a ibua",
    "per ibua",
)
_EXCLUDE = ("innflytj", "rikisfang", "faeding", "medal", "hverf", "manntal", "throun", "bakgrunn")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_TOWN", "0").strip().lower() in {"1", "on", "true", "yes"}


def _current_division(title: str) -> bool:
    """The live 1 January municipality list, not a district or 1950 division."""
    folded = fold(title or "")
    if "mannfjoldi" not in folded or "sveitarfel" not in folded:
        return False
    if any(mark in folded for mark in _EXCLUDE):
        return False
    if "1950" in folded:
        return False
    return True


def _one_place(question: str) -> str | None:
    from grund_lang.kang_places import install, named_places
    from grund_lang.lemma import analyze

    analysis = analyze(question)
    if not getattr(install, "_ready_for_town", False):
        # install is idempotent. The catalogue is loaded by the caller that
        # first asks; a missing list simply does not fire.
        pass
    places = named_places(analysis)
    if len(places) != 1:
        return None
    return places[0]


def municipality_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The one official municipality this headcount names, or none."""
    if not _current_division(title) or not wants_town(question, language):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "sveitarfel" not in blob and "municipality" not in blob:
        return None
    place = _one_place(question)
    if place is None:
        return None
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        if label_is_place(str(label or ""), place):
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def _chosen_label_is_place(edition, chosen: dict, place: str) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        codes = list((chosen or {}).get(variable.code) or [])
        if len(codes) != 1:
            continue
        blob = fold(f"{variable.code} {variable.text}")
        if "sveitarfel" not in blob and "municipality" not in blob:
            continue
        label = variable.label(codes[0]) if hasattr(variable, "label") else ""
        if label_is_place(str(label or ""), place):
            return True
    return False


def town_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    """A headcount word the current municipality table already answers.

    Íbúafjöldi is the same count as mannfjöldi. Hafnarfirði is Hafnarfjörður
    in the dative, which BÍN lemmatises and the official label does not print.
    """
    if edition is None or not _current_division(getattr(edition, "title", "") or ""):
        return False
    if not wants_town(question, language):
        return False
    folded = fold(token)
    title = fold(getattr(edition, "title", "") or "")
    place = _one_place(question)
    if folded in {"ibuafjoldi", "mannfjoldi"} and "mannfjoldi" in title:
        return True
    if (
        place
        and folded.startswith("sveitarfel")
        and "sveitarfel" in title
        and _chosen_label_is_place(edition, chosen, place)
    ):
        return True
    if place is None or not _chosen_label_is_place(edition, chosen, place):
        return False
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        if fold(tok.surface) != folded:
            continue
        # The dictionary lemma is the town, including firði → fjörður.
        if tok.lemma == place:
            return True
    return False


def label_counts_as_asked(question: str, label: str) -> bool:
    """The printed municipality is the inflected town in the question."""
    if not wants_town(question, None):
        return False
    place = _one_place(question)
    if place is None:
        return False
    return label_is_place(str(label or ""), place)


def question_word_in_town_cell(question: str, word: str, claims: list | None) -> bool:
    """Íbúafjöldi and an inflected town are covered by the official cell."""
    if not wants_town(question, None):
        return False
    titles = []
    labels: list[str] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            titles.append(fold(str(cell.get("title") or "")))
            for value in (cell.get("labels") or {}).values():
                labels.append(str(value))
    title = " ".join(titles)
    if "sveitarfel" not in title or "mannfjoldi" not in title or "1950" in title:
        return False
    folded = fold(word)
    if folded == "ibuafjoldi" and "mannfjoldi" in title:
        return True
    place = _one_place(question)
    if place is None or not any(label_is_place(label, place) for label in labels):
        return False
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        if fold(tok.surface) == folded and tok.lemma == place:
            return True
    return False


def _cell_labels(produced: dict) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for claim in produced.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            raw = cell.get("labels")
            if isinstance(raw, dict):
                found.extend((str(key), str(value)) for key, value in raw.items())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        key = str(item.get("variable_text") or item.get("variable") or "")
                        found.append((key, str(item.get("label") or "")))
    return found


def town_states_country(question: str, language: str | None, produced: dict) -> bool:
    """A named municipality answered with the all-municipalities total."""
    if not wants_town(question, language):
        return False
    for key, value in _cell_labels(produced):
        blob = fold(key)
        if "sveitarfel" not in blob and "municip" not in blob:
            continue
        if fold(value) in {"alls", "total", "samtals"}:
            return True
    return False


def town_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """Keep the current municipality cell when the rail only missed the inflection.

    A district table, a postcode table, and a 1950 division stay blocked.
    """
    if not wants_town(question, language):
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"breakdown not asked for", "cited cell does not match the question"}:
        return False
    binding = produced.get("binding")
    operation = getattr(binding, "operation", None) or produced.get("operation") or "level"
    if operation not in {"level", ""}:
        return False
    table = produced.get("table")
    table_id = getattr(table, "id", None) or produced.get("table_id") or ""
    place = _one_place(question)
    if place is None or not table_id:
        return False
    expected = _town_table(_catalogue(), place)
    if expected is None or _stem(str(table_id)) != _stem(expected.id):
        return False
    asked_years = set(re.findall(r"(?:19|20)\d{2}", question or ""))
    claims = produced.get("claims") or []
    named = False
    year_ok = not asked_years
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            for label in (cell.get("labels") or {}).values():
                text = str(label or "")
                folded = fold(text)
                if folded in asked_years:
                    year_ok = True
                    continue
                if folded in {"alls", "total", "samtals", "all"}:
                    continue
                if label_is_place(text, place):
                    named = True
                    continue
                if folded.isdigit():
                    continue
                return False
    return named and year_ok


_HEAD = {
    "hve",
    "hversu",
    "hvad",
    "margir",
    "margur",
    "bjuggu",
    "bua",
    "bu",
    "ibuafjoldi",
    "ibuar",
    "ibua",
    "mannfjoldi",
    "sveitarfelag",
    "i",
    "a",
    "arid",
    "ar",
    "januar",
    "eru",
    "voru",
    "var",
    "er",
}


def _headcount_only(question: str, place: str) -> bool:
    """The question is the headcount and the town, not another subject.

    "Hve margir álfar búa í Hafnarfirði" names elves. The municipality
    population is a different statistic, so the gate stays shut.
    """
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        surface = fold(tok.surface)
        lemma = fold(tok.lemma or "")
        if surface.isdigit() or lemma.isdigit():
            continue
        if surface == place or lemma == place:
            continue
        if surface in _HEAD or lemma in _HEAD:
            continue
        return False
    return True


_EN_COUNT = ("lived", "live", "people", "population", "inhabitant", "folk", "headcount", "resident")
_EN_BLOCK = ("women", "woman", " men", "older", "immigrant", "capital region", "northeast", "northwest", "westfjord", "southwest")
_EN_HEAD = {
    "how", "many", "what", "was", "were", "the", "of", "in", "on", "at", "people", "person",
    "lived", "live", "living", "population", "january", "januar", "1", "did", "have", "had",
    "inhabitant", "inhabitants", "folk", "folks", "headcount", "resident", "residents",
    "start", "during",
}


def _english_town(question: str) -> bool:
    """One current municipality in an English headcount, not a region or a sex."""
    text = fold(question or "")
    if not any(mark in text for mark in _EN_COUNT):
        return False
    if any(mark in text for mark in _EN_BLOCK):
        return False
    place = _one_place(question)
    if place is None or not _on_current_division(place):
        return False
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        surface = fold(tok.surface)
        lemma = fold(tok.lemma or "")
        if surface.isdigit() or lemma.isdigit():
            continue
        if surface == place or lemma == place:
            continue
        if surface in _EN_HEAD or lemma in _EN_HEAD:
            continue
        return False
    return True


def wants_town(question: str, language: str | None) -> bool:
    """Headcount of one current municipality, and nothing else."""
    if not enabled():
        return False
    if language == "en":
        return _english_town(question)
    if language not in {None, "", "is"}:
        return False
    text = fold(question or "")
    if not any(mark in text for mark in _COUNT):
        return False
    if any(mark in text for mark in _BLOCK):
        return False
    place = _one_place(question)
    if place is None or not _headcount_only(question, place):
        return False
    # "Mannfjöldi Vestfjarða" names a region. Only a municipality on the
    # current division is a town. "bjuggu í X" already required that table.
    headcount = any(mark in text for mark in ("bjuggu", "bua", "ibuafjoldi", "ibuar"))
    if not headcount and not _on_current_division(place):
        return False
    return True


def _on_current_division(place: str) -> bool:
    catalogue = _catalogue()
    table = catalogue.by_id.get("MAN02005.px") or catalogue.by_id.get("MAN02005")
    if table is None:
        return False
    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return False
    for variable in edition.variables:
        blob = fold(f"{variable.code} {variable.text}")
        if "sveitarfel" not in blob and "municipality" not in blob:
            continue
        for _code, label in variable.values:
            if label_is_place(str(label or ""), place):
                return True
    return False


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _shared_prefix(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def label_is_place(label: str, place: str) -> bool:
    """The printed municipality is that town, including Reykjavíkurborg-style names."""
    from grund_lang.lemma import lemmatize_label

    if not place or not label:
        return False
    if place in lemmatize_label(label):
        return True
    head = fold(str(label).split("(")[0].split(" - ")[0].strip())
    if " " in head:
        return False
    return _shared_prefix(head, place) >= 7 and min(len(head), len(place)) >= 7


def _lists_place(edition, place: str) -> bool:
    for variable in edition.variables:
        blob = fold(f"{variable.code} {variable.text}")
        if "sveitarfel" not in blob and "municipality" not in blob:
            continue
        for _code, label in variable.values:
            if label_is_place(str(label or ""), place):
                return True
    return False


def _town_table(catalogue, place: str):
    best = None
    best_key = None
    for table in catalogue.tables:
        edition = table.edition("is") or table.edition("en")
        if edition is None:
            continue
        title = fold(edition.title or "")
        if "mannfjoldi" not in title or "sveitarfel" not in title:
            continue
        if any(mark in title for mark in _EXCLUDE):
            continue
        if not _lists_place(edition, place):
            continue
        years = list(edition.years() or [])
        latest = max(years) if years else 0
        span = (max(years) - min(years)) if len(years) >= 2 else 0
        # The 1950 municipal division is a different list. The current
        # 1 January division is the one these questions mean.
        historical = 1 if "1950" in title else 0
        current = 1 if "januar" in title else 0
        key = (current, -historical, latest, span)
        if best_key is None or key > best_key:
            best = table
            best_key = key
    return best


def _place_is_bound(table, question: str, place: str) -> bool:
    from grund_lang.lemma import analyze
    from grund_lang.values import bind_values

    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return False
    for choice in bind_values(question, edition, analyze(question)):
        blob = fold(f"{choice.variable_code} {choice.variable_text}")
        if "sveitarfel" not in blob and "municipality" not in blob:
            continue
        if fold(choice.value_label or "") in {"alls", "total", "samtals"}:
            return False
        if label_is_place(choice.value_label or "", place):
            return True
    return False


def apply_is_town(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Move the municipality population table to the front, or leave the list."""
    if not wants_town(question, language):
        return hits
    from grund_lang.kang_places import install, named_places
    from grund_lang.lemma import analyze

    install(catalogue.tables)
    places = named_places(analyze(question))
    if len(places) != 1:
        return hits
    table = _town_table(catalogue, places[0])
    if table is None or not _place_is_bound(table, question, places[0]):
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _stem(table.id)]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept


def _result_names_place(result: dict, place: str) -> bool:
    cells = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        labels = []
        for key in ("labels", "map", "coords"):
            value = cell.get(key)
            if isinstance(value, dict):
                labels.extend(str(item) for item in value.values())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        labels.append(str(item.get("label") or item.get("value") or ""))
        for label in labels:
            if fold(label) in {"alls", "total", "samtals"}:
                continue
            if label_is_place(label, place):
                return True
    return False


def town_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the ranker's municipality cell when hybrid states a different total."""
    if not wants_town(question, language):
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    from grund_lang.kang_places import named_places
    from grund_lang.lemma import analyze

    places = named_places(analyze(question))
    if len(places) != 1:
        return None
    # A different municipality series (an older division, a district table)
    # can name the town and still be the wrong cell. Keep only the table
    # the gate itself would lead with.
    table = _town_table(_catalogue(), places[0])
    if table is None or _stem(str(ranker.get("table_id") or "")) != _stem(table.id):
        return None
    if not _result_names_place(ranker, places[0]):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_town"] = True
    chosen["source"] = source
    return chosen
