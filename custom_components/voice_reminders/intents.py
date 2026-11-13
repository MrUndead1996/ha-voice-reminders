"""Assist intent handlers for voice reminders."""
from datetime import datetime, timedelta, timezone
import math
import re
from zoneinfo import ZoneInfo

from homeassistant.helpers import intent

from . import grammar
from .api import DOMAIN
from .models import STATUSES
from .services import _parse_date, _resolve_recipient


_RU_ERRORS = {
    'Voice Reminders is not set up': 'Интеграция голосовых напоминаний не настроена',
    'a user is required to create a reminder': 'Нужен пользователь, чтобы создать напоминание',
    'a user is required to list reminders': 'Нужен пользователь, чтобы увидеть список напоминаний',
    'text must be a non-blank string': 'Текст напоминания должен быть непустым',
    'invalid date': 'Некорректная дата',
    'date must be in the future': 'Дата должна быть в будущем',
    'invalid view': 'Некорректный режим списка',
    'invalid status': 'Некорректный статус',
    'reminder not found': 'Напоминание не найдено',
    'reminder is ambiguous': 'Неоднозначное напоминание, уточните какое именно',
    'invalid delay': 'Некорректная задержка',
    'only the recipient can update this reminder': 'Обновить напоминание может только получатель',
    'nothing to update': 'Нечего обновлять',
    'invalid recurrence': 'Некорректная повторяемость',
    'only the recipient or the creator can cancel this reminder': 'Отменить напоминание может только получатель или создатель',
    'only the recipient can snooze this reminder': 'Отложить напоминание может только получатель',
    'only pending reminders can be snoozed': 'Отложить можно только активное напоминание',
    'delay_seconds must be a positive number': 'Задержка должна быть положительным числом',
    'delay_seconds is too large': 'Задержка слишком большая',
    'provide exactly one of delay_seconds or date': 'Укажите одно из: задержка или дата',
    'date must be timezone-aware and in the future': 'Дата должна быть в будущем',
}


def _localize(message, obj):
    if obj.language != 'ru':
        return message
    if message in _RU_ERRORS:
        return _RU_ERRORS[message]
    if 'does not exist' in message:
        return 'Получатель не найден'
    if 'is ambiguous' in message:
        return 'Неоднозначный получатель'
    return message


def _error(obj, english, russian):
    raise intent.IntentHandleError(russian if obj.language == 'ru' else english)


def _manager(obj):
    hass = obj.hass
    for entry in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry, dict) and entry.get('manager') is not None:
            return entry['manager']
    _error(obj, 'Voice Reminders is not set up', _RU_ERRORS['Voice Reminders is not set up'])


def _slot(obj, name):
    return obj.slots.get(name, {}).get('value')


def _user(obj):
    return getattr(obj.context, 'user_id', None)


def _date(value, obj):
    hass = obj.hass
    generated_clock = False
    try:
        # Sentence grammar can provide a normalized duration or calendar/time
        # parts instead of a single free-form date string.
        if value is None:
            count, unit = _slot(obj, 'count'), _slot(obj, 'unit')
            if count is not None and unit is not None:
                value = f'через {count} {unit}'
            else:
                dayref, hour, minute = (_slot(obj, name) for name in ('dayref', 'hour', 'minute'))
                if hour is not None:
                    generated_clock = True
                    when = 'сегодня' if dayref in (None, '0') else 'завтра' if str(dayref) == '1' else str(dayref)
                    value = f'{when} в {int(hour):02d}:{int(minute or 0):02d}'
        if not isinstance(value, (str, datetime)):
            raise ValueError('invalid date')
        try:
            date = _parse_date(value)
        except ValueError:
            if not isinstance(value, str):
                raise
            zone = getattr(getattr(hass, 'config', None), 'time_zone', None)
            date = grammar.parse_datetime(value.strip(), datetime.now(timezone.utc), ZoneInfo(zone) if zone else None)
            if date is None:
                raise ValueError('invalid date')
        if generated_clock and _slot(obj, 'freq') in ('daily', 'weekly', 'monthly'):
            now = datetime.now(timezone.utc)
            if date <= now:
                zone = getattr(getattr(hass, 'config', None), 'time_zone', None)
                local = date.astimezone(ZoneInfo(zone) if zone else timezone.utc)
                date = (local + timedelta(days=1)).astimezone(timezone.utc)
        if date <= datetime.now(timezone.utc):
            raise ValueError('date must be in the future')
        return date
    except ValueError as err:
        raise intent.IntentHandleError(_localize(str(err), obj)) from err


def _format_date(hass, date):
    zone = getattr(getattr(hass, 'config', None), 'time_zone', None)
    return date.astimezone(ZoneInfo(zone) if zone else None).strftime('%Y-%m-%d %H:%M')


def _response(obj, english, russian):
    response = obj.create_response()
    response.async_set_speech(russian if obj.language == 'ru' else english)
    return response



def _question(obj, english, russian, english_reprompt, russian_reprompt):
    response = _response(obj, english, russian)
    response.async_set_reprompt(russian_reprompt if obj.language == 'ru' else english_reprompt)
    return response


def _identifier(obj):
    reminder_id, text = _slot(obj, 'id'), _slot(obj, 'text')
    if (reminder_id is None) == (text is None):
        _error(obj, 'provide either id or text', 'Укажите идентификатор или текст')
    value = reminder_id if reminder_id is not None else text
    if not isinstance(value, str) or not value.strip():
        _error(obj, 'id or text must be a non-blank string', 'Идентификатор или текст должны быть непустыми')
    return reminder_id, text


async def _resolve_id(manager, obj, user_id):
    reminder_id, text = _identifier(obj)
    if reminder_id is not None:
        return reminder_id
    items = await manager.async_list(status='pending', owner_user_id=user_id if user_id else None)
    normalized = ' '.join(text.split()).casefold()
    matches = [item for item in items if ' '.join(item.text.split()).casefold() == normalized]
    if not matches:
        _error(obj, 'reminder not found', _RU_ERRORS['reminder not found'])
    if len(matches) != 1:
        _error(obj, 'reminder is ambiguous', _RU_ERRORS['reminder is ambiguous'])
    return matches[0].id


def _delay(value, obj):
    if isinstance(value, str):
        parsed = grammar.parse_delay(value)
        if parsed is not None:
            return _delay(parsed, obj)
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s+(seconds?|minutes?|hours?)\s*', value, re.IGNORECASE)
        if not match:
            _error(obj, 'invalid delay', _RU_ERRORS['invalid delay'])
        amount = float(match.group(1))
        unit = match.group(2).lower()
        value = amount * (3600 if unit.startswith('hour') else 60 if unit.startswith('minute') else 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        _error(obj, 'invalid delay', _RU_ERRORS['invalid delay'])
    return value


class CreateReminder(intent.IntentHandler):
    intent_type = f'{DOMAIN}.CreateReminder'
    description = 'Create a reminder for a user at a specified time.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj)
        user = _user(intent_obj)
        if not user:
            _error(intent_obj, 'a user is required to create a reminder', _RU_ERRORS['a user is required to create a reminder'])
        text = _slot(intent_obj, 'text')
        if not isinstance(text, str) or not text.strip():
            _error(intent_obj, 'text must be a non-blank string', _RU_ERRORS['text must be a non-blank string'])
        date = _date(_slot(intent_obj, 'date'), intent_obj)
        recurrence = _slot(intent_obj, 'recurrence') or _slot(intent_obj, 'freq')
        if isinstance(recurrence, str):
            recurrence = grammar.parse_recurrence(recurrence) or recurrence
        owner = _slot(intent_obj, 'owner')
        try:
            if owner is not None:
                error = None
                for candidate in grammar.parse_recipient(owner):
                    try:
                        owner = await _resolve_recipient(intent_obj.hass, candidate, 'owner')
                        break
                    except ValueError as err:
                        error = err
                else:
                    raise error
            item = await manager.async_create(text, owner if owner is not None else user, user, date,
                                              recurrence if recurrence is not None else 'none')
        except ValueError as err:
            raise intent.IntentHandleError(_localize(str(err), intent_obj)) from err
        formatted = _format_date(intent_obj.hass, item.date)
        en = f'Reminder created: {item.text} at {formatted}'
        ru = f'Напоминание создано: {item.text} в {formatted}'
        repeats = {'daily': 'каждый день', 'weekly': 'каждую неделю', 'monthly': 'каждый месяц'}
        if item.recurrence in repeats:
            en += f', repeats {item.recurrence}'
            ru += f', повторяется {repeats[item.recurrence]}'
        if owner is not None and item.owner_user_id != user:
            try:
                recipient = await intent_obj.hass.auth.async_get_user(item.owner_user_id)
                name = recipient.name if recipient else None
            except Exception:
                name = None
            if name:
                en = f'Reminder for {name}: {en}'
                ru = f'Напоминание для {name}: {ru}'
        return _response(intent_obj, en, ru)


class ListReminders(intent.IntentHandler):
    intent_type = f'{DOMAIN}.ListReminders'
    description = 'List reminders owned or created by the calling user.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj)
        user = _user(intent_obj)
        if not user:
            _error(intent_obj, 'a user is required to list reminders', _RU_ERRORS['a user is required to list reminders'])
        view = _slot(intent_obj, 'view')
        if view is None:
            view = 'mine'
        if not isinstance(view, str) or view not in ('mine', 'created'):
            _error(intent_obj, 'invalid view', _RU_ERRORS['invalid view'])
        status = _slot(intent_obj, 'status')
        if status is not None and (not isinstance(status, str) or status not in STATUSES):
            _error(intent_obj, 'invalid status', _RU_ERRORS['invalid status'])
        if view == 'mine':
            items = await manager.async_list(owner_user_id=user, status=status)
        else:
            items = await manager.async_list(created_by_user_id=user, status=status)
            items = [item for item in items if item.owner_user_id != user]
        items.sort(key=lambda item: item.date)
        if items:
            details = '; '.join(f'{item.text} — {_format_date(intent_obj.hass, item.date)}' for item in items[:10])
            en, ru = f'{len(items)} reminder(s): {details}', f'Напоминаний: {len(items)}: {details}'
        else:
            en, ru = 'No reminders', 'Нет напоминаний'
        response = _response(intent_obj, en, ru)
        response_type = getattr(intent, 'IntentResponseType', None)
        query_answer = getattr(response_type, 'QUERY_ANSWER', None)
        if query_answer is not None:
            response.response_type = query_answer
        return response


class CancelReminder(intent.IntentHandler):
    intent_type = f'{DOMAIN}.CancelReminder'
    description = 'Cancel a reminder by its identifier or text.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj)
        user = _user(intent_obj)
        if _slot(intent_obj, 'id') is None and _slot(intent_obj, 'text') is None:
            return _question(intent_obj, 'Which reminder should I cancel?', 'Какое напоминание отменить?',
                             'Say the reminder name or id.', 'Назовите напоминание или его идентификатор.')
        reminder_id = await _resolve_id(manager, intent_obj, user)
        try:
            item = await manager.async_cancel(reminder_id, user_id=user)
        except ValueError as err:
            raise intent.IntentHandleError(_localize(str(err), intent_obj)) from err
        return _response(intent_obj, f'Reminder cancelled: {item.text}', f'Напоминание отменено: {item.text}')


class SnoozeReminder(intent.IntentHandler):
    intent_type = f'{DOMAIN}.SnoozeReminder'
    description = 'Snooze a pending reminder by a duration or until a specified time.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj)
        user = _user(intent_obj)
        if _slot(intent_obj, 'id') is None and _slot(intent_obj, 'text') is None:
            return _question(intent_obj, 'Which reminder should I snooze?', 'Какое напоминание отложить?',
                             'Say the reminder name or id.', 'Назовите напоминание или его идентификатор.')
        _identifier(intent_obj)
        delay, date = _slot(intent_obj, 'delay'), _slot(intent_obj, 'date')
        delay_unit = _slot(intent_obj, 'unit') or _slot(intent_obj, 'snooze_unit')
        if delay is None and _slot(intent_obj, 'count') is not None and delay_unit is not None:
            delay = f"{_slot(intent_obj, 'count')} {delay_unit}"
        if delay is None and date is None:
            return _question(intent_obj, 'How long should I snooze the reminder?', 'На сколько отложить напоминание?',
                             'Give a duration, e.g. 10 minutes.', 'Укажите задержку, например 10 минут.')
        if delay is not None and date is not None:
            _error(intent_obj, 'provide either delay or date', 'Укажите задержку или дату')
        delay = _delay(delay, intent_obj) if delay is not None else None
        date = _date(date, intent_obj) if date is not None else None
        reminder_id = await _resolve_id(manager, intent_obj, user)
        try:
            item = await manager.async_snooze(reminder_id, delay_seconds=delay, date=date, user_id=user)
        except ValueError as err:
            raise intent.IntentHandleError(_localize(str(err), intent_obj)) from err
        formatted = _format_date(intent_obj.hass, item.date)
        return _response(intent_obj, f'Reminder snoozed to {formatted}: {item.text}', f'Напоминание перенесено на {formatted}: {item.text}')


_HANDLERS = (CreateReminder, ListReminders, CancelReminder, SnoozeReminder)


async def async_setup_intents(hass):
    """Register the Assist intent handlers."""
    for handler in _HANDLERS:
        intent.async_register(hass, handler())


async def async_remove_intents(hass):
    """Remove the Assist intent handlers."""
    for handler in _HANDLERS:
        intent.async_remove(hass, handler.intent_type)
