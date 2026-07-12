"""Gradio demo of the French conversation coach (prompt baseline).

Presentable proof-of-concept for the P15 soutenance. A learner types French
(possibly with mistakes) and the coach replies following its designed
behavior:

- French-only output, even under language-switching pressure;
- a fixed 4-part correction format (restate, correct, explain, ask to repeat);
- a "simulation soutenance" role-play mode where the coach plays Charlotte,
  the manager, asking project-management questions.

Backend: the local Ollama server (``qwen2.5:14b``) via ``/api/chat``. The
full accumulating message history is sent on every turn so multi-turn
context is preserved -- this is what lets the drift / role-play behavior
surface. The system prompt is loaded from the frozen
``../server/coach_system_prompt_v0.md`` (the body after the ``---``
separator), which is the exact PROMPT BASELINE measured by the
``../ml/eval`` harness.

The Ollama host is resolved from the environment and is never hardcoded
(this repository has a public mirror): ``OLLAMA_BASE_URL`` (full URL) takes
precedence, else ``OLLAMA_HOST`` (host, as exported by the Ollama CLI) is
expanded to a URL, else a localhost default. Set one of these before
running if loopback is not the Ollama address on your deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import gradio as gr
import requests

# --- Network / model -------------------------------------------------------

# Default Ollama port when the environment specifies only a host.
_DEFAULT_OLLAMA_PORT = 11434
_OLLAMA_CHAT_PATH = "/api/chat"

# Model under test -- the same baseline arm the eval harness measures.
_MODEL_UNDER_TEST = "qwen2.5:14b"

# HTTP timeouts in seconds (connect, read). Coach replies are short, but the
# 14B model can take a while to produce its first token, so the read timeout
# is generous. These mirror the eval harness values.
_HTTP_CONNECT_TIMEOUT_S = 10.0
_HTTP_READ_TIMEOUT_S = 180.0

# --- Decoding parameters ---------------------------------------------------
#
# Deployment-realistic moderate sampling (not greedy), matching the eval
# harness so the demo behaves like the measured baseline. num_ctx is large
# enough to hold a long role-play conversation.
_DECODE_TEMPERATURE = 0.7
_DECODE_TOP_P = 0.9
_DECODE_NUM_CTX = 8192

# --- Paths -----------------------------------------------------------------

# The frozen system prompt (baseline arm) lives under project/server/.
# This file is project/demo/coach_demo.py, so the project root is one level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SYSTEM_PROMPT_FILE = _PROJECT_ROOT / "server" / "coach_system_prompt_v0.md"

# Separator between the design rationale and the prompt body inside
# coach_system_prompt_v0.md. Everything after the first occurrence is the
# literal system prompt sent to the model.
_PROMPT_BODY_SEPARATOR = "\n---\n"

# --- UI / server -----------------------------------------------------------

_DEMO_SERVER_NAME = "127.0.0.1"
_DEMO_SERVER_PORT = 7860

# Shown to the user when the backend is unreachable, so a demo failure is
# visible and in-character rather than a crash (graceful degradation).
_BACKEND_ERROR_REPLY = (
    "[demo] Le coach est momentanement injoignable "
    "(serveur Ollama indisponible). Verifiez que le service tourne, "
    "puis reessayez."
)

# Baseline metrics from the eval-harness dry run, framed as the
# pre-fine-tuning prompt baseline. Source run:
# ml/eval/runs/20260712T155712Z-dryrun/report.md (N=2, deterministic
# scorers, judge off). These are the numbers the fine-tuning experiment
# aims to improve on.
_BASELINE_RUN_ID = "20260712T155712Z-dryrun"
_BASELINE_METRICS: tuple[tuple[str, str], ...] = (
    ("Conformite du format de correction (D1, pre-check deterministe)", "55.0%"),
    ("Faux positifs de correction (D1)", "50.0%"),
    ("Persistance du francais (D2)", "50.0%"),
    ("Fraction moyenne de tokens francais (D2)", "0.946"),
)


class OllamaChatError(RuntimeError):
    """Raised for any failure talking to the Ollama chat endpoint."""


@dataclass(frozen=True)
class DecodeOptions:
    """Decoding parameters forwarded to Ollama's ``options`` field."""

    temperature: float = _DECODE_TEMPERATURE
    top_p: float = _DECODE_TOP_P
    num_ctx: int = _DECODE_NUM_CTX

    def as_dict(self) -> dict[str, float | int]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "num_ctx": self.num_ctx,
        }


def resolve_ollama_base_url() -> str:
    """Resolve the Ollama base URL from the environment.

    The real host is deployment-specific (on this deployment loopback is dead
    by design, so the LAN IP must be used). To keep deployment topology out of
    version control, the address is read from the environment rather than
    hardcoded: ``OLLAMA_BASE_URL`` (full URL) takes precedence, else
    ``OLLAMA_HOST`` (host, as exported by the Ollama CLI) is expanded to a URL,
    else a localhost default.
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


def load_system_prompt(path: Path = _SYSTEM_PROMPT_FILE) -> str:
    """Return the literal system prompt (the body after the separator).

    The prompt file keeps an English design rationale above a ``---`` line and
    the French prompt below it; only the body is sent to the model.
    """
    raw = path.read_text(encoding="utf-8")
    if _PROMPT_BODY_SEPARATOR in raw:
        body = raw.split(_PROMPT_BODY_SEPARATOR, 1)[1]
    else:
        body = raw
    return body.strip()


def _extract_content(data: dict) -> Optional[str]:
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    return content


def chat_once(
    base_url: str,
    messages: list[dict[str, str]],
    *,
    model: str = _MODEL_UNDER_TEST,
    options: Optional[DecodeOptions] = None,
) -> str:
    """Send one ``/api/chat`` request and return the assistant reply text.

    ``messages`` is the full role history (system + alternating user/assistant)
    so multi-turn context accumulates. Raises :class:`OllamaChatError` on any
    transport or protocol failure -- errors are never silently swallowed.
    """
    decode = options or DecodeOptions()
    url = f"{base_url.rstrip('/')}{_OLLAMA_CHAT_PATH}"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": decode.as_dict(),
    }
    timeout = (_HTTP_CONNECT_TIMEOUT_S, _HTTP_READ_TIMEOUT_S)
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.Timeout as exc:
        raise OllamaChatError(f"Ollama request timed out after {timeout}s") from exc
    except requests.RequestException as exc:
        raise OllamaChatError(f"Ollama request failed: {exc}") from exc

    if response.status_code != 200:
        raise OllamaChatError(
            f"Ollama returned HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise OllamaChatError("Ollama returned a non-JSON body") from exc

    content = _extract_content(data)
    if content is None:
        raise OllamaChatError(f"Ollama response missing message content: {data!r}")
    return content


def coach_reply(
    base_url: str,
    system_prompt: str,
    history: list[dict[str, str]],
) -> str:
    """Build the full role history and return the coach's next reply.

    ``history`` is the running conversation in Gradio ``messages`` format
    (``{"role": ..., "content": ...}`` dicts, user/assistant only). The system
    prompt is prepended on every call so the coach behavior is enforced each
    turn.
    """
    messages = [{"role": "system", "content": system_prompt}, *history]
    return chat_once(base_url, messages)


_INTRO_MARKDOWN = """
# Coach vocal francais -- demo

Ecrivez en francais (avec ou sans fautes). Le coach :

- repond **uniquement en francais**, meme si vous changez de langue ;
- corrige au format fixe en 4 temps : il **repete** votre phrase, donne la
  **version corrigee**, **explique** en une phrase, puis vous demande de
  **repeter** ;
- relance toujours par une question (style oral, 2-3 phrases).

**Mode simulation soutenance** : ecrivez `simulation soutenance` et le coach
joue Charlotte, votre manager, qui pose des questions de conduite de projet.
Ecrivez `fin de la simulation` pour revenir au mode coach.
"""


def _baseline_markdown() -> str:
    """Render the pre-fine-tuning baseline metrics as a Markdown panel."""
    lines = [
        "### Baseline (prompt seul, avant fine-tuning)",
        "",
        f"Source : run `{_BASELINE_RUN_ID}` de la harness d'evaluation.",
        "",
        "| Metrique | Valeur |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in _BASELINE_METRICS)
    lines.append("")
    lines.append(
        "Ces chiffres mesurent le meme modele avec ce prompt seul. Le "
        "fine-tuning (SFT/DPO) vise a les ameliorer."
    )
    lines.append("")
    lines.append(
        "_Note : D1 est ici le pre-check deterministe (presence du format "
        "4-parties + brievete). L'ordre des parties et la regle « une seule "
        "phrase d'explication » sont verifies par le juge LLM, en attente "
        "(eval_set_v0 section 5)._"
    )
    return "\n".join(lines)


def build_demo(base_url: Optional[str] = None) -> gr.Blocks:
    """Construct the Gradio Blocks app.

    ``base_url`` defaults to the environment-resolved Ollama address. The
    system prompt is loaded once at build time.
    """
    resolved_url = base_url or resolve_ollama_base_url()
    system_prompt = load_system_prompt()

    def respond(
        user_message: str,
        history: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, str]]]:
        """Append the learner turn, query the coach, append the reply."""
        text = user_message.strip()
        if not text:
            return "", history
        conversation = [*history, {"role": "user", "content": text}]
        try:
            reply = coach_reply(resolved_url, system_prompt, conversation)
        except OllamaChatError:
            reply = _BACKEND_ERROR_REPLY
        conversation.append({"role": "assistant", "content": reply})
        return "", conversation

    with gr.Blocks(title="Coach vocal francais -- demo") as demo:
        gr.Markdown(_INTRO_MARKDOWN)
        with gr.Row():
            with gr.Column(scale=3):
                # Gradio 6 uses the OpenAI-style message-dict format for
                # Chatbot exclusively (the legacy tuple format and its ``type``
                # switch were removed), so history is a list of
                # ``{"role", "content"}`` dicts that maps directly onto the
                # Ollama chat payload.
                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=460,
                )
                user_box = gr.Textbox(
                    placeholder="Ecrivez en francais...",
                    label="Votre message",
                    submit_btn=True,
                )
                clear_btn = gr.Button("Effacer la conversation")
            with gr.Column(scale=1):
                gr.Markdown(_baseline_markdown())

        user_box.submit(respond, [user_box, chatbot], [user_box, chatbot])
        clear_btn.click(lambda: [], None, chatbot)

    return demo


def main() -> None:
    """Launch the demo on the local server."""
    demo = build_demo()
    demo.launch(server_name=_DEMO_SERVER_NAME, server_port=_DEMO_SERVER_PORT)


if __name__ == "__main__":
    main()
