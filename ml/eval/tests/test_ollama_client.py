"""Independent unit tests for ``harness.ollama_client``.

The network is never touched: ``requests.post`` / ``requests.get`` are
monkeypatched. Contract under audit:
- ``DecodeOptions`` serialization is forwarded verbatim into ``options``;
- a non-200 response raises ``OllamaError`` (errors are never swallowed);
- transport errors and malformed bodies raise ``OllamaError``.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest
import requests

from harness import ollama_client
from harness.ollama_client import (
    DecodeOptions,
    Message,
    OllamaClient,
    OllamaError,
)

_OPTIONS = DecodeOptions(temperature=0.7, top_p=0.9, seed=42, num_ctx=8192)


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(
        self,
        status_code: int,
        json_data: Optional[dict] = None,
        text: str = "",
        raise_on_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._raise_on_json = raise_on_json

    def json(self) -> Any:
        if self._raise_on_json:
            raise ValueError("no JSON")
        return self._json_data


# --- DecodeOptions serialization -------------------------------------------


def test_decode_options_as_dict_has_expected_keys_and_values() -> None:
    assert _OPTIONS.as_dict() == {
        "temperature": 0.7,
        "top_p": 0.9,
        "seed": 42,
        "num_ctx": 8192,
    }


def test_message_as_dict_role_and_content() -> None:
    assert Message(role="user", content="Bonjour").as_dict() == {
        "role": "user",
        "content": "Bonjour",
    }


# --- chat() happy path ------------------------------------------------------


def test_chat_returns_content_and_sends_serialized_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout
        return _FakeResponse(200, {"message": {"content": "Salut !"}})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)

    client = OllamaClient(base_url="http://testhost:11434")
    reply = client.chat(
        "qwen2.5:14b", [Message(role="user", content="Bonjour")], _OPTIONS
    )

    assert reply == "Salut !"
    assert captured["url"] == "http://testhost:11434/api/chat"
    payload = captured["payload"]
    assert payload["model"] == "qwen2.5:14b"
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "Bonjour"}]
    # Decode options are forwarded verbatim.
    assert payload["options"] == _OPTIONS.as_dict()


def test_chat_base_url_trailing_slash_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        captured["url"] = url
        return _FakeResponse(200, {"message": {"content": "ok"}})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    OllamaClient(base_url="http://testhost:11434/").chat(
        "m", [Message(role="user", content="x")], _OPTIONS
    )
    assert captured["url"] == "http://testhost:11434/api/chat"


# --- chat() error handling --------------------------------------------------


def test_chat_non_200_raises_with_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(500, text="internal boom")

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError) as exc_info:
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)
    assert "500" in str(exc_info.value)
    assert "internal boom" in str(exc_info.value)


def test_chat_timeout_raises_ollama_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        raise requests.Timeout("timed out")

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError) as exc_info:
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)
    assert "timed out" in str(exc_info.value)


def test_chat_connection_error_raises_ollama_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError):
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)


def test_chat_non_json_body_raises_ollama_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(200, raise_on_json=True)

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError):
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)


def test_chat_missing_message_content_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(200, {"done": True})  # no "message" key

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError):
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)


def test_chat_non_string_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(200, {"message": {"content": 123}})

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError):
        client.chat("m", [Message(role="user", content="x")], _OPTIONS)


# --- list_models() ----------------------------------------------------------


def test_list_models_parses_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: Any) -> _FakeResponse:
        return _FakeResponse(
            200, {"models": [{"name": "qwen2.5:14b"}, {"name": "mistral"}]}
        )

    monkeypatch.setattr(ollama_client.requests, "get", fake_get)
    client = OllamaClient(base_url="http://testhost:11434")
    assert client.list_models() == ["qwen2.5:14b", "mistral"]


def test_list_models_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: Any) -> _FakeResponse:
        return _FakeResponse(404)

    monkeypatch.setattr(ollama_client.requests, "get", fake_get)
    client = OllamaClient(base_url="http://testhost:11434")
    with pytest.raises(OllamaError):
        client.list_models()
