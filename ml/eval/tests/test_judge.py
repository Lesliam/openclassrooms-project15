"""Independent unit tests for ``harness.judge``.

Focus: the JSON verdict parser must not fall into the ``bool("false") == True``
trap (fix S3), and must reject unparseable or ambiguous 'pass' values instead
of silently mis-grading. The judge is exercised without touching the network
by injecting a fake chat client.
"""

from __future__ import annotations

import pytest

from harness import judge
from harness.judge import Judge, JudgeError, JudgeVerdict, parse_judge_output
from harness.ollama_client import DecodeOptions, Message


# --- pass coercion (fix S3) -------------------------------------------------


def test_parse_json_boolean_true() -> None:
    assert parse_judge_output('{"pass": true}').passed is True


def test_parse_json_boolean_false() -> None:
    assert parse_judge_output('{"pass": false}').passed is False


def test_parse_string_false_is_false_not_truthy() -> None:
    # The regression this fix targets: bool("false") is True in Python.
    verdict = parse_judge_output('{"pass": "false", "missing_or_violating": "x"}')
    assert verdict.passed is False
    assert verdict.missing_or_violating == "x"


@pytest.mark.parametrize("token", ["true", "TRUE", " yes ", "1"])
def test_parse_truthy_strings(token: str) -> None:
    assert parse_judge_output(f'{{"pass": "{token}"}}').passed is True


@pytest.mark.parametrize("token", ["false", "FALSE", " no ", "0"])
def test_parse_falsy_strings(token: str) -> None:
    assert parse_judge_output(f'{{"pass": "{token}"}}').passed is False


def test_parse_integer_pass() -> None:
    assert parse_judge_output('{"pass": 1}').passed is True
    assert parse_judge_output('{"pass": 0}').passed is False


def test_parse_ambiguous_string_raises() -> None:
    with pytest.raises(JudgeError):
        parse_judge_output('{"pass": "maybe"}')


def test_parse_out_of_range_int_raises() -> None:
    with pytest.raises(JudgeError):
        parse_judge_output('{"pass": 2}')


# --- structural parsing -----------------------------------------------------


def test_parse_tolerates_surrounding_prose() -> None:
    raw = 'Reasoning first...\n{"pass": true, "missing_or_violating": ""}\nend'
    verdict = parse_judge_output(raw)
    assert verdict.passed is True
    assert verdict.raw_output == raw


def test_parse_missing_pass_key_raises() -> None:
    with pytest.raises(JudgeError):
        parse_judge_output('{"missing_or_violating": "no verdict"}')


def test_parse_non_json_raises() -> None:
    with pytest.raises(JudgeError):
        parse_judge_output("no json object here")


def test_build_judge_prompt_includes_fields() -> None:
    prompt = judge.build_judge_prompt(
        judge.CHECK_D1_FORMAT, "learner text", "coach text", "the planted error"
    )
    assert "learner text" in prompt
    assert "coach text" in prompt
    assert "D1_FORMAT" in prompt
    assert "the planted error" in prompt


# --- Judge.grade with a fake client -----------------------------------------


class _FakeClient:
    """Records the chat call and returns a canned raw judge output."""

    def __init__(self, raw: str) -> None:
        self._raw = raw
        self.calls: list[dict] = []

    def chat(
        self, model: str, messages: list[Message], options: DecodeOptions
    ) -> str:
        self.calls.append({"model": model, "messages": messages, "options": options})
        return self._raw


def test_judge_grade_parses_client_output() -> None:
    client = _FakeClient('{"pass": "false", "missing_or_violating": "no repeat"}')
    verdict = Judge(client, model="mistral-small3.2:latest").grade(  # type: ignore[arg-type]
        judge.CHECK_D1_FORMAT, "learner", "coach", "error note"
    )
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.passed is False
    assert client.calls[0]["model"] == "mistral-small3.2:latest"
    # Judge grades at temperature 0 for stable verdicts.
    assert client.calls[0]["options"].temperature == 0.0
