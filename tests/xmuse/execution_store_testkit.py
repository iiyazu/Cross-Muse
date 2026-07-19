"""Test-only aggregate for fixtures spanning several execution authorities.

Production composition must inject one least-authority execution capability at a
time.  A few integration fixtures intentionally exercise an operator decision,
controller run, and review receipt in one scenario; this helper keeps that
convenience out of the production package.
"""

from __future__ import annotations

from pathlib import Path

from xmuse_core.chat.room_execution_controller_store import RoomExecutionControllerStore
from xmuse_core.chat.room_execution_operator_store import RoomExecutionOperatorStore
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_execution_review_store import RoomExecutionReviewStore
from xmuse_core.chat.room_execution_runtime_store import RoomExecutionRuntimeStore


class TestExecutionStore(
    RoomExecutionOperatorStore,
    RoomExecutionControllerStore,
    RoomExecutionRuntimeStore,
    RoomExecutionReviewStore,
    RoomExecutionLedgerReader,
):
    """Fixture composition only; it owns no SQL and is never importable by production."""

    __test__ = False

    def __init__(self, db_path: Path | str) -> None:
        # The controller initializer provides the shared database and reader
        # fields consumed by the inherited capability implementations.
        RoomExecutionControllerStore.__init__(self, db_path)
