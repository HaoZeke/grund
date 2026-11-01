# Questions for the 28 October intro

Online introduction, 28 October 2026, 16:00. Kickoff and any extra data, 30 October. The room is 31 October–1 November in Reykjavík. These are the points to confirm before treating this repository as the entry rather than as preparation.

## What may be written before the event

1. Is code written before 31 October allowed in the submission, or only code written in the room?
2. If some preparation is allowed, which of these are in bounds: a cached PxWeb catalogue, a built index, an evaluation set with gold cells, the rail specification, the application itself?
3. If preparation is not allowed, is it still acceptable to arrive with notes and an empty repository and retype from the design docs?

The repository is split so this can be answered by directory. `indexer/`, `evalset/`, `rails/`, and `docs/` are the reusable pieces. `app/` is the chat application.

## Data and network

4. Will judging call the live PxWeb API, or a snapshot handed out on 30 October?
5. May metadata be crawled and cached before 30 October? The crawl here is rate-limited and cached. English allows 100 calls per 10 seconds, Icelandic 300, both cap a response at 100,000 cells.
6. What, if anything, is released on 30 October that is not already on px.hagstofa.is?
7. Is outbound internet available during the 48 hours, or only the machine and the Statistics Iceland endpoints?
8. Are external model APIs allowed, or only a local server on the DGX Spark and whatever LUMI exposes?

## Machines and the demo

9. What is actually on the DGX Spark (GPU memory, whether vLLM or llama.cpp is the expected server, whether the network can reach PxWeb from that machine)?
10. Does the demo have to run on that machine, or is a laptop acceptable for the UI if the model is on the Spark?
11. Which language should the five-minute demo be in?
12. Is a source card with table id, API URL, cells, and retrieval time the citation format the judges want, or is there a required layout?

## Figures that move

13. Where should a preliminary or revised flag be read from? This entry looks at the table title, the footnote comments, and the metadata note. If the flag lives somewhere else, the card should read that field.
14. Are precomputed embeddings allowed, or must the index be built during the event?

## Rules of the contest

15. Do the 2024 criteria still apply, and with what weights: usefulness, functionality, clarity, near-production-readiness?
16. Team size, submission format, and what has to be handed over at the end (repository, slide, running URL)?
17. Licence the organisers want on the entry.

## Known limits to say out loud if asked

- The committed index is the English tree from the earlier crawl plus a finished Icelandic walk: 2,104 tables, 3,911 editions, 1,807 bilingual. English was not walked again. Historical tables and the environment database did not gain editions.
- A question that names a subject the catalogue does not publish is refused before search. Coverage is titles, variable names, and value labels. Month names on a value label do not count. The token "mars" does not count from titles either, because it is both March and the planet. A date such as "í mars 2024" is not an entity. It is not a minimum search score. `evalset/heldout.jsonl` checks that split and is not part of the 91-question score. "drekar" is in scope: it is a customs heading for grapnels.
- Two indexes of this catalogue are scored in `docs/eval.md`: hashed character n-grams in `data/index`, and `intfloat/multilingual-e5-large` (FastEmbed 0.9, ONNX, dimension 1,024) in `data/index-e5`. The app uses `data/index` unless `GRUND_INDEX` is set.
- The plain language-model baseline is scored only when `GRUND_LLM_BASE_URL` is set. The run in `docs/eval.md` used `Qwen/Qwen2.5-7B-Instruct` quantized Q4_K_M (`bartowski/Qwen2.5-7B-Instruct-GGUF`, file `Qwen2.5-7B-Instruct-Q4_K_M.gguf`, GGUF type `Q4_K - Medium`, 7,615,616,512 parameters) served by llama.cpp b11778 on CPU, scored on this 2,104-table catalogue. The same server was Grund's planner. A hybrid planner on that server constrains the query to a shortlist of tables and their value labels, and falls back to the deterministic plan on low confidence. A larger model on the DGX Spark has not been scored. If the URL is unset, the harness records `not_run`.
- Hag, the organiser demo, answers CPI and internal migration and does not show a source card. Grund's comparison with Hag is in `docs/eval.md`.
- "What was the consumer price index in 2024?" has a year and no month. The scored default cites the annual average, `VIS01005.px`. `GRUND_CLARIFY_MONTH=1` instead asks for a month or for the annual average and states no figure. The flag stays off until the organisers say which behaviour they want. A question that already says "annual average" or "ársmeðaltal" is not affected.
