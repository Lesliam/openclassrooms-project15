# On-device wake word — "hello lingorm" (microWakeWord)

Keyword-spotting (KWS) model that runs on the ESP32-S3 terminal and opens the
Coach FR voice pipeline on the phrase **"hello lingorm"**. This directory holds
the training pipeline, the reproducible trainer image, and the deployable
artifacts. It is the KWS half of the project's model-lifecycle story
(train -> quantize -> package -> deploy -> monitor -> retrain).

## Why an English phrase

The high-diversity LibriTTS-R multi-speaker sample generator is English-only.
A French wake word would fall back to a few single-speaker Piper voices (higher
overfitting risk, lower proven quality). "hello lingorm" keeps the multi-speaker
generator, trading a French phrase for model robustness. The lifecycle and the
MLOps story are identical either way.

## Pipeline

| Stage | Script | Notes |
|---|---|---|
| Positive corpus | (rhasspy/piper-sample-generator, LibriTTS-R) | 5000 multi-speaker clips of the phrase, CPU |
| Features | `scripts/prepare_positive_features.py` | augmentation + 40-feature/10 ms spectrograms |
| Training config | `scripts/make_training_config.py` -> `training_parameters.yaml` | mixednet, 10k steps, INT8 quant |
| Train + quantize | `scripts/train_in_container.sh` | runs inside the trainer image; exports the streaming INT8 tflite |
| Manifest | `scripts/make_manifest.py` -> `models/hello_lingorm.json` | ESPHome micro_wake_word v2 schema |

Negatives are the pre-generated `kahrendt/microwakeword` spectrogram features
(speech / no-speech / dinner-party). They are large (~9.7 GB) and are NOT
committed; download them before reproducing.

## Trainer image (Blackwell / RTX 5080)

`Dockerfile.train` builds on `nvcr.io/nvidia/tensorflow:25.02-tf2-py3` (NVIDIA
official registry; CUDA 12.8, required for Blackwell sm_120 — official pip
TensorFlow bundles an older CUDA and cannot drive the GPU). `container-constraints.txt`
freezes numpy/TensorFlow so no dependency upgrades the GPU-critical stack;
`scripts/sitecustomize.py` is a small numpy-1.26 compatibility shim.

Reproduce (after downloading the negative dataset and generating positives):

```bash
docker build -f Dockerfile.train -t coach-kws-train:1.0 .
bash scripts/train_in_container.sh   # GPU; exports models/hello_lingorm.tflite
python scripts/make_manifest.py      # writes models/hello_lingorm.json
```

The upstream `OHF-Voice/micro-wake-word` is used as an external input with a
two-line pin relaxation in its `setup.py` (numpy>=1.26, tensorflow>=2.17); it is
not vendored here.

## Artifacts

- `models/hello_lingorm.tflite` — INT8 streaming model (~60 KB). Verified to load:
  input int8 `[1, 3, 40]`, output uint8 `[1, 1]`.
- `models/hello_lingorm.json` — ESPHome v2 manifest. Operating point
  `probability_cutoff = 0.87`. `tensor_arena_size` is a starting value copied
  from same-architecture reference models; ESPHome computes the true arena at
  compile time — raise it if the model fails to load on device.

## Evaluation (and its limits)

Measured on the quantized streaming model (false-reject on held-out positives,
false-accepts/hour on the dinner-party ambient set):

| probability_cutoff | false-reject | recall | false-accepts / hour |
|---|---|---|---|
| 0.87 | 0.00 | 100 % | 0.19 |
| 0.81 | 0.00 | 100 % | 0.75 |
| 0.50 | 0.00 | 100 % | 1.31 |

These numbers are **optimistic**: held-out positives come from the same TTS
generator as training, and positive augmentation lacked real background noise.
Real-microphone recall and false-accepts will be worse. A real-room / real-voice
false-accept check on the physical terminal is the pending validation gate
before this is treated as production-ready.

## Deployment

The model is embedded at compile time via the ESPHome `micro_wake_word`
component (see `../../firmware/esphome/coach-terminal.yaml`); updates reach the
device by recompiling and OTA-flashing. The device exposes detection events, not
per-inference confidence, so drift monitoring is built on activation-rate
statistics plus periodic offline re-evaluation.

## Tests

`tests/` validates the shipped artifacts (tflite loads with expected I/O, the
manifest is a well-formed v2 schema, the config parses).
