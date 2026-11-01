"""Cell selection uses the table's value list, not one question's wording."""

from __future__ import annotations

from decimal import Decimal

from grund.cells import derive, operation_for, select_values


class Var:
    def __init__(self, code, text, values, time=False, elimination=False):
        self.code = code
        self.text = text
        self.values = values
        self.time = time
        self.elimination = elimination

    def label(self, code):
        for value_code, value_text in self.values:
            if value_code == code:
                return value_text
        return code

    def codes(self):
        return [code for code, _text in self.values]


class Edition:
    def __init__(self, title, variables):
        self.title = title
        self.variables = variables


def _by_code(choices):
    return {choice.variable_code: choice for choice in choices}


def test_dimension_word_does_not_select_one_municipality():
    edition = Edition(
        "Population by sex, age and municipality",
        [
            Var("Sveitarfélag", "Sveitarfélag", [("9999", "Alls"), ("8200", "Árborg")]),
            Var("Kyn", "Kyn", [("0", "Alls"), ("1", "Karlar"), ("2", "Konur")]),
            Var("Ár", "Ár", [("1981", "1981"), ("2011", "2011")], time=True),
        ],
    )
    question = "What was Census: Population by sex, age and municipality in 1981?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Sveitarfélag"].value_code == "9999"
    assert chosen["Sveitarfélag"].role == "total"
    assert chosen["Kyn"].value_code == "0"
    assert chosen["Ár"].value_code == "1981"


def test_of_which_is_not_the_total_row():
    edition = Edition(
        "Ráðstöfun úrgangs",
        [
            Var(
                "Ráðstöfun",
                "Ráðstöfun",
                [
                    ("0", "Ráðstöfun úrgangs samtals"),
                    ("1", "Endurnýting alls, þar af:"),
                ],
            ),
        ],
    )
    chosen = _by_code(select_values("Hver var ráðstöfun úrgangs árið 2013?", edition))
    assert chosen["Ráðstöfun"].value_code == "0"


def test_magnitude_is_a_difference_and_percent_is_a_percent():
    assert operation_for("Um hve mikið lækkaði olíunotkun frá 2019 til 2020?", "yoy_pct") == "difference"
    assert operation_for("By how much did the index rise from 2024 to 2025?", "yoy_pct") == "difference"
    assert operation_for("By how many points did the index rise?", "yoy_pct") == "difference"
    assert operation_for("Um hve mörg prósent hækkaði vísitalan frá 2024 til 2025?", "difference") == "yoy_pct"
    assert operation_for("By what percentage did exports increase from 2024 to 2025?", "level") == "yoy_pct"
    assert derive("difference", "44092", "44766") == Decimal("-674")
    assert derive("yoy_pct", "110", "100") == Decimal("10")
    assert derive("level", "365") == Decimal("365")


def test_index_base_year_is_not_the_data_period():
    edition = Edition(
        "CPI",
        [
            Var(
                "Mánuður",
                "Mánuður",
                [("1997M03", "1997M03"), ("2025M12", "2025M12")],
                time=True,
            ),
            Var("Liður", "Liður", [("CPI", "Vísitala, mars 1997 = 100"), ("IMP", "Innfluttar vörur")]),
        ],
    )
    question = "Hver var vísitala neysluverðs, mars 1997 = 100, innfluttar vörur í desember 2025?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Mánuður"].value_code == "2025M12"
    assert chosen["Liður"].value_code == "IMP"


def test_median_beats_a_shorter_mean_label():
    edition = Edition(
        "Age of parents",
        [Var("Eining", "Eining", [("mean", "Mean age"), ("median", "Median age"), ("mode", "Modal age")])],
    )
    question = "What was Mean-, median and modal age of parents, Median age in 2025?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Eining"].value_code == "median"


def test_annual_average_row_when_the_question_asks_for_it():
    edition = Edition(
        "Launavísitala",
        [
            Var("Eining", "Eining", [("m", "Vísitölugildi"), ("a", "Ársmeðaltal")]),
            Var("Ár", "Ár", [("2024", "2024"), ("2025", "2025")], time=True),
        ],
    )
    chosen = _by_code(select_values("Hvert var ársmeðaltal launavísitölunnar árið 2025?", edition))
    assert chosen["Eining"].role == "annual_average"
    assert chosen["Eining"].value_code == "a"
    assert chosen["Ár"].value_code == "2025"


def test_census_year_code_with_an_a_prefix():
    edition = Edition(
        "Manntal",
        [Var("Ár", "Ár", [("A1981", "1981"), ("A2011", "2011")], time=True)],
    )
    chosen = _by_code(select_values("Hver var mannfjöldinn árið 1981?", edition))
    assert chosen["Ár"].value_code == "A1981"


def test_two_named_periods_for_a_change():
    edition = Edition(
        "Olía",
        [Var("Ár", "Ár", [("2018", "2018"), ("2019", "2019"), ("2020", "2020")], time=True)],
    )
    chosen = select_values("Um hve mikið lækkaði olíunotkun frá 2019 til 2020?", edition)
    assert chosen[0].role == "time_span"
    assert chosen[0].why == "two:2019,2020"


def test_sum_of_two_published_cells():
    assert derive("sum", "10", "2.5") == Decimal("12.5")


def test_icelandic_does_not_select_the_country():
    edition = Edition(
        "Foreign citizens gaining Icelandic citizenship by country of birth, sex and age",
        [
            Var(
                "Fæðingarland",
                "Country of birth",
                [("9999", "Total"), ("99IS", "Iceland"), ("99DK", "Denmark")],
            ),
            Var("Kyn", "Sex", [("0", "Total"), ("1", "Males"), ("2", "Females")]),
        ],
    )
    question = "What was Foreign citizens gaining Icelandic citizenship by country of birth, sex and age in 2025?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Fæðingarland"].value_code == "9999"
    assert chosen["Kyn"].value_code == "0"


def test_an_unnamed_education_band_is_the_total():
    edition = Edition(
        "Live expectancy for 30 years old by educational attainment level and sex",
        [
            Var("Kyn", "Sex", [("0", "Total"), ("1", "Males"), ("2", "Females")]),
            Var(
                "Menntun",
                "Educational attainment",
                [
                    ("0", "Total"),
                    ("1", "Less than primary, primary and lower secondary education"),
                    ("3", "Tertiary education"),
                ],
            ),
        ],
    )
    question = "What was Live expectancy for 30 years old by educational attainment level and sex in 2025?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Menntun"].value_code == "0"
    assert chosen["Kyn"].value_code == "0"


def test_both_poles_of_a_split_use_the_broad_total():
    edition = Edition(
        "Consumption of renewable and non-renewable energy by economic sectors",
        [
            Var(
                "Atvinnugrein",
                "Economic sector",
                [
                    ("TOTAL", "Total for economic sectors and households"),
                    ("HH", "Total for Households"),
                    ("TOT_AZ", "Total for economic sectors"),
                    ("C", "C - Manufacturing"),
                ],
            ),
            Var(
                "Orkugjafi",
                "Energy source",
                [
                    ("TOTAL", "Total for all sources"),
                    ("OL", "Non-renewable energy source"),
                    ("REN", "Renewable energy source"),
                ],
            ),
        ],
    )
    question = "What was Consumption of renewable and non-renewable energy by economic sectors in 2024?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Orkugjafi"].value_code == "TOTAL"
    assert chosen["Atvinnugrein"].value_code == "TOTAL"


def test_housing_status_without_a_named_tenure_is_the_total():
    edition = Edition(
        "Lágtekjuhlutfall heimila eftir stöðu á húsnæðismarkaði",
        [
            Var(
                "Staða",
                "Staða á húsnæðismarkaði",
                [("0", "Alls"), ("1", "Heimili í eigin húsnæði"), ("2", "Heimili í leiguhúsnæði")],
            ),
            Var(
                "Eining",
                "Eining",
                [("0", "Hlutfall heimila (%)"), ("2", "Áætlaður fjöldi heimila")],
            ),
        ],
    )
    question = "Hver var lágtekjuhlutfall heimila eftir stöðu á húsnæðismarkaði, Áætlaður fjöldi heimila árið 2023?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Staða"].value_code == "0"
    assert chosen["Eining"].value_code == "2"


def test_former_citizenship_is_not_the_stateless_row():
    edition = Edition(
        "Veiting íslensks ríkisfangs eftir fyrra ríkisfangi",
        [
            Var(
                "Fyrra",
                "Fyrra ríkisfang",
                [("01", "Alls"), ("DK", "Danmörk"), ("XZ", "Ríkisfangslaus")],
            ),
        ],
    )
    question = "Hver var veiting íslensks ríkisfangs eftir fyrra ríkisfangi, kyni og aldri árið 2025?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Fyrra"].value_code == "01"


def test_a_published_per_person_series_is_not_divided_again():
    edition = Edition("Annual meat consumption per capita", [])
    assert operation_for("What was Annual meat consumption per capita, Beef in 2015?", "per_capita", edition) == "level"
    assert (
        operation_for(
            "By what percentage did Annual meat consumption per capita change from 2014 to 2015?",
            "per_capita",
            edition,
        )
        == "yoy_pct"
    )
    bare = Edition("Number of passenger cars", [])
    assert operation_for("How many passenger cars were there per capita in 2020?", "per_capita", bare) == "per_capita"


def test_plural_s_still_names_one_sex():
    edition = Edition(
        "Population by sex and age",
        [Var("Kyn", "Sex", [("0", "Total"), ("1", "Males"), ("2", "Females")])],
    )
    chosen = _by_code(select_values("By what percent did the female population change from 2023 to 2024?", edition))
    assert chosen["Kyn"].value_code == "2"


def test_fjoldi_og_hlutfall_is_not_a_share():
    assert operation_for("Hver var fjöldi og hlutfall starfandi fólks árið 2025?", "share") == "level"
    assert operation_for("What percentage of the population in 2024 was females?", "level") == "share"


def test_a_word_after_the_title_beats_a_longer_title_label():
    edition = Edition(
        "Meðal-, mið- og tíðasti aldur brúðhjóna eftir fyrri hjúskaparstétt",
        [
            Var(
                "Eining",
                "Eining",
                [("mean", "Meðalaldur"), ("median", "Miðaldur"), ("mode", "Tíðasti aldur")],
            ),
        ],
    )
    question = "Hver var meðal-, mið- og tíðasti aldur brúðhjóna eftir fyrri hjúskaparstétt, Miðaldur, Brúðgumar árið 2020?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Eining"].value_code == "median"


def test_both_places_named_in_the_title_use_the_total():
    edition = Edition(
        "Aðstoð við kosningu utan kjörfundar og á kjörfundi í forsetakosningum",
        [
            Var(
                "Skipting",
                "Skipting",
                [("0", "Alls"), ("1", "Utan kjörfundar"), ("2", "Á kjörfundi")],
            ),
        ],
    )
    question = "Hver var aðstoð við kosningu utan kjörfundar og á kjörfundi í forsetakosningum árið 2024?"
    chosen = _by_code(select_values(question, edition))
    assert chosen["Skipting"].value_code == "0"


def test_the_shorter_assets_word_stays_when_debts_is_also_in_the_title():
    from grund.cells import refine_selection
    from grund.parse import parse_question

    edition = Edition(
        "Tekjur, eignir og skuldir eftir bakgrunni og kyni",
        [
            Var("Fjárhagur", "Fjárhagur", [("0", "Heildartekjur"), ("1", "Eignir"), ("2", "Skuldir")]),
            Var("Ár", "Ár", [("2016", "2016"), ("2017", "2017")], time=True),
        ],
    )
    parsed = parse_question("Hver var tekjur, eignir og skuldir eftir bakgrunni og kyni, Miðgildi árið 2017?", "is")
    refined, _operation, _notes = refine_selection(
        edition, parsed, {"Fjárhagur": ["1", "2"], "Ár": ["2017"]}, "level"
    )
    assert refined["Fjárhagur"] == ["1"]


def test_a_negative_published_cell_is_an_allowed_magnitude():
    from grund.compute import allowed_numbers

    allowed = allowed_numbers([{"value": "-3785", "key": ["2024"], "labels": []}], None)
    assert 3785.0 in allowed
    assert -3785.0 in allowed


def test_the_binder_row_is_replaced_when_the_question_did_not_name_it():
    from grund.cells import refine_selection
    from grund.parse import parse_question

    edition = Edition(
        "Live expectancy for 30 years old by educational attainment level and sex",
        [
            Var("Ár", "Year", [("2024", "2024"), ("2025", "2025")], time=True),
            Var("Kyn", "Sex", [("0", "Total"), ("1", "Males")]),
            Var(
                "Menntun",
                "Educational attainment",
                [("0", "Total"), ("3", "Tertiary education")],
            ),
        ],
    )
    parsed = parse_question(
        "What was Live expectancy for 30 years old by educational attainment level and sex in 2025?",
        "en",
    )
    refined, operation, _notes = refine_selection(
        edition,
        parsed,
        {"Ár": ["2025"], "Kyn": ["1"], "Menntun": ["3"]},
        parsed.operation,
    )
    assert operation == "level"
    assert refined["Menntun"] == ["0"]
    assert refined["Kyn"] == ["0"]


def test_an_exports_subtotal_is_not_the_gdp_line():
    edition = Edition(
        "Landsframleiðsla og þjóðartekjur 1995-2025",
        [
            Var(
                "Skipting",
                "Skipting",
                [
                    ("5", "6. Útflutningur alls"),
                    ("8", "7. Frádráttur: Innflutningur alls"),
                    ("11", "8. Verg landsframleiðsla"),
                ],
            ),
            Var("Ár", "Ár", [("2024", "2024"), ("2025", "2025")], time=True),
        ],
    )
    with _with_rules("export_subtotal"):
        chosen = _by_code(select_values("Hver var landsframleiðslan árið 2025?", edition))
    assert "Skipting" not in chosen or chosen["Skipting"].value_code == "11"
    from grund.cells import refine_selection
    from grund.parse import parse_question

    parsed = parse_question("Hver var landsframleiðslan árið 2025?", "is")
    with _with_rules("export_subtotal"):
        refined, _operation, _notes = refine_selection(
            edition, parsed, {"Skipting": ["11"], "Ár": ["2025"]}, "level"
        )
    assert refined["Skipting"] == ["11"]


def _with_rules(names: str):
    import os
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        previous = os.environ.get("GRUND_CELL_RULES")
        os.environ["GRUND_CELL_RULES"] = names
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("GRUND_CELL_RULES", None)
            else:
                os.environ["GRUND_CELL_RULES"] = previous

    return _ctx()


def test_eggs_after_the_title_beats_chicks_inside_it():
    edition = Edition(
        "Hatching of poultry chicks by month from 2012",
        [Var("Egg", "Kind", [("0", "Eggs"), ("1", "Chicks")])],
    )
    question = "What was Hatching of poultry chicks by month, Eggs in August 2026?"
    with _with_rules("after_title,title_prefix"):
        chosen = _by_code(select_values(question, edition))
    assert chosen["Egg"].value_code == "0"


def test_a_range_does_not_select_the_zero_row():
    edition = Edition(
        "Deaths of enterprises",
        [Var("Aldur", "Age", [("0", "0"), ("1", "0-5 years"), ("Alls", "Alls")])],
    )
    question = "What was Deaths of enterprises, 0-5 years, Number of persons employed in 2018?"
    with _with_rules("range_number"):
        chosen = _by_code(select_values(question, edition))
    assert chosen["Aldur"].value_code == "1"


def test_sixteen_years_and_older_is_not_age_16():
    edition = Edition(
        "Population 16 years and older by sex, age and marital status",
        [Var("Aldur", "Age", [("-1", "Total"), ("16", "16 years"), ("17", "17 years")])],
    )
    question = "What was Population 16 years and older by sex, age and marital status in 2025?"
    with _with_rules("threshold_age"):
        chosen = _by_code(select_values(question, edition))
    assert chosen["Aldur"].value_code == "-1"


def test_the_headline_total_beats_one_side_named_only_in_the_title():
    edition = Edition(
        "Marriages dissolved and judicial separations",
        [
            Var(
                "Hjúskaparslit",
                "Marriages dissolved",
                [
                    ("ALL", "Marriages dissolved, total"),
                    ("DIV", "Divorces, total"),
                    ("SEP", "Judicial separations, total"),
                ],
            ),
        ],
    )
    question = "What was Marriages dissolved and judicial separations in 2020?"
    with _with_rules("title_names,qualified_name"):
        chosen = _by_code(select_values(question, edition))
    assert chosen["Hjúskaparslit"].value_code == "ALL"


def test_a_price_base_year_is_not_a_second_period():
    from grund.parse import parse_question

    with _with_rules("price_base_year"):
        parsed = parse_question(
            "By what percentage did Total expenditure, Million ISK at fixed prices of 2006 increase from 2005 to 2006?"
        )
    assert parsed.periods == [(2005, None), (2006, None)]


def test_dative_plural_komum_is_the_title_word_komur():
    from grund.scope import _forms

    assert "komur" in _forms("komum")


def test_in_iceland_keeps_the_citizenship_total():
    edition = Edition(
        "Overnight stays and arrivals in all types of registered accommodation 1998-",
        [
            Var(
                "Þjóðerni",
                "Citizenship",
                [("Total", "Total"), ("IS", "Iceland"), ("Foreigners", "Foreigners")],
            ),
        ],
    )
    with _with_rules("place_not_subgroup"):
        chosen = _by_code(select_values("How many overnight stays were there in Iceland in 2025?", edition))
    assert chosen["Þjóðerni"].value_code == "Total"
