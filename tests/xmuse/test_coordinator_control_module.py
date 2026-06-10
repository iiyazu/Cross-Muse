from __future__ import annotations

import json
from pathlib import Path

from xmuse import platform_runner
from xmuse_core.platform import coordinator_control


def test_coordinator_control_module_owns_lifecycle_writer(tmp_path: Path) -> None:
    service = coordinator_control.CoordinatorControlService(
        xmuse_root=tmp_path,
        runner_id="runner-1",
        now=lambda: 123.0,
    )

    service.record_lifecycle("started", details={"scope": "stage-0"})

    records = [
        json.loads(line)
        for line in (tmp_path / "coordinator_incidents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records == [
        {
            "kind": "lifecycle",
            "component": "platform_runner",
            "operation": "started",
            "runner_id": "runner-1",
            "created_at": 123.0,
            "details": {"scope": "stage-0"},
        }
    ]


def test_platform_runner_preserves_coordinator_control_compat_export() -> None:
    assert (
        platform_runner.CoordinatorControlService
        is coordinator_control.CoordinatorControlService
    )
