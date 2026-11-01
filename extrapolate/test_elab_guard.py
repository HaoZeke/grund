"""Adversarial checks for the extra-context number guard."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import pytest

from elab_guard import (
    LABEL_EN,
    LABEL_IS,
    ElabGuardError,
    check,
    extract_numbers,
    island_host,
    verify_watermark,
    watermark,
)

KEY = "unit-test-only"
ANSWER = {
    "answer": (
        "In 2024, the population was 394,324. "
        "Table MAN00000, filters Total, period 2024. "
        "https://px.hagstofa.is/pxen/api/v1/en/Ibuar/mannfjoldi/MAN00000.px"
    ),
    "refused": False,
    "clarify": False,
    "language": "en",
    "value": "394324",
    "value_display": "394,324",
    "table_id": "MAN00000.px",
    "tables": ["MAN00000.px"],
    "operation": "level",
    "source": {
        "table_id": "MAN00000.px",
        "title": "Population by sex and age 2015=100",
        "cells": [
            {
                "key": ["2024"],
                "value": "394324",
                "labels": [{"label": "Total"}, {"label": "2024"}],
            },
            {"key": ["2023"], "value": "191927", "labels": [{"label": "2023"}]},
        ],
        "derived": None,
        "retrieved_at": "2026-11-01T14:23:38Z",
        "api_url": "https://px.hagstofa.is/pxen/api/v1/en/Ibuar/mannfjoldi/MAN00000.px",
    },
    "elapsed_ms": 3290,
    "retries": 2,
}
QUESTION = "What was the population in Q3 2024?"


def _kinds(text, lang="en"):
    return [(hit.kind, hit.value) for hit in extract_numbers(text, lang)]


def test_icelandic_and_english_grouping():
    assert extract_numbers("1.234,5", "en")[0].value == Decimal("1234.5")
    assert extract_numbers("1.234,5", "is")[0].value == Decimal("1234.5")
    assert extract_numbers("1,234.5", "is")[0].value == Decimal("1234.5")
    assert extract_numbers("1.234.567", "en")[0].value == Decimal("1234567")
    assert extract_numbers("1,234,567.89", "is")[0].value == Decimal("1234567.89")


def test_space_grouped_and_nbsp():
    assert extract_numbers("8 476 511", "en")[0].value == Decimal("8476511")
    assert extract_numbers("8\u00a0476\u00a0511", "is")[0].value == Decimal("8476511")
    assert extract_numbers("8\u202f476\u202f511,25", "en")[0].value == Decimal("8476511.25")


def test_ambiguous_group_follows_language():
    assert extract_numbers("1.234", "is")[0].value == Decimal("1234")
    assert extract_numbers("1.234", "en")[0].value == Decimal("1.234")
    assert extract_numbers("1,234", "en")[0].value == Decimal("1234")
    assert extract_numbers("1,234", "is")[0].value == Decimal("1.234")
    assert extract_numbers("394.324", "is")[0].value == Decimal("394324")
    assert extract_numbers("394,324", "en")[0].value == Decimal("394324")


def test_percent_year_quarter_and_month_code():
    percent = extract_numbers("about 12,5%", "is")[0]
    assert percent.kind == "percent" and percent.value == Decimal("12.5")
    assert extract_numbers("12.5 percent", "en")[0].kind == "percent"
    assert extract_numbers("12,5 prósent", "is")[0].value == Decimal("12.5")
    assert _kinds("Q3 2024") == [("quarter", Decimal(3)), ("year", Decimal(2024))]
    assert _kinds("2024Q3") == [("quarter", Decimal(3)), ("year", Decimal(2024))]
    assert _kinds("3rd quarter of 2024") == [("quarter", Decimal(3)), ("year", Decimal(2024))]
    assert _kinds("3. ársfjórðungur 2024", "is") == [("quarter", Decimal(3)), ("year", Decimal(2024))]
    assert _kinds("þriðji ársfjórðungur 2024", "is") == [("quarter", Decimal(3)), ("year", Decimal(2024))]
    assert _kinds("Q3") == [("quarter", Decimal(3))]
    assert _kinds("2024M06") == [("year", Decimal(2024))]
    assert extract_numbers("-1,5", "is")[0].value == Decimal("-1.5")
    assert _kinds("2019-2024") == [("year", Decimal(2019)), ("year", Decimal(2024))]


def test_table_ids_urls_and_timestamps_are_not_figures():
    assert extract_numbers("Table VIS01000 shows the index.", "en") == []
    assert extract_numbers("https://example.com/394324", "en") == []
    assert _kinds("Updated 2026-09-29T08:59:51Z") == [("year", Decimal(2026))]
    assert extract_numbers("CPI2024", "en")[0].kind == "year"


def test_restated_formats_match_verified_value():
    text = "From the data\nThe population was 394.324."
    out = check(text, ANSWER, QUESTION, "is")
    assert out["ok"]
    assert "394.324" in out["text"]

    english = "From the data\nThe population was 394,324."
    assert check(english, ANSWER, QUESTION, "en")["ok"]

    unambiguous = "From the data\nThe derived total is 1.234,5."
    wage = dict(ANSWER, value="1234.5", value_display="1,234.5", operation="level")
    assert check(unambiguous, wage, "How large?", "en")["ok"]


def test_english_grouping_inside_icelandic_text_does_not_match():
    text = "From the data\nThe population was 394,324."
    out = check(text, ANSWER, QUESTION, "is")
    assert "394,324" not in out["text"]


def test_rounded_invented_percent_and_icelandic_decimal_are_dropped():
    text = """From the data
The population was about 394,000.
That is 15% of something else.
The index was 630,9.
The real level was 630,3.
"""
    verified = dict(ANSWER, value="630.3", value_display="630.3", answer="The level was 630.3.")
    out = check(text, verified, "What was the level in 2024?", "en")
    assert "394,000" not in out["text"]
    assert "15%" not in out["text"]
    assert "630,9" not in out["text"]
    assert "630,3" in out["text"]
    assert not out["ok"]


def test_icelandic_decimal_matches_same_figure_and_trailing_zero():
    verified = {
        "answer": "Vísitalan var 630,3.",
        "language": "is",
        "value": "630.3",
        "value_display": "630,3",
        "operation": "level",
    }
    kept = check("Úr gögnunum\nStaðan var 630,30.", verified, "Hver var vísitalan?", "is")
    assert kept["ok"]
    invented = check("Úr gögnunum\nStaðan var 1.234,9.", verified, "Hver var vísitalan?", "is")
    assert "1.234,9" not in invented["text"]


def test_cross_language_display_uses_answer_language():
    text = "Úr gögnunum\nFjöldinn var 394.324."
    out = check(text, ANSWER, "Hver var mannfjöldinn árið 2024?", "is")
    assert "394.324" in out["text"]


def test_question_year_and_quarter_allowed_but_bare_three_is_not():
    kept = check("From the data\nThe quarter in the question is Q3.", ANSWER, QUESTION, "en")
    assert kept["ok"]
    dropped = check("From the data\nThere were 3.", ANSWER, QUESTION, "en")
    assert "There were 3." not in dropped["text"]


def test_cell_value_allowed_metadata_and_title_are_not():
    cell = check("From the data\nThe earlier cell was 191927.", ANSWER, QUESTION, "en")
    assert "191927" in cell["text"]
    leaked = check(
        "From the data\nIt took 3290 ms and the base was 100 in 2015.",
        ANSWER,
        QUESTION,
        "en",
    )
    assert "3290" not in leaked["text"]
    assert "2015" not in leaked["text"]
    assert "100" not in leaked["text"]


def test_percent_unit_is_not_invented_from_a_level():
    level = {
        "answer": "In 2024, the wage index was 9.2.",
        "language": "en",
        "value": "9.2",
        "value_display": "9.2",
        "operation": "level",
    }
    invented = check("From the data\nThat is 9.2%.", level, "What was the wage index in 2024?", "en")
    assert "9.2%" not in invented["text"]
    same = check("From the data\nThe index was 9,2.", level, "What was the wage index in 2024?", "is")
    assert "9,2" in same["text"]


def test_share_percent_may_be_restated():
    share = {
        "answer": "The share was 48.7 percent.",
        "language": "en",
        "value": "48.7",
        "value_display": "48.7",
        "operation": "share",
        "source": {"derived": {"name": "share_percent", "value": "48.7", "inputs": ["100", "205"]}},
    }
    out = check("From the data\nThe share was 48,7%.", share, "What share?", "is")
    assert "48,7%" in out["text"]
    assert check("From the data\nThe inputs were 100 and 205.", share, "What share?", "en")["ok"]


def test_path_pair_and_json_string_answer():
    paired = {
        "answer": "Both figures are stated.",
        "language": "en",
        "value": "10",
        "value_display": "10",
        "operation": "pair",
        "path_pair": {"left": {"value": "10"}, "right": {"value": "25", "cells": [{"value": "25"}]}},
    }
    out = check("From the data\nThe other figure is 25.", paired, "Both?", "en")
    assert out["ok"]
    import json

    encoded = check("From the data\nThe population was 394,324.", json.dumps(ANSWER), QUESTION, "en")
    assert encoded["ok"]


def test_from_the_data_ignores_markers():
    records = [
        {"id": "1", "kind": "calc", "expression": "1+1", "result": "111"},
        {"id": "f", "kind": "fetch", "table": "MAN00101", "cells": [{"value": "111"}]},
        {"kind": "source", "url": "https://www.island.is/tolur", "text": "The page says 111."},
    ]
    text = """From the data
A new total is 111 [calc:1].
A fetched total is 111 [fetch:MAN00101].
A page total is 111 [source:https://www.island.is/tolur].
A guess is 111 (inferred).
Ágiskun er 111 (ályktun).
"""
    out = check(text, ANSWER, QUESTION, "en", records)
    assert "111" not in out["text"]
    assert len(out["dropped_sentences"]) == 5


def test_beyond_unmarked_number_is_dropped_and_known_number_stays():
    text = """Beyond the data
The population was 394,324.
Somebody might say 111.
"""
    out = check(text, ANSWER, QUESTION, "en")
    assert "394,324" in out["text"]
    assert "111" not in out["text"]


def test_fetch_marker_uses_cells_not_the_result_field():
    records = [
        {
            "id": "pop",
            "kind": "fetch",
            "table": "MAN00101.px",
            "cells": [{"value": "8476511", "period": "2024Q3"}],
            "result": "999",
        }
    ]
    kept = check(
        "Beyond the data\nThe register shows 8.476.511 [fetch:MAN00101].",
        ANSWER,
        QUESTION,
        "is",
        records,
    )
    assert "8.476.511" in kept["text"]
    wrong_table = check(
        "Beyond the data\nThe register shows 8.476.511 [fetch:VIS01000].",
        ANSWER,
        QUESTION,
        "is",
        records,
    )
    assert "8.476.511" not in wrong_table["text"]
    result_only = check(
        "Beyond the data\nThe hidden result is 999 [fetch:MAN00101].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "999" not in result_only["text"]
    not_percent = check(
        "Beyond the data\nThe register shows 8476511% [fetch:MAN00101].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "8476511%" not in not_percent["text"]


def test_calc_marker_allows_rounding_and_rejects_a_different_result():
    records = [
        {"id": "1", "kind": "calc", "table": "MAN00000", "expression": "a/b*100", "result": "12.346"},
        {"id": "2", "kind": "calc", "expression": "x", "result": "50"},
    ]
    for sentence in (
        "The change is 12.35 [calc:1].",
        "The change is 12,3 [calc:1].",
        "The change is 12 [calc:1].",
    ):
        out = check("Beyond the data\n" + sentence, ANSWER, QUESTION, "en", records)
        assert sentence.split(" [")[0] in out["text"] or sentence in out["text"]
    exact = check("Beyond the data\nBreytingin er 12,35 [calc:1].", ANSWER, QUESTION, "is", records)
    assert "12,35" in exact["text"]
    truncated = check("Beyond the data\nThe change is 12.34 [calc:1].", ANSWER, QUESTION, "en", records)
    assert "12.34" not in truncated["text"]
    other = check("Beyond the data\nThe change is 50 [calc:1].", ANSWER, QUESTION, "en", records)
    assert "50" not in other["text"]
    right_id = check("Beyond the data\nThe other calc is 50 [calc:2].", ANSWER, QUESTION, "en", records)
    assert "50" in right_id["text"]
    half = check("Beyond the data\nRounded it is 13 [calc:1].", {"answer": "none", "language": "en", "value": "1", "value_display": "1", "operation": "level"}, "Q?", "en", [{"id": "1", "kind": "calc", "result": "12.5"}])
    assert "13" in half["text"]


def test_inferred_marker_allows_a_new_number_only_without_a_failed_citation():
    text = "Handan gagnanna\nÁætluð tala er 42 (ályktun)."
    out = check(text, ANSWER, QUESTION, "is")
    assert "42" in out["text"]
    english = check("Beyond the data\nOne reading is 42 (inferred).", ANSWER, QUESTION, "en")
    assert "42" in english["text"]
    rescued = check(
        "Beyond the data\nThe calc says 42 [calc:1] (inferred).",
        ANSWER,
        QUESTION,
        "en",
        [{"id": "1", "kind": "calc", "result": "7"}],
    )
    assert "42" not in rescued["text"]


def test_source_marker_on_island_is_and_subdomains():
    url = "https://www.island.is/tolur"
    records = [{"id": "s", "kind": "source", "url": url, "text": "Skráð 8 476 511 íbúar."}]
    wrapped = """Beyond the data
The register lists 8 476 511 people
[source:https://www.island.is/tolur].
"""
    out = check(wrapped, ANSWER, QUESTION, "en", records)
    assert "8 476 511" in out["text"]
    apex = "https://island.is/tolur"
    data = "https://data.island.is/tolur"
    for host_url in (apex, data):
        rec = [{"kind": "source", "url": host_url, "text": "Only 222 is written here."}]
        kept = check(
            f"Beyond the data\nThe page says 222 [source:{host_url}].",
            ANSWER,
            QUESTION,
            "en",
            rec,
        )
        assert "222" in kept["text"]
    missing = check(
        "Beyond the data\nThe page says 111 [source:https://www.island.is/tolur].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "111" not in missing["text"]
    other_page = check(
        "Beyond the data\nThe page says 8 476 511 [source:https://www.island.is/other].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "8 476 511" not in other_page["text"]


def test_off_domain_source_is_rejected():
    url = "https://example.com/stat"
    records = [{"kind": "source", "url": url, "text": "The figure is 8476511."}]
    out = check(
        f"Beyond the data\nThe register lists 8476511 people [source:{url}].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "8476511" not in out["text"]
    assert "example.com" not in out["text"]
    path_trick = check(
        "Beyond the data\nThe register lists 8476511 people [source:https://evil.com/island.is].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": "https://evil.com/island.is", "text": "8476511"}],
    )
    assert "8476511" not in path_trick["text"]
    userinfo = check(
        "Beyond the data\nThe register lists 8476511 people [source:https://island.is@evil.com/stat].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": "https://island.is@evil.com/stat", "text": "8476511"}],
    )
    assert "8476511" not in userinfo["text"]
    not_island = check(
        "Beyond the data\nThe register lists 8476511 people [source:https://notisland.is/stat].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": "https://notisland.is/stat", "text": "8476511"}],
    )
    assert "notisland.is" not in not_island["text"]


def test_lookalike_island_host_is_rejected():
    url = "https://island.is.evil.com/stat"
    records = [{"kind": "source", "url": url, "text": "The figure is 8476511."}]
    out = check(
        f"Beyond the data\nThe population was 394,324 [source:{url}].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "394,324" not in out["text"]
    assert "island.is.evil.com" not in out["text"]
    nested = "https://www.island.is.evil.com/stat"
    nested_out = check(
        f"Beyond the data\nA new figure is 8476511 [source:{nested}].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": nested, "text": "8476511"}],
    )
    assert "8476511" not in nested_out["text"]
    cyrillic = "https://isl\u0430nd.is/stat"
    cyrillic_out = check(
        f"Beyond the data\nA new figure is 8476511 [source:{cyrillic}].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": cyrillic, "text": "8476511"}],
    )
    assert "8476511" not in cyrillic_out["text"]
    assert island_host("https://data.island.is/x") == "data.island.is"
    assert island_host(url) is None
    assert island_host("https://island.is.") == "island.is"


def test_userinfo_and_inferred_do_not_launder_a_source():
    real = "https://island.is/tolur"
    disguised = "https://evil.com@island.is/tolur"
    records = [{"kind": "source", "url": real, "text": "The page says 222."}]
    out = check(
        f"Beyond the data\nThe page says 222 [source:{disguised}] (inferred).",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "222" not in out["text"]
    assert "evil.com" not in out["text"]
    off = check(
        "Beyond the data\nA new figure is 333 [source:https://example.com/a] (inferred).",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": "https://example.com/a", "text": "333"}],
    )
    assert "333" not in off["text"]
    assert island_host(disguised) is None


def test_source_percent_and_extra_number_and_url_shape():
    url = "https://www.island.is/tolur"
    records = [{"kind": "source", "url": url + "/", "text": "The share on the page is 12,5 prósent."}]
    kept = check(
        "Beyond the data\nThe page says 12.5% [source:https://www.island.is:443/tolur].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "12.5%" in kept["text"]
    bare = check(
        f"Beyond the data\nThe page says 12.5% [source:{url}].",
        ANSWER,
        QUESTION,
        "en",
        [{"kind": "source", "url": url, "text": "The level on the page is 12.5."}],
    )
    assert "12.5%" not in bare["text"]
    extra = check(
        f"Beyond the data\nThe page says 12,5 prósent and also 333 [source:{url}].",
        ANSWER,
        QUESTION,
        "is",
        records,
    )
    assert "333" not in extra["text"]
    assert "12,5" not in extra["text"]


def test_claim_value_is_a_verified_figure():
    claimed = {
        "answer": "The sentence names the table only.",
        "language": "en",
        "value": "10",
        "value_display": "10",
        "operation": "level",
        "claims": [{"value": "44.5", "op": "level", "cells": [{"value": "44.5", "period": "2020"}]}],
    }
    out = check("From the data\nThe claim figure is 44.5.", claimed, "Which year?", "en")
    assert "44.5" in out["text"]
    assert check("From the data\nThe claim figure is 44,8.", claimed, "Which year?", "is")["text"].find("44,8") < 0


def test_source_marker_does_not_promote_a_strict_section_number():
    url = "https://island.is/tolur"
    records = [{"kind": "source", "url": url, "text": "The page says 111."}]
    out = check(
        f"From the data\nThe page says 111 [source:{url}].",
        ANSWER,
        QUESTION,
        "en",
        records,
    )
    assert "111" not in out["text"]


def test_causality_and_forecast_are_flagged():
    text = """From the data
The level moved because the basket changed, and the figure is 394,324.
It will reach 500000 next year.
Talan er 394.324 vegna innflutnings.
Gert er ráð fyrir 80 (inferred).
"""
    out = check(text, ANSWER, QUESTION, "en")
    assert "394,324" in out["text"]
    assert "500000" not in out["text"]
    kinds = [flag["kind"] for flag in out["flags"]]
    assert "causality" in kinds
    assert "forecast" in kinds
    icelandic = check(
        "Handan gagnanna\nTalan er 394.324 vegna innflutnings. Þetta mun hækka.",
        ANSWER,
        "Hver var mannfjöldinn 2024?",
        "is",
    )
    assert any(flag["kind"] == "causality" for flag in icelandic["flags"])
    assert any(flag["kind"] == "forecast" for flag in icelandic["flags"])
    assert "394.324" in icelandic["text"]


def test_kept_sentences_preserve_order():
    text = """From the data
The population was 394,324.
A made-up total is 111.
The year in the question is 2024.
"""
    out = check(text, ANSWER, QUESTION, "en")
    assert out["text"].index("394,324") < out["text"].index("2024")
    assert "111" not in out["text"]


def _meta():
    return {
        "answer_hash": "abc123",
        "model": "example-model",
        "timestamp": "2026-11-01T18:00:00Z",
        "lang": "en",
    }


def test_watermark_roundtrip_and_visible_label(monkeypatch):
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    meta = _meta()
    body = "The population figure is already stated."
    marked = watermark(body, meta)
    assert marked.splitlines()[0]
    visible = "".join(ch for ch in marked.splitlines()[0] if ch not in "\u200b\u200c\u200d\u2060")
    assert visible == LABEL_EN
    assert "\u200b" in marked or "\u200c" in marked
    assert body in marked
    checked = verify_watermark(marked, meta)
    assert checked.ok
    mac = hmac.new(
        KEY.encode(),
        b"abc123|example-model|2026-11-01T18:00:00Z",
        hashlib.sha256,
    ).hexdigest()
    assert checked.short_id == mac[:8]
    assert mac not in marked
    assert KEY not in marked
    assert checked.short_id not in marked


def test_watermark_icelandic_label_and_answer_fingerprint(monkeypatch):
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    meta = {"answer": ANSWER, "model": "example-model", "timestamp": "t", "lang": "is"}
    marked = watermark("Texti.", meta)
    assert LABEL_IS in marked.splitlines()[0]
    assert verify_watermark(marked, meta).ok
    other = dict(meta, answer={"answer": "different"})
    assert not verify_watermark(marked, other)


def test_watermark_rejects_tampering(monkeypatch):
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    meta = _meta()
    marked = watermark("Hello.", meta)
    assert not verify_watermark(marked, dict(meta, timestamp="other"))
    assert not verify_watermark(marked, dict(meta, model="other"))
    assert not verify_watermark(marked, dict(meta, answer_hash="nope"))
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", "different")
    assert not verify_watermark(marked, meta)
    stripped = LABEL_EN + "\nHello."
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    assert verify_watermark(stripped, meta).reason == "marker missing"
    relabelled = marked.replace(LABEL_EN, "A different label")
    assert verify_watermark(relabelled, meta).reason == "label missing"


def test_watermark_requires_key_and_meta(monkeypatch):
    monkeypatch.delenv("GRUND_ELAB_HMAC_KEY", raising=False)
    with pytest.raises(ElabGuardError):
        watermark("Hello.", _meta())
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    with pytest.raises(ElabGuardError):
        watermark("Hello.", {"answer_hash": "abc"})


def test_body_edit_does_not_change_the_provenance_hmac(monkeypatch):
    monkeypatch.setenv("GRUND_ELAB_HMAC_KEY", KEY)
    meta = _meta()
    marked = watermark("Hello.", meta)
    edited = marked.replace("Hello.", "Hello. Extra clause.")
    assert verify_watermark(edited, meta).ok
