"""Overnight stays in all registered accommodation. Off unless ``GRUND_IS_KANG_STAYS`` is set.

The national total is every citizenship, not the Iceland row. Foreign
visitors are the foreigners row. A hotel-only question is a different table.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "SAM01601"
_REGION = (
    "hofudborg", "capital region", "sudurland", "nordurland", "austurland", "vesturland",
    "vestfird", "sudurnes", "westfjord", "northeast", "northwest", "southwest",
)


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_STAYS", "0").strip().lower() in {"1", "on", "true", "yes"}


def stays_kind(question: str, language: str | None) -> str | None:
    """``foreign`` or ``total``."""
    if not enabled():
        return None
    if language not in {None, "", "is", "en"}:
        return None
    text = fold(question or "")
    if (
        "gistin" not in text
        and "overnight" not in text
        and "gistu" not in text
        and re.search(r"\bnights?\b", text) is None
    ):
        return None
    # "gistinætur skráðar" is an older series, not the all-types table.
    if "skrad" in text:
        return None
    if any(mark in text for mark in ("hotel", "gistiheimil", "guesthouse", "tjald", "camp", "unlisted", "hlutfall", "percent", "prosent", "faekk", "haekk")):
        return None
    if len(re.findall(r"(?:19|20)\d{2}", question or "")) != 1:
        return None
    if any(mark in text for mark in _REGION):
        return None
    if "gestakom" in text or re.search(r"\barrivals?\b", text):
        if "gistin" not in text and "overnight" not in text:
            return None
    if any(mark in text for mark in ("erlend", "utlend", "foreign", "abroad")):
        return "foreign"
    return "total"


def _title_ok(title: str) -> bool:
    folded = fold(title or "")
    return "gistin" in folded or "overnight" in folded


def stays_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    kind = stays_kind(question, language)
    if kind is None or not _title_ok(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "thjoderni" not in blob and "citizen" not in blob:
        return None
    wanted = "foreign" if kind == "foreign" else "total"
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(f"{code} {label}")
        if wanted == "foreign" and (str(code) == "Foreigners" or "foreign" in folded or "utlending" in folded):
            hits.append(str(code))
        elif wanted == "total" and str(code) in {"Total", "Alls"}:
            hits.append(str(code))
    hits = list(dict.fromkeys(hits))
    if len(hits) == 1:
        return hits[0]
    return None


def stays_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if stays_kind(question, language) is None or edition is None:
        return False
    if not _title_ok(getattr(edition, "title", "") or ""):
        return False
    folded = fold(token)
    return folded.startswith(("gistin", "erlend", "utlend", "foreign", "visitor", "overnight", "register", "accommod", "gististad"))


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _claim_labels(produced: dict) -> list[str]:
    labels: list[str] = []
    for claim in produced.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            raw = cell.get("labels")
            if isinstance(raw, dict):
                labels.extend(fold(str(value)) for value in raw.values())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        labels.append(fold(str(item.get("label") or "")))
    return labels


def _cell_ok(kind: str, labels: list[str], question: str) -> bool:
    blob = " ".join(labels)
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) != 1 or years[0] not in blob:
        return False
    if "gistin" not in blob and "overnight" not in blob:
        return False
    if kind == "foreign":
        return "foreign" in blob or "utlending" in blob
    if re.search(r"\b(iceland|island)\b", blob):
        return False
    return "total" in blob or "alls" in blob


def stays_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    kind = stays_kind(question, language)
    if kind is None:
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
        return False
    return _cell_ok(kind, _claim_labels(produced), question)


def _result_labels(result: dict) -> list[str]:
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


def stays_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    kind = stays_kind(question, language)
    if kind is None or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    if not _cell_ok(kind, _result_labels(ranker), question):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_stays"] = True
    chosen["source"] = source
    return chosen


def apply_is_stays(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if stays_kind(question, language) is None:
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
