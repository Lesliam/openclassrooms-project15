"""Dimension D5 on the Transformers backend: prompt baseline vs fine-tuned.

CS-157 measured D5 with prompt-only arms served by Ollama
(``run_disfluency_compare.py``, v2 vs v3, both at a 0.50 disfluency
false-correction rate). CS-158 trained the reconstruct-then-correct behaviour
into the weights, so D5 must now be measured with the LoRA adapter enabled.
Ollama cannot serve the adapter on this box (see ``RESULTS_sft_eval.md``), so
this driver reuses the session-14 pattern instead: ONE 4-bit base model with the
adapter toggled per arm (``run_transformers_compare.TransformersClient``).

Nothing in the CS-157 scorer is modified: the labelled dialogues, the
deterministic detectors, the per-item correctness rule and the metric
aggregation are all imported verbatim from ``run_disfluency_compare``. Only the
serving backend and the set of arms differ, so the CS-158 numbers are produced
by exactly the metric CS-157 defined.

Arms (each = adapter on/off x system prompt), all greedy (temperature 0) like
CS-157:

- ``baseline-v0`` — no adapter, v0 prompt: the frozen prompt the SFT corpus was
  authored against, without the fine-tune. Isolates the adapter's contribution.
- ``baseline-v3`` — no adapter, v3 prompt: the best prompt-only variant found in
  CS-157, i.e. the prompt-engineering ceiling this ticket compares against.
- ``tuned-v0`` — adapter, v0 prompt: the deployed fine-tuned configuration.
- ``tuned-v3`` — adapter, v3 prompt: checks whether prompt and weights stack.

Because all four arms share identical weights, identical nf4 quantization and
identical decode, differences between them are attributable to the adapter and
the prompt alone (the CS-157 Ollama numbers use a different quantization and are
therefore an external reference point, not a same-run control).

Usage::

    gpu-solo ~/dev/coach-sft/.venv/bin/python ml/eval/run_disfluency_tuned.py \\
        --adapter ~/dev/coach-sft/outputs/coach-qlora-v1-cs158 \\
        --out-dir ml/eval/runs/disfluency-d5-cs158
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import constants  # noqa: E402
from harness.ollama_client import DecodeOptions  # noqa: E402
from run_disfluency_compare import (  # noqa: E402
    D5_TEMPERATURE,
    DIALOGUES,
    ArmMetrics,
    _score_arm,
    compute_metrics,
    load_prompt_body,
)

# Model names the TransformersClient routes on: the exact baseline name disables
# the adapter, anything else keeps it enabled (see run_transformers_compare).
BASELINE_MODEL = "baseline"
TUNED_MODEL = "coach-tuned:v1-cs158"

# Longest CS-157 reply was 338 characters (~110 tokens); 256 leaves headroom so
# no reply is truncated mid-correction, which would corrupt the detectors.
DEFAULT_MAX_NEW_TOKENS = 256


@dataclass(frozen=True)
class Arm:
    """One D5 arm: an adapter state paired with a system prompt version."""

    name: str
    model: str
    prompt_file: Path

    @property
    def adapter_enabled(self) -> bool:
        return self.model != BASELINE_MODEL


def build_arms() -> tuple[Arm, ...]:
    """The four arms, ordered baseline-first so the tuned rows read as deltas."""
    v0 = constants.SERVER_DIR / "coach_system_prompt_v0.md"
    v3 = constants.SERVER_DIR / "coach_system_prompt_v3.md"
    return (
        Arm("baseline-v0", BASELINE_MODEL, v0),
        Arm("baseline-v3", BASELINE_MODEL, v3),
        Arm("tuned-v0", TUNED_MODEL, v0),
        Arm("tuned-v3", TUNED_MODEL, v3),
    )


def run_arms(client, arms, decode: DecodeOptions) -> dict[str, list[dict]]:
    """Score every arm with the CS-157 scorer; return per-arm record lists."""
    results: dict[str, list[dict]] = {}
    for arm in arms:
        prompt = load_prompt_body(arm.prompt_file)
        print(
            f"[d5] scoring {arm.name} ({len(DIALOGUES)} dialogues, "
            f"adapter={'on' if arm.adapter_enabled else 'off'})...",
            flush=True,
        )
        results[arm.name] = _score_arm(client, prompt, decode, arm.model)
    return results


def print_comparison(arms, results: dict[str, list[dict]]) -> None:
    """Print a per-dialogue table with one classification column per arm."""
    names = [arm.name for arm in arms]
    by_arm = {name: {r["id"]: r for r in results[name]} for name in names}
    header = f"{'id':<4} {'label':<11}" + "".join(f" {n:<16}" for n in names)
    print(header)
    print("-" * len(header))
    for dialogue in DIALOGUES:
        cells = ""
        for name in names:
            record = by_arm[name][dialogue.dialogue_id]
            mark = "ok" if record["correct"] else "X"
            cells += f" {(record['classification'] or 'n/a') + ' ' + mark:<16}"
        print(f"{dialogue.dialogue_id:<4} {dialogue.label:<11}{cells}")


def print_metrics(name: str, metrics: ArmMetrics) -> None:
    """Print the headline D5 metrics for one arm."""
    print(f"\n[{name}] scored {metrics.n_scored}/{metrics.n_items} items")
    print(f"  accuracy                        : {metrics.accuracy:.3f}")
    print(
        "  disfluency-false-correction rate: "
        f"{metrics.disfluency_false_correction_rate:.3f}"
    )
    print(f"  real-error recall               : {metrics.real_error_recall:.3f}")
    print(f"  incomplete-turn invite rate     : {metrics.incomplete_invite_rate:.3f}")
    for label, acc in metrics.per_label_accuracy.items():
        print(f"  {label:<11} accuracy          : {acc:.3f}")


def write_results(
    out_dir: Path, arms, results: dict[str, list[dict]], adapter: Path, decode
) -> Path:
    """Persist per-arm records + metrics as JSON; return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "dimension": "D5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": "transformers-4bit-nf4-adapter-toggle",
        "base_model": "Qwen/Qwen2.5-14B-Instruct",
        "adapter": str(adapter),
        "decode": decode.as_dict(),
        "arms": {
            arm.name: {
                "adapter_enabled": arm.adapter_enabled,
                "system_prompt": arm.prompt_file.name,
                "records": results[arm.name],
                "metrics": compute_metrics(results[arm.name]).to_dict(),
            }
            for arm in arms
        },
    }
    out_file = out_dir / "results.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=constants.RUNS_DIR / "disfluency-d5-cs158",
        help="Directory the run's results.json is written to.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS)
    args = parser.parse_args()

    # Same decode contract as CS-157: greedy (temperature 0) so the arm
    # comparison is reproducible from a single run.
    decode = DecodeOptions(
        temperature=D5_TEMPERATURE,
        top_p=constants.DECODE_TOP_P,
        seed=constants.DECODE_SEED_BASE,
        num_ctx=constants.DECODE_NUM_CTX,
    )

    # Imported lazily: loading the 4-bit base model is a GPU action, so the
    # module stays importable (and unit-testable) on CPU.
    import run_transformers_compare  # noqa: PLC0415
    from run_transformers_compare import TransformersClient  # noqa: PLC0415

    if BASELINE_MODEL != run_transformers_compare._BASELINE_ARM:
        raise RuntimeError(
            "BASELINE_MODEL diverged from run_transformers_compare._BASELINE_ARM"
            f" ({BASELINE_MODEL!r} != {run_transformers_compare._BASELINE_ARM!r});"
            " the baseline arms would silently run with the adapter enabled."
        )

    arms = build_arms()
    client = TransformersClient(args.adapter.expanduser(), args.max_new_tokens)
    results = run_arms(client, arms, decode)

    print_comparison(arms, results)
    for arm in arms:
        print_metrics(arm.name, compute_metrics(results[arm.name]))

    out_file = write_results(
        args.out_dir, arms, results, args.adapter.expanduser(), decode
    )
    print(f"\n[d5] results written to {out_file}")


if __name__ == "__main__":
    main()
