"""Deliver reminders through Assist satellites."""

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable

CONF_SATELLITES = "satellites"
CONF_PREANNOUNCE = "preannounce"
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_SNOOZE_INTERVALS = "snooze_intervals"
SNOOZE_ACTION_PREFIX = "voice_reminders_snooze"
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_NOTIFY_SERVICE_RE = re.compile(r"^[a-z0-9_]+$")
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_LOGGER = logging.getLogger(__name__)

__all__ = ["CONF_SATELLITES", "CONF_PREANNOUNCE", "resolve_satellites",
           "CONF_NOTIFY_TARGETS", "resolve_notify_targets", "async_notify",
           "CONF_SNOOZE_INTERVALS", "SNOOZE_ACTION_PREFIX", "parse_snooze_intervals",
           "async_register_snooze_actions", "async_announce", "async_delivery_hook"]


def resolve_satellites(hass: Any, setting: str | None) -> list[str]:
    """Resolve a satellite setting to entity IDs.

    Args:
        hass: Home Assistant instance with an entity registry.
        setting: Comma-separated entity IDs, all, or none.

    Returns:
        Entity IDs in configured order, or sorted registry order for all.

    Raises:
        ValueError: If an entity ID is invalid.
    """
    setting = (setting or "").strip() or "all"
    if setting == "none":
        return []
    if setting == "all":
        registry = hass.entity_registry
        return sorted(entity_id for entity_id in (registry.entities if registry else {})
                      if entity_id.startswith("assist_satellite."))
    result = []
    for part in setting.split(","):
        part = part.strip()
        if not part:
            continue
        if not _ENTITY_ID_RE.fullmatch(part):
            raise ValueError(f"invalid satellite entity_id: {part}")
        if part not in result:
            result.append(part)
    return result


def resolve_notify_targets(setting: str | None) -> dict[str, str]:
    """Resolve user IDs to notify service names.

    Args:
        setting: Comma-separated user ID and service pairs.

    Returns:
        Mapping from user IDs to notify service names without the domain.

    Raises:
        ValueError: If a pair is invalid.
    """
    result = {}
    for part in (setting or "").split(","):
        part = part.strip()
        if not part:
            continue
        user_id, separator, service = part.partition(":")
        user_id, service = user_id.strip(), service.strip()
        if service.startswith("notify."):
            service = service[len("notify."):]
        if not separator or not _USER_ID_RE.fullmatch(user_id) or not _NOTIFY_SERVICE_RE.fullmatch(service):
            raise ValueError(f"invalid notify target: {part}")
        result[user_id] = service
    return result


def parse_snooze_intervals(setting: str | None) -> list[int]:
    """Parse configured snooze intervals.

    Args:
        setting: Comma-separated intervals in minutes.

    Returns:
        Distinct positive intervals in configured order.

    Raises:
        ValueError: If an interval is invalid or there are more than five.
    """
    result = []
    for part in (setting or "").split(","):
        token = part.strip()
        if not token:
            continue
        if not re.fullmatch(r"[0-9]+", token) or int(token) <= 0:
            raise ValueError(f"invalid snooze interval: {token}")
        value = int(token)
        if value not in result:
            result.append(value)
            if len(result) > 5:
                raise ValueError("too many snooze intervals")
    return result


def async_register_snooze_actions(hass: Any, manager: Any) -> Callable[[], None]:
    """Register the notification action listener.

    Args:
        hass: Home Assistant instance.
        manager: Reminder manager.

    Returns:
        A callable that removes the listener.
    """
    async def handle_action(event: Any) -> None:
        if event.data.get("action") != SNOOZE_ACTION_PREFIX:
            return
        try:
            data = event.data.get("action_data")
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                raise ValueError("action_data must be an object")
            reminder_id = data.get("reminder_id")
            minutes = data.get("delay_minutes")
            if (not isinstance(reminder_id, str) or isinstance(minutes, bool)
                    or not isinstance(minutes, int) or minutes <= 0):
                raise ValueError("invalid reminder ID or delay")
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Invalid snooze action data: %s", err)
            return
        try:
            await manager.async_snooze(reminder_id, delay_seconds=minutes * 60)
        except Exception as err:
            _LOGGER.warning("Failed to snooze reminder %s: %s", reminder_id, err)

    return hass.bus.async_listen("mobile_app_notification_action", handle_action)


async def async_notify(hass: Any, reminder: Any, service: str,
                       snooze_minutes: list[int] | None = None) -> bool:
    """Send a reminder through a notify service.

    Args:
        hass: Home Assistant instance.
        reminder: Reminder to send.
        service: Notify service name without the domain.
        snooze_minutes: Optional intervals for snooze notifications.

    Returns:
        True if the service was called successfully.
    """
    from homeassistant.exceptions import ServiceNotFound

    try:
        await hass.services.async_call("notify", service,
                                       {"message": reminder.text, "title": "Reminder"}, context=None)
        for minutes in snooze_minutes or []:
            payload = {"message": reminder.text, "title": f"Snooze {minutes} min",
                       "action": SNOOZE_ACTION_PREFIX,
                       "action_data": json.dumps({"reminder_id": reminder.id, "delay_minutes": minutes})}
            await hass.services.async_call("notify", service, payload, context=None)
    except ServiceNotFound:
        _LOGGER.warning("Notify service %s is unavailable", service)
        return False
    return True


async def async_announce(hass: Any, reminder: Any, satellites: list[str],
                         preannounce: str | None = None) -> bool:
    """Announce a reminder to the given satellites.

    Args:
        hass: Home Assistant instance.
        reminder: Reminder to announce.
        satellites: Target entity IDs.
        preannounce: Optional phrase before the reminder.

    Returns:
        True if the service was called successfully.
    """
    if not satellites:
        return False
    payload = {"entity_id": satellites, "text": reminder.text, "announce": True}
    if isinstance(preannounce, str) and preannounce.strip():
        payload["preannounce"] = preannounce.strip()
    from homeassistant.exceptions import ServiceNotFound

    try:
        await hass.services.async_call("tts", "speak", payload, context=None)
    except ServiceNotFound:
        _LOGGER.warning("TTS speak service is unavailable")
        return False
    return True


def async_delivery_hook(hass: Any, settings: dict) -> Callable[[Any], Awaitable[None]]:
    """Create a non-raising reminder delivery callback.

    Args:
        hass: Home Assistant instance.
        settings: Mutable delivery settings read on each invocation.

    Returns:
        An asynchronous reminder callback.
    """
    async def _deliver_tts(reminder: Any) -> None:
        """Deliver through satellites independently of notifications."""
        try:
            satellites = resolve_satellites(hass, settings[CONF_SATELLITES])
        except ValueError as err:
            _LOGGER.warning("Invalid satellite settings: %s", err)
        except Exception:
            _LOGGER.exception("Failed to resolve reminder satellites")
        else:
            try:
                await async_announce(hass, reminder, satellites, settings.get(CONF_PREANNOUNCE, ""))
            except Exception:
                _LOGGER.exception("Failed to announce reminder")

    async def _deliver_push(reminder: Any) -> None:
        """Deliver notifications independently of satellite announcements."""
        try:
            targets = resolve_notify_targets(settings.get(CONF_NOTIFY_TARGETS, ""))
            try:
                snooze_minutes = parse_snooze_intervals(settings.get(CONF_SNOOZE_INTERVALS, ""))
            except ValueError as err:
                _LOGGER.warning("Invalid snooze interval settings: %s", err)
                snooze_minutes = []
        except ValueError as err:
            _LOGGER.warning("Invalid notify target settings: %s", err)
        except Exception:
            _LOGGER.exception("Failed to notify reminder owner")
        else:
            try:
                service = targets.get(reminder.owner_user_id)
                if service:
                    await async_notify(hass, reminder, service, snooze_minutes)
            except Exception:
                _LOGGER.exception("Failed to notify reminder owner")

    async def deliver(reminder: Any) -> None:
        """Deliver one reminder without disrupting the scheduler."""
        await asyncio.gather(_deliver_tts(reminder), _deliver_push(reminder))

    return deliver
