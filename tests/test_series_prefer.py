"""Headline series wins a disagreement. The flag is off by default."""

import pytest

from grund.series_prefer import capital_guard, preferred_path


def _path(table: str, value: str, coords: dict | None = None, labels: dict | None = None) -> dict:
    cell = {
        "table_id": table,
        "value": value,
        "coords": coords or {},
        "labels": labels or {},
        "key": list((coords or {}).values()),
    }
    return {
        "refused": False,
        "value": value,
        "table_id": table + ".px",
        "claims": [{"cells": [cell]}],
    }


def _none() -> dict:
    return {"refused": True, "value": None, "table_id": None}


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("GRUND_SERIES_PICK", "1")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_SERIES_PICK", raising=False)
    ranker = _path("MAN03250", "251912", {"Landshlutar": "Capital region"})
    hybrid = _path("VIN00001", "292400", {"Mánuður": "2026M01"})
    assert preferred_path("How many people lived in the capital region on 1 January 2026?", ranker, hybrid) is None


def test_population_beats_the_labour_force_for_a_named_region():
    ranker = _path("MAN03250", "251912", {"Landshlutar": "Capital region"})
    hybrid = _path("VIN00001", "292400", {"Mánuður": "2026M01"})
    question = "How many people lived in the capital region on 1 January 2026?"
    assert preferred_path(question, ranker, hybrid) == "ranker"


def test_current_price_gdp_beats_constant_prices():
    ranker = _path("THJ01102", "4941211", {"Skipting": "11"})
    hybrid = _path("THJ01103", "3600738", {"Skipting": "10"})
    assert preferred_path("Hver var verg landsframleiðsla á Íslandi árið 2025?", ranker, hybrid) == "ranker"


def test_gdp_beats_a_purchasing_power_index():
    ranker = _path("VIS06124", "228.3", {"Flokkur": "GDP"})
    hybrid = _path("THJ01102", "4576629", {"Skipting": "11"})
    assert preferred_path("What was GDP in 2024?", ranker, hybrid) == "hybrid"


def test_a_single_lookalike_is_not_promoted():
    ranker = _none()
    hybrid = _path("VIN00001", "292400")
    assert preferred_path("How many 18-year-olds lived in Iceland on 1 January 2026?", ranker, hybrid) is None


def test_country_headcount_does_not_take_a_region_total_over_mean_age():
    ranker = _path("MAN03250", "383726", {"Landshlutar": "Total"})
    hybrid = _path("MAN00102", "38.8", {"Ár": "2024"})
    assert preferred_path("What was the population of Iceland on 1 January 2024?", ranker, hybrid) is None


def test_wage_index_prefers_the_long_series_when_both_are_present():
    ranker = _path("LAU04001", "171.4")
    hybrid = _path("LAU04000", "1149.3")
    assert preferred_path("What was the wage index in August 2026?", ranker, hybrid) == "hybrid"


def test_an_icelandic_region_names_the_english_row():
    from grund.bind import _region_aliases
    from grund_index.textutil import fold

    assert "capital" in _region_aliases(fold("á höfuðborgarsvæðinu"))
    assert "west" in _region_aliases(fold("Vesturlands"))
    assert "hafnarfjardarkaupstadur" in _region_aliases(fold("í Hafnarfirði"))


def test_external_migration_beats_internal():
    ranker = _path("MAN01102", "58431")
    hybrid = _path("MAN01400", "18674")
    assert preferred_path("Hve margir fluttu til Íslands árið 2025?", ranker, hybrid) == "hybrid"


def test_a_men_question_does_not_take_the_sex_total():
    ranker = _path("MAN03250", "383726", {"Kyn": "0", "Landshlutar": "Total"}, {"Sex": "Total", "Region": "Total"})
    hybrid = _path("VIN00001", "196000", {"Mánuður": "2024M01"})
    assert preferred_path("Karlkyns íbúar 1. janúar 2024", ranker, hybrid) is None


def test_a_men_question_keeps_the_male_cell():
    ranker = _path("MAN00101", "196552", {"Kyn": "1"}, {"Sex": "Males"})
    hybrid = _path("VIN00001", "196000", {"Mánuður": "2024M01"})
    assert preferred_path("Male population of Iceland on 1 January 2024", ranker, hybrid) == "ranker"


def test_a_named_town_does_not_take_the_country_total():
    ranker = _path("MAN04203", "383726", {"Sveitarfélag": "IS"}, {"Municipality": "Total"})
    hybrid = _path("SAM08050", "121048")
    assert preferred_path("Mannfjöldi Sveitarfélagsins Árborgar 1. janúar 2024", ranker, hybrid) is None
    ranker = _path("MAN02005", "383726", {"Sveitarfélag": "9999"}, {"Municipality": "Total"})
    assert preferred_path("How many people lived in Seltjarnarnes on 1 January 2022?", ranker, hybrid) is None


def test_a_named_town_keeps_the_town_cell():
    ranker = _path(
        "MAN02005",
        "4573",
        {"Sveitarfélag": "1100"},
        {"Municipality": "Seltjarnarnesbaer"},
    )
    hybrid = _path("VIN00001", "4000")
    assert preferred_path("How many people lived in Seltjarnarnes on 1 January 2022?", ranker, hybrid) == "ranker"


def test_an_age_band_does_not_take_the_age_total():
    question = "How many people aged 18 years lived in Iceland on 1 January 2026?"
    hybrid = _path("VIN00001", "5040")
    total = _path("MAN00101", "394324", {"Aldur": "-1"}, {"Age": "Total"})
    single = _path("MAN00101", "5040", {"Aldur": "18"}, {"Age": "18 years"})
    assert preferred_path(question, total, hybrid) is None
    assert preferred_path(question, single, hybrid) == "ranker"


def test_the_capital_is_reykjavik_not_the_region():
    region = _path("MAN03250", "251912", {"Landshlutar": "Capital region"}, {"Region": "Capital region"})
    city = _path("MAN02005", "139804", {"Sveitarfélag": "0000"}, {"Municipality": "Reykjavikurborg"})
    look = _path("VIN00001", "292400")
    question = "How many people lived in the capital on 1 January 2026?"
    assert preferred_path(question, region, look) is None
    assert capital_guard(question, region, look) == "refuse"
    assert capital_guard(question, region, city) == "hybrid"
    assert preferred_path(question, city, look) == "ranker"


def test_the_capital_region_stays_the_region():
    region = _path("MAN03250", "251912", {"Landshlutar": "Capital region"}, {"Region": "Capital region"})
    city = _path("MAN02005", "139804", {"Sveitarfélag": "0000"}, {"Municipality": "Reykjavikurborg"})
    look = _path("VIN00001", "292400")
    question = "How many people lived in the capital region on 1 January 2026?"
    assert capital_guard(question, region, city) is None
    assert preferred_path(question, region, look) == "ranker"
    assert preferred_path(question, city, look) is None


def test_icelandic_capital_words_split_the_city_from_the_region():
    from grund.series_prefer import _capital_scope
    from grund_index.textutil import fold

    assert _capital_scope(fold("Hve margir búa í höfuðborginni?")) == "city"
    assert _capital_scope(fold("Mannfjöldi höfuðborgarinnar 1. janúar 2024")) == "city"
    assert _capital_scope(fold("Hve margir bjuggu á höfuðborgarsvæðinu 1. janúar 2026?")) == "region"


def test_the_south_and_the_northeast_stay_on_their_regions():
    look = _path("VIN00001", "1")
    south = _path("MAN03250", "36570", {"Landshlutar": "South"}, {"Region": "South"})
    northeast = _path("MAN03250", "32296", {"Landshlutar": "Northeast"}, {"Region": "Northeast"})
    assert preferred_path("How many people lived in the South on 1 January 2026?", south, look) == "ranker"
    assert preferred_path("How many people lived in the Northeast on 1 January 2026?", northeast, look) == "ranker"
    assert capital_guard("How many people lived in the South on 1 January 2026?", south, look) is None
    assert capital_guard("Hve margir bjuggu á Suðurlandi 1. janúar 2026?", south, look) is None


def test_women_on_the_country_row_are_not_the_capital_region():
    women = _path(
        "MAN03250",
        "189623",
        {"Landshlutar": "Total", "Kyn": "2"},
        {"Region": "Total", "Sex": "Females"},
    )
    other = _path("MAN00101", "189623", {"Kyn": "2"}, {"Sex": "Females"})
    question = "Hve margar konur bjuggu á Íslandi 1. janúar 2025?"
    assert capital_guard(question, women, other) is None


def test_a_country_total_stays_when_no_subgroup_is_named():
    ranker = _path("MAN03250", "394324", {"Landshlutar": "Total", "Kyn": "0"}, {"Region": "Total", "Sex": "Total"})
    hybrid = _path("VIN00001", "292400")
    assert preferred_path("How many people lived in Iceland on 1 January 2026?", ranker, hybrid) == "ranker"
