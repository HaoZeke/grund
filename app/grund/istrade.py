"""Exports and imports of goods and services. Off unless ``GRUND_IS_KANG_TRADE`` is set.

The national-accounts table publishes the totals. A goods-only question
is the goods line under that total, not the goods-and-services total.
The balance of trade is not one of these lines.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "THJ01102"


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_TRADE", "0").strip().lower() in {"1", "on", "true", "yes"}


def trade_must_refuse(question: str, language: str | None) -> bool:
    """A year of the balance of trade is twelve monthly cells, not one figure."""
    if not enabled():
        return False
    if language not in {None, "", "is", "en"}:
        return False
    text = fold(question or "")
    if (
        "balance of trade" not in text
        and "trade balance" not in text
        and "voruskiptajofn" not in text
        and "skiptajofnud" not in text
    ):
        return False
    if re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|januar|februar|mars|mai|juni|juli|agust|oktober|november|desember)\b",
        text,
    ):
        return False
    return True


def trade_kind(question: str, language: str | None) -> str | None:
    """``exports``, ``imports``, ``goods-exports`` or ``goods-imports``."""
    if not enabled():
        return None
    from grund.measure_guard import monthly_goods

    if monthly_goods(question):
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if any(mark in text for mark in ("balance", "jofnud", "skiptajofn", "and what", "og hver", "og hvad", "hlutfall", "percent", "prosent", "haekk", "laekk", "eftir", "flokk")):
        return None
    if language == "en" and re.search(r"\b(exports|imports) of\b", text) is None:
        return None
    if language in {None, "", "is"} and re.search(r"\b(utflutning\w*|innflutning\w*|voruutflutning\w*)\b", text) is None:
        return None
    exports = "utflutn" in text or "export" in text
    imports = "innflutn" in text or "import" in text
    if exports == imports:
        return None
    services = "thjonust" in text or "service" in text
    goods = "voru" in text or re.search(r"\bgoods\b", text) is not None
    # "vöruútflutningur" is goods exports. "útflutningur vöru og þjónustu" is the total.
    if "voruutflut" in text or "voruinnflut" in text:
        goods, services = True, False
    if exports and goods and not services:
        return "goods-exports"
    if imports and goods and not services:
        return "goods-imports"
    if exports:
        return "exports"
    return "imports"


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _line_kind(label: str) -> str | None:
    folded = fold(label or "")
    if "utflutningur alls" in folded or "exports of goods and services" in folded:
        return "exports"
    if "innflutningur alls" in folded or "imports of goods and services" in folded:
        return "imports"
    if "6.1" in folded and ("vorur" in folded or "goods" in folded):
        return "goods-exports"
    if "7.1" in folded and ("vorur" in folded or "goods" in folded):
        return "goods-imports"
    return None


def trade_line_code(variable, question: str, language: str | None, title: str) -> str | None:
    kind = trade_kind(question, language)
    if kind is None:
        return None
    folded = fold(title or "")
    if "landsframleid" not in folded and "domestic product" not in folded and "thjodartekj" not in folded:
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "skipting" not in blob and "category" not in blob:
        return None
    hits = [str(code) for code, label in getattr(variable, "values", []) or [] if _line_kind(str(label or "")) == kind]
    if len(hits) == 1:
        return hits[0]
    return None


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
            found.extend(str(value) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    found.append(str(item.get("label") or ""))
    return found


def _asked_year(question: str) -> str | None:
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) == 1:
        return years[0]
    return None


def trade_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    kind = trade_kind(question, language)
    if kind is None:
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    year = _asked_year(question)
    labels = _labels(ranker)
    if year is None or year not in {fold(label) for label in labels} and year not in labels:
        return None
    if not any(_line_kind(label) == kind for label in labels):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_trade"] = True
    chosen["source"] = source
    return chosen


def trade_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """Goods and services lines are the cell. The question's compound is not printed on it."""
    kind = trade_kind(question, language)
    if kind is None:
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"}:
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
        return False
    year = _asked_year(question)
    labels: list[str] = []
    for claim in produced.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            raw = cell.get("labels")
            if isinstance(raw, dict):
                labels.extend(str(value) for value in raw.values())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        labels.append(str(item.get("label") or ""))
    if year is None or year not in {fold(label) for label in labels} and year not in labels:
        return False
    return any(_line_kind(label) == kind for label in labels)


def apply_is_trade(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if trade_kind(question, language) is None:
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    from grund.bind import bind
    from grund.parse import parse_question

    edition = table.edition(language or "is") or table.edition("is") or table.edition("en")
    if edition is None:
        return hits
    binding = bind(edition, parse_question(question, language or "is"))
    if binding is None:
        return hits
    line = None
    for variable in edition.variables:
        line = trade_line_code(variable, question, language, edition.title)
        if line is not None:
            break
    if line is None:
        return hits
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    if line not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
