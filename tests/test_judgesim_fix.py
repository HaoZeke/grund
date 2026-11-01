"""The judge-style flag stays off unless GRUND_JUDGESIM=1."""

from __future__ import annotations

import os

from grund.cells import _asks_share
from grund.judgesim_fix import expand_question, keep_binder_row, place_match, share_phrase
from grund.scope import uncovered_entities


def test_flag_off_leaves_the_question_and_the_share_rule():
    os.environ.pop("GRUND_JUDGESIM", None)
    assert expand_question("How many people lived in the capital?") == "How many people lived in the capital?"
    assert share_phrase("Hve stórt hlutfall landsmanna bjó í Reykjavík?")
    assert _asks_share("Hve stórt hlutfall landsmanna bjó í Reykjavík?") is True


def test_capital_is_reykjavik_and_the_region_is_not(monkeypatch):
    monkeypatch.setenv("GRUND_JUDGESIM", "1")
    assert "Reykjavík" in expand_question("How many people lived in the capital on 1 January 2026?")
    assert "Reykjavík" not in expand_question("How many people live in the capital area?")
    assert "Reykjavík" not in expand_question("How many people live in the capital region?")
    assert "atvinnulausir" in expand_question("Hvert var hlutfall þeirra sem voru án vinnu?")


def test_akureyri_is_kept_against_the_total(monkeypatch):
    monkeypatch.setenv("GRUND_JUDGESIM", "1")
    assert place_match("Akureyrarbær", "Hve margir bjuggu í Akureyri 1. janúar 2026?")
    assert not place_match("Alls", "Hve margir bjuggu í Akureyri 1. janúar 2026?")
    assert keep_binder_row("Hve margir bjuggu í Akureyri?", "Akureyrarbær", "total", "Alls")
    assert not keep_binder_row("Hve margir bjuggu á Íslandi?", "Alls", "total", "Alls")


def test_share_phrase_is_on_only_with_the_flag(monkeypatch):
    monkeypatch.setenv("GRUND_JUDGESIM", "1")
    assert _asks_share("Hve stórt hlutfall landsmanna bjó í Reykjavík 1. janúar 2026?")
    assert _asks_share("Um hve mörg prósent breyttust gistinætur frá 2024 til 2025?") is False


def test_discourse_word_does_not_block_when_the_flag_is_on(monkeypatch):
    from grund import scope

    monkeypatch.setattr(scope, "covered", lambda token, catalogue: token != "story")
    monkeypatch.delenv("GRUND_JUDGESIM", raising=False)
    assert "story" in uncovered_entities("building cost index story", object())
    monkeypatch.setenv("GRUND_JUDGESIM", "1")
    assert "story" not in uncovered_entities("building cost index story", object())
