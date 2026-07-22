"""Constants for the Coach STT integration."""

from __future__ import annotations

import re

DOMAIN = "coach_stt"

CONF_MAX_DURATION = "max_duration_seconds"

# The GPU box running wyoming-faster-whisper (large-v3, French) on the LAN.
DEFAULT_HOST = "192.168.1.37"
DEFAULT_PORT = 10300

# Backstop duration for a turn that the satellite never terminates.
DEFAULT_MAX_DURATION_SECONDS = 120.0
MIN_MAX_DURATION_SECONDS = 10.0
MAX_MAX_DURATION_SECONDS = 600.0

# Languages this entity offers to the assist pipeline. The running whisper
# large-v3 service advertises 100 languages, but this entity is for the French
# coach only:
# exposing the whole list would clutter the pipeline language selector without
# serving any use case. English is kept so the entity can also be picked from an
# English pipeline while debugging. Used as the fallback as well, for a service
# that advertises no language at all.
COACH_LANGUAGES = ("fr", "en")

ENTITY_NAME = "Coach FR Whisper sans VAD"

# The spoken end word ("j'ai fini", CS-159) is necessarily captured in the
# audio before the satellite can close the stream, so whisper transcribes it.
# Left in the transcript it collides with the coach's closing-cue prompt rules
# ("j'ai fini" reads as a farewell and triggers a warm close instead of an
# answer). The entity therefore strips ONE TRAILING occurrence before handing
# the text to the pipeline. Only the trailing occurrence is removed:
# mid-sentence uses ("j'ai fini mes etudes en 2020") stay untouched. "finit"
# is accepted as a frequent whisper spelling of the same sound.
# Leading class deliberately excludes sentence-final punctuation (. ! ?):
# in "Voici mon plan. J'ai fini" the dot belongs to the learner's sentence
# and must survive the strip. Details:
# - both apostrophe code points accepted (U+0027 and U+2019), matching what
#   grammar_grounding.py already does on the same transcript path;
# - fini/finit/finis/finie all accepted as whisper spellings of one sound;
# - the whole clause may repeat ("j'ai fini, j'ai fini" stutter) and the
#   trailing [^\w]* eats any non-word run (ellipsis, quotes, brackets).
#
# Second alternative: "refinis". This is not a French word, it is the
# mistranscription whisper produced for the spoken end word during the session
# 26 live run ("... Refinis. Refinis." at the end of the turn, repeated).
# Having no "j'ai" anchor it passed the first alternative and reached the coach
# LLM. Only this one observed variant is accepted, and only in trailing
# position: no fuzzy matching and no bare "finis", both of which would eat
# legitimate learner speech. What excludes the real French neighbours
# "definis" / "redefinis" ("tu redefinis les regles") is the required letter
# sequence r + e/accented-e + finis: "definis" has no "r", "redefinis" has a
# "d" where the "f" must be. \b earns its keep on the other family, words that
# do contain the sequence: "irrefinis", "refinissable", the English "refinish"
# (COACH_LANGUAGES offers en too) and "refinis3" all stay whole. A run may mix
# both alternatives: "... j'ai fini. Refinis." is cleaned in one pass because
# the alternation sits inside the repeated group.
#
# The leading [\s,;]* sits OUTSIDE the repeated group on purpose. Inside it,
# it overlapped with the group's own trailing [^\w]* ([\s,;] is a subset of
# [^\w]), so a separator between two occurrences could be split between two
# iterations in several ways and a repeated run followed by any non-matching
# word ("Refinis. Refinis. ... Merci.") took exponential time to fail - on the
# event loop, since stt.py calls sub() synchronously. Hoisted, the separator
# has exactly one owner and the match is linear. The behaviour is unchanged:
# the inner [^\w]* already covers everything the inner [\s,;]* could match,
# while the hoisted copy still protects the first occurrence from eating
# sentence-final punctuation. See test_repeated_end_word_run_is_linear_time.
END_WORD_TRAILING_PATTERN = re.compile(
    r"[\s,;]*(?:(?:j['’]?\s?ai\s+fini(?:s|t|e)?|\br[ée]finis\b)[^\w]*)+$",
    re.IGNORECASE,
)
