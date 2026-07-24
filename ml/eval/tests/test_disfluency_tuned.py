"""Offline unit tests for the D5 adapter-toggle driver (CS-158).

The driver's own logic is the arm definition, the arm loop and the results
payload; the scoring itself is the frozen CS-157 scorer, covered by
``test_disfluency_scorer.py``. These tests use a fake client (no GPU, no model
load) to check that each arm is dispatched with the right model name and the
right system prompt, and that the persisted payload records per-arm metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

import run_disfluency_tuned as d5t
from harness.ollama_client import DecodeOptions, Message

_DECODE = DecodeOptions(temperature=0.0, top_p=0.9, seed=42, num_ctx=8192)

_CORRECTION_REPLY = (
    "Tu as dit : « je vais au réunion ». On dit plutôt : « je vais à la réunion ». "
    "« Réunion » est féminin. Peux-tu répéter : « je vais à la réunion » ?"
)
_ENGAGED_REPLY = "Ton projet a l'air passionnant. Quel problème veux-tu résoudre ?"


class _FakeClient:
    """Records every (model, system prompt) pair and returns a canned reply."""

    def __init__(self, reply: str = _ENGAGED_REPLY) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def chat(self, model: str, messages: list[Message], options: DecodeOptions) -> str:
        self.calls.append((model, messages[0].content))
        return self.reply


def test_build_arms_covers_both_adapter_states_and_both_prompts() -> None:
    arms = d5t.build_arms()
    assert [arm.name for arm in arms] == [
        "baseline-v0",
        "baseline-v3",
        "tuned-v0",
        "tuned-v3",
    ]
    assert [arm.adapter_enabled for arm in arms] == [False, False, True, True]
    assert [arm.prompt_file.name for arm in arms] == [
        "coach_system_prompt_v0.md",
        "coach_system_prompt_v3.md",
        "coach_system_prompt_v0.md",
        "coach_system_prompt_v3.md",
    ]


def test_baseline_arm_dispatches_the_adapter_disabling_model_name() -> None:
    """The toggle is keyed on the model name, so it must be exactly 'baseline'."""
    arms = d5t.build_arms()
    assert arms[0].model == d5t.BASELINE_MODEL == "baseline"
    assert arms[2].model != d5t.BASELINE_MODEL


def test_run_arms_scores_every_dialogue_on_every_arm() -> None:
    client = _FakeClient()
    arms = d5t.build_arms()
    results = d5t.run_arms(client, arms, _DECODE)

    assert set(results) == {arm.name for arm in arms}
    assert all(len(records) == len(d5t.DIALOGUES) for records in results.values())
    assert len(client.calls) == len(arms) * len(d5t.DIALOGUES)


def test_run_arms_sends_each_arms_own_prompt_and_model() -> None:
    client = _FakeClient()
    arms = d5t.build_arms()
    d5t.run_arms(client, arms, _DECODE)

    per_arm = len(d5t.DIALOGUES)
    for index, arm in enumerate(arms):
        model, system_prompt = client.calls[index * per_arm]
        assert model == arm.model
        assert system_prompt == d5t.load_prompt_body(arm.prompt_file)


def test_write_results_records_metrics_and_arm_metadata(tmp_path: Path) -> None:
    client = _FakeClient()
    arms = d5t.build_arms()
    results = d5t.run_arms(client, arms, _DECODE)

    out_file = d5t.write_results(
        tmp_path, arms, results, Path("/tmp/fake-adapter"), _DECODE
    )
    payload = json.loads(out_file.read_text(encoding="utf-8"))

    assert payload["dimension"] == "D5"
    assert payload["decode"]["temperature"] == 0.0
    assert set(payload["arms"]) == {arm.name for arm in arms}
    baseline = payload["arms"]["baseline-v0"]
    assert baseline["adapter_enabled"] is False
    assert baseline["system_prompt"] == "coach_system_prompt_v0.md"
    # An always-engaged client never corrects: no false correction, no recall.
    assert baseline["metrics"]["disfluency_false_correction_rate"] == 0.0
    assert baseline["metrics"]["real_error_recall"] == 0.0


def test_metrics_track_a_client_that_always_corrects(tmp_path: Path) -> None:
    """Sanity check the opposite extreme: correcting everything is fully unsafe."""
    client = _FakeClient(reply=_CORRECTION_REPLY)
    arms = d5t.build_arms()[:1]
    results = d5t.run_arms(client, arms, _DECODE)

    metrics = d5t.compute_metrics(results["baseline-v0"])
    assert metrics.disfluency_false_correction_rate > 0.0
    assert metrics.incomplete_invite_rate == 0.0
