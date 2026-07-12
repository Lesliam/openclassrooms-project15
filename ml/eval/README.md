# Coach FR — prompt-baseline evaluation harness

Implements the evaluation design frozen in [`eval_set_v0.md`](eval_set_v0.md):
the fixed 20-dialogue set and the scoring protocol used to measure the coach
BEHAVIOR (French-only persistence, correction-format compliance, drift
resistance over long context) for the prompt-baseline vs fine-tuned
comparison.

This harness runs the **baseline arm**: `qwen2.5:14b` under
[`../../server/coach_system_prompt_v0.md`](../../server/coach_system_prompt_v0.md),
with no fine-tuning. The tuned arm reuses the same runner with a different
model tag.

## Layout

```
ml/eval/
  eval_set_v0.md         # FROZEN spec (source of truth) — read-only here
  requirements.txt       # pinned deps
  README.md              # this file
  harness/               # the package
    constants.py         # all named constants + decoding params (v0 guesses)
    ollama_client.py     # /api/chat client with explicit error handling
    dialogues.py         # the 20 dialogues + drift filler script (static data)
    spec_guard.py        # asserts learner texts match eval_set_v0.md verbatim
    scorers.py           # deterministic D1 / D2 / brevity scorers
    judge.py             # LLM-judge client (wired, off during dry-run)
    config.py            # system-prompt loading + content SHAs + run config
    runner.py            # orchestration + JSON output
    report.py            # run dir -> Markdown report
    cli.py / __main__.py # entrypoint
  runs/<run-id>/         # outputs: config.json, transcripts/, scores.json, report.md
```

## Setup

```bash
cd ml/eval
python -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Ollama must be reachable at `http://192.168.1.37:11434` (this host's LAN IP;
loopback is dead by design here) with `qwen2.5:14b` present. The judge model
`mistral-small3.2` is only needed for full runs with `--judge`.

## Run

Dry-run (reduced repetitions and drift depth, judge disabled, deterministic
scorers only — finishes in a few minutes):

```bash
./.venv/bin/python -m harness --dry-run
```

Full baseline run:

```bash
./.venv/bin/python -m harness --full --repetitions 5 --drift-depth 18
# add --judge to enable the LLM judge (judge-model choice is an open point,
# eval_set_v0 section 5)
```

Useful flags: `--repetitions N`, `--drift-depth N`, `--judge-model NAME`,
`--run-id NAME`.

## Outputs and how they map to `eval_set_v0.md`

Each run writes `runs/<run-id>/`:

- `config.json` — model under test, judge model, decoding params, and the
  content SHA-256 of the system prompt and the eval-set spec (traceability).
- `transcripts/dialogue_NN.json` — raw per-repetition transcripts and the
  per-turn deterministic scores.
- `scores.json` — the flat per-turn score records (input to the report).
- `report.md` — aggregated metrics:
  - **D1** correction-format compliance rate + false-positive rate
    (eval_set_v0 section 1, D1).
  - **D2** French-persistence rate + mean French-token fraction
    (section 1, D2).
  - **D3** drift deltas per behavior = compliance(shallow) − compliance(deep)
    (section 1, D3).
  - Per-item rate table.

## Fidelity to the spec

`dialogues.py` reproduces every learner turn from `eval_set_v0.md` VERBATIM,
accents included, keeping only the deliberately planted grammatical errors.
Accent-less input would plant spurious errors that the coach over-corrects
(and real Whisper FR STT emits accents), so `spec_guard.py` asserts each of
the 20 learner texts still appears verbatim in the spec and runs as a
fail-fast precondition of every run:

```bash
./.venv/bin/python -m harness.spec_guard
```

## Scoring model

- Deterministic scorers (`scorers.py`) own the cheap pre-checks: D1 markers
  (restatement, correction, repeat request, brevity), D2 per-sentence
  language ID (`langdetect`, seeded) with a hard CJK-fail rule and a soft
  French-token fraction, and sentence-count brevity.
- The LLM judge (`judge.py`) owns the structural 4-part ordered check and the
  semantic false-positive check (eval_set_v0 section 2). It is wired and
  unit-callable but disabled in the dry-run, pending Lesliam's judge-model
  decision (section 5).

## Reproducibility

Decoding parameters are pinned in `constants.py` and logged into every run's
`config.json`. Per-repetition seed = `seed_base + repetition_index`, giving
controlled variance across the N repetitions while keeping each run
reproducible. `langdetect` is seeded. These decoding values are **v0
guesses** flagged for Lesliam's review (eval_set_v0 section 5).
