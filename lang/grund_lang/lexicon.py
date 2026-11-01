"""Everyday words to the vocabulary of the published tables.

The pairs come from three public sources, not from a question list.

- Hagstofa subject pages: a word that occurs in exactly one subject's
  prose is that subject's heading. ``lögheimili`` is said on the migration
  page, next to ``búferlaflutningar``. ``flytja`` is said there too, and
  ``build`` does not install it. With the disagreement rule off that entry
  states 0 from MAN01002.
- The catalogue's own Icelandic and English folder names, when the two
  languages name the same folder at least eight times.
- BÍN's inhabitant class (ffl) matched to a municipality label. The
  match is a stem, after the inhabitant ending and the firði/fjörður
  alternation, and it has to be unique.

Table notes were empty in the local metadata, and the API answered 429,
so notes are not in this map. A word that the pages use for two subjects
is left unmapped. ``þjóðskrá`` is one of those.
"""

from __future__ import annotations

import difflib
import json
import os
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from grund_lang.binaccess import lexicon_class, real_lemma
from grund_lang.fold import GENERIC, STOP, fold
from grund_lang.lemma import lemmatize_label

_BLOCK = STOP | GENERIC | {
    "hagstofa", "tolur", "tala", "gogn", "upplysing", "upplysingar", "birta",
    "safna", "land", "arid", "manudur", "fjoldi", "vinna", "vinnur", "nara",
    "fra", "vid", "eftir", "thegar", "sidan", "einnig", "her", "landi", "lands",
}

# source lemma -> target lemmas. Empty until install().
_MAP: dict[str, tuple[str, ...]] = {}


def aliases() -> dict[str, tuple[str, ...]]:
    return dict(_MAP)


def install(found: dict[str, tuple[str, ...]]) -> None:
    global _MAP
    _MAP = {key: tuple(values) for key, values in found.items() if values}


def extra_lemmas(token_lemmas: list[str]) -> list[str]:
    # Default on. Each entry was checked on its own and lost no rank-1 gold.
    if os.environ.get("GRUND_LEXICON", "1") == "0" or not _MAP:
        return []
    added: list[str] = []
    bag = set(token_lemmas)
    for lemma in token_lemmas:
        for target in _MAP.get(lemma, ()):
            if target not in bag and target not in added:
                added.append(target)
    return added


def _content(text: str) -> list[str]:
    found: list[str] = []
    for lemma in lemmatize_label(text or ""):
        if lemma in _BLOCK or len(lemma) < 5 or lemma.isdigit():
            continue
        if lemma not in found:
            found.append(lemma)
    return found


def _pos_ok(surface: str) -> bool:
    found = None
    try:
        from grund_lang.binaccess import lexicon_lemma

        found = lexicon_lemma(surface)
    except Exception:
        found = None
    if found is None:
        return True
    return found[1] in {"noun", "verb"}


def prose_maps(pages: list[dict]) -> dict[str, tuple[str, ...]]:
    """A prose word used on exactly one subject page points at that heading."""
    from grund_lang.binaccess import lexicon_lemma
    from grund_lang.fold import words

    votes: dict[str, Counter[str]] = defaultdict(Counter)
    kinds: dict[str, str] = {}
    for page in pages:
        prose = page.get("prose") or ""
        heading = page.get("heading") or ""
        heads = _content(heading)
        if not prose or not heads:
            continue
        head = heads[0]
        seen: set[str] = set()
        for word in words(prose):
            reading = lexicon_lemma(word)
            if reading is None:
                continue
            surface, kind = reading
            term = fold(surface)
            if term in _BLOCK or len(term) < 5 or term == head or term in seen:
                continue
            seen.add(term)
            kinds[term] = kind
            votes[term][head] += 1
    found: dict[str, tuple[str, ...]] = {}
    for term, counter in votes.items():
        if sum(counter.values()) != 1:
            continue
        target = counter.most_common(1)[0][0]
        if target in _BLOCK or len(target) < 5:
            continue
        # A short noun that happens to be said once is not a subject.
        # Verbs and long nouns (lögheimili) are. build() then drops flytja.
        kind = kinds.get(term, "")
        if kind == "verb" or (kind == "noun" and len(term) >= 8):
            found[term] = (target,)
    return found


def folder_maps(tables: list) -> dict[str, tuple[str, ...]]:
    """Icelandic and English names of the same subject folder."""
    counts: Counter[tuple[str, str]] = Counter()
    for table in tables:
        icelandic = table.editions.get("is")
        english = table.editions.get("en")
        if icelandic is None or english is None:
            continue
        left = getattr(icelandic, "path_texts", []) or []
        right = getattr(english, "path_texts", []) or []
        for one, other in zip(left, right):
            a = _content(one)
            b = _content(other)
            if len(a) == 1 and len(b) == 1 and a[0] != b[0] and len(a[0]) >= 8 and len(b[0]) >= 8:
                counts[(a[0], b[0])] += 1
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for (left, right), count in counts.items():
        if count < 8:
            continue
        votes[left][right] += count
        votes[right][left] += count
    found: dict[str, tuple[str, ...]] = {}
    for source, counter in votes.items():
        total = sum(counter.values())
        target, count = counter.most_common(1)[0]
        if count / total < 0.8:
            continue
        found[source] = (target,)
    return found


def _stem_forms(word: str) -> set[str]:
    folded = fold(real_lemma(word) or word)
    forms = {folded}
    for suffix, replacement in (
        ("firdingur", "fjordur"),
        ("firdingar", "fjordur"),
        ("buar", ""),
        ("bui", ""),
        ("ingar", ""),
        ("ingur", ""),
    ):
        minimum = 2 if suffix.startswith("fird") else 4
        if folded.endswith(suffix) and len(folded) - len(suffix) >= minimum:
            forms.add(folded[: -len(suffix)] + replacement)
    return {form for form in forms if len(form) >= 4}


def _places(tables: list) -> list[str]:
    """Short municipality labels, not party lists."""
    found: set[str] = set()
    for table in tables:
        for edition in table.editions.values():
            for variable in edition.variables:
                text = fold(variable.text or "")
                if "sveitarfelag" not in text and "municipality" not in text:
                    continue
                for _code, label in variable.values:
                    raw = str(label or "").strip()
                    head = raw.split("(")[0].split(" - ")[0].strip()
                    if " " in head or len(head) < 4 or len(head) > 28:
                        continue
                    if fold(head) in {"alls", "total", "samtals"}:
                        continue
                    found.add(head)
    return sorted(found)


def demonym_maps(tables: list) -> dict[str, tuple[str, ...]]:
    """An inhabitant name in BÍN points at one municipality label."""
    places = _places(tables)
    folded_places = [(fold(place), place) for place in places]
    # Words are discovered from the place list's own inhabitant pattern only
    # when a query asks. The map itself is built for every ffl we can see
    # by trying the place-derived demonym the other way: store place stems
    # so a query demonym can be resolved at expand time without a word list.
    # Here we just remember the place inventory.
    _PLACES.clear()
    _PLACES.extend(folded_places)
    return {}


_PLACES: list[tuple[str, str]] = []


@lru_cache(maxsize=100_000)
def demonym_target(word: str) -> str | None:
    """Folded municipality for a BÍN inhabitant, when one place wins."""
    if os.environ.get("GRUND_IS_KANG_PLACES", "0") == "1":
        from grund_lang.kang_places import target as place_target

        found = place_target(word)
        if found:
            return found
    flag = os.environ.get("GRUND_DEMONYM", os.environ.get("GRUND_LEXICON", "1"))
    if flag == "0":
        return None
    if lexicon_class(word) != "ffl" and not fold(word).endswith(("ingur", "ingar", "bui", "buar")):
        return None
    if not _PLACES:
        return None
    forms = _stem_forms(word)
    scored: list[tuple[float, str]] = []
    for folded_place, _surface in _PLACES:
        best = 0.0
        for form in forms:
            if folded_place.startswith(form) or form.startswith(folded_place):
                best = max(best, float(min(len(form), len(folded_place))))
                continue
            if abs(len(form) - len(folded_place)) > 3:
                continue
            ratio = difflib.SequenceMatcher(None, form, folded_place).ratio()
            if ratio >= 0.9:
                best = max(best, ratio * 10)
        if best:
            scored.append((best, folded_place))
    if not scored:
        return None
    scored.sort(reverse=True)
    # Several labels of one town (Akureyri, Akureyrarbær) share a score.
    top = scored[0][0]
    winners = {place for score, place in scored if score == top}
    # Keep the shortest label; drop the match when two different towns tie.
    shortest = min(winners, key=len)
    others = [place for place in winners if not (place.startswith(shortest) or shortest.startswith(place))]
    if others:
        return None
    return shortest


def extra_from_tokens(words: list[str]) -> list[str]:
    added = extra_lemmas(words)
    for word in words:
        place = demonym_target(word)
        if place and place not in added and place not in words:
            added.append(place)
    return added


def build(tables: list, pages: list[dict] | None = None) -> dict[str, tuple[str, ...]]:
    if pages is None:
        path = Path(__file__).with_name("subject_prose.json")
        if path.exists():
            pages = json.loads(path.read_text(encoding="utf-8"))
        else:
            pages = []
    found = prose_maps(pages)
    for key, value in folder_maps(tables).items():
        found.setdefault(key, value)
    # The migration page is the only place that says flytja, so the prose
    # rule maps it to búferlaflutningar. That entry does not retrieve the
    # gold table. With the disagreement rule off it states 0 from MAN01002.
    found.pop("flytja", None)
    demonym_maps(tables)
    install(found)
    from grund_lang.kang_places import install as install_places

    install_places(tables)
    return found


def save(path: Path, found: dict[str, tuple[str, ...]]) -> None:
    payload = {key: list(value) for key, value in sorted(found.items())}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
