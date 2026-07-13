# Grounded_v3 vs Tuned — French Grammar Judge Verdicts

Input: `paired_grounded_v3.json` (18 D1 items). Judge scope: grade both arms on
items with an actual grounded_v3 correction (N=12); count + assess the 6
fallthroughs separately.

## Aggregate table (over N=12 gradable items)

| Metric | tuned | grounded_v3 |
|---|---|---|
| explanation_correct | 25.0% (3/12) | 100.0% (12/12) |
| correction_form_right | 83.3% (10/12) | 100.0% (12/12) |
| concise | 58.3% (7/12) | 100.0% (12/12) |

## Fallthrough breakdown (6 items, excluded from correctness denominator)

| dialogue | real error | verdict |
|---|---|---|
| 4 (r0,r1) | `je veux que ... est` -> `soit` (subjunctive) | MISSED |
| 6 (r0,r1) | `plus meilleure` -> `meilleure` (irregular comparative) | MISSED |
| 7 (r0,r1) | `si j'aurais` -> `si j'avais` (si + imperfect, not conditional) | MISSED |

Missed: 6 / 6. Correctly declined (no real grammar error): 0 / 6.
All six fallthroughs are recall gaps: the learner turn contained a genuine
grammar error that the precision gate could not classify (mood, irregular
comparative, si-clause tense) and therefore suppressed.

## Key findings

1. **`le planning` false positive is GONE.** In d18 (`Pour le planning, j'ai
   fait un sprint...`) grounded_v3 corrects only `définir -> défini` and leaves
   `le planning` untouched in both reps. The v2 over-correction no longer fires.

2. **Grounded_v3 explanation correctness holds at 100% (12/12).** Every fired
   template is grammatically sound — participe passé after avoir, elision,
   accord du participe passé avec COD antéposé (d3 `collectées`), infinitive vs
   participle. No remaining wrong template.

3. **Precision was bought with recall.** All 6 fallthroughs (d4, d6, d7) are
   genuine errors the engine declined on — 0 correctly-declined. The gate has
   no coverage for subjunctive mood, irregular comparatives, or si+conditional.
   On exactly these items the tuned model DID produce the right surface form
   (soit / meilleure / si j'avais), so the arms are complementary.

4. **Tuned's low explanation score is driven by fabricated rules.** Right form,
   wrong justification recurs: `après je avoir prend -é` (d1r1), `on utilise
   elle pas elle est` (d2r1), `décider = subjonctif` (d5r0), `après hier le
   verbe prend le participe passé` (d14r1), and the agreement mis-diagnosis in
   d14r0 (`accorde avec légumes` would give *achetés*). Form-right 83% but
   explanation-right only 25%.

5. **Tuned also misses/misfires where grounded catches.** On d3 the tuned arm
   entirely misses the `collecté -> collectées` agreement error — r0 gives
   off-topic encouragement, r1 swaps a non-error lexical item. Grounded_v3
   catches both cleanly. Tuned concision also suffers when it restates the whole
   sentence (d14r0/r1, d18r0) instead of the erroneous phrase.
