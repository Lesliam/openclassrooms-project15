"""Coach FR prompt-baseline evaluation harness.

Implements the evaluation design in ``ml/eval/eval_set_v0.md``: the fixed
20-dialogue set, deterministic scorers (D1 correction format, D2 French
persistence, brevity), an LLM-judge client, a run orchestrator and a
Markdown report aggregator.

The package is import-safe: importing it performs no network calls and no
filesystem writes.
"""

__all__ = [
    "constants",
    "ollama_client",
    "dialogues",
    "scorers",
    "judge",
    "runner",
    "report",
]
