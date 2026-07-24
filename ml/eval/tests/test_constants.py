"""Independent unit tests for ``harness.constants._resolve_ollama_base_url``.

Env-var precedence (per the docstring):
``OLLAMA_BASE_URL`` (full URL) > ``OLLAMA_HOST`` (host, expanded to a URL) >
localhost default. A host without a port gets the default :11434.
"""

from __future__ import annotations

import pytest

from harness import constants
from harness.constants import _resolve_ollama_base_url

_ENV_VARS = ("OLLAMA_BASE_URL", "OLLAMA_HOST")


@pytest.fixture(autouse=True)
def _clear_ollama_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ambient shell exports OLLAMA_HOST; clear both so each test controls
    # the environment explicitly.
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_base_url_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.1.2.3:9999")
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.5")  # must be ignored
    assert _resolve_ollama_base_url() == "http://10.1.2.3:9999"


def test_base_url_env_trailing_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.1.2.3:9999/")
    assert _resolve_ollama_base_url() == "http://10.1.2.3:9999"


def test_host_without_port_gets_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.5")
    assert _resolve_ollama_base_url() == "http://192.168.1.5:11434"


def test_host_without_scheme_gets_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "myhost:11434")
    assert _resolve_ollama_base_url() == "http://myhost:11434"


def test_host_with_explicit_port_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "192.168.1.5:12345")
    assert _resolve_ollama_base_url() == "http://192.168.1.5:12345"


def test_default_is_localhost_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both env vars cleared by the autouse fixture.
    assert _resolve_ollama_base_url() == "http://127.0.0.1:11434"


def test_default_port_constant_matches_expected() -> None:
    assert constants._DEFAULT_OLLAMA_PORT == 11434
