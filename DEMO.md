# Demo

Four questions on the frozen build: one in English, one in Icelandic, one that needs two tables, and one that Grund should refuse.
Every question comes from `evalset/track3-questions.jsonl` or the held-out set of 80 questions, called FINAL here.
Each one was right, or correctly refused, when the frozen build was scored.

Start Grund with `sh script/freeze_run.sh` and wait for the `retrieval:` line and for uvicorn on port 8741.
Then open `http://localhost:8741/`.
Read each figure from the card on screen.
If the card shows a different figure, the run does not match the frozen build.

## 1. An English question

Ask: **How many people lived in Iceland on 1 January 2026?**

The figure is **394,324**, from table **MAN00101**, filters Total, period 2026.

The same question in Icelandic, **Hve margir bjuggu á Íslandi 1. janúar 2026?**, gives **394.324** from MAN00101.

## 2. An Icelandic question

Ask: **Hver var vísitala neysluverðs í september 2026?**

The figure is **697,3**, from table **VIS01000**, period 2026M09.
The Icelandic answer uses a decimal comma.

## 3. A question that needs two tables

Ask: **How many people lived in Iceland on 1 January 2026, and what was the consumer price index in September 2026?**

The answer states both figures, **394,324** from **MAN00101** and **697.3** from **VIS01000**, and cites both tables.
If Grund finds only one part, it refuses the question instead of giving half an answer.

## 4. A question Grund refuses

Ask: **Should the wage index be higher?**

No figure appears.
The answer starts "I can't answer that from a published Statistics Iceland table," and lists the tables it considered, starting with LAU04000.
The question asks for an opinion, and no table records one.

## Do not use these

- "What will Iceland's population be in 2150?"
  The frozen build answers it with 394,324, and that answer is wrong.
  It is one of the four wrong answers on the held-out 80.
- The Vigdís Finnbogadóttir 1980 question.
  The frozen build refuses it, and its gold is a figure, so the refusal is a miss.
