"""Three statuses, and a separate certainty flag.

Mirrors the contract in vangrail's Result: passed, modified, blocked.
certain is false when nothing was checked. That state is not a clean pass
even though the status is passed, matching Vangrail::Result.unchecked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATUSES = ("passed", "modified", "blocked")


@dataclass
class Result:
    status: str
    rail: str
    content: str | None = None
    reason: str | None = None
    categories: list[str] = field(default_factory=list)
    certain: bool = True

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")

    @classmethod
    def passed(cls, rail: str, **kwargs) -> "Result":
        return cls(status="passed", rail=rail, **kwargs)

    @classmethod
    def modified(cls, rail: str, content: str, **kwargs) -> "Result":
        return cls(status="modified", rail=rail, content=content, **kwargs)

    @classmethod
    def blocked(cls, rail: str, **kwargs) -> "Result":
        return cls(status="blocked", rail=rail, **kwargs)

    @classmethod
    def unchecked(cls, rail: str, reason: str, **kwargs) -> "Result":
        return cls(status="passed", rail=rail, certain=False, reason=reason, **kwargs)

    def passed_ok(self) -> bool:
        return self.status == "passed"

    def modified_ok(self) -> bool:
        return self.status == "modified"

    def blocked_turn(self) -> bool:
        return self.status == "blocked"

    def allowed(self) -> bool:
        return not self.blocked_turn()

    def content_or(self, original: str) -> str:
        return original if self.content is None else self.content

    def to_dict(self) -> dict:
        payload = {
            "status": self.status,
            "certain": self.certain,
            "rail": self.rail,
            "reason": self.reason,
        }
        if self.categories:
            payload["categories"] = self.categories
        return payload
