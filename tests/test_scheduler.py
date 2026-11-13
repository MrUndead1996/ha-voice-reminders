"""Tests for one-shot scheduling without Home Assistant installed."""

import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeStore:
    def __init__(self, hass, version, key):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


schedules = []


def async_at_time(hass, when, action):
    record = {"when": when, "action": action, "cancelled": False}
    schedules.append(record)

    def cancel():
        record["cancelled"] = True

    return cancel


homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
storage_module = types.ModuleType("homeassistant.helpers.storage")
event_module = types.ModuleType("homeassistant.helpers.event")
storage_module.Store = FakeStore
event_module.async_at_time = async_at_time
homeassistant.helpers = helpers
helpers.storage = storage_module
helpers.event = event_module
sys.modules["homeassistant"] = homeassistant
sys.modules["homeassistant.helpers"] = helpers
sys.modules["homeassistant.helpers.storage"] = storage_module
sys.modules["homeassistant.helpers.event"] = event_module
package = types.ModuleType("custom_components.voice_reminders")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "voice_reminders")]
sys.modules["custom_components.voice_reminders"] = package
scheduler_module = importlib.import_module("custom_components.voice_reminders.scheduler")
storage = importlib.import_module("custom_components.voice_reminders.storage")
from custom_components.voice_reminders.models import create_reminder


def reminder(date, recurrence="none"):
    return create_reminder("Reminder", "owner", "creator", date, recurrence)


def future(days=1):
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=days)


def setup():
    schedules.clear()
    store = storage.ReminderStore(None)
    return store


def test_earliest_future_pending():
    async def run():
        store = setup()
        early = reminder(future())
        later = reminder(future(2))
        ignored = reminder(future(0))
        ignored.set_status("done")
        await store.async_save([later, ignored, early])
        scheduler = scheduler_module.ReminderScheduler(None, store)
        await scheduler.async_start()
        assert len(schedules) == 1 and schedules[0]["when"] == early.date
        assert schedules[0]["when"].tzinfo == timezone.utc
    asyncio.run(run())


def test_fire_one_time_and_remaining():
    async def run():
        store = setup()
        first, second = reminder(future()), reminder(future(2))
        await store.async_save([first, second])
        fired = []
        async def on_fire(item):
            fired.append(item.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        await schedules[-1]["action"](first.date)
        assert fired == [first.id]
        assert (await store.async_load())[0].status == "fired"
        assert schedules[-1]["when"] == second.date
        await schedules[-1]["action"](second.date)
        assert len(schedules) == 2
        assert all(item.status == "fired" for item in await store.async_load())
    asyncio.run(run())


def test_fire_recurring_and_one_time_together():
    async def run():
        store = setup()
        date = future()
        recurring, once = reminder(date, "daily"), reminder(date)
        await store.async_save([recurring, once])
        scheduler = scheduler_module.ReminderScheduler(None, store)
        await scheduler.async_start()
        await schedules[-1]["action"](date)
        saved = await store.async_load()
        assert saved[0].status == "pending" and saved[0].date == date + timedelta(days=1)
        assert saved[1].status == "fired"
        assert schedules[-1]["when"] == saved[0].date
    asyncio.run(run())


def test_reschedule_and_convenience_methods():
    async def run():
        store = setup()
        late, early = reminder(future(3)), reminder(future())
        await store.async_add(late)
        scheduler = scheduler_module.ReminderScheduler(None, store)
        await scheduler.async_start()
        await scheduler.async_reschedule()
        assert schedules[0]["cancelled"] and schedules[-1]["when"] == late.date
        await store.async_add(early)
        await scheduler.async_reminder_added(early)
        assert schedules[-2]["cancelled"] and schedules[-1]["when"] == early.date
        await store.async_remove(early.id)
        await scheduler.async_reminder_removed(early.id)
        assert schedules[-2]["cancelled"] and schedules[-1]["when"] == late.date
        await scheduler.async_reminder_updated(late.id)
        assert schedules[-2]["cancelled"] and schedules[-1]["when"] == late.date
        await store.async_remove(late.id)
        await scheduler.async_reminder_removed(late.id)
        assert schedules[-1]["cancelled"] and len(schedules) == 5
    asyncio.run(run())


def test_cancel_and_past_only():
    async def run():
        store = setup()
        await store.async_add(reminder(future()))
        scheduler = scheduler_module.ReminderScheduler(None, store)
        await scheduler.async_start()
        await scheduler.async_cancel()
        await scheduler.async_cancel()
        assert schedules[0]["cancelled"]
        await store.async_save([reminder(future(-1))])
        schedules.clear()
        await scheduler.async_start()
        assert not schedules
    asyncio.run(run())


def test_next_occurrence():
    date = datetime(2025, 1, 31, 12, 30, tzinfo=timezone.utc)
    assert scheduler_module.next_occurrence(date, "monthly") == datetime(2025, 2, 28, 12, 30, tzinfo=timezone.utc)
    assert scheduler_module.next_occurrence(date, "daily") == date + timedelta(days=1)
    assert scheduler_module.next_occurrence(date, "weekly") == date + timedelta(days=7)
    assert scheduler_module.next_occurrence(date, "none") is None
    try:
        scheduler_module.next_occurrence(date, "invalid")
    except ValueError:
        pass
    else:
        assert False, "expected ValueError"
