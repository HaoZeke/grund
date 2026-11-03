"""CellClaimRail fixtures. The cases live in eval/rail_cases.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from grund_rails.cell_claim import CellClaimRail, check_claim

CASES = Path("data/work/eval/rail_cases.jsonl")


def _load() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


_CORE = {"wrong_period", "unrequested_breakdown", "undeclared_number", "recompute_mismatch"}


def test_rail_cases_match_their_verdicts():
    from grund_rails.cell_claim import evaluate

    cases = _load()
    assert len(cases) >= 60
    mismatches = []
    for case in cases:
        reason = evaluate(case["question"], case["claim"], case["cells"], case.get("claims"))
        if case["verdict"] == "pass" and reason is not None:
            mismatches.append((case["id"], "pass", reason))
        elif case["verdict"] == "block" and reason is None:
            mismatches.append((case["id"], case["reason"], None))
        elif case["reason"] in _CORE and reason != case["reason"]:
            mismatches.append((case["id"], case["reason"], reason))
    assert mismatches == []


def test_a_share_is_the_ratio_not_the_part_count():
    question = "What percentage of the population by sex and age in 2024 was females?"
    cells = [
        {"table": "MAN00101", "value": "190000", "period": "2024", "labels": {"Sex": "Females"}},
        {"table": "MAN00101", "value": "383000", "period": "2024", "labels": {"Sex": "Total"}},
    ]
    percent = {
        "value": "49.6",
        "table": "MAN00101",
        "period": "2024",
        "labels": {"Sex": "Females"},
        "inputs": ["190000", "383000"],
    }
    assert check_claim(question, percent, cells) is None
    lone = dict(percent, value="190000", inputs=["190000", "383000"])
    assert check_claim(question, lone, cells) == "recompute_mismatch"
    only_part = {"value": "190000", "table": "MAN00101", "period": "2024", "labels": {"Sex": "Females"}}
    assert check_claim(question, only_part, cells[:1]) == "recompute_mismatch"


def test_country_of_birth_is_not_the_resident_population():
    question = "How many people lived in Iceland on 1 January 2026?"
    for labels in (
        {"Country of birth": "Iceland", "Sex": "Total", "Age": "Total"},
        {"Fæðingarland": "Total", "Kyn": "Total", "Aldur": "Total"},
    ):
        cell = {"table": "MAN12103", "value": "304795", "period": "2026", "labels": labels}
        reason = check_claim(
            question,
            {"value": "304795", "table": "MAN12103", "period": "2026", "labels": labels},
            [cell],
        )
        assert reason == "unrequested_breakdown"


def test_the_rail_blocks_and_passes_with_the_fixture_reason():
    rail = CellClaimRail()
    for case in _load():
        result = rail(
            "",
            {
                "question": case["question"],
                "claim": case["claim"],
                "claims": case.get("claims"),
                "cells": case["cells"],
            },
        )
        if case["verdict"] == "pass":
            assert result.status == "passed", case["id"]
            assert result.certain is True
        else:
            assert result.status == "blocked", case["id"]
            if case["reason"] in _CORE:
                assert result.reason == case["reason"], case["id"]


def test_born_beside_the_cells_own_measure_describes_its_members():
    from grund_rails.cell_claim import _birth_event_missing

    population = {"title": "Population by sex, age and country of birth 1998-2025", "labels": {"Country of birth": "Poland", "Year": "2025"}}
    assert not _birth_event_missing("What was the population of people born in Poland in Iceland in 2025?", population)
    assert _birth_event_missing("How many children were born in Iceland in 2025?", population)
    births = {"title": "Live births by sex 1838-2025", "labels": {"Sex": "Total", "Year": "2025"}}
    assert not _birth_event_missing("How many births were there in Iceland in 2025?", births)


def test_the_born_word_does_not_name_the_measure_it_describes():
    from grund_rails.cell_claim import _birth_event_missing

    abroad = {"title": "Population born abroad by background, sex, age and country of birth 1996-2026", "labels": {"Background": "Immigrant", "Year": "2025"}}
    assert _birth_event_missing("How many children were born in Iceland in 2025?", abroad)
    assert not _birth_event_missing("How many people born abroad lived in Iceland in 2025?", abroad)
