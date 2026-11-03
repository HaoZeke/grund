# Grund

Grounded answers over Statistics Iceland.
Ask a question in Icelandic or English.
Grund picks a PxWeb table, checks the query against that table's real variables, fetches the cells, does the arithmetic in code, and answers with a source card.

This is an entry for GAGNAÞON 2026.
Grund is not an official Statistics Iceland product.
The project stack is NVIDIA OpenShell, snelnext, vangrail, and ljos.

## Live demo

<https://201-79-5-118.sslip.io/>

Username `grund`; the password is in the submission email.

## How Grund gets data from Statistics Iceland

Grund reads the public PxWeb API at `px.hagstofa.is`.
The default deterministic mode needs no API key.

1. **Plan.**
   The question is parsed into a measure, a place, a period, and any arithmetic it asks for.
   `GRUND_PLANNER=deterministic` is the default and the mode every frozen score was measured in.
2. **Search the catalogue.**
   `data/catalogue.jsonl` lists 2,104 Statistics Iceland tables.
   Retrieval (`app/grund/retrieve.py`) ranks them with BM25 over titles and paths, a character n-gram (chargram) index, and `multilingual-e5-small` embeddings in `data/index-e5-small`.
   Value codes come from the labels each table publishes, through the index in `data/index-lang`.
3. **Query PxWeb.**
   `PxWebClient` in `indexer/grund_index/client.py` POSTs a JSON query to the table's URL under `https://px.hagstofa.is/pxen/api/v1/en` or `https://px.hagstofa.is/pxis/api/v1/is`.
   The body names each variable code with `{"filter": "item", "values": [...]}`, and the validator (`app/grund/validator.py`) checks those codes against the table's real variables before the request goes out.
   A locked plan grants that one `pxweb.query` call, so the posted table id and query have to match the grant.
4. **Cache.**
   Responses are stored in `data/cache` (GET and POST bodies, keyed by a hash of the request), so a repeated question does not hit PxWeb again.
5. **Compute in code.**
   Differences, changes, and shares are computed in `grund.arithmetic` from the fetched cells, never by a language model.
6. **Check before showing.**
   The number-grounding rail requires every number in the answer to come from a fetched cell, from `grund.arithmetic`, or from a time key on those cells.
   The Ruby cell-claim rail, built on [vangrail](https://github.com/HaoZeke/vangrail) 0.3.0 (`rails/ruby/grund_cell_claim_rail.rb`, called through `rails/grund_rails/vangrail_client.py`), recomputes the figure from the cells.
   If the checker is offline, Grund refuses to start.
   If a claim does not check out, the card shows no figure and says why.

Each answer card links back to the table on `px.hagstofa.is`.

## Caching and rate limits

PxWeb metadata and data queries are stored on disk and read from that cache first.
Metadata is kept for seven days and a data query for six hours.
Set `GRUND_PX_META_TTL` and `GRUND_PX_DATA_TTL` in seconds to change those times.
All PxWeb calls share one limiter.
It allows one call each ten seconds and two calls at a time.
Statistics Iceland answered our scoring runs with HTTP 429, too many requests.
Each of those answers asked us to retry after ten seconds, so the limiter waits ten seconds between calls.
Each API publishes its limit at `?config`.
English allows 100 calls per ten seconds, and Icelandic allows 300.
Both limits count calls per IP address.
When a 429 or 503 carries a Retry-After header, Grund waits that long.
Otherwise the wait grows and jitters, and one question stops waiting after fifteen seconds.
If an older copy is on disk when that limit is reached, the answer says it is cached and gives the fetch time.
If there is no copy, the answer says Statistics Iceland is rate-limiting requests and to try again in a minute.
`python -m grund_index.mirror` builds a dated snapshot of the catalogue under `GRUND_MIRROR_DIR`.
That directory is not part of this repository.
A snapshot manifest stores the table id, the PxWeb updated time, the fetch time, and a sha256.
Grund answers from the snapshot through the same query, and the sentence shows the data-as-of date.
The live API is used only when a table is missing or the snapshot is stale, with the same limiter.
Table selection reads `data/index/tables.jsonl.gz`.
That index lists every table id, title, variable and value label in both languages.
While the index is loaded, table selection never calls the live database search.
The optional Extrapolate sidecar uses the same cache and limiter and stops after twelve tool calls.

These settings change the limiter.
The process reads them when it starts the shared limiter or a question.

| Setting | Default | Meaning |
| --- | --- | --- |
| `GRUND_PX_MAX_CALLS` | `1` | Calls allowed in each window. Values above 10, a tenth of the published English limit, are lowered to 10. |
| `GRUND_PX_WINDOW` | `10` | Window length in seconds, the published `timeWindow`. |
| `GRUND_PX_CONCURRENCY` | `2` | Calls in flight at once, at most `GRUND_PX_CONCURRENCY_MAX` (default 4, never above 10). |
| `GRUND_PX_QUESTION_WAIT` | `15` | Seconds one question may wait for the API before it answers from the cache or says it is rate-limited. |
| `GRUND_PX_TIMEOUT` | `60` | Seconds one HTTP call may take. |

We chose the concurrency cap, the cache times, the question wait, the call timeout and the retry backoff.
No published or measured number backs them.
`indexer/grund_index/client.py` names each number and its setting.
The backoff settings are `GRUND_PX_BACKOFF`, `GRUND_PX_BACKOFF_MAX`, `GRUND_PX_NETWORK_RETRY_MAX`, `GRUND_PX_PAUSE_MAX` and `GRUND_PX_ATTEMPTS`.


## Example questions

These answer with a figure and a source card:

- How many overnight stays were there in registered accommodation in Iceland in 2022?
- What was the unemployment rate in Iceland in the third quarter of 2024?
- How many more men than women lived in Iceland on 1 January 2024?
- By how many points did the consumer price index rise from June 2023 to June 2024?
- What were the wage index and the consumer price index in March 2024?

In Icelandic:

- Hve margar gistinætur voru á skráðum gististöðum á Íslandi árið 2022?
- Hvert var atvinnuleysi á Íslandi á þriðja ársfjórðungi 2024?

This one should be refused:

- What is the minimum wage in Iceland?

Iceland has no statutory minimum wage; pay floors are set in collective agreements, and Statistics Iceland publishes no table for it.
A refusal is a feature: Grund would rather show no number than one it cannot trace to a published cell.

## Extrapolate (optional)

Extrapolate is an opt-in toggle on the chat page.
It is off by default, and it never edits the verified answer.
When it is on, each answer that is not a refusal gets an Extrapolate button.
The button adds a separate panel, headed "Beyond the data · AI-generated", below the verified answer.

The panel text comes from any OpenAI-compatible endpoint.
The server default is set with `GRUND_LLM_BASE_URL`, `GRUND_LLM_MODEL`, and `GRUND_LLM_API_KEY`; all three are optional.
If none are set and the browser sends no settings, `/agent/extrapolate` answers 503 and says to add an endpoint.

Each visitor can also bring their own endpoint under "Model settings (optional)" inside the Extrapolate section.
The panel has three optional fields: an https base URL, an API key in a password field, and a model name.
The values stay in the browser.
They go in `sessionStorage` by default, or in `localStorage` only when "Remember on this device" is ticked.
Saving to one store removes the copy in the other, and Clear removes both.
On each Extrapolate request the browser sends whichever values are set as the headers `X-Grund-LLM-Base`, `X-Grund-LLM-Key`, and `X-Grund-LLM-Model`.
It sends them only from a secure context (an https page).
Over plain http the panel is disabled, nothing is sent, and the page says so.
The sidecar uses them for that request only.
It does not write them to the decision log, which records the model as `custom`, and it redacts the key from any model text it returns.
Blank fields fall back to the server default, so with nothing set the deployment behaves as before.
A custom base URL must come with its own key, because the server key is never sent to a host the browser chose.
A custom base URL must also be https and resolve only to public addresses, and redirects are not followed, so the sidecar cannot be pointed at localhost, the metadata service, or the private network.
The request then connects to the address that was checked, with the certificate verified against the URL's host name, so a second DNS answer cannot move it (DNS rebinding).
On the server's own key, a model name from the browser is used only when it is listed in `GRUND_LLM_MODELS` (comma-separated); otherwise the server's model is used and the reply says `model_ignored`.
With the visitor's own key, any model name is passed through.
No key is in the repository or the build.

### Keeping the key out of the reverse proxy's logs

The sidecar never logs these headers, but the web server in front of it can.
Until the filter below is applied on a host, a request that fails there (sidecar down, dial error, timeout) can write the key to that web server's error log.

Caddy logs request headers in two places, and it redacts only `Authorization`, `Cookie`, `Set-Cookie`, and `Proxy-Authorization` by default:

- The access log of each site. A `log` block in the site filters only that site's access logger.
- `http.log.error`, which writes the full request headers of every request that ends in a 5xx. It goes to the default logger, so a site `log` block does not cover it. A global `log default` filter does.

Header names are logged in Go's canonical form, so `X-Grund-LLM-Key` is logged as `X-Grund-Llm-Key`.
Both blocks are in [`deploy/Caddyfile`](deploy/Caddyfile), which is the versioned config.
In the global options block:

```caddyfile
{
	log default {
		output stderr
		level INFO
		format filter {
			request>headers>X-Grund-Llm-Key delete
			request>headers>X-Grund-Llm-Base delete
		}
	}
}
```

In each site:

```caddyfile
log {
	format filter {
		request>headers>X-Grund-Llm-Key delete
		request>headers>X-Grund-Llm-Base delete
	}
}
```

Keep the level at INFO, because `reverse_proxy` logs request headers at DEBUG.
Plain http must never proxy: the `http://IP` site in `deploy/Caddyfile` only redirects to the https host.
[`deploy/grund-vps-remote.sh`](deploy/grund-vps-remote.sh) renders that file for a host, checks it with `caddy adapt`, refuses a plain-http site that proxies, and reloads Caddy.

To check a config, run `caddy adapt --config deploy/Caddyfile --adapter caddyfile`, then `CADDY=/path/to/caddy deploy/check-caddy-logs.sh`.
The script runs the config on local ports, forces 502s with a dummy key (one upstream drops the connection and one is not listening), and searches every log line and every file Caddy wrote for the key and the base.
It also runs a control copy without the global block, which has to leak, so a pass means the check can see the error log.

The model can call three kinds of tool:

- PxWeb table search, metadata, and cell fetch, on `px.hagstofa.is` only.
- A calculator that parses arithmetic and does not execute code.
- Search and page fetch on official `island.is` pages only, at most two pages for each answer.

Every new number has to carry a mark: `[fetch:TABLE]`, `[calc:N]`, `[source:URL]`, or `(inferred)`.
`elab_guard` drops any sentence with an unmarked new number.
It also drops a marked number that the cited fetch, calculation, or page does not contain.
The "From the data" part may use only numbers that are already in the verified answer or the question.
Each panel carries a visible label and a zero-width watermark signed with an HMAC (hash-based message authentication code).
Each call writes one line to a decision log in JSON Lines format, and `/agent/stats` sums the log.

All scores in this repository come from the deterministic path only.
Extrapolate played no part in any score.

The code is in [`extrapolate/`](extrapolate/): `explain.py` is the small HTTP service, and `elab_guard.py` is the number guard with its tests.

### Next step: a decision gate

An optional `JEV_API_KEY` would let a fast, cheap classification model (Jev by TypeSafe AI) decide whether a question justifies the extra, more expensive model calls before Extrapolate runs.
This check is not wired in yet.

## Frozen submission

This tree is the frozen GAGNAÞON entry: base `2637b291` plus the frame build and `GRUND_UNEMP_GUARD`.
Clone the public repository as usual with `git clone https://github.com/HaoZeke/grund.git`.
If you start from the `grund-pub.bundle` file instead, clone it with `git clone -b main grund-pub.bundle grund`.
One command starts the Ruby rail and the API with that environment.
Nothing else is switched on.

```bash
sh script/freeze_run.sh
```

The API listens on port 8741.
The rail listens on `127.0.0.1:9293`.
Set `GRUND_INDEX`, `GRUND_LANG_INDEX`, `GRUND_E5_SMALL_INDEX`, and `GRUND_E5_DIR` if those directories live elsewhere.

On a clean clone the script needs Python 3.12 with `fastapi`, `uvicorn`, `numpy`, `httpx`, `onnxruntime`, and `tokenizers`, plus Ruby 3.1 or newer, `git`, and `curl`.
The chat page comes prebuilt in `app/web/dist`, so Node.js is only needed to rebuild it.
On its first run it does four things, then prints which retrieval path is live:

1. It clones [vangrail](https://github.com/HaoZeke/vangrail) at commit `e9aa7a1e9942dc089a5c469e54017251b05b105a` (version 0.3.0) into `vendor/vangrail` and sets `RUBYLIB` to its `lib/`, unless `RUBYLIB` is already set.
2. It fetches the `multilingual-e5-small` int8 ONNX (Open Neural Network Exchange) weights into `data/models/small` from the public `Xenova/multilingual-e5-small` repository at revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78`.
   That is the ONNX export of `intfloat/multilingual-e5-small`.
   The three files are checked against the sha256 of the files the frozen run used: `onnx/model_int8.onnx` (118,054,593 bytes) `4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c`, `tokenizer.json` `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`, `tokenizer_config.json` `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b`.
   Set `GRUND_NO_FETCH=1` to skip the download.
3. The chat page is committed prebuilt in `app/web/dist`.
   If that directory is missing, the script builds it with Node.js 20 or newer:

```bash
cd app/web && npm ci && npm run build
```

If `app/web/dist` is missing and `npm` is not installed, the script prints that command and starts anyway.
The API then answers on `/api/ask`, but `http://localhost:8741/` returns 404.

4. If `data/index-lang` is missing, the script builds the value-label index from the committed catalogue:

```bash
PYTHONPATH=lang:indexer:evalset:rails:app python3 -m grund_lang build --catalogue data/catalogue.jsonl --source data/index --out data/index-lang --embeddings chargram
```

The engine only needs that index to be present and loadable.
On start it rebuilds the value matrix from the catalogue with character n-grams, so the stored embeddings do not change an answer.

The script then prints `retrieval: dense recall on` when the e5-small weights and `data/index-e5-small` are both present, and `retrieval: n-gram fallback` when either is missing.
The fallback still answers, but its numbers were not measured for the freeze.

These index files are in the repository:

| File | Bytes | sha256 |
| --- | ---: | --- |
| `data/catalogue.jsonl` | 1,965,140 | `7dea57eebb8b8f2496565be32ee9d4a8aae3d8deda71f2a4398909893a11f138` |
| `data/index/embeddings.npy` | 3,231,872 | `cd5c4054c9522f9e6ea5535ff975be13a0ef7f7ce945a321ae67abadde64daac` |
| `data/index/manifest.json` | 604 | `3a2a11cc8e241a5ec28d2fb4ad0d62ce55d9179a1c32b80cf4fe899f63a147d4` |
| `data/index/tables.jsonl.gz` | 3,867,877 | `f4a0b252295870d117bb86a3b89e78927bf22b6d7d59161cdad051b44f393683` |
| `data/index-e5-small/embeddings.npy` | 3,231,872 | `2bca4e9f78218d05bd7476762e7d0256a26e0c5666708a0335be976917b5b685` |
| `data/index-e5-small/manifest.json` | 608 | `aabd7cd9f2df944369a1727ae65e176a12ce21935e34374c74ae51771082be60` |
| `data/index-e5-small/tables.jsonl.gz` | 3,867,877 | `f4a0b252295870d117bb86a3b89e78927bf22b6d7d59161cdad051b44f393683` |
| `data/index-e5/embeddings.npy` | 8,618,112 | `854c8b7af8b611cd450fdbefcf16a5093313cc247714736db55d8cfa5f55dfb4` |
| `data/index-e5/manifest.json` | 617 | `9d73cc370dd9b6291619da17294d629ae1f1b065c5d92c57526785aa1b64433e` |
| `data/index-e5/tables.jsonl.gz` | 3,867,877 | `d498b5845aa15062d9905c80829a99aabd30cace2a787c914be018b31cdd6aff` |

### Frozen scores

These are measured on this frozen tree, with the Ruby rail and the full indexes: `data/index`, `data/index-lang`, `data/index-e5-small`, and the e5-small weights.
A question counts as right only when the sentence states the gold number and the answer cites an accepted table.
A refusal is not counted as right.
The intervals are Wilson 95% intervals on the share right.

| Set | Questions | Right | Refused | Wrong |
| --- | ---: | ---: | ---: | ---: |
| Organisers' 60 (`evalset/track3-questions.jsonl`, scored with `gagnvist evaluate`) | 60 | 45 | 15 | 0 |
| FINAL, 80 held-out questions, scored once | 80 | 59 | 17 | 4 |
| BANK, 120 development questions | 120 | 105 | 15 | 0 |

FINAL's interval is 63.2% to 82.1%.
Its four wrong answers are: the national 2021 population given for the South; total imports given for goods imports fob; hotel arrivals given for all registered accommodation; and a population stated for 2150, where the right answer is a refusal.

## Run it

These are the usage instructions.
The default deterministic mode needs no API keys.
The chat UI and the API listen on port 8741.

### Container

Run `docker compose up --build`.
That command runs `sh script/freeze_run.sh` inside a container and publishes the chat page at <http://127.0.0.1:8741/>.
API requests use the same port.
Inside the container, the Ruby rail listens on `127.0.0.1:9293`.

Python 3.12.12 and Ruby 3.2.6 are pinned in the image.
Node.js 22.23.4 compiles the page while the image builds, and the running container leaves Node out.
During the build the image clones [vangrail](https://github.com/HaoZeke/vangrail) 0.3.0 at commit `e9aa7a1e9942dc089a5c469e54017251b05b105a`.
It fetches the multilingual-e5-small int8 weights from the public `Xenova/multilingual-e5-small` repository at revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78` and checks the three sha256 values listed above.
`data/index` and `data/index-e5-small` are the copies committed in this repository.
The image build creates `data/index-lang` from `data/catalogue.jsonl`.
PxWeb is public, and the image contains no API key.

```bash
docker compose up --build
```

Stop the container with Ctrl-C, then `docker compose down`.

### Without a container

```bash
pixi install
pixi run serve
```

If pixi is not available, the same process is:

```bash
export PYTHONPATH=indexer:evalset:rails:app
python -m uvicorn grund.api:app --host 0.0.0.0 --port 8741
```

The page is the prebuilt UI committed in `app/web/dist`.
Rebuild it with `cd app/web && npm ci && npm run build` after a frontend change.
`script/freeze_run.sh` builds it only when `app/web/dist` is missing.

One question from the shell:

```bash
python -m grund "What was the consumer price index in June 2024?"
```

## Layout

Reusable pieces are outside `app/`:

| Path | What it is |
| --- | --- |
| `indexer/` | Polite PxWeb crawl, BM25, embeddings, the on-disk index |
| `evalset/` | Question generator, metrics, harness, baselines |
| `rails/` | Rail protocol and the checks. See `rails/SPEC.md` |
| `docs/` | Design, eval, demo script, questions for the 28 October intro |
| `app/` | The ask path and the chat UI |
| `tests/` | Validator, arithmetic, number grounding, binding, engine |

`Snakefile` and the tasks in `pixi.toml` call the same modules.

## Track 3 questions

The scored file is `evalset/track3-questions.jsonl` (30 questions, each in English and Icelandic).
The rules are the track's: every expected number has to be stated, and each number has to come from one of that part's accepted tables.
Wilson intervals are printed with the counts.

```bash
export PYTHONPATH=indexer:evalset:rails:app
export GRUND_PLANNER=deterministic
python3 -m grund_eval.track3 --questions evalset/track3-questions.jsonl --index data/index --out evalset/results-track3.json
```

Which track to enter, and what the other two are, is in `TRACKS.md`.
The frozen scores are in the Frozen submission section above.
The weekend script is `DEMO.md`.
What to do in the hall is `IDEAS.md`.

## Two machines

This workspace is x86_64.
The commands below were not run on an aarch64 GB10 or on an MI250X.
The deterministic score does not need a GPU.
An optional open-weights model is only a chat server that speaks the same `/v1` shape.
Grund checks the query before it fetches a cell either way.

### NVIDIA DGX Spark (aarch64, GB10)

On the machine:

```bash
uname -m          # aarch64
nvidia-smi        # the GB10
```

The scored path:

```bash
cd /path/to/grund
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi 'uvicorn>=0.32' pydantic 'numpy>=1.26' httpx
export PYTHONPATH=indexer:evalset:rails:app
export GRUND_PLANNER=deterministic
python3 -m uvicorn grund.api:app --host 0.0.0.0 --port 8741
```

In another shell, the same environment:

```bash
python3 -m grund_eval.track3
```

An optional chat model, built on the machine so the binary matches aarch64.
This is the CUDA build of llama.cpp, which is the server already used for the CPU run, with the GPU flag turned on:

```bash
cmake -B build -DGGML_CUDA=ON
cmake --build build -j
./build/bin/llama-server -m /path/to/model.gguf --host 0.0.0.0 --port 8767 -c 8192 -np 1 --reasoning off
```

```bash
export GRUND_LLM_BASE_URL=http://127.0.0.1:8767/v1
export GRUND_LLM_MODEL=the-id-passed-to-the-server
export GRUND_PLANNER=hybrid
python3 -m uvicorn grund.api:app --host 0.0.0.0 --port 8741
```

If `vllm` imports on that aarch64 image, the same idea is `vllm serve /path/to/model --host 0.0.0.0 --port 8000`, then `GRUND_LLM_BASE_URL=http://127.0.0.1:8000/v1`.
Do not assume a container tag that has not been pulled on that box.

### LUMI (AMD MI250X, ROCm)

The track 3 job script is the one to follow.
It loads `Local-LAIF` and `lumi-aif-singularity-bindings`, then runs vLLM inside the project container:

`/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260415_130625/lumi-multitorch-full-u24r70f21m50t210-20260415_130625.sif`

The job asks for `--gpus-per-node` on partition `small-g` (or `dev-g` for a short test), sets `MIOPEN_CUSTOM_CACHE_DIR` and `HF_HUB_OFFLINE=1`, and serves on a Unix socket.
A small proxy on the node accepts only requests that carry that job's key.

Log in to LUMI once over ssh from a laptop with an account in the track's project, and confirm the host key.

Using the track's own command, after `gagnvist` is installed and `.env` holds the username and the key path:

```bash
gagnvist lumi start chat MODEL_DIR --partition small-g --gpus 1
gagnvist lumi jobs
gagnvist lumi connect --job JOB_ID
```

`connect` prints three lines: the model id, a URL on `127.0.0.1` (port 8801 unless you pass another), and a key.
Give those to Grund.
Do not commit the key.

```bash
export GRUND_LLM_BASE_URL=http://127.0.0.1:8801/v1
export GRUND_LLM_API_KEY=the-job-key
export GRUND_LLM_MODEL=the-served-name
export GRUND_PLANNER=hybrid
export PYTHONPATH=indexer:evalset:rails:app
python3 -m uvicorn grund.api:app --host 0.0.0.0 --port 8741
```

Stop the job when you are done.
A chip costs the same while it sits idle.
The deterministic evaluation does not need this server.

## Models

No model is required.
With `GRUND_LLM_BASE_URL` unset, a deterministic planner selects the table and a template writes the sentence.
Set the variable to any OpenAI-compatible `/v1` server and Grund will ask it for a structured query, then still validate that query before the POST.

A local CPU score used llama.cpp b11778 and `Qwen2.5-7B-Instruct` at Q4_K_M (`bartowski/Qwen2.5-7B-Instruct-GGUF`, file `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, 7,615,616,512 parameters):

```bash
llama-server -m Qwen2.5-7B-Instruct-Q4_K_M.gguf --host 127.0.0.1 --port 8767 -c 8192 -np 1 --reasoning off -a Qwen2.5-7B-Instruct-Q4_K_M
export GRUND_LLM_BASE_URL=http://127.0.0.1:8767/v1
export GRUND_LLM_MODEL=Qwen2.5-7B-Instruct-Q4_K_M
export GRUND_PLANNER=llm
```

On a DGX Spark, a 14B instruct model fits in vLLM:

```bash
vllm serve Qwen/Qwen2.5-14B-Instruct --host 0.0.0.0 --port 8000
export GRUND_LLM_BASE_URL=http://127.0.0.1:8000/v1
export GRUND_LLM_MODEL=Qwen/Qwen2.5-14B-Instruct
export GRUND_PLANNER=auto
```

`GRUND_PLANNER=deterministic` forces the code path.
The eval harness always does that.
`GRUND_LLM_PROSE=1` lets the model rewrite the sentence; if the rewrite contains a figure that is not on the allow-list, the template is kept.

Embeddings default to `intfloat/multilingual-e5-large` through FastEmbed.
That is the e5 checkpoint FastEmbed 0.9 actually ships; `multilingual-e5-small` is not in that build.
If the weights are missing, an automatic build falls back to hashed character n-grams and the manifest says so.
`--embeddings e5` does not fall back: the build stops.
Queries must use the same function the index was built with.
`data/index` in this repository is the character n-gram index.
`data/index-e5` is multilingual-e5-large, dimension 1,024.
The server reads `data/index` unless `GRUND_INDEX` names the other directory.
Set `FASTEMBED_CACHE_PATH` to `data/models` before building or querying the e5 index.

## Rebuild

```bash
python -m grund_index.crawl --out data/catalog/tables.jsonl --cache data/cache
python -m grund_index.build --catalog data/catalog/tables.jsonl --out data/index --embeddings chargram
python -m grund_index.build --catalog data/catalog/tables.jsonl --out data/index-e5 --embeddings e5
python -m grund_eval.generate
python -m grund_eval.harness
python -m pytest -q
```

The crawl caches GET responses and skips URLs already in the catalogue, so it resumes.
The crawl makes one call each ten seconds by default, the same pace as the shared limiter.
`--rate` sets calls per second, and the crawl never goes above ten calls per ten seconds.
Stay under the published PxWeb window (English 100 calls per 10 seconds, Icelandic 300, both capped at 100,000 cells).
There is no v2 API.

## Licence and data

The code is under the MIT licence; see `LICENSE`.
The tables, titles, and cells come from Statistics Iceland (Hagstofa Íslands) and are published under CC BY 4.0.
`data/catalogue.jsonl` and the indexes in `data/` are built from that published metadata.
Grund is not an official Statistics Iceland product, and Statistics Iceland does not endorse it.

No model weights are stored in this repository.
`script/freeze_run.sh` fetches the `multilingual-e5-small` weights into `data/models/small`, as described above.
`sh lang/fetch-index.sh` fetches `intfloat/multilingual-e5-large` (ONNX build `Qdrant/multilingual-e5-large-onnx`) when you want the large checkpoint.
Without the weights, retrieval falls back to the character n-gram index in `data/index`.

## Prior work

The rails follow the protocol in [vangrail](https://github.com/HaoZeke/vangrail): one check, statuses `passed` / `modified` / `blocked`, and a locked plan that is not allowed to grow a tool call.
Grund does not shell out to the Ruby gem.
Number grounding here is deterministic, because a statistics figure has an exact cell.
See `rails/SPEC.md` and `docs/design.md`.
