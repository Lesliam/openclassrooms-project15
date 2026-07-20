"""Dimension D4: closing-cue / relance-exception compliance (v1 vs v2).

This is a focused mini-eval for CS-156, separate from the frozen eval harness
(`eval_set_v0.md` already uses D3 for long-context drift, so this dimension is
named D4). It measures whether the coach:

- closes warmly with NO forced question on a genuine closing cue (CLOTURE),
- answers a real need WITHOUT ending the session (SOUPLE), and
- still relance by default on ordinary practice turns (DEFAUT).

The deterministic detectors (``reply_ends_with_question``, ``is_warm_close``,
``classify_reply``) are CPU-only and Ollama-free, so the unit tests under
``tests/test_closing_cue_scorer.py`` pass offline. ``main`` runs the model live:
for each dialogue it calls ``qwen2.5:14b`` once with the v1 prompt and once with
the v2 prompt (Ollama host resolved from the environment, mirroring
``harness.constants``), classifies each reply, and prints a v1-vs-v2 table. If
Ollama is unreachable it degrades gracefully: it writes deterministic-only
results (labels, no replies) and exits cleanly.

Usage::

    OLLAMA_HOST=<host[:port]> \\
        ml/eval/.venv/bin/python ml/eval/run_closing_cue_compare.py
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import constants
from harness.ollama_client import DecodeOptions, Message, OllamaClient, OllamaError
from harness.scorers import count_sentences

# --- Labels and classification outcomes ------------------------------------

LABEL_CLOTURE = "CLOTURE"
LABEL_SOUPLE = "SOUPLE"
LABEL_DEFAUT = "DEFAUT"

CLASS_CLOSED = "closed"
CLASS_SOFT = "soft"
CLASS_QUESTION = "question"

# A warm close stays short; a genuine goodbye does not run past a few spoken
# sentences (the system prompt caps normal turns at 2-3, corrections at 4).
WARM_CLOSE_MAX_SENTENCES = 3

# D4 uses greedy decoding (temperature 0) so the v1-vs-v2 comparison is
# reproducible from a single run; the frozen harness samples (temperature 0.7)
# because it is exploratory and averages over repetitions, which this focused
# behavioural comparison does not.
D4_TEMPERATURE = 0.0

# Prompt files (deployment artifacts) live under project/server. v0 is frozen
# and is NOT used here; D4 compares the two deployment prompts v1 and v2.
V1_PROMPT_FILE = constants.SERVER_DIR / "coach_system_prompt_v1.md"
V2_PROMPT_FILE = constants.SERVER_DIR / "coach_system_prompt_v2.md"

# Trailing characters stripped before the terminal "?" test (closing quotes,
# guillemets, brackets, whitespace) so a question inside guillemets still reads
# as a terminal question.
_TRAILING_STRIP = " \t\r\n»\"')]"

# Explicit farewell cues that mark a reply as a close. Vowel classes cover
# accent variants a model may emit (e.g. "a demain" / "à demain").
_CLOSE_MARKER = re.compile(
    r"au revoir"
    r"|[àa] demain"
    r"|[àa] bient[oô]t"
    r"|[àa] la prochaine"
    r"|[àa] plus"
    r"|[àa] tout[e]? [àa] l'heure"
    r"|bonne nuit"
    r"|bonne soir[ée]e"
    r"|bonne journ[ée]e"
    r"|bonne continuation"
    r"|repose-toi"
    r"|reposez-vous"
    r"|prends soin de toi",
    re.IGNORECASE,
)

# The 4-part correction drill's final step ("répète la phrase corrigée"). Its
# presence means the reply dragged the learner into an exercise, so it is NOT a
# warm close even if a farewell cue is present.
_REPEAT_DRILL = re.compile(r"r[ée]p[ée]t\w*[^.?!]{0,40}phrase", re.IGNORECASE)


# --- Deterministic detectors (CPU-only, no Ollama) --------------------------
#
# The detectors are deliberately conservative: `is_warm_close` REQUIRES an
# explicit farewell cue, and `reply_ends_with_question` makes a terminal "?"
# always count as a question (it wins over any farewell cue). The bias is one
# directional: a genuine close phrased without a recognised cue is scored as
# `soft`, not `closed`. So the detectors can only UNDER-credit closer-recall,
# never inflate the premature-close rate (the headline safety number).


def reply_ends_with_question(text: str) -> bool:
    """True if the reply's final sentence ends with a question mark.

    Trailing closing quotes, guillemets, brackets and whitespace are removed
    first so a question wrapped in guillemets still counts as terminal.
    """
    stripped = text.rstrip(_TRAILING_STRIP)
    return stripped.endswith("?")


def has_close_marker(text: str) -> bool:
    """True if the reply carries an explicit farewell cue."""
    return _CLOSE_MARKER.search(text) is not None


def has_repeat_drill(text: str) -> bool:
    """True if the reply contains the 4-part correction 'repeat the phrase' step."""
    return _REPEAT_DRILL.search(text) is not None


def is_warm_close(text: str) -> bool:
    """True if the reply is a short, question-free warm goodbye.

    A warm close is: no trailing question, no 'répète la phrase' drill, an
    explicit farewell cue, and at most ``WARM_CLOSE_MAX_SENTENCES`` sentences.
    The farewell-cue requirement is what separates a genuine close from an
    ordinary short reply that merely happens to omit a question.
    """
    if reply_ends_with_question(text):
        return False
    if has_repeat_drill(text):
        return False
    if not has_close_marker(text):
        return False
    return count_sentences(text) <= WARM_CLOSE_MAX_SENTENCES


def classify_reply(text: str) -> str:
    """Map a reply to one of ``{closed, soft, question}``.

    Order matters: a reply that ends with a question is ``question`` even if it
    also carries a farewell cue (it did not actually close); otherwise a warm
    close is ``closed``; everything else is ``soft`` (answered but stayed open).
    """
    if reply_ends_with_question(text):
        return CLASS_QUESTION
    if is_warm_close(text):
        return CLASS_CLOSED
    return CLASS_SOFT


def is_correct(label: str, classification: str) -> bool:
    """Whether a classification satisfies the item's expected behaviour."""
    if label == LABEL_CLOTURE:
        return classification == CLASS_CLOSED
    if label == LABEL_SOUPLE:
        return classification != CLASS_CLOSED
    return classification == CLASS_QUESTION  # DEFAUT


# --- Labelled dialogues (mirror closing_cue_set_v1.md verbatim) -------------


@dataclass(frozen=True)
class Dialogue:
    """One single-turn labelled dialogue."""

    dialogue_id: str
    label: str
    learner_text: str


DIALOGUES: tuple[Dialogue, ...] = (
    # CLOTURE — must close, no question.
    Dialogue("C1", LABEL_CLOTURE, "Au revoir."),
    Dialogue("C2", LABEL_CLOTURE, "Bonne nuit."),
    Dialogue("C3", LABEL_CLOTURE, "Je suis fatiguée, je dois y aller."),
    Dialogue("C4", LABEL_CLOTURE, "Merci, à demain."),
    Dialogue("C5", LABEL_CLOTURE, "On s'arrête là pour aujourd'hui."),
    Dialogue("C6", LABEL_CLOTURE, "On continue demain, bonne soirée."),
    Dialogue("C7", LABEL_CLOTURE, "C'est bon j'arrête, merci beaucoup."),
    # SOUPLE — must respond, must NOT close.
    Dialogue("S1", LABEL_SOUPLE, 'Comment on dit "thank you" en français ?'),
    Dialogue(
        "S2",
        LABEL_SOUPLE,
        'C\'est quoi la différence entre "savoir" et "connaître" ?',
    ),
    Dialogue("S3", LABEL_SOUPLE, "Parle plus lentement, s'il te plaît."),
    Dialogue("S4", LABEL_SOUPLE, "Répète, je n'ai pas bien compris."),
    Dialogue("S5", LABEL_SOUPLE, "C'est trop dur, je n'y arrive pas."),
    Dialogue("S6", LABEL_SOUPLE, "Je suis découragée, j'en ai marre."),
    Dialogue("S7", LABEL_SOUPLE, "Merci beaucoup !"),
    # DEFAUT — must end with a question.
    Dialogue(
        "D1",
        LABEL_DEFAUT,
        "Bonjour, je m'appelle Marie et je prépare ma soutenance.",
    ),
    Dialogue("D2", LABEL_DEFAUT, "Je pense que mon projet est vraiment intéressant."),
    Dialogue("D3", LABEL_DEFAUT, "Je dois réfléchir à ma réponse."),
    Dialogue(
        "D4",
        LABEL_DEFAUT,
        "Hier, je suis allée au marché et j'ai acheté des légumes.",
    ),
    Dialogue(
        "D5",
        LABEL_DEFAUT,
        "Mon projet parle d'un assistant vocal pour apprendre le français.",
    ),
    Dialogue("D6", LABEL_DEFAUT, "Je travaille sur mon portfolio depuis deux semaines."),
    Dialogue(
        "D7",
        LABEL_DEFAUT,
        "Je suis fatiguée aujourd'hui, j'ai mal dormi mais je veux continuer.",
    ),
)


# --- Metrics ----------------------------------------------------------------


@dataclass(frozen=True)
class ArmMetrics:
    """Aggregate D4 metrics for one prompt arm."""

    n_items: int
    n_scored: int
    accuracy: float
    closer_recall: float
    premature_close_rate: float
    per_label_accuracy: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Return numerator/denominator, or 0.0 when the denominator is zero."""
    return numerator / denominator if denominator else 0.0


def compute_metrics(records: list[dict]) -> ArmMetrics:
    """Aggregate per-item classification records into D4 metrics.

    Only records that carry a ``classification`` (i.e. a live reply was
    scored) count toward the metrics; records without one (Ollama unreachable)
    are ignored so partial runs still produce honest numbers.

    - closer-recall = closed CLOTURE turns / all scored CLOTURE turns.
    - premature-close rate = wrongly-closed non-CLOTURE turns / all scored
      non-CLOTURE turns (the headline risk number).
    """
    scored = [r for r in records if r.get("classification") is not None]
    correct = sum(1 for r in scored if r["correct"])

    cloture = [r for r in scored if r["label"] == LABEL_CLOTURE]
    non_cloture = [r for r in scored if r["label"] != LABEL_CLOTURE]
    closed_cloture = sum(1 for r in cloture if r["classification"] == CLASS_CLOSED)
    closed_non_cloture = sum(
        1 for r in non_cloture if r["classification"] == CLASS_CLOSED
    )

    per_label: dict[str, float] = {}
    for label in (LABEL_CLOTURE, LABEL_SOUPLE, LABEL_DEFAUT):
        subset = [r for r in scored if r["label"] == label]
        per_label[label] = _safe_ratio(
            sum(1 for r in subset if r["correct"]), len(subset)
        )

    return ArmMetrics(
        n_items=len(records),
        n_scored=len(scored),
        accuracy=_safe_ratio(correct, len(scored)),
        closer_recall=_safe_ratio(closed_cloture, len(cloture)),
        premature_close_rate=_safe_ratio(closed_non_cloture, len(non_cloture)),
        per_label_accuracy=per_label,
    )


# --- Prompt loading ---------------------------------------------------------


def load_prompt_body(path: Path) -> str:
    """Return the literal system-prompt body (text after the separator)."""
    raw = path.read_text(encoding="utf-8")
    if constants.PROMPT_BODY_SEPARATOR in raw:
        body = raw.split(constants.PROMPT_BODY_SEPARATOR, 1)[1]
    else:
        body = raw
    return body.strip()


# --- Live comparison --------------------------------------------------------


def _score_arm(
    client: OllamaClient,
    system_prompt: str,
    decode: DecodeOptions,
    model: str,
) -> list[dict]:
    """Run every dialogue through one prompt arm and score each reply.

    Each per-item record always carries the dialogue id, label and learner
    text. On success it also carries the reply and its classification; on an
    Ollama failure it carries ``error`` and a null classification so the run
    stays partial rather than aborting.
    """
    records: list[dict] = []
    for dialogue in DIALOGUES:
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=dialogue.learner_text),
        ]
        record: dict = {
            "id": dialogue.dialogue_id,
            "label": dialogue.label,
            "learner_text": dialogue.learner_text,
            "reply": None,
            "classification": None,
            "correct": False,
            "error": None,
        }
        try:
            reply = client.chat(model, messages, decode)
        except OllamaError as exc:
            record["error"] = str(exc)
        else:
            classification = classify_reply(reply)
            record["reply"] = reply
            record["classification"] = classification
            record["correct"] = is_correct(dialogue.label, classification)
        records.append(record)
    return records


def _print_comparison(v1_records: list[dict], v2_records: list[dict]) -> None:
    """Print a per-dialogue v1-vs-v2 classification table."""
    by_id_v2 = {r["id"]: r for r in v2_records}
    header = f"{'id':<4} {'label':<8} {'v1':<9} {'v2':<9} learner"
    print(header)
    print("-" * len(header))
    for v1_record in v1_records:
        v2_record = by_id_v2[v1_record["id"]]
        v1_class = v1_record["classification"] or "n/a"
        v2_class = v2_record["classification"] or "n/a"
        v1_mark = "" if v1_record["classification"] is None else (
            "ok" if v1_record["correct"] else "X"
        )
        v2_mark = "" if v2_record["classification"] is None else (
            "ok" if v2_record["correct"] else "X"
        )
        print(
            f"{v1_record['id']:<4} {v1_record['label']:<8} "
            f"{v1_class + ' ' + v1_mark:<9} {v2_class + ' ' + v2_mark:<9} "
            f"{v1_record['learner_text']}"
        )


def _print_metrics(name: str, metrics: ArmMetrics) -> None:
    """Print the headline D4 metrics for one arm."""
    print(f"\n[{name}] scored {metrics.n_scored}/{metrics.n_items} items")
    print(f"  accuracy              : {metrics.accuracy:.3f}")
    print(f"  closer-recall         : {metrics.closer_recall:.3f}")
    print(f"  premature-close rate  : {metrics.premature_close_rate:.3f}")
    for label, acc in metrics.per_label_accuracy.items():
        print(f"  {label:<8} accuracy    : {acc:.3f}")


def _write_results(
    out_dir: Path,
    v1_records: list[dict],
    v2_records: list[dict],
    v1_metrics: ArmMetrics,
    v2_metrics: ArmMetrics,
    ollama_reachable: bool,
) -> Path:
    """Persist records + metrics as JSON; return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "dimension": "D4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ollama_reachable": ollama_reachable,
        "model": constants.MODEL_UNDER_TEST,
        "arms": {
            "v1": {"records": v1_records, "metrics": v1_metrics.to_dict()},
            "v2": {"records": v2_records, "metrics": v2_metrics.to_dict()},
        },
    }
    out_file = out_dir / "results.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return out_file


def _empty_records() -> list[dict]:
    """Records with null classifications (used when Ollama is unreachable)."""
    return [
        {
            "id": d.dialogue_id,
            "label": d.label,
            "learner_text": d.learner_text,
            "reply": None,
            "classification": None,
            "correct": False,
            "error": "ollama-unreachable",
        }
        for d in DIALOGUES
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=constants.RUNS_DIR,
        help="Directory under which the closing-cue run folder is written.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=constants.MODEL_UNDER_TEST,
        help="Ollama model tag to compare both prompts on.",
    )
    args = parser.parse_args()

    out_dir = args.out_root / "closing-cue-d4"
    # Greedy decoding (D4_TEMPERATURE=0) for a deterministic, reproducible
    # v1-vs-v2 comparison; top_p/seed/num_ctx follow the harness convention.
    decode = DecodeOptions(
        temperature=D4_TEMPERATURE,
        top_p=constants.DECODE_TOP_P,
        seed=constants.DECODE_SEED_BASE,
        num_ctx=constants.DECODE_NUM_CTX,
    )
    client = OllamaClient()

    # Health check first: if Ollama is unreachable, degrade to a
    # deterministic-only artifact and exit cleanly (0) so CI/unit flows pass.
    ollama_reachable = True
    try:
        client.list_models()
    except OllamaError as exc:
        ollama_reachable = False
        print(f"[warn] Ollama unreachable ({exc}); writing deterministic-only results.")

    if not ollama_reachable:
        v1_records = _empty_records()
        v2_records = _empty_records()
    else:
        v1_prompt = load_prompt_body(V1_PROMPT_FILE)
        v2_prompt = load_prompt_body(V2_PROMPT_FILE)
        print(f"[d4] scoring v1 arm ({len(DIALOGUES)} dialogues)...", flush=True)
        v1_records = _score_arm(client, v1_prompt, decode, args.model)
        print(f"[d4] scoring v2 arm ({len(DIALOGUES)} dialogues)...", flush=True)
        v2_records = _score_arm(client, v2_prompt, decode, args.model)

    v1_metrics = compute_metrics(v1_records)
    v2_metrics = compute_metrics(v2_records)

    _print_comparison(v1_records, v2_records)
    _print_metrics("v1", v1_metrics)
    _print_metrics("v2", v2_metrics)

    out_file = _write_results(
        out_dir, v1_records, v2_records, v1_metrics, v2_metrics, ollama_reachable
    )
    print(f"\n[d4] results written to {out_file}")


if __name__ == "__main__":
    main()
