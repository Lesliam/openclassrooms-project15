"""The Coach STT integration.

Provides a speech-to-text entity that proxies an existing Wyoming ASR service
(wyoming-faster-whisper) but declares requires_external_vad=False. Home
Assistant then skips VoiceCommandSegmenter for this entity, which removes both
the silence-based end of turn and the 15 second capture cap of the assist
pipeline. Ending the turn becomes the responsibility of the satellite.

Requires Home Assistant core 2026.5.0 or later: SpeechAudioProcessing gained
requires_external_vad in that release.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import COACH_LANGUAGES
from .wyoming_client import describe_service, select_languages

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.STT]


@dataclass
class CoachSttData:
    """Runtime data of a Coach STT config entry."""

    host: str
    port: int
    languages: tuple[str, ...]
    service_name: str | None


type CoachSttConfigEntry = ConfigEntry[CoachSttData]


async def async_setup_entry(hass: HomeAssistant, entry: CoachSttConfigEntry) -> bool:
    """Set up Coach STT from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    description = await describe_service(host, port)
    if description is None:
        raise ConfigEntryNotReady(
            f"Unable to reach the Wyoming speech-to-text service at {host}:{port}"
        )

    languages = select_languages(description.languages, COACH_LANGUAGES)
    if "fr" not in description.languages:
        _LOGGER.warning(
            "The Wyoming service at %s:%s does not advertise French; the entity "
            "still offers it, but check the model loaded by the service",
            host,
            port,
        )
    _LOGGER.debug(
        "Connected to Wyoming service %s at %s:%s, languages offered: %s",
        description.name,
        host,
        port,
        ", ".join(languages),
    )

    entry.runtime_data = CoachSttData(
        host=host,
        port=port,
        languages=languages,
        service_name=description.name,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CoachSttConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
