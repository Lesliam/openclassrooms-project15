"""Interpreter-startup compatibility shims for the training container.

The training container pins numpy at 1.26.4 (to keep the NVIDIA Blackwell TF
build intact). microWakeWord's training/eval code calls ``numpy.trapezoid``,
which was only introduced as the canonical name in numpy 2.0; in 1.26 the
equivalent is ``numpy.trapz``. This shim restores the new name so the upstream
source runs unmodified.

Auto-imported by CPython at startup when this directory is on PYTHONPATH.
"""

import numpy as _np

if not hasattr(_np, "trapezoid") and hasattr(_np, "trapz"):
    _np.trapezoid = _np.trapz
