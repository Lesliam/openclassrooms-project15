# DEV REPORT — CS-159 chantier 2, option O2

Custom Home Assistant integration `coach_stt`: a speech-to-text entity that
proxies the existing `wyoming-faster-whisper` service and declares
`requires_external_vad=False`, so `assist_pipeline` never builds a
`VoiceCommandSegmenter` for this entity.

Offline development only. Nothing was deployed, the Synology NAS was not
touched, no git command was run.

## 1. What was built

| File | Lines | Role |
|---|---|---|
| `manifest.json` | 13 | domain `coach_stt`, `version` (mandatory for custom integrations), `config_flow: true`, `dependencies: ["stt"]`, `iot_class: local_push` |
| `const.py` | 27 | defaults: host `192.168.1.37`, port `10300`, max duration 120 s (10-600), languages `fr` + `en`, entity name |
| `__init__.py` | 84 | config entry setup: one `Describe` handshake, `ConfigEntryNotReady` if unreachable, typed `runtime_data`, forwards the `stt` platform |
| `config_flow.py` | 109 | user step (host/port/max duration) validated by a `Describe`, plus an options flow (`OptionsFlowWithReload`) for the max duration |
| `stt.py` | 124 | the HA entity — thin glue, the only behavioural difference with the built-in provider is `audio_processing` |
| `wyoming_client.py` | 283 | HA-free transport: `transcribe_stream`, `describe_service`, `select_languages`; holds the max-duration guard |
| `strings.json`, `translations/{en,fr}.json` | 37 each | config flow UI strings |
| `DEPLOY.md` | 114 | NAS install, verification, rollback |
| `../tests/{conftest.py,test_wyoming_client.py}` | 168 + 295 | 18 unit tests against a real asyncio Wyoming server |

The load-bearing declaration, `stt.py`:

```python
AUDIO_PROCESSING = stt.SpeechAudioProcessing(
    requires_external_vad=False,
    prefers_auto_gain_enabled=True,
    prefers_noise_reduction_enabled=True,
)
```

The two `prefers_*` flags keep their default `True` so the audio path the
satellite already uses is unchanged; only the VAD requirement flips.

## 2. API verification against Home Assistant core 2026.7.3

Every API used was read from the tagged sources, not assumed. Fetched from
`raw.githubusercontent.com/home-assistant/core/2026.7.3/`.

| Claim | Source | Verdict |
|---|---|---|
| `SpeechAudioProcessing(requires_external_vad, prefers_auto_gain_enabled, prefers_noise_reduction_enabled)` — three fields, all mandatory, in that order | `components/stt/models.py:36-55` | confirmed, matches memo F7 |
| `SpeechToTextEntity.audio_processing` returns `DEFAULT_AUDIO_PROCESSING` unless overridden | `components/stt/__init__.py` | confirmed |
| Abstract members to implement: `supported_languages`, `supported_formats`, `supported_codecs`, `supported_bit_rates`, `supported_sample_rates`, `supported_channels`, `async_process_audio_stream` | same file | confirmed, all seven implemented |
| `check_metadata()` rejects a run whose language is not in `supported_languages` | same file | confirmed — drove the language decision in §3 |
| Wyoming streaming sequence `Transcribe` -> `AudioStart` -> `AudioChunk`* -> `AudioStop` -> read until `Transcript` | `components/wyoming/stt.py` | confirmed, our client is a superset (adds timeout + guard) |
| Audio format constants 16000 / 2 / 1 | `components/wyoming/const.py` | confirmed, identical values used |
| `wyoming` is already a HA requirement, pinned `wyoming==1.9.0` | `components/wyoming/manifest.json` | confirmed — our `wyoming>=1.9.0,<2` is satisfied, so HA installs nothing |
| `AddConfigEntryEntitiesCallback` exists | `helpers/entity_platform.py:140` | confirmed |
| `ConfigFlowResult`, `ConfigFlow`, `OptionsFlow.config_entry` (property, no constructor argument), `OptionsFlowWithReload`, `_async_abort_entries_match` | `config_entries.py:306, 3013, 3962+, 4036, 3077` | confirmed |
| `ConfigFlow.async_create_entry(..., options=...)` accepted | `config_entries.py:3417-3446` | confirmed |
| `add_suggested_values_to_schema` | `data_entry_flow.py:658` | confirmed |

Two notes rather than problems:

- `SpeechAudioProcessing` is importable as `stt.SpeechAudioProcessing` (the name
  is bound in `components/stt/__init__.py` via `from .models import ...`) but it
  is **not** listed in that module's `__all__`. Runtime access is unaffected;
  the name is used by the module's own `audio_processing` annotation, so it will
  not disappear while the property exists. Worth re-checking at the next HA
  major upgrade.
- The fetched `components/wyoming/stt.py` contains `except OSError, WyomingError:`
  at line 136 — Python 2 syntax, identical at tags `2026.6.4`, `2026.7.3` and
  `dev`. It was read as reference only and deliberately not copied; our client
  uses a proper exception tuple. Flagging it because it means the built-in
  provider file as published cannot be taken as a byte-for-byte model.

## 3. Design decisions worth reviewing

1. **Languages: `fr` + `en`, not the service's list.** The running service
   advertises **100** languages (measured, §4). Mirroring them, as the built-in
   provider does, would fill the pipeline language selector with 98 useless
   entries. `select_languages()` intersects the advertised list with
   `("fr", "en")`, keeps the preferred order, and falls back to both if the
   service advertises neither, so a service with a thin `Info` event stays
   usable. A missing French advertisement logs a warning instead of failing.
2. **Max-duration backstop implemented in bytes, not wall clock.** 16 kHz mono
   16-bit is exactly 32 000 bytes/s, so counting forwarded bytes gives the same
   answer as a timer for a live stream while staying deterministic under test.
   Default 120 s, configurable 10-600 s through the options flow. When it fires,
   the client stops consuming the stream, still sends `AudioStop` and still
   returns the transcript of what was captured — a truncated turn degrades to a
   shorter answer, never to a hung pipeline. Both the client and the entity log
   it.
3. **Errors are returned, never raised.** `transcribe_stream` converts transport
   and protocol failures into `TranscriptionStatus.ERROR`, which `stt.py` maps to
   `SpeechResult(None, SpeechResultState.ERROR)`. `asyncio.CancelledError` is
   deliberately not caught so pipeline cancellation still works.
4. **Empty audio is a success, not an error.** A turn with no speech returns
   `SpeechResult("", SUCCESS)`; `assist_pipeline` then produces its own
   "no text recognized" error rather than an unhandled exception here.
5. **`transcript_timeout_seconds` default 120 s.** Guards against a wedged
   whisper service; large-v3 on the GPU box needs a few seconds for a two-minute
   recording, so the value is a wedge detector, not a latency budget.

## 4. Tests and evidence

Environment: `project/.venv` (Python 3.14.6, pytest 9.1.1, `wyoming` 1.9.0, and
since review round 1 also `homeassistant` 2026.7.3). Nothing was installed
system-wide. Run both suites with absolute paths, so there is no ambiguity about
which interpreter and which rootdir are used:

```bash
cd /home/yang/wsl-home-yang/openclassrooms/project15/project/server/ha_custom_components
/home/yang/wsl-home-yang/openclassrooms/project15/project/.venv/bin/python \
    -m pytest tests/ -v -p no:cacheprovider
```

`test_wyoming_client.py` imports `wyoming_client.py` by file path, so it needs no
Home Assistant install; each test drives a **real** asyncio server speaking the
Wyoming wire protocol (framing included), not a mock. `test_stt_glue.py` (added
in review round 1) imports the entity itself and therefore needs
`homeassistant`; it is guarded by `pytest.importorskip` so it skips cleanly
where core is absent.

The 18-test run reproduced below is the pre-review baseline. The suite is now
**27 passed** (18 transport + 9 glue).

```
$ .venv/bin/python -m pytest tests/ -v -p no:cacheprovider
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: .../server/ha_custom_components
collected 18 items
tests/test_wyoming_client.py::test_transcribe_returns_text_and_forwards_audio PASSED
tests/test_wyoming_client.py::test_transcribe_announces_language_and_audio_format PASSED
tests/test_wyoming_client.py::test_empty_stream_returns_empty_text_without_raising PASSED
tests/test_wyoming_client.py::test_empty_chunks_are_skipped PASSED
tests/test_wyoming_client.py::test_max_duration_guard_truncates_and_still_transcribes PASSED
tests/test_wyoming_client.py::test_max_duration_guard_can_be_disabled PASSED
tests/test_wyoming_client.py::test_guard_does_not_fire_below_the_limit PASSED
tests/test_wyoming_client.py::test_connection_refused_returns_error_result PASSED
tests/test_wyoming_client.py::test_service_closing_without_transcript_returns_error_result PASSED
tests/test_wyoming_client.py::test_transcript_timeout_returns_error_result PASSED
tests/test_wyoming_client.py::test_describe_service_reports_name_and_languages PASSED
tests/test_wyoming_client.py::test_describe_service_reports_every_advertised_language PASSED
tests/test_wyoming_client.py::test_select_languages_keeps_only_the_preferred_ones PASSED
tests/test_wyoming_client.py::test_select_languages_preserves_the_preferred_order PASSED
tests/test_wyoming_client.py::test_select_languages_drops_unavailable_preferences PASSED
tests/test_wyoming_client.py::test_select_languages_falls_back_when_nothing_matches PASSED
tests/test_wyoming_client.py::test_describe_service_returns_none_when_unreachable PASSED
tests/test_wyoming_client.py::test_describe_service_times_out_on_silent_peer PASSED
============================== 18 passed in 5.24s ==============================
```

The truncation test is the one that matters for the backstop: an endless
generator with `max_duration_seconds=3.0` is consumed exactly 3 times, the fake
service receives exactly 3.0 s of audio, `truncated is True`, and the transcript
still comes back.

Lint and format, ruff 0.15.12:

```
$ ruff check coach_stt tests --select E,F,W,I,N,D,UP,B,SIM,RET,C4,PIE --line-length 88
All checks passed!
$ ruff format --check coach_stt tests
7 files already formatted
```

`--select ARG` additionally reports 4 unused arguments, all in signatures
imposed by an external contract (`async_get_options_flow(config_entry)`, the
platform's `async_setup_entry(hass, ...)`, an `asyncio.start_server` callback).
They are false positives and were left alone; Home Assistant's own codebase does
not enable ARG for the same reason.

Live probe against the real service (read-only, this box, GPU untouched — a
`Describe` plus one second of silent PCM):

```
describe_service -> ServiceDescription(name='faster-whisper', languages=('af', ..., 'zh'))  (0.00s)
advertised count: 100
selected for the entity: ('fr', 'en')
transcribe_stream -> status=success text='' audio_s=1.0 truncated=False (0.02s)
```

This confirms, against the actual `wyoming-faster-whisper` 3.1.0 at
`192.168.1.37:10300`: the `Describe` path, the full
`Transcribe`/`AudioStart`/`AudioChunk`/`AudioStop`/`Transcript` round trip, the
100-language advertisement, and that silence returns an empty transcript rather
than an error.

## 5. What could NOT be verified offline

1. **The load-bearing behaviour itself.** That `requires_external_vad=False`
   makes `assist_pipeline` skip `VoiceCommandSegmenter` is read from
   `pipeline.py:950-957` (memo F4/F7); it has not been observed running. The
   check is the pipeline debug trace after deployment: an `stt-start` event
   carrying `"requires_external_vad": false` and **no** `stt-vad-end` event.
2. **Anything requiring a RUNNING Home Assistant.** Narrowed in review round 1:
   `homeassistant` 2026.7.3 is now installed in `project/.venv`, so
   `tests/test_stt_glue.py` really imports `stt.py` and asserts
   `requires_external_vad is False`, the status mapping and the truncation
   warning. `config_flow.py` and `__init__.py` are still syntax-checked and
   API-cross-checked only: exercising them needs a running instance (a hass
   fixture and a config-entry lifecycle), not just the library. Residual risk on
   those two: a wrong import path or a signature mismatch would surface as a
   setup failure in the HA log, not as a silent misbehaviour.
3. **The HA core version actually running on the NAS.** Still the memo's open
   item. The integration needs **>= 2026.5.0**; on 2026.4.x it will load but the
   segmenter is gated on `is_vad_enabled` alone and the turn will still be cut.
   Read Settings > About after tonight's upgrade before judging a failed test.
4. **The 2026.7.3 sources themselves** are the tagged files, not the bytes
   installed on the NAS; a Synology add-on could carry patches. See also the
   `except OSError, WyomingError:` anomaly in §2.
5. **Config-flow ergonomics** (translation rendering, the range selector on the
   duration field, `already_configured` abort) — UI-only paths, never executed.
6. **End-to-end turn behaviour**, which depends on the companion firmware
   deliverable O5 (`VoiceAssistantAudio{end: true}`). Without O5 every turn runs
   to the 120 s backstop: that is the expected symptom, not a bug in this
   integration.
7. **Long-turn latency.** whisper transcribes only on `AudioStop`, so a 120 s
   turn is transcribed in one pass. The wait before the coach answers was not
   measured; expect it to grow with turn length.

## 6. Suggested deployment order

1. Upgrade HA, then read the core version (must be >= 2026.5.0).
2. Deploy O5 (firmware) first, or accept that every turn hits the backstop.
3. Install this integration per `DEPLOY.md`, switch the "Coach FR" pipeline's
   speech-to-text engine, run one turn, and read the pipeline debug trace for
   the absence of `stt-vad-end`.
4. Rollback is a single dropdown change back to the built-in Wyoming entity.
