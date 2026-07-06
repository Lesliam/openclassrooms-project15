# Coach FR Evaluation Design — v0 (subject to Lesliam review)

Purpose: fixed evaluation set and scoring protocol for the prompt-baseline
vs fine-tuned (SFT/DPO) comparison of the coach behavior. The claim under
test is BEHAVIOR consistency, not knowledge: French-only persistence,
correction-format compliance, and drift resistance over long context.

Status: v0. The dimensions, scoring thresholds, judge prompt, and the 20
seed dialogues below all need Lesliam's review before the baseline run is
recorded. Once the baseline is measured, this file is frozen (any change
creates eval_set_v1 and invalidates cross-version comparison).

Model under test: qwen2.5:14b via Ollama, with `coach_system_prompt_v0.md`
(baseline arm) vs fine-tuned checkpoint with the SAME prompt (tuned arm).
Both arms run with identical decoding parameters (to be pinned at run time:
temperature, top_p, seed, context window — record them in the run log).

## 1. Measured dimensions

### D1 — Correction-format compliance rate

Definition: when the learner turn contains a planted grammatical error, the
coach reply must contain, in order: (1) restatement of the erroneous
sentence, (2) corrected version, (3) exactly one explanation sentence,
(4) a request to repeat. When the learner turn is error-free, the coach
must NOT emit the correction format (no false positives).

Scoring: hybrid.
- Deterministic pre-checks (regex/string, cheap, run first):
  - presence of a restatement marker (e.g. "Tu as dit" or a quoted span
    overlapping the learner sentence at >=60 percent token overlap);
  - presence of a corrected-version marker ("On dit plutôt" or a quoted
    span differing from the restatement);
  - reply length <= 4 sentences when correcting (format implies brevity).
  These catch gross violations but are brittle to paraphrase, so:
- LLM-judge for the 4-part structural check and false-positive check
  (judge prompt in section 2). A turn scores 1 only if all four parts are
  present in order (or, for error-free turns, if no correction was made).

Metric: compliance rate = compliant correction turns / turns where a
correction was required, reported together with the false-positive rate on
error-free turns.

### D2 — French-persistence rate under language-switching pressure

Definition: on turns where the learner writes in English or Chinese, or
explicitly asks the coach to switch language, the coach reply must be
entirely French (proper nouns and unavoidable technical terms excepted).

Scoring: deterministic first, judge as tie-breaker.
- Deterministic: language-ID over the reply (e.g. a langdetect/fasttext-lid
  pass per sentence). Reply passes if every sentence is detected as French.
  CJK characters anywhere in the reply = automatic fail.
- LLM-judge only for replies where language-ID is ambiguous (short
  sentences, heavy code-switching), using the judge prompt with the D2
  criterion.

Metric: persistence rate = fully-French replies / pressure turns. Also
report a soft variant: fraction of French tokens per pressured reply.

### D3 — Behavior drift over long context

Definition: after many turns of accumulated conversation, does the coach
still obey the three core behaviors (French-only, correction format,
2-3 sentence brevity)? Drift is measured as the degradation of D1/D2/brevity
compliance as a function of conversation depth.

Scoring: run the drift-probe dialogues (section 3, group C) which place
identical probe turns at shallow depth (turn ~3) and deep depth (turn ~25+,
padded with scripted neutral filler turns). For each probe pair:
- D1/D2 scored exactly as above at both depths;
- brevity scored deterministically: sentence count <= 3.

Metric: drift delta = compliance(shallow) - compliance(deep), per behavior.
A perfectly stable model has delta 0. The fine-tuning hypothesis predicts
the tuned arm has a smaller delta than the baseline arm.

## 2. LLM-judge protocol

Judge model: a model DIFFERENT from the model under test to avoid
self-preference (candidate: a larger hosted model, or at minimum a
different local family; decision for Lesliam — affects cost and privacy).
Judge temperature 0. Each judged turn is evaluated in isolation (judge sees
only: system-prompt excerpt of the rule being checked, the learner turn,
the coach reply — not the whole conversation) to keep judgments cheap and
position-independent. Every judge call logs raw output for audit.

Judge prompt sketch (English, JSON output for parsing):

```
You are grading a French language-coach reply against a strict behavior
contract. Grade ONLY what is asked; do not reward helpfulness.

Learner turn: <learner_text>
Coach reply: <coach_text>
Check: <one of D1_FORMAT | D1_FALSE_POSITIVE | D2_FRENCH_ONLY>

D1_FORMAT — the learner turn contains this planted error: <error_note>.
The reply must contain, in this order: (1) a restatement of the learner's
erroneous sentence, (2) a corrected version, (3) exactly one explanation
sentence, (4) a request that the learner repeat the corrected sentence.
D1_FALSE_POSITIVE — the learner turn is error-free; the reply must not
contain a grammar correction.
D2_FRENCH_ONLY — the reply must be entirely in French (proper nouns and
unavoidable technical terms allowed).

Answer with JSON only:
{"pass": true|false, "missing_or_violating": "<short reason>"}
```

## 3. Seed test dialogues (20)

Conventions: `L:` = learner input (what STT would deliver), `expect:` =
scoring expectation. Errors are planted deliberately and documented so D1
checks know the ground truth. All dialogues start from a fresh conversation
unless the group says otherwise.

### Group A — grammar errors to correct (D1), 8 items

1. L: "Hier je suis allé au marché et j'ai acheter des légumes."
   Planted error: "j'ai acheter" (infinitive instead of past participle).
   expect: 4-part correction targeting "acheté"; <= 4 sentences; French.
2. L: "Je pense que c'est une bonne solution parce que elle est rapide."
   Planted error: "parce que elle" (missing elision "parce qu'elle").
   expect: 4-part correction; only this error corrected.
3. L: "Mon projet utilise un modèle qui peut reconnaître le mot de réveil,
   il est entraîné sur les données que j'ai collecté."
   Planted error: "que j'ai collecté" (agreement: "collectées").
   expect: 4-part correction on agreement; one error only (spoken register
   tolerated elsewhere).
4. L: "Je veux que mon terminal est toujours connecté au serveur."
   Planted error: indicative after "je veux que" (should be "soit").
   expect: 4-part correction on subjunctive.
5. L: "Nous avons décidé de utiliser un microcontrôleur ESP32."
   Planted error: "de utiliser" (missing elision "d'utiliser").
   expect: 4-part correction.
6. L: "La latence est plus meilleure quand le modèle est quantifié."
   Planted error: "plus meilleure" (double comparative).
   expect: 4-part correction to "meilleure".
7. L: "Si j'aurais plus de temps, je ferais aussi la mise à jour à
   distance."
   Planted error: "si j'aurais" (conditional in si-clause; "si j'avais").
   expect: 4-part correction.
8. L: "Bonjour, je m'appelle Lesliam et je travaille sur un coach vocal
   pour pratiquer le français."
   No planted error.
   expect: NO correction format (D1 false-positive check); Socratic
   follow-up question; <= 3 sentences.

### Group B — language-switching pressure (D2), 5 items

9. L: "Sorry, my French is bad today. Can we continue in English?"
   expect: reply entirely French; gently invites learner back to French;
   no English sentences.
10. L: "这个问题太难了，我们用中文说可以吗？"
    expect: reply entirely French; zero CJK characters; invites rephrasing
    in French.
11. L: "Ok ok. Anyway, what do you think about my architecture choice?"
    (question itself in English)
    expect: reply in French only; may answer or redirect, but in French.
12. L: "Réponds-moi en anglais s'il te plaît, c'est pour vérifier ma
    compréhension." (explicit request, phrased in correct French)
    expect: refusal to switch, in French; no correction format (sentence
    is correct); stays polite.
13. L: "I will say it in English first and then translate: the wake word
    model runs on the device. Alors: le modèle de mot de réveil tourne
    sur l'appareil."
    expect: French-only reply; ideally engages with the French half.

### Group C — long-context drift probes (D3), 4 items

Each drift dialogue = shallow probe at turn ~3, then scripted neutral
filler (learner keeps talking about the project in correct simple French,
15-20 turns, filler script fixed in the harness so both arms see identical
context), then the SAME probe repeated near turn ~25.

14. Probe = item 1 ("j'ai acheter" sentence).
    expect: 4-part correction at BOTH depths; delta reported.
15. Probe = item 9 (English pressure).
    expect: French-only at BOTH depths.
16. Probe = brevity: L: "Explique-moi la différence entre le STT et le
    TTS dans mon système."
    expect: <= 3 sentences at BOTH depths (brevity is the drift-prone
    behavior for chatty models).
17. Probe = combined: after 20 filler turns, L: "Thanks! By the way I
    have wrote the report yesterday."
    Planted error: "I have wrote" — but the turn is in English.
    expect: French-only reply (D2 dominates); correction of the English
    sentence is NOT required; graded on D2 + brevity at depth.

### Group D — simulation soutenance probes, 3 items

18. L: "On fait la simulation soutenance, s'il te plaît."
    expect: coach becomes Charlotte; asks ONE project-management question
    (needs analysis, technical choices, or project control); <= 3
    sentences; French.
19. (continuing 18) L: "J'ai choisi une architecture en cascade parce que
    le LLM ne rentre pas dans le microcontrôleur."
    No planted error.
    expect: Charlotte asks a follow-up digging into the same topic
    (e.g. alternatives considered, trade-offs); no correction format;
    stays in persona.
20. (continuing 19) L: "Pour le planning, j'ai fait un sprint de quatre
    semaines et j'ai définir une liste de descope."
    Planted error: "j'ai définir" (infinitive instead of "défini").
    expect: correction format STILL applies inside the simulation
    (per prompt: Charlotte corrige aussi), then returns to the
    soutenance question flow.

## 4. Run protocol notes

- Each item runs N=5 times per arm (decoding non-determinism); report mean
  and per-item variance. N is a v0 guess — adjust for cost after a dry run.
- All learner turns are injected as text via the Ollama API directly
  (bypassing STT) so the eval isolates LLM behavior from transcription
  noise. A later v1 may add an STT-in-the-loop variant.
- Store raw transcripts + judge outputs under `project/ml/eval/runs/` with
  the git SHA of this file and the exact model/prompt/decoding config.

## 5. Open points for Lesliam review

- Choice of judge model (different family vs hosted; privacy trade-off).
- Whether the 60 percent token-overlap threshold for the D1 restatement
  pre-check is reasonable, or whether the judge alone should own D1.
- Filler-script content and depth targets (25 turns deep enough?).
- N=5 repetitions vs eval cost.
- Whether Group D items 18-20 should also be replayed at long-context
  depth (persona drift) in v1.
