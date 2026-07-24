"""Wyoming ASR client used by the Coach STT entity.

This module is deliberately free of any Home Assistant import so that it can be
unit tested without a Home Assistant installation. The Home Assistant glue lives
in stt.py, which is a thin wrapper around the two coroutines exposed here:

- describe_service: ask the Wyoming service what it is and which languages it
  advertises (used at config-entry setup time).
- transcribe_stream: stream PCM audio to the service and return the transcript.

The Coach pipeline runs with requires_external_vad=False, which means Home
Assistant never ends the speech-to-text stream on silence. The stream normally
ends when the satellite signals the end of the turn. The max-duration guard in
transcribe_stream is the backstop for the case where that signal never arrives.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient, AsyncTcpClient
from wyoming.info import Describe, Info

_LOGGER = logging.getLogger(__name__)

# Audio format expected by wyoming-faster-whisper (and produced by the ESP32-S3
# satellite): 16 kHz, 16-bit signed, mono.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
SAMPLE_CHANNELS = 1
BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_WIDTH * SAMPLE_CHANNELS

# Backstop for a turn that is never terminated by the satellite. Audio received
# up to this point is still transcribed, so a truncated turn degrades to a
# shorter answer instead of a hung pipeline.
DEFAULT_MAX_DURATION_SECONDS = 120.0

# Upper bound on the wait for the Transcript event once the audio stream is
# closed. Whisper large-v3 needs a few seconds for a two-minute recording on the
# GPU box, so this only fires when the service is stuck or gone.
DEFAULT_TRANSCRIPT_TIMEOUT_SECONDS = 120.0

# Timeout and retry policy for the initial Describe handshake.
DEFAULT_DESCRIBE_TIMEOUT_SECONDS = 5.0
DEFAULT_DESCRIBE_RETRIES = 2
DEFAULT_DESCRIBE_RETRY_WAIT_SECONDS = 2.0

ClientFactory = Callable[[], AsyncClient]


class WyomingProtocolError(Exception):
    """Raised when the Wyoming peer closes or answers outside the protocol."""


class TranscriptionStatus(StrEnum):
    """Outcome of a transcription attempt."""

    SUCCESS = "success"
    ERROR = "error"


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of streaming one turn to the Wyoming ASR service.

    An empty transcript is reported as SUCCESS with an empty string: a turn that
    contained no speech is a normal outcome, not a transport failure.
    """

    status: TranscriptionStatus
    text: str
    audio_seconds: float
    truncated: bool
    error: str | None = None


@dataclass(frozen=True)
class ServiceDescription:
    """Subset of the Wyoming Info event that the integration needs."""

    name: str | None
    languages: tuple[str, ...] = field(default=())


def _tcp_factory(host: str, port: int) -> ClientFactory:
    """Return a factory creating a TCP client for the given endpoint."""

    def factory() -> AsyncClient:
        return AsyncTcpClient(host, port)

    return factory


async def _read_transcript(client: AsyncClient, timeout_seconds: float) -> str:
    """Read events until a Transcript arrives and return its text."""
    async with asyncio.timeout(timeout_seconds):
        while True:
            event = await client.read_event()
            if event is None:
                raise WyomingProtocolError(
                    "Connection closed before a transcript was received"
                )
            if Transcript.is_type(event.type):
                return Transcript.from_event(event).text or ""


async def transcribe_stream(
    host: str,
    port: int,
    language: str | None,
    audio_stream: AsyncIterable[bytes],
    *,
    max_duration_seconds: float | None = DEFAULT_MAX_DURATION_SECONDS,
    transcript_timeout_seconds: float = DEFAULT_TRANSCRIPT_TIMEOUT_SECONDS,
    client_factory: ClientFactory | None = None,
) -> TranscriptionResult:
    """Stream one turn of PCM audio to the Wyoming ASR service.

    The audio stream is consumed until it ends on its own or until
    max_duration_seconds of audio has been forwarded, whichever comes first.
    Duration is derived from the number of bytes forwarded, which for a live
    16 kHz mono stream matches wall-clock time and stays deterministic for
    tests. Pass max_duration_seconds=None to disable the guard.

    Transport and protocol failures are reported through the returned result
    rather than raised, so the caller never breaks the assist pipeline with an
    unexpected exception. asyncio.CancelledError is intentionally not caught.
    """
    factory = client_factory or _tcp_factory(host, port)
    max_bytes: int | None = None
    if max_duration_seconds is not None:
        max_bytes = max(1, int(max_duration_seconds * BYTES_PER_SECOND))

    forwarded_bytes = 0
    truncated = False

    try:
        async with factory() as client:
            await client.write_event(Transcribe(language=language).event())
            await client.write_event(
                AudioStart(
                    rate=SAMPLE_RATE,
                    width=SAMPLE_WIDTH,
                    channels=SAMPLE_CHANNELS,
                ).event()
            )

            async for audio_bytes in audio_stream:
                if not audio_bytes:
                    continue

                await client.write_event(
                    AudioChunk(
                        rate=SAMPLE_RATE,
                        width=SAMPLE_WIDTH,
                        channels=SAMPLE_CHANNELS,
                        audio=audio_bytes,
                    ).event()
                )
                forwarded_bytes += len(audio_bytes)

                if max_bytes is not None and forwarded_bytes >= max_bytes:
                    truncated = True
                    _LOGGER.warning(
                        "Maximum turn duration of %.0f s reached; transcribing "
                        "the audio received so far. The end-of-turn signal from "
                        "the satellite was not received",
                        max_duration_seconds,
                    )
                    break

            await client.write_event(AudioStop().event())
            text = await _read_transcript(client, transcript_timeout_seconds)
    except (OSError, WyomingProtocolError, ValueError, KeyError) as err:
        # OSError covers connection refused/reset and TimeoutError; ValueError
        # and KeyError cover malformed events from a misbehaving peer.
        _LOGGER.error("Error while streaming audio to %s:%s: %s", host, port, err)
        return TranscriptionResult(
            status=TranscriptionStatus.ERROR,
            text="",
            audio_seconds=forwarded_bytes / BYTES_PER_SECOND,
            truncated=truncated,
            error=str(err) or type(err).__name__,
        )

    audio_seconds = forwarded_bytes / BYTES_PER_SECOND
    _LOGGER.debug(
        "Transcribed %.1f s of audio (truncated=%s, %d characters)",
        audio_seconds,
        truncated,
        len(text),
    )
    return TranscriptionResult(
        status=TranscriptionStatus.SUCCESS,
        text=text,
        audio_seconds=audio_seconds,
        truncated=truncated,
    )


def _languages_from_info(info: Info) -> tuple[str, ...]:
    """Collect the languages advertised by the installed ASR models."""
    languages: list[str] = []
    for asr_service in info.asr or []:
        for model in asr_service.models or []:
            if not model.installed:
                continue
            for language in model.languages or []:
                if language not in languages:
                    languages.append(language)
    return tuple(languages)


def select_languages(
    advertised: Sequence[str], preferred: Sequence[str]
) -> tuple[str, ...]:
    """Return the preferred languages that the service actually advertises.

    whisper large-v3 advertises close to a hundred languages; the Coach entity
    only offers the handful it is meant for. If the service advertises none of
    them, or advertises nothing at all, the preferred list is returned unchanged
    so that a service with an incomplete Info event stays usable.
    """
    advertised_set = set(advertised)
    selected = tuple(language for language in preferred if language in advertised_set)
    return selected or tuple(preferred)


def _name_from_info(info: Info) -> str | None:
    """Return the name of the first installed ASR service, if any."""
    for asr_service in info.asr or []:
        if asr_service.installed:
            return asr_service.name
    return None


async def describe_service(
    host: str,
    port: int,
    *,
    timeout_seconds: float = DEFAULT_DESCRIBE_TIMEOUT_SECONDS,
    retries: int = DEFAULT_DESCRIBE_RETRIES,
    retry_wait_seconds: float = DEFAULT_DESCRIBE_RETRY_WAIT_SECONDS,
    client_factory: ClientFactory | None = None,
) -> ServiceDescription | None:
    """Describe the Wyoming service, or return None if it cannot be reached.

    Used both by the config flow (to validate user input) and by the config
    entry setup (to learn the advertised languages).
    """
    factory = client_factory or _tcp_factory(host, port)

    for attempt in range(retries + 1):
        try:
            async with asyncio.timeout(timeout_seconds), factory() as client:
                await client.write_event(Describe().event())
                while True:
                    event = await client.read_event()
                    if event is None:
                        raise WyomingProtocolError(
                            "Connection closed before info was received"
                        )
                    if Info.is_type(event.type):
                        info = Info.from_event(event)
                        return ServiceDescription(
                            name=_name_from_info(info),
                            languages=_languages_from_info(info),
                        )
        except (OSError, WyomingProtocolError, ValueError, KeyError) as err:
            _LOGGER.debug(
                "Describe attempt %d for %s:%s failed: %s", attempt + 1, host, port, err
            )
            if attempt < retries:
                await asyncio.sleep(retry_wait_seconds)

    _LOGGER.error("Unable to describe the Wyoming service at %s:%s", host, port)
    return None
