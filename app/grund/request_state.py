"""Per-request engine state.

One Engine serves every request, and a sync endpoint runs each request in
its own worker thread. A pin, lock or guard set for one question therefore
lives in a context variable, never on the Engine, and a scope restores the
value it found rather than resetting to a default.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class RequestState:
    # The table every nested ask must read, and the rows it must state.
    pinned_hit: Any = None
    pinned_rows: Mapping[str, str] | None = None
    # A row or sibling switch is under way; its re-ask must not switch again.
    sibling_lock: bool = False
    # The outer ask has framed the question; nested asks skip the frame.
    in_ask: bool = False
    # The topic-prior baseline pass owns the question.
    prior_guarded: bool = False
    # The ranker pass of the default path is under way.
    gate_active: bool = False
    # A two-part question is being answered half by half.
    defer_present: bool = False
    # The topic prior is off for this request whatever the environment says.
    topic_prior_off: bool = False


_STATE: ContextVar[RequestState] = ContextVar("grund_request_state", default=RequestState())


def current() -> RequestState:
    return _STATE.get()


@contextmanager
def scoped(**changes: Any) -> Iterator[RequestState]:
    """Apply ``changes`` for the block; the previous state comes back on exit."""
    if isinstance(changes.get("pinned_rows"), Mapping):
        changes["pinned_rows"] = MappingProxyType(dict(changes["pinned_rows"]))
    token = _STATE.set(replace(_STATE.get(), **changes))
    try:
        yield _STATE.get()
    finally:
        _STATE.reset(token)
