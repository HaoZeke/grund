"""nlp.patch on top of the citation tree.

Nefnir init() reparses its rule file. lemmas() and the language lemmatizer
call it once. The prose lexicon does not install flytja → búferlaflutningar:
with the disagreement rule off that entry states 0 from MAN01002.
"""

from __future__ import annotations

import sys
import types

import grund_index.textutil as textutil
import grund_lang.lemma as lemma
import grund_lang.lexicon as lexicon


def test_build_drops_flytja(monkeypatch):
    monkeypatch.setattr(
        lexicon,
        "prose_maps",
        lambda pages: {
            "flytja": ("buferlaflutningar",),
            "logheimili": ("buferlaflutningar",),
        },
    )
    monkeypatch.setattr(lexicon, "folder_maps", lambda tables: {})
    monkeypatch.setattr(lexicon, "demonym_maps", lambda tables: {})
    found = lexicon.build([])
    assert "flytja" not in found
    assert found["logheimili"] == ("buferlaflutningar",)
    assert "flytja" not in lexicon.aliases()


def test_textutil_lemmas_initialises_nefnir_once(monkeypatch):
    calls = []
    fake = types.ModuleType("nefnir")

    def init():
        calls.append("init")

    def lemmatize(token, tag):
        return token

    fake.init = init
    fake.lemmatize = lemmatize
    monkeypatch.setitem(sys.modules, "nefnir", fake)
    monkeypatch.setattr(textutil, "_LEMMA_CACHE", {})
    monkeypatch.setattr(textutil, "_NEFNIR_READY", False)
    textutil.lemmas("gististodum", icelandic=True)
    textutil._LEMMA_CACHE.clear()
    textutil.lemmas("innflytjendum", icelandic=True)
    assert calls == ["init"]


def test_language_lemmatizer_initialises_nefnir_once(monkeypatch):
    calls = []
    fake = types.ModuleType("nefnir")

    def init():
        calls.append("init")

    def lemmatize(token, tag):
        return token + "x"

    fake.init = init
    fake.lemmatize = lemmatize
    monkeypatch.setitem(sys.modules, "nefnir", fake)
    monkeypatch.setattr(lemma, "_NEFNIR_READY", False)
    monkeypatch.setattr(lemma, "known_lemma", lambda word: True)
    assert lemma._nefnir_lemma("flutti") == "fluttix"
    assert lemma._nefnir_lemma("fluttir") == "fluttirx"
    assert calls == ["init"]
