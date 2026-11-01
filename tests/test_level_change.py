"""A level cell is refused only when the question asked for a change, and the reverse."""

from grund.level_change import asked, enabled, mismatch, stated


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("GRUND_LEVEL_CHANGE_VETO", raising=False)
    assert enabled() is False
    assert mismatch("How much did the CPI change in June 2025?", {"value": "656.5", "operation": "level"}) is False


def test_a_change_question_keeps_a_change_cell(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    question = "Um hve margar gistinætur fækkaði frá 2023 til 2024?"
    assert asked(question) == "change"
    result = {"value": "-173239", "operation": "difference", "claims": []}
    assert stated(result) == "change"
    assert mismatch(question, result) is False


def test_a_change_question_refuses_an_index_level(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    question = "How much did the consumer price index change in June 2025?"
    result = {
        "value": "656.5",
        "operation": "level",
        "claims": [{"cells": [{"coords": {"Liður": "index"}, "labels": {"Item": "Index"}}]}],
    }
    assert asked(question) == "change"
    assert stated(result) == "level"
    assert mismatch(question, result) is True


def test_a_level_question_refuses_the_change_column(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    question = "What was the consumer price index in December 2023?"
    result = {
        "value": "4.2",
        "operation": "level",
        "claims": [{"cells": [{"labels": {"Item": "Annual change"}}]}],
    }
    assert asked(question) == "level"
    assert stated(result) == "change"
    assert mismatch(question, result) is True


def test_a_level_question_keeps_a_level(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    question = "How many people lived in Iceland on 1 January 2026?"
    result = {"value": "394324", "operation": "level", "claims": [{"cells": [{"labels": {"Unit": "Number"}}]}]}
    assert mismatch(question, result) is False


def test_a_point_rise_is_a_change_and_keeps_the_difference(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    question = "By how many points did the wage index rise from August 2025 to August 2026?"
    assert asked(question) == "change"
    assert mismatch(question, {"value": "61.6", "operation": "difference", "claims": []}) is False


def test_a_percentage_is_not_a_change(monkeypatch):
    monkeypatch.setenv("GRUND_LEVEL_CHANGE_VETO", "1")
    assert asked("What percentage of the population were women?") is None
    assert mismatch("What percentage of the population were women?", {"value": "48.7", "operation": "share"}) is False
