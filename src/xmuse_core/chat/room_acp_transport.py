"""Agent Client Protocol transport for participant-owned room observations.

The adapter owns one long-lived ACP agent process per ``(conversation_id,
participant_id)``, created lazily under a per-participant singleflight lock.  The
Room MCP server (``xmuse-room``) is mounted as an HTTP MCP server on each ACP
session; the agent produces Room truth only through
``chat_room_submit_outcome`` and every other tool request is rejected.  The
``RoomParticipantHost`` still decides completion from durable state.

Provider output only describes transport progress: an ``end_turn`` stop reason
means the provider turn ended, never that the Room commit happened.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import acp
from acp.core import DEFAULT_STDIO_BUFFER_LIMIT_BYTES
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    FileSystemCapabilities,
    HttpMcpServer,
    Implementation,
    PermissionOption,
    ReadTextFileResponse,
    RequestPermissionResponse,
    ToolCallUpdate,
)

from xmuse_core.agents.codex_app_server_transport import _format_turn_prompt
from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import Participant
from xmuse_core.chat.room_agent_stream import RoomAgentStreamProjector
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_ports import ExecutionReviewReceiptWriter
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomTransportResult,
)
from xmuse_core.chat.room_mcp_contract import ROOM_OUTCOME_TOOL_NAME
from xmuse_core.chat.room_memory_runtime import RoomMemoryContextReceiptPort
from xmuse_core.chat.room_observation_transport_base import (
    ROOM_CONTEXT_BYTE_LIMIT,
    ProviderNeutralDeliveryKit,
    build_room_observation_prompt,
    diagnostic_text,
    failed_result,
    normalized_text,
)
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)

logger = logging.getLogger(__name__)

ROOM_ACP_PROVIDER_SESSION_KIND = "acp_session"
ROOM_ACP_DEFAULT_COMMAND = ("npx", "-y", "@agentclientprotocol/claude-agent-acp")
ROOM_ACP_DEFAULT_MCP_URL = "http://127.0.0.1:8100/mcp/room"
ROOM_ACP_MCP_SERVER_NAME = "xmuse-room"
ROOM_ACP_SUPPORTED_CLI_KINDS = (AgentRuntime.CLAUDE.value,)

# Server-only credentials and provider API keys must never reach an agent
# process; the Room agent authenticates only through the mounted MCP server.
_AGENT_ENV_DENYLIST = frozenset(
    {
        "XMUSE_OPERATOR_TOKEN",
        "XMUSE_MEMORYOS_API_KEY",
        "MEMORYOS_API_KEY",
        "ANTHROPIC_API_KEY",
    }
)
_AGENT_ENV_SECRET_PREFIXES = ("XMUSE_", "MEMORYOS_")
_AGENT_ENV_SECRET_SUFFIXES = ("_API_KEY", "_TOKEN")

# Claude Code names a mounted MCP tool ``mcp__<server>__<tool>`` in the ACP
# tool-call title (verified against claude-agent-acp 0.84).
_ROOM_OUTCOME_QUALIFIED_TOOL_NAME = f"mcp__{ROOM_ACP_MCP_SERVER_NAME}__{ROOM_OUTCOME_TOOL_NAME}"
_READ_TEXT_FILE_BYTE_LIMIT = 8 * 1024 * 1024


class RoomAcpTransportError(RuntimeError):
    """Stable ACP transport failure carrying a Room reason code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class AcpTransportConfig:
    """Immutable attachment settings for the ACP agent transport."""

    workspace: Path | str
    command: tuple[str, ...] = ROOM_ACP_DEFAULT_COMMAND
    room_mcp_url: str = ROOM_ACP_DEFAULT_MCP_URL
    client_name: str = "xmuse-room-runner"
    client_version: str = "0.1.0"
    initialize_timeout_s: float = 60.0
    shutdown_grace_s: float = 5.0

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(part, str) and part for part in self.command):
            raise ValueError("room_acp_command_invalid")
        if not isinstance(self.room_mcp_url, str) or not self.room_mcp_url.strip():
            raise ValueError("room_acp_room_mcp_url_invalid")
        for name in ("initialize_timeout_s", "shutdown_grace_s"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"room_acp_{name}_invalid")


def sanitized_agent_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Copy an environment while stripping server-only secrets and API keys."""

    sanitized: dict[str, str] = {}
    for key, value in environ.items():
        if key in _AGENT_ENV_DENYLIST:
            continue
        if key.startswith(_AGENT_ENV_SECRET_PREFIXES) and key.endswith(_AGENT_ENV_SECRET_SUFFIXES):
            continue
        sanitized[key] = value
    return sanitized


class _PreviewStreamClosed(Exception):
    """The disposable preview stream has no more events."""


class _AcpPreviewStream:
    """One disposable listener fed by ACP ``session/update`` notifications."""

    def __init__(self, session: _AcpSession) -> None:
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
class _AcpSession:
    """One live ACP agent process bound to a durable participant identity."""

    generation: int
    god_session_id: str
    acp_session_id: str
    process: asyncio.subprocess.Process
    prompt_task: asyncio.Task[Any] | None = None
    preview_listeners: set[_AcpPreviewStream] = field(default_factory=set)
    closed: bool = False

    def __post_init__(self) -> None:
        self._client: _RoomAcpClient | None = None
        self._connection: Any = None

    @property
    def client(self) -> _RoomAcpClient:
        if self._client is None:
            raise RoomAcpTransportError("room_acp_client_not_attached")
        return self._client

    @property
    def connection(self) -> Any:
        if self._connection is None:
            raise RoomAcpTransportError("room_acp_connection_not_attached")
        return self._connection

    def attach(self, *, client: _RoomAcpClient, connection: Any) -> None:
        self._client = client
        self._connection = connection


class _RoomAcpClient:
    """Client-side ACP handlers: preview, permissions, and read-only filesystem."""

    def __init__(self, transport: AcpRoomObservationTransport, session: _AcpSession) -> None:
        self._transport = transport
        self._session = session
        self._turn_id: str | None = None
        self._outcome_tool_seen = False

    def begin_turn(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._outcome_tool_seen = False
        for listener in tuple(self._session.preview_listeners):
            listener.push({"method": "turn/started", "params": {"turnId": turn_id}})

    def end_turn(self) -> None:
        turn_id = self._turn_id
        self._turn_id = None
        if turn_id is None:
            return
        for listener in tuple(self._session.preview_listeners):
            listener.push({"method": "turn/completed", "params": {"turnId": turn_id}})

    def close_preview_streams(self) -> None:
        for listener in tuple(self._session.preview_listeners):
            listener.close()

    def _push_event(self, method: str, params: dict[str, Any]) -> None:
        if self._turn_id is None:
            return
        event = {"method": method, "params": {"turnId": self._turn_id, **params}}
        for listener in tuple(self._session.preview_listeners):
            listener.push(event)

    async def session_update(self, session_id: str, update: object, **kwargs: Any) -> None:
        if session_id != self._session.acp_session_id:
            return
        kind = getattr(update, "session_update", None)
        if kind == "agent_message_chunk":
            content = getattr(update, "content", None)
            text = getattr(content, "text", None)
            if isinstance(text, str) and text:
                self._push_event("item/agentMessage/delta", {"delta": text})
            return
        if kind in {"tool_call", "tool_call_update"}:
            identifiers = _tool_identity_candidates(update, kwargs)
            if not any(_is_room_outcome_tool_identifier(item) for item in identifiers):
                return
            status = getattr(update, "status", None)
            if kind == "tool_call" or status in {"pending", "in_progress"}:
                self._outcome_tool_seen = True
                self._push_event("item/started", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})
            elif self._outcome_tool_seen and status == "completed":
                self._push_event("item/completed", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})
            return
        # Thought chunks, usage updates, plans, and future kinds are tolerated
        # without becoming Room speech or preview text.

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        identifiers = _tool_identity_candidates(tool_call, kwargs)
        allowed = session_id == self._session.acp_session_id and any(
            _is_room_outcome_tool_identifier(item) for item in identifiers
        )
        logger.info(
            "room_acp_permission decision=%s candidates=%s",
            "allow" if allowed else "reject",
            identifiers,
        )
        preferred = ("allow_once", "allow_always") if allowed else ("reject_once",)
        for kind in preferred:
            option = _permission_option(options, kind)
            if option is not None:
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", option_id=option.option_id)
                )
        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        if session_id != self._session.acp_session_id:
            raise acp.RequestError.invalid_params({"detail": "unknown acp session"})
        resolved = self._transport.resolve_workspace_path(path)
        try:
            if not resolved.is_file():
                raise OSError("not a regular file")
            with resolved.open("rb") as handle:
                raw = handle.read(_READ_TEXT_FILE_BYTE_LIMIT + 1)
        except OSError as exc:
            raise acp.RequestError.resource_not_found(path) from exc
        text = raw[:_READ_TEXT_FILE_BYTE_LIMIT].decode("utf-8", errors="replace")
        if line is not None or limit is not None:
            lines = text.splitlines(keepends=True)
            start = max(0, (line or 1) - 1)
            text = "".join(lines[start : None if limit is None else start + max(0, limit)])
        return ReadTextFileResponse(content=text)

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        # A Room participant never writes workspace bytes directly; workspace
        # changes enter only through exact-patch candidates.
        logger.info("room_acp_write_text_file_denied path=%s", path)
        return None


class AcpRoomObservationTransport:
    """Deliver observations through participant-bound ACP agent sessions."""

    def __init__(
        self,
        *,
        config: AcpTransportConfig,
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
        self._sessions: dict[tuple[str, str], _AcpSession] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._next_generation = 1

    def resolve_workspace_path(self, path: str) -> Path:
        """Resolve an ACP filesystem path and require it inside the workspace."""

        if not isinstance(path, str) or not path.strip():
            raise acp.RequestError.invalid_params({"detail": "empty path"})
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        resolved = candidate.resolve()
        if resolved != self._workspace and not resolved.is_relative_to(self._workspace):
            raise acp.RequestError.invalid_params(
                {"detail": "path is outside the read-only room workspace"}
            )
        return resolved

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        invalid = self._kit.validate_delivery(
            delivery,
            reason_prefix="room_acp",
            supported_cli_kinds=ROOM_ACP_SUPPORTED_CLI_KINDS,
        )
        if invalid is not None:
            return RoomTransportResult("failed", invalid)
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s <= 0
        ):
            return RoomTransportResult("failed", "room_acp_timeout_invalid")

        activation_failure = self._kit.skill_activation_failure(delivery)
        if activation_failure is not None:
            return activation_failure
        if self._controls is not None:
            if not delivery.attempt_id:
                return RoomTransportResult("failed", "room_acp_attempt_binding_missing")
            try:
                self._controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                return failed_result("room_acp_attempt_binding_failed", exc)

        try:
            session = await self._acquire_session(delivery)
        except RoomAcpTransportError as exc:
            self._mark_cleanup(delivery, succeeded=True, reason_code=exc.code)
            return RoomTransportResult("failed", exc.code, diagnostic_text(str(exc)))
        except Exception as exc:
            self._mark_cleanup(
                delivery, succeeded=True, reason_code="room_acp_session_ensure_failed"
            )
            return failed_result("room_acp_session_ensure_failed", exc)

        if session.prompt_task is not None and not session.prompt_task.done():
            return RoomTransportResult("failed", "room_acp_session_busy")
        if self._controls is not None:
            if not delivery.attempt_id:
                await self._fail_session(
                    session, delivery, reason_code="room_acp_attempt_binding_missing"
                )
                return RoomTransportResult("failed", "room_acp_attempt_binding_missing")
            try:
                self._controls.bind_provider_session(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    god_session_id=session.god_session_id,
                    provider_session_id=session.acp_session_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                await self._fail_session(
                    session, delivery, reason_code="room_acp_attempt_binding_failed"
                )
                return failed_result("room_acp_attempt_binding_failed", exc)

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
            prompt=build_room_observation_prompt(AgentRuntime.CLAUDE.value),
            context=submission.text,
        )
        preview = await self._kit.open_preview(
            delivery,
            subscribe_native_events=self._subscribe_preview_events(session),
            god_session_id=session.god_session_id,
            session_is_current=lambda: self._session_is_current(session),
        )
        provider_succeeded = False
        try:
            prompt_task = asyncio.create_task(
                session.connection.prompt(
                    session.acp_session_id,
                    [acp.text_block(prompt_text)],
                ),
                name=f"room-acp-prompt:{delivery.transport_request_id}",
            )
            session.prompt_task = prompt_task
            session.client.begin_turn(delivery.transport_request_id)
            # Let the prompt request reach the agent before the context receipts
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
            try:
                async with asyncio.timeout(float(timeout_s)):
                    response = await asyncio.shield(prompt_task)
            except TimeoutError:
                await self._cancel_prompt(session)
                await self._fail_session(session, delivery, reason_code="room_acp_timeout")
                return RoomTransportResult("failed", "room_acp_timeout")
            except Exception as exc:
                await self._fail_session(session, delivery, reason_code="room_acp_prompt_failed")
                return failed_result("room_acp_prompt_failed", exc)
            stop_reason = normalized_text(getattr(response, "stop_reason", None))
            if stop_reason == "end_turn":
                # "finished" only means the provider turn ended. The host accepts
                # completion only from durable Room state.
                provider_succeeded = True
                return RoomTransportResult("finished")
            await self._fail_session(session, delivery, reason_code="room_acp_stop_reason")
            return RoomTransportResult(
                "failed",
                f"room_acp_stop_{stop_reason or 'unknown'}",
            )
        except asyncio.CancelledError:
            await self._fail_session(session, delivery, reason_code="room_acp_delivery_cancelled")
            raise
        except Exception as exc:
            await self._fail_session(session, delivery, reason_code="room_acp_transport_error")
            return failed_result("room_acp_transport_error", exc)
        finally:
            session.prompt_task = None
            session.client.end_turn()
            await self._kit.finalize_preview(preview, provider_succeeded=provider_succeeded)

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
            return RoomCancelReconcileResult("pending", "room_acp_cancel_binding_invalid")
        if provider_phase == "not_started":
            return RoomCancelReconcileResult("settled", "room_acp_cancel_session_not_started")
        if provider_phase == "cleanup_succeeded":
            return RoomCancelReconcileResult(
                "settled",
                normalized_text(attempt.get("provider_cleanup_reason"))
                or "room_acp_cancel_cleanup_already_succeeded",
            )
        if expected_provider_session_id is None and expected_god_session_id is None:
            # The provider binding never completed, so no ACP generation is
            # provably alive for this attempt; a live replacement session must
            # never be touched from here.
            return RoomCancelReconcileResult(
                "settled", "room_acp_cancel_start_failed_before_binding"
            )
        key = (conversation_id, participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with asyncio.timeout(float(timeout_s)):
                async with lock:
                    session = self._sessions.get(key)
                    if session is None or session.closed:
                        return RoomCancelReconcileResult(
                            "settled", "room_acp_cancel_no_active_session"
                        )
                    if (
                        expected_provider_session_id
                        and session.acp_session_id != expected_provider_session_id
                    ):
                        # Rotation always closes the previous process before a
                        # new session exists, so this attempt's exact provider
                        # generation is already provably gone.
                        return RoomCancelReconcileResult(
                            "settled", "room_acp_cancel_binding_superseded"
                        )
                    await self._close_session(session, reason="room_acp_cancel_reconcile")
        except (TimeoutError, ValueError):
            return RoomCancelReconcileResult("pending", "room_acp_cancel_close_failed")
        return RoomCancelReconcileResult("settled", "room_acp_cancel_session_closed")

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        """Rotate (close) the participant session before retrying a missing outcome.

        A provider turn that ended without durable Room truth may have retained
        poisoned conversation state; replaying the same session can
        deterministically repeat it. Only the exact bound generation is closed,
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
                delivery, succeeded=True, reason_code="room_acp_durable_outcome_missing"
            )
        return rotated

    async def aclose(self) -> None:
        """Terminate every agent process owned by this transport."""

        sessions = [session for session in self._sessions.values() if not session.closed]
        if not sessions:
            return
        await asyncio.gather(
            *(self._close_session(session, reason="room_acp_shutdown") for session in sessions),
            return_exceptions=True,
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
                        and session.acp_session_id != expected_provider_session_id
                    ):
                        # The exact generation is already gone; never abort a
                        # replacement session.
                        return False
                    await self._close_session(session, reason="room_acp_durable_outcome_missing")
        except (TimeoutError, ValueError):
            return False
        return True

    def _subscribe_preview_events(self, session: _AcpSession) -> Callable[[str], object]:
        def subscribe(_god_session_id: str) -> object:
            listener = _AcpPreviewStream(session)
            session.preview_listeners.add(listener)
            return listener

        return subscribe

    def _session_is_current(self, session: _AcpSession) -> bool:
        if session.closed:
            return False
        key = self._session_key(session)
        return key is not None and self._sessions.get(key) is session

    def _session_key(self, session: _AcpSession) -> tuple[str, str] | None:
        for key, candidate in self._sessions.items():
            if candidate is session:
                return key
        return None

    async def _acquire_session(self, delivery: RoomObservationDelivery) -> _AcpSession:
        key = (delivery.conversation_id, delivery.participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            existing = self._sessions.get(key)
            if existing is not None and not existing.closed:
                return existing
            record = self._ensure_god_session_record(delivery)
            session = await self._spawn_session(delivery, record=record)
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
                runtime=AgentRuntime.CLAUDE.value,
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
            record.runtime != AgentRuntime.CLAUDE.value
            or record.role != participant.role
            or record.conversation_id != delivery.conversation_id
            or record.participant_id != participant.participant_id
            or record.feature_scope_id != ROOM_DELIVERY_SESSION_SCOPE
            or record.status not in {"starting", "running"}
        ):
            raise RoomAcpTransportError("room_acp_session_identity_mismatch")
        return record

    async def _spawn_session(
        self,
        delivery: RoomObservationDelivery,
        *,
        record: GodSessionRecord,
    ) -> _AcpSession:
        generation = self._next_generation
        self._next_generation += 1
        env = sanitized_agent_environment(self._environ)
        try:
            process = await asyncio.create_subprocess_exec(
                *self._config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # stderr must stay attached to the runner's stderr; a pipe
                # nobody drains would eventually wedge the agent process.
                stderr=None,
                cwd=str(self._workspace),
                env=env,
                start_new_session=True,
                limit=DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
            )
        except OSError as exc:
            raise RoomAcpTransportError(
                "room_acp_agent_spawn_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        if process.stdin is None or process.stdout is None:
            await _terminate_agent_process(process, grace_s=self._config.shutdown_grace_s)
            raise RoomAcpTransportError("room_acp_agent_spawn_failed")
        session: _AcpSession | None = None
        try:
            session = _AcpSession(
                generation=generation,
                god_session_id=record.god_session_id,
                acp_session_id="",
                process=process,
            )
            client = _RoomAcpClient(self, session)
            # _RoomAcpClient implements the handler subset the Room contract
            # needs; the SDK tolerates the missing optional handlers for
            # terminal, elicitation, and extension traffic we never advertise.
            connection = acp.connect_to_agent(
                cast("acp.Client", client), process.stdin, process.stdout
            )
            session.attach(client=client, connection=connection)
            async with asyncio.timeout(float(self._config.initialize_timeout_s)):
                initialized = await session.connection.initialize(
                    acp.PROTOCOL_VERSION,
                    ClientCapabilities(
                        fs=FileSystemCapabilities(read_text_file=True, write_text_file=False),
                        terminal=False,
                    ),
                    Implementation(
                        name=self._config.client_name,
                        version=self._config.client_version,
                    ),
                )
                if initialized.protocol_version != acp.PROTOCOL_VERSION:
                    raise RoomAcpTransportError("room_acp_protocol_version_unsupported")
                capabilities = getattr(initialized, "agent_capabilities", None)
                mcp_capabilities = getattr(capabilities, "mcp_capabilities", None)
                if getattr(mcp_capabilities, "http", False) is not True:
                    # Without HTTP MCP transport the room tool would be silently
                    # unmounted and the agent could never commit Room truth.
                    raise RoomAcpTransportError("room_acp_mcp_http_unsupported")
                if getattr(initialized, "auth_methods", None):
                    logger.warning(
                        "room_acp_agent_advertises_auth_methods; continuing without "
                        "authenticate (xmuse never authenticates a provider)"
                    )
                created = await session.connection.new_session(
                    cwd=str(self._workspace),
                    mcp_servers=[
                        HttpMcpServer(
                            name=ROOM_ACP_MCP_SERVER_NAME,
                            url=self._config.room_mcp_url,
                            headers=[],
                            type="http",
                        )
                    ],
                )
            acp_session_id = normalized_text(created.session_id)
            if acp_session_id is None:
                raise RoomAcpTransportError("room_acp_session_id_missing")
            session.acp_session_id = acp_session_id
        except RoomAcpTransportError:
            await self._reap_failed_spawn(session, process)
            raise
        except TimeoutError as exc:
            await self._reap_failed_spawn(session, process)
            raise RoomAcpTransportError("room_acp_session_ensure_timeout", str(exc)) from exc
        except Exception as exc:
            await self._reap_failed_spawn(session, process)
            raise RoomAcpTransportError(
                "room_acp_session_ensure_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            self._registry.update_provider_binding(
                record.god_session_id,
                provider_session_id=session.acp_session_id,
                provider_session_kind=ROOM_ACP_PROVIDER_SESSION_KIND,
                provider_binding_status="active",
                provider_binding_failure_reason=None,
            )
            self._registry.promote_running(record.god_session_id, pid=process.pid)
        except Exception as exc:
            await self._close_session(session, reason="room_acp_registry_binding_failed")
            raise RoomAcpTransportError(
                "room_acp_registry_binding_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        logger.info(
            "room_acp_session_ready conversation=%s participant=%s god_session=%s pid=%d",
            delivery.conversation_id,
            delivery.participant.participant_id,
            record.god_session_id,
            process.pid,
        )
        return session

    async def _reap_failed_spawn(
        self, session: _AcpSession | None, process: asyncio.subprocess.Process
    ) -> None:
        if session is not None:
            session.closed = True
            with suppress(Exception):
                await asyncio.wait_for(
                    session.connection.close(), timeout=self._config.shutdown_grace_s
                )
        await _terminate_agent_process(process, grace_s=self._config.shutdown_grace_s)

    async def _cancel_prompt(self, session: _AcpSession) -> None:
        with suppress(Exception):
            await asyncio.wait_for(
                session.connection.cancel(session.acp_session_id),
                timeout=self._config.shutdown_grace_s,
            )

    async def _settle_prompt_task(self, session: _AcpSession) -> None:
        task = session.prompt_task
        if task is None:
            return
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._config.shutdown_grace_s)
            except Exception:
                task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        session.prompt_task = None

    async def _fail_session(
        self,
        session: _AcpSession,
        delivery: RoomObservationDelivery,
        *,
        reason_code: str,
    ) -> None:
        await self._close_session(session, reason=reason_code)
        self._mark_cleanup(delivery, succeeded=True, reason_code=reason_code)

    async def _close_session(self, session: _AcpSession, *, reason: str) -> None:
        if session.closed:
            return
        session.closed = True
        key = self._session_key(session)
        if key is not None and self._sessions.get(key) is session:
            self._sessions.pop(key, None)
        if session.prompt_task is not None and not session.prompt_task.done():
            await self._cancel_prompt(session)
            await self._settle_prompt_task(session)
        with suppress(Exception):
            session.client.close_preview_streams()
        with suppress(Exception):
            await asyncio.wait_for(
                session.connection.close(), timeout=self._config.shutdown_grace_s
            )
        await _terminate_agent_process(session.process, grace_s=self._config.shutdown_grace_s)
        with suppress(Exception):
            self._registry.update_provider_binding(
                session.god_session_id,
                provider_session_id=session.acp_session_id or None,
                provider_session_kind=ROOM_ACP_PROVIDER_SESSION_KIND,
                provider_binding_status="closed",
                provider_binding_failure_reason=reason,
            )

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


def _permission_option(options: Collection[PermissionOption], kind: str) -> PermissionOption | None:
    for option in options:
        if getattr(option, "kind", None) == kind:
            return option
    return None


def _tool_identity_candidates(tool_call: object, extra: Mapping[str, Any]) -> list[str]:
    """Collect agent-authored tool identifiers from one ACP tool-call payload.

    Only the tool call's own title/name count. Tool arguments (``raw_input``),
    extension metadata and request extras are model-controlled content, so a
    name smuggled into them must never authorize a different tool.
    """

    candidates: list[str] = []
    for value in (getattr(tool_call, "title", None), getattr(tool_call, "name", None)):
        if isinstance(value, str) and value and value not in candidates:
            candidates.append(value)
    return candidates


def _is_room_outcome_tool_identifier(value: str) -> bool:
    """Accept only the exact qualified outcome tool of the ``xmuse-room`` server."""

    return value == _ROOM_OUTCOME_QUALIFIED_TOOL_NAME


async def _terminate_agent_process(process: asyncio.subprocess.Process, *, grace_s: float) -> None:
    """Terminate one agent process group with SIGTERM, then SIGKILL."""

    if process.returncode is not None:
        with suppress(Exception):
            await process.wait()
        return
    pgid: int | None = None
    with suppress(Exception):
        pgid = os.getpgid(process.pid)
    if pgid is None or pgid == os.getpgid(0):
        # Never signal the runner's own process group.
        pgid = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if pgid is not None:
                os.killpg(pgid, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            break
        except OSError:
            if sig == signal.SIGKILL:
                with suppress(ProcessLookupError):
                    process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=grace_s)
            return
        except TimeoutError:
            continue
