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
