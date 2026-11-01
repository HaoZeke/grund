"""GRUND_REDTEAM3 stays off unless set."""

from __future__ import annotations

from grund.redteam3 import enabled, maybe_correct


class _Parsed:
    def __init__(self, text, language="en"):
        self.text = text
        self.language = language


def _result(value, table, answer):
    return {"refused": False, "value": value, "table_id": table, "answer": answer, "source": {"cells": []}, "claims": []}


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_REDTEAM3", raising=False)
    assert enabled() is False
    stated = _result("394324", "MAN00101.px", "Total was 394,324.")
    assert maybe_correct(None, _Parsed("Hve margir kynsegin bjuggu á Íslandi?"), stated) is None


def test_nonbinary_total_is_refused_when_set(monkeypatch):
    monkeypatch.setenv("GRUND_REDTEAM3", "1")
    stated = _result("394324", "MAN00101.px", "filters Total, Population was 394,324.")
    assert (
        maybe_correct(None, _Parsed("Hve margir kynsegin eða aðrir bjuggu á Íslandi 1. janúar 2026?", "is"), stated)
        == "all sexes where non-binary was asked"
    )
    people = _result("394324", "MAN00101.px", "Total population was 394,324.")
    assert maybe_correct(None, _Parsed("How many people lived in Iceland on 1 January 2026?"), people) is None
