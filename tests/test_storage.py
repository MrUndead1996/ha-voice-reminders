"""Tests for reminder storage without Home Assistant installed."""

import asyncio
import importlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeStore:
    def __init__(self, hass, version, key):
        self.version = version
        self.key = key
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


homeassistant = types.ModuleType("homeassistant")
helpers = types.ModuleType("homeassistant.helpers")
storage_module = types.ModuleType("homeassistant.helpers.storage")
storage_module.Store = FakeStore
homeassistant.helpers = helpers
helpers.storage = storage_module
sys.modules["homeassistant"] = homeassistant
sys.modules["homeassistant.helpers"] = helpers
sys.modules["homeassistant.helpers.storage"] = storage_module
package = types.ModuleType("custom_components.voice_reminders")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "voice_reminders")]
sys.modules["custom_components.voice_reminders"] = package
storage = importlib.import_module("custom_components.voice_reminders.storage")
from custom_components.voice_reminders.models import create_reminder


def make_reminder(text="Take medicine"):
    return create_reminder(text, "owner", "creator", datetime(2026, 1, 2, tzinfo=timezone.utc), "weekly")


def assert_invalid(function, *args):
    try:
        function(*args)
    except ValueError:
        return
    assert False, "expected ValueError"


def test_payload_round_trip():
    reminder = make_reminder()
    reminder.set_status("fired")
    payload = storage.reminders_to_payload([reminder])
    assert payload == {"schema_version": 1, "reminders": [reminder.to_dict()]}
    assert storage.payload_to_reminders(payload) == [reminder]


def test_invalid_payloads():
    for payload in (None, [], {}, {"schema_version": True, "reminders": []},
                    {"schema_version": 2, "reminders": []},
                    {"schema_version": 1}, {"schema_version": 1, "reminders": {}},
                    {"schema_version": 1, "reminders": [None]},
                    {"schema_version": 1, "reminders": [{}]}):
        assert_invalid(storage.payload_to_reminders, payload)


def test_migration():
    entries = [make_reminder().to_dict()]
    payload = {"schema_version": 1, "reminders": entries}
    assert storage.migrate_payload(0, entries) == payload
    assert storage.migrate_payload(1, payload) is payload
    assert_invalid(storage.migrate_payload, 2, payload)
    assert_invalid(storage.migrate_payload, 0, {})
    assert_invalid(storage.migrate_payload, 0, [{}])
    assert_invalid(storage.migrate_payload, 1, {})


def test_store_operations():
    async def run():
        store = storage.ReminderStore(None)
        first = make_reminder()
        second = make_reminder("Call someone")
        assert await store.async_load() == []
        await store.async_save([first])
        assert await store.async_load() == [first]
        await store.async_add(second)
        assert await store.async_load() == [first, second]
        updated = await store.async_update_status(first.id, "done")
        assert updated.status == "done"
        assert (await store.async_load())[0].status == "done"
        try:
            await store.async_update_status("missing", "done")
        except ValueError:
            pass
        else:
            assert False, "expected ValueError"
        assert await store.async_remove(first.id) is True
        assert await store.async_remove(first.id) is False
        assert await store.async_load() == [second]
    asyncio.run(run())


def test_store_migration_hook():
    async def run():
        store = storage._ReminderStore(None, 1, "voice_reminders")
        assert await store._async_migrate_func(0, "voice_reminders", []) == {
            "schema_version": 1, "reminders": []
        }
    asyncio.run(run())
