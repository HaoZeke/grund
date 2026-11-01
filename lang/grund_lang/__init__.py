"""Icelandic language layer and catalogue retrieval.

The planner calls three functions:

- `analyze` reads a question: lemmas, parts of speech, compounds, numbers, dates.
- `retrieve` returns candidate tables and the values most likely to bind.
- `bind_values` maps a question onto one edition's PxWeb codes.

`retrieve_pair` returns the two tables a comparison needs. `extend_allowed`
adds label and code digits to the number check. `build_index` and
`load_index` prepare the fused BM25 and embedding index.
"""

from __future__ import annotations

from pathlib import Path

import time

from grund_lang.grounding import extend_allowed, metadata_figures
from grund_lang.index import (
    RetrievalIndex,
    build_index,
    index_is_cached,
    load_catalogue,
    load_index,
    load_tables,
    save_index,
)
from grund_lang.lemma import analyze, detect_language, lemmatize_label, lemmatize_token
from grund_lang.pair import retrieve_pair
from grund_lang.types import Analysis, Candidate, ValueChoice
from grund_lang.values import bind_values

__all__ = [
    "Analysis",
    "Candidate",
    "RetrievalIndex",
    "ValueChoice",
    "analyze",
    "bind_values",
    "build_index",
    "detect_language",
    "extend_allowed",
    "lemmatize_label",
    "lemmatize_token",
    "load_catalogue",
    "load_index",
    "load_tables",
    "metadata_figures",
    "retrieve",
    "retrieve_pair",
    "save_index",
]


def retrieve(index: RetrievalIndex, question: str, k: int = 10) -> list[Candidate]:
    """Candidate tables for `question`, best first, with value bindings."""
    return index.search(question, k=k)


def build_saved_index(
    source: Path,
    out: Path,
    embed: str = "auto",
    *,
    catalogue: Path | None = None,
    embed_labels: bool = False,
) -> dict:
    cached = index_is_cached(out, catalogue, embed_labels)
    if cached is not None:
        cached = dict(cached)
        cached["cache"] = "hit"
        return cached
    started = time.perf_counter()
    if catalogue is not None:
        tables = load_catalogue(catalogue, source)
    else:
        tables = load_tables(source)
    index = build_index(tables, embed=embed, embed_labels=embed_labels)
    manifest = save_index(
        index,
        out,
        source,
        catalogue=catalogue,
        metadata=source if catalogue is not None else None,
        embed_labels=embed_labels,
    )
    manifest["build_seconds"] = round(time.perf_counter() - started, 1)
    manifest["cache"] = "miss"
    (out / "manifest.json").write_text(
        __import__("json").dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest
