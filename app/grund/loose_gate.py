"""Refuse figures the rule-off build states for the wrong series.

Fitted on dev-A and dev2. A percent change or a difference answered as a
bare level is withheld. A change whose cited titles and labels lack an
asked measure word is withheld. A count of one sex, or a men-minus-women
difference, whose cells are not those sexes is withheld.

A two-part answer is judged on its table titles together. The disagreement
rule stays the default. These gates run before it.
"""

from __future__ import annotations

import re

from grund.parse import parse_question
from grund.subject_veto import leader_title, titles_gap
from grund_index.textutil import fold, tokens

# Change verbs and calendar words. They are not the measure.
_MEASURE_STOP = {
    "what", "was", "were", "hver", "hvad", "arid", "from", "fra", "til",
    "and", "the", "did", "how", "much", "many", "percentage", "percent",
    "prosent", "with", "med", "eftir", "that", "this", "sem",
    "increase", "increased", "decrease", "decreased", "number", "numbers",
    "fleiri", "margar", "margir", "morgum", "iceland", "islandi", "island",
    "fjoldi", "fjolda", "points", "point", "stig",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "januar", "februar",
    "mars", "april", "juni", "juli", "agust", "september", "oktober",
    "november", "desember",
}

_MALE = re.compile(r"\b(men|males?|karlar|karl)\b")
_FEMALE = re.compile(r"\b(women|females?|konur|kona|kven\w*)\b")
_SEX_VAR = re.compile(r"\b(kyn|sex|gender)\b")
_SEX_TOTAL = {"total", "alls", "samtals", "all"}
_COMPUTED = re.compile(
    r"change from|breyting|calculated by grund|reiknad af grund|difference was|munurinn"
)
_PERCENT = re.compile(r"\b(percent|prosent|hlutfall)\b")


def _cells(result: dict) -> list[dict]:
    found: list[dict] = []
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            found.extend(cell for cell in (claim.get("cells") or []) if isinstance(cell, dict))
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    found.extend(cell for cell in (source.get("cells") or []) if isinstance(cell, dict))
    return found


def _label_values(cell: dict) -> list[str]:
    labels = cell.get("labels") or {}
    if isinstance(labels, dict):
        return [str(value) for value in labels.values()]
    values = []
    for item in labels:
        if isinstance(item, dict):
            values.append(str(item.get("label") or ""))
    return values


def _table_title(catalogue, table_id: str, language: str | None) -> str:
    if catalogue is None:
        return ""
    stem = str(table_id).removesuffix(".px")
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return ""
    edition = table.edition(language or "") or table.edition("en") or table.edition("is")
    return edition.title if edition else ""


def _titles(result: dict, catalogue=None, language: str | None = None) -> str:
    """Titles of every stated table.

    A two-part answer keeps only the first table's cells. The other half is
    named in ``tables``. Both titles are judged together, or a right pair
    looks like a different subject.
    """
    found: list[str] = []

    def add(title: str) -> None:
        if title and title not in found:
            found.append(title)

    for cell in _cells(result):
        add(str(cell.get("title") or ""))
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    add(str(source.get("title") or ""))
    lang = language or result.get("language")
    for table_id in result.get("tables") or []:
        add(_table_title(catalogue, str(table_id), lang))
    return " ".join(found)


def _cited(result: dict, catalogue=None, language: str | None = None) -> str:
    parts = [_titles(result, catalogue, language)]
    for cell in _cells(result):
        parts.extend(_label_values(cell))
    return " ".join(part for part in parts if part)


def _answer(result: dict) -> str:
    return fold(str(result.get("answer") or ""))


def _stated_op(result: dict) -> str:
    stated = str(result.get("operation") or "")
    if stated:
        return stated
    claims = result.get("claims") or []
    if claims and isinstance(claims[0], dict):
        return str(claims[0].get("op") or "")
    return ""


def _norm(token: str) -> str:
    """Overnight-stay inflections are one measure. Hotel occupancy is not."""
    if token.startswith("gistinott") or token.startswith("gistinaet") or token.startswith("gistinat"):
        return "gistinaetur"
    if token.startswith("overnight"):
        return "overnight"
    if token.startswith("fjold"):
        return "fjoldi"
    return token


def _measure_tokens(text: str) -> set[str]:
    kept = set()
    for token in tokens(text):
        if len(token) < 6 or token.isdigit() or token in _MEASURE_STOP:
            continue
        if token.startswith(("haekk", "laekk", "fjolg", "faekk")):
            continue
        kept.add(_norm(token))
    return kept


def _covers(have: set[str], word: str) -> bool:
    for token in have:
        if token == word:
            return True
        common = 0
        for left, right in zip(token, word):
            if left != right:
                break
            common += 1
        if common >= 6:
            return True
    return False


def _sexes(text: str) -> tuple[bool, bool]:
    folded = fold(text)
    return bool(_MALE.search(folded)), bool(_FEMALE.search(folded))


def _sex_label_is_total(result: dict) -> bool:
    """Every cited sex label is Total. A share may also cite the named sex."""
    values: list[str] = []
    for cell in _cells(result):
        labels = cell.get("labels") or {}
        if isinstance(labels, dict):
            pairs = labels.items()
        else:
            pairs = (
                (item.get("variable_text") or item.get("variable") or "", item.get("label") or "")
                for item in labels
                if isinstance(item, dict)
            )
        for key, value in pairs:
            if _SEX_VAR.search(fold(str(key))):
                values.append(fold(str(value)))
    if not values:
        return False
    return all(value in _SEX_TOTAL for value in values)


def loose_gate_reason(catalogue, question: str, language: str | None, result: dict) -> str | None:
    if result.get("refused") or result.get("value") in (None, ""):
        return None
    parsed = parse_question(question, language)
    years = [year for year, _month in parsed.periods]
    titles = _titles(result, catalogue, language)
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    # The national-accounts export or import line is the asked total. The
    # search leader is often a goods table in tonnes.
    if titles and catalogue is not None and not source.get("is_trade") and not source.get("is_stays") and not source.get("is_pop") and not source.get("is_origin") and not source.get("is_building"):
        leader = leader_title(catalogue, question, language, years)
        if titles_gap(question, leader, titles):
            from grund.frame import current_frame
            from grund.lookalike_gate import _frame_keeps

            frame = current_frame()
            if not (frame is not None and frame.use and _frame_keeps(catalogue, frame, result)):
                return "subject"
    answer = _answer(result)
    # Men minus women is computed from the two sex cells. The question's verb
    # is not a series name, so the measure-word check does not apply to it.
    sexdiff = any(
        isinstance(claim, dict) and claim.get("formula") in {"men - women", "women - men"}
        for claim in (result.get("claims") or [])
    )
    if sexdiff:
        return None
    if parsed.operation in {"yoy_pct", "difference"} and not _COMPUTED.search(answer):
        cited = fold(_cited(result, catalogue, language))
        published_change = "annual change" in cited or "arsbreyting" in cited
        stated = _stated_op(result)
        if (
            not published_change
            and not source.get("is_wage")
            and not source.get("is_cpi")
            and (stated == "level" or not _PERCENT.search(answer))
        ):
            return "level-against-change"
    if parsed.operation in {"yoy_pct", "difference"} and titles and not source.get("is_wage") and not source.get("is_cpi"):
        asked = _measure_tokens(question)
        have = _measure_tokens(_cited(result, catalogue, language))
        if asked and any(not _covers(have, word) for word in asked):
            return "measure"
    male, female = _sexes(question)
    blob = fold(_cited(result, catalogue, language) + " " + str(result.get("answer") or ""))
    has_male, has_female = _sexes(blob)
    text = fold(question)
    if re.search(r"\b(more|fleiri)\b", text) and male and female and not (has_male and has_female):
        return "sex-pair"
    if male != female:
        if _sex_label_is_total(result):
            return "sex-total"
        named = has_female if female else has_male
        if not named:
            return "named-sex"
    return None
