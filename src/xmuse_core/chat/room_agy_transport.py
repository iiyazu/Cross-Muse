"""Antigravity CLI (``agy``) transport for participant-owned room observations.

The adapter owns one long-lived ``agy`` process per ``(conversation_id,
participant_id)``, created lazily under a per-participant singleflight lock.
Each process runs ``agy --input-format stream-json --output-format
stream-json --model <m> --dangerously-skip-permissions [--conversation <id>]
-p=`` (``-p=`` last) and reads one NDJSON ``user`` message per stdin line,
running one turn each while keeping context across turns.  The Room MCP
server (``xmuse-room``) reaches the model through agy's ``call_mcp_tool``
tool; the agent produces Room truth only through
``chat_room_submit_outcome`` and coordinates through the lease-bound board
tools.  The ``RoomParticipantHost`` still decides completion from durable
state: provider text and ``result`` lines only describe transport progress.

``agy`` executes its own tools without asking the client, so unattended turns
pass ``--dangerously-skip-permissions`` strictly inside the bubblewrap
sandbox built by ``room_agy_sandbox`` (read-only for non-owners, writable
clone for owners).  Provider output only describes transport progress: a
``SUCCESS`` result means the provider turn ended, never that the Room commit
happened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.codex_app_server_transport import _format_turn_prompt
from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import Participant
from xmuse_core.chat.room_acp_transport import ROOM_ACP_OUTCOME_REMINDER
from xmuse_core.chat.room_agent_stream import RoomAgentStreamProjector
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_ports import ExecutionReviewReceiptWriter
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomTransportResult,
    RoomTurnProgress,
)
from xmuse_core.chat.room_memory_runtime import RoomMemoryContextReceiptPort
from xmuse_core.chat.room_observation_transport_base import (
    ROOM_CONTEXT_BYTE_LIMIT,
    ProviderNeutralDeliveryKit,
    build_room_observation_prompt,
    diagnostic_text,
    failed_result,
    normalized_text,
    sanitized_agent_environment,
    terminate_process_group,
    tool_call_fingerprint,
)
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)

logger = logging.getLogger(__name__)

ROOM_AGY_PROVIDER_SESSION_KIND = "agy_conversation"
ROOM_AGY_SUPPORTED_CLI_KINDS = (AgentRuntime.ANTIGRAVITY.value,)
ROOM_AGY_OUTCOME_REMINDER = ROOM_ACP_OUTCOME_REMINDER
# agy step_update lines embed full tool arguments (whole files for writes).
ROOM_AGY_STDOUT_LINE_LIMIT = 16 * 1024 * 1024


class RoomAgyTransportError(RuntimeError):
    """Stable agy transport failure carrying a Room reason code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class AgyTransportConfig:
    """Immutable attachment settings for the agy CLI transport.

    ``command_builder`` returns the full argv (sandbox prefix plus agy args)
    for one process; it receives the agy conversation id to resume, or None
    for a fresh conversation.  The transport stays independent of how the
    sandbox argv is built.
    """

    workspace: Path | str
    command_builder: Callable[[str | None], tuple[str, ...]]
    default_model: str
    confinement: str
    owner: bool = False
    outcome_reminder: bool = True
    turn_idle_timeout_s: float = 300.0
    initialize_timeout_s: float = 60.0
    shutdown_grace_s: float = 5.0

    def __post_init__(self) -> None:
        if not callable(self.command_builder):
            raise ValueError("room_agy_command_builder_invalid")
        if not normalized_text(self.default_model):
            raise ValueError("room_agy_default_model_invalid")
        if not normalized_text(self.confinement):
            raise ValueError("room_agy_confinement_invalid")
        for name in ("turn_idle_timeout_s", "initialize_timeout_s", "shutdown_grace_s"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"room_agy_{name}_invalid")


class _PreviewStreamClosed(Exception):
    """The disposable preview stream has no more events."""


class _AgyPreviewStream:
    """One disposable listener fed by agy stdout events."""

    def __init__(self, session: _AgySession) -> None:
        self._session = session
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._closed = False

    def push(self, event: dict[str, Any]) -> None:
        if not self._closed:
            self._queue.put_nowait(event)

    async def receive(self) -> dict[str, Any]:
        event = await self._queue.get()
        if event is None:
            raise _PreviewStreamClosed()
        return event

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._session.preview_listeners.discard(self)
        self._queue.put_nowait(None)


@dataclass
class _AgySession:
    """One live agy process bound to a durable participant identity."""

    generation: int
    god_session_id: str
    agy_conversation_id: str | None
    process: asyncio.subprocess.Process
    prompt_task: asyncio.Task[Any] | None = None
    preview_listeners: set[_AgyPreviewStream] = field(default_factory=set)
    line_queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    reader_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None
    closed: bool = False


def resolve_agy_model(participant_model: str | None, default_model: str | None) -> str:
    """Use the participant's model when set, else the configured default."""

    candidate = normalized_text(participant_model)
    if candidate is not None:
        return candidate
    fallback = normalized_text(default_model)
    if fallback is None:
        raise RoomAgyTransportError("room_agy_model_unavailable", "no model configured")
    return fallback


def agy_turn_error_code(error: str) -> str:
    """Classify an agy ``result`` error so operators can tell quota from outages."""

    lowered = error.lower()
    if "quota" in lowered:
        return "room_agy_quota_exhausted"
    if "api error" in lowered or "request failed" in lowered:
        return "room_agy_api_unreachable"
    return "room_agy_turn_failed"


def _is_room_outcome_mcp_call(tool_name: object, tool_info: object) -> bool:
    """Tolerantly recognize the xmuse-room outcome call (preview evidence only)."""

    if tool_name != "call_mcp_tool" or not isinstance(tool_info, dict):
        return False
    try:
        blob = json.dumps(tool_info, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return False
    return "xmuse-room" in blob and "chat_room_submit_outcome" in blob


class AgyRoomObservationTransport:
    """Deliver observations through participant-bound agy CLI processes."""

    def __init__(
        self,
        *,
        config: AgyTransportConfig,
        registry_path: Path | str,
        control_store: RoomObservationControlStore | None = None,
        skill_decision_store: RoomAttemptSkillDecisionStore | None = None,
        execution_store: ExecutionReviewReceiptWriter | None = None,
        memory_runtime: RoomMemoryContextReceiptPort | None = None,
        stream_projector: RoomAgentStreamProjector | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._workspace = Path(config.workspace).expanduser().resolve()
        self._registry = GodSessionRegistry(registry_path)
        self._controls = control_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._environ = dict(os.environ if environ is None else environ)
        self._kit = ProviderNeutralDeliveryKit(
            skill_decision_store=skill_decision_store,
            execution_store=execution_store,
            memory_runtime=memory_runtime,
            stream_projector=stream_projector,
            clock=self._clock,
        )
        self._sessions: dict[tuple[str, str], _AgySession] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._next_generation = 1

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        invalid = self._kit.validate_delivery(
            delivery,
            reason_prefix="room_agy",
            supported_cli_kinds=ROOM_AGY_SUPPORTED_CLI_KINDS,
        )
        if invalid is not None:
            return RoomTransportResult("failed", invalid)
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s <= 0
        ):
            return RoomTransportResult("failed", "room_agy_timeout_invalid")

        activation_failure = self._kit.skill_activation_failure(delivery)
        if activation_failure is not None:
            return activation_failure
        if self._controls is not None:
            if not delivery.attempt_id:
                return RoomTransportResult("failed", "room_agy_attempt_binding_missing")
            try:
                self._controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                return failed_result("room_agy_attempt_binding_failed", exc)

        try:
            session = await self._acquire_session(delivery)
        except RoomAgyTransportError as exc:
            self._mark_cleanup(delivery, succeeded=True, reason_code=exc.code)
            return RoomTransportResult("failed", exc.code, diagnostic_text(str(exc)))
        except Exception as exc:
            self._mark_cleanup(
                delivery, succeeded=True, reason_code="room_agy_session_ensure_failed"
            )
            return failed_result("room_agy_session_ensure_failed", exc)

        if session.prompt_task is not None and not session.prompt_task.done():
            return RoomTransportResult("failed", "room_agy_session_busy")
        if session.agy_conversation_id is None:
            await self._fail_session(session, delivery, reason_code="room_agy_session_id_missing")
            return RoomTransportResult("failed", "room_agy_session_id_missing")
        if self._controls is not None:
            if not delivery.attempt_id:
                await self._fail_session(
                    session, delivery, reason_code="room_agy_attempt_binding_missing"
                )
                return RoomTransportResult("failed", "room_agy_attempt_binding_missing")
            try:
                self._controls.bind_provider_session(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    god_session_id=session.god_session_id,
                    provider_session_id=session.agy_conversation_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                await self._fail_session(
                    session, delivery, reason_code="room_agy_attempt_binding_failed"
                )
                return failed_result("room_agy_attempt_binding_failed", exc)

        submission = self._kit.build_context_submission(
            delivery,
            god_session_id=session.god_session_id,
        )
        if len(submission.text.encode("utf-8")) > ROOM_CONTEXT_BYTE_LIMIT:
            await self._fail_session(session, delivery, reason_code="room_skill_context_too_large")
            return RoomTransportResult("failed", "room_skill_context_too_large")
        prompt_text = _format_turn_prompt(
            role=delivery.participant.role,
            msg_type="room_observation",
            prompt=build_room_observation_prompt(
                AgentRuntime.ANTIGRAVITY.value,
                owner=self._config.owner,
            ),
            context=submission.text,
        )
        preview = await self._kit.open_preview(
            delivery,
            subscribe_native_events=self._subscribe_preview_events(session),
            god_session_id=session.god_session_id,
            session_is_current=lambda: self._session_is_current(session),
        )
        self._push_event(session, "turn/started", {"turnId": delivery.transport_request_id})
        provider_succeeded = False
        try:
            prompt_task = asyncio.create_task(
                self._run_agy_turn(
                    session,
                    delivery,
                    prompt_text=prompt_text,
                    turn_id=delivery.transport_request_id,
                ),
                name=f"room-agy-prompt:{delivery.transport_request_id}",
            )
            session.prompt_task = prompt_task
            # Let the prompt write reach the agent before the context receipts
            # claim the exact bounded context was handed to this session.
            await asyncio.sleep(0)
            self._kit.bind_memory_context_receipt(
                delivery,
                context_payload=submission.payload,
                context_payload_sha256=submission.payload_sha256,
            )
            try:
                self._kit.bind_execution_review_receipts(
                    delivery,
                    context_payload=submission.payload,
                    context_payload_sha256=submission.payload_sha256,
                )
            except RoomExecutionStoreError as exc:
                await self._fail_session(session, delivery, reason_code=exc.code)
                return failed_result(exc.code, exc)
            except Exception as exc:
                await self._fail_session(
                    session, delivery, reason_code="room_execution_review_receipt_failed"
                )
                return failed_result("room_execution_review_receipt_failed", exc)
            try:
                self._kit.mark_skill_context_submitted(
                    delivery,
                    payload_sha256=submission.payload_sha256,
                )
            except RoomSkillDecisionError as exc:
                await self._fail_session(session, delivery, reason_code=exc.code)
                return failed_result(exc.code, exc)
            deadline = asyncio.get_running_loop().time() + float(timeout_s)
            reminded = False
            while True:
                try:
                    async with asyncio.timeout_at(deadline):
                        await asyncio.shield(prompt_task)
                except TimeoutError:
                    prompt_task.cancel()
                    await asyncio.gather(prompt_task, return_exceptions=True)
                    await self._fail_session(session, delivery, reason_code="room_agy_timeout")
                    return RoomTransportResult("failed", "room_agy_timeout")
                except RoomAgyTransportError as exc:
                    await self._fail_session(session, delivery, reason_code=exc.code)
                    return RoomTransportResult("failed", exc.code, diagnostic_text(str(exc)))
                except Exception as exc:
                    await self._fail_session(
                        session, delivery, reason_code="room_agy_prompt_failed"
                    )
                    return failed_result("room_agy_prompt_failed", exc)
                if reminded or not self._outcome_reminder_due(delivery):
                    break
                reminded = True
                logger.info(
                    "room_agy_outcome_reminder conversation=%s participant=%s",
                    delivery.conversation_id,
                    delivery.participant.participant_id,
                )
                prompt_task = asyncio.create_task(
                    self._run_agy_turn(
                        session,
                        delivery,
                        prompt_text=ROOM_AGY_OUTCOME_REMINDER,
                        turn_id=delivery.transport_request_id,
                    ),
                    name=f"room-agy-reminder:{delivery.transport_request_id}",
                )
                session.prompt_task = prompt_task
            # "finished" only means the provider turn ended. The host accepts
            # completion only from durable Room state.
            provider_succeeded = True
            return RoomTransportResult("finished")
        except asyncio.CancelledError:
            await self._fail_session(session, delivery, reason_code="room_agy_delivery_cancelled")
            raise
        except Exception as exc:
            await self._fail_session(session, delivery, reason_code="room_agy_transport_error")
            return failed_result("room_agy_transport_error", exc)
        finally:
            session.prompt_task = None
            self._push_event(session, "turn/completed", {"turnId": delivery.transport_request_id})
            for listener in tuple(session.preview_listeners):
                listener.close()
            await self._kit.finalize_preview(preview, provider_succeeded=provider_succeeded)

    def _outcome_reminder_due(self, delivery: RoomObservationDelivery) -> bool:
        """True only while this exact attempt still owns an uncommitted observation."""

        if not self._config.outcome_reminder or self._controls is None:
            return False
        try:
            state = self._controls.reconcile_state(str(delivery.observation["observation_id"]))
        except (KeyError, RoomControlError):
            return False
        binding = state.get("reconcile_binding") or {}
        return (
            state.get("observation_status") == "claimed"
            and state.get("control_state") == "active"
            and binding.get("attempt_id") == delivery.attempt_id
        )

    async def reconcile_cancel(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        attempt: dict[str, Any],
        timeout_s: float,
    ) -> RoomCancelReconcileResult:
        """Cancel and drop only the exact provider generation of one attempt."""

        attempt_id = normalized_text(attempt.get("attempt_id"))
        delivery_generation = normalized_text(attempt.get("provider_session_generation"))
        expected_god_session_id = normalized_text(attempt.get("god_session_id"))
        expected_provider_session_id = normalized_text(attempt.get("provider_session_id"))
        provider_phase = normalized_text(attempt.get("provider_phase")) or "not_started"
        if (
            participant.conversation_id != conversation_id
            or not attempt_id
            or delivery_generation != attempt_id
        ):
            return RoomCancelReconcileResult("pending", "room_agy_cancel_binding_invalid")
        if provider_phase == "not_started":
            return RoomCancelReconcileResult("settled", "room_agy_cancel_session_not_started")
        if provider_phase == "cleanup_succeeded":
            return RoomCancelReconcileResult(
                "settled",
                normalized_text(attempt.get("provider_cleanup_reason"))
                or "room_agy_cancel_cleanup_already_succeeded",
            )
        if expected_provider_session_id is None and expected_god_session_id is None:
            # The provider binding never completed, so no agy generation is
            # provably alive for this attempt; a live replacement session must
            # never be touched from here.
            return RoomCancelReconcileResult(
                "settled", "room_agy_cancel_start_failed_before_binding"
            )
        key = (conversation_id, participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with asyncio.timeout(float(timeout_s)):
                async with lock:
                    session = self._sessions.get(key)
                    if session is None or session.closed:
                        return RoomCancelReconcileResult(
                            "settled", "room_agy_cancel_no_active_session"
                        )
                    if (
                        expected_provider_session_id
                        and session.agy_conversation_id != expected_provider_session_id
                    ):
                        # Rotation always closes the previous process before a
                        # new session exists, so this attempt's exact provider
                        # generation is already provably gone.
                        return RoomCancelReconcileResult(
                            "settled", "room_agy_cancel_binding_superseded"
                        )
                    await self._close_session(session, reason="room_agy_cancel_reconcile")
        except (TimeoutError, ValueError):
            return RoomCancelReconcileResult("pending", "room_agy_cancel_close_failed")
        return RoomCancelReconcileResult("settled", "room_agy_cancel_session_closed")

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        """Rotate (close) the participant session before retrying a missing outcome.

        A provider turn that ended without durable Room truth may have retained
        poisoned conversation state; replaying the same conversation can
        deterministically repeat it. Only the exact bound generation is closed,
        the stored conversation id is dropped so the next process starts fresh,
        and a replacement session is never aborted.
        """

        expected_provider_session_id: str | None = None
        if self._controls is not None and delivery.attempt_id:
            try:
                projection = self._controls.reconcile_state(
                    str(delivery.observation["observation_id"])
                )
            except (KeyError, RoomControlError):
                return False
            attempt = projection.get("reconcile_binding") or {}
            if (
                attempt.get("attempt_id") != delivery.attempt_id
                or attempt.get("provider_session_generation") != delivery.attempt_id
                or attempt.get("provider_phase") not in {"bound", "cleanup_succeeded"}
            ):
                return False
            if attempt.get("provider_phase") == "cleanup_succeeded":
                return True
            expected_provider_session_id = normalized_text(attempt.get("provider_session_id"))
        rotated = await self._rotate_session(
            delivery,
            timeout_s=timeout_s,
            expected_provider_session_id=expected_provider_session_id,
        )
        if rotated:
            self._mark_cleanup(
                delivery, succeeded=True, reason_code="room_agy_durable_outcome_missing"
            )
        return rotated

    async def aclose(self) -> None:
        """Terminate every agent process owned by this transport."""

        sessions = [session for session in self._sessions.values() if not session.closed]
        if not sessions:
            return
        await asyncio.gather(
            *(self._close_session(session, reason="room_agy_shutdown") for session in sessions),
            return_exceptions=True,
        )

    async def _run_agy_turn(
        self,
        session: _AgySession,
        delivery: RoomObservationDelivery,
        *,
        prompt_text: str,
        turn_id: str,
    ) -> dict[str, Any]:
        """Write one input line and read stdout until the turn's ``result``."""

        payload = {
            "event": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": prompt_text}]},
        }
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        stdin = session.process.stdin
        if stdin is None or session.process.returncode is not None:
            raise RoomAgyTransportError(
                "room_agy_process_exited", "agy process exited before the turn started"
            )
        try:
            stdin.write(raw)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError, ValueError) as exc:
            raise RoomAgyTransportError(
                "room_agy_process_exited", f"agy input write failed: {exc}"
            ) from exc
        while True:
            event = await self._next_event(session)
            kind = event.get("event")
            if kind == "init":
                self._remember_conversation(session, event)
                continue
            if kind == "step_update":
                self._handle_step_update(session, event, turn_id=turn_id, delivery=delivery)
                continue
            if kind == "result":
                result = event.get("result")
                if not isinstance(result, dict):
                    raise RoomAgyTransportError(
                        "room_agy_turn_failed", "agy result is not an object"
                    )
                if result.get("status") == "SUCCESS":
                    return result
                error = normalized_text(result.get("error")) or "agy turn reported ERROR"
                raise RoomAgyTransportError(agy_turn_error_code(error), error)
            self._report_progress(delivery, RoomTurnProgress(kind="other"))

    async def _next_event(self, session: _AgySession) -> dict[str, Any]:
        """Return the next stdout event, proving a dead process as an exit."""

        try:
            async with asyncio.timeout(float(self._config.turn_idle_timeout_s)):
                event = await session.line_queue.get()
        except TimeoutError as exc:
            raise RoomAgyTransportError(
                "room_agy_turn_idle", "agy produced no output before the idle timeout"
            ) from exc
        if event is None:
            raise RoomAgyTransportError(
                "room_agy_process_exited", "agy process exited before the turn's result"
            )
        return event

    def _handle_step_update(
        self,
        session: _AgySession,
        event: dict[str, Any],
        *,
        turn_id: str,
        delivery: RoomObservationDelivery,
    ) -> None:
        update = event.get("step_update")
        if not isinstance(update, dict):
            self._report_progress(delivery, RoomTurnProgress(kind="other"))
            return
        text_delta = update.get("text_delta")
        if isinstance(text_delta, str) and text_delta:
            self._push_event(
                session, "item/agentMessage/delta", {"turnId": turn_id, "delta": text_delta}
            )
            self._report_progress(delivery, RoomTurnProgress(kind="message"))
            return
        tool_name = update.get("tool_name")
        tool_info = update.get("tool_info")
        if update.get("step_type") == "tool" or isinstance(tool_name, str):
            parameters = tool_info.get("parameters") if isinstance(tool_info, dict) else None
            # A failed tool call is finished too; repeating it must count
            # toward loop detection.
            if update.get("state") in {"DONE", "ERROR"}:
                if _is_room_outcome_mcp_call(tool_name, tool_info):
                    self._push_event(
                        session,
                        "item/completed",
                        {"turnId": turn_id, "item": {"name": "chat_room_submit_outcome"}},
                    )
                self._report_progress(
                    delivery,
                    RoomTurnProgress(
                        kind="tool_call",
                        fingerprint=tool_call_fingerprint(tool_name, parameters),
                    ),
                )
            else:
                if _is_room_outcome_mcp_call(tool_name, tool_info):
                    self._push_event(
                        session,
                        "item/started",
                        {"turnId": turn_id, "item": {"name": "chat_room_submit_outcome"}},
                    )
                self._report_progress(delivery, RoomTurnProgress(kind="tool_update"))
            return
        self._report_progress(delivery, RoomTurnProgress(kind="other"))

    def _report_progress(
        self, delivery: RoomObservationDelivery, progress: RoomTurnProgress
    ) -> None:
        """Forward one progress event to the host without failing the turn."""

        callback = delivery.progress
        if callback is None:
            return
        try:
            callback(progress)
        except Exception:
            logger.warning("room_agy_progress_callback_failed", exc_info=True)

    def _push_event(self, session: _AgySession, method: str, params: dict[str, Any]) -> None:
        event = {"method": method, "params": dict(params)}
        for listener in tuple(session.preview_listeners):
            listener.push(event)

    def _remember_conversation(self, session: _AgySession, event: dict[str, Any]) -> None:
        conversation_id = normalized_text(event.get("conversation_id"))
        if conversation_id is None:
            logger.warning("room_agy_init_without_conversation_id")
            return
        if session.agy_conversation_id == conversation_id:
            return
        session.agy_conversation_id = conversation_id
        with suppress(Exception):
            self._registry.update_provider_binding(
                session.god_session_id,
                provider_session_id=conversation_id,
                provider_session_kind=ROOM_AGY_PROVIDER_SESSION_KIND,
                provider_binding_status="active",
                provider_binding_failure_reason=None,
            )

    async def _rotate_session(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
        expected_provider_session_id: str | None,
    ) -> bool:
        key = (delivery.conversation_id, delivery.participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with asyncio.timeout(float(timeout_s)):
                async with lock:
                    session = self._sessions.get(key)
                    if session is None or session.closed:
                        return True
                    if (
                        expected_provider_session_id is not None
                        and session.agy_conversation_id != expected_provider_session_id
                    ):
                        # The exact generation is already gone; never abort a
                        # replacement session.
                        return False
                    await self._close_session(
                        session,
                        reason="room_agy_durable_outcome_missing",
                        drop_conversation_id=True,
                    )
        except (TimeoutError, ValueError):
            return False
        return True

    def _subscribe_preview_events(self, session: _AgySession) -> Callable[[str], object]:
        def subscribe(_god_session_id: str) -> object:
            listener = _AgyPreviewStream(session)
            session.preview_listeners.add(listener)
            return listener

        return subscribe

    def _session_is_current(self, session: _AgySession) -> bool:
        if session.closed:
            return False
        key = self._session_key(session)
        return key is not None and self._sessions.get(key) is session

    def _session_key(self, session: _AgySession) -> tuple[str, str] | None:
        for key, candidate in self._sessions.items():
            if candidate is session:
                return key
        return None

    async def _acquire_session(self, delivery: RoomObservationDelivery) -> _AgySession:
        key = (delivery.conversation_id, delivery.participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            existing = self._sessions.get(key)
            if existing is not None and not existing.closed:
                if existing.process.returncode is None:
                    return existing
                await self._close_session(existing, reason="room_agy_process_exited")
            record = self._ensure_god_session_record(delivery)
            resume: str | None = None
            if (
                record.provider_session_kind == ROOM_AGY_PROVIDER_SESSION_KIND
                and normalized_text(record.provider_session_id) is not None
            ):
                resume = str(record.provider_session_id)
            session = await self._spawn_session(
                delivery, record=record, resume_conversation_id=resume
            )
            self._sessions[key] = session
            return session

    def _ensure_god_session_record(self, delivery: RoomObservationDelivery) -> GodSessionRecord:
        participant = delivery.participant
        try:
            record = self._registry.find_by_conversation_participant(
                delivery.conversation_id,
                participant.participant_id,
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
            )
        except KeyError:
            session_address, session_inbox_id = build_conversation_session_identity(
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
            )
            return self._registry.create(
                role=participant.role,
                agent_name=participant.display_name,
                runtime=AgentRuntime.ANTIGRAVITY.value,
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                model=participant.model,
                prompt_fingerprint=participant_session_prompt_fingerprint(participant),
                worktree=str(self._workspace),
                feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
            )
        if (
            record.runtime != AgentRuntime.ANTIGRAVITY.value
            or record.role != participant.role
            or record.conversation_id != delivery.conversation_id
            or record.participant_id != participant.participant_id
            or record.feature_scope_id != ROOM_DELIVERY_SESSION_SCOPE
            or record.status not in {"starting", "running"}
        ):
            raise RoomAgyTransportError("room_agy_session_identity_mismatch")
        return record

    async def _spawn_session(
        self,
        delivery: RoomObservationDelivery,
        *,
        record: GodSessionRecord,
        resume_conversation_id: str | None,
    ) -> _AgySession:
        generation = self._next_generation
        self._next_generation += 1
        try:
            argv = self._config.command_builder(resume_conversation_id)
        except Exception as exc:
            raise RoomAgyTransportError(
                "room_agy_command_invalid", f"{type(exc).__name__}: {exc}"
            ) from exc
        if not argv or not all(isinstance(part, str) and part for part in argv):
            raise RoomAgyTransportError("room_agy_command_invalid")
        env = sanitized_agent_environment(self._environ)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
                env=env,
                start_new_session=True,
                limit=ROOM_AGY_STDOUT_LINE_LIMIT,
            )
        except OSError as exc:
            raise RoomAgyTransportError(
                "room_agy_agent_spawn_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        if process.stdout is None or process.stdin is None or process.stderr is None:
            await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)
            raise RoomAgyTransportError("room_agy_agent_spawn_failed")
        session = _AgySession(
            generation=generation,
            god_session_id=record.god_session_id,
            agy_conversation_id=None,
            process=process,
        )
        session.reader_task = asyncio.create_task(
            _pump_agy_stdout(process.stdout, session.line_queue),
            name=f"room-agy-stdout:{delivery.transport_request_id}",
        )
        session.stderr_task = asyncio.create_task(
            _drain_agy_stderr(process.stderr),
            name=f"room-agy-stderr:{delivery.transport_request_id}",
        )
        try:
            async with asyncio.timeout(float(self._config.initialize_timeout_s)):
                conversation_id = await self._wait_for_init(session)
        except TimeoutError as exc:
            await self._abandon_session(session)
            raise RoomAgyTransportError(
                "room_agy_session_ensure_timeout", str(exc) or "agy init timed out"
            ) from exc
        except RoomAgyTransportError:
            await self._abandon_session(session)
            raise
        except Exception as exc:
            await self._abandon_session(session)
            raise RoomAgyTransportError(
                "room_agy_session_ensure_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        session.agy_conversation_id = conversation_id
        try:
            self._registry.update_provider_binding(
                record.god_session_id,
                provider_session_id=conversation_id,
                provider_session_kind=ROOM_AGY_PROVIDER_SESSION_KIND,
                provider_binding_status="active",
                provider_binding_failure_reason=None,
            )
            self._registry.promote_running(record.god_session_id, pid=process.pid)
        except Exception as exc:
            await self._close_session(session, reason="room_agy_registry_binding_failed")
            raise RoomAgyTransportError(
                "room_agy_registry_binding_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        logger.info(
            "room_agy_session_ready conversation=%s participant=%s god_session=%s "
            "pid=%d agy_conversation=%s resumed=%s",
            delivery.conversation_id,
            delivery.participant.participant_id,
            record.god_session_id,
            process.pid,
            conversation_id,
            resume_conversation_id is not None,
        )
        return session

    async def _wait_for_init(self, session: _AgySession) -> str:
        """Return the agy conversation id from the process's ``init`` event."""

        while True:
            event = await session.line_queue.get()
            if event is None:
                raise RoomAgyTransportError(
                    "room_agy_process_exited", "agy process exited before init"
                )
            if event.get("event") != "init":
                continue
            conversation_id = normalized_text(event.get("conversation_id"))
            if conversation_id is None:
                raise RoomAgyTransportError("room_agy_session_id_missing")
            return conversation_id

    async def _fail_session(
        self,
        session: _AgySession,
        delivery: RoomObservationDelivery,
        *,
        reason_code: str,
    ) -> None:
        await self._close_session(session, reason=reason_code)
        self._mark_cleanup(delivery, succeeded=True, reason_code=reason_code)

    async def _close_session(
        self,
        session: _AgySession,
        *,
        reason: str,
        drop_conversation_id: bool = False,
    ) -> None:
        if session.closed:
            return
        session.closed = True
        key = self._session_key(session)
        if key is not None and self._sessions.get(key) is session:
            self._sessions.pop(key, None)
        prompt_task = session.prompt_task
        if (
            prompt_task is not None
            and not prompt_task.done()
            and prompt_task is not asyncio.current_task()
        ):
            # Settle the in-flight turn first so its delivery reports this
            # close (e.g. an operator cancel), not a later process exit.
            prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)
        for task in (session.reader_task, session.stderr_task):
            if task is not None and not task.done():
                task.cancel()
        if session.reader_task is not None or session.stderr_task is not None:
            await asyncio.gather(
                *(task for task in (session.reader_task, session.stderr_task) if task is not None),
                return_exceptions=True,
            )
        session.reader_task = None
        session.stderr_task = None
        for listener in tuple(session.preview_listeners):
            listener.close()
        await terminate_process_group(session.process, grace_s=self._config.shutdown_grace_s)
        with suppress(Exception):
            self._registry.update_provider_binding(
                session.god_session_id,
                provider_session_id=None if drop_conversation_id else session.agy_conversation_id,
                provider_session_kind=ROOM_AGY_PROVIDER_SESSION_KIND,
                provider_binding_status="closed",
                provider_binding_failure_reason=reason,
            )

    async def _abandon_session(self, session: _AgySession) -> None:
        """Reap a half-spawned process that never produced a usable session."""

        session.closed = True
        for task in (session.reader_task, session.stderr_task):
            if task is not None and not task.done():
                task.cancel()
        if session.reader_task is not None or session.stderr_task is not None:
            await asyncio.gather(
                *(task for task in (session.reader_task, session.stderr_task) if task is not None),
                return_exceptions=True,
            )
        await terminate_process_group(session.process, grace_s=self._config.shutdown_grace_s)

    def _mark_cleanup(
        self,
        delivery: RoomObservationDelivery,
        *,
        succeeded: bool,
        reason_code: str,
    ) -> None:
        if self._controls is None or not delivery.attempt_id:
            return
        with suppress(RoomControlError):
            self._controls.mark_provider_cleanup(
                observation_id=delivery.observation["observation_id"],
                attempt_id=delivery.attempt_id,
                delivery_generation=delivery.attempt_id,
                succeeded=succeeded,
                reason_code=reason_code,
                now=self._clock(),
            )


async def _pump_agy_stdout(
    stream: asyncio.StreamReader,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    """Forward parsed stdout events; a None sentinel marks EOF exactly once."""

    try:
        while True:
            try:
                raw = await stream.readline()
            except ValueError:
                # One oversized line (e.g. a tool step carrying a whole file)
                # is dropped; it must not read as process exit.
                logger.warning("room_agy_stdout_line_too_long")
                continue
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("room_agy_stdout_not_json")
                continue
            if isinstance(event, dict):
                queue.put_nowait(event)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("room_agy_stdout_pump_failed", exc_info=True)
    finally:
        queue.put_nowait(None)


async def _drain_agy_stderr(stream: asyncio.StreamReader) -> None:
    """Drain stderr to the logger; provider diagnostics never enter Room data."""

    try:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                logger.debug("room_agy_stderr %s", line)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("room_agy_stderr_drain_failed", exc_info=True)


__all__ = [
    "ROOM_AGY_OUTCOME_REMINDER",
    "ROOM_AGY_PROVIDER_SESSION_KIND",
    "ROOM_AGY_SUPPORTED_CLI_KINDS",
    "AgyRoomObservationTransport",
    "AgyTransportConfig",
    "RoomAgyTransportError",
    "agy_turn_error_code",
    "resolve_agy_model",
]
