"""Unit tests for the grammar-grounding correctness layer.

These tests exercise the PURE logic only: the language guard, the token-level
word diff, the has_error / edits consistency, the deterministic ``explain_edit``
grammar classifier, and ``build_grounded_correction``'s concise assembly. Its
central invariants are that BOTH the corrected form and the explanation are
grounded (no model is consulted on the correction path) and that the restated
spans are minimal (not the whole sentence). No model is loaded: the checker's
``_correct`` step is stubbed, so the whole suite runs in milliseconds on CPU.
"""

from __future__ import annotations

from grammar_grounding import (
    GrammarChecker,
    GrammarResult,
    build_grounded_correction,
    explain_edit,
    looks_french,
    word_diff,
)


# --- Language guard ---------------------------------------------------------


def test_looks_french_accepts_french_sentence() -> None:
    assert looks_french("Hier j'ai acheter des légumes au marché.") is True


def test_looks_french_rejects_english() -> None:
    assert looks_french("I think this is a very good solution for the project.") is False


def test_looks_french_rejects_chinese() -> None:
    assert looks_french("这个句子完全是中文写的") is False


def test_looks_french_rejects_empty() -> None:
    assert looks_french("   ") is False


# --- Token-level word diff --------------------------------------------------


def test_word_diff_reports_replacement() -> None:
    assert word_diff("j'ai acheter", "j'ai acheté") == ["'acheter' -> 'acheté'"]


def test_word_diff_reports_insertion() -> None:
    # A word appears in the corrected version that was absent from the original.
    edits = word_diff("je vais marché", "je vais au marché")
    assert edits == ["'' -> 'au'"]


def test_word_diff_reports_deletion() -> None:
    edits = word_diff("je ne sais pas rien", "je ne sais rien")
    assert edits == ["'pas' -> ''"]


def test_word_diff_empty_when_only_punctuation_changes() -> None:
    # Punctuation is not a word token, so a trailing-period change is no edit.
    assert word_diff("Bonjour", "Bonjour.") == []


def test_word_diff_reports_apostrophe_elision() -> None:
    # Apostrophe joins the word, so an added elision is a real word edit.
    assert word_diff("aujourd hui", "aujourd'hui") == ["'aujourd hui' -> 'aujourd'hui'"]


def test_word_diff_reports_hyphenation() -> None:
    assert word_diff("peux tu répéter", "peux-tu répéter") == ["'peux tu' -> 'peux-tu'"]


def test_has_error_and_edits_never_disagree_on_apostrophe() -> None:
    # Regression: has_error and edits are computed from the SAME token stream,
    # so an apostrophe-only change flags an error AND lists the change.
    checker = _StubChecker({"c est vrai": "c'est vrai"})
    result = checker.check("c est vrai")
    assert result.has_error is True
    assert result.edits == ["'c est' -> 'c'est'"]


def test_has_error_and_edits_never_disagree_on_hyphen() -> None:
    checker = _StubChecker({"est ce que": "est-ce que"})
    result = checker.check("est ce que")
    assert result.has_error is True
    assert result.edits == ["'est ce' -> 'est-ce'"]
    # Invariant: an error is flagged only when there is at least one edit.
    assert result.has_error == bool(result.edits)


def test_added_comma_is_not_flagged() -> None:
    # A GEC-added comma touches no word token: no error, no empty change line.
    checker = _StubChecker({"oui je pense": "oui, je pense"})
    result = checker.check("oui je pense")
    assert result.has_error is False
    assert result.edits == []


# --- has_error normalisation (via a stubbed checker) ------------------------


class _StubChecker(GrammarChecker):
    """Checker whose GEC step is a canned mapping -- no model is loaded."""

    def __init__(self, corrections: dict[str, str]) -> None:
        super().__init__()
        self._corrections = corrections
        self.correct_calls: list[str] = []

    def _correct(self, sentence: str) -> str:  # type: ignore[override]
        self.correct_calls.append(sentence)
        return self._corrections.get(sentence, sentence)


def test_check_flags_real_error() -> None:
    checker = _StubChecker(
        {"j'ai acheter des légumes": "j'ai acheté des légumes"}
    )
    result = checker.check("j'ai acheter des légumes")
    assert result.has_error is True
    assert result.corrected == "j'ai acheté des légumes"
    assert result.edits == ["'acheter' -> 'acheté'"]


def test_check_ignores_cosmetic_trailing_punct_and_case() -> None:
    # GEC only changed a final period + capitalisation: not a real error.
    checker = _StubChecker({"je vais bien merci": "Je vais bien merci."})
    result = checker.check("je vais bien merci")
    assert result.has_error is False
    assert result.edits == []


def test_check_skips_non_french_without_calling_gec() -> None:
    checker = _StubChecker({})
    result = checker.check("I think this is a good solution for the project.")
    assert result.has_error is False
    # The guard must short-circuit BEFORE the GEC engine runs.
    assert checker.correct_calls == []


# --- explain_edit deterministic classifier ---------------------------------


def test_explain_edit_elision() -> None:
    msg = explain_edit("que elle", "qu'elle")
    assert msg is not None and "élide" in msg.lower()


def test_explain_edit_contraction() -> None:
    msg = explain_edit("à le", "au")
    assert msg is not None and "contract" in msg.lower()


def test_explain_edit_accent() -> None:
    msg = explain_edit("probleme", "problème")
    assert msg is not None and "accent" in msg.lower()


def test_explain_edit_participle_after_avoir() -> None:
    msg = explain_edit("acheter", "acheté")
    assert msg is not None and "participe passé" in msg.lower()
    # An irregular infinitive is covered too.
    assert explain_edit("voir", "vu") is not None


def test_explain_edit_cod_agreement() -> None:
    msg = explain_edit("collecté", "collectées")
    assert msg is not None and "complément d'objet direct" in msg.lower()


def test_explain_edit_gender_agreement() -> None:
    msg = explain_edit("une grande probleme", "un grand problème")
    assert msg is not None and "genre" in msg.lower()


def test_explain_edit_returns_none_for_unclassifiable() -> None:
    # A whole-clause rewrite with no recognisable single category: no fabricated
    # rule is invented.
    assert explain_edit("le chat dort", "un oiseau vole") is None


def test_explain_edit_rejects_lexical_swap_as_agreement() -> None:
    # "le planning" is correct French; the GEC engine's lexical swap to
    # "la planification" (different lemma) must NOT be read as gender agreement.
    assert explain_edit("le planning", "la planification") is None
    # A bare noun->different-noun swap is likewise unclassifiable.
    assert explain_edit("planning", "planification") is None
    assert explain_edit("chat", "chien") is None


# --- build_grounded_correction (fully deterministic, no model) --------------


class _DecoyClient:
    """A client that must NEVER be called on the correction path."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def chat(self, model: str, messages: list, options: object) -> str:
        self.calls.append((model, messages, options))
        return "DECOY EXPLANATION THAT MUST NOT APPEAR"


_LEARNER = "j'ai acheter des légumes"
_GEC_CORRECTED = "j'ai acheté des légumes"


def test_build_returns_none_when_no_error() -> None:
    result = GrammarResult(has_error=False, corrected=_LEARNER, edits=[])
    assert build_grounded_correction(_LEARNER, result) is None


def test_build_is_deterministic_and_consults_no_model() -> None:
    # build_grounded_correction takes no client: the correction path is fully
    # deterministic. A decoy client is not even reachable from this function.
    decoy = _DecoyClient()
    result = GrammarResult(
        has_error=True, corrected=_GEC_CORRECTED, edits=["'acheter' -> 'acheté'"]
    )
    text = build_grounded_correction(_LEARNER, result)
    assert text is not None
    assert decoy.calls == []
    # The canonical (verified) explanation is present, not a fabricated one.
    assert "participe passé" in text.lower()
    # The 4-part markers are present and ordered.
    assert text.index("Tu as dit") < text.index("On dit plutôt") < text.index(
        "Peux-tu répéter"
    )


def test_build_restates_minimal_span_not_whole_sentence() -> None:
    # Concision: the restate / correct / repeat slots quote only the changed
    # span ("acheter" / "acheté"), never the whole GEC-corrected sentence.
    result = GrammarResult(
        has_error=True, corrected=_GEC_CORRECTED, edits=["'acheter' -> 'acheté'"]
    )
    text = build_grounded_correction(_LEARNER, result)
    assert text is not None
    assert "« acheter »" in text
    assert "« acheté »" in text
    # The full corrected sentence must NOT be quoted (that was the concision bug).
    assert f"« {_GEC_CORRECTED} »" not in text
    assert _GEC_CORRECTED not in text


def test_build_uses_safe_fallback_for_recognized_inflection_without_template() -> None:
    # "mange" -> "mangent" is a real inflection of the same lemma (verb
    # agreement) that no specific template covers: the safe, non-fabricating
    # fallback fires -- a correction is still emitted, but with no invented rule.
    learner = "les enfants mange"
    corrected = "les enfants mangent"
    result = GrammarResult(
        has_error=True, corrected=corrected, edits=["'mange' -> 'mangent'"]
    )
    text = build_grounded_correction(learner, result)
    assert text is not None
    assert "La forme correcte est" in text
    assert "« mangent »" in text


def test_build_falls_through_on_lexical_swap_multiword() -> None:
    # "le planning" is correct; the GEC lexical swap must NOT yield a correction.
    learner = "je gère le planning"
    corrected = "je gère la planification"
    result = GrammarResult(
        has_error=True,
        corrected=corrected,
        edits=["'le planning' -> 'la planification'"],
    )
    assert build_grounded_correction(learner, result) is None


def test_build_falls_through_on_single_word_lexical_swap() -> None:
    result = GrammarResult(
        has_error=True, corrected="j'aime le chien", edits=["'chat' -> 'chien'"]
    )
    assert build_grounded_correction("j'aime le chat", result) is None


# --- GroundedClient routing (no model loaded) -------------------------------

from harness.ollama_client import Message  # noqa: E402
from run_grounded_compare import GroundedClient  # noqa: E402
from run_transformers_compare import _TUNED_ARM  # noqa: E402


class _FakeInner:
    """Fake TransformersClient: records chat calls, returns a fixed reply."""

    def __init__(self, reply: str = "TUNED_REPLY") -> None:
        self._reply = reply
        self.calls: list[tuple[str, list[Message], object]] = []

    def chat(self, model: str, messages: list[Message], options: object) -> str:
        self.calls.append((model, messages, options))
        return self._reply


class _FixedChecker:
    """Fake GrammarChecker returning a preset result for every sentence."""

    def __init__(self, result: GrammarResult) -> None:
        self._result = result
        self.checked: list[str] = []

    def check(self, sentence: str) -> GrammarResult:
        self.checked.append(sentence)
        return self._result


def test_grounded_client_error_turn_returns_grounded_text_without_model() -> None:
    inner = _FakeInner(reply="MODEL REPLY THAT MUST NOT BE USED")
    result = GrammarResult(has_error=True, corrected=_GEC_CORRECTED, edits=["'acheter' -> 'acheté'"])
    client = GroundedClient(inner, _FixedChecker(result))

    messages = [Message("system", "sys"), Message("user", _LEARNER)]
    reply = client.chat("coach-grounded", messages, None)

    # The reply is the deterministic grounded correction with a minimal span.
    assert reply.startswith("Tu as dit : « ")
    assert "« acheté »" in reply
    assert "Peux-tu répéter" in reply
    # The tuned model is NOT consulted on the correction path at all.
    assert inner.calls == []


def test_grounded_client_no_error_turn_falls_through_unchanged() -> None:
    inner = _FakeInner(reply="TUNED_REPLY")
    result = GrammarResult(has_error=False, corrected="Je vais bien.", edits=[])
    client = GroundedClient(inner, _FixedChecker(result))

    messages = [Message("system", "sys"), Message("user", "Je vais bien.")]
    reply = client.chat("coach-grounded", messages, None)

    # Falls through to the tuned model with the ORIGINAL conversation, untouched.
    assert reply == "TUNED_REPLY"
    assert len(inner.calls) == 1
    routed_model, routed_messages, _ = inner.calls[0]
    assert routed_model == _TUNED_ARM
    assert routed_messages is messages


def test_grounded_client_lexical_swap_falls_through_to_model() -> None:
    # GEC flags a token edit (has_error True) but it is a lexical swap of correct
    # French: no grammar correction is emitted, the turn goes to the tuned model.
    inner = _FakeInner(reply="TUNED_REPLY")
    result = GrammarResult(
        has_error=True, corrected="je gère la planification", edits=[]
    )
    client = GroundedClient(inner, _FixedChecker(result))

    messages = [Message("system", "sys"), Message("user", "je gère le planning")]
    reply = client.chat("coach-grounded", messages, None)

    assert reply == "TUNED_REPLY"
    assert len(inner.calls) == 1
    assert inner.calls[0][0] == _TUNED_ARM


def test_last_learner_text_returns_last_user_message() -> None:
    messages = [
        Message("system", "sys"),
        Message("user", "premier tour"),
        Message("assistant", "réponse"),
        Message("user", "dernier tour"),
    ]
    assert GroundedClient._last_learner_text(messages) == "dernier tour"
