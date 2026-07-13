from __future__ import annotations

from xmuse.workroom_status import (
    build_status_projection,
    project_memoryos_receipt,
    project_room_runner_receipt,
)


def test_status_projection_is_read_only_and_omits_local_authority() -> None:
    manifest = {"state": "ready", "generation": "secret-generation"}
    runner = {
        "service": "room_runner",
        "state": "ready",
        "live": True,
        "ready": True,
        "code": "ready",
        "pid": 123,
        "boot_id": "secret-boot",
        "url": "http://127.0.0.1:8100/health",
        "pid_file": "/private/runtime/runner.pid",
        "token": "secret-token",
    }

    code, payload = build_status_projection(
        manifest,
        manager_live=True,
        required_services=[runner],
    )

    assert code == 0
    assert payload["state"] == "ready"
    assert payload["services"] == [
        {
            "service": "room_runner",
            "state": "ready",
            "live": True,
            "ready": True,
            "code": "ready",
        }
    ]
    serialized = repr(payload)
    for forbidden in ("secret-generation", "secret-boot", "secret-token", "/private"):
        assert forbidden not in serialized
    assert manifest == {"state": "ready", "generation": "secret-generation"}


def test_status_state_uses_only_required_readiness() -> None:
    manifest = {"state": "ready"}
    required = [{"service": "chat_api", "live": True, "ready": True}]
    memory = [{"service": "memoryos", "live": False, "ready": False}]

    assert (
        build_status_projection(
            manifest,
            manager_live=True,
            required_services=required,
            optional_services=memory,
        )[1]["state"]
        == "ready"
    )
    assert (
        build_status_projection(
            manifest,
            manager_live=False,
            required_services=required,
            optional_services=memory,
        )[1]["state"]
        == "degraded"
    )


def test_missing_manifest_and_safe_receipt_whitelists() -> None:
    assert build_status_projection(None, manager_live=False, required_services=[]) == (
        1,
        {
            "schema_version": "xmuse_workroom_status/v2",
            "state": "stopped",
            "services": [],
        },
    )
    runner = project_room_runner_receipt(
        {
            "state": "ready",
            "code": "ready",
            "pid": 1,
            "start_identity": "secret",
            "boot_id": "secret",
            "host": {
                "state": "attention",
                "code": "cleanup_pending",
                "active_delivery_count": 2,
                "retained_cleanup_count": 1,
                "provider_output": "secret",
            },
        }
    )
    assert runner == {
        "state": "ready",
        "ready": True,
        "code": "ready",
        "host": {
            "state": "attention",
            "code": "cleanup_pending",
            "active_delivery_count": 2,
            "retained_cleanup_count": 1,
        },
    }
    memory = project_memoryos_receipt(
        {
            "enabled": True,
            "state": "recovering",
            "code": "child_exited",
            "consecutive_restart_count": 2,
            "pid": 2,
            "api_key": "secret",
        }
    )
    assert memory == {
        "enabled": True,
        "state": "recovering",
        "code": "child_exited",
        "consecutive_restart_count": 2,
    }
