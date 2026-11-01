"""Records shared by the language layer and the retrieval index."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Token:
    surface: str
    folded: str
    lemma: str
    lemma_surface: str
    pos: str
    tag: str
    source: str


@dataclass(frozen=True)
class CompoundSplit:
    surface: str
    parts: tuple[str, ...]


@dataclass(frozen=True)
class DateSpan:
    """A time expression in a question.

    `    kind` is one of point, year, year_end, year_start, quarter, month,
    between_years, annual_average, recent_years.
    """

    kind: str
    year: int | None = None
    quarter: int | None = None
    month: int | None = None
    day: int | None = None
    end_year: int | None = None
    end_quarter: int | None = None
    end_month: int | None = None
    count: int | None = None
    raw: str = ""


@dataclass(frozen=True)
class NumberSpan:
    value: float
    raw: str
    kind: str


@dataclass
class Analysis:
    text: str
    language: str
    tokens: list[Token] = field(default_factory=list)
    compounds: list[CompoundSplit] = field(default_factory=list)
    numbers: list[NumberSpan] = field(default_factory=list)
    dates: list[DateSpan] = field(default_factory=list)
    bases: list[int] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValueChoice:
    """One PxWeb value the question most likely selects on one variable."""

    variable_code: str
    variable_text: str
    value_code: str
    value_label: str
    role: str
    score: float
    why: str


@dataclass
class Candidate:
    """A catalogue table, with the values most likely to bind."""

    table_id: str
    score: float
    bm25: float
    cosine: float
    bindings: list[ValueChoice] = field(default_factory=list)
    bm25_rank: int = 0
    cosine_rank: int = 0
    value_bm25: float = 0.0
