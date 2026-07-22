# Second KWS model: end-word "j'ai fini" (CS-159 chantier 1)

Prep document, kept as an append-only working log. Status 2026-07-22: both
corpora and both feature sets are BUILT (99 real + 4961 synthetic clips, see
§2f and the §(c0) current-state table); the trained INT8 model ships at `models/jai_fini.tflite` with its
threshold sweep in `models/jai_fini_tflite_streaming_roc.txt`, and the live
on-device validation is in `firmware/esphome/HW_VALIDATION_CS159.md`. Early
sections that read "empty" or "not yet executed" describe the pre-run state
and are kept for traceability. Interactive steps are for the owner to run in
their own terminal, in the order given.

This model is fully independent from `hello_lingorm`. Every path used here is
new; no existing hello_lingorm file (positives, features, `training_parameters.yaml`,
`trained_models/hello_lingorm/`, `scripts/*.sh` without the `_jai_fini` suffix,
repo `models/hello_lingorm.*`) is read-modify-written by this pipeline.

## 0. What was created by this prep pass

| Path | Purpose |
|---|---|
| `data/positives_jai_fini/` | empty; target for the SYNTHETIC corpus (step c) |
| `data/positives_jai_fini_real/` | empty; target for the owner's REAL recordings (step a) |
| `scripts/record_real_positives_jai_fini.sh` | recording harness, executable, phrase "j'ai fini" |
| `training_parameters_jai_fini.yaml` | training config, `train_dir: trained_models/jai_fini` |
| `scripts/train_in_container_jai_fini.sh` | container training launcher pointing at the config above |
| `scripts/prepare_positives_jai_fini.py` | trim to phrase, optional duration filter, optional peak-normalize |
| `PREP_JAI_FINI.md` | this file |

Shared, unmodified, reused as-is: `scripts/prepare_positive_features.py`
(already parameterised by `--positives-dir` / `--output-dir`), `scripts/make_manifest.py`
(already parameterised), `data/background_noise/` (ESC-50), `data/kahrendt-microwakeword/`
(negatives), `psg-src/` (generator), `.venv` and `.venv-gen`.

Two positives directories, not one, is deliberate: it mirrors the hello_lingorm
layout (`positives_hello_lingorm` synthetic 22050 Hz + `positives_hello_lingorm_real`
16 kHz headset) and is required by the two-source weighted feature config, which
oversamples the real voice 4.0 against synthetic 2.0. Mixing both corpora in one
directory would collapse that weighting.

## 1. Disk space

`df -h /home` at prep time: filesystem `/dev/nvme0n1p2`, 1.9 T total, 730 G used,
**1.2 T available** (40 % used). `~/dev/coach-kws` currently occupies 63 G.

Expected additional cost for this model, extrapolated from the measured
hello_lingorm footprint (`data/generated_augmented_features_noise` = 4.0 G for
5000 synthetic clips, `data/generated_augmented_features_real` = 47 M for 58 real
clips): about **4.1 G of features** plus about **1 G of raw synthetic wavs**
(5000 x ~0.9 s at 22050 Hz mono 16-bit). Roughly 5 G total. There is ample room.

## 2. Steps

### (a) Owner recording session -- owner's own terminal

A shell without a seat records silence; this must be run interactively by the
owner at the machine, in a seated session.

Before starting: set the mic input level to **100 % / 0 dB**. Session 22 used
150 % / +10 dB and clipped every clip.

```bash
cd ~/dev/coach-kws
./scripts/record_real_positives_jai_fini.sh 60
# -> data/positives_jai_fini_real/{0..59}.wav  (16 kHz mono 16-bit PCM)
```

Target **>= 60 clips**, 50-100 is the useful band. The script is resumable: re-run
it to append more clips, it continues from the highest existing index. Delete any
clip where the phrase was fumbled.

Variation to aim for: normal / faster / slower pace, softer / louder, varying
distance, and both the elided rendition ("j'ai fini" run together) and one with a
small pause after "j'ai". Because this is an end-word rather than a wake word, say
it the way a turn actually ends, not as an isolated barked command.

If the default mic source name does not resolve, list sources with
`pactl list short sources` and pass the right one as the third argument.

### (a2) Real-clip preparation -- DONE for the 60 delivered clips

Recorded clips are trimmed and normalized in one step. The raw directory is the
provenance copy and is never modified:

```bash
cd ~/dev/coach-kws
python3 scripts/prepare_positives_jai_fini.py \
  --source-dir data/positives_jai_fini_real_raw \
  --dest-dir   data/positives_jai_fini_real \
  --target-peak-db -6.0
```

No `--max-duration` filter is applied to real clips: they are scarce (60) and, after
trimming, all 60 measure at most 1.06 s, comfortably inside the 1.3 s bound. Result
for the delivered batch: **60/60 fully in-window at 1500 ms, 100 % mean coverage**,
trimmed duration min 0.38 s / p50 0.67 s / max 1.06 s, all peaks exactly -6.0 dB.

### (b) WAV quality gate

Pass criterion, same as session 22: `max_volume` between **-3 dB and -8 dB**, and
**no clip at 0.0 dB** (0.0 dB means the signal hit full scale and is clipped).

```bash
cd ~/dev/coach-kws
for f in data/positives_jai_fini_real/*.wav; do
  peak=$(ffmpeg -hide_banner -nostats -i "$f" -af volumedetect -f null /dev/null 2>&1 \
         | grep max_volume | sed 's/.*max_volume: //')
  printf '%s\t%s\n' "$(basename "$f")" "$peak"
done | tee /tmp/jai_fini_levels.txt

# clipped clips (must be zero rows):
grep -c ' 0.0 dB' /tmp/jai_fini_levels.txt

# out-of-band clips (peak louder than -3 dB or quieter than -8 dB):
awk -F'\t' '{gsub(/ dB/,"",$2); if ($2 > -3.0 || $2 < -8.0) print}' /tmp/jai_fini_levels.txt
```

If more than a handful of clips are out of band, adjust the mic level and re-record
those indices rather than proceeding: the feature pipeline applies a `Gain`
augmentation with probability 1.0, so a clipped source stays clipped through
training.

Spot-check by ear: `ffplay -autoexit data/positives_jai_fini_real/0.wav`.

Count check: `ls data/positives_jai_fini_real/*.wav | wc -l`.

## 2e. ROOT CAUSE: the MLS generator checkpoint ignores short text

The first listening gate failed outright: none of the 12 variant-C smoke clips said
"j'ai fini". Transcription with faster-whisper returned fluent but unrelated French
("Ah oui, ah oui.", "Vas-y, vas-y, vas-y !", "Au revoir."). Everything in section 2c
about "slow MLS speakers" is therefore **retracted as well** -- the clips were not
slow renditions of the phrase, they were unconditioned babble, which also explains
the 2-4 s durations.

### What was ruled out, with evidence

- **Phoneme-to-ID mismatch: NOT the cause.** `piper_sample_generator/__main__.py`
  line 455 reads `config["phoneme_id_map"]` from the model's own `.pt.json`, and the
  espeak `fr` phonemes for "j'ai fini." (`ʒ e _ f i n ˈ i .`) are all present in it.
  The French and English id maps are in fact byte-identical (159 symbols, max id 158).
- **Checkpoint incompatibility: NOT the cause.** Both checkpoints load as the same
  class `SynthesizerTrn` with the same symbol embedding shape `enc_p.emb.weight
  (256, 192)`; only the speaker table differs (French 125, English 904).
- **Speaker sampling / slerp: NOT the cause.** Failure reproduces identically with
  `--max-speakers 1`, with no speaker cap, and with the generator defaults.

### What the controlled battery showed

Each row is 3 clips, transcribed with faster-whisper (small, CPU, beam 5).

| model | text | result |
|---|---|---|
| French `.pt` | "j'ai fini." | babble, 0/3 |
| French `.pt` | "hello lingorm." | babble, 0/3 |
| French `.pt` | "J'ai fini de travailler pour aujourd'hui." | **correct, 3/3** |
| French `.pt` | "Bonjour, je m'appelle Pierre et j'habite à Paris depuis dix ans." | **correct, 3/3** |
| English `.pt` | "j'ai fini." | attempts it ("J. I. Fini.") |
| English `.pt` | "hello lingorm." | correct |

The failing axis is **utterance length, not text content, not language, not the id
map**. `fr_FR-mls-medium` renders long sentences correctly and degenerates into
unconditioned speech below roughly six or seven words. MLS is audiobook data with
long utterances; LibriTTS-R (the English model used in phase 1) contains short
utterances, which is why phase 1 never hit this.

Short carrier sentences do not rescue it: "J'ai fini. Voilà.", "Alors, j'ai fini.",
"Bon. J'ai fini." and "Voilà, j'ai fini." all still babble. Only genuinely long
sentences work, and those would need forced alignment to cut the phrase back out.

The same failure occurs with the MLS voice exported as `.onnx` (0/6 correct), so it
is the MLS corpus, not the export format.

### The fix: Piper `.onnx` voices, which are built for short utterances

`piper_sample_generator` also accepts Piper voice `.onnx` models, and its `.onnx`
code path iterates `speaker_id` over the voice's speakers and respects
`--max-speakers`. Four French voices from `rhasspy/piper-voices` (same upstream
organisation as the generator, downloaded from the canonical HF repo) were each
validated independently at 8 clips:

| voice | speakers | gate result | note |
|---|---|---|---|
| `fr_FR-tom-medium` | 1 | **8/8** | 44.1 kHz source |
| `fr_FR-siwis-medium` | 1 | **7/8** | 22.05 kHz |
| `fr_FR-upmc-medium` | 2 | 0/16 | renders "et finit" / "c'est fini" -- "j'ai" is lost |
| `fr_FR-gilles-low` | 1 | 0/8 | renders "je finis" -- wrong phrase |

The upmc failure was checked against the untrimmed originals to rule out the trim
step clipping the initial fricative; raw and trimmed transcribe identically, so the
voice itself is at fault, not the preprocessing.

**Proven configuration: `fr_FR-siwis-medium` + `fr_FR-tom-medium`.** A 40-clip batch
through the full recipe (generate, trim, filter, normalize) scored **40/40 = 100 %**
on the whisper gate, against the 90 % threshold, with no clips dropped by the 1.3 s
filter (durations 0.58 / p50 0.77 / max 1.07 s). p50 0.77 s is also a close match to
the user's own 0.66 s delivery.

### Cost of the fix, stated plainly

Synthetic speaker diversity collapses from a nominal 125 to **2**. Prosodic variety
comes only from the generator's 4 length-scales x 6 noise-scales x 1 noise-scale-w
grid (24 settings per voice) plus the KWS augmentation stage (RIR, EQ, pitch, colour
noise, background noise). The English `hello_lingorm` model had 800 speakers, so this
is a materially weaker synthetic corpus and the real recordings (weight 4.0) now
carry proportionally more of the burden.

Options if 2 speakers proves too thin, in increasing cost order:

1. Record more real clips -- the cheapest lever, and the corpus that actually drives
   on-device recall.
2. Add non-French Piper voices reading the French text for timbre variety, accepting
   a foreign accent on part of the synthetic corpus.
3. Unlock the 125-speaker MLS model by generating a long carrier sentence and cutting
   the phrase out with whisper word-level timestamps. This restores diversity but
   adds a transcription-and-alignment stage over every generated clip, which is
   roughly an hour of CPU per 5000 clips and introduces its own alignment error.

This decision is deferred; not made here.

## 2f. The whisper gate applies to synthetic clips ONLY

The intelligibility gate introduced in section 2e is correct for synthetic clips and
caught the MLS babble catastrophe. Applied to the **real** corpus it is badly
miscalibrated and must not be used there.

Run against all 101 real recordings it scored **21/101 = 20.8 %**, with the
"failures" reading "c'est fini", "Réfinie", "je finis", "le fini". Read literally
that condemns most of the user's corpus. It is wrong.

"j'ai fini" is [ʒe fini] and "c'est fini" is [se fini]: they differ only in the
voicing of the initial fricative, and "c'est fini" is far the commoner French phrase.
On a short isolated utterance whisper's language prior decides the transcript.
Evidence that the prior, not the audio, was deciding:

- untrimmed raw vs trimmed: 1/12 both, so the trim was not clipping the onset
- adding `initial_prompt="Il dit: j'ai fini."`: 1/12 rises to **5/12**, from biasing
  the prior alone
- whisper `medium` instead of `small`: 0/12, so it is not a model-capacity limit

Settled acoustically instead, with no language model in the loop. /ʒ/ is voiced and
carries energy at F0 with a low zero-crossing rate; /s/ is unvoiced frication with
energy above 4 kHz and a high zero-crossing rate. Both references were synthesized
with the same two voices, measuring the first 60 ms after onset:

| corpus | E<1kHz | E>4kHz | ZCR |
|---|---|---|---|
| reference synthetic "j'ai fini" | 0.790 | 0.083 | 0.140 |
| reference synthetic "c'est fini" | 0.000 | 0.998 | 0.744 |
| real user corpus (101) | **0.883** | **0.000** | **0.065** |

The real corpus sits past the voiced reference and nowhere near the unvoiced one.
The recordings say "j'ai fini". The 20.8 % was an artifact.

**Rule: gate synthetic corpora with whisper; gate real corpora with the onset-voicing
test above.** A transcription model asked to choose between two near-homophones will
answer with its prior, and the corpus that gets thrown away is the one that was fine.

Genuinely bad clips are found by a different signature -- no "fini" in any form, plus
an implausibly short duration. Exactly two of the 101 qualified (`68.wav` raw
"Je vais...", 0.26 s; `71.wav` raw "Riff", 0.20 s). Both moved to
`data/positives_jai_fini_real_rejected/`, raws retained, leaving **99 real clips**.

### (c0) DECIDED RECIPE -- read this before (c) and (d)

`clip_duration_ms` stays at **1500** (decision recorded 2026-07-22). No change to
`training_parameters_jai_fini.yaml`. The window is unchanged because the CS-159
concurrency budget is proven on-device only for the 1500 ms-class model, and because
post-trimming the corpora makes 1500 ms fit. See section 2c/2d for the measurements
and section "Recommendation" for the reasoning.

Consequences that the rest of this document assumes:

- Synthetic generation uses the **Piper `.onnx` voices `fr_FR-siwis-medium` and
  `fr_FR-tom-medium`**, at generator defaults. The `fr_FR-mls-medium.pt` generator
  checkpoint and the variant-A/B/C/D noise and length-scale tuning are **abandoned**
  -- see section 2e: that model ignores short text entirely. Defaults are correct
  here; the tuning existed only to work around the babble, and the measured output is
  already p50 0.77 s.
- Every positive clip, synthetic and real, is **post-trimmed** to the phrase before
  feature extraction, via `scripts/prepare_positives_jai_fini.py`. This is mandatory,
  not optional: leading silence is what pushes a phrase out of the 1500 ms window.
- Synthetic clips are additionally **filtered to a trimmed duration <= 1.3 s**
  (= 1500 ms window minus the 0.2 s jitter). With the Piper voices the measured
  keep-rate is **100 %** (40/40, durations 0.58-1.07 s), so generate **5000 raw for
  5000 usable**. The filter stays in the recipe as a safety net, not as a yield tax.
- Every batch is verified with the **automated intelligibility gate** before use:
  transcribe with faster-whisper and require >= 90 % of clips to match "j'ai fini".
  This gate exists because a generator can produce fluent, well-formed audio of
  entirely the wrong words, which no duration or level check would catch.
- Both corpora are **peak-normalized to -6 dB**. Required because the augmentation
  applies `Gain` at probability 1.0 over -45..0 dB and only ever attenuates, so it
  assumes near-full-scale input. -6 dB also leaves headroom for RIR and EQ
  augmentation, which can overshoot a clip already sitting at 0 dB.

Current state (both corpora and both feature sets BUILT, 2026-07-22):

| directory | contents |
|---|---|
| `data/positives_jai_fini_real_raw/` | **101** raw recordings, untouched provenance copy |
| `data/positives_jai_fini_real/` | **99** trimmed + normalized -- feature-step input |
| `data/positives_jai_fini_real_rejected/` | 2 fumbled takes (68, 71), quarantined, reversible |
| `data/positives_jai_fini/` | **4961** synthetic, trimmed + filtered + normalized |
| `data/positives_jai_fini_rawgen/` | 5000 raw generated clips (2500 siwis + 2500 tom) |
| `data/positives_jai_fini_smoke/` | 12 clips, passed the owner listening gate |
| `data/generated_augmented_features_jai_fini_noise/` | **3.9 GB**, splits 79360 / 4960 / 497 |
| `data/generated_augmented_features_jai_fini_real/` | **81 MB**, splits 1580 / 100 / 10 |

Voice split is **50/50** (2500 siwis + 2500 tom generated). An earlier 60/40 bias
toward siwis was reverted: it came from the owner finding siwis clearer by ear, but
that is a listening-quality judgement, and the synthetic corpus exists to teach
timbre generalization rather than to be listened to. With only two usable voices a
skew costs diversity for no measured benefit -- the gate scored both voices at
100 %.

Remaining step: GPU container training, `gpu-solo bash scripts/train_in_container_jai_fini.sh`.

### (c) Synthetic positive generation -- CPU, but needs a one-time model download

The hello_lingorm synthetic corpus was 5000 clips from
`rhasspy/piper-sample-generator` v3.2.0 with `en_US-libritts_r-medium.pt`
(904 speakers, `--max-speakers 800`), generated on CPU at about 10 samples/s.
That is roughly 8 minutes of CPU per 5000 clips; it does not need the GPU.

**French voice is not downloaded yet.** `psg-src/models/` currently contains only
`en_US-libritts_r-medium.pt` (204 MB). It does contain `fr_FR-mls-medium.pt.json`
(the config), which declares `language.code = fr_FR`, `num_speakers = 125`,
`phoneme_type = espeak`, `espeak.voice = fr`, `audio.sample_rate = 22050`. The
matching weights file is published as a release asset of the same upstream repo
(`rhasspy/piper-sample-generator`, tag `v2.0.0`) -- verified reachable
(HTTP 200) at prep time; it is not present under tag `v1.0.0` (404).

Provenance: same GitHub organisation `rhasspy` and same release tag already used
for the English model in phase 1, which was audited and accepted then. Re-verify
the download host and size before installing it.

```bash
cd ~/dev/coach-kws/psg-src/models
curl -L -o fr_FR-mls-medium.pt \
  'https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/fr_FR-mls-medium.pt'
ls -l fr_FR-mls-medium.pt          # sanity: should be on the order of 100-250 MB
```

Then generate, CPU-only (the GPU is reserved; `CUDA_VISIBLE_DEVICES=""` keeps this
off the card entirely and leaves wyoming-whisper untouched):

```bash
cd ~/dev/coach-kws
PSG=/home/yang/wsl-home-yang/dev/coach-kws/psg-src
GENPY=/home/yang/wsl-home-yang/dev/coach-kws/.venv-gen/bin/python

M=$PSG/models/fr_onnx

# 1. Generate 5000 raw clips from the two validated Piper voices, CPU only.
#    Measured throughput: 40 clips in about 6 s, so roughly 13 min for 5000.
CUDA_VISIBLE_DEVICES="" PYTHONPATH=$PSG $GENPY -m piper_sample_generator "j'ai fini." \
  --model $M/fr_FR-siwis-medium.onnx \
  --model $M/fr_FR-tom-medium.onnx \
  --max-samples 5000 \
  --output-dir data/positives_jai_fini_rawgen/

# 2. Trim to the phrase, drop anything over 1.3 s, normalize to -6 dB.
#    Measured keep-rate is 100 %; the filter is a safety net.
python3 scripts/prepare_positives_jai_fini.py \
  --source-dir data/positives_jai_fini_rawgen \
  --dest-dir   data/positives_jai_fini \
  --max-duration 1.3 \
  --target-peak-db -6.0

ls data/positives_jai_fini/*.wav | wc -l    # confirm the survivor count

# 3. MANDATORY intelligibility gate on a random sample of at least 20 clips.
#    Requires >= 90 % matching "j'ai fini" before the corpus may be used.
/home/yang/wsl-home-yang/voice-services/.venv/bin/python - <<'PY'
from faster_whisper import WhisperModel
from pathlib import Path
import random, re
model = WhisperModel("small", device="cpu", compute_type="int8")
files = sorted(Path("data/positives_jai_fini").glob("*.wav"))
sample = random.sample(files, min(20, len(files)))
hits = 0
for wav in sample:
    segments, _ = model.transcribe(str(wav), language="fr", beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    flat = re.sub(r"[^a-zà-ÿ]", "", text.lower())
    ok = "fini" in flat and "jai" in flat
    hits += ok
    if not ok:
        print(f"  MISS {wav.name}: {text!r}")
print(f"gate: {hits}/{len(sample)} = {hits / len(sample) * 100:.0f}% (need >= 90%)")
PY
```

Voice provenance: `fr_FR-siwis-medium.onnx` and `fr_FR-tom-medium.onnx` were
downloaded from `huggingface.co/rhasspy/piper-voices` (`fr/fr_FR/<voice>/medium/`),
the canonical Piper voice repository from the same `rhasspy` organisation as the
generator, which phase 1 already audited and accepted. They live in
`psg-src/models/fr_onnx/` (328 MB for the four voices trialled).

Notes on the arguments, checked against `psg-src/piper_sample_generator/__main__.py`:
- `--max-speakers 120` because the French model declares 125 speakers (the English
  run used 800 out of 904, the same "stay just under the ceiling to avoid the
  degenerate tail speakers" reasoning).
- `--batch-size` is documented as the CUDA batch size; keep it small on CPU.
- The generator emits 22050 Hz. hello_lingorm's synthetic corpus was fed to feature
  extraction at 22050 Hz directly (verified: `data/positives_hello_lingorm/0.wav`
  is 22050 Hz) -- microWakeWord's `Clips` handles the resample. The separate
  `piper_sample_generator.augment` resample step mentioned in the phase-1 plan was
  NOT used in the run that produced the shipped model. Mirror the shipped run: skip it.
- If GPU speed is wanted later, this step could run under `gpu-solo` -- but it is
  optional, CPU is sufficient, and **the GPU is occupied by the SFT run, so do not
  do that now**.

**Highest-risk configuration point: French phonemisation.** The generator does not
use the system `espeak-ng` binary (not installed on this host); it phonemises via
`piper.phonemize_espeak.EspeakPhonemizer` bundled in `.venv-gen`, selecting the
voice from the model config's `espeak.voice` field. For `fr_FR-mls-medium.pt.json`
that field is `fr`. The text argument is therefore ordinary French orthography and
must be spelled correctly, apostrophe included: `j'ai fini.` -- with the trailing
period, mirroring `hello lingorm.`.

This was verified on CPU during prep, no GPU, no model weights needed:

```
voice 'fr',    "j'ai fini."      -> ʒ e _ f i n ˈ i .
voice 'en-us', "hello lingorm."  -> h ə l ˈ o ʊ _ l ˈ ɪ ŋ ɡ ɔ ː ɹ m .
```

The French output is the expected /ʒe fini/ with stress on the final syllable, so
the phoneme frontend handles the elision and the apostrophe correctly and no
`--phoneme-input` workaround is needed. In shell, keep the phrase in **double
quotes** -- single quotes would terminate on the apostrophe.

### (d) Feature extraction -- CPU, host venv

Both corpora must be extracted with the same augmentation settings, including
`--background-dir`, for the same reason documented for hello_lingorm: mixing a
noise-augmented positive source with a clean one teaches inconsistent cues.

Both corpora must already be trimmed and normalized per (a2) and (c) before this
step. Feature extraction does not trim.

```bash
cd ~/dev/coach-kws
source .venv/bin/activate

# synthetic
python scripts/prepare_positive_features.py \
  --positives-dir   data/positives_jai_fini \
  --impulse-dir     psg-src/piper_sample_generator/impulses \
  --background-dir  data/background_noise \
  --output-dir      data/generated_augmented_features_jai_fini_noise

# real voice
python scripts/prepare_positive_features.py \
  --positives-dir   data/positives_jai_fini_real \
  --impulse-dir     psg-src/piper_sample_generator/impulses \
  --background-dir  data/background_noise \
  --output-dir      data/generated_augmented_features_jai_fini_real

deactivate
```

Each command writes `training/`, `validation/`, `testing/` RaggedMmap spectrograms
(10 ms step, 3.2 s augmentation window, `AddBackgroundNoise` at p=0.75 once
`--background-dir` is passed). Expect about 4 G for the synthetic set and tens of
MB for the real set. No GPU is used.

### (e) Training -- DO NOT RUN NOW

The GPU is occupied by the SFT run. Run this only once the GPU is free.

```bash
cd ~/dev/coach-kws
docker images | grep coach-kws-train      # image coach-kws-train:1.0 must exist
gpu-solo bash scripts/train_in_container_jai_fini.sh
```

`gpu-solo` pauses `wyoming-whisper` for the block, so household STT is briefly
offline and auto-resumes on exit. The hello_lingorm run took 15 min 04 s wall
clock end to end; expect the same order. Exit code 0 plus a printed
false-reject / false-accepts-per-hour sweep means success.

Output: `trained_models/jai_fini/tflite_stream_state_internal_quant/stream_state_internal_quant.tflite`.

### (f) Export + manifest

`test_tflite_streaming_quantized 1` in the launcher already performs the int8
streaming quantisation and export, so there is no separate quantisation command.
Write the ESPHome v2 manifest with the shared generator:

```bash
cd ~/dev/coach-kws
source .venv/bin/activate
python scripts/make_manifest.py \
  --wake-word "j'ai fini" \
  --model-filename jai_fini.tflite \
  --trained-languages fr \
  --probability-cutoff 0.6 \
  --sliding-window-size 5 \
  --tensor-arena-size 26080 \
  --minimum-esphome-version 2024.7.0 \
  --author "P15 Coach Vocal FR" \
  --output trained_models/jai_fini/tflite_stream_state_internal_quant/jai_fini.json
deactivate
```

Expected artifacts, patterned on the deployed `hello_lingorm` pair
(`project/ml/kws/models/hello_lingorm.tflite`, 60928 bytes, and
`hello_lingorm.json`):

- `jai_fini.tflite` -- int8 quantised streaming model, expect roughly 60 KB
  (identical architecture, so the size should land close to hello_lingorm's).
- `jai_fini.json` -- ESPHome micro_wake_word v2 manifest:

```json
{
  "type": "micro",
  "wake_word": "j'ai fini",
  "author": "P15 Coach Vocal FR",
  "model": "jai_fini.tflite",
  "trained_languages": ["fr"],
  "version": 2,
  "micro": {
    "probability_cutoff": 0.6,
    "sliding_window_size": 5,
    "feature_step_size": 10,
    "tensor_arena_size": 26080,
    "minimum_esphome_version": "2024.7.0"
  }
}
```

`probability_cutoff` starts at **0.6**, matching the value currently deployed for
hello_lingorm, then gets tuned from the printed sweep and from on-device testing.
`tensor_arena_size = 26080` is inherited from the same-architecture reference
models; it is a starting value, not a measured figure -- ESPHome computes the true
arena at compile time, so raise it if the model fails to load on device.

Deployment into the repo (`project/ml/kws/models/`) and the ESPHome yaml wiring is
a separate ticket step and is not covered here.

## 2b. Smoke-run result (executed) -- BLOCKING ISSUE FOUND

The French weights were downloaded and the 5-sample CPU smoke run of step (c) was
executed. Generation itself works, but the clip durations are wrong and this must
be resolved before the 5000-sample run.

Download evidence: `psg-src/models/fr_FR-mls-medium.pt`, 202452523 bytes, sha256
`b3311993554e771d9b3a13630ffa82c0649c7dafcfd05f3425595d491b06dd0a`. The size
matches the GitHub API asset record exactly (tag `v2.0.0`, uploader `synesthesiam`,
repo id 642029941 = `rhasspy/piper-sample-generator`, Organization-owned, MIT), and
the download redirect stayed on `github.com` -> `release-assets.githubusercontent.com`.

Smoke output in `data/positives_jai_fini_smoke/` (throwaway; not a training input):

| file | rate | ch | duration | mean_volume | max_volume |
|---|---|---|---|---|---|
| 0.wav | 22050 | 1 | 2.043 s | -18.9 dB | -0.0 dB |
| 1.wav | 22050 | 1 | 3.553 s | -20.9 dB | -2.6 dB |
| 2.wav | 22050 | 1 | 2.252 s | -23.0 dB | -1.9 dB |
| 3.wav | 22050 | 1 | 2.821 s | -20.6 dB | -3.6 dB |
| 4.wav | 22050 | 1 | 3.100 s | -24.5 dB | -7.7 dB |

Rate, channel count and non-silence all pass. **Duration does not.** For comparison,
the English `positives_hello_lingorm` corpus that produced the shipped model is
tightly clustered at 0.75-1.01 s across the whole 5000-clip range (sampled indices
0-5, 100, 500, 1000, 2000, 3000, 4000, 4999). The French clips are 2-3.5x longer for
a phrase of comparable length.

Diagnosis, from two follow-up measurements:

- `silencedetect` shows the clips are not simply padded: in `0.wav`, speech runs
  0-0.76 s, then a 0.24 s pause, then more audio 1.00-1.64 s, then silence. The
  first segment alone (0.76 s) is the plausible "j'ai fini" duration and matches the
  English corpus band. There is spurious audio AFTER the phrase.
- That trailing segment is about 12 dB quieter than the phrase (mean -26.9 dB vs
  -14.9 dB over 0-0.76 s), which is the signature of trailing babble / breath /
  decoder artifact rather than a second rendition of the phrase.
- It is NOT caused by the default `--length-scales [1.0, 0.75, 1.25, 1.4]` spread.
  A controlled re-run with `--length-scales 1.0` still produced 2.35, 2.39, 2.48,
  2.60 and 4.84 s clips.

Why this blocks the batch run: `prepare_positive_features.py` builds `Clips` with
`remove_silence=False` and no duration bounds, inside a 3.2 s augmentation window.
Clips of 2-4.8 s would put the phrase at an inconsistent position in the window,
train the model on the trailing artifact, and in the 4.8 s case exceed the window
entirely.

Options, none applied (all would need either a `_jai_fini` variant of the shared
`prepare_positive_features.py` or a new opt-in CLI flag on it -- the shared script
was deliberately left untouched):

- `Clips(trimmed_clip_duration_s=1.5)` -- trims the end of long clips. Keeps the
  phrase (ends 0.76-1.0 s), drops the tail. Cheapest and most targeted.
- `Clips(remove_silence=True)` -- webrtcvad non-voice trim. May not help, since the
  tail is quiet speech-like audio rather than silence.
- `Clips(max_clip_duration_s=...)` -- note this FILTERS clips out rather than
  truncating them, so at the observed durations it would discard nearly the whole
  corpus.
- Pre-trim with ffmpeg when writing into `data/positives_jai_fini/`, leaving the
  feature pipeline untouched.

Owner listening gate (this is what the samples need checking for -- do the speakers
say "j'ai fini" intelligibly, and what is the trailing audio?):

```bash
for f in ~/dev/coach-kws/data/positives_jai_fini_smoke/*.wav; do
  echo "$f"; ffplay -autoexit -nodisp "$f"
done
```

## 2c. Root cause: the phrase does not survive the training window

Follow-up investigation. The duration anomaly is not cosmetic -- with the current
config the positive clips would carry almost no phrase content into training.

### How a clip is placed (read from the pipeline source, not assumed)

- `Augmentation.add_jitter` pads the clip on the **right** by `min/max_jitter_s`
  (0.195-0.205 s here).
- `Augmentation.create_fixed_size_clip` docstring and body: if the audio is longer
  than the 3.2 s window it keeps `input_audio[-augmented_samples:]`, i.e. **removes
  the start**; if shorter it **pads zeros at the start**. Audio is therefore
  **right-aligned**, ending at about 3.2 - 0.2 = 3.0 s.
- `training_parameters*.yaml` sets `clip_duration_ms: 1500` with
  `truncation_strategy: truncate_start`, and `data.py` documents `truncate_start`
  as "remove the start of the spectrogram". Training therefore sees only the
  **last 1.5 s** of the window, i.e. the span [1.70 s, 3.20 s].

For hello_lingorm this works by luck of the phrase being short: a 0.91 s clip is
placed at 2.09-3.00 s, fully inside [1.70, 3.20].

### Correction to the first measurement pass

The first pass defined the phrase as "up to the end of the first speech segment"
from `silencedetect`. That is wrong: the detector emits sub-millisecond dips inside
continuous speech (for example `13.wav` of the real corpus shows `silence_end
0.31475` followed by `silence_start 0.315688`, a 0.9 ms gap), so many clips were
mis-read as near-silent and the resulting in-window figures were far too pessimistic.

The corrected extractor rebuilds speech intervals as the complement of detected
silence, drops transients under 50 ms, merges gaps under 250 ms as intra-phrase
closures, and takes the phrase as the longest merged interval. All figures below
use the corrected method. Two conclusions from the first pass are retracted:

- **Retracted: "trailing babble after the phrase".** With the corrected extractor
  only 0-8 % of clips carry more than 0.15 s of speech after the phrase. The clips
  are long because the MLS French voices genuinely say the phrase slowly -- the
  phrase itself measures p50 1.39-1.62 s -- not because of a hallucinated tail. The
  quiet post-pause segment observed in `0.wav` was real but not representative.
- **Retracted: "phrase lost, 0-3 % in-window".** The correct figure for the
  generator defaults is 25 % of clips fully in-window with 71 % mean phrase
  coverage. Still bad, still blocking, but not the near-total loss first reported.

### Measured result (corrected), n=40 per variant

Variants, all with `--noise-scales 0.333 --noise-scale-ws 0.333` (the values
`fr_FR-mls-medium.pt.json` declares for inference, against generator defaults of
0.667-1.4). Post-trim keeps 50 ms lead-in and 100 ms tail around the phrase.

| corpus | p50 clip | fully in-window @1500 | @2000 | @2500 |
|---|---|---|---|---|
| A raw, default length-scales | 1.81 s | 25 % (71 % cov) | 50 % (89 %) | 85 % (97 %) |
| B raw, length-scales 0.8-1.0 | 1.47 s | 38 % (82 %) | 72 % (95 %) | 95 % (99 %) |
| A post-trim | 1.72 s | 30 % (77 %) | 52 % (93 %) | 92 % (99 %) |
| B post-trim | 1.43 s | 40 % (87 %) | 82 % (99 %) | 100 % (100 %) |
| C post-trim, length-scales 0.7-0.9 | 1.25 s | 52 % (89 %) | 80 % (98 %) | 98 % (99 %) |

Keep-rate for post-trimmed synthetic clips against a duration bound (a trimmed clip
fits fully iff its duration is at most `clip_duration_ms/1000 - 0.2`):

| bound | fits | variant B keep | variant C keep |
|---|---|---|---|
| <= 1.3 s | 1500 ms | 40 % (2.50x over-generate) | 52 % (1.90x) |
| <= 1.6 s | 1800 ms | 68 % (1.48x) | 78 % (1.29x) |
| <= 1.8 s | 2000 ms | 80 % (1.25x) | 80 % (1.25x) |
| <= 2.0 s | 2200 ms | 95 % (1.05x) | 95 % (1.05x) |

Faster length-scales help but with diminishing returns: variant C still shows a
3.00 s outlier, so part of the slowness is speaker-systematic rather than
length-scale-driven. Pushing the window down to 1500 ms therefore discards roughly
half of an already small 125-speaker pool, and discards it non-randomly -- it keeps
the fast speakers only.

### Real recordings: the same geometry applies, and it already bit hello_lingorm

The recording harness captures a fixed 2.0 s window, so real clips are 2.0 s files
with the phrase somewhere inside. Measured on the existing 58-clip
`positives_hello_lingorm_real` corpus (the corpus that trained the deployed model):

| corpus | p50 phrase | fully in-window @1500 | @2000 | @2500 |
|---|---|---|---|---|
| real, as recorded | 0.85 s | 67 % (94 % cov) | 98 % (99 %) | 100 % |
| real, post-trimmed | 0.85 s | 98 % (100 %) | 100 % | 100 % |

Two things follow. First, post-trimming is the single highest-value step for real
clips: it takes them from 67 % to 98 % in-window at the current 1500 ms setting,
because it removes the leading silence (p50 0.61 s) that otherwise pushes the phrase
forward. Second, the deployed hello_lingorm model was trained with a third of its
real-voice clips only partially in-window -- a plausible contributor to the 8/10
on-device recall. That is a finding about hello_lingorm, recorded for follow-up;
nothing in this pipeline modifies it.

Also checked and cleared: an early flag that 22 of the 58 real clips were
near-silent was a detector artifact of the buggy extractor, not real. With the
corrected method all 58 carry a genuine phrase (min 0.39 s, p50 0.85 s) and none has
trailing speech.

### The user speaks faster than the synthetic voices

Real "hello lingorm" measures p50 0.85 s; synthetic French "j'ai fini" measures p50
1.24-1.62 s depending on variant. Filtering the synthetic corpus toward shorter
clips therefore moves it *toward* the target speaker's tempo rather than away from
it. This is an argument in favour of a smaller window that the raw fit percentages
alone do not show.

### Generator-side trim options: none exist

Checked directly. `piper_sample_generator.__main__` argparse exposes only: `text`,
`--max-samples`, `--model`, `--batch-size`, `--slerp-weights`, `--length-scales`,
`--noise-scales`, `--noise-scale-ws`, `--output-dir`, `--max-speakers`,
`--phoneme-input`, `--verbose`. There is no `--max-sample-duration`, no silence or
LUFS trim. `piper_sample_generator.augment` takes only `input_dir`, `output_dir`,
`--sample-rate`. Any trimming must therefore happen after generation, or be handled
by the feature stage.

### Fix proposal (ordered; none applied, all need authorization)

1. **Raise `clip_duration_ms` for this model** -- one line in
   `training_parameters_jai_fini.yaml`, a file owned by this pipeline, so
   hello_lingorm is unaffected. 1500 ms was tuned for a compact two-word English
   wake word; "j'ai fini" is genuinely a longer utterance. Setting 2500-3000 ms
   makes the window cover the whole utterance and removes the geometry problem at
   its root. **Cost, must be weighed:** it enlarges the model's input window, which
   raises the tensor arena and per-inference compute on the ESP32 and changes
   streaming latency. This is an architecture change, not a free knob.
2. **Generate with the model's declared inference values** -- add
   `--noise-scales 0.333 --noise-scale-ws 0.333`. Measured to shorten clips
   materially. Keep the default `--length-scales` spread for pace variety.
3. **Post-trim after generation**, writing trimmed clips into
   `data/positives_jai_fini/`, leaving the shared `prepare_positive_features.py`
   untouched. Effective on clips with a clean pause (0.wav 2.04 -> 0.86 s,
   2.wav 2.25 -> 0.59 s) but not on contiguous ones.
4. **Over-generate and filter on duration.** With options 2+3 the observed keep
   rate against a 1.3 s bound was 0/6, so if option 1 is rejected this route needs
   a much larger over-generation factor and should be measured on a 50-sample run
   before committing to a batch size.

## 2d. Real recordings: normalization and placement (60 clips delivered)

### Why normalization was needed, from the pipeline source

`Augmentation` applies `audiomentations.Gain` at **probability 1.0** with the
default range **-45 dB to 0 dB** (`prepare_positive_features.py` does not override
`min_gain_db` / `max_gain_db`). The gain augmentation only ever attenuates. The
pipeline therefore assumes input clips sit near full scale and randomizes downward
from there. Feeding it clips already at -25 dB peak would place some augmented
copies 70 dB down, effectively training on silence. This makes peak normalization
a correctness fix, not a cosmetic one.

### What was done

- `data/positives_jai_fini_real_raw/` -- byte-identical copy of the 60 delivered
  clips, verified by md5 before anything was modified. This is the provenance copy.
- `data/positives_jai_fini_real/` -- the same 60 filenames, peak-normalized to
  -6 dB, and the directory the feature step consumes.

Gain applied: min -0.4 dB, p50 +9.4 dB, max +18.7 dB. Peak after: exactly -6.0 dB
on all 60. Clips above -3 dB after normalization: 0. Clips at or above full scale: 0.
No clipping was introduced.

Spot check on the three quietest, as requested:

| file | peak before | gain | peak after | mean after | SNR before | SNR after |
|---|---|---|---|---|---|---|
| 5.wav | -24.7 dB | +18.7 dB | -6.0 dB | -21.8 dB | 30.4 dB | 30.4 dB |
| 11.wav | -24.2 dB | +18.2 dB | -6.0 dB | -25.8 dB | 38.1 dB | 38.1 dB |
| 24.wav | -23.1 dB | +17.1 dB | -6.0 dB | -22.3 dB | 31.4 dB | 31.4 dB |

### The quiet clips are good recordings, not bad ones

Signal-to-noise ratio measured on the raw files (speech RMS over the loudest 15 %
of 20 ms frames, ambient over the quietest 25 % of non-zero frames):

- all 60: p50 **36.2 dB**, min 29.4 dB, max 46.3 dB
- quietest 20 clips: p50 34.9 dB -- only about 4 dB worse than the loudest 20
- clips below 20 dB SNR: **none**

So the low peaks were purely a level issue. Normalization is a linear gain, so it
shifts speech and ambient equally and leaves SNR unchanged -- confirmed above.

One measurement caveat worth recording: an initial attempt to report the noise floor
gave -91.0 dB both before and after, which is physically impossible under +18 dB of
gain. Direct sample inspection showed why -- the first 0.30 s of these captures is
**exact digital zero** (0 of 4800 samples non-zero), and gain on zero is zero. About
27 % of each file is digital silence. The SNR figures above avoid that trap by
measuring only non-zero frames.

### Placement inside the 2.0 s capture window

| measure | min | p50 | max |
|---|---|---|---|
| leading silence before speech | 0.30 s | 0.66 s | 1.23 s |
| phrase length | 0.39 s | **0.66 s** | 1.44 s |
| trailing silence | 0.00 s | 0.73 s | 1.17 s |

| corpus | fully in-window @1500 | @2000 | @2500 |
|---|---|---|---|
| real, as recorded | 33 % (79 % cov) | 100 % (100 %) | 100 % |
| real, post-trimmed | **98 % (100 %)** | 100 % | 100 % |

The recording harness does position unfavourably: a fixed 2.0 s capture with a
countdown leaves p50 0.66 s of leading silence, which under right-alignment pushes
the phrase forward and out of a 1500 ms window in two thirds of clips. **Post-trim
fixes it completely** (33 % to 98 %), and needs no change to the harness or the
window. This is the same effect measured on the hello_lingorm real corpus.

Note also the user's own tempo: the phrase measures p50 **0.66 s**, shorter than
their "hello lingorm" at 0.85 s and roughly half the synthetic French p50. 6 of 60
clips carry more than 0.15 s of speech after the phrase (likely breath or a restart);
post-trim removes that too.

### Recommendation on clip_duration_ms (data above; decision deferred)

**Recommended: keep clip_duration_ms at 1500** -- no change to the deployed window
-- with generation at `--noise-scales 0.333 --noise-scale-ws 0.333 --length-scales
0.6 0.7 0.8` (variant D), post-trim on both corpora, and a `<= 1.3 s` duration
filter on the trimmed synthetic clips.

This **reverses the earlier 2000 ms recommendation**, which was made before the real
clips existed and before the faster length-scale variant was measured. Two new
measurements changed it:

1. Real clips post-trimmed reach **98 %** in-window at 1500 ms, and the user's own
   phrase is only p50 0.66 s -- a very large margin against the 1.3 s bound.
2. Variant D (`--length-scales 0.6 0.7 0.8`) lifts the synthetic keep-rate at
   `<= 1.3 s` from 52 % to **75 %** (over-generate only 1.33x, so 6650 raw for
   5000), with p50 clip 1.10 s.

| corpus at 1500 ms | fit |
|---|---|
| real, post-trimmed | 98 % |
| synthetic variant D, post-trimmed, filtered <= 1.3 s | 75 % kept, kept clips fit by construction |

Device cost: **zero**. That directly protects the CS-159 concurrency budget, which
is the flagged risk, and it avoids an architecture change on a model that must share
the S3 with STT capture.

Two supporting points. The synthetic corpus currently teaches a rendition about
twice as slow as the user actually speaks (synthetic p50 1.24-1.39 s at the earlier
settings, against the user's 0.66 s), so shifting synthetic faster and filtering out
the slowest clips corrects a genuine tempo mismatch rather than merely trimming to
fit. And post-trim is required at any window size regardless, for both corpora.

**Residual risk, needs the listening gate.** `--length-scales 0.6 0.7 0.8` renders
speech 1.25-1.67x faster than the model's natural pace. That is still slower than
the user's own delivery, so it is defensible, but only listening can confirm the
fastest renditions are not slurred. Five variant-D samples are saved at
`data/positives_jai_fini_smoke_fast/` for exactly this check -- audition them
alongside the original smoke set before authorizing the batch.

**Fallback: 2000 ms.** If the audition finds variant D too fast, fall back to
variant C (`--length-scales 0.7 0.8 0.9`) at 2000 ms: 80 % synthetic keep, real
100 %, at the cost of a 33 % larger window, arena and per-inference compute.

**2500 ms is not recommended** at any point on this data.

Options 3 and 4 from the list above are now folded into the recommendation as
standard steps rather than fallbacks: post-trim is required for both corpora at any
window size, and the duration filter is what makes the kept synthetic corpus
well-formed by construction.

## 3. Open questions and risks

1. **False accepts are structurally worse for this phrase than for a wake word.**
   "j'ai fini" is a common French sentence; a wake word like "hello lingorm" is
   deliberately rare. The negative corpus available here (kahrendt speech /
   no_speech / dinner_party) is **English** speech, so the false-accept figures the
   training run prints will be optimistic in a way they were not even for
   hello_lingorm. A French-speech false-accept check is needed before trusting any
   cutoff. Practical mitigation for the terminal: only arm this model while a turn
   is actually in progress, so a stray "j'ai fini" in conversation cannot fire it.
   That is a firmware decision, flagged here rather than resolved.

2. **French generator weights not yet downloaded, and never exercised in this
   project.** The English path was validated end to end in phase 1 with a 5-sample
   smoke test before the 5000-sample run. Do the same here: generate 5 samples
   first, listen to them, confirm the French speakers actually say "j'ai fini"
   intelligibly, and only then launch the 5000-sample run. The `mls` French model
   has 125 speakers against LibriTTS-R's 904, so speaker diversity is roughly 7x
   lower -- real-voice clips carry proportionally more of the load, which is an
   argument for recording toward the top of the 50-100 band.

3. **`scripts/make_training_config.py` was not used to produce
   `training_parameters_jai_fini.yaml`.** That generator still hardcodes the
   original single-positive-source layout (`data/generated_augmented_features`) and
   does not know about the noise/real split that the current hello_lingorm config
   uses; the shipped `training_parameters.yaml` was hand-edited past it. The
   `_jai_fini` config was therefore written directly, mirroring the shipped
   hello_lingorm config with only the two positive `features_dir` entries and
   `train_dir` changed. Making the generator parameterised is a separate cleanup.

4. **Sampling weights carried over unchanged** (synthetic 2.0, real 4.0, negatives
   10/10/5/0) along with `training_steps: [10000]`, `batch_size: 128`,
   `negative_class_weight: [20]` and `clip_duration_ms: 1500`. These were tuned for
   hello_lingorm, not for this phrase. "j'ai fini" is a shorter utterance
   (about 0.8 s against about 1.0 s), still well inside the 1500 ms clip window, so
   no change is proposed for the first run -- but treat the first run as a baseline
   to tune from, not as a final configuration.

5. **Channel mismatch persists.** Recording happens on the desktop headset, while
   the field mic is the on-device INMP441 I2S MEMS. The RIR / EQ / colour-noise
   augmentation partially simulates that, and background-noise augmentation is on
   from the start this time (hello_lingorm's first run had it off), but this is a
   pragmatic approximation, not a field match.
