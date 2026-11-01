"""GRUND_UNEMP_GUARD is refuse-only and off unless set."""

from __future__ import annotations

import os

os.environ.pop("GRUND_UNEMP_GUARD", None)

from grund.unemp_guard import reason  # noqa: E402


def _cell(table: str, labels: dict, value: str = "1") -> dict:
    return {
        "refused": False,
        "value": value,
        "table_id": table if table.endswith(".px") else table + ".px",
        "claims": [{"cells": [{"table_id": table, "labels": labels}]}],
    }


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_UNEMP_GUARD", raising=False)
    stated = _cell(
        "VIN00910",
        {"Age": "16-74", "Unit": "Unemployment rate, % (of labour force)"},
        "3.5",
    )
    assert reason("Unemployed persons, ages 16 to 74, headcount", stated) is None


def test_count_marker_on_a_rate_unit(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    stated = _cell(
        "VIN00910",
        {"Quarter": "2025Q2", "Age": "16-74", "Unit": "Unemployment rate, % (of labour force)"},
        "3.5",
    )
    assert reason("Unemployed persons, ages 16 to 74, second quarter 2025, headcount", stated) == "count marker on a rate unit"
    assert reason("How many unemployed persons, second quarter 2025", stated) == "count marker on a rate unit"
    assert reason("Fjöldi atvinnulausra, annar ársfjórðungur 2025", stated) == "count marker on a rate unit"


def test_rate_marker_on_a_count_unit(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    stated = _cell(
        "VIN00921",
        {
            "Ársfjórðungur": "2025Á1",
            "Aldur": "16-74 ára",
            "Eining": "Atvinnulausir (Áætlaður fjöldi)",
        },
        "11400",
    )
    question = "Hvert var hlutfall atvinnulausra á fyrsta ársfjórðungi 2025?"
    assert reason(question, stated) == "rate marker on a count unit"
    rate = _cell(
        "VIN00921",
        {"Aldur": "16-74 ára", "Eining": "Atvinnuleysi, % (Hlutfall af vinnuafli)"},
        "4.9",
    )
    assert reason(question, rate) is None


def test_both_directions_leave_a_matching_unit(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    count = _cell(
        "VIN00931",
        {"Age": "16-74", "Unit": "Unemployed (Estimated number)"},
        "8400",
    )
    assert reason("Number of unemployed persons aged 16 to 74", count) is None
    rate = _cell(
        "VIN00931",
        {"Age": "25-54", "Unit": "Employment rate, % (of population)"},
        "80.1",
    )
    assert reason("Employment rate, ages 25 to 54", rate) is None


def test_named_age_against_16_74_and_total(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    wide = _cell(
        "VIN00920",
        {"Age": "16-74", "Unit": "Unemployed (Estimated number)"},
        "15400",
    )
    assert reason("Atvinnulausir 25-54 ára, fjöldi", wide) == "named age is not 16-74"
    total = _cell("VIN00002", {"Sex/age": "Total", "Unit": "Unemployed"}, "9000")
    assert reason("Unemployed persons aged 16 to 24, headcount", total) == "named age is not 16-74"
    matched = _cell(
        "VIN00920",
        {"Aldur": "25-54 ára", "Eining": "Atvinnulausir (Áætlaður fjöldi)"},
        "7400",
    )
    assert reason("Atvinnulausir 25–54 ára, fjöldi", matched) is None
    same_span = _cell("VIN00911", {"Age": "16 to 74 years", "Unit": "Unemployment rate"}, "4.9")
    assert reason("Unemployment rate, ages 16 to 74", same_span) is None


def test_other_vin_table_and_not_a_population_table(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    vin = _cell("VIN10001", {"Age": "16-74 years", "Unit": "Activity rate, % (of population)"}, "70")
    assert reason("Activity rate of persons aged 55 to 74", vin) == "named age is not 16-74"
    population = _cell("MAN00101", {"Aldur": "Alls", "Kyn": "Alls"}, "389444")
    assert reason("Mannfjöldi 25-54 ára", population) is None


def test_rate_dimension_is_the_unit_on_other_vin_tables(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    stated = _cell(
        "VIN00911",
        {"Year": "2024", "Age": "16-74", "Rate, %": "Unemployment rate, % (of labour force)"},
        "4.9",
    )
    assert reason("Number of unemployed persons in 2024", stated) == "count marker on a rate unit"
    assert reason("Unemployment rate in 2024, ages 16 to 74", stated) is None


def test_percentage_distribution_is_not_the_rate_marker(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    stated = _cell("VIN01104", {"Ár": "2025", "Eining": "Starfandi í fullustarfi"}, "75.7")
    question = (
        "Hver var vinnumarkaðurinn eftir kyni, aldri, búsetu og menntun, "
        "hlutfallsleg skipting, Starfandi í fullustarfi árið 2025?"
    )
    assert reason(question, stated) is None


def test_how_many_percent_is_not_a_headcount(monkeypatch):
    monkeypatch.setenv("GRUND_UNEMP_GUARD", "1")
    stated = _cell("VIN00911", {"Age": "16-74", "Unit": "Annual change, %"}, "0.4")
    assert reason("Um hve mörg prósent hækkaði atvinnuleysi", stated) is None
    assert reason("How many percent did the unemployment rate rise", stated) is None
