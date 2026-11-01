import json
from pathlib import Path

from grund.engine import Engine
from grund.scope import uncovered_entities
from grund_index.catalogue import Catalogue
from grund_index.embed import Embedder
from grund_index.model import Edition, Table, Variable

from test_bind import cpi, population

ROOT = Path(__file__).resolve().parents[1]


class CountingClient:
    def __init__(self):
        self.posts = 0

    def post_json(self, url, body):
        self.posts += 1
        raise AssertionError("out of scope must not fetch")


def _catalogue() -> Catalogue:
    month_label = Variable(
        "Base",
        "Base period",
        False,
        False,
        [("m1997", "vísitala, mars 1997=100"), ("june", "June")],
    )
    priced = cpi()
    priced.variables = [*priced.variables, month_label]
    tables = [
        Table(id="VIS01000.px", editions={"en": priced}),
        Table(id="MAN00101.px", editions={"en": population()}),
    ]
    return Catalogue(tables, Embedder(kind="chargram"), None, "none")


def test_render_names_the_table_and_the_link():
    from grund.answer import render
    from grund.bind import Binding

    edition = cpi()
    binding = Binding(edition, [], "level", 0.0, "Month", ["2024M06"])
    rows = [{"map": {"Month": "2024M06"}, "labels": [], "value": "630.3"}]
    sentence = render("en", edition, binding, rows, "630.3", None, False)
    assert "VIS01000" in sentence
    assert "px.hagstofa.is" in sentence


def test_a_named_month_is_monthly_and_a_stock_date_is_yearly():
    from grund_index.catalogue import _asked_grain
    from grund_index.textutil import fold

    assert _asked_grain(fold("vísitala í desember 2023")) == "month"
    assert _asked_grain(fold("atvinnuleysi á öðrum ársfjórðungi 2026")) == "quarter"
    assert _asked_grain(fold("mannfjöldi 1. janúar 2026")) == "year"


def test_verbs_pronouns_and_numerals_are_not_subject_nouns():
    from grund.scope import subject_nouns, uncovered_subject_nouns

    nouns = subject_nouns("Hún sýndi tólf töflur hingað og varð komin.")
    assert "hun" not in nouns
    assert "syndi" not in nouns
    assert "tolf" not in nouns
    assert "hingad" not in nouns
    assert "vard" not in nouns
    catalogue = _catalogue()
    missing = uncovered_subject_nouns("Hversu margar konur voru skráðar búsettar á landinu?", catalogue)
    assert "busettar" not in missing
    assert "skradar" not in missing


def test_a_base_phrase_is_not_the_period_and_a_later_clause_keeps_the_year():
    from grund.parse import parse_question, resolve_references

    parsed = parse_question("Vísitalan í desember 2025, þar sem 1988 er sett sem 100?")
    assert (1988, None) not in parsed.periods
    assert (2025, 12) in parsed.periods
    resolved = resolve_references("Mannfjöldinn var 383726 árið 2024. Hver var hún sama ár?")
    assert "2024" in resolved.split(".")[-1]
    assert "Mannfjöldinn" in resolved


def test_natural_icelandic_is_not_a_clear_refusal():
    from grund.scope import clearly_out_of_scope

    assert clearly_out_of_scope("Hvað voru margir með lögheimili á Íslandi 1. janúar 2026?") is None
    assert clearly_out_of_scope("Hversu margar konur voru skráðar búsettar á landinu?") is None
    dragons = clearly_out_of_scope("How many dragons were registered in Iceland in 2020?")
    assert dragons is not None and dragons["kind"] == "non_statistics"
    opinion = clearly_out_of_scope("Hvað finnst þér um mannfjöldann?")
    assert opinion is not None and opinion["kind"] == "opinion"
    future = clearly_out_of_scope("What was the consumer price index in June 2099?")
    assert future is not None and future["kind"] == "future"
    assert clearly_out_of_scope("Hver er mannfjöldaspáin til 2060?") is None
    yesterday = clearly_out_of_scope("Hvernig var veðrið á gærkvöld?")
    assert yesterday is not None and yesterday["kind"] == "non_statistics"


def test_month_labels_do_not_cover_mars_and_loose_population_stays_in_scope():
    catalogue = _catalogue()
    assert "mars" in uncovered_entities("What is the population of Mars?", catalogue)
    assert "dragons" in uncovered_entities("How many dragons were registered in Iceland in 2020?", catalogue)
    assert uncovered_entities("What was the consumer price index in June 2024?", catalogue) == []
    assert uncovered_entities("How many women lived in 2024, counting every age?", catalogue) == []
    assert "mars" not in catalogue.month_title_vocab


def test_engine_refuses_out_of_scope_without_fetching_and_still_answers_june():
    catalogue = _catalogue()
    client = CountingClient()
    asked = Engine(catalogue, client=client, planner="deterministic")
    dragons = asked.ask("How many dragons were registered in Iceland in 2020?")
    assert dragons["refused"] is True
    assert dragons["value"] is None
    assert dragons["table_id"] is None
    assert dragons["candidates"] == []
    assert "not among the subjects" in dragons["answer"]
    assert client.posts == 0

    mars = asked.ask("What is the population of Mars in 2024?")
    assert mars["refused"] is True
    assert "mars" in mars["detail"]["uncovered"]
    assert client.posts == 0

    from test_engine import FakeClient

    live = Engine(catalogue, client=FakeClient(), planner="deterministic")
    june = live.ask("What was the consumer price index in June 2024?")
    assert june["refused"] is False
    assert june["value"] == "630.3"
    assert "VIS01000" in june["answer"]
    assert "px.hagstofa.is" in june["answer"]
    future = live.ask("What was the consumer price index in June 2099?")
    assert future["refused"] is True
    assert "not among the subjects" not in future["answer"]


def test_a_refusal_after_retrieval_names_the_table_and_the_link():
    from grund.parse import parse_question
    from test_engine import FakeClient

    catalogue = _catalogue()
    live = Engine(catalogue, client=FakeClient(), planner="deterministic")
    parsed = parse_question("What was the consumer price index in June 2024?")
    result = live._finish_refusal(
        parsed,
        "no_table",
        [],
        0.0,
        candidates=[
            {
                "table_id": "VIS01000.px",
                "title": "Consumer price index",
                "url": "https://px.hagstofa.is/pxen/api/v1/en/VIS01000.px",
            }
        ],
    )
    assert result["refused"] is True
    assert result["value"] is None
    assert "VIS01000" in result["answer"]
    assert "px.hagstofa.is" in result["answer"]
    assert "630" not in result["answer"]


def test_heldout_roles_follow_the_full_catalogue_not_the_eval_wording():
    catalogue = Catalogue.load(ROOT / "data" / "index")
    held = [
        json.loads(line)
        for line in (ROOT / "evalset" / "heldout.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert held
    for item in held:
        missing = uncovered_entities(item["question"], catalogue)
        if item["role"] == "unanswerable":
            assert missing, item["id"]
        else:
            assert missing == [], (item["id"], missing)
    scored = [
        json.loads(line)
        for line in (ROOT / "evalset" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["id"]: row for row in scored}
    for absent in ("q003", "q007", "q009"):
        assert uncovered_entities(by_id[absent]["question"], catalogue)
    # "drekar" is a customs heading (anchors and grapnels, HS 73160000), so the
    # Icelandic dragons sentence is in scope on this catalogue.
    assert uncovered_entities(by_id["q004"]["question"], catalogue) == []
    for answerable in scored:
        if answerable["expect"] != "answer":
            continue
        missing = uncovered_entities(answerable["question"], catalogue)
        assert missing == [], (answerable["id"], missing)
