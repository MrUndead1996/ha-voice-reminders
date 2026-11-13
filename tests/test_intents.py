"""Standalone tests for Assist intent handlers."""
import asyncio
import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

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
        self.reprompt = {}
        self.response_type = IntentResponseType.ACTION_DONE
    def async_set_speech(self, text):
        self.speech = {'plain': {'speech': text}}
    def async_set_reprompt(self, text):
        self.reprompt = {'plain': {'reprompt': text}}
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
        self.users.update({key: types.SimpleNamespace(id=key, name=name, username=None, last_name=None) for key, name in [('anya', 'Аня'), ('sasha', 'Саша')]})
    async def async_get_user(self, user_id): return self.users.get(user_id)
    async def async_get_users(self): return list(self.users.values())
class FakeHass:
    def __init__(self):
        self.data, self.auth = {}, FakeAuth()
        self.config = types.SimpleNamespace(time_zone='Europe/Moscow')
def future(): return datetime.now(timezone.utc) + timedelta(days=1)
def slots(**kwargs): return {key: {'value': value} for key, value in kwargs.items()}
def speech(response): return response.speech['plain']['speech']
def reprompt(response): return response.reprompt['plain']['reprompt']
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
        response = await call('CancelReminder', 'bob')
        assert speech(response) == 'Which reminder should I cancel?'
        assert reprompt(response) == 'Say the reminder name or id.'
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
        response = await call('SnoozeReminder', 'bob', id=item.id)
        assert speech(response) == 'How long should I snooze the reminder?'
        assert reprompt(response) == 'Give a duration, e.g. 10 minutes.'
        await raises(call('SnoozeReminder', 'bob', id='unknown', delay=1), 'reminder not found')
        await raises(call('SnoozeReminder', 'charlie', id=item.id, delay=1), 'only the recipient')
        for delay in (True, 0, 'bogus', '1 day'):
            await raises(call('SnoozeReminder', 'bob', id=item.id, delay=delay), 'invalid delay')
        await manager.async_cancel(item.id)
        await raises(call('SnoozeReminder', 'bob', id=item.id, delay=1), 'pending')
    asyncio.run(run())


def test_russian_slots():
    async def run():
        _, manager, call = await setup()
        now = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        with patch.object(intents, 'datetime', FixedDatetime):
            # The manager also validates against its own clock; use a future clock
            # for the integration and separately check the fixed calendar example.
            from custom_components.voice_reminders import grammar
            expected = grammar.parse_datetime('завтра в 15:00', now, ZoneInfo('Europe/Moscow'))
            assert expected == datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
            # Capture manager creation so this fixed-clock test is independent of today's date.
            captured = []
            async def create(text, owner, user, date, recurrence):
                item = types.SimpleNamespace(text=text, owner_user_id=owner, date=date, recurrence=recurrence)
                captured.append(item)
                return item
            with patch.object(manager, 'async_create', create):
                await call('CreateReminder', 'bob', text='полить цветы', date='завтра в 15:00', recurrence='каждую неделю', owner='Ане')
                assert (captured[-1].owner_user_id, captured[-1].recurrence, captured[-1].date) == ('anya', 'weekly', expected)
                await call('CreateReminder', 'bob', text='полить цветы', count='5', unit='minutes')
                assert captured[-1].date == now + timedelta(minutes=5)
                await call('CreateReminder', 'bob', text='позвонить', dayref='1', hour='15', minute='30')
                assert captured[-1].date == grammar.parse_datetime('завтра в 15:30', now, ZoneInfo('Europe/Moscow'))
                await call('CreateReminder', 'bob', text='вынести мусор', dayref='0', hour='8', freq='daily')
                assert captured[-1].recurrence == 'daily'
                await raises(call('CreateReminder', 'bob', text='x', date='сегодня в 08:00', recurrence='daily'), 'future')
                await raises(call('CreateReminder', 'bob', text='x', date='сегодня в 08:00', recurrence='none'), 'future')
                await call('CreateReminder', 'bob', text='x', date='через 2 часа', owner='Сашу')
                assert captured[-1].owner_user_id == 'sasha' and captured[-1].date == now + timedelta(hours=2)
                await raises(call('CreateReminder', 'bob', text='x', date='через 2 часа', owner='Василия'), 'does not exist')
                await raises(call('CreateReminder', 'bob', text='x', date='когда-нибудь'), 'invalid date')
        item = await manager.async_create('task', 'bob', 'bob', future())
        original = item.date
        await call('SnoozeReminder', 'bob', id=item.id, delay='через двадцать минут')
        assert (await manager.async_list())[0].date == original + timedelta(seconds=1200)
    asyncio.run(run())


def test_hassil_russian_recognition_and_handler_flow():
    """Exercise the shipped templates with HassIL, then feed slots to handlers."""
    try:
        import yaml
        from hassil.intents import Intents
        from hassil.recognize import recognize
    except ImportError as err:
        raise unittest.SkipTest("install tests/requirements.txt for HassIL recognition") from err

    grammar_path = ROOT / 'custom_components/voice_reminders/sentences/ru/voice_reminders.yaml'
    data = yaml.safe_load(grammar_path.read_text(encoding='utf-8'))
    parsed_intents = Intents.from_dict(data)

    def match(text):
        return recognize(text, parsed_intents, language='ru')

    relative = match('напомни мне через 5 минут полить цветы')
    assert relative and relative.intent.name == 'voice_reminders.CreateReminder'
    assert relative.entities['count'].value == 5
    assert relative.entities['unit'].value == 'minutes'
    assert relative.entities['text'].value == 'полить цветы'

    absolute = match('напомни мне завтра в 15:30 позвонить маме')
    assert absolute and absolute.intent.name == 'voice_reminders.CreateReminder'
    assert absolute.entities['dayref'].value == '1'
    assert absolute.entities['hour'].value == 15
    assert absolute.entities['minute'].value == 30

    recurring = match('напоминай мне каждый день в 8 полить цветы')
    assert recurring and recurring.intent.name == 'voice_reminders.CreateReminder'
    assert recurring.entities['freq'].value == 'daily'

    for phrase in (
        'напомни мне через минуту полить цветы',
        'напомни мне через пять минут полить цветы',
        'напомни мне полить цветы через полчаса',
        'напомни мне через 2 дня полить цветы',
        'напомни мне через неделю полить цветы',
        'напомни мне завтра в 15:05 полить цветы',
        'напоминай мне каждую неделю в 8 полить цветы',
        'напоминай мне каждый месяц в 8 полить цветы',
    ):
        recognized = match(phrase)
        assert recognized and recognized.intent.name == 'voice_reminders.CreateReminder', phrase
    for phrase, expected in (
        ('покажи мои напоминания', 'ListReminders'),
        ('отмени напоминание полить цветы', 'CancelReminder'),
        ('отложи напоминание полить цветы на 5 минут', 'SnoozeReminder'),
    ):
        recognized = match(phrase)
        assert recognized and recognized.intent.name == f'voice_reminders.{expected}', phrase

    assert match('отмени все напоминания') is None
    assert match('напомни мне в следующую среду купить хлеб') is None

    async def flow():
        _, manager, call = await setup()
        captured = []
        async def create(text, owner, user, date, recurrence):
            item = types.SimpleNamespace(text=text, owner_user_id=owner, date=date, recurrence=recurrence)
            captured.append(item)
            return item
        with patch.object(manager, 'async_create', create):
            for phrase in (
                'напомни мне через минуту полить цветы',
                'напомни мне через пять минут полить цветы',
                'напомни мне через неделю полить цветы',
                'напомни мне завтра в 15:05 полить цветы',
                'напоминай мне каждый день в 8 полить цветы',
            ):
                recognized = match(phrase)
                slot_values = {name: entity.value for name, entity in recognized.entities.items()}
                await call('CreateReminder', 'bob', **slot_values)
                assert captured[-1].date > datetime.now(timezone.utc), phrase
        assert captured and captured[0].owner_user_id == 'bob'
        assert captured[0].text == 'полить цветы'
        assert captured[0].date > datetime.now(timezone.utc)

    asyncio.run(flow())


def test_english_slots():
    async def run():
        _, manager, call = await setup()
        now = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        captured = []
        async def create(text, owner, user, date, recurrence):
            item = types.SimpleNamespace(text=text, owner_user_id=owner, date=date, recurrence=recurrence)
            captured.append(item)
            return item
        with patch.object(intents, 'datetime', FixedDatetime), patch.object(manager, 'async_create', create):
            await call('CreateReminder', 'bob', text='water plants', date='tomorrow at 15:00', recurrence='every week', owner='alice')
            assert (captured[-1].owner_user_id, captured[-1].recurrence, captured[-1].date) == ('alice', 'weekly', datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
            await raises(call('CreateReminder', 'bob', text='x', date='sometime'), 'invalid date')
        item = await manager.async_create('task', 'bob', 'bob', future())
        original = item.date
        await call('SnoozeReminder', 'bob', id=item.id, delay='in twenty minutes')
        assert (await manager.async_list())[0].date == original + timedelta(minutes=20)
    asyncio.run(run())


def test_localized_responses():
    async def run():
        hass, manager, call = await setup()
        now = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)
        async def create(text, owner, user, date, recurrence):
            return types.SimpleNamespace(text=text, owner_user_id=owner, date=date, recurrence=recurrence)
        with patch.object(intents, 'datetime', FixedDatetime), patch.object(manager, 'async_create', create):
            response = speech(await call('CreateReminder', 'bob', language='ru', text='полить цветы', date='завтра в 15:00', recurrence='каждую неделю'))
            assert response.startswith('Напоминание создано:') and 'полить цветы' in response
            assert '2026-11-14 15:00' in response and 'повторяется каждую неделю' in response
            response = speech(await call('CreateReminder', 'bob', language='ru', text='цветы', date='завтра в 15:00', owner='Ане'))
            assert response.startswith('Напоминание для Аня:')
            response = speech(await call('CreateReminder', 'bob', text='plants', date='tomorrow at 15:00'))
            assert ' at 2026-11-14 15:00' in response
            await raises(call('CreateReminder', 'bob', language='ru', text='x', date='bad'), 'Некорректная дата')
        item = await manager.async_create('задача', 'bob', 'bob', future())
        response = speech(await call('SnoozeReminder', 'bob', language='ru', id=item.id, delay=60))
        assert 'Напоминание перенесено на' in response and 'задача' in response
        assert intents._format_date(hass, (await manager.async_list())[0].date) in response
        assert speech(await call('CancelReminder', 'bob', language='ru', id=item.id)) == 'Напоминание отменено: задача'
        await raises(call('CancelReminder', 'bob', language='ru', text='missing'), 'Напоминание не найдено')
        await raises(call('SnoozeReminder', 'bob', language='ru', id=item.id, delay='bogus'), 'Некорректная задержка')
        await manager.async_create('дубликат', 'bob', 'bob', future())
        await manager.async_create('дубликат', 'bob', 'bob', future())
        await raises(call('CancelReminder', 'bob', language='ru', text='дубликат'), 'Неоднозначное')
        response = await call('CancelReminder', 'bob', language='ru')
        assert speech(response) == 'Какое напоминание отменить?'
        assert reprompt(response) == 'Назовите напоминание или его идентификатор.'
        response = await call('SnoozeReminder', 'bob', language='ru', id=item.id)
        assert speech(response) == 'На сколько отложить напоминание?'
        assert reprompt(response) == 'Укажите задержку, например 10 минут.'
    asyncio.run(run())
