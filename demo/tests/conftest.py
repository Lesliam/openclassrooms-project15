"""Test bootstrap: make ``coach_demo`` importable.

The suite may be launched from the repository root (``pytest demo/tests/``) or
from ``demo`` directly. Inserting the ``demo`` directory (the parent of this
``tests`` folder) onto ``sys.path`` fixes ``import coach_demo`` for both.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))
