"""Independent validation tests for the trained KWS artifacts (CS-152).

These tests audit the committed model artifacts under ``ml/kws/``:

- ``models/hello_lingorm.tflite`` loads and exposes exactly one input and one
  output tensor (streaming micro_wake_word model);
- ``models/hello_lingorm.json`` is a valid ESPHome micro_wake_word **v2**
  manifest and its ``model`` field points at the tflite file that sits beside
  it;
- ``training_parameters.yaml`` parses as YAML and carries the expected training
  keys.

The tests do NOT modify the artifacts. They are re-runnable in place and locate
the artifacts relative to this file, so they survive a checkout anywhere.

Run with any interpreter that has ``ai-edge-litert`` (or ``tflite_runtime`` /
``tensorflow``) and ``PyYAML`` installed::

    python -m pytest ml/kws/tests/ -q
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

try:  # pragma: no cover - import selection is environment-specific
    import yaml
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PyYAML is required to run the KWS artifact tests") from exc

# --- Artifact locations (relative to this test file) -----------------------

_KWS_DIR = Path(__file__).resolve().parent.parent
_MODELS_DIR = _KWS_DIR / "models"
_TFLITE_PATH = _MODELS_DIR / "hello_lingorm.tflite"
_MANIFEST_PATH = _MODELS_DIR / "hello_lingorm.json"
_TRAINING_PARAMS_PATH = _KWS_DIR / "training_parameters.yaml"


def _load_interpreter(model_path: str) -> Any:
    """Return an allocated tflite interpreter, trying the available backends.

    ai-edge-litert is the primary backend (present in the coach-kws venv);
    tflite_runtime and tensorflow.lite are accepted fallbacks.
    """
    last_error: Exception | None = None
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError as exc:  # pragma: no cover - fallback path
        last_error = exc
        Interpreter = None  # type: ignore[assignment]

    if Interpreter is None:
        try:  # pragma: no cover - fallback path
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError as exc:
            last_error = exc
            Interpreter = None  # type: ignore[assignment]

    if Interpreter is None:
        try:  # pragma: no cover - fallback path
            import tensorflow as tf

            Interpreter = tf.lite.Interpreter  # type: ignore[assignment]
        except ImportError as exc:
            last_error = exc
            Interpreter = None  # type: ignore[assignment]

    if Interpreter is None:  # pragma: no cover
        raise RuntimeError(
            "No tflite interpreter backend available "
            "(ai_edge_litert / tflite_runtime / tensorflow)"
        ) from last_error

    interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    return interpreter


# --- Existence -------------------------------------------------------------


def test_artifact_files_exist() -> None:
    assert _TFLITE_PATH.is_file(), f"missing tflite: {_TFLITE_PATH}"
    assert _MANIFEST_PATH.is_file(), f"missing manifest: {_MANIFEST_PATH}"
    assert _TRAINING_PARAMS_PATH.is_file(), (
        f"missing training params: {_TRAINING_PARAMS_PATH}"
    )


# --- 1. tflite loads and has one input + one output ------------------------


def test_tflite_loads_and_has_single_io() -> None:
    interpreter = _load_interpreter(str(_TFLITE_PATH))
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    assert len(input_details) == 1, "expected exactly one input tensor"
    assert len(output_details) == 1, "expected exactly one output tensor"


def test_tflite_io_shapes_and_dtypes_are_recorded() -> None:
    # Records (and asserts sane) the streaming model I/O contract. The values
    # are reported in TEST_REPORT_CS152.md; the assertions here only guard
    # against a degenerate/empty tensor spec.
    interpreter = _load_interpreter(str(_TFLITE_PATH))
    in_detail = interpreter.get_input_details()[0]
    out_detail = interpreter.get_output_details()[0]

    in_shape = list(in_detail["shape"])
    out_shape = list(out_detail["shape"])

    # Input is a batched feature window; output is a batched probability.
    assert len(in_shape) >= 2
    assert in_shape[0] == 1, "batch dimension should be 1"
    assert all(dim > 0 for dim in in_shape), f"degenerate input shape {in_shape}"
    assert len(out_shape) >= 1
    assert all(dim > 0 for dim in out_shape), f"degenerate output shape {out_shape}"


# --- 2. manifest is a valid ESPHome micro_wake_word v2 manifest ------------


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    with _MANIFEST_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert isinstance(data, dict), "manifest root must be a JSON object"
    return data


def test_manifest_is_valid_json(manifest: dict[str, Any]) -> None:
    # Loading in the fixture already proves validity; assert a non-empty object.
    assert manifest


def test_manifest_top_level_required_keys(manifest: dict[str, Any]) -> None:
    for key in ("type", "wake_word", "model", "trained_languages", "version", "micro"):
        assert key in manifest, f"manifest missing top-level key: {key}"


def test_manifest_type_is_micro(manifest: dict[str, Any]) -> None:
    assert manifest["type"] == "micro"


def test_manifest_version_is_2(manifest: dict[str, Any]) -> None:
    assert manifest["version"] == 2


def test_manifest_wake_word_is_non_empty_string(manifest: dict[str, Any]) -> None:
    assert isinstance(manifest["wake_word"], str)
    assert manifest["wake_word"].strip()


def test_manifest_trained_languages_non_empty(manifest: dict[str, Any]) -> None:
    langs = manifest["trained_languages"]
    assert isinstance(langs, list)
    assert len(langs) >= 1
    assert all(isinstance(lang, str) and lang.strip() for lang in langs)


def test_manifest_micro_required_keys(manifest: dict[str, Any]) -> None:
    micro = manifest["micro"]
    assert isinstance(micro, dict)
    for key in (
        "probability_cutoff",
        "sliding_window_size",
        "feature_step_size",
        "tensor_arena_size",
        "minimum_esphome_version",
    ):
        assert key in micro, f"micro object missing key: {key}"


def test_manifest_probability_cutoff_in_unit_interval(manifest: dict[str, Any]) -> None:
    cutoff = manifest["micro"]["probability_cutoff"]
    assert isinstance(cutoff, (int, float)) and not isinstance(cutoff, bool)
    assert 0.0 <= float(cutoff) <= 1.0, f"probability_cutoff out of range: {cutoff}"


def test_manifest_micro_integer_fields_are_positive(manifest: dict[str, Any]) -> None:
    micro = manifest["micro"]
    for key in ("sliding_window_size", "feature_step_size", "tensor_arena_size"):
        value = micro[key]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert value > 0, f"{key} must be a positive integer, got {value}"


def test_manifest_minimum_esphome_version_is_versionish(manifest: dict[str, Any]) -> None:
    version = manifest["micro"]["minimum_esphome_version"]
    assert isinstance(version, str) and version.strip()
    # ESPHome uses YYYY.M.patch calendar versioning; assert a dotted numeric form.
    parts = version.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts), f"unexpected version: {version}"


# --- 3. training_parameters.yaml parses and has expected keys --------------


@pytest.fixture(scope="module")
def training_params() -> dict[str, Any]:
    with _TRAINING_PARAMS_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict), "training params root must be a mapping"
    return data


def test_training_params_expected_keys(training_params: dict[str, Any]) -> None:
    expected = {
        "window_step_ms",
        "train_dir",
        "features",
        "training_steps",
        "positive_class_weight",
        "negative_class_weight",
        "learning_rates",
        "batch_size",
        "eval_step_interval",
        "clip_duration_ms",
        "target_minimization",
        "maximization_metric",
    }
    missing = expected - training_params.keys()
    assert not missing, f"training params missing keys: {sorted(missing)}"


def test_training_params_features_is_non_empty_list(training_params: dict[str, Any]) -> None:
    features = training_params["features"]
    assert isinstance(features, list) and features
    for feature in features:
        assert "features_dir" in feature
        assert "truth" in feature


def test_training_params_has_positive_and_negative_features(
    training_params: dict[str, Any],
) -> None:
    truths = [feature.get("truth") for feature in training_params["features"]]
    assert any(truths), "no positive (truth=True) feature source"
    assert not all(truths), "no negative (truth=False) feature source"


def test_training_params_training_steps_positive(training_params: dict[str, Any]) -> None:
    steps = training_params["training_steps"]
    assert isinstance(steps, list) and steps
    assert all(isinstance(s, int) and s > 0 for s in steps)


# --- 4. cross-check: manifest.model points at the actual tflite file -------


def test_manifest_model_filename_matches_existing_tflite(manifest: dict[str, Any]) -> None:
    model_filename = manifest["model"]
    assert isinstance(model_filename, str) and model_filename
    # The manifest references the model by bare filename; it must exist beside
    # the manifest.
    referenced = _MANIFEST_PATH.parent / model_filename
    assert referenced.is_file(), (
        f"manifest 'model' -> {model_filename!r} does not exist beside the manifest"
    )
    # And it must be exactly the tflite artifact under test.
    assert referenced.resolve() == _TFLITE_PATH.resolve()
