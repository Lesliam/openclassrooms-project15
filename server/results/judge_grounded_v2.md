# Grammar-Correction Judge — tuned vs grounded_v2 (D1, 18 items)

## Scope
- Total items: 18
- Grounded_v2 fallthrough (engine detected no error → not-applicable): **4** (d6/r0, d6/r1, d7/r0, d7/r1)
- Gradable items (grounded_v2 produced an actual correction): **N = 14**
- Aggregates below are computed over the same 14 shared items for BOTH arms (apples-to-apples).

## Aggregate

| Metric                    | tuned (N=14) | grounded_v2 (N=14) |
|---------------------------|:------------:|:------------------:|
| explanation_correct       | **42.9%** (6/14) | **85.7%** (12/14) |
| correction_form_right     | 78.6% (11/14) | 85.7% (12/14) |
| concise                   | 21.4% (3/14)  | **100%** (14/14) |

Prior-round context (for reference only; those were over N=18):
tuned ≈ 38.9%, grounded-v1 (model-written explanation) ≈ 27.8% explanation-correct.
grounded_v2 explanation-correctness jumps to **85.7%** — the deterministic rule
templates are the intended fix and they work, with one systematic exception below.

## Template errors found in grounded_v2 (the 2 non-correct items)

**d18/r0 and d18/r1 (index 16, 17) — FALSE POSITIVE + inapplicable template.**
- grounded_v2 flags `le planning` as an error and "corrects" it to `la planification`
  with the rule *"L'article et l'adjectif s'accordent en genre avec le nom."*
- This is wrong on three counts: (a) `planning` is masculine in French, so `le planning`
  is already correct; (b) there is no adjectif in the phrase, so the agreement rule is
  inapplicable; (c) the change `planning`→`planification` is a lexical substitution, not a
  grammar fix.
- Worse, the real error in that sentence — `j'ai definir` → `j'ai defini` (infinitive
  used instead of participe passé) — is **missed** by grounded_v2. (tuned/r0 correctly
  catches it.)

These two are the ONLY grounded_v2 template failures; both stem from the same false
positive on d18.

## Coverage gaps (grammar engine fallthroughs on real errors)

The 4 fallthroughs are not clean "no error" cases — the engine missed real errors:
- d6 (`La latence est plus meilleure`): `plus meilleure` → `meilleure` is a real error, undetected.
- d7 (`Si j'aurais plus de temps`): `si j'aurais` → `si j'avais` is a real error, undetected.

So grounded_v2 has a **recall gap** (2 distinct real errors missed, ×2 reps = 4 items),
separate from its precision problem on d18.

## Concision

Fixed. grounded_v2 is **100% concise** — every reply restates only the erroneous
word/phrase and stays within 2–4 sentences. tuned is 21.4%: it routinely re-quotes the
whole learner sentence or a full clause (e.g. index 8, 14, 15, 16).

## tuned explanation failures (why 42.9%)

Most tuned misses are **fabricated / nonsensical grammar rules** attached to an
otherwise-correct fix:
- index 1: "après « je », « avoir » prend « -é »" (nonsense)
- index 3: "après « parce que » on utilise « elle » pas « elle est »" (nonsense)
- index 8: calls `d'utiliser` a *subjonctif* (it's elision + infinitif)
- index 9: "décider se construit avec « d' » et non « de »" (misleading; d' is phonetic)
- index 12/13: "le subjonctif « aille » devient « ai » après « si »" (it's imparfait)
- index 14: "le participe passé s'accorde avec « légumes »" — **actively wrong**: with
  avoir and COD placed after, there is NO agreement (would be `achetés` if it did)
- index 15: "après « hier » le verbe prend le participe passé" (hier irrelevant)
Plus 2 items where tuned didn't correct the actual error at all (index 4 missed COD
agreement; index 5 chased a dubious register point).
