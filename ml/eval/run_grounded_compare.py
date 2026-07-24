"""Run the ``coach-grounded`` third eval arm through the harness.

This arm is the tuned model PLUS the grammar-grounding correctness layer: every
learner turn whose local GEC check finds a real French error is answered by
``build_grounded_correction`` (the corrected form comes from the authoritative
GEC engine, only the one explanation sentence is phrased by the tuned model);
every other turn -- already-correct French, language-switch (D2), drift filler
-- falls through to the tuned model unchanged.

It reuses the same ``TransformersClient`` (base 4-bit weights + LoRA adapter)
and the same harness ``run_all`` / ``build_report`` as the baseline/tuned arms,
so the produced run directory (config + transcripts + scores + report) is
identical in shape and works with the existing report and judge tooling. The
per-turn grounding is implemented as a thin client wrapper so the harness
runner, scorers and report code are untouched.

Usage::

    python ml/eval/run_grounded_compare.py \\
        --adapter ~/dev/coach-sft/outputs/coach-qlora-v0 \\
        --repetitions 2 --drift-depth 7 --out-root ~/dev/coach-sft/eval-runs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _THIS_DIR.parent.parent
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_PROJECT_DIR / "server"))

from grammar_grounding import GrammarChecker, build_grounded_correction  # noqa: E402
from harness import constants  # noqa: E402
from harness.config import build_run_config  # noqa: E402
from harness.ollama_client import DecodeOptions, Message  # noqa: E402
from harness.report import build_report  # noqa: E402
from harness.runner import ensure_drift_depth_available, run_all  # noqa: E402
from run_transformers_compare import _TUNED_ARM, TransformersClient  # noqa: E402

_GROUNDED_ARM = "coach-grounded"
# Coach-model generation budget per turn (matches run_transformers_compare).
_DEFAULT_MAX_NEW_TOKENS = 200


class GroundedClient:
    """Wrap ``TransformersClient`` to ground D1 corrections in the GEC engine.

    On each ``chat`` call the last learner turn is checked by the local GEC
    engine. If a real French error is found, the reply is the fully
    deterministic grounded 4-part correction (both the corrected form and the
    explanation are grounded -- the tuned model is NOT consulted on this path).
    Otherwise the call falls through to the tuned model unchanged, so
    already-correct French, language-switch (D2) and drift turns behave exactly
    like the tuned arm.
    """

    def __init__(self, inner: TransformersClient, checker: GrammarChecker) -> None:
        self._inner = inner
        self._checker = checker

    def list_models(self) -> list[str]:
        return [_GROUNDED_ARM]

    @staticmethod
    def _last_learner_text(messages: list[Message]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return ""

    def chat(
        self, model: str, messages: list[Message], options: DecodeOptions
    ) -> str:
        learner_text = self._last_learner_text(messages)
        result = self._checker.check(learner_text)
        if result.has_error:
            grounded = build_grounded_correction(learner_text, result)
            if grounded is not None:
                return grounded
        return self._inner.chat(_TUNED_ARM, messages, options)


def _run_grounded_arm(
    client: GroundedClient,
    repetitions: int,
    drift_depth: int,
    out_root: Path,
) -> Path:
    decode = DecodeOptions(
        temperature=constants.DECODE_TEMPERATURE,
        top_p=constants.DECODE_TOP_P,
        seed=constants.DECODE_SEED_BASE,
        num_ctx=constants.DECODE_NUM_CTX,
    )
    config = build_run_config(
        run_id=f"transformers-{_GROUNDED_ARM}",
        mode=_GROUNDED_ARM,
        repetitions=repetitions,
        drift_depth=drift_depth,
        judge_enabled=False,
        judge_model="none",
        decode=decode,
        model_under_test=_GROUNDED_ARM,
    )
    output_dir = out_root / config.run_id
    print(f"[grounded] arm={_GROUNDED_ARM} -> {output_dir}", flush=True)
    run_all(
        client,
        config,
        decode,
        output_dir,
        progress=lambda m: print(f"  {m}", flush=True),
    )
    report = build_report(output_dir)
    print(f"[grounded] arm={_GROUNDED_ARM} report: {report}", flush=True)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=constants.DRYRUN_REPETITIONS)
    parser.add_argument("--drift-depth", type=int, default=constants.DRYRUN_DRIFT_DEPTH)
    parser.add_argument("--max-new-tokens", type=int, default=_DEFAULT_MAX_NEW_TOKENS)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args()

    ensure_drift_depth_available(args.drift_depth)
    args.out_root.mkdir(parents=True, exist_ok=True)

    inner = TransformersClient(args.adapter, args.max_new_tokens)
    checker = GrammarChecker()
    client = GroundedClient(inner, checker)
    _run_grounded_arm(client, args.repetitions, args.drift_depth, args.out_root)


if __name__ == "__main__":
    main()
