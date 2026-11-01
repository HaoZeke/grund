"""Subject check is on unless GRUND_SUBJECT=0. A zero count is withheld."""

from grund.subject_veto import enabled, subject_gap, zero_count_reason


def test_two_missing_subject_words_withhold_the_later_table():
    question = "Um hve mikið lækkaði heildarútgjöld til R&Þ sem hlutfall af VLF í Evrópu, Fyrirtæki frá 2023 til 2024?"
    leader = "Heildarútgjöld til R&Þ sem hlutfall af VLF í Evrópu 2013-2024"
    chosen = "Heildarútgjöld til fræðslumála á nemanda 1998-2025, sundurliðuð eftir skólastigum"
    assert subject_gap(question, leader, chosen)


def test_one_missing_word_keeps_the_answer():
    question = "launavísitala og annað"
    leader = "Launavísitala og vísitala neysluverðs"
    chosen = "Vísitala neysluverðs"
    assert not subject_gap(question, leader, chosen)


def test_the_leader_itself_is_not_a_gap():
    title = "Library borrowers by sex and age 2023-2025"
    question = "By what percentage did Library borrowers by sex and age fall?"
    assert not subject_gap(question, title, title)


def test_a_percent_question_answered_as_a_level_is_withheld():
    from grund.loose_gate import loose_gate_reason

    result = {"value": 2.7, "answer": "The figure was 2.7.", "claims": []}
    reason = loose_gate_reason(
        None,
        "By what percentage did overnight stays increase from 2024 to 2025?",
        "en",
        result,
    )
    assert reason == "level-against-change"


def test_points_are_the_unit_of_a_change_not_a_missing_measure():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": 39.0,
        "operation": "difference",
        "answer": "The change was 39 points. Calculated by Grund.",
        "tables": ["VIS01000"],
        "claims": [{
            "op": "difference",
            "cells": [{
                "title": "Consumer price index and changes, base 1988=100",
                "labels": {"Index": "Consumer price index", "Item": "Index"},
            }],
        }],
    }
    question = "By how many points did the consumer price index rise from September 2025 to September 2026?"
    assert loose_gate_reason(None, question, "en", result) is None


def test_a_stated_percent_is_not_that_gate():
    from grund.loose_gate import loose_gate_reason

    result = {"value": 4.3, "answer": "The change was 4.3 percent.", "claims": []}
    reason = loose_gate_reason(
        None,
        "By what percentage did deposits increase from 2015 to 2016?",
        "en",
        result,
    )
    assert reason is None


def test_men_minus_women_without_those_labels_is_withheld():
    from grund.loose_gate import loose_gate_reason

    result = {"value": 1300, "answer": "The difference was 1,300.", "claims": []}
    reason = loose_gate_reason(
        None,
        "How many more men than women lived in Iceland on 1 January 2026?",
        "en",
        result,
    )
    assert reason == "sex-pair"


def test_women_answered_as_the_total_is_withheld():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": 389444,
        "operation": "level",
        "answer": "In 2025, Total in Population by sex and age was 389,444.",
        "claims": [{
            "op": "level",
            "cells": [{
                "title": "Population by sex and age 1 January 1998-2026",
                "labels": {"Sex": "Total", "Age": "Total", "Year": "2025"},
            }],
        }],
    }
    reason = loose_gate_reason(None, "How many women lived in Iceland on 1 January 2025?", "en", result)
    assert reason == "sex-total"


def test_a_female_label_keeps_the_women_count():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": 189623,
        "operation": "level",
        "answer": "In 2025, Females in Population by sex and age was 189,623.",
        "claims": [{
            "op": "level",
            "cells": [{
                "title": "Population by sex and age 1 January 1998-2026",
                "labels": {"Sex": "Females", "Age": "Total", "Year": "2025"},
            }],
        }],
    }
    reason = loose_gate_reason(None, "How many women lived in Iceland on 1 January 2025?", "en", result)
    assert reason is None


def test_overnight_change_from_occupancy_is_withheld():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": 2.7,
        "operation": "yoy_pct",
        "answer": "The change was 2.7 percent. That is the change from 679 (2024) to 697 (2025).",
        "claims": [{
            "op": "yoy_pct",
            "cells": [{
                "title": "Number of establishment and capacity by types of accommodation",
                "labels": {"Accommodation": "Total", "Year": "2025"},
            }],
        }],
    }
    question = "By what percentage did the number of overnight stays in registered accommodation in Iceland increase from 2024 to 2025?"
    assert loose_gate_reason(None, question, "en", result) == "measure"


def test_overnight_change_from_the_stays_table_is_kept():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": 5.77,
        "operation": "yoy_pct",
        "answer": "Breytingin var 5,77 prósent. Það er breyting úr 9.312.648 í 9.850.428.",
        "claims": [{
            "op": "yoy_pct",
            "cells": [{
                "title": "Gistinætur á skráðum gististöðum",
                "labels": {"Eining": "Gistinætur", "Ár": "2025"},
            }],
        }],
    }
    question = "Um hve mörg prósent fjölgaði gistinóttum á skráðum gististöðum á Íslandi frá 2024 til 2025?"
    assert loose_gate_reason(None, question, "is", result) is None


def test_a_price_change_taken_from_hotel_arrivals_is_withheld():
    from grund.loose_gate import loose_gate_reason

    result = {
        "value": -7,
        "operation": "yoy_pct",
        "answer": "Það er breyting úr 164.271 í 152.690. Reiknað af Grund.",
        "claims": [{
            "op": "yoy_pct",
            "cells": [{
                "title": "Gistinætur og gestakomur á hótelum eftir mánuðum",
                "labels": {"Mánuður": "Desember", "Eining": "Gestakomur"},
            }],
        }],
    }
    question = "Um hve mörg prósent hækkaði verðlagið á tólf mánuðum til desember 2023?"
    assert loose_gate_reason(None, question, "is", result) == "measure"


def test_grund_subject_zero_turns_the_check_off(monkeypatch):
    monkeypatch.delenv("GRUND_SUBJECT", raising=False)
    assert enabled()
    monkeypatch.setenv("GRUND_SUBJECT", "0")
    assert enabled() is False


def test_a_zero_count_is_withheld_and_a_zero_percent_is_kept():
    assert zero_count_reason({"operation": "level", "value": 0, "answer": "Foreign citizens was 0."}) == "zero count"
    assert zero_count_reason({"operation": "pair", "value": 0, "answer": "The count was 0."}) == "zero count"
    assert zero_count_reason({"operation": "level", "value": 0, "answer": "The percentage was 0 percent."}) is None
    assert zero_count_reason({"operation": "difference", "value": 0, "answer": "The change was 0."}) == "zero count"
    assert zero_count_reason({"operation": "yoy_pct", "value": 0, "answer": "The change was 0 percent."}) is None
    assert zero_count_reason({"operation": "level", "value": 12, "answer": "The count was 12."}) is None
