"""Independent unit tests for ``harness.config``.

Focus: the persisted run config must never leak the deployment host. The
harness masks the host but keeps scheme + port for reproducibility.
"""

from __future__ import annotations

from harness import config
from harness.ollama_client import DecodeOptions


def test_redact_host_masks_host_keeps_scheme_and_port() -> None:
    assert (
        config._redact_host("http://192.168.1.5:11434")
        == "http://REDACTED:11434"
    )


def test_redact_host_keeps_https_scheme() -> None:
    assert (
        config._redact_host("https://ollama.lan:443")
        == "https://REDACTED:443"
    )


def test_redact_host_without_port_omits_port() -> None:
    assert config._redact_host("http://192.168.1.5") == "http://REDACTED"


def test_redact_host_schemeless_input_keeps_port_and_hides_host() -> None:
    # Fix F1: a bare "host:port" without a scheme is defaulted to http:// before
    # urlsplit, so the port is preserved (previously it was dropped). The
    # security-critical invariant (the raw host never leaks) still holds.
    redacted = config._redact_host("10.0.0.9:11434")
    assert "10.0.0.9" not in redacted
    assert redacted == "http://REDACTED:11434"  # port now preserved


def test_redact_host_never_leaks_raw_ip() -> None:
    raw_ip = "192.0.2.37"
    assert raw_ip not in config._redact_host(f"http://{raw_ip}:11434")


def _make_run_config(base_url: str) -> config.RunConfig:
    return config.RunConfig(
        run_id="20260712T000000Z-test",
        mode="dryrun",
        model_under_test="qwen2.5:14b",
        judge_model="mistral-small3.2:latest",
        judge_enabled=False,
        repetitions=2,
        drift_depth=7,
        shallow_filler_count=2,
        decode=DecodeOptions(temperature=0.7, top_p=0.9, seed=42, num_ctx=8192),
        seed_base=42,
        system_prompt_sha256="a" * 64,
        eval_set_sha256="b" * 64,
        ollama_base_url=base_url,
    )


def test_run_config_to_dict_redacts_host() -> None:
    cfg = _make_run_config("http://192.0.2.37:11434")
    data = cfg.to_dict()
    assert data["ollama_base_url"] == "http://REDACTED:11434"
    assert "192.0.2.37" not in data["ollama_base_url"]


def test_run_config_to_dict_never_emits_raw_host_anywhere() -> None:
    raw_host = "192.0.2.37"
    cfg = _make_run_config(f"http://{raw_host}:11434")
    data = cfg.to_dict()
    # No value in the serialized config may contain the raw host.
    assert raw_host not in repr(data)


def test_run_config_to_dict_serializes_decode_as_plain_dict() -> None:
    cfg = _make_run_config("http://127.0.0.1:11434")
    data = cfg.to_dict()
    assert data["decode"] == {
        "temperature": 0.7,
        "top_p": 0.9,
        "seed": 42,
        "num_ctx": 8192,
    }


def test_sha256_text_is_stable_and_hex() -> None:
    digest = config.sha256_text("hello")
    assert digest == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert len(digest) == 64
