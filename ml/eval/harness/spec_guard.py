"""Guard: every learner text must appear VERBATIM in the frozen spec.

This prevents ``dialogues.py`` from silently drifting from
``eval_set_v0.md`` (for example, an accent-stripping regression that would
plant spurious errors and invalidate the baseline).

Comparison is whitespace-normalized on both sides so the spec's line wrapping
inside a single ``L:`` entry does not cause false mismatches; accents and the
planted grammatical errors are compared exactly.

Run standalone::

    python -m harness.spec_guard

Exit code 0 = all learner texts match; 1 = at least one drifted.
The drift FILLER_SCRIPT is intentionally not checked (it is harness-authored
neutral padding, not a numbered spec item).
"""

from __future__ import annotations

import re
import sys

from . import constants
from .dialogues import ALL_DIALOGUES, LearnerTurn

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends."""
    return _WHITESPACE.sub(" ", text).strip()


def _iter_learner_turns() -> list[LearnerTurn]:
    turns: list[LearnerTurn] = []
    for dialogue in ALL_DIALOGUES:
        turns.extend(dialogue.turns)
        if dialogue.probe is not None:
            turns.append(dialogue.probe)
    return turns


def find_drifted_turns() -> list[tuple[int, str]]:
    """Return (item_id, text) for every learner turn missing from the spec."""
    spec_normalized = _normalize(
        constants.EVAL_SET_FILE.read_text(encoding="utf-8")
    )
    drifted: list[tuple[int, str]] = []
    for turn in _iter_learner_turns():
        if _normalize(turn.text) not in spec_normalized:
            drifted.append((turn.item_id, turn.text))
    return drifted


def verify_dialogues_match_spec() -> None:
    """Raise AssertionError listing any learner text that drifted from the spec."""
    drifted = find_drifted_turns()
    if drifted:
        details = "\n".join(f"  item {item_id}: {text!r}" for item_id, text in drifted)
        raise AssertionError(
            "learner texts drifted from eval_set_v0.md (accents or wording):\n"
            + details
        )


def main() -> int:
    try:
        verify_dialogues_match_spec()
    except AssertionError as exc:
        print(f"[spec_guard] FAIL\n{exc}", file=sys.stderr)
        return 1
    count = len(_iter_learner_turns())
    print(f"[spec_guard] OK: {count} learner texts match eval_set_v0.md verbatim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
