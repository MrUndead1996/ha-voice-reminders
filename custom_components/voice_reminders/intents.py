"""Assist intent handlers for voice reminders."""
from datetime import datetime, timezone
import math
import re
from zoneinfo import ZoneInfo

from homeassistant.helpers import intent

from . import grammar
from .api import DOMAIN
from .models import STATUSES
from .services import _parse_date, _resolve_recipient


def _manager(hass):
    for entry in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry, dict) and entry.get('manager') is not None:
            return entry['manager']
    raise intent.IntentHandleError('Voice Reminders is not set up')


def _slot(obj, name):
    return obj.slots.get(name, {}).get('value')


def _user(obj):
    return getattr(obj.context, 'user_id', None)


def _date(value, hass):
    try:
        try:
            date = _parse_date(value)
        except ValueError:
            if not isinstance(value, str):
                raise
            zone = getattr(getattr(hass, 'config', None), 'time_zone', None)
            date = grammar.parse_datetime(value.strip(), datetime.now(timezone.utc), ZoneInfo(zone) if zone else None)
            if date is None:
                raise ValueError('invalid date')
        if date <= datetime.now(timezone.utc):
            raise ValueError('date must be in the future')
        return date
    except ValueError as err:
        raise intent.IntentHandleError(str(err)) from err


def _format_date(hass, date):
    zone = getattr(getattr(hass, 'config', None), 'time_zone', None)
    return date.astimezone(ZoneInfo(zone) if zone else None).strftime('%Y-%m-%d %H:%M')


def _response(obj, english, russian):
    response = obj.create_response()
    response.async_set_speech(russian if obj.language == 'ru' else english)
    return response


def _identifier(obj):
    reminder_id, text = _slot(obj, 'id'), _slot(obj, 'text')
    if (reminder_id is None) == (text is None):
        raise intent.IntentHandleError('provide either id or text')
    value = reminder_id if reminder_id is not None else text
    if not isinstance(value, str) or not value.strip():
        raise intent.IntentHandleError('id or text must be a non-blank string')
    return reminder_id, text


async def _resolve_id(manager, obj, user_id):
    reminder_id, text = _identifier(obj)
    if reminder_id is not None:
        return reminder_id
    items = await manager.async_list(status='pending', owner_user_id=user_id if user_id else None)
    normalized = ' '.join(text.split()).casefold()
    matches = [item for item in items if ' '.join(item.text.split()).casefold() == normalized]
    if not matches:
        raise intent.IntentHandleError('reminder not found')
    if len(matches) != 1:
        raise intent.IntentHandleError('reminder is ambiguous')
    return matches[0].id


def _delay(value):
    if isinstance(value, str):
        parsed = grammar.parse_delay(value)
        if parsed is not None:
            return _delay(parsed)
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s+(seconds?|minutes?|hours?)\s*', value, re.IGNORECASE)
        if not match:
            raise intent.IntentHandleError('invalid delay')
        amount = float(match.group(1))
        unit = match.group(2).lower()
        value = amount * (3600 if unit.startswith('hour') else 60 if unit.startswith('minute') else 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise intent.IntentHandleError('invalid delay')
    return value


class CreateReminder(intent.IntentHandler):
    intent_type = f'{DOMAIN}.CreateReminder'
    description = 'Create a reminder for a user at a specified time.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj.hass)
        user = _user(intent_obj)
        if not user:
            raise intent.IntentHandleError('a user is required to create a reminder')
        text = _slot(intent_obj, 'text')
        if not isinstance(text, str) or not text.strip():
            raise intent.IntentHandleError('text must be a non-blank string')
        date = _date(_slot(intent_obj, 'date'), intent_obj.hass)
        recurrence = _slot(intent_obj, 'recurrence')
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
            raise intent.IntentHandleError(str(err)) from err
        return _response(intent_obj, f'Reminder created: {item.text}', f'Напоминание создано: {item.text}')


class ListReminders(intent.IntentHandler):
    intent_type = f'{DOMAIN}.ListReminders'
    description = 'List reminders owned or created by the calling user.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj.hass)
        user = _user(intent_obj)
        if not user:
            raise intent.IntentHandleError('a user is required to list reminders')
        view = _slot(intent_obj, 'view')
        if view is None:
            view = 'mine'
        if not isinstance(view, str) or view not in ('mine', 'created'):
            raise intent.IntentHandleError('invalid view')
        status = _slot(intent_obj, 'status')
        if status is not None and (not isinstance(status, str) or status not in STATUSES):
            raise intent.IntentHandleError('invalid status')
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
        manager = _manager(intent_obj.hass)
        user = _user(intent_obj)
        reminder_id = await _resolve_id(manager, intent_obj, user)
        try:
            item = await manager.async_cancel(reminder_id, user_id=user)
        except ValueError as err:
            raise intent.IntentHandleError(str(err)) from err
        return _response(intent_obj, f'Reminder cancelled: {item.text}', f'Напоминание отменено: {item.text}')


class SnoozeReminder(intent.IntentHandler):
    intent_type = f'{DOMAIN}.SnoozeReminder'
    description = 'Snooze a pending reminder by a duration or until a specified time.'

    async def async_handle(self, intent_obj):
        manager = _manager(intent_obj.hass)
        user = _user(intent_obj)
        _identifier(intent_obj)
        delay, date = _slot(intent_obj, 'delay'), _slot(intent_obj, 'date')
        if (delay is None) == (date is None):
            raise intent.IntentHandleError('provide either delay or date')
        delay = _delay(delay) if delay is not None else None
        date = _date(date, intent_obj.hass) if date is not None else None
        reminder_id = await _resolve_id(manager, intent_obj, user)
        try:
            item = await manager.async_snooze(reminder_id, delay_seconds=delay, date=date, user_id=user)
        except ValueError as err:
            raise intent.IntentHandleError(str(err)) from err
        formatted = _format_date(intent_obj.hass, item.date)
        return _response(intent_obj, f'Reminder snoozed to {formatted}', f'Напоминание перенесено на {formatted}')


_HANDLERS = (CreateReminder, ListReminders, CancelReminder, SnoozeReminder)


async def async_setup_intents(hass):
    """Register the Assist intent handlers."""
    for handler in _HANDLERS:
        intent.async_register(hass, handler())


async def async_remove_intents(hass):
    """Remove the Assist intent handlers."""
    for handler in _HANDLERS:
        intent.async_remove(hass, handler.intent_type)
