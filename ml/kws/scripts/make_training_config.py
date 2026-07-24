"""Write the microWakeWord training configuration for the "hello lingorm" model.

Paths are expressed relative to the working directory so the same config works
on the host and inside the training container (mounted at the same relative
root). Feature directories point at the double-nested layout produced by
unzipping the kahrendt/microwakeword negative feature archives.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

import yaml

NEG_ROOT = "data/kahrendt-microwakeword"


def build_features() -> List[Dict[str, Any]]:
    return [
        {
            "features_dir": "data/generated_augmented_features",
            "sampling_weight": 2.0,
            "penalty_weight": 1.0,
            "truth": True,
            "truncation_strategy": "truncate_start",
            "type": "mmap",
        },
        {
            "features_dir": f"{NEG_ROOT}/speech/speech",
            "sampling_weight": 10.0,
            "penalty_weight": 1.0,
            "truth": False,
            "truncation_strategy": "random",
            "type": "mmap",
        },
        {
            "features_dir": f"{NEG_ROOT}/dinner_party/dinner_party",
            "sampling_weight": 10.0,
            "penalty_weight": 1.0,
            "truth": False,
            "truncation_strategy": "random",
            "type": "mmap",
        },
        {
            "features_dir": f"{NEG_ROOT}/no_speech/no_speech",
            "sampling_weight": 5.0,
            "penalty_weight": 1.0,
            "truth": False,
            "truncation_strategy": "random",
            "type": "mmap",
        },
        {
            # Validation/testing ambient set only (false-accepts-per-hour metric).
            "features_dir": f"{NEG_ROOT}/dinner_party_eval/dinner_party_eval",
            "sampling_weight": 0.0,
            "penalty_weight": 1.0,
            "truth": False,
            "truncation_strategy": "split",
            "type": "mmap",
        },
    ]


def build_config(train_dir: str) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    config["window_step_ms"] = 10
    config["train_dir"] = train_dir
    config["features"] = build_features()

    # Single-stage schedule keeps the lifecycle run bounded on the GPU.
    config["training_steps"] = [10000]
    config["positive_class_weight"] = [1]
    config["negative_class_weight"] = [20]
    config["learning_rates"] = [0.001]
    config["batch_size"] = 128

    config["time_mask_max_size"] = [0]
    config["time_mask_count"] = [0]
    config["freq_mask_max_size"] = [0]
    config["freq_mask_count"] = [0]

    config["eval_step_interval"] = 500
    config["clip_duration_ms"] = 1500

    config["target_minimization"] = 0.9
    config["minimization_metric"] = None
    config["maximization_metric"] = "average_viable_recall"
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-dir", default="trained_models/hello_lingorm")
    parser.add_argument("--output", type=Path, default=Path("training_parameters.yaml"))
    args = parser.parse_args()

    config = build_config(args.train_dir)
    with args.output.open("w") as handle:
        yaml.dump(config, handle, sort_keys=False)
    print(f"[make_training_config] wrote {args.output}")


if __name__ == "__main__":
    main()
