"""Antigravity participant transport over the local ``agentapi`` CLI.

The adapter owns one durable provider conversation per ``(conversation_id,
participant_id)``, created lazily under a per-participant singleflight lock.  The
first delivery runs ``agentapi new-conversation`` with the exact Room prompt;
later deliveries append through ``agentapi send-message``.  Turn completion is
observed by polling the provider's own transcript file
(``<brain>/<conversation_id>/.system_generated/logs/transcript.jsonl``) until the
latest step is a terminal ``PLANNER_RESPONSE``, exactly like the operator's
reference client.

Antigravity's agent executes its own tools with no client-side permission hook
and exposes no cancel API, so the transport cannot fence workspace writes
in-process.  The confinement level is ``instructed_read_only``: the prompt
instructs the agent that the Room workspace is read-only and that Room truth is
written only through ``chat_room_submit_outcome`` on the ``xmuse-room`` MCP
server, which the agent mounts through its own global MCP configuration.
Infrastructure never submits an outcome on the agent's behalf, and a rotated
(dropped) conversation can never be reused; late outcomes from abandoned turns
are rejected by the kernel's lease fencing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import urllib.request
from collections.abc import Callable, Collection, Iterator, Mapping
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
    sanitized_agent_environment,
    terminate_process_group,
)
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)

logger = logging.getLogger(__name__)

ROOM_ANTIGRAVITY_PROVIDER_SESSION_KIND = "agentapi_conversation"
ROOM_ANTIGRAVITY_SUPPORTED_CLI_KINDS = (AgentRuntime.ANTIGRAVITY.value,)
ROOM_ANTIGRAVITY_CONFINEMENT = "instructed_read_only"
ROOM_ANTIGRAVITY_MODELS = ("flash_lite", "flash", "pro")
ROOM_ANTIGRAVITY_DEFAULT_MODEL = "flash"
ROOM_ANTIGRAVITY_AGENTAPI_ENV = "XMUSE_ANTIGRAVITY_AGENTAPI"
ROOM_ANTIGRAVITY_BRAIN_DIR_ENV = "XMUSE_ANTIGRAVITY_BRAIN_DIR"
ROOM_ANTIGRAVITY_DEFAULT_AGENTAPI_RELATIVE = Path(".gemini") / "antigravity" / "bin" / "agentapi"
ROOM_ANTIGRAVITY_DEFAULT_BRAIN_RELATIVE = Path(".gemini") / "antigravity" / "brain"
ROOM_ANTIGRAVITY_PROMPT_SUFFIX = (
    "The Room workspace path is READ-ONLY: do not edit files or run state-changing "
    "commands, and submit the durable outcome by calling call_mcp_tool with server "
    "xmuse-room and tool chat_room_submit_outcome."
)
_TRANSCRIPT_RELATIVE = Path(".system_generated") / "logs" / "transcript.jsonl"
_TRANSCRIPT_FULL_RELATIVE = Path(".system_generated") / "logs" / "transcript_full.jsonl"
_HTTP_PROBE_TIMEOUT_S = 0.5
_LANGUAGE_SERVER_MARKER = b"language_server"


class RoomAntigravityTransportError(RuntimeError):
    """Stable Antigravity transport failure carrying a Room reason code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(detail or code)


def resolve_antigravity_agentapi_path(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the ``agentapi`` binary path, defaulting under ``$HOME``."""

    source = os.environ if environ is None else environ
    override = normalized_text(source.get(ROOM_ANTIGRAVITY_AGENTAPI_ENV))
    if override is not None:
        return Path(override).expanduser()
    return Path.home() / ROOM_ANTIGRAVITY_DEFAULT_AGENTAPI_RELATIVE


def resolve_antigravity_brain_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the Antigravity brain directory, defaulting under ``$HOME``."""

    source = os.environ if environ is None else environ
    override = normalized_text(source.get(ROOM_ANTIGRAVITY_BRAIN_DIR_ENV))
    if override is not None:
        return Path(override).expanduser()
    return Path.home() / ROOM_ANTIGRAVITY_DEFAULT_BRAIN_RELATIVE


@dataclass(frozen=True)
class AntigravityTransportConfig:
    """Immutable attachment settings for the Antigravity agent transport."""

    workspace: Path | str
    agentapi_command: tuple[str, ...]
    brain_dir: Path | str
    poll_interval_s: float = 0.5
    shutdown_grace_s: float = 5.0
    agentapi_call_timeout_s: float = 60.0
    default_model: str = ROOM_ANTIGRAVITY_DEFAULT_MODEL

    def __post_init__(self) -> None:
        if not self.agentapi_command or not all(
            isinstance(part, str) and part for part in self.agentapi_command
        ):
            raise ValueError("room_antigravity_agentapi_command_invalid")
        for name in ("workspace", "brain_dir"):
            value = getattr(self, name)
            if not isinstance(value, (str, Path)) or not str(value).strip():
                raise ValueError(f"room_antigravity_{name}_invalid")
        for name in ("poll_interval_s", "shutdown_grace_s", "agentapi_call_timeout_s"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"room_antigravity_{name}_invalid")
        if not normalized_text(self.default_model):
            raise ValueError("room_antigravity_default_model_invalid")


def _loopback_http_probe(port: int, timeout_s: float) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/", timeout=timeout_s) as response:  # noqa: S310
            return int(getattr(response, "status", 0) or 0) == 200
    except Exception:
        return False


def _language_server_csrf_tokens(proc_root: Path) -> dict[int, str | None]:
    """Read ``--csrf_token`` from every running language_server process."""

    tokens: dict[int, str | None] = {}
    if not proc_root.is_dir():
        return tokens
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if _LANGUAGE_SERVER_MARKER not in raw:
            continue
        token: str | None = None
        args = raw.split(b"\0")
        for index, arg in enumerate(args):
            if arg.startswith(b"--csrf_token="):
                token = arg.split(b"=", 1)[1].decode("utf-8", "ignore")
            elif arg == b"--csrf_token" and index + 1 < len(args):
                token = args[index + 1].decode("utf-8", "ignore")
        tokens[int(entry.name)] = token
    return tokens


def _loopback_listening_ports(proc_root: Path) -> list[int]:
    """List 127.0.0.1 TCP listeners from the kernel's /proc/net/tcp table."""

    ports: list[int] = []
    try:
        lines = (proc_root / "net" / "tcp").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ports
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local_address, state = parts[1], parts[3]
        if state != "0A":
            continue
        ip_hex, _, port_hex = local_address.partition(":")
        if ip_hex != "0100007F":
            continue
        try:
            port = int(port_hex, 16)
        except ValueError:
            continue
        if port not in ports:
            ports.append(port)
    return ports


def _address_port(address: str) -> int | None:
    _, _, tail = address.rpartition(":")
    if tail.isdigit() and 1 <= int(tail) <= 65_535:
        return int(tail)
    return None


def discover_antigravity_language_server_env(
    environ: Mapping[str, str],
    *,
    proc_root: Path | str = Path("/proc"),
    probe: Callable[[int, float], bool] | None = None,
) -> dict[str, str]:
    """Resolve the language-server address and CSRF token agentapi needs.

    The runner environment wins when it already carries a live
    ``ANTIGRAVITY_LS_ADDRESS``/``ANTIGRAVITY_CSRF_TOKEN`` pair; otherwise the
    running ``language_server`` process is located directly through /proc.
    """

    probe_once = probe or _loopback_http_probe
    project_id = normalized_text(environ.get("ANTIGRAVITY_PROJECT_ID")) or "outside-of-project"
    address = normalized_text(environ.get("ANTIGRAVITY_LS_ADDRESS"))
    token = normalized_text(environ.get("ANTIGRAVITY_CSRF_TOKEN"))
    if address is not None and token is not None:
        port = _address_port(address)
        if port is not None and probe_once(port, _HTTP_PROBE_TIMEOUT_S):
            return {
                "ANTIGRAVITY_LS_ADDRESS": address,
                "ANTIGRAVITY_CSRF_TOKEN": token,
                "ANTIGRAVITY_PROJECT_ID": project_id,
            }
    root = Path(proc_root)
    tokens = _language_server_csrf_tokens(root)
    if not tokens:
        raise RoomAntigravityTransportError(
            "room_antigravity_language_server_unavailable",
            "no running Antigravity language_server process was found",
        )
    candidates = [value for value in tokens.values() if value]
    if not candidates:
        raise RoomAntigravityTransportError(
            "room_antigravity_language_server_unavailable",
            "language_server processes expose no --csrf_token",
        )
    selected_token = candidates[0]
    listening = _loopback_listening_ports(root)
    for port in listening:
        if probe_once(port, _HTTP_PROBE_TIMEOUT_S):
            return {
                "ANTIGRAVITY_LS_ADDRESS": f"localhost:{port}",
                "ANTIGRAVITY_CSRF_TOKEN": selected_token,
                "ANTIGRAVITY_PROJECT_ID": project_id,
            }
    raise RoomAntigravityTransportError(
        "room_antigravity_language_server_unavailable",
        f"language server found but no loopback port answered (candidates: {listening})",
    )


def read_antigravity_transcript_steps(
    brain_dir: Path | str,
    conversation_id: str,
) -> list[dict[str, Any]] | None:
    """Read parsed transcript steps, resolving truncated fields from the full log.

    Returns ``None`` when the compact transcript does not exist yet, which for an
    established conversation means no reliable completion baseline exists.
    """

    logs = Path(brain_dir) / conversation_id / _TRANSCRIPT_RELATIVE.parent
    try:
        compact_text = (logs / _TRANSCRIPT_RELATIVE.name).read_text(encoding="utf-8")
    except OSError:
        return None
    full_text: str | None = None
    steps: list[dict[str, Any]] = []
    for index, line in enumerate(compact_text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            step = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(step, dict):
            continue
        truncated = step.get("truncated_fields")
        if truncated:
            if full_text is None:
                try:
                    full_text = (logs / _TRANSCRIPT_FULL_RELATIVE.name).read_text(encoding="utf-8")
                except OSError:
                    full_text = ""
            full_lines = [item for item in full_text.splitlines() if item.strip()]
            if index < len(full_lines):
                try:
                    full_step = json.loads(full_lines[index])
                except json.JSONDecodeError:
                    full_step = None
                if isinstance(full_step, dict) and isinstance(truncated, list):
                    for field_name in truncated:
                        if field_name in full_step:
                            step[field_name] = full_step[field_name]
        steps.append(step)
    return steps


def _next_step_index(steps: Collection[Mapping[str, Any]]) -> int:
    highest = -1
    for step in steps:
        index = step.get("step_index")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        highest = max(highest, index)
    return highest + 1


def _step_is_terminal(step: Mapping[str, Any], *, min_step_index: int) -> bool:
    index = step.get("step_index")
    if isinstance(index, bool) or not isinstance(index, int) or index < min_step_index:
        return False
    return (
        step.get("type") == "PLANNER_RESPONSE"
        and step.get("status") == "DONE"
        and not step.get("tool_calls")
    )


class _PreviewStreamClosed(Exception):
    """The disposable preview stream has no more events."""


class _AntigravityPreviewStream:
    """One disposable listener fed by transcript polling."""

    def __init__(self, preview: _AntigravityTurnPreview) -> None:
        self._preview = preview
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
        self._preview.listeners.discard(self)
        self._queue.put_nowait(None)


class _AntigravityTurnPreview:
    """Per-conversation fan-out of transcript-derived preview evidence."""

    def __init__(self) -> None:
        self.listeners: set[_AntigravityPreviewStream] = set()
        self._turn_id: str | None = None
        self._draft = ""
        self._outcome_seen = False

    def begin(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._draft = ""
        self._outcome_seen = False
        self._push("turn/started", {}, turn_id=turn_id)

    def end(self) -> None:
        turn_id = self._turn_id
        self._turn_id = None
        if turn_id is None:
            return
        for listener in tuple(self.listeners):
            listener.push({"method": "turn/completed", "params": {"turnId": turn_id}})

    def close_streams(self) -> None:
        for listener in tuple(self.listeners):
            listener.close()
        self.listeners.clear()

    def feed_steps(
        self,
        steps: Collection[Mapping[str, Any]],
        *,
        min_step_index: int,
    ) -> None:
        if self._turn_id is None:
            return
        latest_draft: str | None = None
        for step in steps:
            index = step.get("step_index")
            if isinstance(index, bool) or not isinstance(index, int) or index < min_step_index:
                continue
            if step.get("type") != "PLANNER_RESPONSE":
                continue
            tool_calls = step.get("tool_calls")
            if isinstance(tool_calls, list) and any(
                isinstance(call, Mapping) and ROOM_OUTCOME_TOOL_NAME in str(call.get("name") or "")
                for call in tool_calls
            ):
                if not self._outcome_seen:
                    self._outcome_seen = True
                    self._push("item/started", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})
            content = step.get("content")
            if isinstance(content, str) and content:
                latest_draft = content
        if latest_draft is None or self._outcome_seen or latest_draft == self._draft:
            return
        if latest_draft.startswith(self._draft):
            delta = latest_draft[len(self._draft) :]
        else:
            # The provider rewrote its draft; the preview is disposable evidence.
            delta = latest_draft
        self._draft = latest_draft
        if delta:
            self._push("item/agentMessage/delta", {"delta": delta})

    def mark_outcome_completed(self) -> None:
        if self._outcome_seen and self._turn_id is not None:
            self._push("item/completed", {"item": {"name": ROOM_OUTCOME_TOOL_NAME}})

    def _push(self, method: str, params: dict[str, Any], *, turn_id: str | None = None) -> None:
        active_turn = turn_id if turn_id is not None else self._turn_id
        if active_turn is None:
            return
        event = {"method": method, "params": {"turnId": active_turn, **params}}
        for listener in tuple(self.listeners):
            listener.push(event)


@dataclass
class _AntigravityConversation:
    """One durable agentapi conversation bound to a Room participant identity."""

    generation: int
    god_session_id: str
    conversation_id: str | None = None
    process: asyncio.subprocess.Process | None = None
    drain_task: asyncio.Task[None] | None = None
    turn_active: bool = False
    closed: bool = False
    preview: _AntigravityTurnPreview = field(default_factory=_AntigravityTurnPreview)


class AntigravityRoomObservationTransport:
    """Deliver observations through participant-bound agentapi conversations."""

    def __init__(
        self,
        *,
        config: AntigravityTransportConfig,
        registry_path: Path | str,
        control_store: RoomObservationControlStore | None = None,
        skill_decision_store: RoomAttemptSkillDecisionStore | None = None,
        execution_store: ExecutionReviewReceiptWriter | None = None,
        memory_runtime: RoomMemoryContextReceiptPort | None = None,
        stream_projector: RoomAgentStreamProjector | None = None,
        environ: Mapping[str, str] | None = None,
        ls_env_provider: Callable[[], Mapping[str, str]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._workspace = Path(config.workspace).expanduser().resolve()
        self._brain_dir = Path(config.brain_dir).expanduser()
        self._registry = GodSessionRegistry(registry_path)
        self._controls = control_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._environ = dict(os.environ if environ is None else environ)
        self._ls_env_provider = ls_env_provider or (
            lambda: discover_antigravity_language_server_env(self._environ)
        )
        self._ls_env: dict[str, str] | None = None
        self._kit = ProviderNeutralDeliveryKit(
            skill_decision_store=skill_decision_store,
            execution_store=execution_store,
            memory_runtime=memory_runtime,
            stream_projector=stream_projector,
            clock=self._clock,
        )
        self._conversations: dict[tuple[str, str], _AntigravityConversation] = {}
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
            reason_prefix="room_antigravity",
            supported_cli_kinds=ROOM_ANTIGRAVITY_SUPPORTED_CLI_KINDS,
        )
        if invalid is not None:
            return RoomTransportResult("failed", invalid)
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or timeout_s <= 0
        ):
            return RoomTransportResult("failed", "room_antigravity_timeout_invalid")

        activation_failure = self._kit.skill_activation_failure(delivery)
        if activation_failure is not None:
            return activation_failure
        if self._controls is not None:
            if not delivery.attempt_id:
                return RoomTransportResult("failed", "room_antigravity_attempt_binding_missing")
            try:
                self._controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                return failed_result("room_antigravity_attempt_binding_failed", exc)

        key = (delivery.conversation_id, delivery.participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            active = self._conversations.get(key)
            if active is not None and not active.closed and active.turn_active:
                return RoomTransportResult("failed", "room_antigravity_participant_busy")
            try:
                record = self._ensure_god_session_record(delivery)
            except RoomAntigravityTransportError as exc:
                self._mark_cleanup(delivery, succeeded=True, reason_code=exc.code)
                return RoomTransportResult("failed", exc.code, diagnostic_text(str(exc)))
            except Exception as exc:
                self._mark_cleanup(
                    delivery, succeeded=True, reason_code="room_antigravity_session_ensure_failed"
                )
                return failed_result("room_antigravity_session_ensure_failed", exc)
            if active is None or active.closed:
                active = _AntigravityConversation(
                    generation=self._next_generation,
                    god_session_id=record.god_session_id,
                )
                self._next_generation += 1
                self._conversations[key] = active
            active.god_session_id = record.god_session_id
            active.turn_active = True
        # The turn itself runs outside the lock so cancel reconciliation and
        # rotation can always drop the binding of an abandoned turn.
        try:
            return await self._run_turn(active, delivery, record=record, timeout_s=timeout_s)
        finally:
            active.turn_active = False

    async def reconcile_cancel(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        attempt: dict[str, Any],
        timeout_s: float,
    ) -> RoomCancelReconcileResult:
        """Drop only the exact provider conversation bound to one attempt.

        There is no provider cancel API: the abandoned turn keeps running on the
        language server, but its conversation binding is dropped so the turn can
        never be reused, and its late outcome is rejected by lease fencing.
        """

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
            return RoomCancelReconcileResult("pending", "room_antigravity_cancel_binding_invalid")
        if provider_phase == "not_started":
            return RoomCancelReconcileResult(
                "settled", "room_antigravity_cancel_session_not_started"
            )
        if provider_phase == "cleanup_succeeded":
            return RoomCancelReconcileResult(
                "settled",
                normalized_text(attempt.get("provider_cleanup_reason"))
                or "room_antigravity_cancel_cleanup_already_succeeded",
            )
        if expected_provider_session_id is None and expected_god_session_id is None:
            # The provider binding never completed, so no conversation is
            # provably alive for this attempt.
            return RoomCancelReconcileResult(
                "settled", "room_antigravity_cancel_start_failed_before_binding"
            )
        key = (conversation_id, participant.participant_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with asyncio.timeout(float(timeout_s)):
                async with lock:
                    conversation = self._conversations.get(key)
                    if conversation is None or conversation.closed:
                        return RoomCancelReconcileResult(
                            "settled", "room_antigravity_cancel_no_active_conversation"
                        )
                    if (
                        expected_provider_session_id
                        and conversation.conversation_id != expected_provider_session_id
                    ):
                        # Rotation always drops the previous conversation before a
                        # new one exists, so this attempt's exact generation is gone.
                        return RoomCancelReconcileResult(
                            "settled", "room_antigravity_cancel_binding_superseded"
                        )
                    await self._close_conversation(
                        conversation, reason="room_antigravity_cancel_reconcile"
                    )
        except (TimeoutError, ValueError):
            return RoomCancelReconcileResult("pending", "room_antigravity_cancel_drop_failed")
        return RoomCancelReconcileResult("settled", "room_antigravity_cancel_abandoned_turn")

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        """Rotate (drop) the participant conversation before retrying a missing outcome.

        A provider turn that ended without durable Room truth may have retained
        poisoned conversation state; replaying the same conversation can
        deterministically repeat it. Only the exact bound generation is dropped,
        and a replacement conversation is never touched.
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
        rotated = await self._rotate_conversation(
            delivery,
            timeout_s=timeout_s,
            expected_provider_session_id=expected_provider_session_id,
        )
        if rotated:
            self._mark_cleanup(
                delivery, succeeded=True, reason_code="room_antigravity_durable_outcome_missing"
            )
        return rotated

    async def aclose(self) -> None:
        """Drop every conversation binding owned by this transport."""

        conversations = [
            conversation for conversation in self._conversations.values() if not conversation.closed
        ]
        if not conversations:
            return
        await asyncio.gather(
            *(
                self._close_conversation(conversation, reason="room_antigravity_shutdown")
                for conversation in conversations
            ),
            return_exceptions=True,
        )

    async def _run_turn(
        self,
        conversation: _AntigravityConversation,
        delivery: RoomObservationDelivery,
        *,
        record: GodSessionRecord,
        timeout_s: float,
    ) -> RoomTransportResult:
        submission = self._kit.build_context_submission(
            delivery,
            god_session_id=record.god_session_id,
        )
        if len(submission.text.encode("utf-8")) > ROOM_CONTEXT_BYTE_LIMIT:
            await self._fail_conversation(
                conversation, delivery, reason_code="room_skill_context_too_large"
            )
            return RoomTransportResult("failed", "room_skill_context_too_large")
        prompt_text = _format_turn_prompt(
            role=delivery.participant.role,
            msg_type="room_observation",
            prompt=(
                build_room_observation_prompt(AgentRuntime.ANTIGRAVITY.value)
                + " "
                + ROOM_ANTIGRAVITY_PROMPT_SUFFIX
            ),
            context=submission.text,
        )
        preview = await self._kit.open_preview(
            delivery,
            subscribe_native_events=self._subscribe_preview_events(conversation),
            god_session_id=record.god_session_id,
            session_is_current=lambda: self._conversation_is_current(conversation),
        )
        conversation.preview.begin(delivery.transport_request_id)
        provider_succeeded = False
        try:
            async with asyncio.timeout(float(timeout_s)):
                min_step_index = await self._ensure_turn_started(
                    conversation, delivery, record=record, prompt_text=prompt_text
                )
                if self._controls is not None:
                    if not delivery.attempt_id:
                        raise RoomAntigravityTransportError(
                            "room_antigravity_attempt_binding_missing"
                        )
                    self._controls.bind_provider_session(
                        observation_id=delivery.observation["observation_id"],
                        attempt_id=delivery.attempt_id,
                        delivery_generation=delivery.attempt_id,
                        god_session_id=record.god_session_id,
                        provider_session_id=str(conversation.conversation_id),
                        now=self._clock(),
                    )
                # The turn is already enqueued by the provider CLI; receipts now
                # claim the exact bounded context this conversation received.
                self._kit.bind_memory_context_receipt(
                    delivery,
                    context_payload=submission.payload,
                    context_payload_sha256=submission.payload_sha256,
                )
                self._kit.bind_execution_review_receipts(
                    delivery,
                    context_payload=submission.payload,
                    context_payload_sha256=submission.payload_sha256,
                )
                self._kit.mark_skill_context_submitted(
                    delivery,
                    payload_sha256=submission.payload_sha256,
                )
                await self._wait_for_turn_completion(
                    conversation,
                    min_step_index=min_step_index,
                )
                conversation.preview.mark_outcome_completed()
                await self._reap_turn_process(conversation)
                provider_succeeded = True
                return RoomTransportResult("finished")
        except TimeoutError:
            await self._fail_conversation(
                conversation, delivery, reason_code="room_antigravity_timeout"
            )
            return RoomTransportResult("failed", "room_antigravity_timeout")
        except RoomAntigravityTransportError as exc:
            await self._fail_conversation(conversation, delivery, reason_code=exc.code)
            return RoomTransportResult("failed", exc.code, diagnostic_text(str(exc)))
        except RoomControlError as exc:
            await self._fail_conversation(conversation, delivery, reason_code=exc.code)
            return failed_result(exc.code, exc)
        except RoomSkillDecisionError as exc:
            await self._fail_conversation(conversation, delivery, reason_code=exc.code)
            return failed_result(exc.code, exc)
        except RoomExecutionStoreError as exc:
            await self._fail_conversation(conversation, delivery, reason_code=exc.code)
            return failed_result(exc.code, exc)
        except asyncio.CancelledError:
            await self._fail_conversation(
                conversation, delivery, reason_code="room_antigravity_delivery_cancelled"
            )
            raise
        except Exception as exc:
            await self._fail_conversation(
                conversation, delivery, reason_code="room_antigravity_transport_error"
            )
            return failed_result("room_antigravity_transport_error", exc)
        finally:
            conversation.preview.end()
            await self._kit.finalize_preview(preview, provider_succeeded=provider_succeeded)

    async def _ensure_turn_started(
        self,
        conversation: _AntigravityConversation,
        delivery: RoomObservationDelivery,
        *,
        record: GodSessionRecord,
        prompt_text: str,
    ) -> int:
        """Start the provider turn and return the completion step baseline."""

        env = await asyncio.to_thread(self._agentapi_environment)
        if conversation.conversation_id is None:
            model = self._resolve_model(delivery.participant.model)
            argv = (
                *self._config.agentapi_command,
                "new-conversation",
                f"--model={model}",
                prompt_text,
            )
            output = await self._invoke_agentapi(
                argv, env=env, conversation=conversation, expect_conversation_id=True
            )
            conversation_id = _parse_new_conversation_id(output)
            conversation.conversation_id = conversation_id
            self._registry.update_provider_binding(
                record.god_session_id,
                provider_session_id=conversation_id,
                provider_session_kind=ROOM_ANTIGRAVITY_PROVIDER_SESSION_KIND,
                provider_binding_status="active",
                provider_binding_failure_reason=None,
            )
            self._registry.promote_running(record.god_session_id)
            logger.info(
                "room_antigravity_conversation_ready conversation=%s participant=%s "
                "conversation_id=%s model=%s",
                delivery.conversation_id,
                delivery.participant.participant_id,
                conversation_id,
                model,
            )
            return 0
        steps = await asyncio.to_thread(
            read_antigravity_transcript_steps,
            self._brain_dir,
            conversation.conversation_id,
        )
        if steps is None:
            # Without a readable baseline a stale terminal step from the previous
            # turn could be mistaken for this turn's completion.
            raise RoomAntigravityTransportError(
                "room_antigravity_transcript_unavailable",
                f"conversation {conversation.conversation_id} has no readable transcript",
            )
        min_step_index = _next_step_index(steps)
        argv = (
            *self._config.agentapi_command,
            "send-message",
            conversation.conversation_id,
            prompt_text,
        )
        await self._invoke_agentapi(
            argv, env=env, conversation=conversation, expect_conversation_id=False
        )
        return min_step_index

    async def _wait_for_turn_completion(
        self,
        conversation: _AntigravityConversation,
        *,
        min_step_index: int,
    ) -> None:
        """Poll the provider transcript until the turn's terminal step lands."""

        conversation_id = conversation.conversation_id
        if conversation_id is None:
            raise RoomAntigravityTransportError("room_antigravity_conversation_id_missing")
        while True:
            steps = await asyncio.to_thread(
                read_antigravity_transcript_steps,
                self._brain_dir,
                conversation_id,
            )
            if steps:
                conversation.preview.feed_steps(steps, min_step_index=min_step_index)
                if _step_is_terminal(steps[-1], min_step_index=min_step_index):
                    return
            await asyncio.sleep(self._config.poll_interval_s)

    async def _rotate_conversation(
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
                    conversation = self._conversations.get(key)
                    if conversation is None or conversation.closed:
                        return True
                    if (
                        expected_provider_session_id is not None
                        and conversation.conversation_id != expected_provider_session_id
                    ):
                        # The exact generation is already gone; never touch a
                        # replacement conversation.
                        return False
                    await self._close_conversation(
                        conversation, reason="room_antigravity_durable_outcome_missing"
                    )
        except (TimeoutError, ValueError):
            return False
        return True

    def _subscribe_preview_events(
        self, conversation: _AntigravityConversation
    ) -> Callable[[str], object]:
        def subscribe(_god_session_id: str) -> object:
            listener = _AntigravityPreviewStream(conversation.preview)
            conversation.preview.listeners.add(listener)
            return listener

        return subscribe

    def _conversation_is_current(self, conversation: _AntigravityConversation) -> bool:
        if conversation.closed:
            return False
        key = self._conversation_key(conversation)
        return key is not None and self._conversations.get(key) is conversation

    def _conversation_key(self, conversation: _AntigravityConversation) -> tuple[str, str] | None:
        for key, candidate in self._conversations.items():
            if candidate is conversation:
                return key
        return None

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
            raise RoomAntigravityTransportError("room_antigravity_session_identity_mismatch")
        return record

    def _resolve_model(self, participant_model: str) -> str:
        candidate = normalized_text(participant_model)
        if candidate in ROOM_ANTIGRAVITY_MODELS:
            return str(candidate)
        return self._config.default_model

    def _agentapi_environment(self) -> dict[str, str]:
        if self._ls_env is None:
            self._ls_env = dict(self._ls_env_provider())
        env = sanitized_agent_environment(self._environ)
        env.update(self._ls_env)
        if not env.get("PATH"):
            env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env["NO_PROXY"] = "localhost,127.0.0.1,::1"
        env["no_proxy"] = "localhost,127.0.0.1,::1"
        return env

    async def _invoke_agentapi(
        self,
        argv: tuple[str, ...],
        *,
        env: Mapping[str, str],
        conversation: _AntigravityConversation,
        expect_conversation_id: bool,
    ) -> str:
        """Start one agentapi call and return its stdout text.

        The CLI prints a pretty-printed multi-line JSON response, so a single
        ``readline`` is not a whole document; ``new-conversation`` reads until
        the conversation-id document decodes, ``send-message`` until the first
        non-empty output.  The process stays on the conversation for reaping or
        termination, and a background drain keeps a chatty child from wedging on
        a full stdout pipe.
        """

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                # stderr must stay attached to the runner's stderr; no cancel API
                # exists for this provider, so diagnostics are the only signal.
                stderr=None,
                cwd=str(self._workspace),
                env=dict(env),
                start_new_session=True,
            )
        except OSError as exc:
            self._ls_env = None
            raise RoomAntigravityTransportError(
                "room_antigravity_agentapi_spawn_failed", f"{type(exc).__name__}: {exc}"
            ) from exc
        if process.stdout is None:
            await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)
            raise RoomAntigravityTransportError("room_antigravity_agentapi_spawn_failed")
        conversation.process = process
        try:
            async with asyncio.timeout(self._config.agentapi_call_timeout_s):
                text = await _read_agentapi_stdout(
                    process.stdout,
                    expect_conversation_id=expect_conversation_id,
                )
        except TimeoutError:
            await self._terminate_turn_process(conversation)
            raise RoomAntigravityTransportError(
                "room_antigravity_agentapi_timeout",
                f"agentapi printed no complete response within "
                f"{self._config.agentapi_call_timeout_s}s",
            ) from None
        except BaseException:
            await self._terminate_turn_process(conversation)
            raise
        if not text.strip():
            await self._reap_turn_process(conversation)
            if process.returncode in (0, None):
                # send-message output is not part of the contract; an immediate
                # clean exit is an accepted send.
                return ""
            self._ls_env = None
            raise RoomAntigravityTransportError(
                "room_antigravity_agentapi_failed", f"exit_code={process.returncode}"
            )
        conversation.drain_task = asyncio.create_task(
            _drain_stream(process.stdout),
            name=f"room-antigravity-drain:{process.pid}",
        )
        return text

    async def _reap_turn_process(self, conversation: _AntigravityConversation) -> None:
        process = conversation.process
        drain = conversation.drain_task
        conversation.process = None
        conversation.drain_task = None
        if drain is not None:
            with suppress(Exception):
                await drain
        if process is None:
            return
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=self._config.shutdown_grace_s)
            except TimeoutError:
                await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)

    async def _terminate_turn_process(self, conversation: _AntigravityConversation) -> None:
        process = conversation.process
        drain = conversation.drain_task
        conversation.process = None
        conversation.drain_task = None
        if drain is not None:
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)
        if process is not None:
            await terminate_process_group(process, grace_s=self._config.shutdown_grace_s)

    async def _fail_conversation(
        self,
        conversation: _AntigravityConversation,
        delivery: RoomObservationDelivery,
        *,
        reason_code: str,
    ) -> None:
        await self._close_conversation(conversation, reason=reason_code)
        self._mark_cleanup(delivery, succeeded=True, reason_code=reason_code)

    async def _close_conversation(
        self, conversation: _AntigravityConversation, *, reason: str
    ) -> None:
        if conversation.closed:
            return
        conversation.closed = True
        key = self._conversation_key(conversation)
        if key is not None and self._conversations.get(key) is conversation:
            self._conversations.pop(key, None)
        await self._terminate_turn_process(conversation)
        with suppress(Exception):
            conversation.preview.close_streams()
        with suppress(Exception):
            self._registry.update_provider_binding(
                conversation.god_session_id,
                provider_session_id=conversation.conversation_id,
                provider_session_kind=ROOM_ANTIGRAVITY_PROVIDER_SESSION_KIND,
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


def _json_documents(text: str) -> Iterator[dict[str, Any]]:
    """Yield every decodable JSON object inside ``text`` in order."""

    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return
        try:
            payload, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(payload, dict):
            yield payload
        index = end


def _new_conversation_id_from_text(text: str) -> str | None:
    for payload in _json_documents(text):
        response = payload.get("response")
        new_conversation = response.get("newConversation") if isinstance(response, dict) else None
        if isinstance(new_conversation, dict):
            conversation_id = normalized_text(new_conversation.get("conversationId"))
            if conversation_id:
                return conversation_id
    return None


def _parse_new_conversation_id(stdout: str) -> str:
    conversation_id = _new_conversation_id_from_text(stdout)
    if conversation_id is None:
        raise RoomAntigravityTransportError(
            "room_antigravity_conversation_id_missing", diagnostic_text(stdout)
        )
    return conversation_id


async def _read_agentapi_stdout(
    stream: asyncio.StreamReader,
    *,
    expect_conversation_id: bool,
) -> str:
    """Read agentapi stdout until the expected payload arrives or the CLI ends.

    The response document may be split across reads, so the conversation id is
    looked up in the whole buffer accumulated so far; anything already read
    stays the caller's diagnostic evidence.
    """

    buffer = ""
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return buffer
        buffer += chunk.decode("utf-8", errors="replace")
        if expect_conversation_id:
            if _new_conversation_id_from_text(buffer) is not None:
                return buffer
        elif buffer.strip():
            return buffer


async def _drain_stream(stream: asyncio.StreamReader) -> None:
    with suppress(Exception):
        while await stream.read(64 * 1024):
            pass
