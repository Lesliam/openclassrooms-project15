"""Test helpers for the Coach STT integration.

The integration package imports Home Assistant, which is not installed in this
development environment. wyoming_client.py is deliberately free of Home
Assistant imports, so it is loaded here directly from its file path instead of
through the coach_stt package.

The helpers below start a real asyncio TCP server speaking the Wyoming protocol,
so the client is exercised against real framing rather than against mocks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from wyoming.asr import Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import async_read_event, async_write_event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info

_CLIENT_PATH = Path(__file__).resolve().parents[1] / "coach_stt" / "wyoming_client.py"


def _load_wyoming_client() -> ModuleType:
    """Load wyoming_client.py without importing the coach_stt package."""
    spec = importlib.util.spec_from_file_location("coach_wyoming_client", _CLIENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {_CLIENT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wyoming_client = _load_wyoming_client()


@dataclass
class FakeService:
    """State of a fake Wyoming ASR service, inspected by the tests."""

    transcript_text: str = "bonjour"
    reply_with_transcript: bool = True
    transcript_delay: float = 0.0
    describe_reply: bool = True
    languages: list[str] = field(default_factory=lambda: ["fr"])
    asr_installed: bool = True

    host: str = "127.0.0.1"
    port: int = 0
    received_audio: bytearray = field(default_factory=bytearray)
    transcribe_language: str | None = None
    audio_start_format: tuple[int, int, int] | None = None
    audio_stopped: bool = False

    @property
    def received_seconds(self) -> float:
        """Return the duration of the audio received, in seconds."""
        return len(self.received_audio) / wyoming_client.BYTES_PER_SECOND


def _build_info(service: FakeService) -> Info:
    """Build the Info event advertised by the fake service."""
    attribution = Attribution(name="test", url="http://localhost")
    return Info(
        asr=[
            AsrProgram(
                name="faster-whisper",
                description="fake service",
                attribution=attribution,
                installed=service.asr_installed,
                version="3.1.0",
                models=[
                    AsrModel(
                        name="large-v3",
                        description="fake model",
                        attribution=attribution,
                        installed=True,
                        languages=list(service.languages),
                        version="1.0",
                    )
                ],
            )
        ]
    )


async def _handle_client(
    service: FakeService,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Serve one client connection using the Wyoming protocol."""
    try:
        while True:
            event = await async_read_event(reader)
            if event is None:
                break

            if Describe.is_type(event.type):
                if not service.describe_reply:
                    # Stay silent so the client hits its own timeout.
                    continue
                await async_write_event(_build_info(service).event(), writer)
            elif event.type == "transcribe":
                service.transcribe_language = event.data.get("language")
            elif AudioStart.is_type(event.type):
                start = AudioStart.from_event(event)
                service.audio_start_format = (start.rate, start.width, start.channels)
            elif AudioChunk.is_type(event.type):
                service.received_audio.extend(AudioChunk.from_event(event).audio)
            elif AudioStop.is_type(event.type):
                service.audio_stopped = True
                if service.transcript_delay:
                    await asyncio.sleep(service.transcript_delay)
                if not service.reply_with_transcript:
                    break
                await async_write_event(
                    Transcript(text=service.transcript_text).event(), writer
                )
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


@asynccontextmanager
async def fake_service(**kwargs: object) -> AsyncIterator[FakeService]:
    """Start a fake Wyoming service on an ephemeral port for the duration."""
    service = FakeService(**kwargs)  # type: ignore[arg-type]
    server = await asyncio.start_server(
        lambda reader, writer: _handle_client(service, reader, writer),
        service.host,
        0,
    )
    service.port = server.sockets[0].getsockname()[1]
    try:
        yield service
    finally:
        server.close()
        await server.wait_closed()


async def audio_stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    """Yield the given chunks as an async audio stream."""
    for chunk in chunks:
        yield chunk


def pcm_seconds(seconds: float) -> bytes:
    """Return a block of silent 16 kHz mono PCM of the given duration."""
    return bytes(int(seconds * wyoming_client.BYTES_PER_SECOND))


async def free_port() -> int:
    """Return a TCP port with no listener, for connection-failure tests."""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port
