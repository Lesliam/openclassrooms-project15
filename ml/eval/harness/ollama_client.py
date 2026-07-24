"""Minimal Ollama chat client for the evaluation harness.

Uses the ``/api/chat`` endpoint with role messages so multi-turn context
accumulates across a dialogue (required for the D3 drift probes). Decoding
parameters are passed explicitly and are meant to be logged by the caller.

All failures (timeout, connection error, non-200, malformed body) raise
``OllamaError`` — errors are never silently swallowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import requests

from . import constants

Role = Literal["system", "user", "assistant"]


class OllamaError(RuntimeError):
    """Raised for any failure talking to the Ollama server."""


@dataclass(frozen=True)
class Message:
    """A single chat message in the Ollama role format."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class DecodeOptions:
    """Decoding parameters forwarded to Ollama's ``options`` field.

    These are logged verbatim into each run's config so a run is
    reproducible from its record alone.
    """

    temperature: float
    top_p: float
    seed: int
    num_ctx: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "num_ctx": self.num_ctx,
        }


class OllamaClient:
    """Thin wrapper over the Ollama chat API."""

    def __init__(
        self,
        base_url: str = constants.OLLAMA_BASE_URL,
        connect_timeout_s: float = constants.HTTP_CONNECT_TIMEOUT_S,
        read_timeout_s: float = constants.HTTP_READ_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = (connect_timeout_s, read_timeout_s)

    def chat(
        self,
        model: str,
        messages: list[Message],
        options: DecodeOptions,
    ) -> str:
        """Send a chat request and return the assistant reply text.

        Raises ``OllamaError`` on any transport or protocol failure.
        """
        url = f"{self._base_url}{constants.OLLAMA_CHAT_PATH}"
        payload = {
            "model": model,
            "messages": [m.as_dict() for m in messages],
            "stream": False,
            "options": options.as_dict(),
        }
        try:
            response = requests.post(url, json=payload, timeout=self._timeout)
        except requests.Timeout as exc:
            raise OllamaError(f"Ollama request timed out after {self._timeout}s") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        if response.status_code != 200:
            body = response.text[:500]
            raise OllamaError(
                f"Ollama returned HTTP {response.status_code}: {body}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a non-JSON body") from exc

        content = self._extract_content(data)
        if content is None:
            raise OllamaError(f"Ollama response missing message content: {data!r}")
        return content

    @staticmethod
    def _extract_content(data: dict) -> Optional[str]:
        message = data.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if not isinstance(content, str):
            return None
        return content

    def list_models(self) -> list[str]:
        """Return the names of models the server has loaded (for a health check)."""
        url = f"{self._base_url}{constants.OLLAMA_TAGS_PATH}"
        try:
            response = requests.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama tags request failed: {exc}") from exc
        if response.status_code != 200:
            raise OllamaError(f"Ollama tags returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama tags returned a non-JSON body") from exc
        return [m.get("name", "") for m in data.get("models", [])]
