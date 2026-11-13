"""Small, dependency-free parsers for Russian and English Assist slots."""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

_NUMBERS = dict(zip(('ноль один одна одно два две три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто').split(), (0, 1, 1, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 30, 40, 50, 60, 70, 80, 90, 100)))

_NUMBERS.update(dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred'.split(), list(range(21)) + list(range(30, 100, 10)) + [100])))

def _normalize(text):
    return ' '.join(text.casefold().split())

def parse_number(text: str) -> float | None:
    """Parse a decimal number or additive number words up to 100."""
    text = _normalize(text)
    if re.fullmatch(r'\d+(?:\.\d+)?', text):
        return float(text)
    words = re.sub(r'(?<=[a-z])-(?=[a-z])', ' ', text).split()
    if not words or any(word not in _NUMBERS for word in words):
        return None
    values = [_NUMBERS[word] for word in words]
    if len(values) > 2 or (len(values) == 2 and not (20 <= values[0] <= 90 and 1 <= values[1] <= 9)):
        return None
    return float(sum(values))

_UNITS = {'секунда': 1, 'секунды': 1, 'секунд': 1, 'second': 1, 'seconds': 1,
          'минута': 60, 'минуты': 60, 'минут': 60, 'minute': 60, 'minutes': 60,
          'час': 3600, 'часа': 3600, 'часов': 3600, 'hour': 3600, 'hours': 3600}

def parse_delay(text: str) -> float | None:
    """Parse a duration in seconds, minutes, or hours into seconds."""
    text = _normalize(text)
    if text.startswith('через '):
        text = text[6:]
    if text.startswith('in '):
        text = text[3:]
    if text in ('half an hour', 'half hour'):
        return 1800.0
    if text in ('an hour and a half', 'one and a half hours'):
        return 5400.0
    if text == 'полчаса':
        return 1800.0
    if text == 'полтора часа':
        return 5400.0
    parts = text.rsplit(' ', 1)
    if len(parts) != 2 or parts[1] not in _UNITS:
        return None
    number = 1.0 if parts[0] in ('a', 'an') else parse_number(parts[0])
    return number * _UNITS[parts[1]] if number is not None else None

_WEEKDAYS = {'понедельник': 0, 'вторник': 1, 'среда': 2, 'среду': 2, 'четверг': 3, 'пятница': 4, 'пятницу': 4, 'суббота': 5, 'субботу': 5, 'воскресенье': 6}
_PARTS = {'утром': 9, 'днем': 12, 'днём': 12, 'вечером': 18, 'вечера': 18, 'ночью': 22}

def parse_datetime(text: str, now: datetime, tz: ZoneInfo | None) -> datetime | None:
    """Interpret relative and calendar expressions as UTC instants."""
    text = _normalize(text)
    if text.startswith(('через ', 'in ')) and (text.startswith('через ') or re.fullmatch(r'in .+ (?:seconds?|minutes?|hours?|days?|weeks?|months?)', text)):
        duration = text[6:] if text.startswith('через ') else text[3:]
        seconds = parse_delay(duration)
        if seconds is None:
            parts = duration.rsplit(' ', 1)
            units = {'день': 86400, 'дня': 86400, 'дней': 86400, 'неделя': 604800, 'недели': 604800, 'недель': 604800, 'месяц': 2592000, 'месяца': 2592000, 'месяцев': 2592000, 'day': 86400, 'days': 86400, 'week': 604800, 'weeks': 604800, 'month': 2592000, 'months': 2592000}
            if len(parts) == 2 and parts[1] in units:
                number = parse_number(parts[0])
                if number is not None:
                    seconds = number * units[parts[1]]
        try:
            return (now + timedelta(seconds=seconds)).astimezone(timezone.utc) if seconds is not None else None
        except OverflowError:
            return None
    local = now.astimezone(tz or timezone.utc)
    next_week = 'на следующей неделе' in text or bool(re.search(r'(?<!\w)next week(?!\w)', text))
    text = re.sub(r'(?<!\w)next week(?!\w)', ' ', text)
    if re.search(r'(?<!\w)next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?!\w)', text):
        next_week = True
        text = re.sub(r'(?<!\w)next\s+(?=(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?!\w))', '', text)
    text = text.replace('на следующей неделе', ' ').strip()
    day_offset = None
    weekday = None
    for word, offset in [('the day after tomorrow', 2), ('tomorrow', 1), ('today', 0), ('послезавтра', 2), ('завтра', 1), ('сегодня', 0)]:
        if re.search(r'(?<!\w)' + word + r'(?!\w)', text):
            day_offset = offset
            text = re.sub(r'(?<!\w)' + word + r'(?!\w)', ' ', text, count=1)
            break
    weekdays = {**_WEEKDAYS, **dict(zip(('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'), range(7)))}
    for word, index in weekdays.items():
        match = re.search(r'(?<!\w)(?:(?:в|on)\s+)?' + word + r'(?!\w)', text)
        if match:
            if day_offset is not None:
                return None
            weekday = index
            text = text[:match.start()] + ' ' + text[match.end():]
            break
    part = None
    parts_of_day = {**_PARTS, 'in the morning': 9, 'morning': 9, 'at noon': 12, 'in the afternoon': 12, 'afternoon': 12, 'in the evening': 18, 'evening': 18, 'at night': 22, 'night': 22}
    for word, hour in parts_of_day.items():
        match = re.search(r'(?<!\w)' + word + r'(?!\w)', text)
        if match:
            part = (word, hour)
            text = text[:match.start()] + ' ' + text[match.end():]
            break
    text = ' '.join(text.split())
    hour, minute = local.hour, local.minute
    if text:
        english = re.fullmatch(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|o'clock)?", text)
        if english:
            hour, minute = int(english.group(1)), int(english.group(2) or 0)
            meridiem = english.group(3)
            if meridiem in ('am', 'pm'):
                if not 1 <= hour <= 12:
                    return None
                hour = hour % 12 + (12 if meridiem == 'pm' else 0)
            elif not english.group(2) and not meridiem and not part:
                return None
            if part and part[0] in ('in the evening', 'evening') and 1 <= hour <= 11:
                hour += 12
            if hour > 23 or minute > 59:
                return None
        else:
            match = re.fullmatch(r'в\s+(\d{1,2})(?::(\d{2})|\s+час(?:а|ов)?(?:\s+(\d{1,2})\s+минут(?:а|ы)?)?)?', text)
            if not match or (not part and ':' not in text and 'час' not in text):
                return None
            hour = int(match.group(1))
            minute = int(match.group(2) or match.group(3) or 0)
            if part and part[0] in ('вечера', 'вечером') and 1 <= hour <= 11:
                hour += 12
            if hour > 23 or minute > 59:
                return None
    elif part:
        hour, minute = part[1], 0
    elif day_offset is None and weekday is None:
        return None
    if next_week and weekday is None:
        return None
    if next_week:
        start_next_week = (local - timedelta(days=local.weekday())) + timedelta(days=7)
        result = (start_next_week + timedelta(days=weekday)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        offset = (weekday - local.weekday()) % 7 if weekday is not None else (day_offset or 0)
        result = (local + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if weekday is not None and result <= local:
            result += timedelta(days=7)
    return result.astimezone(timezone.utc)

def parse_recurrence(text: str) -> str | None:
    """Map supported English and Russian recurrence phrases to manager values."""
    text = _normalize(text)
    phrases = {'none': 'none', 'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly', 'каждый день': 'daily', 'каждые день': 'daily', 'ежедневно': 'daily', 'каждую неделю': 'weekly', 'каждые неделю': 'weekly', 'раз в неделю': 'weekly', 'еженедельно': 'weekly', 'каждый месяц': 'monthly', 'каждые месяц': 'monthly', 'раз в месяц': 'monthly', 'ежемесячно': 'monthly'}
    phrases.update({'every day': 'daily', 'each day': 'daily', 'every week': 'weekly', 'each week': 'weekly', 'once a week': 'weekly', 'every month': 'monthly', 'each month': 'monthly', 'once a month': 'monthly'})
    return phrases.get(text)

def parse_recipient(text: str) -> list[str]:
    """Return plausible nominative names for a Russian declined name."""
    if not isinstance(text, str):
        return [text]
    original = text
    text = ' '.join(text.split())
    result = [original]
    if not re.fullmatch(r'[А-Яа-яЁё]+', text):
        return result
    lower = text.casefold()
    if lower.endswith('ия'):
        result.append(text[:-2] + 'ий')
    for suffix in ('ей', 'ой', 'ою', 'ом', 'ем', 'у', 'ю', 'е', 'ы', 'и'):
        if lower.endswith(suffix) and len(text) > len(suffix):
            stem = text[:-len(suffix)]
            if suffix == 'ей':
                result.append(stem + 'ь')
            result.extend((stem + 'а', stem + 'я'))
            break
    return list(dict.fromkeys(result))[:4]
