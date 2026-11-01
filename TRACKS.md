# The three tracks

Read from the repositories released on 29 October 2026, and from the 28 October introduction slides that sit in the track 1 and track 2 repositories. The slides are the same file in both.

The brief is one chatbot. A person asks in everyday Icelandic or English. The answer names a figure, a unit, and an official Statistics Iceland source. The three tracks differ in where the numbers come from and what the team is expected to build.

No file in the three repositories, and no slide in the introduction, forbids code written before the event. The slides say to read the track README and check the code, the data, and the compute before the event starts. The track 3 README says to do the setup before the hackathon if the download is slow. Judging, still marked as a draft on the slides, scores the result: functionality, presentation, usability, clarity, deployment, and user value, each from 1 to 5. The solution is expected to be free of charge. Hardware does not earn points. Grund's retrieval, checks, and chat page were written before these repositories were published. The adaptation to the track 3 question file was done after reading them. Confirm that split with the organisers before treating the earlier work as part of the submission.

## Track 1 — prepared retrieval

Repository: `hIngolfur/hagstofa-ai-track1-`.

Task. A local retrieval backend is the starting point. The team builds a web chat, connects it to that backend, and tests answers. Extending the data with `ingest.py` is optional.

Data. Two stores, neither of them the full catalogue.

- An Excel workbook, `VIS01002_20260810-092754.xlsx`, sheet `VIS01002`, loaded into memory as a price-index dictionary.
- A Chroma collection named `hagstofa_master`. The README points at a Google Drive archive (`chroma_db_master.zip`, about 190 MB) with `chroma_db/` and `data.db`. The code looks for the directory `chroma_db_master`. The collection that is described in the slides is domestic migration. Embeddings are BAAI/bge-m3.

Evaluation. There is no question file and no scoring script. The documented check is one `curl` against `POST /query` with an Icelandic migration question about women and men moving from the north to the capital in 2024. The slides ask for a browser demo: a real question, the retrieved values, units, a source, an ambiguous query, a response time, and a known limitation.

Deliverables. A web interface with loading and error states, answers that show values, units, and sources, and a test with curl and with the browser. The slides also list a working prototype and 5–7 slides. Setup is Python 3.10+, a virtualenv, and a local Ollama model (`llama3` in the code, `hagstofa-ai:latest` on the slides).

## Track 2 — direct PxWeb

Repository: `hIngolfur/hagstofa-ai-track2-`.

Task. Query the live PxWeb API. The team extends table selection and the GET/POST calls, supports more than one question in a call, and builds the web chat. There is no vector index.

Data. The starter ships three Icelandic tables in a Python dictionary: consumer price index `VIS01002.px`, population key figures `MAN00000.px`, and internal migration `MAN01002.px`. The slides describe a later catalogue of 2,009 tables in memory (`hagstofa_catalog.json`), with keywords and dimension codes. That file is not in the repository.

Evaluation. There is no question file and no scoring script. The documented check is `POST /query` with the English sentence "Get population statistics for municipalities in 2024". The slides ask for the same demo shape as track 1, and for invalid selections to be clarified rather than guessed.

Deliverables. Same as track 1: web chat, curl, browser, sources and units. Python 3.10+ and network access to `https://px.hagstofa.is`. No local model is required by the starter; the slides still list a language-model answer step as team work.

## Track 3 — retrieval on a supercomputer

Repository: `SyedMuhammadAzhar/gagnvist-starter`.

Task. Answer questions about Iceland, in Icelandic or English, from the official tables. The starter is a four-step pipeline: find a table from an embedding of its card, let a model choose categories, read the cells from a local `data.px` file, and let a model write the sentence. The program checks category codes, adds the source, and flags numbers in the sentence that were not in the cells. The starter reads one table. Questions that need a calculation, or two tables, are the gap the README points at.

Data. A release dated 18 October 2026, shipped as six zip parts under `data-release/`, unpacked by `gagnvist get-data`. The cards README says 1,886 tables that exist in both languages (3,772 cards). The unpacked tree is about 5.7 GB. Five corrections to the data's own README are in `docs/pxweb.md`. Cards, with titles, dimensions, categories, and the period covered, are in `cards/`. A vector index of those cards, made with the shared embedding model, is in `index/`. Numbers are read from `data.px`, not from the live API. The live API was used on 29 October 2026 only to check the question file.

Evaluation. `gagnvist evaluate` answers `questions/examples.jsonl`: 30 questions, each in English and Icelandic, 60 in all. Ten per language at each of three levels.

| Level | What it asks | Per language |
| --- | --- | --- |
| easy | one number from one table | 10 |
| medium | a calculation from several cells of one table | 10 |
| hard | numbers from two tables | 10 |

An answer is right only when it states every expected number and each number comes from one of that part's accepted tables. A right number from any other table is reported as "other table" and is not counted. Rounding is allowed down to the digits the answer actually prints: the written form may be no coarser than half a unit in the last digit it shows. Thousands separators in either language, and spaces, count. A sign is ignored. Some questions also accept the same number in another unit (GDP in billions or trillions as well as millions of krónur). The command prints a table of right answers by level and language and writes a JSON file under `local/evaluations/`.

Deliverables. The slides' track 3 line is: use the supercomputer to create or improve embeddings and retrieval, connect that to a web chat, and in the demo compare retrieval quality and say what the machine did. The starter's own bar is to raise the evaluate count. Shared settings live in `gagnvist.toml` (LUMI host `lumi.csc.fi`, project `project_462001820`, a shared chat model and a shared embedding model reached through an SSH tunnel). Personal settings (LUMI username, SSH key, team key) stay in `.env` and are not committed. The data licence is Creative Commons Attribution 4.0, with Statistics Iceland named as the source.

## Which track Grund should enter

Track 3.

Grund already finds a table, checks a structured query against the table's own codes, fetches the cells, does the arithmetic in code, and answers with a source card, in both languages. That is the track 3 pipeline, with the calculation done in code rather than left to a model. The track 3 question file is the only scored set in the three repositories, and it covers the full bilingual catalogue rather than a price index plus one migration collection (track 1) or three hardcoded tables (track 2). The track 3 repository is also the one that documents the supercomputer: a shared OpenAI-compatible server on LUMI, and a job script that serves an open-weights model on the MI250X nodes. Track 1 and track 2 do not.

Grund keeps its own index and still reads cells from the live PxWeb API. The track 3 scorer does not require the unpacked `data.px` files if the live cells match the question file. The question file's own note says those cells were checked against the live API on 29 October 2026. The run recorded in `evalset/results-track3.json` uses that scorer's number and table rules on Grund's answers.

## Score on the 60

Deterministic planner, character n-gram index, live PxWeb, 30 October 2026. A right answer states every expected number and cites an accepted table for each part. Intervals are Wilson 95%.

| Slice | Right |
| --- | --- |
| All 60 | 38/60 = 63.3% [50.7, 74.4] |
| English | 29/30 = 96.7% [83.3, 99.4] |
| Icelandic | 9/30 = 30.0% [16.7, 47.9] |
| Easy (20) | 16/20 = 80.0% [58.4, 91.9] |
| Medium (20) | 9/20 = 45.0% [25.8, 65.8] |
| Hard (20) | 13/20 = 65.0% [43.3, 81.9] |

English easy and English hard are 10/10. The one English miss is the wage-index change in points from August 2025 to August 2026: the answer was 7.8 from `LAU04001.px`, and the expected figure is 61.6 from `LAU04000.px`. Icelandic medium is 0/10. The Icelandic misses are mostly the wage index and overnight stays, where the inflected word does not yet retrieve the table, plus births and immigrants landing on a neighbour table. Those are listed in `IDEAS.md`.
