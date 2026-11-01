"""Refuse a look-alike table when the series is a different one.

Fitted on dev-A and dev2 with the rule off. A historical copy, a population
projection, a CPI series that does not hold the asked base year, a locality
or district table for a named municipality, and a population table for a
labour-status question are withheld. A percent change whose cited titles
lack the asked measure is withheld. The two stated titles of a pair are
judged together.
"""

from __future__ import annotations

import re

from grund.parse import parse_question
from grund.subject_veto import search_leader_title, subject_gap
from grund_index.textutil import fold, tokens

_MEASURE_STOP = {
    "what", "was", "were", "hver", "hvad", "arid", "from", "fra", "til",
    "and", "the", "did", "how", "much", "many", "percentage", "percent",
    "prosent", "with", "med", "eftir", "that", "this", "sem",
    "increase", "increased", "decrease", "decreased", "number", "numbers",
    "fleiri", "margar", "margir", "morgum", "iceland", "islandi", "island",
    "fjoldi", "fjolda", "points", "point", "stig",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "januar", "februar",
    "mars", "juni", "juli", "agust", "oktober", "desember",
}
_HISTORICAL_Q = re.compile(r"\b(historical|soguleg\w*)\b")
_GEO_Q = re.compile(r"(thettbylis|byggdakjarn|hverf|localit|urban nucle|district)")
_GEO_VAR = ("thettbylis", "byggdakjarn", "hverfi", "localit", "urban", "district")
_BASE = re.compile(r"((?:19|20)\d{2})\s*=\s*100")


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
    return [str(item.get("label") or "") for item in labels if isinstance(item, dict)]


def _table(catalogue, table_id: str):
    if catalogue is None:
        return None
    stem = str(table_id).removesuffix(".px")
    return catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)


def _edition(table, language: str | None):
    if table is None:
        return None
    return table.edition(language or "") or table.edition("en") or table.edition("is")


def _stems(result: dict) -> list[str]:
    found = []
    for table_id in result.get("tables") or []:
        stem = str(table_id).removesuffix(".px")
        if stem and stem not in found:
            found.append(stem)
    if not found and result.get("table_id"):
        found.append(str(result["table_id"]).removesuffix(".px"))
    return found


def _blob(catalogue, stem: str, language: str | None) -> str:
    table = _table(catalogue, stem)
    edition = _edition(table, language)
    if edition is None:
        return ""
    return fold(edition.db + " " + " ".join(edition.path_texts) + " " + edition.title)


def _titles(catalogue, result: dict, language: str | None) -> str:
    found: list[str] = []

    def add(title: str) -> None:
        if title and title not in found:
            found.append(title)

    for cell in _cells(result):
        add(str(cell.get("title") or ""))
    for stem in _stems(result):
        edition = _edition(_table(catalogue, stem), language)
        if edition is not None:
            add(edition.title)
    return " ".join(found)


def _years(catalogue, stem: str) -> set[int]:
    table = _table(catalogue, stem)
    if table is None:
        return set()
    found: set[int] = set()
    for edition in table.editions.values():
        found |= edition.years()
    return found


def _municipalities(catalogue) -> list[str]:
    labels: list[str] = []
    table = _table(catalogue, "MAN02005")
    edition = _edition(table, "is")
    if edition is None:
        return labels
    for variable in edition.variables:
        if "sveitar" not in fold(variable.text):
            continue
        for _code, label in variable.values:
            folded = fold(label)
            if len(folded) >= 6 and folded not in {"alls", "total"}:
                labels.append(folded)
    return labels


def _place_named(question_folded: str, labels: list[str]) -> bool:
    for word in re.findall(r"[a-z0-9]+", question_folded):
        if len(word) < 6:
            continue
        prefix = word[:6]
        for label in labels:
            if label[:6] == prefix:
                return True
    return False


def _geo_kind(catalogue, stem: str) -> str:
    table = _table(catalogue, stem)
    if table is None:
        return ""
    for edition in table.editions.values():
        for variable in edition.variables:
            key = fold(variable.text)
            if any(mark in key for mark in _GEO_VAR):
                return key
    return ""


def _frame_keeps(catalogue, frame, result: dict) -> bool:
    """The frame already chose this table. A search-leader title gap is not a miss."""
    stem = ""
    for table_id in list(result.get("tables") or []) + [result.get("table_id")]:
        stem = str(table_id or "").removesuffix(".px")
        if stem:
            break
    if not stem or catalogue is None:
        return False
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return False
    return frame.preference(table) >= 40


def _norm(token: str) -> str:
    if token.startswith(("gistinott", "gistinaet", "gistinat")):
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


def _cited_labels(result: dict) -> str:
    parts = []
    for cell in _cells(result):
        parts.extend(_label_values(cell))
    return " ".join(parts)


def lookalike_reason(catalogue, question: str, language: str | None, result: dict) -> str | None:
    if result.get("refused") or result.get("value") in (None, ""):
        return None
    if catalogue is None:
        return None
    folded = fold(question)
    stems = _stems(result)
    titles = _titles(catalogue, result, language)
    blobs = [_blob(catalogue, stem, language) for stem in stems]

    if stems and _HISTORICAL_Q.search(folded) is None:
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        # A Sögulegar span that has ended, while the current table continues,
        # is the series asked for. Ferry passengers through 2017 are that case.
        if any("soguleg" in blob or "historical" in blob for blob in blobs) and not source.get("closed_historical"):
            return "historical-copy"

    if stems and not re.search(r"(mannfjoldaspa|population projection|forecast|\bspa\b|framreikn)", folded):
        if any("mannfjoldaspa" in blob or "population projection" in blob for blob in blobs):
            return "projection"

    bases = [int(year) for year in _BASE.findall(question)]
    if bases:
        for stem in stems:
            years = _years(catalogue, stem)
            title = fold(_titles(catalogue, {"tables": [stem]}, language))
            if years and any(year not in years and str(year) not in title for year in bases):
                return "base-year"

    if stems and _GEO_Q.search(folded) is None and _place_named(folded, _municipalities(catalogue)):
        if any(_geo_kind(catalogue, stem) for stem in stems):
            return "wider-geo"

    if re.search(r"\b(stodu|status)\b", folded):
        for stem, blob in zip(stems, blobs):
            if "stodu" in blob or "status" in blob:
                continue
            if any(word in blob for word in ("sveitarfelag", "rikisfang", "citizenship", "municip")):
                return "status-vs-geo"

    if re.search(r"\b(vedrid|vedur|weather)\b", folded):
        return "weather"

    if "art form" in folded and "art form" not in fold(titles):
        return "art-form"
    if "tegund verka" in folded and "tegund verka" not in fold(titles):
        return "art-form"

    if re.search(r"\b(adflutt\w*|settust)\b", folded):
        if stems and not any(
            "buferlaflutn" in blob or "migration" in blob or "adflutt" in blob for blob in blobs
        ):
            return "immigration"

    if re.search(r"\b(faerdu|fluttu|flutti)\b", folded) and re.search(r"(logheimil|innanlands)", folded):
        if stems and not any("buferlaflutn" in blob or "migration" in blob for blob in blobs):
            return "internal-move"

    parsed = parse_question(question, language)
    years = [year for year, _month in parsed.periods]
    sexdiff = any(
        isinstance(claim, dict) and claim.get("formula") in {"men - women", "women - men"}
        for claim in (result.get("claims") or [])
    )
    if sexdiff:
        return None
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    # Exports and imports are the national-accounts line, not the goods table the search leads with.
    if titles and not source.get("is_trade") and not source.get("is_stays") and not source.get("is_pop") and not source.get("is_origin") and not source.get("is_building"):
        leader = search_leader_title(catalogue, question, language, years)
        if subject_gap(question, leader, titles):
            from grund.frame import current_frame

            frame = current_frame()
            if not (frame is not None and frame.use and _frame_keeps(catalogue, frame, result)):
                return "subject"
    if parsed.operation in {"yoy_pct", "difference"} and titles and not source.get("is_wage") and not source.get("is_cpi"):
        asked = _measure_tokens(question)
        have = _measure_tokens(titles + " " + _cited_labels(result))
        if asked and any(not _covers(have, word) for word in asked):
            return "measure"
    return None
