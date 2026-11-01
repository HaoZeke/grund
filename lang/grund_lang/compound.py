"""Split an Icelandic compound into dictionary parts.

The parts come from the BÍN compound word list (the same DAWG the
inflection database uses to segment a word). A linking vowel or
consonant (s, u, a, ar, na, i) may sit between the parts. Both parts
have to be real dictionary words. The whole word is kept as well; the
parts are extra retrieval terms.

Kvistur is not required. When the word list cannot be loaded, the same
two-part dictionary cut is used.
"""

from __future__ import annotations

from functools import lru_cache

from grund_lang.binaccess import is_opaque_name, real_lemma
from grund_lang.fold import fold

_LINKERS = ("ar", "na", "s", "u", "a", "i")
# A short head that is a real compound part. "tal" in vísir+tal is not.
# "nótt" is the head of gistinótt; the inflected form is gistinætur.
_SHORT_HEADS = {"afl", "afli", "verd", "nott"}


def _grew(surface: str, lemma: str) -> bool:
    """The lemma added more than one letter that was not in the compound piece."""
    return len(fold(lemma)) > len(fold(surface)) + 1


def _left_lemma(piece: str) -> tuple[str, int] | None:
    """Lemma of the left part, and how many linker letters were not in that lemma."""
    found = real_lemma(piece)
    if found:
        extra = ""
        folded_piece = fold(piece)
        folded_lemma = fold(found)
        if folded_piece.startswith(folded_lemma):
            extra = folded_piece[len(folded_lemma) :]
        # Genitive -ar on höfuðborgar is a linker, not a different word.
        if extra in _LINKERS:
            return found, len(extra)
        return found, 0
    for linker in _LINKERS:
        if piece.endswith(linker) and len(piece) - len(linker) >= 3:
            found = real_lemma(piece[: -len(linker)])
            if found:
                return found, len(linker)
    return None


def _opaque(word: str) -> bool:
    """A place or a person, including when only the capitalised form is marked."""
    if is_opaque_name(word):
        return True
    titled = word[:1].upper() + word[1:]
    return titled != word and is_opaque_name(titled)


def _dawg_segments(word: str) -> list[list[str]] | None:
    """Segmentations from the BÍN compound list. None when that list is absent."""
    try:
        from islenska.dawgdictionary import Wordbase
    except Exception:
        return None
    try:
        combos = Wordbase.dawg().find_combinations(word)
    except Exception:
        return None
    found: list[list[str]] = []
    lowered = word.lower()
    for parts in combos:
        if len(parts) < 2:
            continue
        if "".join(parts).lower() != lowered:
            continue
        found.append(list(parts))
    return found


def _score_parts(parts: list[str]) -> tuple[tuple[int, int, int], tuple[str, ...]] | None:
    lemmas: list[str] = []
    linkers = 0
    for index, piece in enumerate(parts):
        head = index == len(parts) - 1
        if head:
            found = real_lemma(piece)
            if not found:
                return None
            lemma, extra = found, 0
        else:
            hit = _left_lemma(piece)
            if not hit:
                return None
            lemma, extra = hit
            linkers += extra
        folded = fold(lemma)
        if len(folded) < 3:
            return None
        lemmas.append(folded)
    head = lemmas[-1]
    if len(head) < 5 and head not in _SHORT_HEADS:
        return None
    if len(parts) == 2:
        hit = _left_lemma(parts[0])
        if hit and _grew(parts[0], hit[0]) and len(head) < 6 and head not in _SHORT_HEADS:
            return None
    # More of the word accounted for, then fewer parts, then a longer left part.
    # lands+framleiðsla beats lands+fram+leiðsla. höfuðborg+svæði ties
    # höfuð+borgarsvæði on letters and wins on the left word.
    score = (sum(len(part) for part in lemmas) + linkers, -len(lemmas), len(lemmas[0]))
    return score, tuple(lemmas)


def _split_surface(word: str) -> tuple[str, ...]:
    segments = _dawg_segments(word)
    if segments is None:
        return _split_cuts(word)
    best: tuple[str, ...] = ()
    best_score = (0, 0, 0)
    for parts in segments:
        scored = _score_parts(parts)
        if scored is None:
            continue
        score, lemmas = scored
        if score > best_score:
            best = lemmas
            best_score = score
    return best


def _split_cuts(word: str) -> tuple[str, ...]:
    """Two-part cut used only when the compound list is not installed."""
    best: tuple[str, ...] = ()
    best_score = (0, 0)
    for cut in range(3, len(word) - 2):
        left_hit = _left_lemma(word[:cut])
        right = real_lemma(word[cut:])
        if not left_hit or not right:
            continue
        left, linker = left_hit
        folded = (fold(left), fold(right))
        if min(len(folded[0]), len(folded[1])) < 3:
            continue
        if len(folded[1]) < 5 and folded[1] not in _SHORT_HEADS:
            continue
        if _grew(word[:cut], left) and len(folded[1]) < 6 and folded[1] not in _SHORT_HEADS:
            continue
        if folded[0] == fold(word) or folded[1] == fold(word):
            continue
        score = (len(folded[0]) + len(folded[1]) + linker, len(folded[0]))
        if score > best_score:
            best = folded
            best_score = score
    return best


@lru_cache(maxsize=100_000)
def split_compound(word: str) -> tuple[str, ...]:
    """Folded lemmas of the parts, or an empty tuple when the word does not split."""
    if len(word) < 8 or len(word) > 40 or word.isdigit():
        return ()
    # Akureyri is a town in the dictionary, not akur+eyrir.
    if _opaque(word):
        return ()
    lemma = real_lemma(word)
    if lemma and fold(lemma) != fold(word) and not _opaque(lemma) and 8 <= len(lemma) <= 40:
        found = _split_surface(lemma)
        if found:
            return found
    return _split_surface(word)
