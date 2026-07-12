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

2. **Automated check.** `check_leakage.py` parses every `L: "..."` learner
   turn from `../eval/eval_set_v0.md` (source of truth, so the check tracks
   the eval file if it is ever edited), normalizes text (lowercase, strip
   punctuation, collapse whitespace, NFC), and asserts **zero exact matches**
   against the 80 corpus user turns. It also reports the worst token-overlap
   (Jaccard) near-duplicate as a soft signal.

## Check result

```
Eval learner turns parsed : 18
Corpus user turns         : 80
Exact overlaps            : 0
Max Jaccard near-dup      : 0.50 (pairs >= 0.70: 0)
PASS: corpus is disjoint from the evaluation set (0 exact overlaps).
```

Note on the count: `eval_set_v0.md` lists 20 items, but items 14 and 15 are
long-context drift probes that **reuse** items 1 and 9 ("Probe = item 1")
rather than introducing new learner turns. So there are 18 distinct quoted
learner turns, and the parser covers all of them.

The highest near-duplicate (Jaccard 0.50) is the corpus turn
`"What do you think about my project timeline?"` vs the eval turn
`"Ok ok. Anyway, what do you think about my architecture choice?"` — same
generic English frame, different content ("timeline" vs "architecture
choice"), well below the 0.70 warning threshold. This is a surface n-gram
overlap on a common English phrase, not a reused test item.

## The dev split does not break the rule

`sft_config.yaml` sets `val_set_size: 0.1`, carving ~8 dev examples out of the
80 for an in-training loss signal. Those 8 come from the **corpus**, never
from the eval set — the eval set stays fully held out and unseen by training.

## Re-running the check

```bash
cd <project-root>
python ml/finetune/check_leakage.py   # exit 0 = disjoint, 1 = leakage
```

Run this again after any edit to the corpus or the eval set before training.
