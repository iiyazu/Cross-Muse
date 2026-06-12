from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.integrations.memoryos_events import MemoryOSWritebackEvent
from xmuse_core.integrations.memoryos_namespace import (
    conversation_namespace,
    shared_namespace,
)
from xmuse_core.platform.memoryos_governance_evidence_capture import (
    capture_memoryos_governance_evidence,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)


def test_capture_memoryos_governance_evidence_from_writeback_events(
    tmp_path: Path,
) -> None:
    blueprint_event = _write_event(
        tmp_path / "blueprint-event.json",
        MemoryOSWritebackEvent(
            kind="blueprint_frozen",
            namespace=conversation_namespace("conv-1"),
            actor_id="god-architect",
            event_id="bp-1",
            summary="Blueprint bp-1 was frozen.",
            source_refs=["message:proposal-1", "blueprint:bp-1"],
            commit_sha="abc123",
        ),
    )
    merge_event = _write_event(
        tmp_path / "merge-event.json",
        MemoryOSWritebackEvent(
            kind="pr_merged",
            namespace=conversation_namespace("conv-1"),
            actor_id="god-execute",
            event_id="43",
            summary="PR 43 merged the overnight closure.",
            source_refs=["github:pr:43", "review:rv-1"],
            promote_to_shared=True,
            shared_namespace=shared_namespace("iiyazu/Cross-Muse"),
            reviewed=True,
        ),
    )
    output = tmp_path / "memory-governance-production-evidence.json"

    artifact = capture_memoryos_governance_evidence(
        run_id="overnight-memory",
        writeback_event_artifacts=[blueprint_event, merge_event],
        output_path=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == artifact
    assert artifact["schema_version"] == "xmuse.production_evidence.v1"
    assert artifact["run_id"] == "overnight-memory"
    assert artifact["stage_id"] == "S5"
    assert artifact["action"] == "memory_governance_policy_evaluated"
    assert artifact["status"] == "ok"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["source_authority"] == "memoryos_governance_policy"
    assert artifact["source_refs"] == [
        "memory-governance:plan:blueprint-event",
        "memory://conversation/conv-1/commits/abc123/events/blueprint_frozen/bp-1",
        "message:proposal-1",
        "blueprint:bp-1",
        "memory-governance:plan:merge-event",
        "memory://conversation/conv-1/events/pr_merged/43",
        "github:pr:43",
        "review:rv-1",
    ]
    assert artifact["target_refs"] == [
        "memory://conversation/conv-1",
        "memory://global/shared/iiyazu/Cross-Muse",
    ]
    assert artifact["artifacts"] == [str(blueprint_event), str(merge_event)]
    assert artifact["blocked_reason"] is None
    assert artifact["summary"] == (
        "MemoryOS governance evaluated 2 plan(s): "
        "1 ingest, 1 promote_to_shared, 0 provider_session_binding_only, 0 blocked."
    )

    replay_bundle = capture_overnight_replay_bundle(
        run_id="overnight-memory",
        artifacts_dir=tmp_path / "empty-release-gates",
        output_path=tmp_path / "bundle.json",
        section_artifacts={"memory_governance": output},
    )
    sections = {section["section_id"]: section for section in replay_bundle["sections"]}
    assert sections["memory_governance"]["status"] == "ok"
    assert sections["memory_governance"]["proof_level"] == "contract_proof"
    assert sections["memory_governance"]["source_authority"] == (
        "memoryos_governance_policy"
    )


def test_capture_memoryos_governance_evidence_reports_blocked_plan(
    tmp_path: Path,
) -> None:
    blocked_event = _write_event(
        tmp_path / "blocked-shared-event.json",
        MemoryOSWritebackEvent(
            kind="pr_merged",
            namespace=conversation_namespace("conv-1"),
            actor_id="god-execute",
            event_id="43",
            summary="PR 43 merged the overnight closure.",
            source_refs=["github:pr:43"],
            promote_to_shared=True,
            shared_namespace=shared_namespace("iiyazu/Cross-Muse"),
        ),
    )

    artifact = capture_memoryos_governance_evidence(
        run_id="overnight-memory",
        writeback_event_artifacts=[blocked_event],
        output_path=tmp_path / "memory-governance-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["blocked_reason"] == (
        "memory governance blocked plans: shared promotion requires explicit review"
    )
    assert artifact["next_action"] == (
        "Attach review evidence before promoting memory beyond task scope."
    )


def test_memoryos_governance_evidence_capture_cli_writes_artifact(
    tmp_path: Path,
) -> None:
    from xmuse.memoryos_governance_evidence_capture import main

    event_path = _write_event(
        tmp_path / "blueprint-event.json",
        MemoryOSWritebackEvent(
            kind="blueprint_frozen",
            namespace=conversation_namespace("conv-1"),
            actor_id="god-architect",
            event_id="bp-1",
            summary="Blueprint bp-1 was frozen.",
            source_refs=["message:proposal-1"],
        ),
    )
    output = tmp_path / "memory-governance-production-evidence.json"

    assert (
        main(
            [
                "--run-id",
                "overnight-memory",
                "--writeback-event",
                str(event_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert artifact["action"] == "memory_governance_policy_evaluated"


def test_memoryos_governance_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-memoryos-governance-evidence-capture"]
        == "xmuse.memoryos_governance_evidence_capture:main"
    )


def _write_event(path: Path, event: MemoryOSWritebackEvent) -> Path:
    path.write_text(
        json.dumps(event.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
