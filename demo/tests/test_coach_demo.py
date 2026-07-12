"""Independent unit tests for the Gradio coach demo (CS-154).

Audits the PURE / mockable functions of ``coach_demo.py`` without touching a
live Ollama server (the HTTP layer is monkeypatched). Coverage:

1. ``resolve_ollama_base_url`` env precedence and expansion;
2. ``load_system_prompt`` returns the body after the ``---`` separator, stripped;
3. message-history assembly (system + alternating user/assistant) into the
   ``/api/chat`` payload;
4. graceful degradation: a failing Ollama call yields the in-character fallback
   reply instead of propagating the exception.

The tests do NOT modify ``coach_demo.py`` and are re-runnable in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import requests

import coach_demo

# Type of the built demo's reply handler: (message, history) -> (cleared, history)
RespondHandler = Callable[
    [str, list[dict[str, str]]], tuple[str, list[dict[str, str]]]
]


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(
        self,
        status_code: int,
        json_data: dict | None = None,
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


def _get_respond_handler(demo: Any) -> RespondHandler:
    """Extract the ``respond`` closure registered on the built Gradio demo."""
    fns = demo.fns
    items = list(fns.values()) if isinstance(fns, dict) else list(fns)
    for block_fn in items:
        fn = getattr(block_fn, "fn", None)
        if fn is not None and getattr(fn, "__name__", "") == "respond":
            return fn
    raise AssertionError("respond handler not found on the built demo")


# --- 1. resolve_ollama_base_url --------------------------------------------

_ENV_VARS = ("OLLAMA_BASE_URL", "OLLAMA_HOST")


@pytest.fixture(autouse=True)
def _clear_ollama_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ambient shell exports OLLAMA_HOST; clear both so each test controls
    # the environment explicitly.
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_base_url_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.1.2.3:9999")
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.5")  # must be ignored
    assert coach_demo.resolve_ollama_base_url() == "http://10.1.2.3:9999"


def test_base_url_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.1.2.3:9999/")
    assert coach_demo.resolve_ollama_base_url() == "http://10.1.2.3:9999"


def test_host_without_scheme_or_port_expands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.5")
    assert coach_demo.resolve_ollama_base_url() == "http://192.168.1.5:11434"


def test_host_without_scheme_keeps_explicit_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "myhost:12345")
    assert coach_demo.resolve_ollama_base_url() == "http://myhost:12345"


def test_empty_env_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both env vars cleared by the autouse fixture.
    assert coach_demo.resolve_ollama_base_url() == "http://127.0.0.1:11434"


# --- 2. load_system_prompt --------------------------------------------------


def test_load_system_prompt_from_real_baseline_file() -> None:
    body = coach_demo.load_system_prompt()
    # Body is the French prompt after the "---" separator, stripped: the design
    # rationale above the separator must not leak in.
    assert body.startswith("Tu es un coach de conversation en français")
    assert "Design rationale" not in body
    assert body == body.strip()


def test_load_system_prompt_returns_body_after_separator(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(
        "Rationale header\n\n---\n\n  Corps du prompt en français.  \n",
        encoding="utf-8",
    )
    assert coach_demo.load_system_prompt(prompt_file) == "Corps du prompt en français."


def test_load_system_prompt_without_separator_returns_whole_stripped(
    tmp_path: Path,
) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("  Un prompt sans separateur.  \n", encoding="utf-8")
    assert coach_demo.load_system_prompt(prompt_file) == "Un prompt sans separateur."


def test_load_system_prompt_splits_only_on_first_separator(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(
        "rationale\n---\nbody part one\n---\nbody part two\n", encoding="utf-8"
    )
    # Only the FIRST separator splits; the second stays inside the body.
    assert coach_demo.load_system_prompt(prompt_file) == (
        "body part one\n---\nbody part two"
    )


# --- 3. message-history assembly -------------------------------------------


def test_decode_options_as_dict_keys() -> None:
    assert coach_demo.DecodeOptions().as_dict() == {
        "temperature": 0.7,
        "top_p": 0.9,
        "num_ctx": 8192,
    }


def test_chat_once_builds_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(200, {"message": {"content": "D'accord."}})

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)

    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "Bonjour"},
    ]
    reply = coach_demo.chat_once("http://testhost:11434/", messages)

    assert reply == "D'accord."
    assert captured["url"] == "http://testhost:11434/api/chat"
    payload = captured["payload"]
    assert payload["model"] == "qwen2.5:14b"
    assert payload["stream"] is False
    assert payload["messages"] == messages
    assert payload["options"] == coach_demo.DecodeOptions().as_dict()


def test_coach_reply_prepends_system_and_preserves_multi_turn_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        captured["payload"] = json
        return _FakeResponse(200, {"message": {"content": "Continue."}})

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)

    history = [
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Salut ! Parle-moi de ton projet."},
        {"role": "user", "content": "Je construis un coach vocal."},
    ]
    reply = coach_demo.coach_reply("http://testhost:11434", "SYSTEM PROMPT", history)

    assert reply == "Continue."
    sent = captured["payload"]["messages"]
    # System message prepended, then the history verbatim and in order.
    assert sent[0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert sent[1:] == history
    assert [m["role"] for m in sent] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_chat_once_missing_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(200, {"done": True})  # no "message" key

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)
    with pytest.raises(coach_demo.OllamaChatError):
        coach_demo.chat_once("http://testhost:11434", [{"role": "user", "content": "x"}])


# --- 4. graceful degradation ------------------------------------------------


def test_chat_once_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(503, text="unavailable")

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)
    with pytest.raises(coach_demo.OllamaChatError):
        coach_demo.chat_once("http://testhost:11434", [{"role": "user", "content": "x"}])


def test_chat_once_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        raise requests.Timeout("slow")

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)
    with pytest.raises(coach_demo.OllamaChatError):
        coach_demo.chat_once("http://testhost:11434", [{"role": "user", "content": "x"}])


def test_respond_returns_fallback_when_coach_reply_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reply handler must swallow OllamaChatError and answer in-character.
    monkeypatch.setattr(
        coach_demo,
        "coach_reply",
        lambda *a, **k: (_ for _ in ()).throw(coach_demo.OllamaChatError("down")),
    )
    demo = coach_demo.build_demo(base_url="http://testhost:11434")
    respond = _get_respond_handler(demo)

    cleared, history = respond("Bonjour", [])
    assert cleared == ""
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == coach_demo._BACKEND_ERROR_REPLY
    # The user turn is preserved before the fallback assistant turn.
    assert history[0] == {"role": "user", "content": "Bonjour"}


def test_respond_degrades_through_real_chat_path_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end degradation: mock only the HTTP layer (transport error). The
    # exception must be wrapped by chat_once and absorbed by respond.
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)
    demo = coach_demo.build_demo(base_url="http://testhost:11434")
    respond = _get_respond_handler(demo)

    _, history = respond("Salut", [])
    assert history[-1]["content"] == coach_demo._BACKEND_ERROR_REPLY


def test_respond_on_successful_backend_appends_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        return _FakeResponse(200, {"message": {"content": "Bonjour ! Continue."}})

    monkeypatch.setattr(coach_demo.requests, "post", fake_post)
    demo = coach_demo.build_demo(base_url="http://testhost:11434")
    respond = _get_respond_handler(demo)

    cleared, history = respond("Bonjour", [])
    assert cleared == ""
    assert history[-1] == {"role": "assistant", "content": "Bonjour ! Continue."}


def test_respond_ignores_blank_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # A whitespace-only message must not hit the backend or mutate history.
    def fail_post(url: str, json: dict, timeout: Any) -> _FakeResponse:
        raise AssertionError("backend must not be called for a blank message")

    monkeypatch.setattr(coach_demo.requests, "post", fail_post)
    demo = coach_demo.build_demo(base_url="http://testhost:11434")
    respond = _get_respond_handler(demo)

    cleared, history = respond("   ", [])
    assert cleared == ""
    assert history == []
