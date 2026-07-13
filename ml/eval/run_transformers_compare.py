"""Run the baseline-vs-tuned eval through a local Transformers backend.

The Ollama harness (``harness/``) is backend-agnostic: ``run_all`` only needs a
client exposing ``chat(model, messages, options)``. This driver supplies a
Transformers-backed client so the tuned arm can be evaluated WITHOUT importing
the LoRA into Ollama (this box's Ollama binds a LAN IP only and its Linux build
cannot quantize a safetensors ``lm_head``).

Both arms share ONE 4-bit base model; the tuned arm simply enables the LoRA
adapter and the baseline arm disables it via ``PeftModel.disable_adapter()``.
This is the most controlled comparison possible: identical weights, identical
nf4 quantization, identical decode — the only difference is the adapter.

Usage::

    python ml/eval/run_transformers_compare.py \\
        --adapter ~/dev/coach-sft/outputs/coach-qlora-v0 \\
        --repetitions 2 --drift-depth 7 --out-root ~/dev/coach-sft/eval-runs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import constants  # noqa: E402
from harness.config import build_run_config  # noqa: E402
from harness.ollama_client import DecodeOptions, Message  # noqa: E402
from harness.report import build_report  # noqa: E402
from harness.runner import ensure_drift_depth_available, run_all  # noqa: E402

_BASE = "Qwen/Qwen2.5-14B-Instruct"
_BASELINE_ARM = "baseline"
_TUNED_ARM = "coach-tuned:v0"


class TransformersClient:
    """OllamaClient-compatible client backed by a local 4-bit PeftModel.

    ``chat`` routes to the base weights with the adapter disabled for the
    baseline arm and enabled for the tuned arm, keyed on the model name the
    runner passes (``config.model_under_test``).
    """

    def __init__(self, adapter_dir: Path, max_new_tokens: int) -> None:
        self._tokenizer = AutoTokenizer.from_pretrained(_BASE)
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        base = AutoModelForCausalLM.from_pretrained(
            _BASE, quantization_config=bnb, dtype=torch.bfloat16, device_map={"": 0}
        )
        self._model = PeftModel.from_pretrained(base, str(adapter_dir))
        self._model.eval()
        self._max_new_tokens = max_new_tokens

    def list_models(self) -> list[str]:
        return [_BASELINE_ARM, _TUNED_ARM]

    def _generate(self, messages: list[Message], options: DecodeOptions) -> str:
        enc = self._tokenizer.apply_chat_template(
            [m.as_dict() for m in messages],
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)
        prompt_len = enc["input_ids"].shape[1]
        # options.num_ctx is honoured by the Ollama backend but not by HF
        # generate (HF uses the model's native window); both arms here run on
        # the same Transformers backend, so the comparison stays controlled.
        torch.manual_seed(options.seed)
        with torch.no_grad():
            out = self._model.generate(
                **enc,
                max_new_tokens=self._max_new_tokens,
                do_sample=options.temperature > 0.0,
                temperature=options.temperature or None,
                top_p=options.top_p,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        return self._tokenizer.decode(
            out[0, prompt_len:], skip_special_tokens=True
        ).strip()

    def chat(
        self, model: str, messages: list[Message], options: DecodeOptions
    ) -> str:
        if model == _BASELINE_ARM:
            with self._model.disable_adapter():
                return self._generate(messages, options)
        return self._generate(messages, options)


def _run_arm(
    client: TransformersClient,
    arm: str,
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
        run_id=f"transformers-{arm.replace(':', '-')}",
        mode=arm,
        repetitions=repetitions,
        drift_depth=drift_depth,
        judge_enabled=False,
        judge_model="none",
        decode=decode,
        model_under_test=arm,
    )
    output_dir = out_root / config.run_id
    print(f"[compare] arm={arm} -> {output_dir}", flush=True)
    run_all(client, config, decode, output_dir, progress=lambda m: print(f"  {m}", flush=True))
    report = build_report(output_dir)
    print(f"[compare] arm={arm} report: {report}", flush=True)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=constants.DRYRUN_REPETITIONS)
    parser.add_argument("--drift-depth", type=int, default=constants.DRYRUN_DRIFT_DEPTH)
    parser.add_argument("--max-new-tokens", type=int, default=200)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args()

    ensure_drift_depth_available(args.drift_depth)
    args.out_root.mkdir(parents=True, exist_ok=True)

    client = TransformersClient(args.adapter, args.max_new_tokens)
    for arm in (_BASELINE_ARM, _TUNED_ARM):
        _run_arm(client, arm, args.repetitions, args.drift_depth, args.out_root)


if __name__ == "__main__":
    main()
