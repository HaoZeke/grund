"""A named subgroup has to be the value on the chosen cell."""

from grund.subgroup_bind import bind_reason


def _result(labels: dict, value: str = "1") -> dict:
    return {
        "refused": False,
        "value": value,
        "table_id": "MAN03260.px",
        "claims": [{"cells": [{"labels": labels, "coords": {}, "value": value}]}],
    }


def test_age_total_is_not_the_named_year():
    result = _result({"Sex": "Females", "Age": "Total", "Region": "Total"})
    assert bind_reason("How many women aged 70 years lived in Iceland on 1 January 2017?", result) == "subgroup-bind:age"


def test_a_matching_age_and_sex_is_kept():
    result = _result({"Sex": "Females", "Age": "70 years"})
    assert bind_reason("How many women aged 70 years lived in Iceland on 1 January 2017?", result) is None


def test_women_without_an_age_keep_the_female_total():
    result = _result({"Sex": "Females", "Age": "Total", "Region": "Total"})
    assert bind_reason("How many women lived in Iceland on 1 January 2016?", result) is None


def test_the_capital_region_is_not_the_output_area_total():
    result = _result({"Sex": "Females", "Region": "Total"})
    question = "How many women lived in the capital region on 1 January 2017?"
    assert bind_reason(question, result) == "subgroup-bind:place"


def test_the_capital_region_cell_matches_the_region_question():
    result = _result({"Sex": "Total", "Region": "Capital region"})
    assert bind_reason("How many people lived in the capital region on 1 January 2019?", result) is None


def test_the_capital_city_does_not_match_the_region_cell():
    result = _result({"Region": "Capital region"})
    assert bind_reason("How many people lived in the capital on 1 January 2019?", result) == "subgroup-bind:place"


def test_reykjavik_matches_the_capital_city():
    result = _result({"Municipality": "Reykjavikurborg"})
    assert bind_reason("How many people lived in the capital on 1 January 2019?", result) is None


def test_a_title_echo_may_use_the_dimension_total():
    result = _result({"Sex": "Total", "Age": "Total", "Citizenship": "Total"})
    question = "What was Population by sex, citizenship and region in 1981?"
    assert bind_reason(question, result) is None


def test_men_do_not_match_the_female_cell():
    result = _result({"Sex": "Females"})
    assert bind_reason("How many men lived in Iceland on 1 January 2019?", result) == "subgroup-bind:sex"


def test_foreign_citizens_do_not_match_the_citizenship_total():
    result = _result({"Citizenship": "Total"})
    assert bind_reason("How many foreign citizens lived in Iceland in 2019?", result) == "subgroup-bind:nationality"


def test_foreign_citizens_match_the_foreign_row():
    result = _result({"Citizenship": "Foreign"})
    assert bind_reason("How many foreign citizens lived in Iceland in 2019?", result) is None


def test_a_share_keeps_the_female_cell_beside_the_total():
    result = {
        "refused": False,
        "value": "48.7",
        "table_id": "MAN03250.px",
        "claims": [{"cells": [
            {"labels": {"Kyn": "Konur", "Landshlutar": "Alls", "Aldur": "Alls"}},
            {"labels": {"Kyn": "Alls", "Landshlutar": "Alls", "Aldur": "Alls"}},
        ]}],
    }
    assert bind_reason("Hve stórt hlutfall landsmanna 1. janúar 2026 voru konur?", result) is None


def test_kilotonnes_is_not_a_place():
    result = _result({"Measure": "Kilotonnes", "Indicator": "Domestic extraction (DE)"})
    assert bind_reason("What was domestic extraction in kilotonnes in 2025?", result) is None


def test_the_south_matches_the_south_row():
    result = _result({"Region": "South"})
    assert bind_reason("How many people lived in the South on 1 January 2018?", result) is None
