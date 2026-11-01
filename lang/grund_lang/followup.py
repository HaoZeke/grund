"""Carry the previous turn's wording into a pronominal follow-up.

``hún`` and ``það`` do not name a table. When the question has a pronoun
and no noun of its own, the previous question is placed in front of it
so the ranker still sees the topic. A question that already names a
noun is left unchanged.
"""

from __future__ import annotations

import re

from grund_lang.fold import fold

_PRONOUNS = {"hun", "hann", "tad", "thad", "tetta", "thetta", "pad", "she", "he"}
_WORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÝÞÆÖÐáéíóúýþæöð]+")


def _has_pronoun(question: str) -> bool:
    for word in _WORD.findall(question or ""):
        if fold(word) in _PRONOUNS:
            return True
    return False


def with_context(context: str | None, question: str) -> str:
    """Return ``question``, or the previous turn plus ``question``."""
    import os

    if os.environ.get("GRUND_FOLLOWUP", "0") == "0":
        return question
    if not context or not question or not _has_pronoun(question):
        return question
    from grund_lang.lemma import analyze

    parsed = analyze(question)
    nouns = [
        token
        for token in parsed.tokens
        if token.pos in {"noun", "propn"} and len(token.lemma) > 3 and token.lemma not in _PRONOUNS
    ]
    if nouns:
        return question
    return context.rstrip(" ?.") + ". " + question
