"""A share question is a ratio of two cells, not a number to invent.

The part and the total come from the same variable on the headline series.
The percent is `(part / whole) * 100`, recomputed from those cells. Nothing
in this module stores a percent of its own.
"""

from __future__ import annotations

import re

from grund_lang.fold import fold

# A pasted title that begins "what was Percentage of ..." is a level.
# A published rate asked as "what was the unemployment rate" is a level.
_LEVEL_OPENERS = ("what was", "hver var", "hvert var", "hvad var")
_CHANGE = (
    "by what percent",
    "um hve m",
    "percent change",
    "prosentubreyting",
    "haekk",
    "laekk",
    "increas",
    "decreas",
    "breyting",
)


def is_ratio_question(text: str) -> bool:
    """True when the question asks what fraction one named part is of a whole.

    "What proportion of overnight stays were by residents" is a ratio.
    "What was the unemployment rate" is a published rate, and "by what
    percentage did it rise" is a change. Those stay on their own operations.
    """
    folded = fold(text)
    if any(piece in folded for piece in _CHANGE) and re.search(r"prosent|percent", folded):
        return False
    if folded.startswith(_LEVEL_OPENERS) and not re.search(
        r"\b(what percentage|what proportion|what share|what percent of)\b",
        folded,
    ):
        return False
    patterns = (
        r"\b(hve|hversu)\s+\S+\s+hlutfall\b",
        r"\bhlutfall\b.{0,80}\b(voru|eru|var|sem)\b",
        r"\bwhat\s+(share|proportion|percentage|percent)\s+of\b",
        r"\b(share|proportion|percentage)\s+of\b",
        r"\bpercent\s+of\b.{0,80}\b(were|are|was|is)\b",
        r"\b(prosent|percent)\b.{0,50}\b(voru|were)\b",
    )
    return any(re.search(pattern, folded) for pattern in patterns)


def ratio_members(edition, analysis):
    """The named part and the total on the variable that actually encodes the part.

    Returns `(variable_code, part_code, whole_code)` or None when the question
    does not name a subgroup the table can split. A weak overlap is not a part:
    answering with the total count would not be a ratio.
    """
    from grund_lang.values import _is_total, bind_dimension

    title = getattr(edition, "title", "") or ""
    best: tuple[float, str, str, str] | None = None
    for variable in edition.variables:
        if getattr(variable, "time", False):
            continue
        whole = next((str(code) for code, label in variable.values if _is_total(str(label))), None)
        if whole is None:
            continue
        choice = bind_dimension(variable, analysis, title)
        if choice is None or _is_total(choice.value_label):
            continue
        if choice.score < 4:
            continue
        if best is None or choice.score > best[0]:
            best = (choice.score, variable.code, choice.value_code, whole)
    if best is None:
        return None
    _score, variable_code, part_code, whole_code = best
    return variable_code, part_code, whole_code
