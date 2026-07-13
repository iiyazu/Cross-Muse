from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.memoryos_supervisor import (
    memoryos_incident_guard,
    read_memoryos_status,
    write_memoryos_status,
)
from xmuse_core.chat.room_operations import (
    RoomRuntimeOperatorActionStore,
    runtime_incident_guard,
)


def _runtime(*, state: str, code: str, ready: bool) -> dict:
    live = state != "stopped"
    return {
        "state": state,
        "code": code,
        "ready": ready,
        "generation": "secret-generation",
        "boot_id": "secret-boot",
        "services": {
            "room_runner": {
                "live": live,
                "ready": ready,
                "pids": [9101] if live else [],
                "assessment_code": code,
            },
            "room_mcp": {
                "live": live,
                "ready": ready,
                "pids": [9102] if live else [],
            },
        },
        "host": {
            "state": "healthy",
            "code": "room_host_healthy",
            "active_delivery_count": 0,
            "retained_cleanup_count": 0,
        },
    }


def _headers() -> dict[str, str]:
    return {"X-XMuse-Operator-Token": "operator-secret"}


def _write_rebuildable_memory_runtime(root: Path) -> str:
    stamp = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    write_memoryos_status(
        root,
        enabled=True,
        state="degraded",
        code="memoryos_crash_loop",
        generation="private-memory-generation",
        pid=9876,
        start_identity="private-memory-start-identity",
        started_at=stamp,
        heartbeat_at=stamp,
        consecutive_restart_count=6,
        next_retry_at=stamp,
        last_healthy_at=stamp,
    )
    status_path = root / "memoryos-status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload.update(
        {
            "api_key": "private-memory-api-key",
            "data_dir": "/private/memoryos-derived",
            "provider_output": "private-room-content",
        }
    )
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    private = read_memoryos_status(root)
    assert private is not None
    return memoryos_incident_guard(private)


def test_operations_get_is_no_store_safe_and_always_has_action(tmp_path: Path) -> None:
    runtime = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: runtime,
    )

    with TestClient(app) as client:
        response = client.get("/api/chat/runtime/operations")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["overall"] == "blocked"
    assert payload["actions"]["recover_runtime"] == {
        "available": True,
        "method": "POST",
        "href": "/api/chat/operator/room-runtime/recover",
        "expected_incident_id": runtime_incident_guard(runtime),
        "mode": "start",
        "confirmation_required": True,
    }
    encoded = response.text
    assert "secret-generation" not in encoded
    assert "secret-boot" not in encoded
    assert "9101" not in encoded
    assert "9102" not in encoded


def test_operations_get_returns_stable_503_when_database_disappears(
    tmp_path: Path,
) -> None:
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: _runtime(
            state="stopped",
            code="room_runtime_stopped",
            ready=False,
        ),
    )
    (tmp_path / "chat.db").unlink()

    with TestClient(app) as client:
        response = client.get("/api/chat/runtime/operations")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "room_database_unavailable",
        "message": "Room database is unavailable",
    }


def test_recover_requires_operator_token_and_applies_once(tmp_path: Path) -> None:
    stopped = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    ready = _runtime(state="ready", code="ready", ready=True)
    current = [stopped]
    recover_calls: list[str] = []

    def inspector(*_args):
        return current[0]

    def recoverer(_root, _execution_root, expected):
        recover_calls.append(expected)
        current[0] = ready
        return {
            "status": "applied",
            "after": {"state": "ready", "code": "ready"},
        }

    app = create_app(
        tmp_path,
        workroom_runtime_inspector=inspector,
        workroom_runtime_recoverer=recoverer,
    )
    body = {
        "client_action_id": "recover-one",
        "expected_incident_id": runtime_incident_guard(stopped),
    }
    with TestClient(app) as client:
        unauthorized = client.post("/api/chat/operator/room-runtime/recover", json=body)
        assert unauthorized.status_code == 503

        import os

        prior = os.environ.get("XMUSE_OPERATOR_TOKEN")
        os.environ["XMUSE_OPERATOR_TOKEN"] = "operator-secret"
        try:
            first = client.post(
                "/api/chat/operator/room-runtime/recover",
                headers=_headers(),
                json=body,
            )
            replay = client.post(
                "/api/chat/operator/room-runtime/recover",
                headers=_headers(),
                json=body,
            )
        finally:
            if prior is None:
                os.environ.pop("XMUSE_OPERATOR_TOKEN", None)
            else:
                os.environ["XMUSE_OPERATOR_TOKEN"] = prior

    assert first.status_code == 200
    assert first.json()["status"] == "applied"
    assert first.json()["action_id"].startswith("rta_")
    assert replay.json() == first.json()
    assert recover_calls == [body["expected_incident_id"]]


def test_stale_guard_is_durably_rejected_and_extra_fields_forbidden(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    stopped = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: stopped,
        workroom_runtime_recoverer=lambda *_args: (_ for _ in ()).throw(
            AssertionError("stale guard must not recover")
        ),
    )
    body = {
        "client_action_id": "stale-one",
        "expected_incident_id": "incident_stale",
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover", headers=_headers(), json=body
        )
        replay = client.post(
            "/api/chat/operator/room-runtime/recover", headers=_headers(), json=body
        )
        invalid = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json={**body, "client_action_id": "invalid", "pid": 123},
        )

    assert response.status_code == replay.status_code == 409
    assert response.json() == replay.json()
    assert response.json()["detail"]["code"] == "room_runtime_incident_changed"
    assert invalid.status_code == 422


def test_requested_replay_reconciles_ready_without_second_restart(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    ready = _runtime(state="ready", code="ready", ready=True)
    payload = {
        "client_action_id": "crash-replay",
        "expected_incident_id": "incident_prior",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: ready,
        workroom_runtime_recoverer=lambda *_args: (_ for _ in ()).throw(
            AssertionError("ready reconciliation must not restart")
        ),
    )
    ledger = RoomRuntimeOperatorActionStore(tmp_path / "chat.db")
    ledger.reserve(
        client_action_id="crash-replay",
        request_fingerprint=fingerprint,
        incident_guard="incident_prior",
        before_state="degraded",
        before_code="room_runner_heartbeat_stale",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert response.json()["result"] == {"source": "ready_reconciliation"}


def test_requested_replay_continues_after_api_crashed_post_stop(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    stopped = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    prior_guard = "incident_prior_degraded"
    payload = {
        "client_action_id": "post-stop-replay",
        "expected_incident_id": prior_guard,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    recover_guards: list[str] = []
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: stopped,
        workroom_runtime_recoverer=lambda _root, _execution, guard: (
            recover_guards.append(guard) or {"after": {"state": "ready", "code": "ready"}}
        ),
    )
    ledger = RoomRuntimeOperatorActionStore(tmp_path / "chat.db")
    ledger.reserve(
        client_action_id="post-stop-replay",
        request_fingerprint=fingerprint,
        incident_guard=prior_guard,
        before_state="degraded",
        before_code="room_runner_heartbeat_stale",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert recover_guards == [runtime_incident_guard(stopped)]


def test_requested_replay_does_not_treat_new_degraded_boot_as_old_action_success(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    degraded = _runtime(state="degraded", code="room_runner_heartbeat_stale", ready=False)
    payload = {
        "client_action_id": "new-fault-replay",
        "expected_incident_id": "incident_prior_boot",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: degraded,
        workroom_runtime_recoverer=lambda *_args: (_ for _ in ()).throw(
            AssertionError("new degraded topology must require a fresh action")
        ),
    )
    RoomRuntimeOperatorActionStore(tmp_path / "chat.db").reserve(
        client_action_id="new-fault-replay",
        request_fingerprint=hashlib.sha256(encoded.encode()).hexdigest(),
        incident_guard="incident_prior_boot",
        before_state="degraded",
        before_code="room_runner_heartbeat_stale",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=payload,
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_runtime_incident_changed"


def test_different_client_is_rejected_while_recovery_is_requested(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    stopped = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: stopped,
        workroom_runtime_recoverer=lambda *_args: (_ for _ in ()).throw(
            AssertionError("second action must not restart")
        ),
    )
    ledger = RoomRuntimeOperatorActionStore(tmp_path / "chat.db")
    ledger.reserve(
        client_action_id="first",
        request_fingerprint="first-fingerprint",
        incident_guard=runtime_incident_guard(stopped),
        before_state="stopped",
        before_code="room_runtime_stopped",
    )
    second = {
        "client_action_id": "second",
        "expected_incident_id": runtime_incident_guard(stopped),
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=second,
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_runtime_recovery_in_progress"


def test_recover_inspection_failure_is_durable_503_without_process_action(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: (_ for _ in ()).throw(
            OSError("private inspection failure")
        ),
        workroom_runtime_recoverer=lambda *_args: (_ for _ in ()).throw(
            AssertionError("unverifiable runtime must not recover")
        ),
    )
    body = {
        "client_action_id": "unverifiable-one",
        "expected_incident_id": "incident_unknown",
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=body,
        )
        replay = client.post(
            "/api/chat/operator/room-runtime/recover",
            headers=_headers(),
            json=body,
        )

    assert response.status_code == replay.status_code == 503
    assert response.json() == replay.json()
    assert response.json()["detail"] == {
        "code": "room_runtime_unverifiable",
        "message": "Room runtime recovery was not applied",
    }


def test_operations_v2_projects_memory_recovery_without_private_evidence(
    tmp_path: Path,
) -> None:
    expected_incident_id = _write_rebuildable_memory_runtime(tmp_path)
    app = create_app(
        tmp_path,
        auth_token="operator-secret",
        workroom_runtime_inspector=lambda *_args: _runtime(state="ready", code="ready", ready=True),
    )

    with TestClient(app) as client:
        response = client.get("/api/chat/runtime/operations")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["schema_version"] == "room_operations_projection/v2"
    assert payload["overall"] == "attention"
    assert payload["runtime"]["memory"] == {
        "enabled": True,
        "state": "degraded",
        "code": "memoryos_crash_loop",
        "consecutive_restart_count": 6,
        "next_retry_at": payload["runtime"]["memory"]["next_retry_at"],
        "last_healthy_at": payload["runtime"]["memory"]["last_healthy_at"],
    }
    memory_incident = next(
        incident for incident in payload["incidents"] if incident["kind"] == "memory"
    )
    assert memory_incident["incident_id"] == expected_incident_id
    assert memory_incident["severity"] == "attention"
    assert memory_incident["next_action"] == "rebuild_memory_index"
    assert payload["actions"]["rebuild_memory_index"] == {
        "available": True,
        "pending": False,
        "status": None,
        "phase": None,
        "method": "POST",
        "href": "/api/chat/operator/memory-runtime/rebuild",
        "expected_incident_id": expected_incident_id,
        "confirmation_required": True,
    }
    encoded = response.text
    for secret in (
        "private-memory-generation",
        "private-memory-start-identity",
        "private-memory-api-key",
        "/private/memoryos-derived",
        "private-room-content",
        "9876",
    ):
        assert secret not in encoded


def test_memory_rebuild_api_auth_guard_idempotency_and_safe_receipt(
    tmp_path: Path,
) -> None:
    expected_incident_id = _write_rebuildable_memory_runtime(tmp_path)
    app = create_app(
        tmp_path,
        auth_token="operator-secret",
        workroom_runtime_inspector=lambda *_args: _runtime(state="ready", code="ready", ready=True),
    )
    correct = {
        "client_action_id": "memory-rebuild-one",
        "expected_incident_id": expected_incident_id,
    }
    stale = {
        "client_action_id": "memory-rebuild-stale",
        "expected_incident_id": "memoryos_incident_stale",
    }

    with TestClient(app) as client:
        unauthorized = client.post("/api/chat/operator/memory-runtime/rebuild", json=correct)
        stale_response = client.post(
            "/api/chat/operator/memory-runtime/rebuild", headers=_headers(), json=stale
        )
        stale_replay = client.post(
            "/api/chat/operator/memory-runtime/rebuild", headers=_headers(), json=stale
        )
        first = client.post(
            "/api/chat/operator/memory-runtime/rebuild", headers=_headers(), json=correct
        )
        replay = client.post(
            "/api/chat/operator/memory-runtime/rebuild", headers=_headers(), json=correct
        )
        conflict = client.post(
            "/api/chat/operator/memory-runtime/rebuild",
            headers=_headers(),
            json={**correct, "expected_incident_id": "memoryos_incident_other"},
        )
        competing = client.post(
            "/api/chat/operator/memory-runtime/rebuild",
            headers=_headers(),
            json={**correct, "client_action_id": "memory-rebuild-two"},
        )
        extra = client.post(
            "/api/chat/operator/memory-runtime/rebuild",
            headers=_headers(),
            json={**correct, "pid": 9876},
        )

    assert unauthorized.status_code == 401
    assert stale_response.status_code == stale_replay.status_code == 409
    assert stale_response.json() == stale_replay.json()
    assert stale_response.json()["detail"]["code"] == ("room_memory_rebuild_incident_changed")
    assert first.status_code == replay.status_code == 202
    assert first.headers["cache-control"] == "no-store"
    assert first.json() == replay.json()
    assert set(first.json()) == {
        "schema_version",
        "action_id",
        "client_action_id",
        "status",
        "phase",
        "reason_code",
        "before",
        "after",
        "result",
        "requested_at",
        "applied_at",
        "proof_boundary",
    }
    assert first.json()["status"] == "requested"
    assert first.json()["phase"] == "requested"
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == ("room_memory_rebuild_idempotency_conflict")
    assert competing.status_code == 409
    assert competing.json()["detail"]["code"] == "room_memory_rebuild_in_progress"
    assert extra.status_code == 422
    for response in (stale_response, first, replay, conflict, competing):
        assert "private-memory" not in response.text
        assert "9876" not in response.text
