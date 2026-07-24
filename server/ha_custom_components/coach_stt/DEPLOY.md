# Coach STT — deployment on the Home Assistant instance (Synology NAS)

Custom integration providing a speech-to-text entity that proxies the existing
`wyoming-faster-whisper` service (`tcp://192.168.1.37:10300`) and declares
`requires_external_vad=False`.

Effect: `assist_pipeline` skips `VoiceCommandSegmenter` for this entity, so
neither the silence timer (0.25 / 0.70 / 1.25 s, "finished speaking detection")
nor the 15 s hard cap can end the turn. See `firmware/esphome/VAD_OPTIONS_CS159.md`
findings F4, F5, F7 for the source references.

## Prerequisites

- **Home Assistant core >= 2026.5.0.** `SpeechAudioProcessing.requires_external_vad`
  does not exist before that release, and on 2026.4.x the pipeline gates the
  segmenter on `is_vad_enabled` alone, which a satellite cannot set. The code
  here was written against the 2026.7.3 API.
- The Wyoming ASR service reachable from Home Assistant at `192.168.1.37:10300`.
- The `wyoming` Python package: already a Home Assistant dependency. The manifest
  pins `wyoming==1.9.0`, the exact version core 2026.7.3 pins, so the requirement
  is already satisfied and nothing extra is downloaded. See the upgrade section
  below before moving to another core release.
- **Companion firmware change (O5) is required for normal use.** With this
  integration installed, the only things that can end a turn are the satellite's
  graceful end-of-audio signal and the max-duration backstop below. Deploying
  this integration without the firmware side means every turn runs to the
  backstop.

## Install

1. Copy the integration directory into the Home Assistant configuration
   directory (the one holding `configuration.yaml`):

   ```bash
   # from a machine that can reach the NAS; adjust the destination to the
   # actual Home Assistant config path on that host
   scp -r server/ha_custom_components/coach_stt \
       <user>@192.168.1.100:<ha_config_dir>/custom_components/
   ```

   Result: `<ha_config_dir>/custom_components/coach_stt/` containing
   `manifest.json`, `__init__.py`, `config_flow.py`, `stt.py`,
   `wyoming_client.py`, `const.py`, `strings.json`, `translations/`.

   The exact `<ha_config_dir>` on the NAS is not recorded in this repository;
   read it from the Home Assistant UI (Settings > System > Repairs > three-dot
   menu > System information) before copying.

2. Restart Home Assistant (Settings > System > top-right menu > Restart).

3. Add the integration: Settings > Devices & Services > Add Integration >
   "Coach STT (Wyoming sans VAD)". Fields:

   | Field | Value |
   |---|---|
   | Host | `192.168.1.37` (default) |
   | Port | `10300` (default) |
   | Maximum turn duration | `120` seconds (default, 10-600 allowed) |

   The flow performs one Wyoming `Describe` handshake and refuses to create the
   entry if the service does not answer. The entity offers `fr` + `en` only:
   whisper large-v3 advertises 100 languages (verified against the running
   service), which would clutter the pipeline language selector for no benefit.
   A preferred language the service does not advertise is dropped, and if it
   advertises neither, both are offered anyway so the entity stays usable.

4. Switch the pipeline: Settings > Voice assistants > "Coach FR" > Speech-to-text
   > select **Coach FR Whisper sans VAD** (entity id will be
   `stt.coach_fr_whisper_sans_vad` unless renamed). Save.

## Verify

- The entity exists and is not `unavailable`: Developer tools > States >
  `stt.coach_fr_whisper_sans_vad`.
- Run one turn from the satellite and check the pipeline debug trace
  (Settings > Voice assistants > "Coach FR" > three-dot menu > Debug): the
  `stt-start` event carries
  `"audio_processing": {"requires_external_vad": false, ...}`, and there is **no**
  `stt-vad-end` event in the run.
- If the turn is cut at exactly the configured maximum, the Home Assistant log
  contains `Maximum turn duration of 120 s reached` from
  `custom_components.coach_stt.wyoming_client` — that means the satellite never
  sent its end-of-turn signal.

## Upgrading Home Assistant core

A custom integration's `requirements` are installed into the SAME Python
environment as core, so a mismatch here can break a built-in integration rather
than this one. Before (or right after) every core upgrade:

1. **Re-check core's `wyoming` pin.** Read `requirements` in core's
   `homeassistant/components/wyoming/manifest.json` for the target release. If it
   is no longer `wyoming==1.9.0`, update `manifest.json` here to the same exact
   version and redeploy. Leaving a stale pin forces pip to downgrade the shared
   `wyoming` package and breaks the built-in `wyoming` integration, which this
   project uses for Piper TTS. The symptom is "TTS stopped working after the
   upgrade", far from its cause.
2. **Re-check the `stt` API this integration depends on**: the
   `SpeechAudioProcessing` dataclass fields and the fact that
   `assist_pipeline` still gates `VoiceCommandSegmenter` on
   `stt_provider.audio_processing.requires_external_vad`. If either changed, the
   turn may silently go back to being ended by the server-side VAD.
3. After restarting, run one turn and confirm the pipeline debug trace still
   shows `"requires_external_vad": false` and no `stt-vad-end` event.

## Change the maximum turn duration

Settings > Devices & Services > Coach STT > Configure. The config entry reloads
automatically.

## Rollback

Set the "Coach FR" pipeline's Speech-to-text engine back to the built-in Wyoming
entity (the one created by the `wyoming` integration for `192.168.1.37:10300`)
and save. That single change restores the previous behaviour, including the
silence-based end of turn; the custom integration can stay installed.

To remove it completely: delete the config entry (Settings > Devices & Services
> Coach STT > Delete), then remove
`<ha_config_dir>/custom_components/coach_stt/` and restart Home Assistant.

## Tests

Two suites, both run with the same command. Use absolute paths so there is no
doubt about which interpreter and which rootdir are used:

```bash
cd /home/yang/wsl-home-yang/openclassrooms/project15/project/server/ha_custom_components
/home/yang/wsl-home-yang/openclassrooms/project15/project/.venv/bin/python \
    -m pytest tests/ -q
```

- `tests/test_wyoming_client.py` covers the transport logic of
  `wyoming_client.py` against a real asyncio Wyoming server; it needs only
  `pytest` + `wyoming` and never imports Home Assistant.
- `tests/test_stt_glue.py` covers the `stt.py` entity glue: the
  `requires_external_vad=False` contract, the `TranscriptionStatus` ->
  `SpeechResultState` mapping and the truncation warning. It needs the
  `homeassistant` package in the venv and is skipped automatically
  (`pytest.importorskip`) where that package is absent. ANY run that reports
  skips is therefore NOT a full pass, whatever the counts — recreate the venv
  from `../requirements-dev.txt` so the whole suite actually runs. A real full
  pass collects the entire `tests/` directory with ZERO skips (80 tests as of
  2026-07-22; the exact count grows with the suite — the invariant to check is
  "0 skipped", not a fixed number).

`config_flow.py` and `__init__.py` are still only exercised by deploying: they
need a running Home Assistant instance, not just the library.

Not covered anywhere offline, to watch during the first long turn on the NAS:
when the max-duration backstop fires, this integration stops consuming the audio
stream while the satellite keeps feeding Home Assistant's queue until the run
ends. Expected to be bounded (the run ends shortly after), but it is worth a
look at memory and at the log timestamps on that first test.
