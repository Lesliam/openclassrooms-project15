"""Aggregate a run directory into a Markdown report.

Reads ``scores.json`` + ``config.json`` from a run directory and produces
``report.md`` with the D1/D2/D3 headline metrics, a per-item table and the
exact model / prompt-SHA / decoding config used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Optional

from .runner import DEPTH_DEEP, DEPTH_SHALLOW


def _rate(flags: list[bool]) -> Optional[float]:
    if not flags:
        return None
    return sum(1 for f in flags if f) / len(flags)


def _fmt_rate(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


@dataclass
class DriftDelta:
    dialogue_id: int
    behavior: str
    shallow_rate: Optional[float]
    deep_rate: Optional[float]
    delta: Optional[float]


def _behavior_metric(record: dict, behavior: str) -> Optional[bool]:
    if behavior == "D1":
        return record["d1_pass"]
    if behavior == "D2":
        return record["d2_pass"]
    if behavior == "brevity":
        return record["brevity_pass"]
    return None


def _drift_behaviors(record: dict) -> list[str]:
    behaviors: list[str] = []
    if record["d1_required"]:
        behaviors.append("D1")
    if record["french_only_required"]:
        behaviors.append("D2")
    behaviors.append("brevity")
    return behaviors


def compute_drift_deltas(records: list[dict]) -> list[DriftDelta]:
    """Per drift dialogue and behavior: compliance(shallow) - compliance(deep)."""
    drift = [r for r in records if r["depth"] in (DEPTH_SHALLOW, DEPTH_DEEP)]
    dialogue_ids = sorted({r["dialogue_id"] for r in drift})
    deltas: list[DriftDelta] = []
    for dialogue_id in dialogue_ids:
        items = [r for r in drift if r["dialogue_id"] == dialogue_id]
        behaviors = _drift_behaviors(items[0])
        for behavior in behaviors:
            shallow = [
                _behavior_metric(r, behavior)
                for r in items
                if r["depth"] == DEPTH_SHALLOW
            ]
            deep = [
                _behavior_metric(r, behavior)
                for r in items
                if r["depth"] == DEPTH_DEEP
            ]
            shallow_rate = _rate([b for b in shallow if b is not None])
            deep_rate = _rate([b for b in deep if b is not None])
            delta = (
                None
                if shallow_rate is None or deep_rate is None
                else shallow_rate - deep_rate
            )
            deltas.append(
                DriftDelta(dialogue_id, behavior, shallow_rate, deep_rate, delta)
            )
    return deltas


def _headline_metrics(records: list[dict]) -> dict:
    d1_flags = [r["d1_pass"] for r in records if r["d1_required"]]
    fp_flags = [
        r["false_positive_triggered"] for r in records if r["false_positive_check"]
    ]
    d2_flags = [r["d2_pass"] for r in records if r["french_only_required"]]
    token_fracs = [
        r["d2"]["french_token_fraction"]
        for r in records
        if r["french_only_required"]
    ]
    return {
        "d1_compliance_rate": _rate([b for b in d1_flags if b is not None]),
        "d1_false_positive_rate": _rate([b for b in fp_flags if b is not None]),
        "d2_persistence_rate": _rate([b for b in d2_flags if b is not None]),
        "d2_mean_french_token_fraction": (mean(token_fracs) if token_fracs else None),
    }


def _per_item_rows(records: list[dict]) -> list[str]:
    rows: list[str] = []
    item_ids = sorted({r["item_id"] for r in records})
    for item_id in item_ids:
        items = [r for r in records if r["item_id"] == item_id]
        group = items[0]["group"]
        d1 = _rate([r["d1_pass"] for r in items if r["d1_pass"] is not None])
        fp = _rate(
            [
                r["false_positive_triggered"]
                for r in items
                if r["false_positive_triggered"] is not None
            ]
        )
        d2 = _rate([r["d2_pass"] for r in items if r["d2_pass"] is not None])
        brevity = _rate([r["brevity_pass"] for r in items])
        rows.append(
            f"| {item_id} | {group} | {_fmt_rate(d1)} | {_fmt_rate(fp)} "
            f"| {_fmt_rate(d2)} | {_fmt_rate(brevity)} |"
        )
    return rows


def render_markdown(config: dict, records: list[dict]) -> str:
    """Render the full Markdown report."""
    headline = _headline_metrics(records)
    deltas = compute_drift_deltas(records)
    decode = config["decode"]

    lines: list[str] = []
    lines.append(f"# Coach FR baseline evaluation report - {config['run_id']}")
    lines.append("")
    lines.append(f"- Mode: `{config['mode']}`")
    lines.append(f"- Model under test: `{config['model_under_test']}`")
    lines.append(
        f"- Judge: `{config['judge_model']}` "
        f"(enabled: {config['judge_enabled']})"
    )
    lines.append(f"- Repetitions per item: {config['repetitions']}")
    lines.append(
        f"- Drift depth: {config['drift_depth']} filler turns "
        f"(shallow after {config['shallow_filler_count']})"
    )
    lines.append(f"- System prompt SHA-256: `{config['system_prompt_sha256']}`")
    lines.append(f"- Eval set SHA-256: `{config['eval_set_sha256']}`")
    lines.append(
        "- Decoding: "
        f"temperature={decode['temperature']}, top_p={decode['top_p']}, "
        f"seed_base={config['seed_base']}, num_ctx={decode['num_ctx']} "
        "(v0 guesses, pending Lesliam review)"
    )
    lines.append("")

    lines.append("## Headline metrics")
    lines.append("")
    lines.append(
        "- D1 deterministic pre-check compliance (4-part marker PRESENCE + "
        "brevity; part ORDER and the 'exactly one explanation sentence' rule "
        f"are NOT verified here - judge pending): "
        f"{_fmt_rate(headline['d1_compliance_rate'])}"
    )
    lines.append(
        f"- D1 false-positive rate (error-free turns wrongly corrected): "
        f"{_fmt_rate(headline['d1_false_positive_rate'])}"
    )
    lines.append(
        f"- D2 French-persistence rate: {_fmt_rate(headline['d2_persistence_rate'])}"
    )
    frac = headline["d2_mean_french_token_fraction"]
    lines.append(
        "- D2 mean French-token fraction: "
        + ("n/a" if frac is None else f"{frac:.3f}")
    )
    lines.append("")
    lines.append(
        "> The `D1` column below is the same deterministic pre-check "
        "(presence + brevity), not the spec's full D1 rate; order and "
        "single-explanation checks are the judge's job (eval_set_v0 section 2)."
    )
    lines.append("")

    lines.append("## D3 drift deltas (shallow - deep)")
    lines.append("")
    lines.append("| Dialogue | Behavior | Shallow | Deep | Delta |")
    lines.append("| --- | --- | --- | --- | --- |")
    for delta in deltas:
        delta_str = "n/a" if delta.delta is None else f"{delta.delta * 100:+.1f}pp"
        lines.append(
            f"| {delta.dialogue_id} | {delta.behavior} "
            f"| {_fmt_rate(delta.shallow_rate)} | {_fmt_rate(delta.deep_rate)} "
            f"| {delta_str} |"
        )
    lines.append("")

    lines.append("## Per-item rates")
    lines.append("")
    lines.append("| Item | Group | D1 | D1 false-pos | D2 | Brevity |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.extend(_per_item_rows(records))
    lines.append("")

    return "\n".join(lines)


def build_report(run_dir: Path) -> Path:
    """Read a run dir, render the report and write ``report.md``. Return its path."""
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    records = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    markdown = render_markdown(config, records)
    report_path = run_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    return report_path
