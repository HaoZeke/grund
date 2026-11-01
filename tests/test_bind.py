from grund.bind import bind
from grund.parse import parse_question
from grund.validator import validate
from grund_index.model import Edition, Table, Variable


def cpi() -> Edition:
    return Edition(
        lang="en",
        title="Consumer price index and changes, base 1988=100",
        db="Efnahagur",
        path=["Efnahagur", "visitolur", "1_vnv", "1_vnv"],
        path_texts=["Economy", "Prices", "Consumer price index"],
        url="https://px.hagstofa.is/pxen/api/v1/en/Efnahagur/visitolur/1_vnv/1_vnv/VIS01000.px",
        updated="2026-09-01",
        variables=[
            Variable(
                "Month",
                "Month",
                True,
                False,
                [("2024M06", "2024M06"), ("2025M06", "2025M06"), ("2023M06", "2023M06")],
            ),
            Variable(
                "Index",
                "Index",
                False,
                False,
                [("CPI", "Consumer price index"), ("CPILH", "Consumer price index less housing cost")],
            ),
            Variable(
                "Item",
                "Item",
                False,
                False,
                [
                    ("index", "Index"),
                    ("change_M", "Monthly change, %"),
                    ("change_A", "Annual change, %"),
                ],
            ),
        ],
    )


def population() -> Edition:
    return Edition(
        lang="en",
        title="Population by sex and age 1841-2026",
        db="Ibuar",
        path=["Ibuar", "mannfjoldi"],
        path_texts=["Population"],
        url="https://example.test/MAN00101.px",
        updated=None,
        variables=[
            Variable("Kyn", "Sex", False, False, [("Total", "Total"), ("1", "Males"), ("2", "Females")]),
            Variable("Aldur", "Age", False, False, [("-1", "Total"), ("0", "Under 1 year"), ("54", "54 years")]),
            Variable("Ár", "Year", True, False, [(str(year), str(year)) for year in range(2020, 2026)]),
        ],
    )


def values(binding, code):
    for entry in binding.selections:
        if entry["code"] == code:
            return entry["selection"]["values"]
    return None


def test_cpi_level_selects_the_index_not_the_housing_variant():
    parsed = parse_question("What was the consumer price index in June 2024?")
    binding = bind(cpi(), parsed)
    assert binding is not None
    assert values(binding, "Month") == ["2024M06"]
    assert values(binding, "Index") == ["CPI"]
    assert values(binding, "Item") == ["index"]
    validate(cpi(), binding.selections)


def test_official_annual_change_is_not_recomputed():
    parsed = parse_question("What was the annual change in the consumer price index in June 2025?")
    binding = bind(cpi(), parsed)
    assert binding is not None
    assert binding.official_measure
    assert binding.operation == "level"
    assert values(binding, "Item") == ["change_A"]
    assert values(binding, "Month") == ["2025M06"]


def test_over_the_year_uses_the_published_annual_change():
    parsed = parse_question("By what percent did the consumer price index rise over the year to June 2025?")
    binding = bind(cpi(), parsed)
    assert binding is not None
    assert binding.official_measure
    assert values(binding, "Item") == ["change_A"]


def test_share_fetches_the_part_and_the_total():
    parsed = parse_question("What percentage of the population by sex and age in 2024 was females?")
    binding = bind(population(), parsed)
    assert binding is not None
    assert binding.operation == "share"
    assert binding.part_code == "2"
    assert binding.whole_code == "Total"
    assert values(binding, "Aldur") == ["-1"]
    assert values(binding, "Ár") == ["2024"]
    validate(population(), binding.selections)


def test_yoy_on_a_level_table_asks_for_both_years():
    parsed = parse_question("By what percent did the female population by sex and age change from 2023 to 2024?")
    binding = bind(population(), parsed)
    assert binding is not None
    assert binding.operation == "yoy_pct"
    assert values(binding, "Ár") == ["2023", "2024"]
    assert values(binding, "Kyn") == ["2"]


def test_alls_is_the_icelandic_total():
    from grund.bind import is_total

    assert is_total("Alls")
    assert is_total("Total")
    assert is_total("Allt landið")
    assert not is_total("Austurland")
    assert not is_total("Konur")


def test_december_in_a_yearly_title_does_not_block_the_years():
    edition = Edition(
        lang="en",
        title="Disability allowance beneficiaries by financers, residence, gender and age in December",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society"],
        url="https://example.test/FEL02005.px",
        updated=None,
        variables=[
            Variable("Ár", "Year", True, False, [("2021", "2021"), ("2022", "2022")]),
            Variable("Kyn", "Sex", False, False, [("0", "Total"), ("1", "Males")]),
        ],
    )
    parsed = parse_question(
        "By what percentage did Disability allowance beneficiaries by financers, residence, gender and age in December increase from 2021 to 2022?"
    )
    binding = bind(edition, parsed)
    assert binding is not None
    assert binding.operation == "yoy_pct"
    assert values(binding, "Ár") == ["2021", "2022"]


def test_the_month_just_after_the_crawled_list_can_be_requested():
    from grund.bind import acceptable_time_value

    edition = Edition(
        lang="en",
        title="Employment, unemployment and labour force",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society"],
        url="https://example.test/VIN00002.px",
        updated=None,
        variables=[
            Variable("Mánuður", "Month", True, False, [("2026M07", "2026M07"), ("2026M08", "2026M08")]),
            Variable("Eining", "Unit", False, False, [("0", "Total"), ("2", "Employed")]),
        ],
    )
    parsed = parse_question("What was Employment, unemployment and labour force, Employed in September 2026?")
    binding = bind(edition, parsed)
    assert binding is not None
    assert values(binding, "Mánuður") == ["2026M09"]
    assert acceptable_time_value(edition.variable("Mánuður"), "2026M09")
    validate(edition, binding.selections)


def test_a_long_codelist_uses_its_first_total_line():
    labels = [("0", "Erlendar eignir, alls")] + [(str(i), f"Line {i}") for i in range(1, 30)]
    edition = Edition(
        lang="is",
        title="Reikningar bankakerfisins",
        db="Efnahagur",
        path=["Efnahagur"],
        path_texts=["Economy"],
        url="https://example.test/PEN01104.px",
        updated=None,
        variables=[
            Variable("Ár", "Ár", True, False, [("2016", "2016")]),
            Variable("Skipting", "Skipting", False, False, labels),
        ],
    )
    parsed = parse_question("Hver var reikningar bankakerfisins árið 2016?", "is")
    binding = bind(edition, parsed)
    assert binding is not None
    assert values(binding, "Skipting") == ["0"]


def test_fjoldi_og_hlutfall_stays_a_level_binding():
    edition = Edition(
        lang="is",
        title="Fjöldi og hlutfall starfandi fólks eftir árum",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society"],
        url="https://example.test/VIN00931.px",
        updated=None,
        variables=[
            Variable("Ár", "Ár", True, False, [("2024", "2024"), ("2025", "2025")]),
            Variable("Eining", "Eining", False, False, [("0", "Alls"), ("1", "Við vinnu í viðmiðunarviku")]),
        ],
    )
    parsed = parse_question(
        "Hver var fjöldi og hlutfall starfandi fólks eftir árum, 25-54 ára, Við vinnu í viðmiðunarviku árið 2025?",
        "is",
    )
    binding = bind(edition, parsed)
    assert binding is not None
    assert binding.operation == "level"
    assert values(binding, "Eining") == ["1"]


def test_a_year_outside_the_series_does_not_bind():
    parsed = parse_question("What was the consumer price index in June 2099?")
    assert bind(cpi(), parsed) is None


def test_search_prefers_the_table_whose_title_matches():
    from grund_index.catalogue import Catalogue
    from grund_index.embed import Embedder
    from grund_index.model import Table

    price = Table(id="VIS01000.px", editions={"en": cpi()})
    people = Table(id="MAN00101.px", editions={"en": population()})
    catalogue = Catalogue([people, price], Embedder(kind="chargram"), None, "none")
    hits = catalogue.search("consumer price index June 2024", years=[2024])
    assert hits[0].table.id == "VIS01000.px"


def test_a_one_word_title_does_not_beat_the_specific_table():
    from grund_index.catalogue import Catalogue
    from grund_index.embed import Embedder
    from grund_index.model import Table

    generic = Edition(
        lang="en",
        title="Population",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society"],
        url="https://example.test/HEI11501.px",
        updated=None,
        variables=population().variables,
    )
    lifelong = Edition(
        lang="en",
        title="Participation in lifelong learning by sex, age, labour force status and type of learning",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society", "Labour"],
        url="https://example.test/VIN01207.px",
        updated=None,
        variables=population().variables,
    )
    people = Table(id="MAN00101.px", editions={"en": population()})
    catalogue = Catalogue(
        [
            Table(id="HEI11501.px", editions={"en": generic}),
            Table(id="VIN01207.px", editions={"en": lifelong}),
            people,
        ],
        Embedder(kind="chargram"),
        None,
        "none",
    )
    hits = catalogue.search(
        "What percentage of the population by sex and age in 2024 was females?",
        years=[2024],
    )
    assert hits[0].table.id == "MAN00101.px"


def test_internal_moves_beat_a_municipality_table_and_a_population_table():
    from grund_index.catalogue import Catalogue
    from grund_index.embed import Embedder

    def edition(title: str, url: str) -> Edition:
        return Edition(
            lang="en",
            title=title,
            db="Ibuar",
            path=["Ibuar"],
            path_texts=["Population"],
            url=url,
            updated=None,
            variables=[],
        )

    catalogue = Catalogue(
        [
            Table(id="MAN00000.px", editions={"en": edition("Population - key figures 1703-2026", "https://example.test/MAN00000.px")}),
            Table(id="MAN01201.px", editions={"en": edition("Migration by municipality and sex 1986-2025", "https://example.test/MAN01201.px")}),
            Table(id="MAN01102.px", editions={"en": edition("Internal migration by sex and age 1986-2025", "https://example.test/MAN01102.px")}),
        ],
        Embedder(kind="chargram"),
        None,
        "none",
    )
    hits = catalogue.search("How many people moved within Iceland in 2024?", years=[2024])
    assert hits[0].table.id == "MAN01102.px"


def test_cpi_annual_average_beats_the_wage_index():
    from grund_index.catalogue import Catalogue
    from grund_index.embed import Embedder

    def edition(title: str, url: str) -> Edition:
        return Edition(
            lang="en",
            title=title,
            db="Efnahagur",
            path=["Efnahagur"],
            path_texts=["Economy"],
            url=url,
            updated=None,
            variables=[],
        )

    catalogue = Catalogue(
        [
            Table(id="LAU04200.px", editions={"en": edition("Wage index, annual averages from 1989", "https://example.test/LAU04200.px")}),
            Table(id="VIS01000.px", editions={"en": edition("Consumer price index and changes, base 1988=100", "https://example.test/VIS01000.px")}),
            Table(id="VIS01005.px", editions={"en": edition("CPI, annual averages", "https://example.test/VIS01005.px")}),
        ],
        Embedder(kind="chargram"),
        None,
        "none",
    )
    hits = catalogue.search(
        "Rebase the consumer price index annual average so that 2020=100. What was the value in 2024?",
        years=[2024],
    )
    assert hits[0].table.id == "VIS01005.px"


def _vessels() -> Edition:
    return Edition(
        lang="en",
        title="Icelandic fishing vessels by region and vessel type 1999-2024",
        db="Atvinnuvegir",
        path=["Atvinnuvegir"],
        path_texts=["Industries"],
        url="https://example.test/SJA05001.px",
        updated=None,
        variables=[
            Variable("Skipagerð", "Type of vessel", False, False, [
                ("0", "All fishing vessels"),
                ("1", "Trawlers"),
                ("2", "Decked fishing vessels"),
            ]),
            Variable("Landsvæði", "Region", False, False, [
                ("0", "Whole Iceland"),
                ("1", "Capitol region"),
            ]),
            Variable("Ár", "Year", True, False, [("2022", "2022")]),
            Variable("Eining", "Unit", False, False, [("0", "Number of fishing vessels")]),
        ],
    )


def test_and_inside_a_title_does_not_select_a_second_vessel_type():
    parsed = parse_question(
        "What percentage of Icelandic fishing vessels by region and vessel type was Capitol region in 2022?"
    )
    binding = bind(_vessels(), parsed)
    assert binding is not None
    assert values(binding, "Skipagerð") == ["0"]
    assert values(binding, "Landsvæði") == ["1", "0"]


def test_a_share_does_not_select_the_percentage_unit():
    edition = Edition(
        lang="en",
        title="Museum employees 1995-2020",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Society"],
        url="https://example.test/MEN07005.px",
        updated=None,
        variables=[
            Variable("Ár", "Year", True, False, [("2019", "2019")]),
            Variable("Skráning", "Accreditation", False, False, [
                ("0", "Total"),
                ("1", "Accredited and principal museums"),
                ("2", "Other museums"),
            ]),
            Variable("Eining", "Unit", False, False, [
                ("0", "Number of employees"),
                ("1", "Percentage"),
                ("2", "Number of museums"),
            ]),
        ],
    )
    parsed = parse_question("What percentage of Museum employees was Accredited and principal museums in 2019?")
    binding = bind(edition, parsed)
    assert binding is not None
    assert values(binding, "Eining") == ["0"]
    assert values(binding, "Skráning") == ["1", "0"]


def test_two_month_phrases_keep_the_year_that_follows_each_month():
    parsed = parse_question(
        "By how many points did the consumer price index rise from September 2025 to September 2026?"
    )
    assert parsed.operation == "difference"
    assert parsed.periods == [(2025, 9), (2026, 9)]


def test_a_named_quarter_is_not_a_bare_year():
    parsed = parse_question("What was the unemployment rate in Iceland in the second quarter of 2026?")
    assert parsed.quarter == (2026, 2)
    assert parsed.periods == [(2026, None)]
    icelandic = parse_question("Hvert var atvinnuleysi á Íslandi á öðrum ársfjórðungi 2026?")
    assert icelandic.quarter == (2026, 2)


def test_a_january_census_date_uses_the_year_on_a_yearly_table():
    from grund.bind import _select_time
    from grund_index.model import Variable

    parsed = parse_question("How many people lived in Iceland on 1 January 2026?")
    assert parsed.periods == [(2026, 1)]
    variable = Variable("Ár", "Year", True, False, [("2025", "2025"), ("2026", "2026")])
    assert _select_time(variable, parsed, "level") == ["2026"]


def test_a_month_inside_a_title_does_not_pair_with_a_distant_year():
    buried = parse_question(
        "What percentage of Percent of old age pension beneficiaries by type of payment, financers, residence, gender and age in December was Old age pension beneficiaries with residence in Iceland in 2020?"
    )
    assert buried.periods == [(2020, None)]
    named = parse_question("What was the consumer price index in June 2024?")
    assert named.periods == [(2024, 6)]
    bimonthly = parse_question("In 2005, what was January-February for Turnover by industry?")
    assert (2005, 1) in bimonthly.periods
    assert (2005, 2) in bimonthly.periods


def test_a_title_figure_is_not_copied_into_the_measure_phrase():
    from grund.answer import measure_phrase

    edition = Edition(
        lang="en",
        title="Live expectancy for 30 years old by educational attainment level and sex",
        db="Ibuar",
        path=["Ibuar"],
        path_texts=["Population"],
        url="https://example.test/MAN05405.px",
        updated=None,
        variables=[
            Variable("Ár", "Year", True, False, [("2023", "2023")]),
            Variable("Kyn", "Sex", False, False, [("0", "Total"), ("1", "Males")]),
            Variable("Menntun", "Educational attainment", False, False, [("0", "Total")]),
        ],
    )
    parsed = parse_question(
        "What percentage of Live expectancy for 30 years old by educational attainment level and sex was Males in 2023?"
    )
    binding = bind(edition, parsed)
    assert binding is not None
    phrase = measure_phrase(binding, edition, "en")
    assert "30" not in phrase
    assert "Males" in phrase


def test_an_unnamed_variable_uses_the_first_total_not_a_shorter_component():
    edition = Edition(
        lang="en",
        title="Marriages dissolved and judicial separations 1951-2020",
        db="Ibuar",
        path=["Ibuar"],
        path_texts=["Population"],
        url="https://example.test/MAN06201.px",
        updated=None,
        variables=[
            Variable("Year", "Year", True, False, [("2020", "2020"), ("2019", "2019")]),
            Variable(
                "Kind",
                "Dissolution",
                False,
                False,
                [
                    ("ALL", "Marriages dissolved, total"),
                    ("DIV", "Divorces, total"),
                    ("SEP", "Judicial separations, total"),
                ],
            ),
        ],
    )
    binding = bind(edition, parse_question("What was Marriages dissolved and judicial separations in 2020?"))
    assert binding is not None
    kind = next(entry for entry in binding.selections if entry["code"] == "Kind")
    assert kind["selection"]["values"] == ["ALL"]


def test_a_unit_named_after_the_title_beats_the_title_word():
    edition = Edition(
        lang="en",
        title="Employment, unemployment and labour force - Trend - Monthly",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Labour market"],
        url="https://example.test/VIN00003.px",
        updated=None,
        variables=[
            Variable(
                "Month",
                "Month",
                True,
                False,
                [("2025M09", "September 2025"), ("2026M09", "September 2026")],
            ),
            Variable("Age", "Sex and age", False, False, [("0", "Total"), ("1", "Males")]),
            Variable(
                "Unit",
                "Unit",
                False,
                False,
                [("1", "Labour force"), ("4", "Employed"), ("3", "Unemployed")],
            ),
        ],
    )
    question = (
        "By how much did Employment, unemployment and labour force - Trend - Monthly, "
        "Employed fall from September 2025 to September 2026?"
    )
    binding = bind(edition, parse_question(question))
    assert binding is not None
    assert binding.operation == "difference"
    unit = next(entry for entry in binding.selections if entry["code"] == "Unit")
    assert unit["selection"]["values"] == ["4"]


def test_all_editions_is_the_total_when_book_only_repeats_the_title():
    edition = Edition(
        lang="en",
        title="Book publishing, number of volumes 1965-2000",
        db="Samfelag",
        path=["Samfelag"],
        path_texts=["Culture"],
        url="https://example.test/MEN01101.px",
        updated=None,
        variables=[
            Variable("Year", "Year", True, False, [("2000", "2000")]),
            Variable("Unit", "Unit", False, False, [("1", "Number"), ("2", "Percentage")]),
            Variable(
                "Division",
                "Division",
                False,
                False,
                [("total", "All editions"), ("1", "Books"), ("2", "Booklets")],
            ),
        ],
    )
    binding = bind(edition, parse_question("What was Book publishing, number of volumes in 2000?"))
    assert binding is not None
    division = next(entry for entry in binding.selections if entry["code"] == "Division")
    assert division["selection"]["values"] == ["total"]
