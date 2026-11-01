"""Question frames. GRUND_FRAME is off unless the test turns it on."""

from __future__ import annotations

import pytest

from grund.frame import (
    current_frame,
    frame_enabled,
    frame_question,
    impose_frame,
    latest_period_label,
    push_frame,
    reset_frame,
    value_named_by_frame,
    variable_role,
)


class _Var:
    def __init__(self, text, code, values, time=False):
        self.text = text
        self.code = code
        self.values = values
        self.time = time

    def label(self, code):
        for item, name in self.values:
            if item == code:
                return name
        return code


class _Edition:
    def __init__(self, variables):
        self.variables = variables
        self.title = "Population by regions"
        self.path_texts = []

    def years(self):
        return {2024, 2025, 2026}


def test_frame_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_FRAME", raising=False)
    assert frame_enabled() is False
    assert current_frame() is None
    monkeypatch.setenv("GRUND_FRAME", "1")
    assert frame_enabled() is True


def test_a_dated_national_headcount_stays_with_the_binder():
    dated = frame_question("Hversu margir bjuggu á Íslandi árið 2016?")
    latest = frame_question("how many people live in iceland")
    assert dated.measure == "population"
    assert dated.use is False
    assert latest.use is True


def test_people_in_iceland_is_a_latest_population_count():
    frame = frame_question("how many people live in iceland")
    assert frame.use
    assert frame.measure == "population"
    assert frame.operation == "level"
    assert frame.period.implicit
    assert frame.period.kind == "latest"
    assert frame.language == "en"


def test_icelandic_town_is_lemmatised():
    frame = frame_question("hvað búa margir í Kópavogi")
    assert frame.use
    assert frame.measure == "population"
    assert frame.municipality == "Kópavogur"
    assert frame.period.implicit
    assert frame.language == "is"


def test_inflation_now_is_a_cpi_change():
    frame = frame_question("what's inflation now")
    assert frame.use
    assert frame.measure == "cpi"
    assert frame.operation == "change"
    assert frame.period.implicit
    assert "annual change" in frame.pipeline_text.lower()


def test_south_does_not_select_southwest():
    frame = frame_question("How many people lived in the South on 1 January 2026?")
    assert frame.region == "south"
    regions = _Var(
        "Region",
        "Landshlutar",
        [
            ("0", "Total"),
            ("SW", "Southwest"),
            ("S", "South"),
            ("NE", "Northeast"),
        ],
    )
    edition = _Edition([regions])
    token = push_frame(frame)
    try:
        chosen = impose_frame(edition, {})
    finally:
        reset_frame(token)
    assert chosen == {"Landshlutar": ["S"]}


def test_open_age_span_is_not_one_cell():
    frame = frame_question("How many people aged 65 and older lived in Iceland on 1 January 2026?")
    assert frame.blocked == "age_span"
    assert frame.use is False


def test_trade_balance_without_a_month_is_blocked():
    frame = frame_question("What was the balance of trade in 2025?")
    assert frame.blocked == "month_missing"


def test_opinion_and_weather_are_not_cells():
    assert frame_question("Is inflation too high?").blocked == "opinion"
    assert frame_question("What was the temperature in Reykjavík yesterday?").blocked == "non_statistics"
    assert frame_question("How many people live on Mars?").blocked == "non_statistics"
    assert frame_question("How many people live on the Moon?").blocked == "non_statistics"
    assert frame_question("Hve margir búa á tunglinu?").blocked == "non_statistics"


def test_filters_map_to_dimension_codes():
    frame = frame_question("What was the unemployment rate for women in the second quarter of 2026?")
    assert frame.measure == "unemployment_rate"
    assert frame.sex == "female"
    assert frame.period.quarter == 2
    sex = _Var("Sex", "Kyn", [("0", "Males and females"), ("1", "Males"), ("2", "Females")])
    unit = _Var(
        "Unit",
        "Eining",
        [("r", "Unemployment rate, % (of labour force)"), ("n", "Unemployed (Estimated number)")],
    )
    edition = _Edition([sex, unit])
    token = push_frame(frame)
    try:
        chosen = impose_frame(edition, {})
        assert value_named_by_frame("Females")
    finally:
        reset_frame(token)
    assert chosen["Kyn"] == ["2"]
    assert chosen["Eining"] == ["r"]
    assert variable_role(sex) == "sex"


def test_relative_last_year_and_the_card_label():
    frame = frame_question("what was the wage index last year")
    assert frame.period.kind == "relative"
    assert frame.period.relative == "previous"
    assert latest_period_label("en", "2026M08") == "latest published period: 2026M08"
    assert latest_period_label("is", "2026M09") == "nýjasta birta tímabil: 2026M09"


def test_eighteen_year_olds_and_a_typo():
    age = frame_question("How many 18-year-olds lived in Iceland on 1 January 2026?")
    assert age.age_exact == "18"
    assert age.measure == "population"
    typo = frame_question("how many peopl lived in iceland on 1 janury 2026")
    assert typo.measure == "population"
    assert "people" in typo.corrected.lower()
    assert typo.period.year == 2026


def test_impose_is_a_no_op_without_a_frame():
    edition = _Edition([_Var("Sex", "Kyn", [("0", "Total"), ("1", "Males")])])
    assert current_frame() is None
    assert impose_frame(edition, {"Kyn": ["0"]}) == {"Kyn": ["0"]}


def test_a_capitalised_common_noun_is_not_a_town():
    beds = frame_question("What was Hospital beds, Number in 2020?")
    prisoners = frame_question("What was Prisoners in 2013?")
    debt = frame_question("What was Long-term foreign debt in 2016?")
    register = frame_question("Hversu margar konur voru á þjóðskrá 1. janúar 2024?")
    assert beds.municipality == ""
    assert prisoners.municipality == ""
    assert debt.municipality == ""
    assert register.municipality == ""
    assert beds.use is False
    assert prisoners.use is False
    assert debt.use is False
    assert register.use is False


def test_capital_area_is_not_the_capital_region_or_the_city():
    area = frame_question("How many people live in the capital area?")
    city = frame_question("How many people lived in the capital on 1 January 2026?")
    region = frame_question("How many people lived in the capital region on 1 January 2026?")
    assert area.unresolved_place is True
    assert area.use is False
    assert area.region == ""
    assert city.municipality == "Reykjavík"
    assert city.region == ""
    assert city.use is True
    assert region.region == "capital"
    assert region.municipality == ""
    assert region.use is True


def test_a_share_or_a_difference_or_two_measures_stay_with_the_planner():
    share = frame_question("What percentage of Iceland's population on 1 January 2026 were women?")
    gap = frame_question("How many more men than women lived in Iceland on 1 January 2026?")
    both = frame_question("What were the wage index and the consumer price index in August 2026?")
    assert share.operation == "share" and share.use is False
    assert gap.operation == "difference" and gap.use is False
    assert both.use is False


def test_a_year_on_a_monthly_index_does_not_pick_the_average():
    bare = frame_question("What was the consumer price index in 2024?")
    month = frame_question("What was the consumer price index in September 2026?")
    denied = frame_question(
        "What was the consumer price index in September 2026, the index level and not the annual change?"
    )
    assert bare.use is False
    assert month.use is True
    assert month.period.month == 9
    assert denied.operation == "level"


def test_an_age_band_inside_a_rate_is_not_blocked():
    rate = frame_question(
        "Um hve mörg prósent hækkaði lágtekjuhlutfall einstaklinga 25 ára og eldri frá 2022 til 2023?"
    )
    assert rate.blocked == ""
    assert rate.use is False


def test_a_bare_unemployment_year_is_not_one_series():
    annual = frame_question("Hvert var atvinnuleysið árið 2023?")
    quarter = frame_question("What was the unemployment rate for women in the second quarter of 2026?")
    assert annual.measure == "unemployment_rate"
    assert annual.use is False
    assert quarter.use is True


def test_reykjanesbaer_is_a_town_and_january_is_the_stock():
    frame = frame_question("Hvað var Reykjanesbær stór 1. janúar 2025?")
    assert frame.municipality == "Reykjanesbær"
    assert frame.period.month == 1
    assert frame.measure == "population"
    assert frame.use is True
