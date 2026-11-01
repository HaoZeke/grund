#!/bin/sh
# Cold rebuild of Grund. Unset means the shipped behaviour:
# a stated answer is refused when the ranker and hybrid do not fully agree,
# catalogue look-alike rerank is on, and a bare vísitala or verðlag
# maps to the consumer price index. The logistic cut in calibrator.json
# stays off (GRUND_CALIBRATE=logistic turns it on; cut 0.9 refuses
# correct figures). GRUND_ABSTAIN_RULE=off states every gated answer.
# GRUND_RERANK=0 and GRUND_QUERY_FIX=0 turn those two off.
# The language-index shortlist is not reranked.
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-indexer:evalset:rails:app:lang}"
export GRUND_PATH="${GRUND_PATH:-ranker}"
export GRUND_RAIL="${GRUND_RAIL:-python}"
export GRUND_FUSION="${GRUND_FUSION:-rrf}"
unset GRUND_CALIBRATE
unset GRUND_ABSTAIN_RULE
unset GRUND_RERANK
unset GRUND_QUERY_FIX
unset GRUND_JUDGESIM
if [ ! -f data/index/tables.jsonl.gz ]; then
  echo "missing data/index. Build the catalogue index before asking." >&2
  exit 1
fi
if [ ! -f data/index-lang/embeddings.npy ] || [ ! -f data/index-lang/manifest.json ]; then
  echo "missing data/index-lang. Run: sh lang/fetch-index.sh" >&2
  exit 1
fi
echo "Grund cold start"
echo "  GRUND_PATH=$GRUND_PATH"
echo "  GRUND_RAIL=$GRUND_RAIL  (python does not need the Ruby rail on :9293)"
echo "  GRUND_FUSION=$GRUND_FUSION"
echo "  GRUND_CALIBRATE unset  (logistic cut is off; logistic turns it on)"
echo "  GRUND_ABSTAIN_RULE unset  (refuse unless the two paths agree)"
echo "  GRUND_RERANK unset  (catalogue stage is on; 0 disables it)"
echo "  GRUND_QUERY_FIX unset  (bare vísitala and verðlag map to CPI)"
echo "  GRUND_LEXICON unset  (everyday-word map is on; 0 disables it)"
echo "  GRUND_RECALL unset  (fill appends e5-small after the ranker top 20; 0 disables it)"
echo "  GRUND_JUDGESIM unset"
echo "  catalogue and value index present"
