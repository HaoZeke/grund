"""Run the rails on one side, in order."""

from __future__ import annotations

from grund_rails.patterns import InjectedInstructionsRail, JailbreakRail
from grund_rails.rail import Rail
from grund_rails.result import Result


class RailEngine:
    def __init__(self, rails: list[Rail]) -> None:
        self.rails = rails

    def run(self, side: str, text: str, context: dict | None = None) -> list[Result]:
        ctx = dict(context or {})
        ctx["side"] = side
        results = []
        current = text
        for rail in self.rails:
            if not rail.applies_to(side):
                continue
            result = rail(current, ctx)
            results.append(result)
            if result.blocked_turn():
                break
            if result.modified_ok() and result.content is not None:
                current = result.content
        return results

    def first_block(self, results: list[Result]) -> Result | None:
        for result in results:
            if result.blocked_turn():
                return result
        return None


def default_engine() -> RailEngine:
    return RailEngine(
        [
            JailbreakRail(),
            InjectedInstructionsRail(),
        ]
    )
