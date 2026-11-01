"""A named category beats Alls. A title word, or a piece of a longer word, does not."""

from grund.bind import bind
from grund.parse import parse_question
from grund_index.model import Edition, Variable


def _edition(title, variables, lang="en", url="https://example.test/T.px"):
    return Edition(
        lang=lang,
        title=title,
        db="Test",
        path=["Test"],
        path_texts=["Test"],
        url=url,
        updated=None,
        variables=variables,
    )


def _values(binding, code):
    for entry in binding.selections:
        if entry["code"] == code:
            return entry["selection"]["values"]
    return None


def test_books_inside_childrenbooks_is_not_the_publishing_type():
    edition = _edition(
        "Publishing of textbooks and childrenbooks 1965-2000",
        [
            Variable("Year", "Year", True, False, [("2000", "2000")]),
            Variable("Type of books", "Type of books", False, False, [
                ("1", "Childrenbooks"),
                ("2", "Textbooks"),
            ]),
            Variable("Type of publishing", "Type of publishing", False, False, [
                ("total", "All editions"),
                ("1", "Books"),
                ("2", "Booklets"),
            ]),
        ],
    )
    binding = bind(edition, parse_question("What was Publishing of textbooks and childrenbooks in 2000?"))
    assert binding is not None
    assert _values(binding, "Type of books") == ["1"]
    assert _values(binding, "Type of publishing") == ["total"]


def test_an_inflected_icelandic_book_word_is_not_the_publishing_type():
    edition = _edition(
        "Útgáfa kennslu-, barna- og unglingabóka 1965-2000",
        [
            Variable("Ár", "Ár", True, False, [("2000", "2000")]),
            Variable("Tegund", "Tegund", False, False, [
                ("1", "Barna- og unglingabækur"),
                ("2", "Kennslubækur"),
            ]),
            Variable("Útgáfa", "Útgáfa", False, False, [
                ("Alls", "Allar útgáfur"),
                ("1", "Bækur"),
            ]),
        ],
        lang="is",
    )
    question = "Hver var útgáfa kennslu-, barna- og unglingabóka, Barna- og unglingabækur árið 2000?"
    binding = bind(edition, parse_question(question))
    assert binding is not None
    assert _values(binding, "Tegund") == ["1"]
    assert _values(binding, "Útgáfa") == ["Alls"]


def test_by_region_uses_the_whole_county_row():
    edition = _edition(
        "Livestock by region from 1980",
        [
            Variable("Ár", "Year", True, False, [("2024", "2024"), ("2025", "2025")]),
            Variable("Búpeningur", "Livestock", False, False, [
                ("0", "Cattle, total"),
                ("1", "Dairy cows"),
            ]),
            Variable("Landshluti", "Region", False, False, [
                ("0", "Whole county"),
                ("1", "Capital region and Southwest"),
                ("2", "West"),
            ]),
        ],
    )
    binding = bind(edition, parse_question("By how much did Livestock by region from rise from 2024 to 2025?"))
    assert binding is not None
    assert _values(binding, "Landshluti") == ["0"]
    assert _values(binding, "Búpeningur") == ["0"]


def test_a_title_word_does_not_beat_the_unnamed_total():
    edition = _edition(
        "Deposits and lending of commercial banks by category 2010-2016",
        [
            Variable("Ár", "Year", True, False, [("2015", "2015"), ("2016", "2016")]),
            Variable("Skipting", "Category", False, False, [
                ("0", "Domestic assets, total"),
                ("4", "Lending"),
                ("20", "Foreign assets, total"),
            ]),
        ],
    )
    question = "By what percentage did Deposits and lending of commercial banks by category increase from 2015 to 2016?"
    binding = bind(edition, parse_question(question))
    assert binding is not None
    assert _values(binding, "Skipting") == ["0"]


def test_a_category_written_after_the_title_still_wins():
    edition = _edition(
        "Icelandic fishing vessels by region and vessel type 1999-2024",
        [
            Variable("Skipagerð", "Type of vessel", False, False, [
                ("0", "All fishing vessels"),
                ("1", "Trawlers"),
            ]),
            Variable("Landsvæði", "Region", False, False, [
                ("0", "Whole county"),
                ("1", "Capitol region"),
            ]),
            Variable("Ár", "Year", True, False, [("2022", "2022")]),
        ],
    )
    question = "What percentage of Icelandic fishing vessels by region and vessel type was Capitol region in 2022?"
    binding = bind(edition, parse_question(question))
    assert binding is not None
    assert _values(binding, "Landsvæði") == ["1", "0"]


def test_the_other_language_total_beats_a_title_word():
    english = _edition(
        "Waste processing of packaging waste 2010-2022",
        [
            Variable("Ár", "Year", True, False, [("2021", "2021"), ("2022", "2022")]),
            Variable("Úrgangur", "Waste", False, False, [
                ("W1501", "Packaging"),
                ("W150102", "Plastic packaging"),
            ]),
            Variable("Mæling", "Measure", False, False, [
                ("GEN", "Waste generated"),
                ("RCV_E", "Recovery - energy recovery from packaging waste"),
                ("RCY", "Recycling"),
            ]),
            Variable("Eining", "Unit", False, False, [("T", "Tonnes")]),
        ],
        url="https://example.test/en/UMH04111.px",
    )
    icelandic = _edition(
        "Úrvinnsla á umbúðaúrgangi 2010-2022",
        [
            Variable("Ár", "Ár", True, False, [("2021", "2021"), ("2022", "2022")]),
            Variable("Úrgangur", "Úrgangur", False, False, [
                ("W1501", "Samtals umbúðaúrgangur"),
                ("W150102", "Plastumbúðir"),
            ]),
            Variable("Mæling", "Mæling", False, False, [
                ("GEN", "Umbúðaúrgangur sem fellur til"),
                ("RCV_E", "Endurnýting til orkuvinnslu"),
                ("RCY", "Samtals endurunnið"),
            ]),
            Variable("Eining", "Eining", False, False, [("T", "Tonn")]),
        ],
        lang="is",
        url="https://example.test/is/UMH04111.px",
    )
    question = "By how much did Waste processing of packaging waste, Tonnes fall from 2021 to 2022?"
    binding = bind(english, parse_question(question), icelandic)
    assert binding is not None
    assert _values(binding, "Úrgangur") == ["W1501"]
    assert _values(binding, "Mæling") == ["RCY"]
    assert _values(binding, "Eining") == ["T"]
