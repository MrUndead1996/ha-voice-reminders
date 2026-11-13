"""Configuration and options flows for Voice Reminders."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

DOMAIN = "voice_reminders"
CONF_NAME = "name"
CONF_INTERVAL = "interval_minutes"
DEFAULT_INTERVAL = 30


def _schema(interval: int, *, include_name: bool = False) -> vol.Schema:
    """Build a form schema for the requested flow."""
    fields: dict = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default="Voice Reminders")] = str
    fields[vol.Required(CONF_INTERVAL, default=interval)] = int
    return vol.Schema(fields)


def _interval_errors(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the reminder interval."""
    if not 1 <= user_input[CONF_INTERVAL] <= 1440:
        return {CONF_INTERVAL: "invalid_interval"}
    return {}


class VoiceRemindersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Voice Reminders config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create the options flow for this entry."""
        return VoiceRemindersOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial setup form."""
        errors = {}
        if user_input is not None:
            errors = _interval_errors(user_input)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_schema(DEFAULT_INTERVAL, include_name=True), errors=errors
        )


class VoiceRemindersOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Voice Reminders."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the reminder interval."""
        errors = {}
        if user_input is not None:
            errors = _interval_errors(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        interval = self.config_entry.options.get(
            CONF_INTERVAL, self.config_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        )
        return self.async_show_form(step_id="init", data_schema=_schema(interval), errors=errors)
