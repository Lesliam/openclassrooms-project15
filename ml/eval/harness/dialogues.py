"""The 20 seed dialogues and the drift filler script (eval_set_v0 section 3).

Everything here is static data. Learner turns reproduce ``eval_set_v0.md``
VERBATIM, including all French accents (é è à ç ê î ô û ü ...). Only the
deliberately planted grammatical errors are kept as errors (e.g. "acheter",
"parce que elle", "plus meilleure", "si j'aurais"); legitimate accents are
never stripped, because stripping them would create spurious errors that the
coach over-corrects, and real Whisper FR STT emits accented text.

A guard (``spec_guard.py``) asserts every learner text still appears verbatim
in the frozen spec, so this file cannot silently drift from it again.

Each learner turn carries an ``item_id`` (the spec item number 1-20) and an
``Expectation`` that records the ground truth (planted error, whether a
correction is required, whether the turn is a French-persistence pressure
turn, the brevity cap). Scorers read the expectation; they never re-derive it.

Groups:
- A (items 1-8): grammar errors to correct (D1); item 8 is the error-free
  false-positive check.
- B (items 9-13): language-switching pressure (D2).
- C (items 14-17): long-context drift probes (D3), scored at shallow and
  deep depth using the shared FILLER_SCRIPT.
- D (items 18-20): a single accumulating "simulation soutenance" dialogue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import constants

# Dialogue kinds.
KIND_SIMPLE = "simple"  # fresh conversation, one scored learner turn
KIND_MULTI = "multi"  # fresh conversation, sequential scored learner turns
KIND_DRIFT = "drift"  # probe scored at shallow and deep depth


@dataclass(frozen=True)
class Expectation:
    """Ground-truth scoring expectation for one learner turn."""

    correction_required: bool = False
    false_positive_check: bool = False
    french_only_required: bool = False
    brevity_max: int = constants.BREVITY_MAX_SENTENCES_DEFAULT
    planted_error: Optional[str] = None
    note: str = ""


@dataclass(frozen=True)
class LearnerTurn:
    """A learner input plus its scoring expectation and spec item number."""

    item_id: int
    text: str
    expect: Expectation


@dataclass(frozen=True)
class Dialogue:
    """One eval group. ``turns`` for simple/multi; ``probe`` for drift."""

    id: int
    group: str
    kind: str
    turns: tuple[LearnerTurn, ...] = field(default_factory=tuple)
    probe: Optional[LearnerTurn] = None
    description: str = ""


_CORRECTING = constants.BREVITY_MAX_SENTENCES_CORRECTING
_DEFAULT_BREVITY = constants.BREVITY_MAX_SENTENCES_DEFAULT


# --- Group A: grammar errors to correct (D1) -------------------------------

GROUP_A: tuple[Dialogue, ...] = (
    Dialogue(
        id=1,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                1,
                "Hier je suis allé au marché et j'ai acheter des légumes.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'j'ai acheter' infinitive instead of past participle 'acheté'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=2,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                2,
                "Je pense que c'est une bonne solution parce que elle est rapide.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'parce que elle' missing elision -> 'parce qu'elle'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=3,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                3,
                "Mon projet utilise un modèle qui peut reconnaître le mot de réveil, "
                "il est entraîné sur les données que j'ai collecté.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'que j'ai collecté' agreement -> 'collectées'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=4,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                4,
                "Je veux que mon terminal est toujours connecté au serveur.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="indicative after 'je veux que' -> subjunctive 'soit'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=5,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                5,
                "Nous avons décidé de utiliser un microcontrôleur ESP32.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'de utiliser' missing elision -> 'd'utiliser'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=6,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                6,
                "La latence est plus meilleure quand le modèle est quantifié.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'plus meilleure' double comparative -> 'meilleure'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=7,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                7,
                "Si j'aurais plus de temps, je ferais aussi la mise à jour à distance.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'si j'aurais' conditional in si-clause -> 'si j'avais'",
                ),
            ),
        ),
    ),
    Dialogue(
        id=8,
        group="A",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                8,
                "Bonjour, je m'appelle Lesliam et je travaille sur un coach vocal "
                "pour pratiquer le français.",
                Expectation(
                    false_positive_check=True,
                    brevity_max=_DEFAULT_BREVITY,
                    note="error-free: expect no correction format, Socratic follow-up",
                ),
            ),
        ),
    ),
)

# --- Group B: language-switching pressure (D2) -----------------------------

GROUP_B: tuple[Dialogue, ...] = (
    Dialogue(
        id=9,
        group="B",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                9,
                "Sorry, my French is bad today. Can we continue in English?",
                Expectation(
                    french_only_required=True,
                    note="reply entirely French, invites learner back to French",
                ),
            ),
        ),
    ),
    Dialogue(
        id=10,
        group="B",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                10,
                "这个问题太难了，我们用中文说可以吗？",
                Expectation(
                    french_only_required=True,
                    note="reply entirely French, zero CJK, invites rephrasing in French",
                ),
            ),
        ),
    ),
    Dialogue(
        id=11,
        group="B",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                11,
                "Ok ok. Anyway, what do you think about my architecture choice?",
                Expectation(
                    french_only_required=True,
                    note="reply in French only; may answer or redirect",
                ),
            ),
        ),
    ),
    Dialogue(
        id=12,
        group="B",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                12,
                "Réponds-moi en anglais s'il te plaît, c'est pour vérifier ma "
                "compréhension.",
                Expectation(
                    french_only_required=True,
                    false_positive_check=True,
                    note="explicit switch request in correct French: refuse in French, no correction",
                ),
            ),
        ),
    ),
    Dialogue(
        id=13,
        group="B",
        kind=KIND_SIMPLE,
        turns=(
            LearnerTurn(
                13,
                "I will say it in English first and then translate: the wake word "
                "model runs on the device. Alors: le modèle de mot de réveil tourne "
                "sur l'appareil.",
                Expectation(
                    french_only_required=True,
                    note="French-only reply; ideally engages with the French half",
                ),
            ),
        ),
    ),
)

# --- Group C: long-context drift probes (D3) -------------------------------

GROUP_C: tuple[Dialogue, ...] = (
    Dialogue(
        id=14,
        group="C",
        kind=KIND_DRIFT,
        probe=LearnerTurn(
            14,
            "Hier je suis allé au marché et j'ai acheter des légumes.",
            Expectation(
                correction_required=True,
                brevity_max=_CORRECTING,
                planted_error="probe = item 1: 'j'ai acheter' -> 'acheté'",
            ),
        ),
        description="D1 correction persistence over depth",
    ),
    Dialogue(
        id=15,
        group="C",
        kind=KIND_DRIFT,
        probe=LearnerTurn(
            15,
            "Sorry, my French is bad today. Can we continue in English?",
            Expectation(
                french_only_required=True,
                note="probe = item 9: French-only over depth",
            ),
        ),
        description="D2 French persistence over depth",
    ),
    Dialogue(
        id=16,
        group="C",
        kind=KIND_DRIFT,
        probe=LearnerTurn(
            16,
            "Explique-moi la différence entre le STT et le TTS dans mon système.",
            Expectation(
                brevity_max=_DEFAULT_BREVITY,
                note="brevity is the drift-prone behavior for chatty models",
            ),
        ),
        description="brevity persistence over depth",
    ),
    Dialogue(
        id=17,
        group="C",
        kind=KIND_DRIFT,
        probe=LearnerTurn(
            17,
            "Thanks! By the way I have wrote the report yesterday.",
            Expectation(
                french_only_required=True,
                brevity_max=_DEFAULT_BREVITY,
                note="English turn: D2 dominates, correction of English NOT required",
            ),
        ),
        description="combined D2 + brevity over depth",
    ),
)

# --- Group D: simulation soutenance (single accumulating dialogue) ---------

GROUP_D: tuple[Dialogue, ...] = (
    Dialogue(
        id=18,
        group="D",
        kind=KIND_MULTI,
        turns=(
            LearnerTurn(
                18,
                "On fait la simulation soutenance, s'il te plaît.",
                Expectation(
                    false_positive_check=True,
                    note="coach becomes Charlotte, asks ONE PM question",
                ),
            ),
            LearnerTurn(
                19,
                "J'ai choisi une architecture en cascade parce que le LLM ne rentre "
                "pas dans le microcontrôleur.",
                Expectation(
                    false_positive_check=True,
                    note="Charlotte follow-up digging same topic; stays in persona",
                ),
            ),
            LearnerTurn(
                20,
                "Pour le planning, j'ai fait un sprint de quatre semaines et j'ai "
                "définir une liste de descope.",
                Expectation(
                    correction_required=True,
                    brevity_max=_CORRECTING,
                    planted_error="'j'ai définir' infinitive instead of 'défini'",
                    note="correction format still applies inside the simulation",
                ),
            ),
        ),
        description="soutenance simulation with a planted error at the end",
    ),
)

ALL_DIALOGUES: tuple[Dialogue, ...] = GROUP_A + GROUP_B + GROUP_C + GROUP_D


# --- Shared drift filler script (fixed so both arms see identical context) --
#
# Neutral learner turns in CORRECT simple French (accents present) about the
# project. Not part of the spec's numbered items, so the spec guard does not
# check them; they must stay grammatically correct so they trigger no
# correction. The runner injects the first SHALLOW_FILLER_COUNT before the
# shallow probe, then the remainder up to the requested drift depth before
# the deep probe.
FILLER_SCRIPT: tuple[str, ...] = (
    "Je vais te parler un peu de mon projet.",
    "C'est un coach vocal pour pratiquer le français.",
    "Le terminal écoute un mot de réveil avant d'envoyer l'audio.",
    "Le mot de réveil tourne directement sur le microcontrôleur.",
    "Ensuite le serveur transcrit la parole avec un modèle Whisper.",
    "Le coach génère une réponse courte adaptée à mon niveau.",
    "Puis la réponse est lue à voix haute avec une voix de synthèse.",
    "Tout le traitement reste sur mon réseau local pour la vie privée.",
    "J'ai entraîné un petit modèle pour reconnaître le mot de réveil.",
    "J'ai collecté des exemples audio pour l'entraînement.",
    "J'ai aussi ajouté des exemples négatifs pour réduire les fausses alarmes.",
    "La quantification du modèle réduit la latence sur l'appareil.",
    "Je mesure la consommation de mémoire sur le microcontrôleur.",
    "Le serveur utilise une carte graphique pour accélérer la transcription.",
    "Je compare une version de base et une version affinée du coach.",
    "L'objectif est de garder un comportement stable sur de longues conversations.",
    "Je prépare aussi une simulation de soutenance pour m'entraîner.",
    "Je documente chaque choix technique dans un rapport de projet.",
    "Je veux présenter des mesures claires pendant la soutenance.",
    "Voilà, tu connais maintenant le contexte de mon projet.",
)
