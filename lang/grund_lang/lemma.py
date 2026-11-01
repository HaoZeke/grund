"""Lemmas and parts of speech for a question or a catalogue label.

Icelandic goes through the parser when it is installed: the parser supplies
one lemma and one tag for the word in the sentence. A word the parser does
not know is looked up in the inflection database, then in the lemmatizer
that needs a tag, then reduced by a case ending. English uses a short
irregular list and a plural or past ending. The same function lemmatizes
catalogue labels, so the two sides meet.
"""

from __future__ import annotations

import re
from functools import lru_cache

from grund_lang.binaccess import known_lemma, lexicon_lemma
from grund_lang.bridge import detect_concepts, expand_terms
from grund_lang.compound import split_compound
from grund_lang.dates import find_bases, parse_dates
from grund_lang.fold import STOP, fold, words
from grund_lang.numbers import parse_numbers
from grund_lang.types import Analysis, CompoundSplit, Token

_IS_CHARS = set("ðþæöáéíóúý")
_IS_FUNCTION = {
    "og", "í", "á", "hve", "hver", "hvað", "var", "voru", "eru", "sem", "fyrir",
    "ekki", "frá", "til", "með", "við", "eftir", "árið", "íslandi", "hversu",
    "þetta", "það", "eða", "en", "um", "af",
}
_EN_IRREGULAR = {
    "lived": "live", "lives": "live", "living": "live",
    "moved": "move", "moves": "move", "moving": "move",
    "born": "born", "women": "woman", "men": "man",
    "children": "child", "indices": "index", "was": "be", "were": "be",
    "did": "do", "gone": "go", "went": "go",
}
_CASE = ("inum", "unum", "anna", "um", "ar", "ir", "ur", "inn", "an", "i", "a")
_NEFNIR_TAGS = (
    "nven", "nveo", "nveþ", "nvee", "nvfn", "nken", "nkeo", "nkeþ", "nkee",
    "nhen", "nheo", "nheþ", "nhee", "sfg3eþ", "sfg3fþ", "sng", "lkensf",
)
# init() rereads the rule file. One successful call is enough.
_NEFNIR_READY = False
_POS_FROM_CAT = {
    "no": "noun", "kk": "noun", "kvk": "noun", "hk": "noun",
    "so": "verb", "lo": "adj", "ao": "adv", "fs": "adp",
    "fn": "pron", "st": "conj", "nhm": "verb",
    "tala": "num", "ártal": "num", "töl": "num",
    "person": "propn", "entity": "propn",
}
_GREYNIR = None
_GREYNIR_MISSING = object()


def detect_language(text: str) -> str:
    lowered = text.lower()
    if any(ch in lowered for ch in _IS_CHARS):
        return "is"
    hits = 0
    for word in re.findall(r"[a-záðþæöéíóúý]+", lowered):
        if word in _IS_FUNCTION:
            hits += 1
    return "is" if hits >= 2 else "en"


def _parser():
    global _GREYNIR
    if _GREYNIR is _GREYNIR_MISSING:
        return None
    if _GREYNIR is not None:
        return _GREYNIR
    try:
        from reynir import Greynir

        _GREYNIR = Greynir()
    except Exception:
        _GREYNIR = _GREYNIR_MISSING
        return None
    return _GREYNIR


def _suffix_lemma(token: str) -> str | None:
    """One case ending off a long token, kept only when the stem is a known lemma."""
    folded = fold(token)
    if folded.endswith("andi") and len(folded) >= 9:
        return folded[:-4] + "andi"
    for ending in ("endum", "endur", "enda"):
        if folded.endswith(ending) and len(folded) - len(ending) >= 5:
            return folded[: -len(ending)] + "andi"
    for ending in _CASE:
        if folded.endswith(ending) and len(folded) - len(ending) >= 5:
            stem = folded[: -len(ending)]
            surface_stem = token[: len(token) - len(ending)]
            if known_lemma(surface_stem) or known_lemma(stem):
                return fold(real_surface(surface_stem) or stem)
            return stem
    if len(folded) >= 10 and folded.endswith("n") and folded[-2] in "aeiou":
        return folded[:-1]
    return None


def real_surface(word: str) -> str | None:
    found = lexicon_lemma(word)
    if found is None:
        return None
    return found[0]


def _nefnir_lemma(token: str) -> str | None:
    global _NEFNIR_READY
    try:
        from nefnir import init, lemmatize
    except Exception:
        return None
    try:
        if not _NEFNIR_READY:
            init()
            _NEFNIR_READY = True
    except Exception:
        return None
    for tag in _NEFNIR_TAGS:
        try:
            lemma = lemmatize(token, tag)
        except Exception:
            continue
        if not lemma or fold(lemma) == fold(token):
            continue
        if known_lemma(lemma) or (len(lemma) >= 4 and fold(token).startswith(fold(lemma))):
            return lemma
    return None


@lru_cache(maxsize=100_000)
def lemmatize_token(token: str, language: str = "is", *, deep: bool = True) -> tuple[str, str, str, str]:
    """Return folded lemma, surface lemma, coarse pos, and which tool produced it.

    `deep` asks the tag-based lemmatizer after the dictionary. Catalogue
    labels leave it off: one unknown string would otherwise be tried against
    every ordinary tag, and a label list has tens of thousands of them.
    """
    if token.isdigit():
        return token, token, "num", "surface"
    found = lexicon_lemma(token)
    if found is not None:
        surface, pos = found
        return fold(surface), surface, pos, "bin"
    if language != "is" and not any(ch in token.lower() for ch in _IS_CHARS):
        irregular = _EN_IRREGULAR.get(token.lower())
        if irregular:
            return irregular, irregular, "other", "irregular"
        lemma = _english_lemma(token.lower())
        return lemma, lemma, "other", "english"
    if not deep:
        stem = _suffix_lemma(token)
        if stem:
            return stem, stem, "noun", "suffix"
        return fold(token), token, "other", "surface"
    guessed = _nefnir_lemma(token)
    if guessed:
        pos = "verb" if fold(guessed) != fold(token) and token.lower().endswith(("di", "ðu", "u")) else "noun"
        return fold(guessed), guessed, pos, "nefnir"
    stem = _suffix_lemma(token)
    if stem:
        return stem, stem, "noun", "suffix"
    return fold(token), token, "other", "surface"


def _english_lemma(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        if len(stem) > 3 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def lemmatize_label(text: str) -> list[str]:
    """Folded lemmas and surfaces of a catalogue label. No sentence parse."""
    found: list[str] = []
    for word in words(text):
        if word.isdigit():
            if len(word) == 4 and word.startswith(("19", "20")):
                found.append(word)
            continue
        folded = fold(word)
        language = "is" if any(ch in word.lower() for ch in _IS_CHARS) else "en"
        if language == "en" and folded in STOP:
            continue
        lemma, _surface, _pos, _source = lemmatize_token(word, language, deep=False)
        for piece in (folded, lemma):
            if len(piece) > 2 and piece not in STOP and piece not in found:
                found.append(piece)
        if language == "is" and len(word) >= 8:
            for part in split_compound(word):
                if part not in STOP and part not in found and len(part) > 2:
                    found.append(part)
    return found


def _content_terms(tokens: list[Token], compounds: list[CompoundSplit]) -> list[str]:
    terms: list[str] = []
    for token in tokens:
        if token.pos in {"adp", "conj", "punct", "pron"}:
            continue
        for piece in (token.lemma, token.folded):
            if len(piece) > 2 and piece not in STOP and not piece.isdigit() and piece not in terms:
                terms.append(piece)
    for compound in compounds:
        for part in compound.parts:
            if part not in STOP and part not in terms and len(part) > 2:
                terms.append(part)
    return terms


def _from_parser(text: str) -> list[Token] | None:
    parser = _parser()
    if parser is None:
        return None
    try:
        job = parser.parse(text)
    except Exception:
        return None
    sentences = job.get("sentences") if hasattr(job, "get") else None
    if not sentences:
        return None
    tokens: list[Token] = []
    parsed = False
    for sentence in sentences:
        terminals = getattr(sentence, "terminals", None) or []
        if getattr(sentence, "tree", None) is not None:
            parsed = True
        tags = list(getattr(sentence, "ifd_tags", []) or [])
        for index, terminal in enumerate(terminals):
            surface = getattr(terminal, "text", "") or ""
            if not surface or surface in "?.!,;:":
                continue
            lemma_surface = getattr(terminal, "lemma", None) or surface
            category = getattr(terminal, "category", "") or ""
            pos = _POS_FROM_CAT.get(category, "other")
            tag = tags[index] if index < len(tags) else ""
            if not getattr(terminal, "lemma", None):
                folded, lemma_surface, pos, source = lemmatize_token(surface, "is")
                tokens.append(Token(surface, fold(surface), folded, lemma_surface, pos, tag, source))
                continue
            tokens.append(
                Token(
                    surface=surface,
                    folded=fold(surface),
                    lemma=fold(lemma_surface),
                    lemma_surface=lemma_surface,
                    pos=pos,
                    tag=tag,
                    source="parser",
                )
            )
    if not parsed or not tokens:
        return None
    return tokens


def _from_words(text: str, language: str) -> list[Token]:
    tokens: list[Token] = []
    for word in words(text):
        if not word or (word.isdigit() and len(word) != 4):
            if word.isdigit():
                tokens.append(Token(word, word, word, word, "num", "", "surface"))
            continue
        lemma, surface, pos, source = lemmatize_token(word, language)
        tokens.append(Token(word, fold(word), lemma, surface, pos, "", source))
    return tokens


def analyze(text: str) -> Analysis:
    """Lemmas, parts of speech, compounds, numbers, dates, and bridged concepts."""
    language = detect_language(text)
    tokens = _from_parser(text) if language == "is" else None
    if tokens is None:
        tokens = _from_words(text, language)
    compounds: list[CompoundSplit] = []
    if language == "is":
        for token in tokens:
            if token.pos == "num" or len(token.surface) < 8:
                continue
            parts = split_compound(token.lemma_surface or token.surface)
            if parts:
                compounds.append(CompoundSplit(token.surface, parts))
    analysis = Analysis(
        text=text,
        language=language,
        tokens=tokens,
        compounds=compounds,
        numbers=parse_numbers(text, language),
        dates=parse_dates(text),
        bases=find_bases(text),
    )
    analysis.concepts = detect_concepts(analysis)
    analysis.terms = expand_terms(analysis, _content_terms(tokens, compounds))
    # Colloquial names learned from the catalogue. Compound parts are not
    # rewritten: höfuðborgarsvæði must not become the city inside the region.
    from grund_lang.rewrite import extra_lemmas

    for lemma in extra_lemmas([token.lemma for token in analysis.tokens]):
        if lemma not in analysis.terms:
            analysis.terms.append(lemma)
    from grund_lang.lexicon import demonym_target, extra_lemmas as lexicon_lemmas

    for lemma in lexicon_lemmas([token.lemma for token in analysis.tokens]):
        if lemma not in analysis.terms:
            analysis.terms.append(lemma)
    for token in analysis.tokens:
        place = demonym_target(token.lemma_surface or token.surface)
        if place and place not in analysis.terms:
            analysis.terms.append(place)
    return analysis
