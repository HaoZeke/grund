"""National sex share of the population. Off unless ``GRUND_IS_KANG_SHARE`` is set.

"Hversu hátt hlutfall íbúa voru karlar" is men divided by everyone, on the
national population-by-sex table, rounded to one decimal. A town, a region,
and a change stay on the ordinary list.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "MAN00101"
_BLOCK = ("og eldri", "og yngri", "sveitarfel", "landshlut", "hofudborg", "haekk", "laekk", "munadi", "milli")
_NATIONAL = ("ibua", "landsmann", "a islandi", "islandi", "mannfjold", "landinu", "population", "resident", "inhabitant")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_SHARE", "0").strip().lower() in {"1", "on", "true", "yes"}


def sex_side(question: str) -> str | None:
    """``male`` or ``female`` when the question names one sex."""
    text = fold(question or "")
    male = re.search(r"\b(karl\w*|males?|men)\b", text) is not None
    female = re.search(r"\b(konur|konu\w*|kven\w*|wom[ae]n|females?)\b", text) is not None
    if male == female:
        return None
    return "male" if male else "female"


def wants_sex_share(question: str, language: str | None) -> str | None:
    """Icelandic percent of residents who are men, or who are women."""
    if not enabled():
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if language == "en":
        if re.search(r"\b(share|percentage|percent|proportion)\b", text) is None:
            return None
    elif "hlutfall" not in text and "hlutdeild" not in text and "hluti" not in text:
        return None
    if any(mark in text for mark in _BLOCK):
        return None
    if not any(mark in text for mark in _NATIONAL):
        return None
    return sex_side(question)


def share_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The sex the share divides by everyone, not the all-sex total."""
    side = wants_sex_share(question, language)
    if side is None:
        return None
    folded = fold(title or "")
    if "kyni og aldri" not in folded and "sex and age" not in folded:
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "kyn" not in blob and "sex" not in blob:
        return None
    found = _sex_code_on(variable, side)
    return found


def _sex_code_on(variable, side: str) -> str | None:
    wanted = {"karlar", "karl", "men", "males"} if side == "male" else {"konur", "kona", "women", "females"}
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        if fold(str(label or "")) in wanted:
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _national_table(catalogue):
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    return table


def _sex_code(edition, side: str) -> tuple[str, str] | None:
    wanted = {"karlar", "karl", "men", "males"} if side == "male" else {"konur", "kona", "women", "females"}
    for variable in edition.variables:
        blob = fold(f"{variable.code} {variable.text}")
        if "kyn" not in blob and "sex" not in blob:
            continue
        for code, label in variable.values:
            if fold(str(label or "")) in wanted:
                return variable.code, str(code)
    return None


def _share_binds(table, question: str, side: str) -> bool:
    from grund.bind import bind
    from grund.parse import parse_question

    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return False
    parsed = parse_question(question, "is")
    if parsed.operation != "share":
        return False
    binding = bind(edition, parsed)
    if binding is None or binding.operation != "share":
        return False
    found = _sex_code(edition, side)
    if found is None:
        return False
    variable, code = found
    for selection in binding.selections:
        if selection.get("code") != variable:
            continue
        values = [str(item) for item in (selection.get("selection") or {}).get("values") or []]
        return code in values
    return False


def apply_is_share(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Move the national population-by-sex table to the front, or leave the list."""
    side = wants_sex_share(question, language)
    if side is None:
        return hits
    table = _national_table(catalogue)
    if table is None or not _share_binds(table, question, side):
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _stem(table.id)]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept


def _labels(result: dict) -> list[str]:
    cells: list = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    found: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        raw = cell.get("labels")
        if isinstance(raw, dict):
            found.extend(fold(str(value)) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    found.append(fold(str(item.get("label") or "")))
    return found


def _number(value) -> float | None:
    try:
        return float(str(value).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def share_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """The percent is men or women over everyone. "prósentum" is not a price change.

    The rail recomputes two same-year counts as a change because the question
    says to answer in percent. The share itself is the part divided by the total.
    """
    side = wants_sex_share(question, language)
    if side is None:
        return False
    if str((verdict or {}).get("reason") or "") != "value does not recompute from the cited cells":
        return False
    binding = produced.get("binding")
    if getattr(binding, "operation", None) != "share":
        return False
    table = produced.get("table")
    table_id = getattr(table, "id", None) or ""
    if _stem(str(table_id)) != _TABLE:
        return False
    part_code = str(getattr(binding, "part_code", "") or "")
    whole_code = str(getattr(binding, "whole_code", "") or "")
    if not part_code or not whole_code:
        return False
    claims = produced.get("claims") or []
    stated = None
    part = whole = None
    labels: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if stated is None:
            stated = _number(claim.get("value"))
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            coords = {str(value) for value in (cell.get("coords") or {}).values()}
            amount = _number(cell.get("value"))
            if part_code in coords:
                part = amount
            if whole_code in coords:
                whole = amount
            raw = cell.get("labels")
            if isinstance(raw, dict):
                labels.extend(fold(str(value)) for value in raw.values())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        labels.append(fold(str(item.get("label") or "")))
    if stated is None or part is None or whole is None or whole == 0 or part > whole or part < 0:
        return False
    if abs(stated - (part / whole * 100.0)) > 0.05:
        return False
    wanted = ("karl", "men", "male") if side == "male" else ("kon", "wom", "female")
    return any(any(bit in label for bit in wanted) for label in labels)


def _share_arithmetic(result: dict, side: str) -> bool:
    """True when the stated percent is the smaller cited count over the larger."""
    numbers = []
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                number = _number(cell.get("value"))
                if number is not None:
                    numbers.append(number)
    stated = _number(result.get("value"))
    if stated is None or len(numbers) < 2:
        return False
    numbers.sort()
    part, whole = numbers[0], numbers[-1]
    if whole == 0 or part > whole or part < 0:
        return False
    return abs(stated - (part / whole * 100.0)) <= 0.05


def share_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the computed sex share when hybrid states a headcount."""
    side = wants_sex_share(question, language)
    if side is None:
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    operation = str(ranker.get("operation") or "")
    labels = _labels(ranker)
    if operation not in {"share", "share_percent"} and not _share_arithmetic(ranker, side):
        return None
    wanted = ("karl", "men", "male") if side == "male" else ("kon", "wom", "female")

    def _label_has(label: str) -> bool:
        return any(label == bit or label.startswith(bit) for bit in wanted)

    if not any(_label_has(label) for label in labels):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_share"] = True
    chosen["source"] = source
    return chosen
