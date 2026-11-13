"""Schedule reminder delivery using one-shot Home Assistant callbacks."""

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .models import Reminder
from .storage import ReminderStore

_LOGGER = logging.getLogger(__name__)

__all__ = ["next_occurrence", "ReminderScheduler"]


def next_occurrence(date: datetime, recurrence: str) -> datetime | None:
    """Return the next occurrence, preserving the original time and timezone.

    Monthly dates are clamped to the last day of the next month. Raise
    ValueError for an unsupported recurrence.
    """
    if recurrence == "none":
        return None
    if recurrence == "daily":
        return date + timedelta(days=1)
    if recurrence == "weekly":
        return date + timedelta(days=7)
    if recurrence == "monthly":
        year = date.year + (date.month == 12)
        month = date.month % 12 + 1
        return date.replace(year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1]))
    raise ValueError("invalid recurrence")


class ReminderScheduler:
    """Maintain a single callback for the earliest future pending reminder."""

    def __init__(self, hass: Any, store: ReminderStore,
                 on_fire: Callable[[Reminder], Awaitable[None]] | None = None) -> None:
        """Initialize the scheduler with storage and an optional delivery hook."""
        self._hass = hass
        self._store = store
        self._on_fire = on_fire
        self._cancel: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """Process missed reminders and schedule the next future reminder."""
        await self._async_process_due(datetime.now(timezone.utc))
        await self.async_reschedule()

    async def async_reschedule(self) -> None:
        """Replace the current callback with one for the earliest future reminder."""
        await self.async_cancel()
        reminders = await self._store.async_load()
        now = datetime.now(timezone.utc)
        future = [item.date for item in reminders if item.status == "pending" and item.date > now]
        if future:
            from homeassistant.helpers.event import async_at_time

            async def fire(when: datetime) -> None:
                """Process reminders due at the callback time."""
                self._cancel = None
                await self._async_fire(when)

            self._cancel = async_at_time(self._hass, min(future).astimezone(timezone.utc), fire)

    async def async_cancel(self) -> None:
        """Cancel the scheduled callback, if any."""
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    async def _async_fire(self, now: datetime) -> None:
        """Deliver due reminders, persist their next state, and reschedule."""
        await self._async_process_due(now)
        await self.async_reschedule()

    async def _async_process_due(self, now: datetime) -> None:
        """Deliver each due reminder once and persist its next state."""
        reminders = await self._store.async_load()
        recurring_changed = False
        for reminder in reminders:
            if reminder.status != "pending" or reminder.date > now:
                continue
            if self._on_fire is not None:
                try:
                    await self._on_fire(reminder)
                except Exception:
                    _LOGGER.exception("Failed to deliver reminder %s", reminder.id)
            if reminder.recurrence == "none":
                await self._store.async_update_status(reminder.id, "fired")
                reminder.set_status("fired")
            else:
                while reminder.date <= now:
                    reminder.date = next_occurrence(reminder.date, reminder.recurrence)
                recurring_changed = True
        if recurring_changed:
            await self._store.async_save(reminders)

    async def async_reminder_added(self, reminder: Reminder) -> None:
        """Reschedule after a reminder has been added to storage."""
        await self.async_reschedule()

    async def async_reminder_removed(self, reminder_id: str) -> None:
        """Reschedule after a reminder has been removed from storage."""
        await self.async_reschedule()

    async def async_reminder_updated(self, reminder_id: str) -> None:
        """Reschedule after a reminder has been updated in storage."""
        await self.async_reschedule()
