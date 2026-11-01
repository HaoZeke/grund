"""Share recompute and a fully totalled cell, both off unless the flag is set."""

from grund_rails.cell_claim import check_claim, question_match_claims


def test_a_part_and_its_total_recompute_as_a_percent():
    from grund_rails.cell_claim import _share_of_total

    cells = [
        {"value": "189623", "labels": {"Kyn": "Konur", "Aldur": "Alls", "Ár": "2018"}},
        {"value": "385000", "labels": {"Kyn": "Alls", "Aldur": "Alls", "Ár": "2018"}},
    ]
    got = _share_of_total(cells)
    assert got is not None and abs(got - 189623 / 385000 * 100) < 1e-6
    change = [
        {"value": "100", "labels": {"Year": "2024"}},
        {"value": "110", "labels": {"Year": "2025"}},
    ]
    assert _share_of_total(change) is None


def test_a_named_place_is_not_covered_by_a_national_total():
    from grund_rails.cell_claim import _subject_stem

    cells = [{
        "title": "Mannfjöldi eftir landshlutum, kyni og aldri",
        "labels": {"Landshluti": "Alls", "Kyn": "Alls", "Aldur": "Alls", "Ár": "2022"},
    }]
    question = "Hver var mannfjöldinn í Reykjavík árið 2022?"
    assert _subject_stem(question, cells) is False


def test_a_short_word_inside_a_compound_is_not_the_subject():
    from grund_rails.cell_claim import _subject_stem

    births = [{"title": "Lifandi fæddir eftir fæðingarröð", "path": "Fæddir"}]
    assert _subject_stem("Hversu mörg börn fæddust á Íslandi árið 2021?", births)
    labour = [{"title": "Mannfjöldi eftir stöðu á vinnumarkaði", "path": ""}]
    assert _subject_stem("Hve margir voru í vinnu árið 2024?", labour) is False


def test_a_question_with_no_year_does_not_keep_a_total(monkeypatch):
    monkeypatch.setenv("GRUND_TOTAL_CELL", "1")
    question = "Er einhver að selja miða á leikinn í kvöld?"
    claim = {
        "op": "level",
        "value": "38",
        "cells": [{
            "title": "Hlutfall fyrirtækja sem selja vörur eða þjónustu",
            "labels": {"Alls": "Alls"},
        }],
    }
    assert question_match_claims(question, [claim]) is False


def test_a_change_total_does_not_pass_question_match(monkeypatch):
    monkeypatch.setenv("GRUND_TOTAL_CELL", "1")
    question = "Hversu miklu munaði á mannfjölda Íslands milli 2020 og 2024?"
    claim = {
        "op": "level",
        "value": "354042",
        "cells": [{
            "title": "Mannfjöldi eftir kyni og aldri",
            "path": "Mannfjöldi",
            "period": "2024",
            "labels": {"Kyn": "Alls", "Aldur": "Alls", "Ár": "2024"},
        }],
    }
    assert question_match_claims(question, [claim]) is False


def test_a_change_does_not_keep_the_totalled_level(monkeypatch):
    from grund_rails.cell_claim import total_cell_keeps

    monkeypatch.setenv("GRUND_TOTAL_CELL", "1")
    result = {
        "claims": [{
            "cells": [{
                "title": "Mannfjöldi eftir kyni og aldri",
                "labels": {"Kyn": "Alls", "Aldur": "Alls", "Ár": "2024"},
            }],
        }],
    }
    question = "Hversu miklu munaði á mannfjölda Íslands milli 2020 og 2024?"
    assert total_cell_keeps(question, result) is False


def test_disagreement_keeps_a_fully_totalled_cell_only_when_the_flag_is_on(monkeypatch):
    from grund.abstain_rule import abstain_for_disagreement

    result = {
        "refused": False,
        "value": 4869,
        "features": {"agreement": 0.2},
        "source": {"total_cell": True},
    }
    monkeypatch.delenv("GRUND_TOTAL_CELL", raising=False)
    assert abstain_for_disagreement(result)
    monkeypatch.setenv("GRUND_TOTAL_CELL", "1")
    assert not abstain_for_disagreement(result)


def test_a_fully_totalled_birth_cell_passes_only_when_the_flag_is_on(monkeypatch):
    question = "Hversu mörg börn fæddust á Íslandi árið 2021?"
    total = {
        "op": "level",
        "value": "4869",
        "cells": [{
            "title": "Lifandi fæddir eftir fæðingarröð og hjúskaparstétt móður 1951-2025",
            "path": "Fæddir",
            "period": "2021",
            "value": "4869",
            "labels": {"Hjúskaparstaða": "Alls", "Ár": "2021", "Fæðingarröð": "Alls"},
        }],
    }
    weight = {
        "op": "level",
        "value": "4869",
        "cells": [{
            "title": "Lifandi fæddir eftir þyngd 1998-2025",
            "path": "Fæddir",
            "period": "2021",
            "value": "4869",
            "table_id": "MAN05111",
            "labels": {"Kyn": "Alls", "Ár": "2021", "Þyngd": "Fjöldi barna"},
        }],
    }
    monkeypatch.delenv("GRUND_TOTAL_CELL", raising=False)
    assert question_match_claims(question, [total]) is False
    monkeypatch.setenv("GRUND_TOTAL_CELL", "1")
    assert question_match_claims(question, [total]) is True
    assert question_match_claims(question, [weight]) is False
