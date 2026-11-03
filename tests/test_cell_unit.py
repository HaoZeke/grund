"""The unit of a stated cell comes from the table's own metadata, most specific first."""

from __future__ import annotations

from grund.cell_unit import cell_unit, title_measure
from grund_index.model import Edition, Variable


def _edition(title, variables):
    return Edition("en", title, "db", ["Ibuar"], [], "", None, variables)


_CITIZENSHIP = Variable("Ríkisfang", "Citizenship", False, False, [("01", "Total"), ("IN", "India")])
_SEX = Variable("Kyn", "Sex", False, False, [("0", "Total"), ("1", "Males")])
_YEAR = Variable("Ár", "Year", True, False, [("2025", "2025")])
_UNIT = Variable("Eining", "Unit", False, False, [("0", "Number"), ("1", "Percent")])


def _cells(*labels):
    return [{"labels": [{"variable": v, "variable_text": t, "code": c, "label": l} for v, t, c, l in labels]}]


def test_stated_unit_row_wins():
    edition = _edition("Population by citizenship and unit 2025", [_CITIZENSHIP, _UNIT, _YEAR])
    cells = _cells(("Ríkisfang", "Citizenship", "IN", "India"), ("Eining", "Unit", "1", "Percent"))
    assert cell_unit(edition, {"columns": [{"type": "c", "unit": "persons"}]}, cells) == {"unit": "Percent", "unit_from": "row"}


def test_published_contents_unit_is_next():
    edition = _edition("Population by citizenship 2025", [_CITIZENSHIP, _YEAR])
    payload = {"columns": [{"code": "x", "type": "c", "unit": "persons"}]}
    assert cell_unit(edition, payload, _cells(("Ríkisfang", "Citizenship", "IN", "India"))) == {"unit": "persons", "unit_from": "published"}


def test_title_measure_when_nothing_is_published():
    edition = _edition("Population by country of citizenship, sex and age 1 January 1998-2026", [_CITIZENSHIP, _SEX, _YEAR])
    assert title_measure(edition) == "Population"
    assert cell_unit(edition, {}, _cells(("Ríkisfang", "Citizenship", "IN", "India"))) == {"unit": "Population", "unit_from": "title"}


def test_total_unit_row_is_not_a_unit():
    edition = _edition("Live births by unit 2025", [Variable("Eining", "Unit", False, False, [("0", "Total")]), _YEAR])
    assert cell_unit(edition, {}, _cells(("Eining", "Unit", "0", "Total")))["unit_from"] == "title"
