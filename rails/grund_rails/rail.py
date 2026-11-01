"""One object, one method, three statuses."""

from __future__ import annotations

from grund_rails.result import Result

SIDES = ("input", "context", "output")


class Rail:
    name = "rail"
    sides = ("input", "output")

    def applies_to(self, side: str) -> bool:
        return side in self.sides

    def decide(self, text: str, context: dict) -> Result:
        raise NotImplementedError

    def __call__(self, text: str, context: dict | None = None) -> Result:
        return self.decide(text or "", context or {})
