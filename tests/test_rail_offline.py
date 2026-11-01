"""A missing rail is a startup failure, not a refusal of every question."""

from __future__ import annotations

import pytest

from grund.engine import Engine, IndexOffline


def test_unreachable_ruby_raises_instead_of_an_uncertain_pass(monkeypatch):
    import grund_rails.vangrail_client as client

    client.reset_checker_cache()
    monkeypatch.delenv("GRUND_RAIL", raising=False)
    monkeypatch.setattr(client, "_health", lambda url: None)
    monkeypatch.setattr(client, "_post", lambda url, payload: None)

    def missing(_payload):
        raise client.RailOffline(client._offline_message("ruby is not installed."))

    monkeypatch.setattr(client, "_once", missing)
    with pytest.raises(client.RailOffline, match="checker offline"):
        client.require_checker()
    client.reset_checker_cache()
    with pytest.raises(client.RailOffline, match="will not start"):
        client.check_output("The figure was 1.", "How many people live in Iceland?", {"claims": []})
    client.reset_checker_cache()


def test_python_rail_is_an_explicit_certain_fallback(monkeypatch):
    import grund_rails.vangrail_client as client

    client.reset_checker_cache()
    monkeypatch.setenv("GRUND_RAIL", "python")
    called = {"ruby": False}

    def ruby_must_not_run(_payload):
        called["ruby"] = True
        raise AssertionError("ruby ran")

    monkeypatch.setattr(client, "_once", ruby_must_not_run)
    monkeypatch.setattr(client, "_post", lambda url, payload: called.__setitem__("ruby", True))
    status = client.require_checker()
    assert status["mode"] == "python"
    assert status["offline"] is False
    verdict = client.check_output(
        "The figure was 2.6.",
        "How many people live in Iceland?",
        {
            "claims": [
                {
                    "value": "2.6",
                    "op": "level",
                    "cells": [
                        {
                            "title": "Total fertility rate",
                            "value": "2.6",
                            "period": "2024",
                            "labels": {"Year": "2024", "Unit": "fertility rate"},
                        }
                    ],
                }
            ]
        },
    )
    assert called["ruby"] is False
    assert verdict["certain"] is True
    assert verdict["status"] == "blocked"
    assert "unsupported_cell" in (verdict.get("categories") or [])
    client.reset_checker_cache()


def test_unknown_rail_mode_is_rejected(monkeypatch):
    import grund_rails.vangrail_client as client

    monkeypatch.setenv("GRUND_RAIL", "off")
    with pytest.raises(client.RailOffline, match="GRUND_RAIL"):
        client.rail_mode()


def test_engine_refuses_to_start_when_the_checker_is_offline(monkeypatch):
    import grund_rails.vangrail_client as client

    def boom():
        raise client.RailOffline("checker offline: ruby is not installed")

    monkeypatch.setattr(client, "require_checker", boom)
    with pytest.raises(client.RailOffline, match="checker offline"):
        Engine(object(), planner="deterministic")


def test_the_default_path_refuses_to_start_without_the_value_index(monkeypatch, tmp_path):
    monkeypatch.delenv("GRUND_PATH", raising=False)
    monkeypatch.setenv("GRUND_LANG_INDEX", str(tmp_path / "no-index"))

    class Wide:
        tables = [object()] * 100

    with pytest.raises(IndexOffline, match="fetch-index.sh"):
        Engine(Wide(), planner="deterministic")


def test_index_path_refuses_to_start_without_the_index(monkeypatch, tmp_path):
    monkeypatch.setenv("GRUND_PATH", "index")
    monkeypatch.setenv("GRUND_LANG_INDEX", str(tmp_path / "no-index"))

    class Wide:
        tables = [object()] * 100

    engine = Engine(Wide(), planner="deterministic")
    with pytest.raises(IndexOffline, match="value-label index"):
        engine.ask("How many people lived in Iceland in 2024?")
