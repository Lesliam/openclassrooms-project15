"""Dimension D5: disfluency tolerance / incomplete-turn handling (v2 vs v3).

This is a focused mini-eval for CS-157, separate from the frozen eval harness.
`eval_set_v0.md` uses D1-D3 and the CS-156 mini-eval added D4, so this new
dimension is named D5. It measures whether the coach, on spontaneous spoken
French:

- ignores a disfluency (word/segment repetition, filler ``euh``/``hmm``, false
  start, or an already-self-corrected form) and does NOT emit a correction,
- gently invites the learner to continue on a cut-off / unfinished turn, and
- still corrects a GENUINE error hidden inside disfluent speech, while leaving
  an ordinary clean turn uncorrected (v2 over-correction guard preserved).

The deterministic detectors (``correction_emitted``, ``invites_to_continue``,
``classify_reply``) are CPU-only and Ollama-free, so the unit tests under
``tests/test_disfluency_scorer.py`` pass offline. ``main`` runs the model live:
for each dialogue it calls ``qwen2.5:14b`` once with the v2 prompt and once with
the v3 prompt (Ollama host resolved from the environment, mirroring
``harness.constants``), classifies each reply, and prints a v2-vs-v3 table. If
Ollama is unreachable it degrades gracefully: it writes deterministic-only
results (labels, no replies) and exits cleanly.

Usage::

    OLLAMA_HOST=<host[:port]> \\
        ml/eval/.venv/bin/python ml/eval/run_disfluency_compare.py
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
from harness.scorers import d1_correction_emitted, score_d1

# --- Labels and classification outcomes ------------------------------------

LABEL_DISFLUENCY = "DISFLUENCY"
LABEL_INCOMPLETE = "INCOMPLETE"
LABEL_REALERROR = "REALERROR"
LABEL_CLEAN = "CLEAN"

CLASS_CORRECTED = "corrected"
CLASS_INVITED = "invited"
CLASS_ENGAGED = "engaged"

# D5 uses greedy decoding (temperature 0) so the v2-vs-v3 comparison is
# reproducible from a single run; the frozen harness samples (temperature 0.7)
# because it is exploratory and averages over repetitions, which this focused
# behavioural comparison does not. Mirrors the D4 scorer's D4_TEMPERATURE.
D5_TEMPERATURE = 0.0

# Correction brevity cap (sentences) used by the 4-part-format check. Reuses the
# system-prompt / eval_set_v0 cap for a turn that emits a correction.
CORRECTION_BREVITY_MAX = constants.BREVITY_MAX_SENTENCES_CORRECTING

# Prompt files (deployment artifacts) live under project/server. v0/v1 are prior
# artifacts and are NOT used here; D5 compares the two most recent deployment
# prompts v2 (baseline) and v3 (disfluency + incomplete-turn additions).
V2_PROMPT_FILE = constants.SERVER_DIR / "coach_system_prompt_v2.md"
V3_PROMPT_FILE = constants.SERVER_DIR / "coach_system_prompt_v3.md"

# Filler tokens that mark thinking-aloud rather than content (used to tell a
# disfluency-targeted correction from a real-error correction).
_FILLER_TOKENS = frozenset({"euh", "euhh", "heu", "hmm", "hum", "mmh", "ben"})

# Local word / quoted-span extractors for the disfluency-target quality signal.
# Kept local (rather than importing the harness's private helpers) so this
# module depends only on the harness's public correction API.
_WORD = re.compile(r"[0-9A-Za-zÀ-ÿ]+")
_QUOTED_SPAN = re.compile("[«\"]([^«»\"]+)[»\"]")


def _tokens(text: str) -> list[str]:
    """Lowercased word tokens (letters incl. accents and digits)."""
    return _WORD.findall(text.lower())


def _quoted_spans(text: str) -> list[str]:
    """Spans quoted in guillemets or straight double quotes."""
    return [m.group(1).strip() for m in _QUOTED_SPAN.finditer(text)]

# Invitation-to-continue markers: phrasings the coach uses to ask the learner to
# keep going on a cut-off turn. Vowel classes cover accent variants a model may
# emit. Deliberately targeted so an ordinary Socratic relance question does not
# register as an invite; it stays permissive on genuine continue-invitations
# because only the INCOMPLETE label's correctness depends on this signal.
_INVITE_MARKER = re.compile(
    r"prends? (?:ton|le) temps"
    r"|prenez votre temps"
    r"|je t'?[ée]coute"
    r"|je vous [ée]coute"
    r"|(?:tu veux|veux-tu|tu peux|voudrais|[àa]|de)\s+continuer"
    r"|continuer\s*\?"
    r"|vas-y"
    r"|poursuis"
    r"|poursuivre"
    r"|poursuivez"
    r"|termine (?:ta phrase|ton|ta pens[ée]e)"
    r"|finis (?:ta phrase|ton)"
    r"|dis-moi (?:la suite|en plus)"
    r"|dis-m'en plus"
    r"|la suite\s*\?"
    r"|(?:tu peux|peux-tu) (?:pr[ée]ciser|d[ée]velopper|terminer)"
    r"|qu'est-ce que tu voulais dire",
    re.IGNORECASE,
)


# --- Deterministic detectors (CPU-only, no Ollama) --------------------------
#
# The detectors reuse the frozen harness's correction detectors so "a correction
# was emitted" means the same thing here as in D1: the reply both restates the
# learner sentence and supplies a corrected version. `correction_emitted` is the
# headline-safety signal; `invites_to_continue` is only consulted when no
# correction fired, so a reply can never be both corrected and invited.


def correction_emitted(reply: str, learner_text: str) -> bool:
    """True if the reply emits a correction (restatement + corrected version).

    Delegates to ``harness.scorers.d1_correction_emitted`` so the notion of "a
    correction was given" is identical to the frozen D1 dimension.
    """
    return d1_correction_emitted(reply, learner_text)


def applies_4part_format(reply: str, learner_text: str) -> bool:
    """True if all four correction markers are present within the brevity cap.

    Stricter than ``correction_emitted``: it additionally requires the repeat
    request and the length bound. Reported as a quality signal, not used for
    per-item correctness (a correction may be emitted without the drill's final
    repeat step, e.g. a lightened close-tier correction).
    """
    return score_d1(reply, learner_text, CORRECTION_BREVITY_MAX).deterministic_compliant


def invites_to_continue(reply: str) -> bool:
    """True if the reply asks the learner to keep going (continue-invitation)."""
    return _INVITE_MARKER.search(reply) is not None


def _has_immediate_repetition(text: str) -> bool:
    """True if two consecutive word tokens are identical (a stutter/repetition)."""
    tokens = _tokens(text)
    return any(a == b for a, b in zip(tokens, tokens[1:]))


def _contains_filler(text: str) -> bool:
    """True if the text contains a hesitation filler token (``euh``/``hmm``…)."""
    return any(token in _FILLER_TOKENS for token in _tokens(text))


def correction_targets_disfluency(reply: str) -> bool:
    """True if a quoted, restated span is itself a disfluency, not a real error.

    A good real-error correction quotes the erroneous words; a bad one quotes the
    stutter or filler. This flags the latter: any quoted span that is an
    immediate word repetition or contains a filler token. Reported as a quality
    signal so a REALERROR correction can be checked for targeting the error.
    """
    return any(
        _has_immediate_repetition(span) or _contains_filler(span)
        for span in _quoted_spans(reply)
    )


def classify_reply(reply: str, learner_text: str) -> str:
    """Map a reply to one of ``{corrected, invited, engaged}``.

    Order matters: a reply that emits a correction is ``corrected`` even if it
    also happens to contain a continue-invitation phrase (the correction is the
    dominant, learner-visible act); otherwise a continue-invitation is
    ``invited``; everything else is ``engaged`` (a normal reply that neither
    corrected nor invited).
    """
    if correction_emitted(reply, learner_text):
        return CLASS_CORRECTED
    if invites_to_continue(reply):
        return CLASS_INVITED
    return CLASS_ENGAGED


def is_correct(label: str, classification: str) -> bool:
    """Whether a classification satisfies the item's expected behaviour."""
    if label == LABEL_DISFLUENCY:
        return classification != CLASS_CORRECTED
    if label == LABEL_INCOMPLETE:
        return classification == CLASS_INVITED
    if label == LABEL_REALERROR:
        return classification == CLASS_CORRECTED
    return classification != CLASS_CORRECTED  # CLEAN


# --- Labelled dialogues (mirror disfluency_set_v1.md verbatim) --------------


@dataclass(frozen=True)
class Dialogue:
    """One single-turn labelled dialogue."""

    dialogue_id: str
    label: str
    learner_text: str


DIALOGUES: tuple[Dialogue, ...] = (
    # DISFLUENCY — must NOT correct (reconstruct the intended sentence).
    Dialogue("F1", LABEL_DISFLUENCY, "Je je pense que mon projet est intéressant."),
    Dialogue(
        "F2",
        LABEL_DISFLUENCY,
        "Mon projet, mon projet parle d'un assistant vocal.",
    ),
    Dialogue("F3", LABEL_DISFLUENCY, "Euh, je travaille sur euh mon portfolio."),
    Dialogue("F4", LABEL_DISFLUENCY, "Hmm, comment dire, je prépare ma soutenance."),
    Dialogue(
        "F5",
        LABEL_DISFLUENCY,
        "Je vais... non, je prépare une présentation pour vendredi.",
    ),
    Dialogue("F6", LABEL_DISFLUENCY, "Hier je suis allé... allée au marché."),
    Dialogue("F7", LABEL_DISFLUENCY, "J'ai un rendez-vous... un entretien demain."),
    Dialogue("F8", LABEL_DISFLUENCY, "Donc euh, le le problème c'est la latence."),
    # INCOMPLETE — must invite to continue, must NOT correct.
    Dialogue("I1", LABEL_INCOMPLETE, "Alors, je pense que le plus important c'est de..."),
    Dialogue("I2", LABEL_INCOMPLETE, "Mon projet utilise un microcontrôleur pour"),
    Dialogue(
        "I3",
        LABEL_INCOMPLETE,
        "Et donc, ce que je voulais dire c'est que... euh...",
    ),
    Dialogue("I4", LABEL_INCOMPLETE, "Quand j'ai commencé le projet, j'ai"),
    # REALERROR — must correct the genuine error, ignoring the disfluency.
    Dialogue("R1", LABEL_REALERROR, "Euh, hier je suis allé au marché."),
    Dialogue("R2", LABEL_REALERROR, "Je je vais au réunion demain."),
    Dialogue("R3", LABEL_REALERROR, "Je suis... je suis responsable de le projet."),
    Dialogue("R4", LABEL_REALERROR, "Donc euh, je vais expliquer vous mon projet."),
    # CLEAN — ordinary correct turn, must NOT correct (control).
    Dialogue(
        "N1",
        LABEL_CLEAN,
        "Bonjour, je m'appelle Marie et je prépare ma soutenance.",
    ),
    Dialogue("N2", LABEL_CLEAN, "Je travaille sur mon portfolio depuis deux semaines."),
    Dialogue(
        "N3",
        LABEL_CLEAN,
        "Hier, je suis allée au marché et j'ai acheté des légumes.",
    ),
)


# --- Metrics ----------------------------------------------------------------


@dataclass(frozen=True)
class ArmMetrics:
    """Aggregate D5 metrics for one prompt arm."""

    n_items: int
    n_scored: int
    accuracy: float
    disfluency_false_correction_rate: float
    real_error_recall: float
    incomplete_invite_rate: float
    per_label_accuracy: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Return numerator/denominator, or 0.0 when the denominator is zero."""
    return numerator / denominator if denominator else 0.0


def compute_metrics(records: list[dict]) -> ArmMetrics:
    """Aggregate per-item classification records into D5 metrics.

    Only records that carry a ``classification`` (i.e. a live reply was scored)
    count toward the metrics; records without one (Ollama unreachable) are
    ignored so partial runs still produce honest numbers.

    - disfluency-false-correction rate = wrongly-corrected DISFLUENCY turns / all
      scored DISFLUENCY turns (the headline risk number).
    - real-error recall = corrected REALERROR turns / all scored REALERROR turns.
    - incomplete-invite rate = invited INCOMPLETE turns / all scored INCOMPLETE
      turns.
    """
    scored = [r for r in records if r.get("classification") is not None]
    correct = sum(1 for r in scored if r["correct"])

    disfluency = [r for r in scored if r["label"] == LABEL_DISFLUENCY]
    realerror = [r for r in scored if r["label"] == LABEL_REALERROR]
    incomplete = [r for r in scored if r["label"] == LABEL_INCOMPLETE]

    false_corrections = sum(
        1 for r in disfluency if r["classification"] == CLASS_CORRECTED
    )
    recalled = sum(1 for r in realerror if r["classification"] == CLASS_CORRECTED)
    invited = sum(1 for r in incomplete if r["classification"] == CLASS_INVITED)

    per_label: dict[str, float] = {}
    for label in (LABEL_DISFLUENCY, LABEL_INCOMPLETE, LABEL_REALERROR, LABEL_CLEAN):
        subset = [r for r in scored if r["label"] == label]
        per_label[label] = _safe_ratio(
            sum(1 for r in subset if r["correct"]), len(subset)
        )

    return ArmMetrics(
        n_items=len(records),
        n_scored=len(scored),
        accuracy=_safe_ratio(correct, len(scored)),
        disfluency_false_correction_rate=_safe_ratio(
            false_corrections, len(disfluency)
        ),
        real_error_recall=_safe_ratio(recalled, len(realerror)),
        incomplete_invite_rate=_safe_ratio(invited, len(incomplete)),
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
    text. On success it also carries the reply, its classification and the
    quality signals; on an Ollama failure it carries ``error`` and a null
    classification so the run stays partial rather than aborting.
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
            "applies_4part_format": None,
            "invites_to_continue": None,
            "correction_targets_disfluency": None,
            "error": None,
        }
        try:
            reply = client.chat(model, messages, decode)
        except OllamaError as exc:
            record["error"] = str(exc)
        else:
            classification = classify_reply(reply, dialogue.learner_text)
            record["reply"] = reply
            record["classification"] = classification
            record["correct"] = is_correct(dialogue.label, classification)
            record["applies_4part_format"] = applies_4part_format(
                reply, dialogue.learner_text
            )
            record["invites_to_continue"] = invites_to_continue(reply)
            record["correction_targets_disfluency"] = correction_targets_disfluency(
                reply
            )
        records.append(record)
    return records


def _print_comparison(v2_records: list[dict], v3_records: list[dict]) -> None:
    """Print a per-dialogue v2-vs-v3 classification table."""
    by_id_v3 = {r["id"]: r for r in v3_records}
    header = f"{'id':<4} {'label':<11} {'v2':<12} {'v3':<12} learner"
    print(header)
    print("-" * len(header))
    for v2_record in v2_records:
        v3_record = by_id_v3[v2_record["id"]]
        v2_class = v2_record["classification"] or "n/a"
        v3_class = v3_record["classification"] or "n/a"
        v2_mark = "" if v2_record["classification"] is None else (
            "ok" if v2_record["correct"] else "X"
        )
        v3_mark = "" if v3_record["classification"] is None else (
            "ok" if v3_record["correct"] else "X"
        )
        print(
            f"{v2_record['id']:<4} {v2_record['label']:<11} "
            f"{v2_class + ' ' + v2_mark:<12} {v3_class + ' ' + v3_mark:<12} "
            f"{v2_record['learner_text']}"
        )


def _print_metrics(name: str, metrics: ArmMetrics) -> None:
    """Print the headline D5 metrics for one arm."""
    print(f"\n[{name}] scored {metrics.n_scored}/{metrics.n_items} items")
    print(f"  accuracy                        : {metrics.accuracy:.3f}")
    print(
        "  disfluency-false-correction rate: "
        f"{metrics.disfluency_false_correction_rate:.3f}"
    )
    print(f"  real-error recall               : {metrics.real_error_recall:.3f}")
    print(f"  incomplete-turn invite rate     : {metrics.incomplete_invite_rate:.3f}")
    for label, acc in metrics.per_label_accuracy.items():
        print(f"  {label:<11} accuracy          : {acc:.3f}")


def _write_results(
    out_dir: Path,
    v2_records: list[dict],
    v3_records: list[dict],
    v2_metrics: ArmMetrics,
    v3_metrics: ArmMetrics,
    ollama_reachable: bool,
) -> Path:
    """Persist records + metrics as JSON; return the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "dimension": "D5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ollama_reachable": ollama_reachable,
        "model": constants.MODEL_UNDER_TEST,
        "arms": {
            "v2": {"records": v2_records, "metrics": v2_metrics.to_dict()},
            "v3": {"records": v3_records, "metrics": v3_metrics.to_dict()},
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
            "applies_4part_format": None,
            "invites_to_continue": None,
            "correction_targets_disfluency": None,
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
        help="Directory under which the disfluency run folder is written.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=constants.MODEL_UNDER_TEST,
        help="Ollama model tag to compare both prompts on.",
    )
    args = parser.parse_args()

    out_dir = args.out_root / "disfluency-d5"
    # Greedy decoding (D5_TEMPERATURE=0) for a deterministic, reproducible
    # v2-vs-v3 comparison; top_p/seed/num_ctx follow the harness convention.
    decode = DecodeOptions(
        temperature=D5_TEMPERATURE,
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
        v2_records = _empty_records()
        v3_records = _empty_records()
    else:
        v2_prompt = load_prompt_body(V2_PROMPT_FILE)
        v3_prompt = load_prompt_body(V3_PROMPT_FILE)
        print(f"[d5] scoring v2 arm ({len(DIALOGUES)} dialogues)...", flush=True)
        v2_records = _score_arm(client, v2_prompt, decode, args.model)
        print(f"[d5] scoring v3 arm ({len(DIALOGUES)} dialogues)...", flush=True)
        v3_records = _score_arm(client, v3_prompt, decode, args.model)

    v2_metrics = compute_metrics(v2_records)
    v3_metrics = compute_metrics(v3_records)

    _print_comparison(v2_records, v3_records)
    _print_metrics("v2", v2_metrics)
    _print_metrics("v3", v3_metrics)

    out_file = _write_results(
        out_dir, v2_records, v3_records, v2_metrics, v3_metrics, ollama_reachable
    )
    print(f"\n[d5] results written to {out_file}")


if __name__ == "__main__":
    main()
