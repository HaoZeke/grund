"""A lockable read grant for the PxWeb POST.

Same split as vangrail's Plan: the grant is written down, then locked.
The fetch is allowed only when the table id and the query match the grant.
Nothing in a model reply can add a grant after lock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


class PlanError(RuntimeError):
    pass


@dataclass
class Grant:
    tool: str
    effect: str
    arguments: dict
    uses: int = 1
    used: int = 0

    def allows(self, tool: str, arguments: dict) -> bool:
        if self.tool != tool or self.effect != "read":
            return False
        if self.used >= self.uses:
            return False
        return _canonical(self.arguments) == _canonical(arguments)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


@dataclass
class Plan:
    grants: list[Grant] = field(default_factory=list)
    locked: bool = False
    audit: list[str] = field(default_factory=list)

    def read(self, tool: str, arguments: dict, uses: int = 1) -> Grant:
        if self.locked:
            raise PlanError("the plan is locked")
        grant = Grant(tool=tool, effect="read", arguments=arguments, uses=uses)
        self.grants.append(grant)
        self.audit.append(f"grant {tool}")
        return grant

    def lock(self) -> "Plan":
        self.locked = True
        self.audit.append("locked")
        return self

    def check_call(self, tool: str, arguments: dict) -> Grant:
        if not self.locked:
            raise PlanError("refusing to call a tool on an unlocked plan")
        for grant in self.grants:
            if grant.allows(tool, arguments):
                grant.used += 1
                self.audit.append(f"used {tool}")
                return grant
        raise PlanError(f"no grant for {tool}")
