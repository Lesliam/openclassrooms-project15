# BENCH RESULT — CS-159 concurrent mid-turn wake word

## CLEAN RE-TEST 2026-07-22 (both brain services up) — supersedes the TTS hypothesis below

The earlier "continuous KWS breaks TTS" hypothesis was WRONG. Root cause of the
whole no-reply episode was that BOTH 5080 voice services were down/stopped
(whisper SIGTERM'd 16:39; wyoming-piper also stopped — tts_proxy URL 404'd, 0
bytes). After restarting whisper AND piper, and adding gain_factor:4 to the bench
STT path too, a clean re-test showed:

- **Coach replies + TTS actually plays** now: e.g. 08:56:47.482 TTS stream start
  -> 08:56:52.687 end = ~5.2 s of real playback, then "Speaker has finished".
  (Confirms firmware/esphome were never the cause; esphome has been 2026.5.3 for
  every build 2026-07-16..21, so there was no version regression to roll back.)
- **End-word (2nd "hello lingorm" mid-turn) DOES stop the turn** when spoken while
  the turn is still active: 08:57:19.675 (0.62/0.78) and 08:57:31.698 (0.73/1.00)
  both routed `during ACTIVE turn -> voice_assistant.stop`. Routing correct
  (active->stop, idle->start). Concurrency + CPU budget: confirmed feasible.

### KEY FINDING — device `silence_detection: false` does NOT disable HA's server-side end-of-speech VAD

The logs repeatedly show `Starting STT by VAD` -> `STT by VAD end`: the Home
Assistant assist pipeline runs its OWN VAD that ends the turn on a silence
timeout, independent of the device's `silence_detection: false`. Consequence:
- If the learner speaks the end-word BEFORE HA's VAD fires -> end-word wins, turn
  stops (works). e.g. 08:57:16 start -> 08:57:19.675 end-word -> stop.
- If the learner PAUSES -> HA's VAD ends the turn first -> coach replies -> by the
  time she says the wake word the turn is already over (is_running=false) -> it
  routes to `start` (new turn), NOT `stop`. This is exactly the user-observed
  "later, saying the wake word doesn't stop it; coach replies on the pause."

So the "pause as long as you want" goal is NOT achievable by the device end-word +
`silence_detection: false` alone. **Chantier 2 hard prerequisite:** disable or
greatly lengthen the HA-side end-of-speech VAD (the assist pipeline STT
"end-of-speech"/silence setting the user set to "relaxed" in session 23, and/or
the wyoming-whisper VAD), so silence never auto-ends the turn and the end-word is
the sole turn terminator. Without that HA-side change, the end-word only wins a
race against the VAD timeout.

---
(historical, partly-superseded notes below)

# BENCH RESULT — CS-159 concurrent mid-turn wake word (original, contaminated run)

**Date:** 2026-07-21 (session 24). **Verdict: PARTIAL / MIXED — do NOT read as a
clean end-to-end PASS.**

- POSITIVE: KWS reliably detects a deliberately-spoken end-word DURING active
  voice_assistant STT capture, on the real ESP32-S3 (HW-678A) @ ESPHome 2026.5.3,
  with no crash / reboot / watchdog. The spike's narrow CPU-budget concern for
  KWS-during-STT-capture looks feasible.
- PROBLEM: the coach's TTS reply NEVER played audibly in the bench. The bench's
  "keep KWS alive continuously through the WHOLE turn (including TTS playback)"
  approach appears to break TTS audio output. So the naive continuous-KWS design
  is NOT viable as-is; the fix is to scope the end-word detector to the LISTENING
  window only (KWS off during TTS, exactly as production does).

Firmware under test: `coach-terminal-benchtest-cs159.yaml` (throwaway; reuses
`hello_lingorm` as a single continuously-listening model, `stop_after_detection:
false`, `silence_detection: false`, mid-turn detection → `voice_assistant.stop`).
Flashed over USB serial to the live device.

## Environmental issue found + fixed first (NOT a bench result)

First attempt errored on every turn: `Error: stt-stream-failed - speech-to-text
failed`, screen "Erreur". Root cause was environmental, NOT the firmware:
`wyoming-whisper.service` had been cleanly SIGTERM'd at 16:39 (down ~1h44m; port
10300 not listening). Restarted it (VRAM fit: ~10.8 GB Ollama + ~4 GB whisper =
~14.9/16.3 GB). All findings below are post-restart.

## POSITIVE — KWS detects during active STT capture (USER-confirmed deliberate)

- 18:27:43.957 `Detected 'hello lingorm' 0.64/0.99` → `cs159: wake word during
  ACTIVE turn -> voice_assistant.stop`, landing right after `Starting STT by VAD`
  (18:27:43.731) — the wake word was detected WHILE voice_assistant was actively
  capturing STT. USER confirmed this (and 18:27:25.892, 0.69/0.90) were
  deliberately-spoken 2nd wake words after a pause = valid trials per §3b.
- 18:27:34.468 `0.77/1.00` idle → `voice_assistant.start` (routing correct).
- `silence_detection: false` held the turn open across the deliberate pause:
  the 2nd wake word routed to `-> stop` (the `is_running` branch), proving the
  turn was still ACTIVE after the pause (not cut off).
- No crash, reboot, or watchdog across the trials.

## PROBLEM — coach TTS reply never played (USER: "no coach reply the whole time")

Even on a turn that completed naturally (no mid-turn stop, e.g. ending 18:27:20.451):
- `TTS stream start` → `TTS stream end` in ~12 ms (a real spoken reply is seconds).
- `Response URL: http://<NAS_IP>:8123/api/tts_proxy/...wav` delivered.
- `Speaker has finished outputting all audio` immediately; `i2s_audio.speaker
  Starting` → `Stopped` in 0–11 ms; ring buffer created but no audio streamed.
→ The speaker output no audio; the learner heard nothing.

Attribution: the bench tts/speaker/media config is byte-identical to production
(same `speaker: terminal_speaker`, streaming TTS, on_tts_stream_start/end amp
gating, no media_player) — production plays TTS fine (the coach talks in normal
use). The ONLY behavioral difference is that the bench keeps `micro_wake_word`
alive CONTINUOUSLY (incl. during TTS), whereas production deliberately stops KWS
during the turn/TTS ("no KWS during TTS", to avoid I2S 'parent bus is busy').
Strong hypothesis: continuous KWS during TTS playback contends with the speaker
I2S path and empties the TTS stream. (To confirm: reflash production and verify
the coach speaks again — isolates the bench change as the cause.)

## Refined conclusion for CS-159

- The end-word only needs to be detected WHILE THE LEARNER IS SPEAKING (during STT
  capture), NOT during TTS playback. So the correct refonte pattern is: enable the
  end-word detector during the LISTENING/STT window and DISABLE it during TTS
  (as production already stops KWS during TTS). This also removes the TTS-echo
  false-trigger path.
- Concurrency during STT capture = feasible (proven, no CPU crash). Continuous KWS
  through TTS = breaks playback (avoid).

## Next (chantiers)

1. Chantier 1 — train a distinct, least-ambiguous end-word KWS model (NOT reuse
   hello_lingorm; "voilà"/"terminé" risky as common fillers). Needs GPU + USER
   recordings; coach-kws pipeline mirror.
2. Chantier 2 — firmware refonte: end-word detector enabled ONLY during the STT
   listening window (enable_model on `on_listening`, disable on TTS/on_end),
   `silence_detection: false`, end-word → `voice_assistant.stop`. Rework the
   interval restart safety-net + UI state machine. Keep production's "no KWS
   during TTS" invariant.
3. Confirm the TTS-break hypothesis by reflashing production (coach should speak).
