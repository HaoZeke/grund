"""National population. Off unless ``GRUND_IS_KANG_POP`` is set.

One Iceland headcount, with or without a year, is everyone on MAN00101.
A sex, an age, a town, and a region stay off this gate. A missing year is
the latest 1 January in the table.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "MAN00101"
_BLOCK_PLACES = (
    "reykjav", "kopavog", "akureyr", "hafnarfj", "gardabae", "mosfell", "arborg",
    "sveitarfel", "municip", "hofudborg", "capital", "sudurnes", "vestfird",
    "nordurland", "austurland", "vesturland", "sudurland", "westfjord",
    "northeast", "northwest", "southwest", "landshlut",
)


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_POP", "0").strip().lower() in {"1", "on", "true", "yes"}


def wants_nation(question: str, language: str | None) -> bool:
    if not enabled():
        return False
    from grund.measure_guard import population_measure_miss

    if population_measure_miss(question):
        return False
    if language not in {None, "", "is", "en"}:
        return False
    from grund.isguard import blocks_population

    if blocks_population(question):
        return False
    text = fold(question or "")
    if any(mark in text for mark in ("overnight", "gistin", "gistu", "unemploy", "atvinnu", "starfand", "launavisit", "wage", "neysluverd", "consumer price", "landsframleid", "utflutn", "innflutn", "export", "import", "birth", "night", "lodging", "naetur", "naetur")):
        return False
    if re.search(r"\b(nights?|stays?)\b", text):
        return False
    named = re.search(r"\b(island\w*|iceland\w*|islndi|islend\w*|landsins)\b", text) is not None
    bare = re.search(r"\bmannfjold\w*\b(?:\s+([a-z0-9]+))?", text)
    if not named and bare is None:
        return False
    if not named and bare is not None:
        nxt = bare.group(1)
        if nxt and nxt not in {"1", "arid", "a", "i", "the", "of"} and not nxt.isdigit():
            return False
    head = re.search(
        r"\b(mannfjold\w*|ibuar\w*|ibua\b|ibuafjold\w*|ibutal\w*|folkafjold\w*|folksfjold\w*|population|popul\w*|people|peopl|inhabitants?|headcount|residents?|bua|bjuggu|live|lived|lives)\b",
        text,
    )
    folk_many = re.search(r"\bfolk\w*\b", text) and re.search(r"\bmargt\b", text)
    if head is None and not folk_many and "how many" not in text and "hve marg" not in text and "hvad eru margir" not in text:
        return False
    if any(mark in text for mark in _BLOCK_PLACES):
        return False
    if re.search(r"\b(women|woman|females?|konur|kvenna|men|males?|karlar|karlmenn)\b", text):
        return False
    if re.search(r"\b\d{1,3}\s+ara\b", text) or "year-old" in text or "year old" in text or "aged" in text or "eldri" in text or "yngri" in text or "older" in text:
        return False
    if any(mark in text for mark in ("innflytj", "immigrant", "immigrat", "arrival", "gestakom", "born", "faed", "babi", "prosent", "percent", "hlutfall", "fjolgun", "increase", "settust", "adflutt", "brottflutt", "fluttu", "flutti")):
        return False
    if len(re.findall(r"(?:19|20)\d{2}", question or "")) > 1:
        return False
    # These clean Icelandic year questions are already answered. Matching them
    # dropped the 2014 total.
    if re.search(r"\bbjuggu\b", text) and re.search(r"\barid\b", text):
        return False
    if re.search(r"\bmannfjoldi islands\b", text):
        return False
    return True


def open_age_is_total(question: str, result: dict) -> bool:
    """A headcount of 'N and older' is not the all-age total."""
    if not enabled():
        return False
    text = fold(question or "")
    if re.search(r"(\d{1,3}\s+and older|\baged\s+\d{1,3}\b|\bog eldri\b)", text) is None:
        return False
    if re.search(r"\b(percent|percentage|hlutfall|rate|prosent)\b", text):
        return False
    if any(mark in text for mark in ("and what", "og hver", "og hvert")):
        return False
    stem = str(result.get("table_id") or "").removesuffix(".px")
    if stem not in {"MAN00000", "MAN00101", "MAN03200", "MAN03250", "MAN03260"}:
        return False
    labels: list[str] = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells = list(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        raw = cell.get("labels")
        if isinstance(raw, dict):
            labels.extend(fold(str(value)) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    labels.append(fold(str(item.get("label") or "")))
    blob = " ".join(labels)
    if "og eldri" in blob or "and older" in blob or re.search(r"\b\d{1,3}\s+ara\b", blob):
        return False
    return True


def _title_ok(title: str) -> bool:
    folded = fold(title or "")
    return "kyni og aldri" in folded or "sex and age" in folded


def pop_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    if not wants_nation(question, language) or not _title_ok(title):
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        folded = fold(str(label or ""))
        if ("kyn" in blob or re.search(r"\bsex\b", blob)) and str(code) in {"Total", "0"} and folded in {"alls", "total"}:
            hits.append(str(code))
        elif ("aldur" in blob or re.search(r"\bage\b", blob)) and str(code) == "-1":
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def pop_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if not wants_nation(question, language) or edition is None:
        return False
    if not _title_ok(getattr(edition, "title", "") or ""):
        return False
    folded = fold(token)
    return folded.startswith(("mannfjold", "ibuar", "islnd", "peopl", "janur", "popul"))


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def _labels_of(obj: dict) -> list[str]:
    cells: list = []
    source = obj.get("source") if isinstance(obj.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in obj.get("claims") or []:
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


def _cell_ok(labels: list[str], question: str) -> bool:
    blob = " ".join(labels)
    if "karlar" in blob or "konur" in blob:
        return False
    if not any(mark in blob for mark in ("alls", "total")):
        return False
    years = re.findall(r"(?:19|20)\d{2}", question or "")
    if len(years) == 1 and years[0] not in blob:
        return False
    return True


def pop_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    if not wants_nation(question, language):
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"} and not reason.startswith("measure "):
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
        return False
    return _cell_ok(_labels_of(produced), question)


def pop_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    if not wants_nation(question, language) or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    if not _cell_ok(_labels_of(ranker), question):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_pop"] = True
    chosen["source"] = source
    return chosen


def apply_is_pop(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if not wants_nation(question, language):
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
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    if "Total" not in picked and "-1" not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
