# Retrieval handoff

Call these in order. `analyze`, `retrieve`, and `bind_values` keep the signatures they already had. `retrieve_pair` and `extend_allowed` are additions.

## Once, at startup

```python
from grund_lang import load_index

index = load_index("data/index-lang")
```

`GRUND_EMBED_CACHE` must point at the unpacked ONNX directory from `grund-index-lang.tar` (`grund-index-lang/onnx`). No network. The BM25 postings are in the index directory, so this load does not lemmatize the catalogue again.

Offline:

```text
tar -xf grund-index-lang.tar -C /opt/grund
GRUND_EMBED_CACHE=/opt/grund/grund-index-lang/onnx \
  PYTHONPATH=lang:indexer:app \
  python3 -c "from grund_lang import load_index; load_index('/opt/grund/grund-index-lang/index')"
```

Build the tar with `sh lang/fetch-index.sh`. The script fetches `intfloat/multilingual-e5-large` through the ONNX package `Qdrant/multilingual-e5-large-onnx`, and retries that download against `hf-mirror.com` when the first host does not answer. The tar is about 2.2 GB and is not stored next to this note. If neither host can be reached, the script builds a chargram index and does not write the tar. On dev-A that fallback's primary top-1 is 0.800 against 0.815 for the checkpoint, and recall at 5 is 0.963 for both. On dev-short-tune the primary top-1 is 0.171 against 0.179.

## One question, one table

```python
from grund_lang import retrieve, bind_values, extend_allowed

candidates = retrieve(index, question, k=10)
# candidates[0].table_id is the public id, without .px
# look the edition up in the catalogue you already hold
codes = bind_values(question, edition)
```

`codes` is one `ValueChoice` per variable, or two when the question names both ends of a range. Send those PxWeb codes. Do not re-rank with the gold table id.

## A comparison (two tables)

```python
from grund_lang import retrieve, retrieve_pair, bind_values

pair = retrieve_pair(index, question, k=5)
shortlist = retrieve(index, question, k=10)
```

`retrieve` on a comparison puts the first series first and the second series second. The old fusion put whichever half matched more strongly in front, so the first table missed top-1 even when both were in the top 5. `pair` is the same two tables as an explicit pair. Bind each half against its own edition:

```python
left_codes = bind_values(left_half, left_edition)
right_codes = bind_values(right_half, right_edition)
```

`question_halves` in `grund_lang.pair` is the split, if you need the half strings. `retrieve` itself is unchanged and still returns one ranked list.

## After the fetch

```python
allowed = extend_allowed(cell_allow_list, fetched_rows, derived)
```

Pass `allowed` to the number check. Digits in fetched labels and codes (`01-02-04`) and the magnitude of a negative cell are allowed. A figure that is neither a fetched cell nor one of those digits is still blocked.

`LangEngine` does this sequence itself: `retrieve` for the shortlist, `bind_values` for the codes, `extend_allowed` around the existing check. Fetch, arithmetic, and the sentence stay in the engine.

```python
from grund_lang.driver import LangEngine

engine = LangEngine(catalogue, index, client=client)
result = engine.ask(question)
```

## What the ranker prefers

The lexical index contains, in both languages, the title, the subject headings, the variable names, and every value label. A heading embedding is fused with that lexical rank. A value label that occurs on only a few tables is a name: the table that lists it is pulled into a shortlist of 20 even when the name is not in the title. Sex and other labels that appear on many tables are not names.

Those 20 are reordered from the table metadata. A specific title that adds words the question never used loses to the series with fewer added words. A one-word heading is not that series. An overview path wins a tie. The year span is the span printed on the title. A later update stamp breaks a remaining tie. No question phrase and no table id is a rule.

Coverage comes from the title span and the year codes, not from the table id. A historical twin with the same title loses to the current series unless the question asks for an old period.

- A title the question already recites, when it has two or more content words, is boosted. A one-word heading such as "Population" is not.
- A series filed under an earlier or historical path is down-weighted when the question does not name an old period and does not recite that title. If it is still tied with the current copy, the rerank puts the current copy first.
- A series whose coverage ends before 2015 is down-weighted when the asked years are not inside that span.
- A title that runs "from 2015" is treated as still open.

The question embedding is cached on the text. A comparison used to embed each half twice; the second call is the cached vector. The passage matrix is unchanged, so this does not move the ranking.

A bare topic question prefers the headline series. The signals are the subject tree, a title that states the topic and does not add a split, broad scope, and recency. They are not table ids.

- Population of Iceland, with or without a year, uses the resident-population overview. "By country of birth", citizenship, origin, and method-change tables lose when the question names no such split. On those variables, Iceland is where people live, so the total cell is kept. "Born in" or "citizenship" still selects that country.
- Population of a named place uses the current population series whose title names that place, not a census whose coverage ended decades earlier.
- GDP / landsframleiðsla uses the national-accounts table whose title is that aggregate, and the line that is the aggregate rather than exports, a per-capita figure, or an index.
- Overnight stays in Iceland uses the all-accommodation total, not the by-municipality table and not a satellite split.
- The dollar rate uses the exchange-rate series whose title names the currency, not a debt table that happens to carry a dollar row.

`analyze(question)` is optional. `retrieve` and `bind_values` call it. It is the place that reads lemmas, compounds, `á höfuðborgarsvæðinu`, and `síðustu fimm ár` (the last N years published on that table).

## parse-then-tools

This is the main path. The ranker is only a fallback, used when the parse is rejected or no table can map every filter.

```python
from grund_lang.pxtools import MetaStore, answer
from grund_index.client import PxWebClient

store = MetaStore("data/index/tables.jsonl.gz")
client = PxWebClient(cache_dir="data/cache")
result = answer(question, store, client, ranker=index.search, live=True)
```

`live=False` uses only the offline metadata index. `live=True` also calls the PxWeb database search (`/api/v1/{lang}/{database}?query=`) on the five databases and merges those ids with the local score.

### Parse

`parse_request` returns `{measure, filters, period, op, unit_hint}`. `op` is `level`, `change`, `pct_change`, `sum`, `share`, or `compare`. `period.kind` is `point`, `range`, or `latest`. Years sit only in `period`. `validate_request` rejects a missing field, an unknown op, or any digit in the measure, the filters, or the unit hint. A rejected parse does not call PxWeb.

An external model may emit the same object. It has to pass `validate_request` before a tool runs. `parse_request_model` asks the engine's chat client for that object. The prompt is the subject tree to depth three, a sample of table titles, and five requests whose measures are subject headings. Digits are rejected outside `period`, and a rejected object is sent back once.

On dev-short-tune, before any POST, the deterministic measure landed on the gold table's subject path for 93 of 140 questions. The model landed for 92 of 140. Twenty-four model replies failed validation, most of them by putting the year into `filters`. Among the 116 valid replies the land rate was 92/116. Icelandic headings are the weak spot for the deterministic parser: 30 of 69 exact tokens, against 34 of 69 for the model. Allowing a shared six-character stem raises the deterministic rate to 125 of 140, so most of that miss is a lemma against a plural heading. The client was pointed at Qwen2.5-3B-Instruct. No base URL was set, and the default 14B id was not being served. The dev-A parse comparison was still running when this note was written.

### Tools

1. Search the local metadata by the measure words and the filter words (title, subject path, variable names, value labels, both languages). Overview paths get a small bonus. The live database search adds its own score when it is enabled.
2. Fetch that table's metadata from the local index.
3. Map each filter value onto a value code through the labels in either language. Map the period onto the time variable. Every other variable is set to its total, or left out when the metadata says it can be eliminated. A variable with no total and no requested value is an unrequested breakdown: the table is not a candidate.
4. POST that selection. The op is applied in code to the returned cells (`level` is the cell, `change` is later minus earlier, `pct_change` and `share` are percents).

The claim shape for CellClaimRail is the same shape the ranker already passes in:

```text
value, op, unit, period,
cells[]: table_id, coords, labels, value, period, latest_period, api_url, web_url, retrieved_at
```

`period` on a cell is the time code (`2018`, `2019M06`). On the claim it is that code, or `2018 to 2020` when the operation cites two. Labels are keyed by the variable text and do not include the time variable. The rail recomputes a change from `cell["period"]`. A claim that only stored the year under `coords` could not be recomputed, so the rail returned `undeclared_number` and the integrated tools path refused. The ranker path treats that reason as a pass, which is why the two paths disagreed.

`value` is the op on those cells. `rail_block` returns a reason when the value is not that op or a cell is incomplete. On a block the next mapped table is tried, up to four. Then the result is a refusal: `refused`, `reason`, and `candidates` with `table_id`, `api_url`, and `web_url`. `confidence` is the gap between the chosen table's search score and the next hit, divided by the chosen score.

A total is an exact label (`Total`, `Alls`, `Samtals`, …), a label that starts with total and says all (`Total - all activities`), or a label that ends with `total` (`Long-term foreign debt, total`). `Total revenue` stays a line in an account list. A variable whose values are years is the time variable even when the edition left the time flag unset.

`source` is `tools`, `hybrid`, or `ranker`. `mode="tools"` searches the metadata index. `mode="hybrid"` takes the ranker's top 20 and keeps only the tables whose measure words hit a title, a subject heading, or a variable name, ordered by that score plus the unit hint. `mode="ranker"` tries the ranker's own order and does not rescore. A table with no measure hit is not a candidate. The ranker is also the fallback when the parse is rejected.

### Integrated coverage

`eval/score.sh` on the integrated tree, dev-A, `GRUND_PATH=tools`: coverage 30.5%, 139 no-bind refusals. Hybrid: coverage 55%, 90 no-bind. The local tools and hybrid runs on the same rows covered 0.630 and 0.655. `eval/dev-A-path-diff.json` records 100 python-right rows that tools turned into no bind, and 58 that hybrid turned into no bind.

Of those 100, 58 gold tables had no exact total label, 11 had a Year variable with the time flag unset, and 8 asked for a month the gold table does not publish. The rest mapped and posted, and the cell rail then refused the claim because `period` was missing. A change was the common case: 18 of the mapped dev-A rows failed as `undeclared_number` until the time code was written on `period`. With that field the same synthetic cells pass `check_claim`.

`GRUND_PATH` is read by `score_heldout.py`, which calls `grund_lang.harness.install_path`. Unset, the scorer stays on catalogue search. The local value rule (first gold figure, absolute gap at most 0.05) and `answer_is_right` (every gold figure in the sentence, every part's table in `accepted`) differ by that table check. On the saved deterministic run the official score is 148/200 and the local rule is 155/200. On the hybrid run through `score.sh` the official accuracy when answering is 23/131 and the local rule is 40/131, the same 0.305 measured earlier. The 0.36 versus 82% gap is the catalogue binder against the tool shortlist, not a different tolerance.

### Grading

A cell matches gold when the absolute difference is at most 0.05. That allows an index to round. It does not allow a different count. A different table is not accepted unless the value matches under that rule. The same subject path with a different number is a different series or a different unit, not an equivalent cell.

On dev-short-tune, before this rescoring, 116 questions were answered and 4 values matched. Of the other 112: 3 were the right table but a different geography category, 36 were another table on the same subject path with a different number, and 73 were a different subject. None of the mismatches had the gold value. The rule was not widened.

### Comparison

Accuracy is the strict value match among questions that returned a cell. Hybrid is the best joint of coverage and accuracy on dev-A and dev-B.

| mode | tune cov / acc | dev-A cov / acc | dev-B cov / acc | total ms |
|---|---|---|---|---|
| tools | 0.679 / 0.105 | 0.630 / 0.278 | 0.690 / 0.246 | 487 / 635 / 1269 |
| hybrid | 0.693 / 0.103 | 0.655 / 0.305 | 0.700 / 0.329 | 765 / 1144 / 1134 |
| ranker | 0.471 / 0.136 | 0.510 / 0.363 | 0.550 / 0.364 | 614 / 1026 / 1012 |

Search in hybrid and ranker includes the embedding shortlist, about 0.3 to 0.5 s. The metadata search alone is about 10 ms. The post is the rest.

### Confidence

`confidence` is the tune-set accuracy of the raw margin. Raw is half the gap to the next candidate and half the share of measure words found on the chosen table. On the tune set that raw score was right 0.048 of the time below 0.20, 0.132 from 0.20 to 0.80, and 0.50 above 0.80. The 0.40 to 0.80 band was not better than the band below it, so they are one step. Refusing below 0.05 keeps the upper steps: on the check set, scored once, coverage falls from 0.733 to 0.350 and accuracy rises from 0.136 to 0.286. Refusing below 0.20 leaves one answer, and it was correct.

dev-short-check, hybrid, one pass: coverage 0.733, accuracy 0.136.

### dev-short

`eval/dev-short.jsonl` is 200 short single-series questions, English and Icelandic, built from the subject tree rather than table titles. It is hashed before it is split. `dev-short-tune.jsonl` (140) is the set to measure while changing the path. `dev-short-check.jsonl` (60) is scored once at the end. The hash is recorded in `nlp/NOTES.md`.

## A share is a ratio of two cited cells

A question that asks what fraction a named part is of a whole is operation `share`. Examples of the shape, not a fixed list: "what proportion of … were …", "what percentage of … were …", "hve stórt hlutfall … voru …". A published rate ("what was the unemployment rate") and a percent change ("by what percentage did it rise") stay `level` and `yoy_pct`.

`LangEngine` then does three things:

1. Retrieves the headline series for the topic (the resident population table for a population share, the national accommodation table for a share of overnight stays). A breakdown the question did not name, such as country of birth or municipality, still loses.
2. Binds two codes on the same variable: the named part and the total. `binding.group_var`, `binding.part_code`, and `binding.whole_code` are those codes. Both are in the PxWeb selection, so the fetch returns both cells.
3. Sets `binding.operation` to `share`. The notes contain `ratio share_percent (part / whole) * 100` and `recompute the percent from the cited part and total; do not supply a number`.

The percent is not stored on the binding. `grund.arithmetic.share_percent` is `(part / whole) * 100`, and `grund.compute` records it as derived name `share_percent` with `inputs` equal to the two raw cell strings. That is the only figure that may be stated.

CellClaimRail should recompute that formula from the two cited cells and block the turn when the sentence states any other number. A drafted sentence must not be the source of the percent. A lone count, including the part cell by itself, is not an answer to a ratio question. Both cells are cited.
