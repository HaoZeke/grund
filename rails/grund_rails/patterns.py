"""Deterministic shapes for jailbreaks and injected instructions.

These are a floor, the same role vangrail gives Rails::Jailbreak and
Rails::InjectedInstructions. A rephrasing walks past them. They exist so the
copied-and-pasted majority never reaches a model, including when no model
is configured. Patterns are original to this entry; the categories follow
the vangrail rails.
"""

from __future__ import annotations

import re

from grund_rails.rail import Rail
from grund_rails.result import Result

JAILBREAK = {
    "unrestricted_persona": re.compile(
        r"\b(you are|act as|pretend to be|roleplay as|þú ert)\b.{0,80}\b"
        r"(dan|do anything now|jailbroken|unfiltered|unrestricted|án takmarkana|engin takmörk)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "restrictions_lifted": re.compile(
        r"\b(developer|debug|god|sudo|dan)\s+mode\b.{0,40}\b(enabled|activated|on)\b"
        r"|\b(enter|activate|enable)\s+(developer|debug|god|dan)\s+mode\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "dual_answer": re.compile(
        r"\b(answer|respond|svara)\b.{0,40}\b(two|both|tvær)\b.{0,30}\b(ways|versions|answers|útgáfur)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "forged_authority": re.compile(
        r"\b(as your developer|this is your creator|ég er forritarinn þinn)\b.{0,60}\b"
        r"(you must|you are now permitted|þú verður)\b",
        re.IGNORECASE | re.DOTALL,
    ),
}

INJECTED = {
    "role_header": re.compile(
        r"(?m)^\s{0,3}(?:###\s*)?(system|assistant|user|kerfi|aðstoðarmaður)\s*:\s*\S",
        re.IGNORECASE,
    ),
    "override_above": re.compile(
        r"\b(ignore|disregard|forget|override|hunsa|gleyma)\b.{0,40}\b"
        r"(instructions|guidelines|rules|above|fyrirmæli|leiðbeiningar|reglur)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "role_assignment": re.compile(
        r"\b(you are now|you must now act as|þú ert nú)\b.{0,40}\b(assistant|model|chatbot|dan)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "exfiltration": re.compile(
        r"\b(reveal|print|repeat|output|sýndu|prenta)\b.{0,40}\b"
        r"(system prompt|api[_ -]?key|token|credentials|leynilykil)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "hidden_directive": re.compile(
        r"<!--.{0,120}\b(ignore|instruction|system|hunsa|fyrirmæli)\b.{0,80}-->",
        re.IGNORECASE | re.DOTALL,
    ),
}


class PatternRail(Rail):
    patterns: dict[str, re.Pattern[str]]

    def decide(self, text: str, context: dict) -> Result:
        hits = [name for name, pattern in self.patterns.items() if pattern.search(text)]
        if not hits:
            return Result.passed(self.name)
        return Result.blocked(
            self.name,
            categories=hits,
            reason=f"{self.name}: {', '.join(hits)}",
        )


class JailbreakRail(PatternRail):
    name = "jailbreak"
    sides = ("input", "context")
    patterns = JAILBREAK


class InjectedInstructionsRail(PatternRail):
    name = "injected_instructions"
    sides = ("input", "context")
    patterns = INJECTED
