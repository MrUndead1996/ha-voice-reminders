"""Configuration and options flows for Voice Reminders."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .delivery import (CONF_NOTIFY_TARGETS, CONF_PREANNOUNCE, CONF_SATELLITES, CONF_SNOOZE_INTERVALS,
                       _ENTITY_ID_RE, parse_snooze_intervals, resolve_notify_targets)

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
            satellites = user_input.get(CONF_SATELLITES, "all").strip()
            if satellites and satellites != "all" and any(
                not _ENTITY_ID_RE.fullmatch(part.strip())
                for part in satellites.split(",") if part.strip()
            ):
                errors[CONF_SATELLITES] = "invalid_satellites"
            try:
                resolve_notify_targets(user_input.get(CONF_NOTIFY_TARGETS, ""))
            except ValueError:
                errors[CONF_NOTIFY_TARGETS] = "invalid_notify_targets"
            try:
                parse_snooze_intervals(user_input.get(CONF_SNOOZE_INTERVALS, ""))
            except ValueError:
                errors[CONF_SNOOZE_INTERVALS] = "invalid_snooze_intervals"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        interval = self.config_entry.options.get(
            CONF_INTERVAL, self.config_entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        )
        satellites = self.config_entry.options.get(
            CONF_SATELLITES, self.config_entry.data.get(CONF_SATELLITES, "all")
        )
        preannounce = self.config_entry.options.get(
            CONF_PREANNOUNCE, self.config_entry.data.get(CONF_PREANNOUNCE, "")
        )
        notify_targets = self.config_entry.options.get(
            CONF_NOTIFY_TARGETS, self.config_entry.data.get(CONF_NOTIFY_TARGETS, "")
        )
        snooze_intervals = self.config_entry.options.get(
            CONF_SNOOZE_INTERVALS, self.config_entry.data.get(CONF_SNOOZE_INTERVALS, "")
        )
        schema = vol.Schema({
            vol.Required(CONF_INTERVAL, default=interval): int,
            vol.Optional(CONF_SATELLITES, default=satellites): str,
            vol.Optional(CONF_PREANNOUNCE, default=preannounce): str,
            vol.Optional(CONF_NOTIFY_TARGETS, default=notify_targets): str,
            vol.Optional(CONF_SNOOZE_INTERVALS, default=snooze_intervals): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
