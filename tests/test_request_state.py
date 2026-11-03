"""Per-request state on one shared Engine.

The API's sync endpoint runs each request in a worker thread that copies the
caller's context, against the one Engine the server built. A pin or lock set
for one request must not be visible to another, and a scope must hand back
the value it found.
"""

import contextvars
import os
import threading

import pytest

from grund import request_state
from grund.frame import current_frame, push_frame, reset_frame
from grund.parse import parse_question
from grund.topic_prior import enabled as topic_prior_enabled

from test_engine import engine

_SEX = "Kyn"
_PINS = ("1", "2")
_QUESTION = "How many people lived in Iceland in 2024?"


@pytest.fixture(autouse=True)
def _python_rail(monkeypatch):
    # The rail is not under test; the Ruby checker need not be running.
    monkeypatch.setenv("GRUND_RAIL", "python")


def _concurrently(work, arguments):
    """Run ``work`` once per argument, each in its own thread and copied context.

    ``work`` receives a barrier that every thread must reach before any
    passes it, so all the requests are inside their scopes at once.
    """
    barrier = threading.Barrier(len(arguments))
    seen: dict = {}
    errors: list = []

    def run(argument):
        try:
            seen[argument] = work(barrier, argument)
        except BaseException as error:
            errors.append(error)
            barrier.abort()

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(run, argument))
        for argument in arguments
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    return seen


def _recording_engine(barrier_of):
    shared = engine()
    seen: dict = {}

    def answer(question, language=None):
        barrier_of[threading.get_ident()].wait()
        state = request_state.current()
        seen[threading.get_ident()] = (state.pinned_hit, dict(state.pinned_rows or {}), state.sibling_lock)
        return {"refused": True, "value": None}

    shared._ask_with_prior = answer
    return shared, seen


def test_concurrent_row_switches_see_only_their_own_pin():
    barrier_of: dict = {}
    shared, seen = _recording_engine(barrier_of)
    parsed = parse_question(_QUESTION, "en")
    stated = {"refused": False, "value": "383000", "table_id": "MAN00101.px", "rails": [], "candidates": []}

    def switch(barrier, code):
        barrier_of[threading.get_ident()] = barrier
        shared._switch_row(parsed, stated, _SEX, code, "test", "test")
        after = request_state.current()
        return seen[threading.get_ident()], (after.pinned_hit, after.pinned_rows, after.sibling_lock)

    results = _concurrently(switch, _PINS)
    for code in _PINS:
        (hit, rows, lock), after = results[code]
        assert rows == {_SEX: code}
        assert hit is not None and hit.table.id == "MAN00101.px"
        assert lock is True
        assert after == (None, None, False)


def test_concurrent_pinned_asks_see_only_their_own_table():
    barrier_of: dict = {}
    shared, seen = _recording_engine(barrier_of)
    tables = {table.id: table for table in shared.catalogue.tables}

    def ask(barrier, table_id):
        from grund_index.catalogue import Hit

        barrier_of[threading.get_ident()] = barrier
        hit = Hit(table=tables[table_id], score=1.0, bm25=0.0, cosine=0.0, value_boost=0.0)
        shared._ask_pinned(_QUESTION, "en", hit, pinned_rows={_SEX: table_id})
        return seen[threading.get_ident()]

    results = _concurrently(ask, tuple(tables))
    for table_id, (hit, rows, _lock) in results.items():
        assert hit.table.id == table_id
        assert rows == {_SEX: table_id}


def test_a_switch_restores_the_lock_it_found():
    barrier_of = {threading.get_ident(): threading.Barrier(1)}
    shared, seen = _recording_engine(barrier_of)
    parsed = parse_question(_QUESTION, "en")
    stated = {"refused": False, "value": "383000", "table_id": "MAN00101.px", "rails": [], "candidates": []}
    outer_rows = {_SEX: _PINS[0]}
    with request_state.scoped(sibling_lock=True, pinned_rows=outer_rows):
        shared._switch_row(parsed, stated, _SEX, _PINS[1], "test", "test")
        assert seen[threading.get_ident()][1] == {_SEX: _PINS[1]}
        assert request_state.current().sibling_lock is True
        assert dict(request_state.current().pinned_rows) == outer_rows
    assert request_state.current() == request_state.RequestState()


def test_the_baseline_pass_turns_the_prior_off_for_its_own_request_only(monkeypatch):
    monkeypatch.setenv("GRUND_TOPIC_PRIOR", "1")

    def look(barrier, off):
        with request_state.scoped(topic_prior_off=off):
            barrier.wait()
            return topic_prior_enabled()

    assert _concurrently(look, (True, False)) == {True: False, False: True}
    assert os.environ["GRUND_TOPIC_PRIOR"] == "1"


def test_concurrent_frames_are_per_request():
    def frame(barrier, name):
        token = push_frame(name)
        try:
            barrier.wait()
            return current_frame()
        finally:
            reset_frame(token)

    names = ("left", "right")
    assert _concurrently(frame, names) == {name: name for name in names}
    assert current_frame() is None
