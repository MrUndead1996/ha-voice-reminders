"""Standalone tests for Assist intent handlers."""
import asyncio
import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ha = types.ModuleType('homeassistant')
helpers = types.ModuleType('homeassistant.helpers')
intent = types.ModuleType('homeassistant.helpers.intent')
class IntentHandler: pass
class IntentHandleError(Exception): pass
class IntentResponseType(Enum):
    ACTION_DONE = 'action_done'
    QUERY_ANSWER = 'query_answer'
class IntentResponse:
    def __init__(self):
        self.speech = {}
        self.response_type = IntentResponseType.ACTION_DONE
    def async_set_speech(self, text):
        self.speech = {'plain': {'speech': text}}
    def async_set_card(self, title, content):
        self.card = (title, content)
class Intent:
    def __init__(self, hass, slots=None, user=None, language='en'):
        self.hass, self.slots = hass, slots or {}
        self.context = types.SimpleNamespace(user_id=user)
        self.language, self.platform = language, 'test'
    def create_response(self): return IntentResponse()
intent.IntentHandler, intent.IntentHandleError = IntentHandler, IntentHandleError
intent.IntentResponse, intent.IntentResponseType = IntentResponse, IntentResponseType
intent.Intent = Intent
intent.async_register = lambda hass, handler: hass.data.setdefault('intent_helpers', {}).__setitem__(handler.intent_type, handler)
intent.async_remove = lambda hass, kind: hass.data.setdefault('intent_helpers', {}).pop(kind, None)
helpers.intent = intent
for name, module in [('homeassistant', ha), ('homeassistant.helpers', helpers), ('homeassistant.helpers.intent', intent)]:
    sys.modules[name] = module
for name in ('config_entries', 'core', 'helpers.typing', 'helpers.storage', 'helpers.event'):
    key = 'homeassistant.' + name
    if key not in sys.modules: sys.modules[key] = types.ModuleType(key)
sys.modules['homeassistant.helpers.storage'].Store = type('Store', (), {})
sys.modules['homeassistant.helpers.event'].async_at_time = lambda *args: lambda: None
package = types.ModuleType('custom_components.voice_reminders')
package.__path__ = [str(ROOT / 'custom_components/voice_reminders')]
sys.modules['custom_components.voice_reminders'] = package
api = importlib.import_module('custom_components.voice_reminders.api')
intents = importlib.import_module('custom_components.voice_reminders.intents')

class FakeStore:
    def __init__(self): self.data = []
    async def async_load(self): return self.data.copy()
    async def async_save(self, items): self.data = items.copy()
    async def async_add(self, item): self.data.append(item)
    async def async_update_status(self, reminder_id, status):
        for item in self.data:
            if item.id == reminder_id:
                item.set_status(status)
                return item
        raise ValueError('reminder not found')
class FakeScheduler:
    async def async_reminder_added(self, reminder_id): pass
    async def async_reminder_updated(self, reminder_id): pass
class FakeAuth:
    def __init__(self):
        self.users = {name: types.SimpleNamespace(id=name, name=name, username=None, last_name=None) for name in ('alice', 'bob', 'charlie')}
    async def async_get_user(self, user_id): return self.users.get(user_id)
    async def async_get_users(self): return list(self.users.values())
class FakeHass:
    def __init__(self): self.data, self.auth = {}, FakeAuth()
def future(): return datetime.now(timezone.utc) + timedelta(days=1)
def slots(**kwargs): return {key: {'value': value} for key, value in kwargs.items()}
def speech(response): return response.speech['plain']['speech']
async def raises(awaitable, message=None):
    try: await awaitable
    except IntentHandleError as err:
        if message: assert message in str(err), str(err)
    else: assert False, 'expected IntentHandleError'
async def setup():
    hass = FakeHass()
    manager = api.ReminderManager(FakeStore(), FakeScheduler())
    hass.data['voice_reminders'] = {'entry': {'manager': manager}}
    await intents.async_setup_intents(hass)
    async def call(name, user=None, language='en', **values):
        return await hass.data['intent_helpers']['voice_reminders.' + name].async_handle(Intent(hass, slots(**values), user, language))
    return hass, manager, call

def test_registration_and_missing_manager():
    async def run():
        hass, _, call = await setup()
        assert set(hass.data['intent_helpers']) == {'voice_reminders.' + n for n in ('CreateReminder', 'ListReminders', 'CancelReminder', 'SnoozeReminder')}
        hass.data.pop('voice_reminders')
        await raises(call('ListReminders', 'bob'), 'Voice Reminders is not set up')
        await intents.async_remove_intents(hass)
        assert not hass.data['intent_helpers']
    asyncio.run(run())

def test_create():
    async def run():
        _, manager, call = await setup()
        date = future().isoformat()
        assert 'buy milk' in speech(await call('CreateReminder', 'bob', text='buy milk', date=date))
        item = (await manager.async_list())[0]
        assert (item.owner_user_id, item.created_by_user_id) == ('bob', 'bob')
        await call('CreateReminder', 'bob', text='other', date=date, owner='alice')
        assert (await manager.async_list())[-1].owner_user_id == 'alice'
        for values in ({'date': date}, {'text': 'x'}, {'text': 'x', 'date': 'bad'}, {'text': 'x', 'date': (future()-timedelta(days=2)).isoformat()}, {'text': 'x', 'date': date, 'owner': 'unknown'}):
            await raises(call('CreateReminder', 'bob', **values))
        await raises(call('CreateReminder', text='x', date=date), 'a user is required')
    asyncio.run(run())

def test_list():
    async def run():
        _, manager, call = await setup()
        await manager.async_create('later', 'bob', 'bob', future()+timedelta(hours=1))
        await manager.async_create('earlier', 'bob', 'bob', future())
        await manager.async_create('for alice', 'alice', 'bob', future())
        result = await call('ListReminders', 'bob')
        assert result.response_type == IntentResponseType.QUERY_ANSWER
        assert speech(result).index('earlier') < speech(result).index('later') and 'for alice' not in speech(result)
        result = speech(await call('ListReminders', 'bob', view='created'))
        assert 'for alice' in result and 'earlier' not in result
        await raises(call('ListReminders'), 'a user is required')
        await raises(call('ListReminders', 'bob', view='bad'))
    asyncio.run(run())

def test_cancel():
    async def run():
        _, manager, call = await setup()
        item = await manager.async_create('Buy Milk', 'bob', 'alice', future())
        await raises(call('CancelReminder', 'charlie', id=item.id), 'only the recipient')
        assert 'Buy Milk' in speech(await call('CancelReminder', 'bob', id=item.id))
        item = await manager.async_create('Buy   Milk', 'bob', 'alice', future())
        await call('CancelReminder', 'bob', text=' BUY milk ')
        assert item.status == 'cancelled'
        item = await manager.async_create('for bob', 'bob', 'alice', future())
        await call('CancelReminder', 'alice', id=item.id)
        assert item.status == 'cancelled'
        await raises(call('CancelReminder', 'bob', text='missing'), 'reminder not found')
        await raises(call('CancelReminder', 'bob'), 'provide either id or text')
        await manager.async_create('duplicate', 'bob', 'bob', future())
        await manager.async_create('duplicate', 'bob', 'bob', future())
        await raises(call('CancelReminder', 'bob', text='duplicate'), 'reminder is ambiguous')
    asyncio.run(run())

def test_snooze():
    async def run():
        _, manager, call = await setup()
        item = await manager.async_create('task', 'bob', 'alice', future())
        original = item.date
        await call('SnoozeReminder', 'bob', id=item.id, delay=30)
        assert (await manager.async_list())[0].date == original + timedelta(seconds=30)
        await call('SnoozeReminder', 'bob', text='TASK', delay='10 minutes')
        assert (await manager.async_list())[0].date == original + timedelta(seconds=630)
        await raises(call('SnoozeReminder', 'bob', id=item.id), 'delay')
        await raises(call('SnoozeReminder', 'bob', id='unknown', delay=1), 'reminder not found')
        await raises(call('SnoozeReminder', 'charlie', id=item.id, delay=1), 'only the recipient')
        for delay in (True, 0, 'bogus', '1 day'):
            await raises(call('SnoozeReminder', 'bob', id=item.id, delay=delay), 'invalid delay')
        await manager.async_cancel(item.id)
        await raises(call('SnoozeReminder', 'bob', id=item.id, delay=1), 'pending')
    asyncio.run(run())
