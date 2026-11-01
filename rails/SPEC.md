# Grund rails

Prior work: [vangrail](https://github.com/HaoZeke/vangrail) (Rohit Goswami). vangrail runs input, context, and output rails inside a Ruby process. A rail is one object with one method and three statuses, `passed`, `modified`, and `blocked`. `certain?` is orthogonal: a check that did not run must not look like a clean pass. Detection is not authority. A locked plan grants a tool call; a rail can refuse to use a grant, and it cannot create one.

Grund does not shell out to the gem. The hackathon runtime is Python, and the failure that matters here is a number that was not in the fetched PxWeb cells. vangrail's `Rails::Grounding` is a model judge over passages. A judge can be persuaded, and it cannot show the cell. Grund's number-grounding rail is a deterministic specialisation of that idea: every numeric token in the prose must parse to a value the code path registered from a cell, from `grund.arithmetic`, or from a time key on those cells. That cell-claim check stays in this tree. It is not moved into vangrail. Further cell-selection heuristics are not the replacement for it; a claim rail plus a retry is. The other rails follow the same protocol.

## Protocol

| Piece | Meaning |
| --- | --- |
| Side | `input` (the question), `context` (footnotes and retrieved text about to enter a prompt), `output` (the answer) |
| Status | `passed` unchanged, `modified` rewritten, `blocked` the turn stops |
| `certain` | False when the rail did not actually check. Callers that only branch on status can ignore it. Reports must not. |
| Plan | Read grant for `pxweb.query`, frozen before the POST. The posted table id and query have to be the granted ones. |

Flows are an ordered list per side. vangrail can express flows in a Colang 1.0 subset; Grund keeps the list in `rails.yaml` and does not port the interpreter.

## Rails in this entry

| Rail | Side | Certain when | Blocks when |
| --- | --- | --- | --- |
| `jailbreak` | input, context | Patterns ran | A known jailbreak shape is in the question or in retrieved text |
| `injected_instructions` | input, context | Patterns ran | A role header, an "ignore the above" override, or an exfiltration request is in the text |
| `number_grounding` | output | An allow-list was supplied | A numeric token is not on the allow-list |
| `refusal` | output | The turn is a refusal or an answer | A refusal contains a number that was not in the question, or an answer is empty of both a value and a refusal |
| `citation` | output | A source card was required | An answer that states a value has no table id, no retrieval time, or no cells |

Footnotes that trip `injected_instructions` are kept on the source card for the reader and omitted from any model prompt. Official footnotes rarely look like role headers; the patterns are shapes, not a word list of statistical terms.

## Number allow-list

The engine registers:

- the float value of every cell used
- every derived value produced by `grund.arithmetic`, using the same rounded string the prose will print
- numeric pieces of the cell keys (the year in `2024M06`)

It does not register numbers merely because the user typed them, except on a refusal, where the answer may echo the question and may not introduce a figure. Formula text such as "× 100" stays in the structured source card, which is built by code, not in the sentence the rail checks. A model rewrite that adds a figure the card does not contain is discarded and the template sentence is used (`modified`).
