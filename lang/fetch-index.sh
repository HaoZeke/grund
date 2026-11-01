#!/bin/sh
# Build one offline tarball: index, BM25 postings, and the ONNX weights.
# The weights are about 2.2 GB, so the tar is not stored beside this script.
# Run this once where the weights are cached, or once with a network so the
# checkpoint can be fetched into GRUND_EMBED_CACHE. Carry the tar into the
# room. Loading it does not use the network.
#
# The checkpoint fastembed asks for is intfloat/multilingual-e5-large. The
# weights it stores are the ONNX build Qdrant/multilingual-e5-large-onnx.
# If that host does not answer, the same repo is requested from
# hf-mirror.com. If neither answers, the index is a character n-gram
# vector and this script does not write the tar.
#
# Measured where both indexes could be built, headings only, same catalogue:
#   dev-A primary top-1: chargram 0.800 (160/200), e5 0.815 (163/200).
#   dev-A recall at 5: 0.963 for both.
#   dev-short-tune primary top-1: chargram 0.171 (24/140), e5 0.179 (25/140).
set -eu

ROOT="${GRUND_ROOT:-.}"
INDEX="${GRUND_LANG_INDEX:-$ROOT/data/index-lang}"
CACHE="${GRUND_EMBED_CACHE:-$ROOT/embed-cache}"
OUT="${1:-$ROOT/grund-index-lang.tar}"
CATALOGUE="${GRUND_CATALOGUE:-}"
SOURCE="${GRUND_METADATA:-$ROOT/data/index}"
EMBEDDINGS="e5"

export GRUND_EMBED_CACHE="$CACHE"

have_weights() {
  [ -d "$CACHE" ] && [ -n "$(find "$CACHE" -name 'model.onnx' -print -quit 2>/dev/null)" ]
}

fetch_fastembed() {
  python3 - << 'PY'
import os
from fastembed import TextEmbedding
TextEmbedding("intfloat/multilingual-e5-large", cache_dir=os.environ["GRUND_EMBED_CACHE"])
PY
}

fetch_snapshot() {
  endpoint="$1"
  HF_ENDPOINT="$endpoint" HF_HUB_ENABLE_HF_TRANSFER=0 python3 - << 'PY'
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="Qdrant/multilingual-e5-large-onnx",
    cache_dir=os.environ["GRUND_EMBED_CACHE"],
    endpoint=os.environ.get("HF_ENDPOINT") or None,
)
PY
}

if ! have_weights; then
  echo "embedding weights are not in $CACHE; fetching them once" >&2
  mkdir -p "$CACHE"
  if ! fetch_fastembed; then
    echo "fastembed could not fetch intfloat/multilingual-e5-large; trying the ONNX repo" >&2
    if ! fetch_snapshot "https://huggingface.co"; then
      echo "huggingface.co did not serve Qdrant/multilingual-e5-large-onnx; trying hf-mirror.com" >&2
      fetch_snapshot "https://hf-mirror.com" || true
    fi
  fi
fi

if ! have_weights; then
  echo "e5 checkpoint is not fetchable. Building a chargram index instead." >&2
  echo "dev-A primary top-1 falls from 0.815 to 0.800. Recall at 5 stays 0.963." >&2
  echo "dev-short-tune primary top-1 falls from 0.179 to 0.171." >&2
  EMBEDDINGS="chargram"
fi

if [ ! -f "$INDEX/embeddings.npy" ]; then
  if [ -z "$CATALOGUE" ]; then
    echo "set GRUND_CATALOGUE to catalogue.jsonl before the first build" >&2
    exit 1
  fi
  PYTHONPATH="${PYTHONPATH:-lang:indexer}" python3 -m grund_lang build \
    --catalogue "$CATALOGUE" \
    --source "$SOURCE" \
    --out "$INDEX" \
    --embeddings "$EMBEDDINGS"
fi

if [ "$EMBEDDINGS" = "chargram" ]; then
  echo "chargram index is at $INDEX. No ONNX tar was written." >&2
  exit 0
fi

PYTHONPATH="${PYTHONPATH:-lang:indexer:app}" python3 -m grund_lang pack \
  --index "$INDEX" \
  --cache "$CACHE" \
  --out "$OUT"

python3 - "$OUT" << 'PY'
import hashlib, sys
path = sys.argv[1]
digest = hashlib.sha256()
with open(path, "rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
print(digest.hexdigest(), path)
PY

cat << EOF

Load on a laptop with no network, after unpacking:

  tar -xf $OUT -C /opt/grund
  GRUND_EMBED_CACHE=/opt/grund/grund-index-lang/onnx \\
    PYTHONPATH=lang:indexer:app \\
    python3 -c "from grund_lang import load_index; load_index('/opt/grund/grund-index-lang/index')"

EOF
