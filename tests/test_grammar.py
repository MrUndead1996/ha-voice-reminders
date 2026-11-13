"""Standalone tests for Russian grammar helpers."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from custom_components.voice_reminders import grammar

NOW = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
TZ = ZoneInfo('Europe/Moscow')

def test_parse_number():
    for text, expected in [('пять', 5), ('две', 2), ('двадцать пять', 25), ('100', 100), ('2.5', 2.5), ('garbage', None)]:
        assert grammar.parse_number(text) == expected

def test_parse_delay():
    for text, expected in [('через 5 минут', 300), ('через двадцать минут', 1200), ('через два часа', 7200), ('полчаса', 1800), ('полтора часа', 5400), ('10 минут', 600), ('bogus', None), ('1 day', None)]:
        assert grammar.parse_delay(text) == expected

def test_parse_datetime():
    for text, local in [('завтра', (14, 13)), ('завтра в 15:00', (14, 15)), ('послезавтра в 8:00', (15, 8)), ('в пятницу утром', (20, 9)), ('в субботу', (14, 13)), ('сегодня вечером', (13, 18)), ('в 6 вечера', (13, 18)), ('вечером', (13, 18))]:
        expected = datetime(2026, 11, local[0], local[1], tzinfo=TZ).astimezone(timezone.utc)
        assert grammar.parse_datetime(text, NOW, TZ) == expected, text
        assert grammar.parse_datetime(text, NOW, TZ).tzinfo == timezone.utc
    assert grammar.parse_datetime('через 2 часа', NOW, TZ) == NOW + timedelta(hours=2)
    assert grammar.parse_datetime('завтра', NOW, None) == NOW + timedelta(days=1)
    assert grammar.parse_datetime('на следующей неделе в понедельник', NOW, TZ) == datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
    assert grammar.parse_datetime('в понедельник на следующей неделе', datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc), TZ) == datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
    for text in ('когда-нибудь', '', '2026-11-14T15:00:00'):
        assert grammar.parse_datetime(text, NOW, TZ) is None

def test_parse_recurrence():
    for text, expected in [('каждый день', 'daily'), ('каждую неделю', 'weekly'), ('раз в месяц', 'monthly'), ('none', 'none'), ('unknown', None)]:
        assert grammar.parse_recurrence(text) == expected

def test_parse_recipient():
    assert 'Аня' in grammar.parse_recipient('Ане')
    assert 'Саша' in grammar.parse_recipient('Сашу')
    assert 'Василий' in grammar.parse_recipient('Василия')
    assert grammar.parse_recipient('alice') == ['alice']

def test_english_numbers_and_delays():
    for text, expected in [('five', 5), ('twenty five', 25), ('twenty-five', 25), ('hundred', 100), ('garbage', None)]:
        assert grammar.parse_number(text) == expected
    for text, expected in [('in 5 minutes', 300), ('in two hours', 7200), ('in 30 seconds', 30), ('half an hour', 1800), ('half hour', 1800), ('an hour and a half', 5400), ('one and a half hours', 5400), ('an hour', 3600), ('bogus', None)]:
        assert grammar.parse_delay(text) == expected


def test_english_datetime():
    for text, day, hour in [('tomorrow at 3 pm', 14, 15), ('tomorrow at 15:00', 14, 15), ('today in the evening', 13, 18), ('on Friday morning', 20, 9), ('in the evening', 13, 18), ('at 6 in the evening', 13, 18), ('next week on Monday', 16, 13), ('next Friday', 20, 13), ('the day after tomorrow at noon', 15, 12), ('at 3 o\'clock', 13, 3)]:
        result = grammar.parse_datetime(text, NOW, TZ)
        assert result == datetime(2026, 11, day, hour, tzinfo=TZ).astimezone(timezone.utc), text
        assert result.tzinfo == timezone.utc
    assert grammar.parse_datetime('in 3 days', NOW, TZ) == NOW + timedelta(days=3)
    for text in ('sometime', '', '2026-11-14T15:00:00', 'tomorrow at 25:00', 'at 3:60'):
        assert grammar.parse_datetime(text, NOW, TZ) is None


def test_english_recurrence():
    for text, expected in [('every day', 'daily'), ('each day', 'daily'), ('once a week', 'weekly'), ('each week', 'weekly'), ('every month', 'monthly'), ('once a month', 'monthly'), ('monthly', 'monthly'), ('unknown', None)]:
        assert grammar.parse_recurrence(text) == expected
