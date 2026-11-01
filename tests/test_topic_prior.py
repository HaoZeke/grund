"""Topic prior. Off unless GRUND_TOPIC_PRIOR=1. It reorders; it does not state a figure."""

from __future__ import annotations

import os
import unittest

from grund.bind import bind
from grund.parse import parse_question
from grund.topic_prior import (
    _is_gdp,
    _is_population,
    _is_unemployment,
    _is_wage,
    _pad,
    baseline_paths_agreed,
    enabled,
    maybe_topic_prior,
    named_cells,
    region_value,
)
from grund_index.textutil import fold
from grund_index.catalogue import Hit
from grund_index.model import Edition, Table, Variable


def _var(code: str, text: str, values: list[tuple[str, str]], time: bool = False) -> Variable:
    return Variable(code=code, text=text, time=time, elimination=False, values=values)


def _edition(lang: str, title: str, db: str, path: list[str], variables: list[Variable]) -> Edition:
    return Edition(
        lang=lang,
        title=title,
        db=db,
        path=[],
        path_texts=path,
        url=f"https://px.example/{lang}/{title}",
        updated="2026-01-01",
        variables=variables,
    )


def _table(table_id: str, editions: list[Edition]) -> Table:
    table = Table(id=table_id if table_id.endswith(".px") else table_id + ".px")
    for edition in editions:
        table.editions[edition.lang] = edition
    return table


def _hit(table: Table, score: float) -> Hit:
    return Hit(table=table, score=score, bm25=score, cosine=0.0, value_boost=0.0)


class _Catalogue:
    def __init__(self, tables: list[Table]) -> None:
        self.tables = tables
        self.by_id = {table.id: table for table in tables}


def _years() -> list[tuple[str, str]]:
    return [("2026", "2026")]


def _population_catalogue() -> tuple[_Catalogue, Table, Table, Table]:
    man00000 = _table(
        "MAN00000",
        [
            _edition(
                "en",
                "Population - key figures 1703-2026",
                "Ibuar",
                ["Ibuar", "Population", "Overview"],
                [_var("Ár", "Year", _years(), time=True), _var("Eining", "Unit", [("0", "Population 1 January")])],
            ),
            _edition(
                "is",
                "Lykiltölur mannfjöldans 1703-2026",
                "Ibuar",
                ["Ibuar", "Mannfjöldi", "Yfirlit"],
                [_var("Ár", "Ár", _years(), time=True), _var("Eining", "Eining", [("0", "Mannfjöldi 1. janúar")])],
            ),
        ],
    )
    man00101 = _table(
        "MAN00101",
        [
            _edition(
                "en",
                "Population by sex and age 1841-2026",
                "Ibuar",
                ["Ibuar", "Population", "Overview"],
                [
                    _var("Kyn", "Sex", [("Total", "Total"), ("1", "Males"), ("2", "Females")]),
                    _var("Ár", "Year", _years(), time=True),
                ],
            ),
            _edition(
                "is",
                "Mannfjöldi eftir kyni og aldri 1841-2026",
                "Ibuar",
                ["Ibuar", "Mannfjöldi", "Yfirlit"],
                [
                    _var("Kyn", "Kyn", [("Total", "Alls"), ("1", "Karlar"), ("2", "Konur")]),
                    _var("Ár", "Ár", _years(), time=True),
                ],
            ),
        ],
    )
    man03250 = _table(
        "MAN03250",
        [
            _edition(
                "en",
                "Population by regions, sex and age 1 January 1998-2026",
                "Ibuar",
                ["Ibuar", "Population", "Municipalities and urban nuclei", "Other areas"],
                [
                    _var("Landshlutar", "Region", [("Total", "Total"), ("Capital region", "Capital region"), ("South", "South")]),
                    _var("Kyn", "Sex", [("0", "Total"), ("2", "Females")]),
                    _var("Ár", "Year", _years(), time=True),
                ],
            ),
            _edition(
                "is",
                "Mannfjöldi eftir landshlutum, kyni og aldri 1. janúar 1998-2026",
                "Ibuar",
                ["Ibuar", "Mannfjöldi", "Sveitarfélög og byggðarkjarnar"],
                [
                    _var("Landshlutar", "Landshlutar", [("Total", "Alls"), ("Capital region", "Höfuðborgarsvæði"), ("South", "Suðurland")]),
                    _var("Kyn", "Kyn", [("0", "Alls"), ("2", "Konur")]),
                    _var("Ár", "Ár", _years(), time=True),
                ],
            ),
        ],
    )
    man02005 = _table(
        "MAN02005",
        [
            _edition(
                "en",
                "Population by municipality, age and sex 1998-2026",
                "Ibuar",
                ["Ibuar", "Population", "Municipalities"],
                [_var("Sveitarfélag", "Municipality", [("0000", "Reykjavík"), ("9999", "Total")])],
            )
        ],
    )
    man10001 = _table(
        "MAN10001",
        [
            _edition(
                "en",
                "Population by municipality and sex, quarterly",
                "Ibuar",
                ["Ibuar", "Population", "Overview"],
                [_var("Ársfjórðungur", "Quarter", [("2026Q1", "2026Q1")], time=True)],
            )
        ],
    )
    vin = _table(
        "VIN00001",
        [
            _edition(
                "en",
                "Employment, unemployment and labour force - original data - monthly 2003-2026",
                "Samfelag",
                ["Samfelag", "Labour market", "Labour force survey"],
                [
                    _var("Mánuður", "Month", [("2026M01", "2026M01")], time=True),
                    _var("Eining", "Unit", [("0", "Estimated population (16-74 years)")]),
                ],
            ),
            _edition(
                "is",
                "Vinnuafl, starfandi, atvinnulausir og vinnustundir - mánaðarlegar tölur",
                "Samfelag",
                ["Samfelag", "Vinnumarkaður", "Vinnumarkaðsrannsókn"],
                [_var("Eining", "Eining", [("0", "Mannfjöldi")])],
            ),
        ],
    )
    thj_current = _table(
        "THJ01102",
        [
            _edition(
                "en",
                "Gross domestic product and Gross national income 1995-2025",
                "Efnahagur",
                ["Efnahagur", "National accounts", "Gross domestic product"],
                [_var("Ár", "Year", [("2025", "2025")], time=True)],
            ),
            _edition(
                "is",
                "Landsframleiðsla og þjóðartekjur 1995-2025",
                "Efnahagur",
                ["Efnahagur", "Þjóðhagsreikningar", "Landsframleiðsla"],
                [_var("Ár", "Ár", [("2025", "2025")], time=True)],
            ),
        ],
    )
    thj_constant = _table(
        "THJ01103",
        [
            _edition(
                "en",
                "Gross domestic product and Gross national income at constant prices 1980-2025",
                "Efnahagur",
                ["Efnahagur", "National accounts", "Gross domestic product"],
                [_var("Ár", "Year", [("2025", "2025")], time=True)],
            ),
            _edition(
                "is",
                "Landsframleiðsla og þjóðartekjur á föstu verðlagi 1980-2025",
                "Efnahagur",
                ["Efnahagur", "Þjóðhagsreikningar", "Landsframleiðsla"],
                [_var("Ár", "Ár", [("2025", "2025")], time=True)],
            ),
        ],
    )
    catalogue = _Catalogue([man00000, man00101, man03250, man02005, man10001, vin, thj_current, thj_constant])
    return catalogue, vin, man03250, man00000


class TopicPriorTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["GRUND_TOPIC_PRIOR"] = "1"

    def tearDown(self) -> None:
        os.environ.pop("GRUND_TOPIC_PRIOR", None)

    def test_an_unmatched_question_is_not_reordered(self) -> None:
        catalogue, vin, regions, _key = _population_catalogue()
        hits = [_hit(vin, 4.0), _hit(regions, 1.0)]
        question = "Hvaða lög eru efst á Spotify á Íslandi í dag?"
        self.assertIs(maybe_topic_prior(catalogue, question, hits), hits)

    def test_flag_off_returns_the_same_list(self) -> None:
        os.environ.pop("GRUND_TOPIC_PRIOR", None)
        self.assertFalse(enabled())
        catalogue, vin, regions, _key = _population_catalogue()
        hits = [_hit(vin, 4.0), _hit(regions, 1.0)]
        self.assertIs(maybe_topic_prior(catalogue, "How many people lived in the capital region?", hits), hits)

    def test_capital_region_prefers_the_population_table(self) -> None:
        catalogue, vin, regions, _key = _population_catalogue()
        ranked = maybe_topic_prior(
            catalogue,
            "How many people lived in the capital region on 1 January 2026?",
            [_hit(vin, 4.0), _hit(regions, 1.0)],
        )
        self.assertEqual(ranked[0].table.id, "MAN03250.px")
        self.assertGreater(ranked[0].score, ranked[1].score)
        self.assertNotIn("value", ranked[0].__dict__)

    def test_icelandic_capital_region_uses_the_dimension_label(self) -> None:
        catalogue, vin, regions, _key = _population_catalogue()
        ranked = maybe_topic_prior(
            catalogue,
            "Hve margir bjuggu á höfuðborgarsvæðinu 1. janúar 2026?",
            [_hit(vin, 3.0)],
        )
        self.assertEqual(ranked[0].table.id, "MAN03250.px")
        self.assertEqual(ranked[1].table.id, "VIN00001.px")

    def test_national_population_keeps_a_same_subject_table(self) -> None:
        catalogue, vin, _regions, key = _population_catalogue()
        sex = catalogue.by_id["MAN00101.px"]
        hits = [_hit(sex, 4.0), _hit(key, 2.0), _hit(vin, 3.5)]
        ranked = maybe_topic_prior(catalogue, "How many people lived in Iceland on 1 January 2026?", hits)
        self.assertIs(ranked, hits)

    def test_quarterly_leader_yields_to_the_key_figures_on_1_january(self) -> None:
        catalogue, _vin, _regions, key = _population_catalogue()
        quarterly = catalogue.by_id["MAN10001.px"]
        ranked = maybe_topic_prior(
            catalogue,
            "How many people lived in Iceland on 1 January 2026?",
            [_hit(quarterly, 4.0), _hit(key, 1.0)],
        )
        self.assertEqual(ranked[0].table.id, "MAN00101.px")

    def test_a_town_in_the_dative_is_not_the_national_total(self) -> None:
        catalogue, _vin, _regions, key = _population_catalogue()
        sex = catalogue.by_id["MAN00101.px"]
        hits = [_hit(sex, 3.0), _hit(key, 1.0)]
        ranked = maybe_topic_prior(catalogue, "Hversu margir bjuggu í Árborgu árið 2024?", hits)
        self.assertIs(ranked, hits)

    def test_reykjavik_is_not_the_national_total(self) -> None:
        catalogue, _vin, _regions, key = _population_catalogue()
        town = catalogue.by_id["MAN02005.px"]
        hits = [_hit(town, 4.0), _hit(key, 1.0)]
        ranked = maybe_topic_prior(catalogue, "How many people lived in Reykjavík on 1 January 2026?", hits)
        self.assertIs(ranked, hits)

    def test_women_count_leaves_a_table_that_publishes_the_sex(self) -> None:
        catalogue, _vin, regions, _key = _population_catalogue()
        hits = [_hit(regions, 4.0)]
        ranked = maybe_topic_prior(catalogue, "What percentage of the population were women?", hits)
        self.assertIs(ranked, hits)

    def test_population_lookalike_keeps_the_sex_table_already_in_the_list(self) -> None:
        catalogue, vin, _regions, key = _population_catalogue()
        sex = catalogue.by_id["MAN00101.px"]
        ranked = maybe_topic_prior(
            catalogue,
            "Hversu margir bjuggu á Íslandi árið 2014?",
            [_hit(vin, 4.0), _hit(sex, 2.0), _hit(key, 1.0)],
        )
        self.assertEqual(ranked[0].table.id, "MAN00101.px")

    def test_women_count_moves_off_the_labour_table(self) -> None:
        catalogue, vin, _regions, _key = _population_catalogue()
        ranked = maybe_topic_prior(catalogue, "How many women lived in Iceland on 1 January 2026?", [_hit(vin, 4.0)])
        self.assertEqual(ranked[0].table.id, "MAN00101.px")

    def test_current_price_gdp_beats_the_constant_price_table(self) -> None:
        catalogue, _vin, _regions, _key = _population_catalogue()
        current = catalogue.by_id["THJ01102.px"]
        constant = catalogue.by_id["THJ01103.px"]
        ranked = maybe_topic_prior(
            catalogue,
            "Hver var verg landsframleiðsla á Íslandi árið 2025?",
            [_hit(constant, 4.0), _hit(current, 1.0)],
        )
        self.assertEqual(ranked[0].table.id, "THJ01102.px")

    def test_constant_prices_keep_the_constant_table(self) -> None:
        catalogue, _vin, _regions, _key = _population_catalogue()
        current = catalogue.by_id["THJ01102.px"]
        constant = catalogue.by_id["THJ01103.px"]
        hits = [_hit(constant, 4.0), _hit(current, 1.0)]
        ranked = maybe_topic_prior(catalogue, "Hver var landsframleiðsla á föstu verðlagi 2025?", hits)
        self.assertIs(ranked, hits)

    def test_a_quoted_labour_title_is_not_the_unemployment_rate(self) -> None:
        catalogue, vin, _regions, _key = _population_catalogue()
        question = (
            "What was Employment, unemployment and labour force - Orginal Data - Monthly, "
            "Employed in September 2026?"
        )
        hits = [_hit(vin, 4.0)]
        self.assertIs(maybe_topic_prior(catalogue, question, hits), hits)

    def test_headline_phrases_stay_narrow(self) -> None:
        def padded(text: str) -> str:
            return _pad(fold(text))

        self.assertFalse(_is_wage(padded("What was Wage indices by sector in 2024?")))
        self.assertTrue(_is_wage(padded("What was the wage index in August 2026?")))
        self.assertTrue(_is_wage(padded("Hver var launavísitalan í ágúst 2026?")))
        self.assertFalse(_is_gdp(padded("Percentage of gross domestic product, total expenditure")))
        self.assertFalse(_is_gdp(padded("R&Þ útgjöld sem hlutfall af landsframleiðslu")))
        self.assertTrue(_is_gdp(padded("Hver var verg landsframleiðsla á Íslandi árið 2025?")))
        self.assertFalse(_is_population(padded("Population by status and year, 25-54 in 2025")))
        self.assertFalse(_is_population(padded("Hver var mannfjöldi eftir þéttbýlisstöðum árið 2019?")))
        self.assertTrue(_is_population(padded("How many people lived in Iceland on 1 January 2026?")))
        self.assertFalse(
            _is_unemployment(padded("Employment, unemployment and labour force - original data, Employed"))
        )
        self.assertTrue(_is_unemployment(padded("What was the unemployment rate in Iceland?")))

    def test_lookalike_with_no_overlap_moves_behind_the_subject(self) -> None:
        catalogue, vin, regions, _key = _population_catalogue()
        ranked = maybe_topic_prior(
            catalogue,
            "Hve margir bjuggu á Íslandi 1. janúar 2026?",
            [_hit(vin, 4.0), _hit(regions, 1.0)],
        )
        self.assertEqual(ranked[0].table.id, "MAN00101.px")
        self.assertIn("VIN00001.px", {hit.table.id for hit in ranked})


class BaselineAgreementTests(unittest.TestCase):
    def test_same_figure_on_both_paths_is_kept(self) -> None:
        agreed = {
            "refused": False,
            "value": "394324",
            "path_pair": {
                "left": {"refused": False, "value": "394324"},
                "right": {"refused": False, "value": "394324"},
            },
        }
        self.assertTrue(baseline_paths_agreed(agreed))

    def test_a_refusal_or_one_path_is_not_agreement(self) -> None:
        self.assertFalse(baseline_paths_agreed({"refused": True, "path_pair": {}}))
        self.assertFalse(
            baseline_paths_agreed(
                {
                    "refused": False,
                    "value": "199622",
                    "path_pair": {
                        "left": {"refused": False, "value": "199622"},
                        "right": {"refused": True, "value": None},
                    },
                }
            )
        )


class NamedRegionTests(unittest.TestCase):
    def test_the_capital_region_is_not_the_all_regions_total(self) -> None:
        _catalogue, _vin, regions, _key = _population_catalogue()
        icelandic = regions.edition("is")
        english = regions.edition("en")
        os.environ["GRUND_TOPIC_PRIOR"] = "1"
        try:
            self.assertEqual(
                region_value(icelandic, "Hve margir bjuggu á höfuðborgarsvæðinu 1. janúar 2026?"),
                ("Landshlutar", "Capital region"),
            )
            self.assertEqual(
                region_value(english, "How many people lived in the capital region on 1 January 2026?"),
                ("Landshlutar", "Capital region"),
            )
            self.assertEqual(
                region_value(icelandic, "Hve margir bjuggu á Suðurlandi 1. janúar 2026?"),
                ("Landshlutar", "South"),
            )
            self.assertIsNone(
                region_value(english, "How many people lived in the Northeast on 1 January 2026?")
            )
            self.assertIsNone(
                region_value(english, "How many people lived in the capital on 1 January 2026?")
            )
        finally:
            os.environ.pop("GRUND_TOPIC_PRIOR", None)
        self.assertIsNone(
            region_value(icelandic, "Hve margir bjuggu á höfuðborgarsvæðinu 1. janúar 2026?")
        )

    def test_a_municipality_group_does_not_keep_the_region_slot(self) -> None:
        catalogue, vin, regions, _key = _population_catalogue()
        group = _table(
            "MAN10001",
            [
                _edition(
                    "en",
                    "Population by municipality and sex, quarterly",
                    "Ibuar",
                    ["Ibuar", "Population"],
                    [_var("Sveitarfélag", "Municipality", [("IS001", "Capital region"), ("IS002", "Outside capital region")])],
                )
            ],
        )
        catalogue.tables.append(group)
        os.environ["GRUND_TOPIC_PRIOR"] = "1"
        try:
            ranked = maybe_topic_prior(
                catalogue,
                "How many people lived in the capital region on 1 January 2026?",
                [_hit(group, 9.0), _hit(vin, 4.0)],
            )
            self.assertEqual(ranked[0].table.id, "MAN03250.px")
        finally:
            os.environ.pop("GRUND_TOPIC_PRIOR", None)

    def test_the_binder_keeps_the_capital_region(self) -> None:
        _catalogue, _vin, regions, _key = _population_catalogue()
        question = "Hve margir bjuggu á höfuðborgarsvæðinu 1. janúar 2026?"
        os.environ["GRUND_TOPIC_PRIOR"] = "1"
        try:
            binding = bind(regions.edition("is"), parse_question(question, "is"))
            self.assertIsNotNone(binding)
            selected = {entry["code"]: entry["selection"]["values"] for entry in binding.selections}
            self.assertEqual(selected.get("Landshlutar"), ["Capital region"])
            self.assertEqual(
                named_cells(regions.edition("is"), question),
                [("Landshlutar", "Capital region")],
            )
            men = "Hve margir karlar bjuggu á höfuðborgarsvæðinu 1. janúar 2026?"
            sexed = regions.edition("is")
            # The shared fixture has no male row. A catalogue that publishes one
            # has to keep that row, not the sex total, once the region is named.
            male = _edition(
                "is",
                sexed.title,
                "Ibuar",
                ["Ibuar"],
                [
                    _var("Landshlutar", "Landshlutar", [("Total", "Alls"), ("Capital region", "Höfuðborgarsvæði")]),
                    _var("Kyn", "Kyn", [("0", "Alls"), ("1", "Karlar"), ("2", "Konur")]),
                    _var("Ár", "Ár", _years(), time=True),
                ],
            )
            self.assertEqual(
                named_cells(male, men),
                [("Landshlutar", "Capital region"), ("Kyn", "1")],
            )
            bound = bind(male, parse_question(men, "is"))
            self.assertIsNotNone(bound)
            picked = {entry["code"]: entry["selection"]["values"] for entry in bound.selections}
            self.assertEqual(picked.get("Landshlutar"), ["Capital region"])
            self.assertEqual(picked.get("Kyn"), ["1"])
            country = bind(
                regions.edition("is"),
                parse_question("Hve margir bjuggu á Íslandi 1. janúar 2026?", "is"),
            )
            if country is not None:
                national = {entry["code"]: entry["selection"]["values"] for entry in country.selections}
                self.assertEqual(national.get("Landshlutar"), ["Total"])
        finally:
            os.environ.pop("GRUND_TOPIC_PRIOR", None)


if __name__ == "__main__":
    unittest.main()
