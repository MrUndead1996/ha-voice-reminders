"""Standalone tests for reminder management and services."""
import asyncio
import importlib
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
homeassistant = types.ModuleType('homeassistant')
helpers = types.ModuleType('homeassistant.helpers')
config_entries = types.ModuleType('homeassistant.config_entries')
core = types.ModuleType('homeassistant.core')
typing_module = types.ModuleType('homeassistant.helpers.typing')
storage_module = types.ModuleType('homeassistant.helpers.storage')
event_module = types.ModuleType('homeassistant.helpers.event')
intent_module = types.ModuleType('homeassistant.helpers.intent')
intent_module.IntentHandler = type('IntentHandler', (), {})
intent_module.IntentHandleError = type('IntentHandleError', (Exception,), {})
intent_module.async_register = lambda hass, handler: hass.data.setdefault('intent_helpers', {}).__setitem__(handler.intent_type, handler)
intent_module.async_remove = lambda hass, kind: hass.data.setdefault('intent_helpers', {}).pop(kind, None)
helpers.intent = intent_module
config_entries.ConfigEntry = type('ConfigEntry', (), {})
core.HomeAssistant = type('HomeAssistant', (), {})
typing_module.ConfigType = dict

class FakeStore:
    def __init__(self, *args):
        self.data = []
    async def async_load(self):
        return self.data.copy()
    async def async_save(self, items):
        self.data = items.copy()
    async def async_add(self, item):
        self.data.append(item)
    async def async_update_status(self, reminder_id, status):
        for item in self.data:
            if item.id == reminder_id:
                item.set_status(status)
                return item
        raise ValueError('reminder not found')

class FakeHAStore:
    def __init__(self, *args):
        self.data = None
    async def async_load(self):
        return self.data
    async def async_save(self, data):
        self.data = data

storage_module.Store = FakeHAStore
event_module.async_at_time = lambda *args: lambda: None
for name, module in [('homeassistant', homeassistant), ('homeassistant.helpers', helpers),
                     ('homeassistant.config_entries', config_entries), ('homeassistant.core', core),
                     ('homeassistant.helpers.typing', typing_module),
                     ('homeassistant.helpers.storage', storage_module), ('homeassistant.helpers.event', event_module),
                     ('homeassistant.helpers.intent', intent_module)]:
    sys.modules[name] = module
package = types.ModuleType('custom_components.voice_reminders')
package.__path__ = [str(ROOT / 'custom_components/voice_reminders')]
sys.modules['custom_components.voice_reminders'] = package
api = importlib.import_module('custom_components.voice_reminders.api')
services = importlib.import_module('custom_components.voice_reminders.services')

class FakeScheduler:
    def __init__(self, *args):
        self.calls = []
    async def async_reminder_added(self, reminder_id):
        self.calls.append(('added', reminder_id))
    async def async_reminder_updated(self, reminder_id):
        self.calls.append(('updated', reminder_id))
    async def async_reminder_removed(self, reminder_id):
        self.calls.append(('removed', reminder_id))
    async def async_start(self):
        pass
    async def async_cancel(self):
        pass
    async def async_reschedule(self):
        pass

class FakeServices:
    def __init__(self):
        self.handlers = {}
    def async_register(self, domain, name, handler):
        self.handlers[domain, name] = handler
    def async_remove(self, domain, name):
        del self.handlers[domain, name]
    def has_service(self, domain, name):
        return (domain, name) in self.handlers

class FakeAuth:
    def __init__(self, user_ids):
        self.users = {user_id: types.SimpleNamespace(id=user_id, name=user_id, last_name=None, username=None)
                      for user_id in user_ids}
    async def async_get_user(self, user_id):
        return self.users.get(user_id)
    async def async_get_users(self):
        return list(self.users.values())

class FakeHass:
    def __init__(self):
        self.data = {}
        self.services = FakeServices()
        self.auth = FakeAuth({"a", "alice", "bob"})

class FakeServiceCall:
    def __init__(self, data, context=None):
        self.data = data
        self.context = context

def future():
    return datetime.now(timezone.utc) + timedelta(days=1)

async def raises(awaitable, message=None):
    try:
        await awaitable
    except ValueError as err:
        if message is not None:
            assert message in str(err), str(err)
    else:
        assert False, 'expected ValueError'

def test_manager_create_and_list():
    async def run():
        store, scheduler = FakeStore(), FakeScheduler()
        manager = api.ReminderManager(store, scheduler)
        a = await manager.async_create('first', 'alice', 'alice', future())
        b = await manager.async_create('second', 'bob', 'alice', future(), 'daily')
        b.set_status('done')
        assert scheduler.calls == [('added', a.id), ('added', b.id)]
        assert await manager.async_list(owner_user_id='alice') == [a]
        assert await manager.async_list(status='done') == [b]
        assert await manager.async_list(created_by_user_id='alice') == [a, b]
        assert await manager.async_list(owner_user_id='alice', status='done') == []
        for date in (datetime.now(), datetime.now(timezone.utc) - timedelta(seconds=1)):
            await raises(manager.async_create('x', 'a', 'a', date), 'date must be timezone-aware and in the future')
        await raises(manager.async_create('x', 'a', 'a', future(), 'bad'))
    asyncio.run(run())

def test_manager_update_cancel():
    async def run():
        store, scheduler = FakeStore(), FakeScheduler()
        manager = api.ReminderManager(store, scheduler)
        item = await manager.async_create('first', 'a', 'a', future())
        date = future() + timedelta(days=1)
        updated = await manager.async_update(item.id, text='new', date=date, recurrence='weekly', status='done')
        assert (updated.text, updated.date, updated.recurrence, updated.status) == ('new', date, 'weekly', 'done')
        for fields in ({}, {'text': ' '}, {'recurrence': 'bad'}, {'status': 'bad'},
                       {'date': datetime.now()}, {'date': datetime.now(timezone.utc) - timedelta(days=1)}):
            await raises(manager.async_update(item.id, **fields))
        await raises(manager.async_update('missing', text='x'), 'reminder not found')
        assert (await manager.async_cancel(item.id)).status == 'cancelled'
        assert scheduler.calls[-1] == ('updated', item.id)
        await raises(manager.async_cancel('missing'), 'reminder not found')
    asyncio.run(run())

def test_manager_snooze():
    async def run():
        store, scheduler = FakeStore(), FakeScheduler()
        manager = api.ReminderManager(store, scheduler)
        item = await manager.async_create('x', 'a', 'a', future())
        initial = item.date
        assert (await manager.async_snooze(item.id, delay_seconds=60)).date == initial + timedelta(seconds=60)
        date = future() + timedelta(days=3)
        assert (await manager.async_snooze(item.id, date=date)).date == date
        assert scheduler.calls[-1] == ('updated', item.id)
        for kwargs in ({}, {'date': date, 'delay_seconds': 1}, {'delay_seconds': 0},
                       {'delay_seconds': -1}, {'delay_seconds': True}, {'delay_seconds': '2'},
                       {'date': datetime.now()}, {'date': datetime.now(timezone.utc) - timedelta(days=1)}):
            await raises(manager.async_snooze(item.id, **kwargs))
        await manager.async_cancel(item.id)
        await raises(manager.async_snooze(item.id, delay_seconds=1), 'only pending reminders can be snoozed')
        await raises(manager.async_snooze('missing', delay_seconds=1), 'reminder not found')
    asyncio.run(run())

def test_services():
    async def run():
        hass = FakeHass()
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        await services.async_register_services(hass, manager)
        assert set(name for domain, name in hass.services.handlers) == {'create', 'list', 'update', 'cancel', 'snooze'}
        async def call(name, data):
            return await hass.services.handlers['voice_reminders', name](FakeServiceCall(data))
        date = future().isoformat()
        created = await call('create', {'text': 'x', 'owner_user_id': 'a', 'date': date})
        assert created['created_by_user_id'] == 'a' and created['date'] == date
        assert (await call('list', {}))['reminders'] == [created]
        assert (await call('update', {'id': created['id'], 'text': 'new'}))['text'] == 'new'
        assert (await call('snooze', {'id': created['id'], 'delay': 60}))['date'] != date
        assert (await call('cancel', {'id': created['id']}))['status'] == 'cancelled'
        await raises(call('create', {}), 'missing required field: text')
        for value in ('bad', '2025-01-01T12:00:00', 123, None):
            await raises(call('create', {'text': 'x', 'owner_user_id': 'a', 'date': value}), 'date')
        await raises(call('update', {'id': created['id'], 'date': '2025-01-01T12:00:00'}), 'date')
        await services.async_unregister_services(hass)
        assert not hass.services.handlers
    asyncio.run(run())

def test_services_user_context():
    async def run():
        hass = FakeHass()
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        await services.async_register_services(hass, manager)
        async def call(name, data, context=None):
            return await hass.services.handlers['voice_reminders', name](FakeServiceCall(data, context))
        data = {'text': 'x', 'owner_user_id': 'bob', 'date': future().isoformat()}
        alice = types.SimpleNamespace(user_id='alice')
        ghost = types.SimpleNamespace(user_id='ghost')
        created = await call('create', data, alice)
        assert created['created_by_user_id'] == 'alice'
        await raises(call('create', {**data, 'owner_user_id': 'ghost'}), 'does not exist')
        await raises(call('create', data, ghost), 'does not exist')
        await raises(call('list', {'owner_user_id': 'ghost'}), 'does not exist')
        assert (await call('list', {'owner_user_id': 'bob'}))['reminders'] == [created]
        assert (await call('list', {'owner_user_id': 'alice'}))['reminders'] == []
        for name, fields in [('update', {'text': 'new'}), ('snooze', {'delay': 60}), ('cancel', {})]:
            args = {'id': created['id'], **fields}
            await raises(call(name, args, ghost), 'does not exist')
            await call(name, args)
    asyncio.run(run())

def test_services_personal_lists():
    async def run():
        hass = FakeHass()
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        await services.async_register_services(hass, manager)
        async def call(name, data, context=None):
            return await hass.services.handlers['voice_reminders', name](FakeServiceCall(data, context))
        alice = types.SimpleNamespace(user_id='alice')
        bob = types.SimpleNamespace(user_id='bob')
        ghost = types.SimpleNamespace(user_id='ghost')
        data = {'text': 'x', 'date': future().isoformat()}
        own = await call('create', {**data, 'owner_user_id': 'alice'}, alice)
        for_bob = await call('create', {**data, 'owner_user_id': 'bob'}, alice)
        from_bob = await call('create', {**data, 'owner_user_id': 'alice'}, bob)
        assert (await call('list', {'view': 'mine'}, alice))['reminders'] == [own, from_bob]
        assert (await call('list', {'view': 'created'}, alice))['reminders'] == [for_bob]
        await call('cancel', {'id': own['id']}, alice)
        assert (await call('list', {'view': 'mine', 'status': 'pending'}, alice))['reminders'] == [from_bob]
        assert (await call('list', {'view': 'created', 'status': 'pending'}, alice))['reminders'] == [for_bob]
        for view in ('mine', 'created'):
            await raises(call('list', {'view': view}), 'view requires a calling user')
        await raises(call('list', {'view': 'mine'}, ghost), 'does not exist')
        for view in ('bad', None, []):
            await raises(call('list', {'view': view}, alice), 'invalid view')
        for key in ('owner', 'owner_user_id'):
            await raises(call('list', {'view': 'mine', key: 'bob'}, alice), 'not both')
        assert (await call('list', {'owner': 'bob'}))['reminders'] == [for_bob]
    asyncio.run(run())

def test_services_recipient_by_name():
    async def run():
        hass = FakeHass()
        hass.auth.users['bob'] = types.SimpleNamespace(id='bob', name='Аня', last_name='Иванова', username='AnyAlias')
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        await services.async_register_services(hass, manager)
        async def call(name, data, context=None):
            return await hass.services.handlers['voice_reminders', name](FakeServiceCall(data, context))
        data = {'text': 'x', 'date': future().isoformat()}
        created = await call('create', {**data, 'owner': 'Аня'}, types.SimpleNamespace(user_id='alice'))
        assert created['owner_user_id'] == 'bob' and created['created_by_user_id'] == 'alice'
        for value in ('anyalias', '  аНя   иВаНоВа  ', 'bob'):
            result = await call('create', {**data, 'owner': value})
            assert result['owner_user_id'] == 'bob' and result['created_by_user_id'] == 'bob'
        await raises(call('create', {**data, 'owner': 'unknown'}), 'owner does not exist: unknown')
        for value in ('  ', None, 123):
            await raises(call('create', {**data, 'owner': value}), 'owner must be a non-blank string')
        await raises(call('create', data), 'missing required field: owner_user_id')
        await raises(call('create', {**data, 'owner': 'Аня', 'owner_user_id': 'bob'}), 'not both')
        assert len((await call('list', {'owner': ' ANYALIAS '}))['reminders']) == 4
        await raises(call('list', {'owner': 'unknown'}), 'does not exist')
        await raises(call('list', {'owner': ''}), 'non-blank')
        await raises(call('list', {'owner': 'Аня', 'owner_user_id': 'bob'}), 'not both')
        hass.auth.users['another'] = types.SimpleNamespace(id='another', name='Аня', last_name=None, username=None)
        await raises(call('create', {**data, 'owner': 'аня'}), 'owner is ambiguous: аня')
        await raises(call('list', {'owner': 'Аня'}), 'ambiguous')
        assert (await call('create', {**data, 'owner': 'bob'}))['owner_user_id'] == 'bob'
    asyncio.run(run())

def test_setup_and_unload():
    async def run():
        spec = importlib.util.spec_from_file_location('voice_reminders_setup_test', ROOT / 'custom_components/voice_reminders/__init__.py', submodule_search_locations=[str(ROOT / 'custom_components/voice_reminders')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.ReminderStore, module.ReminderScheduler = FakeStore, FakeScheduler
        hass = FakeHass()
        listeners = {}
        def listen(name, handler):
            listeners[name] = handler
            return lambda: listeners.pop(name)
        hass.events = types.SimpleNamespace(async_listen=listen)
        entry = types.SimpleNamespace(entry_id='entry')
        assert await module.async_setup_entry(hass, entry)
        assert 'mobile_app_notification_action' in listeners
        assert len(hass.services.handlers) == 5
        assert len(hass.data['intent_helpers']) == 4
        assert isinstance(hass.data['voice_reminders']['entry']['manager'], module.ReminderManager)
        assert await module.async_unload_entry(hass, entry)
        assert not hass.services.handlers and not hass.data['voice_reminders']
        assert not hass.data['intent_helpers']
        assert not listeners
    asyncio.run(run())

def test_services_access_rules():
    async def run():
        hass = FakeHass()
        hass.auth.users['charlie'] = types.SimpleNamespace(id='charlie')
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        await services.async_register_services(hass, manager)
        async def call(name, data, context=None):
            return await hass.services.handlers['voice_reminders', name](FakeServiceCall(data, context))
        alice, bob, charlie = (types.SimpleNamespace(user_id=user) for user in ('alice', 'bob', 'charlie'))
        async def create(owner):
            return await call('create', {'text': 'x', 'owner_user_id': owner, 'date': future().isoformat()}, alice)
        item = await create('bob')
        for context, operations in ((alice, ('update', 'snooze')), (charlie, ('update', 'snooze', 'cancel'))):
            for name in operations:
                fields = {'update': {'text': 'new'}, 'snooze': {'delay': 60}, 'cancel': {}}[name]
                await raises(call(name, {'id': item['id'], **fields}, context),
                             {'update': 'only the recipient can update this reminder',
                              'snooze': 'only the recipient can snooze this reminder',
                              'cancel': 'only the recipient or the creator can cancel this reminder'}[name])
        assert (await call('update', {'id': item['id'], 'text': 'bob'}, bob))['text'] == 'bob'
        assert (await call('snooze', {'id': item['id'], 'delay': 60}, bob))['date'] != item['date']
        assert (await call('cancel', {'id': item['id']}, bob))['status'] == 'cancelled'
        other = await create('bob')
        assert (await call('cancel', {'id': other['id']}, alice))['status'] == 'cancelled'
        own = await create('alice')
        assert (await call('update', {'id': own['id'], 'text': 'own'}, alice))['text'] == 'own'
        assert (await call('snooze', {'id': own['id'], 'delay': 60}, alice))['date'] != own['date']
        assert (await call('cancel', {'id': own['id']}, alice))['status'] == 'cancelled'
        automatic = await create('bob')
        assert (await call('update', {'id': automatic['id'], 'text': 'auto'}))['text'] == 'auto'
        assert (await call('snooze', {'id': automatic['id'], 'delay': 60}))['date'] != automatic['date']
        assert (await call('cancel', {'id': automatic['id']}))['status'] == 'cancelled'
    asyncio.run(run())

def test_manager_access_rules():
    async def run():
        manager = api.ReminderManager(FakeStore(), FakeScheduler())
        item = await manager.async_create('x', 'bob', 'alice', future())
        await raises(manager.async_update(item.id, text='x', user_id='charlie'), 'only the recipient can update this reminder')
        await raises(manager.async_snooze(item.id, delay_seconds=60, user_id='charlie'), 'only the recipient can snooze this reminder')
        await raises(manager.async_cancel(item.id, user_id='charlie'), 'only the recipient or the creator can cancel this reminder')
        assert (await manager.async_update(item.id, text='auto', user_id=None)).text == 'auto'
        assert (await manager.async_snooze(item.id, delay_seconds=60, user_id=None)).date > item.date
        assert (await manager.async_cancel(item.id, user_id=None)).status == 'cancelled'
    asyncio.run(run())
