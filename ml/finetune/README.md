# Coach behavior SFT (fine-tuning arm)

This directory prepares the **fine-tuned arm** of the coach experiment: an
SFT (supervised fine-tuning) corpus plus a QLoRA training config. The eval
harness in `../eval` measures the SAME `qwen2.5:14b` model with the frozen
prompt alone (baseline arm) versus after this fine-tuning (tuned arm), on the
held-out `../eval/eval_set_v0.md`.

The hypothesis being tested is **behavior consistency**, not knowledge:
French-only persistence under English/Chinese pressure, the fixed 4-part
correction format, spoken-style brevity, Socratic relance, and the
"simulation soutenance" (Charlotte) persona — and that these hold up better
under long-context drift than the prompt baseline.

> Status: PREPARATION ONLY. No training has been run. The full run waits for
> Lesliam to be present, `gpu-solo` to free whisper's VRAM, and the §5 judge
> decision in the eval design. See "Run the SFT later" below.

## Files

| File | Purpose |
|------|---------|
| `corpus/coach_sft.jsonl` | 80 hand-authored chat examples (system + learner + ideal coach reply). |
| `build_corpus.py` | Assembles the JSONL; reads the system prompt VERBATIM from the frozen baseline prompt. |
| `check_leakage.py` | Asserts the corpus is disjoint from the eval set (CPU only). |
| `sft_config.yaml` | QLoRA 4-bit training config (documented, not run). |
| `DATA_SEPARATION.md` | How train/eval disjointness is guaranteed + the check result. |
| `PREP_REPORT.md` | Corpus counts, leakage result, config summary, files to commit. |

## Corpus design rationale

- **Chat format, shared frozen system prompt.** Every example carries the
  exact body of `../../server/coach_system_prompt_v0.md` as its system
  message. `build_corpus.py` reads that file at build time and extracts the
  text below the design-rationale `---` separator, so the corpus can never
  drift from the baseline prompt — both experiment arms must share it.
- **Hand-authored for correctness.** Each ideal coach reply itself obeys the
  coach contract: French only, the 4-part correction format (`Tu as dit ... /
  On dit plutôt ... / one explanation / Peux-tu répéter ...`) when the learner
  turn has a planted error, `<= 3` sentences of spoken register otherwise,
  and a closing question or invitation to speak. Replies were validated to
  contain no CJK, to keep corrections `<= 4` sentences and non-corrections
  `<= 3`, and to always end on a relance.
- **Behavior coverage** (the classes the eval scores):
  - D1 corrections across varied error types: agreement, elision,
    subjunctive, comparative, tense, plus gender / preposition / pronoun /
    anglicism / negation / subject-verb.
  - D1 false-positive avoidance: error-free learner turns that must NOT
    trigger the correction format (Socratic follow-up instead).
  - D2 French persistence under English AND Chinese pressure (the reply stays
    French, invites the learner back, never switches, no CJK).
  - Brevity: concise spoken explanations that resist over-explaining.
  - Simulation soutenance: the Charlotte persona asking one project-management
    question at a time (needs analysis, technical choices, project control),
    including corrections that still fire inside the persona.
- **Small and curated on purpose.** Behavior shaping needs far less data than
  knowledge injection, so the corpus is ~80 high-quality examples and the
  LoRA rank is modest (16) to avoid overfitting.

## Train / eval separation

Summarized here, detailed in `DATA_SEPARATION.md`. The corpus reuses no eval
learner turn. Same grammar *classes* appear (that is the skill taught), but
always with different sentences. `check_leakage.py` enforces zero exact
overlap and reports near-duplicates; current result is 0 overlaps, max
Jaccard 0.50.

```bash
cd <project-root>
python ml/finetune/check_leakage.py
```

## Rebuild the corpus (CPU, safe)

```bash
cd <project-root>
python ml/finetune/build_corpus.py     # rewrites corpus/coach_sft.jsonl
python ml/finetune/check_leakage.py     # re-verify disjointness
```

## Validate before running

`sft_config.yaml` uses axolotl-style keys. Axolotl's schema changes across
releases, so before any run:

1. Install a pinned axolotl into a venv and read its config docs for that
   version; confirm each key (`adapter`, `chat_template`, `field_messages`,
   `train_on_inputs`, `val_set_size`, `lora_target_modules`) still maps to the
   same behavior.
2. Print `model.named_modules()` once to confirm the Qwen2 projection names
   (`q_proj`, `k_proj`, ...) match the checkpoint.
3. Confirm the HF base weights (`Qwen/Qwen2.5-14B-Instruct`, revision) match
   the model Ollama serves as `qwen2.5:14b` — both arms must share the base.

If axolotl drifts, the fallback is a small TRL script:
`SFTTrainer` + `peft.LoraConfig` (same r/alpha/targets) +
`BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)`,
loading `corpus/coach_sft.jsonl` and applying the tokenizer chat template.

## Run the SFT later (RUN WHEN LESLIAM IS PRESENT, under gpu-solo)

This run is VRAM-bound. It must not start while Home Assistant voice is in
use, because `wyoming-whisper` holds ~4 GB resident and the 14B QLoRA run's
expected ~10-12 GB peak leaves too little margin on the 5080's ~15.5 GB. Use
`gpu-solo` to stop whisper for the duration (a Stop hook resumes it when the
job exits).

```bash
# From the project root, with the training venv active and axolotl installed.
cd <project-root>

# Optional dry run first: copy the config, set num_epochs: 1 on a 4-example
# subset, watch nvidia-smi to confirm the real VRAM peak fits.

# Full run (stops whisper for the duration via gpu-solo):
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  gpu-solo accelerate launch -m axolotl.cli.train ml/finetune/sft_config.yaml
```

After training, the LoRA adapter lands in `outputs/coach-qlora-v0`. To serve
the tuned arm through Ollama for the eval harness, merge the adapter into the
base and convert to GGUF (documented at run time), then register it as a new
Ollama model tag used only for the tuned-arm eval. The baseline prompt stays
identical on both arms.

## Constraints honored during preparation

No training run, no `gpu-solo`, no GPU work, no git, no Home Assistant /
systemd changes. Only CPU authoring + the leakage check were executed.
