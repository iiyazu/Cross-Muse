"""Frozen contracts shared by the offline xmuse data commands.

This module intentionally contains no lifecycle or persistence orchestration.
Keeping the stable error shape and wire identifiers here lets the command
entrypoint and its narrow authority modules share them without importing one
another.
"""

from __future__ import annotations

from typing import Any

from xmuse_core.runtime.root_contract import (
    DATA_OPERATION_JOURNAL_NAME,
    GOD_SESSIONS_NAME,
)

COMMAND_SCHEMA = "xmuse_data_command/v1"
DOCTOR_SCHEMA = "xmuse_data_doctor/v1"
BACKUP_SCHEMA = "xmuse_data_backup/v1"
OPERATION_SCHEMA = "xmuse_data_operation/v1"
CHAT_SCHEMA_CONTRACT = "xmuse.chat_db/v1"
ROOM_SCHEMA_CONTRACT = "xmuse.room_db/v1"
DATA_SCHEMA_VERSION = 1

SESSION_NAME = GOD_SESSIONS_NAME
BACKUP_MANIFEST_NAME = "manifest.json"
OPERATION_JOURNAL_NAME = DATA_OPERATION_JOURNAL_NAME


class DataError(RuntimeError):
    """Stable user-facing data lifecycle error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


__all__ = [
    "BACKUP_MANIFEST_NAME",
    "BACKUP_SCHEMA",
    "CHAT_SCHEMA_CONTRACT",
    "COMMAND_SCHEMA",
    "DATA_SCHEMA_VERSION",
    "DOCTOR_SCHEMA",
    "DataError",
    "OPERATION_JOURNAL_NAME",
    "OPERATION_SCHEMA",
    "ROOM_SCHEMA_CONTRACT",
    "SESSION_NAME",
]
