"""Independent unit tests for ``harness.spec_guard``.

The guard's contract: every learner turn in ``dialogues.py`` must appear
verbatim (whitespace-normalized) inside the frozen ``eval_set_v0.md``. A
deliberately altered learner text must be reported as drift.
"""

from __future__ import annotations

import pytest

from harness import dialogues, spec_guard
from harness.dialogues import Dialogue, Expectation, LearnerTurn


def test_shipped_dialogues_match_spec_verbatim() -> None:
    # The as-committed dialogue set must not drift from the frozen spec.
    assert spec_guard.find_drifted_turns() == []


def test_verify_dialogues_match_spec_does_not_raise_for_clean_set() -> None:
    # Should return None (no exception) when everything matches.
    assert spec_guard.verify_dialogues_match_spec() is None


def test_altered_learner_text_is_flagged_as_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    # Plant an accent-stripped variant that does NOT appear in the spec.
    altered = LearnerTurn(
        item_id=999,
        text="Hier je suis alle au marche et j'ai acheter des legumes.",
        expect=Expectation(correction_required=True),
    )
    altered_dialogue = Dialogue(
        id=999, group="A", kind=dialogues.KIND_SIMPLE, turns=(altered,)
    )
    monkeypatch.setattr(spec_guard, "ALL_DIALOGUES", (altered_dialogue,))

    drifted = spec_guard.find_drifted_turns()
    assert (999, altered.text) in drifted


def test_verify_raises_assertion_error_on_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    altered = LearnerTurn(
        item_id=999,
        text="Ceci est une phrase qui n'existe pas dans la specification.",
        expect=Expectation(),
    )
    altered_dialogue = Dialogue(
        id=999, group="A", kind=dialogues.KIND_SIMPLE, turns=(altered,)
    )
    monkeypatch.setattr(spec_guard, "ALL_DIALOGUES", (altered_dialogue,))

    with pytest.raises(AssertionError) as exc_info:
        spec_guard.verify_dialogues_match_spec()
    assert "999" in str(exc_info.value)


def test_drift_probe_turns_are_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    # A drift dialogue carries its learner text on ``probe`` (not ``turns``);
    # the guard must still validate it.
    probe = LearnerTurn(
        item_id=999,
        text="Phrase de sonde absente de la specification figee.",
        expect=Expectation(),
    )
    drift_dialogue = Dialogue(
        id=999, group="C", kind=dialogues.KIND_DRIFT, probe=probe
    )
    monkeypatch.setattr(spec_guard, "ALL_DIALOGUES", (drift_dialogue,))

    drifted = spec_guard.find_drifted_turns()
    assert (999, probe.text) in drifted


def test_whitespace_normalization_tolerates_reflowed_spec_text() -> None:
    # Learner turns that span multiple source lines (e.g. item 3) still match
    # despite line-wrapping differences, because both sides are normalized.
    multiline = (
        "Mon projet utilise un modèle qui peut reconnaître le mot de réveil, "
        "il est entraîné sur les données que j'ai collecté."
    )
    normalized = spec_guard._normalize("  Mon projet   utilise\n un modèle  ")
    assert normalized == "Mon projet utilise un modèle"
    # And the real multi-line item is not flagged as drift.
    drifted_texts = [text for _, text in spec_guard.find_drifted_turns()]
    assert multiline not in drifted_texts
