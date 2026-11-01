"""Query aliases learned from catalogue titles and value labels.

A label such as "Capital (Reykjavík)" or "Eswatini (Swaziland)" puts two
names on the same line. The same value code in the other language does
too: "Höfuðborg" sits on the code whose English label is that gloss.
The colloquial word is expanded to the name. A longer label that
contains the word but not the name ("capital region", "capital
formation") blocks the expansion, so the single word is only rewritten
when the question did not already use the longer phrase.

Nothing here is copied from a question set. The pairs are counted on
the catalogue that was loaded.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from grund_lang.binaccess import is_opaque_name, lexicon_class
from grund_lang.fold import GENERIC, STOP, fold, words
from grund_lang.lemma import lemmatize_label

_VERSION = 1
_PAREN = re.compile(r"^([^()]{1,60}?)\s*\(([^()]{1,60})\)$")
_NAME = re.compile(r"^[A-ZÁÉÍÓÚÝÞÆÖÐ][A-Za-zÁÉÍÓÚÝÞÆÖÐáéíóúýþæöð.-]{3,}$")
_PLACE = {"þor", "örn", "göt", "gat", "bær", "ism", "lönd", "föð", "móð", "ætt"}

# source lemma -> target lemmas. Empty until install_from_tables runs.
_ALIASES: dict[str, tuple[str, ...]] = {}
# source lemma -> phrases that already name something else.
_BLOCKS: dict[str, tuple[frozenset[str], ...]] = {}


def aliases() -> dict[str, tuple[str, ...]]:
    return dict(_ALIASES)


def install(found: dict[str, tuple[str, ...]], blocks: dict[str, tuple[frozenset[str], ...]]) -> None:
    """Replace the alias table. An empty install leaves questions unchanged."""
    global _ALIASES, _BLOCKS
    _ALIASES = {key: tuple(values) for key, values in found.items() if values}
    _BLOCKS = {key: tuple(values) for key, values in blocks.items() if values}


def extra_lemmas(token_lemmas: list[str]) -> list[str]:
    """Names to add for a colloquial word, when no longer phrase already covers it."""
    if not _ALIASES:
        return []
    bag = {lemma for lemma in token_lemmas if lemma}
    added: list[str] = []
    for lemma in token_lemmas:
        targets = _ALIASES.get(lemma)
        if not targets:
            continue
        blocks = _BLOCKS.get(lemma, ())
        if any(len(block) >= 2 and block <= bag for block in blocks):
            continue
        for target in targets:
            if target not in bag and target not in added:
                added.append(target)
    return added


def _content(text: str) -> list[str]:
    found: list[str] = []
    for lemma in lemmatize_label(text or ""):
        if lemma in STOP or lemma in GENERIC or len(lemma) < 3 or lemma.isdigit():
            continue
        if lemma not in found:
            found.append(lemma)
    return found


def _acronym(token: str) -> bool:
    letters = token.replace("-", "")
    return len(letters) <= 5 and letters.isascii() and letters.isupper()


def _gloss_pairs(text: str) -> tuple[str, str] | None:
    """Head and parenthetical name, when the parenthesis is a proper name."""
    match = _PAREN.match((text or "").strip())
    if match is None:
        return None
    head, inner = match.group(1).strip(), match.group(2).strip()
    if " " in inner or _acronym(inner) or _NAME.match(inner) is None:
        return None
    if not head or len(head.split()) > 4:
        return None
    return head, inner


def _title_df(tables: list) -> Counter[str]:
    counts: Counter[str] = Counter()
    for table in tables:
        for edition in table.editions.values():
            seen = set(_content(edition.title or ""))
            for piece in getattr(edition, "path_texts", []) or []:
                seen.update(_content(piece))
            counts.update(seen)
    return counts


def _is_name(word: str) -> bool:
    """A place or a country. The folded lemma drops the accent, so try the surface too."""
    if not word:
        return False
    titled = word[:1].upper() + word[1:]
    for form in (word, titled):
        if is_opaque_name(form) or lexicon_class(form) in _PLACE:
            return True
    return False


def _name_lemmas(text: str, title_df: Counter[str]) -> list[str]:
    """Content lemmas of a gloss that are names, not ordinary or frequent words.

    "Reykjavík" is a town. "capital" titles many tables and is not the name.
    """
    kept: list[str] = []
    for word in words(text or ""):
        for lemma in _content(word):
            if lemma in kept:
                continue
            if _is_name(word) or _is_name(lemma):
                kept.append(lemma)
                continue
            if lexicon_class(word) == "alm" or lexicon_class(lemma) == "alm":
                continue
            if title_df[lemma] >= 8:
                continue
            kept.append(lemma)
    return kept


def mine(tables: list) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[frozenset[str], ...]]]:
    """Count glosses and aligned labels. Returns aliases and blocking phrases."""
    gloss_counts: Counter[tuple[str, str]] = Counter()
    labels: list[str] = []
    alignments: list[tuple[str, str]] = []
    for table in tables:
        for edition in table.editions.values():
            for text in (edition.title, *(getattr(edition, "path_texts", []) or [])):
                if text and _gloss_pairs(text):
                    gloss_counts[_gloss_pairs(text)] += 1
            for variable in edition.variables:
                for _code, label in variable.values:
                    text = str(label or "").strip()
                    if not text:
                        continue
                    labels.append(text)
                    pair = _gloss_pairs(text)
                    if pair:
                        gloss_counts[pair] += 1
        icelandic = table.editions.get("is")
        english = table.editions.get("en")
        if icelandic is None or english is None:
            continue
        other = {variable.code: variable for variable in english.variables}
        for variable in icelandic.variables:
            twin = other.get(variable.code)
            if twin is None:
                continue
            by_code = {code: str(label or "").strip() for code, label in twin.values}
            for code, label in variable.values:
                left = str(label or "").strip()
                right = by_code.get(code, "")
                if left and right and left != right:
                    alignments.append((left, right))

    accepted = {pair for pair, count in gloss_counts.items() if count >= 3}
    # The full label, as stored, points at the name inside the parentheses.
    gloss_targets: dict[str, list[str]] = {}
    title_df = _title_df(tables)
    for head, inner in accepted:
        gloss_targets[f"{head} ({inner})"] = _name_lemmas(inner, title_df)
    votes: dict[str, Counter[str]] = defaultdict(Counter)

    def add_vote(source: str, targets: list[str], times: int) -> None:
        if not source or source in STOP or source in GENERIC or len(source) < 4:
            return
        kept = [target for target in targets if target and target != source]
        if not kept:
            return
        for target in kept:
            votes[source][target] += times

    for head, inner in accepted:
        head_lemmas = _content(head)
        inner_lemmas = _name_lemmas(inner, title_df)
        head_names = _name_lemmas(head, title_df)
        times = gloss_counts[(head, inner)]
        if len(head_lemmas) == 1:
            add_vote(head_lemmas[0], inner_lemmas, times)
        if len(inner_lemmas) == 1:
            add_vote(inner_lemmas[0], head_names, times)

    # A one-word label on the same code as an accepted gloss inherits the name.
    # "Höfuðborg" is the Icelandic line for "Capital (Reykjavík)".
    for left, right in alignments:
        for source_text, other_text in ((left, right), (right, left)):
            if other_text not in gloss_targets:
                continue
            source = _content(source_text)
            if len(source) != 1:
                continue
            add_vote(source[0], gloss_targets[other_text], 1)

    found: dict[str, tuple[str, ...]] = {}
    for source, counter in votes.items():
        total = sum(counter.values())
        target, count = counter.most_common(1)[0]
        if total <= 0 or count / total < 0.6:
            continue
        # A parenthetical gloss needs three labels. A word that only occurs
        # as the other language's line for such a gloss can pass on one table.
        if count < 3 and total != count:
            continue
        extras = [lemma for lemma, seen in counter.most_common() if seen == count and lemma != source]
        found[source] = tuple(extras[:3])

    blocks: dict[str, Counter[frozenset[str]]] = defaultdict(Counter)
    interesting = set(found)
    if interesting:
        seen_labels: Counter[tuple[str, ...]] = Counter()
        for text in labels:
            folded = fold(text)
            if not any(source in folded or source in text.lower() for source in interesting):
                # lemmatize only labels that can contain an alias source
                continue
            lemmas = _content(text)
            if len(lemmas) < 2:
                continue
            key = tuple(lemmas)
            seen_labels[key] += 1
        for lemmas, count in seen_labels.items():
            if count < 3:
                continue
            bag = frozenset(lemmas)
            for source, targets in found.items():
                if source not in bag or any(target in bag for target in targets):
                    continue
                blocks[source][bag] += count
    packed = {source: tuple(counter.keys()) for source, counter in blocks.items()}
    return found, packed


def install_from_tables(tables: list, cache: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Mine the catalogue, or read a cache written for this same alias version."""
    if cache is not None and Path(cache).exists():
        try:
            payload = json.loads(Path(cache).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("version") == _VERSION:
            found = {key: tuple(values) for key, values in (payload.get("aliases") or {}).items()}
            blocks = {
                key: tuple(frozenset(phrase) for phrase in phrases)
                for key, phrases in (payload.get("blocks") or {}).items()
            }
            install(found, blocks)
            return found
    found, blocks = mine(tables)
    install(found, blocks)
    if cache is not None:
        payload = {
            "version": _VERSION,
            "aliases": {key: list(values) for key, values in found.items()},
            "blocks": {key: [sorted(phrase) for phrase in phrases] for key, phrases in blocks.items()},
        }
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        Path(cache).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return found
