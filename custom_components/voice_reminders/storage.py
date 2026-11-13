"""Persistent storage for voice reminders."""

from typing import Any

from homeassistant.helpers.storage import Store

from .models import Reminder

STORAGE_KEY = "voice_reminders"
STORAGE_VERSION = 1

__all__ = [
    "STORAGE_KEY", "STORAGE_VERSION", "ReminderStore", "reminders_to_payload",
    "payload_to_reminders", "migrate_payload",
]


def reminders_to_payload(reminders: list[Reminder]) -> dict[str, Any]:
    """Serialize reminders in the current storage envelope.

    Args:
        reminders: Reminders to serialize.

    Returns:
        A versioned, JSON-safe storage envelope.
    """
    return {"schema_version": STORAGE_VERSION, "reminders": [item.to_dict() for item in reminders]}


def payload_to_reminders(payload: Any) -> list[Reminder]:
    """Validate a storage envelope and deserialize its reminders.

    Args:
        payload: Stored data to validate.

    Returns:
        The reminders contained in the envelope.

    Raises:
        ValueError: If the envelope or a reminder is invalid.
    """
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int:
        raise ValueError("invalid storage envelope")
    if payload["schema_version"] != STORAGE_VERSION or not isinstance(payload.get("reminders"), list):
        raise ValueError("invalid storage envelope")
    return [Reminder.from_dict(item) for item in payload["reminders"]]


def migrate_payload(version: int, data: Any) -> dict[str, Any]:
    """Migrate stored data to the current envelope.

    Args:
        version: Version of the stored data.
        data: Stored data to migrate.

    Returns:
        A validated version-one envelope.

    Raises:
        ValueError: If the version or data is invalid.
    """
    if type(version) is not int:
        raise ValueError("unknown storage version")
    if version == 0:
        if not isinstance(data, list):
            raise ValueError("legacy data must be a list")
        payload = {"schema_version": STORAGE_VERSION, "reminders": data}
    elif version == STORAGE_VERSION:
        payload = data
    else:
        raise ValueError("unknown storage version")
    payload_to_reminders(payload)
    return payload


class _ReminderStore(Store):
    """Home Assistant store with reminder data migration."""

    async def _async_migrate_func(self, version: int, key: str, data: Any) -> dict[str, Any]:
        return migrate_payload(version, data)


class ReminderStore:
    """Load and save reminders through Home Assistant storage."""

    def __init__(self, hass: Any) -> None:
        """Initialize the store.

        Args:
            hass: Home Assistant instance.
        """
        self._store = _ReminderStore(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> list[Reminder]:
        """Load reminders, returning an empty list when no data exists."""
        payload = await self._store.async_load()
        return [] if payload is None else payload_to_reminders(payload)

    async def async_save(self, reminders: list[Reminder]) -> None:
        """Save reminders.

        Args:
            reminders: Reminders to persist.
        """
        await self._store.async_save(reminders_to_payload(reminders))

    async def async_add(self, reminder: Reminder) -> None:
        """Append and save a reminder.

        Args:
            reminder: Reminder to add.
        """
        reminders = await self.async_load()
        reminders.append(reminder)
        await self.async_save(reminders)

    async def async_update_status(self, reminder_id: str, status: str) -> Reminder:
        """Update and save a reminder's status.

        Args:
            reminder_id: Identifier of the reminder.
            status: New status.

        Returns:
            The updated reminder.

        Raises:
            ValueError: If the reminder or status is invalid.
        """
        reminders = await self.async_load()
        for reminder in reminders:
            if reminder.id == reminder_id:
                reminder.set_status(status)
                await self.async_save(reminders)
                return reminder
        raise ValueError("reminder not found")

    async def async_remove(self, reminder_id: str) -> bool:
        """Remove and save reminders with the given identifier.

        Args:
            reminder_id: Identifier of the reminder to remove.

        Returns:
            Whether a reminder was removed.
        """
        reminders = await self.async_load()
        remaining = [reminder for reminder in reminders if reminder.id != reminder_id]
        await self.async_save(remaining)
        return len(remaining) != len(reminders)
