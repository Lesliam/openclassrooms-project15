"""Offline unit tests for the D4 closing-cue deterministic detectors.

These exercise ``reply_ends_with_question``, ``is_warm_close``,
``classify_reply`` and the metric aggregation on hand-written replies. They run
on CPU with no Ollama, mirroring the frozen-harness scorer tests
(``test_scorers.py``): the model call in ``run_closing_cue_compare.main`` is out
of scope here.
"""

from __future__ import annotations

import run_closing_cue_compare as d4

# --- reply_ends_with_question ----------------------------------------------


def test_ends_with_question_plain_terminal_mark() -> None:
    assert d4.reply_ends_with_question("Tu veux réviser un mot ?") is True


def test_ends_with_question_ignores_trailing_quote_and_space() -> None:
    # A question wrapped in guillemets, with trailing whitespace, still counts.
    assert d4.reply_ends_with_question('On dit « comment ça va ? »  ') is True


def test_ends_with_question_false_for_statement() -> None:
    assert d4.reply_ends_with_question("À demain, repose-toi bien.") is False


def test_ends_with_question_false_when_question_is_not_terminal() -> None:
    # A mid-reply question that is not the final sentence is not "terminal".
    assert d4.reply_ends_with_question("Bonne question ? Oui. On continue.") is False


# --- is_warm_close ----------------------------------------------------------


def test_warm_close_true_for_short_farewell_without_question() -> None:
    assert d4.is_warm_close("À demain, repose-toi bien. Bonne nuit !") is True


def test_warm_close_false_without_farewell_cue() -> None:
    # Short and question-free, but no goodbye cue -> not a close (it is soft).
    assert d4.is_warm_close("De rien, c'était un plaisir.") is False


def test_warm_close_false_when_ends_with_question() -> None:
    assert d4.is_warm_close("Bonne nuit ! Tu veux un dernier mot ?") is False


def test_warm_close_false_when_repeat_drill_present() -> None:
    # A close must not drag the learner into the correction drill.
    reply = (
        "Bonne nuit ! On dit plutôt « j'ai fini ». "
        "Peux-tu répéter la phrase corrigée ?"
    )
    assert d4.is_warm_close(reply) is False


def test_warm_close_false_when_too_long() -> None:
    long_reply = (
        "Au revoir. Tu as bien travaillé. "
        "Tu progresses vraiment. Continue comme ça. Repose-toi."
    )
    assert d4.is_warm_close(long_reply) is False


# --- classify_reply ---------------------------------------------------------


def test_classify_question_takes_priority_over_close_marker() -> None:
    # Ends with a question despite a farewell cue -> it did not actually close.
    assert d4.classify_reply("À demain ! Tu veux réviser encore un mot ?") == (
        d4.CLASS_QUESTION
    )


def test_classify_closed_for_warm_farewell() -> None:
    assert d4.classify_reply("Repose-toi bien, à demain. Bonne nuit !") == (
        d4.CLASS_CLOSED
    )


def test_classify_soft_for_answer_without_goodbye_or_question() -> None:
    assert d4.classify_reply("De rien, c'était un plaisir de t'aider.") == (
        d4.CLASS_SOFT
    )


def test_classify_bare_thanks_reply_not_closed() -> None:
    # Regression for the headline risk: bare-thanks reply that stays engaged
    # must be soft or question, never closed.
    assert d4.classify_reply("De rien ! On continue avec un nouveau mot ?") != (
        d4.CLASS_CLOSED
    )


# --- is_correct per label ---------------------------------------------------


def test_is_correct_cloture_requires_closed() -> None:
    assert d4.is_correct(d4.LABEL_CLOTURE, d4.CLASS_CLOSED) is True
    assert d4.is_correct(d4.LABEL_CLOTURE, d4.CLASS_QUESTION) is False
    assert d4.is_correct(d4.LABEL_CLOTURE, d4.CLASS_SOFT) is False


def test_is_correct_souple_forbids_closed_only() -> None:
    assert d4.is_correct(d4.LABEL_SOUPLE, d4.CLASS_SOFT) is True
    assert d4.is_correct(d4.LABEL_SOUPLE, d4.CLASS_QUESTION) is True
    assert d4.is_correct(d4.LABEL_SOUPLE, d4.CLASS_CLOSED) is False


def test_is_correct_defaut_requires_question() -> None:
    assert d4.is_correct(d4.LABEL_DEFAUT, d4.CLASS_QUESTION) is True
    assert d4.is_correct(d4.LABEL_DEFAUT, d4.CLASS_CLOSED) is False
    assert d4.is_correct(d4.LABEL_DEFAUT, d4.CLASS_SOFT) is False


# --- compute_metrics --------------------------------------------------------


def test_compute_metrics_headline_numbers() -> None:
    records = [
        # CLOTURE: one correctly closed, one wrongly left as a question.
        {"label": d4.LABEL_CLOTURE, "classification": d4.CLASS_CLOSED, "correct": True},
        {
            "label": d4.LABEL_CLOTURE,
            "classification": d4.CLASS_QUESTION,
            "correct": False,
        },
        # SOUPLE: one soft (good), one wrongly closed (premature close).
        {"label": d4.LABEL_SOUPLE, "classification": d4.CLASS_SOFT, "correct": True},
        {
            "label": d4.LABEL_SOUPLE,
            "classification": d4.CLASS_CLOSED,
            "correct": False,
        },
        # DEFAUT: one question (good).
        {
            "label": d4.LABEL_DEFAUT,
            "classification": d4.CLASS_QUESTION,
            "correct": True,
        },
    ]
    metrics = d4.compute_metrics(records)
    assert metrics.n_scored == 5
    assert metrics.closer_recall == 0.5  # 1 of 2 CLOTURE closed
    # 1 of 3 non-CLOTURE wrongly closed.
    assert round(metrics.premature_close_rate, 4) == round(1 / 3, 4)
    assert metrics.per_label_accuracy[d4.LABEL_DEFAUT] == 1.0


def test_compute_metrics_ignores_unscored_records() -> None:
    records = [
        {"label": d4.LABEL_CLOTURE, "classification": None, "correct": False},
        {"label": d4.LABEL_SOUPLE, "classification": None, "correct": False},
    ]
    metrics = d4.compute_metrics(records)
    assert metrics.n_items == 2
    assert metrics.n_scored == 0
    assert metrics.accuracy == 0.0
    assert metrics.premature_close_rate == 0.0


def test_dialogue_set_counts_match_spec() -> None:
    labels = [d.label for d in d4.DIALOGUES]
    assert len(labels) == 20
    assert labels.count(d4.LABEL_CLOTURE) == 7
    assert labels.count(d4.LABEL_SOUPLE) == 7
    assert labels.count(d4.LABEL_DEFAUT) == 6
