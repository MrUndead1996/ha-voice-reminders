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
