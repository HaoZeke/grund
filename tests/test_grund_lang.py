"""Language layer and value binding. Retrieval against gold tables is separate."""

from __future__ import annotations

import pytest

from grund_lang.compound import split_compound
from grund_lang.dates import find_bases, parse_dates
from grund_lang.fold import fold
from grund_lang.lemma import analyze, lemmatize_token
from grund_lang.numbers import parse_numbers
from grund_lang.values import bind_values


def _choice(choices, code):
    found = [choice for choice in choices if choice.variable_code == code]
    return found


class Var:
    def __init__(self, code, text, time, values):
        self.code = code
        self.text = text
        self.time = time
        self.values = values
        self.elimination = False


class Edition:
    def __init__(self, title, variables, lang="en"):
        self.title = title
        self.variables = variables
        self.lang = lang


def test_fold_strips_icelandic_diacritics():
    assert fold("Þjóðhátíð") == "thjodhatid"
    assert fold("Ísland") == fold("Island") == "island"
    assert fold("árslok") == "arslok"


def test_numbers_follow_icelandic_grouping():
    spans = parse_numbers("Árslok 2025 voru 13,2 prósent og 1.234 manns.", "is")
    by_raw = {span.raw: span for span in spans}
    assert by_raw["13,2"].value == pytest.approx(13.2)
    assert by_raw["13,2"].kind == "percent"
    assert by_raw["1.234"].value == pytest.approx(1234)
    english = parse_numbers("The figure was 1,234.5 percent.", "en")
    assert english[0].value == pytest.approx(1234.5)
    assert english[0].kind == "percent"


def test_year_end_quarter_and_between_years():
    end = parse_dates("Íbúar við árslok 2025")
    assert any(span.kind == "year_end" and span.year == 2025 for span in end)
    quarter = parse_dates("Hve mörg börn fæddust á fjórða ársfjórðungi 2025?")
    assert any(span.kind == "quarter" and span.quarter == 4 and span.year == 2025 for span in quarter)
    bare = parse_dates("Hver var breytingin milli ára?")
    assert any(span.kind == "between_years" and span.year is None for span in bare)
    ranged = parse_dates("Breyting milli áranna 2024 og 2025")
    assert any(span.kind == "between_years" and span.year == 2024 and span.end_year == 2025 for span in ranged)
    english = parse_dates("How many children were born in the fourth quarter of 2025?")
    assert any(span.kind == "quarter" and span.quarter == 4 and span.year == 2025 for span in english)
    point = parse_dates("Hve margir bjuggu á Íslandi 1. janúar 2026?")
    assert any(span.kind == "point" and span.year == 2026 and span.month == 1 and span.day == 1 for span in point)
    average = parse_dates("What was the annual average in 2024?")
    assert any(span.kind == "annual_average" for span in average)
    assert find_bases("vísitala, grunnur 1988=100") == [1988]
    # The base year is not also reported as the data year.
    dated = parse_dates("Consumer price index, base 1988=100, in September 2026")
    assert 1988 not in {span.year for span in dated if span.kind == "year"}
    assert any(span.kind == "month" and span.year == 2026 and span.month == 9 for span in dated)


def test_lemmatize_and_pos_when_the_database_is_installed():
    pytest.importorskip("islenska")
    lemma, _surface, pos, source = lemmatize_token("ársfjórðungi", "is")
    assert lemma == fold("ársfjórðungur")
    assert pos == "noun"
    assert source == "bin"
    lemma, _surface, pos, source = lemmatize_token("innflytjendum", "is")
    assert lemma == fold("innflytjandi")
    assert pos == "noun"
    lemma, _surface, pos, _source = lemmatize_token("bjuggu", "is")
    assert lemma == fold("búa")
    assert pos == "verb"
    lemma, _surface, pos, _source = lemmatize_token("konur", "is")
    assert lemma == fold("kona")
    pytest.importorskip("reynir")
    parsed = analyze("Hve margir bjuggu á Íslandi á fjórða ársfjórðungi?")
    by_surface = {token.surface: token for token in parsed.tokens}
    assert by_surface["bjuggu"].pos == "verb"
    assert by_surface["bjuggu"].lemma == fold("búa")
    assert "population" in parsed.concepts


def test_compound_parts_when_the_database_is_installed():
    pytest.importorskip("islenska")
    parts = split_compound("neysluverð")
    assert fold("neysla") in parts
    assert fold("verð") in parts
    parts = split_compound("heildarlosun")
    assert fold("heild") in parts or fold("heildar") in parts
    assert fold("losun") in parts


def test_concept_bridge_adds_the_other_language():
    parsed = analyze("Hve margir bjuggu í Reykjavík?")
    assert "population" in parsed.concepts
    assert "population" in parsed.terms
    english = analyze("How many women lived in Iceland?")
    assert "sex_female" in english.concepts
    assert "female" in english.terms or "females" in english.terms


def _people():
    return Edition(
        "Population by sex and age",
        [
            Var("Kyn", "Sex", False, [("0", "Total"), ("1", "Males"), ("2", "Females")]),
            Var("Aldur", "Age", False, [("-1", "Total"), ("0", "Under 1 year"), ("5", "5 years")]),
            Var("Ár", "Year", True, [("2024", "2024"), ("2025", "2025"), ("2026", "2026")]),
        ],
    )


def _citizens():
    return Edition(
        "Population by citizenship",
        [
            Var(
                "Ríkisfang",
                "Citizenship",
                False,
                [("0", "Total"), ("1", "Icelandic citizens"), ("2", "Foreign citizens")],
            ),
            Var("Ár", "Year", True, [("2024", "2024"), ("2025", "2025")]),
        ],
    )


def test_a_quoted_label_is_kept_when_the_title_shares_its_words():
    edition = Edition(
        "R&D expenditures as percentage of GDP 2013-2024",
        [
            Var("Niðurstöður", "Results", False, [("0", "Million ISK"), ("1", "Percentage of total"), ("2", "Percentage of GDP")]),
            Var("Ár", "Year", True, [("2024", "2024")]),
        ],
    )
    choices = bind_values(
        "What was R&D expenditures as percentage of GDP, Percentage of total in 2024?",
        edition,
    )
    assert _choice(choices, "Niðurstöður")[0].value_label == "Percentage of total"


def test_title_words_do_not_select_a_subgroup():
    edition = Edition(
        "Dissolution of consensual unions and number of dependent children 1991-2011",
        [
            Var("Fjöldi barna", "Number of children", False, [("0", "Total"), ("1", "Without children")]),
            Var("Ár", "Year", True, [("2010", "2010"), ("2011", "2011")]),
        ],
    )
    choices = bind_values(
        "By what percentage did Dissolution of consensual unions and number of dependent children increase from 2010 to 2011?",
        edition,
    )
    assert _choice(choices, "Fjöldi barna")[0].value_label == "Total"


def test_total_versus_subgroup():
    women = bind_values("How many women lived in Iceland in 2026?", _people())
    assert _choice(women, "Kyn")[0].value_label == "Females"
    assert _choice(women, "Aldur")[0].value_label == "Total"
    assert _choice(women, "Ár")[0].value_code == "2026"
    everyone = bind_values("How many people lived in Iceland in 2026?", _people())
    assert _choice(everyone, "Kyn")[0].value_label == "Total"
    assert _choice(everyone, "Aldur")[0].value_label == "Total"


def test_citizens_versus_all():
    everyone = bind_values("How many people lived in Iceland in 2024?", _citizens())
    assert _choice(everyone, "Ríkisfang")[0].value_label == "Total"
    icelandic = bind_values("How many Icelandic citizens lived in Iceland in 2024?", _citizens())
    assert _choice(icelandic, "Ríkisfang")[0].value_label == "Icelandic citizens"
    foreign = bind_values("Hve margir erlendir ríkisborgarar bjuggu á Íslandi árið 2024?", _citizens())
    assert _choice(foreign, "Ríkisfang")[0].value_label == "Foreign citizens"


def test_internal_versus_international_migration():
    internal = Edition(
        "Internal migration by sex and age",
        [
            Var(
                "Flutningssvæði",
                "Migration region",
                False,
                [
                    ("0", "Total"),
                    ("1", "Within municipality"),
                    ("2", "Within region"),
                    ("3", "Between regions"),
                ],
            )
        ],
    )
    external = Edition(
        "External migration by sex and citizenship",
        [
            Var(
                "Tegund flutnings",
                "Type of migration",
                False,
                [("1", "Net immigration"), ("2", "Immigration"), ("3", "Emigration")],
            )
        ],
    )
    within = bind_values("How many people moved within the municipality?", internal)
    assert _choice(within, "Flutningssvæði")[0].value_label == "Within municipality"
    between = bind_values("Internal migration between regions", internal)
    assert _choice(between, "Flutningssvæði")[0].value_label == "Between regions"
    arrived = bind_values("How many people immigrated to Iceland?", external)
    assert _choice(arrived, "Tegund flutnings")[0].value_label == "Immigration"
    left = bind_values("How many people emigrated from Iceland?", external)
    assert _choice(left, "Tegund flutnings")[0].value_label == "Emigration"


def test_quarter_annual_average_and_index_base():
    quarters = Edition(
        "Births by quarter",
        [Var("Ársfjórðungur", "Quarter", True, [("2025Q3", "2025Q3"), ("2025Q4", "2025Q4"), ("2026Q1", "2026Q1")])],
    )
    born = bind_values("Hve mörg börn fæddust á fjórða ársfjórðungi 2025?", quarters)
    assert _choice(born, "Ársfjórðungur")[0].value_code == "2025Q4"
    wages = Edition(
        "Wage index",
        [
            Var("Mánuður", "Month", True, [("2025M09", "2025M09"), ("0", "Annual average")]),
            Var("Ár", "Year", True, [("2024", "2024"), ("2025", "2025")]),
        ],
    )
    average = bind_values("What was the annual average of the wage index in 2025?", wages)
    assert _choice(average, "Mánuður")[0].value_label == "Annual average"
    assert _choice(average, "Ár")[0].value_code == "2025"
    prices = Edition(
        "Consumer price index, annual averages, base 1988=100",
        [
            Var("Grunnur", "Base", False, [("B1988", "Base 1988"), ("B1997", "Base 1997"), ("B2008", "Base 2008")]),
            Var("Liður", "Item", False, [("index", "Index"), ("change_A", "Annual change, %")]),
        ],
    )
    level = bind_values("What was the consumer price index on base 1988=100?", prices)
    assert _choice(level, "Grunnur")[0].value_code == "B1988"
    assert _choice(level, "Liður")[0].value_code == "index"
    change = bind_values("What was the annual change in the consumer price index?", prices)
    assert _choice(change, "Liður")[0].value_label == "Annual change, %"
    ranged = bind_values(
        "How many children were born from the fourth quarter of 2025 to the first quarter of 2026?",
        quarters,
    )
    codes = {choice.value_code for choice in _choice(ranged, "Ársfjórðungur")}
    assert codes == {"2025Q4", "2026Q1"}


def test_retrieval_prefers_the_table_whose_labels_match():
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table, Variable

    def edition(title, variables):
        return RealEdition(
            lang="en",
            title=title,
            db="Ibuar",
            path=["Ibuar"],
            path_texts=["Population"],
            url="https://example.test/x",
            updated=None,
            variables=variables,
        )

    people = Table(id="POP00001.px")
    people.editions["en"] = edition(
        "Population by municipality and sex",
        [
            Variable("Sex", "Sex", False, False, [("0", "Total"), ("1", "Males"), ("2", "Females")]),
            Variable("Muni", "Municipality", False, False, [("0000", "Reykjavíkurborg"), ("1000", "Kópavogur")]),
            Variable("Year", "Year", True, False, [("2024", "2024"), ("2026", "2026")]),
        ],
    )
    fish = Table(id="FISH0001.px")
    fish.editions["en"] = edition(
        "Fish catch by species",
        [Variable("Species", "Species", False, False, [("0", "Total"), ("1", "Cod"), ("2", "Haddock")])],
    )
    from grund_lang.index import build_index

    index = build_index([people, fish], embed="chargram")
    ranked = index.search("How many women lived in Reykjavík in 2024?", k=2)
    assert ranked[0].table_id == "POP00001"
    labels = {choice.variable_code: choice.value_label for choice in ranked[0].bindings}
    assert labels["Sex"] == "Females"
    assert "Reykjav" in labels["Muni"]


def test_label_digits_and_a_negative_cell_pass_the_number_check():
    """01-02-04 is metadata. 999 is not a fetched cell, so it still blocks."""
    from grund.answer import render
    from grund.bind import Binding
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Variable
    from grund_rails.grounding import NumberGroundingRail

    from grund_lang.driver import sentence_allowed

    edition = RealEdition(
        lang="en",
        title="Income statement for other cattle farms in regions 2008-2024",
        db="Atvinnuvegir",
        path=["Atvinnuvegir"],
        path_texts=["Industries"],
        url="https://example.test/x",
        updated=None,
        variables=[
            Variable("Landsvæði", "Region", False, False, [("0", "Total")]),
            Variable("Reikningsliður", "Account heading", False, False, [("6", "01-02-04 Depreciation")]),
            Variable("Ár", "Year", True, False, [("2024", "2024")]),
        ],
    )
    binding = Binding(
        edition=edition,
        selections=[
            {"code": "Landsvæði", "selection": {"filter": "item", "values": ["0"]}},
            {"code": "Reikningsliður", "selection": {"filter": "item", "values": ["6"]}},
            {"code": "Ár", "selection": {"filter": "item", "values": ["2024"]}},
        ],
        operation="level",
        score=1,
        time_var="Ár",
        time_codes=["2024"],
        notes=["row used: 01-02-04 Depreciation"],
    )
    rows = [
        {
            "value": "-276",
            "key": ["0", "6", "2024"],
            "map": {"Landsvæði": "0", "Reikningsliður": "6", "Ár": "2024"},
            "labels": [
                {"variable": "Landsvæði", "variable_text": "Region", "code": "0", "label": "Total"},
                {"variable": "Reikningsliður", "variable_text": "Account heading", "code": "6", "label": "01-02-04 Depreciation"},
                {"variable": "Ár", "variable_text": "Year", "code": "2024", "label": "2024"},
            ],
        }
    ]
    prose = render("en", edition, binding, rows, "-276", None, False)
    assert "01-02-04" in prose
    allowed = sentence_allowed(rows, None)
    rail = NumberGroundingRail()
    assert rail.decide(prose, {"language": "en", "allowed": allowed}).passed_ok()
    # The cell allow-list alone used to reject this sentence: the finder
    # reads 276, and 1, 2, 4 come from the label rather than the cell.
    bare = rail.decide(prose, {"language": "en", "allowed": [-276.0]})
    assert bare.blocked_turn()
    invented = prose.replace(".", " and 999.")
    blocked = rail.decide(invented, {"language": "en", "allowed": allowed})
    assert blocked.blocked_turn()
    assert "999" in (blocked.reason or "")


def test_label_digits_are_not_added_to_the_allow_list():
    from grund_lang.grounding import extend_allowed

    rows = [{"value": "10", "key": ["1.2.3"], "labels": [{"code": "1.2.3", "label": "Group 1.2.3"}]}]
    assert extend_allowed([10.0], rows) == [10.0]


def test_retrieve_pair_returns_one_table_for_each_half():
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table, Variable

    from grund_lang.index import build_index
    from grund_lang.pair import retrieve_pair

    def edition(title, variables):
        return RealEdition(
            lang="en",
            title=title,
            db="Ibuar",
            path=["Ibuar"],
            path_texts=["Population"],
            url="https://example.test/x",
            updated=None,
            variables=variables,
        )

    people = Table(id="POP00001.px")
    people.editions["en"] = edition(
        "Population by municipality and sex",
        [
            Variable("Sex", "Sex", False, False, [("0", "Total"), ("1", "Males"), ("2", "Females")]),
            Variable("Muni", "Municipality", False, False, [("0000", "Reykjavíkurborg")]),
            Variable("Year", "Year", True, False, [("2024", "2024")]),
        ],
    )
    fish = Table(id="FISH0001.px")
    fish.editions["en"] = edition(
        "Fish catch of cod by species",
        [Variable("Species", "Species", False, False, [("0", "Total"), ("1", "Cod")])],
    )
    index = build_index([people, fish], embed="chargram")
    question = "How many women lived in Reykjavík in 2024 and how many tonnes of cod were landed in 2024?"
    pair = retrieve_pair(index, question, k=5)
    assert [item.table_id for item in pair] == ["POP00001", "FISH0001"]


def test_saved_bm25_reloads_without_rebuilding_postings(tmp_path):
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table, Variable

    from grund_lang.index import build_index, load_index, save_index

    def edition(title, variables):
        return RealEdition(
            lang="en",
            title=title,
            db="Ibuar",
            path=["Ibuar"],
            path_texts=["Population"],
            url="https://example.test/x",
            updated=None,
            variables=variables,
        )

    people = Table(id="POP00001.px")
    people.editions["en"] = edition(
        "Population by municipality and sex",
        [Variable("Sex", "Sex", False, False, [("0", "Total"), ("2", "Females")])],
    )
    out = tmp_path / "index"
    index = build_index([people], embed="chargram")
    save_index(index, out, tmp_path, catalogue=None, metadata=None)
    assert (out / "bm25.json.gz").exists()
    # No catalogue in the manifest: load falls back to tables, which are absent.
    # The postings file is readable on its own.
    from grund_lang.index import load_bm25

    stored = load_bm25(out / "bm25.json.gz", 1)
    assert stored is not None
    assert stored[0][0]


def test_iceland_is_the_place_people_live_not_a_birth_country():
    birth = Edition(
        "Population by country of birth, sex and age",
        [
            Var("Fæðingarland", "Country of birth", False, [("9999", "Total"), ("99IS", "Iceland"), ("99IS2", "Ísland")]),
            Var("Aldur", "Age", False, [("1", "Total"), ("6", "20-24 years")]),
            Var("Kyn", "Sex", False, [("0", "Total"), ("1", "Males")]),
            Var("Ár", "Year", True, [("2026", "2026"), ("2024", "2024")]),
        ],
    )
    total = bind_values("How many people lived in Iceland on 1 January 2026?", birth)
    assert _choice(total, "Fæðingarland")[0].value_code == "9999"
    assert _choice(total, "Aldur")[0].value_label == "Total"
    born = bind_values("How many people born in Iceland lived there in 2026?", birth)
    assert _choice(born, "Fæðingarland")[0].value_code == "99IS"
    icelandic = Edition(
        "Mannfjöldi eftir fæðingarlandi",
        [
            Var("Fæðingarland", "Fæðingarland", False, [("9999", "Alls"), ("99IS", "Ísland")]),
            Var("Ár", "Ár", True, [("2026", "2026")]),
        ],
    )
    native = bind_values("Hve margir bjuggu á Íslandi 1. janúar 2026?", icelandic)
    assert _choice(native, "Fæðingarland")[0].value_code == "9999"


def test_recent_years_and_the_capital_region():
    recent = parse_dates("Hve margir bjuggu á höfuðborgarsvæðinu á síðustu fimm árum?")
    assert any(span.kind == "recent_years" and span.count == 5 for span in recent)
    english = parse_dates("How many people lived there over the last five years?")
    assert any(span.kind == "recent_years" and span.count == 5 for span in english)
    region = Edition(
        "Population by region",
        [
            Var("Landsvæði", "Region", False, [("0", "Alls"), ("1", "Höfuðborgarsvæðið"), ("2", "Landsbyggð")]),
            Var("Ár", "Year", True, [(str(year), str(year)) for year in range(2018, 2026)]),
        ],
    )
    choices = bind_values("Hve margir bjuggu á höfuðborgarsvæðinu síðustu fimm ár?", region)
    assert _choice(choices, "Landsvæði")[0].value_label == "Höfuðborgarsvæðið"
    years = {choice.value_code for choice in _choice(choices, "Ár")}
    assert years == {"2021", "2022", "2023", "2024", "2025"}


def test_continuing_series_beats_a_discontinued_copy():
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table

    from grund_lang.index import _series_adjustment, _title_covered

    def table(title, path_texts):
        made = Table(id="X.px")
        made.editions["en"] = RealEdition(
            "en", title, "Samfelag", ["Samfelag"], path_texts, "https://example.test", None, []
        )
        return made

    discontinued = table("Wage changes by quarter 2000-2006", ["Wages", "Earlier tables"])
    continuing = table("Wage indices by month from 2015", ["Wages", "Monthly figures"])
    question = "What was the wage index?"
    old = _series_adjustment(question, discontinued, set(), set())
    current = _series_adjustment(question, continuing, set(), set())
    assert old[0] < current[0]
    heading = table("Population", ["Population"])
    specific = table("Population by municipality age and sex 1997-2022", ["Population"])
    assert _title_covered("How many people lived in Reykjavík?", heading) is False
    assert _title_covered("Population by municipality age and sex in Reykjavík", specific) is True


def test_rerank_prefers_the_current_series_and_skips_an_unasked_breakdown():
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table, Variable

    from grund_lang.index import _rerank
    from grund_lang.lemma import analyze
    from grund_lang.types import Candidate

    def table(table_id, title, path_texts, variables=()):
        made = Table(id=table_id)
        made.editions["en"] = RealEdition(
            "en", title, "Ibuar", ["Ibuar"], path_texts, "https://example.test", None, list(variables)
        )
        return made

    current = table("MEN.px", "Theatre performances and spectators 1930-2020", ["Culture", "Theatre"])
    historical = table("SOG.px", "Theatre performances and spectators 1930-2020", ["Sogulegar", "Culture"])
    question = "Theatre performances and spectators"
    analysis = analyze(question)
    ranked = _rerank(
        question,
        [Candidate("SOG", 0.9, 0, 0, []), Candidate("MEN", 0.8, 0, 0, [])],
        analysis,
        {"SOG": historical, "MEN": current},
    )
    assert [item.table_id for item in ranked] == ["MEN", "SOG"]
    overview = table("POP.px", "Population - key figures 1703-2026", ["Population", "Overview"])
    birth = table(
        "BIRTH.px",
        "Population by country of birth, sex and age",
        ["Population", "Country of birth"],
        [Variable("Birth", "Country of birth", False, False, [("9999", "Total"), ("IS", "Iceland")])],
    )
    asked = "How many people lived in Iceland on 1 January 2026?"
    analysis = analyze(asked)
    ranked = _rerank(
        asked,
        [Candidate("BIRTH", 0.9, 0, 0, []), Candidate("POP", 0.8, 0, 0, [])],
        analysis,
        {"BIRTH": birth, "POP": overview},
    )
    assert ranked[0].table_id == "POP"


def test_choose_pair_keeps_both_tables_inside_the_top_pool():
    from grund_lang.pair import choose_pair
    from grund_lang.types import Candidate

    def candidate(table_id):
        return Candidate(table_id=table_id, score=1.0, bm25=0.0, cosine=0.0, bindings=[])

    joint = [candidate("A"), candidate("B"), candidate("C")]
    # A is the best left hit and also the best right hit. The other half is B.
    left = [candidate("A"), candidate("B"), candidate("C")]
    right = [candidate("A"), candidate("B"), candidate("C")]
    # Give B the best right rank by listing it first on the right.
    right = [candidate("B"), candidate("A"), candidate("C")]
    chosen = [item.table_id for item in choose_pair(joint, left, right)]
    assert chosen == ["A", "B"]


def test_children_are_not_births_and_a_death_verb_is_deaths():
    children = analyze("Hve mörg börn voru í leikskóla?")
    assert "births" not in children.concepts
    deaths = analyze("Hve margir létust á landinu?")
    assert "deaths" in deaths.concepts
    pupils = analyze("Hve margir nemendur voru í grunnskóla?")
    assert "population" not in pupils.concepts
    still = analyze("Hve margir bjuggu á Íslandi?")
    assert "population" in still.concepts


def test_cod_catch_splits_as_cod_and_catch():
    pytest.importorskip("islenska")
    parts = split_compound("þorskafli")
    assert fold("þorskur") in parts
    assert fold("afli") in parts or "afl" in parts


def test_a_subject_folder_is_not_an_unasked_breakdown():
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Table, Variable

    from grund_lang.index import _series_adjustment, _unasked_breakdown

    made = Table(id="CIT.px")
    made.editions["en"] = RealEdition(
        "en",
        "Foreign citizens 1950-2026",
        "Ibuar",
        ["Ibuar", "mannfjoldi", "bakgrunnur"],
        ["Population", "Background", "Citizenship"],
        "https://example.test",
        None,
        [Variable("Ár", "Year", True, False, [("2018", "2018")])],
    )
    question = "How many foreign citizens were counted in Iceland in 2018?"
    analysis = analyze(question)
    assert _unasked_breakdown(question, analysis, made) is False
    municipality = Table(id="MUN.px")
    municipality.editions["en"] = RealEdition(
        "en",
        "Population by municipality, age and sex 1998-2026",
        "Ibuar",
        ["Ibuar"],
        ["Population", "Municipalities"],
        "https://example.test",
        None,
        [Variable("Sveitarfélag", "Municipality", False, False, [("6000", "Akureyrarbær"), ("3000", "Akraneskaupstaður")])],
    )
    asked = "How many inhabitants did Akranes have in 2019?"
    placed = _series_adjustment(asked, municipality, {2019}, set(), analyze(asked))
    assert placed[1] >= 0.06
    other = "How many inhabitants did the country have in 2019?"
    plain = _series_adjustment(other, municipality, {2019}, set(), analyze(other))
    assert plain[1] < placed[1]


def test_a_ratio_uses_the_named_part_and_the_total():
    from grund.parse import parse_question
    from grund_index.model import Edition as RealEdition
    from grund_index.model import Variable

    from grund_lang.driver import binding_from_values, resolve_operation

    men = parse_question("What proportion of the population were men in 2019?")
    assert resolve_operation(men) == "share"
    rate = parse_question("What was the unemployment rate in the first quarter of 2019?")
    assert resolve_operation(rate) == "level"
    change = parse_question("By what percentage did the wage index rise from 2018 to 2019?")
    assert resolve_operation(change) != "share"
    pasted = parse_question("What was Percentage of enterprises with a website in 2019?")
    assert resolve_operation(pasted) == "level"

    population = RealEdition(
        "en",
        "Population by sex and age",
        "Ibuar",
        ["Ibuar"],
        ["Population", "Overview"],
        "https://example.test",
        None,
        [
            Variable("Kyn", "Sex", False, False, [("Total", "Total"), ("1", "Males"), ("2", "Females")]),
            Variable("Aldur", "Age", False, False, [("-1", "Total")]),
            Variable("Ár", "Year", True, False, [("2019", "2019")]),
        ],
    )
    binding = binding_from_values(population, men)
    assert binding is not None
    assert binding.operation == "share"
    assert binding.group_var == "Kyn"
    assert binding.part_code == "1"
    assert binding.whole_code == "Total"
    assert any("share_percent" in note for note in binding.notes)
    assert any("do not supply a number" in note for note in binding.notes)

    stays = RealEdition(
        "en",
        "Overnight stays and arrivals in all types of registered accommodation",
        "Atvinnuvegir",
        ["Atvinnuvegir"],
        ["Tourism"],
        "https://example.test",
        None,
        [
            Variable(
                "Þjóðerni",
                "Citizenship",
                False,
                False,
                [("Total", "Total"), ("IS", "Iceland"), ("Foreigners", "Foreigners")],
            ),
            Variable("Ár", "Year", True, False, [("2019", "2019")]),
            Variable("Eining", "Unit", False, False, [("0", "Overnight stays"), ("1", "Arrivals")]),
            Variable("Mánuður", "Month", False, False, [("0", "Total"), ("7", "July")]),
        ],
    )
    foreign = parse_question("What percentage of overnight stays in 2019 were by foreigners?")
    stay_binding = binding_from_values(stays, foreign)
    assert stay_binding is not None
    assert stay_binding.operation == "share"
    assert stay_binding.part_code == "Foreigners"
    assert stay_binding.whole_code == "Total"
    assert stay_binding.group_var == "Þjóðerni"

    pupils = RealEdition(
        "is",
        "Nemendur í grunnskólum eftir kyni",
        "Samfelag",
        ["Samfelag"],
        ["Menntun"],
        "https://example.test",
        None,
        [
            Variable("Kyn", "Kyn", False, False, [("0", "Alls"), ("1", "Drengir"), ("2", "Stúlkur")]),
            Variable("Ár", "Ár", True, False, [("2019", "2019")]),
        ],
    )
    girls = parse_question("Hve stórt hlutfall nemenda í grunnskóla árið 2019 voru stúlkur?")
    girl_binding = binding_from_values(pupils, girls)
    assert girl_binding is not None
    assert girl_binding.part_code == "2"
    assert girl_binding.whole_code == "0"


def test_an_untitled_row_falls_back_to_the_total_and_the_latest_period():
    edition = Edition(
        "Marriages dissolved and judicial separations",
        [
            Var(
                "Kind",
                "Kind",
                False,
                [("1", "Judicial separations"), ("0", "Marriages dissolved, total")],
            ),
            Var("Year", "Year", True, [("2020", "2020"), ("2024", "2024")]),
        ],
    )
    choices = bind_values("What was Marriages dissolved and judicial separations?", edition)
    kind = _choice(choices, "Kind")
    assert kind and kind[0].value_code == "0"
    year = _choice(choices, "Year")
    assert year and year[0].value_code == "2024"


def test_a_change_claim_names_the_period_and_a_loose_total_maps():
    from grund_lang.pxtools import _claim_from_payload, map_request

    edition = {
        "variables": [
            {
                "code": "Atvinnugrein",
                "text": "Economic activity",
                "time": False,
                "elimination": False,
                "values": [("T", "Total - all activites"), ("A", "Agriculture")],
            },
            {
                "code": "Year",
                "text": "Year",
                "time": False,
                "elimination": False,
                "values": [("2018", "2018"), ("2020", "2020")],
            },
        ]
    }
    request = {
        "measure": "activity",
        "filters": {},
        "period": {"kind": "range", "start": {"year": 2018}, "end": {"year": 2020}},
        "op": "change",
        "unit_hint": "",
    }
    mapped = map_request(edition, request)
    assert mapped == {"Atvinnugrein": ["T"], "Year": ["2018", "2020"]}
    payload = {
        "columns": [
            {"code": "Atvinnugrein", "type": "d"},
            {"code": "Year", "type": "t"},
            {"code": "value", "type": "c"},
        ],
        "data": [
            {"key": ["T", "2018"], "values": ["10"]},
            {"key": ["T", "2020"], "values": ["14"]},
        ],
    }
    claim = _claim_from_payload("JVS00001", edition, mapped, payload, request)
    assert claim["value"] == "4"
    assert [cell["period"] for cell in claim["cells"]] == ["2018", "2020"]
    assert claim["period"] == "2018 to 2020"
    assert claim["cells"][0]["labels"] == {"Economic activity": "Total - all activites"}
    debt = {
        "variables": [
            {
                "code": "Skipting",
                "text": "Division",
                "time": False,
                "elimination": False,
                "values": [("1", "Long-term foreign debt, total"), ("2", "Central Bank")],
            },
            {
                "code": "Ár",
                "text": "Year",
                "time": True,
                "elimination": False,
                "values": [("2016", "2016")],
            },
        ]
    }
    point = dict(request)
    point["period"] = {"kind": "point", "year": 2016}
    point["op"] = "level"
    assert map_request(debt, point)["Skipting"] == ["1"]
    accounts = {
        "variables": [
            {
                "code": "Reikningsliður",
                "text": "Account heading",
                "time": False,
                "elimination": False,
                "values": [(str(i), f"0{i} Total revenue" if i == 1 else f"line {i}") for i in range(18)],
            }
        ]
    }
    assert map_request(accounts, point) is None
    from grund_rails.cell_claim import check_claim

    assert check_claim(
        "By how much did economic activity rise from 2018 to 2020?",
        claim,
        claim["cells"],
    ) is None


def test_bin_compound_list_splits_a_rate_and_overnight_stays():
    pytest.importorskip("islenska")
    rate = split_compound("atvinnuleysishlutfall")
    assert fold("atvinnuleysi") in rate
    assert fold("hlutfall") in rate
    nights = split_compound("gistinætur")
    assert fold("nótt") in nights
    assert "aetur" not in nights
    assert split_compound("vísitala") == ()
    assert split_compound("Akureyri") == ()


def test_label_glosses_rewrite_a_colloquial_word_and_keep_the_longer_phrase():
    from types import SimpleNamespace

    from grund_lang.rewrite import extra_lemmas, install, mine

    def edition(title, code, labels):
        return SimpleNamespace(
            title=title,
            path_texts=[],
            variables=[SimpleNamespace(code=code, text=code, values=labels)],
        )

    tables = []
    for index in range(3):
        tables.append(
            SimpleNamespace(
                editions={
                    "en": edition(
                        f"Residency {index}",
                        "res",
                        [("0", "Capital (Reykjavík)"), ("1", "Capital region"), ("2", "Eswatini (Swaziland)")],
                    ),
                    "is": edition(
                        f"Buseta {index}",
                        "res",
                        [("0", "Höfuðborg"), ("1", "Höfuðborgarsvæði"), ("2", "Eswatini")],
                    ),
                }
            )
        )
    found, blocks = mine(tables)
    install(found, blocks)
    try:
        assert fold("Reykjavík") in found[fold("capital")]
        assert fold("Reykjavík") in found[fold("Höfuðborg")]
        assert fold("Swaziland") in extra_lemmas([fold("Eswatini")])
        assert fold("Reykjavík") in extra_lemmas([fold("capital")])
        assert fold("Reykjavík") not in extra_lemmas([fold("capital"), fold("region")])
        assert fold("Reykjavík") not in extra_lemmas([fold("höfuðborgarsvæði")])
    finally:
        install({}, {})


def test_a_bare_index_is_the_price_index_and_the_wage_index_is_not():
    bare = analyze("Hvað var vísitalan í desember?")
    assert "cpi" in bare.concepts
    assert fold("neysluverð") in bare.terms
    wages = analyze("Hver var launavísitalan?")
    assert "cpi" not in wages.concepts
    priced = analyze("Hvað var verðlagið í desember?")
    assert "cpi" in priced.concepts
