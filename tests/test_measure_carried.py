"""The stated cell carries the question's measure, from the catalogue alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from grund.bind import is_total
from grund.measure_carried import uncarried
from grund_index.catalogue import Catalogue

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.load(ROOT / "data" / "index")


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")


def _cell(catalogue, table_id, lang, year, rows=None):
    edition = catalogue.by_id[table_id + ".px"].editions[lang]
    labels = []
    for variable in edition.variables:
        if variable.time:
            labels.append({"variable": variable.code, "code": str(year), "label": str(year)})
            continue
        wanted = (rows or {}).get(variable.code)
        if wanted:
            code, label = next((c, l) for c, l in variable.values if str(c) == wanted)
        else:
            code, label = next(((c, l) for c, l in variable.values if is_total(l or c)), variable.values[0])
        labels.append({"variable": variable.code, "code": str(code), "label": str(label)})
    return {"table_id": table_id + ".px", "value": "1", "language": lang, "source": {"language": lang, "cells": [{"labels": labels}]}}


def test_a_total_of_one_measure_is_not_a_count_of_another(catalogue):
    result = _cell(catalogue, "MAN00101", "en", 2000)
    assert "MAN01302" in uncarried("How many moves of residence were registered in Iceland in 2000?", result, catalogue)


def test_a_word_another_row_of_the_codelist_writes(catalogue):
    result = _cell(catalogue, "IDN02101", "en", 2019, {"Orka": "1", "Tegund": "1", "Eining": "Q"})
    why = uncarried("How many GWh did public power plants produce in 2019?", result, catalogue)
    assert why and "gwh" in why.lower()
    named = _cell(catalogue, "IDN02101", "en", 2019, {"Orka": "2", "Tegund": "1", "Eining": "Q"})
    assert uncarried("How many GWh did public power plants produce in 2019?", named, catalogue) is None


@pytest.mark.parametrize(
    "question, lang",
    [
        ("How many people lived in Iceland on 1 January 2026?", "en"),
        ("Hve margir bjuggu á Íslandi 1. janúar 2026?", "is"),
        ("How many people lived in Iceland on 1 January 2026, and what was the consumer price index in September 2026?", "en"),
    ],
)
def test_the_population_total_carries_a_population_question(catalogue, question, lang):
    assert uncarried(question, _cell(catalogue, "MAN00101", lang, 2026), catalogue) is None


def test_off_without_the_flag(catalogue, monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "0")
    result = _cell(catalogue, "MAN00101", "en", 2000)
    assert uncarried("How many moves of residence were registered in Iceland in 2000?", result, catalogue) is None
