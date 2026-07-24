"""Independent unit tests for ``harness.runner`` orchestration.

No network: a fake chat client returns canned replies. Covers the drift-depth
guard (fix S4) and incremental score persistence so a mid-run failure stays
recoverable (fix S5).
"""

from __future__ import annotations

import json

import pytest

from harness import constants, dialogues as dialogues_mod, runner
from harness.config import build_run_config
from harness.ollama_client import DecodeOptions, Message, OllamaError

_BASE_DECODE = DecodeOptions(temperature=0.7, top_p=0.9, seed=42, num_ctx=8192)
_COMPLIANT_REPLY = (
    "Tu as dit : « x ». On dit plutôt : « y ». Explication simple. Répète."
)


def _config(*, repetitions: int, drift_depth: int):
    return build_run_config(
        run_id="test-run",
        mode="dryrun",
        repetitions=repetitions,
        drift_depth=drift_depth,
        judge_enabled=False,
        judge_model="mistral-small3.2:latest",
        decode=_BASE_DECODE,
    )


class _CannedClient:
    """Returns a fixed reply, optionally raising on the Nth chat call."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self._fail_on_call = fail_on_call

    def chat(self, model: str, messages: list[Message], options: DecodeOptions) -> str:
        self.calls += 1
        if self._fail_on_call is not None and self.calls >= self._fail_on_call:
            raise OllamaError("simulated mid-run failure")
        return _COMPLIANT_REPLY


# --- S4: drift-depth guard --------------------------------------------------


def test_filler_script_has_enough_lines_for_default_depth() -> None:
    assert runner.available_filler_depth() >= constants.DEFAULT_DRIFT_DEPTH
    assert runner.available_filler_depth() >= 25  # spec "~turn 25+" reachable


def test_ensure_drift_depth_available_allows_capacity() -> None:
    runner.ensure_drift_depth_available(runner.available_filler_depth())


def test_ensure_drift_depth_available_raises_when_exceeded() -> None:
    with pytest.raises(ValueError):
        runner.ensure_drift_depth_available(runner.available_filler_depth() + 1)


def test_run_all_rejects_oversize_drift_depth(tmp_path) -> None:
    cfg = _config(repetitions=1, drift_depth=runner.available_filler_depth() + 1)
    with pytest.raises(ValueError):
        runner.run_all(
            _CannedClient(), cfg, _BASE_DECODE, tmp_path, dialogues=dialogues_mod.GROUP_A[:1]
        )


# --- S5: incremental / recoverable score persistence ------------------------


def test_scores_written_incrementally_survive_midrun_failure(tmp_path) -> None:
    # Two simple dialogues, one repetition each -> one chat call per dialogue.
    # The client fails on the 2nd call, so only the first dialogue completes.
    cfg = _config(repetitions=1, drift_depth=7)
    client = _CannedClient(fail_on_call=2)
    two_dialogues = dialogues_mod.GROUP_A[:2]

    with pytest.raises(OllamaError):
        runner.run_all(client, cfg, _BASE_DECODE, tmp_path, dialogues=two_dialogues)

    partial = tmp_path / "scores.partial.json"
    assert partial.exists(), "partial snapshot must survive a mid-run failure"
    records = json.loads(partial.read_text(encoding="utf-8"))
    assert len(records) == 1  # first dialogue's single turn was persisted
    assert records[0]["item_id"] == 1
    # The final (complete) scores file must NOT exist for an incomplete run.
    assert not (tmp_path / "scores.json").exists()


def test_successful_run_writes_scores_and_removes_partial(tmp_path) -> None:
    cfg = _config(repetitions=1, drift_depth=7)
    client = _CannedClient()
    two_dialogues = dialogues_mod.GROUP_A[:2]

    results = runner.run_all(
        client, cfg, _BASE_DECODE, tmp_path, dialogues=two_dialogues
    )

    scores_path = tmp_path / "scores.json"
    assert scores_path.exists()
    records = json.loads(scores_path.read_text(encoding="utf-8"))
    assert len(records) == len(results) == 2
    # On success the intermediate snapshot is cleaned up.
    assert not (tmp_path / "scores.partial.json").exists()
    # config.json is persisted and the host is redacted.
    config_data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "REDACTED" in config_data["ollama_base_url"]
