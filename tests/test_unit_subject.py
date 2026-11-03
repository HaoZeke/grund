"""Units and subjects are carried by the stated cell, read from the catalogue alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from grund import row_guard
from grund.bind import is_total
from grund.measure_carried import carried_decide
from grund.unit_subject import asked_units, subject_missing, unit_decide, units
from grund_index.catalogue import Catalogue

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.load(ROOT / "data" / "index")


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")


def _cell(catalogue, table_id, lang, period, rows=None):
    edition = catalogue.by_id[table_id + ".px"].editions[lang]
    labels = []
    for variable in edition.variables:
        if variable.time:
            labels.append({"variable": variable.code, "code": str(period), "label": str(period)})
            continue
        wanted = (rows or {}).get(variable.code)
        if wanted:
            code, label = next((c, l) for c, l in variable.values if str(c) == wanted)
        else:
            code, label = next(((c, l) for c, l in variable.values if is_total(l or c)), variable.values[0])
        labels.append({"variable": variable.code, "code": str(code), "label": str(label)})
    return {"table_id": table_id + ".px", "value": "1", "language": lang, "source": {"language": lang, "cells": [{"labels": labels}]}}


def test_units_come_from_value_labels(catalogue):
    vocabulary = units(catalogue)
    assert {"gwh", "mw"} <= vocabulary
    assert not {"january", "januar", "persons", "index", "dairy"} & vocabulary
    assert all(len(word) > 1 for word in vocabulary)


def test_a_question_asks_in_the_units_it_writes(catalogue):
    assert asked_units("How much electricity did geothermal plants generate in 2015, in GWh?", catalogue) == ["gwh"]
    assert asked_units("How many people lived in Iceland in 2015?", catalogue) == []


@pytest.mark.parametrize("lang", ["en", "is"])
def test_the_one_row_in_the_asked_unit_is_stated(catalogue, lang):
    capacity = _cell(catalogue, "IDN02101", lang, 2015, {"Eining": "Q", "Orka": "1", "Tegund": "3"})
    question = {
        "en": "How much electricity did geothermal power plants generate in Iceland in 2015, in GWh?",
        "is": "Hve mikil var orkuvinnsla jarðvarmavirkjana á Íslandi árið 2015, í GWh?",
    }[lang]
    decision = unit_decide(question, capacity, catalogue)
    assert (decision.action, decision.variable, decision.code) == ("switch", "Orka", "2")


def test_the_stated_unit_is_kept(catalogue):
    capacity = _cell(catalogue, "IDN02101", "en", 2015, {"Eining": "Q", "Orka": "1", "Tegund": "3"})
    question = "What was the installed capacity of geothermal power plants in Iceland at the end of 2015, in MW?"
    assert unit_decide(question, capacity, catalogue).action == "keep"


def test_a_table_without_the_unit_is_refused(catalogue):
    decision = unit_decide("How much did the population of Iceland produce in 2015, in GWh?", _cell(catalogue, "MAN00101", "en", 2015), catalogue)
    assert decision.action == "refuse" and "gwh" in decision.detail


@pytest.mark.parametrize(
    "question, lang",
    [
        ("How many dairy cows were there in Iceland in 2022?", "en"),
        ("Hversu margar mjólkurkýr voru á Íslandi árið 2022?", "is"),
    ],
)
def test_a_table_about_something_else_is_refused(catalogue, question, lang):
    why = subject_missing(question, _cell(catalogue, "MAN00101", lang, 2022), catalogue)
    assert why and why.startswith("subject: MAN00101")


@pytest.mark.parametrize(
    "question, lang",
    [
        ("How many people lived in Iceland on 1 January 2022?", "en"),
        ("Hve margir bjuggu á Íslandi 1. janúar 2022?", "is"),
    ],
)
def test_the_population_table_carries_a_population_question(catalogue, question, lang):
    assert subject_missing(question, _cell(catalogue, "MAN00101", lang, 2022), catalogue) is None


def test_a_word_the_catalogue_never_writes_says_nothing(catalogue):
    assert subject_missing("How many zxqwv were there in Iceland in 2022?", _cell(catalogue, "MAN00101", "en", 2022), catalogue) is None


def test_off_without_the_flag(catalogue, monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "0")
    result = _cell(catalogue, "MAN00101", "en", 2022)
    assert subject_missing("How many dairy cows were there in Iceland in 2022?", result, catalogue) is None
    assert unit_decide("How much did Iceland produce in 2015, in GWh?", result, catalogue).action == "keep"


def test_u_umlaut_is_one_word():
    assert row_guard._unumlaut("löndum") == "landum"
    assert row_guard._same("land", "löndum")
    assert row_guard._unumlaut("land") == "land"


def test_the_named_row_of_the_measure_codelist_is_stated(catalogue):
    wage = _cell(catalogue, "LAU04001", "en", "2021M03", {"Vísitala": "LVT", "Eining": "index"})
    decision = carried_decide("What was the basic wage index in March 2021?", wage, catalogue)
    assert (decision.action, decision.variable, decision.code) == ("switch", "Vísitala", "VTG")
    assert carried_decide("What was the wage index in March 2021?", wage, catalogue).action == "keep"
    # Another wording may refuse, but never keeps the general wage index row.
    assert carried_decide("How high was the basic wage index in March 2021?", wage, catalogue).action != "keep"
