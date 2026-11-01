"""Refuse a neighbouring cell the tightened gates still state.

``GRUND_REDTEAM3`` is off unless it is ``1``, ``true``, ``yes``, or ``on``.
It does not run unless set, and it leaves ``GRUND_REDTEAM2`` alone. The
cases are the ones still wrong on the 205 after that flag:

- non-binary headcount answered with the all-sex total
- boys or girls answered with all live births
- national employment answered from the culture table
- the West answered with the national population
- a CPI monthly change answered with the index level
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold


def enabled() -> bool:
    return os.environ.get("GRUND_REDTEAM3", "").strip().lower() in {"1", "true", "yes", "on"}


def maybe_correct(engine, parsed, result: dict):
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return None
    text = fold(parsed.text)
    blob = _blob(result)
    if _nonbinary(text) and _total_sex(blob) and not _nonbinary(blob):
        return "all sexes where non-binary was asked"
    if _birth_sex(text) and _birth_total(blob) and not _birth_sex(blob):
        return "all births where one sex was asked"
    if _employed_people(text) and _stem(result).startswith("MEN") and "menning" not in text and "cultur" not in text:
        return "culture employment is not the national total"
    if _west_region(text) and _stem(result) in {"MAN00101", "MAN00000"} and "vestur" not in blob and "west" not in blob:
        return "national population is not the West"
    if _cpi_monthly(text) and _stem(result) == "VIS01000" and "monthly change" not in blob and "manadarbreyting" not in blob:
        replaced = _swap_cpi_month(engine, parsed, result)
        return replaced or "the index level is not the monthly change"
    return None


def _nonbinary(text: str) -> bool:
    return any(mark in text for mark in ("kynsegin", "non-binary", "nonbinary", "other sex"))


def _total_sex(blob: str) -> bool:
    return any(mark in blob for mark in ("total", "alls", "all sexes"))


def _birth_sex(text: str) -> bool:
    return re.search(r"\b(boys?|girls?|dreng\w*|stulk\w*)\b", text) is not None


def _birth_total(blob: str) -> bool:
    return "live birth" in blob or "lifandi" in blob


def _employed_people(text: str) -> bool:
    return ("employ" in text or "starfand" in text) and "unemploy" not in text and "atvinnuleys" not in text


def _west_region(text: str) -> bool:
    if "westfjord" in text or "vestfird" in text or "westman" in text:
        return False
    return "west of iceland" in text or "in the west" in text


def _cpi_monthly(text: str) -> bool:
    if not any(mark in text for mark in ("cpi", "neysluverd", "consumer price", "vnv")):
        return False
    return "monthly change" in text or "manadarbreyting" in text


def _stem(result: dict) -> str:
    return str(result.get("table_id") or "").removesuffix(".px")


def _blob(result: dict) -> str:
    parts = [str(result.get("answer") or "")]
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        if isinstance(cell, dict):
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                parts.extend(str(value) for value in labels.values())
    return fold(" ".join(parts))


def _swap_cpi_month(engine, parsed, result: dict):
    if engine is None:
        return None
    from grund.redteam2 import _swap_unit

    return _swap_unit(engine, parsed, result, ("monthly change", "manadarbreyting"))
