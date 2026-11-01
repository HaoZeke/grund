"""Passage embeddings.

Prefers intfloat/multilingual-e5-large via FastEmbed (ONNX, no GPU). FastEmbed
0.9 does not ship multilingual-e5-small; the large model is the e5 checkpoint
that build includes, and its language coverage includes Icelandic. Queries and
passages use the e5 prefixes. If the weights cannot be downloaded, a hashed
character n-gram vector is used and the manifest records that fact so queries
use the same function the index was built with.
"""

from __future__ import annotations

import os
import zlib
from pathlib import Path

import numpy as np

E5_MODEL = "intfloat/multilingual-e5-large"
DIM = 384


def _chargram(text: str, dim: int = DIM) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    padded = f" {text.lower()} "
    encoded = padded.encode("utf-8", errors="ignore")
    for size in (3, 4, 5):
        if len(encoded) < size:
            continue
        for start in range(len(encoded) - size + 1):
            digest = zlib.crc32(encoded[start : start + size])
            sign = 1.0 if digest & 1 else -1.0
            vector[digest % dim] += sign
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector


class Embedder:
    def __init__(self, kind: str = "auto", model_name: str = E5_MODEL) -> None:
        self.model_name = model_name
        self.kind = "chargram"
        self._model = None
        self.error: str | None = None
        if kind == "chargram":
            return
        cache = os.environ.get("FASTEMBED_CACHE_PATH")
        if cache:
            Path(cache).mkdir(parents=True, exist_ok=True)
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name)
            self.kind = "e5"
        except Exception as exc:  # noqa: BLE001 - fallback is the product behaviour
            self.error = f"{type(exc).__name__}: {exc}"
            self.kind = "chargram"

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self.kind == "e5" and self._model is not None:
            prefixed = [f"passage: {text}" for text in texts]
            rows = [np.asarray(vector, dtype=np.float32) for vector in self._model.embed(prefixed)]
            matrix = np.vstack(rows)
        else:
            matrix = np.vstack([_chargram(text) for text in texts])
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (matrix / norms).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        if self.kind == "e5" and self._model is not None:
            vector = np.asarray(next(self._model.embed([f"query: {text}"])), dtype=np.float32)
        else:
            vector = _chargram(text)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector.astype(np.float32)
