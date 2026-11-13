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


def test_restart_fires_missed_once_and_marks_fired():
    async def run():
        store = setup()
        item = reminder(future(-1))
        await store.async_save([item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
        assert fired == [item.id]
        assert (await store.async_load())[0].status == "fired"
        assert not schedules
    asyncio.run(run())


def test_restart_recurring_advances_past_now():
    async def run():
        store = setup()
        now = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        original = scheduler_module.datetime
        scheduler_module.datetime = FrozenDatetime
        try:
            daily = reminder(now - timedelta(days=3), "daily")
            monthly = reminder(datetime(2025, 1, 31, 12, tzinfo=timezone.utc), "monthly")
            await store.async_save([daily, monthly])
            fired = []
            async def on_fire(value):
                fired.append(value.id)
            await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
            saved = await store.async_load()
            assert fired == [daily.id, monthly.id]
            assert all(item.status == "pending" and item.date > now for item in saved)
            assert saved[1].date == datetime(2025, 2, 28, 12, tzinfo=timezone.utc)
            assert len(schedules) == 1 and schedules[0]["when"] == saved[0].date
        finally:
            scheduler_module.datetime = original
    asyncio.run(run())


def test_restart_restores_future_and_ignores_non_pending():
    async def run():
        store = setup()
        past, early, late = reminder(future(-1)), reminder(future()), reminder(future(2))
        ignored = [reminder(future(-1)) for _ in range(3)]
        for item, status in zip(ignored, ("done", "fired", "cancelled")):
            item.set_status(status)
        await store.async_save([past, late, *ignored, early])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
        assert fired == [past.id]
        assert len(schedules) == 1 and schedules[0]["when"] == early.date
        assert [item.status for item in (await store.async_load())[2:5]] == ["done", "fired", "cancelled"]
    asyncio.run(run())


def test_fire_callback_catchup_skips_elapsed_periods():
    async def run():
        store = setup()
        item = reminder(future(), "daily")
        await store.async_save([item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        now = item.date + timedelta(days=5)
        await schedules[-1]["action"](now)
        saved = (await store.async_load())[0]
        assert fired == [item.id]
        assert saved.status == "pending" and saved.date == now + timedelta(days=1)
        assert schedules[-1]["when"] == saved.date
    asyncio.run(run())


def test_restart_without_on_fire_hook():
    async def run():
        store = setup()
        now = datetime.now(timezone.utc)
        once, recurring = reminder(now - timedelta(days=1)), reminder(now - timedelta(days=3), "daily")
        await store.async_save([once, recurring])
        await scheduler_module.ReminderScheduler(None, store).async_start()
        saved = await store.async_load()
        assert saved[0].status == "fired"
        assert saved[1].status == "pending" and saved[1].date > now
        assert len(schedules) == 1 and schedules[0]["when"] == saved[1].date
    asyncio.run(run())


def test_delivery_failure_does_not_redeliver():
    async def run():
        import logging
        import unittest
        now = datetime.now(timezone.utc)
        for recurrence in ("none", "daily"):
            store = setup()
            item = reminder(now - timedelta(seconds=1), recurrence)
            await store.async_save([item])
            fired = []
            async def on_fire(value):
                fired.append(value.id)
                raise RuntimeError("delivery failed")
            scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
            with unittest.TestCase().assertLogs(scheduler_module.__name__, level=logging.ERROR) as logs:
                await scheduler._async_process_due(now)
            assert f"Failed to deliver reminder {item.id}" in logs.output[0]
            saved = (await store.async_load())[0]
            assert saved.status == ("fired" if recurrence == "none" else "pending")
            if recurrence == "daily":
                assert saved.date > now
            assert fired == [item.id]
            await scheduler._async_process_due(now)
            assert fired == [item.id]
    asyncio.run(run())


class ZonedStore:
    """Keep zoneinfo objects intact while exercising scheduler timezone arithmetic."""
    def __init__(self, items):
        self.items = items

    async def async_load(self):
        return self.items

    async def async_save(self, items):
        self.items = items

    async def async_update_status(self, reminder_id, status):
        item = next(item for item in self.items if item.id == reminder_id)
        item.set_status(status)


def test_dst_one_time_utc_callback():
    from zoneinfo import ZoneInfo
    async def run():
        schedules.clear()
        date = datetime(2025, 3, 30, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        item = reminder(date)
        store = ZonedStore([item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2025, 3, 29, tzinfo=timezone.utc)
        original = scheduler_module.datetime
        scheduler_module.datetime = FrozenDatetime
        try:
            scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
            await scheduler.async_start()
            when = date.astimezone(timezone.utc)
            assert schedules[-1]["when"] == when
            await schedules[-1]["action"](when)
            assert fired == [item.id] and item.status == "fired"
            assert len(schedules) == 1
        finally:
            scheduler_module.datetime = original
    asyncio.run(run())


def test_dst_daily_spring_and_autumn():
    from zoneinfo import ZoneInfo
    async def run():
        berlin = ZoneInfo("Europe/Berlin")
        for month, day, before_offset, after_offset in ((3, 29, 1, 2), (10, 25, 2, 1)):
            schedules.clear()
            date = datetime(2025, month, day, 12, tzinfo=berlin)
            expected = datetime(2025, month, day + 1, 12, tzinfo=berlin)
            item = reminder(date, "daily")
            store = ZonedStore([item])
            fired = []
            async def on_fire(value):
                fired.append(value.id)
            class FrozenDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return date.astimezone(timezone.utc) - timedelta(days=1)
            original = scheduler_module.datetime
            scheduler_module.datetime = FrozenDatetime
            try:
                scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
                await scheduler.async_start()
                await schedules[-1]["action"](date.astimezone(timezone.utc))
                assert fired == [item.id]
                assert date.utcoffset() == timedelta(hours=before_offset)
                assert item.date == expected and item.date.hour == 12
                assert item.date.utcoffset() == timedelta(hours=after_offset)
                assert item.date.astimezone(timezone.utc) - date.astimezone(timezone.utc) == timedelta(hours=24 + before_offset - after_offset)
                assert schedules[-1]["when"] == expected.astimezone(timezone.utc)
            finally:
                scheduler_module.datetime = original
    asyncio.run(run())


def test_dst_reschedule_earliest_utc():
    from zoneinfo import ZoneInfo
    async def run():
        schedules.clear()
        berlin = ZoneInfo("Europe/Berlin")
        utc_item = reminder(datetime(2025, 3, 30, 10, 30, tzinfo=timezone.utc))
        berlin_item = reminder(datetime(2025, 3, 30, 12, tzinfo=berlin))
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2025, 3, 29, tzinfo=timezone.utc)
        original = scheduler_module.datetime
        scheduler_module.datetime = FrozenDatetime
        try:
            for items in ([utc_item, berlin_item], [berlin_item, utc_item]):
                await scheduler_module.ReminderScheduler(None, ZonedStore(items)).async_reschedule()
                assert schedules[-1]["when"] == datetime(2025, 3, 30, 10, tzinfo=timezone.utc)
        finally:
            scheduler_module.datetime = original
    asyncio.run(run())


def test_dst_restart_daily_catchup():
    from zoneinfo import ZoneInfo
    async def run():
        schedules.clear()
        berlin = ZoneInfo("Europe/Berlin")
        now = datetime(2025, 3, 31, 11, tzinfo=timezone.utc)
        item = reminder(datetime(2025, 3, 28, 12, tzinfo=berlin), "daily")
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        original = scheduler_module.datetime
        scheduler_module.datetime = FrozenDatetime
        try:
            await scheduler_module.ReminderScheduler(None, ZonedStore([item]), on_fire).async_start()
            expected = datetime(2025, 4, 1, 12, tzinfo=berlin)
            assert fired == [item.id] and item.date == expected
            assert item.date.hour == 12 and item.date.utcoffset() == timedelta(hours=2)
            assert len(schedules) == 1 and schedules[0]["when"] == expected.astimezone(timezone.utc)
        finally:
            scheduler_module.datetime = original
    asyncio.run(run())


def test_simultaneous_all_recurrences():
    async def run():
        store = setup()
        date = future()
        items = [reminder(date, kind) for kind in ("none", "daily", "weekly", "monthly")]
        ignored = reminder(date)
        ignored.set_status("fired")
        await store.async_save([*items, ignored])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        await schedules[0]["action"](date)
        saved = await store.async_load()
        assert fired == [item.id for item in items] and len(set(fired)) == 4
        assert saved[0].status == "fired" and saved[4].status == "fired"
        for item, kind in zip(saved[1:4], ("daily", "weekly", "monthly")):
            assert item.status == "pending" and item.date == scheduler_module.next_occurrence(date, kind)
        assert len(schedules) == 2 and schedules[1]["when"] == date + timedelta(days=1)
    asyncio.run(run())


def test_seconds_precise_schedule_and_boundary():
    async def run():
        store = setup()
        date = future().replace(second=37, microsecond=123456)
        exact, later = reminder(date), reminder(date + timedelta(seconds=1))
        await store.async_save([exact, later])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        assert schedules[0]["when"] == date.astimezone(timezone.utc)
        assert schedules[0]["when"].second == 37 and schedules[0]["when"].microsecond == 123456
        await scheduler._async_process_due(date)
        assert fired == [exact.id]
        saved = await store.async_load()
        assert [item.status for item in saved] == ["fired", "pending"]
    asyncio.run(run())


def test_seconds_daily_late_tick():
    async def run():
        store = setup()
        date = future().replace(second=12, microsecond=345678)
        item = reminder(date, "daily")
        await store.async_save([item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        tick = date + timedelta(seconds=30)
        await schedules[0]["action"](tick)
        saved = (await store.async_load())[0]
        assert fired == [item.id] and saved.date == date + timedelta(days=1) > tick
        assert len(schedules) == 2 and schedules[1]["when"] == saved.date
    asyncio.run(run())


def test_seconds_simultaneous_ids():
    async def run():
        store = setup()
        date = future().replace(second=42, microsecond=0)
        items = [reminder(date) for _ in range(3)]
        await store.async_save(items)
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
        await schedules[0]["action"](date)
        assert fired == [item.id for item in items] and len(set(fired)) == 3
        assert all(item.status == "fired" for item in await store.async_load())
        assert len(schedules) == 1
    asyncio.run(run())


def test_remove_scheduled_reminder_cancels_callback():
    async def run():
        store = setup()
        early, late = reminder(future()), reminder(future(2))
        await store.async_save([late, early])
        scheduler = scheduler_module.ReminderScheduler(None, store)
        await scheduler.async_start()
        old = schedules[0]
        await store.async_remove(early.id)
        await scheduler.async_reminder_removed(early.id)
        assert old["cancelled"] and len(schedules) == 2
        assert not schedules[1]["cancelled"] and schedules[1]["when"] == late.date
    asyncio.run(run())


def test_cancelled_past_ignored_on_start():
    async def run():
        store = setup()
        item = reminder(future(-1))
        item.set_status("cancelled")
        await store.async_save([item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
        assert fired == [] and schedules == []
        assert (await store.async_load())[0].status == "cancelled"
    asyncio.run(run())


def test_cancel_then_add_creates_working_callback():
    async def run():
        store = setup()
        old_item, new_item = reminder(future(2)), reminder(future())
        await store.async_save([old_item])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        scheduler = scheduler_module.ReminderScheduler(None, store, on_fire)
        await scheduler.async_start()
        old = schedules[0]
        await scheduler.async_cancel()
        await store.async_add(new_item)
        await scheduler.async_reminder_added(new_item)
        assert old["cancelled"] and len(schedules) == 2
        assert schedules[1]["when"] == new_item.date and not schedules[1]["cancelled"]
        await schedules[1]["action"](new_item.date)
        assert fired == [new_item.id]
        assert (await store.async_load())[1].status == "fired"
    asyncio.run(run())


def test_restart_mixed_missed_and_future():
    async def run():
        store = setup()
        now = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)
        once = reminder(now - timedelta(hours=1))
        daily = reminder(now - timedelta(days=3), "daily")
        weekly = reminder(now + timedelta(hours=1), "weekly")
        await store.async_save([once, daily, weekly])
        fired = []
        async def on_fire(value):
            fired.append(value.id)
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        original = scheduler_module.datetime
        scheduler_module.datetime = FrozenDatetime
        try:
            await scheduler_module.ReminderScheduler(None, store, on_fire).async_start()
            saved = await store.async_load()
            assert fired == [once.id, daily.id]
            assert saved[0].status == "fired"
            assert saved[1].status == "pending" and saved[1].date == now + timedelta(days=1)
            assert saved[2].status == "pending" and saved[2].date == weekly.date
            assert len(schedules) == 1 and schedules[0]["when"] == weekly.date
        finally:
            scheduler_module.datetime = original
    asyncio.run(run())
