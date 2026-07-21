# Disfluency / incomplete-turn mini-eval — set v1 (dimension D5)

This is a FOCUSED mini-eval for CS-157, separate from the frozen
`eval_set_v0.md`. It measures dimension **D5 = disfluency tolerance and
incomplete-turn handling**: in spontaneous speech the learner hesitates,
repeats words, makes false starts and self-corrects while she is still
thinking. Does the coach

- ignore the disfluency and NOT correct a repetition, filler, false start or
  already-self-corrected form,
- gently invite her to continue when the turn was cut off early, and
- still correct a GENUINE error hidden inside disfluent speech, and still leave
  an ordinary clean turn uncorrected?

D5 is a NEW name on purpose: `eval_set_v0.md` uses D1 (correction-format), D2
(French-persistence) and D3 (long-context drift), and the CS-156 mini-eval added
D4 (closing-cue), so this set does not reuse D1-D4.

## Labels

Each dialogue is a single learner turn labelled with the expected coach
behaviour:

- **DISFLUENCY** — disfluent speech (word/segment repetition, filler « euh » /
  « hmm », false start, or an already-self-corrected form) with NO genuine
  language error in the intended sentence. The coach must NOT emit a correction.
  This is where the headline disfluency-false-correction rate is measured.
- **INCOMPLETE** — the turn was cut off / trailing / unfinished. The coach must
  invite the learner to continue and must NOT force a correction or analysis.
- **REALERROR** — a genuine language error embedded in disfluent speech. The
  coach must STILL correct it (ignoring the disfluency), so this measures
  real-error recall within disfluent speech.
- **CLEAN** — an ordinary clean, complete, correct turn. The coach must NOT
  correct it (v2 over-correction guard preserved). These controls prove v3 did
  not start correcting or inviting on normal turns.

## Deterministic detectors (CPU-only, no Ollama)

The scorer maps a reply to three boolean signals, mirroring the D4 scorer's
approach and reusing `harness.scorers`:

- **correction_emitted** — the reply restates the learner sentence AND supplies
  a corrected version (`harness.scorers.d1_correction_emitted`). This is the
  4-part correction drill firing: a restatement (« Tu as dit : … ») plus a
  corrected version (« On dit plutôt : … » or two distinct quoted spans).
- **applies_4part_format** — the stricter check that all four markers are
  present (restatement + corrected version + repeat request, within the
  correction brevity cap) via `harness.scorers.score_d1`.
- **invites_to_continue** — the reply asks the learner to keep going (« prends
  ton temps », « je t'écoute », « tu veux continuer ? », « vas-y », « poursuis »,
  « termine ta phrase »…) without emitting a correction.
- **correction_targets_disfluency** — when a correction is emitted, whether the
  quoted erroneous span is itself a disfluency (an immediate word repetition or
  a filler like « euh »). Reported as a quality signal: a good real-error
  correction targets the error, not the disfluency.

## Per-item correctness

- DISFLUENCY correct iff NOT `correction_emitted`.
- INCOMPLETE correct iff `invites_to_continue` AND NOT `correction_emitted`.
- REALERROR correct iff `correction_emitted`.
- CLEAN correct iff NOT `correction_emitted`.

## Key metrics (measured for v2 and for v3)

- **disfluency-false-correction rate** = fraction of DISFLUENCY turns wrongly
  given a correction. This is the headline number: it captures the risk that the
  coach "corrects" thinking-aloud that is not an error. Must be ~0 for v3.
- **real-error recall within disfluent speech** = fraction of REALERROR turns
  correctly corrected. A good fix must keep this high while driving the
  false-correction rate down — the two must not trade off.
- **incomplete-turn invite rate** = fraction of INCOMPLETE turns correctly
  invited to continue.

## Dialogues

The `DIALOGUES` list in `run_disfluency_compare.py` mirrors this table verbatim
(learner text + label). Keep the two in sync.

### DISFLUENCY (must NOT correct — reconstruct the intended sentence)

| id | learner turn | intended sentence | sub-case |
|----|--------------|-------------------|----------|
| F1 | Je je pense que mon projet est intéressant. | Je pense que mon projet est intéressant. | word repetition |
| F2 | Mon projet, mon projet parle d'un assistant vocal. | Mon projet parle d'un assistant vocal. | segment repetition |
| F3 | Euh, je travaille sur euh mon portfolio. | Je travaille sur mon portfolio. | filler « euh » |
| F4 | Hmm, comment dire, je prépare ma soutenance. | Je prépare ma soutenance. | filler « hmm » + hesitation |
| F5 | Je vais... non, je prépare une présentation pour vendredi. | Je prépare une présentation pour vendredi. | false start |
| F6 | Hier je suis allé... allée au marché. | Hier je suis allée au marché. | ALREADY self-corrected agreement (near-miss vs R1) |
| F7 | J'ai un rendez-vous... un entretien demain. | J'ai un entretien demain. | already self-corrected word choice |
| F8 | Donc euh, le le problème c'est la latence. | Le problème c'est la latence. | filler + word repetition combined |

### INCOMPLETE (must invite to continue, must NOT correct)

| id | learner turn | sub-case |
|----|--------------|----------|
| I1 | Alors, je pense que le plus important c'est de... | trailing « de... » |
| I2 | Mon projet utilise un microcontrôleur pour | cut off after « pour » |
| I3 | Et donc, ce que je voulais dire c'est que... euh... | trailing hesitation |
| I4 | Quand j'ai commencé le projet, j'ai | cut off after « j'ai » |

### REALERROR (must correct the genuine error, ignoring the disfluency)

| id | learner turn | genuine error | disfluency to ignore |
|----|--------------|---------------|----------------------|
| R1 | Euh, hier je suis allé au marché. | « allé » → « allée » (never self-corrected) | filler « euh » (near-miss vs F6) |
| R2 | Je je vais au réunion demain. | « au réunion » → « à la réunion » | « je je » repetition |
| R3 | Je suis... je suis responsable de le projet. | « de le projet » → « du projet » | « je suis... je suis » false start |
| R4 | Donc euh, je vais expliquer vous mon projet. | « expliquer vous » → « vous expliquer » | filler « euh » |

### CLEAN (ordinary correct turn — must NOT correct, v2 behaviour preserved)

| id | learner turn | sub-case |
|----|--------------|----------|
| N1 | Bonjour, je m'appelle Marie et je prépare ma soutenance. | ordinary clean turn |
| N2 | Je travaille sur mon portfolio depuis deux semaines. | ordinary clean turn |
| N3 | Hier, je suis allée au marché et j'ai acheté des légumes. | clean + correct feminine (over-correction guard) |

Counts: 8 DISFLUENCY, 4 INCOMPLETE, 4 REALERROR, 3 CLEAN = 19 single-turn
dialogues.

## Near-misses deliberately included

- **F6 vs R1**: « je suis allé... allée » (self-corrected → do NOT re-flag) vs
  « euh, hier je suis allé au marché » (genuine, never self-corrected → correct
  it). The only difference is whether the learner produced the correct feminine
  form herself; the coach must not correct the first and must correct the second.
- **F7**: « rendez-vous... un entretien » is a self-corrected word choice; the
  final intended word is correct, so no correction.
- **R2/R3**: the genuine error sits right next to a repetition / false start, so
  a naive coach might "correct" the disfluency (« je je ») instead of the real
  error (« au réunion »). The scorer flags whether the correction targeted the
  disfluency.
- **N3**: the correct feminine « je suis allée » must not be flipped to the
  masculine — the same over-correction guard the frozen harness checks.
