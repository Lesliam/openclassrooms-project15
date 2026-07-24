"""Independent unit tests for ``harness.cli`` argument gating.

These tests exercise only the pre-run gates (no Ollama, no filesystem run
output): the --judge flag must fail loudly (fix B1) and an over-large
--drift-depth must be rejected before any network call (fix S4).
"""

from __future__ import annotations

import pytest

from harness import cli
from harness.runner import available_filler_depth


def test_judge_flag_rejected_loudly_on_full_run() -> None:
    # --judge is not wired; it must raise rather than write a config that could
    # claim the judge ran.
    with pytest.raises(NotImplementedError):
        cli.main(["--full", "--judge"])


def test_judge_flag_rejected_loudly_on_dry_run() -> None:
    with pytest.raises(NotImplementedError):
        cli.main(["--dry-run", "--judge"])


def test_oversize_drift_depth_returns_error_code_without_network() -> None:
    # Requesting more filler than exists must be rejected before any Ollama
    # call (return code 4), never silently truncated.
    too_deep = available_filler_depth() + 5
    assert cli.main(["--dry-run", "--drift-depth", str(too_deep)]) == 4


def test_drift_depth_at_capacity_is_accepted_by_the_guard() -> None:
    # Exactly at capacity is allowed by the depth guard; the run then proceeds
    # to the spec guard / health check (not exercised here). We only assert the
    # guard itself does not reject the boundary value.
    from harness.runner import ensure_drift_depth_available

    ensure_drift_depth_available(available_filler_depth())  # must not raise
