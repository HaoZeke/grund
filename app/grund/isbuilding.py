"""Annual building-cost index. Off unless ``GRUND_IS_BUILDING`` is set.

The English title says "building cost", not "bygging", so the subject check
drops the annual average. A typo such as "bulding" or "byggingarvisitla"
is the same index. A change question keeps the annual-change row.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_ASK = re.compile(r"byggingarvisit|bulding cost|building cost|construction cost")
_CHANGE = re.compile(r"\b(change|breyting|haekk\w*|laekk\w*|prosent|percent)\b")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_BUILDING", "0").strip().lower() in {"1", "on", "true", "yes"}


def wants(question: str) -> bool:
    if not enabled():
        return False
    return _ASK.search(fold(question or "")) is not None


def item_code(question: str) -> str | None:
    """``avg`` or ``change_A`` on VIS13401."""
    if not wants(question):
        return None
    if _CHANGE.search(fold(question or "")):
        return "change_A"
    return "avg"


def apply_is_building(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if not wants(question):
        return hits
    table = catalogue.by_id.get("VIS13401.px") or catalogue.by_id.get("VIS13401")
    if table is None:
        return hits
    kept = [hit for hit in hits if str(hit.table.id).removesuffix(".px") != "VIS13401"]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead, *kept]


def building_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    if not wants(question) or ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if str(ranker.get("table_id") or "").removesuffix(".px") != "VIS13401":
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["is_building"] = True
    chosen["source"] = source
    return chosen
