# Closing-cue / relance-exception mini-eval — set v1 (dimension D4)

This is a FOCUSED mini-eval for CS-156, separate from the frozen
`eval_set_v0.md`. It measures dimension **D4 = closing-cue / relance-exception
compliance**: does the coach close warmly (no forced question) on a genuine
closing cue, answer a real need without killing the session, and still relance
by default on ordinary practice turns.

D4 is a NEW name on purpose: `eval_set_v0.md` already uses **D3** for
long-context drift, so this set does not reuse D3.

## Labels

Each dialogue is a single learner turn labelled with the expected coach
behaviour:

- **CLOTURE** — the coach must close warmly and must NOT end with a question.
- **SOUPLE** — the coach must answer the real need and must NOT close (no hard
  goodbye). A light natural follow-up is allowed; a forced quiz question is not.
- **DEFAUT** — the coach must end with a question or an invitation to speak.
  These prove v2 did not over-generalise the exception to ordinary turns.

The deterministic classifier maps a reply to `{closed, soft, question}`:

- `question` — the reply ends with a question mark.
- `closed` — the reply is a warm close: short, no trailing question, no
  "répète la phrase" drill, and it carries an explicit farewell cue.
- `soft` — anything else (answers the need, stays engaged, no goodbye).

Per-item correctness:

- CLOTURE is correct iff the reply is `closed`.
- SOUPLE is correct iff the reply is NOT `closed` (`soft` or `question`).
- DEFAUT is correct iff the reply is `question`.

## Key metrics (measured for v1 and for v2)

- **closer-recall** = fraction of CLOTURE turns correctly closed.
- **premature-close rate** = fraction of NON-CLOTURE turns (SOUPLE + DEFAUT)
  wrongly closed. This is the headline number: it captures the risk that the
  new exception makes the coach hang up mid-practice.

## Dialogues

The `DIALOGUES` list in `run_closing_cue_compare.py` mirrors this table
verbatim (learner text + label). Keep the two in sync.

### CLOTURE (must close, no question)

| id | learner turn | sub-case |
|----|--------------|----------|
| C1 | Au revoir. | adieu explicite |
| C2 | Bonne nuit. | adieu explicite (the live bug that motivated CS-156) |
| C3 | Je suis fatiguée, je dois y aller. | arrêt / départ explicite |
| C4 | Merci, à demain. | remerciement COMBINÉ à un adieu |
| C5 | On s'arrête là pour aujourd'hui. | arrêt explicite |
| C6 | On continue demain, bonne soirée. | départ + adieu |
| C7 | C'est bon j'arrête, merci beaucoup. | arrêt + remerciement |

### SOUPLE (must respond, must NOT close)

| id | learner turn | sub-case |
|----|--------------|----------|
| S1 | Comment on dit "thank you" en français ? | question factuelle directe |
| S2 | C'est quoi la différence entre "savoir" et "connaître" ? | question factuelle directe |
| S3 | Parle plus lentement, s'il te plaît. | instruction méta / contrôle |
| S4 | Répète, je n'ai pas bien compris. | instruction méta / contrôle |
| S5 | C'est trop dur, je n'y arrive pas. | frustration / découragement |
| S6 | Je suis découragée, j'en ai marre. | frustration / découragement |
| S7 | Merci beaucoup ! | remerciement SEUL (near-miss vs C4) |

### DEFAUT (must end with a question)

| id | learner turn | sub-case |
|----|--------------|----------|
| D1 | Bonjour, je m'appelle Marie et je prépare ma soutenance. | tour ordinaire |
| D2 | Je pense que mon projet est vraiment intéressant. | tour ordinaire |
| D3 | Je dois réfléchir à ma réponse. | near-miss : réflexion en cours, PAS un arrêt |
| D4 | Hier, je suis allée au marché et j'ai acheté des légumes. | tour ordinaire correct |
| D5 | Mon projet parle d'un assistant vocal pour apprendre le français. | tour ordinaire |
| D6 | Je travaille sur mon portfolio depuis deux semaines. | tour ordinaire |
| D7 | Je suis fatiguée aujourd'hui, j'ai mal dormi mais je veux continuer. | near-miss : fatigue SANS signal d'arrêt, PAS une clôture |

Counts: 7 CLOTURE, 7 SOUPLE, 7 DEFAUT = 21 single-turn dialogues.

## Near-misses deliberately included

- **C4 vs S7**: "merci, à demain" (close) vs bare "merci beaucoup !" (do NOT
  close). Bare thanks must stay engaged, or practice dies mid-session.
- **D3**: "je dois réfléchir à ma réponse" is a thinking pause, not a stop —
  must stay in DEFAUT and relance, not be misread as a closing cue.
- **C3 vs D7**: "je suis fatiguée, je dois y aller" (fatigue COMBINED with a
  departure cue → close) vs "je suis fatiguée aujourd'hui, ... mais je veux
  continuer" (bare fatigue as ordinary content, no stop cue → must relance).
  Bare state-of-fatigue alone must NOT trigger a close.
