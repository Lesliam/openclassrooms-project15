# Coach Vocal FR — Edge Voice Terminal + Self-Hosted AI Brain

A French conversation coach for oral exam and interview practice: a
hands-free voice terminal built on ESP32-S3, backed by a fully
self-hosted AI pipeline on a local GPU workstation. No cloud, LAN only.

## Why

Practicing spoken French (presentations, interviews) requires a partner
who corrects you consistently and never gets tired. Cloud voice
assistants are unsuitable: latency, cost, privacy, and no control over
coaching behavior. This project runs the entire voice loop at home and
uses the coach persona as a testbed for two AI engineering practices:

1. **KWS model lifecycle** — wake-word model: train, INT8 quantization,
   on-device deployment, detection telemetry, drift monitoring, and a
   demonstrated retrain cycle.
2. **Behavior fine-tuning vs prompting** — coach behavior (correction
   format, French-only persistence, coaching tone) implemented first as
   a system prompt baseline, then as an SFT/DPO fine-tune, compared on a
   frozen evaluation set with quantified behavior-consistency metrics.

## Architecture

Cascade design: a tiny always-on model at the edge gates a large
on-demand brain on the LAN.

```
ESP32-S3 terminal                      GPU workstation (RTX 5080)
+---------------------+               +------------------------------+
| microWakeWord (KWS) |  --wake-->    | Home Assistant Assist        |
| AFE audio front-end |  audio via    |   Whisper STT (Wyoming)      |
| I2S mic + speaker   |  HA protocol  |   Coach LLM (Ollama)         |
+---------------------+  <--tts--     |   Piper TTS (Wyoming, FR)    |
                                      +------------------------------+
```

- **Edge**: ESP32-S3 N16R8, ESPHome firmware, INMP441 I2S microphone,
  MAX98357 amplifier. The wake-word model runs on-device; nothing
  streams until it fires.
- **Brain**: existing self-hosted voice stack reused — Wyoming Whisper
  (STT), Ollama `qwen2.5:14b` with a dedicated coach persona, Wyoming
  Piper (`fr_FR-siwis-medium`). Orchestrated as an additive Home
  Assistant Assist pipeline.
- **Security**: services bound to the LAN IP only, host firewall
  whitelists the Home Assistant machine. Real network values are kept
  in an untracked local file; tracked files use placeholders.

## Repository layout

| Path | Content |
|---|---|
| `firmware/esphome/` | ESP32-S3 terminal configuration (ESPHome) |
| `server/` | Brain pipeline: architecture, applied setup guide, coach system prompt |
| `ml/eval/` | Frozen evaluation set for the prompt-vs-fine-tune comparison |
| `ml/` (upcoming) | KWS training pipeline, fine-tuning runs, drift analysis |

## Status

- Brain pipeline applied and verified: firewall, LAN-only bindings,
  French TTS voice, "Coach FR" Assist pipeline, text smoke test passed
  (coach style and French-only behavior confirmed).
- Next: terminal bring-up (ESP32-S3 flash + end-to-end voice test),
  custom KWS training, fine-tuning runs and evaluation.

## Design decisions on record

- BLE OTA for the terminal is documented as a design (architecture and
  sequence diagrams) rather than implemented; flashing is manual in
  this iteration.
- The wake word ships in English first; a French custom wake word is a
  timeboxed experiment (audio data availability is the risk, not the
  training pipeline).
- Vendor claims of "offline LLM on ESP32" were audited and refuted by
  memory arithmetic (8 MB PSRAM vs 1.6 GB model weights); this audit
  motivated the cascade architecture.
