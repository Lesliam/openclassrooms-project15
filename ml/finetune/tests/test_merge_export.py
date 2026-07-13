"""Pure-constant unit test for ``merge_export`` (no model load).

Only checks the Modelfile constant. The merge itself loads the bf16 14B model
on CPU and is never exercised here.
"""

from __future__ import annotations

import merge_export


def test_modelfile_is_from_current_dir() -> None:
    # "FROM .\n" is what makes Ollama read the merged safetensors directory
    # (chat template + stop tokens come from the tokenizer config in that dir,
    # so no SYSTEM/TEMPLATE override is needed). A drift here would break the
    # `ollama create` step of the tuned arm.
    assert merge_export._MODELFILE == "FROM .\n"
