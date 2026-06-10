from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from xmuse_core.chat.driver import ChatDriver
from xmuse_core.platform.coordinator_incidents import COORDINATOR_INCIDENTS_FILENAME
from xmuse_core.self_evolution.watcher import TerminalRunWatcher
from xmuse_core.structuring.blueprint_execution import BlueprintAutomationService

logger = logging.getLogger(__name__)


class CoordinatorControlService:
    """Stage 0 coordinator service for lifecycle and degraded-path evidence.

    The runner owns process lifecycle, writer lease, and scheduling cadence.
    PlatformOrchestrator owns lane execution/review/merge transitions through
    LaneStateMachine. This service records coordinator-level evidence for
    non-lane failures without becoming a second state writer.
    """

    def __init__(
        self,
        *,
        xmuse_root: Path,
        runner_id: str,
        now=time.time,
    ) -> None:
        self._xmuse_root = xmuse_root
        self._runner_id = runner_id
        self._now = now
        self._incident_path = xmuse_root / COORDINATOR_INCIDENTS_FILENAME

    @property
    def incident_path(self) -> Path:
        return self._incident_path

    def record_lifecycle(
        self,
        operation: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append_record(
            {
                "kind": "lifecycle",
                "component": "platform_runner",
                "operation": operation,
                "runner_id": self._runner_id,
                "created_at": self._now(),
                "details": details or {},
            }
        )

    def record_dead_letter(
        self,
        *,
        component: str,
        operation: str,
        error: BaseException,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append_record(
            self._failure_record(
                kind="dead_letter",
                component=component,
                operation=operation,
                error=error,
                details=details,
            )
        )

    def record_degraded(
        self,
        *,
        component: str,
        operation: str,
        error: BaseException,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._append_record(
            self._failure_record(
                kind="degraded",
                component=component,
                operation=operation,
                error=error,
                details=details,
            )
        )

    def drive_blueprint_automation(
        self,
        service: BlueprintAutomationService,
        *,
        worker_id: str,
    ):
        try:
            outcome = service.tick(worker_id=worker_id)
        except Exception as exc:
            logger.exception("blueprint automation tick failed; continuing")
            self.record_dead_letter(
                component="blueprint_automation",
                operation="tick",
                error=exc,
                details={"worker_id": worker_id},
            )
            return None
        if outcome is not None:
            logger.info(
                "blueprint automation: started planning_run=%s from event=%s",
                outcome.planning_run_id,
                outcome.claimed_event_id,
            )
        return outcome

    def drive_auto_evolve(self, watcher: TerminalRunWatcher) -> list[Any]:
        try:
            outcomes = list(watcher.tick())
        except Exception as exc:
            logger.exception("auto-evolve tick failed; continuing")
            self.record_degraded(
                component="auto_evolve",
                operation="tick",
                error=exc,
            )
            return []
        for outcome in outcomes:
            if outcome.spawned is not None:
                logger.info(
                    "auto-evolve: spawned %s from %s",
                    outcome.spawned.spawned_graph_id,
                    outcome.source_run_id,
                )
            elif outcome.skip_reason:
                logger.debug(
                    "auto-evolve: skipped %s (%s)",
                    outcome.source_run_id,
                    outcome.skip_reason,
                )
        return outcomes

    def drive_chat(self, driver: ChatDriver) -> list[Any]:
        try:
            outcomes = list(driver.tick())
        except Exception as exc:
            logger.exception("chat-driver tick failed; continuing")
            self.record_degraded(
                component="chat_driver",
                operation="tick",
                error=exc,
            )
            return []
        for outcome in outcomes:
            if outcome.reply_message_id:
                logger.info(
                    "chat-driver: %s replied in %s (envelope=%s)",
                    outcome.god_role,
                    outcome.conversation_id,
                    outcome.envelope_type,
                )
            elif outcome.skip_reason:
                logger.warning(
                    "chat-driver: %s skipped %s (%s)",
                    outcome.god_role,
                    outcome.source_message_id,
                    outcome.skip_reason,
                )
        return outcomes

    async def tick_peer_chat_scheduler(self, peer_chat_scheduler) -> None:
        try:
            await peer_chat_scheduler.tick_once()
        except Exception as exc:
            logger.exception("peer-chat scheduler tick failed; continuing")
            self.record_degraded(
                component="peer_chat_scheduler",
                operation="tick_once",
                error=exc,
            )

    def _failure_record(
        self,
        *,
        kind: str,
        component: str,
        operation: str,
        error: BaseException,
        details: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "component": component,
            "operation": operation,
            "runner_id": self._runner_id,
            "created_at": self._now(),
            "error_type": type(error).__name__,
            "error": str(error),
            "details": details or {},
        }

    def _append_record(self, record: dict[str, Any]) -> None:
        try:
            self._incident_path.parent.mkdir(parents=True, exist_ok=True)
            with self._incident_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
        except OSError:
            logger.warning(
                "coordinator incident record write failed",
                extra={"incident_path": str(self._incident_path)},
            )
