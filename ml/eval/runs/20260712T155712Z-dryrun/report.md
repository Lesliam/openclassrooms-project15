# Coach FR baseline evaluation report - 20260712T155712Z-dryrun

- Mode: `dryrun`
- Model under test: `qwen2.5:14b`
- Judge: `mistral-small3.2:latest` (enabled: False)
- Repetitions per item: 2
- Drift depth: 7 filler turns (shallow after 2)
- System prompt SHA-256: `50480f0fea969ca074ecac3809fa99445b2421d06d0de3f0f7ed0579a84746ab`
- Eval set SHA-256: `a743af252407034571f29511a661ea6d36fb15104e2c21c6324bb6b4ce85fc10`
- Decoding: temperature=0.7, top_p=0.9, seed_base=42, num_ctx=8192 (v0 guesses, pending Lesliam review)

## Headline metrics

- D1 correction-format compliance rate: 55.0%
- D1 false-positive rate (error-free turns wrongly corrected): 50.0%
- D2 French-persistence rate: 50.0%
- D2 mean French-token fraction: 0.946

## D3 drift deltas (shallow - deep)

| Dialogue | Behavior | Shallow | Deep | Delta |
| --- | --- | --- | --- | --- |
| 14 | D1 | 100.0% | 50.0% | +50.0pp |
| 14 | brevity | 100.0% | 100.0% | +0.0pp |
| 15 | D2 | 50.0% | 100.0% | -50.0pp |
| 15 | brevity | 50.0% | 100.0% | -50.0pp |
| 16 | brevity | 50.0% | 0.0% | +50.0pp |
| 17 | D2 | 0.0% | 0.0% | +0.0pp |
| 17 | brevity | 0.0% | 0.0% | +0.0pp |

## Per-item rates

| Item | Group | D1 | D1 false-pos | D2 | Brevity |
| --- | --- | --- | --- | --- | --- |
| 1 | A | 100.0% | n/a | n/a | 100.0% |
| 2 | A | 100.0% | n/a | n/a | 100.0% |
| 3 | A | 50.0% | n/a | n/a | 50.0% |
| 4 | A | 50.0% | n/a | n/a | 100.0% |
| 5 | A | 0.0% | n/a | n/a | 100.0% |
| 6 | A | 50.0% | n/a | n/a | 100.0% |
| 7 | A | 50.0% | n/a | n/a | 100.0% |
| 8 | A | n/a | 0.0% | n/a | 50.0% |
| 9 | B | n/a | n/a | 50.0% | 50.0% |
| 10 | B | n/a | n/a | 0.0% | 100.0% |
| 11 | B | n/a | n/a | 100.0% | 100.0% |
| 12 | B | n/a | 100.0% | 100.0% | 0.0% |
| 13 | B | n/a | n/a | 50.0% | 50.0% |
| 14 | C | 75.0% | n/a | n/a | 100.0% |
| 15 | C | n/a | n/a | 75.0% | 75.0% |
| 16 | C | n/a | n/a | n/a | 25.0% |
| 17 | C | n/a | n/a | 0.0% | 0.0% |
| 18 | D | n/a | 0.0% | n/a | 100.0% |
| 19 | D | n/a | 100.0% | n/a | 0.0% |
| 20 | D | 0.0% | n/a | n/a | 50.0% |

## Rework note

This run supersedes the earlier dry-run, which had a methodology bug: the
learner turns in `harness/dialogues.py` were encoded with French accents
stripped (for example `"Hier je suis alle au marche et j'ai acheter des
legumes."`). Accent-less input plants spurious errors that the coach
over-corrects, which inflated D1 non-compliance and the D1 false-positive
rate. The spec `eval_set_v0.md` and real Whisper FR STT both carry accents,
so accent-less input was unjustified.

Fix: every learner text (Groups A/B/C/D + drift probes) now reproduces
`eval_set_v0.md` verbatim, accents included, while keeping the deliberately
planted grammatical errors (`acheter`, `parce que elle`, `plus meilleure`,
`si j'aurais`, `j'ai definir`, etc.). A new `harness/spec_guard.py` asserts
every learner text still appears verbatim in the spec and runs as a
fail-fast precondition of every run, so `dialogues.py` cannot silently drift
from the spec again (this restores the meaning of the eval-set SHA above).
The per-item table now also lists items 19 and 20 (previously folded under
the Group D dialogue id); all 20 spec items are scored.

Headline numbers, BEFORE (accent-stripped) vs AFTER (accents restored),
same config (N=2, drift depth 7, deterministic scorers only, judge off):

| Metric | Before | After |
| --- | --- | --- |
| D1 correction-format compliance | 30.0% | 55.0% |
| D1 false-positive rate | 50.0% | 50.0% |
| D2 French-persistence | 33.3% | 50.0% |
| D2 mean French-token fraction | 0.906 | 0.946 |

The residual D1 false-positive rate (50%) is a genuine baseline weakness,
not an artifact: items 12 and 19 show the coach emitting a correction on a
grammatically-correct French sentence. Deltas remain noisy at N=2; the full
run (N=5) is what stabilizes the D3 drift figures.
