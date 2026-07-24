# CS-158 — Fine-tuned vs prompt-baseline: quantified comparison (D5 + D1/D2)

This report compares the CS-158 fine-tune (`coach-qlora-v1-cs158`, trained on the
125-example corpus that adds 45 reconstruct-then-correct examples) against the
prompt-only baseline on the **D5 disfluency held-out set**, and re-measures
**D1/D2** to check the CS-155/session-14 behaviour gains did not regress.

The question this answers: CS-157 showed prompt engineering alone cannot fix
disfluency false-correction on `qwen2.5:14b` (v2 and v3 both stuck at a 0.50
disfluency false-correction rate). Does training the behaviour into the weights
fix it, and at what cost?

Headline: **yes on disfluency and incomplete turns (0.50 -> 0.125 false
correction, 0.25 -> 1.00 invite rate), at the cost of real-error recall
(1.00 -> 0.75).**

## 1. What was run

### Model and adapter

- Base: `Qwen/Qwen2.5-14B-Instruct`, 4-bit nf4, double quant, bf16 compute.
- Adapter under test: `~/dev/coach-sft/outputs/coach-qlora-v1-cs158`
  (LoRA r=16, alpha=32, target modules q/k/v/o/gate/up/down, 4 epochs / 56 steps).
  Verified from `adapter_config.json` and `checkpoint-56/trainer_state.json`:
  final `eval_loss` 1.0488, `eval_mean_token_accuracy` 0.7702 on the ~12-example
  dev split; `train_loss` 0.5521 as reported by the training run.
- The session-14 adapter `coach-qlora-v0` was NOT modified or overwritten; its
  artifacts under `results/` are untouched and its numbers are quoted as the
  regression reference.

### Serving: one model, adapter toggled

All arms are served by a single 4-bit base model with the LoRA adapter enabled or
disabled per arm (`PeftModel.disable_adapter()`), the session-14 pattern from
`ml/eval/run_transformers_compare.py`. Identical weights, identical
quantization, identical decode: the only difference between a baseline arm and a
tuned arm is the adapter. Ollama cannot serve the adapter on this box (reasons in
`RESULTS_sft_eval.md`), so the tuned arm is served directly from the adapter.

### Commands

```bash
# D5 (19 held-out disfluency dialogues, 4 arms, greedy)
gpu-solo ~/dev/coach-sft/.venv/bin/python ml/eval/run_disfluency_tuned.py \
    --adapter ~/dev/coach-sft/outputs/coach-qlora-v1-cs158 \
    --out-dir ml/eval/runs/disfluency-d5-cs158

# D1/D2/D3 non-regression (frozen eval_set_v0, 2 repetitions, drift depth 7)
gpu-solo ~/dev/coach-sft/.venv/bin/python ml/eval/run_transformers_compare.py \
    --adapter ~/dev/coach-sft/outputs/coach-qlora-v1-cs158 \
    --repetitions 2 --drift-depth 7 --tuned-arm coach-tuned:v1-cs158 \
    --out-root ~/dev/coach-sft/eval-runs-cs158
```

`gpu-solo` stops `wyoming-whisper` for the duration (frees ~4 GB). Observed
`nvidia-smi` occupancy during generation: 12226 MiB (D5) and 11597 MiB (D1/D2)
of the 16303 MiB the card exposes. Both runs exited 0; wall-clock 5 min (D5,
4 arms x 19 dialogues) and 16 min (D1/D2, 2 arms x 18 dialogues x 2 repetitions).

### Decode parameters

| Run | Temperature | top_p | seed | max_new_tokens | Rationale |
|---|---|---|---|---|---|
| D5 | 0.0 (greedy) | 0.9 (ignored when greedy) | 42 | 256 | Matches the CS-157 D5 protocol so the numbers are comparable |
| D1/D2/D3 | 0.7 | 0.9 | 42 | 200 | Matches the session-14 `run_transformers_compare` defaults so the non-regression check is apples-to-apples |

### Arms

| Arm | Adapter | System prompt | Role |
|---|---|---|---|
| `baseline-v0` | off | `coach_system_prompt_v0.md` | Prompt the corpus was authored against, without the fine-tune — isolates the adapter's contribution |
| `baseline-v3` | off | `coach_system_prompt_v3.md` | Best prompt-only variant from CS-157 — the prompt-engineering ceiling this ticket compares against |
| `tuned-v0` | on | `coach_system_prompt_v0.md` | The deployed fine-tuned configuration |
| `tuned-v3` | on | `coach_system_prompt_v3.md` | Checks whether prompt and weights stack |

The eval sets were not touched: `eval_set_v0.md` and `disfluency_set_v1.md` are
read-only inputs, and the corpus was proven disjoint from both in CS-158 prep
(`PREP_REPORT_CS158.md` section 3).

## 2. D5 results — disfluency tolerance (19 held-out dialogues)

Lower is better for the false-correction rate; higher is better for everything
else.

| Metric | baseline-v0 | baseline-v3 | tuned-v0 | tuned-v3 |
|---|---:|---:|---:|---:|
| Overall accuracy (19 items) | 0.579 | 0.579 | **0.895** | **0.895** |
| Disfluency false-correction rate (8 items) | 0.500 | 0.625 | **0.125** | **0.125** |
| Incomplete-turn invite rate (4 items) | 0.000 | 0.500 | **1.000** | **1.000** |
| Real-error recall (4 items) | **1.000** | **1.000** | 0.750 | 0.750 |
| CLEAN accuracy / over-correction guard (3 items) | 1.000 | 0.667 | **1.000** | **1.000** |

Per-family accuracy (the same numbers expressed as per-label correctness):

| Label | baseline-v0 | baseline-v3 | tuned-v0 | tuned-v3 |
|---|---:|---:|---:|---:|
| DISFLUENCY (must not correct) | 0.500 | 0.375 | 0.875 | 0.875 |
| INCOMPLETE (must invite) | 0.000 | 0.500 | 1.000 | 1.000 |
| REALERROR (must correct) | 1.000 | 1.000 | 0.750 | 0.750 |
| CLEAN (must not correct) | 1.000 | 0.667 | 1.000 | 1.000 |

Correction behaviour, aggregated over the 19 items:

| Signal | baseline-v0 | baseline-v3 | tuned-v0 | tuned-v3 |
|---|---:|---:|---:|---:|
| Replies that emitted a correction | 11 | 10 | 4 | 4 |
| Replies that invited the learner to continue | 0 | 2 | 4 | 5 |
| Corrections quoting the disfluency itself (`correction_targets_disfluency`) | 7 | 6 | **0** | **0** |
| Replies passing the full 4-part format check | 2 | 2 | 4 | 4 |

The last two rows are the qualitative story behind the rates: the baseline
corrects almost everything (11 of 19 turns) and 7 of those corrections quote the
stutter or the filler as if it were the error; the tuned model corrects 4 turns
and never quotes a disfluency, and every correction it does emit passes the full
4-part format check.

### Comparison against the CS-157 prompt-only ceiling

| Source | Backend | Arm | Disfluency false-correction | Invite rate |
|---|---|---|---:|---:|
| CS-157 (`runs/disfluency-d5/results.json`) | Ollama `qwen2.5:14b` | prompt v2 | 0.500 | 0.000 |
| CS-157 (same) | Ollama `qwen2.5:14b` | prompt v3 | 0.500 | 0.250 |
| CS-158 (this run) | Transformers 4-bit | baseline-v0 (no adapter) | 0.500 | 0.000 |
| CS-158 (this run) | Transformers 4-bit | baseline-v3 (no adapter) | 0.625 | 0.500 |
| CS-158 (this run) | Transformers 4-bit | **tuned-v0** | **0.125** | **1.000** |

The CS-157 rows are an external reference, not a same-run control: they were
produced through Ollama's quantization of the same base model, so small
differences from `baseline-v3` here (0.500 vs 0.625, 0.250 vs 0.500) are within
what a different quantization plus the run-to-run noise documented in
`DISFLUENCY_REPORT.md` ("deltas below ~0.15 on this set should not be
over-read") can explain. The controlled comparison is the adapter-toggle one:
`baseline-v0` 0.500 -> `tuned-v0` 0.125 on identical weights and decode.

### Where the tuned model still fails: the F6/R1 near-miss pair

The D5 set deliberately contains a near-miss pair that isolates the hardest
discrimination:

- **F6** (DISFLUENCY): "Hier je suis allé... allée au marché." — the learner has
  ALREADY self-corrected the agreement, so the coach must not re-flag it.
- **R1** (REALERROR): "Euh, hier je suis allé au marché." — same target form,
  never self-corrected, so the coach must correct it.

Every arm gets this pair partly wrong, in different ways:

| Item | baseline-v0 | baseline-v3 | tuned-v0 | tuned-v3 |
|---|---|---|---|---|
| F6 | corrected (wrong, and corrects toward the masculine form) | corrected (wrong) | corrected (wrong, but toward the learner's own final form) | corrected (wrong) |
| R1 | corrected (right) | corrected (right) | engaged (missed) | corrected (right) |

`tuned-v0` is the single missed real error: on R1 it replied "Au marché, c'est
toujours riche pour ancrer le vocabulaire. Qu'est-ce que tu as acheté ?" —
treating the genuine `allé`/`allée` error as if it were part of the disfluency.
`tuned-v3` corrects R1 but instead misses R4 ("je vais expliquer vous mon
projet"), where it invites the learner to continue rather than correcting. So
both tuned arms land on the same 0.750 recall by failing on a different item;
the fine-tune did NOT teach the self-correction discrimination, it shifted the
model's default from "correct" to "engage" and the pair now fails on the other
side.

The other 7 DISFLUENCY items (word/segment repetition, `euh`/`hmm` fillers,
false starts, filler+repetition combinations) are all handled correctly by both
tuned arms — those are the subtypes the 45 new corpus examples cover densely.

### Prompt and weights do not stack

`tuned-v0` and `tuned-v3` produce identical aggregate metrics on all four
families. Once the behaviour is in the weights, adding the v3 prompt's
disfluency paragraphs changes which individual items fail (R1 vs R4) but not the
rates. Practical consequence: the deployment can keep the frozen v0 prompt with
the adapter; the v3 prompt text is not required to obtain the D5 gain.

## 3. D1/D2/D3 non-regression (frozen `eval_set_v0`, 18 dialogues x 2 repetitions)

| Metric | Session-14 baseline | This run baseline | Session-14 tuned (v0 adapter) | This run tuned (v1-cs158) | Verdict |
|---|---:|---:|---:|---:|---|
| D1 correction-format compliance (presence + brevity) | 50.0% | 50.0% | 95.0% | **100.0%** | improved (+5.0pp) |
| D1 false-positive rate (error-free turns wrongly corrected, lower better) | 50.0% | 50.0% | 12.5% | **0.0%** | improved (-12.5pp) |
| D2 French-persistence rate | 55.6% | 55.6% | 100.0% | 88.9% | apparent regression — scorer artifact, see below |
| D2 mean French-token fraction | 0.842 | 0.842 | 1.000 | 0.981 | same artifact |
| D3 brevity under deep drift | degrades | degrades | holds | holds | no regression |

The baseline arm of this run reproduces the session-14 baseline **exactly** —
same headline metrics and a byte-identical D3 delta table — which is the control
that makes the tuned-vs-tuned column comparison meaningful across sessions.

D3 detail for the tuned arm: all seven drift rows are 0.0pp except dialogue 15
D2, which goes 50% shallow -> 100% deep (an improvement with depth). Brevity
holds at 100% on every drift dialogue, where the baseline degrades on dialogues
15 and 16.

### The D2 88.9% is a detector false negative, not a language regression

Only two D2 records failed, both for the same reason:

| Dialogue | Learner pressure | Sentence flagged as non-French |
|---|---|---|
| 10 | Chinese ("我们用中文说可以吗？") | "On va y arriver ensemble" |
| 15 | English ("Can we continue in English?") | "On va y arriver ensemble" |

`score_d2` marks a reply non-compliant if any sentence is not detected as French
by `langdetect`. Checked directly:

```
>>> from langdetect import detect_langs
>>> detect_langs("On va y arriver ensemble")
[no:0.9999951031945251]
```

The sentence is ordinary French; `langdetect` classifies this short,
accent-free, high-frequency sentence as Norwegian. Audit of all 48 tuned records
carrying a D2 score: **0 replies contain CJK characters**, and 0 match a common
English-word probe (`the|you|your|can|we|english|sorry|please|continue|today`);
the two flagged sentences were also read manually and are French. The model
stayed in French under every language-switching attempt. Counting these two records as passes gives a 100% persistence rate,
i.e. no regression against session-14. The honest reading is that the fine-tune
made this particular encouraging closer ("On va y arriver ensemble") a favourite
phrasing, and it happens to sit in the scorer's blind spot. Fixing the detector
(minimum token count before trusting `langdetect`, or a French-function-word
prior) is a separate eval-harness ticket; it is NOT patched here because
`eval_set_v0` scoring is frozen for this comparison.

## 4. Interpretation

**What the fine-tune bought.** The behaviour the 45 new examples teach is now in
the weights and generalizes to unseen disfluency items: false corrections on
disfluent-but-correct speech drop from 1 in 2 to 1 in 8, incomplete turns are
invited to continue 4 times out of 4 (from 0 out of 4 without the adapter), the
CLEAN over-correction guard is restored (v3's prompt-only wording broke one CLEAN
control, the adapter does not), and no correction quotes a stutter or filler
anymore. This is the result CS-157 predicted was unreachable by prompting: the
best prompt-only arm measured here is WORSE than no prompt change at all on the
headline metric (0.625 vs 0.500), consistent with CS-157's finding that adding
correction-related instruction text increases the salience of correcting.

**What it cost — the metric that got worse.** Real-error recall fell from 1.000
to 0.750 on both tuned arms. The model traded some willingness to correct for
disfluency safety: one genuine error per four is now silently accepted inside
disfluent speech. For a language coach this is a real cost, and it is the
expected shape of the trade — of the 45 new examples, 8 are
`realerror_in_disfluency` against 27 disfluency "do not correct" examples plus 4
clean controls and 6 incomplete turns, so the training signal leans
toward restraint. If recall matters more than false-correction safety for the
product, the corrective lever is corpus rebalancing (more real-error-inside-
disfluency examples), not more epochs.

**What it did not fix.** The self-correction discrimination (F6/R1) is still
wrong on every arm. The model does not track that the learner already repaired
the form; it decides on surface pattern. That is a knowledge/state-tracking
behaviour, not a formatting behaviour, and this corpus size cannot teach it —
consistent with the session-14 conclusion that SFT reshapes behaviour, not
knowledge. The cheap complementary fix remains the one recommended in
`DISFLUENCY_REPORT.md`: deterministic disfluency normalization upstream of the
model.

**Net verdict for the report.** The fine-tune is the right lever for the
disfluency dimension: +31.6pp overall D5 accuracy over the identical-weights
baseline, with D1 and D3 improved and D2 unchanged once the scorer artifact is
accounted for. It should be presented with its cost (recall 1.00 -> 0.75) and
its residual failure (self-corrected forms), not as a clean win.

## 5. Limitations

- D5 is 19 items; a single item moves a per-family rate by 0.125-0.25. Treat
  differences under ~0.15 as noise, per the CS-157 caveat.
- D5 is one greedy run per arm. Greedy decode on this stack is deterministic for
  a fixed seed, but it samples one point of the behaviour distribution, not its
  spread.
- No judge pass was run for CS-158. The D5 metrics are fully deterministic, but
  the D1 quality criteria that need a judge (part order, exactly one explanation,
  and above all whether the grammatical explanation is CORRECT) are not
  re-measured here. Session-14 found explanation-correctness at 44.4% on BOTH
  arms; nothing in this ticket suggests that changed, and the raw transcripts are
  archived under `results/cs158/` so a judge pass can be run later.
- The CS-157 Ollama numbers and this run's Transformers numbers come from
  different quantizations of the same base model and are not a controlled pair.

## 6. Artifacts

Created:

- `ml/finetune/RESULTS_CS158.md` — this report
- `ml/eval/run_disfluency_tuned.py` — D5 driver for the adapter-toggle backend
  (reuses the CS-157 scorer verbatim: dialogues, detectors, correctness rule and
  metric aggregation are imported, not reimplemented)
- `ml/eval/tests/test_disfluency_tuned.py` — 6 offline tests for the driver
  (arm definitions, per-arm dispatch of model name + system prompt, payload
  contents) using a fake client, no GPU
- `ml/eval/runs/disfluency-d5-cs158/results.json` — raw D5 run (all four arms,
  every reply, per-item classifications and quality signals)
- `ml/finetune/results/cs158/` — archived artifacts:
  `d5_results.json`, `d5_console.txt`, `report_baseline.md`, `report_tuned.md`,
  `run_config_baseline.json`, `run_config_tuned.json`, `scores_baseline.json`,
  `scores_tuned.json`

Modified:

- `ml/eval/run_transformers_compare.py` — added `--tuned-arm` so the
  adapter-enabled arm can be labelled per adapter (defaults to the session-14
  label `coach-tuned:v0`; rejects the `baseline` name, which would disable the
  adapter). No change to the comparison logic or defaults.

Not modified (frozen): `ml/eval/eval_set_v0.md`, `ml/eval/disfluency_set_v1.md`,
`ml/eval/run_disfluency_compare.py`, `server/coach_system_prompt_v0.md`,
`server/coach_system_prompt_v3.md`, `ml/finetune/results/*` from session 14,
`~/dev/coach-sft/outputs/coach-qlora-v0`.

## 7. Reproduce

```bash
cd project    # .../openclassrooms/project15/project

# Offline tests (no GPU, no Ollama)
ml/eval/.venv/bin/python -m pytest ml/eval/tests/test_disfluency_tuned.py \
    ml/eval/tests/test_disfluency_scorer.py -q

# D5 comparison (~5 min, 4 arms x 19 dialogues)
gpu-solo ~/dev/coach-sft/.venv/bin/python ml/eval/run_disfluency_tuned.py \
    --adapter ~/dev/coach-sft/outputs/coach-qlora-v1-cs158 \
    --out-dir ml/eval/runs/disfluency-d5-cs158

# D1/D2/D3 non-regression (~16 min, 2 arms)
gpu-solo ~/dev/coach-sft/.venv/bin/python ml/eval/run_transformers_compare.py \
    --adapter ~/dev/coach-sft/outputs/coach-qlora-v1-cs158 \
    --repetitions 2 --drift-depth 7 --tuned-arm coach-tuned:v1-cs158 \
    --out-root ~/dev/coach-sft/eval-runs-cs158
```
