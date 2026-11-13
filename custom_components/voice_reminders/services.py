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


def _context_user_id(call):
    return getattr(getattr(call, "context", None), "user_id", None)


async def _require_user(hass, user_id, label):
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError(f"{label} must be a non-blank string")
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise ValueError(f"{label} does not exist: {user_id}")
    return user_id


async def _resolve_recipient(hass, value, label):
    """Resolve a user ID, name, full name, or username to a user ID."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-blank string")
    user = await hass.auth.async_get_user(value)
    if user is not None:
        return user.id

    def normalize(text):
        return " ".join(text.split()).casefold()

    target = normalize(value)
    matches = []
    for user in await hass.auth.async_get_users():
        name = getattr(user, "name", None)
        last_name = getattr(user, "last_name", None)
        username = getattr(user, "username", None)
        candidates = [name, username]
        if name and last_name:
            candidates.append(f"{name} {last_name}")
        if any(isinstance(candidate, str) and normalize(candidate) == target
               for candidate in candidates):
            matches.append(user)
    if not matches:
        raise ValueError(f"{label} does not exist: {value}")
    if len(matches) > 1:
        raise ValueError(f"{label} is ambiguous: {value}")
    return matches[0].id


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
        if "owner_user_id" in data and "owner" in data:
            raise ValueError("provide either owner_user_id or owner, not both")
        if "owner" in data:
            owner = await _resolve_recipient(hass, data["owner"], "owner")
        else:
            owner = _required(data, "owner_user_id")
            await _require_user(hass, owner, "owner_user_id")
        creator = _context_user_id(call) or data.get("created_by_user_id", owner)
        await _require_user(hass, creator, "created_by_user_id")
        date = _parse_date(_required(data, "date"))
        reminder = await manager.async_create(text, owner, creator,
                                              date, data.get("recurrence", "none"))
        return reminder.to_dict()

    async def list_reminders(call: Any) -> dict[str, Any]:
        """List reminders matching the service filters."""
        data = call.data
        if "view" in data:
            view = data["view"]
            if not isinstance(view, str) or view not in {"mine", "created"}:
                raise ValueError(f"invalid view: {view}")
            if "owner" in data or "owner_user_id" in data:
                raise ValueError("provide either view or owner, not both")
            user_id = _context_user_id(call)
            if user_id is None:
                raise ValueError("view requires a calling user")
            await _require_user(hass, user_id, "context user")
            if view == "mine":
                items = await manager.async_list(owner_user_id=user_id, status=data.get("status"))
            else:
                items = await manager.async_list(created_by_user_id=user_id, status=data.get("status"))
                items = [item for item in items if item.owner_user_id != user_id]
            return {"reminders": [item.to_dict() for item in items]}
        if "owner_user_id" in data and "owner" in data:
            raise ValueError("provide either owner_user_id or owner, not both")
        owner = data.get("owner_user_id")
        if "owner" in data:
            owner = await _resolve_recipient(hass, data["owner"], "owner")
        elif owner is not None:
            await _require_user(hass, owner, "owner_user_id")
        items = await manager.async_list(owner, data.get("status"))
        return {"reminders": [item.to_dict() for item in items]}

    async def update(call: Any) -> dict[str, Any]:
        """Update a reminder from service data."""
        data = call.data
        reminder_id = _required(data, "id")
        date = _parse_date(data["date"]) if "date" in data else None
        user_id = _context_user_id(call)
        if user_id is not None:
            await _require_user(hass, user_id, "context user")
        reminder = await manager.async_update(reminder_id, text=data.get("text"), date=date,
                                              recurrence=data.get("recurrence"), status=data.get("status"),
                                              user_id=user_id)
        return reminder.to_dict()

    async def cancel(call: Any) -> dict[str, Any]:
        """Cancel a reminder."""
        user_id = _context_user_id(call)
        if user_id is not None:
            await _require_user(hass, user_id, "context user")
        return (await manager.async_cancel(_required(call.data, "id"), user_id=user_id)).to_dict()

    async def snooze(call: Any) -> dict[str, Any]:
        """Snooze a reminder by delay or to a date."""
        data = call.data
        reminder_id = _required(data, "id")
        date = _parse_date(data["date"]) if "date" in data else None
        user_id = _context_user_id(call)
        if user_id is not None:
            await _require_user(hass, user_id, "context user")
        return (await manager.async_snooze(reminder_id, delay_seconds=data.get("delay"), date=date,
                                           user_id=user_id)).to_dict()

    for name, handler in zip(_SERVICES, (create, list_reminders, update, cancel, snooze)):
        hass.services.async_register(DOMAIN, name, handler)


async def async_unregister_services(hass: Any) -> None:
    """Remove registered reminder management services."""
    for name in _SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
