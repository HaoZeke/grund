"""The same question must rank the same way twice.

The hall's count gap on one build was the value index, not PxWeb and not
Nefnir. This machine's data/index-lang is e5-large, 1024-d, 2189 passages.
data/index and the hall value index are chargram, 384-d, 2104 tables.
The engine rebuilds that chargram matrix from the catalogue, so a saved
matrix cannot change the hybrid path. Tied catalogue scores break on the
table id. Nefnir init() runs once; a second init does not change the rank.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ("cpi-2026-09-en", "gdp-2025-is", "women-share-2026-en")


def _questions() -> list[dict]:
    found = []
    seen = set()
    for line in (ROOT / "evalset" / "track3-questions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in IDS and row["id"] not in seen:
            found.append(row)
            seen.add(row["id"])
    return found


def _tops(questions: list[dict]) -> list[str]:
    from grund.rerank import maybe_rerank
    from grund_index.catalogue import Catalogue

    catalogue = Catalogue.load(ROOT / "data" / "index")
    lines = []
    for row in questions:
        hits = maybe_rerank(catalogue, row["question"], catalogue.search(row["question"], k=8))
        lines.append(",".join(f"{hit.table.id}:{round(hit.score, 6)}" for hit in hits[:5]))
    return lines


def test_catalogue_search_is_stable_inside_one_process():
    questions = _questions()
    assert _tops(questions) == _tops(questions)


def test_catalogue_search_agrees_across_hash_seeds():
    code = (
        "import json, os, sys\n"
        f"sys.path[:0] = { [str(ROOT / 'indexer'), str(ROOT / 'app'), str(ROOT / 'rails')] !r}\n"
        "from pathlib import Path\n"
        "from grund.rerank import maybe_rerank\n"
        "from grund_index.catalogue import Catalogue\n"
        f"root = Path({str(ROOT)!r})\n"
        "catalogue = Catalogue.load(root / 'data' / 'index')\n"
        "wanted = set(" + repr(IDS) + ")\n"
        "for line in (root / 'evalset' / 'track3-questions.jsonl').read_text().splitlines():\n"
        "    row = json.loads(line)\n"
        "    if row['id'] not in wanted:\n"
        "        continue\n"
        "    hits = maybe_rerank(catalogue, row['question'], catalogue.search(row['question'], k=8))\n"
        "    print(row['id'] + '\\t' + ','.join(f'{hit.table.id}:{round(hit.score, 6)}' for hit in hits[:5]))\n"
    )
    runs = []
    for seed in ("0", "1"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr[-500:]
        runs.append(completed.stdout)
    assert runs[0] == runs[1]


def test_a_saved_e5_matrix_is_replaced_with_chargram(tmp_path, monkeypatch):
    """Two machines with different saved matrices still build one chargram index."""
    import numpy as np

    from grund.engine import Engine

    folder = tmp_path / "index-lang"
    folder.mkdir()
    (folder / "manifest.json").write_text('{"embedding_kind":"e5","embedding_dim":1024}', encoding="utf-8")
    np.save(folder / "embeddings.npy", np.zeros((2, 1024), dtype=np.float32))
    seen = {}

    def load_index(path):
        seen["loaded"] = str(path)
        return {"kind": "e5", "dim": 1024}

    def build_index(tables, *, embed="auto"):
        seen["embed"] = embed
        seen["tables"] = len(list(tables))
        return {"kind": "chargram", "dim": 384}

    monkeypatch.setenv("GRUND_LANG_INDEX", str(folder))
    monkeypatch.setattr("grund_lang.load_index", load_index, raising=False)
    import grund_lang.index as index_mod

    monkeypatch.setattr(index_mod, "build_index", build_index)
    engine = Engine.__new__(Engine)
    engine.catalogue = type("Cat", (), {"tables": ["a", "b"], "by_id": {}})()
    engine._lang_ready = False
    engine._lang_index = None
    # The import inside the method is `from grund_lang import load_index`.
    import grund_lang

    monkeypatch.setattr(grund_lang, "load_index", load_index)
    built = engine._language_index(required=True)
    assert seen["embed"] == "chargram"
    assert built == {"kind": "chargram", "dim": 384}
    assert engine._language_index(required=True) == built
