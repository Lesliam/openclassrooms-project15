"""Unit tests for the ``--model`` flag / ``model_under_test`` plumbing.

Covers the new tuned-arm selector end to end at the pure-logic level:
- ``build_run_config`` threads an explicit tag into ``RunConfig.model_under_test``
  and defaults to the baseline constant when omitted.
- the CLI parser accepts ``--model`` and defaults it to the baseline constant.

No Ollama call, no run output — ``build_run_config`` only reads the frozen
prompt / eval-set files and hashes them, and the parser is inspected directly.
"""

from __future__ import annotations

from harness import cli, constants
from harness.config import build_run_config
from harness.ollama_client import DecodeOptions

_DECODE = DecodeOptions(temperature=0.7, top_p=0.9, seed=42, num_ctx=8192)


def _build(**overrides):
    kwargs = dict(
        run_id="20260713T000000Z-test",
        mode="baseline",
        repetitions=2,
        drift_depth=7,
        judge_enabled=False,
        judge_model="none",
        decode=_DECODE,
    )
    kwargs.update(overrides)
    return build_run_config(**kwargs)


def test_build_run_config_threads_explicit_model() -> None:
    cfg = _build(model_under_test="foo:v0")
    assert cfg.model_under_test == "foo:v0"


def test_build_run_config_defaults_model_to_baseline_constant() -> None:
    cfg = _build()
    assert cfg.model_under_test == constants.MODEL_UNDER_TEST


def test_explicit_model_survives_to_dict() -> None:
    data = _build(model_under_test="coach-tuned:v0").to_dict()
    assert data["model_under_test"] == "coach-tuned:v0"


def test_cli_parser_accepts_model_flag() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["--full", "--model", "coach-tuned:v0"])
    assert args.model == "coach-tuned:v0"


def test_cli_parser_model_defaults_to_baseline_constant() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["--dry-run"])
    assert args.model == constants.MODEL_UNDER_TEST
