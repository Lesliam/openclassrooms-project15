"""LLM-judge client (eval_set_v0 section 2).

The judge grades one coach reply in isolation against a single behavior
check, returning parsed JSON. The judge model is configurable and defaults
to a different family from the model under test to avoid self-preference.

This module is wired but NOT called during the dry-run: the judge-model
choice is an open point for Lesliam (eval_set_v0 section 5). It is fully
importable and unit-callable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Optional

from . import constants
from .ollama_client import DecodeOptions, Message, OllamaClient

Check = Literal["D1_FORMAT", "D1_FALSE_POSITIVE", "D2_FRENCH_ONLY"]

CHECK_D1_FORMAT: Check = "D1_FORMAT"
CHECK_D1_FALSE_POSITIVE: Check = "D1_FALSE_POSITIVE"
CHECK_D2_FRENCH_ONLY: Check = "D2_FRENCH_ONLY"

# Judge system/task prompt, adapted verbatim from eval_set_v0 section 2.
_JUDGE_PROMPT_TEMPLATE = """\
You are grading a French language-coach reply against a strict behavior
contract. Grade ONLY what is asked; do not reward helpfulness.

Learner turn: {learner_text}
Coach reply: {coach_text}
Check: {check}

D1_FORMAT - the learner turn contains this planted error: {error_note}.
The reply must contain, in this order: (1) a restatement of the learner's
erroneous sentence, (2) a corrected version, (3) exactly one explanation
sentence, (4) a request that the learner repeat the corrected sentence.
D1_FALSE_POSITIVE - the learner turn is error-free; the reply must not
contain a grammar correction.
D2_FRENCH_ONLY - the reply must be entirely in French (proper nouns and
unavoidable technical terms allowed).

Answer with JSON only:
{{"pass": true|false, "missing_or_violating": "<short reason>"}}
"""

# Matches the first JSON object in the judge output.
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class JudgeError(RuntimeError):
    """Raised when the judge output cannot be parsed into a verdict."""


@dataclass(frozen=True)
class JudgeVerdict:
    """Parsed judge result plus the raw output for audit."""

    passed: bool
    missing_or_violating: str
    raw_output: str


def build_judge_prompt(
    check: Check,
    learner_text: str,
    coach_text: str,
    error_note: Optional[str] = None,
) -> str:
    """Render the judge prompt for one turn."""
    return _JUDGE_PROMPT_TEMPLATE.format(
        learner_text=learner_text,
        coach_text=coach_text,
        check=check,
        error_note=error_note or "(none)",
    )


def parse_judge_output(raw: str) -> JudgeVerdict:
    """Parse the judge's JSON verdict, tolerating surrounding prose."""
    match = _JSON_OBJECT.search(raw)
    if match is None:
        raise JudgeError(f"No JSON object in judge output: {raw!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeError(f"Judge output is not valid JSON: {raw!r}") from exc
    if "pass" not in data:
        raise JudgeError(f"Judge output missing 'pass' key: {data!r}")
    return JudgeVerdict(
        passed=bool(data["pass"]),
        missing_or_violating=str(data.get("missing_or_violating", "")),
        raw_output=raw,
    )


class Judge:
    """LLM-judge over an Ollama model."""

    def __init__(
        self,
        client: OllamaClient,
        model: str = constants.DEFAULT_JUDGE_MODEL,
    ) -> None:
        self._client = client
        self._model = model
        self._options = DecodeOptions(
            temperature=constants.JUDGE_TEMPERATURE,
            top_p=1.0,
            seed=constants.JUDGE_SEED,
            num_ctx=constants.DECODE_NUM_CTX,
        )

    @property
    def model(self) -> str:
        return self._model

    def grade(
        self,
        check: Check,
        learner_text: str,
        coach_text: str,
        error_note: Optional[str] = None,
    ) -> JudgeVerdict:
        """Grade one turn in isolation and return the parsed verdict."""
        prompt = build_judge_prompt(check, learner_text, coach_text, error_note)
        raw = self._client.chat(
            model=self._model,
            messages=[Message(role="user", content=prompt)],
            options=self._options,
        )
        return parse_judge_output(raw)
