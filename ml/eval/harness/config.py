"""Run configuration: system-prompt loading and content SHAs.

The harness records a content SHA-256 of the frozen system prompt and of the
eval-set spec in every run's config, so a run is traceable to the exact
inputs that produced it. Content hashing is used instead of git SHAs so the
harness never needs to shell out to git.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from . import constants
from .ollama_client import DecodeOptions

_REDACTED_HOST = "REDACTED"


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redact_host(base_url: str) -> str:
    """Mask the host in an Ollama base URL, keeping scheme and port.

    The persisted run config can be committed to a public repository, so the
    deployment address must not leak; the port is kept for reproducibility.
    """
    parts = urlsplit(base_url)
    scheme = parts.scheme or "http"
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{scheme}://{_REDACTED_HOST}{port}"


def load_system_prompt() -> str:
    """Return the literal system prompt (the body after the separator)."""
    raw = constants.SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    if constants.PROMPT_BODY_SEPARATOR in raw:
        body = raw.split(constants.PROMPT_BODY_SEPARATOR, 1)[1]
    else:
        body = raw
    return body.strip()


def _read_optional(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@dataclass(frozen=True)
class RunConfig:
    """Everything needed to reproduce and audit a run."""

    run_id: str
    mode: str
    model_under_test: str
    judge_model: str
    judge_enabled: bool
    repetitions: int
    drift_depth: int
    shallow_filler_count: int
    decode: DecodeOptions
    seed_base: int
    system_prompt_sha256: str
    eval_set_sha256: str
    ollama_base_url: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["decode"] = self.decode.as_dict()
        # Persisted config may be committed (public mirror), so mask the
        # deployment host, keeping only scheme + port for reproducibility.
        data["ollama_base_url"] = _redact_host(self.ollama_base_url)
        return data


def build_run_config(
    *,
    run_id: str,
    mode: str,
    repetitions: int,
    drift_depth: int,
    judge_enabled: bool,
    judge_model: str,
    decode: DecodeOptions,
) -> RunConfig:
    """Assemble the immutable run config, hashing the frozen inputs."""
    system_prompt = load_system_prompt()
    eval_set_text = _read_optional(constants.EVAL_SET_FILE)
    return RunConfig(
        run_id=run_id,
        mode=mode,
        model_under_test=constants.MODEL_UNDER_TEST,
        judge_model=judge_model,
        judge_enabled=judge_enabled,
        repetitions=repetitions,
        drift_depth=drift_depth,
        shallow_filler_count=constants.SHALLOW_FILLER_COUNT,
        decode=decode,
        seed_base=constants.DECODE_SEED_BASE,
        system_prompt_sha256=sha256_text(system_prompt),
        eval_set_sha256=sha256_text(eval_set_text),
        ollama_base_url=constants.OLLAMA_BASE_URL,
    )
