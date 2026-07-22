"""Unit tests for the Home Assistant glue of the Coach STT entity.

These cover what test_wyoming_client.py structurally cannot: stt.py imports
Home Assistant, so it is only importable where the homeassistant package is
installed. The module is skipped cleanly elsewhere.

Three behaviours are asserted, in decreasing order of importance:

1. audio_processing.requires_external_vad is False. This single flag is the
   entire reason the integration exists: assist_pipeline reads it to decide
   whether to run VoiceCommandSegmenter, i.e. whether silence and the 15 second
   cap can end the turn.
2. The TranscriptionStatus -> SpeechResultState mapping, including the empty
   transcript being reported as SUCCESS rather than as an error.
3. The truncation warning, which is the only signal that the satellite failed
   to end a turn and the backstop had to.

No Home Assistant instance is started: the entity only reads plain attributes
off its config entry, so a stub entry is enough and keeps the test fast.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import unicodedata
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("homeassistant", reason="the Home Assistant glue needs core")

from homeassistant.components import stt  # noqa: E402
from homeassistant.components.stt.models import SpeechAudioProcessing  # noqa: E402

# The integration is deployed as custom_components/coach_stt/, so its parent
# directory is what has to be importable, not the package directory itself.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coach_stt import CoachSttData  # noqa: E402
from coach_stt.const import DEFAULT_MAX_DURATION_SECONDS  # noqa: E402
from coach_stt.stt import CoachSttEntity  # noqa: E402
from coach_stt.wyoming_client import (  # noqa: E402
    TranscriptionResult,
    TranscriptionStatus,
)

BACKSTOP_SECONDS = 30.0


@dataclass
class StubConfigEntry:
    """Minimal stand-in for a ConfigEntry, holding only what the entity reads."""

    runtime_data: CoachSttData
    options: dict[str, Any]
    data: dict[str, Any]
    entry_id: str = "test-entry"


def make_entity(**options: Any) -> CoachSttEntity:
    """Build the entity from a stub config entry."""
    entry = StubConfigEntry(
        runtime_data=CoachSttData(
            host="127.0.0.1",
            port=10300,
            languages=("fr", "en"),
            service_name="faster-whisper",
        ),
        options=dict(options),
        data={},
    )
    return CoachSttEntity(entry)  # type: ignore[arg-type]


def make_metadata() -> stt.SpeechMetadata:
    """Build the audio metadata the pipeline passes for one turn."""
    return stt.SpeechMetadata(
        language="fr",
        format=stt.AudioFormats.WAV,
        codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16,
        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )


async def empty_stream() -> AsyncIterable[bytes]:
    """Yield an audio stream with a single chunk."""
    yield b"\x00\x00"


def patch_transcribe(
    monkeypatch: pytest.MonkeyPatch, result: TranscriptionResult
) -> dict[str, Any]:
    """Replace transcribe_stream with a stub returning the given result.

    Returns the dict that records the keyword arguments it was called with.
    """
    calls: dict[str, Any] = {}

    async def fake_transcribe_stream(
        host: str,
        port: int,
        language: str | None,
        audio_stream: AsyncIterable[bytes],
        **kwargs: Any,
    ) -> TranscriptionResult:
        calls.update(host=host, port=port, language=language, **kwargs)
        return result

    monkeypatch.setattr("coach_stt.stt.transcribe_stream", fake_transcribe_stream)
    return calls


def process(entity: CoachSttEntity) -> stt.SpeechResult:
    """Run one turn through the entity."""
    return asyncio.run(
        entity.async_process_audio_stream(make_metadata(), empty_stream())
    )


def test_audio_processing_does_not_require_external_vad() -> None:
    """The pipeline must skip VoiceCommandSegmenter for this entity."""
    audio_processing = make_entity().audio_processing

    assert isinstance(audio_processing, SpeechAudioProcessing)
    assert audio_processing.requires_external_vad is False


def test_audio_processing_keeps_the_current_audio_path() -> None:
    """The two preference flags stay enabled, as with the built-in provider."""
    audio_processing = make_entity().audio_processing

    assert audio_processing.prefers_auto_gain_enabled is True
    assert audio_processing.prefers_noise_reduction_enabled is True


def test_supported_audio_format_matches_the_satellite() -> None:
    """The entity advertises exactly the 16 kHz 16-bit mono PCM the ESP32 sends."""
    entity = make_entity()

    assert entity.supported_languages == ["fr", "en"]
    assert entity.supported_formats == [stt.AudioFormats.WAV]
    assert entity.supported_codecs == [stt.AudioCodecs.PCM]
    assert entity.supported_bit_rates == [stt.AudioBitRates.BITRATE_16]
    assert entity.supported_sample_rates == [stt.AudioSampleRates.SAMPLERATE_16000]
    assert entity.supported_channels == [stt.AudioChannels.CHANNEL_MONO]


def test_successful_transcription_maps_to_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SUCCESS status returns the text with SpeechResultState.SUCCESS."""
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="je voudrais un cafe",
            audio_seconds=2.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "je voudrais un cafe"


def test_trailing_end_word_is_stripped_from_returned_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entity returns the STRIPPED transcript, not the raw one.

    Guards the wiring in async_process_audio_stream: the pattern itself is
    covered by test_end_word_strip.py, but only this test fails if stt.py
    reverts to returning result.text.
    """
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="Est-ce que tout va bien ? j'ai fini",
            audio_seconds=4.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "Est-ce que tout va bien ?"


def test_mixed_end_word_run_is_stripped_in_one_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end word and its observed mistranscription go in the same pass.

    async_process_audio_stream calls sub() once, so a turn ending with both
    forms is only clean if the pattern covers the whole trailing run.
    """
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="Voici mon plan. J'ai fini. Réfinis. Réfinis.",
            audio_seconds=6.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "Voici mon plan."


def test_transcript_made_of_only_end_words_becomes_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn whose whole transcript is the end word strips to empty text.

    Different path from a transcript whisper itself returned empty: this one
    goes through the strip and its debug log. assist_pipeline turns the empty
    text into its own handled "stt-no-text-recognized" error, so SUCCESS with
    an empty string is the intended contract here.
    """
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="Réfinis. Réfinis.",
            audio_seconds=3.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == ""


def test_decomposed_accent_is_normalised_before_the_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An NFD transcript is stripped like its NFC twin.

    The pattern spells the variant with a precomposed U+00E9. Without the NFC
    normalisation in async_process_audio_stream, the same spoken end word
    would slip through whenever the transcript arrives decomposed.
    """
    decomposed = unicodedata.normalize("NFD", "Voici mon plan. Réfinis.")
    assert decomposed != "Voici mon plan. Réfinis.", "input must really be NFD"

    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text=decomposed,
            audio_seconds=4.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "Voici mon plan."


def test_normalisation_leaves_ordinary_accented_text_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learner content with no end word survives the normalisation unchanged."""
    text = "j'ai étudié les critères de l'évaluation"
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text=text,
            audio_seconds=5.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == text


def test_error_status_maps_to_error_with_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ERROR status is reported as ERROR and never leaks partial text."""
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.ERROR,
            text="",
            audio_seconds=0.0,
            truncated=False,
            error="Connection refused",
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.ERROR
    assert result.text is None


def test_empty_transcript_is_a_success_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn with no speech is SUCCESS with empty text.

    assist_pipeline turns that into its own stt-no-text-recognized error; raising
    here instead would surface as an unhandled exception in the pipeline.
    """
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="",
            audio_seconds=1.0,
            truncated=False,
        ),
    )

    result = process(make_entity())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == ""


def test_truncated_turn_warns_with_the_configured_duration(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Hitting the backstop still returns the text, and warns once."""
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="une phrase tres longue",
            audio_seconds=BACKSTOP_SECONDS,
            truncated=True,
        ),
    )
    entity = make_entity(max_duration_seconds=BACKSTOP_SECONDS)

    with caplog.at_level(logging.WARNING, logger="coach_stt.stt"):
        result = process(entity)

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == "une phrase tres longue"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "30 s" in warnings[0].getMessage()


def test_untruncated_turn_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The normal path stays silent, so the warning is a usable signal."""
    patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="bonjour",
            audio_seconds=2.0,
            truncated=False,
        ),
    )

    with caplog.at_level(logging.WARNING, logger="coach_stt.stt"):
        process(make_entity())

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_max_duration_option_overrides_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backstop passed to the client comes from the config entry options."""
    calls = patch_transcribe(
        monkeypatch,
        TranscriptionResult(
            status=TranscriptionStatus.SUCCESS,
            text="bonjour",
            audio_seconds=1.0,
            truncated=False,
        ),
    )

    process(make_entity(max_duration_seconds=BACKSTOP_SECONDS))
    assert calls["max_duration_seconds"] == BACKSTOP_SECONDS

    process(make_entity())
    assert calls["max_duration_seconds"] == DEFAULT_MAX_DURATION_SECONDS
