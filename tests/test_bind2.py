"""Classifier, period sets, totals, and measure conflicts for GRUND_BIND2."""

from datetime import date

import pytest

from grund.answer import render
from grund.bind import Binding
from grund.bind2 import (
    AskedMeasure,
    apply_binding,
    classify_question,
    classify_value,
    classify_variable,
    explicit_codes,
    frequency,
    guard_url,
    narrow_latest,
    parse_period_query,
    pxjson_from_jsonstat,
    response_format,
    selections_for,
)
from grund.compute import extract_rows
from grund.parse import parse_question
from grund.validator import query_body
from grund_index.model import Edition, Variable


TODAY = date(2026, 10, 31)


def _edition(variables, title="People"):
    return Edition(
        lang="en",
        title=title,
        db="Ibuar",
        path=["Ibuar"],
        path_texts=["Population"],
        url="https://px.hagstofa.is/pxen/api/v1/en/Ibuar/MAN00101.px",
        updated=None,
        variables=variables,
    )


def _binding(edition, selections, operation="level", time_var="Year", time_codes=None, notes=None):
    return Binding(
        edition=edition,
        selections=selections,
        operation=operation,
        score=1,
        time_var=time_var,
        time_codes=list(time_codes or []),
        notes=list(notes or []),
    )


def _years():
    return Variable(
        "Year",
        "Year",
        True,
        False,
        [(str(year), str(year)) for year in range(2018, 2027)],
    )


def test_totals_aggregates_and_of_which():
    total = classify_value("0", "Total", geography="")
    assert total.is_total and total.is_aggregate and not total.of_which
    alls = classify_value("Alls", "Alls")
    assert alls.is_total
    aggregate = classify_value("1", "Salmon caught, total")
    assert aggregate.is_aggregate and not aggregate.is_total
    part = classify_value("2", "of which: immigrants")
    assert part.of_which and not part.is_total and not part.is_aggregate
    icelandic = classify_value("3", "Þar af karlar")
    assert icelandic.of_which and not icelandic.is_total


def test_measure_kinds_in_both_languages():
    assert classify_value("1", "Number").measure_kind == "count"
    assert classify_value("1", "Fjöldi").measure_kind == "count"
    assert classify_value("2", "Percent").measure_kind == "percent"
    assert classify_value("2", "Hlutfall").measure_kind == "percent"
    assert classify_value("2", "Hlutfall").unit == "percent"
    assert classify_value("3", "Index").measure_kind == "index"
    assert classify_value("3", "Vísitala").measure_kind == "index"
    assert classify_value("4", "Per 1,000 inhabitants").measure_kind == "rate"
    assert classify_value("4", "Per 1,000 inhabitants").denominator == "per 1,000"
    rate = classify_value("5", "Fjöldi á hverja 1.000 íbúa")
    assert rate.measure_kind == "rate"
    assert classify_value("6", "Annual change").measure_kind == "change"
    assert classify_value("6", "Breyting frá fyrra ári").measure_kind == "change"
    stock = classify_value("7", "Population 1 January")
    assert stock.measure_kind == "stock"
    assert stock.stock_flow == "stock"
    assert stock.stat_type == "measuredValue"
    assert stock.population == "persons"
    assert classify_value("8", "Arrivals").measure_kind == "flow"
    assert classify_value("8", "Aðfluttir").stock_flow == "flow"
    immigrants = classify_value("9", "Innflytjendur")
    assert immigrants.measure_kind == "stock"
    assert immigrants.population == "immigrants"
    assert classify_value("10", "Krónur").unit == "isk"


def test_question_uses_the_same_fields():
    asked = classify_question("How many immigrants live in Iceland?", "level")
    assert isinstance(asked, AskedMeasure)
    assert asked.population == "immigrants"
    assert asked.stock_flow == "stock"
    assert asked.kind == "stock"
    assert asked.stat_type == "measuredValue"
    flow = classify_question("How many immigrant arrivals were there in 2024?", "level")
    assert flow.stock_flow == "flow"
    assert flow.kind == "flow"


def test_geography_level_and_period_grain():
    variable = classify_variable(
        Variable(
            "Sveitarfelag",
            "Sveitarfélag",
            False,
            False,
            [("0", "Alls"), ("1", "Reykjavík")],
        )
    )
    assert variable.role == "geography"
    assert variable.geography_level == "municipality"
    assert variable.values[0].geography == "country"
    assert variable.values[1].geography == "municipality"
    assert frequency(["2020", "2021", "2022"]) == "year"
    assert frequency(["2024M01", "2024M02", "2024M03"]) == "month"
    assert frequency(["2024Q1", "2024Q2"]) == "quarter"
    assert frequency(["2024K1", "2024K2", "2024K3"]) == "quarter"
    assert classify_value("2024M09", "2024M09").period_grain == "month"


def test_period_phrases_become_explicit_codes():
    codes = [str(year) for year in range(2010, 2027)]
    assert explicit_codes(parse_period_query("What was the population in 2024?", today=TODAY), codes) == ["2024"]
    assert explicit_codes(parse_period_query("árið 2024", today=TODAY), codes) == ["2024"]
    assert explicit_codes(parse_period_query("last year", today=TODAY), codes) == ["2025"]
    assert explicit_codes(parse_period_query("á síðasta ári", today=TODAY), codes) == ["2025"]
    assert explicit_codes(parse_period_query("í fyrra", today=TODAY), codes) == ["2025"]
    assert explicit_codes(parse_period_query("from 2015 to 2025", today=TODAY), codes) == [
        str(year) for year in range(2015, 2026)
    ]
    assert explicit_codes(parse_period_query("frá 2015 til 2025", today=TODAY), codes) == [
        str(year) for year in range(2015, 2026)
    ]
    quarters = [f"2024Q{number}" for number in range(1, 5)] + [f"2025Q{number}" for number in range(1, 5)]
    assert explicit_codes(parse_period_query("in the third quarter of 2024", today=TODAY), quarters) == ["2024Q3"]
    assert explicit_codes(parse_period_query("á þriðja ársfjórðungi 2024", today=TODAY), ["2024K1", "2024K2", "2024K3", "2024K4"]) == ["2024K3"]
    months = ["2026M08", "2026M09", "2026M10"]
    assert explicit_codes(parse_period_query("í september 2026", today=TODAY), months) == ["2026M09"]
    assert explicit_codes(parse_period_query("September 2026", today=TODAY), months) == ["2026M09"]
    assert explicit_codes(parse_period_query("in 1981", today=TODAY), ["A1980", "A1981", "A1990"]) == ["A1981"]


def test_unconstrained_dimension_uses_the_total(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Sex", "Sex", False, False, [("0", "Total"), ("1", "Males"), ("2", "Females")]),
    ])
    parsed = parse_question("How many people lived in Iceland in 2024?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2026"]}},
            {"code": "Sex", "selection": {"filter": "item", "values": ["1"]}},
        ],
        time_codes=["2026"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    by_code = {entry["code"]: entry["selection"] for entry in tied.selections}
    assert by_code["Sex"] == {"filter": "item", "values": ["0"]}
    assert by_code["Year"] == {"filter": "item", "values": ["2024"]}


def test_elimination_omits_the_total(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable(
            "Region",
            "Region",
            False,
            True,
            [("0", "Total"), ("1", "Reykjavík")],
        ),
    ])
    parsed = parse_question("How many people lived in Iceland in 2024 by region?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
            {"code": "Region", "selection": {"filter": "item", "values": ["1"]}},
        ],
        time_codes=["2024"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    assert [entry["code"] for entry in tied.selections] == ["Year"]
    assert any(note.startswith("bind2-omit:Region") for note in tied.notes)


def test_period_stays_when_the_codes_already_include_the_year(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Sex", "Sex", False, False, [("0", "Total"), ("1", "Males")]),
    ])
    parsed = parse_question("How many people lived in Iceland in 2024?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2023", "2024"]}},
            {"code": "Sex", "selection": {"filter": "item", "values": ["0"]}},
        ],
        time_codes=["2023", "2024"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    year = next(entry for entry in tied.selections if entry["code"] == "Year")
    assert year["selection"]["values"] == ["2023", "2024"]


def _stated(labels, operation="level", title="Population by sex", period="2024"):
    return {
        "value": 10,
        "operation": operation,
        "claims": [{
            "op": operation,
            "cells": [{
                "title": title,
                "period": period,
                "labels": labels,
            }],
        }],
    }


def test_veto_is_off_unless_the_flag_is_set(monkeypatch):
    from grund.bind2 import veto_reason

    monkeypatch.delenv("GRUND_BIND2_VETO", raising=False)
    result = _stated({"Sex": "Total"})
    assert veto_reason("How many women lived in Iceland in 2024?", result) is None


def test_veto_refuses_a_total_when_a_category_is_named(monkeypatch):
    from grund.bind2 import veto_reason

    monkeypatch.setenv("GRUND_BIND2_VETO", "1")
    women = _stated({"Sex": "Total"})
    assert veto_reason("How many women lived in Iceland in 2024?", women) == "bind2-veto:total_where_named"
    people = _stated({"Sex": "Total"})
    assert veto_reason("How many people lived in Iceland in 2024?", people) is None


def test_veto_refuses_a_count_when_a_rate_was_asked(monkeypatch):
    from grund.bind2 import veto_reason

    monkeypatch.setenv("GRUND_BIND2_VETO", "1")
    count = _stated({"Unit": "Number of persons"}, operation="level", title="Labour force")
    assert veto_reason("What was the unemployment rate in 2024?", count) == "bind2-veto:count_where_rate"
    change = _stated({"Unit": "Number"}, operation="yoy_pct", title="Population")
    assert veto_reason("By what percentage did the population rise from 2023 to 2024?", change) is None


def test_veto_refuses_stock_against_flow_and_a_level_against_a_change(monkeypatch):
    from grund.bind2 import veto_reason

    monkeypatch.setenv("GRUND_BIND2_VETO", "1")
    arrivals = _stated({"Measure": "Arrivals"}, title="Migration")
    assert veto_reason("How many immigrants live in Iceland in 2024?", arrivals) == "bind2-veto:stock_against_flow"
    level = _stated({"Unit": "Number of borrowers"}, operation="level", title="Library borrowers", period="2024Q3")
    assert veto_reason(
        "By what percentage did the number of borrowers fall from the third quarter of 2024 to the third quarter of 2025?",
        level,
    ) == "bind2-veto:level_against_change"


def test_veto_refuses_the_wrong_grain_and_constant_prices(monkeypatch):
    from grund.bind2 import veto_reason

    monkeypatch.setenv("GRUND_BIND2_VETO", "1")
    year = _stated({"Month": "Total"}, title="Borrowers", period="2024")
    assert veto_reason("What was the number of borrowers in the third quarter of 2024?", year) == "bind2-veto:period_grain"
    quarter = _stated({"Sex": "Total"}, title="Borrowers", period="2024Q3")
    assert veto_reason("What was the number of borrowers in the third quarter of 2024?", quarter) is None
    prices = _stated({"Item": "Total"}, title="Consumption at constant prices", period="2024")
    assert veto_reason("What was nominal consumption in 2024?", prices) == "bind2-veto:constant_where_nominal"


def test_a_replaced_cell_does_not_count_as_path_agreement(monkeypatch):
    from grund.calibrate import agreement_score

    chosen = {"table_id": "MAN00101.px", "value": 10.0, "source": {"notes": ["bind2-total:Kyn"]}}
    other = {"table_id": "MAN00101.px", "value": 10.0}
    plain = {"table_id": "MAN00101.px", "value": 10.0, "source": {"notes": ["bind2"]}}
    monkeypatch.delenv("GRUND_BIND2", raising=False)
    untouched = agreement_score(chosen, [other], None)
    monkeypatch.setenv("GRUND_BIND2", "1")
    assert agreement_score(plain, [other], None) == untouched
    assert agreement_score(chosen, [other], None) < untouched


def test_one_retie_is_reused_for_the_same_table(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    from grund.bind2 import remember_query, shared_binding

    edition = _edition([_years()])
    built = _binding(
        edition,
        [{"code": "Year", "selection": {"filter": "item", "values": ["2024"]}}],
        time_codes=["2024"],
    )
    remember_query("How many people lived in Iceland in 2024?", "MAN00101.px", built)
    again = shared_binding("How many people lived in Iceland in 2024?", edition, "MAN00101")
    assert again is not None
    assert again.selections == built.selections
    assert shared_binding("How many people lived in Iceland in 2024?", edition, "OTHER") is None


def test_latest_uses_top_and_skips_an_empty_cell(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Sex", "Sex", False, False, [("0", "Total"), ("1", "Males")]),
    ])
    parsed = parse_question("How many people live in Iceland?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2026"]}},
            {"code": "Sex", "selection": {"filter": "item", "values": ["0"]}},
        ],
        time_codes=["2026"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    year = next(entry for entry in tied.selections if entry["code"] == "Year")
    assert year["selection"]["filter"] == "top"
    assert "bind2-latest" in tied.notes
    rows = [
        {"map": {"Year": "2025"}, "value": "10", "labels": []},
        {"map": {"Year": "2026"}, "value": "..", "labels": []},
    ]
    kept = narrow_latest(rows, tied)
    assert [row["map"]["Year"] for row in kept] == ["2025"]
    assert tied.time_codes == ["2025"]


def test_a_named_row_is_not_replaced_by_a_total(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable(
            "Line",
            "Line",
            False,
            False,
            [("1", "01-01-00 Rekstrartekjur samtals"), ("6", "01-02-04 Fyrningar")],
        ),
    ])
    parsed = parse_question("Hver var rekstrar og efnahagsyfirlit, 01-02-04 Fyrningar árið 2024?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
            {"code": "Line", "selection": {"filter": "item", "values": ["6"]}},
        ],
        time_codes=["2024"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    line = next(entry for entry in tied.selections if entry["code"] == "Line")
    assert line["selection"]["values"] == ["6"]


def test_named_median_stays_when_the_title_also_says_mean(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Unit", "Unit", False, False, [("0", "Mean age"), ("1", "Median age")]),
    ])
    parsed = parse_question("What was Mean-, median and modal age of parents, Median age in 2025?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2025"]}},
            {"code": "Unit", "selection": {"filter": "item", "values": ["1"]}},
        ],
        time_codes=["2025"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    unit = next(entry for entry in tied.selections if entry["code"] == "Unit")
    assert unit["selection"]["values"] == ["1"]


def test_stock_question_rejects_an_arrivals_measure(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Unit", "Unit", False, False, [("A", "Arrivals")]),
    ])
    parsed = parse_question("How many immigrants live in Iceland in 2024?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
            {"code": "Unit", "selection": {"filter": "item", "values": ["A"]}},
        ],
        time_codes=["2024"],
    )
    assert apply_binding(edition, parsed, built) is None


def test_stock_question_switches_to_the_immigrant_row(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([
        _years(),
        Variable("Unit", "Unit", False, False, [("A", "Arrivals"), ("I", "Immigrants")]),
    ])
    parsed = parse_question("How many immigrants live in Iceland in 2024?")
    built = _binding(
        edition,
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
            {"code": "Unit", "selection": {"filter": "item", "values": ["A"]}},
        ],
        time_codes=["2024"],
    )
    tied = apply_binding(edition, parsed, built)
    assert tied is not None
    unit = next(entry for entry in tied.selections if entry["code"] == "Unit")
    assert unit["selection"]["values"] == ["I"]


def test_flag_off_leaves_the_binding_and_the_format(monkeypatch):
    monkeypatch.delenv("GRUND_BIND2", raising=False)
    edition = _edition([_years()])
    parsed = parse_question("How many people lived in Iceland in 2024?")
    built = _binding(
        edition,
        [{"code": "Year", "selection": {"filter": "item", "values": ["2020"]}}],
        time_codes=["2020"],
    )
    assert apply_binding(edition, parsed, built) is built
    assert response_format() == "json"
    assert query_body(built.selections)["response"] == {"format": "json"}
    with pytest.raises(ValueError):
        guard_url("https://px.hagstofa.is/pxen/api/v2/tables")


def test_jsonstat_becomes_rows():
    payload = {
        "class": "dataset",
        "id": ["Sex", "Year"],
        "size": [1, 2],
        "value": [10, None],
        "role": {"time": ["Year"]},
        "dimension": {
            "Sex": {"label": "Sex", "category": {"index": {"0": 0}, "label": {"0": "Total"}}},
            "Year": {
                "label": "Year",
                "category": {
                    "index": {"2024": 0, "2025": 1},
                    "label": {"2024": "2024", "2025": "2025"},
                },
            },
        },
    }
    converted = pxjson_from_jsonstat(payload)
    assert converted["data"][0]["key"] == ["0", "2024"]
    assert converted["data"][0]["values"] == ["10"]
    assert converted["data"][1]["values"] == [".."]
    edition = _edition([
        Variable("Sex", "Sex", False, False, [("0", "Total")]),
        Variable("Year", "Year", True, False, [("2024", "2024"), ("2025", "2025")]),
    ])
    rows = extract_rows(payload, edition)
    assert rows[0]["map"] == {"Sex": "0", "Year": "2024"}
    assert rows[0]["value"] == "10"
    assert rows[1]["value"] == ".."


def test_derived_sentence_names_the_cells(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    edition = _edition([_years()])
    binding = _binding(
        edition,
        [{"code": "Year", "selection": {"filter": "item", "values": ["2023", "2024"]}}],
        operation="difference",
        time_codes=["2023", "2024"],
    )
    rows = [
        {"map": {"Year": "2023"}, "value": "4", "labels": []},
        {"map": {"Year": "2024"}, "value": "7", "labels": []},
    ]
    derived = {"name": "difference", "value": "3", "formula": "later - earlier", "inputs": ["4", "7"]}
    sentence = render("en", edition, binding, rows, "3", derived, False)
    assert "Calculated from cells 2023 and 2024 of table MAN00101." in sentence
    assert binding.derivation.op == "difference"
    assert binding.derivation.formula == "later - earlier"


def test_top_filter_is_the_tail_of_the_value_list():
    variables = [_years()]
    codes = [str(year) for year in range(2018, 2027)]
    query = selections_for({"Year": codes[-8:]}, variables, time_code="Year")
    assert query == [{"code": "Year", "selection": {"filter": "top", "values": ["8"]}}]
    middle = selections_for({"Year": ["2020", "2024"]}, variables, time_code="Year")
    assert middle[0]["selection"]["filter"] == "item"


def test_response_format_is_jsonstat_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv("GRUND_BIND2", "1")
    assert response_format() == "json-stat2"
    body = query_body([{"code": "Year", "selection": {"filter": "top", "values": ["1"]}}])
    assert body["response"] == {"format": "json-stat2"}


def _table_url(stem: str, lang: str) -> str:
    import gzip
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "index" / "tables.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            url = str(row.get("url") or "")
            if stem in url and f"/{lang}/" in url:
                return url
    raise AssertionError(stem)


def _echo(url: str, title: str, labels: list[tuple[str, str]], operation: str = "level"):
    return {
        "value": 1,
        "operation": operation,
        "source": {
            "title": title,
            "api_url": url,
            "operation": operation,
            "cells": [{
                "labels": [{"variable_text": key, "label": value} for key, value in labels],
            }],
        },
    }


def test_title_echo_refuses_a_share_and_an_of_which_total(monkeypatch):
    from grund.bind2 import echo_reason

    monkeypatch.setenv("GRUND_TITLE_ECHO", "1")
    monkeypatch.delenv("GRUND_BIND2_VETO", raising=False)
    pension = _echo(
        _table_url("FEL02000", "en"),
        "Percent of old age pension beneficiaries by type of payment, financers, residence, gender and age in December 2007-2022",
        [
            ("Type of payment", "Old age pension beneficiaries with residence in Iceland"),
            ("Payments from", "Total"),
            ("Year", "2022"),
        ],
        operation="share",
    )
    asked = "What was Percent of old age pension beneficiaries by type of payment, financers, residence, gender and age in December in 2022?"
    assert echo_reason(asked, pension) == "bind2-echo:share"
    waste = _echo(
        _table_url("UMH04102", "en"),
        "Total waste managed 1995-2013",
        [("Waste", "Total waste managed"), ("Year", "2013")],
    )
    assert echo_reason("What was Total waste managed in 2013?", waste) == "bind2-echo:of-which"
    vehicles = _echo(
        _table_url("UMH04112", "en"),
        "Waste processing of end of life vehicles 2008-2022",
        [("Waste", "Total waste"), ("Measure", "Total reuse and recovery (X2=A+D1+D2+F2) tonnes"), ("Year", "2022")],
        operation="difference",
    )
    assert echo_reason(
        "By how much did Waste processing of end of life vehicles, Tonnes fall from 2021 to 2022?",
        vehicles,
    ) == "bind2-echo:title-row"
    beds = _echo(
        _table_url("HEI04103", "en"),
        "Hospital beds 2007-2020",
        [("Type of beds", "Total hospital beds"), ("Unit", "Number"), ("Year", "2020")],
    )
    assert echo_reason("What was Hospital beds, Number in 2020?", beds) is None
    marriages = _echo(
        _table_url("MAN06100", "en"),
        "Marriages by type of marriage ceremony 1951-2020",
        [("Division", "Marriages Total"), ("Year", "2020")],
    )
    assert echo_reason("What was Marriages by type of marriage ceremony in 2020?", marriages) is None
    monkeypatch.setenv("GRUND_TITLE_ECHO", "0")
    assert echo_reason(asked, pension) is None
