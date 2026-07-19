from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from xmuse import chat_api, chat_api_runtime
from xmuse.chat_api import create_app
from xmuse_core.chat.room_execution_profiles import RoomExecutionProfileError
from xmuse_core.chat.room_operations import runtime_incident_guard


def test_chat_api_import_and_app_creation_keep_compat_control_planes_lazy(
    tmp_path: Path,
) -> None:
    script = r"""
import json
import sys
from pathlib import Path

from xmuse.chat_api import create_app

app = create_app(
    Path(sys.argv[1]),
    workroom_runtime_inspector=lambda *_args: {
        "state": "stopped",
        "ready": False,
    },
)
forbidden = sorted(
    name
    for name in sys.modules
    if name == "a2a"
    or name.startswith("a2a.")
    or name.startswith("xmuse.compat")
    or name == "xmuse_core.chat.compat_api_models"
    or name.startswith("xmuse_core.integrations.a2a")
    or name.startswith("xmuse_core.providers.adapters.a2a")
    or name == "xmuse_core.chat.peer_scheduler"
    or name.startswith("xmuse_core.chat.scheduler_")
    or name.startswith("xmuse_core.structuring")
    or name.startswith("xmuse_core.platform")
)
print(
    json.dumps(
        {
            "forbidden": forbidden,
            "routes": sorted(
                route.path
                for route in app.routes
                if isinstance(getattr(route, "path", None), str)
            ),
        }
    )
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "runtime")],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["forbidden"] == []
    business_routes = {
        route for route in payload["routes"] if route.startswith("/api/") or route == "/health"
    }
    assert business_routes == {
        "/health",
        "/api/chat/conversations",
        "/api/chat/rooms",
        "/api/chat/bootstrap",
        "/api/chat/room-setup-options",
        "/api/chat/conversations/{conversation_id}/room-projection",
        "/api/chat/conversations/{conversation_id}/agent-streams",
        "/api/chat/conversations/{conversation_id}/events",
        "/api/chat/threads/{conversation_id}/messages",
        "/api/chat/operator/room-observations/{observation_id}/cancel",
        "/api/chat/operator/room-observations/{observation_id}/retry",
        "/api/chat/runtime/operations",
        "/api/chat/operator/room-runtime/recover",
        "/api/chat/conversations/{conversation_id}/executions",
        "/api/chat/execution-candidates/{candidate_id}",
        "/api/chat/operator/conversations/{conversation_id}/execution-policy",
        "/api/chat/operator/execution-candidates/{candidate_id}/decision",
        "/api/chat/operator/execution-runs/{run_id}/cancel",
        "/api/chat/conversations/{conversation_id}/memory",
        "/api/chat/operator/memory-candidates/{candidate_id}/resolve",
        "/api/chat/operator/memory-runtime/rebuild",
        "/api/chat/conversations/{conversation_id}/codex-agents",
        "/api/chat/operator/room-participants/{participant_id}/codex-actions",
    }


def test_chat_api_main_reads_server_only_workspace_and_fixed_profile_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    observed: dict[str, object] = {}
    sentinel_app = object()

    def fake_create_app(**kwargs):
        observed.update(kwargs)
        return sentinel_app

    def fake_run(app, **kwargs):
        observed["app"] = app
        observed["uvicorn"] = kwargs

    monkeypatch.setenv("XMUSE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("XMUSE_EXECUTION_PROFILE_ID", "python-uv/v1")
    monkeypatch.setattr(chat_api, "resolve_operator_token", lambda: "operator-secret")
    monkeypatch.setattr(chat_api, "create_app", fake_create_app)
    monkeypatch.setattr(chat_api.uvicorn, "run", fake_run)

    chat_api.main()

    assert observed["execution_worktree"] == str(workspace)
    assert observed["execution_profile_id"] == "python-uv/v1"
    assert observed["auth_token"] == "operator-secret"
    assert observed["app"] is sentinel_app
    assert observed["uvicorn"] == {"host": "127.0.0.1", "port": 8201}


def test_chat_api_rejects_unknown_execution_profile_during_composition(
    tmp_path: Path,
) -> None:
    with pytest.raises(RoomExecutionProfileError, match="room_execution_gate_profile_unknown"):
        create_app(
            tmp_path / "runtime",
            execution_worktree=tmp_path / "workspace",
            execution_profile_id="repository-command/v1",
        )


def test_chat_api_lifespan_does_not_start_runtime_without_managed_flag(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("XMUSE_WORKROOM_MANAGED", raising=False)

    def starter(_root, _execution_root):
        calls.append("start")
        return {"state": "running"}

    def stopper(_root):
        calls.append("stop")
        return {"state": "stopped"}

    app = create_app(
        tmp_path,
        workroom_runtime_starter=starter,
        workroom_runtime_stopper=stopper,
        workroom_runtime_inspector=lambda *_args: {
            "state": "degraded",
            "ready": False,
            "code": "room_runtime_stopped",
        },
        workroom_runtime_reconcile_interval_s=0.01,
    )
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert "path" not in str(health.json())
        assert "pid" not in str(health.json())

    assert calls == []


def test_managed_chat_api_starts_reconciles_and_stops_owned_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    calls_lock = threading.Lock()
    reconciled = threading.Event()
    monkeypatch.setenv("XMUSE_WORKROOM_MANAGED", "1")

    def starter(root, execution_root):
        assert root == tmp_path
        assert execution_root == tmp_path / "repo"
        with calls_lock:
            calls.append("start")
            if calls.count("start") >= 2:
                reconciled.set()
        return {
            "schema_version": "workroom_room_runtime/v1",
            "state": "ready",
            "ready": True,
            "code": "ready",
        }

    def stopper(root):
        assert root == tmp_path
        with calls_lock:
            calls.append("stop")
        return {"state": "stopped"}

    app = create_app(
        tmp_path,
        execution_worktree=tmp_path / "repo",
        workroom_runtime_starter=starter,
        workroom_runtime_stopper=stopper,
        workroom_runtime_inspector=lambda *_args: {
            "state": "ready",
            "ready": True,
            "code": "ready",
        },
        workroom_runtime_reconcile_interval_s=0.01,
    )
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert reconciled.wait(timeout=1)
        assert app.state.workroom_runtime["state"] == "ready"

    with calls_lock:
        assert calls[:3] == ["stop", "start", "start"]
        assert calls[-1] == "stop"
        assert calls.count("stop") == 2


def test_health_uses_fresh_inspection_over_cached_ready_payload(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("XMUSE_WORKROOM_MANAGED", raising=False)
    app = create_app(
        tmp_path,
        workroom_runtime_inspector=lambda *_args: {
            "state": "degraded",
            "ready": False,
            "code": "room_runner_process_missing",
        },
    )
    app.state.workroom_runtime = {
        "state": "ready",
        "ready": True,
        "code": "ready",
    }

    with TestClient(app) as client:
        payload = client.get("/health").json()

    assert payload == {
        "status": "degraded",
        "service": "xmuse-chat-api",
        "runtime": {
            "state": "degraded",
            "code": "room_runner_process_missing",
            "ready": False,
        },
    }


def test_guarded_recover_stops_degraded_then_ensures_once(tmp_path: Path, monkeypatch) -> None:
    degraded = {
        "state": "degraded",
        "code": "room_runner_heartbeat_stale",
        "ready": False,
        "generation": "generation-one",
        "boot_id": "boot-one",
        "services": {
            "room_runner": {
                "live": True,
                "ready": False,
                "pids": [101],
                "assessment_code": "room_runner_heartbeat_stale",
            },
            "room_mcp": {"live": True, "ready": True, "pids": [102]},
        },
        "host": {"state": "healthy", "code": "room_host_healthy"},
    }
    calls: list[str] = []
    monkeypatch.setattr(
        chat_api_runtime,
        "_workroom_room_runtime_config",
        lambda *_args, **_kwargs: type("Config", (), {"generation": "generation-one"})(),
    )
    monkeypatch.setattr(chat_api_runtime, "inspect_room_runtime", lambda _config: degraded)
    monkeypatch.setattr(
        chat_api_runtime,
        "_stop_workroom_room_runtime_locked",
        lambda *_args, **_kwargs: calls.append("stop") or {"state": "stopped"},
    )
    monkeypatch.setattr(
        chat_api_runtime,
        "ensure_room_runtime",
        lambda _config: (
            calls.append("ensure") or {"state": "ready", "ready": True, "code": "ready"}
        ),
    )

    result = chat_api_runtime.recover_workroom_room_runtime(
        tmp_path,
        tmp_path / "repo",
        runtime_incident_guard(degraded),
    )

    assert result["status"] == "applied"
    assert calls == ["stop", "ensure"]


def test_guarded_recover_rechecks_guard_before_any_process_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    stopped = {
        "state": "stopped",
        "code": "room_runtime_stopped",
        "ready": False,
        "generation": "generation-one",
        "services": {
            "room_runner": {"live": False, "ready": False, "pids": []},
            "room_mcp": {"live": False, "ready": False, "pids": []},
        },
        "host": {"state": "unknown", "code": "room_host_unknown"},
    }
    monkeypatch.setattr(
        chat_api_runtime,
        "_workroom_room_runtime_config",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(chat_api_runtime, "inspect_room_runtime", lambda _config: stopped)
    monkeypatch.setattr(
        chat_api_runtime,
        "ensure_room_runtime",
        lambda _config: pytest.fail("stale guard must not start a process"),
    )

    with pytest.raises(HTTPException) as raised:
        chat_api_runtime.recover_workroom_room_runtime(
            tmp_path,
            tmp_path / "repo",
            "incident_stale",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "room_runtime_incident_changed"


def test_live_process_with_unverifiable_identity_is_not_recoverable(
    tmp_path: Path, monkeypatch
) -> None:
    unsafe = {
        "state": "degraded",
        "code": "room_runner_process_identity_mismatch",
        "ready": False,
        "generation": "generation-one",
        "services": {
            "room_runner": {
                "live": True,
                "ready": False,
                "pids": [101],
                "assessment_code": "room_runner_process_identity_mismatch",
            },
            "room_mcp": {"live": True, "ready": True, "pids": [102]},
        },
        "host": {"state": "healthy", "code": "room_host_healthy"},
    }
    monkeypatch.setattr(
        chat_api_runtime,
        "_workroom_room_runtime_config",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(chat_api_runtime, "inspect_room_runtime", lambda _config: unsafe)
    monkeypatch.setattr(
        chat_api_runtime,
        "_stop_workroom_room_runtime_locked",
        lambda *_args, **_kwargs: pytest.fail("unverifiable identity must not be signalled"),
    )

    with pytest.raises(HTTPException) as raised:
        chat_api_runtime.recover_workroom_room_runtime(
            tmp_path,
            tmp_path / "repo",
            runtime_incident_guard(unsafe),
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "room_runtime_not_recoverable"
