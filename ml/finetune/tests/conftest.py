"""Test bootstrap: make ``check_leakage`` importable.

The suite may be launched from the repository root
(``pytest ml/finetune/tests/``) or from ``ml/finetune`` directly. Inserting the
``ml/finetune`` directory (the parent of this ``tests`` folder) onto
``sys.path`` fixes ``import check_leakage`` for both.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FINETUNE_DIR = Path(__file__).resolve().parent.parent
if str(_FINETUNE_DIR) not in sys.path:
    sys.path.insert(0, str(_FINETUNE_DIR))
