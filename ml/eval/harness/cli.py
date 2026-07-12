"""Command-line entrypoint for the evaluation harness.

Examples:
    python -m harness --dry-run
    python -m harness --full --repetitions 5 --drift-depth 18 --judge

The dry-run uses reduced repetitions and drift depth, keeps the judge
disabled, and hits Ollama for real to produce a report under
``ml/eval/runs/<run-id>/``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import constants
from .config import build_run_config
from .ollama_client import DecodeOptions, Message, OllamaClient, OllamaError
from .report import build_report
from .runner import run_all
from .spec_guard import verify_dialogues_match_spec

_HEALTH_CHECK_PROMPT = "Reponds simplement: bonjour."
_HEALTH_CHECK_MAX_TOKENS_CTX = 512


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Coach FR prompt-baseline evaluation harness.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="reduced repetitions and drift depth, judge disabled (default)",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="full baseline run",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=None,
        help="override repetitions per item",
    )
    parser.add_argument(
        "--drift-depth",
        type=int,
        default=None,
        help="override number of filler turns before the deep probe",
    )
    parser.add_argument(
        "--judge",
        dest="judge",
        action="store_true",
        default=False,
        help="enable the LLM judge (full runs only; off in dry-run)",
    )
    parser.add_argument(
        "--judge-model",
        default=constants.DEFAULT_JUDGE_MODEL,
        help="judge model name",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="explicit run id (default: <utc-timestamp>-<mode>)",
    )
    return parser


def _default_run_id(mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{mode}"


def _health_check(client: OllamaClient) -> None:
    models = client.list_models()
    required = {constants.MODEL_UNDER_TEST}
    missing = [m for m in required if not any(m in name for name in models)]
    if missing:
        raise OllamaError(f"required model(s) not present on server: {missing}")
    decode = DecodeOptions(
        temperature=0.0,
        top_p=1.0,
        seed=constants.DECODE_SEED_BASE,
        num_ctx=_HEALTH_CHECK_MAX_TOKENS_CTX,
    )
    reply = client.chat(
        model=constants.MODEL_UNDER_TEST,
        messages=[Message(role="user", content=_HEALTH_CHECK_PROMPT)],
        options=decode,
    )
    if not reply.strip():
        raise OllamaError("health-check chat returned an empty reply")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    is_full = args.full
    mode = "baseline" if is_full else "dryrun"
    repetitions = args.repetitions or (
        constants.DEFAULT_REPETITIONS if is_full else constants.DRYRUN_REPETITIONS
    )
    drift_depth = args.drift_depth or (
        constants.DEFAULT_DRIFT_DEPTH if is_full else constants.DRYRUN_DRIFT_DEPTH
    )
    judge_enabled = args.judge and is_full  # never in dry-run
    run_id = args.run_id or _default_run_id(mode)

    base_decode = DecodeOptions(
        temperature=constants.DECODE_TEMPERATURE,
        top_p=constants.DECODE_TOP_P,
        seed=constants.DECODE_SEED_BASE,
        num_ctx=constants.DECODE_NUM_CTX,
    )
    config = build_run_config(
        run_id=run_id,
        mode=mode,
        repetitions=repetitions,
        drift_depth=drift_depth,
        judge_enabled=judge_enabled,
        judge_model=args.judge_model,
        decode=base_decode,
    )

    print(f"[harness] mode={mode} run_id={run_id}", flush=True)
    print("[harness] spec guard: checking dialogues match eval_set_v0.md...", flush=True)
    try:
        verify_dialogues_match_spec()
    except AssertionError as exc:
        print(f"[harness] spec guard FAILED: {exc}", file=sys.stderr)
        return 1
    print("[harness] spec guard ok", flush=True)

    client = OllamaClient()
    print("[harness] health check...", flush=True)
    try:
        _health_check(client)
    except OllamaError as exc:
        print(f"[harness] health check FAILED: {exc}", file=sys.stderr)
        return 2
    print("[harness] health check ok", flush=True)

    output_dir = constants.RUNS_DIR / run_id

    def _progress(msg: str) -> None:
        print(f"[harness] {msg}", flush=True)

    try:
        run_all(client, config, base_decode, output_dir, progress=_progress)
    except OllamaError as exc:
        print(f"[harness] run FAILED: {exc}", file=sys.stderr)
        return 3

    report_path = build_report(output_dir)
    print(f"[harness] done. run dir: {output_dir}", flush=True)
    print(f"[harness] report: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
