# Retrain `hello_lingorm` with real voice

## Why

The shipped model (`models/hello_lingorm.tflite`) was trained ONLY on 5000
synthetic piper / LibriTTS-R speakers. On-device recall on the owner's real
voice/accent measured **~1/8**. Lowering the probability cutoff (0.5 -> 0.4,
already applied in `models/hello_lingorm.json`) is a cheap partial mitigation,
but the real fix is to fold real-voice positives into the corpus and retrain.

**Honest caveat — channel mismatch.** Recording is done on the desktop headset
mic, not the on-device INMP441 I2S MEMS mic that runs the wake word in the
field. This closes the dominant gap (the owner's phonetics/accent vs synthetic
speakers) but not the microphone-channel gap. The pipeline's RIR + EQ + color-
noise augmentation partially simulates channel variation, so this is a large,
pragmatic improvement — not a perfect field match. If recall is still weak after
this, the next step is capturing a few positives through the device mic itself.

## Background-noise augmentation (do this — it is the biggest lever)

Every positive clip used to train `hello_lingorm.tflite` so far (synthetic AND
the real-voice batch from step 1 below) went through `Augmentation` with
`AddBackgroundNoise` probability **0.0** and `background_paths=[]` — the model
has never once seen its own wake phrase mixed with room noise (fan hum, TV,
traffic, other people talking). It was trained and evaluated on clean/quiet
audio only. On-device the ESP32 mic always picks up some ambient noise, so
this is very likely a bigger contributor to the ~1/8 real-voice recall miss
than accent/phonetics alone — fixing it costs one flag, not a re-recording
session.

A background-noise corpus is now available at
`~/dev/coach-kws/data/background_noise/` (2000 clips, ESC-50, see
provenance below). Both feature-extraction commands below now accept
`--background-dir` — when passed, it sets `AddBackgroundNoise` probability
to 0.75 (matching microWakeWord's own upstream default) and points
`background_paths` at the corpus. **Regenerate BOTH the synthetic and the
real-voice feature sets with this flag** — mixing a noise-augmented positive
source with a clean one in the same training run would just teach the model
inconsistent cues, so both must be regenerated together, not just the new
real-voice batch.

```bash
cd ~/dev/coach-kws
source .venv/bin/activate

# Synthetic corpus (regenerate to add noise augmentation)
python scripts/prepare_positive_features.py \
  --positives-dir data/positives_hello_lingorm \
  --impulse-dir   psg-src/piper_sample_generator/impulses \
  --background-dir data/background_noise \
  --output-dir    data/generated_augmented_features

deactivate
```

Corpus provenance: **ESC-50** (Karol Piczak, `github.com/karolpiczak/ESC-50`),
2000 five-second environmental-sound clips, CC BY-NC 3.0 license (fine for
this non-commercial student project), downloaded from the official archive
link `https://github.com/karoldvl/ESC-50/archive/master.zip` (~600 MB), then
resampled to 16 kHz mono WAV (matching the pipeline's native rate) into a flat
directory — 313 MB on disk. License + per-clip attribution copied to
`data/background_noise_LICENSE.txt`, class metadata to
`data/background_noise_esc50_meta.csv`.

All heavy work happens in the training env `~/dev/coach-kws/` (59 GB, intact:
51 GB kahrendt negatives, `data/positives_hello_lingorm`, augmented features,
`trained_models/`, `scripts/`, `Dockerfile.train`, `training_parameters.yaml`).
This repo (`project/ml/kws/`) holds the versioned pipeline copy + the deployed
model artifacts.

## Prerequisites

- The Blackwell trainer image `coach-kws-train:1.0` (built once from
  `Dockerfile.train`). Rebuild only if `docker images | grep coach-kws-train`
  is empty.
- A free GPU block. Training pauses `wyoming-whisper` via `gpu-solo` for ~15 min
  (household voice STT is briefly offline; auto-resumes on exit).

## Steps

### 1. Record real-voice positives (headset mic, ~10 min)

```bash
cd ~/wsl-home-yang/openclassrooms/project15/project/ml/kws
./scripts/record_real_positives.sh 60
# -> ~/dev/coach-kws/data/positives_hello_lingorm_real/{0..59}.wav
```

Aim for **50-100 clips** with natural variation (pace, volume, distance,
intonation). Re-run the script to add more; it resumes from the last index.
Delete any clip where you fumbled the phrase.

Sanity-check a few:

```bash
ls ~/dev/coach-kws/data/positives_hello_lingorm_real/*.wav | wc -l
ffplay -autoexit ~/dev/coach-kws/data/positives_hello_lingorm_real/0.wav
```

### 2. Extract augmented features for the real clips

```bash
cd ~/dev/coach-kws
source .venv/bin/activate
python scripts/prepare_positive_features.py \
  --positives-dir data/positives_hello_lingorm_real \
  --impulse-dir   psg-src/piper_sample_generator/impulses \
  --background-dir data/background_noise \
  --output-dir    data/generated_augmented_features_real
deactivate
```

This writes `training/`, `validation/`, `testing/` RaggedMmap spectrograms for
the real corpus, same framing (10 ms step, 3.2 s window) as the synthetic set.
`--background-dir` is included here to match the regenerated synthetic corpus
above (see "Background-noise augmentation" section) — omit it from BOTH
commands together if you decide to skip that improvement for this run.

### 3. Add the real corpus as a weighted positive source

Edit `~/dev/coach-kws/training_parameters.yaml`. The existing synthetic positive
source has `sampling_weight: 2.0`. Add a SECOND positive block, weighted HIGHER
so the model prioritizes the real voice while keeping synthetic generalization
(`sampling_weight` is per-batch draw probability, independent of clip count, so
this genuinely oversamples the real voice):

```yaml
features:
- features_dir: data/generated_augmented_features        # synthetic (keep)
  sampling_weight: 2.0
  penalty_weight: 1.0
  truth: true
  truncation_strategy: truncate_start
  type: mmap
- features_dir: data/generated_augmented_features_real    # NEW real voice
  sampling_weight: 4.0
  penalty_weight: 1.0
  truth: true
  truncation_strategy: truncate_start
  type: mmap
# ... negative sources unchanged ...
```

Leave the negative sources, `training_steps: [10000]`, and class weights as-is.

### 4. Train (GPU block, ~15 min)

```bash
cd ~/dev/coach-kws
gpu-solo bash scripts/train_in_container.sh
```

Exit code 0 + a printed evaluation sweep = success. New quantized model at:
`trained_models/hello_lingorm/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite`

### 5. Pick the operating cutoff from the printed sweep

The run prints a false-reject / false-accepts-per-hour table over cutoffs. Note
this is still measured on synthetic held-out positives (real held-out is a small
slice from step 2), so treat it as guidance, not ground truth. Start deployment
at **0.4-0.5** and tune on-device toward >=7/10 real wakes with tolerable false
accepts.

### 6. Deploy into the repo + reflash

```bash
cd ~/wsl-home-yang/openclassrooms/project15/project/ml/kws
cp ~/dev/coach-kws/trained_models/hello_lingorm/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite \
   models/hello_lingorm.tflite
# keep models/hello_lingorm.json; set "probability_cutoff" to the chosen value
```

Then reflash `firmware/esphome/coach-terminal-faces-drawn.yaml` (it packages
`coach-terminal-base.yaml`, which references `../../ml/kws/models/hello_lingorm.json`).
Retest wake recall on-device.

## Fallback for a reliable demo / soutenance

If real-voice recall is still not demo-grade in time, flash the stock
`okay_nabu` microWakeWord model (excellent recall) for the live demo, and keep
`hello_lingorm` as the CS-152 custom-KWS lifecycle deliverable/story (train ->
quantize -> deploy -> measure -> retrain-with-real-voice). The retrain cycle
documented here IS the "one retrain cycle demonstrated" W3 deliverable, whether
or not it becomes the demo model.
