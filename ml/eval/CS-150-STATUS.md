# CS-150 status — prompt-baseline eval harness

Worker status note (messages do not route to PM; read this + the run report).

## Rework requested by PM — all 5 items done

1. Accents restored. Every learner turn / drift probe in `harness/dialogues.py`
   now reproduces `eval_set_v0.md` VERBATIM, accents included, keeping only
   the planted grammatical errors (`acheter`, `parce que elle`, `plus
   meilleure`, `si j'aurais`, `j'ai définir`, ...). The drift FILLER_SCRIPT is
   also correct accented French.
2. Drift guard added: `harness/spec_guard.py` asserts each of the 20 learner
   texts appears verbatim in the spec (whitespace-normalized so the spec's
   line wrapping does not cause false mismatches). Wired as a fail-fast
   precondition in `cli.py` (run aborts before any Ollama call if drift is
   detected). Standalone: `python -m harness.spec_guard`.
3. Items 19 and 20 are encoded (Group D, one accumulating conversation) and
   now scored as their own rows: each learner turn carries an `item_id`
   (1-20) and the per-item report table keys on `item_id`. All 20 items in
   the latest report.
4. Re-ran `--dry-run` (N=2, deterministic-only, judge off). New run dir:
   `runs/20260712T155712Z-dryrun/`. Its `report.md` has a "Rework note"
   section with BEFORE/AFTER headline numbers.
5. No git commit. No systemd/HA/NAS touched. Inference only.

## Headline numbers, BEFORE (accent-stripped) vs AFTER (accents restored)

| Metric | Before | After |
| --- | --- | --- |
| D1 correction-format compliance | 30.0% | 55.0% |
| D1 false-positive rate | 50.0% | 50.0% |
| D2 French-persistence | 33.3% | 50.0% |
| D2 mean French-token fraction | 0.906 | 0.946 |

Residual 50% D1 false-positive is a real baseline weakness (items 12 and 19:
the coach corrects a grammatically-correct French sentence), not an artifact.

## Verification evidence

- `python -m harness.spec_guard` -> `OK: 20 learner texts match eval_set_v0.md
  verbatim`.
- CLI run log shows `spec guard ok` then `health check ok` before scoring.
- `git status` (read-only) shows only untracked new files under `ml/eval/`;
  branch `feature/cs-150-eval-baseline-harness`; no commits made.
- `wyoming-whisper.service` still `active` (untouched).

## Open points for Lesliam (unchanged, eval_set_v0 §5)

- Judge model choice (default `mistral-small3.2`, wired, not yet exercised).
- Decoding params temp=0.7 / top_p=0.9 / seed_base=42 / num_ctx=8192 (v0
  guesses, logged in every `config.json`).
- D1 60% restatement-overlap threshold.
- N=5 vs cost; drift depth (dry-run used 7; full-run default 18).

## Note on file size

`harness/dialogues.py` is 432 lines (> the 300 guideline) — it is pure static
eval data (20 dialogues + expectations + filler). Within the global 800-line
cap. Flagged rather than fragmenting the eval set across files.
