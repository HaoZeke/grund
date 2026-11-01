"""A named subgroup is kept only when the mapper selected that cell."""

import os

from grund.subgroup_guard import _measure_conflict, enabled, guard_reason
from grund_index.model import Edition, Variable


def _edition():
    return Edition(
        "en",
        "Population by sex and age",
        "db",
        [],
        [],
        "https://example",
        None,
        [
            Variable("Kyn", "Sex", False, False, [("0", "Total"), ("1", "Males"), ("2", "Females")]),
            Variable("Aldur", "Age", False, False, [("0", "Total"), ("1", "16-24")]),
            Variable("Ár", "Year", True, False, [("2018", "2018")]),
        ],
    )


class _Table:
    def __init__(self, edition):
        self.id = "MAN00101.px"
        self._edition = edition

    def edition(self, lang):
        return self._edition


class _Catalogue:
    def __init__(self, edition):
        self.by_id = {"MAN00101.px": _Table(edition), "MAN00101": _Table(edition)}


class _Engine:
    def __init__(self, edition):
        self.catalogue = _Catalogue(edition)


class _Parsed:
    text = "How many women lived in Iceland in 2018?"
    language = "en"
    periods = [(2018, None)]


def _result(labels, title="Population by sex and age"):
    return {
        "refused": False,
        "value": "1",
        "table_id": "MAN00101.px",
        "source": {"title": title},
        "claims": [{"cells": [{"labels": labels, "title": title}]}],
    }


def test_flag_off_keeps_the_figure(monkeypatch):
    monkeypatch.delenv("GRUND_SUBGROUP_GUARD", raising=False)
    assert enabled() is False
    assert guard_reason(_Engine(_edition()), _Parsed(), _result({"Sex": "Females"})) is None


def test_mapper_women_keeps_the_female_cell(monkeypatch):
    monkeypatch.setenv("GRUND_SUBGROUP_GUARD", "1")
    assert guard_reason(_Engine(_edition()), _Parsed(), _result({"Sex": "Females"})) is None


def test_a_missing_women_row_is_a_disagreement(monkeypatch):
    monkeypatch.setenv("GRUND_SUBGROUP_GUARD", "1")
    edition = _edition()
    edition.variables[0] = Variable("Kyn", "Sex", False, False, [("0", "Total")])
    reason = guard_reason(_Engine(edition), _Parsed(), _result({"Sex": "Total"}))
    assert reason == "subgroup-guard:mapper"


def test_the_activity_sheet_is_not_the_employment_rate():
    question = "what was the employment rate for women in iceland in 2018"
    assert _measure_conflict(question, "Activity rate, employment rate, underemployment rate and unemployment rate by year")
    assert _measure_conflict(question, "Employed - number and percent by year") is False


def test_avoidable_deaths_are_not_plain_deaths():
    assert _measure_conflict("hve margir karlar dou a islandi arid 2016", "Otimabaer daudsfall")
    assert _measure_conflict("how many women died in iceland in 2018", "Members of associations of artists")
    assert _measure_conflict("how many women died in iceland in 2018", "Deaths and crude death rate by sex and age") is False


def test_a_line_of_study_table_is_not_the_matriculation_count():
    question = "how many men passed the matriculation examination in iceland in the 2018-2019 school year"
    assert _measure_conflict(question, "Graduations with matriculation examination by line of study, type of examination and sex")
    assert _measure_conflict(question, "Students passing matriculation examination by domicile, age and sex") is False


def test_an_account_code_is_not_an_age_band(monkeypatch):
    monkeypatch.setenv("GRUND_SUBGROUP_GUARD", "1")
    parsed = _Parsed()
    parsed.text = "What was Income statement and balance sheet for sheep farms by number of livestock, 01-02-04 Depreciation in 2024?"
    assert guard_reason(_Engine(_edition()), parsed, _result({"Item": "01-02-04 Depreciation"})) is None


def test_a_question_without_a_subgroup_is_kept(monkeypatch):
    monkeypatch.setenv("GRUND_SUBGROUP_GUARD", "1")
    parsed = _Parsed()
    parsed.text = "What was the unemployment rate in Iceland in the second quarter of 2026?"
    assert guard_reason(_Engine(_edition()), parsed, _result({"Sex": "Total"})) is None
