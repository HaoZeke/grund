"""Build the searchable index from a crawl catalogue.

Usage:
    python -m grund_index.build --catalog data/catalog/tables.jsonl --out data/index
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

import numpy as np

from grund_index.catalogue import document_text
from grund_index.embed import E5_MODEL, Embedder
from grund_index.model import Table


def load_catalog(path: Path) -> list[Table]:
    from grund_index.catalogue import edition_from_json

    grouped: dict[str, Table] = {}
    order: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            table_id = payload.get("id")
            if not table_id:
                continue
            table = grouped.get(table_id)
            if table is None:
                table = Table(id=table_id)
                grouped[table_id] = table
                order.append(table_id)
            edition = edition_from_json(payload)
            table.editions[edition.lang] = edition
    return [grouped[table_id] for table_id in order]


def passage(table: Table) -> str:
    """Short text for the embedding model: titles, path, variable names."""
    parts = [table.id]
    for edition in table.editions.values():
        parts.append(edition.title)
        parts.extend(edition.path_texts)
        for variable in edition.variables:
            parts.append(variable.text)
            labels = [label for _code, label in variable.values[:12] if label]
            parts.extend(labels)
    text = " ".join(parts)
    return text[:1800]


def build(catalog: Path, out: Path, kind: str = "auto") -> dict:
    tables = load_catalog(catalog)
    if not tables:
        raise SystemExit(f"no tables in {catalog}")
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path("data/models").resolve()))
    embedder = Embedder(kind=kind, model_name=E5_MODEL)
    if kind == "e5" and embedder.kind != "e5":
        raise SystemExit(f"e5 embeddings were requested but not loaded: {embedder.error}")
    vectors = embedder.embed_passages([passage(table) for table in tables])
    np.save(out / "embeddings.npy", vectors)
    tables_path = out / "tables.jsonl.gz"
    both = 0
    by_db: dict[str, int] = {}
    with gzip.open(tables_path, "wt", encoding="utf-8") as handle:
        for table in tables:
            if len(table.editions) > 1:
                both += 1
            for edition in table.editions.values():
                by_db[edition.db] = by_db.get(edition.db, 0) + 1
                record = {
                    "id": table.id,
                    "lang": edition.lang,
                    "db": edition.db,
                    "title": edition.title,
                    "path": edition.path,
                    "path_texts": edition.path_texts,
                    "url": edition.url,
                    "updated": edition.updated,
                    "notes": edition.notes,
                    "variables": [
                        {
                            "code": variable.code,
                            "text": variable.text,
                            "time": variable.time,
                            "elimination": variable.elimination,
                            "values": variable.values,
                        }
                        for variable in edition.variables
                    ],
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    manifest = {
        "tables": len(tables),
        "editions": sum(len(table.editions) for table in tables),
        "bilingual": both,
        "by_db_editions": by_db,
        "embedding_kind": embedder.kind,
        "embedding_model": E5_MODEL if embedder.kind == "e5" else "chargram-384",
        "embedding_error": embedder.error,
        "embedding_dim": int(vectors.shape[1]) if len(vectors) else 0,
        "document_example": document_text(tables[0])[:240],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the Grund hybrid index")
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog/tables.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/index"))
    parser.add_argument("--embeddings", choices=["auto", "e5", "chargram"], default="auto")
    args = parser.parse_args(argv)
    manifest = build(args.catalog, args.out, kind=args.embeddings)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
