"""Config flow for the Coach STT integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import (
    CONF_MAX_DURATION,
    DEFAULT_HOST,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_PORT,
    DOMAIN,
    ENTITY_NAME,
    MAX_MAX_DURATION_SECONDS,
    MIN_MAX_DURATION_SECONDS,
)
from .wyoming_client import describe_service

_DURATION_SELECTOR = vol.All(
    vol.Coerce(float),
    vol.Range(min=MIN_MAX_DURATION_SECONDS, max=MAX_MAX_DURATION_SECONDS),
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(
            CONF_MAX_DURATION, default=DEFAULT_MAX_DURATION_SECONDS
        ): _DURATION_SELECTOR,
    }
)


class CoachSttConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Coach STT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        host: str = user_input[CONF_HOST]
        port: int = user_input[CONF_PORT]

        self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})

        # A single quick handshake is enough here: the entry setup retries on
        # its own if the service is briefly unavailable later.
        description = await describe_service(host, port, retries=0)
        if description is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    STEP_USER_DATA_SCHEMA, user_input
                ),
                errors={"base": "cannot_connect"},
            )

        return self.async_create_entry(
            title=ENTITY_NAME,
            data={CONF_HOST: host, CONF_PORT: port},
            options={CONF_MAX_DURATION: user_input[CONF_MAX_DURATION]},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> CoachSttOptionsFlow:
        """Return the options flow handler."""
        return CoachSttOptionsFlow()


class CoachSttOptionsFlow(OptionsFlowWithReload):
    """Handle the Coach STT options, i.e. the maximum turn duration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_MAX_DURATION, DEFAULT_MAX_DURATION_SECONDS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_MAX_DURATION, default=current): _DURATION_SELECTOR}
            ),
        )
