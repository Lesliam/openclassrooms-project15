"""Run orchestration: drive the baseline arm over the dialogue set.

For each dialogue and repetition, this builds an accumulating message list
(system prompt + alternating user/assistant), calls Ollama, applies the
deterministic scorers and writes raw transcripts plus a flat per-turn score
record. Drift dialogues score the same probe at shallow and deep depth.

The judge is wired in ``judge.py`` but this runner does not call it by
default (dry-run keeps judge disabled per eval_set_v0 section 5).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from . import constants, scorers
from .config import RunConfig, load_system_prompt
from .dialogues import (
    ALL_DIALOGUES,
    FILLER_SCRIPT,
    KIND_DRIFT,
    KIND_MULTI,
    KIND_SIMPLE,
    Dialogue,
    Expectation,
    LearnerTurn,
)
from .ollama_client import DecodeOptions, Message, OllamaClient

DEPTH_SHALLOW = "shallow"
DEPTH_DEEP = "deep"

ProgressCallback = Callable[[str], None]


@dataclass
class TurnResult:
    """Scored record for one coach reply."""

    dialogue_id: int
    item_id: int
    group: str
    kind: str
    turn_index: int
    depth: Optional[str]
    repetition: int
    seed: int
    learner_text: str
    coach_reply: str
    expect: dict
    d1: dict
    d2: dict
    sentence_count: int
    d1_required: bool
    d1_pass: Optional[bool]
    false_positive_check: bool
    false_positive_triggered: Optional[bool]
    french_only_required: bool
    d2_pass: Optional[bool]
    brevity_max: int
    brevity_pass: bool


def _decode_for_repetition(base: DecodeOptions, repetition: int) -> DecodeOptions:
    """Per-repetition seed = base seed + repetition index (reproducible variance)."""
    return DecodeOptions(
        temperature=base.temperature,
        top_p=base.top_p,
        seed=base.seed + repetition,
        num_ctx=base.num_ctx,
    )


def _score_reply(
    *,
    dialogue: Dialogue,
    item_id: int,
    turn_index: int,
    depth: Optional[str],
    repetition: int,
    seed: int,
    learner_text: str,
    expect: Expectation,
    reply: str,
) -> TurnResult:
    d1 = scorers.score_d1(reply, learner_text, expect.brevity_max)
    d2 = scorers.score_d2(reply)
    sentence_count = d1.sentence_count

    d1_pass = d1.deterministic_compliant if expect.correction_required else None
    false_positive_triggered = (
        scorers.d1_correction_emitted(reply, learner_text)
        if expect.false_positive_check
        else None
    )
    d2_pass = d2.passes if expect.french_only_required else None
    brevity_pass = sentence_count <= expect.brevity_max

    return TurnResult(
        dialogue_id=dialogue.id,
        item_id=item_id,
        group=dialogue.group,
        kind=dialogue.kind,
        turn_index=turn_index,
        depth=depth,
        repetition=repetition,
        seed=seed,
        learner_text=learner_text,
        coach_reply=reply,
        expect=asdict(expect),
        d1=d1.to_dict(),
        d2=d2.to_dict(),
        sentence_count=sentence_count,
        d1_required=expect.correction_required,
        d1_pass=d1_pass,
        false_positive_check=expect.false_positive_check,
        false_positive_triggered=false_positive_triggered,
        french_only_required=expect.french_only_required,
        d2_pass=d2_pass,
        brevity_max=expect.brevity_max,
        brevity_pass=brevity_pass,
    )


class BaselineRunner:
    """Runs the baseline arm (system prompt + model under test)."""

    def __init__(
        self,
        client: OllamaClient,
        config: RunConfig,
        base_decode: DecodeOptions,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        self._client = client
        self._config = config
        self._base_decode = base_decode
        self._system_prompt = load_system_prompt()
        self._progress = progress or (lambda _msg: None)

    def _chat(self, messages: list[Message], decode: DecodeOptions) -> str:
        return self._client.chat(
            model=self._config.model_under_test,
            messages=messages,
            options=decode,
        )

    def _system_message(self) -> Message:
        return Message(role="system", content=self._system_prompt)

    def _run_sequential(
        self, dialogue: Dialogue, repetition: int, decode: DecodeOptions
    ) -> list[TurnResult]:
        """Simple/multi dialogues: send turns in one accumulating conversation."""
        messages: list[Message] = [self._system_message()]
        results: list[TurnResult] = []
        for turn_index, turn in enumerate(dialogue.turns):
            messages.append(Message(role="user", content=turn.text))
            reply = self._chat(messages, decode)
            messages.append(Message(role="assistant", content=reply))
            results.append(
                _score_reply(
                    dialogue=dialogue,
                    item_id=turn.item_id,
                    turn_index=turn_index,
                    depth=None,
                    repetition=repetition,
                    seed=decode.seed,
                    learner_text=turn.text,
                    expect=turn.expect,
                    reply=reply,
                )
            )
        return results

    def _run_drift(
        self, dialogue: Dialogue, repetition: int, decode: DecodeOptions
    ) -> list[TurnResult]:
        """Drift dialogues: probe at shallow depth, pad filler, probe at deep depth."""
        assert dialogue.probe is not None
        probe = dialogue.probe
        depth = self._config.drift_depth
        shallow_n = self._config.shallow_filler_count

        messages: list[Message] = [self._system_message()]
        results: list[TurnResult] = []

        # Warm-up filler -> shallow probe.
        self._inject_filler(messages, FILLER_SCRIPT[:shallow_n], decode)
        results.append(
            self._probe(dialogue, probe, DEPTH_SHALLOW, repetition, decode, messages)
        )

        # Remaining filler up to the requested depth -> deep probe.
        self._inject_filler(messages, FILLER_SCRIPT[shallow_n:depth], decode)
        results.append(
            self._probe(dialogue, probe, DEPTH_DEEP, repetition, decode, messages)
        )
        return results

    def _inject_filler(
        self, messages: list[Message], filler: tuple[str, ...], decode: DecodeOptions
    ) -> None:
        for line in filler:
            messages.append(Message(role="user", content=line))
            reply = self._chat(messages, decode)
            messages.append(Message(role="assistant", content=reply))

    def _probe(
        self,
        dialogue: Dialogue,
        probe: LearnerTurn,
        depth: str,
        repetition: int,
        decode: DecodeOptions,
        messages: list[Message],
    ) -> TurnResult:
        messages.append(Message(role="user", content=probe.text))
        reply = self._chat(messages, decode)
        messages.append(Message(role="assistant", content=reply))
        return _score_reply(
            dialogue=dialogue,
            item_id=probe.item_id,
            turn_index=0,
            depth=depth,
            repetition=repetition,
            seed=decode.seed,
            learner_text=probe.text,
            expect=probe.expect,
            reply=reply,
        )

    def run_dialogue(self, dialogue: Dialogue) -> list[TurnResult]:
        """Run all repetitions of one dialogue."""
        results: list[TurnResult] = []
        for repetition in range(self._config.repetitions):
            decode = _decode_for_repetition(self._base_decode, repetition)
            self._progress(
                f"dialogue {dialogue.id} ({dialogue.group}/{dialogue.kind}) "
                f"rep {repetition + 1}/{self._config.repetitions}"
            )
            if dialogue.kind in (KIND_SIMPLE, KIND_MULTI):
                results.extend(self._run_sequential(dialogue, repetition, decode))
            elif dialogue.kind == KIND_DRIFT:
                results.extend(self._run_drift(dialogue, repetition, decode))
            else:  # pragma: no cover - guarded by dialogue data
                raise ValueError(f"unknown dialogue kind: {dialogue.kind}")
        return results


def available_filler_depth() -> int:
    """Number of filler turns available for the deep drift probe."""
    return len(FILLER_SCRIPT)


def ensure_drift_depth_available(drift_depth: int) -> None:
    """Raise if the requested drift depth exceeds the available filler.

    Prevents a silently-truncated deep probe (fix S4): an over-large
    ``--drift-depth`` would otherwise slice past the end of FILLER_SCRIPT and
    quietly land the deep probe shallower than requested.
    """
    available = available_filler_depth()
    if drift_depth > available:
        raise ValueError(
            f"drift_depth {drift_depth} exceeds available filler turns "
            f"({available}); add more FILLER_SCRIPT lines or lower --drift-depth"
        )


def _write_scores(path: Path, results: list[TurnResult]) -> None:
    path.write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run_all(
    client: OllamaClient,
    config: RunConfig,
    base_decode: DecodeOptions,
    output_dir: Path,
    dialogues: tuple[Dialogue, ...] = ALL_DIALOGUES,
    progress: Optional[ProgressCallback] = None,
) -> list[TurnResult]:
    """Run every dialogue, persist config + transcripts + scores, return results.

    Scores are snapshotted to ``scores.partial.json`` after each dialogue so a
    mid-run failure (a full run is hours) stays recoverable; on full success
    the complete ``scores.json`` is written and the partial snapshot removed.
    """
    ensure_drift_depth_available(config.drift_depth)

    output_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir = output_dir / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)

    (output_dir / "config.json").write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    runner = BaselineRunner(client, config, base_decode, progress)
    partial_path = output_dir / "scores.partial.json"
    all_results: list[TurnResult] = []
    for dialogue in dialogues:
        results = runner.run_dialogue(dialogue)
        all_results.extend(results)
        (transcripts_dir / f"dialogue_{dialogue.id:02d}.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # Incremental snapshot: leaves a recoverable file if a later dialogue
        # fails before the run completes.
        _write_scores(partial_path, all_results)

    _write_scores(output_dir / "scores.json", all_results)
    partial_path.unlink(missing_ok=True)
    return all_results
