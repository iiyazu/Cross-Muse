"""Agent Client Protocol transport for participant-owned room observations.

The adapter owns one long-lived ACP agent process per ``(conversation_id,
participant_id)``, created lazily under a per-participant singleflight lock.  The
Room MCP server (``xmuse-room``) is mounted as an HTTP MCP server on each ACP
session; the agent produces Room truth only through
``chat_room_submit_outcome`` and coordinates through the lease-bound board
tools; for non-owners every other tool request is rejected.  The
``RoomParticipantHost`` still decides completion from durable state.

Claude (via ``claude-agent-acp``) is confined in-process on three axes, because
Claude Code auto-approves its built-in read-only Bash allowlist *without* asking
the ACP client: the session is created with the built-in tool set limited to
``ROOM_ACP_BUILTIN_TOOLS`` (no Bash/Edit/Write/WebFetch/Task), workspace
project/local settings are not loaded (``settingSources: ["user"]``, so a Room
workspace cannot inject allow rules, hooks, or CLAUDE.md; the operator's user
settings still load because they may carry the provider credential),
``strictMcpConfig`` blocks MCP servers from the operator's user config so only
the ACP-mounted room server loads, and ``session/set_mode`` pins the
``default`` permission mode.  The ACP permission callback then grants only the
exact Room MCP tools; MCP tools are not affected by the built-in tool filter.
Workspace-write owners are the exception: they keep their full native tools,
own MCP servers and Skills, and are confined by the OS sandbox instead.

Provider output only describes transport progress: an ``end_turn`` stop reason
means the provider turn ended, never that the Room commit happened.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
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
    RoomTurnProgress,
)
from xmuse_core.chat.room_mcp_contract import ROOM_OUTCOME_TOOL_NAME, ROOM_TOOL_NAMES
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
)
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)
from xmuse_core.chat.room_workspace_sandbox import ROOM_WORKSPACE_WRITE_CONFINEMENT

logger = logging.getLogger(__name__)

ROOM_ACP_PROVIDER_SESSION_KIND = "acp_session"
# Pinned: an unpinned ``npx -y`` silently picks up new bridge releases, and
# claude-agent-acp 0.85.1 failed every Room prompt (room_acp_prompt_failed right
# after session/new). Bump only after a live Room smoke on the new version;
# XMUSE_CLAUDE_ACP_COMMAND still overrides the whole command.
ROOM_ACP_DEFAULT_COMMAND = ("npx", "-y", "@agentclientprotocol/claude-agent-acp@0.85.0")
ROOM_ACP_DEFAULT_MCP_URL = "http://127.0.0.1:8100/mcp/room"
ROOM_ACP_MCP_SERVER_NAME = "xmuse-room"
ROOM_ACP_SUPPORTED_CLI_KINDS = (AgentRuntime.CLAUDE.value, AgentRuntime.OPENCODE.value)
# Claude Code enforces the Room boundary in-process: the session's built-in tool
# set is limited to ROOM_ACP_BUILTIN_TOOLS with workspace settings not loaded,
# and ACP permission requests are granted solely for the exact room outcome tool
# while every other tool is denied.
ROOM_ACP_CONFINEMENT = "client_permission_gated"

# The complete base set of BUILT-IN Claude Code tools this session may use.
# Bash is excluded because Claude Code auto-approves its built-in read-only Bash
# allowlist (ls, cat, find, grep, git log, ...) without ever calling the ACP
# permission callback, so the client cannot reject those commands.  Edit/Write/
# NotebookEdit would write workspace bytes outside exact-patch candidates,
# WebFetch/WebSearch would leave the loopback-only boundary, and Task/Skill hide
# further tool use (including agents with wider tools) from this client.  MCP
# tools such as the room outcome tool are not affected by this base set.
ROOM_ACP_BUILTIN_TOOLS: tuple[str, ...] = ("Read", "Glob", "Grep")
# Load only the operator's user settings: they may hold the provider credential
# (an empty list leaves such machines unauthenticated), while the Room
# workspace's project/local settings must not shape the session.
ROOM_ACP_SETTING_SOURCES: tuple[str, ...] = ("user",)

# Claude Code names a mounted MCP tool ``mcp__<server>__<tool>`` in the ACP
# tool-call title (verified against claude-agent-acp 0.84).
_ROOM_OUTCOME_QUALIFIED_TOOL_NAME = f"mcp__{ROOM_ACP_MCP_SERVER_NAME}__{ROOM_OUTCOME_TOOL_NAME}"
# Every Room tool (outcome plus board tools) by its exact qualified title; the
# board tools are bound to the caller's live lease server-side like the outcome.
_ROOM_QUALIFIED_TOOL_NAMES = frozenset(
    f"mcp__{ROOM_ACP_MCP_SERVER_NAME}__{name}" for name in ROOM_TOOL_NAMES
)
_READ_TEXT_FILE_BYTE_LIMIT = 8 * 1024 * 1024

# OpenCode never asks the ACP client before running its own tools (shell, write,
# and MCP calls through its code-execution tool all run unprompted), so the
# client cannot gate it.  Its agent process instead runs inside a read-only OS
# sandbox (``room_opencode_sandbox``); OpenCode's own tool configuration stays
# untouched because altering it disables OpenCode's hosted free tier.
ROOM_OPENCODE_CONFINEMENT = "os_read_only_sandbox"


@dataclass(frozen=True)
class AcpProviderProfile:
    """Provider-specific facts of one ACP agent family sharing this transport.

    ``approvable_tool_titles`` are the exact ACP tool-call titles the permission
    callback may approve; every other request is rejected.  ``session_meta`` is
    sent as ``session/new`` ``_meta`` and ``model_config_option`` names the ACP
    session config option that selects the participant's model.
    """

    runtime: str
    confinement: str
    approvable_tool_titles: frozenset[str]
    session_meta: Mapping[str, Any] = field(default_factory=dict)
    pin_default_mode: bool = False
    model_config_option: str | None = None
    # When a turn ends while the attempt still holds no durable outcome, prompt
    # the same session once more inside the same lease and timeout budget.
    outcome_reminder: bool = False
    # Dynamic models (e.g. OpenCode ACP server discovering third-party models
    # asynchronously on startup) may take several seconds to settle.
    model_settle_timeout_s: float = 15.0
    model_settle_poll_interval_s: float = 0.5
    # When True (owners only), the permission callback approves every tool the
    # agent asks for: built-ins, the agent's own MCP servers and Skills.  The OS
    # sandbox, not this callback, confines an owner's writes.
    approve_all_tools: bool = False
    # How many times a failed spawn may be retried when the agent process has
    # already exited during initialization (cold-start crash).
    early_exit_spawn_retries: int = 0


CLAUDE_ACP_PROFILE = AcpProviderProfile(
    runtime=AgentRuntime.CLAUDE.value,
    confinement=ROOM_ACP_CONFINEMENT,
    approvable_tool_titles=_ROOM_QUALIFIED_TOOL_NAMES,
    # claude-agent-acp forwards ``claudeCode.options`` to the Claude Agent SDK:
    # only the Read/Glob/Grep built-ins remain, and only the operator's user
    # settings load (they may carry the provider credential); workspace
    # project/local settings cannot add allow rules, hooks, or CLAUDE.md.  User
    # allow rules cannot re-enable tools removed from the base set.
    # ``strictMcpConfig`` blocks MCP servers from the operator's user config so
    # only the ACP-mounted room server loads.
    session_meta={
        "claudeCode": {
            "options": {
                "tools": list(ROOM_ACP_BUILTIN_TOOLS),
                "settingSources": list(ROOM_ACP_SETTING_SOURCES),
                "strictMcpConfig": True,
            }
        }
    },
    pin_default_mode=True,
)
OPENCODE_ACP_PROFILE = AcpProviderProfile(
    runtime=AgentRuntime.OPENCODE.value,
    confinement=ROOM_OPENCODE_CONFINEMENT,
    # OpenCode calls MCP tools without a permission request; nothing it asks
    # for (only tools its configuration sets to ``ask``) is ever approved.
    approvable_tool_titles=frozenset(),
    model_config_option="model",
    # Low-cost models often answer the Room in plain text, which never becomes
    # Room truth; one in-lease reminder recovers most of those turns.
    outcome_reminder=True,
    model_settle_timeout_s=15.0,
    model_settle_poll_interval_s=0.5,
    early_exit_spawn_retries=1,
)
CLAUDE_ACP_WORKSPACE_WRITE_PROFILE = AcpProviderProfile(
    runtime=AgentRuntime.CLAUDE.value,
    confinement=ROOM_WORKSPACE_WRITE_CONFINEMENT,
    approvable_tool_titles=_ROOM_QUALIFIED_TOOL_NAMES,
    # No ``tools`` key, so Claude Code's full built-in preset stays enabled for
    # the writable owner workspace, and without ``strictMcpConfig`` or a Skill
    # ban the owner keeps its own MCP servers and Skills.  Writes are confined
    # by the OS sandbox, not the in-process tool filter.  Known residual: an
    # MCP server reached over the network (or one that delegates to another
    # agent) runs outside the sandbox; the operator accepted that exposure.
    session_meta={
        "claudeCode": {
            "options": {
                "settingSources": list(ROOM_ACP_SETTING_SOURCES),
            }
        }
    },
    pin_default_mode=True,
    approve_all_tools=True,
)
OPENCODE_ACP_WORKSPACE_WRITE_PROFILE = replace(
    OPENCODE_ACP_PROFILE,
    confinement=ROOM_WORKSPACE_WRITE_CONFINEMENT,
)
ROOM_ACP_OUTCOME_REMINDER = (
    "Your turn ended without a durable Room outcome, so the Room received nothing: "
    "plain-text replies are never shown to the Human or other participants. Decide "
    "now and call chat_room_submit_outcome exactly once with the identifiers from "
    "xmuse_context.durable_outcome and one of its allowed_outcomes, putting your "
    "visible text in outcome_payload.content. If you have nothing to add, submit the "
    "allowed outcome that records that instead of replying in text."
)


class RoomAcpTransportError(RuntimeError):
    """Stable ACP transport failure carrying a Room reason code."""

    def __init__(self, code: str, detail: str | None = None, *, agent_exited: bool = False) -> None:
        self.code = code
        # True when the agent process had already exited on its own when the
        # failure surfaced (a cold-start crash), as opposed to a live agent.
        self.agent_exited = agent_exited
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
    profile: AcpProviderProfile = CLAUDE_ACP_PROFILE
    # Model selected through ``profile.model_config_option`` when the
    # participant's own model is not a provider-qualified ``provider/model`` id.
    default_model: str | None = None

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(part, str) and part for part in self.command):
            raise ValueError("room_acp_command_invalid")
        if self.profile.model_config_option is not None and not normalized_text(self.default_model):
            raise ValueError("room_acp_default_model_invalid")
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
        self._progress: Callable[[RoomTurnProgress], None] | None = None
        # Partial tool-call identity per ACP tool_call_id until the call finishes.
        self._tool_calls: dict[str, dict[str, Any]] = {}

    def begin_turn(
        self,
        turn_id: str,
        *,
        progress: Callable[[RoomTurnProgress], None] | None = None,
    ) -> None:
        self._turn_id = turn_id
        self._outcome_tool_seen = False
        self._progress = progress
        self._tool_calls = {}
        for listener in tuple(self._session.preview_listeners):
            listener.push({"method": "turn/started", "params": {"turnId": turn_id}})

    def end_turn(self) -> None:
        turn_id = self._turn_id
        self._turn_id = None
        self._progress = None
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
            self._report_progress(RoomTurnProgress(kind="message"))
            return
        if kind == "agent_thought_chunk":
            self._report_progress(RoomTurnProgress(kind="thought"))
            return
        if kind == "plan":
            self._report_progress(RoomTurnProgress(kind="plan"))
            return
        if kind in {"tool_call", "tool_call_update"}:
            identifiers = _tool_identity_candidates(update, kwargs)
            if any(self._transport.is_room_outcome_tool(item) for item in identifiers):
                status = getattr(update, "status", None)
                if kind == "tool_call" or status in {"pending", "in_progress"}:
                    self._outcome_tool_seen = True
                    self._push_event("item/started", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})
                elif self._outcome_tool_seen and status == "completed":
                    self._push_event("item/completed", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})
            self._report_progress(self._tool_progress(kind, update))
            return
        # Usage updates and future kinds are tolerated without becoming Room
        # speech or preview text, but they still prove the provider is alive.
        self._report_progress(RoomTurnProgress(kind="other"))

    def _tool_progress(self, kind: str, update: object) -> RoomTurnProgress:
        """Merge one tool call's updates and fingerprint it only once it finishes.

        Adapters often announce a call with a placeholder title and empty
        arguments (Claude: ``Terminal`` with ``{}``) and fill both in later
        updates, so fingerprinting the announcement would make every distinct
        shell command look identical to the loop probe.
        """

        call_id = getattr(update, "tool_call_id", None)
        key = call_id if isinstance(call_id, str) and call_id else None
        title = getattr(update, "title", None) or getattr(update, "name", None)
        raw_input = getattr(update, "raw_input", None)
        merged = self._tool_calls.get(key, {}) if key is not None else {}
        if title:
            merged["title"] = title
        if raw_input is not None:
            merged["raw_input"] = raw_input
        status = getattr(update, "status", None)
        if status in {"completed", "failed"}:
            if key is not None:
                self._tool_calls.pop(key, None)
            return RoomTurnProgress(
                kind="tool_call",
                fingerprint=_tool_call_fingerprint(merged.get("title"), merged.get("raw_input")),
            )
        if key is not None:
            self._tool_calls[key] = merged
        return RoomTurnProgress(kind="tool_update")

    def _report_progress(self, progress: RoomTurnProgress) -> None:
        """Forward one progress event to the host without failing the turn."""

        callback = self._progress
        if callback is None:
            return
        try:
            callback(progress)
        except Exception:
            logger.warning("room_acp_progress_callback_failed", exc_info=True)

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        identifiers = _tool_identity_candidates(tool_call, kwargs)
        session_matches = session_id == self._session.acp_session_id
        room_tool_match = any(self._transport.is_room_tool(item) for item in identifiers)
        owner_match = self._transport.profile.approve_all_tools and bool(identifiers)
        allowed = session_matches and (room_tool_match or owner_match)
        # The adapter's ``claudeCode.toolName`` metadata is observation-only
        # evidence; authorization stays with the exact tool-call title because
        # metadata is not covered by the same-name guarantee.
        logger.info(
            "room_acp_permission decision=%s candidates=%s meta_tool=%s",
            "allow" if allowed else "reject",
            identifiers,
            _field_meta_tool_name(tool_call),
        )
        preferred = ("allow_once", "allow_always") if allowed else ("reject_once",)
        for kind in preferred:
            option = _permission_option(options, kind)
            if option is not None:
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(outcome="selected", option_id=option.option_id)
                )
        # ``cancelled`` makes the adapter abort the whole turn; only use it when
        # the agent offered no reject option to select instead.
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

    @property
    def profile(self) -> AcpProviderProfile:
        return self._config.profile

    def is_room_outcome_tool(self, value: str) -> bool:
        """Match only this provider's exact qualified room outcome tool title."""

        return value == _ROOM_OUTCOME_QUALIFIED_TOOL_NAME and self.is_room_tool(value)

    def is_room_tool(self, value: str) -> bool:
        """Accept only this provider's exact qualified Room tool titles."""

        return value in self._config.profile.approvable_tool_titles

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
            supported_cli_kinds=(self._config.profile.runtime,),
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
            prompt=build_room_observation_prompt(
                self._config.profile.runtime,
                # Only a transport that really confines an owner tells it the
                # workspace is writable.
                owner=self._config.profile.confinement == ROOM_WORKSPACE_WRITE_CONFINEMENT,
            ),
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
            session.client.begin_turn(delivery.transport_request_id, progress=delivery.progress)
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
            deadline = asyncio.get_running_loop().time() + float(timeout_s)
            reminded = False
            while True:
                try:
                    async with asyncio.timeout_at(deadline):
                        response = await asyncio.shield(prompt_task)
                except TimeoutError:
                    await self._cancel_prompt(session)
                    await self._fail_session(session, delivery, reason_code="room_acp_timeout")
                    return RoomTransportResult("failed", "room_acp_timeout")
                except Exception as exc:
                    await self._fail_session(
                        session, delivery, reason_code="room_acp_prompt_failed"
                    )
                    return failed_result("room_acp_prompt_failed", exc)
                stop_reason = normalized_text(getattr(response, "stop_reason", None))
                if (
                    stop_reason != "end_turn"
                    or reminded
                    or not self._outcome_reminder_due(delivery)
                ):
                    break
                reminded = True
                logger.info(
                    "room_acp_outcome_reminder conversation=%s participant=%s",
                    delivery.conversation_id,
                    delivery.participant.participant_id,
                )
                prompt_task = asyncio.create_task(
                    session.connection.prompt(
                        session.acp_session_id,
                        [acp.text_block(ROOM_ACP_OUTCOME_REMINDER)],
                    ),
                    name=f"room-acp-reminder:{delivery.transport_request_id}",
                )
                session.prompt_task = prompt_task
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

    def _outcome_reminder_due(self, delivery: RoomObservationDelivery) -> bool:
        """True only while this exact attempt still owns an uncommitted observation."""

        if not self._config.profile.outcome_reminder or self._controls is None:
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
                runtime=self._config.profile.runtime,
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
            record.runtime != self._config.profile.runtime
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
        max_retries = max(0, int(self._config.profile.early_exit_spawn_retries))
        attempt = 0
        while True:
            try:
                return await self._spawn_session_once(delivery, record=record)
            except RoomAcpTransportError as exc:
                if attempt >= max_retries or not exc.agent_exited:
                    raise
                attempt += 1
                logger.info(
                    "room_acp_spawn_retry attempt=%d code=%s",
                    attempt,
                    exc.code,
                )
                await asyncio.sleep(1.0)

    @staticmethod
    async def _agent_exited_on_its_own(process: asyncio.subprocess.Process) -> bool:
        """Report whether the agent already died, before the failed spawn is reaped.

        A broken stdio connection usually surfaces before the child is reaped, so
        give it a brief moment; a still-running agent is never treated as exited.
        """

        if process.returncode is not None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), timeout=1.0)
        except Exception:
            return False
        return True

    async def _spawn_session_once(
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
            await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)
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
                    # Agent-client-protocol sends extra kwargs as the request
                    # ``_meta`` (see ``AcpProviderProfile.session_meta``).
                    **dict(self._config.profile.session_meta),
                )
                acp_session_id = normalized_text(created.session_id)
                if acp_session_id is None:
                    raise RoomAcpTransportError("room_acp_session_id_missing")
                session.acp_session_id = acp_session_id
                if self._config.profile.pin_default_mode:
                    await self._select_default_mode(session, created)
                await self._select_model(session, delivery)
        except RoomAcpTransportError as exc:
            exc.agent_exited = await self._agent_exited_on_its_own(process)
            await self._reap_failed_spawn(session, process)
            raise
        except TimeoutError as exc:
            exited = await self._agent_exited_on_its_own(process)
            await self._reap_failed_spawn(session, process)
            raise RoomAcpTransportError(
                "room_acp_session_ensure_timeout", str(exc), agent_exited=exited
            ) from exc
        except Exception as exc:
            exited = await self._agent_exited_on_its_own(process)
            await self._reap_failed_spawn(session, process)
            raise RoomAcpTransportError(
                "room_acp_session_ensure_failed",
                f"{type(exc).__name__}: {exc}",
                agent_exited=exited,
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

    async def _select_default_mode(self, session: _AcpSession, created: Any) -> None:
        """Pin the session's ``default`` permission mode after creation.

        ``permissionMode`` cannot be set through ``new_session`` ``_meta``; the
        adapter accepts it only via ``session/set_mode``.  An agent that does not
        advertise session modes has no modal setting to pin, so a rejected
        request is tolerated with a warning there; an agent that does advertise
        modes must honor the request or the session could run under a more
        permissive mode.
        """

        try:
            await session.connection.set_session_mode(session.acp_session_id, "default")
        except Exception as exc:
            if getattr(created, "modes", None) is not None:
                raise
            logger.warning(
                "room_acp_set_default_mode_unsupported error=%s",
                f"{type(exc).__name__}: {exc}",
            )
            return
        logger.info("room_acp_permission_mode_selected mode_id=default")

    async def _select_model(self, session: _AcpSession, delivery: RoomObservationDelivery) -> None:
        """Select the participant's model through the profile's ACP config option.

        Some providers (e.g. OpenCode) discover dynamic third-party models
        asynchronously after starting their internal standalone server. Retry
        until ``model_settle_timeout_s`` expires.
        """

        option = self._config.profile.model_config_option
        if option is None:
            return
        model = resolve_acp_model(delivery.participant.model, self._config.default_model)
        settle_timeout = min(
            max(0.0, float(self._config.profile.model_settle_timeout_s)),
            max(0.0, float(self._config.initialize_timeout_s)),
        )
        poll_interval = max(0.01, float(self._config.profile.model_settle_poll_interval_s))
        deadline = asyncio.get_running_loop().time() + settle_timeout

        last_error: Exception | None = None
        while True:
            if session.closed or session.process.returncode is not None:
                raise RoomAcpTransportError(
                    "room_acp_model_unavailable",
                    f"{model}: agent process exited before model could be selected"
                    + (f": {last_error}" if last_error else ""),
                )
            try:
                await session.connection.set_config_option(
                    config_id=option,
                    session_id=session.acp_session_id,
                    value=model,
                )
                logger.info("room_acp_model_selected model=%s", model)
                return
            except Exception as exc:
                last_error = exc
                now = asyncio.get_running_loop().time()
                # Only a definite agent reply (e.g. "model not found" while models are
                # still loading) is worth waiting out; transport failures fail fast.
                if (
                    not isinstance(exc, acp.RequestError)
                    or now >= deadline
                    or session.closed
                    or session.process.returncode is not None
                ):
                    # Never fall back to the agent's own default model: it may be a paid
                    # model the operator did not choose for this participant.
                    raise RoomAcpTransportError(
                        "room_acp_model_unavailable", f"{model}: {type(exc).__name__}: {exc}"
                    ) from exc
                logger.debug(
                    "room_acp_model_waiting_settle model=%s remaining=%.1fs error=%s",
                    model,
                    deadline - now,
                    exc,
                )
                sleep_duration = min(poll_interval, deadline - now)
                await asyncio.sleep(sleep_duration)

    async def _reap_failed_spawn(
        self, session: _AcpSession | None, process: asyncio.subprocess.Process
    ) -> None:
        if session is not None:
            session.closed = True
            with suppress(Exception):
                await asyncio.wait_for(
                    session.connection.close(), timeout=self._config.shutdown_grace_s
                )
        await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)

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
        await terminate_process_group(session.process, grace_s=self._config.shutdown_grace_s)
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


def resolve_acp_model(participant_model: str | None, default_model: str | None) -> str:
    """Use a provider-qualified participant model, else the configured default."""

    candidate = normalized_text(participant_model)
    if candidate is not None and "/" in candidate:
        return candidate
    fallback = normalized_text(default_model)
    if fallback is None:
        raise RoomAcpTransportError("room_acp_model_unavailable", "no model configured")
    return fallback


def _permission_option(options: Collection[PermissionOption], kind: str) -> PermissionOption | None:
    for option in options:
        if getattr(option, "kind", None) == kind:
            return option
    return None


def _tool_call_fingerprint(title: object, raw_input: object) -> str:
    """Return a stable identity for one ACP tool call: title plus arguments."""

    title = title if isinstance(title, str) else ""
    try:
        canonical = json.dumps(raw_input, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = json.dumps(str(raw_input))
    return hashlib.sha256(f"{title}\0{canonical}".encode()).hexdigest()


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


def _field_meta_tool_name(tool_call: object) -> str | None:
    """Return the adapter's ``claudeCode.toolName`` metadata for logging only."""

    meta = getattr(tool_call, "field_meta", None)
    if not isinstance(meta, Mapping):
        return None
    claude_code = meta.get("claudeCode")
    if not isinstance(claude_code, Mapping):
        return None
    name = claude_code.get("toolName")
    return name if isinstance(name, str) and name else None
