"""Merge the QLoRA adapter into the base weights and export for Ollama.

After ``train_sft.py`` produces a LoRA adapter, this script folds it back into
a full-precision copy of the base model so the tuned arm can be served through
Ollama exactly like the baseline (``qwen2.5:14b``). The merge runs on CPU
because the bf16 14B model does not fit in 16 GB of VRAM; only ~29 GB of host
RAM is needed.

The merged model is written with the PRISTINE base tokenizer (not the
generation-tagged training template), so the served chat template matches the
baseline arm exactly — the two arms must differ only by the adapter.

Then quantize + register with Ollama to Q4_K_M (the baseline's quant), e.g.::

    OLLAMA_HOST=<host> ollama create coach-tuned:v0 --experimental \\
        -q q4_K_M -f <merged-dir>/Modelfile

Usage::

    python ml/finetune/merge_export.py \\
        --adapter ~/dev/coach-sft/outputs/coach-qlora-v0 \\
        --out ~/dev/coach-sft/outputs/coach-merged
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

_BASE_MODEL = "Qwen/Qwen2.5-14B-Instruct"

# A minimal Modelfile: FROM the merged safetensors directory. The chat template
# and stop tokens come from the tokenizer config Ollama reads out of that
# directory, so no SYSTEM / TEMPLATE override is needed — the eval harness
# supplies the coach system prompt per request, identically on both arms.
_MODELFILE = "FROM .\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", default=_BASE_MODEL)
    args = parser.parse_args()

    print(f"[load] base (CPU, bf16): {args.base}")
    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map="cpu",
    )

    print(f"[merge] applying adapter: {args.adapter}")
    model = PeftModel.from_pretrained(model, str(args.adapter))
    model = model.merge_and_unload()

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"[save] merged model -> {args.out}")
    model.save_pretrained(str(args.out), safe_serialization=True)

    # Pristine base tokenizer, NOT the training-time generation-tagged template.
    AutoTokenizer.from_pretrained(args.base).save_pretrained(str(args.out))

    (args.out / "Modelfile").write_text(_MODELFILE)
    print(f"[done] merged model + Modelfile ready in {args.out}")


if __name__ == "__main__":
    main()
