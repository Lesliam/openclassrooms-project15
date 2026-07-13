# Nuanced LLM-Judge Verdicts — Baseline vs Fine-Tuned Coach

38 paired items graded on the criteria a marker-presence scorer cannot check:
correction-format **order**, **exactly one** explanation sentence, and — most
important — **grammatical correctness of the explanation** (fabricated rules
flagged). Plus false-positive over-correction and D2 French-persistence quality.

## Aggregate table

| Criterion | Baseline | Tuned |
|---|---|---|
| **D1_correction** (n=18) | | |
| order correct (4-part in order) | 66.7% (12/18) | 94.4% (17/18) |
| exactly one explanation sentence | 100% (18/18) | 94.4% (17/18) |
| **explanation grammatically correct** | **44.4% (8/18)** | **44.4% (8/18)** |
| **D1_false_positive_probe** (n=8) | | |
| wrongly corrected (lower=better) | 50.0% (4/8) | 12.5% (1/8) |
| **D2_french_persistence** (n=12) | | |
| fully French (no CJK/English) | 50.0% (6/12) | 100% (12/12) |
| natural invitation back to French | 25.0% (3/12) | 100% (12/12) |

## Headline finding

The fine-tune bought **format compliance** (order 67%->94%, repeat-request now
almost always present) and **large real wins on D2 and false positives** — but
**explanation correctness did NOT improve at all (44.4% -> 44.4%)**. The
deterministic "D1 compliance 50%->95%" number hides that ~half of tuned
corrections still ship a **fabricated or wrong grammatical justification**, and
the tuned arm invents them *more confidently* (fake "subjonctif" / "participe
passe agreement" rules) than the baseline.

## Quality tradeoffs found

### Tuned FABRICATES wrong grammar rules (explanation_correct = false)
- **d5 r0** (item idx8): calls the infinitive `d'utiliser` a **subjonctif**.
- **d7 r0** (idx12): "Le subjonctif **aille** devient **ai** apres si" — pure
  nonsense; `aille` is the subjunctive of *aller*, unrelated to the sentence.
- **d7 r1** (idx13): "Le subjonctif prend **ait**, pas **ait eu**" — no
  subjunctive is involved; the rule is *si + imparfait*.
- **d14 r0** (idx26): "Le participe passe **s'accorde avec legumes**" — with
  *avoir* + a FOLLOWING direct object there is **no agreement** (right form
  `acheté` reached by a wrong rule; agreement would give `achetés`).
- **d14 r1** (idx27): "**Apres hier**, le verbe prend le participe passe" —
  wrong causal attribution (the auxiliary *avoir* governs it, not the adverb).
- **d1 r1** (idx1): garbled "Apres je, avoir prend -é".
- **d2 r1** (idx3): "on utilise **elle**, pas **elle est**" — the correction
  keeps `est`; explanation is wrong.
- **d6 r0** (idx10): "comparatif d'un adjectif **deja positif**" — confused
  terminology for the meilleur/plus-meilleur error.

### Tuned over-corrects / mis-targets (behavioural failures)
- **d3 r0** (idx4): **failed to correct a real error** — gave a Socratic
  follow-up on a D1_correction turn (collecté agreement) as if it were
  error-free.
- **d3 r1** (idx5): invented a **vocab correction** (`mot de reveil`->`mot
  d'appel`, dubious) and ignored the real agreement error.
- **d18 t1 r1** (idx36): the **only tuned false-positive** — "corrected"
  the perfectly correct `ne rentre pas dans` -> `ne tient pas` with a
  fabricated `entrer = se glisser physiquement` rationale.
- **d18 t2 r1** (idx37): **missed the real error** — restate silently writes
  `j'ai défini` (already correct), so the `definir`->`défini` fix is never
  taught; it swaps in a descope vocab gloss instead.

### Baseline was ALSO frequently wrong (so this is not tuned-only)
- **d2 r0/r1** (idx2, idx3): fabricates a "`elle` becomes possessive `sa`"
  rule for a simple `que`->`qu'` elision — egregious.
- **d5 r0/r1** (idx8, idx9): "la preposition **de n'est pas necessaire** apres
  decider" — false; *de* is required, only elides.
- **d1 r1** (idx1): "il faut **l'accorder avec j'ai**" — no subject agreement
  with *avoir*.
- **d7 r0** (idx12): calls `j'avais` **"au present"** (it is imparfait).
- **d3 r1** (idx5): "Utilisez le passe compose" as the reason for an
  *agreement* error.
- Baseline also **over-corrects error-free sentences** (idx22, idx23, idx33,
  idx36) and, in D2, **drops entirely into Chinese** (idx18, idx19) or
  reproduces the learner's English inside a `On dit plutot` correction format
  (idx20, idx21, idx30, idx31).

### Where the tune genuinely improved
- **D2 persistence**: 100% fully French + 100% natural invitation vs baseline
  falling into Chinese / English-quote correction mode. Clear, real win.
- **False positives**: 50% -> 12.5% — tuned stops rewriting grammatically
  correct requests (idx22, idx23, idx33 fixed).
- **Format**: tuned reliably ends with the `Peux-tu repeter` request; baseline
  often replaced it with a follow-up question (idx6, idx7, idx26, idx27, idx37).
- **Clean, correct corrections** by tuned: idx0, idx2, idx6, idx7, idx34.

## Bottom line
Tuned is clearly better on *behaviour* (stays French, stops over-correcting,
keeps the format) but is **not more trustworthy on grammatical substance** —
its explanation-correctness is identical to baseline (44%) and it fabricates
grammar rules with more confidence. A learner following the tuned coach would
be **misinformed about the grammar roughly half the time on genuine
corrections**. The deterministic scores overstate the quality gain.
