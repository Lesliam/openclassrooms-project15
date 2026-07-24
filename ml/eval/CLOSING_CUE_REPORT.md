# CS-156 — Closing-cue / relance-exception report (dimension D4)

## Problem

The deployment prompt v1 encodes an unconditional relance rule (line 70-71):

> « Tu relances toujours : chaque tour se termine par une question ou une
> invitation à parler, jamais par une conclusion fermée. »

Because it is unconditional, the coach cannot end an exchange: when the learner
says « bonne nuit » it answers with a quiz question instead of a warm goodbye.
This is a premature-close failure in the reverse direction — the coach is
structurally unable to close.

## v2 design — a 3-tier exception system

v2 (`../../server/coach_system_prompt_v2.md`) = full text of v1 PLUS a closing-cue
design that subordinates the "Tu relances toujours" rule to three tiers. v1 is
kept as the prior deployment artifact; v0 stays frozen (baseline + fine-tuning
corpus).

- **TIER CLÔTURE** — on an explicit farewell (« au revoir », « bonne nuit »,
  « à demain »…), an explicit stop (« je suis fatiguée », « je dois y aller »,
  « on continue demain »…), or thanks combined with a farewell (« merci, à
  demain »): reply warmly and briefly, keep feminine agreement, and do NOT end
  with a question. If the closing turn also holds a genuine error, keep the
  correction light and skip the "répète la phrase" drill.
- **TIER SOUPLE** — on a real need (direct factual question, meta/control
  instruction like « parle plus lentement », frustration like « c'est trop
  dur », or bare thanks alone): answer the need, never force a quiz question,
  and do NOT close the session. Bare « merci » alone must NOT be treated as a
  close, or practice dies mid-session.
- **TIER DÉFAUT** — everything else: keep v1 behaviour exactly (always end with
  a Socratic question or an invitation to speak).

Cross-cutting rules still apply on top of every tier: French-only persistence,
the 4-part correction format for genuine errors (lightened in CLÔTURE), the
feminine learner profile, the anti-over-correction guard, the simulation
soutenance (Charlotte) mode, and a new line telling the coach not to invent a
question when the transcription is empty or nonsensical.

## How D4 is measured

The dimension is named **D4** because `eval_set_v0.md` already uses D3 for
long-context drift. The mini-eval (`closing_cue_set_v1.md` +
`run_closing_cue_compare.py`) is deliberately separate from the frozen harness.

- 21 single-turn labelled dialogues: 7 CLOTURE, 7 SOUPLE, 7 DEFAUT, including
  the near-misses « merci » alone (SOUPLE, must stay open) vs « merci, à demain »
  (CLOTURE, must close), « je dois réfléchir à ma réponse » (DEFAUT — a thinking
  pause, not a stop), and « je suis fatiguée aujourd'hui... mais je veux
  continuer » (DEFAUT — bare fatigue without a stop cue must NOT close, vs
  « je suis fatiguée, je dois y aller » which does).
- Deterministic CPU scorers (no Ollama): `reply_ends_with_question`,
  `is_warm_close` (short, no trailing question, no repeat-drill, explicit
  farewell cue) and `classify_reply` → `{closed, soft, question}`.
- Per-item correctness: CLOTURE correct iff `closed`; SOUPLE correct iff NOT
  `closed`; DEFAUT correct iff `question`.
- The scorer script runs the model live: each dialogue is sent once with the v1
  prompt and once with the v2 prompt to `qwen2.5:14b` via Ollama (host resolved
  from `OLLAMA_HOST`/`OLLAMA_BASE_URL`, never hardcoded). If Ollama is
  unreachable it writes deterministic-only results and exits cleanly; the unit
  tests pass offline regardless.

### Why the premature-close rate is the headline number

The risk of adding a closing exception is over-generalisation: the coach starts
hanging up on ordinary practice turns. **Premature-close rate** = fraction of
NON-CLOTURE turns (SOUPLE + DEFAUT) wrongly classified `closed`. It directly
measures that risk. A good fix must raise **closer-recall** (CLOTURE turns
correctly closed) toward 1.0 while keeping premature-close rate at 0.0.

## Results — v1 vs v2

Live run: `qwen2.5:14b` via Ollama, both arms on the same 21 dialogues, greedy
decode for reproducibility (temperature 0 / greedy, top_p 0.9, seed 42,
num_ctx 8192). Artifact: `runs/closing-cue-d4/results.json`.

| Metric | v1 | v2 |
|--------|----|----|
| Overall accuracy | 0.667 | 1.000 |
| **closer-recall** (CLOTURE closed) | **0.000** | **1.000** |
| **premature-close rate** (non-CLOTURE wrongly closed) | **0.000** | **0.000** |
| CLOTURE accuracy | 0.000 | 1.000 |
| SOUPLE accuracy | 1.000 | 1.000 |
| DEFAUT accuracy | 1.000 | 1.000 |

Per-dialogue classification (`ok` = matches the expected behaviour):

| id | label | v1 | v2 | learner turn |
|----|-------|----|----|--------------|
| C1 | CLOTURE | question X | closed ok | Au revoir. |
| C2 | CLOTURE | question X | closed ok | Bonne nuit. |
| C3 | CLOTURE | soft X | closed ok | Je suis fatiguée, je dois y aller. |
| C4 | CLOTURE | soft X | closed ok | Merci, à demain. |
| C5 | CLOTURE | question X | closed ok | On s'arrête là pour aujourd'hui. |
| C6 | CLOTURE | soft X | closed ok | On continue demain, bonne soirée. |
| C7 | CLOTURE | soft X | closed ok | C'est bon j'arrête, merci beaucoup. |
| S1 | SOUPLE | question ok | question ok | Comment on dit "thank you" en français ? |
| S2 | SOUPLE | question ok | question ok | C'est quoi la différence entre "savoir" et "connaître" ? |
| S3 | SOUPLE | question ok | question ok | Parle plus lentement, s'il te plaît. |
| S4 | SOUPLE | soft ok | soft ok | Répète, je n'ai pas bien compris. |
| S5 | SOUPLE | question ok | question ok | C'est trop dur, je n'y arrive pas. |
| S6 | SOUPLE | soft ok | soft ok | Je suis découragée, j'en ai marre. |
| S7 | SOUPLE | soft ok | question ok | Merci beaucoup ! |
| D1 | DEFAUT | question ok | question ok | Bonjour, je m'appelle Marie et je prépare ma soutenance. |
| D2 | DEFAUT | question ok | question ok | Je pense que mon projet est vraiment intéressant. |
| D3 | DEFAUT | question ok | question ok | Je dois réfléchir à ma réponse. |
| D4 | DEFAUT | question ok | question ok | Hier, je suis allée au marché et j'ai acheté des légumes. |
| D5 | DEFAUT | question ok | question ok | Mon projet parle d'un assistant vocal pour apprendre le français. |
| D6 | DEFAUT | question ok | question ok | Je travaille sur mon portfolio depuis deux semaines. |
| D7 | DEFAUT | question ok | question ok | Je suis fatiguée aujourd'hui, j'ai mal dormi mais je veux continuer. |

Example (C2 « Bonne nuit. »):

- v1: « Bonne nuit ! Es-tu prête pour ta soutenance demain ? Tu veux peut-être
  faire une simulation avant ? » → forced question (the exact bug).
- v2: « Bonne nuit ! Repose-toi bien. À bientôt pour de nouvelles
  conversations. » → warm close, no question.

Example (D7, bare fatigue as ordinary content, the CS-156 round-2 hole):

- v1: « D'accord, prenons les choses étape par étape... Que ressens-tu comme
  principaux défis ? » → relance (question), correct.
- v2: « D'accord, on peut continuer doucement alors... Quel est le problème
  principal que tu essaies de résoudre ? » → relance (question), correct — the
  qualified fatigue trigger keeps bare fatigue in DÉFAUT rather than closing.

## Reading

Under greedy decoding v1 closes 0 of 7 farewells (closer-recall 0.000); it
forces a question or a non-closing acknowledgement on « au revoir »,
« bonne nuit », « merci, à demain »… never actually saying goodbye. v2 closes
all 7 (closer-recall 1.000) while premature-close rate stays 0.000 and DEFAUT
accuracy stays 1.000 — the exception did NOT bleed into ordinary practice
turns, including the bare-fatigue near-miss D7. SOUPLE stays at 1.000 on both
arms (the model already never hung up on a need); v2 additionally makes the
closing behaviour correct, which was the whole point of CS-156.

## Reproduce

```bash
OLLAMA_HOST=<host:port> \
    ml/eval/.venv/bin/python ml/eval/run_closing_cue_compare.py
ml/eval/.venv/bin/python -m pytest ml/eval/tests/test_closing_cue_scorer.py -q
```
