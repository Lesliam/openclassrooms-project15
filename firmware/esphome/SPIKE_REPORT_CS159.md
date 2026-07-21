# SPIKE REPORT — CS-159: Concurrent end-of-turn wake word on ESPHome

> **PM/USER decision (2026-07-21):** the §5/§6 push-to-talk fallback is NOT
> adopted — USER requires a 100% voice UX and deliberately excluded the button
> at initial design. The retained direction is the concurrent end-word (§4),
> gated on the one hardware bench test defined in §6.2. See the CS-159 Linear
> ticket decision comment and BENCH_PROCEDURE_CS159.md.

**Type:** Feasibility spike (HARD GATE — no firmware code written).
**Date:** 2026-07-21
**Author:** dev-firmware spike
**Verdict:** **CONDITIONAL** (config-level feasible on the pinned ESPHome version; the sole remaining blocker is an *empirical S3 real-time CPU budget*, not an architectural or version dependency).

---

## 1. Question restated

Can ESPHome run a **second `micro_wake_word` model** (an end-of-turn word, e.g. "voilà"/"terminé") **concurrently with `voice_assistant` audio capture**, so the learner can pause as long as she wants mid-sentence and the turn ends only when she speaks the end-word?

The current firmware **deliberately stops** on-device KWS during a turn (design notes: "no KWS during TTS", the microphone/I2S stream is treated as **single-owner**). The spike must determine whether concurrent capture — one mic feeding both a live `voice_assistant` turn **and** an end-word detector — is cleanly possible on current ESPHome.

---

## 2. Current firmware architecture findings (file:line cites)

Repo: `firmware/esphome/`. The two production configs are `coach-terminal-base.yaml` (shared base, used by the A/B face front-ends) and `coach-terminal.yaml` (folded single-file production). They are architecturally identical for audio.

**One physical mic, referenced by BOTH components:**
- `microphone:` defines a single `terminal_mic` on I2S bus `i2s_bus_mic` — `coach-terminal-base.yaml:118-127` (32-bit, 16 kHz, mono).
- `micro_wake_word: … microphone: terminal_mic` — `coach-terminal-base.yaml:138-140`.
- `voice_assistant: … microphone: terminal_mic` — `coach-terminal-base.yaml:148-151`.
  → Both components already point at the same mic id. What blocked concurrency historically was the *runtime ownership model*, not the wiring.

**Single-owner design is explicit and deliberate:**
- `micro_wake_word` uses `stop_after_detection` (self-stops on every detection) "to free the mic for the turn" — `coach-terminal-base.yaml:157-158`.
- Wake word is restarted by **exactly one owner**, an `interval: 1s` safety-net, and ONLY when `voice_assistant.is_running` is false — `coach-terminal-base.yaml:240-251`. The comment states restart is suppressed "During a turn — INCLUDING TTS playback … so there is no KWS-vs-I2S contention during playback (bug #1)" — `coach-terminal-base.yaml:238-239`.
- Direct evidence of the old single-owner I2S constraint: restarting the mic mid-turn "caused I2S 'parent bus is busy'" — `coach-terminal.yaml:219-221`; and the removal of per-event restarts was justified as "no double-management … no KWS during TTS" — `coach-terminal-base.yaml:162-163`.

**Separate, independent constraint — on-device KWS CPU budget:**
- Running **two `micro_wake_word` models at once** (hello_lingorm + okay_nabu) "overran the S3's real-time KWS inference budget and BROKE detection for both. One model detects cleanly (~0.90 …, cutoff 0.87)." — `coach-terminal.yaml:164-166` (also `coach-terminal-base.yaml:142-143`).
- Model manifest: `ml/kws/models/hello_lingorm.json` — `tensor_arena_size: 26080`, `probability_cutoff: 0.6`, `minimum_esphome_version: 2024.7.0`.

**Version actually installed / pinned:**
- `esphome version` → **2026.5.3** (system binary `/usr/bin/esphome`). No `min_version`/version pin in any yaml; the only version floor is the model manifest's `minimum_esphome_version: 2024.7.0`.

**Takeaway:** the firmware carries TWO distinct blockers that must not be conflated:
1. **Mic/I2S single-owner** (the "parent bus is busy" / "no KWS during TTS" design) — an *architectural* constraint of the era the firmware was written for.
2. **S3 real-time KWS inference budget** — a *hardware CPU* constraint, proven by the two-model overrun.

---

## 3. ESPHome capability findings (each with fetched source URL + version)

### 3.1 A single microphone can now be shared by multiple components concurrently — since ESPHome 2025.5.0
- **Source (fetched):** https://esphome.io/changelog/2025.5.0/ — quotes verbatim: **"Multiple components can simultaneously read from one microphone."** Each consumer sets its own gain/channel; settings validated at compile time. Introduces a `MicrophoneSource` helper for "passive audio capture across multiple simultaneous consumers", touching `i2s_audio`, `microphone`, `micro_wake_word`, `voice_assistant`.
- **Independent 2nd source (fetched):** https://github.com/esphome/esphome/pull/8645 (kahrendt, titled *"[i2s_audio, microphone, micro_wake_word, voice_assistant] Use microphone source to process incoming audio"*) — introduces the `MicrophoneSource` class "allowing `micro_wake_word` and `voice_assistant` to work with the same microphone input."
- **Version relevance:** feature landed **2025.5.0**; installed version **2026.5.3** is well past it. → **The mic/I2S single-owner blocker (blocker #1) is removed by the version already installed.** The firmware's "parent bus is busy" / "single-owner" comments reflect the *pre-2025.5.0* architecture.
- **Migration caveat (fetched, same changelog):** for a mic previously at **32 bits per sample** you should "add a gain factor of 4 to match ESPHome's previous behavior" (`gain_factor: 4`). The project mic is `bits_per_sample: 32bit`, so this applies if concurrency work touches the mic config. Existing YAML still builds without change; only the gain scaling differs. ⚠️ not re-verified on-device this session.

### 3.2 `micro_wake_word` supports multiple models with per-model enable/disable
- **Source (fetched):** https://esphome.io/components/micro_wake_word/ — "The models to use. Only the first model is enabled by default on the first boot." Per-model runtime actions exist: **`micro_wake_word.enable_model`** and **`micro_wake_word.disable_model`**, each taking a `model_id`; plus `micro_wake_word.start` / `micro_wake_word.stop`. `stop_after_detection` defaults to `true`.
- **Implication:** the end-word can be a *second model in the same `micro_wake_word` list*, toggled on only during a turn — so at any instant **only one model is active**, sidestepping the two-models-at-once overrun (blocker #2's known-bad case).

### 3.3 `voice_assistant` has NO native stop-word / end-of-turn-word feature, BUT exposes a manual stop hook
- **Source (fetched):** https://esphome.io/components/voice_assistant/ — documentation shows **no** stop-word, second-wake-word-to-end, or "pause indefinitely" feature. The only manual turn-terminator: **"Call `voice_assistant.stop` to signal the end of the voice command if `silence_detection` is set to `false`."**
- **Implication:** the end-of-turn mechanism is not a built-in; it must be *assembled* from `silence_detection: false` (so VAD never cuts the learner off mid-pause) + an end-word detection that fires `voice_assistant.stop`. This is **config-level automation**, not a source-code custom component.
- ⚠️ **Unverified:** the docs do not state whether `micro_wake_word` keeps *detecting* while `voice_assistant` is actively streaming STT — they only establish that the mic *stream* can be shared (§3.1). Whether on-device KWS inference and live STT streaming coexist within the S3's real-time budget is **not addressed by any doc I fetched** and is the crux of the verdict below.

### 3.4 Multi-mic-channel note (not required here, recorded for completeness)
- **Source (fetched):** https://esphome.io/components/micro_wake_word/ — up to two mic *sources* may be listed; the 2nd channel to HA needs Home Assistant ≥ 2026.6.0. Not needed for this single-mic design.

---

## 4. VERDICT — **CONDITIONAL**

**Why not PASS:** A clean PASS would require asserting that the ESP32-S3 can run `micro_wake_word` end-word inference **concurrently with a live `voice_assistant` STT stream** (plus `noise_suppression_level: 2`, `auto_gain`, and Wi-Fi audio streaming). No fetched source establishes that, and the project has **direct on-hardware evidence that the S3's real-time KWS budget is already tight** (two models broke each other — `coach-terminal.yaml:164-166`). Claiming PASS would violate evidence-first discipline.

**Why not FAIL:** The historical blocker everyone assumed ("single-owner mic → impossible") **no longer holds** on the installed version. ESPHome 2025.5.0's `MicrophoneSource` (§3.1, two sources) explicitly lets `micro_wake_word` and `voice_assistant` read the same mic simultaneously, and multi-model + per-model enable/disable + `voice_assistant.stop` + `silence_detection:false` (§3.2, §3.3) provide every config primitive needed — **no version bump, no custom C++ component required** for the wiring itself.

**The condition:** feasibility hinges on **one empirical, hardware-in-the-loop check** — does a single end-word model detecting *during* a live turn fit the S3 real-time budget? This is a bench test, not a code dependency. The blocker moved from *"architecturally impossible"* to *"architecturally supported since 2025.5.0, CPU-budget-unverified on this board."*

### Config sketch — *sketch only, to be validated on hardware; action names verified against docs §3.2/§3.3 but exact parameter forms not compiled*

```yaml
# SKETCH — not validated by a build. Two models in ONE micro_wake_word; only one
# active at a time, so the two-model real-time overrun is avoided.
micro_wake_word:
  id: kws
  microphone: terminal_mic
  models:
    - model: ../../ml/kws/models/hello_lingorm.json   # start-of-turn wake word
      id: mdl_wake
    - model: ../../ml/kws/models/end_turn.json         # end-word "voilà"/"terminé" (to train)
      id: mdl_end
  on_wake_word_detected:
    # NOTE: fires for whichever model is active. Branch on the detected word,
    # or (simpler) keep the detected-word check in the actions. SKETCH.
    - if:
        condition: { lambda: 'return id(va).is_running();' }   # end-word during a turn
        then:
          - voice_assistant.stop:                 # §3.3 manual turn terminator
        else:                                     # start-word while idle
          - micro_wake_word.disable_model: mdl_wake
          - micro_wake_word.enable_model:  mdl_end
          - voice_assistant.start:
          # micro_wake_word intentionally KEPT RUNNING here (do NOT stop it),
          # so mdl_end can detect during the turn — this is the concurrency the
          # spike is about; §3.1 makes the shared mic legal on 2026.5.3.

voice_assistant:
  id: va
  microphone: terminal_mic
  speaker: terminal_speaker
  use_wake_word: false
  silence_detection: false        # §3.3 — never cut the learner off on a pause
  on_end:
    - micro_wake_word.enable_model:  mdl_wake     # restore start-word for next turn
    - micro_wake_word.disable_model: mdl_end
```

Open items this sketch does **not** resolve (all require validation):
1. **CPU budget** — end-word inference during live STT streaming on the S3 (the verdict's condition).
2. **`on_wake_word_detected` per-model routing** — whether the trigger cleanly distinguishes which model fired, or whether two `micro_wake_word` blocks / a wake_word string check is needed. ⚠️ unverified.
3. Interaction with the existing `interval: 1s` restart safety-net (bug #0 fix) — it must be reworked so it does not fight the per-model enable/disable.
4. `gain_factor: 4` migration for the 32-bit mic (§3.1) if the mic block is touched.

---

## 5. Fallback (since not PASS): BOOT/GPIO0 push-to-talk end-of-turn

**Mechanism:** a `binary_sensor` (GPIO platform, internal pull-up, inverted) on the BOOT button; `on_press` (or `on_release`) → `voice_assistant.stop`, with `voice_assistant: silence_detection: false`. Learner presses the button when she has finished; the turn ends deterministically. No 2nd model, no ML, no added inference load. *(Config not sketched here to avoid unvalidated syntax; it is the standard binary_sensor → voice_assistant.stop pattern.)*

**Assessment — clearly simpler, and I recommend it as the default:**
- **Zero CPU risk.** Removes the verdict's only open condition entirely — no KWS-during-STT concurrency, so the S3 real-time budget is untouched.
- **Deterministic & debuggable.** A button press is unambiguous; an end-word detector adds a whole train/tune/false-trigger surface (a mid-sentence "voilà" would end the turn prematurely — a real UX hazard for a French coach where "voilà" is a common filler).
- **No new model to train.** The end-word path needs a second custom KWS model built through the full dev-kws lifecycle.
- ⚠️ **Caveat:** GPIO0 is an ESP32-S3 **strapping pin** (must read high at boot). A momentary-to-GND button with internal pull-up is the standard safe pattern *post-boot*; confirm the HW-678A doesn't hold GPIO0 in a way that conflicts, or use another free GPIO. Verify on the board.

---

## 6. Concrete next-step recommendation for the PM

**Ship the push-to-talk fallback (§5) as the CS-159 baseline; treat the concurrent end-word (§4) as a stretch goal gated on ONE bench test.**

1. **Now:** implement GPIO0 (or a confirmed-free GPIO) push-to-talk `voice_assistant.stop` + `silence_detection: false`. Low-risk, unblocks the "pause as long as you want" UX immediately, no ML dependency. (Confirm the strapping-pin caveat on the HW-678A first.)
2. **One-shot spike-2 (hardware-in-the-loop) before committing to the end-word path:** on the real S3 at 2026.5.3, flash a throwaway config that keeps a *single* `micro_wake_word` model detecting **during** an active `voice_assistant` turn (`silence_detection: false`) and measure: does KWS still detect reliably, and does STT stay intact? This directly tests the verdict's only condition. PASS there → promote the §4 sketch; FAIL → the fallback stands as the permanent solution.
3. Either way, the old "concurrent KWS is architecturally impossible" assumption in the firmware comments is **stale** for 2026.5.3 and should be annotated so future work doesn't re-derive it.

---

### Evidence ledger (sources fetched this session)
- https://esphome.io/changelog/2025.5.0/ — "Multiple components can simultaneously read from one microphone"; 32-bit `gain_factor: 4` migration note.
- https://github.com/esphome/esphome/pull/8645 — `MicrophoneSource`, lets `micro_wake_word` + `voice_assistant` share one mic.
- https://esphome.io/components/micro_wake_word/ — multi-model ("only the first enabled on first boot"), `enable_model`/`disable_model`/`start`/`stop`, `stop_after_detection`.
- https://esphome.io/components/voice_assistant/ — no native stop-word; `voice_assistant.stop` requires `silence_detection: false`.
- Repo reads: `coach-terminal-base.yaml` (lines cited §2), `coach-terminal.yaml` (lines cited §2), `ml/kws/models/hello_lingorm.json`, `esphome version` → 2026.5.3.

⚠️ **Unverified this session:** the S3 concurrent-CPU-budget outcome; exact `on_wake_word_detected` per-model routing syntax; the `gain_factor` on-device effect. All config blocks above are labelled sketches pending a build/flash.
