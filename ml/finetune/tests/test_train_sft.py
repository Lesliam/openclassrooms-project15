"""Pure-logic unit tests for ``train_sft`` (no model load, CPU-only).

These exercise only the config-mapping and corpus-loading helpers, which build
plain config objects / read tiny temp files. Nothing here loads the 14B model,
touches the GPU, or trains — the heavy ``AutoModelForCausalLM.from_pretrained``
call lives in ``main`` and is never invoked.

Covered:
1. ``_load_config`` round-trips a YAML file into a dict.
2. ``_build_bnb_config`` maps the QLoRA quant keys -> BitsAndBytesConfig
   (nf4 + double quant + bfloat16 compute).
3. ``_build_lora_config`` maps the LoRA keys -> LoraConfig
   (r=16, alpha=32, the 7 attention/MLP target modules).
4. ``_load_corpus`` truncates to ``max_examples``.
5. ``_CHATML_WITH_GENERATION`` carries the {% generation %} markers the
   assistant_only_loss mask depends on (regression guard).
"""

from __future__ import annotations

import json
from pathlib import Path

import torch

import train_sft

_EXPECTED_TARGET_MODULES = {
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
}


def test_load_config_maps_yaml_to_dict(tmp_path: Path) -> None:
    yaml_path = tmp_path / "cfg.yaml"
    yaml_path.write_text(
        "lora_r: 16\n"
        "lora_alpha: 32\n"
        "seed: 42\n"
        "targets:\n"
        "  - a\n"
        "  - b\n",
        encoding="utf-8",
    )
    cfg = train_sft._load_config(yaml_path)
    assert cfg == {
        "lora_r": 16,
        "lora_alpha": 32,
        "seed": 42,
        "targets": ["a", "b"],
    }


def test_build_bnb_config_maps_qlora_quant_keys() -> None:
    cfg = {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
        "bnb_4bit_compute_dtype": "bfloat16",
    }
    bnb = train_sft._build_bnb_config(cfg)
    assert bnb.load_in_4bit is True
    assert bnb.bnb_4bit_quant_type == "nf4"
    assert bnb.bnb_4bit_use_double_quant is True
    assert bnb.bnb_4bit_compute_dtype == torch.bfloat16


def test_build_bnb_config_compute_dtype_float16_variant() -> None:
    # The dtype string is looked up in _BNB_QUANT_DTYPE; float16 must resolve too.
    cfg = {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
        "bnb_4bit_compute_dtype": "float16",
    }
    bnb = train_sft._build_bnb_config(cfg)
    assert bnb.bnb_4bit_compute_dtype == torch.float16


def test_build_lora_config_maps_lora_keys() -> None:
    cfg = {
        "lora_r": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "lora_target_modules": [
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    }
    lora = train_sft._build_lora_config(cfg)
    assert lora.r == 16
    assert lora.lora_alpha == 32
    assert lora.lora_dropout == 0.05
    # LoraConfig stores target_modules as a set; assert the exact 7 modules.
    assert set(lora.target_modules) == _EXPECTED_TARGET_MODULES
    assert len(_EXPECTED_TARGET_MODULES) == 7
    assert lora.bias == "none"
    assert str(lora.task_type) == "CAUSAL_LM"


def test_build_lora_config_uses_shipped_yaml(tmp_path: Path) -> None:
    # End-to-end on the real sft_config.yaml: the shipped config must still
    # produce the r=16 / alpha=32 / 7-module adapter the experiment claims.
    shipped = Path(train_sft.__file__).resolve().parent / "sft_config.yaml"
    cfg = train_sft._load_config(shipped)
    lora = train_sft._build_lora_config(cfg)
    assert lora.r == 16
    assert lora.lora_alpha == 32
    assert set(lora.target_modules) == _EXPECTED_TARGET_MODULES


def _write_jsonl(path: Path, n: int) -> None:
    lines = [
        json.dumps(
            {
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": f"u{i}"},
                    {"role": "assistant", "content": f"a{i}"},
                ]
            }
        )
        for i in range(n)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_corpus_truncates_to_max_examples(tmp_path: Path) -> None:
    jsonl = tmp_path / "corpus.jsonl"
    _write_jsonl(jsonl, 5)
    dataset = train_sft._load_corpus(jsonl, max_examples=2)
    assert len(dataset) == 2
    assert dataset[0]["messages"][1]["content"] == "u0"


def test_load_corpus_max_examples_none_keeps_all(tmp_path: Path) -> None:
    jsonl = tmp_path / "corpus.jsonl"
    _write_jsonl(jsonl, 3)
    dataset = train_sft._load_corpus(jsonl, max_examples=None)
    assert len(dataset) == 3


def test_load_corpus_max_examples_over_length_clamps(tmp_path: Path) -> None:
    jsonl = tmp_path / "corpus.jsonl"
    _write_jsonl(jsonl, 3)
    dataset = train_sft._load_corpus(jsonl, max_examples=10)
    assert len(dataset) == 3


def test_chatml_template_carries_generation_markers() -> None:
    # The assistant_only_loss mask is emitted only if the template wraps the
    # assistant content in {% generation %} ... {% endgeneration %}. Losing
    # these markers silently trains on an empty mask (see _assert_assistant_mask).
    template = train_sft._CHATML_WITH_GENERATION
    assert "{% generation %}" in template
    assert "{% endgeneration %}" in template
    assert template.index("{% generation %}") < template.index("{% endgeneration %}")
