"""Independent validation tests for the coach SFT corpus + config (CS-155).

Audits the shipped artifacts under ``ml/finetune/`` without training anything
(CPU only):

1. ``corpus/coach_sft.jsonl`` structure: every line is valid JSON with
   ``messages`` = [system, user, assistant] in that order; exactly one distinct
   system message, equal to the body (after ``---``) of
   ``server/coach_system_prompt_v0.md``.
2. Reply contract on every assistant turn: no CJK codepoints; correction
   replies (carrying the D1 markers) are <= 4 sentences, non-correction replies
   <= 3 sentences (the eval_set_v0 D1 / brevity rule).
3. Leakage (load-bearing, strict): zero exact overlaps between corpus user
   turns and the eval_set_v0 learner turns.
4. ``sft_config.yaml`` parses and carries the expected keys; ``train_on_inputs``
   is false and ``val_set_size`` > 0.

Artifacts are NOT modified. Any reply-contract violation is reported by row
index (see TEST_REPORT_CS155.md).

Note on sentence counting: eval_set_v0's scorers split on ``[.!?…]+``. That
naive splitter treats an intra-sentence ellipsis ("aussi... que") as a sentence
boundary and over-counts. These tests use the SAME terminator set and the SAME
brevity caps, but treat ``...`` / ``…`` as non-terminal ellipsis so the count
reflects true sentence structure. The divergence (and the one corpus row it
affects) is documented as a finding in TEST_REPORT_CS155.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

import check_leakage

# --- Artifact locations (relative to this test file) -----------------------

_FINETUNE_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _FINETUNE_DIR.parent.parent  # .../project15/project
_CORPUS_FILE = _FINETUNE_DIR / "corpus" / "coach_sft.jsonl"
_CONFIG_FILE = _FINETUNE_DIR / "sft_config.yaml"
_SYSTEM_PROMPT_FILE = _PROJECT_ROOT / "server" / "coach_system_prompt_v0.md"
_PROMPT_BODY_SEPARATOR = "\n---\n"

# --- Structural rules mirrored from eval_set_v0 D1 / brevity ---------------

_CJK = re.compile("[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")
_RESTATEMENT_MARKER = re.compile(r"tu\s+as\s+dit", re.IGNORECASE)
_CORRECTION_MARKER = re.compile(r"on\s+dit\s+plut", re.IGNORECASE)
_ELLIPSIS = re.compile(r"\.{2,}")  # ASCII "..." (2+ dots)
_SENTENCE_TERMINATORS = re.compile(r"[.!?]+")

_BREVITY_MAX_CORRECTING = 4
_BREVITY_MAX_DEFAULT = 3


def _count_sentences(text: str) -> int:
    """Sentence count using the eval terminator set, ellipsis-aware.

    ``...`` and ``…`` are treated as intra-sentence ellipsis (non-terminal) so a
    quoted "aussi... que" is one sentence, not three.
    """
    without_ellipsis = _ELLIPSIS.sub(" ", text).replace("…", " ")
    return len([p for p in _SENTENCE_TERMINATORS.split(without_ellipsis) if p.strip()])


def _naive_count_sentences(text: str) -> int:
    """The eval_set_v0 scorers' splitter verbatim (``[.!?…]+``), for the finding."""
    return len([p for p in re.split("[.!?…]+", text) if p.strip()])


def _is_correction_reply(text: str) -> bool:
    """A reply emits the correction format when both D1 markers are present."""
    return bool(_RESTATEMENT_MARKER.search(text)) and bool(
        _CORRECTION_MARKER.search(text)
    )


def _has_cjk(text: str) -> bool:
    return _CJK.search(text) is not None


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    lines = _CORPUS_FILE.read_text(encoding="utf-8").splitlines()
    parsed: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed.append(json.loads(stripped))
        except json.JSONDecodeError as exc:  # pragma: no cover - fails loudly
            raise AssertionError(f"line {index}: invalid JSON: {exc}") from exc
    return parsed


@pytest.fixture(scope="module")
def expected_system_prompt() -> str:
    raw = _SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    body = raw.split(_PROMPT_BODY_SEPARATOR, 1)[1] if _PROMPT_BODY_SEPARATOR in raw else raw
    return body.strip()


# --- 1. Structure -----------------------------------------------------------


def test_corpus_is_non_empty(rows: list[dict[str, Any]]) -> None:
    assert len(rows) > 0


def test_every_row_has_system_user_assistant_in_order(rows: list[dict[str, Any]]) -> None:
    bad: list[int] = []
    for index, row in enumerate(rows):
        messages = row.get("messages")
        if not isinstance(messages, list):
            bad.append(index)
            continue
        roles = [m.get("role") for m in messages]
        if roles != ["system", "user", "assistant"]:
            bad.append(index)
    assert not bad, f"rows with wrong role sequence: {bad}"


def test_message_contents_are_non_empty_strings(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        for msg in row["messages"]:
            assert isinstance(msg.get("content"), str) and msg["content"].strip(), (
                f"row {index}: empty/invalid content for role {msg.get('role')!r}"
            )


def test_exactly_one_distinct_system_message(rows: list[dict[str, Any]]) -> None:
    systems = {row["messages"][0]["content"] for row in rows}
    assert len(systems) == 1, f"expected 1 distinct system message, got {len(systems)}"


def test_system_message_equals_prompt_body(
    rows: list[dict[str, Any]], expected_system_prompt: str
) -> None:
    system_message = rows[0]["messages"][0]["content"]
    assert system_message == expected_system_prompt


# --- 2. Reply contract ------------------------------------------------------


def _assistant_turns(rows: list[dict[str, Any]]) -> list[tuple[int, str]]:
    turns: list[tuple[int, str]] = []
    for index, row in enumerate(rows):
        for msg in row["messages"]:
            if msg["role"] == "assistant":
                turns.append((index, msg["content"]))
    return turns


def test_no_cjk_in_any_assistant_turn(rows: list[dict[str, Any]]) -> None:
    offenders = [index for index, text in _assistant_turns(rows) if _has_cjk(text)]
    assert not offenders, f"rows with CJK in the assistant reply: {offenders}"


def test_correction_replies_within_four_sentences(rows: list[dict[str, Any]]) -> None:
    violations = [
        (index, _count_sentences(text))
        for index, text in _assistant_turns(rows)
        if _is_correction_reply(text)
        and _count_sentences(text) > _BREVITY_MAX_CORRECTING
    ]
    assert not violations, (
        f"correction replies exceeding {_BREVITY_MAX_CORRECTING} sentences "
        f"(row, count): {violations}"
    )


def test_non_correction_replies_within_three_sentences(rows: list[dict[str, Any]]) -> None:
    violations = [
        (index, _count_sentences(text))
        for index, text in _assistant_turns(rows)
        if not _is_correction_reply(text)
        and _count_sentences(text) > _BREVITY_MAX_DEFAULT
    ]
    assert not violations, (
        f"non-correction replies exceeding {_BREVITY_MAX_DEFAULT} sentences "
        f"(row, count): {violations}"
    )


def test_row_21_ellipsis_is_a_splitter_artifact_not_a_real_violation(
    rows: list[dict[str, Any]],
) -> None:
    # Documents finding F-CS155-1: the eval scorers' naive [.!?…]+ splitter
    # over-counts this compliant 4-sentence correction to 5 because of the
    # intra-quote ellipsis in « aussi... que ». The ellipsis-aware count is 4.
    if len(rows) <= 21:
        pytest.skip("corpus has fewer than 22 rows")
    reply = rows[21]["messages"][2]["content"]
    if "..." not in reply and "…" not in reply:
        pytest.skip("row 21 no longer contains an ellipsis")
    assert _is_correction_reply(reply)
    assert _naive_count_sentences(reply) == 5  # naive splitter over-counts
    assert _count_sentences(reply) == 4  # true (ellipsis-aware) sentence count
    assert _count_sentences(reply) <= _BREVITY_MAX_CORRECTING


# --- 3. Leakage (load-bearing) ---------------------------------------------


def test_zero_exact_leakage_between_corpus_and_eval() -> None:
    eval_turns = check_leakage.load_eval_turns()
    corpus_turns = check_leakage.load_corpus_user_turns()
    assert eval_turns, "no eval learner turns parsed (source-of-truth missing)"
    assert corpus_turns, "no corpus user turns loaded"

    eval_norm = {check_leakage.normalize(t) for t in eval_turns}
    overlaps = [c for c in corpus_turns if check_leakage.normalize(c) in eval_norm]
    assert overlaps == [], f"train/test leakage: corpus reuses eval turns: {overlaps}"


def test_zero_raw_exact_leakage_independent_of_shipped_normalizer() -> None:
    # Independent, stricter check: no corpus user turn equals an eval learner
    # turn after only whitespace/case normalization (punctuation preserved).
    def norm_raw(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    eval_turns = {norm_raw(t) for t in check_leakage.load_eval_turns()}
    corpus_turns = [norm_raw(c) for c in check_leakage.load_corpus_user_turns()]
    overlaps = [c for c in corpus_turns if c in eval_turns]
    assert overlaps == [], f"raw exact leakage detected: {overlaps}"


def test_check_leakage_main_reports_disjoint() -> None:
    # The shipped checker's own exit code must be 0 (disjoint).
    assert check_leakage.main() == 0


# --- 4. sft_config.yaml -----------------------------------------------------


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    data = yaml.safe_load(_CONFIG_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "config root must be a mapping"
    return data


def test_config_expected_keys_present(config: dict[str, Any]) -> None:
    expected = {
        "base_model",
        "adapter",
        "lora_r",
        "lora_alpha",
        "datasets",
        "val_set_size",
        "train_on_inputs",
        "num_epochs",
    }
    missing = expected - config.keys()
    assert not missing, f"config missing keys: {sorted(missing)}"


def test_config_train_on_inputs_is_false(config: dict[str, Any]) -> None:
    assert config["train_on_inputs"] is False


def test_config_val_set_size_positive(config: dict[str, Any]) -> None:
    val = config["val_set_size"]
    assert isinstance(val, (int, float)) and not isinstance(val, bool)
    assert val > 0, f"val_set_size must be > 0, got {val}"


def test_config_num_epochs_positive(config: dict[str, Any]) -> None:
    epochs = config["num_epochs"]
    assert isinstance(epochs, int) and not isinstance(epochs, bool)
    assert epochs > 0


def test_config_dataset_path_points_at_corpus(config: dict[str, Any]) -> None:
    datasets = config["datasets"]
    assert isinstance(datasets, list) and datasets, "datasets must be a non-empty list"
    paths = [d.get("path") for d in datasets if isinstance(d, dict)]
    assert "corpus/coach_sft.jsonl" in paths, f"unexpected dataset paths: {paths}"


def test_config_lora_dimensions_are_positive_ints(config: dict[str, Any]) -> None:
    for key in ("lora_r", "lora_alpha"):
        value = config[key]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert value > 0, f"{key} must be a positive integer, got {value}"
