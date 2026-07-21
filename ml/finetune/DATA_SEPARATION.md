# Train / eval separation — no leakage

The hard ML rule for this experiment: the SFT corpus
(`corpus/coach_sft.jsonl`) must be **disjoint** from the evaluation set
(`../eval/eval_set_v0.md`). If a training example reused an eval learner
turn, the fine-tuned arm would be measured partly on data it memorized, and
the prompt-baseline-vs-fine-tuned comparison would be invalid.

## What "disjoint" means here

The eval set defines the learner turns (`L: "..."`) that both arms are graded
on. The corpus provides the ideal coach turns the tuned arm learns from. The
guarantee is: **no corpus user turn reuses an eval learner turn.** The coach
replies are not shared either — the eval file contains only expectations, not
reference replies, so there is nothing to leak on the assistant side.

## How disjointness was guaranteed

1. **Different sentences by construction.** Every corpus learner turn was
   hand-authored as a new sentence. Where the corpus covers the same error
   *class* as the eval set (agreement, elision, subjunctive, comparative,
   tense), it uses a *different* sentence and often a different lexical
   trigger. Covering the same grammar phenomenon is required (that is the
   skill being taught); reusing the same sentence is forbidden.

   Examples of same-class / different-sentence:
   - Elision: eval item 2 tests `parce que elle -> parce qu'elle` and item 5
     tests `de utiliser -> d'utiliser`; the corpus tests `que il -> qu'il`,
     `si il -> s'il`, `de une -> d'une`, `de le -> du`, `à le -> au`,
     `je aime -> j'aime` — none of the eval sentences.
   - Subjunctive: eval item 4 tests `je veux que ... est -> soit`; the corpus
     tests `il faut que je finis -> finisse`, `bien que ... est -> soit`,
     `à condition que tu es -> sois`, etc. — different matrices.
   - Comparative: eval item 6 tests `plus meilleure -> meilleure`; the corpus
     tests `plus bonne -> meilleure`, `plus bien -> mieux`,
     `aussi meilleure -> aussi bonne`, `le plus pire -> le pire`.
   - Tense: eval items 1 / 20 test `j'ai acheter` / `j'ai définir` (infinitive
     for past participle); the corpus deliberately avoids that exact pattern
     and uses imperfect-vs-present, future-vs-imperfect, `si`+present->future,
     and `répond -> répondu` instead.

2. **Automated check, two held-out sets.** `check_leakage.py` checks the corpus
   against BOTH frozen held-out sets and fails if either has an exact overlap:
   - `../eval/eval_set_v0.md` — the frozen D1-D3 harness; learner turns parsed
     as `L: "..."`.
   - `../eval/disfluency_set_v1.md` — the D5 disfluency / incomplete-turn
     mini-eval (CS-157); learner turns parsed from the markdown tables keyed by
     an id (`F1`, `I2`, `R3`, `N1`, ...). CS-158 adds disfluency training
     examples, so D5 must be proven disjoint too or it stops being a valid
     held-out metric.

   For each set it normalizes text (lowercase, strip punctuation, collapse
   whitespace, NFC), asserts **zero exact matches** against the 125 corpus user
   turns, and reports the worst token-overlap (Jaccard) near-duplicate as a
   soft signal.

## D5 same-class / different-sentence (CS-158)

The 45 disfluency examples added in CS-158 cover the SAME subtypes as the D5
held-out set (word/segment repetition, fillers « euh »/« hmm », false start,
already-self-corrected agreement/word-choice, filler+repetition combined,
incomplete turn, real error inside disfluency, clean control) but always with
DIFFERENT sentences and topics (planning, capteur, latence, prototype, rapport,
mentor…) than the D5 items (marché, portfolio, soutenance, réunion…). The
near-miss pairs of D5 (F6 vs R1: already-self-corrected `allé... allée` vs
genuine `allé`) are taught by analogous but non-overlapping corpus pairs
(self-corrected `motivé... motivée` vs genuine participle/gender errors).

## Check result

```
[eval_v0] held-out learner turns : 18
[eval_v0] corpus user turns      : 125
[eval_v0] exact overlaps         : 0
[eval_v0] max Jaccard near-dup   : 0.50 (pairs >= 0.7: 0)

[disfluency_d5] held-out learner turns : 19
[disfluency_d5] corpus user turns      : 125
[disfluency_d5] exact overlaps         : 0
[disfluency_d5] max Jaccard near-dup   : 0.50 (pairs >= 0.7: 0)

PASS: corpus is disjoint from both held-out sets (eval_set_v0 + disfluency_set_v1; 0 exact overlaps).
```

Note on the counts: `eval_set_v0.md` lists 20 items, but items 14 and 15 are
long-context drift probes that **reuse** items 1 and 9 ("Probe = item 1")
rather than introducing new learner turns, so there are 18 distinct quoted
learner turns. `disfluency_set_v1.md` has 19 single-turn dialogues
(8 DISFLUENCY + 4 INCOMPLETE + 4 REALERROR + 3 CLEAN); the parser covers all.

The highest near-duplicate (Jaccard 0.50) is the corpus turn
`"What do you think about my project timeline?"` vs the eval turn
`"Ok ok. Anyway, what do you think about my architecture choice?"` — same
generic English frame, different content ("timeline" vs "architecture
choice"), well below the 0.70 warning threshold. This is a surface n-gram
overlap on a common English phrase, not a reused test item.

## The dev split does not break the rule

`sft_config.yaml` sets `val_set_size: 0.1`, carving ~12 dev examples out of the
125 for an in-training loss signal. Those come from the **corpus**, never from
a held-out set — both `eval_set_v0` and `disfluency_set_v1` stay fully held out
and unseen by training.

## Re-running the check

```bash
cd <project-root>
python ml/finetune/check_leakage.py   # exit 0 = disjoint, 1 = leakage
```

Run this again after any edit to the corpus or the eval set before training.
