# CS-157 — Disfluency tolerance / incomplete-turn report (dimension D5)

## Problem

In spontaneous speech the learner hesitates (« euh », « hmm »), repeats a word
or a segment (« je je », « le le »), makes false starts, and self-corrects while
she is still THINKING. Two risks with the deployed prompt v2:

- (a) it may "correct" a repetition, a hesitation, a false start or an
  already-self-corrected form as if it were a language error;
- (b) it may treat a turn that Home Assistant's voice-activity detection cut off
  early as a complete thought and correct / analyse an unfinished utterance.

The "when to stop listening" side (VAD) is handled separately on the HA side and
is out of scope here; this ticket is purely the prompt + eval.

## v3 design — two additions on top of v2

v3 (`../../server/coach_system_prompt_v3.md`) = the full text of v2 PLUS two
additions in the correction logic. v2 stays as the comparison baseline; v0/v1
stay as prior artifacts (v0 FROZEN for the fine-tuning corpus + eval baseline).

1. **Disfluency tolerance** — the coach reconstructs the INTENDED sentence and
   corrects ONLY genuine language errors in that intended meaning; it never
   corrects the disfluency itself, and it never re-flags a form the learner
   already self-corrected (« je suis allé... allée » → keep « allée »). A real
   error hidden inside disfluent speech is STILL corrected (once, the most
   important), just ignoring the disfluency. This extends the existing
   anti-over-correction guard.
2. **Incomplete / cut-off turn** — if the turn looks cut off, trailing or
   unfinished, the coach does NOT force a correction or a full analysis; it
   gently invites the learner to continue (« Prends ton temps, je t'écoute »,
   « Tu veux continuer ? ») and only analyses a complete thought. This case is
   deliberately narrow so it does not swallow ordinary complete turns.

## How D5 is measured

The dimension is named **D5** because `eval_set_v0.md` already uses D1-D3 and the
CS-156 mini-eval added D4. The mini-eval (`disfluency_set_v1.md` +
`run_disfluency_compare.py`) is deliberately separate from the frozen harness.

- 19 single-turn labelled dialogues: 8 DISFLUENCY (must NOT correct), 4
  INCOMPLETE (must invite to continue), 4 REALERROR (a genuine error inside
  disfluent speech — must correct, ignoring the disfluency), 3 CLEAN controls
  (ordinary correct turns — must NOT correct). Near-misses are deliberate, e.g.
  F6 « je suis allé... allée » (self-corrected → do NOT re-flag) vs R1 « euh,
  hier je suis allé au marché » (genuine, never self-corrected → correct it).
- Deterministic CPU detectors (no Ollama), reusing the frozen harness's
  correction API (`harness.scorers.d1_correction_emitted` / `score_d1`):
  `correction_emitted` (restatement + corrected version), `invites_to_continue`
  (continue-invitation phrasing), and `classify_reply` → `{corrected, invited,
  engaged}`. A `correction_targets_disfluency` quality signal flags whether a
  quoted, restated span is itself a stutter or filler.
- Per-item correctness: DISFLUENCY correct iff NOT `corrected`; INCOMPLETE
  correct iff `invited`; REALERROR correct iff `corrected`; CLEAN correct iff NOT
  `corrected`.
- The scorer runs the model live: each dialogue is sent once with the v2 prompt
  and once with the v3 prompt to `qwen2.5:14b` via Ollama (host resolved from
  `OLLAMA_HOST` / `OLLAMA_BASE_URL`, never hardcoded), greedy decode
  (temperature 0) for reproducibility. If Ollama is unreachable it writes
  deterministic-only results and exits cleanly; the unit tests pass offline
  regardless. Artifact: `runs/disfluency-d5/results.json`.

### Why the disfluency-false-correction rate is the headline number

The core risk is that the coach "corrects" thinking-aloud that is not an error —
turning a natural hesitation into a needless drill and killing the learner's
flow. **Disfluency-false-correction rate** = fraction of DISFLUENCY turns wrongly
given a correction. It directly measures that risk. A good fix must drive this
toward 0 while KEEPING **real-error recall within disfluent speech** at 1.0 (the
two must not trade off) and correctly **inviting to continue** on cut-off turns.

## Results — v2 vs v3

Live run: `qwen2.5:14b` via Ollama, both arms on the same 19 dialogues, greedy
decode (temperature 0, top_p 0.9, seed 42, num_ctx 8192). Artifact:
`runs/disfluency-d5/results.json`.

| Metric | v2 | v3 |
|--------|----|----|
| Overall accuracy | 0.579 | 0.632 |
| **disfluency-false-correction rate** (headline; lower is better) | **0.500** | **0.500** |
| **real-error recall** within disfluent speech | **1.000** | **1.000** |
| **incomplete-turn invite rate** | **0.000** | **0.250** |
| DISFLUENCY accuracy | 0.500 | 0.500 |
| INCOMPLETE accuracy | 0.000 | 0.250 |
| REALERROR accuracy | 1.000 | 1.000 |
| CLEAN accuracy | 1.000 | 1.000 |

Reading:

- **No regression, one real gain.** v3 keeps disfluency-false-correction level
  with v2 (0.500), keeps real-error recall at 1.000 and CLEAN at 1.000, and it
  is the ONLY arm that ever invites on a cut-off turn (incomplete-invite
  0.000 → 0.250, on the clearest trailing case I3 « ...c'est que... euh... »).
  Overall accuracy rises 0.579 → 0.632.
- **The headline target (~0) is NOT reached by prompt alone.** Four disfluency
  turns are wrongly corrected on BOTH arms every run: F1 (« je je »), F3
  (« euh »), F6 (self-corrected « allé... allée »), F8 (« le le »). The model
  restates the disfluent fragment in « Tu as dit : ... » and rewrites it « for
  fluidity », which is exactly the failure v3 was meant to remove.

### Prompt-strengthening experiment (why v3 is worded the way it is)

Before settling on the shipped wording, three progressively stronger variants of
the two additions were measured live against the same set:

| v3 variant | disfluency-false-correction rate |
|------------|----------------------------------|
| moderate (shipped) | 0.50 |
| + explicit negative examples (« je je », « le le »…) | 0.75 |
| + positive "reconstruct-first" two-step framing | 0.75 |
| + restrict "real error" to grammar-only, forbid style/fluency edits | 0.875 |

Adding MORE correction-related instruction text made `qwen2.5:14b` correct
disfluencies MORE, not less — the added salience of the "correction" topic pulls
its strong instruction-following prior toward commenting on the very repetitions
and fillers it was told to ignore (the last variant even broke a CLEAN control).
The moderate wording is therefore the one shipped: it expresses the intent
clearly, adds the working incomplete-turn behaviour, and does not inflate the
false-correction rate.

### Reproducibility caveat

Greedy decode via Ollama (llama.cpp) is not bit-reproducible: two runs of the
identical moderate prompt classified F4 differently (corrected vs engaged),
moving the 8-item DISFLUENCY rate by one item (~0.125). The persistent failures
(F1/F3/F6/F8) are stable across runs; small deltas below ~0.15 on this set are
within run-to-run noise and should not be over-read.

## Conclusion and recommendation

Prompt-only tuning does not drive the disfluency-false-correction rate to ~0 on
`qwen2.5:14b`; pushing harder in the prompt is counterproductive. The shipped v3
is the best-behaved prompt found (no regression, plus working incomplete-turn
handling), and it doubles as the behavioural spec for the next step. To actually
reach ~0, use one or both of:

- **Fine-tuning** (the project's `ml/finetune` SFT arm): train the
  reconstruct-then-correct behaviour into the model, using D5 as the held-out
  metric. This is the project's intended lever for behaviours prompt cannot fix
  and matches the "coach behaviour fine-tuning vs prompt baseline with
  quantified eval" methodology core.
- **Deterministic disfluency normalization upstream**: strip immediate word/
  segment repetitions and fillers (« euh », « hmm ») from the transcript before
  the model sees it, so there is no disfluent fragment left to "correct". This is
  cheap, model-agnostic, and directly removes F1/F3/F8-type failures; it does not
  help the self-correction case F6, which fine-tuning covers.

## Reproduce

```bash
OLLAMA_HOST=<host:port> \
    ml/eval/.venv/bin/python ml/eval/run_disfluency_compare.py
ml/eval/.venv/bin/python -m pytest ml/eval/tests/test_disfluency_scorer.py -q
```
