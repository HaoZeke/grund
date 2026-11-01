"""GRUND_PATH selects the answer path. The default is the ranker."""

from __future__ import annotations

from grund.engine import Engine
from grund.toolpath import PathError, answer_path
from grund_index.catalogue import Hit
from grund_index.model import Edition, Table, Variable


def test_the_default_path_is_the_ranker(monkeypatch):
    monkeypatch.delenv("GRUND_PATH", raising=False)
    assert answer_path() == "ranker"


def test_tools_and_hybrid_are_explicit(monkeypatch):
    monkeypatch.setenv("GRUND_PATH", "tools")
    assert answer_path() == "tools"
    monkeypatch.setenv("GRUND_PATH", "hybrid")
    assert answer_path() == "hybrid"


def test_an_unknown_path_is_rejected(monkeypatch):
    monkeypatch.setenv("GRUND_PATH", "primary")
    try:
        answer_path()
    except PathError as exc:
        assert "GRUND_PATH" in str(exc)
    else:
        raise AssertionError("unknown path was accepted")


class _Client:
    def post_json(self, url, body):
        return {"data": [{"key": ["2024"], "values": ["394324"]}]}


def test_hybrid_uses_the_shortlist_then_the_rail(monkeypatch):
    monkeypatch.setenv("GRUND_PATH", "hybrid")
    edition = Edition(
        lang="en",
        title="Population",
        db="Ibuar",
        path=["Ibuar"],
        path_texts=["Population"],
        url="https://px.hagstofa.is/pxen/api/v1/en/Ibuar/MAN00000.px",
        updated="2026-01-01",
        variables=[
            Variable("Year", "Year", True, False, [("2024", "2024")]),
        ],
    )
    table = Table(id="MAN00000.px", editions={"en": edition})
    hit = Hit(table=table, score=1.0, bm25=1.0, cosine=0.0, value_boost=0.0)

    class Catalogue:
        tables: list = []

    engine = Engine(Catalogue(), client=_Client(), planner="deterministic")
    engine._lang_shortlist = lambda question, k=20: ([hit], {})
    result = engine.ask("How many people lived in Iceland in 2024?")
    assert result["refused"] is False
    assert result["planner"] == "hybrid"
    assert result["table_id"] == "MAN00000.px"
    assert "394" in result["answer"]
