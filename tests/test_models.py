"""Tests for the standalone reminder model."""

from datetime import datetime, timezone
from uuid import UUID

from custom_components.voice_reminders.models import (
    RECURRENCE_DAILY, RECURRENCE_MONTHLY, RECURRENCE_NONE, RECURRENCE_TYPES,
    RECURRENCE_WEEKLY, STATUSES, STATUS_CANCELLED, STATUS_DONE, STATUS_FIRED,
    STATUS_PENDING, Reminder, create_reminder,
)


def assert_invalid(function, *args, **kwargs):
    """Assert that a call rejects invalid input."""
    try:
        function(*args, **kwargs)
    except ValueError:
        return
    assert False, "expected ValueError"


def make_reminder():
    return create_reminder("Take medicine", "owner", "creator", datetime(2026, 1, 2, tzinfo=timezone.utc))


def test_create_defaults():
    reminder = make_reminder()
    assert UUID(reminder.id).version == 4
    assert reminder.status == STATUS_PENDING
    assert reminder.recurrence == RECURRENCE_NONE


def test_create_validation():
    date = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert_invalid(create_reminder, "  ", "owner", "creator", date)
    assert_invalid(create_reminder, "text", " ", "creator", date)
    assert_invalid(create_reminder, "text", "owner", "", date)
    assert_invalid(create_reminder, "text", "owner", "creator", datetime(2026, 1, 2))
    assert_invalid(create_reminder, "text", "owner", "creator", date, "yearly")
    assert_invalid(Reminder, "bad", "text", "owner", "creator", date, RECURRENCE_NONE, STATUS_PENDING)


def test_set_status():
    reminder = make_reminder()
    for status in (STATUS_FIRED, STATUS_DONE, STATUS_CANCELLED, STATUS_PENDING):
        reminder.set_status(status)
        assert reminder.status == status
    assert_invalid(reminder.set_status, "unknown")
    assert reminder.status == STATUS_PENDING


def test_round_trip():
    reminder = make_reminder()
    reminder.recurrence = RECURRENCE_WEEKLY
    reminder.set_status(STATUS_FIRED)
    payload = reminder.to_dict()
    assert isinstance(payload["date"], str)
    assert Reminder.from_dict(payload) == reminder
    assert Reminder.from_dict(payload).to_dict() == payload


def test_invalid_payloads():
    payload = make_reminder().to_dict()
    for key in payload:
        missing = payload.copy()
        del missing[key]
        assert_invalid(Reminder.from_dict, missing)
        wrong_type = payload.copy()
        wrong_type[key] = 12
        assert_invalid(Reminder.from_dict, wrong_type)
    assert_invalid(Reminder.from_dict, None)
    assert_invalid(Reminder.from_dict, {**payload, "date": "2026-01-02T12:00:00"})
    assert_invalid(Reminder.from_dict, {**payload, "date": "not a date"})
    assert_invalid(Reminder.from_dict, {**payload, "status": "bad"})
    assert_invalid(Reminder.from_dict, {**payload, "recurrence": "bad"})


def test_constants():
    assert STATUSES == frozenset({"pending", "fired", "done", "cancelled"})
    assert RECURRENCE_TYPES == frozenset({"none", "daily", "weekly", "monthly"})
    assert {STATUS_PENDING, STATUS_FIRED, STATUS_DONE, STATUS_CANCELLED} == STATUSES
    assert {RECURRENCE_NONE, RECURRENCE_DAILY, RECURRENCE_WEEKLY, RECURRENCE_MONTHLY} == RECURRENCE_TYPES
