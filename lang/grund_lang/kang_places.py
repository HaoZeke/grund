"""Municipality and region name forms, behind GRUND_IS_KANG_PLACES.

PxWeb prints one nominative label (Hafnarfjörður, Ísafjarðarbær). A
question uses the dative, the genitive, or the longer official name.
Forms come from the inflection database when it is installed, and from
the label strings in the loaded catalogue otherwise. A form adds the
catalogue label only when the question's own lemma is not already that
label, so a question that already says Reykjavík is left as it was.
The flag defaults off. Place-name data in the database is BÍN, CC BY-SA
4.0, used by lookup and not copied into this tree.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from grund_lang.fold import fold

_GEO = ("sveitarfelag", "municipality", "landshluti", "landsvaedi", "region", "byggd")
_READY = False
# folded form -> catalogue label lemmas that this form belongs to
_FORMS: dict[str, tuple[str, ...]] = {}
_LABELS: set[str] = set()


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_PLACES", "0") == "1"


def _head(label: str) -> str:
    head = str(label or "").split("(")[0].split(" - ")[0].strip()
    head = re.sub(r"\s+", " ", head)
    return head


def _geo(text: str) -> bool:
    folded = fold(text or "")
    return any(piece in folded for piece in _GEO)


def install(tables: list) -> int:
    """Remember every inflected form of a municipality or region label."""
    global _READY, _FORMS, _LABELS
    labels: list[str] = []
    seen: set[str] = set()
    for table in tables:
        editions = getattr(table, "editions", {}) or {}
        for edition in editions.values():
            for variable in getattr(edition, "variables", []) or []:
                if not _geo(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}"):
                    continue
                for _code, label in getattr(variable, "values", []) or []:
                    head = _head(str(label or ""))
                    if not (4 <= len(head) <= 40):
                        continue
                    if len(head.split()) > 3:
                        continue
                    folded = fold(head)
                    if folded in {"alls", "total", "samtals", "annad", "other"} or folded in seen:
                        continue
                    seen.add(folded)
                    labels.append(head)
    forms: dict[str, list[str]] = {}
    try:
        from grund_lang.kang_binforms import paradigm
    except Exception:
        paradigm = None
    for label in labels:
        folded = fold(label)
        bucket = forms.setdefault(folded, [])
        if folded not in bucket:
            bucket.append(folded)
        if paradigm is None:
            continue
        for form in paradigm(label):
            slot = forms.setdefault(form, [])
            if folded not in slot:
                slot.append(folded)
    # A longer official name (Reykjavíkurborg) and the short label share a stem.
    # The short label is the one a value list actually prints.
    for label in labels:
        folded = fold(label)
        for other in labels:
            shorter = fold(other)
            if shorter == folded or len(shorter) < 6:
                continue
            if folded.startswith(shorter) and len(folded) - len(shorter) <= 6:
                for form, owners in list(forms.items()):
                    if folded in owners and shorter not in owners:
                        owners.append(shorter)
    _FORMS = {form: tuple(owners) for form, owners in forms.items()}
    _LABELS = set(seen)
    _READY = True
    return len(_LABELS)


def _ensure() -> None:
    if _READY:
        return
    index = os.environ.get("GRUND_INDEX", "data/index")
    try:
        from pathlib import Path

        from grund_index.catalogue import Catalogue

        install(Catalogue.load(Path(index)).tables)
    except Exception:
        install([])


_COUNT = ("bjuggu", "bua", "ibuafjoldi", "ibuar", "ibua", "margir", "fjoldi", "fjoldinn", "fjolmenn")
_NOT_HEADCOUNT = ("fyrirtaek", "innflytj", "skola", "nemend", "atvinnu", "laun", "gistin")
_BREAKDOWN = ("innflytj", "rikisfang", "faeding", "medalmann", "throun", "manntal", "hverfum", "bakgrunn")


def named_places(analysis) -> list[str]:
    """One catalogue label per place the question actually names."""
    if not _READY:
        _ensure()
    found: list[str] = []
    words = []
    for token in getattr(analysis, "tokens", []) or []:
        words.append(token.surface)
        words.append(getattr(token, "lemma_surface", "") or "")
        words.append(token.lemma)
    for term in getattr(analysis, "terms", []) or []:
        words.append(term)
    for word in words:
        folded = fold(str(word or ""))
        if not folded:
            continue
        if folded in _LABELS and folded not in found:
            found.append(folded)
        for target in _FORMS.get(folded, ()):
            if target not in found:
                found.append(target)
    # Vestmannaeyjar and Vestmannaeyjabær are one town. Keep the official name.
    drop: set[str] = set()
    for place in found:
        for other in found:
            if place == other:
                continue
            if other.startswith(place) or f" {place} " in f" {other} ":
                drop.add(place)
                continue
            shared = 0
            for left, right in zip(place, other):
                if left != right:
                    break
                shared += 1
            longer = other if len(other) >= len(place) else place
            if shared >= 8 and longer[shared:].startswith(("baer", "borg", "kaup")) and place != longer:
                drop.add(place)
    kept = [place for place in found if place not in drop]
    return kept or found


def prefer_municipality(ranked, analysis, index):
    """A named town's population table leads a bare population heading.

    Only a headcount question, and only a table already in the list whose
    title is the municipality breakdown and whose values name that town.
    The flag is off unless GRUND_IS_KANG_PLACES is 1.
    """
    if not enabled() or len(ranked) < 2:
        return ranked
    places = named_places(analysis)
    if len(places) != 1:
        return ranked
    text = fold(getattr(analysis, "text", "") or "")
    if not any(word in text for word in _COUNT):
        return ranked
    if any(word in text for word in _NOT_HEADCOUNT):
        return ranked
    place = places[0]

    def title_of(table_id: str) -> str:
        table = index.by_key.get(table_id)
        if table is None:
            return ""
        edition = table.editions.get(getattr(analysis, "language", "is")) or table.editions.get("is")
        if edition is None and table.editions:
            edition = next(iter(table.editions.values()))
        return edition.title if edition is not None else ""

    def lists_place(table_id: str) -> bool:
        row = index._row_for(table_id)
        if row is None:
            return False
        terms = index.value_bm25.tf[row]
        title_terms = index.title_bm25.tf[row]
        return place in terms or place in title_terms

    pool = []
    for candidate in ranked:
        title = fold(title_of(candidate.table_id))
        if "sveitarfelag" not in title and "municipality" not in title:
            continue
        if not lists_place(candidate.table_id):
            continue
        penalty = sum(1 for marker in _BREAKDOWN if marker in title)
        pool.append((penalty, len(title), candidate))
    if not pool:
        return ranked
    pool.sort(key=lambda item: (item[0], item[1]))
    best = pool[0][2]
    if best is ranked[0]:
        return ranked
    return [best] + [candidate for candidate in ranked if candidate is not best]


def targets_for(word: str) -> tuple[str, ...]:
    """Catalogue labels for one question word, excluding the word's own lemma."""
    if not enabled() or not word:
        return ()
    _ensure()
    folded = fold(word)
    if folded in _LABELS:
        return ()
    return _FORMS.get(folded, ())


def extra_folded(tokens: list[str]) -> list[str]:
    if not enabled():
        return []
    _ensure()
    found: list[str] = []
    seen = set(tokens)
    for token in tokens:
        if fold(token) in _LABELS:
            continue
        for target in _FORMS.get(fold(token), ()):
            if target not in seen:
                seen.add(target)
                found.append(target)
    return found


@lru_cache(maxsize=100_000)
def target(word: str) -> str | None:
    """One label for the demonym hook. The shortest catalogue label wins."""
    found = targets_for(word)
    if not found:
        return None
    return min(found, key=len)
