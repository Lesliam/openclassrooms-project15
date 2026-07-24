# Coach SFT — fine-tuned vs prompt-baseline results

This report records the outcome of the coach behavior fine-tune (the tuned arm
of the experiment) measured against the frozen prompt baseline, using the
evaluation harness in `../eval`.

## What was run

- **Training**: QLoRA 4-bit SFT of `Qwen/Qwen2.5-14B-Instruct` on the 80-example
  hand-authored corpus (`corpus/coach_sft.jsonl`), config `sft_config.yaml`,
  runner `train_sft.py` (TRL `SFTTrainer`, LoRA r=16, 4 epochs). Final
  `train_loss` 0.644, eval token-accuracy 0.81 on the 8-example held-out split.
- **Serving both arms**: one 4-bit base model, LoRA adapter toggled on/off
  (`../eval/run_transformers_compare.py`). Both arms therefore share identical
  weights, identical nf4 quantization, and identical decode — the ONLY
  difference is the adapter. This is a tighter control than serving the two
  arms through separately-quantized Ollama tags.
- **Eval scope (v0 defaults, `eval_set_v0.md` §5 still open)**: 18 dialogues,
  2 repetitions, drift depth 7, temperature 0.7. These are documented defaults
  pending the §5 parameter decision (repetitions, drift depth, token-overlap
  threshold), not final parameters.

> Why the Transformers backend and not Ollama: this box's Ollama binds a LAN IP
> only (safetensors model creation is refused as "remote"), and its Linux build
> cannot quantize a safetensors `lm_head` (requires MLX). Rather than change the
> production Ollama binding, the tuned arm is served directly from the adapter.

## Deterministic metrics (marker presence + brevity)

| Metric | Baseline | Tuned |
|---|---|---|
| D1 correction-format compliance (presence + brevity) | 50.0% | 95.0% |
| D1 false-positive rate (error-free turns wrongly corrected) | 50.0% | 12.5% |
| D2 French-persistence rate | 55.6% | 100.0% |
| D2 mean French-token fraction | 0.842 | 1.000 |
| D3 brevity under deep drift | degrades (−50pp) | holds |

The deterministic scorer checks that the four correction markers are PRESENT and
the reply is short. It does NOT check part order, the "exactly one explanation"
rule, or whether the explanation is grammatically correct. Those require a judge.

## Judge verdicts (nuanced criteria the scorer cannot check)

A judge graded all 38 D1/D2/false-positive items on both arms
(`../../../dev/coach-sft/eval-runs/judge/verdicts.{json,md}`, raw verdicts frozen).

| Criterion | Baseline | Tuned |
|---|---|---|
| D1 order correct | 66.7% | 94.4% |
| D1 exactly one explanation | 100% | 94.4% |
| **D1 explanation grammatically correct** | **44.4%** | **44.4%** |
| False-positive: wrongly corrected (lower better) | 50.0% | 12.5% |
| D2 fully French | 50.0% | 100% |
| D2 natural invitation back to French | 25.0% | 100% |

## Conclusion — behavior improved, knowledge did not

The fine-tune delivered exactly what the corpus taught and nothing it did not:

- **Behavior consistency improved sharply**: the 4-part correction format and its
  order, French-only persistence under English/Chinese pressure, the closing
  repeat-request, robustness under long-context drift, and a large drop in
  false corrections on error-free turns.
- **Grammatical correctness did NOT improve** (explanation-correct 44.4% on both
  arms). Roughly half of tuned corrections still ship a wrong grammatical
  justification, and the tuned model fabricates them more confidently. Examples
  of fabricated rules are logged in `verdicts.md`.

This is the expected result and it validates the stated hypothesis
(`README.md`): the experiment tests **behavior consistency, not knowledge
injection**. Eighty behavior-shaping examples cannot teach a 14B model French
grammar it does not already reliably know; they can and did reshape how it
formats, persists, and paces its replies. The practical implication for the
coach product: the fine-tune is a net win for interaction discipline, but the
grammatical content of corrections must not be trusted as authoritative — a
retrieval or rule-checked correction layer would be the next step, not more SFT.

## Reproduce

```bash
# Train (VRAM-bound, under gpu-solo — see README.md "Run the SFT later"):
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  gpu-solo python ml/finetune/train_sft.py --config ml/finetune/sft_config.yaml

# Merge for serving (CPU):
python ml/finetune/merge_export.py \
  --adapter ~/dev/coach-sft/outputs/coach-qlora-v0 \
  --out ~/dev/coach-sft/outputs/coach-merged

# Compare both arms (Transformers backend, adapter toggled):
python ml/eval/run_transformers_compare.py \
  --adapter ~/dev/coach-sft/outputs/coach-qlora-v0 \
  --repetitions 2 --drift-depth 7 --out-root ~/dev/coach-sft/eval-runs
```
