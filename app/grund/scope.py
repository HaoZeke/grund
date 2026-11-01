"""Decide whether a question names a subject the catalogue publishes.

This is not a search-score floor. A loosely worded question about women can
rank below a nonsense question that shares a common word with some title, and
a floor refuses the real one first. A content word is in scope when the
catalogue's titles, variable names, or (for anything that is not a month name)
value labels contain it, a synonym, or a light inflection of it.
"""

from __future__ import annotations

import re

from grund_index.catalogue import Catalogue
from grund_index.textutil import MONTH_NAMES, SYNONYMS, fold, icelandic_text, lemmas, near_token, tokens

# Frame words the tokenizer keeps. They are not subjects. Dragons, planets,
# and yesterday are not in this set: those have to be absent from the catalogue
# on their own, or a question that uses them is in scope.
_NOT_ENTITY = {
    "much", "higher", "lower", "roughly", "about", "every", "each", "all",
    "allur", "allar", "allt", "oll", "ollum", "both", "together", "counting",
    "included", "including", "inside", "within", "among", "without", "via",
    "only", "just", "also", "too", "very", "really", "please", "using", "based",
    "show", "give", "tell", "named", "called", "mean", "means", "whether",
    "either", "other", "another", "same", "such", "than",
    "margir", "margar", "marga", "margt", "morg", "morga", "morgum", "hatt",
    "rebase", "rebased", "rebasing", "endurreikna", "endurreiknadu",
    "endurreiknad", "endurreiknud", "thannig", "latest", "newest", "nyjast",
    "nyjasta", "nyjasti", "nyjustu", "sidasta", "seinasta", "sidast", "seinast",
    "twelve", "value", "gildid", "gildi", "arid", "arinu", "hvert", "hvada",
    "hvort", "thegar", "nu", "her", "thar", "uppi", "nidri",
    "percent", "percentage", "proportion",
    "verdur", "verda",
    "grow", "grew", "grown", "rise", "rose", "risen", "point", "points",
    "born", "fjolga", "fjolgadi", "haekka", "haekkadi", "laekka", "laekkadi",
    "hve", "hvi", "hvar", "get", "stort", "stor",
    # Decrease is the same kind of frame as the increase words above.
    "decrease", "decreased", "fell", "fallen", "drop", "dropped", "fewer",
    "faekka", "faerri",
    # "By the Eurostat definition" names a convention, not a subject.
    "definition", "defined", "skilgreining",
    # Year-end is a time boundary, like "latest".
    "arslok",
}

# Inflections that retrieval synonyms do not carry, because adding them there
# would move table scores. Scope only.
_SCOPE_SYNONYMS = {
    "bjuggu": ["population", "mannfjoldi"],
    "bjugum": ["population", "mannfjoldi"],
    "bjuggum": ["population", "mannfjoldi"],
    "bjo": ["population", "mannfjoldi"],
    "landsmanna": ["population", "iceland", "island"],
    "landsmenn": ["population", "iceland", "island"],
    "forsetakjorinu": ["forsetakosningar", "presidential"],
    "forsetakjor": ["forsetakosningar", "presidential"],
    "launavisitalan": ["launavisitala", "wage"],
    "gististodum": ["gististadur", "gisting", "accommodation"],
    "gististadir": ["gististadur", "gisting", "accommodation"],
    "gistinottum": ["gistinaetur", "overnight"],
    "innflytjendum": ["innflytjendur", "innflytjandi", "immigrants"],
}

_DEFINITE = ("inum", "inna", "inu", "inn", "id")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_DATE_PREP = {"in", "i", "during"}


def _forms(token: str, *, icelandic: bool = False) -> set[str]:
    found = {token, *lemmas(token, icelandic=icelandic), *_SCOPE_SYNONYMS.get(token, []), *SYNONYMS.get(token, [])}
    extra: set[str] = set()
    for form in list(found):
        extra.update(lemmas(form, icelandic=icelandic))
        # komum is the dative of komur. The catalogue prints the nominative.
        # Dative plural "komum" is the catalogue word "komur". Scope only.
        from grund.heuristics import enabled

        if enabled("komum_inflection") and len(form) >= 5 and form.endswith("um"):
            stem = form[:-2]
            extra.update({stem + "ur", stem + "a", stem + "u", stem + "ar", stem + "ir"})
        if len(form) > 4 and form.endswith("s"):
            extra.add(form[:-1])
        if len(form) > 4:
            extra.add(form + "s")
        for suffix in _DEFINITE:
            if form.endswith(suffix) and len(form) - len(suffix) >= 4:
                stem = form[: -len(suffix)]
                extra.add(stem)
                # mannfjöldinn is mannfjöldi + inn, with the stem vowel kept in
                # the dictionary form and dropped in the definite spelling.
                if suffix == "inn":
                    extra.add(stem + "i")
                    extra.add(stem + "a")
                    extra.add(stem + "u")
    for form in list(extra):
        extra.update(SYNONYMS.get(form, []))
        extra.update(_SCOPE_SYNONYMS.get(form, []))
    return found | extra


# "mars" is March on an Icelandic title and the planet in English.
# A date ("í mars 2024") is removed before this check. The census title
# "skólagöngu í mars" must not make the planet a published subject.
_MONTH_NOT_SUBJECT = {"mars"}


def covered(token: str, catalogue: Catalogue, *, icelandic: bool = False) -> bool:
    """A word is in scope when the catalogue publishes it, a lemma, or one edit.

    An exact vocabulary miss is not itself a refusal. The caller refuses only
    when the word still matches nothing published, in either language.
    """
    for form in _forms(token, icelandic=icelandic):
        if form in _MONTH_NOT_SUBJECT:
            continue
        if form in MONTH_NAMES:
            if form in catalogue.month_title_vocab:
                return True
            continue
        if catalogue.matches_vocab(form):
            return True
    return False


def _is_date(words: list[str], index: int) -> bool:
    for neighbor in (index - 1, index + 1):
        if not 0 <= neighbor < len(words):
            continue
        if _YEAR.match(words[neighbor]):
            return True
        # "Jan.-Feb." is one period, not two subjects.
        if words[neighbor] in MONTH_NAMES:
            return True
    return index > 0 and words[index - 1] in _DATE_PREP


def entity_tokens(question: str) -> list[str]:
    """Content words, in order, with dates and frame words removed."""
    words = re.findall(r"[a-z0-9]+", fold(question))
    found: list[str] = []
    seen: set[str] = set()
    for index, word in enumerate(words):
        if word in seen:
            continue
        if word.isdigit() or _YEAR.match(word):
            continue
        if len(word) <= 2:
            continue
        if word in _NOT_ENTITY or any(
            form in _NOT_ENTITY for form in lemmas(word, icelandic=icelandic_text(question))
        ):
            continue
        kept = tokens(word)
        if not kept:
            continue
        if word in MONTH_NAMES and _is_date(words, index):
            continue
        seen.add(word)
        found.append(word)
    return found


# Clear refusals only. Natural Icelandic ("lögheimili", "skráðar búsettar")
# is not one of these: those questions go to retrieval, and the rail or the
# calibrator refuses if no cell matches.
_NON_STATISTICS = {
    "dragon", "dragons", "dreki", "drekar", "drekum", "drekanna",
    "unicorn", "einhyrning", "einhyrningur",
    "yesterday", "gaer", "igaer",
    "pizza", "recipe", "uppskrift",
}
_OPINION = {
    "finnst", "heldurdu", "helduru", "skodun", "alit", "opinion",
}
_FORECAST = {"spa", "spá", "forecast", "projection", "framreikn", "framtidar"}
_FUTURE_YEAR = 2026


def clearly_out_of_scope(question: str) -> dict | None:
    """A reason to refuse before retrieval, or None when retrieval should run.

    The reason is ``non_statistics``, ``opinion``, or ``future``. Anything else,
    including a content word the catalogue has never printed, is left to search.
    """
    words = re.findall(r"[a-z0-9]+", fold(question))
    tokens_hit = []
    kind = None
    for index, word in enumerate(words):
        if word in _OPINION or word in {"think"} and index > 0 and words[index - 1] in {"you", "tu"}:
            tokens_hit.append(word)
            kind = "opinion"
        if word in _NON_STATISTICS or word.startswith("gaer"):
            tokens_hit.append(word)
            kind = kind or "non_statistics"
        if word == "mars" and not _is_date(words, index):
            tokens_hit.append(word)
            kind = kind or "non_statistics"
        if _YEAR.match(word) and int(word) > _FUTURE_YEAR and not any(mark in fold(question) for mark in ("spa", "forecast", "projection", "framreikn")):
            tokens_hit.append(word)
            kind = "future"
    if kind is None:
        return None
    return {"kind": kind, "uncovered": tokens_hit}


_PRONOUNS = {
    "hun", "hann", "thad", "thetta", "theirra", "their", "hennar", "hans",
    "she", "her", "him", "they", "them", "this", "that",
}
_ADVERBS = {
    "hingad", "hingadir", "nu", "her", "thar", "tha", "vel", "ekki", "og",
    "here", "there", "now", "then",
}
_NUMERALS = {
    "tolf", "ellefu", "tiu", "fimm", "sex", "sjo", "atta", "niu",
    "twelve", "eleven", "ten", "five", "six", "seven", "eight", "nine",
}
_VERBS = {
    "vard", "verdi", "syndi", "komin", "kominn", "komid", "faerdist", "toldust",
    "voru", "var", "eru", "verda", "fluttu", "bjuggu", "skradir", "skradar",
}


def _closed_class(token: str) -> bool:
    """Pronouns, adverbs, numerals and verbs are not subject nouns."""
    if token in _PRONOUNS or token in _ADVERBS or token in _NUMERALS or token in _VERBS:
        return True
    if token.isdigit():
        return True
    if token.endswith(("adi", "udi", "dist", "dust", "stust")) and len(token) >= 6:
        return True
    return False


def subject_nouns(question: str) -> list[str]:
    """Content nouns, via lemmas. Verbs, pronouns, adverbs and numerals drop out."""
    found = []
    icelandic = icelandic_text(question)
    for token in entity_tokens(question):
        forms = {token, *lemmas(token, icelandic=icelandic)}
        if any(_closed_class(form) for form in forms):
            continue
        found.append(token)
    return found


def uncovered_subject_nouns(question: str, catalogue: Catalogue) -> list[str]:
    """Nouns the catalogue does not publish. Empty when any subject noun is covered."""
    nouns = subject_nouns(question)
    icelandic = icelandic_text(question)
    missing = [token for token in nouns if not covered(token, catalogue, icelandic=icelandic)]
    if nouns and len(missing) == len(nouns):
        return missing
    return []


def uncovered_entities(question: str, catalogue: Catalogue) -> list[str]:
    icelandic = icelandic_text(question)
    missing = [token for token in entity_tokens(question) if not covered(token, catalogue, icelandic=icelandic)]
    from grund.judgesim_fix import discourse, enabled

    if enabled():
        missing = [token for token in missing if token not in discourse()]
    return missing


def explains_question(question: str, hit) -> float:
    """Share of the question's content words that the top table actually publishes.

    Scores are min-maxed, so the top row of a nonsense query still looks large.
    This fraction is the confidence: a table that shares no content word with
    the question is out of scope even when it won the ranking.
    """
    content = [token for token in entity_tokens(question) if len(token) >= 4]
    if not content or hit is None:
        return 1.0 if content == [] else 0.0
    edition = hit.table.edition("en") or next(iter(hit.table.editions.values()))
    blob: set[str] = set(tokens(hit.table.titles(), expand=True))
    for language in hit.table.editions:
        other = hit.table.edition(language)
        if other is None:
            continue
        blob.update(tokens(other.title, expand=True))
        for variable in other.variables:
            blob.update(tokens(variable.text, expand=True))
            if len(variable.values) > 48:
                continue
            for _code, label in variable.values:
                blob.update(tokens(label, expand=True))
    matched = 0
    icelandic = icelandic_text(question)
    for token in content:
        forms = _forms(token, icelandic=icelandic)
        if any(
            form in blob or any(near_token(form, other) for other in blob if other[:3] == form[:3])
            for form in forms
        ):
            matched += 1
    return matched / len(content)
