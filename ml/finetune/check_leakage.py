"""Assert the SFT corpus is DISJOINT from every frozen held-out set.

Hard ML rule: no train/test leakage. The SFT corpus user turns must never
reuse a held-out learner turn. Two held-out sets are checked:

- ``eval_set_v0.md`` (the frozen D1-D3 harness) — learner turns as ``L: "..."``.
- ``disfluency_set_v1.md`` (the D5 disfluency / incomplete-turn mini-eval added
  in CS-157) — learner turns in markdown tables keyed by an id (``F1``, ``I2``,
  ``R3``, ``N1``, ...). CS-158 adds disfluency training examples, so D5 must be
  proven disjoint too or it stops being a valid held-out metric.

For each held-out set this script:

1. Parses every learner turn from the file (source of truth, so the check
   tracks the file if it changes).
2. Loads every user turn from the corpus JSONL.
3. Asserts zero EXACT matches after normalization (fail = leakage).
4. Reports the highest token-overlap (Jaccard) near-duplicate pair as a soft
   signal, so accidental paraphrase-level reuse is visible even though it is
   not an automatic failure.

Exit code 0 = disjoint from both sets, 1 = leakage detected in either. CPU
only; no GPU, no training.
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
D5_FILE = PROJECT_ROOT / "ml" / "eval" / "disfluency_set_v1.md"
CORPUS_FILE = HERE / "corpus" / "coach_sft.jsonl"

# A learner turn appears as  L: "<text possibly spanning lines>"
LEARNER_RE = re.compile(r'L:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)

# A D5 table row: | <id like F1/I2/R3/N1> | <learner turn> | ... |. The learner
# turn is always the second cell; later cells (intended sentence, sub-case) are
# not held-out learner turns and are ignored.
D5_ROW_RE = re.compile(r"^\|\s*([FIRN]\d+)\s*\|\s*(.+?)\s*\|")

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


def load_d5_turns() -> list[str]:
    """Parse D5 learner turns (second table cell) from the disfluency set."""
    text = D5_FILE.read_text(encoding="utf-8")
    turns: list[str] = []
    for line in text.splitlines():
        match = D5_ROW_RE.match(line)
        if match:
            turns.append(match.group(2).strip())
    if not turns:
        raise ValueError(f"No learner turns parsed from {D5_FILE}")
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


def check_set(
    name: str, held_out_turns: list[str], corpus_turns: list[str]
) -> list[tuple[str, str]]:
    """Check the corpus against one held-out set; return exact-overlap pairs.

    Prints per-set counts, any near-duplicate warnings, and the worst-case
    Jaccard pair. The returned list is empty when the corpus is disjoint.
    """
    held_norm = {normalize(t): t for t in held_out_turns}
    exact_hits: list[tuple[str, str]] = []
    for c in corpus_turns:
        n = normalize(c)
        if n in held_norm:
            exact_hits.append((c, held_norm[n]))

    print(f"[{name}] held-out learner turns : {len(held_out_turns)}")
    print(f"[{name}] corpus user turns      : {len(corpus_turns)}")
    print(f"[{name}] exact overlaps         : {len(exact_hits)}")

    # Soft near-duplicate report: worst-case Jaccard per corpus turn.
    worst: tuple[float, str, str] = (0.0, "", "")
    over_threshold = 0
    for c in corpus_turns:
        for e in held_out_turns:
            j = jaccard(c, e)
            if j > worst[0]:
                worst = (j, c, e)
            if j >= NEAR_DUP_WARN:
                over_threshold += 1
                print(f"  [warn] Jaccard {j:.2f} >= {NEAR_DUP_WARN}")
                print(f"         corpus  : {c}")
                print(f"         held-out: {e}")
    print(
        f"[{name}] max Jaccard near-dup   : {worst[0]:.2f} "
        f"(pairs >= {NEAR_DUP_WARN}: {over_threshold})"
    )
    if worst[0] > 0:
        print(f"  closest corpus turn   : {worst[1]}")
        print(f"  closest held-out turn : {worst[2]}")

    if exact_hits:
        print(f"\nLEAKAGE DETECTED ({name}): corpus reuses held-out learner turns:")
        for c, e in exact_hits:
            print(f"  corpus  : {c}\n  held-out: {e}\n")
    return exact_hits


def main() -> int:
    corpus_turns = load_corpus_user_turns()

    hits = check_set("eval_v0", load_eval_turns(), corpus_turns)
    print()
    hits += check_set("disfluency_d5", load_d5_turns(), corpus_turns)

    if hits:
        return 1

    print(
        "\nPASS: corpus is disjoint from both held-out sets "
        "(eval_set_v0 + disfluency_set_v1; 0 exact overlaps)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
