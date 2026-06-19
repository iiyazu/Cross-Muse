from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.providers.registry import normalize_codex_model_id

PeerRequestStatus = Literal[
    "ok",
    "peer_unavailable",
    "delivery_failed",
    "timeout",
    "request_id_missing",
    "request_id_mismatch",
    "peer_error",
]


class PersistentPeerSessionLayer(Protocol):
    async def ensure_conversation_session(self, **kwargs: Any) -> GodSessionRecord: ...
    async def send_message(self, **kwargs: Any) -> None: ...
    async def receive_message(self, god_session_id: str) -> StdoutMessage | None: ...


class PeerCompatibilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PeerHandle:
    conversation_id: str
    participant_id: str
    god_session_id: str
    role: str
    cli_kind: str
    runtime: str
    model: str
    prompt_fingerprint: str
    worktree: str
    feature_scope_id: str | None = None


@dataclass(frozen=True)
class PeerRequestResult:
    status: PeerRequestStatus
    request_id: str
    reason: str | None = None
    message: StdoutMessage | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class PersistentCliPeerService:
    def __init__(self, *, db_path: Path | str, session_layer: PersistentPeerSessionLayer) -> None:
        self._participants = ParticipantStore(db_path)
        self._session_layer = session_layer

    async def ensure_peer(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        model: str,
        prompt: str,
        session_prompt: str | None = None,
        worktree: Path,
        feature_scope_id: str | None = None,
        prompt_contract: dict[str, object] | None = None,
    ) -> PeerHandle:
        try:
            participant = self._participants.get(participant_id)
        except KeyError as exc:
            raise PeerCompatibilityError("unknown_participant", participant_id) from exc
        if participant.conversation_id != conversation_id:
            raise PeerCompatibilityError("conversation_mismatch", participant_id)
        if participant.status != "active":
            raise PeerCompatibilityError("participant_inactive", participant_id)
        if participant.cli_kind == "codex":
            runtime = AgentRuntime.CODEX
            normalized_model = normalize_codex_model_id(
                model,
                profile_id=participant.profile_id,
            )
        elif participant.cli_kind == "opencode":
            runtime = AgentRuntime.OPENCODE
            normalized_model = model.strip()
            if not normalized_model:
                raise PeerCompatibilityError("model_required", participant.cli_kind)
        else:
            raise PeerCompatibilityError("runtime_mismatch", participant.cli_kind)
        if participant.model != normalized_model:
            raise PeerCompatibilityError(
                "model_mismatch",
                f"participant model {participant.model!r} != requested {normalized_model!r}",
            )

        prompt_fingerprint = fingerprint_prompt(
            session_prompt if session_prompt is not None else prompt
        )
        try:
            record = await self._session_layer.ensure_conversation_session(
                conversation_id=conversation_id,
                participant_id=participant_id,
                role=participant.role,
                agent=AgentDescriptor(
                    runtime=runtime,
                    name=participant.display_name,
                    capabilities=[participant.role],
                ),
                worktree=worktree,
                model=normalized_model,
                prompt_fingerprint=prompt_fingerprint,
                feature_scope_id=feature_scope_id,
            )
        except Exception as exc:
            raise PeerCompatibilityError(
                "session_compatibility_mismatch",
                str(exc),
            ) from exc
        _record_prompt_contract_if_supported(
            self._session_layer,
            record.god_session_id,
            prompt_contract,
        )
        return PeerHandle(
            conversation_id=conversation_id,
            participant_id=participant_id,
            god_session_id=record.god_session_id,
            role=participant.role,
            cli_kind=participant.cli_kind,
            runtime=runtime.value,
            model=normalized_model,
            prompt_fingerprint=prompt_fingerprint,
            worktree=str(worktree),
            feature_scope_id=feature_scope_id,
        )

    async def send_request(
        self,
        handle: PeerHandle,
        *,
        message_type: str,
        request_id: str,
        prompt: str,
        context: str,
    ) -> PeerRequestResult:
        try:
            await self._session_layer.send_message(
                god_session_id=handle.god_session_id,
                message_type=message_type,
                request_id=request_id,
                prompt=prompt,
                context=context,
            )
        except Exception as exc:
            return PeerRequestResult(
                status="delivery_failed",
                request_id=request_id,
                reason="send_failed",
                error_message=str(exc),
            )
        return PeerRequestResult(status="ok", request_id=request_id)

    async def receive_result(
        self,
        *,
        god_session_id: str,
        request_id: str,
        timeout_s: float,
    ) -> PeerRequestResult:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return PeerRequestResult(
                    status="timeout",
                    request_id=request_id,
                    reason="timeout",
                )
            try:
                message = await asyncio.wait_for(
                    self._session_layer.receive_message(god_session_id),
                    timeout=remaining,
                )
            except TimeoutError:
                return PeerRequestResult(
                    status="timeout",
                    request_id=request_id,
                    reason="timeout",
                )
            except Exception as exc:
                return PeerRequestResult(
                    status="delivery_failed",
                    request_id=request_id,
                    reason="receive_failed",
                    error_message=str(exc),
                )
            if message is None:
                return PeerRequestResult(
                    status="delivery_failed",
                    request_id=request_id,
                    reason="no_result_message",
                )
            if message.type not in {"result", "error"}:
                continue
            if message.request_id is None:
                return PeerRequestResult(
                    status="request_id_missing",
                    request_id=request_id,
                    reason="request_id_missing",
                    message=message,
                )
            if message.request_id != request_id:
                return PeerRequestResult(
                    status="request_id_mismatch",
                    request_id=request_id,
                    reason="request_id_mismatch",
                    message=message,
                )
            if message.type == "error":
                return PeerRequestResult(
                    status="peer_error",
                    request_id=request_id,
                    reason=message.code or "peer_error",
                    message=message,
                    error_message=message.message,
                )
            return PeerRequestResult(status="ok", request_id=request_id, message=message)

    async def request(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        model: str,
        prompt: str,
        session_prompt: str | None = None,
        worktree: Path,
        request_id: str,
        message_type: str,
        context: str,
        feature_scope_id: str | None = None,
        timeout_s: float = 180.0,
        prompt_contract: dict[str, object] | None = None,
    ) -> PeerRequestResult:
        try:
            handle = await self.ensure_peer(
                conversation_id=conversation_id,
                participant_id=participant_id,
                model=model,
                prompt=prompt,
                session_prompt=session_prompt,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
                prompt_contract=prompt_contract,
            )
        except Exception as exc:
            return PeerRequestResult(
                status="peer_unavailable",
                request_id=request_id,
                reason="ensure_failed",
                error_message=str(exc),
            )
        sent = await self.send_request(
            handle,
            message_type=message_type,
            request_id=request_id,
            prompt=prompt,
            context=context,
        )
        if not sent.ok:
            return sent
        return await self.receive_result(
            god_session_id=handle.god_session_id,
            request_id=request_id,
            timeout_s=timeout_s,
        )


def fingerprint_prompt(prompt: str) -> str:
    return f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"


def _record_prompt_contract_if_supported(
    session_layer: PersistentPeerSessionLayer,
    god_session_id: str,
    prompt_contract: dict[str, object] | None,
) -> None:
    if prompt_contract is None:
        return
    recorder = getattr(session_layer, "record_prompt_contract", None)
    if not callable(recorder):
        return
    recorder(god_session_id, **prompt_contract)
