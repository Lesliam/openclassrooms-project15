"""Test bootstrap: make the ``harness`` package importable.

The suite may be launched from the repository root (``pytest
project/ml/eval/tests/``) or from ``ml/eval`` directly. In the former case the
``harness`` package directory is not on ``sys.path``; inserting the ``ml/eval``
directory (the parent of this ``tests`` folder) fixes imports for both.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))
