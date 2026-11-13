"""Set up the Voice Reminders integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .api import DOMAIN, ReminderManager
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
    scheduler = ReminderScheduler(hass, store)
    manager = ReminderManager(store, scheduler)
    await async_register_services(hass, manager)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "store": store, "scheduler": scheduler, "manager": manager
    }
    await scheduler.async_start()
    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Voice Reminders config entry."""
    await async_unregister_services(hass)
    entries = hass.data.get(DOMAIN, {})
    if entry.entry_id in entries:
        await entries[entry.entry_id]["scheduler"].async_cancel()
        entries.pop(entry.entry_id)
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
