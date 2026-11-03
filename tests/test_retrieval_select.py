"""Table choice from the shipped metadata index. No live calls."""

from __future__ import annotations

from grund.frame import frame_question, needs_clarification
from grund.isgdp import table_stem as gdp_table
from grund.isjobs import survey_unemployment
from grund.isorigin import age_total_code, migration_code
from grund.istrade import table_stem as trade_table


class _Var:
    def __init__(self, code, text, values):
        self.code = code
        self.text = text
        self.values = values


def test_constant_price_gdp_is_not_the_current_price_table(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_GDP", "1")
    assert gdp_table("GDP at constant prices for 2021?") == "THJ01103"
    assert gdp_table("Verg landsframleiðsla á föstu verðlagi árið 2021?") == "THJ01103"
    assert gdp_table("What was Iceland's gross domestic product in 2025?") == "THJ01102"


def test_constant_price_trade_uses_the_constant_price_accounts(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_TRADE", "1")
    assert trade_table("Constant-price exports of goods and services in 2020?") == "THJ01103"
    assert trade_table("Exports of goods and services in 2024?") == "THJ01102"


def test_a_named_labour_force_survey_year_is_annual(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_JOBS", "1")
    assert survey_unemployment("Labour-force-survey unemployment rate for 2021?", "en")
    assert survey_unemployment("Atvinnuleysi samkvæmt vinnumarkaðsrannsókninni árið 2021?", "is")
    assert not survey_unemployment(
        "What was the unemployment rate in Iceland in the second quarter of 2026?", "en"
    )


def test_migration_codes_follow_the_labels_when_the_numbers_differ(monkeypatch):
    monkeypatch.setenv("GRUND_IS_ORIGIN", "1")
    aged = _Var("Tegund flutnings", "Type of migration", [("0", "Net immigration"), ("1", "Immigration"), ("2", "Emigration")])
    icelandic = _Var("Tegund flutnings", "Tegund flutnings", [("0", "Aðfluttir umfram brottflutta"), ("1", "Aðfluttir"), ("2", "Brottfluttir")])
    assert migration_code(aged, "How many people immigrated to Iceland during 2021, all ages?") == "1"
    assert migration_code(icelandic, "Hversu margir fluttu til Íslands árið 2021, allir aldurshópar?") == "1"
    assert migration_code(icelandic, "Hversu margir fluttu frá Íslandi árið 2022?") == "2"
    assert migration_code(aged, "Net immigration to Iceland in 2022?") == "0"
    assert migration_code(aged, "How many people emigrated from Iceland during 2022?") == "2"
    classic = _Var("Tegund flutnings", "Type of migration", [("1", "Net immigration"), ("2", "Immigration"), ("3", "Emigration")])
    assert migration_code(classic, "How many people immigrated to Iceland in 2025?") == "2"
    age = _Var("Aldur", "Age", [("-1", "Total"), ("0", "Under 1 year")])
    assert age_total_code(age, "How many people immigrated to Iceland during 2021, all ages?") == "-1"


def test_hotels_are_not_all_accommodation(monkeypatch):
    from grund.isstays import hotel_kind, stays_kind

    monkeypatch.setenv("GRUND_IS_KANG_STAYS", "1")
    asked = "Overnight stays in hotels and guesthouses in Iceland during 2022?"
    assert hotel_kind(asked, "en") == "overnight"
    assert stays_kind(asked, "en") is None
    assert stays_kind("How many overnight stays were there in Iceland in 2025?", "en") == "total"


def test_a_named_price_basis_is_not_the_nominal_wage_index(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_WAGE", "1")
    from grund.iswage import _wage_stem
    from grund_rails.cell_claim import _measure_block

    constant = "What was the constant-price wage index in March 2020?"
    icelandic = "Hver var launavísitalan á föstu verðlagi í mars 2020?"
    nominal = "What was the wage index in August 2026?"
    level = "Wage index level in March 2019?"
    percent = "How much did the wage index rise, in percent, over the year to March 2019?"
    assert _wage_stem(constant) == "LAU04800"
    assert _wage_stem(icelandic) == "LAU04800"
    assert _wage_stem(nominal) == "LAU04000"
    assert _wage_stem("Hver var launavísitalan í ágúst 2026?") == "LAU04000"
    assert _wage_stem(level) == "LAU04001"
    assert _wage_stem(percent) == "LAU04001"
    nominal_cell = {"title": "Wage index from 1989", "labels": {"Unit": "Value of index"}, "value": "708.7", "period": "2020M03", "latest_period": "2020M03", "table_id": "LAU04000"}
    constant_cell = {"title": "Wage index at constant price, from 1989", "labels": {"Month": "2020M03"}, "value": "153", "period": "2020M03", "latest_period": "2020M03", "table_id": "LAU04800"}
    assert _measure_block(constant, {"op": "level"}, [nominal_cell]) == "unsupported_cell"
    assert _measure_block(constant, {"op": "level"}, [constant_cell]) is None
    assert _measure_block(nominal, {"op": "level"}, [constant_cell]) == "unsupported_cell"


def test_a_named_age_is_not_the_birth_total(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_BIRTHS", "1")
    from grund.isbirths import birth_value_code, parent_role, specific_age, wants_births

    asked = "Hve mörg börn fæddust árið 2021 mæðrum sem voru 30 ára?"
    assert specific_age(asked) == "30"
    assert parent_role(asked) == "mother"
    assert wants_births(asked, "is") is False
    assert wants_births("Hve mörg börn fæddust á Íslandi árið 2024?", "is") is True
    assert specific_age("What was the fertility rate of women aged 30 to 34 in 2022?") is None
    ages = _Var("Aldur", "Age", [("0", "Total"), ("16", "29 years"), ("17", "30 years"), ("18", "31 years")])
    assert birth_value_code(ages, asked, "is", "Live births by age of mother") == "17"


def test_a_short_list_label_matches_an_inflected_word():
    from grund_lang.pxtools import match_value_codes

    question = "Hve margar komur farþega voru með flugi árið 2024?"
    values = [("0", "Alls"), ("1", "1. Flug"), ("2", "1.1. Áætlunarflug"), ("4", "2. Sjóleið")]
    assert match_value_codes(values, question, "Komur farþega eftir tegund ferða") == ["1"]
    english = "How many international arrivals came by air in 2024?"
    modes = [("0", "Total"), ("1", "1. Air"), ("2", "1.1. Scheduled flights (estimates)")]
    assert match_value_codes(modes, english, "International arrivals by modes of transport") == ["1"]


def test_a_bare_year_asks_instead_of_guessing():
    cpi = frame_question("What was the consumer price index in 2024?")
    month = frame_question("What was the consumer price index in September 2026?")
    town = frame_question("What was the population of Reykjavík in 2024?")
    day = frame_question("How many people lived in Reykjavík on 1 January 2026?")
    assert needs_clarification(cpi) == "clarify_month"
    assert needs_clarification(month) is None
    assert needs_clarification(town) == "clarify"
    assert needs_clarification(day) is None


def test_loaded_metadata_does_not_call_the_live_search(tmp_path):
    import json

    from grund_lang.pxtools import MetaStore

    row = {
        "id": "VIS01000.px",
        "lang": "en",
        "title": "Consumer price index",
        "path_texts": ["Prices"],
        "updated": "2026-01-01",
        "variables": [{"code": "Item", "text": "Item", "values": [["CPI", "Consumer price index"]]}],
    }
    path = tmp_path / "tables.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")
    store = MetaStore(str(path))

    class _Client:
        def get_json(self, url):
            raise AssertionError(url)

    found = store.search({"measure": "consumer price index", "_language": "en"}, _Client())
    assert found and found[0][0] == "VIS01000"
