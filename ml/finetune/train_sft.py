"""QLoRA SFT runner for the coach behavior fine-tune (tuned arm).

This is the TRL ``SFTTrainer`` implementation of the QLoRA run described in
``sft_config.yaml``. The YAML remains the single source of truth for every
hyper-parameter; this script reads it and maps the axolotl-style keys onto the
TRL / transformers / peft API. The axolotl CLI path was dropped because its
schema drifts across releases (see README.md "Validate before running"); a
self-contained TRL script is more reproducible.

The run is VRAM-bound and MUST be launched under ``gpu-solo`` so that
``wyoming-whisper`` releases its resident VRAM first. See README.md.

Usage (from the project root, with the training venv active)::

    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \\
        python ml/finetune/train_sft.py --config ml/finetune/sft_config.yaml

A short dry run that only verifies the pipeline and the real VRAM peak::

    python ml/finetune/train_sft.py --config ml/finetune/sft_config.yaml \\
        --dry-run --max-examples 4 --epochs 1
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import torch
import yaml
from datasets import Dataset
from peft import LoraConfig
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    set_seed,
)
from trl import SFTConfig, SFTTrainer

# Qwen2.5 ChatML template rewritten with the {% generation %} markers that
# transformers needs to emit an assistant-token mask. It is intentionally
# minimal (no tool-calling branch) because the corpus is exactly
# system/user/assistant single-turn; a dry-run assertion checks that the mask
# it produces is non-empty and lands on the assistant span only.
_CHATML_WITH_GENERATION = (
    "{% for message in messages %}"
    "{% if message['role'] == 'assistant' %}"
    "{{ '<|im_start|>assistant\n' }}"
    "{% generation %}{{ message['content'] }}{{ '<|im_end|>' }}{% endgeneration %}"
    "{{ '\n' }}"
    "{% else %}"
    "{{ '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}"
    "{% endif %}"
    "{% endfor %}"
)

_BNB_QUANT_DTYPE = {"bfloat16": torch.bfloat16, "float16": torch.float16}


def _load_config(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle)


def _build_bnb_config(cfg: dict[str, Any]) -> BitsAndBytesConfig:
    """Map the QLoRA quantization keys from the YAML onto BitsAndBytesConfig."""
    return BitsAndBytesConfig(
        load_in_4bit=cfg["load_in_4bit"],
        bnb_4bit_quant_type=cfg["bnb_4bit_quant_type"],
        bnb_4bit_use_double_quant=cfg["bnb_4bit_use_double_quant"],
        bnb_4bit_compute_dtype=_BNB_QUANT_DTYPE[cfg["bnb_4bit_compute_dtype"]],
    )


def _build_lora_config(cfg: dict[str, Any]) -> LoraConfig:
    return LoraConfig(
        r=cfg["lora_r"],
        lora_alpha=cfg["lora_alpha"],
        lora_dropout=cfg["lora_dropout"],
        target_modules=list(cfg["lora_target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )


def _prepare_qlora(model: Any, use_gradient_checkpointing: bool) -> Any:
    """Prepare a 4-bit model for QLoRA WITHOUT the fp32 embedding upcast.

    peft's ``prepare_model_for_kbit_training`` upcasts every non-4-bit param to
    fp32, which on Qwen2.5-14B doubles the 3.1 GB bf16 ``embed_tokens`` +
    ``lm_head`` to 6.2 GB — the difference between fitting and OOM on a 16 GB
    card. Those two tensors are frozen in QLoRA (only the LoRA adapters train),
    so they do not need fp32. We keep them bf16 and upcast only the tiny
    LayerNorm/RMSNorm params, which is the part that actually helps stability.

    Note: SFTTrainer is given ``peft_config`` and a bare 4-bit model, so TRL
    runs its own PEFT preparation. On the pinned TRL (1.8) this does NOT re-add
    the fp32 embedding upcast — empirically confirmed by the measured training
    peak of ~11 GB (a re-upcast would push the baseline past 13 GB and OOM the
    16 GB card, as the earlier bare-``prepare_model_for_kbit_training`` attempt
    did). Re-verify the peak if TRL is upgraded.
    """
    for module in model.modules():
        if "norm" in type(module).__name__.lower():
            module.to(torch.float32)
    model.config.use_cache = False
    if use_gradient_checkpointing:
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        model.enable_input_require_grads()
    return model


def _load_corpus(path: Path, max_examples: int | None) -> Dataset:
    dataset = Dataset.from_json(str(path))
    if max_examples is not None:
        dataset = dataset.select(range(min(max_examples, len(dataset))))
    return dataset


def _assert_assistant_mask(tokenizer: AutoTokenizer, example: dict[str, Any]) -> None:
    """Fail loudly if assistant_only_loss would train on an empty mask.

    Renders one example with return_assistant_tokens_mask and asserts the mask
    is non-empty and strictly inside the sequence (i.e. the system/user prefix
    is masked out). This is the guard that the generation-tagged template works.
    """
    encoded = tokenizer.apply_chat_template(
        example["messages"],
        return_assistant_tokens_mask=True,
        return_dict=True,
        tokenize=True,
    )
    mask = encoded["assistant_masks"]
    trained = sum(mask)
    total = len(mask)
    if trained == 0:
        raise RuntimeError(
            "assistant_only_loss mask is empty — the chat template did not emit "
            "generation markers. Aborting rather than training on nothing."
        )
    if trained >= total:
        raise RuntimeError(
            "assistant mask covers the whole sequence — system/user turns are "
            "not being masked. Aborting."
        )
    print(f"[mask check] assistant tokens trained: {trained}/{total}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Override corpus path (default: resolved relative to the config).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "dev" / "coach-sft" / "outputs" / "coach-qlora-v0",
        help="Where the LoRA adapter lands (kept OUTSIDE the public repo).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--epochs", type=float, default=None)
    args = parser.parse_args()

    cfg = _load_config(args.config)
    config_dir = args.config.resolve().parent
    corpus_path = args.corpus or (config_dir / cfg["datasets"][0]["path"])
    epochs = args.epochs if args.epochs is not None else cfg["num_epochs"]

    set_seed(cfg["seed"])

    print(f"[load] tokenizer + 4-bit model: {cfg['base_model']}")
    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])
    tokenizer.chat_template = _CHATML_WITH_GENERATION

    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_model"],
        quantization_config=_build_bnb_config(cfg),
        dtype=_BNB_QUANT_DTYPE[cfg["bnb_4bit_compute_dtype"]],
        device_map={"": 0},
    )
    model = _prepare_qlora(
        model, use_gradient_checkpointing=cfg["gradient_checkpointing"]
    )

    dataset = _load_corpus(corpus_path, args.max_examples)
    _assert_assistant_mask(tokenizer, dataset[0])

    val_fraction = cfg["val_set_size"]
    if len(dataset) > 1 and val_fraction > 0 and not args.dry_run:
        split = dataset.train_test_split(test_size=val_fraction, seed=cfg["seed"])
        train_dataset, eval_dataset = split["train"], split["test"]
        eval_strategy = "epoch"
    else:
        train_dataset, eval_dataset, eval_strategy = dataset, None, "no"

    sft_config = SFTConfig(
        output_dir=str(args.output_dir),
        max_length=cfg["sequence_len"],
        packing=cfg["sample_packing"],
        assistant_only_loss=not cfg["train_on_inputs"],
        # Fused linear cross-entropy: Qwen2.5's 152k vocab makes the fp32 logit
        # projection the VRAM peak on a 16 GB card. Liger computes the loss
        # without materializing the full logits tensor, which is what lets the
        # 14B QLoRA run fit under the ~15.5 GB budget (dry-run OOM'd without it).
        use_liger_kernel=True,
        per_device_train_batch_size=cfg["micro_batch_size"],
        per_device_eval_batch_size=cfg["micro_batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation_steps"],
        num_train_epochs=epochs,
        optim=cfg["optimizer"],
        lr_scheduler_type=cfg["lr_scheduler"],
        learning_rate=cfg["learning_rate"],
        warmup_ratio=cfg["warmup_ratio"],
        weight_decay=cfg["weight_decay"],
        max_grad_norm=cfg["max_grad_norm"],
        bf16=cfg["bf16"],
        tf32=cfg["tf32"],
        gradient_checkpointing=cfg["gradient_checkpointing"],
        gradient_checkpointing_kwargs={"use_reentrant": False},
        seed=cfg["seed"],
        logging_steps=cfg["logging_steps"],
        save_strategy="no" if args.dry_run else cfg["save_strategy"],
        save_total_limit=cfg["save_total_limit"],
        eval_strategy=eval_strategy,
        report_to=[],
        dataset_kwargs={"skip_prepare_dataset": False},
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
        peft_config=_build_lora_config(cfg),
    )

    print(f"[train] examples={len(train_dataset)} epochs={epochs} dry_run={args.dry_run}")
    trainer.train()

    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        trainer.save_model(str(args.output_dir))
        # Save the PRISTINE base tokenizer, NOT the training-time
        # generation-tagged template: that template renders assistant turns
        # unconditionally and has no add_generation_prompt branch, so loading
        # it from the adapter dir for inference would drop the assistant prompt.
        AutoTokenizer.from_pretrained(cfg["base_model"]).save_pretrained(
            str(args.output_dir)
        )
        print(f"[done] adapter saved to {args.output_dir}")
    else:
        peak = torch.cuda.max_memory_allocated() / 1e9
        print(f"[dry-run done] peak VRAM allocated: {peak:.2f} GB")


if __name__ == "__main__":
    main()
