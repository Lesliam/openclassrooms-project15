"""Grammar-grounding correctness layer for the French conversation coach.

Why this module exists
----------------------
Fine-tuning improved the coach's *behaviour* (the 4-part correction format and
French persistence) but not the *correctness* of its grammar explanations: an
automated judge model found only a minority of the coach's corrections carried
a grammatically-valid explanation, because the model fabricates rules from its
own memory (e.g. calling a present-tense verb a "participe passe"). This layer
grounds the FACTUAL part of a correction -- the corrected sentence itself -- in
an authoritative local grammar-error-correction (GEC) engine, so the coach
model is only ever asked to *explain* a change that is already known to be
correct, never to invent the correction.

Backend
-------
The GEC engine is ``PoloHuggingface/French_grammar_error_corrector``, a
``T5ForConditionalGeneration`` fine-tune. It takes a raw French sentence and
returns the corrected sentence (no task prefix required). It runs fully local
on CPU so it never contends with the coach model for the GPU, and learner text
never leaves the machine.

Known limitation (GEC-engine detection boundary)
------------------------------------------------
The residual correctness gaps are in the GEC engine's DETECTION, not in the
explanation templates. The engine over-detects some lexical swaps (it rewrites
the already-correct "le planning" to "la planification"); those are suppressed
here by the classifiable-only precision gate, which corrects only edits that
map to a real grammar rule. It also under-detects errors it was not trained on
(e.g. "plus meilleure", "si j'aurais"), which pass through uncorrected. A
stronger grammar engine would close these; this is a documented boundary, not a
template defect.

Security -- safetensors-only weights
------------------------------------
The upstream checkpoint ships its weights as a pickle (``pytorch_model.bin``);
no safetensors file exists upstream. That pickle was opcode-scanned before use:
it references only ``collections.OrderedDict``, ``torch.FloatStorage`` and
``torch._utils._rebuild_tensor_v2`` -- a benign tensor state_dict with no
``os`` / ``subprocess`` / ``eval`` / ``socket`` opcodes, i.e. no code-execution
vector. On first use this module loads that verified checkpoint ONCE (a plain
load, since no upstream safetensors exists to force) and re-serialises it as
``safetensors`` into a local cache directory *outside* the repository
(``~/dev/coach-sft/models/fr-gec-safetensors`` by default). Every subsequent
load reads only that safetensors copy (``use_safetensors=True``), so no pickle
is deserialised on the runtime path. Model weights are never committed to the
repository.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from langdetect import DetectorFactory, LangDetectException, detect

# --- Determinism ------------------------------------------------------------

# Seed langdetect so the French-only guard yields stable decisions across runs
# (mirrors the harness scorers' determinism note).
LANGDETECT_SEED = 42
DetectorFactory.seed = LANGDETECT_SEED

# --- Constants (no magic numbers) -------------------------------------------

GEC_MODEL_ID = "PoloHuggingface/French_grammar_error_corrector"
DEFAULT_SAFETENSORS_DIR = Path.home() / "dev" / "coach-sft" / "models" / "fr-gec-safetensors"
_SAFETENSORS_MARKER = "model.safetensors"

GEC_MAX_NEW_TOKENS = 256
GEC_NUM_BEAMS = 4

# Word tokens: letters (incl. French accents) and digits, keeping apostrophes
# and hyphens that sit BETWEEN word characters as part of the token (so
# "qu'il", "aujourd'hui", "peux-tu", "c'est" are single tokens). This single
# token stream drives BOTH ``has_error`` and ``edits`` so the two can never
# disagree: an elision or hyphenation change (e.g. "aujourd hui" ->
# "aujourd'hui", "peux tu" -> "peux-tu") shows up as a real word edit, and a
# leading/trailing or non-joining punctuation change (a final period, an added
# comma) touches no token and is therefore not flagged.
_WORD = re.compile(r"[0-9A-Za-zÀ-ÿ]+(?:['’\-][0-9A-Za-zÀ-ÿ]+)*")
# CJK codepoint ranges (kana, CJK ext A, unified/compatibility ideographs,
# half-width katakana). Any hit means the input is not French.
_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")
# langdetect labels that are unambiguously not French. langdetect misclassifies
# short French as Dutch/Italian, so only English is blocklisted here; CJK is
# handled separately by codepoint.
_NON_FRENCH_LABELS = frozenset({"en"})


# --- Data types -------------------------------------------------------------


@dataclass(frozen=True)
class GrammarResult:
    """Outcome of a single grammar check.

    Attributes:
        has_error: True when the GEC correction differs from the input beyond
            cosmetic trailing punctuation / capitalisation.
        corrected: The authoritative corrected sentence from the GEC engine
            (equal to the input, trimmed, when ``has_error`` is False).
        edits: Human-readable token-level word changes, e.g.
            ``"'acheter' -> 'acheté'"``. Empty when there is no word change.
    """

    has_error: bool
    corrected: str
    edits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --- Language guard ---------------------------------------------------------


def has_cjk(text: str) -> bool:
    """True if the text contains any CJK codepoint."""
    return _CJK.search(text) is not None


def looks_french(text: str) -> bool:
    """Heuristic guard: True unless the text is clearly English or CJK.

    The GEC engine is French-only, so it must not run on the eval's
    language-switch (D2) turns. langdetect is unreliable on short French
    (it often reports Dutch/Italian), so the guard is deliberately permissive:
    it skips only inputs that are clearly CJK or confidently English, and lets
    everything else through -- the GEC engine is a no-op on already-correct
    French anyway.

    Residual (accepted, low risk): a very short, cognate-heavy French error that
    langdetect confidently labels ``en`` would be skipped and left uncorrected.
    """
    stripped = text.strip()
    if not stripped or has_cjk(stripped):
        return False
    try:
        return detect(stripped) not in _NON_FRENCH_LABELS
    except LangDetectException:
        return False


# --- Diff helpers -----------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lower-cased word tokens (apostrophes/hyphens kept inside words)."""
    return _WORD.findall(text.lower())


def word_edits(original: str, corrected: str) -> list[tuple[str, str]]:
    """Structured token-level diff as ``(old_span, new_span)`` pairs.

    Each pair is a minimal changed phrase: the joined old tokens and the joined
    new tokens of one non-equal diff block. An insertion shows an empty old
    span, a deletion an empty new span. Returns an empty list when the two
    sentences share the same word tokens (e.g. a punctuation-only change).
    """
    old_tokens = _tokenize(original)
    new_tokens = _tokenize(corrected)
    edits: list[tuple[str, str]] = []
    matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        edits.append((" ".join(old_tokens[i1:i2]), " ".join(new_tokens[j1:j2])))
    return edits


def word_diff(original: str, corrected: str) -> list[str]:
    """Human-readable form of :func:`word_edits`: ``"'<old>' -> '<new>'"``."""
    return [f"'{old}' -> '{new}'" for old, new in word_edits(original, corrected)]


# --- Grammar checker --------------------------------------------------------


class GrammarChecker:
    """Local French grammar-error-correction checker.

    Loads the GEC model lazily from a local safetensors copy, converting the
    upstream checkpoint once on first use. Instantiation is cheap; the weights
    are only touched on the first ``check`` call.
    """

    def __init__(
        self,
        model_id: str = GEC_MODEL_ID,
        safetensors_dir: Path = DEFAULT_SAFETENSORS_DIR,
        device: str = "cpu",
    ) -> None:
        self._model_id = model_id
        self._safetensors_dir = Path(safetensors_dir)
        self._device = device
        self._tokenizer = None
        self._model = None

    # -- model loading --

    def _prepare_safetensors(self) -> None:
        """Ensure a local safetensors copy of the checkpoint exists.

        On first use, load the upstream checkpoint once and re-save it as
        safetensors into ``self._safetensors_dir`` (outside the repo). Later
        runs find the marker file and skip the conversion.
        """
        marker = self._safetensors_dir / _SAFETENSORS_MARKER
        if marker.exists():
            return
        from transformers import AutoTokenizer, T5ForConditionalGeneration

        self._safetensors_dir.mkdir(parents=True, exist_ok=True)
        tokenizer = AutoTokenizer.from_pretrained(self._model_id)
        # One-time pickle load: upstream ships ONLY pytorch_model.bin, so
        # ``use_safetensors=True`` is deliberately NOT set here (it would fail).
        # That pickle was opcode-scanned and references only OrderedDict /
        # torch.FloatStorage / torch._utils._rebuild_tensor_v2 (a benign tensor
        # state_dict, no code-execution opcodes). We immediately re-serialise it
        # as safetensors; every later load (``_ensure_loaded``) is safetensors.
        model = T5ForConditionalGeneration.from_pretrained(self._model_id)
        model.save_pretrained(self._safetensors_dir, safe_serialization=True)
        tokenizer.save_pretrained(self._safetensors_dir)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoTokenizer, T5ForConditionalGeneration

        self._prepare_safetensors()
        self._tokenizer = AutoTokenizer.from_pretrained(self._safetensors_dir)
        self._model = T5ForConditionalGeneration.from_pretrained(
            self._safetensors_dir, use_safetensors=True
        )
        self._model.to(self._device)
        self._model.eval()

    def _correct(self, sentence: str) -> str:
        """Run the GEC engine deterministically and return the corrected text."""
        import torch

        self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None
        encoded = self._tokenizer(sentence, return_tensors="pt").to(self._device)
        with torch.no_grad():
            generated = self._model.generate(
                **encoded,
                max_new_tokens=GEC_MAX_NEW_TOKENS,
                num_beams=GEC_NUM_BEAMS,
                do_sample=False,
            )
        return self._tokenizer.decode(generated[0], skip_special_tokens=True).strip()

    # -- public API --

    def check(self, sentence: str) -> GrammarResult:
        """Check one sentence and return its grounded correction result.

        Non-French input (English or CJK) is skipped and returned as error-free,
        so the caller falls through to the normal coach path for D2
        language-switch turns.
        """
        text = sentence.strip()
        if not looks_french(text):
            return GrammarResult(has_error=False, corrected=text, edits=[])
        corrected = self._correct(text)
        # ``has_error`` is defined AS "there is at least one word-token edit", so
        # it and ``edits`` are computed from the same token stream and can never
        # disagree (no empty-change-line correction bubbles).
        edits = word_diff(text, corrected)
        return GrammarResult(has_error=bool(edits), corrected=corrected, edits=edits)


# --- Deterministic explanation engine ---------------------------------------
#
# The corrected FORM is authoritative (from the GEC engine); the EXPLANATION is
# derived here by rule, NOT free-written by any model. A model handed the right
# form still fabricates the grammar rule, so the explanation is classified
# deterministically from the word-diff and returned as canonical, verified
# French. An edit that cannot be confidently classified yields no explanation
# (``None``); the caller then states the change without inventing a reason.

# Words that elide their final vowel before a vowel or mute h, mapped to their
# elided prefix (e.g. "que" -> "qu'").
_ELIDABLE = {
    "que": "qu",
    "ce": "c",
    "de": "d",
    "je": "j",
    "le": "l",
    "la": "l",
    "se": "s",
    "ne": "n",
    "me": "m",
    "te": "t",
    "si": "s",
}
# Valid elided prefixes (the part before the apostrophe in the corrected form).
_ELIDED_PREFIXES = frozenset(_ELIDABLE.values())

# Preposition + definite article contractions.
_CONTRACTIONS = {
    "à le": "au",
    "a le": "au",
    "à les": "aux",
    "a les": "aux",
    "de le": "du",
    "de les": "des",
}

# Irregular infinitive -> past participle pairs seen in French coaching text.
_IRREGULAR_PARTICIPLES = {
    "voir": "vu",
    "avoir": "eu",
    "être": "été",
    "faire": "fait",
    "prendre": "pris",
    "mettre": "mis",
    "dire": "dit",
    "écrire": "écrit",
    "lire": "lu",
    "boire": "bu",
    "devoir": "dû",
    "pouvoir": "pu",
    "vouloir": "voulu",
    "savoir": "su",
    "venir": "venu",
    "tenir": "tenu",
}
# Regular infinitive endings mapped to their participle vowel.
_REGULAR_INFINITIVE_ENDINGS = (("er", "é"), ("ir", "i"), ("re", "u"))
# Agreement suffixes appended to a participle or adjective (feminine / plural).
_AGREEMENT_SUFFIXES = frozenset({"e", "s", "es"})
# Endings that mark a word as a past participle (for the COD-agreement rule).
_PARTICIPLE_ENDINGS = ("é", "i", "u", "t", "s")
# Feminine / masculine determiner pairs, for gender-agreement detection.
_DETERMINER_PAIRS = (
    ("une", "un"),
    ("la", "le"),
    ("cette", "ce"),
    ("ma", "mon"),
    ("ta", "ton"),
    ("sa", "son"),
)
# All determiner forms, stripped before the content-word lemma comparison.
_DETERMINERS = frozenset(form for pair in _DETERMINER_PAIRS for form in pair)
# Max trailing-character delta for two words to count as the same lemma (an
# inflectional change like "grande" -> "grand"), NOT a lexical swap like
# "planning" -> "planification".
_MAX_INFLECTION_DELTA = 3

# Canonical, grammatically-verified explanation sentences.
_MSG_ELISION = (
    "Devant une voyelle ou un h muet, on élide la voyelle finale et on met une "
    "apostrophe."
)
_MSG_CONTRACTION = "La préposition et l'article défini se contractent en « {new} »."
_MSG_ACCENT = "Ce mot porte un accent : il s'écrit « {new} »."
_MSG_PARTICIPLE_AVOIR = (
    "Après l'auxiliaire « avoir », on emploie le participe passé « {new} », "
    "pas l'infinitif."
)
_MSG_COD_AGREEMENT = (
    "Le participe passé s'accorde en genre et en nombre avec le complément "
    "d'objet direct placé avant."
)
_MSG_ADJ_AGREEMENT = "Ce mot s'accorde en genre et en nombre avec le nom."
_MSG_GENDER_AGREEMENT = "L'article et l'adjectif s'accordent en genre avec le nom."
_SAFE_FALLBACK = "La forme correcte est « {new} »."


def _strip_accents(text: str) -> str:
    """Return ``text`` with combining diacritical marks removed."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _is_elision(old_span: str, new_span: str) -> bool:
    if "'" not in new_span and "’" not in new_span:
        return False
    prefix = re.split("['’]", new_span, maxsplit=1)[0].lower()
    if prefix not in _ELIDED_PREFIXES:
        return False
    old_first = (old_span.split() or [""])[0].lower()
    # Either the learner wrote the full word ("que" -> "qu'") or dropped the
    # apostrophe of an already-elided form ("c est" -> "c'est").
    return old_first == prefix or _ELIDABLE.get(old_first) == prefix


def _infinitive_to_participle(word: str) -> Optional[str]:
    if word in _IRREGULAR_PARTICIPLES:
        return _IRREGULAR_PARTICIPLES[word]
    for ending, participle_vowel in _REGULAR_INFINITIVE_ENDINGS:
        if word.endswith(ending):
            return word[: -len(ending)] + participle_vowel
    return None


def _agreement_suffix(old_word: str, new_word: str) -> Optional[str]:
    """Return the added agreement suffix if ``new_word`` == ``old_word`` + suffix."""
    if new_word != old_word and new_word.startswith(old_word):
        suffix = new_word[len(old_word):]
        if suffix in _AGREEMENT_SUFFIXES:
            return suffix
    return None


def _has_determiner_flip(old_tokens: list[str], new_tokens: list[str]) -> bool:
    old_set, new_set = set(old_tokens), set(new_tokens)
    for feminine, masculine in _DETERMINER_PAIRS:
        if (feminine in old_set and masculine in new_set) or (
            masculine in old_set and feminine in new_set
        ):
            return True
    return False


def _same_lemma(first: str, second: str) -> bool:
    """True if two words are the same lemma up to an inflectional suffix.

    Accent-insensitive. Two words match when they are equal ignoring accents,
    or when the shorter is a prefix of the longer with only a short suffix delta
    (e.g. "grand"/"grande"). A lexical swap of unrelated words ("planning" vs
    "planification") is NOT a lemma match, so it never counts as an inflection.
    """
    first_n, second_n = _strip_accents(first.lower()), _strip_accents(second.lower())
    if first_n == second_n:
        return True
    shorter, longer = sorted((first_n, second_n), key=len)
    return (
        longer.startswith(shorter)
        and (len(longer) - len(shorter)) <= _MAX_INFLECTION_DELTA
    )


def _is_gender_agreement(old_tokens: list[str], new_tokens: list[str]) -> bool:
    """True only for a real determiner/adjective gender-agreement inflection.

    Requires a determiner gender flip AND that every remaining content word is
    an inflection of its counterpart (same lemma). This rejects a determiner
    flip that accompanies a lexical noun swap (e.g. "le planning" ->
    "la planification"), which is a vocabulary substitution, not a grammar rule.
    """
    if not _has_determiner_flip(old_tokens, new_tokens):
        return False
    old_content = [tok for tok in old_tokens if tok not in _DETERMINERS]
    new_content = [tok for tok in new_tokens if tok not in _DETERMINERS]
    if not old_content or len(old_content) != len(new_content):
        return False
    return all(_same_lemma(a, b) for a, b in zip(old_content, new_content))


def explain_edit(old_span: str, new_span: str) -> Optional[str]:
    """Classify one ``(old_span, new_span)`` word edit into a French grammar rule.

    Returns a canonical, grammatically-correct one-sentence French explanation
    for the recognised category, or ``None`` when the edit cannot be classified
    with confidence (so no rule is ever fabricated). Categories covered:
    elision, preposition+article contraction, accent orthography, past
    participle after ``avoir``, past-participle agreement with a preceding
    direct object, adjective/noun agreement, and determiner gender agreement.
    """
    old = old_span.strip()
    new = new_span.strip()
    if not new:
        return None
    old_l, new_l = old.lower(), new.lower()

    if old_l in _CONTRACTIONS and _CONTRACTIONS[old_l] == new_l:
        return _MSG_CONTRACTION.format(new=new)

    if _is_elision(old, new):
        return _MSG_ELISION

    if old_l != new_l and _strip_accents(old_l) == _strip_accents(new_l):
        return _MSG_ACCENT.format(new=new)

    old_tokens, new_tokens = old_l.split(), new_l.split()

    if len(old_tokens) == 1 and len(new_tokens) == 1:
        participle = _infinitive_to_participle(old_l)
        if participle is not None and (
            new_l == participle
            or new_l in {participle + suffix for suffix in _AGREEMENT_SUFFIXES}
        ):
            return _MSG_PARTICIPLE_AVOIR.format(new=new)
        if _agreement_suffix(old_l, new_l) is not None:
            if old_l.endswith(_PARTICIPLE_ENDINGS):
                return _MSG_COD_AGREEMENT
            return _MSG_ADJ_AGREEMENT

    if _is_gender_agreement(old_tokens, new_tokens):
        return _MSG_GENDER_AGREEMENT

    return None


def _is_grammar_edit(old_span: str, new_span: str) -> bool:
    """True if the edit is a genuine grammar change, not a lexical/cosmetic one.

    An edit qualifies when :func:`explain_edit` classifies it, OR when it is a
    single-word inflection of the same lemma that a recognised class covers but
    for which no specific template is defined (verb-agreement suffixes beyond
    feminine/plural, etc.). A whole-word lexical substitution of a different
    lemma (``planning`` -> ``planification``) is NOT a grammar edit, so the
    caller can fall through instead of "correcting" already-correct French.
    """
    if explain_edit(old_span, new_span) is not None:
        return True
    old_l, new_l = old_span.strip().lower(), new_span.strip().lower()
    if not old_l or not new_l:
        return False
    old_tokens, new_tokens = old_l.split(), new_l.split()
    if len(old_tokens) == 1 and len(new_tokens) == 1:
        return _same_lemma(old_l, new_l)
    return False


# --- Grounded correction assembly -------------------------------------------


def _select_primary_edit(edits: list[tuple[str, str]]) -> tuple[str, str]:
    """Pick the most salient edit: prefer a classifiable one with a non-empty old
    span, breaking ties by the longest corrected span."""
    classifiable = [edit for edit in edits if explain_edit(*edit) is not None]
    pool = classifiable or edits
    with_old = [edit for edit in pool if edit[0]] or pool
    return max(with_old, key=lambda edit: len(edit[1]))


def build_grounded_correction(
    learner_text: str,
    gec_result: GrammarResult,
) -> Optional[str]:
    """Assemble the concise 4-part coach correction, fully deterministically.

    Both the corrected FORM and the EXPLANATION are grounded: the form comes
    from the GEC engine and the explanation from :func:`explain_edit`. No model
    is consulted on this path. Concision is achieved by restating only the
    minimal changed span (not the whole sentence) in the restate / correct /
    repeat slots, keeping the standard 4-sentence correcting shape.

    Precision gate: a correction is emitted ONLY when at least one edit is a
    genuine, classifiable grammar change. If the GEC engine's edits are ALL
    lexical swaps or cosmetic (e.g. the correct "le planning" rewritten to
    "la planification"), this returns ``None`` so the caller falls through to
    the normal path -- the coach never tells a grammatically-correct learner
    they were wrong. Also returns ``None`` when ``gec_result.has_error`` is
    False or no word edit is found.
    """
    if not gec_result.has_error:
        return None
    edits = word_edits(learner_text, gec_result.corrected)
    grammar_edits = [edit for edit in edits if _is_grammar_edit(*edit)]
    if not grammar_edits:
        return None
    old_span, new_span = _select_primary_edit(grammar_edits)
    explanation = explain_edit(old_span, new_span) or _SAFE_FALLBACK.format(new=new_span)
    restate = old_span if old_span else learner_text
    return (
        f"Tu as dit : « {restate} ». "
        f"On dit plutôt : « {new_span} ». "
        f"{explanation} "
        f"Peux-tu répéter : « {new_span} » ?"
    )
