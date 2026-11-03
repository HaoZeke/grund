"""A named country routes to its codelist row, from the catalogue alone."""

from __future__ import annotations

from pathlib import Path

import pytest

from grund import country_row
from grund.bind import is_total
from grund_index.catalogue import Catalogue

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.load(ROOT / "data" / "index")


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")


def _total_cell(catalogue, table_id, lang, year):
    edition = catalogue.by_id[table_id + ".px"].editions[lang]
    labels = []
    for variable in edition.variables:
        if variable.time:
            labels.append({"variable": variable.code, "code": str(year), "label": str(year)})
            continue
        code, label = next((c, l) for c, l in variable.values if is_total(l or c))
        labels.append({"variable": variable.code, "code": code, "label": label})
    return {"table_id": table_id + ".px", "value": "389444", "language": lang, "source": {"language": lang, "cells": [{"labels": labels}]}}


def _decide(catalogue, question, lang="en", covers=lambda table, years: True):
    return country_row.country_decide(question, _total_cell(catalogue, "MAN00101", lang, 2025), catalogue, {2025}, covers)


@pytest.mark.parametrize(
    "question, lang, table, variable, code",
    [
        ("How many indians are in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "IN"),
        ("How many Polish people live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "PL"),
        ("How many Filipinos live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "PH"),
        ("How many people living in Iceland were born in India in 2025", "en", "MAN12103", "Fæðingarland", "99IN"),
        ("Hversu margir indverskir ríkisborgarar búa á Íslandi árið 2025", "is", "MAN04103", "Ríkisfang", "IN"),
        ("Hversu margir Pólverjar bjuggu á Íslandi árið 2025", "is", "MAN04103", "Ríkisfang", "PL"),
        ("How many Indian citizens live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "IN"),
        ("How many Danes live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "DK"),
        ("How many Poles live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "PL"),
        ("How many Danish citizens live in Iceland in 2025", "en", "MAN04103", "Ríkisfang", "DK"),
        ("How many people living in Iceland were born in Poland in 2025", "en", "MAN12103", "Fæðingarland", "99PL"),
    ],
)
def test_population_total_switches_to_the_country_row(catalogue, question, lang, table, variable, code):
    decision = _decide(catalogue, question, lang)
    assert (decision.action, decision.table, decision.variable, decision.code) == ("switch", table, variable, code)


def test_question_without_a_country_keeps_the_total(catalogue):
    assert _decide(catalogue, "How many people lived in Iceland in 2025").action == "keep"
    assert _decide(catalogue, "Hver var mannfjöldi á Íslandi árið 2025", "is").action == "keep"


def test_two_countries_are_refused(catalogue):
    assert _decide(catalogue, "How many Indians and Filipinos lived in Iceland in 2025").action == "refuse"


def test_no_covering_table_is_refused_not_answered_with_the_total(catalogue):
    decision = _decide(catalogue, "How many indians are in Iceland in 2025", covers=lambda table, years: False)
    assert decision.action == "refuse" and "no table" in decision.detail


def test_a_census_snapshot_covers_only_the_year_its_title_writes(catalogue):
    from grund.sibling_measure import covers

    result = _total_cell(catalogue, "MAN00101", "en", 1990)
    decision = country_row.country_decide(
        "How many Indians lived in Iceland in 1990", result, catalogue, {1990}, lambda stem, years: covers(catalogue, stem, years)
    )
    assert decision.action == "refuse" and decision.detail.endswith("in 1990")


def test_tool_path_claims_are_read_as_the_stated_cell(catalogue):
    result = {
        "table_id": "MAN00101.px",
        "value": "389444",
        "language": "is",
        "source": {},
        "claims": [{"cells": [{"coords": {"Kyn": "Total", "Aldur": "-1", "Ár": "2025"}, "labels": {"Kyn": "Alls", "Aldur": "Alls"}}]}],
    }
    decision = country_row.country_decide("Hversu margir Pólverjar bjuggu á Íslandi árið 2025", result, catalogue, {2025}, lambda t, y: True)
    assert (decision.action, decision.table, decision.code) == ("switch", "MAN04103", "PL")


@pytest.mark.parametrize("word", ["nights", "children", "together", "percent", "guesthouse", "came", "polishing"])
def test_catalogue_words_are_not_countries(catalogue, word):
    lists = country_row._lists(catalogue)
    assert country_row.mentions(f"How many {word} were there in 2025", lists, []) == []


def test_stated_country_row_is_kept(catalogue):
    result = _total_cell(catalogue, "MAN04103", "en", 2025)
    for item in result["source"]["cells"][0]["labels"]:
        if item["variable"] == "Ríkisfang":
            item.update(code="IN", label="India")
    decision = country_row.country_decide("How many indians are in Iceland in 2025", result, catalogue, {2025}, lambda t, y: True)
    assert decision.action == "stated" and decision.code == "IN"


def test_derived_words_come_from_a_codelist_whose_codes_extend_country_codes(catalogue):
    lists = country_row._lists(catalogue)
    assert "denmark" in lists.derived["danish"] and "poland" in lists.derived["polish"]
    rows = lists.lists[("MAN04103.px", "Ríkisfang")]
    for currency_name in ("krone", "real", "baht"):
        assert country_row.match_country(currency_name, rows, lists) is None


def test_a_title_listing_places_beside_iceland_does_not_hide_a_country(catalogue):
    rows = country_row._lists(catalogue).lists[("MAN04103.px", "Ríkisfang")]
    assert any(row.code == "DK" for row in rows)


@pytest.mark.parametrize("word", ["dance", "Danir", "sales", "data"])
def test_words_that_only_share_letters_with_a_derived_word_are_not_countries(catalogue, word):
    lists = country_row._lists(catalogue)
    assert country_row.match_country(word, lists.lists[("MAN04103.px", "Ríkisfang")], lists) is None
