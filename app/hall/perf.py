"""HALL PERF SECTION.

This file is separate so an integrator can fold it in on its own. The only
other edit is the two calls in app/hall/fastsearch.py, marked with the same
name. Nothing here changes a score, a bound value, or a refusal.

The hybrid answer was reading the tag-lemmatizer rule file again on every
new word. The Icelandic price-index search was analyzing the sentence again
and lemmatizing the same labels again, then walking every table a second
time for a shorter list. Those results are stored after the first time.
"""

from __future__ import annotations

import functools

_INSTALLED = False
_WARMED = False
_SERIES: dict[tuple, tuple[float, float]] = {}
_BINDS: dict[tuple, list] = {}


def install() -> None:
    """Cache pure work. A second call does nothing."""
    global _INSTALLED
    if _INSTALLED:
        return
    _nefnir_once()
    _cache_fold()
    _cache_tokens()
    _cache_analyze()
    _cache_labels()
    _cache_series()
    _cache_bind_values()
    _INSTALLED = True


def warm(catalogue) -> None:
    """Read the rule file once, and lemmatize each published label once."""
    global _WARMED
    install()
    if _WARMED:
        return
    _nefnir_once()
    import grund_lang.values as values

    seen: set[str] = set()
    terms = values._label_terms
    for table in getattr(catalogue, "tables", ()) or ():
        for edition in table.editions.values():
            _remember(terms, edition.title or "", seen)
            for variable in edition.variables:
                _remember(terms, variable.text or "", seen)
                for _code, label in variable.values:
                    _remember(terms, str(label or ""), seen)
    _WARMED = True


def _remember(terms, text: str, seen: set[str]) -> None:
    if not text or text in seen:
        return
    seen.add(text)
    terms(text)


def _nefnir_once() -> None:
    """The rule file is a few megabytes. Load it on the first call only."""
    try:
        import nefnir
        import nefnir.wrapper as wrapper
    except Exception:
        return
    original = wrapper.init
    if getattr(original, "_hall_perf", False):
        return

    def init() -> None:
        if getattr(wrapper, "_nefnir", None) is not None:
            return
        original()

    init._hall_perf = True
    wrapper.init = init
    nefnir.init = init
    try:
        init()
    except Exception:
        return


def _cache_fold() -> None:
    import grund_index.textutil as textutil

    original = textutil.fold
    cached = original if getattr(original, "cache_info", None) else functools.lru_cache(maxsize=500_000)(original)
    textutil.fold = cached
    for name in (
        "grund.bind",
        "grund.scope",
        "grund.engine",
        "grund.parse",
        "grund.retrieve",
        "grund.headline",
        "grund.cells",
        "grund.compute",
        "grund.langbind",
        "grund_index.catalogue",
    ):
        _rebind(name, "fold", original, cached)


def _cache_tokens() -> None:
    import grund_index.textutil as textutil

    original = textutil.tokens
    if getattr(original, "_hall_perf", False):
        return

    @functools.lru_cache(maxsize=200_000)
    def cached(text: str, expand: bool) -> tuple[str, ...]:
        return tuple(original(text, expand=expand))

    def tokens(text: str, *, expand: bool = False) -> list[str]:
        return list(cached(text, expand))

    tokens._hall_perf = True
    textutil.tokens = tokens
    for name in (
        "grund.bind",
        "grund.scope",
        "grund.engine",
        "grund.parse",
        "grund.retrieve",
        "grund_index.catalogue",
    ):
        module = _module(name)
        if module is None:
            continue
        current = getattr(module, "tokens", None)
        if current is original:
            module.tokens = tokens


def _cache_analyze() -> None:
    import grund_lang.lemma as lemma

    original = lemma.analyze
    if getattr(original, "_hall_perf", False):
        cached = original
    else:

        @functools.lru_cache(maxsize=256)
        def cached(text: str):
            return original(text)

        cached._hall_perf = True
        lemma.analyze = cached
    for name in (
        "grund_lang",
        "grund_lang.index",
        "grund_lang.values",
        "grund_lang.request",
        "grund_lang.driver",
    ):
        _rebind(name, "analyze", original, cached)


def _cache_labels() -> None:
    import grund_lang.lemma as lemma
    import grund_lang.values as values

    original = lemma.lemmatize_label
    if getattr(original, "cache_info", None) is None:
        cached = functools.lru_cache(maxsize=200_000)(original)
        lemma.lemmatize_label = cached
    else:
        cached = original
    for name in ("grund_lang", "grund_lang.index", "grund_lang.values"):
        _rebind(name, "lemmatize_label", original, cached)
    current = values._label_terms
    if getattr(current, "_hall_perf", False):
        return

    @functools.lru_cache(maxsize=200_000)
    def terms(label: str):
        return current(label)

    terms._hall_perf = True
    values._label_terms = terms


def _cache_series() -> None:
    import grund_lang.index as index

    original = index._series_adjustment
    if getattr(original, "_hall_perf", False):
        return

    def adjustment(question, table, asked, published, analysis=None):
        key = (question, id(table))
        found = _SERIES.get(key)
        if found is not None:
            return found
        found = original(question, table, asked, published, analysis)
        if len(_SERIES) > 20_000:
            _SERIES.clear()
        _SERIES[key] = found
        return found

    adjustment._hall_perf = True
    index._series_adjustment = adjustment


def _cache_bind_values() -> None:
    import grund_lang.index as index
    import grund_lang.values as values

    original = values.bind_values
    if getattr(original, "_hall_perf", False):
        return

    def bind_values(question, edition, analysis=None):
        key = (question, id(edition), id(analysis) if analysis is not None else 0)
        found = _BINDS.get(key)
        if found is not None:
            return list(found)
        found = original(question, edition, analysis)
        if len(_BINDS) > 4_000:
            _BINDS.clear()
        _BINDS[key] = list(found)
        return list(found)

    bind_values._hall_perf = True
    values.bind_values = bind_values
    index.bind_values = bind_values
    grund = _module("grund_lang")
    if grund is not None and getattr(grund, "bind_values", None) is original:
        grund.bind_values = bind_values


def _rebind(module_name: str, attr: str, original, cached) -> None:
    module = _module(module_name)
    if module is None:
        return
    if getattr(module, attr, None) is original:
        setattr(module, attr, cached)


def _module(name: str):
    import importlib
    import sys

    module = sys.modules.get(name)
    if module is not None:
        return module
    try:
        return importlib.import_module(name)
    except Exception:
        return None
