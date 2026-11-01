"""GRUND_IS_ORIGIN stays off and only matches immigrant stock or a migration flow."""

from __future__ import annotations

import os

os.environ.pop("GRUND_IS_ORIGIN", None)

from grund.isorigin import flow_code, stock_question


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_IS_ORIGIN", raising=False)
    assert stock_question("Hve margir innflytjendur bjuggu á Íslandi 1. janúar 2026?") is False
    assert flow_code("Hve margir fluttu til Íslands árið 2025?") is None


def test_stock_and_flow(monkeypatch):
    monkeypatch.setenv("GRUND_IS_ORIGIN", "1")
    assert stock_question("How many immigrants lived in Iceland on 1 January 2026?") is True
    assert stock_question("Hve margir innflytjendur bjuggu á Íslandi 1. janúar 2026?") is True
    assert stock_question("Hve margir innflytjendur áttu lögheimili á Íslandi 1. janúar 2025?") is True
    assert stock_question("Hver var tekjur, eignir og skuldir innflytjenda eftir búsetu?") is False
    assert stock_question("Hver var fjöldi innflytjenda í skóla skipt eftir skólastigi?") is False
    assert flow_code("How many people immigrated to Iceland in 2025?") == "2"
    assert flow_code("Hve margir fluttu til Íslands árið 2025?") == "2"
    assert flow_code("What was net immigration to Iceland in 2024?") == "1"
    assert flow_code("Hver var nettó aðflutningur árið 2024?") == "1"
    assert stock_question("How many people immigrated to Iceland in 2025?") is False
