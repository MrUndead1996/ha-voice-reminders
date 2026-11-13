"""Standalone tests for satellite reminder delivery."""
import asyncio
import importlib
import logging
import sys
import types
from datetime import datetime, timedelta, timezone

exceptions = types.ModuleType("homeassistant.exceptions")
exceptions.ServiceNotFound = type("ServiceNotFound", (Exception,), {})
sys.modules["homeassistant.exceptions"] = exceptions

delivery = importlib.import_module("custom_components.voice_reminders.delivery")
models = importlib.import_module("custom_components.voice_reminders.models")
scheduler_module = importlib.import_module("custom_components.voice_reminders.scheduler")


class FakeServices:
    """Record service calls and optionally raise an error."""
    def __init__(self):
        self.calls = []
        self.error = None

    async def async_call(self, domain, service, payload, context=None):
        if self.error:
            raise self.error
        self.calls.append((domain, service, payload, context))


class FakeStore:
    """Store reminders for the scheduler."""
    def __init__(self, reminders):
        self.data = reminders

    async def async_load(self):
        return self.data.copy()

    async def async_update_status(self, reminder_id, status):
        for item in self.data:
            if item.id == reminder_id:
                item.set_status(status)


def make_hass():
    """Create a fake Home Assistant instance."""
    registry = types.SimpleNamespace(entities={"assist_satellite.z": None,
        "light.one": None, "assist_satellite.a": None})
    return types.SimpleNamespace(entity_registry=registry, services=FakeServices())


def test_resolve_satellites():
    hass = make_hass()
    expected = ["assist_satellite.a", "assist_satellite.z"]
    for setting in ("all", "", "  ", None):
        assert delivery.resolve_satellites(hass, setting) == expected
    assert delivery.resolve_satellites(hass, " x.y, assist_satellite.a, x.y,, ") == [
        "x.y", "assist_satellite.a"]
    for value in ("bad id", "no_dot", "UPPER.x"):
        try:
            delivery.resolve_satellites(hass, value)
        except ValueError as err:
            assert str(err) == f"invalid satellite entity_id: {value}"
        else:
            assert False, "expected ValueError"
    hass.entity_registry = None
    assert delivery.resolve_satellites(hass, "all") == []


def test_announce_payload_and_missing_service():
    async def run():
        hass = make_hass()
        reminder = types.SimpleNamespace(text="Take medicine")
        assert await delivery.async_announce(hass, reminder, ["assist_satellite.a"], "  Hello  ")
        assert hass.services.calls[-1] == ("tts", "speak", {"entity_id": ["assist_satellite.a"],
            "text": "Take medicine", "announce": True, "preannounce": "Hello"}, None)
        for value in (None, "", "  "):
            assert await delivery.async_announce(hass, reminder, ["assist_satellite.a"], value)
            assert "preannounce" not in hass.services.calls[-1][2]
        assert not await delivery.async_announce(hass, reminder, [])
        hass.services.error = exceptions.ServiceNotFound("missing")
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            assert not await delivery.async_announce(hass, reminder, ["assist_satellite.a"])
    asyncio.run(run())


def test_delivery_hook_and_scheduler():
    async def run():
        hass = make_hass()
        settings = {"satellites": "not an id"}
        hook = delivery.async_delivery_hook(hass, settings)
        now = datetime.now(timezone.utc)
        reminder = models.create_reminder("Due", "owner", "owner", now - timedelta(seconds=1))
        await hook(reminder)
        assert not hass.services.calls
        settings["satellites"] = "assist_satellite.a"
        hass.services.error = RuntimeError("failed")
        await hook(reminder)
        hass.services.error = None
        settings["preannounce"] = "Attention"
        store = FakeStore([reminder])
        scheduler = scheduler_module.ReminderScheduler(hass, store, on_fire=hook)
        await scheduler._async_process_due(now)
        assert hass.services.calls[-1][2] == {"entity_id": ["assist_satellite.a"],
            "text": "Due", "announce": True, "preannounce": "Attention"}
        assert reminder.status == "fired"
    asyncio.run(run())


def test_resolve_notify_targets():
    for setting in (None, "", "  , "):
        assert delivery.resolve_notify_targets(setting) == {}
    assert delivery.resolve_notify_targets(
        " user-1 : notify.mobile_app_anna, other_2:phone, user-1 : replacement ,,"
    ) == {"user-1": "replacement", "other_2": "phone"}
    for value in ("missing", ":phone", "user:", "bad user:phone", "user:Bad", "user:notify.", "user:a:b"):
        try:
            delivery.resolve_notify_targets(value)
        except ValueError as err:
            assert str(err) == f"invalid notify target: {value}"
        else:
            assert False, "expected ValueError"


def test_notify_payload_and_missing_service():
    async def run():
        hass = make_hass()
        reminder = types.SimpleNamespace(text="Take medicine")
        assert await delivery.async_notify(hass, reminder, "mobile_app_anna")
        assert hass.services.calls[-1] == ("notify", "mobile_app_anna",
            {"message": "Take medicine", "title": "Reminder"}, None)
        hass.services.error = exceptions.ServiceNotFound("missing")
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            assert not await delivery.async_notify(hass, reminder, "mobile_app_anna")
    asyncio.run(run())


def test_delivery_hook_personal_notifications():
    async def run():
        hass = make_hass()
        settings = {"satellites": "assist_satellite.a", "notify_targets": "owner:notify.phone"}
        hook = delivery.async_delivery_hook(hass, settings)
        reminder = types.SimpleNamespace(text="Due", owner_user_id="owner")
        await hook(reminder)
        assert [call[:2] for call in hass.services.calls] == [("tts", "speak"), ("notify", "phone")]
        hass.services.calls.clear()
        reminder.owner_user_id = "other"
        await hook(reminder)
        assert [call[:2] for call in hass.services.calls] == [("tts", "speak")]
        hass.services.calls.clear()
        settings["notify_targets"] = "invalid"
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            await hook(reminder)
        assert [call[:2] for call in hass.services.calls] == [("tts", "speak")]
        hass.services.calls.clear()
        settings["notify_targets"] = "owner:phone"
        reminder.owner_user_id = "owner"
        original_call = hass.services.async_call
        async def missing_notify(domain, service, payload, context=None):
            if domain == "notify":
                raise exceptions.ServiceNotFound("missing")
            await original_call(domain, service, payload, context=context)
        hass.services.async_call = missing_notify
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            await hook(reminder)
        assert [call[:2] for call in hass.services.calls] == [("tts", "speak")]
        hass.services.calls.clear()
        settings["satellites"] = "invalid satellite"
        hass.services.async_call = original_call
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            await hook(reminder)
        assert [call[:2] for call in hass.services.calls] == [("notify", "phone")]
    asyncio.run(run())


def test_parse_snooze_intervals():
    for value in (None, "", " ", ", ,"):
        assert delivery.parse_snooze_intervals(value) == []
    assert delivery.parse_snooze_intervals("10, 60,10 , 1440") == [10, 60, 1440]
    for value in ("0", "-5", "abc", "1.5", "True-like"):
        try:
            delivery.parse_snooze_intervals(value)
        except ValueError as err:
            assert str(err) == f"invalid snooze interval: {value}"
        else:
            assert False, "expected ValueError"
    try:
        delivery.parse_snooze_intervals("1,2,3,4,5,6")
    except ValueError as err:
        assert str(err) == "too many snooze intervals"
    else:
        assert False, "expected ValueError"


def test_notify_snooze_actions():
    import json
    async def run():
        hass = make_hass()
        reminder = types.SimpleNamespace(id="uuid", text="Due")
        assert await delivery.async_notify(hass, reminder, "phone", [10, 60])
        payloads = [call[2] for call in hass.services.calls]
        assert payloads == [{"message": "Due", "title": "Reminder"}] + [
            {"message": "Due", "title": f"Snooze {minutes} min",
             "action": delivery.SNOOZE_ACTION_PREFIX,
             "action_data": json.dumps({"reminder_id": "uuid", "delay_minutes": minutes})}
            for minutes in (10, 60)]
        for intervals in (None, []):
            hass.services.calls.clear()
            assert await delivery.async_notify(hass, reminder, "phone", intervals)
            assert len(hass.services.calls) == 1
        hass.services.calls.clear()
        original = hass.services.async_call
        async def missing_snooze(domain, service, payload, context=None):
            if payload["title"].startswith("Snooze"):
                raise exceptions.ServiceNotFound("missing")
            await original(domain, service, payload, context=context)
        hass.services.async_call = missing_snooze
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
            assert not await delivery.async_notify(hass, reminder, "phone", [10, 60])
        assert len(hass.services.calls) == 1
    asyncio.run(run())


def test_snooze_action_handler():
    import json
    async def run():
        hass = make_hass()
        listeners = {}
        unsub = lambda: None
        hass.events = types.SimpleNamespace(async_listen=lambda name, handler: (listeners.update({name: handler}) or unsub))
        calls = []
        async def snooze(reminder_id, **kwargs):
            calls.append((reminder_id, kwargs))
        manager = types.SimpleNamespace(async_snooze=snooze)
        assert delivery.async_register_snooze_actions(hass, manager) is unsub
        handler = listeners["mobile_app_notification_action"]
        async def event(action, data):
            await handler(types.SimpleNamespace(data={"action": action, "action_data": data}))
        action = delivery.SNOOZE_ACTION_PREFIX
        await event(action, json.dumps({"reminder_id": "id1", "delay_minutes": 10}))
        await event(action, {"reminder_id": "id2", "delay_minutes": 2})
        await event("other", {})
        assert calls == [("id1", {"delay_seconds": 600}), ("id2", {"delay_seconds": 120})]
        for data in ({}, "bad json", {"reminder_id": "id", "delay_minutes": 0},
                     {"reminder_id": 1, "delay_minutes": 1},
                     {"reminder_id": "id", "delay_minutes": True}):
            with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING):
                await event(action, data)
        assert len(calls) == 2
        async def fail(*args, **kwargs):
            raise ValueError("missing")
        manager.async_snooze = fail
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING) as logs:
            await event(action, {"reminder_id": "unknown", "delay_minutes": 1})
        assert "unknown" in logs.output[0]
    asyncio.run(run())


def test_delivery_hook_snooze_buttons():
    async def run():
        hass = make_hass()
        settings = {"satellites": "assist_satellite.a", "notify_targets": "owner:phone",
                    "snooze_intervals": "10, 60"}
        reminder = types.SimpleNamespace(id="uuid", text="Due", owner_user_id="owner")
        hook = delivery.async_delivery_hook(hass, settings)
        await hook(reminder)
        assert [call[2].get("title") for call in hass.services.calls] == [None, "Reminder", "Snooze 10 min", "Snooze 60 min"]
        hass.services.calls.clear()
        settings["snooze_intervals"] = "bad"
        with __import__("unittest").TestCase().assertLogs(delivery.__name__, level=logging.WARNING) as logs:
            await hook(reminder)
        assert "Invalid snooze interval settings" in logs.output[0]
        assert len(hass.services.calls) == 2
        hass.services.calls.clear()
        settings["snooze_intervals"] = ""
        await hook(reminder)
        assert len(hass.services.calls) == 2
    asyncio.run(run())
