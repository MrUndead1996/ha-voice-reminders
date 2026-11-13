"""Home Assistant services for managing reminders."""
from datetime import datetime
from typing import Any

from .api import DOMAIN, ReminderManager

__all__ = ["async_register_services", "async_unregister_services"]
_SERVICES = ("create", "list", "update", "cancel", "snooze")


def _required(data: dict[str, Any], name: str) -> Any:
    """Return a required field or raise a clear error."""
    if name not in data:
        raise ValueError(f"missing required field: {name}")
    return data[name]


def _parse_date(value: Any) -> datetime:
    """Parse a timezone-aware ISO datetime."""
    if not isinstance(value, str):
        raise ValueError("date must be a timezone-aware ISO datetime string")
    try:
        date = datetime.fromisoformat(value)
    except ValueError as err:
        raise ValueError("date must be a timezone-aware ISO datetime string") from err
    if date.utcoffset() is None:
        raise ValueError("date must be a timezone-aware ISO datetime string")
    return date


async def async_register_services(hass: Any, manager: ReminderManager) -> None:
    """Register reminder management service handlers."""
    async def create(call: Any) -> dict[str, Any]:
        """Create a reminder from service data."""
        data = call.data
        text = _required(data, "text")
        owner = _required(data, "owner_user_id")
        date = _parse_date(_required(data, "date"))
        reminder = await manager.async_create(text, owner, data.get("created_by_user_id", owner),
                                              date, data.get("recurrence", "none"))
        return reminder.to_dict()

    async def list_reminders(call: Any) -> dict[str, Any]:
        """List reminders matching the service filters."""
        items = await manager.async_list(call.data.get("owner_user_id"), call.data.get("status"))
        return {"reminders": [item.to_dict() for item in items]}

    async def update(call: Any) -> dict[str, Any]:
        """Update a reminder from service data."""
        data = call.data
        reminder_id = _required(data, "id")
        date = _parse_date(data["date"]) if "date" in data else None
        reminder = await manager.async_update(reminder_id, text=data.get("text"), date=date,
                                              recurrence=data.get("recurrence"), status=data.get("status"))
        return reminder.to_dict()

    async def cancel(call: Any) -> dict[str, Any]:
        """Cancel a reminder."""
        return (await manager.async_cancel(_required(call.data, "id"))).to_dict()

    async def snooze(call: Any) -> dict[str, Any]:
        """Snooze a reminder by delay or to a date."""
        data = call.data
        reminder_id = _required(data, "id")
        date = _parse_date(data["date"]) if "date" in data else None
        return (await manager.async_snooze(reminder_id, delay_seconds=data.get("delay"), date=date)).to_dict()

    for name, handler in zip(_SERVICES, (create, list_reminders, update, cancel, snooze)):
        hass.services.async_register(DOMAIN, name, handler)


async def async_unregister_services(hass: Any) -> None:
    """Remove registered reminder management services."""
    for name in _SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
