# Coach correction correctness — grammar-grounding layer

This report records the correctness layer added on top of the fine-tuned coach
(see `../ml/finetune/RESULTS_sft_eval.md`). The fine-tune improved the coach's
behavior but left grammar-explanation correctness unchanged (~40% of
corrections shipped a fabricated rule). This layer targets that gap.

## The idea

Fine-tuning (SFT) shapes behavior, not knowledge. Correctness of factual
grammar has to be grounded in an authoritative source, not generated from the
model's memory. The layer:

1. Detects the error and produces the corrected form with a local French
   grammar-error-correction model (`PoloHuggingface/French_grammar_error_corrector`,
   run offline on CPU; the learner text never leaves the machine).
2. Explains the correction with a **deterministic rule template** keyed on the
   edit category (elision, preposition+article contraction, accent, participe
   passé after *avoir*, past-participle agreement with a preceding direct
   object, adjective/determiner agreement). The coach model is NOT involved in
   the correction — no fabricated rules are possible.
3. A **precision gate**: only corrects when the edit classifies as a real
   grammar rule. Purely lexical or cosmetic changes proposed by the engine
   (e.g. `le planning -> la planification`) are suppressed and the turn falls
   through to the tuned model — the coach never tells a correct learner they
   were wrong.

## Result (judge over the D1 correction turns)

Three conditions, same 18 D1 turns, judged for explanation correctness, form,
and concision:

| Metric | prompt baseline | fine-tuned (tuned) | grounded (this layer) |
|---|---|---|---|
| explanation grammatically correct | ~44% | ~40% (25% on the fired subset) | **100%** (on the turns it fires) |
| corrected form right | — | ~83% | **100%** |
| concise (restates only the erroneous phrase) | — | ~58% | **100%** |

The three arms were judged by an independent grader across iterations; raw
verdicts are frozen in `results/` and `../ml/finetune/results/`.

The harness's own deterministic metrics (marker presence + brevity, computed by
`ml/eval`, not the judge) confirm the same ranking:

| Deterministic metric | baseline | tuned | grounded |
|---|---|---|---|
| D1 correction-format compliance | 50.0% | 95.0% | **100.0%** |
| D1 false-positive rate | 50.0% | 12.5% | 12.5% |
| D2 French-persistence | 55.6% | 100% | 100% |

The grounded arm's false-positive rate is back to the tuned arm's 12.5% (the
pre-precision-gate v2 had regressed it to 37.5% by over-correcting), and D1
compliance is 100% because corrections are now concise by construction.

### An honest iteration trail (kept because it is the lesson)

- **v1 — ground the form only, let the model write the explanation**: explanation
  correctness got WORSE (27.8%). Handing the model the right answer did not stop
  it fabricating the reason. This is the key finding: the model's grammatical
  *reasoning* is unreliable independent of whether it knows the answer.
- **v2 — deterministic rule-template explanations**: explanation correctness
  jumped to 85.7%, concision to 100%, but the engine's lexical over-correction
  (`le planning -> la planification`) produced one false positive.
- **v3 — precision gate (only correct classifiable grammar edits)**: the false
  positive is gone and, on the turns it fires, the layer is 100% correct on all
  three axes.

## The trade-off — precision bought with recall

The gate declines on 6 of 18 D1 turns whose real errors fall outside the
template coverage (subjunctive mood, the irregular comparative `plus meilleure`,
`si` + conditional). It does not correct them — it routes them to the tuned
model. So:

- **Grounded layer**: high precision (never wrong when it speaks), limited
  recall (only the grammar categories it has templates for).
- **Tuned model**: high recall (attempts every turn), low explanation precision
  (fabricates rules).

They are complementary, which is the architecture: a **precision-first grounded
layer with a model fallback**. The coach speaks with authority on the grammar
categories it has grounded, and defers to the fine-tuned model (behaviorally
strong, factually softer) on the rest.

## Answering "how do we improve correctness / knowledge?"

Not with more fine-tuning. SFT cannot inject reliable grammatical reasoning into
the model. Correctness comes from grounding: an authoritative engine for the
form and deterministic rule templates for the explanation, gated on precision.
The remaining gap (recall) is closed by widening template coverage or swapping
in a stronger grammar engine — not by more training. This is the productized
version of the report's conclusion: **SFT for behavior, grounding for facts.**

## Known limitation

Residual misses are the grammar engine's detection limits (it under-detects
error types it was not trained on) and the finite template set — both are
coverage/engineering boundaries, not fabrication. The layer's contract is: when
it corrects, it is right; when it is unsure, it stays silent.
