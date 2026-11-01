"""Every figure in the prose must be on the code path's allow-list."""

from __future__ import annotations

from grund_rails.numbers import find_numbers, matches
from grund_rails.rail import Rail
from grund_rails.result import Result


class NumberGroundingRail(Rail):
    name = "number_grounding"
    sides = ("output",)

    def decide(self, text: str, context: dict) -> Result:
        allowed = context.get("allowed")
        if allowed is None:
            return Result.unchecked(self.name, "no allow-list supplied")
        language = context.get("language") or "en"
        allowed_values = [float(value) for value in allowed]
        stray = []
        for number in find_numbers(text, language):
            if any(matches(number, permitted) for permitted in allowed_values):
                continue
            stray.append(number)
        if stray:
            rendered = ", ".join(f"{number:g}" for number in stray)
            return Result.blocked(
                self.name,
                reason=f"figures not in fetched cells or derived values: {rendered}",
                categories=["ungrounded_number"],
            )
        return Result.passed(self.name)


class CitationRail(Rail):
    """An answer that states a value has to carry a source card."""

    name = "citation"
    sides = ("output",)

    def decide(self, text: str, context: dict) -> Result:
        if context.get("refused") or context.get("clarify"):
            return Result.passed(self.name)
        source = context.get("source")
        if not isinstance(source, dict):
            return Result.blocked(self.name, reason="answer has no source card", categories=["missing_source"])
        missing = [
            field
            for field in ("table_id", "retrieved_at", "cells", "api_url")
            if not source.get(field)
        ]
        if missing:
            return Result.blocked(
                self.name,
                reason=f"source card missing {', '.join(missing)}",
                categories=["incomplete_source"],
            )
        return Result.passed(self.name)


class RefusalRail(Rail):
    """A refusal may echo the question. It may not introduce a figure."""

    name = "refusal"
    sides = ("output",)

    def decide(self, text: str, context: dict) -> Result:
        if not (context.get("refused") or context.get("clarify")):
            if not (text or "").strip():
                return Result.blocked(self.name, reason="empty answer", categories=["empty"])
            return Result.passed(self.name)
        language = context.get("language") or "en"
        question = context.get("question") or ""
        from grund_rails.numbers import find_numbers, matches

        allowed = find_numbers(question, language) + find_numbers(question, "en") + find_numbers(question, "is")
        stray = []
        for number in find_numbers(text, language):
            if any(matches(number, permitted) for permitted in allowed):
                continue
            stray.append(number)
        if stray:
            rendered = ", ".join(f"{number:g}" for number in stray)
            return Result.blocked(
                self.name,
                reason=f"refusal introduced figures: {rendered}",
                categories=["refusal_number"],
            )
        return Result.passed(self.name)
