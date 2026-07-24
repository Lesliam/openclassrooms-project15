# Coach FR baseline evaluation report - transformers-coach-tuned-v1-cs158

- Mode: `coach-tuned:v1-cs158`
- Model under test: `coach-tuned:v1-cs158`
- Judge: `none` (enabled: False)
- Repetitions per item: 2
- Drift depth: 7 filler turns (shallow after 2)
- System prompt SHA-256: `50480f0fea969ca074ecac3809fa99445b2421d06d0de3f0f7ed0579a84746ab`
- Eval set SHA-256: `a743af252407034571f29511a661ea6d36fb15104e2c21c6324bb6b4ce85fc10`
- Decoding: temperature=0.7, top_p=0.9, seed_base=42, num_ctx=8192 (v0 guesses, pending Lesliam review)

## Headline metrics

- D1 deterministic pre-check compliance (4-part marker PRESENCE + brevity; part ORDER and the 'exactly one explanation sentence' rule are NOT verified here - judge pending): 100.0%
- D1 false-positive rate (error-free turns wrongly corrected): 0.0%
- D2 French-persistence rate: 88.9%
- D2 mean French-token fraction: 0.981

> The `D1` column below is the same deterministic pre-check (presence + brevity), not the spec's full D1 rate; order and single-explanation checks are the judge's job (eval_set_v0 section 2).

## D3 drift deltas (shallow - deep)

| Dialogue | Behavior | Shallow | Deep | Delta |
| --- | --- | --- | --- | --- |
| 14 | D1 | 100.0% | 100.0% | +0.0pp |
| 14 | brevity | 100.0% | 100.0% | +0.0pp |
| 15 | D2 | 50.0% | 100.0% | -50.0pp |
| 15 | brevity | 100.0% | 100.0% | +0.0pp |
| 16 | brevity | 100.0% | 100.0% | +0.0pp |
| 17 | D2 | 100.0% | 100.0% | +0.0pp |
| 17 | brevity | 100.0% | 100.0% | +0.0pp |

## Per-item rates

| Item | Group | D1 | D1 false-pos | D2 | Brevity |
| --- | --- | --- | --- | --- | --- |
| 1 | A | 100.0% | n/a | n/a | 100.0% |
| 2 | A | 100.0% | n/a | n/a | 100.0% |
| 3 | A | 100.0% | n/a | n/a | 100.0% |
| 4 | A | 100.0% | n/a | n/a | 100.0% |
| 5 | A | 100.0% | n/a | n/a | 100.0% |
| 6 | A | 100.0% | n/a | n/a | 100.0% |
| 7 | A | 100.0% | n/a | n/a | 100.0% |
| 8 | A | n/a | 0.0% | n/a | 100.0% |
| 9 | B | n/a | n/a | 100.0% | 100.0% |
| 10 | B | n/a | n/a | 50.0% | 100.0% |
| 11 | B | n/a | n/a | 100.0% | 100.0% |
| 12 | B | n/a | 0.0% | 100.0% | 100.0% |
| 13 | B | n/a | n/a | 100.0% | 100.0% |
| 14 | C | 100.0% | n/a | n/a | 100.0% |
| 15 | C | n/a | n/a | 75.0% | 100.0% |
| 16 | C | n/a | n/a | n/a | 100.0% |
| 17 | C | n/a | n/a | 100.0% | 100.0% |
| 18 | D | n/a | 0.0% | n/a | 100.0% |
| 19 | D | n/a | 0.0% | n/a | 100.0% |
| 20 | D | 100.0% | n/a | n/a | 100.0% |
