"""Dense recall that cannot reorder the ranker's prefix.

The table vectors are the 384-d int8 checkpoint already packed for the hall:
one row per published table, in first-seen order of that index's
``tables.jsonl.gz``. The query uses the same checkpoint and the ``query: ``
prefix. A missing archive leaves retrieval unchanged.

``mix_ids`` keeps the ranker's first ``protect`` hits, then fills the
remaining shortlist slots with dense-only ids the ranker missed, then any
ranker hits that still fit.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import numpy as np

_DIM = 384
_MODEL = "multilingual-e5-small"


def mix_ids(lexical: list[str], dense: list[str], k: int, protect: int, *, extend: bool = False) -> list[str]:
    """Keep the ranker's prefix. Fill later slots with ids it never returned.

    ``protect`` is how many leading ranker hits stay in front. A dense id
    already in the ranker's list is not a miss. When ``extend`` is set and
    the whole ranker list is protected, the misses are appended after it
    instead of pushing a ranker hit out of the top ``k``.
    """
    if k <= 0:
        return []
    ranker: list[str] = []
    for table_id in lexical:
        if table_id not in ranker:
            ranker.append(table_id)
    if not ranker:
        return [table_id for table_id in dense if table_id][:k]
    width = min(max(protect, 1), k, len(ranker))
    head = ranker[:width]
    seen = set(ranker)
    missed: list[str] = []
    for table_id in dense:
        if not table_id or table_id in seen:
            continue
        missed.append(table_id)
        seen.add(table_id)
    if extend and width >= min(k, len(ranker)):
        return ranker[:k] + missed
    return (head + missed + ranker[len(head) :])[:k]


def _stem(table_id: str) -> str:
    base = table_id.split("#", 1)[0]
    if base.endswith(".px"):
        base = base[:-3]
    return base


def _read_ids(path: Path) -> list[str]:
    opener = gzip.open if str(path).endswith(".gz") else open
    seen: set[str] = set()
    found: list[str] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            stem = _stem(str(row.get("id") or ""))
            if not stem or stem in seen:
                continue
            seen.add(stem)
            found.append(stem)
    return found


def _is_small_index(path: Path) -> bool:
    matrix = path / "embeddings.npy"
    manifest_path = path / "manifest.json"
    ids = path / "tables.jsonl.gz"
    if not ids.is_file():
        ids = path / "tables.jsonl"
    if not matrix.is_file() or not ids.is_file() or not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if int(manifest.get("embedding_dim") or 0) != _DIM:
        return False
    model = str(manifest.get("embedding_model") or "")
    return "small" in model


def _model_dir(path: Path) -> Path | None:
    if (path / "tokenizer.json").is_file() and _onnx(path) is not None:
        return path
    return None


def _onnx(directory: Path) -> Path | None:
    for candidate in (
        directory / "onnx" / "model_int8.onnx",
        directory / "model_int8.onnx",
        directory / "onnx" / "model.onnx",
        directory / "model.onnx",
    ):
        if candidate.is_file():
            return candidate
    return None


def locate() -> tuple[Path, Path] | None:
    """Hall model directory and the matching 384-d index, when both are present."""
    raw_model = os.environ.get("GRUND_E5_DIR", "").strip()
    model = _model_dir(Path(raw_model)) if raw_model else None
    raw_index = os.environ.get("GRUND_E5_SMALL_INDEX", "").strip()
    index = Path(raw_index) if raw_index else None
    if index is None:
        shared = os.environ.get("GRUND_INDEX", "").strip()
        if shared and _is_small_index(Path(shared)):
            index = Path(shared)
    if index is None and model is not None:
        sibling = model.resolve().parents[1] / "index-e5-small"
        if _is_small_index(sibling):
            index = sibling
    if model is None or index is None or not _is_small_index(index):
        return None
    return model, index


class SmallRecall:
    """Query encoder plus the precomputed table matrix."""

    def __init__(self, model_dir: Path, index_dir: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        onnx = _onnx(model_dir)
        if onnx is None:
            raise FileNotFoundError(f"no onnx file in {model_dir}")
        ids_path = index_dir / "tables.jsonl.gz"
        if not ids_path.is_file():
            ids_path = index_dir / "tables.jsonl"
        self.ids = _read_ids(ids_path)
        self.matrix = np.load(index_dir / "embeddings.npy")
        if self.matrix.ndim != 2 or self.matrix.shape[1] != _DIM or len(self.ids) != len(self.matrix):
            raise ValueError(
                f"small matrix {getattr(self.matrix, 'shape', None)} does not match {len(self.ids)} ids"
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("GRUND_E5_THREADS", "4"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(onnx), sess_options=options, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        pad = self.tokenizer.token_to_id("<pad>")
        if pad is None:
            pad = 1
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=pad, pad_token="<pad>")
        self.inputs = {node.name for node in self.session.get_inputs()}
        self._cache: dict[str, np.ndarray] = {}
        self.model_name = _MODEL

    def encode(self, question: str) -> np.ndarray:
        cached = self._cache.get(question)
        if cached is not None:
            return cached
        encoded = self.tokenizer.encode("query: " + question)
        ids = np.asarray([encoded.ids], dtype=np.int64)
        mask = np.asarray([encoded.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feed)[0]
        weights = mask.astype(np.float64)[:, :, None]
        pooled = (hidden.astype(np.float64) * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        vector = pooled[0]
        norm = float(np.linalg.norm(vector) or 1.0)
        unit = (vector / norm).astype(np.float32)
        if len(self._cache) > 4000:
            self._cache.clear()
        self._cache[question] = unit
        return unit

    def top(self, question: str, k: int) -> list[tuple[str, float]]:
        if k <= 0 or len(self.ids) == 0:
            return []
        scores = self.matrix @ self.encode(question)
        width = min(k, len(scores))
        chosen = np.argpartition(-scores, width - 1)[:width]
        chosen = chosen[np.argsort(-scores[chosen], kind="stable")]
        return [(self.ids[int(index)], float(scores[int(index)])) for index in chosen]


_CHANNEL: SmallRecall | None = None
_TRIED = False


def channel() -> SmallRecall | None:
    """The shared hall channel. ``GRUND_RECALL=0`` leaves it unloaded."""
    global _CHANNEL, _TRIED
    mode = os.environ.get("GRUND_RECALL", "fill").strip().lower()
    if mode in {"0", "off", "false", "no"}:
        return None
    if _TRIED:
        return _CHANNEL
    _TRIED = True
    found = locate()
    if found is None:
        return None
    try:
        _CHANNEL = SmallRecall(*found)
    except Exception as exc:  # noqa: BLE001 - retrieval still runs on the ranker
        _CHANNEL = None
        print(f"small recall unavailable: {type(exc).__name__}: {exc}", flush=True)
    return _CHANNEL


def reset_channel() -> None:
    """Drop the cached encoder so a later env change can load it."""
    global _CHANNEL, _TRIED
    _CHANNEL = None
    _TRIED = False
