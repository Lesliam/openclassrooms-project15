# Local fork of the ESPHome `voice_assistant` component (CS-159, option O5)

Upstream base: **ESPHome 2026.5.3**, copied verbatim from
`/usr/lib/python3.14/site-packages/esphome/components/voice_assistant/`
(`__init__.py`, `voice_assistant.h`, `voice_assistant.cpp`) on 2026-07-22.

Wired into the build with:

```yaml
external_components:
  - source:
      type: local
      path: components
    components: [voice_assistant]
```

ESPHome allows a bundled component to be overridden this way
(https://esphome.io/components/external_components/).

## Why the fork exists

The end-word ("j'ai fini") must end the learner's turn AND still produce a
transcript plus a coach reply. The stock component offers only
`voice_assistant.stop`, which sends `VoiceAssistantRequest{start: false}`;
`aioesphomeapi` maps that to `handle_stop(abort=True)`, and Home Assistant's
`_abort_pipeline()` cancels the whole pipeline task: no STT result, no
conversation stage, no TTS. See `VAD_OPTIONS_CS159.md` finding F8.

The graceful path already exists in the wire protocol but is not reachable from
YAML: `VoiceAssistantAudio{end: true}` is mapped by `aioesphomeapi` to
`handle_stop(abort=False)` -> `_stop_pipeline()`, which just closes the audio
stream so STT transcribes what it has (finding F9). The `end` field exists in
ESPHome's generated struct (`api_pb2.h`, `bool end{false}`) and is encoded
(`api_pb2.cpp`, field 2), but the stock component never sets it.

A device-initiated end must ALSO stop the microphone locally: without an
`STT_VAD_END` event the mic is otherwise only stopped at `RUN_END`, i.e. after
TTS, so it would stream through the whole playback (finding F9, last paragraph).
The fork therefore repeats the transition the `STT_VAD_END` handler performs.

## The complete diff vs upstream 2026.5.3

**66 added lines, 0 removed, 0 modified** (42 code + 19 comment + 5 blank).

Counting method, so the next maintainer can reproduce the figures exactly:

```bash
UP=/usr/lib/python3.14/site-packages/esphome/components/voice_assistant
for f in __init__.py voice_assistant.h voice_assistant.cpp; do
  echo "$f +$(diff -u $UP/$f $f | grep -v '^+++' | grep -c '^+')"
done
```

Blank lines are counted; `grep -c '^+[^+]'` silently drops them and is what made
the first version of this section disagree with itself.

| File | Added |
|---|---|
| `__init__.py` | +17 |
| `voice_assistant.h` | +11 |
| `voice_assistant.cpp` | +38 |
| **Total** | **+66** |

### `__init__.py` (+17 lines)

1. After `StopAction`, declare the new action class:

```python
FinishAction = voice_assistant_ns.class_(
    "FinishAction", automation.Action, cg.Parented.template(VoiceAssistant)
)
```

2. After `voice_assistant_stop_to_code`, register the action:

```python
@register_action(
    "voice_assistant.finish",
    FinishAction,
    VOICE_ASSISTANT_ACTION_SCHEMA,
    synchronous=True,
)
async def voice_assistant_finish_to_code(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var
```

### `voice_assistant.h` (+11 lines)

1. Public: `void request_finish();` next to `request_stop()`.
2. Protected: `bool signal_finish_();` next to `signal_stop_()`. It returns a
   bool where `signal_stop_()` returns void, so the caller can react to a
   dropped message (see below).
3. The action template next to `StopAction`:

```cpp
template<typename... Ts> class FinishAction : public Action<Ts...>, public Parented<VoiceAssistant> {
 public:
  void play(const Ts &...x) override { this->parent_->request_finish(); }
};
```

### `voice_assistant.cpp` (+38 lines)

Two new methods inserted between `signal_stop_()` and
`start_playback_timeout_()`:

```cpp
void VoiceAssistant::request_finish() {
  // state_, not desired_state_: START_MICROPHONE / STARTING_MICROPHONE also carry
  // desired_state_ == STREAMING_MICROPHONE, and in that window no audio has
  // reached Home Assistant yet, so end: true would close an empty stream while
  // the microphone is still coming up.
  if (this->state_ != State::STREAMING_MICROPHONE) {
    ESP_LOGW(TAG, "Finish ignored, not capturing speech (state %s, desired %s)",
             LOG_STR_ARG(voice_assistant_state_to_string(this->state_)),
             LOG_STR_ARG(voice_assistant_state_to_string(this->desired_state_)));
    return;
  }
  if (!this->signal_finish_()) {
    // Home Assistant never learned the turn is over. Going to AWAITING_RESPONSE
    // anyway would release the microphone and wait in a state that has no
    // device-side timeout, with no server VAD left to close the stage either.
    // Abort visibly instead: request_stop() signals the abort and returns to IDLE.
    ESP_LOGE(TAG, "Failed to signal end of speech, aborting the turn");
    this->request_stop();
    return;
  }
  this->set_state_(State::STOP_MICROPHONE, State::AWAITING_RESPONSE);
}

bool VoiceAssistant::signal_finish_() {
  if (this->api_client_ == nullptr) {
    return false;
  }
  ESP_LOGD(TAG, "Signaling end of speech (voice_assistant.finish)");
  api::VoiceAssistantAudio msg;
  msg.end = true;
  return this->api_client_->send_message(msg);
}
```

Guard semantics. The guard tests `state_`, not `desired_state_`.
`desired_state_` is already `STREAMING_MICROPHONE` during `START_MICROPHONE` and
`STARTING_MICROPHONE` (both are set by `start_streaming()`), i.e. before any
audio has been sent; finishing there would close an empty stream and would jump
to `STOP_MICROPHONE` while the microphone is still coming up. Testing `state_`
restricts the action to the window where the component is genuinely streaming
the user's speech. Any other state logs a warning — printing BOTH `state_` and
`desired_state_`, since either can be the reason for the rejection — and does
nothing. Nothing else is touched: `continuous_` and `continue_conversation_`
keep their values, unlike `request_stop()` which clears them.

Failure handling. `APIConnection::send_message()` returns false when the message
could not be queued (TX buffer pressure right after a burst of audio frames).
Ignoring that return value would strand the device: the microphone is released,
`AWAITING_RESPONSE` has no device-side timeout (it is left only on `RUN_END` or
`ERROR`), and with option O2 deployed there is no server VAD left to close the
speech-to-text stage — the turn would hang until the `coach_stt` 120 s backstop.
The fork therefore falls back to `request_stop()`, which signals the abort and
returns the component to `IDLE`. The learner sees a failed turn immediately
(the YAML routes it to `on_error`, red LED and error screen) instead of a
two-minute silence. This is a deliberate trade: a visible abort beats a silent
hang.

## Maintenance on an ESPHome upgrade

1. Diff the new upstream files against
   `/usr/lib/.../esphome/components/voice_assistant/` at the version recorded
   above to see what changed upstream.
2. Copy the new upstream files here, re-apply the three hunks listed above,
   update the "Upstream base" version at the top of this file.
3. Re-check the four upstream facts the fork depends on:
   - `api::VoiceAssistantAudio` still has an `end` field that is encoded;
   - the `STT_VAD_END` handler still does
     `set_state_(State::STOP_MICROPHONE, State::AWAITING_RESPONSE)`;
   - `APIConnection::send_message()` still returns a bool meaning "queued"
     (upstream itself checks it on the pipeline-start request);
   - `request_stop()` still handles `State::STREAMING_MICROPHONE` by signalling
     the stop and returning to `IDLE` — that is the fallback path taken when the
     finish message cannot be sent.
4. Delete the fork entirely if upstream ever ships an equivalent action.

Verification that the fork is the code being built (checked on 2026-07-22 with
ESPHome 2026.5.3 — note that the tool prints no "loading local component" line,
so these three checks are the evidence):

1. `esphome config` accepts `voice_assistant.finish` and dumps
   `external_components: - source: {path: <repo>/firmware/esphome/components,
   type: local}, components: [voice_assistant]`. The action does not exist in
   ESPHome 2026.5.3, so acceptance alone proves the override.
2. `diff -q .esphome/build/coach-terminal/src/esphome/components/voice_assistant/voice_assistant.cpp
   components/voice_assistant/voice_assistant.cpp` reports no difference, and the
   build copy contains `request_finish`.
3. Generated `main.cpp` instantiates `voice_assistant::FinishAction<std::string>`
   and wires it into the end-word branch.

On the device, the distinctive runtime log lines are:

| Level | Line | Meaning |
|---|---|---|
| DEBUG | `Signaling end of speech (voice_assistant.finish)` | the happy path, the turn was ended gracefully by the end word |
| WARN | `Finish ignored, not capturing speech (state ..., desired ...)` | the action fired outside the listening window; the turn is unchanged |
| ERROR | `Failed to signal end of speech, aborting the turn` | the message could not be queued; the turn was aborted instead of hanging |
