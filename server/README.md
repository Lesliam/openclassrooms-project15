# Coach FR — Server-Side Voice Pipeline (Home Assistant + Wyoming + Ollama)

Status: v0 design + setup guide (CS-149). Nothing in this document has been
applied to the live Home Assistant instance yet. Every change that touches
shared infrastructure is listed in the approval section at the bottom and
requires Lesliam's explicit go-ahead.

Placeholders: `<AI_HOST_IP>` (CachyOS GPU host) and `<NAS_IP>` (Home
Assistant NAS) are deliberately not written in this tracked file. Real
values live in `local_notes.md` next to this file (untracked, local only).

## 1. Architecture

The Coach FR pipeline reuses the existing household voice infrastructure
(Wyoming Whisper STT + Wyoming Piper TTS on the CachyOS host) and adds an
ADDITIVE Assist pipeline in Home Assistant plus an Ollama conversation agent.
The existing English household pipeline is not modified.

```
+---------------------------+          Wi-Fi / LAN
|  ESP32-S3 N16R8 terminal  |
|  (ESPHome satellite)      |
|  - micro_wake_word (KWS)  |
|  - INMP441 I2S mic        |
|  - MAX98357 + speaker     |
+------------+--------------+
             | ESPHome native API (voice_assistant protocol)
             v
+---------------------------+
|  Home Assistant           |   NAS, LAN <NAS_IP>
|  Assist pipeline:         |
|  "Coach FR" (NEW,         |
|   additive — existing     |
|   household pipeline      |
|   untouched)              |
+--+-----------+---------+--+
   |           |         |
   | STT       | Agent   | TTS
   v           v         v
+--------+ +---------+ +--------+
| Wyoming| | Ollama  | | Wyoming|
| Whisper| | conv.   | | Piper  |
| :10300 | | agent   | | :10200 |
| (large | | qwen2.5 | | (needs |
|  -v3,  | | :14b +  | | fr_FR  |
| FR cfg | | coach   | | voice, |
| needed)| | prompt  | | see    |
|        | | :11434  | | 3.4)   |
+--------+ +---------+ +--------+
     all three on CachyOS host, LAN <AI_HOST_IP>
```

Round trip: wake word detected on-device -> ESP32 streams mic audio to HA ->
HA "Coach FR" pipeline sends audio to Wyoming Whisper (STT, French) -> text
goes to the Ollama conversation agent (qwen2.5:14b with the coach system
prompt, see `coach_system_prompt_v0.md`) -> response text goes to Wyoming
Piper (TTS, French voice) -> audio streams back to the ESP32 speaker.

Reference docs:

- Wyoming protocol integration: https://www.home-assistant.io/integrations/wyoming/
- Whisper STT: https://www.home-assistant.io/integrations/whisper/
- Fully local Assist pipeline guide: https://www.home-assistant.io/voice_control/voice_remote_local_assistant/
- Ollama integration: https://www.home-assistant.io/integrations/ollama/
- Piper voice catalog: https://github.com/rhasspy/piper/blob/master/VOICES.md
  (samples: https://rhasspy.github.io/piper-samples/)
- ESPHome voice_assistant component: https://esphome.io/components/voice_assistant/

## 2. Language handling — how the pipeline becomes French

Two independent language settings matter:

1. **HA Assist pipeline language.** Each Assist pipeline has its own language
   setting; since HA 2023.8 multiple pipelines can run different languages
   side by side (source: https://www.home-assistant.io/voice_control/voice_remote_local_assistant/).
   The new "Coach FR" pipeline is set to French; the existing household
   pipeline stays English. When creating the pipeline, HA lets you pick the
   language for the pipeline itself and for the STT/TTS engines under it.

2. **Wyoming Whisper server-side language flag.** The running
   `wyoming-whisper` service uses faster-whisper `large-v3`, which is a
   multilingual model, so French transcription is possible with the CURRENT
   model — no re-download needed. However, wyoming-faster-whisper accepts a
   `--language` startup flag (usage example in
   https://github.com/rhasspy/wyoming-faster-whisper). The current systemd
   user unit was set up for the English household assistant and its
   `--language` value has NOT been inspected in this ticket.
   - If it is pinned to `en`, French audio will be transcribed wrongly and
     the flag must change (options: `fr` is wrong for the shared household
     use; `auto` adds latency to every household request; a second whisper
     instance on another port pinned to `fr` isolates the two pipelines but
     costs extra VRAM).
   - DECISION FOR LESLIAM: inspect the unit
     (`systemctl --user cat wyoming-whisper` on the CachyOS host) and choose
     between `--language auto` on the shared instance vs a dedicated second
     instance for French. This document does not change anything.

## 3. Step-by-step HA configuration (additive only)

All steps below are performed in the HA UI on the NAS instance. None of
them modify the existing pipeline; they only add new entries.

### 3.1 Prerequisite check — Wyoming integrations already present

Settings -> Devices & Services: the Wyoming integrations for Whisper
(<AI_HOST_IP>:10300) and Piper (<AI_HOST_IP>:10200) should already exist from
the household setup. Do not touch them. If the French voice ends up served by
a second Piper/Whisper instance on new ports (see 3.4 and section 2), those
would be ADDED as new Wyoming entries (Settings -> Devices & Services ->
Add Integration -> Wyoming Protocol -> host <AI_HOST_IP>, port NNNNN).

### 3.2 Install the Ollama integration (new)

Per https://www.home-assistant.io/integrations/ollama/ :

1. Settings -> Devices & Services -> Add Integration -> "Ollama".
2. URL: `http://<AI_HOST_IP>:11434`.
3. Model: `qwen2.5:14b` (already pulled on the host).
4. In the integration options, paste the coach system prompt from
   `coach_system_prompt_v0.md` into the "Instructions" (prompt template)
   field. Leave "Control Home Assistant" DISABLED — the coach must not get
   device control; the household assistant keeps that role.
5. Options worth setting: context window (HA defaults to 8k tokens, larger
   than Ollama's server default) and max kept messages (conversation
   history length — relevant to the long-context drift experiment, see
   `../ml/eval/eval_set_v0.md`).

BLOCKER — Ollama currently binds `127.0.0.1:11434` on the CachyOS host, so
HA on the NAS CANNOT reach it as-is. Resolution options (decision for
Lesliam, do NOT change silently — see section 4):

- Option A: set `OLLAMA_HOST=0.0.0.0` (or `<AI_HOST_IP>`) via a systemd
  drop-in for `ollama.service` and restart it. Exposes the Ollama API to the
  whole LAN (no auth in Ollama) — acceptable on a trusted home LAN, but note
  the CachyOS host currently has no firewall configured.
- Option B: keep Ollama on loopback and add a reverse proxy (nginx/caddy)
  or socat forward on <AI_HOST_IP> that only accepts connections from
  <NAS_IP> (the NAS). More setup, tighter exposure.

### 3.3 (If needed) Second Whisper instance for French

Only if the decision in section 2 is "dedicated FR instance": run another
wyoming-faster-whisper process on a new port (e.g. 10301) with the French
language flag, as a new systemd user unit, and register it in HA as a new
Wyoming integration. VRAM note: a second large-v3 instance is heavy; a
smaller multilingual model (e.g. medium) may be the right trade-off. This is
a shared-GPU-budget decision (whisper already holds ~4 GB).

### 3.4 French Piper voice

The current Piper serves `en_US-amy-medium` only. French voices available in
the Piper catalog (https://github.com/rhasspy/piper/blob/master/VOICES.md):
`fr_FR-siwis-low`, `fr_FR-siwis-medium`, `fr_FR-upmc-medium` (2 speakers:
jessica, pierre), `fr_FR-tom-medium`. Recommended starting point:
`fr_FR-siwis-medium` (single clear female voice, medium quality; listen and
compare at https://rhasspy.github.io/piper-samples/ before committing).

How to add it: wyoming-piper takes `--voice <name>` and a data/download
directory (`--data-dir` / `--download-dir`, per
https://github.com/rhasspy/wyoming-piper) and downloads the voice model into
that directory. Whether the single running instance can serve BOTH the
English household voice and a French voice simultaneously (voice selected
per-request by HA) needs a quick test; if not, run a second wyoming-piper
instance on port 10201 with the French voice and register it as a new
Wyoming integration. Either way this touches the shared TTS service ->
approval required (section 4).

### 3.5 Create the "Coach FR" Assist pipeline (new)

Per https://www.home-assistant.io/voice_control/voice_remote_local_assistant/ :

1. Settings -> Voice assistants -> Add Assistant.
2. Name: `Coach FR`. Language: French.
3. Conversation agent: the Ollama entity created in 3.2.
4. Speech-to-text: the Wyoming Whisper engine; set its language to French.
5. Text-to-speech: the Wyoming Piper engine with the fr_FR voice from 3.4.
6. Wake word: leave "none" at pipeline level — wake word detection runs
   on-device on the ESP32 (micro_wake_word), which then opens the pipeline.
7. Do NOT set Coach FR as the default/preferred assistant — the household
   pipeline stays default. The ESP32 satellite selects Coach FR explicitly
   (in the ESPHome device's Voice Assistant settings in HA, pick the
   `Coach FR` pipeline for this device).

### 3.6 Wire the ESP32 satellite

Flash `../firmware/esphome/coach-terminal.yaml` (skeleton; INMP441 mic
confirmed, proposed pins in the YAML), adopt the device in HA (ESPHome
integration auto-discovers it),
then in the device page set its assistant/pipeline to `Coach FR`.

### 3.7 Smoke test

1. HA -> Settings -> Voice assistants -> Coach FR -> "Start a conversation"
   (text mode) to validate the Ollama agent + prompt without audio.
2. Then debug tab of the pipeline to test STT/TTS stages with a mic from the
   browser.
3. Finally end-to-end from the ESP32 terminal.

## 4. Impact on existing infra (requires Lesliam approval)

Everything below touches services that other things depend on (household HA
voice). NONE of it is done by this ticket; each line is a separate approval.

| # | Change | Shared component touched | Risk if done carelessly |
|---|--------|--------------------------|-------------------------|
| 1 | Expose Ollama to LAN (`OLLAMA_HOST` drop-in + restart) OR add a proxy on <AI_HOST_IP> | `ollama.service` on CachyOS | Unauthenticated LLM API visible to whole LAN; no firewall currently configured on the host |
| 2 | Whisper language strategy: change `--language` on the shared instance to `auto`, or spawn a second FR instance | `wyoming-whisper` systemd user unit / GPU VRAM budget (~4 GB already resident) | `auto` slows the household EN pipeline; second instance eats VRAM needed by fine-tune runs (gpu-solo conflicts) |
| 3 | Add French voice to Piper (same instance) or spawn second wyoming-piper on :10201 | `wyoming-piper` systemd user unit | Restarting piper interrupts household TTS momentarily; misconfig could change the household voice |
| 4 | New Wyoming integration entries + new Assist pipeline in HA | HA config on the NAS (additive, but same instance the household depends on) | Low — additive; main risk is accidentally editing the existing pipeline instead of adding one |
| 5 | (Later, HA option 2 bonus) giving any agent device control | HA entity access | Out of scope for Coach FR; keep "Control Home Assistant" off |

Explicitly NOT requiring approval (fully additive, no shared state): the
ESPHome firmware for the new device, the coach system prompt file, the eval
set, and this document.
