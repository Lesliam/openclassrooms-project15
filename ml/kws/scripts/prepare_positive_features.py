"""Generate augmented spectrogram features for the positive wake-word corpus.

Reads the synthetic "hello lingorm" wav clips produced by piper-sample-generator,
applies microWakeWord's augmentation pipeline, and writes RaggedMmap spectrogram
feature sets for the training, validation and testing splits.

Background-noise augmentation is intentionally disabled: no external background
corpus (AudioSet / FMA) is available in this run. Room-impulse-response (RIR)
augmentation uses the impulse responses bundled with piper-sample-generator.
This is a documented limitation of the run, not the upstream default.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict

from mmap_ninja.ragged import RaggedMmap

from microwakeword.audio.augmentation import Augmentation
from microwakeword.audio.clips import Clips
from microwakeword.audio.spectrograms import SpectrogramGeneration

# Feature framing must match the pre-generated negative datasets: 10 ms step.
STEP_MS = 10
AUGMENTATION_DURATION_S = 3.2
SPLIT_COUNT = 0.1
RANDOM_SPLIT_SEED = 10

# (clips split name, output subdir, slide_frames, repetition)
SPLIT_PLAN = [
    ("train", "training", 10, 2),
    ("validation", "validation", 10, 1),
    ("test", "testing", 1, 1),
]

AUGMENTATION_PROBABILITIES: Dict[str, float] = {
    "SevenBandParametricEQ": 0.1,
    "TanhDistortion": 0.1,
    "PitchShift": 0.1,
    "BandStopFilter": 0.1,
    "AddColorNoise": 0.25,
    "AddBackgroundNoise": 0.0,  # disabled: no external background corpus
    "Gain": 1.0,
    "GainTransition": 0.25,
    "RIR": 0.5,
}


def build_clips(positives_dir: Path) -> Clips:
    return Clips(
        input_directory=str(positives_dir),
        file_pattern="*.wav",
        max_clip_duration_s=None,
        remove_silence=False,
        random_split_seed=RANDOM_SPLIT_SEED,
        split_count=SPLIT_COUNT,
    )


def build_augmenter(impulse_dir: Path) -> Augmentation:
    impulse_paths = [str(impulse_dir)] if impulse_dir.is_dir() else []
    return Augmentation(
        augmentation_duration_s=AUGMENTATION_DURATION_S,
        augmentation_probabilities=AUGMENTATION_PROBABILITIES,
        impulse_paths=impulse_paths,
        background_paths=[],
        min_jitter_s=0.195,
        max_jitter_s=0.205,
    )


def generate_split(
    clips: Clips,
    augmenter: Augmentation,
    output_root: Path,
    split_name: str,
    output_subdir: str,
    slide_frames: int,
    repetition: int,
) -> None:
    out_dir = output_root / output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    spectrograms = SpectrogramGeneration(
        clips=clips,
        augmenter=augmenter,
        step_ms=STEP_MS,
        slide_frames=slide_frames,
    )

    RaggedMmap.from_generator(
        out_dir=str(out_dir / "wakeword_mmap"),
        sample_generator=spectrograms.spectrogram_generator(
            split=split_name, repeat=repetition
        ),
        batch_size=100,
        verbose=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positives-dir", required=True, type=Path)
    parser.add_argument("--impulse-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    clips = build_clips(args.positives_dir)
    augmenter = build_augmenter(args.impulse_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split_name, output_subdir, slide_frames, repetition in SPLIT_PLAN:
        generate_split(
            clips=clips,
            augmenter=augmenter,
            output_root=args.output_dir,
            split_name=split_name,
            output_subdir=output_subdir,
            slide_frames=slide_frames,
            repetition=repetition,
        )
        print(f"[prepare_positive_features] wrote split '{output_subdir}'")


if __name__ == "__main__":
    main()
