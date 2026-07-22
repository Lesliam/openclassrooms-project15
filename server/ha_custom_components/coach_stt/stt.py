"""Speech-to-text entity for the Coach pipeline.

Thin Home Assistant glue around wyoming_client. The single behavioural
difference with the built-in Wyoming provider is the audio_processing property:
returning requires_external_vad=False makes assist_pipeline skip
VoiceCommandSegmenter, so neither the silence timer nor the 15 second cap can
end the turn (see assist_pipeline/pipeline.py, speech-to-text stage).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from homeassistant.components import stt
from homeassistant.components.stt.models import SpeechAudioProcessing
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoachSttConfigEntry
from .const import (
    CONF_MAX_DURATION,
    DEFAULT_MAX_DURATION_SECONDS,
    END_WORD_TRAILING_PATTERN,
    ENTITY_NAME,
)
from .wyoming_client import TranscriptionStatus, transcribe_stream

_LOGGER = logging.getLogger(__name__)

# The satellite drives the end of the turn, so Home Assistant must not run its
# own voice activity detection. The two preference flags are only read by
# multi-channel satellites to pick between the raw and the enhanced microphone
# channel; keeping them enabled preserves the current audio path.
# Imported from stt.models rather than through the stt package: the re-export in
# stt/__init__.py works today but SpeechAudioProcessing is absent from that
# module's __all__, so a stricter re-export upstream would break it silently.
AUDIO_PROCESSING = SpeechAudioProcessing(
    requires_external_vad=False,
    prefers_auto_gain_enabled=True,
    prefers_noise_reduction_enabled=True,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CoachSttConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Coach speech-to-text entity."""
    async_add_entities([CoachSttEntity(config_entry)])


class CoachSttEntity(stt.SpeechToTextEntity):
    """Wyoming speech-to-text entity that does not require an external VAD."""

    _attr_name = ENTITY_NAME

    def __init__(self, config_entry: CoachSttConfigEntry) -> None:
        """Initialise the entity from its config entry."""
        data = config_entry.runtime_data
        self._host = data.host
        self._port = data.port
        self._supported_languages = list(data.languages)
        self._max_duration_seconds = float(
            config_entry.options.get(
                CONF_MAX_DURATION,
                config_entry.data.get(CONF_MAX_DURATION, DEFAULT_MAX_DURATION_SECONDS),
            )
        )
        self._attr_unique_id = f"{config_entry.entry_id}-stt"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return self._supported_languages

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return a list of supported formats."""
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return a list of supported codecs."""
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        """Return a list of supported bit rates."""
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        """Return a list of supported sample rates."""
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        """Return a list of supported channels."""
        return [stt.AudioChannels.CHANNEL_MONO]

    @property
    def audio_processing(self) -> SpeechAudioProcessing:
        """Return the input audio processing settings of this entity."""
        return AUDIO_PROCESSING

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Process an audio stream with the Wyoming speech-to-text service."""
        result = await transcribe_stream(
            self._host,
            self._port,
            metadata.language,
            stream,
            max_duration_seconds=self._max_duration_seconds,
        )

        if result.status is not TranscriptionStatus.SUCCESS:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

        if result.truncated:
            _LOGGER.warning(
                "Turn truncated at %.0f s of audio; the satellite did not signal "
                "the end of the turn",
                self._max_duration_seconds,
            )

        # The trailing end word is a turn-control token, not learner content:
        # strip it so the conversation stage never sees it (see const.py). If
        # the learner said ONLY the end word, the transcript becomes empty and
        # falls through to the empty-transcript path below.
        text = result.text
        stripped = END_WORD_TRAILING_PATTERN.sub("", text)
        if stripped != text:
            _LOGGER.debug(
                "Trailing end word stripped from transcript: %r -> %r",
                text,
                stripped,
            )

        # An empty transcript is returned as a successful result with empty
        # text: assist_pipeline turns that into its own "no text recognized"
        # error instead of an unhandled exception here.
        return stt.SpeechResult(stripped, stt.SpeechResultState.SUCCESS)
