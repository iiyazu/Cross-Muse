"""HTTP surface for bounded Room exact-patch execution projections and actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query, Request, Response, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_api_models import (
    RoomExecutionCandidateDecisionRequest,
    RoomExecutionPolicyRequest,
    RoomExecutionRunCancelRequest,
)
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_projection import (
    RoomExecutionReadStore,
    build_room_execution_candidate_projection,
    build_room_execution_list_projection,
)
from xmuse_core.runtime.frontend_api import operator_error


class RoomExecutionCommandStore(RoomExecutionReadStore, Protocol):
    def set_policy(
        self,
        *,
        conversation_id: str,
        mode: Literal["manual", "consensus"],
        client_action_id: str,
        operator_identity: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def apply_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
        workspace_guard: ExecutionWorkspaceGuard | None,
        risk_evaluation: ExecutionRiskEvaluation | None,
        gate_plan: ExecutionGatePlan | None,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def replay_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
    ) -> Mapping[str, Any] | None: ...

    def request_cancel(
        self,
        *,
        run_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...


RoomExecutionStoreFactory = Callable[[Path], RoomExecutionCommandStore]
RoomExecutionReadStoreFactory = Callable[[Path], RoomExecutionReadStore]
ExecutionRunStarter = Callable[[str], None]
ExecutionDecisionContextProvider = Callable[
    [str],
    tuple[
        ExecutionWorkspaceGuard | None,
        ExecutionRiskEvaluation | None,
        ExecutionGatePlan | None,
    ],
]
ExecutionProfileProvider = Callable[[], Mapping[str, Any]]
ConversationExists = Callable[[str], bool]

_CONFLICT_MARKERS = (
    "conflict",
    "guard",
    "revision",
    "digest",
    "state_changed",
    "not_actionable",
    "already_",
    "idempotency",
)


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("room_execution_"):
        return code
    value = str(exc)
    if value.startswith("room_execution_") and len(value) <= 200:
        return value
    return "room_execution_action_failed"


def _store_error(exc: Exception) -> HTTPException:
    code = _error_code(exc)
    if code.endswith("_not_found"):
        http_status = status.HTTP_404_NOT_FOUND
    elif any(marker in code for marker in _CONFLICT_MARKERS):
        http_status = status.HTTP_409_CONFLICT
    elif code.endswith("_unavailable"):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=http_status,
        detail=operator_error(code, "Room execution action was not applied"),
    )


def _identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned) <= 200 else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _child_mapping(result: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = result.get(key)
    return value if isinstance(value, Mapping) else {}


def _safe_action_result(
    result: Mapping[str, Any],
    *,
    client_action_id: str,
    fallback_status: str = "applied",
) -> dict[str, Any]:
    run = _child_mapping(result, "run")
    policy = _child_mapping(result, "policy")
    candidate = _child_mapping(result, "candidate")
    return {
        "action_id": _identifier(result.get("action_id")) or client_action_id,
        "status": _identifier(result.get("status")) or fallback_status,
        "conversation_id": _identifier(
            result.get("conversation_id") or policy.get("conversation_id")
        ),
        "candidate_id": _identifier(
            result.get("candidate_id") or candidate.get("candidate_id") or candidate.get("id")
        ),
        "run_id": _identifier(result.get("run_id") or run.get("run_id") or run.get("id")),
        "state": _identifier(result.get("state") or run.get("state") or candidate.get("state")),
        "revision": _integer(
            result.get("revision") or run.get("revision") or candidate.get("revision")
        ),
        "policy_mode": _identifier(policy.get("mode") or result.get("mode")),
        "policy_revision": _integer(
            policy.get("revision")
            or result.get("policy_revision")
            or (
                result.get("revision")
                if result.get("schema_version") == "room_execution_policy/v1"
                else None
            )
        ),
        "proof_boundary": "operator_action_receipt_not_execution_or_room_authority",
    }


def register_room_execution_routes(
    app: FastAPI,
    *,
    root: Path,
    store_factory: RoomExecutionStoreFactory,
    read_store_factory: RoomExecutionReadStoreFactory | None = None,
    operator_token: str | None = None,
    decision_context_provider: ExecutionDecisionContextProvider | None = None,
    run_starter: ExecutionRunStarter | None = None,
    execution_profile_provider: ExecutionProfileProvider | None = None,
    consensus_kill_switch_enabled: bool = False,
    conversation_exists: ConversationExists | None = None,
) -> None:
    def store() -> RoomExecutionCommandStore:
        return store_factory(root / "chat.db")

    def read_store() -> RoomExecutionReadStore:
        if read_store_factory is None:
            return store()
        return read_store_factory(root / "chat.db")

    def execution_profile() -> Mapping[str, Any] | None:
        if execution_profile_provider is None:
            return None
        try:
            return execution_profile_provider()
        except Exception:
            return None

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

    @app.get("/api/chat/conversations/{conversation_id}/executions")
    def room_executions(
        conversation_id: str,
        response: Response,
        limit: int = Query(default=20, ge=1, le=50),
        cursor: str | None = Query(default=None, min_length=1, max_length=200),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            require_conversation(conversation_id)
            return build_room_execution_list_projection(
                read_store(),
                conversation_id,
                limit=limit,
                cursor=cursor,
                consensus_kill_switch_enabled=consensus_kill_switch_enabled,
                execution_profile=execution_profile(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_code(exc)) from exc

    @app.get("/api/chat/execution-candidates/{candidate_id}")
    def room_execution_candidate(
        candidate_id: str,
        response: Response,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return build_room_execution_candidate_projection(
                read_store(),
                candidate_id,
                consensus_kill_switch_enabled=consensus_kill_switch_enabled,
                execution_profile=execution_profile(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="execution candidate not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=_error_code(exc)) from exc

    @app.put("/api/chat/operator/conversations/{conversation_id}/execution-policy")
    def update_room_execution_policy(
        conversation_id: str,
        request: Request,
        payload: RoomExecutionPolicyRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            result = store().set_policy(
                conversation_id=conversation_id,
                mode=payload.mode,
                client_action_id=payload.client_action_id,
                operator_identity="operator:local",
                expected_revision=payload.expected_revision,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        return _safe_action_result(result, client_action_id=payload.client_action_id)

    @app.post("/api/chat/operator/execution-candidates/{candidate_id}/decision")
    def decide_room_execution_candidate(
        candidate_id: str,
        request: Request,
        payload: RoomExecutionCandidateDecisionRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        decision_store = store()

        def finish(
            result: Mapping[str, Any],
            *,
            start_new_run: bool,
        ) -> dict[str, Any]:
            safe = _safe_action_result(result, client_action_id=payload.client_action_id)
            if (
                start_new_run
                and payload.decision == "execute"
                and safe["run_id"] is not None
                and run_starter is not None
            ):
                try:
                    run_starter(str(safe["run_id"]))
                except Exception:
                    # Authorization and the requested run are already durable. The
                    # background reconciler will safely start or recover it.
                    safe["status"] = "recovery_pending"
                    safe["reason_code"] = "room_execution_controller_reconcile_pending"
            return safe

        def replay() -> Mapping[str, Any] | None:
            try:
                return decision_store.replay_operator_decision(
                    candidate_id=candidate_id,
                    decision=payload.decision,
                    client_action_id=payload.client_action_id,
                    operator_identity="operator:local",
                    expected_candidate_digest=payload.expected_candidate_digest,
                    expected_candidate_revision=payload.expected_candidate_revision,
                    expected_policy_revision=payload.expected_policy_revision,
                )
            except (KeyError, ValueError, RuntimeError) as exc:
                raise _store_error(exc) from exc

        def unavailable(code: str, message: str) -> dict[str, Any]:
            durable = replay()
            if durable is not None:
                return finish(durable, start_new_run=False)
            raise HTTPException(
                status_code=503,
                detail=operator_error(code, message),
            )

        durable = replay()
        if durable is not None:
            return finish(durable, start_new_run=False)

        workspace_guard: ExecutionWorkspaceGuard | None = None
        risk_evaluation: ExecutionRiskEvaluation | None = None
        gate_plan: ExecutionGatePlan | None = None
        if payload.decision == "execute" and decision_context_provider is None:
            return unavailable(
                "room_execution_decision_context_unavailable",
                "Execution guards could not be established",
            )
        if payload.decision == "execute" and run_starter is None:
            return unavailable(
                "room_execution_controller_unavailable",
                "Execution controller is not available",
            )
        if payload.decision == "execute" and decision_context_provider is not None:
            try:
                workspace_guard, risk_evaluation, gate_plan = decision_context_provider(
                    candidate_id
                )
            except Exception as exc:
                durable = replay()
                if durable is not None:
                    return finish(durable, start_new_run=False)
                raise HTTPException(
                    status_code=503,
                    detail=operator_error(
                        "room_execution_decision_context_unavailable",
                        "Execution guards could not be established",
                    ),
                ) from exc
            if workspace_guard is None:
                return unavailable(
                    "room_execution_decision_context_unavailable",
                    "Execution guards could not be established",
                )
            if gate_plan is None:
                return unavailable(
                    "room_execution_gate_profile_unavailable",
                    "The fixed execution gate profile is not ready",
                )
            durable = replay()
            if durable is not None:
                return finish(durable, start_new_run=False)
        try:
            result = decision_store.apply_operator_decision(
                candidate_id=candidate_id,
                decision=payload.decision,
                client_action_id=payload.client_action_id,
                operator_identity="operator:local",
                expected_candidate_digest=payload.expected_candidate_digest,
                expected_candidate_revision=payload.expected_candidate_revision,
                expected_policy_revision=payload.expected_policy_revision,
                workspace_guard=workspace_guard,
                risk_evaluation=risk_evaluation,
                gate_plan=gate_plan,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        return finish(result, start_new_run=True)

    @app.post("/api/chat/operator/execution-runs/{run_id}/cancel")
    def cancel_room_execution_run(
        run_id: str,
        request: Request,
        payload: RoomExecutionRunCancelRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            result = store().request_cancel(
                run_id=run_id,
                client_action_id=payload.client_action_id,
                operator_identity="operator:local",
                expected_state=payload.expected_run_state,
                expected_revision=payload.expected_run_revision,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        return _safe_action_result(result, client_action_id=payload.client_action_id)
