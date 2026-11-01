import json
from pathlib import Path

from grund.retrieve import ListingRetriever, title_core
from grund_index.catalogue import Catalogue
from grund_index.embed import Embedder
from grund_index.model import Edition, Table, Variable


def _edition(lang, title, path_texts, years, labels):
    return Edition(
        lang=lang,
        title=title,
        db="Efnahagur",
        path=["x"],
        path_texts=path_texts,
        url="https://px.hagstofa.is/pxen/api/v1/en/x.px",
        updated=None,
        variables=[
            Variable("Ár", "Year", True, False, [(str(year), str(year)) for year in years]),
            Variable("Liður", "Item", False, False, labels),
        ],
    )


def test_title_core_drops_the_published_span():
    assert title_core("Fertility 1853-2025") == "fertility"
    assert title_core("CPI breakdown from 2002-2025") == "cpi breakdown"


def test_a_quoted_current_table_outranks_the_earlier_sibling(tmp_path: Path):
    current = Table(
        id="VIS01300.px",
        editions={
            "en": _edition(
                "en",
                "CPI breakdown and contribution to monthly price changes",
                ["Prices", "Consumer price index", "Subindices"],
                range(2025, 2027),
                [("0", "Index"), ("02", "02 Alcoholic beverages, tobacco and narcotics")],
            )
        },
    )
    earlier = Table(
        id="VIS01301.px",
        editions={
            "en": _edition(
                "en",
                "CPI breakdown and contribution to monthly price changes from 2002-2025",
                ["Prices", "Consumer price index", "Earlier tables"],
                range(2002, 2026),
                [("0", "Index"), ("02", "02 Alcoholic beverages, tobacco and narcotics")],
            )
        },
    )
    listing = tmp_path / "catalogue.jsonl"
    rows = []
    for table, title, path in (
        (current, "CPI breakdown and contribution to monthly price changes", ["Subindices"]),
        (earlier, "CPI breakdown and contribution to monthly price changes from 2002-2025", ["Earlier tables"]),
    ):
        rows.append(
            {
                "id": table.id.removesuffix(".px"),
                "en": {"title": title, "path_texts": path},
                "is": {"title": title, "path_texts": path},
            }
        )
    listing.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    catalogue = Catalogue([current, earlier], Embedder(kind="chargram"), None, "none")
    hits = ListingRetriever(catalogue, listing).search(
        "By what percentage did CPI breakdown and contribution to monthly price changes, "
        "02 Alcoholic beverages, tobacco and narcotics increase from September 2025 to September 2026?",
        "en",
        k=2,
        years=[2025, 2026],
    )
    assert hits[0].table.id == "VIS01300.px"


def test_an_age_band_keeps_the_table_that_publishes_it(tmp_path: Path):
    broad = Table(
        id="MAN05201.px",
        editions={
            "en": _edition(
                "en",
                "Fertility 1853-2025",
                ["Births"],
                range(1990, 2026),
                [("3", "20-24 years"), ("0", "Total")],
            )
        },
    )
    citizen = Table(
        id="MAN05303.px",
        editions={
            "en": _edition(
                "en",
                "Fertility by mother's citizenship 1998-2025",
                ["Births"],
                range(1998, 2026),
                [("0", "Total fertility rate")],
            )
        },
    )
    listing = tmp_path / "catalogue.jsonl"
    rows = [
        {"id": "MAN05201", "en": {"title": "Fertility 1853-2025", "path_texts": ["Births"]}, "is": {}},
        {
            "id": "MAN05303",
            "en": {"title": "Fertility by mother's citizenship 1998-2025", "path_texts": ["Births"]},
            "is": {},
        },
    ]
    listing.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    catalogue = Catalogue([broad, citizen], Embedder(kind="chargram"), None, "none")
    hits = ListingRetriever(catalogue, listing).search(
        "By how much did Fertility, 20-24 years fall from 2024 to 2025?",
        "en",
        k=2,
        years=[2024, 2025],
    )
    assert hits[0].table.id == "MAN05201.px"
