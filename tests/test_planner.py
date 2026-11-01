import json

from grund.engine import Engine
from grund.llm import LLMSettings
from grund.parse import parse_question
from grund.planner import (
    candidate_values,
    confidence_band,
    query_schema,
    shortlist,
    use_model_selections,
)
from grund_index.catalogue import Catalogue
from grund_index.embed import Embedder
from grund_index.model import Table, Variable
from test_bind import cpi, population
from test_engine import FakeClient


class ScriptedChat:
    def __init__(self, content: str):
        self.settings = LLMSettings(base_url="http://127.0.0.1:9/v1", model="scripted", api_key="local", timeout=1)
        self.content = content
        self.calls = []

    def complete(self, messages, temperature=0.0, response_format=None, max_tokens=None):
        self.calls.append({"messages": messages, "response_format": response_format, "max_tokens": max_tokens})
        return self.content


def catalogue():
    tables = [
        Table(id="VIS01000.px", editions={"en": cpi()}),
        Table(id="MAN00101.px", editions={"en": population()}),
    ]
    return Catalogue(tables, Embedder(kind="chargram"), None, "none")


def test_shortlist_schema_only_offers_codes_the_table_has():
    parsed = parse_question("What was the consumer price index in June 2024?")
    hits = catalogue().search(parsed.text, k=4)
    cards = shortlist(hits, parsed)
    schema = query_schema(cards, parsed)
    offered = set()
    for branch in schema["oneOf"]:
        selections = branch["properties"].get("selections")
        if not selections:
            continue
        for variable, spec in selections["properties"].items():
            offered.update(spec["items"]["enum"])
            assert spec["items"]["enum"]
    assert "2024M06" in offered
    assert "CPI" in offered
    prompt = ScriptedChat("{}")
    # The labels, not only the codes, are what the model reads.
    rendered = cards[0]
    assert rendered[0] == "VIS01000.px"
    labels = [label for _variable, values in rendered[2] for _code, label in values]
    assert "Consumer price index" in labels


def test_a_long_time_list_keeps_the_named_period():
    variable = Variable("Ár", "Year", True, False, [(str(year), str(year)) for year in range(1990, 2026)])
    parsed = parse_question("What was the figure in 2024?")
    codes = [code for code, _label in candidate_values(variable, parsed)]
    assert codes == ["2024"]
    assert len(codes) < 8


def test_low_confidence_uses_the_deterministic_figure():
    chat = ScriptedChat(json.dumps({"action": "refuse", "confidence": "low"}))
    result = Engine(catalogue(), client=FakeClient(), chat=chat, planner="hybrid").ask(
        "What was the consumer price index in June 2024?"
    )
    assert result["refused"] is False
    assert result["value"] == "630.3"
    assert result["table_id"] == "VIS01000.px"
    assert result["source"]["planner"] == "deterministic"
    assert any("hybrid fell back" in note for note in result["source"]["planner_notes"])
    schema = chat.calls[0]["response_format"]["json_schema"]["schema"]
    assert schema["oneOf"]
    assert all(branch["properties"]["action"]["enum"] == ["query"] for branch in schema["oneOf"])


def test_high_confidence_keeps_the_model_codes():
    plan = {
        "action": "query",
        "confidence": "high",
        "table_id": "VIS01000.px",
        "selections": {"Month": ["2024M06"], "Index": ["CPI"], "Item": ["index"]},
    }
    result = Engine(catalogue(), client=FakeClient(), chat=ScriptedChat(json.dumps(plan)), planner="hybrid").ask(
        "What was the consumer price index in June 2024?"
    )
    assert result["refused"] is False
    assert result["value"] == "630.3"
    assert result["source"]["planner"] == "hybrid"
    assert result["source"]["official_measure"] is False


def test_high_confidence_on_different_codes_keeps_the_deterministic_figure():
    plan = {
        "action": "query",
        "confidence": "high",
        "table_id": "VIS01000.px",
        "selections": {"Month": ["2025M06"], "Index": ["CPI"], "Item": ["index"]},
    }
    result = Engine(catalogue(), client=FakeClient(), chat=ScriptedChat(json.dumps(plan)), planner="hybrid").ask(
        "What was the consumer price index in June 2024?"
    )
    assert result["value"] == "630.3"
    assert result["source"]["planner"] == "deterministic"
    assert any("disagree" in note for note in result["source"]["planner_notes"])


def test_medium_confidence_does_not_override_the_deterministic_plan():
    plan = {
        "action": "query",
        "confidence": "medium",
        "table_id": "VIS01000.px",
        "selections": {"Month": ["2025M06"], "Index": ["CPI"], "Item": ["index"]},
    }
    result = Engine(catalogue(), client=FakeClient(), chat=ScriptedChat(json.dumps(plan)), planner="hybrid").ask(
        "What was the consumer price index in June 2024?"
    )
    assert result["value"] == "630.3"
    assert result["source"]["planner"] == "deterministic"


def test_model_planner_keeps_the_template_sentence():
    plan = {
        "action": "query",
        "confidence": "high",
        "table_id": "VIS01000.px",
        "selections": {"Month": ["2024M06"], "Index": ["CPI"], "Item": ["index"]},
    }
    chat = ScriptedChat(json.dumps(plan))
    result = Engine(catalogue(), client=FakeClient(), chat=chat, planner="model").ask(
        "What was the consumer price index in June 2024?"
    )
    assert result["refused"] is False
    assert result["value"] == "630.3"
    assert "630.3" in result["answer"]
    assert result["planner"] == "model"
    assert len(chat.calls) == 1
    assert "sentence" not in chat.calls[0]["messages"][0]["content"].lower()


def test_confidence_bands_and_rank_gate():
    assert confidence_band("high") == "high"
    assert confidence_band(0.9) == "high"
    assert confidence_band(75) == "medium"
    assert confidence_band(0.2) == "low"
    assert use_model_selections("high", "VIS01000.px", "MAN00101.px", 1)
    assert not use_model_selections("medium", "VIS01000.px", "VIS01000.px", 1)
    assert not use_model_selections("high", "OTHER.px", "VIS01000.px", 4)
    assert use_model_selections("high", "VIS01000.px", "VIS01000.px", 4)
