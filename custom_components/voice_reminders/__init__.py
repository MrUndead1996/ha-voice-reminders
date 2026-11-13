"""Set up the Voice Reminders integration."""

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from . import intents
from .api import DOMAIN, ReminderManager
from .delivery import (async_delivery_hook, async_register_snooze_actions, CONF_NOTIFY_TARGETS,
                       CONF_PREANNOUNCE, CONF_SATELLITES, CONF_SNOOZE_INTERVALS)
from .services import async_register_services, async_unregister_services
from .scheduler import ReminderScheduler
from .storage import ReminderStore
from .sentence_install import install_sentences

PLATFORMS: list = []
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration without YAML configuration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Voice Reminders config entry."""
    try:
        result = await hass.async_add_executor_job(
            install_sentences, hass.config.config_dir, str(Path(__file__).parent)
        )
    except OSError:
        # Sentence publication is best-effort and must not prevent reminders
        # from working if the HA config directory is read-only.
        _LOGGER.exception("Could not install Russian Assist sentences")
        result = "error"
    if result == "conflict":
        _LOGGER.warning(
            "Russian Assist sentence file %s already exists and is not an unchanged "
            "Voice Reminders file; leaving it untouched. Review/merge it manually. "
            "No sentence changes are active until Home Assistant restarts.",
            Path(hass.config.config_dir) / "custom_sentences" / "ru" / "voice_reminders.yaml",
        )
    elif result in ("created", "updated"):
        _LOGGER.info(
            "Russian Assist sentences %s; restart Home Assistant for changes to load.",
            result,
        )
    store = ReminderStore(hass)
    options = getattr(entry, "options", {})
    data = getattr(entry, "data", {})
    settings = {
        "satellites": options.get(CONF_SATELLITES, data.get(CONF_SATELLITES, "all")),
        "preannounce": options.get(CONF_PREANNOUNCE, data.get(CONF_PREANNOUNCE, "")),
        "notify_targets": options.get(CONF_NOTIFY_TARGETS, data.get(CONF_NOTIFY_TARGETS, "")),
        "snooze_intervals": options.get(CONF_SNOOZE_INTERVALS, data.get(CONF_SNOOZE_INTERVALS, "")),
    }
    scheduler = ReminderScheduler(hass, store, async_delivery_hook(hass, settings))
    manager = ReminderManager(store, scheduler)
    unsub_snooze = async_register_snooze_actions(hass, manager)
    await async_register_services(hass, manager)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "store": store, "scheduler": scheduler, "manager": manager, "unsub_snooze": unsub_snooze
    }
    await intents.async_setup_intents(hass)
    await scheduler.async_start()
    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Voice Reminders config entry."""
    await async_unregister_services(hass)
    await intents.async_remove_intents(hass)
    entries = hass.data.get(DOMAIN, {})
    if entry.entry_id in entries:
        unsub_snooze = entries[entry.entry_id].get("unsub_snooze")
        if unsub_snooze:
            unsub_snooze()
        await entries[entry.entry_id]["scheduler"].async_cancel()
        entries.pop(entry.entry_id)
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
