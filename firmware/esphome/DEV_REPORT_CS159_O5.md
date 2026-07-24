# DEV REPORT — CS-159 chantier 2: option O5 fork + end-word firmware refonte

Date: 2026-07-22. Offline work only: no flashing, no device access, no HA change,
no git command. Toolchain: ESPHome 2026.5.3 (`pip show esphome`).

The implementation was re-verified end to end in a second pass on the same day:
every upstream fact the fork relies on was re-read in the installed 2026.5.3
tree, both configs were re-validated and the forked C++ was force-recompiled
(object file deleted first). That pass found and closed one functional gap (the
`on_tts_start` backstop, section 3) and corrected one unverifiable claim in
`FORK_NOTES.md` (ESPHome prints no "loading local component" line). All outputs
in section 4 come from that pass.

## 1. What was built

| # | Deliverable | Location |
|---|---|---|
| 1 | Local fork of `voice_assistant` with a graceful `voice_assistant.finish` action | `firmware/esphome/components/voice_assistant/` (+ `FORK_NOTES.md`) |
| 2 | End-word refonte of the production firmware | `firmware/esphome/coach-terminal-base.yaml` |

Files created:

- `components/voice_assistant/__init__.py` (copy of 2026.5.3 + 17 lines)
- `components/voice_assistant/voice_assistant.h` (copy + 11 lines)
- `components/voice_assistant/voice_assistant.cpp` (copy + 38 lines)
- `components/voice_assistant/FORK_NOTES.md` (fork rationale, complete diff,
  upgrade procedure)
- `DEV_REPORT_CS159_O5.md` (this file)

File modified: `coach-terminal-base.yaml`. Untouched: `coach-terminal.yaml`,
`coach-terminal-benchtest-cs159.yaml`, `coach-terminal-faces-drawn.yaml`,
`coach-terminal-faces-bitmap.yaml` (both variants inherit the change through
`packages:`).

## 2. Deliverable 1 — the fork

66 added lines, 0 removed, 0 modified vs upstream 2026.5.3 (42 code + 19 comment
+ 5 blank lines; the counting command is given in `FORK_NOTES.md` so the figures
can be reproduced instead of trusted). The complete diff is reproduced in
`components/voice_assistant/FORK_NOTES.md`; summary:

- `__init__.py`: declare `FinishAction` and register the action
  `voice_assistant.finish` on the existing `VOICE_ASSISTANT_ACTION_SCHEMA`.
- `voice_assistant.h`: `request_finish()` (public), `signal_finish_()`
  (protected), and the `FinishAction` template calling `request_finish()`.
- `voice_assistant.cpp`: the two method bodies.

`request_finish()` does exactly the two things the memo requires:

1. `signal_finish_()` sends `api::VoiceAssistantAudio` with `end = true`. That is
   the graceful stop: `aioesphomeapi` maps it to `handle_stop(False)` ->
   `_stop_pipeline()`, which closes the audio stream so STT transcribes what it
   already has and the pipeline continues to the reply (memo F9). `end` is a real
   encoded field of the struct (`api_pb2.h:2445`, `api_pb2.cpp:2909` field 2).
2. `set_state_(State::STOP_MICROPHONE, State::AWAITING_RESPONSE)` — the same
   local transition the `STT_VAD_END` handler performs
   (`voice_assistant.cpp:938`), so the microphone is released before playback.
   Without it the mic is only stopped at `RUN_END`, i.e. after TTS (memo F9).

Guard: `request_finish()` is a no-op with `ESP_LOGW("Finish ignored, not
capturing speech (state %s, desired %s)")` unless `state_ ==
STREAMING_MICROPHONE`, i.e. unless the component is actually streaming the
learner's speech. Nothing else is touched: unlike `request_stop()`,
`continuous_` and `continue_conversation_` keep their values.

Failure path: `signal_finish_()` returns the bool from
`APIConnection::send_message()`. If the message could not be queued, the fork
logs `ESP_LOGE("Failed to signal end of speech, aborting the turn")` and calls
`request_stop()` instead of transitioning to `AWAITING_RESPONSE`.

Design decisions worth reviewing:

- **Why a new action and not a change to `StopAction`.** `voice_assistant.stop`
  keeps its abort semantics for genuine cancels; `finish` is additive, so any
  other YAML in the repo keeps working unchanged.
- **Why the guard uses `state_` and not `desired_state_`.** `desired_state_` is
  already `STREAMING_MICROPHONE` during `START_MICROPHONE` and
  `STARTING_MICROPHONE` (`start_streaming()` sets both), i.e. before any audio
  has reached Home Assistant. Finishing in that window would close an empty
  stream, and the jump to `STOP_MICROPHONE` would be taken while the microphone
  is still coming up — `loop()`'s `STOP_MICROPHONE` case sees `is_running()`
  false and goes straight to `AWAITING_RESPONSE`, leaving a microphone about to
  come up unattended. Testing `state_` restricts the action to the window where
  audio is genuinely flowing. Both values are printed in the rejection warning,
  since either can be the reason.
- **Why a dropped `finish` message aborts instead of waiting.** Ignoring the
  `send_message()` return value would release the microphone and park the device
  in `AWAITING_RESPONSE`, which has no device-side timeout, while option O2
  removes the server VAD that could otherwise close the stage — the turn would
  hang until the `coach_stt` 120 s backstop. A visible abort (red LED, error
  screen through `on_error`) is the better failure mode.
- **Log line as fork evidence.** `Signaling end of speech (voice_assistant.finish)`
  does not exist upstream, so a device log proves which component is running.

## 3. Deliverable 2 — the refonte in `coach-terminal-base.yaml`

Turn lifecycle now implemented:

| Moment | KWS state | Action |
|---|---|---|
| boot | end model off, wake model on, KWS started | explicit, so a crash cannot leave a stale flash flag armed |
| idle | wake model armed, `end_word_window` cleared | interval safety-net keeps it that way |
| wake word detected (pipeline idle) | KWS self-stops | `voice_assistant.start: silence_detection: false` |
| `on_listening` (STT started) | wake model off, end model on, `end_word_window` set, KWS restarted (interval repairs a lost start within 1 s) | UI state 2 |
| end word detected (pipeline running) | KWS self-stops, wake model re-armed, `end_word_window` cleared | `voice_assistant.finish`, UI state 3 (gated on the window) |
| `on_stt_end` | KWS stopped, wake model re-armed | UI state 3 |
| `on_tts_start` | KWS stopped, wake model re-armed (backstop) | UI state 4, amp on |
| TTS | KWS stopped | amp SD gating unchanged |
| `on_error` | KWS stopped, wake model re-armed | UI state 5 |

Key decisions:

- **Only ever one enabled model.** The session-17 lesson (two simultaneous models
  overran the S3 real-time budget) is respected by construction:
  `micro_wake_word` loads a model's tensor arena lazily on the first inference
  after it is enabled and unloads it as soon as it is disabled
  (`streaming_model.h:33-49`, `streaming_model.cpp`), so exactly one inference
  runs per audio slice. The second model costs flash (a second copy of the 60 928
  byte tflite, currently the placeholder) but no steady-state RAM or CPU.
- **Routing by pipeline state, not by phrase.** `voice_assistant.is_running` is
  the test, as in the bench. This is required today (the placeholder end-word
  model reports the same phrase "hello lingorm") and stays correct once
  `jai_fini.json` exists, since only one model is ever enabled.
- **Placeholder.** Both model entries point at `hello_lingorm.json`; the end-word
  entry carries `# TODO CS-159: swap to ../../ml/kws/models/jai_fini.json once
  chantier 1 has trained it`. A second entry cannot be validated without an
  existing manifest, and both models must share `feature_step_size`
  (`micro_wake_word/__init__.py:426`), which the same file trivially satisfies.
- **`internal: true` on the end-word model.** Keeps it out of the wake words
  advertised to Home Assistant and keeps its enabled flag out of flash
  (`streaming_model.cpp:272-284`), so only the wake word model's flag is
  persisted.
- **Single-owner interval preserved and extended.** The interval remains the only
  owner of the idle-path KWS restart (the fix for bug #0). CS-159 adds a second,
  separately guarded branch to the same interval: when the pipeline is idle, the
  armed model must be the wake word. That covers the paths where no
  `voice_assistant` event fires at all (mid-turn wifi/HA drop) and would
  otherwise leave the end word armed while idle. The guard means the flash flag
  is written only on a real transition, not once per second.
- **In-turn KWS arming is self-healing, not one-shot (fix for the review's H-1).**
  The `micro_wake_word.start` in `on_listening` is only a fast path and it is
  best-effort: `MicroWakeWord::stop()` is asynchronous (it sets `pending_stop_`
  and the component walks DETECTING -> STOPPING -> STOPPED across several
  `loop()` iterations, `micro_wake_word.cpp:371-379`, `:205-206`). `on_listening`
  fires on the `STT_START` event, i.e. after a network round trip to HA, so it is
  usually later than that teardown — but not guaranteed. If the teardown is still
  in flight, `is_running()` is true, the guarded start is skipped, the pending
  stop wins and micro_wake_word settles in STOPPED with nothing left to restart
  it: the end word would be dead for the WHOLE turn, and with O2 deployed the
  turn could then only end at the `coach_stt` 120 s backstop. Dropping the guard
  does not help either, since `start()` early-returns while `is_running()` is
  true. The fix is a boolean global `end_word_window`, set at `on_listening` and
  cleared by every event that closes the listening window (the end-word detection
  itself, `on_stt_end`, `on_tts_start`, `on_error`, `on_client_disconnected`, and
  the idle branch of the interval). The interval gets an `else:` branch that
  restarts KWS while `end_word_window` is set AND the end model is the armed one,
  so a lost start costs at most 1 s instead of the turn. It cannot restart KWS
  during playback: the flag is cleared before TTS on every path, which is what
  preserves the "no KWS during TTS" invariant (bug #1).
- **`on_listening` is still the only in-turn `micro_wake_word.start` outside the
  interval**, and it is guarded by `not micro_wake_word.is_running` so it never
  logs "already running". KWS is stopped again at `on_stt_end`, at the end-word
  detection (`stop_after_detection`), at `on_error` and at `on_tts_start` —
  always before playback.
- **The UI "thinking" state is gated on the same window.** `voice_assistant.finish`
  is itself guarded device-side, so setting `ui_state = 3` unconditionally after
  it could show a thinking face while the coach is actually speaking. The
  end-word branch now sets the UI only inside `end_word_window`, which is the
  YAML-visible equivalent of the C++ guard. The model re-arm stays
  unconditional: a detection outside the window must still leave the wake word
  armed.
- **`on_tts_start` backstop (gap found and closed during verification).** The
  component DROPS an `STT_END` event whose text is empty — upstream
  `voice_assistant.cpp:762-764`, `ESP_LOGW("No text in STT_END event"); return;`
  — so on that path `on_stt_end` never fires. Through THIS pipeline that path now
  looks unreachable (an empty transcript makes `assist_pipeline` raise
  `stt-no-text-recognized`, `pipeline.py:985-987`, which arrives as a
  `VOICE_ASSISTANT_ERROR` already handled by `on_error`), so the necessity below
  is stated as a defence against unknown paths, not as an established fact. The
  backstop is kept because it is free. Without a second stop, the end word
  would still be armed AND running when playback starts, reproducing bug #1 (KWS
  contending with the speaker I2S path). `on_tts_start` therefore repeats
  `micro_wake_word.stop` + the model swap. Cost on the normal path is zero:
  `MicroWakeWord::stop()` returns silently when already `STOPPED`
  (`micro_wake_word.cpp:371-373`) and an unchanged preference blob is not written
  to NVS (`esp32/preferences.cpp:165-183`, `is_changed_` does a `memcmp` first).
  The interval safety-net cannot cover this case, because it only ever RESTARTS
  KWS and only while the pipeline is idle — during TTS `is_running` is true.

Preserved production behaviours (verified by reading the diff of the file):
`gain_factor: 4` on both the `micro_wake_word` and `voice_assistant` microphone
sources, amp SD gating on `on_tts_start` / `on_tts_stream_start` /
`on_tts_stream_end` / `on_error`, wake word decoupled from HA
(`on_boot` start, no stop on `on_client_disconnected`), UI state machine 0-5, LED
colours, both display variants building from the same base.

## 4. Validation (exact commands and exit codes)

Working directory `firmware/esphome`, ESPHome 2026.5.3, run after the final edit
of every file listed in section 1 (the `on_tts_start` backstop included).

```
$ esphome config coach-terminal-faces-drawn.yaml
INFO Configuration is valid!
CONFIG_DRAWN_EXIT=0

$ esphome config coach-terminal-faces-bitmap.yaml
INFO Configuration is valid!
CONFIG_BITMAP_EXIT=0

$ esphome compile coach-terminal-faces-drawn.yaml
Compiling .pioenvs/coach-terminal/src/esphome/components/voice_assistant/voice_assistant.cpp.o
Compiling .pioenvs/coach-terminal/src/main.cpp.o
RAM:   [==        ]  16.1% (used 52708 bytes from 327680 bytes)
Flash: [==        ]  15.8% (used 1280359 bytes from 8126464 bytes)
Successfully created ESP32-S3 image.
========================= [SUCCESS] Took 23.68 seconds =========================
INFO Successfully compiled program.
COMPILE_EXIT=0
```

These figures are from the post-review-fix rebuild (round 1 of the review loop),
which recompiled the fork because `voice_assistant.cpp` had genuinely changed —
the `Compiling .../voice_assistant/voice_assistant.cpp.o` line above is a real
recompilation, not a cache hit. It produced no compiler warning or error;
checked by grepping the whole log for `error` and `warning`, whose only match in
the run is the unrelated pre-existing config warning "WiFi AP is configured but
neither captive_portal nor web_server is enabled". RAM and flash grew by 192 and
1076 bytes respectively against the pre-fix build (52 516 / 1 279 283), which is
the cost of the added state check, the error branch and the extra global.

`coach-terminal-base.yaml` is not directly buildable (no `display:`), so the
`faces-drawn` variant that actually gets flashed was validated, plus the
`faces-bitmap` variant that shares the same base.

Proof the fork is the code being built, not the bundled component. ESPHome
2026.5.3 prints NO "loading local component" line, so the evidence is:

- `esphome config` dumps
  `external_components: - source: {path: <REPO_ROOT>/firmware/esphome/components, type: local}`
  with `components: [voice_assistant]`, and accepts
  `- voice_assistant.finish: {}` — an action that does not exist in ESPHome
  2026.5.3, so acceptance alone proves the override took effect.
- `diff -q .esphome/build/coach-terminal/src/esphome/components/voice_assistant/voice_assistant.cpp components/voice_assistant/voice_assistant.cpp`
  reports no difference (build tree carries the fork, not the bundled file), and
  that copy contains `request_finish`.
- Generated `main.cpp` instantiates
  `voice_assistant::FinishAction<std::string>` (lines 126-127, 1420) and wires it
  into the end-word branch of `on_wake_word_detected`.

Upstream facts the fork depends on, re-verified in this session against the
installed 2026.5.3 tree:

| Claim | Evidence |
|---|---|
| `VoiceAssistantAudio` carries `bool end` and ENCODES it (not decode-only) | `api_pb2.h:2445` field, `:2448` `encode()`; `api_pb2.cpp:2909` `encode_bool(..., 2, this->end)` |
| HA maps `end: true` to the graceful stop | `aioesphomeapi/client.py:1927-1932` -> `handle_stop(False)` (local 45.3.1, same code as v45.6.1 quoted in the memo) |
| `state_ == STREAMING_MICROPHONE` is reached before `on_listening` can fire | set by `start_streaming()` (`voice_assistant.cpp:599-607`); `on_listening` fires on the `STT_START` event (`:777-778`), i.e. strictly after it |
| `send_message()` returns a bool meaning "queued" | upstream checks it itself on the pipeline-start request (`voice_assistant.cpp:303`) |
| `request_stop()` from `STREAMING_MICROPHONE` signals the stop and returns to IDLE | `voice_assistant.cpp:659-676` |
| Only the FIRST declared model is enabled on first boot | `micro_wake_word/__init__.py:497` `default_enabled = i == 0` |
| `internal: true` keeps the enabled flag out of flash | `streaming_model.cpp:272-284`, `pref_.save()` guarded by `!internal_only_` |
| `micro_wake_word.stop` is silent when already stopped | `micro_wake_word.cpp:371-373` |

## 5. Open risks (all require the device or the NAS, i.e. out of scope here)

1. **Half the fix is server-side.** Without option O2 on the NAS (custom STT
   entity returning `requires_external_vad=False`), Home Assistant's
   `VoiceCommandSegmenter` still ends the turn after the silence window and still
   caps it at 15 s (memo F3/F5). The firmware then only wins a race, exactly as
   in the bench. O2 also needs HA core >= 2026.5.0, still unverified on the NAS.
2. **`VoiceAssistantAudio{end: true}` is only observed to work from source
   reading** (`aioesphomeapi` v45.6.1 + HA 2026.7.3). It has not been exercised
   against the actual HA instance. If the running HA is older, verify that
   `_on_voice_assistant_audio` routes `end` to `handle_stop(False)`.
3. **Placeholder end word.** Until chantier 1 delivers `jai_fini.json`, the end
   word IS "hello lingorm", so any bench run repeats the phrase, and a false
   trigger during the learner's speech ends the turn early.
4. **KWS during STT capture is proven, KWS + `finish` is not.** The bench proved
   concurrent detection during capture on HW-678A; it did not exercise the new
   graceful finish, the model swap, or the flash-persisted enabled flag.
5. **Timing edge — downgraded after verification.** The `finish` guard rejects a
   detection made before the component reaches `state_ == STREAMING_MICROPHONE`.
   That window is believed unreachable: the end-word model is only armed in
   `on_listening`, which fires on the `STT_START` event
   (`voice_assistant.cpp:777-778`), strictly after `start_streaming()` has set
   the state (`:599-607`). If it ever happens, the symptom is the log line
   `Finish ignored, not capturing speech (state ..., desired ...)` and a turn
   that ends on the server VAD instead; no deadlock, since the interval
   safety-net re-arms the wake word once the pipeline is idle. With the guard now
   testing `state_`, the rejected window is strictly larger than before (it also
   covers `START_MICROPHONE` / `STARTING_MICROPHONE`), which is intentional: in
   those sub-states no audio has reached HA yet.
8. **A dropped `finish` message aborts the turn.** New behaviour: if
   `send_message()` returns false the turn is aborted rather than left hanging.
   Never observed (it needs TX buffer pressure), so the abort path itself is
   unexercised. Symptom in the log: `Failed to signal end of speech, aborting the
   turn`, followed by the error face. If this ever appears in normal use, the fix
   is to retry rather than abort.
6. **Flash flag wear — quantified.** The wake word model is not `internal`, so
   its enabled flag is saved on each arm/disarm. ESPHome does not rewrite an
   unchanged blob (`esp32/preferences.cpp:165-183` compares with `memcmp` first),
   but the value genuinely alternates, so a normal turn produces two NVS writes.
   Total endurance was NOT measured and no figure should be quoted. If it ever
   matters, marking the wake word model `internal: true` as well removes the
   writes entirely (`on_boot` already arms the models explicitly, so nothing
   depends on the persisted flag) at the cost of no longer advertising the wake
   word to Home Assistant.
7. **Empty-transcript path is covered but never exercised.** The `on_tts_start`
   backstop was added from source reading (`voice_assistant.cpp:762-764`); no
   bench run has produced an empty `STT_END` yet. Watch for a `No text in STT_END
   event` warning followed by normal playback in the next device log.

## 6. Hardware test plan for the next session (named items, not "run a turn")

Nothing below can be done offline. Each item states what to do and what result
accepts it. Items 1 and 2 are the ones this design has never exercised on
hardware and must not be folded into a generic smoke test.

1. **Utterance onset across the KWS stop/restart on the shared microphone.**
   This is the one behaviour the CS-159 bench did NOT cover: it ran with
   `stop_after_detection: false`, so KWS was never stopped, whereas the
   production sequence now tears the KWS microphone consumer down
   (`micro_wake_word.cpp:205-206` calls `microphone_source_->stop()` on the
   shared `terminal_mic`) and re-opens it at `on_listening` while
   `voice_assistant` is already streaming the same I2S source. A glitch or a lost
   leading fragment would land exactly where the learner starts speaking.
   Procedure: say the wake word, then immediately (no pause) speak a sentence
   whose first syllable is distinctive, e.g. "Bonjour, je voudrais un cafe".
   Capture the first ~2 s of the turn — from the Home Assistant pipeline debug
   trace (the `stt-start` / `stt-end` pair with the returned transcript) and, if
   available, by saving the audio the ASR service received. Repeat 5 times.
   Accepted if the first word is present and correctly transcribed in 5 runs out
   of 5, with no clipped or dropped leading syllable. If it fails, the fallback
   is to delay the in-turn KWS restart (only the interval branch arms it, at the
   cost of up to 1 s) or to keep KWS running through the turn with
   `stop_after_detection: false`, as the bench did.
2. **In-turn KWS restart actually happens (H-1 fix).** Watch the serial log
   during a turn: after the `on_listening` event there must be a
   `micro_wake_word` start, either immediately or within 1 s from the interval
   branch. Accepted if the end word is detected during the turn in 5 runs out of
   5. Deliberately try one turn where the wake word and the end word follow each
   other very quickly, which is the case most likely to lose the race to the
   asynchronous stop.
3. **No KWS during TTS (bug #1 regression check).** Over a full turn, confirm no
   `micro_wake_word` start appears between `on_tts_start` and
   `on_tts_stream_end`, and that playback has no dropout. Accepted on 3 clean
   turns.
4. **Graceful finish keeps the transcript and the reply.** The end word must
   produce the log line `Signaling end of speech (voice_assistant.finish)`, and
   Home Assistant must still return a transcript and speak a reply. Accepted when
   the pipeline debug trace shows a normal `stt-end` -> `intent` -> `tts` chain
   with no abort.
5. **Turn survives a long silence.** With O2 deployed, stay silent for more than
   the old 15 s cap mid-turn, then say the end word. Accepted if the turn is
   still ended by the end word and not by the server.
6. **Backstop path.** Start a turn and never say the end word. Accepted if the
   turn is cut at the configured maximum with `Maximum turn duration of 120 s
   reached` in the Home Assistant log. While doing it, watch memory and log
   timestamps on the Home Assistant side: once the backstop fires the integration
   stops consuming the stream but the satellite keeps feeding the queue until the
   run ends. Expected to be bounded; note anything that suggests otherwise.
7. **Wifi/HA drop mid-turn.** Power-cycle the network mid-turn. Accepted if the
   terminal returns to the idle face with the wake word armed and running within
   a few seconds, without a reboot.

Prerequisite for anything involving a real learner: `jai_fini.json` must exist.
Until then the end word IS "hello lingorm" (see the RELEASE GATE comment in
`coach-terminal-base.yaml`), so these runs are bench runs only.
