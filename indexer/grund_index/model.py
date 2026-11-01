"""In-memory catalogue records built from the crawl."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Variable:
    code: str
    text: str
    time: bool
    elimination: bool
    values: list[tuple[str, str]]

    def label(self, code: str) -> str:
        for value_code, value_text in self.values:
            if value_code == code:
                return value_text or value_code
        return code

    def codes(self) -> list[str]:
        return [code for code, _text in self.values]


@dataclass
class Edition:
    lang: str
    title: str
    db: str
    path: list[str]
    path_texts: list[str]
    url: str
    updated: str | None
    variables: list[Variable]
    notes: str | None = None

    def time_variable(self) -> Variable | None:
        for variable in self.variables:
            if variable.time:
                return variable
        return None

    def variable(self, code: str) -> Variable | None:
        for variable in self.variables:
            if variable.code == code:
                return variable
        return None

    def years(self) -> set[int]:
        variable = self.time_variable()
        found: set[int] = set()
        if variable is None:
            return found
        for code, text in variable.values:
            for match in re.findall(r"(?:19|20)\d{2}", f"{code} {text}"):
                found.add(int(match))
        return found


@dataclass
class Table:
    id: str
    editions: dict[str, Edition] = field(default_factory=dict)

    def edition(self, lang: str) -> Edition | None:
        if lang in self.editions:
            return self.editions[lang]
        if not self.editions:
            return None
        return next(iter(self.editions.values()))

    def titles(self) -> str:
        return " ".join(edition.title for edition in self.editions.values())

    def databases(self) -> set[str]:
        return {edition.db for edition in self.editions.values()}
