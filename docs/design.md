# Design

Grund answers a question about Statistics Iceland only after a PxWeb cell, or a calculation on those cells, has been read. The sentence is allowed to contain a number when that number is on an allow-list built by code.

## What is reusable, and what is the app

It is not yet known whether code written before GAGNAÞON may be brought into the room. The split is there so that question can be answered by pointing at directories.

- `indexer/`, `evalset/`, `rails/`, and `docs/` are the pieces that are useful even if the app has to be rewritten on site: the crawl, the index format, the rail specification, and the evaluation set.
- `app/` is the ask path and the chat page. It imports the other packages. It does not own the catalogue format.

## Crawl

PxWeb v1 only. English is `https://px.hagstofa.is/pxen/api/v1/en/` and Icelandic is `https://px.hagstofa.is/pxis/api/v1/is/`. A published v2 path does not exist on this host.

The client sends `User-Agent: Grund/0.1 (GAGNATHON 2026; rgoswami@ieee.org)`, spaces requests, and on HTTP 429 pauses every caller before retrying. GET responses are cached by URL hash, so a second crawl resumes. The catalogue is one JSON object per table edition (language). Variable codes differ by language, so each edition is stored whole and tables are joined on the `.px` filename.

The crawl visits the consumer-price, population, and internal-migration folders first, then walks both trees. A run that is still going is a partial catalogue. The manifest records how many editions were actually indexed.

## Retrieval

Search is hybrid.

- BM25, Okapi, k1 = 1.5, b = 0.75, over a short document: title, path, variable names, and a capped set of distinctive value labels. Age labels such as "1 year" are left out, because they make the document long and bury the title.
- Embeddings, when the manifest says the index was built with them. The query and the passage must use the same model. For e5 that means the `query:` and `passage:` prefixes. FastEmbed 0.9 provides `intfloat/multilingual-e5-large` and does not provide `multilingual-e5-small`. The large model is the one that covers Icelandic in this build. A missing download is recorded as `chargram` in the manifest rather than silently mixed with a different vector.
- A value-label overlap, so "females" can select a column whose title never says females. Tokens that occur in most tables are ignored.
- A coverage term for the years named in the question, a title-alignment term, and a penalty for titles marked earlier, previous, eldra, or change of method when the question did not ask for those.

Title alignment is what stops a one-word title ("Population") and a long off-topic title ("lifelong learning by sex and age") from beating "Population by sex and age". A few subject phrases are explicit: annual averages versus the wage index, consumer prices versus a constant-tax index, internal migration versus a municipality breakdown the question did not name.

## Scope

A question is refused before search when a content word is not in the catalogue. Coverage is titles, path labels, variable names, and value labels. Month-name tokens count only from titles and variable names, so a March label does not make "March" a known subject. The token "mars" is the exception: it is March in the census title "skólagöngu í mars" and the planet in English, and a date such as "í mars 2024" is not an entity. Synonyms and a short inflection (plural s, Icelandic definite endings) count. Words that name the question rather than the subject, such as rebase, roughly, and every, are not entities. A minimum search score is not used. Future years stay on the ordinary bind failure, because the subject itself is in the catalogue. `evalset/heldout.jsonl` is a separate list and is not part of the scored 91.

## Binding

The planner emits a table id and a PxWeb selection. The deterministic planner does this itself. An OpenAI-compatible model may do it when `GRUND_LLM_BASE_URL` is set and the planner is `llm` or `auto`. The model replies with one JSON object, `{"action":"query","table_id","operation","selections":[{"code","values"}]}` or `{"action":"refuse"}`, using codes from the candidate cards. `validate` refuses a variable or a code the edition does not have, and refuses a `top` filter that would exceed the value cap. The model gets the error and two further tries. After that the deterministic planner is used. A failed validation does not POST.

Time codes have to match. A year on a monthly series is not silently turned into one month. A consumer-price question that names a year and no month cites the annual average unless `GRUND_CLARIFY_MONTH=1`, in which case Grund asks for the month or for the annual average and states no figure. The scored run leaves the flag unset. A share has to name a part and the total on the same variable. A part larger than the whole is rejected and the next table is tried, which is how a participation rate stops impersonating a population share. An official change column (annual change, ársbreyting, population increase) is cited as a cell. It is not recomputed, because the published rounding is the statistic.

Icelandic totals are labelled `Alls`. That label is treated as a total, same as `Total`.

## Arithmetic

`app/grund/arithmetic.py` is the only place a figure is derived. Inputs are the strings PxWeb returned, parsed with `Decimal`. The operations are year-on-year percent, difference, share, rebase to 100, and per capita. Units are scaled only when the label says thousands or millions. The formatted result is registered on the allow-list before it is written into a sentence.

## Rails

Prior work is [vangrail](https://github.com/HaoZeke/vangrail). A rail is one check. Statuses are `passed`, `modified`, and `blocked`. `certain` is separate, so a check that did not run cannot be reported as a clean pass. A plan grants `pxweb.query` and is locked before the POST. The posted URL and the query have to be the granted ones.

vangrail's grounding rail is a model judge over passages. Grund does not use that for numbers. A judge can be talked into a figure, and it cannot show the cell. The number-grounding rail parses every numeric token in the sentence, in English and Icelandic grouping, and blocks the turn unless the token is a fetched cell, a value `arithmetic.py` just produced, or a number that already appears in a cell key or in the label of a used row. A refusal may echo a number from the question and may not introduce one. Prompt-injection and jailbreak rails are deterministic patterns on the question and on footnotes. A footnote that trips them stays on the source card and is kept out of any model prompt.

The flow list is `rails/rails.yaml`. The Colang interpreter from vangrail is not ported.

## Source card

Every answer that states a figure carries the table id, the API URL, the exact selection, the retrieval time, the cells used, any derivation (name, formula, inputs), footnote text, and whether the title or the notes look preliminary or revised. The HTML PxWeb tree does not deep-link to a table — those paths return 404 — so the card links to the API URL, which does return the table.

## Model boundary

The model may choose a table and may rewrite a sentence. It may not add, divide, or invent a code. The eval harness sets the planner to deterministic so the score is the retrieval and the arithmetic, not whichever server happened to be up.
