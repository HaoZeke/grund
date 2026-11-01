# Extra-context guard

Optional panel text can explain a verified Grund answer. The panel is off unless a caller asks for it. This module checks that text. It does not call a model, does not fetch pages, and does not change the verified answer.

The verified answer is the JSON object from `POST /api/ask`. Figures are read from `answer`, `value`, `value_display`, `source.cells`, `source.derived`, `claims`, and `path_pair`. `value` is the PxWeb string (`394324`, `630.3`). `value_display` is the grouped form (`394,324` or `394.324`) and is read in `language` on that object. Table ids, URLs, `elapsed_ms`, retrieval timestamps, and `source.title` are not figures.

## Numbers

`extract_numbers(text, lang)` returns `NumberSpan` values (`raw`, `value`, `kind`, `start`, `end`).

* `1.234,5` and `1,234.5` are both `1234.5`. Repeated groups (`1.234.567`, `1,234,567.89`) and spaced groups (`8 476 511`, including non-breaking spaces) are unambiguous.
* A single group of three follows `lang`: Icelandic `1.234` is `1234`, English `1.234` is `1.234`. The same rule applies to `1,234`.
* `12,5%`, `12.5 percent`, and `12,5 prósent` are percents. The value stays `12.5`, not `0.125`.
* `Q3 2024`, `2024Q3`, `3rd quarter of 2024`, and `3. ársfjórðungur 2024` yield a quarter and a year. `Q3` is a quarter, not the cardinal 3. `2024M06` yields the year only.

## What may be shown

`check(elaboration, verified_answer_json, question, lang, tool_records=None)` returns `text`, `dropped_sentences`, `flags`, and `ok`.

Text before a heading, and a `From the data` / `Úr gögnunum` / `Frá gögnunum` section, may use only numbers from the verified answer or the question. A percent in the elaboration has to be a percent in that material: a level of `9.2` does not allow `9.2%`. A share or year-on-year result does. Markers do not relax this section.

A `Beyond the data` / `Handan gagnanna` section may also use a new number when the same sentence is marked:

| Marker | Record | Number may stay when |
| --- | --- | --- |
| `[fetch:TABLEID]` | `kind: fetch`, `table`, `cells` | it is a cell figure on that table. `result` is ignored. `.px` is ignored. |
| `[calc:N]` | `kind: calc`, `id`, `expression`, `result` | it matches `result` after half-up rounding to the precision that was written. |
| `[source:URL]` | `kind: source`, `url`, `text` | the host is `island.is` or a subdomain, the URL is that record, and the number is in `text`. |
| `(inferred)` or `(ályktun)` | none | the sentence cites no fetch, calc, or source. |

`island.is.evil.com`, `notisland.is`, a URL with userinfo such as `https://evil.com@island.is/`, and any other host are rejected, and the whole sentence is removed. A bad source citation is not saved by `(inferred)`. Unmarked new numbers are removed. Rounded numbers such as `394,000` for `394324` are removed unless a calc result really rounds to what was written. A calc match is the numeric value, so `12.3` and `12.3%` both match a result of `12.3`. A fetch cell or a source page keeps a percent only when that recorded figure was itself a percent.

`flags` lists `causality` and `forecast` sentences. Those sentences stay when their numbers are allowed.

`tool_records` is a list of `{id, kind, table, cells or expression, result, url, text}`. Fetch cells use `value`, and may include `period`, `key`, and `labels`.

## Provenance stamp

`watermark(text, meta)` puts a visible label on the first line and an invisible zero-width marker after it. The English label is `Extra context (LLM, unverified)`. The Icelandic label is `Aukalegt samhengi (mállíkan, óstaðfest)`. `meta["label"]` overrides either one. `meta["lang"]` selects the label.

The marker carries a short id (the first 8 hex characters) and an HMAC-SHA256 over `answer_hash|model|timestamp`. The key is the environment variable `GRUND_ELAB_HMAC_KEY`. If `answer_hash` is omitted, the hash is SHA-256 of `meta["answer"]` when that is a string, otherwise of the canonical JSON. `verify_watermark(text, meta)` checks the label and the HMAC. It does not cover later edits to the paragraph; it binds the stamp to the answer, the model, and the timestamp.

```sh
python -m pytest test_elab_guard.py
```
