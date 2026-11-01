"""A look-alike on the other path does not refuse the series the gate accepts."""

import grund.keep_gate as keep_gate
from grund.keep_gate import path_to_keep
from grund.loose_gate import loose_gate_reason


def test_the_flag_is_on_unless_turned_off(monkeypatch):
    monkeypatch.delenv("GRUND_KEEP", raising=False)
    assert keep_gate.keep_enabled()
    monkeypatch.setenv("GRUND_KEEP", "0")
    assert not keep_gate.keep_enabled()


def test_a_refused_lookalike_keeps_the_other_path(monkeypatch):
    monkeypatch.delenv("GRUND_KEEP", raising=False)

    def reason(_catalogue, _question, _language, result):
        if result.get("table_id") == "LOOK.px":
            return "measure"
        return None

    monkeypatch.setattr("grund.loose_gate.loose_gate_reason", reason)
    ranker = {"value": 1064, "table_id": "MAN07109.px", "refused": False}
    hybrid = {"value": 900, "table_id": "LOOK.px", "refused": False}
    kept = path_to_keep(None, "by how much did families increase", "en", ranker, hybrid)
    assert kept is not None
    assert kept[0]["table_id"] == "MAN07109.px"


def test_two_accepted_paths_still_disagree(monkeypatch):
    monkeypatch.setattr("grund.loose_gate.loose_gate_reason", lambda *args: None)
    ranker = {"value": 1, "table_id": "A.px", "refused": False}
    hybrid = {"value": 2, "table_id": "B.px", "refused": False}
    assert path_to_keep(None, "question", "en", ranker, hybrid) is None


def test_the_flag_off_keeps_nothing(monkeypatch):
    monkeypatch.setenv("GRUND_KEEP", "0")
    ranker = {"value": 1, "table_id": "A.px", "refused": False}
    hybrid = {"value": 2, "table_id": "B.px", "refused": False}
    assert path_to_keep(None, "question", "en", ranker, hybrid) is None


def test_points_are_not_a_different_series():
    result = {
        "value": 39,
        "operation": "difference",
        "answer": "The change was 39. That is the change from 658.3 to 697.3.",
        "claims": [{
            "op": "difference",
            "cells": [{
                "title": "Consumer price index and changes, base 1988=100",
                "labels": {"Index": "Consumer price index"},
            }],
        }],
    }
    question = "By how many points did the consumer price index rise from September 2025 to September 2026?"
    assert loose_gate_reason(None, question, "en", result) is None


def test_women_may_not_cite_sex_total():
    result = {
        "value": 389444,
        "operation": "level",
        "answer": "In 2025, women, Total in Population by sex was 389,444.",
        "claims": [{"cells": [{"labels": {"Sex": "Total", "Age": "Total"}}]}],
    }
    assert loose_gate_reason(None, "How many women lived in Iceland on 1 January 2025?", "en", result) == "sex-total"


def test_a_women_share_may_cite_the_total_as_well():
    result = {
        "value": 48.7,
        "operation": "share",
        "answer": "In 2026, Females was 48.7 percent of Total.",
        "claims": [{"cells": [
            {"labels": {"Sex": "Females", "Year": "2026"}},
            {"labels": {"Sex": "Total", "Year": "2026"}},
        ]}],
    }
    assert loose_gate_reason(None, "What percentage of Iceland's population were women?", "en", result) is None


def test_a_female_row_is_kept():
    result = {
        "value": 189623,
        "operation": "level",
        "answer": "In 2025, Females in Population by sex was 189,623.",
        "claims": [{"cells": [{"labels": {"Sex": "Females", "Age": "Total"}}]}],
    }
    assert loose_gate_reason(None, "How many women lived in Iceland on 1 January 2025?", "en", result) is None
