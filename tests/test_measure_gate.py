"""The cited cell has to be the measure the question asked for."""

from __future__ import annotations

import pytest

from grund.parse import parse_question
from grund.toolpath import decide_gate
from grund_index.model import Edition, Variable
from grund_rails.cell_claim import _measure_block


def _cell(title, labels, value="1", period="2025", latest="2025"):
    return {
        "title": title,
        "labels": labels,
        "value": value,
        "period": period,
        "latest_period": latest,
    }


def test_a_population_count_rejects_a_rate_and_a_percent():
    question = "How many people live in Iceland?"
    fertility = _cell("Population", {"Unit": "Total fertility rate"}, "2.6", "2024", "2024")
    share = _cell("Population", {"Division": "Immigrants percent of total population, %"}, "11.6", "2017", "2017")
    assert _measure_block(question, {"measure": "count"}, [fertility]) == "unsupported_cell"
    assert _measure_block("Hver er mannfjöldi Íslands?", {"measure": "count"}, [share]) == "unsupported_cell"
    stock = _cell("Population - key figures", {"Unit": "Population 1 January"}, "394324", "2026", "2026")
    assert _measure_block(question, {"measure": "count"}, [stock]) is None


def test_gdp_has_to_be_the_isk_level():
    question = "What was Iceland's GDP in 2025?"
    ratio = _cell("Key indicators", {"Category": "Total investment to GDP ratio"}, "26.9")
    exports = _cell("Gross domestic product", {"Category": "6. Exports of goods and services"}, "1997388")
    level = _cell("Gross domestic product", {"Category": "8. Gross Domestic Product"}, "4941211")
    icelandic = _cell("Landsframleiðsla", {"Skipting": "8. Verg landsframleiðsla"}, "4941211")
    assert _measure_block(question, {"measure": "gdp"}, [ratio]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "gdp"}, [exports]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "gdp"}, [level]) is None
    assert _measure_block("Hver var landsframleiðslan árið 2025?", {"measure": "gdp"}, [icelandic]) is None


def test_reykjavik_has_to_cite_reykjavik():
    question = "Hve margir búa í Reykjavík?"
    country = _cell("Population by postcodes", {"Postcodes": "Total"}, "394324", "2026", "2026")
    postcode = _cell("Population by postcodes", {"Postcodes": "101 Reykjavík"}, "20000", "2026", "2026")
    city = _cell("Population in Reykjavík by districts", {"Districts": "Total"}, "139804", "2026", "2026")
    assert _measure_block(question, {"measure": "count"}, [country]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "count"}, [postcode]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "count"}, [city]) is None


def test_no_year_rejects_an_older_period():
    question = "How many people live in Iceland?"
    old = _cell("Population", {"Unit": "Population 1 January", "Year": "2011"}, "319000", "2011", "2026")
    assert _measure_block(question, {"measure": "count"}, [old]) == "unsupported_cell"


def test_the_dollar_is_the_selling_rate_not_gdp_per_capita():
    question = "What is the exchange rate of the US dollar?"
    per_capita = _cell("GDP per capita", {"Unit": "USD, current exchange rate"}, "86473", "2024", "2024")
    rate = _cell("Central Bank average selling rates of USD", {"Currency": "USD", "Month": "All year"}, "120.96", "2016", "2016")
    assert _measure_block(question, {"measure": "currency"}, [per_capita]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "currency"}, [rate]) is None


def test_overnight_stays_are_not_the_hotels_only_series():
    question = "How many overnight stays were there in Iceland in 2025?"
    hotels = _cell("Overnight stays and arrivals in hotels", {"Unit": "Overnight stays"}, "5444463")
    every = _cell("Overnight stays and arrivals in all types of registered accommodation", {"Unity": "Overnight stays"}, "9850428")
    assert _measure_block(question, {"measure": "count"}, [hotels]) == "unsupported_cell"
    assert _measure_block(question, {"measure": "count"}, [every]) is None


def test_citizenship_iceland_is_not_the_resident_total():
    question = "How many people lived in Iceland on 1 January 2026?"
    citizens = _cell(
        "Population by country of citizenship",
        {"Citizenship": "Iceland", "Age": "Total", "Sex": "Total"},
        "323769",
        "2026",
        "2026",
    )
    from grund_rails.cell_claim import check_claim

    assert check_claim(question, {"value": "323769", "period": "2026", "labels": citizens["labels"]}, [citizens]) == "unrequested_breakdown"


def test_the_binder_picks_the_gdp_line_and_not_exports():
    from grund.bind import bind

    edition = Edition(
        lang="en",
        title="Gross domestic product and Gross national income 1995-2025",
        db="Efnahagur",
        path=["Efnahagur"],
        path_texts=["National accounts"],
        url="https://px.example/THJ01102.px",
        updated="2026-01-01",
        variables=[
            Variable("Year", "Year", True, False, [("2025", "2025")]),
            Variable(
                "Category",
                "Category",
                False,
                False,
                [("5", "6. Exports of goods and services"), ("11", "8. Gross Domestic Product")],
            ),
        ],
    )
    binding = bind(edition, parse_question("What was Iceland's GDP in 2025?"))
    assert binding is not None
    chosen = {item["code"]: item["selection"]["values"] for item in binding.selections}
    assert chosen["Category"] == ["11"]


def test_gdp_index_and_votes_and_a_lone_level_are_the_wrong_measure():
    index = _cell("Indices of GDP", {"Value unit": "Volume index", "Category": "8. Gross Domestic Product"}, "120.67")
    assert _measure_block("What was Iceland's GDP in 2025?", {"measure": "gdp"}, [index]) == "unsupported_cell"
    votes = _cell("Úrslit borgarstjórnakosninga í Reykjavík", {"Einingar": "Gild atkvæði"}, "58971", "2018", "2018")
    assert _measure_block("Hve margir búa í Reykjavík?", {"measure": "count"}, [votes]) == "unsupported_cell"
    band = _cell("Population by status", {"Age": "16-74", "Unit": "Population (Total)"}, "289900", "2025", "2025")
    from grund_rails.cell_claim import check_claim

    assert check_claim("How many people live in Iceland?", {"value": "289900", "op": "level", "period": "2025"}, [band]) == "unrequested_breakdown"
    fish = _cell("Aquaculture production in Iceland", {"Species": "Total"}, "64417")
    assert _measure_block("How many overnight stays were there in Iceland in 2025?", {"op": "level"}, [fish]) == "unsupported_cell"
    level = _cell("Wage index", {"Unit": "Value of index"}, "1087.7", "2025M08", "2026M08")
    assert _measure_block(
        "By how many points did the wage index rise from August 2025 to August 2026?",
        {"op": "level", "value": "1087.7"},
        [level],
    ) == "unsupported_cell"


def test_the_headline_series_is_not_a_sub_index():
    from grund_rails.cell_claim import _measure_block

    cpi = "Hvar stóð vísitala neysluverðs í desember 2023?"
    housing = _cell(
        "Vísitala neysluverðs án húsnæðis",
        {"Mánuður": "2023", "Liður": "Vísitala"},
        "8814482",
        "2023",
        "2023",
    )
    headline = _cell(
        "Vísitala neysluverðs og breytingar, grunnur 1988=100",
        {"Mánuður": "2023M12", "Liður": "Vísitala"},
        "608.3",
        "2023M12",
        "2023M12",
    )
    assert _measure_block(cpi, {"op": "level", "measure": "index"}, [housing]) == "unsupported_cell"
    assert _measure_block(cpi, {"op": "level", "measure": "index"}, [headline]) is None
    hotels = _cell("Gistinætur og gestakomur á hótelum", {"Eining": "Gistinætur", "Þjóðerni": "Alls"}, "1", "2023", "2023")
    stays = "Hve margar gistinætur voru skráðar árið 2023?"
    assert _measure_block(stays, {"op": "level"}, [hotels]) == "unsupported_cell"
    exports = _cell("Landsframleiðsla og þjóðartekjur", {"Skipting": "6. Útflutningur alls"}, "1244827", "2021", "2021")
    gdp = _cell("Landsframleiðsla og þjóðartekjur", {"Skipting": "8. Verg landsframleiðsla"}, "3331537", "2021", "2021")
    asked = "Hver var verg landsframleiðsla 2021, í milljónum króna?"
    assert _measure_block(asked, {"op": "level", "measure": "gdp"}, [exports]) == "unsupported_cell"
    assert _measure_block(asked, {"op": "level", "measure": "gdp"}, [gdp]) is None
    school = _cell("Brottfall starfsfólks við kennslu í grunnskólum", {"Eining": "Starfsfólk"}, "5911", "2024", "2024")
    assert _measure_block("Hve margir voru í vinnuafli árið 2024?", {"op": "level"}, [school]) == "unsupported_cell"
    national = _cell("Mannfjöldi eftir landshlutum", {"Landshluti": "Alls", "Ár": "2026"}, "394324", "2026", "2026")
    assert _measure_block("Hve margir bjuggu á Akranesi 1. janúar 2026?", {"op": "level"}, [national]) == "unsupported_cell"


def test_a_birth_count_is_not_the_population_by_birthplace():
    from grund_rails.cell_claim import _measure_block

    question = "Hve mörg börn fæddust á Íslandi árið 2024?"
    people = _cell(
        "Mannfjöldi eftir fæðingarlandi, kyni og aldri",
        {"Fæðingarland": "Ísland", "Kyn": "Alls", "Aldur": "Alls"},
        "301931",
        "2024",
        "2024",
    )
    births = _cell(
        "Lifandi fædd börn eftir aldursflokki móður",
        {"Skipting": "Alls lifandi fædd börn", "Aldur": "Alls"},
        "4311",
        "2024",
        "2024",
    )
    assert _measure_block(question, {"op": "level", "measure": "count"}, [people]) == "unsupported_cell"
    assert _measure_block(question, {"op": "level", "measure": "count"}, [births]) is None
    first = _cell(
        "Live births by age of mother",
        {"Unit": "First born children", "Age": "Total"},
        "1712",
        "2024",
        "2024",
    )
    english = "How many children were born in Iceland in 2024?"
    assert _measure_block(english, {"op": "level"}, [first]) == "unsupported_cell"


def test_the_eight_dev_a_wrongs_that_have_a_lossless_gate():
    from grund_rails.cell_claim import (
        _measure_block,
        _question_measure_conflict,
        _superlative_total,
        _unemployed_beside_employed,
        _unnamed_cpi_base,
    )

    percent = _cell(
        "Percent of old age pension beneficiaries by type of payment",
        {"Type of payment": "Total", "Gender": "Total"},
        "65.3",
    )
    other = _cell(
        "Percent of old age pension beneficiaries by type of payment",
        {"Type of payment": "Old age pension beneficiaries with residence in Iceland"},
        "63.7",
    )
    question = "What was Percent of pension beneficiaries by type of payment in December 2022?"
    assert _measure_block(question, {"op": "share"}, [percent, other]) == "unsupported_cell"

    debt = _cell(
        "Income, assets and debts of immigrants by residency",
        {"Residency": "Northeast", "Finances": "Debt", "Unit": "Median"},
        "836730",
    )
    assets = _cell(
        "Income, assets and debts of immigrants by residency",
        {"Residency": "Northeast", "Finances": "Assets", "Unit": "Median"},
        "5361708",
    )
    finance = "What was Income, assets and debts of immigrants by residency, Northeast, Median, 2017?"
    assert _question_measure_conflict(finance, debt)
    assert _question_measure_conflict(finance, assets) is False

    unemployed = _cell(
        "Vinnuafl, starfandi, atvinnulausir og vinnustundir",
        {"Eining": "Atvinnulausir", "Kyn/aldur": "Alls"},
        "11900",
    )
    labour = "Hver var vinnuafl, starfandi, atvinnulausir og vinnustundir í september 2026?"
    assert _question_measure_conflict(labour, unemployed)
    only_unemployed = _cell("Labour force", {"Unit": "Unemployed"}, "11900")
    assert _unemployed_beside_employed("How many were unemployed in September 2026?", only_unemployed) is False

    recovery = _cell(
        "Waste processing of end of life vehicles",
        {"Measure": "Total reuse and recovery", "Unit": "Tonnes"},
        "-2382.10",
    )
    recycling = _cell(
        "Waste processing of end of life vehicles",
        {"Measure": "Recycling", "Unit": "Tonnes"},
        "-2562",
    )
    vehicles = "By how much did Waste processing of end of life vehicles, Tonnes, fall from 2021 to 2022?"
    assert _question_measure_conflict(vehicles, recovery)
    assert _question_measure_conflict(vehicles, recycling) is False

    national = _cell(
        "Population by sex, municipality, citizenship and age",
        {"Municipality": "Alls", "Sex": "Total"},
        "394324",
    )
    national["table_id"] = "MAN04208"
    reykjavik = _cell(
        "Population by municipality, age and sex",
        {"Municipality": "Reykjavík", "Sex": "Total"},
        "139804",
    )
    reykjavik["table_id"] = "MAN02005"
    largest = "How many people lived in the most populous municipality in Iceland on 1 January 2026?"
    assert _superlative_total(largest, national)
    assert _superlative_total(largest, reykjavik) is False
    national_total = _cell(
        "Population by sex, municipality, citizenship and age",
        {"Municipality": "Total", "Sex": "Total"},
        "394324",
    )
    assert _superlative_total(largest, national_total)
    sex_only = _cell(
        "Population by sex and age",
        {"Sex": "Total", "Age": "Total"},
        "394324",
    )
    assert _superlative_total(largest, sex_only) is False
    flest = _cell(
        "Mannfjöldi eftir kyni, sveitarfélagi, aldri og ríkisfangi",
        {"Sveitarfélag": "Alls"},
        "394324",
    )
    assert _superlative_total("Hvar búa flestir íbúar í einu sveitarfélagi?", flest)
    assert _superlative_total("Hvar búa flestir íbúar í einu sveitarfélagi?", reykjavik) is False
    origin = _cell(
        "Vísitala neysluverðs eftir eðli og uppruna",
        {"Liður": "Vísitala"},
        "95.1",
    )
    origin["table_id"] = "VIS01101"
    headline = _cell(
        "Vísitala neysluverðs og breytingar, grunnur 1988=100",
        {"Liður": "Vísitala neysluverðs án húsnæðis"},
        "511.7",
    )
    headline["table_id"] = "VIS01000"
    housing = "Hvað sýndi vísitalan án húsnæðis í desember 2024?"
    assert _unnamed_cpi_base(housing, origin)
    assert _unnamed_cpi_base(housing, headline) is False
    from grund_rails.cell_claim import _unnamed_projection

    projection = _cell("Population projection by age and sex 2026-2075", {"Sex": "Females", "Variant": "Median"}, "48.1")
    actual = _cell("Population by regions, sex and age", {"Sex": "Females", "Region": "Total"}, "48.7")
    women = "What percentage of Iceland's population on 1 January 2026 were women?"
    assert _unnamed_projection(women, projection)
    assert _unnamed_projection(women, actual) is False
    from grund_rails.cell_claim import _listed_age_statistics

    mean = _cell("Mean age, median age and modal age of spouses", {"Age": "Mean age", "Sex": "Bridegrooms"}, "39.8")
    median = _cell("Mean age, median age and modal age of spouses", {"Age": "Median age", "Sex": "Bridegrooms"}, "37")
    listed = "What was Mean age, median age and modal age of spouses by previous marital status, Bridegrooms in 2020?"
    named = "Hver var meðal-, mið- og tíðasti aldur, Miðaldur, Brúðgumar árið 2020?"
    assert _listed_age_statistics(listed, mean)
    assert _listed_age_statistics(named, median) is False
    assert _unnamed_projection("What is the population projection for 2050?", projection) is False
    named = _cell("Vísitala neysluverðs eftir eðli og uppruna frá 1997-2025", {"Liður": "Vísitala"}, "231.9")
    named["table_id"] = "VIS01102"
    assert _unnamed_cpi_base(
        "Hver var vísitala neysluverðs eftir eðli og uppruna, mars 1997 = 100 í desember 2025?",
        named,
    ) is False


def test_a_count_of_families_is_not_the_money_total_on_the_same_table():
    from grund_rails.cell_claim import _measure_block

    question = "How many families had negative net worth in real estate in 2025?"
    money = _cell(
        "Number of families with negative net worth in real estate 1997-2025",
        {"Year": "2025", "Number of families with negative net worth in real estate": "Total"},
        "-32634913342",
        "2025",
        "2025",
    )
    money["table_id"] = "THJ09008"
    count = _cell(
        "Number of families with negative net worth in real estate 1997-2025",
        {"Year": "2025", "Number of families with negative net worth in real estate": "Number of families"},
        "2722",
        "2025",
        "2025",
    )
    count["table_id"] = "THJ09008"
    assert _measure_block(question, {"op": "level"}, [money]) == "unsupported_cell"
    assert _measure_block(question, {"op": "level"}, [count]) is None


def test_a_population_question_needs_a_population_table():
    from grund_rails.cell_claim import _measure_block

    question = "Hve margir voru búsettir á Íslandi á nýársdag 2026?"
    turnover = _cell(
        "VSK velta í einkennandi atvinnugreinum ferðaþjónustu á Íslandi 2016-",
        {"Ár": "2026", "Atvinnugrein (ÍSAT2008)": "Total"},
        "121048",
        "2026",
        "2026",
    )
    turnover["table_id"] = "SAM08050"
    people = _cell(
        "Mannfjöldi eftir kyni og aldri 1841-2026",
        {"Kyn": "Alls", "Aldur": "Alls", "Ár": "2026"},
        "394324",
        "2026",
        "2026",
    )
    people["table_id"] = "MAN00101"
    assert _measure_block(question, {"op": "level"}, [turnover]) == "unsupported_cell"
    assert _measure_block(question, {"op": "level"}, [people]) is None


def test_registered_overnight_stays_are_not_room_capacity():
    from grund_rails.cell_claim import _question_measure_conflict

    question = "Um hve mörg prósent fjölgaði gistinóttum á skráðum gististöðum á Íslandi frá 2024 til 2025?"
    capacity = _cell(
        "Fjöldi þjónustuaðila og nýting gistirýmis eftir tegund gistingar 2009-2025",
        {"Ár": "2025", "Fjöldi": "Nýting rúma, %"},
        "2.7",
        "2025",
        "2025",
    )
    capacity["table_id"] = "SAM08007"
    stays = _cell(
        "Gistinætur og gestakomur á öllum tegundum skráðra gististaða 1998-",
        {"Eining": "Gistinætur", "Ár": "2025"},
        "5.77",
        "2025",
        "2025",
    )
    stays["table_id"] = "SAM01601"
    assert _question_measure_conflict(question, capacity)
    assert _question_measure_conflict(question, stays) is False


def test_accommodation_operators_are_not_overnight_stays_and_one_sex_is_not_a_difference():
    from grund_rails.cell_claim import _measure_block

    operators = _cell(
        "Fjöldi þjónustuaðila og nýting gistirýmis",
        {"Tegund gistingar": "Hótel og gistiheimili", "Fjöldi": "Fjöldi þjónustuaðila"},
        "697",
        "2025",
        "2025",
    )
    assert (
        _measure_block(
            "Hve margar gistinætur voru á skráðum gististöðum á Íslandi árið 2025?",
            {"op": "level"},
            [operators],
        )
        == "unsupported_cell"
    )
    women = _cell("Mannfjöldi eftir kyni og aldri", {"Kyn": "Konur", "Aldur": "Alls"}, "191927", "2026", "2026")
    assert (
        _measure_block(
            "Hve mörgum fleiri karlar en konur bjuggu á Íslandi 1. janúar 2026?",
            {"op": "level"},
            [women],
        )
        == "unsupported_cell"
    )


def test_a_stock_date_is_not_a_monthly_cell():
    from grund_rails.cell_claim import _measure_block

    stock = _cell("Population - key figures", {"Unit": "Population 1 January"}, "394324", "2026", "2026")
    assert _measure_block(
        "How many people lived in Iceland on 1 January 2026?",
        {"op": "level", "measure": "count"},
        [stock],
    ) is None


def test_the_agreement_gate():
    assert decide_gate(True, True, True) == "ranker"
    assert decide_gate(False, True, False) == "ranker"
    assert decide_gate(False, False, True) == "hybrid"
    assert decide_gate(False, True, True) == "refuse"
    assert decide_gate(False, False, False) == "refuse"


def test_the_immigrant_stock_is_not_arrivals_in_the_year():
    from grund_rails.cell_claim import _measure_block

    question = "How many immigrants lived in Iceland in 2026?"
    stock = _cell(
        "Population by origin, sex and age 1996-2026",
        {"Origin": "Immigrant", "Age": "Total", "Sex": "Total", "Year": "2026"},
        "77226",
        "2026",
        "2026",
    )
    flow = _cell(
        "External migration by sex",
        {"Unit": "Immigrants", "Sex": "Total", "Year": "2026"},
        "18674",
        "2026",
        "2026",
    )
    assert _measure_block(question, {"op": "level", "measure": "count"}, [stock]) == "unsupported_cell"
    assert _measure_block(question, {"op": "level", "measure": "count"}, [flow]) is None


def test_a_blocked_ranker_still_runs_hybrid(monkeypatch):
    from grund.engine import Engine
    from grund.parse import parse_question
    from grund.toolpath import run_hybrid_safe

    monkeypatch.delenv("GRUND_PATH", raising=False)

    class Tiny:
        tables: list = []

    engine = Engine(Tiny(), planner="deterministic")
    seen = {}

    def hybrid(*_args, **_kwargs):
        seen["ran"] = True
        return {"refused": True, "value": None, "claims": [], "candidates": []}

    monkeypatch.setattr("grund.toolpath.run_hybrid_safe", hybrid)
    parsed = parse_question("How many immigrants lived in Iceland in 2026?")
    ranker = {"refused": True, "value": None, "claims": [], "candidates": [{"table_id": "MAN43000"}]}
    result = engine._agree_with_hybrid(parsed.text, parsed, ranker, [], 0.0)
    assert seen.get("ran") is True
    assert result["refused"] is True
    assert run_hybrid_safe  # the quiet-refusal helper stays importable


def test_a_missing_index_is_not_a_quiet_hybrid_refusal(monkeypatch):
    from grund.engine import Engine, IndexOffline
    from grund.parse import parse_question
    from grund.toolpath import run_hybrid_safe

    class Tiny:
        tables: list = []

    engine = Engine(Tiny(), planner="deterministic")

    def missing(self):
        raise IndexOffline("value-label index is missing. sh lang/fetch-index.sh")

    monkeypatch.setattr(Engine, "_require_value_index", missing)
    with pytest.raises(IndexOffline):
        run_hybrid_safe(engine, "How many immigrants lived in Iceland in 2026?", parse_question("How many immigrants lived in Iceland in 2026?"), [], 0.0)


def test_an_unrelated_table_does_not_match_the_question():
    from grund_rails.cell_claim import question_match_claims

    claims = [{
        "value": "0",
        "op": "level",
        "cells": [{
            "title": "Production account",
            "period": "2024",
            "labels": {"Category": "Total", "Year": "2024"},
            "value": "0",
        }],
    }]
    assert question_match_claims(
        "By how much did R&D expenditures as percentage of GDP fall from 2023 to 2024?",
        claims,
    ) is False


def test_both_paths_treat_undeclared_number_the_same():
    from grund_rails.cell_claim import CellClaimRail, rail_effect

    assert rail_effect("undeclared_number", ["undeclared_number"], computed=True) == "pass"
    assert rail_effect("undeclared_number", ["undeclared_number"], computed=False) == "refuse"
    assert rail_effect("unsupported_cell", ["unsupported_cell"], computed=True) == "retry"
    assert rail_effect("missing_source", ["missing_source"], computed=True) == "refuse"
    rail = CellClaimRail()
    context = {
        "question": "How many people live in Iceland?",
        "computed": True,
        "claim": {"value": "1", "op": "level"},
        "cells": [{"value": "394324", "period": "2026", "labels": {"Unit": "Population 1 January"}, "title": "Population"}],
        "claims": [{"value": "1", "op": "level", "cells": [{"value": "394324", "period": "2026", "labels": {"Unit": "Population 1 January"}, "title": "Population"}]}],
    }
    computed = rail.decide("The figure was 1.", context)
    context["computed"] = False
    raw = rail.decide("The figure was 1.", context)
    assert computed.passed_ok()
    assert raw.blocked_turn()


def test_a_share_cannot_state_a_headcount():
    question = "Hve stórt hlutfall landsmanna 1. janúar 2026 voru konur?"
    headcount = _cell("Mannfjöldi", {"Kyn": "Konur", "Unit": "Number"}, "142800", "2026", "2026")
    percent = _cell("Mannfjöldi", {"Kyn": "Konur", "Unit": "Percent"}, "48.7", "2026", "2026")
    assert _measure_block(question, {"op": "level"}, [headcount]) == "unsupported_cell"
    assert _measure_block(question, {"op": "level"}, [percent]) is None
    assert _measure_block(question, {"op": "share"}, [headcount]) is None


def test_residents_are_not_the_labour_force_and_the_catch_is_not_exports():
    people = "Hve mörgum fleiri karlar en konur bjuggu 1. janúar 2026?"
    labour = _cell("Vinnuafl, starfandi, atvinnulausir og vinnustundir", {"Kyn": "Karlar"}, "3100", "2026", "2026")
    population = _cell("Mannfjöldi á Íslandi eftir kyni", {"Kyn": "Karlar"}, "202000", "2026", "2026")
    assert _measure_block(people, {"op": "difference"}, [labour]) == "unsupported_cell"
    assert _measure_block(people, {"op": "difference"}, [population, population]) is None
    catch = "How much cod was caught in September 2026?"
    exports = _cell("Exports of goods fob", {"Category": "Total"}, "88123", "2026M09", "2026M09")
    fishing = _cell("Afli eftir fisktegundum", {"Tegund": "Þorskur"}, "16550932", "2026M09", "2026M09")
    assert _measure_block(catch, {"op": "level"}, [exports]) == "unsupported_cell"
    assert _measure_block(catch, {"op": "level"}, [fishing]) is None
    building = "Hver var byggingarvísitalan, ársmeðaltal, árið 2024?"
    wage = _cell("Launavísitala eftir mánuðum", {"Unit": "Index"}, "1004.6", "2024", "2024")
    other = _cell("Vísitala annarra liða", {"Unit": "Index"}, "288", "2024", "2024")
    assert _measure_block(building, {"op": "level"}, [wage]) == "unsupported_cell"
    assert _measure_block(building, {"op": "level"}, [other]) == "unsupported_cell"


def test_an_unqualified_wage_index_is_not_constant_prices():
    nominal = "Hver var launavísitalan í ágúst 2026?"
    constant = _cell("Launavísitala miðað við fast verðlag", {"Unit": "Index"}, "169.7", "2026M08", "2026M08")
    level = _cell("Launavísitala eftir mánuðum", {"Unit": "Index"}, "1149.3", "2026M08", "2026M08")
    assert _measure_block(nominal, {"op": "level"}, [constant]) == "unsupported_cell"
    assert _measure_block(nominal, {"op": "level"}, [level]) is None
    real = "What was the wage index at constant prices in August 2026?"
    assert _measure_block(real, {"op": "level"}, [constant]) is None
    mortgage = _cell("Launavísitala til greiðslujöfnunar", {"Unit": "Index"}, "24494", "2026M08", "2026M08")
    mortgage["table_id"] = "LAU04802"
    nominal = _cell("Launavísitala eftir mánuðum", {"Unit": "Index"}, "1149.3", "2026M08", "2026M08")
    nominal["table_id"] = "LAU04000"
    bare = "Hver var launavísitalan í ágúst 2026?"
    assert _measure_block(bare, {"op": "level"}, [mortgage]) == "unsupported_cell"
    assert _measure_block(bare, {"op": "level"}, [nominal]) is None


def test_two_parts_from_the_same_table_are_refused():
    from grund.compound import combine_answers
    from decimal import Decimal

    left = {"refused": False, "value": "139804", "tables": ["MAN03270.px"], "answer": "139804"}
    right = {"refused": False, "value": "138772", "tables": ["MAN03270.px"], "answer": "138772"}
    assert combine_answers("pair", left, right, Decimal(1), "is") is None
    other = {"refused": False, "value": "16501806", "tables": ["SJA01101.px"], "answer": "16501806"}
    assert combine_answers("pair", left, other, Decimal(1), "is") is not None
