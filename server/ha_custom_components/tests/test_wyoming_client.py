"""Unit tests for the Wyoming client used by the Coach STT entity.

The tests run without a Home Assistant installation. Each test drives a real
asyncio Wyoming server (see conftest.py) through asyncio.run, so no
pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from conftest import (
    audio_stream,
    fake_service,
    free_port,
    pcm_seconds,
    wyoming_client,
)

TranscriptionStatus = wyoming_client.TranscriptionStatus


def test_transcribe_returns_text_and_forwards_audio() -> None:
    """A normal turn returns the transcript and forwards every chunk."""

    async def scenario() -> None:
        async with fake_service(transcript_text="je voudrais un cafe") as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                audio_stream([pcm_seconds(0.5), pcm_seconds(0.5)]),
            )

        assert result.status is TranscriptionStatus.SUCCESS
        assert result.text == "je voudrais un cafe"
        assert result.truncated is False
        assert result.audio_seconds == pytest.approx(1.0)
        assert service.received_seconds == pytest.approx(1.0)
        assert service.audio_stopped is True

    asyncio.run(scenario())


def test_transcribe_announces_language_and_audio_format() -> None:
    """The language and the 16 kHz mono format reach the service."""

    async def scenario() -> None:
        async with fake_service() as service:
            await wyoming_client.transcribe_stream(
                service.host, service.port, "fr", audio_stream([pcm_seconds(0.1)])
            )

        assert service.transcribe_language == "fr"
        assert service.audio_start_format == (16000, 2, 1)

    asyncio.run(scenario())


def test_empty_stream_returns_empty_text_without_raising() -> None:
    """A turn without audio is a successful, empty result."""

    async def scenario() -> None:
        async with fake_service(transcript_text="") as service:
            result = await wyoming_client.transcribe_stream(
                service.host, service.port, "fr", audio_stream([])
            )

        assert result.status is TranscriptionStatus.SUCCESS
        assert result.text == ""
        assert result.audio_seconds == 0.0
        assert service.audio_stopped is True

    asyncio.run(scenario())


def test_empty_chunks_are_skipped() -> None:
    """Zero-length chunks are not forwarded to the service."""

    async def scenario() -> None:
        async with fake_service() as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                audio_stream([b"", pcm_seconds(0.25), b""]),
            )

        assert result.audio_seconds == pytest.approx(0.25)
        assert service.received_seconds == pytest.approx(0.25)

    asyncio.run(scenario())


def test_max_duration_guard_truncates_and_still_transcribes() -> None:
    """The backstop stops consuming audio but still returns a transcript."""
    consumed = 0

    async def endless_stream() -> AsyncIterator[bytes]:
        nonlocal consumed
        for _ in range(100):
            consumed += 1
            yield pcm_seconds(1.0)

    async def scenario() -> None:
        async with fake_service(transcript_text="tronque") as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                endless_stream(),
                max_duration_seconds=3.0,
            )

        assert result.status is TranscriptionStatus.SUCCESS
        assert result.text == "tronque"
        assert result.truncated is True
        assert result.audio_seconds == pytest.approx(3.0)
        assert service.received_seconds == pytest.approx(3.0)
        assert consumed == 3

    asyncio.run(scenario())


def test_max_duration_guard_can_be_disabled() -> None:
    """max_duration_seconds=None consumes the whole stream."""

    async def scenario() -> None:
        async with fake_service() as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                audio_stream([pcm_seconds(1.0)] * 5),
                max_duration_seconds=None,
            )

        assert result.truncated is False
        assert result.audio_seconds == pytest.approx(5.0)

    asyncio.run(scenario())


def test_guard_does_not_fire_below_the_limit() -> None:
    """Audio shorter than the limit is not reported as truncated."""

    async def scenario() -> None:
        async with fake_service() as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                audio_stream([pcm_seconds(1.0), pcm_seconds(1.0)]),
                max_duration_seconds=10.0,
            )

        assert result.truncated is False

    asyncio.run(scenario())


def test_connection_refused_returns_error_result() -> None:
    """An unreachable service is reported through the result, not an exception."""

    async def scenario() -> None:
        port = await free_port()
        result = await wyoming_client.transcribe_stream(
            "127.0.0.1", port, "fr", audio_stream([pcm_seconds(0.1)])
        )

        assert result.status is TranscriptionStatus.ERROR
        assert result.text == ""
        assert result.error

    asyncio.run(scenario())


def test_service_closing_without_transcript_returns_error_result() -> None:
    """A service that disconnects after audio-stop yields an error result."""

    async def scenario() -> None:
        async with fake_service(reply_with_transcript=False) as service:
            result = await wyoming_client.transcribe_stream(
                service.host, service.port, "fr", audio_stream([pcm_seconds(0.1)])
            )

        assert result.status is TranscriptionStatus.ERROR
        assert result.audio_seconds == pytest.approx(0.1)

    asyncio.run(scenario())


def test_transcript_timeout_returns_error_result() -> None:
    """A service that never answers is bounded by the transcript timeout."""

    async def scenario() -> None:
        async with fake_service(transcript_delay=5.0) as service:
            result = await wyoming_client.transcribe_stream(
                service.host,
                service.port,
                "fr",
                audio_stream([pcm_seconds(0.1)]),
                transcript_timeout_seconds=0.2,
            )

        assert result.status is TranscriptionStatus.ERROR

    asyncio.run(scenario())


def test_describe_service_reports_name_and_languages() -> None:
    """Describe returns the ASR name and the languages of installed models."""

    async def scenario() -> None:
        async with fake_service(languages=["fr", "en"]) as service:
            description = await wyoming_client.describe_service(
                service.host, service.port
            )

        assert description is not None
        assert description.name == "faster-whisper"
        assert description.languages == ("fr", "en")

    asyncio.run(scenario())


def test_describe_service_reports_every_advertised_language() -> None:
    """Describe reports the raw list; narrowing is the caller's decision."""

    async def scenario() -> None:
        async with fake_service(languages=["fr", "en", "de", "it"]) as service:
            description = await wyoming_client.describe_service(
                service.host, service.port
            )

        assert description is not None
        assert description.languages == ("fr", "en", "de", "it")

    asyncio.run(scenario())


def test_select_languages_keeps_only_the_preferred_ones() -> None:
    """A service advertising many languages is narrowed to the Coach ones."""
    advertised = ("de", "en", "es", "fr", "it", "zh")

    assert wyoming_client.select_languages(advertised, ("fr", "en")) == ("fr", "en")


def test_select_languages_preserves_the_preferred_order() -> None:
    """The order of the preferred list wins over the advertised order."""
    assert wyoming_client.select_languages(("en", "fr"), ("fr", "en")) == ("fr", "en")


def test_select_languages_drops_unavailable_preferences() -> None:
    """A preferred language the service does not serve is not offered."""
    assert wyoming_client.select_languages(("fr", "de"), ("fr", "en")) == ("fr",)


def test_select_languages_falls_back_when_nothing_matches() -> None:
    """An empty or unrelated advertisement leaves the entity usable."""
    assert wyoming_client.select_languages((), ("fr", "en")) == ("fr", "en")
    assert wyoming_client.select_languages(("zh",), ("fr", "en")) == ("fr", "en")


def test_describe_service_returns_none_when_unreachable() -> None:
    """Describe gives up after its retries and returns None."""

    async def scenario() -> None:
        port = await free_port()
        description = await wyoming_client.describe_service(
            "127.0.0.1", port, retries=1, retry_wait_seconds=0.01
        )

        assert description is None

    asyncio.run(scenario())


def test_describe_service_times_out_on_silent_peer() -> None:
    """A peer that accepts the connection but never answers is bounded."""

    async def scenario() -> None:
        async with fake_service(describe_reply=False) as service:
            description = await wyoming_client.describe_service(
                service.host,
                service.port,
                timeout_seconds=0.2,
                retries=0,
            )

        assert description is None

    asyncio.run(scenario())
