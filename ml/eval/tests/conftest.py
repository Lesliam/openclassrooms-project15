"""Test bootstrap: make the ``harness`` package and ``server`` module importable.

The suite may be launched from the repository root (``pytest
project/ml/eval/tests/``) or from ``ml/eval`` directly. In the former case the
``harness`` package directory is not on ``sys.path``; inserting the ``ml/eval``
directory (the parent of this ``tests`` folder) fixes imports for both. The
``project/server`` directory is also inserted so ``grammar_grounding`` (the
grammar-grounding correctness layer under test) imports without loading torch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent.parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

_SERVER_DIR = _EVAL_DIR.parent.parent / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))
