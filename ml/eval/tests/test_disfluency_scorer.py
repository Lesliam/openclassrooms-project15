"""Offline unit tests for the D5 disfluency deterministic detectors.

These exercise ``correction_emitted``, ``applies_4part_format``,
``invites_to_continue``, ``correction_targets_disfluency``, ``classify_reply``
and the metric aggregation on hand-written replies. They run on CPU with no
Ollama, mirroring the frozen-harness scorer tests (``test_scorers.py``): the
model call in ``run_disfluency_compare.main`` is out of scope here.
"""

from __future__ import annotations

import run_disfluency_compare as d5

# Learner turns reused across tests (a self-corrected form and a genuine error).
_LEARNER_SELF_CORRECTED = "Hier je suis allé... allée au marché."
_LEARNER_REAL_ERROR = "Euh, hier je suis allé au marché."

# A full 4-part correction reply and a bare non-correction reply.
_CORRECTION_REPLY = (
    "Tu as dit : « je suis allé ». On dit plutôt : « je suis allée ». "
    "Le participe s'accorde au féminin. Peux-tu répéter la phrase corrigée ?"
)
_ENGAGED_REPLY = "Ton projet a l'air passionnant. Quel problème veux-tu résoudre ?"


# --- correction_emitted -----------------------------------------------------


def test_correction_emitted_true_for_full_drill() -> None:
    assert d5.correction_emitted(_CORRECTION_REPLY, _LEARNER_REAL_ERROR) is True


def test_correction_emitted_false_for_engaged_reply() -> None:
    assert d5.correction_emitted(_ENGAGED_REPLY, "Mon projet est intéressant.") is False


def test_correction_emitted_false_for_praised_self_correction() -> None:
    # Acknowledging the learner's own fix (one quoted span, no "on dit plutôt")
    # must NOT count as a correction.
    reply = "Bravo, tu t'es corrigée toute seule : « je suis allée ». C'est parfait !"
    assert d5.correction_emitted(reply, _LEARNER_SELF_CORRECTED) is False


# --- applies_4part_format ---------------------------------------------------


def test_applies_4part_format_true_when_all_markers_present() -> None:
    assert d5.applies_4part_format(_CORRECTION_REPLY, _LEARNER_REAL_ERROR) is True


def test_applies_4part_format_false_without_repeat_request() -> None:
    # A correction with no repeat step is still `correction_emitted` but not the
    # full 4-part drill.
    reply = "Tu as dit « je suis allé ». On dit plutôt « je suis allée »."
    assert d5.correction_emitted(reply, _LEARNER_REAL_ERROR) is True
    assert d5.applies_4part_format(reply, _LEARNER_REAL_ERROR) is False


# --- invites_to_continue ----------------------------------------------------


def test_invites_true_for_prompt_examples() -> None:
    assert d5.invites_to_continue("Prends ton temps, je t'écoute.") is True
    assert d5.invites_to_continue("Tu veux continuer ?") is True


def test_invites_true_for_develop_and_precise() -> None:
    assert d5.invites_to_continue("Tu peux développer ta pensée ?") is True


def test_invites_false_for_ordinary_socratic_question() -> None:
    assert d5.invites_to_continue("Quel est ton projet préféré ?") is False


# --- correction_targets_disfluency ------------------------------------------


def test_correction_targets_disfluency_true_for_quoted_repetition() -> None:
    reply = "Tu as dit : « je je vais ». On dit plutôt : « je vais »."
    assert d5.correction_targets_disfluency(reply) is True


def test_correction_targets_disfluency_true_for_quoted_filler() -> None:
    reply = "Tu as dit : « euh ». Ce n'est pas nécessaire."
    assert d5.correction_targets_disfluency(reply) is True


def test_correction_targets_disfluency_false_for_real_error_span() -> None:
    reply = "Tu as dit : « au réunion ». On dit plutôt : « à la réunion »."
    assert d5.correction_targets_disfluency(reply) is False


# --- classify_reply ---------------------------------------------------------


def test_classify_corrected_takes_priority_over_invite() -> None:
    # A reply that both corrects and invites is `corrected` (the dominant act).
    reply = _CORRECTION_REPLY + " Ensuite, prends ton temps, je t'écoute."
    assert d5.classify_reply(reply, _LEARNER_REAL_ERROR) == d5.CLASS_CORRECTED


def test_classify_invited_for_continue_invitation() -> None:
    assert d5.classify_reply("Prends ton temps, je t'écoute.", "Je pense que...") == (
        d5.CLASS_INVITED
    )


def test_classify_engaged_for_plain_relance() -> None:
    assert d5.classify_reply(_ENGAGED_REPLY, "Mon projet est intéressant.") == (
        d5.CLASS_ENGAGED
    )


# --- is_correct per label ---------------------------------------------------


def test_is_correct_disfluency_forbids_correction() -> None:
    assert d5.is_correct(d5.LABEL_DISFLUENCY, d5.CLASS_ENGAGED) is True
    assert d5.is_correct(d5.LABEL_DISFLUENCY, d5.CLASS_INVITED) is True
    assert d5.is_correct(d5.LABEL_DISFLUENCY, d5.CLASS_CORRECTED) is False


def test_is_correct_incomplete_requires_invite() -> None:
    assert d5.is_correct(d5.LABEL_INCOMPLETE, d5.CLASS_INVITED) is True
    assert d5.is_correct(d5.LABEL_INCOMPLETE, d5.CLASS_ENGAGED) is False
    assert d5.is_correct(d5.LABEL_INCOMPLETE, d5.CLASS_CORRECTED) is False


def test_is_correct_realerror_requires_correction() -> None:
    assert d5.is_correct(d5.LABEL_REALERROR, d5.CLASS_CORRECTED) is True
    assert d5.is_correct(d5.LABEL_REALERROR, d5.CLASS_ENGAGED) is False
    assert d5.is_correct(d5.LABEL_REALERROR, d5.CLASS_INVITED) is False


def test_is_correct_clean_forbids_correction() -> None:
    assert d5.is_correct(d5.LABEL_CLEAN, d5.CLASS_ENGAGED) is True
    assert d5.is_correct(d5.LABEL_CLEAN, d5.CLASS_CORRECTED) is False


# --- compute_metrics --------------------------------------------------------


def test_compute_metrics_headline_numbers() -> None:
    records = [
        # DISFLUENCY: one engaged (good), one wrongly corrected (false correction).
        {
            "label": d5.LABEL_DISFLUENCY,
            "classification": d5.CLASS_ENGAGED,
            "correct": True,
        },
        {
            "label": d5.LABEL_DISFLUENCY,
            "classification": d5.CLASS_CORRECTED,
            "correct": False,
        },
        # INCOMPLETE: one invited (good), one engaged (missed the invite).
        {
            "label": d5.LABEL_INCOMPLETE,
            "classification": d5.CLASS_INVITED,
            "correct": True,
        },
        {
            "label": d5.LABEL_INCOMPLETE,
            "classification": d5.CLASS_ENGAGED,
            "correct": False,
        },
        # REALERROR: one corrected (recalled), one missed.
        {
            "label": d5.LABEL_REALERROR,
            "classification": d5.CLASS_CORRECTED,
            "correct": True,
        },
        {
            "label": d5.LABEL_REALERROR,
            "classification": d5.CLASS_ENGAGED,
            "correct": False,
        },
        # CLEAN: one engaged (good).
        {"label": d5.LABEL_CLEAN, "classification": d5.CLASS_ENGAGED, "correct": True},
    ]
    metrics = d5.compute_metrics(records)
    assert metrics.n_scored == 7
    assert metrics.disfluency_false_correction_rate == 0.5  # 1 of 2 DISFLUENCY
    assert metrics.real_error_recall == 0.5  # 1 of 2 REALERROR corrected
    assert metrics.incomplete_invite_rate == 0.5  # 1 of 2 INCOMPLETE invited
    assert metrics.per_label_accuracy[d5.LABEL_CLEAN] == 1.0


def test_compute_metrics_ignores_unscored_records() -> None:
    records = [
        {"label": d5.LABEL_DISFLUENCY, "classification": None, "correct": False},
        {"label": d5.LABEL_REALERROR, "classification": None, "correct": False},
    ]
    metrics = d5.compute_metrics(records)
    assert metrics.n_items == 2
    assert metrics.n_scored == 0
    assert metrics.accuracy == 0.0
    assert metrics.disfluency_false_correction_rate == 0.0
    assert metrics.real_error_recall == 0.0


def test_dialogue_set_counts_match_spec() -> None:
    labels = [d.label for d in d5.DIALOGUES]
    assert len(labels) == 19
    assert labels.count(d5.LABEL_DISFLUENCY) == 8
    assert labels.count(d5.LABEL_INCOMPLETE) == 4
    assert labels.count(d5.LABEL_REALERROR) == 4
    assert labels.count(d5.LABEL_CLEAN) == 3
