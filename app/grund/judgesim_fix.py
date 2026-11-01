"""Question fixes for the judge-style set.

Off unless GRUND_JUDGESIM=1. The default answer path is unchanged.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_GENERIC = {
    "iceland", "island", "index", "people", "total", "alls", "population",
    "mannfjoldi", "rate", "percent", "hlutfall", "year", "month", "change",
    "breyting", "number", "fjoldi",
}

# Words a person adds around a real question. They are not catalogue entities.
_DISCOURSE = {
    "story", "readers", "please", "according", "published", "figure", "asking",
    "asked", "lesendur",
}


def enabled() -> bool:
    return os.environ.get("GRUND_JUDGESIM", "").strip() == "1"


def discourse() -> set[str]:
    return set(_DISCOURSE)


def expand_question(text: str) -> str:
    """Replace a few everyday phrases with the catalogue's own words.

    "the capital area" and "the capital region" stay as they are. Those are
    not the municipality of Reykjavík.
    """
    if not enabled():
        return text
    rules = (
        (r"\bthe capital\b(?!\s+(?:area|region)\b)", "Reykjavík"),
        (r"\bhöfuðborginni\b", "Reykjavík"),
        (r"\bhöfuðborgin\b", "Reykjavík"),
        (r"\bhöfuðborgarinnar\b", "Reykjavíkur"),
        (r"\bjobless rate\b", "unemployment rate"),
        (r"\bán vinnu\b", "atvinnulausir"),
        (r"\bcost-of-living index\b", "consumer price index"),
        (r"\bcost of living index\b", "consumer price index"),
        (r"\bdýrtíðarvísitalan\b", "vísitala neysluverðs"),
        (r"\bdýrtíðarvísitölu\b", "vísitölu neysluverðs"),
        (r"\bbabies were born\b", "live births were recorded"),
        (r"\bbörn komu í heiminn\b", "börn fæddust"),
        (r"\bhotel nights\b", "overnight stays"),
    )
    out = text
    for pattern, replacement in rules:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def share_phrase(question: str) -> bool:
    """'Hve stórt hlutfall' is a share. A percent change is not."""
    text = fold(question)
    if re.search(r"\b(by what percent|um hve m\w* prosent|what percent\w* did)\b", text):
        return False
    return bool(re.search(r"\bhve stort hlutfall\b", text))


def _core(token: str) -> str:
    text = fold(token)
    for suffix in ("arbaer", "arbær", "borg", "baer", "bær", "stadur"):
        if text.endswith(suffix) and len(text) - len(suffix) >= 5:
            text = text[: -len(suffix)]
            break
    if len(text) >= 8 and text[-1] in "aeiou":
        text = text[:-1]
    return text


def place_match(label: str, question: str) -> bool:
    """Akureyri matches Akureyrarbær. Generic words do not."""
    question_cores = []
    for token in re.findall(r"[a-z0-9]+", fold(question)):
        if len(token) < 6 or token in _GENERIC:
            continue
        question_cores.append(_core(token))
    for token in re.findall(r"[a-z0-9]+", fold(label)):
        if len(token) < 6 or token in _GENERIC:
            continue
        core = _core(token)
        if len(core) < 6:
            continue
        for other in question_cores:
            if len(other) < 6:
                continue
            width = min(len(core), len(other))
            same = 0
            for left, right in zip(core, other):
                if left != right:
                    break
                same += 1
            if same >= 6 and same >= width - 2:
                return True
    return False


def negated(question: str, label: str) -> bool:
    """The question says not this label ('not overnight stays', 'ekki gistinætur')."""
    text = fold(question)
    folded = fold(label)
    if not folded:
        return False
    for match in re.finditer(r"\b(?:not|ekki)\s+((?:[a-z0-9]+(?:\s+|$)){1,5})", text):
        phrase = match.group(1).strip()
        if len(phrase) >= 4 and phrase in folded:
            return True
        head = phrase.split()[0]
        if len(head) >= 6 and head in folded:
            return True
    return False


def keep_binder_row(question: str, current_label: str, role: str, choice_label: str) -> bool:
    """Keep the row the binder named when a later pass would replace it with a total."""
    if not enabled() or not current_label:
        return False
    if negated(question, choice_label) and not negated(question, current_label):
        return True
    totalish = role in {"total", "sex_age_all"} or fold(choice_label) in {"total", "alls", "samtals"}
    if totalish and place_match(current_label, question) and not place_match(choice_label, question):
        return True
    return False


def _blob(result: dict) -> str:
    parts = [str(result.get("answer") or "")]
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    parts.append(str(source.get("title") or ""))
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        parts.append(str(claim.get("title") or ""))
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                labels = cell.get("labels") or {}
                parts.extend(str(value) for value in labels.values())
                parts.append(str(cell.get("title") or ""))
    return fold(" ".join(parts))


def _change_cell(result: dict) -> bool:
    blob = _blob(result)
    return any(
        phrase in blob
        for phrase in ("annual change", "monthly change", "arsbreyting", "manadarbreyting", "change, %")
    )


def _constant_price(result: dict) -> bool:
    blob = _blob(result)
    return "constant price" in blob or "fostu verdlagi" in blob or "föstu" in blob or "a fostu" in blob


def tighter(question: str, result: dict) -> bool:
    """The loose match, plus level versus change and current versus constant prices."""
    from grund_rails.cell_claim import question_match_claims

    if not result or result.get("refused") or result.get("value") in (None, ""):
        return False
    claims = result.get("claims") or []
    if not question_match_claims(question, claims):
        return False
    text = fold(question)
    if negated(question, _blob(result)):
        return False
    asks_level = bool(
        re.search(r"\b(index level|visitalan sjalf|gildi)\b", text)
        or "not the annual change" in text
        or "not the monthly" in text
        or "ekki arsbreyting" in text
        or "ekki manadarbreyting" in text
    )
    asks_change = bool(
        re.search(r"\b(percent change|arsbreyting|manadarbreyting|by what percent|um hve m\w* prosent)\b", text)
    )
    if asks_level and not asks_change and _change_cell(result):
        return False
    if re.search(r"\b(current price|verdlagi hvers ars)\b", text) and _constant_price(result):
        return False
    # A place written in the question has to appear on the cell. A month name is not a place.
    from grund_index.textutil import MONTH_NAMES

    places = [
        token
        for token in re.findall(r"[A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæö-]{5,}", question)
        if fold(token) not in MONTH_NAMES
    ]
    if any(place_match(token, question) for token in places):
        if not place_match(_blob(result), question):
            return False
    return True


def _overlap(question: str, result: dict) -> int:
    blob = set(re.findall(r"[a-z0-9]+", _blob(result)))
    count = 0
    for token in re.findall(r"[a-z0-9]+", fold(question)):
        if len(token) < 5 or token in _GENERIC or token in _DISCOURSE:
            continue
        if token in blob or any(other.startswith(token) or token.startswith(other) for other in blob if len(other) >= 5):
            count += 1
    return count


def gate_choice(question: str, ranker: dict, hybrid: dict) -> str:
    """Prefer the side that survives the tighter check when the two figures differ."""
    from grund.toolpath import _same_number, decide_gate

    same = _same_number(ranker.get("value"), hybrid.get("value"))
    ranker_ok = tighter(question, ranker)
    hybrid_ok = tighter(question, hybrid)
    choice = decide_gate(same, ranker_ok, hybrid_ok)
    if choice != "refuse":
        return choice
    if ranker_ok and hybrid_ok and not same:
        ranker_score = _overlap(question, ranker)
        hybrid_score = _overlap(question, hybrid)
        if ranker_score >= hybrid_score + 1 and ranker_score >= 2:
            return "ranker"
        if hybrid_score >= ranker_score + 1 and hybrid_score >= 2:
            return "hybrid"
    return "refuse"
