"""Configuration and options flows for Voice Reminders."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .delivery import (CONF_NOTIFY_TARGETS, CONF_PREANNOUNCE, CONF_SATELLITES, CONF_SNOOZE_INTERVALS,
                       parse_snooze_intervals, resolve_notify_targets)

DOMAIN = "voice_reminders"
CONF_NAME = "name"


class VoiceRemindersConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Voice Reminders config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create the options flow for this entry."""
        return VoiceRemindersOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial setup form."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_NAME, default="Voice Reminders"): str})
        )


class VoiceRemindersOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Voice Reminders."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage delivery settings."""
        errors = {}
        if user_input is not None:
            try:
                parse_snooze_intervals(user_input.get(CONF_SNOOZE_INTERVALS, ""))
            except ValueError:
                errors[CONF_SNOOZE_INTERVALS] = "invalid_snooze_intervals"
            if not errors:
                self._options = {**self.config_entry.options, **user_input}
                self._options.pop("all_satellites", None)
                selected = user_input.get(CONF_SATELLITES, [])
                self._options[CONF_SATELLITES] = (
                    "all" if user_input.get("all_satellites") else ",".join(selected) or "none"
                )
                setting = self.config_entry.options.get(
                    CONF_NOTIFY_TARGETS, self.config_entry.data.get(CONF_NOTIFY_TARGETS, "")
                )
                try:
                    self._targets = resolve_notify_targets(setting)
                except ValueError:
                    self._targets = {}
                self._users = [user for user in await self.hass.auth.async_get_users()
                               if not user.system_generated]
                self._user_index = 0
                return await self.async_step_notification()
        satellites = self.config_entry.options.get(
            CONF_SATELLITES, self.config_entry.data.get(CONF_SATELLITES, "all")
        ) or "all"
        selected = [] if satellites in ("all", "none") else [
            part.strip() for part in satellites.split(",") if part.strip()
        ]
        states = {state.entity_id: state for state in self.hass.states.async_all("assist_satellite")}
        choices = [
            {"value": entity_id, "label": (
                f"{states[entity_id].name} ({entity_id})" if entity_id in states else entity_id
            )}
            for entity_id in sorted(set(states) | set(selected))
        ]
        preannounce = self.config_entry.options.get(
            CONF_PREANNOUNCE, self.config_entry.data.get(CONF_PREANNOUNCE, "")
        )
        snooze_intervals = self.config_entry.options.get(
            CONF_SNOOZE_INTERVALS, self.config_entry.data.get(CONF_SNOOZE_INTERVALS, "")
        )
        schema = vol.Schema({
            vol.Optional("all_satellites", default=satellites == "all"): bool,
            vol.Optional(CONF_SATELLITES, default=selected): SelectSelector(
                SelectSelectorConfig(options=choices, multiple=True, mode="list")
            ),
            vol.Optional(CONF_PREANNOUNCE, default=preannounce): str,
            vol.Optional(CONF_SNOOZE_INTERVALS, default=snooze_intervals): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def async_step_notification(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose a notification service for each Home Assistant user."""
        if user_input is not None:
            user = self._users[self._user_index]
            target = user_input["notify_target"]
            if target == "__none__":
                self._targets.pop(user.id, None)
            else:
                self._targets[user.id] = target
            self._user_index += 1

        if self._user_index == len(self._users):
            self._options[CONF_NOTIFY_TARGETS] = ",".join(
                f"{user_id}:{service}" for user_id, service in self._targets.items()
            )
            return self.async_create_entry(title="", data=self._options)

        user = self._users[self._user_index]
        services = set(self.hass.services.async_services().get("notify", {}))
        current = self._targets.get(user.id)
        if current:
            services.add(current)
        choices = [{"value": "__none__", "label": "None"}] + [
            {"value": service, "label": f"notify.{service}"} for service in sorted(services)
        ]
        return self.async_show_form(
            step_id="notification",
            description_placeholders={"user": user.name},
            data_schema=vol.Schema({
                vol.Required("notify_target", default=current or "__none__"):
                    SelectSelector(SelectSelectorConfig(options=choices)),
            }),
        )
