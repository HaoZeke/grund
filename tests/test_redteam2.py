"""GRUND_REDTEAM2 stays off unless set, and it only replaces a neighbouring figure."""

from __future__ import annotations

import os

from grund.redteam2 import enabled, maybe_correct


class _Parsed:
    def __init__(self, text, language="en"):
        self.text = text
        self.language = language


def _result(value, table, answer):
    return {
        "refused": False,
        "value": value,
        "table_id": table,
        "answer": answer,
        "source": {"cells": [{"labels": {"label": answer}}]},
        "claims": [],
    }


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_REDTEAM2", raising=False)
    assert enabled() is False
    stated = _result("389444", "MAN00101.px", "Population was 389,444.")
    assert maybe_correct(None, _Parsed("How many people were employed in Iceland in 2025?"), stated) is None
    assert os.environ.get("GRUND_REDTEAM2") is None


def test_population_table_for_jobs_is_refused_only_when_set(monkeypatch):
    monkeypatch.setenv("GRUND_REDTEAM2", "1")
    stated = _result("389444", "MAN00101.px", "In 2025, Population by sex and age was 389,444.")
    assert (
        maybe_correct(None, _Parsed("How many people were employed in Iceland in 2025?"), stated)
        == "population table for a different question"
    )
    people = _result("394324", "MAN00101.px", "Population was 394,324.")
    assert maybe_correct(None, _Parsed("How many people lived in Iceland on 1 January 2026?"), people) is None


def test_constant_prices_are_not_left_on_the_current_price_table(monkeypatch):
    monkeypatch.setenv("GRUND_REDTEAM2", "1")
    stated = _result("4941211", "THJ01102.px", "Verg landsframleiðsla var 4,941,211.")
    # No catalogue here, so the retarget cannot run and the current-price cell is refused.
    assert maybe_correct(None, _Parsed("Hver var landsframleiðslan á föstu verðlagi árið 2025?", "is"), stated) == (
        "current prices are not constant prices"
    )
