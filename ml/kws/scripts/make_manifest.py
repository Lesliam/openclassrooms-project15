"""Write the ESPHome micro_wake_word v2 model manifest for the trained model.

Schema mirrors the official esphome/micro-wake-word-models v2 format
(models/v2/*.json). tensor_arena_size defaults to the value reported by the
microWakeWord conversion step; probability_cutoff should be tuned from the
streaming evaluation false-accept / recall trade-off.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def build_manifest(
    wake_word: str,
    model_filename: str,
    trained_languages: list[str],
    probability_cutoff: float,
    sliding_window_size: int,
    tensor_arena_size: int,
    minimum_esphome_version: str,
    author: str,
    website: str,
) -> Dict[str, Any]:
    return {
        "type": "micro",
        "wake_word": wake_word,
        "author": author,
        "website": website,
        "model": model_filename,
        "trained_languages": trained_languages,
        "version": 2,
        "micro": {
            "probability_cutoff": probability_cutoff,
            "sliding_window_size": sliding_window_size,
            "feature_step_size": 10,
            "tensor_arena_size": tensor_arena_size,
            "minimum_esphome_version": minimum_esphome_version,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wake-word", default="hello lingorm")
    parser.add_argument("--model-filename", default="hello_lingorm.tflite")
    parser.add_argument("--trained-languages", default="en")
    parser.add_argument("--probability-cutoff", type=float, default=0.87)
    parser.add_argument("--sliding-window-size", type=int, default=5)
    parser.add_argument("--tensor-arena-size", type=int, default=26080)
    parser.add_argument("--minimum-esphome-version", default="2024.7.0")
    parser.add_argument("--author", default="P15 Coach Vocal FR")
    parser.add_argument("--website", default="")
    parser.add_argument("--output", type=Path, default=Path("hello_lingorm.json"))
    args = parser.parse_args()

    manifest = build_manifest(
        wake_word=args.wake_word,
        model_filename=args.model_filename,
        trained_languages=[s.strip() for s in args.trained_languages.split(",")],
        probability_cutoff=args.probability_cutoff,
        sliding_window_size=args.sliding_window_size,
        tensor_arena_size=args.tensor_arena_size,
        minimum_esphome_version=args.minimum_esphome_version,
        author=args.author,
        website=args.website,
    )
    with args.output.open("w") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"[make_manifest] wrote {args.output}")


if __name__ == "__main__":
    main()
