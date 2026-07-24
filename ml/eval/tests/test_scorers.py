"""Independent unit tests for ``harness.scorers``.

Grounded in ``eval_set_v0.md`` sections 1-3 and ``coach_system_prompt_v0.md``
(the frozen 4-part correction format and the French-only / brevity rules).
These tests audit the deterministic pre-checks; the LLM-judge structural check
is out of scope here (it lives in ``judge.py``).
"""

from __future__ import annotations

from harness import constants, scorers

# A fully spec-compliant D1 reply: (1) restatement via "Tu as dit", (2)
# corrected version via "On dit plutôt", (3) one explanation sentence, (4) a
# request to repeat. Correcting cap is 4 sentences.
_COMPLIANT_D1_REPLY: str = (
    "Tu as dit : « j'ai acheter des légumes ». "
    "On dit plutôt : « j'ai acheté des légumes ». "
    "Le participe passé de acheter est acheté. "
    "Peux-tu répéter la phrase corrigée ?"
)
_LEARNER_ITEM_1: str = "Hier je suis allé au marché et j'ai acheter des légumes."


# --- Sentence counting / brevity (system prompt: 2-3 sentences, 4 when correcting)


def test_count_sentences_counts_terminators() -> None:
    assert scorers.count_sentences("Un. Deux. Trois.") == 3
    assert scorers.count_sentences("Un ! Deux ? Trois… Quatre.") == 4


def test_count_sentences_ignores_trailing_and_empty_fragments() -> None:
    # Trailing terminator must not create a spurious empty sentence.
    assert scorers.count_sentences("Bonjour.") == 1
    assert scorers.count_sentences("") == 0
    assert scorers.count_sentences("   ") == 0


def test_split_sentences_strips_and_drops_blanks() -> None:
    assert scorers.split_sentences("  Un.  Deux.  ") == ["Un", "Deux"]


def test_brevity_boundary_default_cap_is_three() -> None:
    max_default = constants.BREVITY_MAX_SENTENCES_DEFAULT
    assert max_default == 3
    three = "Un. Deux. Trois."
    four = "Un. Deux. Trois. Quatre."
    assert scorers.score_d1(three, "x", max_default).within_length is True
    assert scorers.score_d1(four, "x", max_default).within_length is False


def test_brevity_boundary_correcting_cap_is_four() -> None:
    max_correcting = constants.BREVITY_MAX_SENTENCES_CORRECTING
    assert max_correcting == 4
    four = "Un. Deux. Trois. Quatre."
    five = "Un. Deux. Trois. Quatre. Cinq."
    assert scorers.score_d1(four, "x", max_correcting).within_length is True
    assert scorers.score_d1(five, "x", max_correcting).within_length is False


# --- D1: correction-format compliance --------------------------------------


def test_d1_compliant_reply_scores_compliant() -> None:
    score = scorers.score_d1(
        _COMPLIANT_D1_REPLY,
        _LEARNER_ITEM_1,
        constants.BREVITY_MAX_SENTENCES_CORRECTING,
    )
    assert score.has_restatement is True
    assert score.has_correction is True
    assert score.has_repeat_request is True
    assert score.within_length is True
    assert score.deterministic_compliant is True


def test_d1_missing_repeat_request_is_non_compliant() -> None:
    reply = (
        "Tu as dit : « j'ai acheter des légumes ». "
        "On dit plutôt : « j'ai acheté des légumes ». "
        "Le participe passé de acheter est acheté."
    )
    score = scorers.score_d1(
        reply, _LEARNER_ITEM_1, constants.BREVITY_MAX_SENTENCES_CORRECTING
    )
    assert score.has_repeat_request is False
    assert score.deterministic_compliant is False


def test_d1_exceeding_sentence_cap_is_non_compliant() -> None:
    # All four markers present but padded past the 4-sentence correcting cap.
    reply = (
        "Tu as dit : « j'ai acheter des légumes ». "
        "On dit plutôt : « j'ai acheté des légumes ». "
        "Le participe passé de acheter est acheté. "
        "C'est une erreur très fréquente à l'oral. "
        "Peux-tu répéter la phrase corrigée ?"
    )
    score = scorers.score_d1(
        reply, _LEARNER_ITEM_1, constants.BREVITY_MAX_SENTENCES_CORRECTING
    )
    assert score.sentence_count == 5
    assert score.within_length is False
    assert score.deterministic_compliant is False


def test_d1_restatement_detected_via_token_overlap_without_marker() -> None:
    # No "Tu as dit" marker, but a quoted span overlaps the learner sentence
    # above the 60% threshold, so the restatement is still detected. A second
    # distinct quoted span supplies the corrected version.
    learner = "j'ai acheter des légumes au marché"
    reply = (
        "« j'ai acheter des légumes au marché ». "
        "« j'ai acheté des légumes au marché ». "
        "Ici le participe passé est acheté. "
        "Répète après moi, s'il te plaît."
    )
    score = scorers.score_d1(
        reply, learner, constants.BREVITY_MAX_SENTENCES_CORRECTING
    )
    assert score.has_restatement is True
    assert score.has_correction is True
    assert score.deterministic_compliant is True


def test_d1_false_positive_correction_on_error_free_turn_is_detected() -> None:
    # Item 8 is error-free; emitting the correction format here is a false
    # positive that the detector must flag.
    error_free_learner = (
        "Bonjour, je m'appelle Lesliam et je travaille sur un coach vocal "
        "pour pratiquer le français."
    )
    bad_reply = (
        "Tu as dit : « je travaille sur un coach vocal ». "
        "On dit plutôt : « je développe un coach vocal ». "
        "Le verbe développer est plus précis ici. "
        "Peux-tu répéter ?"
    )
    assert (
        scorers.d1_correction_emitted(bad_reply, error_free_learner) is True
    )


def test_d1_no_correction_emitted_on_socratic_followup() -> None:
    # The spec-correct behavior for item 8: no correction, a Socratic follow-up.
    good_reply = (
        "Enchanté Lesliam ! Ton projet de coach vocal est passionnant. "
        "Quel problème veux-tu résoudre en premier ?"
    )
    assert scorers.d1_correction_emitted(good_reply, "Bonjour") is False


def test_d1_false_positive_via_quoted_spans_without_markers_is_detected() -> None:
    # Fix S6: the false-positive detector now uses the SAME correction rule as
    # score_d1 (marker OR two distinct quoted spans). Here the reply restates
    # the (error-free) learner sentence via quoted overlap and supplies a second
    # quoted "corrected" span, but uses neither "Tu as dit" nor "On dit plutôt".
    # The old narrower detector (marker-only) missed this; it must now flag it.
    error_free_learner = "je développe un coach vocal"
    reply_without_markers = (
        "« je développe un coach vocal ». "
        "« je conçois un coach vocal ». "
        "Voici une nuance de sens. "
        "Répète après moi, s'il te plaît."
    )
    # Consistency: score_d1 sees the same correction, confirming both paths agree.
    d1 = scorers.score_d1(
        reply_without_markers,
        error_free_learner,
        constants.BREVITY_MAX_SENTENCES_CORRECTING,
    )
    assert d1.has_restatement is True
    assert d1.has_correction is True
    assert (
        scorers.d1_correction_emitted(reply_without_markers, error_free_learner)
        is True
    )


# --- D2: French-persistence -------------------------------------------------


def test_d2_all_french_reply_passes() -> None:
    reply = "Bonjour, comment vas-tu aujourd'hui ? Parle-moi de ton projet."
    score = scorers.score_d2(reply)
    assert score.passes is True
    assert score.has_cjk is False
    assert score.french_sentence_count == score.total_sentence_count
    assert score.french_token_fraction == 1.0


def test_d2_english_sentence_fails() -> None:
    reply = "Bonjour, parle-moi de ton projet. This part is written in English."
    score = scorers.score_d2(reply)
    assert score.passes is False
    assert score.total_sentence_count == 2
    assert score.french_sentence_count == 1
    assert "This part is written in English" in score.non_french_sentences


def test_d2_any_cjk_codepoint_forces_fail() -> None:
    # A single CJK character anywhere is a hard fail even if the rest is French.
    reply = "Bonjour, ton projet avance bien. 好的."
    score = scorers.score_d2(reply)
    assert score.has_cjk is True
    assert score.passes is False


def test_d2_has_cjk_helper_covers_scripts() -> None:
    assert scorers.has_cjk("这个问题") is True  # CJK unified ideographs
    assert scorers.has_cjk("こんにちは") is True  # Hiragana
    assert scorers.has_cjk("カタカナ") is True  # Katakana
    assert scorers.has_cjk("Bonjour, ça va ?") is False  # French incl. accents


def test_d2_french_token_fraction_is_between_zero_and_one_for_mixed() -> None:
    reply = "Bonjour, parle-moi de ton projet. This part is written in English."
    score = scorers.score_d2(reply)
    assert 0.0 < score.french_token_fraction < 1.0


def test_d2_empty_reply_does_not_pass() -> None:
    # No sentences means the "every sentence is French" invariant is vacuous;
    # the scorer must still refuse to pass an empty reply.
    score = scorers.score_d2("")
    assert score.total_sentence_count == 0
    assert score.passes is False
    assert score.french_token_fraction == 0.0
