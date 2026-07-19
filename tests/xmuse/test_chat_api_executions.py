from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.xmuse.execution_store_testkit import TestExecutionStore
from tests.xmuse.test_room_execution_outcomes import (
    DIGEST,
    PATH,
    make_candidate,
    trusted_gate_plan,
)
from xmuse.chat_api_executions import register_room_execution_routes
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_contracts import ExecutionWorkspaceGuard
from xmuse_core.chat.room_execution_operator_store import RoomExecutionOperatorStore
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader


class _ExecutionStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.actions: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.policy = {
            "conversation_id": "conv-1",
            "mode": "manual",
            "revision": 2,
            "risk_policy_revision": "room_execution_low_risk/v1",
        }
        self.candidate = {
            "candidate_id": "candidate-1",
            "conversation_id": "conv-1",
            "proposal_id": "proposal-1",
            "author_participant_id": "participant-1",
            "base_head": "a" * 40,
            "summary": "Bounded change",
            "unified_diff": "diff --git a/a.py b/a.py\n+x = 1\n",
            "allowed_files": ["a.py"],
            "digest": "sha256:candidate",
            "snapshot_digest": "sha256:snapshot",
            "state": "open",
            "revision": 4,
            "policy_mode": "manual",
            "policy_revision": 2,
            "risk_policy_revision": "room_execution_low_risk/v1",
            "snapshot_members": [],
            "assessments": [],
        }
        self.run = {
            "run_id": "run-1",
            "candidate_id": "candidate-1",
            "state": "requested",
            "revision": 1,
            "gates": [],
        }

    def get_policy(self, conversation_id: str):
        return self.policy if conversation_id == "conv-1" else None

    def get_candidate(self, candidate_id: str, *, include_patch: bool = False):
        assert isinstance(include_patch, bool)
        return self.candidate if candidate_id == "candidate-1" else None

    def list_conversation_candidates(self, conversation_id: str, *, limit: int = 50):
        return (
            {"candidates": [self.candidate][:limit]}
            if conversation_id == "conv-1"
            else {"candidates": []}
        )

    def get_run(self, run_id: str):
        return self.run if run_id == "run-1" else None

    def list_conversation_runs(self, conversation_id: str, *, limit: int = 50):
        return {"runs": []}

    def _idempotent(self, action_id: str, fingerprint: dict[str, Any], result: dict[str, Any]):
        prior = self.actions.get(action_id)
        if prior is not None:
            if prior[0] != fingerprint:
                raise ValueError("room_execution_action_idempotency_conflict")
            return prior[1]
        self.actions[action_id] = (fingerprint, result)
        return result

    def set_policy(
        self,
        conversation_id: str,
        mode: str,
        client_action_id: str,
        operator_identity: str,
        expected_revision: int,
        *,
        now=None,
    ):
        del now
        arguments = {
            "conversation_id": conversation_id,
            "mode": mode,
            "operator_identity": operator_identity,
            "expected_revision": expected_revision,
        }
        self.calls.append(("policy", arguments))
        if expected_revision != 2:
            raise ValueError("room_execution_policy_revision_conflict")
        return self._idempotent(
            client_action_id,
            arguments,
            {
                "action_id": client_action_id,
                "status": "applied",
                "policy": {"conversation_id": conversation_id, "mode": mode, "revision": 3},
            },
        )

    def apply_operator_decision(self, candidate_id: str, **kwargs):
        self.calls.append(("decision", {"candidate_id": candidate_id, **kwargs}))
        if kwargs["expected_candidate_digest"] != "sha256:candidate":
            raise ValueError("room_execution_candidate_digest_conflict")
        fingerprint = {
            "candidate_id": candidate_id,
            **{
                key: kwargs[key]
                for key in (
                    "decision",
                    "expected_candidate_digest",
                    "expected_candidate_revision",
                    "expected_policy_revision",
                    "operator_identity",
                )
            },
        }
        prior = self.actions.get(kwargs["client_action_id"])
        if prior is not None:
            return self._idempotent(kwargs["client_action_id"], fingerprint, {})
        if kwargs["decision"] == "execute" and kwargs["workspace_guard"] is None:
            raise ValueError("room_execution_workspace_guard_required")
        result = {
            "action_id": kwargs["client_action_id"],
            "status": "applied",
            "candidate_id": candidate_id,
            "state": "authorized",
            **({"run_id": "run-1"} if kwargs["decision"] == "execute" else {}),
        }
        return self._idempotent(kwargs["client_action_id"], fingerprint, result)

    def replay_operator_decision(self, candidate_id: str, **kwargs):
        fingerprint = {
            "candidate_id": candidate_id,
            **{
                key: kwargs[key]
                for key in (
                    "decision",
                    "expected_candidate_digest",
                    "expected_candidate_revision",
                    "expected_policy_revision",
                    "operator_identity",
                )
            },
        }
        prior = self.actions.get(kwargs["client_action_id"])
        if prior is None:
            return None
        if prior[0] != fingerprint:
            raise ValueError("room_execution_action_idempotency_conflict")
        return prior[1]

    def request_cancel(self, *, run_id: str, **kwargs):
        self.calls.append(("cancel", {"run_id": run_id, **kwargs}))
        if kwargs["expected_state"] != "requested":
            raise ValueError("room_execution_run_state_conflict")
        return self._idempotent(
            kwargs["client_action_id"],
            {"run_id": run_id, **kwargs},
            {
                "action_id": kwargs["client_action_id"],
                "status": "applied",
                "run": {"run_id": run_id, "state": "cancel_requested", "revision": 2},
            },
        )


def _client(
    store: _ExecutionStore,
    *,
    token: str | None = "operator-secret",
    starters: list[str] | None = None,
) -> TestClient:
    app = FastAPI()
    register_room_execution_routes(
        app,
        root=Path("/tmp/xmuse-execution-api-test"),
        store_factory=lambda _path: store,
        operator_token=token,
        decision_context_provider=lambda candidate_id: (
            {"head": "trusted-head", "candidate_id": candidate_id},
            {"policy": "low-risk"},
            {"profile_id": "xmuse-monorepo/v2", "trusted": True},
        ),
        execution_profile_provider=lambda: {
            "schema_version": "room_execution_gate_profile/v1",
            "profile_id": "xmuse-monorepo/v2",
            "revision": 2,
            "gate_ids": [
                "patch_diff_check",
                "backend_ruff",
                "backend_mypy",
                "backend_pytest",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_vitest",
                "frontend_build",
            ],
            "readiness": {"state": "ready", "ready": True, "code": "ready"},
            "workspace_path": "/must-not-project",
        },
        run_starter=(starters.append if starters is not None else None),
        conversation_exists=lambda conversation_id: conversation_id == "conv-1",
    )
    return TestClient(app)


def _headers(token: str = "operator-secret") -> dict[str, str]:
    return {"X-XMuse-Operator-Token": token}


def test_execution_reads_are_bounded_no_store_and_candidate_detail_is_explicit() -> None:
    store = _ExecutionStore()
    client = _client(store)

    listing = client.get("/api/chat/conversations/conv-1/executions?limit=20")
    detail = client.get("/api/chat/execution-candidates/candidate-1")

    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "no-store"
    assert "unified_diff" not in listing.text
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["candidate"]["unified_diff"].startswith("diff --git")
    assert listing.json()["gate_profile"] == {
        "schema_version": "room_execution_gate_profile/v1",
        "profile_id": "xmuse-monorepo/v2",
        "revision": 2,
        "gate_ids": [
            "patch_diff_check",
            "backend_ruff",
            "backend_mypy",
            "backend_pytest",
            "frontend_typecheck",
            "frontend_lint",
            "frontend_vitest",
            "frontend_build",
        ],
        "readiness": {"state": "ready", "ready": True, "code": "ready"},
    }
    assert "/must-not-project" not in listing.text
    assert client.get("/api/chat/execution-candidates/missing").status_code == 404
    assert client.get("/api/chat/conversations/conv-1/executions?limit=51").status_code == 422


def test_execution_get_routes_do_not_construct_the_command_store() -> None:
    read_store = _ExecutionStore()
    app = FastAPI()

    def command_store_forbidden(_path: Path):
        raise AssertionError("GET projection acquired the command store")

    register_room_execution_routes(
        app,
        root=Path("/tmp/xmuse-execution-read-api-test"),
        store_factory=command_store_forbidden,
        read_store_factory=lambda _path: read_store,
        conversation_exists=lambda conversation_id: conversation_id == "conv-1",
    )
    client = TestClient(app)

    assert client.get("/api/chat/conversations/conv-1/executions").status_code == 200
    assert client.get("/api/chat/execution-candidates/candidate-1").status_code == 200


def test_operator_routes_require_token_and_reject_extra_or_invalid_guards() -> None:
    store = _ExecutionStore()
    client = _client(store)
    body = {
        "client_action_id": "policy-1",
        "mode": "consensus",
        "expected_revision": 2,
    }

    assert (
        client.put(
            "/api/chat/operator/conversations/conv-1/execution-policy", json=body
        ).status_code
        == 401
    )
    assert (
        client.put(
            "/api/chat/operator/conversations/conv-1/execution-policy",
            headers=_headers("wrong"),
            json=body,
        ).status_code
        == 401
    )
    assert (
        client.put(
            "/api/chat/operator/conversations/conv-1/execution-policy",
            headers=_headers(),
            json={**body, "href": "https://evil.invalid"},
        ).status_code
        == 422
    )
    conflict = client.put(
        "/api/chat/operator/conversations/conv-1/execution-policy",
        headers=_headers(),
        json={**body, "expected_revision": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "room_execution_policy_revision_conflict"


def test_policy_and_decision_are_guarded_idempotent_and_start_only_the_created_run() -> None:
    store = _ExecutionStore()
    starters: list[str] = []
    client = _client(store, starters=starters)
    policy_body = {
        "client_action_id": "policy-1",
        "mode": "consensus",
        "expected_revision": 2,
    }

    first = client.put(
        "/api/chat/operator/conversations/conv-1/execution-policy",
        headers=_headers(),
        json=policy_body,
    )
    replay = client.put(
        "/api/chat/operator/conversations/conv-1/execution-policy",
        headers=_headers(),
        json=policy_body,
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["policy_mode"] == "consensus"

    decision_body = {
        "client_action_id": "decision-1",
        "decision": "execute",
        "expected_candidate_digest": "sha256:candidate",
        "expected_candidate_revision": 4,
        "expected_policy_revision": 2,
    }
    decision = client.post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json=decision_body,
    )
    assert decision.status_code == 200
    assert decision.json()["run_id"] == "run-1"
    assert starters == ["run-1"]
    replayed_decision = client.post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json=decision_body,
    )
    assert replayed_decision.status_code == 200
    assert replayed_decision.json()["run_id"] == "run-1"
    assert starters == ["run-1"]
    assert len(set(starters)) == 1
    call = next(
        arguments
        for name, arguments in store.calls
        if name == "decision" and arguments["workspace_guard"] is not None
    )
    assert call["workspace_guard"] == {
        "head": "trusted-head",
        "candidate_id": "candidate-1",
    }
    assert call["risk_evaluation"] == {"policy": "low-risk"}
    assert call["gate_plan"] == {
        "profile_id": "xmuse-monorepo/v2",
        "trusted": True,
    }

    digest_conflict = client.post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json={
            **decision_body,
            "client_action_id": "decision-2",
            "expected_candidate_digest": "wrong",
        },
    )
    assert digest_conflict.status_code == 409
    assert starters == ["run-1"]


def test_reject_needs_no_controller_and_cancel_passes_exact_run_guards() -> None:
    store = _ExecutionStore()
    client = _client(store)
    rejected = client.post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json={
            "client_action_id": "reject-1",
            "decision": "reject",
            "expected_candidate_digest": "sha256:candidate",
            "expected_candidate_revision": 4,
            "expected_policy_revision": 2,
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["run_id"] is None

    cancelled = client.post(
        "/api/chat/operator/execution-runs/run-1/cancel",
        headers=_headers(),
        json={
            "client_action_id": "cancel-1",
            "expected_run_state": "requested",
            "expected_run_revision": 1,
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancel_requested"
    call = next(arguments for name, arguments in store.calls if name == "cancel")
    assert call["run_id"] == "run-1"
    assert call["operator_identity"] == "operator:local"
    assert call["expected_revision"] == 1


def test_missing_controller_fails_closed_before_durable_run_request() -> None:
    store = _ExecutionStore()
    response = _client(store).post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json={
            "client_action_id": "execute-no-controller",
            "decision": "execute",
            "expected_candidate_digest": "sha256:candidate",
            "expected_candidate_revision": 4,
            "expected_policy_revision": 2,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "room_execution_controller_unavailable"
    assert not any(name == "decision" for name, _arguments in store.calls)
    assert store.actions == {}


def test_unready_fixed_profile_fails_before_durable_run_request() -> None:
    store = _ExecutionStore()
    app = FastAPI()
    register_room_execution_routes(
        app,
        root=Path("/tmp/xmuse-execution-api-test"),
        store_factory=lambda _path: store,
        operator_token="operator-secret",
        decision_context_provider=lambda candidate_id: (
            {"head": "trusted-head", "candidate_id": candidate_id},
            None,
            None,
        ),
        run_starter=lambda _run_id: None,
        conversation_exists=lambda conversation_id: conversation_id == "conv-1",
    )

    response = TestClient(app).post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json={
            "client_action_id": "execute-profile-blocked",
            "decision": "execute",
            "expected_candidate_digest": "sha256:candidate",
            "expected_candidate_revision": 4,
            "expected_policy_revision": 2,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == ("room_execution_gate_profile_unavailable")
    assert not any(name == "decision" for name, _arguments in store.calls)
    assert store.actions == {}


def test_start_failure_reports_durable_recovery_pending_instead_of_false_failure() -> None:
    store = _ExecutionStore()
    app = FastAPI()
    register_room_execution_routes(
        app,
        root=Path("/tmp/xmuse-execution-api-test"),
        store_factory=lambda _path: store,
        operator_token="operator-secret",
        decision_context_provider=lambda candidate_id: (
            {"head": "trusted-head", "candidate_id": candidate_id},
            {"policy": "low-risk"},
            {"profile_id": "xmuse-monorepo/v2", "trusted": True},
        ),
        run_starter=lambda _run_id: (_ for _ in ()).throw(RuntimeError("start failed")),
        conversation_exists=lambda conversation_id: conversation_id == "conv-1",
    )

    response = TestClient(app).post(
        "/api/chat/operator/execution-candidates/candidate-1/decision",
        headers=_headers(),
        json={
            "client_action_id": "execute-reconcile",
            "decision": "execute",
            "expected_candidate_digest": "sha256:candidate",
            "expected_candidate_revision": 4,
            "expected_policy_revision": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "recovery_pending"
    assert response.json()["reason_code"] == "room_execution_controller_reconcile_pending"


def test_routes_bind_the_real_store_keyword_contract_and_default_manual_policy(
    tmp_path: Path,
) -> None:
    database = RoomDatabase(tmp_path / "chat.db")
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            "insert into conversations(id, title, created_at) values (?, ?, ?)",
            ("conv-real-store", "Real execution store", "2026-07-12T10:00:00Z"),
        )
    app = FastAPI()
    register_room_execution_routes(
        app,
        root=tmp_path,
        store_factory=RoomExecutionOperatorStore,
        read_store_factory=RoomExecutionLedgerReader,
        operator_token="operator-secret",
        consensus_kill_switch_enabled=False,
    )
    client = TestClient(app)

    listing = client.get("/api/chat/conversations/conv-real-store/executions")
    assert listing.status_code == 200
    assert listing.json()["policy"]["mode"] == "manual"
    assert listing.json()["policy"]["kill_switch_enabled"] is False

    updated = client.put(
        "/api/chat/operator/conversations/conv-real-store/execution-policy",
        headers=_headers(),
        json={
            "client_action_id": "real-store-policy",
            "mode": "consensus",
            "expected_revision": 0,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["policy_mode"] == "consensus"
    assert updated.json()["policy_revision"] == 1
    stored = RoomExecutionLedgerReader(tmp_path / "chat.db").get_policy("conv-real-store")
    assert stored is not None
    assert stored["mode"] == "consensus"

    operator_store = RoomExecutionOperatorStore(tmp_path / "chat.db")
    assert not hasattr(operator_store, "claim_requested_run")
    assert not hasattr(operator_store, "record_gate_evidence")
    assert not hasattr(operator_store, "prepare_promotion")
    assert not hasattr(operator_store, "finalize_run")


def _real_decision_fixture(tmp_path: Path, *, action_id: str):
    db, _registry, _conversation_id, _records, _claims, outcome, execution = make_candidate(
        tmp_path
    )
    candidate = execution.get_candidate(outcome["execution_candidate"]["candidate_id"])
    assert candidate is not None
    body = {
        "client_action_id": action_id,
        "decision": "execute",
        "expected_candidate_digest": candidate["candidate_digest"],
        "expected_candidate_revision": candidate["revision"],
        "expected_policy_revision": 0,
    }
    apply_kwargs = {
        "candidate_id": candidate["candidate_id"],
        **body,
        "operator_identity": "operator:local",
        "workspace_guard": ExecutionWorkspaceGuard(
            "a" * 40,
            True,
            DIGEST,
            frozenset({PATH}),
        ),
        "gate_plan": trusted_gate_plan(),
    }
    return db, execution, candidate, body, apply_kwargs


def test_real_store_lost_response_replays_before_context_or_controller_failure(
    tmp_path: Path,
) -> None:
    _db, execution, candidate, body, apply_kwargs = _real_decision_fixture(
        tmp_path,
        action_id="lost-response",
    )
    applied = execution.apply_operator_decision(**apply_kwargs)
    context_calls = 0

    def unavailable_context(_candidate_id: str):
        nonlocal context_calls
        context_calls += 1
        raise RuntimeError("workspace unavailable after promotion")

    app = FastAPI()
    register_room_execution_routes(
        app,
        root=tmp_path,
        store_factory=TestExecutionStore,
        read_store_factory=RoomExecutionLedgerReader,
        operator_token="operator-secret",
        decision_context_provider=unavailable_context,
        run_starter=None,
    )
    client = TestClient(app)

    replay = client.post(
        f"/api/chat/operator/execution-candidates/{candidate['candidate_id']}/decision",
        headers=_headers(),
        json=body,
    )
    conflict = client.post(
        f"/api/chat/operator/execution-candidates/{candidate['candidate_id']}/decision",
        headers=_headers(),
        json={**body, "expected_candidate_revision": 999},
    )

    assert replay.status_code == 200
    assert replay.json()["run_id"] == applied["run"]["run_id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == ("room_execution_action_idempotency_conflict")
    assert context_calls == 0


def test_real_store_secondary_replay_closes_context_provider_commit_race(
    tmp_path: Path,
) -> None:
    db, execution, candidate, body, apply_kwargs = _real_decision_fixture(
        tmp_path,
        action_id="context-race",
    )
    context_calls = 0

    def concurrent_context(_candidate_id: str):
        nonlocal context_calls
        context_calls += 1
        execution.apply_operator_decision(**apply_kwargs)
        raise RuntimeError("the first request lost its response")

    starters: list[str] = []
    app = FastAPI()
    register_room_execution_routes(
        app,
        root=tmp_path,
        store_factory=TestExecutionStore,
        read_store_factory=RoomExecutionLedgerReader,
        operator_token="operator-secret",
        decision_context_provider=concurrent_context,
        run_starter=starters.append,
    )

    response = TestClient(app).post(
        f"/api/chat/operator/execution-candidates/{candidate['candidate_id']}/decision",
        headers=_headers(),
        json=body,
    )

    assert response.status_code == 200
    assert response.json()["run_id"] is not None
    assert context_calls == 1
    assert starters == []
    with sqlite3.connect(db) as conn:
        action_count = conn.execute(
            "select count(*) from room_execution_operator_actions"
        ).fetchone()[0]
    assert action_count == 1
