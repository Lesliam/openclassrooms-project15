"""Tests for the trailing end-word strip pattern (CS-159 transcript hygiene).

Loads const.py by file path so the tests run without a Home Assistant
install, mirroring the conftest approach used for wyoming_client.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_CONST_PATH = Path(__file__).parent.parent / "coach_stt" / "const.py"
_SPEC = importlib.util.spec_from_file_location("coach_stt_const", _CONST_PATH)
_CONST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CONST)

PATTERN = _CONST.END_WORD_TRAILING_PATTERN


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        # Plain trailing end word, with and without punctuation.
        ("Est-ce que tout va bien ? j'ai fini", "Est-ce que tout va bien ?"),
        ("Est-ce que tout va bien ? J'ai fini.", "Est-ce que tout va bien ?"),
        ("Mon projet avance bien, j'ai fini !", "Mon projet avance bien"),
        # Whisper spelling variant.
        ("Voici mon plan. J'ai finit", "Voici mon plan."),
        # Elision variants whisper sometimes produces.
        ("Voici mon plan. Jai fini", "Voici mon plan."),
        ("Voici mon plan. j' ai fini", "Voici mon plan."),
        # ONLY the end word -> empty transcript (intentional-close edge).
        ("j'ai fini", ""),
        ("J'ai fini.", ""),
        # Typographic apostrophe U+2019 (H1).
        ("Voici mon plan. J’ai fini", "Voici mon plan."),
        # Ellipsis / quote in the trailing run (M1).
        ("Voici mon plan. J'ai fini…", "Voici mon plan."),
        # Other whisper spellings of the same sound (M2).
        ("Voici mon plan. J'ai finis", "Voici mon plan."),
        ("Voici mon plan. J'ai finie", "Voici mon plan."),
        # Stuttered/repeated end word (M3): all trailing occurrences go.
        ("Mon plan est solide, j'ai fini, j'ai fini", "Mon plan est solide"),
        ("Mon plan est solide. J'ai fini. J'ai fini.", "Mon plan est solide."),
        # Observed whisper mistranscription of the end word (session 26 live
        # run): single, repeated, lowercase and unaccented spellings.
        ("Voici mon plan. Réfinis.", "Voici mon plan."),
        ("Voici mon plan. Réfinis. Réfinis.", "Voici mon plan."),
        ("Voici mon plan, réfinis", "Voici mon plan"),
        ("Voici mon plan. Refinis", "Voici mon plan."),
        ("Voici mon plan. réfinis !", "Voici mon plan."),
        ("Voici mon plan. RÉFINIS.", "Voici mon plan."),
        # Only the mistranscription -> empty transcript.
        ("Réfinis.", ""),
        ("Réfinis. Réfinis.", ""),
        # Mixed run: the real end word followed by its mistranscription must be
        # cleaned in the single sub() call stt.py performs.
        ("Voici mon plan. J'ai fini. Réfinis.", "Voici mon plan."),
        ("Voici mon plan. J'ai fini. Réfinis. Réfinis.", "Voici mon plan."),
        ("Mon plan avance, réfinis, j'ai fini", "Mon plan avance"),
    ],
)
def test_trailing_end_word_is_stripped(transcript: str, expected: str) -> None:
    assert PATTERN.sub("", transcript) == expected


@pytest.mark.parametrize(
    "transcript",
    [
        # Mid-sentence use is learner content and must remain untouched.
        "j'ai fini mes etudes en 2020 et je cherche un poste",
        "quand j'ai fini le projet, j'etais fiere",
        # Other 'fini' phrases are not the end word.
        "le projet est fini mais je continue",
        "c'est fini pour la partie technique, passons a la suite",
        # Real French words ending in -finis must survive in trailing position:
        # only the observed "refinis" mistranscription is stripped.
        "tu définis les règles",
        "tu définis",
        "les critères que tu redéfinis",
        "je redéfinis",
        "ce sont les paramètres redéfinis",
        "confinis",
        # 'refinis' inside a larger word is not the end word either.
        "les résultats irréfinis",
        "réfinissable",
        # Mid-sentence occurrence is not trailing, so it stays.
        "réfinis le plan puis reviens vers moi",
        "quand tu réfinis le plan, note les écarts",
    ],
)
def test_non_trailing_or_other_fini_untouched(transcript: str) -> None:
    assert PATTERN.sub("", transcript) == transcript
