"""Constants for the Coach STT integration."""

from __future__ import annotations

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
