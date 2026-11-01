# Evaluation

91 questions. Gold cells were read from PxWeb by `python -m grund_eval.generate` and written to `evalset/questions.jsonl`. The system under test saw only the question text. The harness forced the deterministic planner. A value is exact when it is within 0.051 of the gold figure, or within 0.1% when that is larger. A citation is correct when the table id matches, the API URL and the retrieval time are present, and every gold cell key is among the cited cells. Refusals and clarifications are not in the value denominator. Intervals are Wilson 95%.

Before search, a question is refused when one of its content words is outside the catalogue. A word counts as covered when a title, a path label, or a variable name contains it, or a value label does, except that month-name tokens on a value label do not count. The token "mars" does not count from titles either. The 1981 census title says "skólagöngu í mars", which is March, and "population of Mars" stays out of scope. A date such as "í mars 2024" is not an entity. "drekar" does count: the customs heading "Akkeri, drekar og hlutar til þeirra" (HS 73160000, anchors and grapnels) is in the catalogue, so the Icelandic dragons sentence is in scope. Synonyms and a light inflection count (women, lived, mannfjöldinn, bjuggu). Frame words such as rebase, roughly, every, and verður are not entities. This is not a search-score floor. `evalset/heldout.jsonl` has six unanswerable questions and four loosely phrased answerable ones that are not in the 91. On this run every answerable scored question stayed in scope.

Both indexes cover the same catalogue after the Icelandic walk: 2,104 tables, 3,911 editions, 1,807 of them bilingual. English editions are 1,906 and were not walked again. Icelandic editions are 2,108, up from 554. `data/index` is hashed character n-grams, dimension 384. `data/index-e5` is `intfloat/multilingual-e5-large` through FastEmbed 0.9 (ONNX, dimension 1,024). FastEmbed 0.9 does not ship `multilingual-e5-small`. The running app reads `data/index` unless `GRUND_INDEX` points at `data/index-e5`. On both indexes the demo figures are unchanged: CPI June 2024 is 630.3, the June 2025 annual change is 4.2, the female share of the 2024 population is 48.7, internal migration in 2024 is 61,299, and the CPI annual average rebased so that 2020 is 100 is 130.2 in 2024.

## What was asked

| Stratum | n | What the gold is |
| --- | ---: | --- |
| level | 36 | One published cell |
| latest | 8 | The newest period, named as such |
| yoy_official | 8 | A published change column |
| yoy_computed | 8 | A percent change computed from two cells |
| share | 10 | Part divided by the total, in code |
| rebase | 5 | An index rescaled so an earlier year is 100 |
| paraphrase | 3 | CPI change, female population, internal migration, in other words |
| unanswerable | 10 | Future years, absent topics, prompt injection |
| clarify | 3 | Reykjavík without a geography, CPI with a year and no month |

72 questions are English and 19 are Icelandic. 10 are inside the topics Hag covers (CPI and internal migration). 81 are not.

## Results

Answerable questions, n = 78.

| System | Table | Exact value | Citation |
| --- | --- | --- | --- |
| Grund, char-n-gram | 67/78 = 85.9% [76.5, 91.9] | 66/78 = 84.6% [75.0, 91.0] | 64/78 = 82.1% [72.1, 89.0] |
| Grund, multilingual-e5-large | 67/78 = 85.9% [76.5, 91.9] | 66/78 = 84.6% [75.0, 91.0] | 64/78 = 82.1% [72.1, 89.0] |
| Grund, char-n-gram, Qwen planner | 38/78 = 48.7% [37.9, 59.6] | 27/78 = 34.6% [25.0, 45.7] | 27/78 = 34.6% [25.0, 45.7] |
| Grund, char-n-gram, hybrid planner | 65/78 = 83.3% [73.5, 90.0] | 56/78 = 71.8% [61.0, 80.6] | 55/78 = 70.5% [59.6, 79.5] |
| Naive BM25 | 63/78 = 80.8% [70.7, 88.0] | 6/78 = 7.7% [3.6, 15.8] | 6/78 = 7.7% [3.6, 15.8] |
| Plain Qwen2.5-7B-Instruct Q4_K_M | 0/78 = 0% [0.0, 4.7] | 1/78 = 1.3% [0.2, 6.9] | 0/78 = 0% [0.0, 4.7] |

Naive BM25 does not read the vectors, so that row is the same on both indexes. The char-n-gram case file is `evalset/results.json`. The e5 case file is `evalset/results-e5.json`. After the share fixes the two embedding rows agree on every case: table, value, and citation. Share value is 10/10 on both. Hag's seven answerable questions are 7/7 = 100% [64.6, 100.0] on both. Outside those topics both are 59/71 = 83.1% [72.7, 90.1].

Every row in the table above is this 2,104-table catalogue. The char-n-gram, e5, and naive rows are unchanged from the deterministic harness. The two Qwen rows were rerun on the same index.

The plain model and the Grund planner row used the same local server. The weights are `Qwen2.5-7B-Instruct-Q4_K_M.gguf` from `bartowski/Qwen2.5-7B-Instruct-GGUF`, a Q4_K_M quantization of `Qwen/Qwen2.5-7B-Instruct`. llama-server (llama.cpp b11778) reports 7,615,616,512 parameters and GGUF type `Q4_K - Medium`. It ran on CPU, 8 threads, context 8,192, at `http://127.0.0.1:8767/v1`, model id `Qwen2.5-7B-Instruct-Q4_K_M`. The sentence template was left on. `GRUND_LLM_PROSE` was unset, so the model chose the query and did not rewrite the sentence. A query that fails validation three times falls back to the deterministic planner. The case file is `evalset/results-llm.json`.

Of the 78 answerable questions, the model produced the query on 75 and the deterministic fallback produced it on 3. The model’s own queries were exact on 25/75. The fallback was exact on 2/3 (`FYR04101.px` and `MAN00102.px`); the third fallback, `q024`, still refused. Shares were 0/10 and rebase values 0/5, with one rebase table right. Level was 15/36, computed year-on-year 3/8, official year-on-year 5/8, latest 3/8, paraphrase 1/3. Hag’s seven answerable questions were 3/7 = 42.9% [15.8, 75.0]. Outside those topics, 24/71 = 33.8% [23.9, 45.4].

The plain model was asked for a number from memory and was given no table. It names no source, so the citation is 0/78. The one exact value is the computed change in total waste managed from 2011 to 2012, gold 1.5 (`q053`). It refused none of the 13 withheld questions, because the prompt told it to include a number.

The hybrid row is the same model and the same char-n-gram index, with a different planner. The model sees four candidate tables. Each variable is shown with its name and the value labels that overlap the question, plus totals and the named period. llama-server constrains the reply with a JSON schema: `table_id` is one of those four, and every value code is an enum taken from that shortlist, so an illegal code cannot be emitted. Confidence is `low`, `medium`, or `high`. Low, medium, a refusal, a query that will not bind, and a high-confidence disagreement on the codes of the deterministic table all fall back to the deterministic plan. A high-confidence query is kept when its codes match that plan, or when it names a different table from the top of the shortlist. The case file is `evalset/results-hybrid.json`.

Of the 78 answerable questions, 51 kept the model query and 27 used the deterministic plan. Twenty of the fallbacks were code disagreements on the same table. The kept queries are exact on the same cells as the deterministic plan except where the model chose another table. That raised the value from 54/78 to 56/78. The gains are `q015`, `q049`, `q052`, and `q068`. The losses are `q060` (share, `VIS02500.px` instead of `VIS02000.px`) and `q082` (the table is now right and the value is not). On that run, level value is 26/36, computed year-on-year 6/8, latest 5/8, shares 5/10, and rebase 5/5. Hag’s seven answerable questions stay 6/7 = 85.7% [48.7, 97.4]. Outside those topics, 50/71 = 70.4% [59.0, 79.8]. That run used the binder from before the share fixes, so the 56/78 is not a rescore of the 66/78 deterministic row.

The naive baseline takes the top BM25 title, the latest period, and the first code of every other variable. It does not read the question and it does not refuse. On this set it lands on the gold table about as often as Grund, and the intervals overlap. It almost never lands on the gold cell. Grund's gain is the cell and the citation, not a large gain in table selection.

Questions that should be refused or clarified, n = 13.

| System | Refusal or clarify, with no figure |
| --- | --- |
| Grund, both embedding indexes | 9/13 = 69.2% [42.4, 87.3] |
| Grund, Qwen planner | 9/13 = 69.2% [42.4, 87.3] |
| Grund, hybrid planner | 9/13 = 69.2% [42.4, 87.3] |
| Naive BM25 | 0/13 = 0% [0.0, 22.8] |
| Plain Qwen2.5-7B-Instruct Q4_K_M | 0/13 = 0% [0.0, 22.8] |

On the deterministic planner, Grund refuses 9 of the 10 unanswerable questions: the future years, the prompt injections, dragons, Mars, and yesterday's temperature in Reykjavík. "Hversu margir drekar voru skráðir á Íslandi árið 2020?" is answered, because "drekar" is the grapnel term in the customs tables. Char-n-gram cites `SAM08050.px` and e5 cites `SJA07001.px`. The three clarify questions are still answered, which is why the 13-question row is 9/13. "How many women lived in Iceland in 2024, counting every age?" still matches the gold figure 187,015. Both indexes now cite `MAN43000.px` rather than `MAN00101.px`, so the table and the citation for that question are wrong and the value is right.

With the Qwen planner the withheld row is the same 9/13 as the deterministic planner. Scope still refuses six of the unanswerable questions before the model is called. The model itself refused three more (`q001`, `q002`, `q010`) and answered the dragons question from `SAM08050.px`, the same customs term the deterministic planner cites. It answered both Reykjavík questions (`MAN00000.px`, `MAN03200.px`) and the CPI year with no month from `VIS01005.px`. Questions the scope check refuses never reach the model.

## Hag, and everything else

Hag answers CPI and internal migration and shows no cell.

| Slice | Grund value, char-n-gram | Naive value |
| --- | --- | --- |
| Hag's topics (7 answerable, 3 withheld) | 7/7 = 100% [64.6, 100.0] | 0/7 = 0% [0.0, 35.4] |
| Outside those topics (71 answerable) | 59/71 = 83.1% [72.7, 90.1] | 6/71 = 8.5% [3.9, 17.2] |

On the clarify items inside the Hag slice, Grund answered the CPI annual average for a year with no month, which the gold marks as a clarification rather than an answer.

Grund with the char-n-gram index, by stratum. Value when the question is answerable, refusal when it is not. The e5 differences are in the table above.

| Stratum | Table | Value | Refusal |
| --- | --- | --- | --- |
| level | 31/36 | 29/36 | |
| latest | 7/8 | 7/8 | |
| yoy_official | 6/8 | 6/8 | |
| yoy_computed | 6/8 | 6/8 | |
| share | 10/10 | 10/10 | |
| rebase | 5/5 | 5/5 | |
| paraphrase | 2/3 | 3/3 | |
| unanswerable | | | 9/10 |
| clarify | | | 0/3 |

Rebase is still exact on all five questions. The three paraphrase values are exact, and one of them cites the wrong table. Shares are 10/10. Five of them had been wrong for a reason in the binder, not in the arithmetic. "by region and vessel type" was selecting a second vessel type because the question contains "and". A share was computed on a column labelled Percentage because the question says "percentage". "in December" inside a pasted table title was paired with a year later in the sentence, so a yearly table would not bind. The life-expectancy share was computed and then refused, because the title's "30" was copied into the sentence and failed the number check. The Icelandic within-municipality share was a near-tie between `MAN01101.px` (1986–2018) and `MAN01102.px` (1986–2025); the question quotes the shared title and not the later end year, so the closed vintage is kept. When two neighbours are close and the question pastes one title in full, that title wins instead of a clarification. The three clarify items were all answered: Reykjavík from a municipality table, and the CPI year from the annual-average table.

## Left for the event

- Decide, with the organisers, whether "the consumer price index in 2024" should clarify or should cite the annual average. The scored run leaves `GRUND_CLARIFY_MONTH` unset and cites `VIS01005.px`. Setting the flag to `1` asks for a month, or for the annual average, and states no figure. An explicit annual-average question is not that case.
- The Icelandic tree was walked to completion for this catalogue. English was not walked again. Historical tables and the environment database did not gain editions.
- Rescore the plain model and the Grund planner on the DGX Spark if a larger model is available there. The CPU score above is Qwen2.5-7B-Instruct at Q4_K_M, not a 14B vLLM run.
- Confirm the questions in `docs/rules-questions.md` on 28 October, including whether this evaluation set may be brought in.
