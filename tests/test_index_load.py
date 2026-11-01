import gzip
import json
from pathlib import Path

import numpy as np

from grund_index.catalogue import Catalogue
from grund_index.embed import Embedder


def test_load_keeps_the_manifest_width(tmp_path: Path):
    record = {
        "id": "VIS01000.px",
        "lang": "en",
        "db": "Efnahagur",
        "title": "Consumer price index",
        "path": ["Efnahagur"],
        "path_texts": ["Economy"],
        "url": "https://example.test/VIS01000.px",
        "updated": None,
        "notes": None,
        "variables": [
            {"code": "Month", "text": "Month", "time": True, "elimination": False, "values": [["2024M06", "2024M06"]]}
        ],
    }
    with gzip.open(tmp_path / "tables.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    matrix = np.ones((1, 1024), dtype=np.float32)
    np.save(tmp_path / "embeddings.npy", matrix)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"embedding_kind": "chargram", "embedding_model": "chargram-384", "embedding_dim": 1024}),
        encoding="utf-8",
    )
    catalogue = Catalogue.load(tmp_path, embedder=Embedder(kind="chargram"))
    assert catalogue.matrix is not None
    assert catalogue.matrix.shape == (1, 1024)
    assert catalogue.kind == "chargram"
