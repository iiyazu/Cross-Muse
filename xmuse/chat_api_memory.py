"""HTTP surface for bounded Room memory projections and candidate approval."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Request, Response, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_api_models import RoomMemoryCandidateResolveRequest
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_projection import (
    RoomMemoryBindingReadStore,
    RoomMemoryDeliveryReadStore,
    RoomMemoryGovernanceReadStore,
    RoomMemoryRecallReadStore,
    build_room_memory_projection,
    build_room_memory_projection_v2,
)
from xmuse_core.runtime.frontend_api import operator_error


class RoomMemoryCandidateCommandStore(RoomMemoryGovernanceReadStore, Protocol):
    def resolve_candidate(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...


RoomMemoryBindingStoreFactory = Callable[[Path], RoomMemoryBindingReadStore]
RoomMemoryGovernanceStoreFactory = Callable[[Path], RoomMemoryCandidateCommandStore]
RoomMemoryDeliveryStoreFactory = Callable[[Path], RoomMemoryDeliveryReadStore]
RoomMemoryRecallStoreFactory = Callable[[Path], RoomMemoryRecallReadStore]
MemoryRuntimeStatusProvider = Callable[[], Mapping[str, Any]]
ConversationExists = Callable[[str], bool]

_CONFLICT_CODES = {
    "room_memory_candidate_already_resolved",
    "room_memory_candidate_guard_mismatch",
    "room_memory_action_idempotency_conflict",
}


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("room_memory_"):
        return code
    value = str(exc)
    if value.startswith("room_memory_") and len(value) <= 200:
        return value
    return "room_memory_action_failed"


def _store_error(exc: Exception) -> HTTPException:
    code = _error_code(exc)
    if code == "room_memory_candidate_not_found":
        http_status = status.HTTP_404_NOT_FOUND
    elif code in _CONFLICT_CODES or any(
        marker in code for marker in ("guard", "conflict", "already_resolved")
    ):
        http_status = status.HTTP_409_CONFLICT
    elif code.endswith("_unavailable"):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=http_status,
        detail=operator_error(code, "Room memory candidate was not resolved"),
    )


def _identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned) <= 200 else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _safe_resolve_result(
    result: Mapping[str, Any], *, client_action_id: str, candidate_id: str
) -> dict[str, Any]:
    candidate = result.get("candidate")
    source = candidate if isinstance(candidate, Mapping) else result
    return {
        "action_id": _identifier(result.get("action_id")) or client_action_id,
        "status": _identifier(result.get("status")) or "applied",
        "candidate_id": _identifier(source.get("candidate_id")) or candidate_id,
        "conversation_id": _identifier(source.get("conversation_id")),
        "approval_state": _identifier(source.get("approval_state")),
        "publish_state": _identifier(source.get("publish_state")),
        "revision": _integer(source.get("revision")),
        "reason_code": _identifier(source.get("reason_code")),
        "proof_boundary": "operator_action_receipt_not_memory_or_room_authority",
    }


def register_room_memory_routes(
    app: FastAPI,
    *,
    root: Path,
    binding_store_factory: RoomMemoryBindingStoreFactory,
    governance_store_factory: RoomMemoryGovernanceStoreFactory,
    delivery_store_factory: RoomMemoryDeliveryStoreFactory,
    recall_store_factory: RoomMemoryRecallStoreFactory,
    operator_token: str | None = None,
    runtime_status_provider: MemoryRuntimeStatusProvider | None = None,
    conversation_exists: ConversationExists | None = None,
) -> None:
    def binding_store() -> RoomMemoryBindingReadStore:
        return binding_store_factory(root / "chat.db")

    def governance_store() -> RoomMemoryCandidateCommandStore:
        return governance_store_factory(root / "chat.db")

    def delivery_store() -> RoomMemoryDeliveryReadStore:
        return delivery_store_factory(root / "chat.db")

    def recall_store() -> RoomMemoryRecallReadStore:
        return recall_store_factory(root / "chat.db")

    def require_conversation(conversation_id: str) -> None:
        if conversation_exists is not None:
            if not conversation_exists(conversation_id):
                raise HTTPException(status_code=404, detail="conversation not found")
            return
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            exists = conn.execute(
                "select 1 from conversations where id = ?", (conversation_id,)
            ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="conversation not found")

    @app.get("/api/chat/conversations/{conversation_id}/memory")
    def room_memory(conversation_id: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        require_conversation(conversation_id)
        runtime_status: Mapping[str, Any] | None = None
        if runtime_status_provider is not None:
            try:
                runtime_status = runtime_status_provider()
            except Exception:
                runtime_status = {
                    "enabled": True,
                    "state": "degraded",
                    "code": "room_memory_runtime_status_unavailable",
                }
        try:
            binding = binding_store()
            governance = governance_store()
            delivery = delivery_store()
            recall = recall_store()
            if (
                isinstance(runtime_status, Mapping)
                and runtime_status.get("profile") == "full-local"
            ):
                return build_room_memory_projection_v2(
                    conversation_id,
                    binding_store=binding,
                    governance_store=governance,
                    delivery_store=delivery,
                    recall_store=recall,
                    runtime_status=runtime_status,
                )
            return build_room_memory_projection(
                conversation_id,
                binding_store=binding,
                governance_store=governance,
                delivery_store=delivery,
                recall_store=recall,
                runtime_status=runtime_status,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=_error_code(exc)) from exc

    @app.post("/api/chat/operator/memory-candidates/{candidate_id}/resolve")
    def resolve_room_memory_candidate(
        candidate_id: str,
        request: Request,
        payload: RoomMemoryCandidateResolveRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            result = governance_store().resolve_candidate(
                candidate_id=candidate_id,
                decision=payload.decision,
                client_action_id=payload.client_action_id,
                operator_identity="operator:local",
                expected_candidate_digest=payload.expected_digest,
                expected_revision=payload.expected_revision,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        return _safe_resolve_result(
            result,
            client_action_id=payload.client_action_id,
            candidate_id=candidate_id,
        )
