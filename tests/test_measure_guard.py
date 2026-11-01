"""The measure guard is off unless GRUND_MEASURE_GUARD is set."""

from __future__ import annotations

import os

import pytest

os.environ.pop("GRUND_MEASURE_GUARD", None)

from grund.measure_guard import (  # noqa: E402
    basic_wage,
    blocks,
    monthly_goods,
    national_sex,
    population_measure_miss,
    value_code,
)
from grund.isquarter import quarter_kind  # noqa: E402


class _Var:
    def __init__(self, code, text, values):
        self.code = code
        self.text = text
        self.values = values


def test_guard_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_MEASURE_GUARD", raising=False)
    monkeypatch.setenv("GRUND_IS_KANG_QUARTER", "1")
    assert population_measure_miss("How many deaths were registered in Iceland in 2022?") is False
    assert basic_wage("What was the basic wage index in February 2025?") is False
    assert monthly_goods("Hver var vöruútflutningur í október 2024?") is False
    assert quarter_kind("Hvert var hlutfall atvinnulausra á fyrsta ársfjórðungi 2025?", "is") == "count"


def test_guard_separates_the_measure(monkeypatch):
    monkeypatch.setenv("GRUND_MEASURE_GUARD", "1")
    monkeypatch.setenv("GRUND_IS_KANG_QUARTER", "1")
    assert not population_measure_miss("How many deaths were registered in Iceland in 2022?")
    assert population_measure_miss("Hve margir létust á Íslandi árið 2023?")
    assert population_measure_miss("How many foreign citizens were counted in Iceland in 2022?")
    assert quarter_kind("Hvert var hlutfall atvinnulausra á fyrsta ársfjórðungi 2025?", "is") == "rate"
    from grund.isguard import blocks_population, guard_reason

    monkeypatch.setenv("GRUND_IS_KANG_GUARD", "1")
    assert blocks_population("How many deaths were registered in Iceland in 2022?")
    assert guard_reason(
        "How many deaths were registered in Iceland in 2022?",
        {"table_id": "MAN00101", "value": "364917"},
    )
    assert not blocks(
        "How many deaths were registered in Iceland in 2022?",
        {"table_id": "MAN00101", "value": "364917", "source": {"title": "Population by sex and age"}},
    )
    assert blocks(
        "Hve margir létust á Íslandi árið 2023?",
        {"table_id": "MAN00101", "value": "375218", "source": {"title": "Mannfjöldi eftir kyni og aldri"}},
    )
    assert blocks(
        "Hvert var hlutfall atvinnulausra á fyrsta ársfjórðungi 2025?",
        {
            "table_id": "VIN00920",
            "value": "11400",
            "source": {"cells": [{"labels": {"Eining": "Atvinnulausir (Áætlaður fjöldi)"}}]},
        },
    )
    assert blocks(
        "What was the value of goods exports in August 2024?",
        {"table_id": "UTA06001", "value": "69088"},
    )
    assert national_sex("Hve margir karlar bjuggu á Íslandi í ársbyrjun 2024?")
    assert not national_sex("Hversu miklu munaði á fjölda karla og kvenna á Íslandi árið 2018?")
    assert not national_sex("Hvert var atvinnuleysi kvenna á Íslandi árið 2018?")
    assert blocks(
        "Hve margir karlar bjuggu á Íslandi í ársbyrjun 2024?",
        {"table_id": "MAN02007", "value": "196552"},
    )
    euro = value_code(
        _Var("Gjaldmiðill", "Gjaldmiðill", [("0", "Bandaríkjadalur"), ("2", "Evra")]),
        "Hvert var meðalsölugengi evru árið 2015?",
        "is",
        "Meðalsölugengi",
    )
    assert euro == "2"
