"""Dictionary lookup against the Icelandic inflection database, when installed.

The database is not shipped in this tree. Callers that do not have it
installed get an empty result and the suffix fallback in `lemma` is used.
"""

from __future__ import annotations

from functools import lru_cache

_BIN = None
_MISSING = object()

_POS = {
    "kk": "noun",
    "kvk": "noun",
    "hk": "noun",
    "so": "verb",
    "lo": "adj",
    "ao": "adv",
    "fn": "pron",
    "fs": "adp",
    "st": "conj",
}


def database():
    global _BIN
    if _BIN is _MISSING:
        return None
    if _BIN is not None:
        return _BIN
    try:
        from islenska import Bin

        _BIN = Bin()
    except Exception:
        _BIN = _MISSING
        return None
    return _BIN


def _readings(word: str) -> list:
    db = database()
    if db is None or not word:
        return []
    tried = []
    for form in (word, word.lower(), word[:1].upper() + word[1:]):
        if form in tried:
            continue
        tried.append(form)
        try:
            _surface, entries = db.lookup(form)
        except Exception:
            continue
        real = [entry for entry in entries if getattr(entry, "bin_id", 0)]
        if real:
            return real
    return []


def _prefer(entries: list):
    def rank(entry) -> tuple[int, int]:
        pos = _POS.get(entry.ofl, "other")
        # A published label is usually a noun. Verbs still win when they are
        # the only reading, because the rank tuple is compared, not filtered.
        preference = {"noun": 0, "adj": 1, "verb": 2, "adv": 3}.get(pos, 4)
        hyphen = 1 if "-" in (entry.ord or "") else 0
        return (hyphen, preference)

    return sorted(entries, key=rank)[0]


@lru_cache(maxsize=100_000)
def lexicon_lemma(word: str) -> tuple[str, str] | None:
    """Return the dictionary lemma and a coarse part of speech, or None."""
    entries = _readings(word)
    if not entries:
        return None
    entry = _prefer(entries)
    lemma = (entry.ord or word).replace("-", "")
    return lemma, _POS.get(entry.ofl, "other")


@lru_cache(maxsize=100_000)
def real_lemma(word: str) -> str | None:
    found = lexicon_lemma(word)
    if found is None:
        return None
    return found[0]


# BÍN marks place names and people so they are not ordinary compounds.
_OPAQUE = {"þor", "örn", "göt", "gat", "bær", "ism", "föð", "móð", "ætt"}


def is_opaque_name(word: str) -> bool:
    """True for a place or a person, which is not a compound to split."""
    return lexicon_class(word) in _OPAQUE


def lexicon_class(word: str) -> str | None:
    """The BÍN register of the preferred reading, such as alm or þor."""
    entries = _readings(word)
    if not entries:
        return None
    return getattr(_prefer(entries), "hluti", None)


def lexicon_place(word: str) -> str | None:
    """Lemma of a town or a municipality, or None.

    BÍN marks a town with ``þor``. A municipality that is filed as an
    organisation (Kópavogsbær, Akureyrarbær) ends in bær, hreppur or
    kaupstaður. A common noun, a region, and a company do not.
    """
    entries = _readings(word)
    for entry in entries:
        if _class_has(entry, "þor"):
            return (entry.ord or word).replace("-", "")
    for entry in entries:
        if not _class_has(entry, "fyr"):
            continue
        lemma = (entry.ord or "").replace("-", "")
        folded = lemma.lower()
        if folded.endswith(("bær", "baer", "hreppur", "kaupstaður", "kaupstadur")):
            return lemma
    return None


def _class_has(entry, kind: str) -> bool:
    parts = {part.strip() for part in str(getattr(entry, "hluti", "") or "").split(",")}
    return kind in parts


def known_lemma(lemma: str) -> bool:
    db = database()
    if db is None or not lemma:
        return False
    try:
        _surface, entries = db.lookup_lemmas(lemma)
    except Exception:
        return lexicon_lemma(lemma) is not None
    return any(getattr(entry, "bin_id", 0) for entry in entries)
