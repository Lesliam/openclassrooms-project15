"""Deterministic scorers for the evaluation harness.

Only cheap, reproducible string/regex/language-ID checks live here. The
structural 4-part ordered check and false-positive semantic check are the
LLM-judge's job (see ``judge.py``); these scorers provide the deterministic
pre-checks described in eval_set_v0 sections 1 and 2.

Determinism note: ``langdetect`` is seeded at import so per-sentence language
IDs are stable across runs.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from langdetect import DetectorFactory, LangDetectException, detect

from . import constants

DetectorFactory.seed = constants.LANGDETECT_SEED

# --- Markers (compiled once) -----------------------------------------------

# Restatement marker: the prompt's canonical opener "Tu as dit".
_RESTATEMENT_MARKER = re.compile(r"tu\s+as\s+dit", re.IGNORECASE)
# Corrected-version marker: the prompt's canonical "On dit plutot".
_CORRECTION_MARKER = re.compile(r"on\s+dit\s+plut", re.IGNORECASE)
# Repeat request: several natural phrasings of "please repeat". The vowel
# classes cover accents (repete / répète / répéter / repète).
_REPEAT_MARKER = re.compile(r"r[éeè]p[éeè]t|redis|redites|reprends", re.IGNORECASE)
# Quoted spans in guillemets or straight double quotes.
_QUOTED_SPAN = re.compile("[«\"]([^«»\"]+)[»\"]")
# Sentence terminators for the simple splitter.
_SENTENCE_SPLIT = re.compile("[.!?…]+")
# Word tokens (letters incl. accents and digits).
_WORD = re.compile(r"[0-9A-Za-zÀ-ÿ]+")
# CJK codepoint ranges: Hiragana/Katakana, CJK ext A, unified ideographs,
# compatibility ideographs, half-width Katakana. Any hit is a hard D2 fail.
_CJK = re.compile(
    "[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]"
)


def split_sentences(text: str) -> list[str]:
    """Split text into non-empty, stripped sentences (simple French splitter)."""
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def count_sentences(text: str) -> int:
    """Number of sentences in a reply (brevity metric)."""
    return len(split_sentences(text))


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _quoted_spans(text: str) -> list[str]:
    return [m.group(1).strip() for m in _QUOTED_SPAN.finditer(text)]


def _token_overlap(span: str, reference: str) -> float:
    """Fraction of reference tokens that also appear in ``span``."""
    ref_tokens = set(_tokens(reference))
    if not ref_tokens:
        return 0.0
    span_tokens = set(_tokens(span))
    return len(ref_tokens & span_tokens) / len(ref_tokens)


def has_cjk(text: str) -> bool:
    """True if the text contains any CJK codepoint (hard D2 fail)."""
    return _CJK.search(text) is not None


# --- D1: correction-format deterministic pre-check --------------------------


@dataclass(frozen=True)
class D1Score:
    """Deterministic D1 markers for one reply."""

    has_restatement: bool
    has_correction: bool
    has_repeat_request: bool
    within_length: bool
    sentence_count: int
    # True only when all four deterministic markers are present.
    deterministic_compliant: bool

    def to_dict(self) -> dict:
        return asdict(self)


def score_d1(reply: str, learner_text: str, brevity_max: int) -> D1Score:
    """Deterministic pre-check for the 4-part correction format."""
    quoted = _quoted_spans(reply)
    overlap_hit = any(
        _token_overlap(span, learner_text) >= constants.D1_RESTATEMENT_OVERLAP_THRESHOLD
        for span in quoted
    )
    has_restatement = bool(_RESTATEMENT_MARKER.search(reply)) or overlap_hit
    # A correction is present if the explicit marker appears, or if there are
    # at least two distinct quoted spans (restated vs corrected).
    has_correction = bool(_CORRECTION_MARKER.search(reply)) or len(set(quoted)) >= 2
    has_repeat_request = bool(_REPEAT_MARKER.search(reply))
    sentence_count = count_sentences(reply)
    within_length = sentence_count <= brevity_max
    deterministic_compliant = (
        has_restatement and has_correction and has_repeat_request and within_length
    )
    return D1Score(
        has_restatement=has_restatement,
        has_correction=has_correction,
        has_repeat_request=has_repeat_request,
        within_length=within_length,
        sentence_count=sentence_count,
        deterministic_compliant=deterministic_compliant,
    )


def d1_correction_emitted(reply: str, learner_text: str) -> bool:
    """Whether the reply appears to emit a correction (for false-positive check)."""
    quoted = _quoted_spans(reply)
    overlap_hit = any(
        _token_overlap(span, learner_text) >= constants.D1_RESTATEMENT_OVERLAP_THRESHOLD
        for span in quoted
    )
    restatement = bool(_RESTATEMENT_MARKER.search(reply)) or overlap_hit
    correction = bool(_CORRECTION_MARKER.search(reply))
    return restatement and correction


# --- D2: French-persistence deterministic check -----------------------------


@dataclass(frozen=True)
class D2Score:
    """Deterministic D2 language check for one reply."""

    passes: bool
    has_cjk: bool
    french_sentence_count: int
    total_sentence_count: int
    french_token_fraction: float
    # Sentences whose detected language was not French (for audit).
    non_french_sentences: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _detect_lang(sentence: str) -> str:
    try:
        return detect(sentence)
    except LangDetectException:
        return "unknown"


def score_d2(reply: str) -> D2Score:
    """Deterministic French-persistence check with a soft token fraction."""
    cjk = has_cjk(reply)
    sentences = split_sentences(reply)
    total = len(sentences)
    french_sentences = 0
    non_french: list[str] = []
    french_tokens = 0
    total_tokens = 0
    for sentence in sentences:
        n_tokens = len(_tokens(sentence))
        total_tokens += n_tokens
        if _detect_lang(sentence) == constants.FRENCH_LANG_CODE:
            french_sentences += 1
            french_tokens += n_tokens
        else:
            non_french.append(sentence)
    fraction = (french_tokens / total_tokens) if total_tokens else 0.0
    # Pass requires: no CJK, at least one sentence, and every sentence French.
    passes = (not cjk) and total > 0 and french_sentences == total
    return D2Score(
        passes=passes,
        has_cjk=cjk,
        french_sentence_count=french_sentences,
        total_sentence_count=total,
        french_token_fraction=round(fraction, 4),
        non_french_sentences=tuple(non_french),
    )
