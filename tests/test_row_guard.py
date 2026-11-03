"""The stated row against the question, from the codelists alone."""

from __future__ import annotations

from grund.row_guard import label_decide, row_reason
from grund_index.model import Edition, Table, Variable


class _Catalogue:
    def __init__(self, tables):
        self.tables = tables
        self.by_id = {table.id: table for table in tables}


def _edition(lang, title, variables, path=("Efnahagur", "visitolur", "vnv", "leaf")):
    return Edition(lang, title, "db", list(path), [], "", None, variables)


def _year(*years):
    return Variable("Ár", "Year", True, False, [(str(year), str(year)) for year in years])


def _result(table_id, lang, labels):
    return {
        "table_id": table_id + ".px",
        "value": "1",
        "language": lang,
        "source": {
            "language": lang,
            "cells": [{"labels": [{"variable": code, "code": value, "label": text} for code, value, text in labels]}],
        },
    }


def _spending():
    variable = Variable("Skipting", "Category", False, False, [
        ("0", "Total"), ("1", "01 Food, beverages and tobacco"), ("2", "01.1 Food"), ("3", "01.4 Tobacco"),
    ])
    edition = _edition("en", "Household final consumption expenditure at constant prices", [variable, _year(1985)])
    return _Catalogue([Table("THJ0", {"en": edition})])


def test_total_row_is_refused_when_one_other_row_is_named(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    catalogue = _spending()
    stated = _result("THJ0", "en", [("Skipting", "0", "Total"), ("Ár", "1985", "1985")])
    assert row_reason("What was household spending on food at constant prices in 1985?", stated, catalogue)
    assert row_reason("What was household final consumption expenditure in 1985?", stated, catalogue) is None


def test_named_row_is_kept(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    stated = _result("THJ0", "en", [("Skipting", "2", "01.1 Food"), ("Ár", "1985", "1985")])
    assert row_reason("What was spending on food in 1985?", stated, _spending()) is None


def test_unnamed_subgroup_is_refused_when_the_codelist_has_a_total(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    stated = _result("THJ0", "en", [("Skipting", "3", "01.4 Tobacco"), ("Ár", "1985", "1985")])
    assert row_reason("What was household final consumption expenditure in 1985?", stated, _spending())


def test_ranked_class_is_named_by_lowest(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    quartile = Variable("Q", "Quartile of income", False, False, [
        ("0", "1. quartile"), ("1", "2. quartile"), ("2", "3. quartile"), ("3", "4. quartile"), ("4", "Total"),
    ])
    edition = _edition("en", "Average household expenditure by income", [quartile, _year(2016)])
    catalogue = _Catalogue([Table("VIS0", {"en": edition})])
    total = _result("VIS0", "en", [("Q", "4", "Total"), ("Ár", "2016", "2016")])
    assert row_reason("What was household expenditure in the lowest income quartile in 2016?", total, catalogue)
    assert row_reason("What was household expenditure in 2016?", total, catalogue) is None


def test_a_list_of_totals_has_no_single_total(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    unit = Variable("Unit", "Unit", False, False, [("1", "Total persons"), ("2", "Total men")])
    edition = _edition("en", "Moves by type", [unit, _year(2000)])
    catalogue = _Catalogue([Table("MAN0", {"en": edition})])
    stated = _result("MAN0", "en", [("Unit", "2", "Total persons"), ("Ár", "2000", "2000")])
    assert row_reason("How many moves were there in 2000?", stated, catalogue) is None


def _cpi_family():
    item = Variable("Item", "Item", False, False, [("index", "Index")])
    headline = _edition("en", "Consumer price index and changes", [_year(2026), item])
    groups = Variable("Category", "Category", False, False, [("CPI", "Consumer Price Index"), ("1a", "1a Durable products")])
    sub = _edition("en", "CPI by expenditure groups", [_year(2026), item, groups])
    other = _edition("en", "Wage index", [_year(2026), item], path=("Samfelag", "laun", "x", "leaf"))
    return _Catalogue([Table("VIS1", {"en": headline}), Table("VIS2", {"en": sub}), Table("LAU1", {"en": other})])


def test_headline_is_left_for_the_sibling_whose_row_names_the_subindex(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    catalogue = _cpi_family()
    stated = _result("VIS1", "en", [("Ár", "2026", "2026"), ("Item", "index", "Index")])
    question = "What was the consumer price index for durable products in 2026?"
    decision = label_decide(question, stated, catalogue, ["consumer", "price", "index", "durable", "product"], {2026}, lambda stem, years: True)
    assert decision.action == "switch" and decision.table == "VIS2"
    plain = label_decide("What was the consumer price index in 2026?", stated, catalogue, ["consumer", "price", "index"], {2026}, lambda stem, years: True)
    assert plain.action == "keep"


def test_subindex_is_refused_when_no_sibling_covers_the_year(monkeypatch):
    monkeypatch.setenv("GRUND_ROW_GUARD", "1")
    catalogue = _cpi_family()
    stated = _result("VIS1", "en", [("Ár", "2026", "2026"), ("Item", "index", "Index")])
    decision = label_decide(
        "What was the consumer price index for durable products in 2026?", stated, catalogue,
        ["consumer", "price", "index", "durable", "product"], {2026}, lambda stem, years: False,
    )
    assert decision.action == "refuse"


def test_guard_is_off_without_the_flag(monkeypatch):
    monkeypatch.delenv("GRUND_ROW_GUARD", raising=False)
    stated = _result("THJ0", "en", [("Skipting", "0", "Total"), ("Ár", "1985", "1985")])
    assert row_reason("What was spending on food in 1985?", stated, _spending()) is None


def test_roots_never_shorter_than_an_index_token():
    from grund.row_guard import _ENDINGS, _root
    from grund_index.textutil import MIN_TOKEN_LEN, tokens

    shortest = "x" * MIN_TOKEN_LEN
    assert tokens(shortest) == [shortest]
    assert tokens(shortest[:-1]) == []
    for ending in _ENDINGS:
        assert _root(shortest + ending) == shortest
        for stem in (shortest[:-1], shortest):
            root = _root(stem + ending)
            assert len(root) >= MIN_TOKEN_LEN or root == stem + ending
