"""Keep a figure when the other path is a look-alike the loose gate refuses.

``GRUND_KEEP=0`` leaves a path disagreement as a refusal. The default keeps
the path the gate accepts.
"""

from __future__ import annotations

import os


def keep_enabled() -> bool:
    """On unless ``GRUND_KEEP=0``."""
    return os.environ.get("GRUND_KEEP", "1").strip().lower() not in {"0", "off", "none"}


def _stated(result: dict | None) -> bool:
    if not result or result.get("refused"):
        return False
    return result.get("value") not in (None, "")


def path_to_keep(catalogue, question: str, language: str | None, ranker: dict, hybrid: dict):
    """The path to state, or None when the disagreement stands.

    One path cites a figure the loose gate refuses. The other cites a figure
    the gate accepts. That accepted figure is the series to keep.
    """
    if not keep_enabled():
        return None
    from grund.loose_gate import loose_gate_reason

    def reason(result: dict) -> str | None:
        if not _stated(result):
            return None
        return loose_gate_reason(catalogue, question, language, result) or ""

    ranker_reason = reason(ranker)
    hybrid_reason = reason(hybrid)
    if ranker_reason == "" and hybrid_reason not in (None, ""):
        return ranker, hybrid
    if hybrid_reason == "" and ranker_reason not in (None, ""):
        return hybrid, ranker
    return None
