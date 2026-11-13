"""Set up the Voice Reminders integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from . import intents
from .api import DOMAIN, ReminderManager
from .delivery import async_delivery_hook, CONF_PREANNOUNCE, CONF_SATELLITES
from .services import async_register_services, async_unregister_services
from .scheduler import ReminderScheduler
from .storage import ReminderStore

PLATFORMS: list = []


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration without YAML configuration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Voice Reminders config entry."""
    store = ReminderStore(hass)
    options = getattr(entry, "options", {})
    data = getattr(entry, "data", {})
    settings = {
        "satellites": options.get(CONF_SATELLITES, data.get(CONF_SATELLITES, "all")),
        "preannounce": options.get(CONF_PREANNOUNCE, data.get(CONF_PREANNOUNCE, "")),
    }
    scheduler = ReminderScheduler(hass, store, async_delivery_hook(hass, settings))
    manager = ReminderManager(store, scheduler)
    await async_register_services(hass, manager)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "store": store, "scheduler": scheduler, "manager": manager
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
        await entries[entry.entry_id]["scheduler"].async_cancel()
        entries.pop(entry.entry_id)
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
