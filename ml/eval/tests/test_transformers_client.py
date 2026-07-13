"""Unit tests for ``TransformersClient`` routing WITHOUT loading a model.

The heavy work (loading the 4-bit base + LoRA adapter) happens in
``__init__``; we bypass it with ``object.__new__`` and inject fakes, so these
run in milliseconds on CPU. What is under test is purely the ``chat`` routing
contract:

- baseline arm -> enter ``self._model.disable_adapter()`` (adapter OFF)
- tuned arm    -> do NOT enter it (adapter ON)

plus the static ``list_models`` listing.
"""

from __future__ import annotations

from run_transformers_compare import (
    _BASELINE_ARM,
    _TUNED_ARM,
    TransformersClient,
)


class _RecordingAdapterCtx:
    """Context manager that records whether it was entered."""

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> "_RecordingAdapterCtx":
        self.entered = True
        return self

    def __exit__(self, *exc) -> bool:
        self.exited = True
        return False


class _FakeModel:
    """Stub PeftModel whose ``disable_adapter`` yields a recording ctx."""

    def __init__(self) -> None:
        self.ctx = _RecordingAdapterCtx()
        self.disable_calls = 0

    def disable_adapter(self) -> _RecordingAdapterCtx:
        self.disable_calls += 1
        return self.ctx


def _make_client() -> TransformersClient:
    # Bypass __init__ (which loads the 14B base + adapter). Inject a fake model
    # and a fake _generate so no weights are touched.
    client = object.__new__(TransformersClient)
    client._model = _FakeModel()
    client._generate = lambda messages, options: "REPLY"
    return client


def test_list_models_returns_both_arms() -> None:
    client = _make_client()
    assert client.list_models() == [_BASELINE_ARM, _TUNED_ARM]
    assert client.list_models() == ["baseline", "coach-tuned:v0"]


def test_chat_baseline_arm_disables_adapter() -> None:
    client = _make_client()
    reply = client.chat(_BASELINE_ARM, messages=[], options=None)
    assert reply == "REPLY"
    assert client._model.disable_calls == 1
    assert client._model.ctx.entered is True
    assert client._model.ctx.exited is True


def test_chat_tuned_arm_keeps_adapter_enabled() -> None:
    client = _make_client()
    reply = client.chat(_TUNED_ARM, messages=[], options=None)
    assert reply == "REPLY"
    # Tuned arm must NOT touch disable_adapter -> the adapter stays ON.
    assert client._model.disable_calls == 0
    assert client._model.ctx.entered is False
