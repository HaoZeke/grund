"""Query expansions from GRUND_IS_KANG_* flags. Default off.

The catalogue ranker stores folded label tokens. Each flag adds folded
forms to the query only, and only when that flag is set to ``1``.
A missing module is skipped, so one flag can be installed on its own.
"""

from __future__ import annotations

import importlib
import os

_FLAGS = (
    ("GRUND_IS_KANG_BINFORMS", "grund_lang.kang_binforms"),
    ("GRUND_IS_KANG_PLACES", "grund_lang.kang_places"),
    ("GRUND_IS_KANG_SYNONYM", "grund_lang.kang_synonym"),
)


def expand(tokens: list[str]) -> list[str]:
    if not any(os.environ.get(flag, "0") == "1" for flag, _mod in _FLAGS):
        return []
    found: list[str] = []
    seen = set(tokens)
    for flag, modname in _FLAGS:
        if os.environ.get(flag, "0") != "1":
            continue
        try:
            module = importlib.import_module(modname)
        except Exception:
            continue
        try:
            extra = module.extra_folded(tokens)
        except Exception:
            continue
        for token in extra:
            if token and token not in seen:
                seen.add(token)
                found.append(token)
    return found
