"""Set up the Voice Reminders integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

PLATFORMS: list = []


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration without YAML configuration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Voice Reminders config entry."""
    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Voice Reminders config entry."""
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
