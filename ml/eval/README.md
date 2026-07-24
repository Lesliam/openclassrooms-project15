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

Point the harness at Ollama via the environment (the address is not
hardcoded, to keep deployment topology out of version control): set
`OLLAMA_BASE_URL` (a full URL) or `OLLAMA_HOST` (host, expanded to
`http://<host>:11434`); it defaults to `http://127.0.0.1:11434`. On this
deployment loopback is disabled by design, so `OLLAMA_HOST` is exported to
the host's LAN address in the shell environment. The server must have
`qwen2.5:14b` present. The judge model `mistral-small3.2` is only needed for
full runs with `--judge`.

## Run

Dry-run (reduced repetitions and drift depth, judge disabled, deterministic
scorers only — finishes in a few minutes):

```bash
./.venv/bin/python -m harness --dry-run
```

Full baseline run:

```bash
./.venv/bin/python -m harness --full --repetitions 5 --drift-depth 25
```

The judge is not wired yet (the judge model is a pending Lesliam decision,
eval_set_v0 section 5); passing `--judge` is rejected loudly so a persisted
config can never claim the judge ran. `--drift-depth` may not exceed the
number of `FILLER_SCRIPT` lines — the runner raises rather than silently
truncating the deep probe.

Useful flags: `--repetitions N`, `--drift-depth N`, `--run-id NAME`.

## Outputs and how they map to `eval_set_v0.md`

Each run writes `runs/<run-id>/`:

- `config.json` — model under test, judge model, decoding params, and the
  content SHA-256 of the system prompt and the eval-set spec (traceability).
- `transcripts/dialogue_NN.json` — raw per-repetition transcripts and the
  per-turn deterministic scores.
- `scores.json` — the flat per-turn score records (input to the report).
- `report.md` — aggregated metrics:
  - **D1** deterministic pre-check compliance (4-part marker presence +
    brevity; part order and the "exactly one explanation sentence" rule are
    NOT verified here — those belong to the judge, eval_set_v0 section 2) +
    false-positive rate.
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
  (restatement, correction, repeat request, brevity) — this verifies 4-part
  marker PRESENCE and brevity only, NOT part order or the "exactly one
  explanation sentence" rule; D2 per-sentence language ID (`langdetect`,
  seeded) with a hard CJK-fail rule and a soft French-token fraction; and
  sentence-count brevity.
- The LLM judge (`judge.py`) owns the structural 4-part ORDERED check and the
  semantic false-positive check (eval_set_v0 section 2). It is importable and
  unit-callable but NOT wired into any run path yet, pending Lesliam's
  judge-model decision (section 5); `--judge` is rejected until it is.

## Known v0 limitations

- **N1 — restatement overlap is asymmetric.** The D1 restatement pre-check
  measures the fraction of the learner sentence's tokens that appear in a
  quoted span (learner-to-span direction). A very long quoted span that
  contains the learner sentence plus much more still counts as a restatement.
  This is intentional for v0 (the judge owns the precise structural check);
  flagged for review with the 60% threshold (eval_set_v0 section 5).
- **N2 — D2 has no proper-noun exception.** The spec allows proper nouns and
  unavoidable technical terms in an otherwise-French reply. The deterministic
  D2 check runs `langdetect` per sentence and does not special-case such
  tokens, so a sentence dominated by a proper noun could be misclassified.
  The soft French-token fraction is reported alongside the hard pass/fail to
  make this visible; the judge is the tie-breaker for ambiguous sentences.

## Reproducibility

Decoding parameters are pinned in `constants.py` and logged into every run's
`config.json`. Per-repetition seed = `seed_base + repetition_index`, giving
controlled variance across the N repetitions while keeping each run
reproducible. `langdetect` is seeded. These decoding values are **v0
guesses** flagged for Lesliam's review (eval_set_v0 section 5).
