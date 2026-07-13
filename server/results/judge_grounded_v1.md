# Grounded vs Tuned — D1 Grammar Correction Judge

n = 18 paired D1 correction items. Each reply graded on explanation correctness
(the key metric), correction-form correctness, and concision.

## Aggregate table

| Criterion | Tuned | Grounded |
|---|---|---|
| explanation_correct | 7/18 = 38.9% | 5/18 = 27.8% |
| correction_form_right | 16/18 = 88.9% | 18/18 = 100% |
| concise | 18/18 = 100% | 4/18 = 22.2% |

## Honest verdict

**Grounding did NOT raise explanation correctness — it lowered it (38.9% -> 27.8%).**
The grounded arm sources only the corrected FORM from the grammar engine; the model
still free-writes the justification, and it fabricates rules just as badly as the
tuned model — sometimes worse, because a correct form is now paired with an invented
reason. The prior tuned-vs-baseline result (both ~44% explanation-correct) is
reproduced here: grounding the form does not fix the reasoning.

**What grounding did buy: form correctness went to 100%.** The grammar engine caught
the two hard cases the tuned model completely missed (preceding-COD agreement
`collectées`), so every grounded reply proposes a correct fix.

**What grounding broke: concision collapsed (100% -> 22%).** The engine corrects the
whole sentence, so the grounded replies echo the entire learner sentence three times
(`Tu as dit` / `On dit plutôt` / `Peux-tu répéter`) instead of restating just the
erroneous phrase. Confirmed as the known caveat.

## What grounding fixed (specific items)

- **Item 4 & Item 5 (dialogue 3)** — the clearest wins. Learner error was the subtle
  preceding-COD agreement `les données que j'ai collecté -> collectées`. Tuned FAILED
  both: item 4 gave no correction at all (only praise + a follow-up question), item 5
  invented an unrelated "mot de réveil -> mot d'appel" change. Grounded produced the
  correct form AND a correct explanation (agreement with the preceding feminine-plural
  direct object). Both form and explanation fixed by grounding.
- **Form-only saves**: every item where tuned's form was already right stayed right;
  no item where grounding broke a previously-correct form.

## What grounding broke or failed to fix (wrong grounded explanations)

Grounded replies with a correct form but a WRONG/fabricated explanation:

- **Item 0 & Item 14** — passé composé with *avoir*, but grounded invents
  "s'accorde avec le verbe être ... règle du subjonctif passé avec être."
- **Item 1 & Item 15** — circular non-explanation "j'ai acheté devient j'ai acheté
  (pas d'accord)"; never states infinitive-vs-participle, the actual error.
- **Item 2** — elision `parce qu'elle` wrongly attributed to "l'accord du subjonctif."
- **Item 7** — subjunctive `soit` wrongly attributed to "verbe à la 3e personne du
  singulier"; omits the *vouloir que* trigger.
- **Item 8 & Item 9** — self-contradictory: says "on utilise l'infinitif sans « de »"
  while the correct fix keeps *de* (`d'utiliser`).
- **Item 16 & Item 17** — introduces a spurious `planning -> planification` change
  (not an error) and calls `défini` "un adjectif conjugué à la 3e personne du singulier."

## Concision detail

- Items 10-13 (dialogue 6 & 7) are the only "concise" grounded replies — because the
  grounded text is byte-identical to the tuned text there (the engine fell back / had
  a short correction), so they only quote the erroneous phrase.
- All 14 genuinely-grounded replies quote the full sentence and are non-concise.

## Bottom line

Grounding the correction form in a grammar engine reliably fixes the FORM (100%) and
rescued the two hardest agreement cases, but it does not improve — and here slightly
worsens — the grammatical EXPLANATION, because the explanation is still model-generated
free text. To gain on the key metric, the explanation itself (not just the form) must
be grounded/templated. Concision also needs a fix: restate only the corrected phrase,
not the whole sentence.
