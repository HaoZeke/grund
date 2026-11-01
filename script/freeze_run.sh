#!/bin/sh
# One command for the frozen tree. Frame on-wave plus GRUND_UNEMP_GUARD.
# AGREE_HYB, TOPIC_PRIOR, TOPICMAP, and LEVEL_CHANGE_VETO stay unset.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)

export GRUND_FRAME=1
export GRUND_IS_KANG_TOWN=1
export GRUND_IS_KANG_JOBS=1
export GRUND_IS_KANG_SHARE=1
export GRUND_IS_KANG_JOBSEX=1
export GRUND_IS_KANG_BIRTHS=1
export GRUND_IS_KANG_REGION=1
export GRUND_IS_KANG_GDP=1
export GRUND_IS_KANG_CPI=1
export GRUND_IS_KANG_WAGE=1
export GRUND_IS_KANG_STAYS=1
export GRUND_IS_KANG_QUARTER=1
export GRUND_IS_KANG_POP=1
export GRUND_IS_KANG_TRADE=1
export GRUND_IS_KANG_GUARD=1
export GRUND_IS_COVER=1
export GRUND_IS_ORIGIN=1
export GRUND_IS_BUILDING=1
export GRUND_RC1=1
export GRUND_RC2=1
export GRUND_RC3=1
export GRUND_REDTEAM2=1
export GRUND_REDTEAM3=1
export GRUND_MEASURE_GUARD=1
export GRUND_SIBLING_GUARD=1
export GRUND_SEXDIFF=1
export GRUND_TOTAL_CELL=1
export GRUND_UNEMP_GUARD=1
export GRUND_PLANNER=deterministic
export GRUND_E5=small
export GRUND_RAIL=ruby
export GRUND_INDEX="${GRUND_INDEX:-$ROOT/data/index}"
export GRUND_LANG_INDEX="${GRUND_LANG_INDEX:-$ROOT/data/index-lang}"
export GRUND_E5_DIR="${GRUND_E5_DIR:-$ROOT/data/models/small}"
export GRUND_E5_SMALL_INDEX="${GRUND_E5_SMALL_INDEX:-$ROOT/data/index-e5-small}"
export PYTHONPATH="$ROOT/lang:$ROOT/indexer:$ROOT/evalset:$ROOT/rails:$ROOT/app"

# Pinned public inputs. Nothing here is a secret.
VANGRAIL_URL=https://github.com/HaoZeke/vangrail
VANGRAIL_REV=e9aa7a1e9942dc089a5c469e54017251b05b105a
E5_REPO=Xenova/multilingual-e5-small
E5_REV=761b726dd34fb83930e26aab4e9ac3899aa1fa78

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

# Vangrail 0.3.0, the Ruby cell-claim rail. Cloned once into vendor/.
if [ -z "${RUBYLIB:-}" ]; then
  if [ ! -f "$ROOT/vendor/vangrail/lib/vangrail.rb" ]; then
    echo "fetching vangrail $VANGRAIL_REV into vendor/vangrail" >&2
    mkdir -p "$ROOT/vendor"
    git clone --quiet "$VANGRAIL_URL" "$ROOT/vendor/vangrail"
    git -C "$ROOT/vendor/vangrail" checkout --quiet "$VANGRAIL_REV"
  fi
  export RUBYLIB="$ROOT/vendor/vangrail/lib"
fi

# multilingual-e5-small, int8 ONNX, for dense recall. Fetched once from the
# public repo and checked against the bytes the frozen run used.
# GRUND_NO_FETCH=1 skips this and runs the n-gram fallback.
fetch_e5_file() {
  rel="$1"
  want="$2"
  dest="$GRUND_E5_DIR/$rel"
  if [ -f "$dest" ] && [ "$(sha256_of "$dest")" = "$want" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  curl -fsSL -o "$dest.part" "https://huggingface.co/$E5_REPO/resolve/$E5_REV/$rel" || return 1
  if [ "$(sha256_of "$dest.part")" != "$want" ]; then
    echo "sha256 mismatch for $rel; not using it" >&2
    rm -f "$dest.part"
    return 1
  fi
  mv "$dest.part" "$dest"
}

if [ "${GRUND_NO_FETCH:-0}" != "1" ]; then
  echo "checking $E5_REPO@$E5_REV in $GRUND_E5_DIR" >&2
  fetch_e5_file tokenizer_config.json a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b || true
  fetch_e5_file tokenizer.json 0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39 || true
  fetch_e5_file onnx/model_int8.onnx 4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c || true
fi

# Value-label index. load_index only needs it present and loadable: the
# engine rebuilds the value matrix from the catalogue with chargram on start.
if [ ! -f "$GRUND_LANG_INDEX/manifest.json" ] || [ ! -f "$GRUND_LANG_INDEX/embeddings.npy" ]; then
  echo "building $GRUND_LANG_INDEX from data/catalogue.jsonl (chargram)" >&2
  python3 -m grund_lang build \
    --catalogue "$ROOT/data/catalogue.jsonl" \
    --source "$ROOT/data/index" \
    --out "$GRUND_LANG_INDEX" \
    --embeddings chargram
fi

# The chat page is the prebuilt UI committed in app/web/dist. It is built
# here only if that directory is missing. Without it only /api/ask answers
# and / returns 404.
if [ ! -f "$ROOT/app/web/dist/index.html" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "building the web UI into app/web/dist (npm ci && npm run build)" >&2
    (cd "$ROOT/app/web" && npm ci && npm run build)
  else
    echo "npm is not installed, so app/web/dist was not built." >&2
    echo "The API still answers on /api/ask, but http://localhost:8741/ returns 404." >&2
    echo "Install Node.js 20 or newer, then run: cd app/web && npm ci && npm run build" >&2
  fi
fi

if [ -f "$GRUND_E5_DIR/tokenizer.json" ] && [ -f "$GRUND_E5_DIR/onnx/model_int8.onnx" ] \
  && [ -f "$GRUND_E5_SMALL_INDEX/manifest.json" ] && [ -f "$GRUND_E5_SMALL_INDEX/embeddings.npy" ]; then
  echo "retrieval: dense recall on (multilingual-e5-small, $GRUND_E5_SMALL_INDEX) plus the ranker on $GRUND_INDEX" >&2
else
  echo "retrieval: n-gram fallback (character n-gram index $GRUND_INDEX); dense recall is off" >&2
fi
echo "rail: RUBYLIB=$RUBYLIB" >&2

unset GRUND_AGREE_HYB GRUND_TOPIC_PRIOR GRUND_TOPICMAP GRUND_LEVEL_CHANGE_VETO \
  GRUND_SHARE_RECOMPUTE GRUND_SUBGROUP_GUARD GRUND_URBAN_AGE GRUND_SERIES_PICK \
  GRUND_YEAREND GRUND_UNIT_ASK GRUND_CALIBRATE GRUND_FUSION GRUND_JUDGESIM \
  GRUND_BIND_COVER GRUND_BIND_NAMED || true

if ! curl -sf --max-time 2 http://127.0.0.1:9293/v1/health 2>/dev/null | grep -q '"ok":true'; then
  ruby "$ROOT/script/grund_guard_server.rb" >/tmp/grund-freeze-rail.log 2>&1 &
  echo $! >/tmp/grund-freeze-rail.pid
  i=0
  while [ "$i" -lt 30 ]; do
    if curl -sf --max-time 2 http://127.0.0.1:9293/v1/health 2>/dev/null | grep -q '"ok":true'; then
      break
    fi
    i=$((i + 1))
    sleep 1
  done
fi

exec python3 -m uvicorn grund.api:app --host 0.0.0.0 --port 8741
