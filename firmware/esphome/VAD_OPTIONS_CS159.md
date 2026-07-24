# CS-159 — Who ends the turn, and how to make the end-word the sole terminator

Read-only investigation memo. No firmware, config or service was modified.

## 0. Scope, sources and version caveats

Question: for an ESPHome voice satellite driven by a Home Assistant Assist
pipeline, which component decides that the user has finished speaking, and can
that decision be handed over entirely to an on-device end-word detector?

Sources actually read in this investigation:

| Source | Version | How obtained |
|---|---|---|
| ESPHome `voice_assistant` component | 2026.5.3 | local install, `/usr/lib/python3.14/site-packages/esphome/components/voice_assistant/` (`pip show esphome` -> 2026.5.3) |
| ESPHome `micro_wake_word` component | 2026.5.3 | same tree |
| ESPHome generated API structs | 2026.5.3 | `esphome/components/api/api_pb2.h` |
| `aioesphomeapi` | local 45.3.1, and v45.6.1 (the version pinned by HA `esphome/manifest.json`) | local install + `raw.githubusercontent.com/esphome/aioesphomeapi/v45.6.1` |
| Home Assistant core | tag `2026.7.3` (latest release per GitHub releases API) and `dev` | `raw.githubusercontent.com/home-assistant/core/2026.7.3/...` |
| `wyoming-faster-whisper` | 3.1.0 (with `faster-whisper` 1.2.1) | local venv `<VOICE_VENV>/.../wyoming_faster_whisper/` |
| ESPHome documentation | current | `https://esphome.io/components/voice_assistant/`, `https://esphome.io/components/external_components/` |

Caveat that must be closed before implementing: **the HA core version running on
the Synology NAS is unknown.** `http://<NAS_IP>:8123/api/` returns 401 and
no unauthenticated endpoint exposes the core version, so the version was not
verified in this session. All HA line numbers below are from tag `2026.7.3`, and
every claim was cross-checked against `dev` (identical). One recommendation below
requires HA core **>= 2026.5.0** — see F7.

---

## 1. Findings

### F1. `silence_detection` is an option of the `voice_assistant.start` ACTION, not of the component

In ESPHome 2026.5.3 the component-level schema (`voice_assistant/__init__.py`,
lines 95-175) has no `silence_detection` key. The key exists only on the action:

- `__init__.py:417` — `cv.Optional(CONF_SILENCE_DETECTION, default=True): cv.boolean`
  inside `@register_action("voice_assistant.start", StartAction, ...)`.
- `__init__.py:426-427` — `cg.add(var.set_silence_detection(...))`.

The project's bench firmware uses it correctly at
`coach-terminal-benchtest-cs159.yaml:179-180`
(`voice_assistant.start:` / `silence_detection: false`).

Note a trap for later: `voice_assistant.start_continuous` has **no** such
parameter and hardcodes VAD on — `voice_assistant.h:357`,
`this->parent_->request_start(true, true);`.

### F2. On the device, `silence_detection` only sets one bit in the pipeline-start request

- `voice_assistant.h:346` — `StartAction::play()` -> `request_start(false, this->silence_detection_)`.
- `voice_assistant.cpp:282-283` — `if (this->silence_detection_) flags |= api::enums::VOICE_ASSISTANT_REQUEST_USE_VAD;`

The bit value is defined in `aioesphomeapi/model.py:1774-1776`:

```
class VoiceAssistantCommandFlag(enum.IntFlag):
    USE_VAD = 1 << 0
    USE_WAKE_WORD = 1 << 1
```

That is the entire on-device effect. The device does no end-of-speech detection
of its own in either case.

### F3. Home Assistant IGNORES the `USE_VAD` bit — this is the root cause

The ESPHome integration receives those flags in
`homeassistant/components/esphome/assist_satellite.py`,
`handle_pipeline_start(self, conversation_id, flags, audio_settings, wake_word_phrase)`
(line 523 in 2026.7.3). The **only** test performed on `flags` in the whole
function is line 556:

```python
if flags & VoiceAssistantCommandFlag.USE_WAKE_WORD:
    start_stage = PipelineStage.WAKE_WORD
else:
    start_stage = PipelineStage.STT
```

`USE_VAD` is never read anywhere in that file, and `manager.py` does not touch
`flags` at all. The `audio_settings` argument (noise suppression, auto gain,
volume multiplier sent by the device) is likewise never forwarded: the pipeline's
`AudioSettings` object is built in the shared base class
`homeassistant/components/assist_satellite/entity.py:531-533` with exactly one
field set:

```python
audio_settings=AudioSettings(
    silence_seconds=self._resolve_vad_sensitivity()
),
```

`AudioSettings.is_vad_enabled` therefore keeps its default `True`
(`assist_pipeline/pipeline.py:519`).

**Conclusion: `silence_detection: false` on the device is a no-op for a Home
Assistant Assist pipeline.** This exactly matches the bench observation recorded
in `BENCH_RESULT_CS159.md` ("device `silence_detection: false` does NOT disable
HA's server-side end-of-speech VAD").

### F4. The actual turn-ender is `VoiceCommandSegmenter` inside HA's assist_pipeline

`assist_pipeline/pipeline.py:950-957`:

```python
stt_vad: VoiceCommandSegmenter | None = None
if (
    self.audio_settings.is_vad_enabled
    and self.stt_provider.audio_processing.requires_external_vad
):
    stt_vad = VoiceCommandSegmenter(
        silence_seconds=self.audio_settings.silence_seconds
    )
```

and `pipeline.py:1003-1035` (`_speech_to_text_stream`): for every audio chunk it
calls `stt_vad.process(...)`; when that returns `False` it fires
`PipelineEventType.STT_VAD_END` (line 1021) and `break`s out of the loop, which
closes the audio generator feeding the STT engine.

On the device, that event is what visibly ends the turn —
`voice_assistant.cpp:932-939`:

```cpp
case api::enums::VOICE_ASSISTANT_STT_VAD_START:
  ESP_LOGD(TAG, "Starting STT by VAD");
...
case api::enums::VOICE_ASSISTANT_STT_VAD_END:
  ESP_LOGD(TAG, "STT by VAD end");
  this->set_state_(State::STOP_MICROPHONE, State::AWAITING_RESPONSE);
```

So the two log lines seen on the device are *received events*, not device
decisions. The device is a passive reporter here.

### F5. What the 3-option select maps to numerically — and the hidden 15-second cap

The select the user sees ("finished speaking detection", i.e. how long a silence
must last before Home Assistant decides the speaker has finished) is
`VadSensitivitySelect` (`assist_pipeline/select.py:145-155`), instantiated for
ESPHome devices as `EsphomeVadSensitivitySelect` (`esphome/select.py:56`,
`103-109`). Its options are exactly the enum members, and the numbers are in
`assist_pipeline/vad.py:13-30`:

| Select option | `silence_seconds` |
|---|---|
| aggressive | 0.25 |
| default | 0.70 |
| relaxed | 1.25 |

(The user's "Relaxed ~1s" is 1.25 s.) There is no "off" member, so the UI can
never disable it. `Pipeline` itself (`pipeline.py:417-433`) has no VAD field, so
there is nothing to set in `configuration.yaml` either.

Second, less obvious limit — `assist_pipeline/vad.py:73-147`:

```python
@dataclass
class VoiceCommandSegmenter:
    speech_seconds: float = 0.3
    command_seconds: float = 1.0
    silence_seconds: float = 0.7
    timeout_seconds: float = 15.0      # line 85
    reset_seconds: float = 1.0
```

`process()` decrements `_timeout_seconds_left` on **every** chunk and never
refills it while speech continues; only `reset()` (called when a command finishes
or when the timeout fires) restores it. Since `pipeline.py:955-957` constructs
the segmenter with `silence_seconds` only, `timeout_seconds` stays at its default.

**Consequence: the STT capture window is hard-capped at 15 seconds from the start
of the STT stage, regardless of whether the learner is still speaking.** The log
line is `"VAD end of speech detection timed out after %s seconds"`
(`vad.py:141-144`). For a learner doing long French monologues this is a second,
independent blocker that lengthening the silence window would not fix.

### F6. wyoming-faster-whisper's `--vad-filter` is exonerated

Local source, `wyoming_faster_whisper/dispatch_handler.py:47-91`: every
`AudioChunk` is appended to a temporary WAV file ("Audio is saved to a WAV file
for transcription later. None of the underlying models support streaming."), and
transcription runs only when `AudioStop` arrives. `--vad-filter` is passed
straight into `model.transcribe(..., vad_filter=self.vad_filter)`
(`faster_whisper_handler.py:23,41-46`), i.e. it filters silence *inside* an
already-complete recording.

The whisper service therefore never terminates a turn; it accepts an arbitrarily
long stream and only reacts to the stream being closed by HA. It is not the
problem, and lengthening the turn creates no whisper-side issue.

Corollary that kills one candidate option: a **wyoming middleman proxy cannot
help**, because HA's segmenter sits *upstream* of the STT provider. By the time
audio would reach a proxy, HA has already decided to stop sending it.

### F7. There IS a supported HA-side lever: `SpeechToTextEntity.audio_processing`

Re-read the condition in F4: the segmenter is created only if
`self.stt_provider.audio_processing.requires_external_vad` is also true.

- `stt/models.py:36-55` defines `SpeechAudioProcessing` with
  `requires_external_vad: bool` ("True if an external voice activity detector
  (VAD) is required. If False, the speech-to-text entity must detect the end of
  speech itself") and `DEFAULT_AUDIO_PROCESSING = SpeechAudioProcessing(requires_external_vad=True, ...)`.
- `stt/__init__.py:204-207` — `SpeechToTextEntity.audio_processing` returns that
  default unless the entity overrides it.
- `wyoming/stt.py` (`WyomingSttProvider`) does **not** override it, so the
  Coach FR pipeline currently gets `requires_external_vad=True`.

An STT entity that returns `requires_external_vad=False` makes HA skip
`VoiceCommandSegmenter` entirely — killing both the 1.25 s silence cut and the
15 s cap in one move, through a documented public property, with no core patching.

Version boundary, verified by fetching `stt/models.py` at several tags:

| HA tag | `requires_external_vad` present |
|---|---|
| 2026.4.0 / 2026.4.1 / 2026.4.4 | no |
| 2026.5.0b0 / 2026.5.0 / 2026.6.4 / 2026.7.3 | yes |

So this lever requires **HA core >= 2026.5.0**. Before 2026.5.0 the segmenter was
gated by `is_vad_enabled` alone (checked at tag 2026.4.0, `pipeline.py:947-951`),
which satellites cannot set.

For completeness: HA *does* expose a full VAD off-switch, but only to WebSocket
clients — `assist_pipeline/websocket_api.py:211-215` builds
`AudioSettings(..., is_vad_enabled=not msg_input.get("no_vad", False))`. That path
is used by the browser/companion app, not by ESPHome satellites.

### F8. `voice_assistant.stop` from the device ABORTS the pipeline — it does not finalize STT

This is the finding that most changes the CS-159 design, and it contradicts the
ESPHome documentation.

Device side, `voice_assistant.cpp:705-714`:

```cpp
void VoiceAssistant::signal_stop_() {
  ...
  api::VoiceAssistantRequest msg;
  msg.start = false;
  this->api_client_->send_message(msg);
}
```

Client side, `aioesphomeapi` v45.6.1 `client.py:1907-1927`:

```python
command = VoiceAssistantCommand.from_pb(msg)
if command.start:
    ... handle_start(...)
else:
    self._create_background_task(handle_stop(True))     # abort=True
```

HA side, `esphome/assist_satellite.py:631-635` and `779-789`:

```python
async def handle_pipeline_stop(self, abort: bool) -> None:
    if abort:
        self._abort_pipeline()
    else:
        self._stop_pipeline()
...
def _stop_pipeline(self) -> None:          # graceful: closes the audio stream
    self._audio_queue.put_nowait(None)
def _abort_pipeline(self) -> None:         # hard: closes the stream AND cancels the run
    self._audio_queue.put_nowait(None)
    if self._pipeline_task is not None:
        self._pipeline_task.cancel()
```

So a device-initiated `voice_assistant.stop` cancels the whole pipeline task:
no transcript, no conversation stage, no TTS reply.

The documented push-to-talk recipe on
`https://esphome.io/components/voice_assistant/` ("Push to Talk": `on_press:
voice_assistant.start: silence_detection: false` / `on_release:
voice_assistant.stop:`, plus the prose "Call `voice_assistant.stop` to signal the
end of the voice command if `silence_detection` is set to `false`") describes an
intent that the current HA + aioesphomeapi code path no longer implements: the
flag is ignored (F3) and the stop is an abort (this finding).

Practical impact on the bench already run: the two mid-turn end-word events
(08:57:19.675 and 08:57:31.698 in `BENCH_RESULT_CS159.md`) would have aborted the
pipeline, so "the end-word stopped the turn" is expected to mean "stopped without
any coach reply". `BENCH_RESULT_CS159.md` does not record whether a reply
followed those two stops. **Verify this on the device before designing around it**
— it is the single cheapest confirmation of this memo.

### F9. There is a graceful device-initiated stop in the protocol, just not wired into a YAML action

`aioesphomeapi` v45.6.1 `client.py:1934-1939`:

```python
def _on_voice_assistant_audio(msg: VoiceAssistantAudio) -> None:
    audio = VoiceAssistantAudioData.from_pb(msg)
    if audio.end:
        self._create_background_task(handle_stop(False))   # graceful
    else:
        self._create_background_task(handle_audio(audio.data, audio.data2))
```

`end` is a real field of the message in both directions:
`aioesphomeapi/model.py:1799-1802` and, on the device, ESPHome's generated struct
`esphome/components/api/api_pb2.h:2436-2447` (`bool end{false};`).

The stock ESPHome component never sets it: the only place it builds a
`VoiceAssistantAudio` is the streaming loop at `voice_assistant.cpp:318-341`,
which sets `data`/`data2` only. So the graceful "the user has finished, transcribe
what you have" signal exists in the wire protocol and is understood by HA, but is
unreachable from YAML today.

Also relevant to any device-initiated end: without an `STT_VAD_END` event the
device does not stop its microphone. `voice_assistant.cpp:871-878` shows the
microphone is otherwise only stopped at `RUN_END` (i.e. after TTS). A correct
device-side "finish" must therefore also perform the same local transition that
the `STT_VAD_END` handler does (`set_state_(State::STOP_MICROPHONE,
State::AWAITING_RESPONSE)`, line 937), or the microphone will keep streaming
through the whole TTS playback — which is precisely the I2S-contention situation
the bench already found to break TTS audio.

### F10. Supporting facts for the device-side options

- `micro_wake_word` exposes `micro_wake_word.enable_model` and
  `micro_wake_word.disable_model` actions (`micro_wake_word/__init__.py:556-566`),
  which is what a "end-word detector active only during the listening window"
  design needs. `stop_after_detection` is at `__init__.py:46,518`.
- ESPHome supports overriding a bundled component:
  "Bundled components can be overridden using this feature" —
  `https://esphome.io/components/external_components/`, with
  `source: type: local, path: ...`.
- PSRAM arithmetic for a buffer-the-whole-utterance design: 16 kHz, 16-bit, mono
  = 32 000 bytes/s exactly. 1 MiB = 32.8 s, 4 MiB = 131 s, 8 MiB = 262 s. The
  board has 8 MB octal PSRAM, but the share still free after ESPHome, the
  micro_wake_word models, the display buffers and the voice_assistant ring
  buffers (`voice_assistant.cpp:22-27`) was **not measured in this session** —
  treat any figure above 4 MiB as unverified.
- HA has an authenticated HTTP STT endpoint, `POST /api/stt/{provider}` with
  audio metadata in a header (`stt/__init__.py:257-307`), which is what a
  device-owned-capture design would post to.

---

## 2. Options

B1 = "HA's silence VAD (and 15 s cap) must stop ending the turn".
B2 = "the end-word must be able to end the turn *and still get a transcript + reply*".
Both blockers must be solved; most options solve only one.

| # | Option | Solves | What changes, where | Effort | Risk | Standard Assist pipeline kept |
|---|---|---|---|---|---|---|
| O1 | Status quo, select on "relaxed" | neither | nothing | 0 | none | yes |
| O2 | Custom HA integration providing an STT entity that proxies wyoming-faster-whisper and returns `requires_external_vad=False` | B1 | new `custom_components/<name>/` on the NAS (~150-200 lines, `stt.py` + `manifest.json`); select it as STT engine in the "Coach FR" pipeline | M (half a day) | low-med: public API, but needs HA >= 2026.5.0 (F7); STT entity API could change across major upgrades | yes |
| O3 | Shadow-copy HA's built-in `wyoming` integration into `custom_components/wyoming` and add a 6-line `audio_processing` override | B1 | one copied integration directory on the NAS | S | med-high: must be re-synced on **every** HA upgrade; HA logs a "custom integration overrides built-in" warning; silently diverges | yes |
| O4 | Monkey-patch `VoiceCommandSegmenter` / `AudioSettings` from a small custom component | B1 | ~20 lines on the NAS | S | high: patches private internals of two integrations; breaks silently on upgrade | yes |
| O5 | Fork `voice_assistant` as a local `external_components` and add a `voice_assistant.finish` action: send `VoiceAssistantAudio{end: true}` (F9) then `set_state_(STOP_MICROPHONE, AWAITING_RESPONSE)` (F9) | B2 | `firmware/esphome/components/voice_assistant/` (copy of 3 files) + ~15 new lines; YAML end-word handler calls `voice_assistant.finish` instead of `voice_assistant.stop` | M | med: uses the protocol's documented graceful path, but the fork must be re-based on each ESPHome upgrade (the component is ~1.2 kloc) | yes |
| O6 | HA-side service (e.g. `coach.finish_turn`) that reaches the ESPHome satellite entity and calls its private `_stop_pipeline()`; device calls it via the built-in `homeassistant.service` action | B2, partially | ~30 lines on the NAS; firmware stays stock | S | med-high: private API; **and** it does not stop the device microphone, which then streams through TTS (F9) — the exact condition the bench linked to broken TTS | yes |
| O7 | Device-owned capture: buffer the whole utterance in PSRAM, then `POST /api/stt/{provider}`, and drive conversation + TTS from an HA automation | B1+B2 | large firmware rewrite (custom component, HTTP client, long-lived token on device) + HA automations | XL | high: abandons the satellite integration, re-implements state machine, TTS routing and error handling; duration capped by free PSRAM (F10) | no |
| O8 | Wyoming STT proxy that withholds end-of-speech until it sees a marker | neither | new service on the GPU box | M | rejected by evidence: HA's segmenter is upstream of the STT provider (F4/F6) | yes |
| O9 | Inject comfort noise during pauses so `pymicro_vad` never reports silence | B1 partially | firmware audio path | M | rejected: does not defeat the 15 s hard cap (F5); degrades transcription | yes |

---

## 3. Recommendation

**Recommended: O2 + O5.**

1. **O2 on the NAS** removes the server-side turn-ender through a supported,
   public property. One new custom integration, no core files touched, the
   "Coach FR" pipeline keeps its shape (Ollama agent, piper TTS, the same
   wyoming-faster-whisper at <AI_HOST_IP>:10300 — the new entity just speaks the
   wyoming protocol to it directly, and the `wyoming` python library is already a
   HA dependency). Both the 1.25 s silence cut and the 15 s cap disappear at once.
2. **O5 in this repo** gives the end-word a way to finish the turn that actually
   produces a transcript and a coach reply, using the protocol's own graceful
   stop (`VoiceAssistantAudio{end: true}`), and stops the microphone locally so
   TTS playback happens under the same I2S conditions as today's working
   production firmware.

Together the end-word becomes the only terminator, the UX stays 100 % voice, and
both changes live where the project already works (firmware YAML + a local
component in this repo; one custom integration in the HA config dir).

**Fallback: O3 + O6.** Both are much smaller and need no C++ fork, at the price
of upgrade fragility (O3) and a private-API call plus a microphone that keeps
streaming during TTS (O6). Take this path only if the schedule does not allow
O2/O5, and re-test TTS playback explicitly.

**Explicitly not recommended:** O7 (rewrites the whole integration for one
behaviour), O8 and O9 (do not work, per F6 and F5).

### Verification steps to run before implementing

1. Read the HA core version on the NAS (Settings > About, or `ha core info`).
   If it is < 2026.5.0, O2 and O3 are both unavailable and the plan must start
   with an HA upgrade.
2. Re-run one bench turn and check whether a coach reply follows an end-word
   `voice_assistant.stop`. F8 predicts no reply. This is the cheapest
   confirmation of the abort semantics.
3. Confirm the pipeline's STT engine name and that switching it to a new entity
   is a one-click change in the "Coach FR" pipeline.
4. Measure free PSRAM at runtime once, so the O7 numbers stop being unverified
   even though O7 is not the chosen path.

### Open items

- HA core version on the NAS: not verified in this session (401 on the REST API).
- Whether a reply follows an end-word stop today: not recorded in
  `BENCH_RESULT_CS159.md`; predicted "no" from source.
- Free PSRAM on the device: not measured.
