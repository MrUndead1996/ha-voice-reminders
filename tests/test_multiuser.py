"""Standalone end-to-end multi-user reminder scenarios."""
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
    def async_set_speech(self, text): self.speech = {'plain': {'speech': text}}
    def async_set_reprompt(self, text): self.reprompt = {'plain': {'reprompt': text}}
    def async_set_card(self, title, content): self.card = (title, content)
class Intent:
    def __init__(self, hass, slots, user, language):
        self.hass, self.slots = hass, slots
        self.context = types.SimpleNamespace(user_id=user)
        self.language, self.platform = language, 'test'
    def create_response(self): return IntentResponse()
intent.IntentHandler, intent.IntentHandleError = IntentHandler, IntentHandleError
intent.IntentResponse, intent.IntentResponseType = IntentResponse, IntentResponseType
intent.async_register = lambda hass, handler: hass.data.setdefault('intent_helpers', {}).__setitem__(handler.intent_type, handler)
intent.async_remove = lambda hass, kind: hass.data.setdefault('intent_helpers', {}).pop(kind, None)
helpers.intent = intent
exceptions = types.ModuleType('homeassistant.exceptions')
exceptions.ServiceNotFound = type('ServiceNotFound', (Exception,), {})
for name, module in [('homeassistant', ha), ('homeassistant.helpers', helpers),
                     ('homeassistant.helpers.intent', intent), ('homeassistant.exceptions', exceptions)]:
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
services = importlib.import_module('custom_components.voice_reminders.services')
intents = importlib.import_module('custom_components.voice_reminders.intents')
delivery = importlib.import_module('custom_components.voice_reminders.delivery')
storage = importlib.import_module('custom_components.voice_reminders.storage')

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
        self.users = {name: types.SimpleNamespace(id=name, name=name, username=None, last_name=None)
                      for name in ('alice', 'bob', 'charlie')}
    async def async_get_user(self, user_id): return self.users.get(user_id)
    async def async_get_users(self): return list(self.users.values())
class FakeServices:
    def __init__(self): self.handlers, self.calls = {}, []
    def async_register(self, domain, name, handler): self.handlers[domain, name] = handler
    async def async_call(self, domain, service, payload, context=None):
        self.calls.append((domain, service, payload, context))
class FakeHass:
    def __init__(self):
        self.data, self.auth, self.services = {}, FakeAuth(), FakeServices()
        self.config = types.SimpleNamespace(time_zone='Europe/Moscow')
        self.entity_registry = types.SimpleNamespace(entities={'assist_satellite.room': None})

def future(): return datetime.now(timezone.utc) + timedelta(days=1)
def speech(response): return response.speech['plain']['speech']
async def raises(awaitable, exception, message):
    try: await awaitable
    except exception as err: assert message in str(err), str(err)
    else: assert False, 'expected ' + exception.__name__

async def setup():
    hass, store = FakeHass(), FakeStore()
    manager = api.ReminderManager(store, FakeScheduler())
    hass.data['voice_reminders'] = {'entry': {'manager': manager}}
    await services.async_register_services(hass, manager)
    await intents.async_setup_intents(hass)
    async def service(name, data, user=None):
        context = types.SimpleNamespace(user_id=user) if user is not None else None
        return await hass.services.handlers['voice_reminders', name](types.SimpleNamespace(data=data, context=context))
    async def assist(name, user=None, language='en', **values):
        slots = {key: {'value': value} for key, value in values.items()}
        return await hass.data['intent_helpers']['voice_reminders.' + name].async_handle(Intent(hass, slots, user, language))
    return hass, store, manager, service, assist

def test_multiuser_lists_and_persistence():
    async def run():
        _, store, manager, service, assist = await setup()
        async def create(text, owner, creator):
            return await service('create', {'text': text, 'owner_user_id': owner, 'date': future().isoformat()}, creator)
        own = await create('alice private', 'alice', 'alice')
        to_bob = await create('bob parcel', 'bob', 'alice')
        to_alice = await create('alice letter', 'alice', 'bob')
        expected = {('alice', 'mine'): [own, to_alice], ('alice', 'created'): [to_bob],
                    ('bob', 'mine'): [to_bob], ('bob', 'created'): [to_alice]}
        async def check():
            for (user, view), items in expected.items():
                assert (await service('list', {'view': view}, user))['reminders'] == items
                spoken = speech(await assist('ListReminders', user, view=view))
                for item in (own, to_bob, to_alice):
                    assert (item['text'] in spoken) == (item in items)
            assert speech(await assist('ListReminders', 'alice')) != speech(await assist('ListReminders', 'bob'))
        await check()
        before = await manager.async_list()
        store.data = storage.payload_to_reminders(storage.reminders_to_payload(before))
        assert [(x.id, x.owner_user_id, x.created_by_user_id) for x in store.data] == [
            (x.id, x.owner_user_id, x.created_by_user_id) for x in before]
        await check()
    asyncio.run(run())

def test_multiuser_access_services_and_intents():
    async def run():
        _, _, manager, service, assist = await setup()
        async def create(text):
            return await service('create', {'text': text, 'owner_user_id': 'bob', 'date': future().isoformat()}, 'alice')
        item = await create('shared task')
        messages = {'update': 'only the recipient can update this reminder',
                    'snooze': 'only the recipient can snooze this reminder',
                    'cancel': 'only the recipient or the creator can cancel this reminder'}
        fields = {'update': {'text': 'changed'}, 'snooze': {'delay': 60}, 'cancel': {}}
        for user, names in [('alice', ('update', 'snooze')), ('charlie', ('update', 'snooze', 'cancel'))]:
            for name in names:
                await raises(service(name, {'id': item['id'], **fields[name]}, user), ValueError, messages[name])
        for user in ('alice', 'charlie'):
            await raises(assist('SnoozeReminder', user, id=item['id'], delay=60), intents.intent.IntentHandleError, messages['snooze'])
        await raises(assist('CancelReminder', 'charlie', id=item['id']), intents.intent.IntentHandleError, messages['cancel'])
        for name, extra in [('CancelReminder', {}), ('SnoozeReminder', {'delay': 60})]:
            await raises(assist(name, 'charlie', text='shared task', **extra), intents.intent.IntentHandleError, 'reminder not found')
        assert (await manager.async_list())[0].status == 'pending'
        assert (await service('update', {'id': item['id'], 'text': 'bob task'}, 'bob'))['text'] == 'bob task'
        assert (await service('snooze', {'id': item['id'], 'delay': 60}, 'bob'))['date'] != item['date']
        await assist('SnoozeReminder', 'bob', text='bob task', delay=60)
        await assist('CancelReminder', 'bob', text='bob task')
        assert (await manager.async_list())[0].status == 'cancelled'
        item = await create('owner cancellation')
        assert (await service('cancel', {'id': item['id']}, 'bob'))['status'] == 'cancelled'
        item = await create('creator cancellation')
        assert (await service('cancel', {'id': item['id']}, 'alice'))['status'] == 'cancelled'
        item = await create('creator intent')
        await assist('CancelReminder', 'alice', id=item['id'])
        assert (await manager.async_list())[-1].status == 'cancelled'
        item = await create('system task')
        assert (await service('update', {'id': item['id'], 'text': 'system updated'}))['text'] == 'system updated'
        assert (await service('snooze', {'id': item['id'], 'delay': 60}))['date'] != item['date']
        assert (await service('cancel', {'id': item['id']}))['status'] == 'cancelled'
    asyncio.run(run())

def test_unknown_users_and_delivery():
    async def run():
        hass, _, manager, service, assist = await setup()
        data = {'text': 'bob delivery', 'owner_user_id': 'bob', 'date': future().isoformat()}
        item = await service('create', data, 'alice')
        for name, args in [('create', data), ('list', {'view': 'mine'}),
                           ('update', {'id': item['id'], 'text': 'x'}),
                           ('cancel', {'id': item['id']}), ('snooze', {'id': item['id'], 'delay': 60})]:
            await raises(service(name, args, 'ghost'), ValueError, 'does not exist')
        for name, args in [('create', {**data, 'owner_user_id': 'ghost'}), ('list', {'owner_user_id': 'ghost'})]:
            await raises(service(name, args), ValueError, 'does not exist')
        await raises(assist('CreateReminder', 'alice', text='x', date=data['date'], owner='ghost'), intents.intent.IntentHandleError, 'does not exist')
        await raises(assist('CreateReminder', 'alice', language='ru', text='x', date=data['date'], owner='ghost'), intents.intent.IntentHandleError, 'Получатель не найден')
        await raises(assist('ListReminders'), intents.intent.IntentHandleError, 'a user is required')
        await service('create', {**data, 'text': 'charlie delivery', 'owner_user_id': 'charlie'}, 'alice')
        bob, charlie = await manager.async_list()
        hook = delivery.async_delivery_hook(hass, {'satellites': 'assist_satellite.room',
            'notify_targets': 'bob:mobile_app_bob,alice:mobile_app_alice'})
        await hook(bob)
        await hook(charlie)
        notify = [call for call in hass.services.calls if call[0] == 'notify']
        tts = [call for call in hass.services.calls if call[0] == 'tts']
        assert len(notify) == 1 and notify[0][1] == 'mobile_app_bob' and notify[0][2]['message'] == bob.text
        assert len(tts) == 2 and [call[1] for call in tts] == ['speak', 'speak']
        assert [call[2]['text'] for call in tts] == [bob.text, charlie.text]
    asyncio.run(run())
