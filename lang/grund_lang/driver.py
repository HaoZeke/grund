"""Deterministic planner path that calls retrieve() and bind_values().

The fetch, the arithmetic, and the sentence stay in the existing engine.
This module only replaces the table shortlist and the value codes. The
signatures of retrieve() and bind_values() are unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from grund.engine import Engine
from grund.parse import ParsedQuestion
from grund.validator import ValidationError, validate
from grund_index.catalogue import Hit

from grund_lang.index import load_index
from grund_lang.values import bind_values
from grund.bind import Binding


def _span_codes(parsed: ParsedQuestion, edition):
    """Both ends of a from-to question, even when the year variable is not flagged as time."""
    from grund_lang.dates import parse_dates

    spans = [
        span for span in parse_dates(parsed.text)
        if span.kind == "between_years" and span.year and span.end_year
    ]
    if not spans:
        return None
    wanted = {str(spans[0].year), str(spans[0].end_year)}
    for variable in edition.variables:
        codes = []
        for code, label in variable.values:
            if str(code) in wanted or str(label).strip() in wanted:
                if str(code) not in codes:
                    codes.append(str(code))
        if len(codes) >= 2:
            return variable.code, sorted(codes)
    return None


def _time_codes(choices, variable) -> list[str]:
    codes = []
    for choice in choices:
        if choice.value_code not in codes:
            codes.append(choice.value_code)
    return sorted(codes)


def resolve_operation(parsed: ParsedQuestion) -> str:
    """Keep a pasted title from being read as a share or a percent change.

    "What was Percentage of enterprises..." is a level. "By how much did it
    fall" is a difference. "By what percentage" stays a percent change.
    """
    from grund_lang.dates import parse_dates
    from grund_lang.fold import fold

    from grund_lang.ratio import is_ratio_question

    text = fold(parsed.text)
    if is_ratio_question(parsed.text):
        return "share"
    operation = parsed.operation
    ranged = any(
        span.kind == "between_years" and span.year and span.end_year for span in parse_dates(parsed.text)
    )
    percent = "prosent" in text or "percent" in text
    how_much = any(piece in text for piece in ("hve mikid", "how much", "by how much"))
    asks_level = text.startswith("what was") or text.startswith("hver var") or text.startswith("hvert var")
    if operation == "share" and asks_level and not text.startswith("what percentage") and "hvert hlutfall" not in text:
        operation = "level"
    if ranged and percent and not how_much:
        return "yoy_pct"
    if ranged and (how_much or any(piece in text for piece in ("haekk", "laekk", "rise", "rose", "fell", "fall", "increas", "decreas"))):
        if percent and not how_much:
            return "yoy_pct"
        return "difference"
    return operation


def binding_from_values(edition, parsed: ParsedQuestion):
    """A Binding the existing fetch and arithmetic already understand."""
    choices = bind_values(parsed.text, edition)
    by_code: dict[str, list] = {}
    for choice in choices:
        by_code.setdefault(choice.variable_code, []).append(choice)
    chosen: dict[str, list[str]] = {}
    time_var = None
    time_codes: list[str] = []
    for variable in edition.variables:
        picks = by_code.get(variable.code) or []
        if variable.time:
            codes = _time_codes(picks, variable)
            if not codes:
                if variable.elimination:
                    continue
                return None
            time_var = variable.code
            time_codes = codes
            chosen[variable.code] = codes
            continue
        if not picks:
            if getattr(variable, "elimination", False):
                continue
            return None
        chosen[variable.code] = [picks[0].value_code]

    operation = resolve_operation(parsed)
    notes = ["lang bind", operation]
    if operation in {"yoy_pct", "difference"} and len(time_codes) < 2:
        filled = _span_codes(parsed, edition)
        if filled is not None:
            time_var, time_codes = filled
            chosen[time_var] = time_codes
    if operation in {"yoy_pct", "difference"} and len(time_codes) < 2:
        return None

    group_var = None
    part_code = None
    whole_code = None
    if operation == "share":
        from grund_lang.lemma import analyze
        from grund_lang.ratio import ratio_members

        members = ratio_members(edition, analyze(parsed.text))
        if members is None:
            return None
        group_var, part_code, whole_code = members
        codes = [part_code]
        if whole_code not in codes:
            codes.append(whole_code)
        chosen[group_var] = codes
        notes.append("ratio share_percent (part / whole) * 100")
        notes.append("recompute the percent from the cited part and total; do not supply a number")

    selections = [
        {"code": code, "selection": {"filter": "item", "values": values}}
        for code, values in chosen.items()
        if values
    ]
    binding = Binding(
        edition=edition,
        selections=selections,
        operation=operation,
        score=1.0,
        time_var=time_var,
        time_codes=time_codes,
        group_var=group_var,
        part_code=part_code,
        whole_code=whole_code,
        notes=notes,
        official_measure=False,
    )
    try:
        validate(edition, binding.selections)
    except ValidationError:
        return None
    return binding


def sentence_allowed(rows, derived=None, population=None) -> list[float]:
    """Cell figures only. Declared claims replace the label-digit allow-list."""
    from grund.compute import allowed_numbers

    return allowed_numbers(rows, derived, population)


class LangEngine(Engine):
    """Engine whose deterministic shortlist and codes come from grund_lang."""

    def __init__(self, catalogue, retrieval, **kwargs) -> None:
        super().__init__(catalogue, **kwargs)
        self.retrieval = retrieval
        self.planner = "deterministic"

    def ask(self, question: str, language: str | None = None):
        import grund.engine as engine_mod

        saved = self.catalogue.search
        saved_allowed = engine_mod.allowed_numbers
        self.catalogue.search = self._lang_search
        engine_mod.allowed_numbers = sentence_allowed
        try:
            return super().ask(question, language)
        finally:
            self.catalogue.search = saved
            engine_mod.allowed_numbers = saved_allowed

    def _lang_search(self, question: str, k: int = 12, years: list[int] | None = None):
        hits = []
        for candidate in self.retrieval.search(question, k=k):
            table = self.catalogue.by_id.get(f"{candidate.table_id}.px")
            if table is None:
                table = self.catalogue.by_id.get(candidate.table_id)
            if table is None:
                continue
            hits.append(
                Hit(
                    table=table,
                    score=candidate.score,
                    bm25=candidate.bm25,
                    cosine=candidate.cosine,
                    value_boost=candidate.value_bm25,
                )
            )
        return hits

    def _rank(self, parsed: ParsedQuestion, hits: list[Hit]):
        ranked = []
        for hit in hits:
            edition = hit.table.edition(parsed.language) or hit.table.edition("en")
            if edition is None:
                continue
            binding = binding_from_values(edition, parsed)
            if binding is None:
                continue
            ranked.append((hit.score * 10, binding, hit.table))
            ranked.sort(key=lambda item: (-round(item[0], 6), item[2].id))
        return ranked


def attach(engine: Engine, index_dir: str | Path) -> None:
    """Point an existing engine at a saved language index. Used by a tree copy."""
    retrieval = load_index(Path(index_dir))
    engine.retrieval = retrieval
    engine.planner = "deterministic"
    engine._lang_engine = LangEngine(engine.catalogue, retrieval, client=engine.client, rails=engine.rails, planner="deterministic")
    engine.ask = engine._lang_engine.ask


def maybe_attach(engine: Engine) -> None:
    index_dir = os.environ.get("GRUND_LANG_INDEX")
    if index_dir:
        attach(engine, index_dir)
