"""Assert the SFT corpus is DISJOINT from the frozen evaluation set.

Hard ML rule: no train/test leakage. The SFT corpus user turns must never
reuse an ``eval_set_v0.md`` learner turn. This script:

1. Parses every learner turn (``L: "..."``) from the eval set file (source of
   truth, so the check tracks the eval file if it changes).
2. Loads every user turn from the corpus JSONL.
3. Asserts zero EXACT matches after normalization (fail = leakage).
4. Reports the highest token-overlap (Jaccard) near-duplicate pair as a soft
   signal, so accidental paraphrase-level reuse is visible even though it is
   not an automatic failure.

Exit code 0 = disjoint, 1 = leakage detected. CPU only; no GPU, no training.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent  # .../project15/project
EVAL_FILE = PROJECT_ROOT / "ml" / "eval" / "eval_set_v0.md"
CORPUS_FILE = HERE / "corpus" / "coach_sft.jsonl"

# A learner turn appears as  L: "<text possibly spanning lines>"
LEARNER_RE = re.compile(r'L:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)

NEAR_DUP_WARN = 0.7  # Jaccard threshold above which we print a warning.


def normalize(text: str) -> str:
    """Lowercase, collapse whitespace, drop punctuation, NFC-normalize."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\n", " ").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def load_eval_turns() -> list[str]:
    text = EVAL_FILE.read_text(encoding="utf-8")
    turns = [m.group(1).strip() for m in LEARNER_RE.finditer(text)]
    if not turns:
        raise ValueError(f"No learner turns parsed from {EVAL_FILE}")
    return turns


def load_corpus_user_turns() -> list[str]:
    turns: list[str] = []
    with CORPUS_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for msg in record["messages"]:
                if msg["role"] == "user":
                    turns.append(msg["content"])
    return turns


def main() -> int:
    eval_turns = load_eval_turns()
    corpus_turns = load_corpus_user_turns()

    eval_norm = {normalize(t): t for t in eval_turns}
    exact_hits: list[tuple[str, str]] = []
    for c in corpus_turns:
        n = normalize(c)
        if n in eval_norm:
            exact_hits.append((c, eval_norm[n]))

    print(f"Eval learner turns parsed : {len(eval_turns)}")
    print(f"Corpus user turns         : {len(corpus_turns)}")
    print(f"Exact overlaps            : {len(exact_hits)}")

    # Soft near-duplicate report: worst-case Jaccard per corpus turn.
    worst: tuple[float, str, str] = (0.0, "", "")
    over_threshold = 0
    for c in corpus_turns:
        for e in eval_turns:
            j = jaccard(c, e)
            if j > worst[0]:
                worst = (j, c, e)
            if j >= NEAR_DUP_WARN:
                over_threshold += 1
                print(f"  [warn] Jaccard {j:.2f} >= {NEAR_DUP_WARN}")
                print(f"         corpus: {c}")
                print(f"         eval  : {e}")
    print(
        f"Max Jaccard near-dup      : {worst[0]:.2f} "
        f"(pairs >= {NEAR_DUP_WARN}: {over_threshold})"
    )
    if worst[0] > 0:
        print(f"  closest corpus turn : {worst[1]}")
        print(f"  closest eval turn   : {worst[2]}")

    if exact_hits:
        print("\nLEAKAGE DETECTED: corpus reuses eval learner turns:")
        for c, e in exact_hits:
            print(f"  corpus: {c}\n  eval  : {e}\n")
        return 1

    print("\nPASS: corpus is disjoint from the evaluation set (0 exact overlaps).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
