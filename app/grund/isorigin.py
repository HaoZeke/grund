"""Immigrant stock and external migration. Off unless ``GRUND_IS_ORIGIN`` is set.

A question that asks how many immigrants lived in the country is the origin
cell on the population-by-origin table, not an arrival during the year.
A question that asks who immigrated, or the net flow, is the external-migration
table. Income, assets, and pupils are left alone. The flag defaults off.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_FLOW_OUT = re.compile(r"\b(emigrat\w*|flutt\w*\s+fra|brottflutt\w*)\b")
_FLOW_IN = re.compile(r"\b(immigrated|flutt\w*\s+til|moved to iceland|moved to the country)\b")
_FLOW_NET = re.compile(
    r"\b(net immigration|net flow of migration|netto adflutning\w*|adflutning\w*\s+umfram\s+brott\w*)\b"
)
_STOCK = re.compile(r"\b(innflytj\w*|immigrants?)\b")
_SECOND = re.compile(r"second.generation|annarri kynslod|onnur kynslod|kynslod innflytj")
_NONE = re.compile(r"no foreign background|engan erlendan bakgrunn|enginn erlendur bakgrunn")
_LIVED = re.compile(
    r"\b(bjuggu|bua|busett\w*|lived|living|live|logheimil|legal residence|january|januar|were there)\b"
)
_NOT_STOCK = re.compile(
    r"\b(tekjur|tekna|eignir|eignum|skuldir|skuldum|skola|school|prosent|percent|haekk\w*|laekk\w*)\b"
)


def enabled() -> bool:
    return os.environ.get("GRUND_IS_ORIGIN", "0").strip().lower() in {"1", "on", "true", "yes"}


def _asked(question: str) -> str:
    return fold(question or "")


def migration_code(variable, question: str) -> str | None:
    """The flow row on whichever external-migration table this edition is.

    MAN01400 numbers the rows 1/2/3. MAN01401 numbers the same rows 0/1/2.
    A code that is not on this variable is matched by its label instead.
    """
    legacy = flow_code(question)
    if not legacy:
        return None
    key = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "flutning" not in key and re.search(r"\bmigration\b", key) is None:
        return None
    values = list(getattr(variable, "values", []) or [])
    kind = {"1": "net", "2": "in", "3": "out"}.get(legacy, "")
    for code, label in values:
        plain = fold(str(label or ""))
        net = "net" in plain or "netto" in plain or "umfram" in plain
        arrived = "adflutt" in plain or "immigration" in plain
        left = "brott" in plain or "emigration" in plain
        if kind == "net" and net:
            return str(code)
        if kind == "in" and arrived and not net and not left:
            return str(code)
        if kind == "out" and left and not net:
            return str(code)
    return None


def sex_total_code(variable, question: str) -> str | None:
    """A flow that does not name a sex is both sexes."""
    if flow_code(question) is None or sex_code(question) is not None:
        return None
    key = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if not re.search(r"\b(kyn|sex)\b", key):
        return None
    for code, label in getattr(variable, "values", []) or []:
        if fold(str(label or "")) in {"total", "alls", "all", "males and females", "karlar og konur"}:
            return str(code)
    return None


def citizenship_total_code(variable, question: str) -> str | None:
    """A flow that does not name a citizenship is the total, not Icelandic citizens."""
    if flow_code(question) is None or citizenship_code(question) is not None:
        return None
    key = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "rikisfang" not in key and "citizenship" not in key:
        return None
    for code, label in getattr(variable, "values", []) or []:
        if fold(str(label or "")) in {"total", "alls", "all"}:
            return str(code)
    return None


def age_total_code(variable, question: str) -> str | None:
    """'All ages' is the age total, not one year of age."""
    text = fold(question or "")
    if "all ages" not in text and "allir aldur" not in text and "aldurshop" not in text:
        return None
    key = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "aldur" not in key and re.search(r"\bage\b", key) is None:
        return None
    for code, label in getattr(variable, "values", []) or []:
        plain = fold(str(label or ""))
        if plain in {"total", "alls", "all"}:
            return str(code)
    return None


def flow_code(question: str) -> str | None:
    """External-migration type code, or nothing when this is not a flow question."""
    if not enabled():
        return None
    asked = _asked(question)
    # "aðfluttir umfram brottflutta" is the published net, not emigration.
    if re.search(r"umfram\s+brott", asked) or _FLOW_NET.search(asked):
        return "1"
    if re.search(r"\b(fleiri|faerri|munur\w*|difference|haekk|laekk|percent|prosent)\b", asked):
        return None
    if re.search(r"\ben\s+(?:19|20)\d{2}\b", asked):
        return None
    if _FLOW_OUT.search(asked):
        return "3"
    if _FLOW_IN.search(asked):
        return "2"
    return None


def _lived(asked: str) -> bool:
    return _LIVED.search(asked) is not None


def origin_code(question: str) -> str | None:
    """Population-by-origin code, or nothing when this is not a stock question."""
    if not enabled() or flow_code(question):
        return None
    asked = _asked(question)
    if _NOT_STOCK.search(asked) or not _lived(asked):
        return None
    if _SECOND.search(asked):
        return "024"
    if _NONE.search(asked):
        return "000"
    if _STOCK.search(asked):
        return "124"
    return None


def stock_question(question: str) -> bool:
    """A headcount of immigrants living in the country, not a flow and not income."""
    return origin_code(question) == "124"


def sex_code(question: str) -> str | None:
    """Sex code on the origin or migration table, when the question names one."""
    if origin_code(question) is None and flow_code(question) is None:
        return None
    asked = _asked(question)
    if re.search(r"\b(women|woman|female|females|konur|konum|kona|kvenna)\b", asked):
        return "2"
    if re.search(r"\b(men|man|male|males|karlar|karl|karla)\b", asked):
        return "1"
    return None


def citizenship_code(question: str) -> str | None:
    """Citizenship code on the migration table, when the question names one."""
    if flow_code(question) is None:
        return None
    asked = _asked(question)
    if "foreign citizen" in asked or ("erlend" in asked and "rikisborg" in asked):
        return "3"
    if "icelandic citizen" in asked or ("islensk" in asked and "rikisborg" in asked):
        return "2"
    return None


def _table(catalogue, stem: str):
    found = catalogue.by_id.get(stem) or catalogue.by_id.get(stem + ".px")
    return found


def apply_is_origin(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Lead with the origin table or the external-migration table."""
    if not enabled():
        return hits
    # The age table is the flow the question can pin to a total. The table
    # without an age dimension stays available when the age table is absent.
    flow_stem = "MAN01401" if flow_code(question) else ""
    stem = "MAN43000" if origin_code(question) else flow_stem
    if not stem:
        return hits
    table = _table(catalogue, stem)
    if table is None:
        return hits
    kept = []
    for hit in hits:
        other = str(hit.table.id).removesuffix(".px")
        if other == stem:
            continue
        # A district or sex split of the same stock states the right number
        # from a table the gold does not accept.
        if stem == "MAN43000" and other.startswith("MAN43"):
            continue
        kept.append(hit)
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead, *kept]


def _cell_pairs(result: dict) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells = list(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        labels = cell.get("labels")
        if isinstance(labels, dict):
            for key, value in labels.items():
                found.append((fold(str(key)), str(value), fold(str(value))))
    return found


def origin_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    """Keep the ranker's origin or migration cell when this flag selected it."""
    if not enabled() or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    stem = str(ranker.get("table_id") or "").removesuffix(".px")
    if origin_code(question) and stem == "MAN43000":
        origin = [
            label
            for key, _code, label in _cell_pairs(ranker)
            if "bakgrunn" in key or key == "origin" or "background" in key
        ]
        if origin and any(label in {"total", "alls", "all"} for label in origin):
            return None
    elif flow_code(question) and stem in {"MAN01400", "MAN01401"}:
        pass
    else:
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["is_origin"] = True
    chosen["source"] = source
    return chosen
