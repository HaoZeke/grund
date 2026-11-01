import pytest

from grund.answer import refusal
from grund.engine import underspecified_cpi_month
from grund.parse import parse_question

from test_engine import FakeClient, engine


def test_month_clarify_is_off_unless_the_flag_is_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GRUND_CLARIFY_MONTH", raising=False)
    parsed = parse_question("What was the consumer price index in 2024?")
    assert underspecified_cpi_month(parsed) is False
    result = engine().ask("What was the consumer price index in June 2024?")
    assert result["refused"] is False
    assert result["value"] == "630.3"


def test_flag_asks_for_a_month_and_does_not_fetch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRUND_CLARIFY_MONTH", "1")
    asked = engine()
    asked.client = FakeClient()
    year = asked.ask("What was the consumer price index in 2024?")
    assert year["refused"] is True
    assert year["clarify"] is True
    assert year["value"] is None
    assert year["table_id"] is None
    assert "every month" in year["answer"]

    icelandic = parse_question("Hver var vísitala neysluverðs árið 2024?")
    assert underspecified_cpi_month(icelandic) is True
    assert icelandic.language == "is"
    assert "mánuði" in refusal("is", "clarify_month")

    june = asked.ask("What was the consumer price index in June 2024?")
    assert june["refused"] is False
    assert june["value"] == "630.3"

    annual = parse_question("What was the consumer price index, annual averages, in 2024?")
    assert underspecified_cpi_month(annual) is False
