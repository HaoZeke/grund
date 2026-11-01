"""Pack the retrieval index, its BM25 postings, and the ONNX weights.

The packed tree loads with no network. The weights are about 2.2 GB, so the
tarball is produced by ``python -m grund_lang pack`` on a machine that
already has them cached, then carried into the room.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from grund_lang.index import load_index, save_bm25


def _copy_tree(source: Path, dest: Path) -> None:
    """Copy a cache, keeping hard links so the weight file is stored once."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["cp", "-a", str(source), str(dest)])


def stage_bundle(index_dir: Path, cache_dir: Path, stage: Path) -> Path:
    """Write ``stage/grund-index-lang`` with relative catalogue paths."""
    index_dir = Path(index_dir)
    cache_dir = Path(cache_dir)
    has_weights = any(cache_dir.glob("models--*")) or (cache_dir / "model.onnx").exists()
    if not has_weights:
        raise FileNotFoundError(f"no embedding weights under {cache_dir}")
    root = Path(stage) / "grund-index-lang"
    if root.exists():
        shutil.rmtree(root)
    packed = root / "index"
    packed.mkdir(parents=True)
    for name in ("embeddings.npy", "owners.npy", "bm25.json.gz"):
        source = index_dir / name
        if source.exists():
            shutil.copy2(source, packed / name)
    if not (packed / "bm25.json.gz").exists():
        previous = os.environ.get("GRUND_EMBED_CACHE")
        os.environ["GRUND_EMBED_CACHE"] = str(cache_dir)
        try:
            save_bm25(load_index(index_dir), packed)
        finally:
            if previous is None:
                os.environ.pop("GRUND_EMBED_CACHE", None)
            else:
                os.environ["GRUND_EMBED_CACHE"] = previous
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    catalogue = manifest.get("catalogue")
    metadata = manifest.get("metadata")
    if catalogue and Path(catalogue).exists():
        shutil.copy2(catalogue, packed / "catalogue.jsonl")
        manifest["catalogue"] = "catalogue.jsonl"
    if metadata and Path(metadata).exists():
        meta_out = packed / "metadata"
        meta_out.mkdir()
        source_meta = Path(metadata)
        tables = source_meta / "tables.jsonl.gz"
        if not tables.exists():
            tables = source_meta / "tables.jsonl"
        if not tables.exists():
            raise FileNotFoundError(f"no tables file in {source_meta}")
        shutil.copy2(tables, meta_out / tables.name)
        manifest["metadata"] = "metadata"
    manifest["source"] = "metadata"
    manifest["offline"] = True
    (packed / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _copy_tree(cache_dir, root / "onnx")
    return root


def pack_bundle(index_dir: Path, cache_dir: Path, out: Path) -> dict:
    """Write one tar of the index, the BM25 postings, and the ONNX cache."""
    out = Path(out)
    stage = out.parent / (out.name + ".stage")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        root = stage_bundle(index_dir, cache_dir, stage)
        if out.exists():
            out.unlink()
        with tarfile.open(out, "w") as archive:
            archive.add(root, arcname="grund-index-lang")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    digest = hashlib.sha256()
    with out.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {"path": str(out), "bytes": out.stat().st_size, "sha256": digest.hexdigest()}
