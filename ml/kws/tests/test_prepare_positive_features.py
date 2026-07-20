"""Unit tests for prepare_positive_features.build_augmenter() (CS-152 follow-up).

Covers the --background-dir code path added in commit 9743a5c (background-noise
augmentation for wake-word retrain). These tests do NOT invoke the real
microwakeword Augmentation pipeline (no audio I/O, no TensorFlow/GPU work) --
they monkeypatch the ``Augmentation`` symbol inside the script module with a
fake that just captures the kwargs it was called with, so build_augmenter's
own branching logic is verified in isolation and the suite stays fast (ms).

Run with::

    python -m pytest ml/kws/tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# --- Import target under test (scripts/ is not a package) -------------------

_KWS_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _KWS_DIR / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import prepare_positive_features as ppf  # noqa: E402


class _FakeAugmentation:
    """Stand-in for microwakeword.audio.augmentation.Augmentation.

    Records the kwargs it was constructed with instead of building a real
    augmentation pipeline (which requires audio backends and is slow).
    """

    last_kwargs: Dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs


@pytest.fixture(autouse=True)
def _patch_augmentation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ppf, "Augmentation", _FakeAugmentation)


@pytest.fixture()
def impulse_dir(tmp_path: Path) -> Path:
    # build_augmenter only checks impulse_dir.is_dir(); an empty dir suffices.
    directory = tmp_path / "impulses"
    directory.mkdir()
    return directory


# --- (1) no --background-dir: default behaviour unchanged ------------------


def test_build_augmenter_without_background_dir_keeps_defaults(impulse_dir: Path) -> None:
    ppf.build_augmenter(impulse_dir, None)
    kwargs = _FakeAugmentation.last_kwargs
    assert kwargs["augmentation_probabilities"]["AddBackgroundNoise"] == 0.0
    assert kwargs["background_paths"] == []


# --- (2) valid --background-dir: enabled at p=0.75, dir passed through -----


def test_build_augmenter_with_background_dir_enables_augmentation(tmp_path: Path,
                                                                    impulse_dir: Path) -> None:
    background_dir = tmp_path / "background_noise"
    background_dir.mkdir()

    ppf.build_augmenter(impulse_dir, background_dir)
    kwargs = _FakeAugmentation.last_kwargs
    assert kwargs["augmentation_probabilities"]["AddBackgroundNoise"] == 0.75
    assert kwargs["background_paths"] == [str(background_dir)]


# --- (3) non-existent --background-dir: clear ValueError -------------------


def test_build_augmenter_with_missing_background_dir_raises_value_error(
    tmp_path: Path, impulse_dir: Path
) -> None:
    missing_dir = tmp_path / "does_not_exist"

    with pytest.raises(ValueError, match="does not exist"):
        ppf.build_augmenter(impulse_dir, missing_dir)


# --- (4) module-level default dict is never mutated -------------------------


def test_build_augmenter_does_not_mutate_module_level_probabilities(
    tmp_path: Path, impulse_dir: Path
) -> None:
    background_dir = tmp_path / "background_noise"
    background_dir.mkdir()

    ppf.build_augmenter(impulse_dir, background_dir)

    assert ppf.AUGMENTATION_PROBABILITIES["AddBackgroundNoise"] == 0.0
