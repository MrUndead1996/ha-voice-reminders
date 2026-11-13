"""Standalone data model for voice reminders."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

STATUS_PENDING = "pending"
STATUS_FIRED = "fired"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUSES = frozenset({STATUS_PENDING, STATUS_FIRED, STATUS_DONE, STATUS_CANCELLED})

RECURRENCE_NONE = "none"
RECURRENCE_DAILY = "daily"
RECURRENCE_WEEKLY = "weekly"
RECURRENCE_MONTHLY = "monthly"
RECURRENCE_TYPES = frozenset(
    {RECURRENCE_NONE, RECURRENCE_DAILY, RECURRENCE_WEEKLY, RECURRENCE_MONTHLY}
)


@dataclass
class Reminder:
    """A reminder and its planned date and recurrence.

    Attributes:
        id: Canonical UUID4 string identifying the reminder.
        text: Reminder text.
        owner_user_id: Identifier of the reminder's owner.
        created_by_user_id: Identifier of the user who created the reminder.
        date: Timezone-aware planned date.
        recurrence: Recurrence type.
        status: Current reminder status.
    """

    id: str
    text: str
    owner_user_id: str
    created_by_user_id: str
    date: datetime
    recurrence: str
    status: str

    def __post_init__(self) -> None:
        """Validate reminder fields after construction.

        Raises:
            ValueError: If any field is invalid.
        """
        try:
            parsed_id = UUID(self.id) if isinstance(self.id, str) else None
        except (ValueError, AttributeError):
            parsed_id = None
        if parsed_id is None or parsed_id.version != 4 or str(parsed_id) != self.id:
            raise ValueError("id must be a canonical UUID4 string")
        for name in ("text", "owner_user_id", "created_by_user_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-blank string")
        if not isinstance(self.date, datetime) or self.date.utcoffset() is None:
            raise ValueError("date must be a timezone-aware datetime")
        if not isinstance(self.recurrence, str) or self.recurrence not in RECURRENCE_TYPES:
            raise ValueError("invalid recurrence")
        self.set_status(self.status)

    def set_status(self, status: str) -> None:
        """Set the status to a supported value.

        Args:
            status: New status.

        Raises:
            ValueError: If the status is invalid.
        """
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("invalid status")
        self.status = status

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation of the reminder."""
        return {
            "id": self.id,
            "text": self.text,
            "owner_user_id": self.owner_user_id,
            "created_by_user_id": self.created_by_user_id,
            "date": self.date.isoformat(),
            "recurrence": self.recurrence,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reminder":
        """Create a reminder from its stored representation.

        Args:
            data: Dictionary containing all reminder fields.

        Returns:
            The validated reminder.

        Raises:
            ValueError: If the payload is missing fields or contains invalid values.
        """
        if not isinstance(data, dict):
            raise ValueError("reminder payload must be a dictionary")
        fields = ("id", "text", "owner_user_id", "created_by_user_id", "date", "recurrence", "status")
        for field in fields:
            if field not in data:
                raise ValueError(f"missing required field: {field}")
            if not isinstance(data[field], str):
                raise ValueError(f"{field} must be a string")
        try:
            date = datetime.fromisoformat(data["date"])
        except ValueError as err:
            raise ValueError("date must be a valid ISO 8601 datetime") from err
        return cls(
            id=data["id"], text=data["text"], owner_user_id=data["owner_user_id"],
            created_by_user_id=data["created_by_user_id"], date=date,
            recurrence=data["recurrence"], status=data["status"],
        )


def create_reminder(
    text: str,
    owner_user_id: str,
    created_by_user_id: str,
    date: datetime,
    recurrence: str = RECURRENCE_NONE,
) -> Reminder:
    """Create a pending reminder with a new UUID4 identifier.

    Args:
        text: Reminder text.
        owner_user_id: Identifier of the reminder's owner.
        created_by_user_id: Identifier of the user who created the reminder.
        date: Timezone-aware planned date.
        recurrence: Recurrence type, defaulting to none.

    Returns:
        The new reminder.

    Raises:
        ValueError: If a field is invalid.
    """
    return Reminder(str(uuid4()), text, owner_user_id, created_by_user_id, date, recurrence, STATUS_PENDING)
