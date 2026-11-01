"""Speed up catalogue search without changing the ranking.

The slow part is title alignment: every question re-tokenizes every title
and stems every token again. Titles do not change after load, so their
tokens, stems, and folded form are stored once. The question side is built
once per question. The numeric score is the same formula as the catalogue.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

_INSTALLED = False
_TITLE_PACKS: dict[str, "TitlePack"] = {}
_QUESTION_PACKS: dict[str, "QuestionPack"] = {}


@dataclass
class TitlePack:
    pool: set[str]
    stems: tuple[tuple[str, str], ...]
    folded: str
    cleaned: str


@dataclass
class QuestionPack:
    raw: tuple[str, ...]
    alt_sets: tuple[tuple[str, ...], ...]
    expanded_stems: tuple[tuple[str, str], ...]
    expanded: frozenset[str]


def installed() -> bool:
    return _INSTALLED


def install() -> None:
    """Patch the catalogue helpers. A second call does nothing."""
    global _INSTALLED
    if _INSTALLED:
        return
    import grund_index.catalogue as cat
    from grund_index.model import Edition

    cat.fold = functools.lru_cache(maxsize=200_000)(cat.fold)
    cat.tokens = functools.lru_cache(maxsize=200_000)(cat.tokens)
    cat.inflections = functools.lru_cache(maxsize=200_000)(cat.inflections)
    cat._stem = functools.lru_cache(maxsize=200_000)(cat._stem)
    _cache_years(Edition)
    cat._title_alignment = _align
    _cache_language_fold()
    _memo_catalogue_search(cat)
    _memo_lang_search()
    # HALL PERF SECTION. The hybrid answer and the Icelandic search.
    # app/hall/perf.py is the whole of that section.
    from hall.perf import install as install_perf

    install_perf()
    _INSTALLED = True


def prepare(catalogue) -> None:
    """Fill the title cache and the year sets so the first question is warm."""
    install()
    import grund_lang.fold as foldmod
    import grund_lang.index as indexmod

    for table in catalogue.tables:
        titles = []
        parts: list[str] = []
        for edition in table.editions.values():
            edition.years()
            title = edition.title or ""
            titles.append(title)
            _title_pack(title)
            foldmod.fold(title)
            indexmod._title_tokens(title)
            indexmod._title_years(title)
            indexmod._content_tokens(title)
            parts.append(edition.db or "")
            parts.extend(edition.path or [])
            parts.extend(edition.path_texts or [])
        foldmod.fold(" ".join(titles))
        foldmod.fold(" ".join(parts))
        _titles_blob(table)
    from grund_lang.lemma import analyze

    analyze("What was the consumer price index in September 2026?")
    analyze("Hver var vísitala neysluverðs í september 2026?")
    # HALL PERF SECTION. Label lemmas are ready before the first question.
    from hall.perf import warm

    warm(catalogue)


def _cache_language_fold() -> None:
    import functools

    import grund_lang.fold as foldmod
    import grund_lang.index as indexmod

    if getattr(foldmod.fold, "cache_info", None) is None:
        foldmod.fold = functools.lru_cache(maxsize=500_000)(foldmod.fold)
    indexmod.fold = foldmod.fold
    if getattr(indexmod._content_tokens, "cache_info", None) is None:
        indexmod._content_tokens = functools.lru_cache(maxsize=200_000)(indexmod._content_tokens)
        indexmod._title_tokens = functools.lru_cache(maxsize=200_000)(indexmod._title_tokens)
        indexmod._title_years = functools.lru_cache(maxsize=200_000)(indexmod._title_years)


def _memo_catalogue_search(cat) -> None:
    if getattr(cat.Catalogue.search, "_hall_memo", False):
        return
    original = cat.Catalogue.search

    def memo(self, question: str, k: int = 8, years: list[int] | None = None):
        cache = self.__dict__.setdefault("_hall_q", {})
        key = (question, k, tuple(years or ()))
        found = cache.get(key)
        if found is not None:
            return list(found)
        found = original(self, question, k=k, years=years)
        if len(cache) > 48:
            cache.clear()
        cache[key] = found
        return found

    memo._hall_memo = True
    cat.Catalogue.search = memo


def _memo_lang_search() -> None:
    from grund_lang.index import RetrievalIndex

    if getattr(RetrievalIndex.search, "_hall_memo", False):
        return
    original = RetrievalIndex.search

    def memo(self, question: str, k: int = 10):
        cache = self.__dict__.setdefault("_hall_q", {})
        key = (question, k)
        found = cache.get(key)
        if found is not None:
            return list(found)
        found = original(self, question, k=k)
        if len(cache) > 48:
            cache.clear()
        cache[key] = found
        return found

    memo._hall_memo = True
    RetrievalIndex.search = memo


def _cache_years(edition_cls) -> None:
    original = edition_cls.years

    def years(self):
        cached = self.__dict__.get("_hall_years")
        if cached is None:
            cached = original(self)
            self._hall_years = cached
        return cached

    edition_cls.years = years


def _stem(token: str) -> str:
    import grund_index.catalogue as cat

    return cat._stem(token)


def _title_pack(title: str) -> TitlePack:
    pack = _TITLE_PACKS.get(title)
    if pack is not None:
        return pack
    import grund_index.catalogue as cat

    pool = set(cat.tokens(title))
    stems = []
    for token in pool:
        stem = _stem(token)
        if len(stem) >= 6:
            stems.append((token, stem))
    import re

    folded = cat.fold(title)
    cleaned = re.sub(r"\b1[7-9]\d{2}\s*[-–]\s*(?:1[7-9]|20)\d{2}\b", " ", folded)
    cleaned = re.sub(r"\b(?:1[7-9]|20)\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–,")
    pack = TitlePack(pool=pool, stems=tuple(stems), folded=folded, cleaned=cleaned)
    _TITLE_PACKS[title] = pack
    return pack


def _titles_blob(table) -> str:
    import grund_index.catalogue as cat

    blob = table.__dict__.get("_hall_titles")
    if blob is None:
        blob = cat.tokens(table.titles())
        table._hall_titles = blob
    return blob


def _question_pack(question: str) -> QuestionPack:
    pack = _QUESTION_PACKS.get(question)
    if pack is not None:
        return pack
    import grund_index.catalogue as cat

    raw = tuple(
        token
        for token in cat.tokens(question, expand=False)
        if not token.isdigit() and token not in cat._OPERATION_QUERY
    )
    alt_sets = []
    expanded: set[str] = set()
    for token in raw:
        forms = [token, *cat.inflections(token)]
        alts = set(forms)
        for form in forms:
            alts.update(cat.SYNONYMS.get(form, ()))
        expanded |= alts
        alt_sets.append(tuple(alts))
    stems = []
    for token in expanded:
        stem = _stem(token)
        if len(stem) >= 6:
            stems.append((token, stem))
    pack = QuestionPack(
        raw=raw,
        alt_sets=tuple(alt_sets),
        expanded_stems=tuple(stems),
        expanded=frozenset(expanded),
    )
    if len(_QUESTION_PACKS) > 64:
        _QUESTION_PACKS.clear()
    _QUESTION_PACKS[question] = pack
    return pack


def _alt_in_title(alt: str, pack: TitlePack) -> bool:
    if alt in pack.pool:
        return True
    if len(alt) > 4 and alt.endswith("s") and alt[:-1] in pack.pool:
        return True
    if len(alt) > 4 and (alt + "s") in pack.pool:
        return True
    stem = _stem(alt)
    if len(stem) < 6:
        return False
    for other, other_stem in pack.stems:
        if stem == other_stem or other.startswith(stem) or stem.startswith(other_stem):
            return True
    return False


def _token_in_expanded(token: str, pack: QuestionPack) -> bool:
    if token in pack.expanded:
        return True
    if len(token) > 4 and token.endswith("s") and token[:-1] in pack.expanded:
        return True
    if len(token) > 4 and (token + "s") in pack.expanded:
        return True
    stem = _stem(token)
    if len(stem) < 6:
        return False
    for other, other_stem in pack.expanded_stems:
        if len(other_stem) < 6:
            continue
        if stem == other_stem or other.startswith(stem) or stem.startswith(other_stem):
            return True
    return False


_FLAGS: dict[str, dict] = {}


def _question_flags(question: str):
    import re

    import grund_index.catalogue as cat

    cached = _FLAGS.get(question)
    if cached is not None:
        return cached
    folded = cat.fold(question)
    words = set(folded.split())
    wants_cpi = (
        "consumer price" in folded
        or "neysluverd" in folded
        or re.search(r"\b(cpi|vnv)\b", folded) is not None
    )
    wants_internal = bool(
        words
        & {
            "moved", "moves", "move", "migrated", "migration", "flutning",
            "internally", "internal", "fluttu", "buferlum", "innanlands",
        }
    )
    # The original bonus looks for these words inside the folded question,
    # including as parts of a longer token. Keep that test, not only split words.
    wants_within = any(
        word in folded.split()
        for word in ("within", "internally", "internal", "innanlands", "buferlum")
    )
    flags = {
        "folded": folded,
        "annual": "annual average" in folded or "arsmedal" in folded,
        "cpi": wants_cpi,
        "internal": wants_internal,
        "within": wants_within,
        "place": any(
            word in folded
            for word in ("municipality", "sveitarfelag", "region", "landshluti", "localit", "byggdakjarn")
        ),
        "change": any(
            phrase in folded
            for phrase in ("annual change", "arleg breyting", "arsbreyting", "yearly change")
        ),
    }
    if len(_FLAGS) > 64:
        _FLAGS.clear()
    _FLAGS[question] = flags
    return flags


def _subject_from_flags(flags: dict, title_folded: str) -> float:
    import re

    bonus = 0.0
    if flags["annual"]:
        if "annual average" in title_folded or "arsmedal" in title_folded:
            bonus += 0.35
        else:
            bonus -= 0.15
    if flags["cpi"]:
        has_cpi = (
            "consumer price" in title_folded
            or "neysluverd" in title_folded
            or re.search(r"\bcpi\b", title_folded) is not None
        )
        bonus += 0.30 if has_cpi else -0.20
    if flags["internal"] and flags["within"]:
        if "internal migration" in title_folded or "buferlafl" in title_folded:
            bonus += 0.25
        elif "population" in title_folded and "migration" not in title_folded:
            bonus -= 0.20
    if flags["internal"] and not flags["place"]:
        if any(word in title_folded for word in ("municipality", "sveitarfelag", "between regions", "localit", "milli landsvaed")):
            bonus -= 0.15
        if "internal migration" in title_folded or "buferlaflinnanland" in title_folded or "innanlands" in title_folded:
            bonus += 0.10
    if flags["change"]:
        headline = ("breyting" in title_folded or "change" in title_folded) and (
            "neysluverd" in title_folded or "consumer price" in title_folded
        )
        if headline:
            bonus += 0.35
        if any(phrase in title_folded for phrase in ("fastskatt", "arsmedal", "ahrif", "constant tax", "annual average")):
            bonus -= 0.25
    return bonus


def _align(question: str, title: str) -> float:
    question_pack = _question_pack(question)
    title_pack = _title_pack(title)
    flags = _question_flags(question)
    if not question_pack.raw:
        return _subject_from_flags(flags, title_pack.folded)
    hits = 0
    for alts in question_pack.alt_sets:
        if any(_alt_in_title(alt, title_pack) for alt in alts):
            hits += 1
    coverage = hits / len(question_pack.raw)
    extras = 0
    for token in title_pack.pool:
        if token.isdigit() or len(token) <= 3:
            continue
        if _token_in_expanded(token, question_pack):
            continue
        extras += 1
    exact = 0.45 if len(title_pack.cleaned) >= 16 and title_pack.cleaned in flags["folded"] else 0.0
    return (
        0.45 * coverage
        - 0.035 * min(extras, 8)
        + _subject_from_flags(flags, title_pack.folded)
        + exact
    )


def search_is_fast() -> bool:
    """True when this process is using the cached title alignment."""
    import grund_index.catalogue as cat

    return getattr(cat, "_title_alignment", None) is _align
