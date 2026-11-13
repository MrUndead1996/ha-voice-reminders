"""Management operations for reminders."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math

from .models import RECURRENCE_TYPES, Reminder, create_reminder
from .scheduler import ReminderScheduler
from .storage import ReminderStore

DOMAIN = "voice_reminders"
__all__ = ["DOMAIN", "ReminderManager"]


def _validate_date(date: datetime) -> None:
    """Require a timezone-aware datetime strictly in the future."""
    if not isinstance(date, datetime) or date.utcoffset() is None or date <= datetime.now(timezone.utc):
        raise ValueError("date must be timezone-aware and in the future")


def _find(reminders: list[Reminder], reminder_id: str) -> Reminder:
    """Find a reminder or raise an error."""
    for reminder in reminders:
        if reminder.id == reminder_id:
            return reminder
    raise ValueError("reminder not found")


class ReminderManager:
    """Coordinate reminder persistence and scheduler notifications."""

    def __init__(self, store: ReminderStore, scheduler: ReminderScheduler) -> None:
        """Initialize the manager with its store and scheduler."""
        self._store = store
        self._scheduler = scheduler

    async def async_create(self, text: str, owner_user_id: str, created_by_user_id: str,
                           date: datetime, recurrence: str = "none") -> Reminder:
        """Create, persist, and schedule a reminder."""
        _validate_date(date)
        reminder = create_reminder(text, owner_user_id, created_by_user_id, date, recurrence)
        await self._store.async_add(reminder)
        await self._scheduler.async_reminder_added(reminder.id)
        return reminder

    async def async_list(self, owner_user_id: str | None = None,
                         status: str | None = None,
                         created_by_user_id: str | None = None) -> list[Reminder]:
        """Return reminders matching the supplied filters."""
        reminders = await self._store.async_load()
        return [item for item in reminders if (owner_user_id is None or item.owner_user_id == owner_user_id)
                and (status is None or item.status == status)
                and (created_by_user_id is None or item.created_by_user_id == created_by_user_id)]

    async def async_update(self, reminder_id: str, text: str | None = None,
                           date: datetime | None = None, recurrence: str | None = None,
                           status: str | None = None) -> Reminder:
        """Validate and persist the provided changes to a reminder."""
        reminders = await self._store.async_load()
        original = _find(reminders, reminder_id)
        if all(value is None for value in (text, date, recurrence, status)):
            raise ValueError("nothing to update")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise ValueError("text must be a non-blank string")
        if recurrence is not None and (not isinstance(recurrence, str) or recurrence not in RECURRENCE_TYPES):
            raise ValueError("invalid recurrence")
        if date is not None:
            _validate_date(date)
        reminder = replace(original)
        if status is not None:
            reminder.set_status(status)
        if text is not None:
            reminder.text = text
        if date is not None:
            reminder.date = date
        if recurrence is not None:
            reminder.recurrence = recurrence
        reminders[reminders.index(original)] = reminder
        await self._store.async_save(reminders)
        await self._scheduler.async_reminder_updated(reminder_id)
        return reminder

    async def async_cancel(self, reminder_id: str) -> Reminder:
        """Cancel a reminder and notify the scheduler."""
        reminder = await self._store.async_update_status(reminder_id, "cancelled")
        await self._scheduler.async_reminder_updated(reminder_id)
        return reminder

    async def async_snooze(self, reminder_id: str, delay_seconds: int | float | None = None,
                           date: datetime | None = None) -> Reminder:
        """Move a pending reminder to a future date."""
        if (delay_seconds is None) == (date is None):
            raise ValueError("provide exactly one of delay_seconds or date")
        if delay_seconds is not None and (isinstance(delay_seconds, bool)
                or not isinstance(delay_seconds, (int, float))
                or not math.isfinite(delay_seconds) or delay_seconds <= 0):
            raise ValueError("delay_seconds must be a positive number")
        reminders = await self._store.async_load()
        original = _find(reminders, reminder_id)
        if original.status != "pending":
            raise ValueError("only pending reminders can be snoozed")
        try:
            new_date = date if date is not None else original.date + timedelta(seconds=delay_seconds)
        except OverflowError as err:
            raise ValueError("delay_seconds is too large") from err
        _validate_date(new_date)
        reminder = replace(original, date=new_date)
        reminders[reminders.index(original)] = reminder
        await self._store.async_save(reminders)
        await self._scheduler.async_reminder_updated(reminder_id)
        return reminder
