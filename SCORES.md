# Scores, 2026-10-31

Python rail. The calibrator cut 0.9 was chosen on dev-A only and maximises TrustSQL at penalty 10. is-native-dev2 was not used to choose it. TrustSQL is a signed sum. A Wilson interval beside it is on wrong/n, not on the sum.

| Slice | Result |
| --- | --- |
| dev-A before the cut, coverage | 145/200 = 72.5% [65.9, 78.2] |
| dev-A before the cut, accuracy when answering | 117/145 = 80.7% [73.5, 86.3] |
| dev-A before the cut, wrong when answering | 28/145 = 19.3% [13.7, 26.5] |
| dev-A after the cut, overall | 17/200 = 8.5% [5.4, 13.2] |
| dev-A after the cut, coverage | 18/200 = 9.0% [5.8, 13.8] |
| dev-A after the cut, wrong when answering | 1/18 = 5.6% [1.0, 25.8] |
| dev-A after the cut, TrustSQL penalty 10 | 7 |
| dev-A after the cut, error rate | 1/200 = 0.5% [0.1, 2.8] |
| is-native-dev2 overall | 16/80 = 20.0% [12.7, 30.0] |
| is-native-dev2 coverage | 0/80 = 0.0% [0.0, 4.6] |
| is-native-dev2 wrong when answering | 0 stated; wrong count 0 |
| is-native-dev2 TrustSQL penalty 10 | 16 |
| is-native-dev2 error rate | 0/80 = 0.0% [0.0, 4.6] |

The 16 dev2 successes are the gold refusals. Dev-A is the selection set.

## 2026-10-31 gates, then the abstain choice

Python rail, catalogue rerank on, logistic cut off. The 0.9 cut is not the default (`GRUND_CALIBRATE=logistic` turns it back on). TrustSQL is the signed sum. The mean is sum/n.

The fit is dev-A plus dev2 after the three gates. The organisers' 60 and the Track 3 52 are the same rows, scored once, and were not used to pick the policy. Disagreement wins the union by 115 points over the next policy, so the tie-break (more rights) does not apply. It is the default. Stated answers on dev-A under that default: 103/200 = 51.5%. The coverage test fails if that share falls under 30%.

| Policy | dev-A sum (mean) | dev-A right / wrong | dev2 sum (mean) | dev2 right / wrong | union sum | union right |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| none | −145 (−0.725) | 105 / 25 | −86 (−1.075) | 24 / 11 | −231 | 129 |
| share below 0.65 | −135 (−0.675) | 105 / 24 | −86 (−1.075) | 24 / 11 | −221 | 129 |
| pair, share or change below 0.65 | −86 (−0.430) | 104 / 19 | −86 (−1.075) | 24 / 11 | −172 | 128 |
| hybrid gate and score below 0.70 | −97 (−0.485) | 103 / 20 | −26 (−0.325) | 24 / 5 | −123 | 127 |
| path disagreement | −29 (−0.145) | 91 / 12 | 21 (0.263) | 21 / 0 | −8 | 112 |

| Set | Gates only | Disagreement (the default) |
| --- | --- | --- |
| dev-A | 105 right, 25 wrong, TrustSQL −145 | 91 right, 12 wrong, TrustSQL −29 |
| dev2 | 24 right, 11 wrong, TrustSQL −86 | 21 right, 0 wrong, TrustSQL 21 |
| organisers' 60 | 27 right, 7 wrong, TrustSQL −43 | 15 right, 0 wrong, TrustSQL 15 |
| Track 3 52 | 20 right, 5 wrong, TrustSQL −30 | 10 right, 0 wrong, TrustSQL 10 |

On the 52, a hybrid-gate cut at 0.70 scores TrustSQL 16 with 16 right and 0 wrong. That is better than disagreement on that set alone. It was not used to change the choice.

## 2026-10-31 Ruby citation parity on the organisers' 60

Both rails, one engine. `GRUND_RAIL=python` and `GRUND_RAIL=ruby` (Vangrail 0.3.0 on 127.0.0.1:9293). Env on every row: `GRUND_ABSTAIN_RULE` unset (disagree), `GRUND_CALIBRATE` unset, `GRUND_RECALL` unset (fill; the e5-small index is not on this machine, so fill added no neighbours), `GRUND_LEXICON` unset (on), `GRUND_SUBJECT_CHECK` unset, catalogue `data/index`. TrustSQL is the signed sum. The mean is sum/n. Wilson intervals are on the rate, not on the sum.

The two rails matched question by question: same refusal, or the same value and table. Table codes, calendar dates, and the updated stamp are not claims.

| Rail | Right | Refused | Wrong | Coverage Wilson 95% | Error-rate Wilson 95% | TrustSQL-10 | Mean |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| `GRUND_RAIL=python` | 15 | 45 | 0 | 15/60 = 25.0% [15.8, 37.2] | 0/60 = 0.0% [0.0, 6.0] | 15 | 0.250 |
| `GRUND_RAIL=ruby` | 15 | 45 | 0 | 15/60 = 25.0% [15.8, 37.2] | 0/60 = 0.0% [0.0, 6.0] | 15 | 0.250 |

The smoke ten (nine gold questions from that file, plus the Mars refusal) also matched rail to rail: 6 right, 4 refused, 0 wrong.

## 2026-10-31 Ruby, e5-small, subject check and zero-count on

Rail `GRUND_RAIL=ruby` (Vangrail 0.3.0). Env on every row: `GRUND_ABSTAIN_RULE` unset (disagreement, plus a published-figure match on a different table), `GRUND_CALIBRATE` unset, `GRUND_RECALL` unset (fill), `GRUND_LEXICON` unset (on), `GRUND_RERANK` unset (on), `GRUND_SUBJECT` unset (on), zero-count on, `GRUND_BIND2_VETO` unset, `GRUND_E5=small`, `GRUND_E5_DIR=data/models/small`, `GRUND_E5_SMALL_INDEX=data/index-e5-small`, catalogue `data/index`. TrustSQL is the signed sum. The mean is sum/n. Wilson intervals are on the rate.

The relaxation was chosen on dev-A plus dev2 only. It keeps a stated figure when the other path names the same published rounding on a different table, unless the stated table is a Sögulegar copy and the other path is not. Same-table agreement below 1 stays a refusal. That cut adds no wrong figure on dev-A or dev2.

| Set | Right | Refused | Wrong | Coverage Wilson 95% | Error-rate Wilson 95% | TrustSQL-10 | Mean |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| dev-A | 106 | 86 | 8 | 114/200 = 57.0% | 8/200 = 4.0% [2.0, 7.7] | 26 | 0.130 |
| dev2 | 21 | 75 | 0 | 5 stated, 16 of the rights are gold refusals | 0/80 = 0.0% [0.0, 4.6] | 21 | 0.263 |
| organisers' 60 | 23 | 37 | 0 | 23/60 = 38.3% [27.1, 51.0] | 0/60 = 0.0% [0.0, 6.0] | 23 | 0.383 |
| Track 3 52 | 18 | 34 | 0 | 18/52 = 34.6% [23.2, 48.2] | 0/52 = 0.0% [0.0, 6.9] | 18 | 0.346 |

Before this relaxation, the same tree under plain disagreement was dev-A 99 right and 8 wrong, dev2 21 right and 0 wrong, the 60 15 right and 0 wrong, and the 52 10 right and 0 wrong.

## 2026-10-31 loose gates, disagreement stays the default

`app/grund/loose_gate.py` is on for every stated answer, before the disagreement rule. It withholds a percent change or a difference answered as a bare level, a change whose cited titles and labels lack an asked measure (overnight stays do not match an occupancy series), a men-minus-women difference that does not cite both sexes, and a count of one sex whose labels are not that sex. A two-part answer is judged on its table titles together. `GRUND_ABSTAIN_RULE` unset remains disagreement. Rule-off is not the default: on the fit sets it still loses against this relaxation (dev-A −16 and dev2 −69 in the category note, penalty 10).

The same-table bucket stays refused. With the rule off and these gates on, Ruby e5-small still states isd2-23 (511.7, VIS01000) and isd2-33 (6090333, SAM01601), both right, and isd2-46 (29176, MEN10001) and isd2-54 (138772, MAN03270), both wrong. The gates do not separate those four. A pair the offline title join had flagged, d3-sko00003b-and-vin00930-en, stays right when both table titles are present.

## 2026-10-31 hall count gap, superlative, historical, CPI base

Rail on every row below: `GRUND_RAIL=ruby`, Vangrail 0.3.0. Env: `GRUND_ABSTAIN_RULE` unset (disagreement; a matching published figure on another table is kept; a Sögulegar table is kept only when its span ends and the other table continues past that end), `GRUND_CALIBRATE` unset, `GRUND_RECALL` unset (fill), `GRUND_LEXICON` unset (on), `GRUND_RERANK` unset (on), `GRUND_SUBJECT` unset (on), zero-count on, loose gates on, `GRUND_E5=small`, catalogue `data/index` (chargram-384). The value index is rebuilt as chargram from that catalogue. `data/index-lang` on this machine is e5-large, 1024-d, 2189 passages, and is not what the hybrid path searches.

The hall's 104/10 against 106/8 on dev-A, the extra dev2 wrong on isd2-23, and 17 against 18 on the 52, were that saved matrix. Nefnir `init()` once removes a stall; it does not change the rank. Catalogue ties break on table id. The same three organisers' questions, search plus rerank, match across two calls and across `PYTHONHASHSEED` 0 and 1.

A largest, stærsta, flest, or most-populous municipality question cannot cite Alls, Total, or Iceland on a municipality or country key. Sex=Total does not fire. No dev-A or dev2 question uses those words. js-largest-muni-en was already a path disagreement on the ruby e5-small capture, not 394324.

Preferring every Sögulegar twin loses 22 dev rank-1 golds, including d3-umh01101 (gold UMH01101, same span as SOG09001). js-hist-kosningar is not the same series as KOS02004; SOG13004, which is, ends in 2016 and does not cover 2024. The one lossless keep is a closed copy: js-hist-ferdir-is stays 23861 from SOG03001. js-hist-umhverfi-is stays 122 from UMH01101.

isd2-23's gold is 511.7 from VIS01000. VIS01101 is "Vísitala neysluverðs eftir eðli og uppruna" / "CPI by expenditure groups" and is refused unless the question names that base. VIS01000 is not. With the rule off the ruby capture states 511.7 from VIS01000. Same-table agreement 0.666 still abstains it under the default.

## 2026-10-31 points, projection, title echo, look-alikes

Rail on every row: `GRUND_RAIL=ruby`, Vangrail 0.3.0. Env: `GRUND_ABSTAIN_RULE` unset (disagreement), `GRUND_CALIBRATE` unset, `GRUND_RECALL` unset (fill), `GRUND_LEXICON` unset (on), `GRUND_RERANK` unset (on), `GRUND_SUBJECT` unset (on), `GRUND_TITLE_ECHO` unset (on), look-alike gate on, `GRUND_BIND2_VETO` unset, `GRUND_E5=small`, `GRUND_E5_DIR=data/models/small`, `GRUND_E5_SMALL_INDEX=data/index-e5-small`, value index rebuilt as chargram from `data/index`. Disagreement stays the default.

`cpi-points-2026-en` was refused because the loose measure check treated `points` as a series word. The unit of a point change is not the series. Both paths already agreed on 39.0 from VIS01000 and VIS01002. `women-share-2026-en` was refused because the hybrid path cited 48.1 from the population projection MAN09010. A projection is not the population on a date unless the question asks for one. The ranker and the repaired hybrid both give 48.7, and the stated table is MAN03250.

The title-echo gate refuses a cell that only repeats the table title: a share of an unnamed part, a total with an of-which sibling, or a total that drops a title noun another row still carries. It is how both `d3-umh04102` rows (526) leave the stated set. `dc-men13102-level-en` (`Rulings, total`) is refused by the same gate. That question was not used to turn the gate off.

The look-alike gate refuses a different series: a Sögulegar copy that is not a closed span, a CPI table that does not contain the asked base year, a population projection, a locality table for a named municipality, a municipality table for a by-status question, and an art-form question answered from the theatre-group table. On the stated dev-A and dev2 rows it drops `d3-vis01102-level-is`, `d3-men05107-and-sja04902-is`, and `d3-vin00901-and-lan10302-is`, and no right. It does not refuse `cpi-points-2026-en` or `women-share-2026-en`.

| Set | Right | Wrong | Refused | Right Wilson 95% | Wrong Wilson 95% | TrustSQL-10 | Mean |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| dev-A | 104/200 | 0 | 96 | 52.0% [45.1, 58.8] | 0.0% [0.0, 1.9] | 104 | 0.520 |
| dev2 | 21/80 | 0 | 59 | 26.2% [17.9, 36.8] | 0.0% [0.0, 4.6] | 21 | 0.263 |
| organisers' 60 | 23/60 | 0 | 37 | 38.3% [27.1, 51.0] | 0.0% [0.0, 6.0] | 23 | 0.383 |
| Track 3 52 | 17/52 | 0 | 35 | 32.7% [21.5, 46.2] | 0.0% [0.0, 6.9] | 17 | 0.327 |
| dev-B | 45/100 | 8 | 47 | 45.0% [35.6, 54.8] | 8.0% [4.1, 15.0] | −35 | −0.350 |
| dev-C | 49/100 | 9 | 42 | 49.0% [39.4, 58.7] | 9.0% [4.8, 16.2] | −41 | −0.410 |

dev-A and dev2 chose the gates. The 60, the 52, dev-B, and dev-C were scored after the gates were frozen.

## 2026-10-31 dev-B as a fit set, GRUND_KEEP on

`All editions` is a total, the same way `Alls` is. A title that lists mean, median, and modal age is not a request for the mean; naming `Miðaldur` still keeps the median. `GRUND_KEEP` is on: when the paths disagree and the loose gate refuses exactly one stated figure, the other figure is kept and disagreement does not drop it. A one-sex question whose sex label is only Total is `sex-total`. A women share that also cites Females is kept.

Fit, after these gates. Rail `GRUND_RAIL=ruby`, Vangrail 0.3.0. Env: disagreement default, `GRUND_CALIBRATE` unset, `GRUND_RECALL` unset (fill), `GRUND_LEXICON` unset (on), `GRUND_RERANK` unset (on), `GRUND_SUBJECT` unset (on), `GRUND_TITLE_ECHO` unset (on), look-alike on, `GRUND_KEEP` unset (on), `GRUND_BIND2_VETO` unset, `GRUND_E5=small`, `GRUND_E5_DIR=data/models/small`, `GRUND_E5_SMALL_INDEX=data/index-e5-small`, chargram value index rebuilt from `data/index`.

| Set | Role | Right | Wrong | Refused | Right Wilson 95% | Wrong Wilson 95% | TrustSQL-10 | Mean |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| dev-A | fit | 107/200 | 0 | 93 | 53.5% [46.6, 60.3] | 0.0% [0.0, 1.9] | 107 | 0.535 |
| dev2 | fit | 22/80 | 0 | 58 | 27.5% [18.9, 38.1] | 0.0% [0.0, 4.6] | 22 | 0.275 |
| dev-B | fit | 46/100 | 6 | 48 | 46.0% [36.6, 55.7] | 6.0% [2.8, 12.5] | −14 | −0.140 |
| dev-C | held-out | 53/100 | 9 | 38 | 53.0% [43.3, 62.5] | 9.0% [4.8, 16.2] | −37 | −0.370 |
| organisers' 60 | confirm | 23/60 | 0 | 37 | 38.3% [27.1, 51.0] | 0.0% [0.0, 6.0] | 23 | 0.383 |
| Track 3 52 | confirm | 17/52 | 0 | 35 | 32.7% [21.5, 46.2] | 0.0% [0.0, 6.9] | 17 | 0.327 |
| diag-100 | confirm | 20/100 | 3 | 77 | 20.0% [13.3, 28.9] | 3.0% [1.0, 8.5] | −10 | −0.100 |

The four kept rights are `d3-man07109-difference-en` 1064, `d3-sam04201-difference-en` 203820, `d3-man03107-difference-is` 1926, and `isd2-03` 187015. No fit right was lost and no new fit wrong was added. The six dev-B wrongs that remain are two-part questions.

Replaying the abstain rule on the ruby e5-small captures, with the closed-copy flag set from the catalogue spans:

| Set | Capture | Rows whose abstain decision changed | Rail and env |
| --- | --- | --- | --- |
| dev-A | ruby-e5, 200; ruby-gates, 59 | 0 | ruby, e5-small, disagreement, chargram catalogue |
| dev2 | ruby-gates, 80 | 0 | ruby, e5-small, disagreement, chargram catalogue |
| organisers' 60 | ruby-gates, 60 | 0 | ruby, e5-small, disagreement, chargram catalogue |
| Track 3 52 | ruby-gates, 52 | 0 | ruby, e5-small, disagreement, chargram catalogue |
| diag-100 | ruby-gates, 100 | js-hist-ferdir-is, correct, 23861, SOG03001 | ruby, e5-small, disagreement, chargram catalogue |
