"""Safely publish the integration's Assist sentences into HA's config directory."""
from __future__ import annotations

import hashlib
from pathlib import Path

_SENTENCE_NAME = "voice_reminders.yaml"
_HASH_NAME = ".voice_reminders.yaml.sha256"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install_sentences(config_dir: str, source_dir: str) -> str:
    """Install/update an unchanged managed file; preserve user-owned edits.

    Returns ``created``, ``updated``, ``unchanged`` or ``conflict``. A hash
    sidecar records the exact previous integration-owned version.
    """
    source = Path(source_dir) / "sentences" / "ru" / _SENTENCE_NAME
    target_dir = Path(config_dir) / "custom_sentences" / "ru"
    target = target_dir / _SENTENCE_NAME
    marker = target_dir / _HASH_NAME
    shipped = source.read_bytes()
    shipped_hash = _digest(shipped)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Never follow a user-provided symlink out of the sentence directory.
    if target.is_symlink() or marker.is_symlink():
        return "conflict"

    if not target.exists():
        target.write_bytes(shipped)
        marker.write_text(shipped_hash, encoding="ascii")
        return "created"

    current = target.read_bytes()
    current_hash = _digest(current)
    if current_hash == shipped_hash:
        marker.write_text(shipped_hash, encoding="ascii")
        return "unchanged"

    try:
        previous_hash = marker.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        previous_hash = ""
    if previous_hash and current_hash == previous_hash:
        target.write_bytes(shipped)
        marker.write_text(shipped_hash, encoding="ascii")
        return "updated"

    return "conflict"
