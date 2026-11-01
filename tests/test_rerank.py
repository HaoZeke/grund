"""Look-alike reranking. Catalogue search uses it unless GRUND_RERANK=0."""

from __future__ import annotations

import os
import unittest

from grund.rerank import lookalike_rerank, maybe_rerank, rerank_enabled, same_series, search_k
from grund.rerank import _fact
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
        url=f"https://px.example/{lang}",
        updated="2024-01-01",
        variables=variables,
    )


def _table(table_id: str, editions: list[Edition]) -> Table:
    table = Table(id=table_id if table_id.endswith(".px") else table_id + ".px")
    for edition in editions:
        table.editions[edition.lang] = edition
    return table


def _years(start: int, end: int) -> list[tuple[str, str]]:
    return [(str(year), str(year)) for year in range(start, end + 1)]


def _hit(table: Table, score: float) -> Hit:
    return Hit(table=table, score=score, bm25=score, cosine=0.0, value_boost=0.0)


class RerankTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("GRUND_RERANK", None)

    def test_flag_off_keeps_width_and_order(self) -> None:
        os.environ["GRUND_RERANK"] = "0"
        self.assertFalse(rerank_enabled())
        self.assertEqual(search_k(), 12)
        current, older = self._marriage_pair()
        hits = [_hit(older, 3.0), _hit(current, 2.2)]
        self.assertIs(maybe_rerank(None, "Hver var hjónavígslur árið 2020?", hits, [2020]), hits)

    def test_default_reorders_the_catalogue_shortlist(self) -> None:
        os.environ.pop("GRUND_RERANK", None)
        self.assertTrue(rerank_enabled())
        self.assertEqual(search_k(), 20)
        current, older = self._marriage_pair()
        ranked = maybe_rerank(None, "Hver var hjónavígslur árið 2020?", [_hit(older, 3.0), _hit(current, 2.2)], [2020])
        self.assertEqual(ranked[0].table.id, current.id)

    def test_historical_copy_loses_when_the_year_is_shared(self) -> None:
        current, older = self._marriage_pair()
        ranked = lookalike_rerank(
            "Hver var hjónavígslur árið 2020?",
            [_hit(older, 3.0), _hit(current, 2.2)],
            years=[2020],
        )
        self.assertEqual(ranked[0].table.id, current.id)
        self.assertGreater(ranked[0].score, ranked[1].score)
        self.assertTrue(same_series(_fact(current), _fact(older)))

    def test_historical_copy_kept_for_a_year_the_current_series_lacks(self) -> None:
        current, older = self._marriage_pair()
        ranked = lookalike_rerank(
            "Hver var hjónavígslur árið 1800?",
            [_hit(current, 3.0), _hit(older, 2.2)],
            years=[1800],
        )
        self.assertEqual(ranked[0].table.id, older.id)

    def test_percent_question_prefers_the_percent_table(self) -> None:
        percent, counts = self._pension_pair()
        ranked = lookalike_rerank(
            "What was Percent of old age pension beneficiaries by type of payment in 2022?",
            [_hit(counts, 3.0), _hit(percent, 2.6)],
            years=[2022],
        )
        self.assertEqual(ranked[0].table.id, percent.id)

    def test_percentage_distribution_is_not_demoted(self) -> None:
        """The question already says hlutfallsleg. The percent series stays first."""
        percent = _table(
            "VIN01104",
            [
                _edition(
                    "is",
                    "Vinnumarkaðurinn eftir kyni og menntun 1991-2025, hlutfallsleg skipting",
                    "Samfelag",
                    ["Vinnumarkaður"],
                    [_var("Ár", "Ár", _years(1991, 2025), time=True)],
                ),
                _edition(
                    "en",
                    "Labour market by sex and education 1991-2025, percentage distribution",
                    "Samfelag",
                    ["Labour market"],
                    [_var("Year", "Year", _years(1991, 2025), time=True)],
                ),
            ],
        )
        plain = _table(
            "VIN01205",
            [
                _edition(
                    "is",
                    "Vinnumarkaðurinn eftir kyni og menntun 1991-2020",
                    "Samfelag",
                    ["Vinnumarkaður"],
                    [_var("Ár", "Ár", _years(1991, 2020), time=True)],
                )
            ],
        )
        ranked = lookalike_rerank(
            "Hver var vinnumarkaðurinn eftir kyni og menntun, hlutfallsleg skipting árið 2025?",
            [_hit(percent, 2.8), _hit(plain, 2.5)],
            years=[2025],
        )
        self.assertEqual(ranked[0].table.id, percent.id)

    def test_base_year_keeps_the_series_that_publishes_it(self) -> None:
        earlier = _table(
            "VIS01102",
            [
                _edition(
                    "en",
                    "CPI by expenditure groups from 1997-2025",
                    "Efnahagur",
                    ["Prices"],
                    [_var("Year", "Year", _years(1997, 2025), time=True)],
                )
            ],
        )
        current = _table(
            "VIS01101",
            [
                _edition(
                    "en",
                    "CPI by expenditure groups",
                    "Efnahagur",
                    ["Prices"],
                    [_var("Year", "Year", _years(2024, 2026), time=True)],
                )
            ],
        )
        ranked = lookalike_rerank(
            "What was CPI by expenditure groups, Index, March 1997=100 in December 2025?",
            [_hit(current, 3.1), _hit(earlier, 2.4)],
            years=[2025],
        )
        self.assertEqual(ranked[0].table.id, earlier.id)

    def _marriage_pair(self) -> tuple[Table, Table]:
        current = _table(
            "MAN06100",
            [
                _edition(
                    "is",
                    "Hjónavígslur 1951-2020",
                    "Ibuar",
                    ["Fjölskyldan"],
                    [_var("Ár", "Ár", _years(1951, 2020), time=True)],
                ),
                _edition(
                    "en",
                    "Marriages 1951-2020",
                    "Ibuar",
                    ["Family"],
                    [_var("Year", "Year", _years(1951, 2020), time=True)],
                ),
            ],
        )
        older = _table(
            "SOG02003",
            [
                _edition(
                    "is",
                    "Hjónavígslur 1771-2020",
                    "Sogulegar",
                    ["Sögulegar", "Giftingar og skilnaðir"],
                    [_var("Ár", "Ár", [], time=True)],
                )
            ],
        )
        return current, older

    def _pension_pair(self) -> tuple[Table, Table]:
        percent = _table(
            "FEL02000",
            [
                _edition(
                    "en",
                    "Percent of old age pension beneficiaries by type of payment",
                    "Samfelag",
                    ["Social affairs"],
                    [_var("Year", "Year", _years(2022, 2022), time=True)],
                )
            ],
        )
        counts = _table(
            "FEL02001",
            [
                _edition(
                    "en",
                    "Old age pension beneficiaries by type of payment",
                    "Samfelag",
                    ["Social affairs"],
                    [_var("Year", "Year", _years(2022, 2022), time=True)],
                )
            ],
        )
        return percent, counts


if __name__ == "__main__":
    unittest.main()
