"""Named constants for the evaluation harness.

All magic values used across the harness live here so a single edit changes
behavior everywhere and every value is documented. Decoding parameters are
flagged as v0 guesses that need Lesliam's review (eval_set_v0 section 5).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

# Default Ollama port when the environment specifies only a host.
_DEFAULT_OLLAMA_PORT = 11434


def _resolve_ollama_base_url() -> str:
    """Resolve the Ollama base URL from the environment.

    The real host is deployment-specific (and on this deployment loopback is
    dead by design, so the LAN IP must be used). To keep deployment topology
    out of version control, the address is read from the environment rather
    than hardcoded: ``OLLAMA_BASE_URL`` (full URL) takes precedence, else
    ``OLLAMA_HOST`` (host, as exported by the Ollama CLI env) is expanded to a
    URL, else a localhost default. Set one of these before running.
    """
    explicit = os.environ.get("OLLAMA_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1")
    if "://" not in host:
        host = f"http://{host}"
    if urlsplit(host).port is None:
        host = f"{host}:{_DEFAULT_OLLAMA_PORT}"
    return host.rstrip("/")


# --- Network / models ------------------------------------------------------

# Ollama base URL — resolved from the environment (never hardcode the
# deployment's address; see _resolve_ollama_base_url).
OLLAMA_BASE_URL = _resolve_ollama_base_url()
OLLAMA_CHAT_PATH = "/api/chat"
OLLAMA_TAGS_PATH = "/api/tags"

# Model under test (baseline arm) and default judge model. The judge is a
# different family from the model under test to avoid self-preference; the
# final judge choice is an open point for Lesliam (eval_set_v0 section 5).
MODEL_UNDER_TEST = "qwen2.5:14b"
DEFAULT_JUDGE_MODEL = "mistral-small3.2:latest"

# HTTP timeouts in seconds (connect, read). Coach replies are short but the
# 14B model can take a while on first token, so the read timeout is generous.
HTTP_CONNECT_TIMEOUT_S = 10.0
HTTP_READ_TIMEOUT_S = 180.0

# --- Decoding parameters (v0 GUESSES — need Lesliam's review) ---------------
#
# Rationale: a fixed base seed makes every run reproducible; per-repetition
# seeds (base + repetition index) give the controlled decoding variance the
# run protocol asks for (N repetitions) without sacrificing reproducibility.
# temperature/top_p are moderate deployment-realistic values, not greedy,
# so the variance measured is meaningful. num_ctx must be large enough to
# hold the deep drift context (25+ turns).
DECODE_TEMPERATURE = 0.7
DECODE_TOP_P = 0.9
DECODE_SEED_BASE = 42
DECODE_NUM_CTX = 8192

# Judge decoding: temperature 0 for stable grading (eval_set_v0 section 2).
JUDGE_TEMPERATURE = 0.0
JUDGE_SEED = 0

# --- Scoring thresholds ----------------------------------------------------

# D1 restatement pre-check: a quoted span counts as a restatement of the
# learner sentence when its token overlap reaches this fraction. This 0.60
# value is a v0 guess flagged for review in eval_set_v0 section 5.
D1_RESTATEMENT_OVERLAP_THRESHOLD = 0.60

# Brevity caps (sentence counts) from the system prompt and eval_set_v0.
BREVITY_MAX_SENTENCES_CORRECTING = 4  # when a correction is emitted
BREVITY_MAX_SENTENCES_DEFAULT = 3  # normal spoken-style turn

# Language-ID: langdetect determinism seed (langdetect.DetectorFactory.seed).
LANGDETECT_SEED = 0
FRENCH_LANG_CODE = "fr"

# --- Run parameters --------------------------------------------------------

# Repetitions per item. Full-run default is a v0 guess (eval_set_v0 section
# 4); the dry-run overrides it to keep cost low.
DEFAULT_REPETITIONS = 5
DRYRUN_REPETITIONS = 2

# Drift depth = number of scripted filler turns injected before the deep
# probe. Full run pads to a deep conversation; dry-run uses a reduced depth
# so the dry-run finishes in minutes.
DEFAULT_DRIFT_DEPTH = 18
DRYRUN_DRIFT_DEPTH = 7

# Number of warm-up filler turns sent before the SHALLOW probe so the probe
# lands around turn 3 (eval_set_v0 section 3, group C).
SHALLOW_FILLER_COUNT = 2

# --- Paths -----------------------------------------------------------------

# eval/ directory (parent of this package).
EVAL_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = EVAL_DIR / "runs"
EVAL_SET_FILE = EVAL_DIR / "eval_set_v0.md"

# The frozen system prompt (baseline arm). Lives under project/server/.
# EVAL_DIR = project/ml/eval, so the project root is two levels up.
PROJECT_ROOT = EVAL_DIR.parent.parent
SERVER_DIR = PROJECT_ROOT / "server"
SYSTEM_PROMPT_FILE = SERVER_DIR / "coach_system_prompt_v0.md"

# Separator between the design rationale and the prompt body inside
# coach_system_prompt_v0.md. Everything after the first occurrence is the
# literal system prompt sent to the model.
PROMPT_BODY_SEPARATOR = "\n---\n"
