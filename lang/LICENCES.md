# Licences

The language layer calls these tools when they are installed. None of their
data files are copied into this tree. A machine without them still runs:
case endings and the concept list do the work, and the manifest records
that the embedding checkpoint was not loaded.

| Piece | What it is used for | Licence |
|---|---|---|
| Tokenizer 3.x | Sentence and date tokens | MIT |
| Greynir parser (`reynir` 3.x), which is the installable Greynir engine | Lemmas and parts of speech in a sentence | MIT |
| Nefnir 1.0 | Lemma of a word the inflection database does not list, given a tag | Apache-2.0 |
| `islenska` 2.x, code | Lookup API for the inflection database | MIT |
| `islenska-data` 5.x | Beygingarlýsing íslensks nútímamáls (BÍN), the Database of Icelandic Morphology | CC BY-SA 4.0 for the data; MIT for the package code |
| Multilingual e5 large checkpoint | Passage and query embeddings, 1024 dimensions, CPU | MIT |

BÍN is included. The copyright holder is Stofnun Árna Magnússonar í íslenskum
fræðum. Credit, as required by the data licence:

Beygingarlýsing íslensks nútímamáls. Stofnun Árna Magnússonar í íslenskum
fræðum. Höfundur og ritstjóri Kristín Bjarnadóttir.

CC BY-SA 4.0 allows this lookup. It also requires the same licence on a
redistributed adaptation of the database. This tree does not redistribute
the database. The publisher of the installed data package adds its own
forms for the parser and claims no endorsement by the institute.

The Database of Icelandic Morphology is the same published BÍN data. No
separate DIM file is downloaded.

Nefnir is only asked for a lemma the database did not return, and the lemma
is kept when it is itself a dictionary word or a stem of the surface form.
A tag the parser did not supply is one of a short list of ordinary noun and
verb tags, not every tag in the tagset.
