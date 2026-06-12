from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.integrations.memoryos_events import MemoryOSWritebackEvent
from xmuse_core.integrations.memoryos_namespace import conversation_namespace
from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
)
from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
from xmuse_core.structuring.feature_owner_contract import (
    build_feature_owner_execution_contract,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_section_evidence(
    path: Path,
    *,
    section_id: str,
    status: str,
    proof_level: str,
    source_authority: str,
    source_refs: list[str],
    summary: str,
) -> None:
    _write_json(
        path,
        {
            "schema_version": "xmuse.production_evidence.v1",
            "stage_id": "S4",
            "action": f"{section_id}_evidence",
            "status": status,
            "proof_level": proof_level,
            "source_authority": source_authority,
            "source_refs": source_refs,
            "target_refs": [],
            "commands": [],
            "test_results": [],
            "artifacts": [],
            "blocked_reason": None,
            "owner": "codex",
            "next_action": None,
            "summary": summary,
        },
    )


def _write_supervisor_snapshot(tmp_path: Path, *, run_id: str) -> Path:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id=run_id,
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="supervise overnight closure",
                )
            ],
        )
    )
    supervisor.start_stage("S4")
    supervisor.record_heartbeat(note="supervisor running")
    supervisor.record_checkpoint(
        stage_id="S4",
        summary="supervisor checkpoint captured",
        validation=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        commands=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        source_refs=["goal:stage:S4"],
    )
    return tmp_path / f"overnight-supervisor-{run_id}.json"


def _write_memoryos_event(path: Path) -> Path:
    event = MemoryOSWritebackEvent(
        kind="blueprint_frozen",
        namespace=conversation_namespace("conv-1"),
        actor_id="god-architect",
        event_id="bp-1",
        summary="Blueprint bp-1 was frozen.",
        source_refs=["message:proposal-1", "blueprint:bp-1"],
    )
    _write_json(path, event.model_dump(mode="json"))
    return path


def _write_memoryos_trace(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": "xmuse.memoryos_lite_trace.v1",
        "proof_level": "live_service_proof",
        "fact_state": "observed",
        "namespace_uri": "memory://conversation/conv-prod-1/god-review/thread-1",
        "session_id": "memoryos-session-1",
        "trace_events": [
            {
                "kind": "session_created",
                "metadata": {"xmuse_source_refs": ["conversation:conv-prod-1"]},
            },
            {
                "kind": "ingest",
                "metadata": {"xmuse_source_refs": ["lane:lane-memoryos"]},
            },
            {
                "kind": "context_built",
                "estimated_tokens": 128,
                "metadata": {"xmuse_source_refs": ["blueprint:bp-overnight"]},
            },
        ],
        "source_refs": [
            "conversation:conv-prod-1",
            "lane:lane-memoryos",
            "blueprint:bp-overnight",
        ],
        "estimated_tokens": 128,
        "blockers": [],
    }
    payload.update(overrides)
    _write_json(path, payload)
    return path


def _provider_stage_timings(offset: float) -> dict[str, dict[str, float]]:
    return {
        "ray_actor_delivery_start": {"at": offset + 1.0},
        "codex_app_server_turn_start": {"at": offset + 2.0},
        "chat_post_message": {"at": offset + 3.0},
        "trace_persisted": {"at": offset + 4.0},
    }


def _write_real_provider_runtime(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": "xmuse.real_provider_runtime.v1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "run_id": "real-provider-pack-run",
        "conversation_id": "conv-prod-1",
        "source_refs": ["chat:conversation:conv-prod-1"],
        "provider_runtime": {
            "provider_id": "codex",
            "runtime_backend": "ray",
            "transport": "codex-app-server",
            "provider_session_id": "codex-thread-prod-1",
            "mcp_writeback": True,
        },
        "restart_resume": {
            "fresh_provider_session_id": "codex-thread-prod-1",
            "resumed_provider_session_id": "codex-thread-prod-1",
            "provider_session_reused": True,
        },
        "turns": [
            {
                "turn_id": "turn-fresh-1",
                "phase": "fresh",
                "delivery_mode": "mcp_writeback",
                "degraded_reason": None,
                "provider_id": "codex",
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "provider_session_id": "codex-thread-prod-1",
                "stage_timings": _provider_stage_timings(1.0),
            },
            {
                "turn_id": "turn-resume-1",
                "phase": "resume",
                "delivery_mode": "mcp_writeback",
                "degraded_reason": None,
                "provider_id": "codex",
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "provider_session_id": "codex-thread-prod-1",
                "stage_timings": _provider_stage_timings(10.0),
            },
        ],
        "blockers": [],
    }
    payload.update(overrides)
    _write_json(path, payload)
    return path


def _write_github_server_truth(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": "github_server_side_truth_capture.v1",
        "repo": "iiyazu/Cross-Muse",
        "pull_request_number": 43,
        "head_sha": "head-pack-1",
        "expected_head_sha": "head-pack-1",
        "head_sha_matches_expected": True,
        "required_checks": [
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
        ],
        "check_run_ids": [211, 212, 213],
        "expected_source_app": "github-actions",
        "branch_protection_snapshot": {
            "required_status_checks": {
                "checks": [
                    {"context": "quality-gates"},
                    {"context": "contract-smoke-gates"},
                    {"context": "real-runtime-integration-gate"},
                ]
            }
        },
        "ruleset_snapshot": None,
        "proof_level": "manual_gap",
        "gap_reason": "missing server-side truth: review_truth, merge_truth",
        "can_emit_pr_merged": False,
        "merged": False,
        "review_event_id": None,
        "merge_event_id": None,
        "capture_mode": "opt_in_read_only_gh_api",
    }
    payload.update(overrides)
    _write_json(path, payload)
    return path


def _write_internal_review(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": "xmuse.internal_review.v1",
        "review_id": "review-pr43-head-pack-1",
        "reviewer": "codex-reviewer",
        "reviewed_head_sha": "head-pack-1",
        "decision": "approved",
        "summary": "No blocking findings.",
        "findings": [
            {"severity": "minor", "status": "open", "summary": "Doc polish."}
        ],
        "source_refs": ["github:pr:43"],
    }
    payload.update(overrides)
    _write_json(path, payload)
    return path


def _write_transcript(path: Path) -> Path:
    _write_json(
        path,
        {
            "schema_version": "xmuse.operator_transcript.v1",
            "conversation_id": "conv-prod-1",
            "proof_level": "real_provider_proof",
            "fact_state": "observed",
            "natural_deliberation": True,
            "source_refs": ["memory://conversation/conv-prod-1/transcript"],
            "target_refs": ["blueprint:prod:1"],
            "messages": [
                {
                    "message_id": "msg-1",
                    "conversation_id": "conv-prod-1",
                    "god_id": "architect-god",
                    "provider_id": "codex",
                    "provider_profile": "codex-prod",
                    "session_id": "codex-session-1",
                    "speech_act": "propose",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["memory://conversation/conv-prod-1/source"],
                    "target_refs": ["blueprint:prod:1"],
                    "blocking": False,
                },
                {
                    "message_id": "msg-2",
                    "conversation_id": "conv-prod-1",
                    "god_id": "review-god",
                    "provider_id": "opencode",
                    "provider_profile": "opencode-prod",
                    "session_id": "opencode-session-1",
                    "speech_act": "vote",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["message:msg-1"],
                    "target_refs": ["blueprint:prod:1", "lane:prod-a"],
                    "blocking": False,
                },
            ],
            "blockers": [],
        },
    )
    return path


def _write_god_runtime(path: Path) -> Path:
    _write_json(
        path,
        {
            "schema_version": "xmuse.god_runtime_continuity.v1",
            "conversation_id": "conv-prod-1",
            "proof_level": "contract_proof",
            "fact_state": "observed",
            "source_refs": ["god_cli_selection:conv-prod-1"],
            "items": [
                {
                    "god_id": "architect-god",
                    "cli_id": "codex.god",
                    "peer_god_ready": True,
                    "bounded": False,
                    "provider_session_ready": True,
                    "proof_level": "contract_proof",
                    "source_refs": ["god_session:architect"],
                },
                {
                    "god_id": "review-god",
                    "cli_id": "custom.peer",
                    "peer_god_ready": True,
                    "bounded": False,
                    "provider_session_ready": True,
                    "proof_level": "contract_proof",
                    "source_refs": ["god_session:review"],
                },
            ],
        },
    )
    return path


def _write_blueprint(path: Path, *, status: MissionBlueprintStatus) -> Path:
    blueprint = MissionBlueprintV1(
        blueprint_id="bp-overnight",
        conversation_id="conv-prod-1",
        revision=3,
        goal="Close overnight autonomy evidence loop.",
        scope=["feature graph", "release replay"],
        constraints=["Use uv run.", "Do not create xmuse/__init__.py."],
        non_goals=["No proof upgrades by rendering."],
        acceptance_contracts=[
            "Frozen blueprint is attached to replay evidence.",
            "Feature execution starts from graph authority.",
        ],
        repo_areas=["src/xmuse_core/platform", "src/xmuse_core/structuring"],
        open_questions=[],
        decision_log=[
            {
                "decision": "Freeze before feature owner execution.",
                "source_refs": ["message:challenge-1"],
            }
        ],
        source_refs=["message:proposal-1", "message:challenge-1"],
        status=status,
        approved_by=["architect-god", "review-god"],
    )
    _write_json(path, blueprint.model_dump(mode="json"))
    return path


def _write_feature_contract(path: Path) -> Path:
    contract = build_feature_owner_execution_contract(
        feature_id="feature-replay-pack",
        objective="Attach graph-native feature lineage to the release pack.",
        graph_set_id="graph-set-prod-1",
        feature_graph_id="graph-release-replay",
        source_authority="graph_set_store",
        source_refs=("graph-set:graph-set-prod-1", "blueprint:bp-overnight"),
        allowed_files=("src/xmuse_core/platform/release_evidence_pack.py",),
        lanes=(
            {
                "feature_id": "lane-blueprint",
                "lane_local_id": "lane-blueprint",
                "conversation_id": "conv-prod-1",
                "graph_id": "graph-release-replay",
                "status": "pending",
                "depends_on": [],
            },
            {
                "feature_id": "lane-feature-lineage",
                "lane_local_id": "lane-feature-lineage",
                "conversation_id": "conv-prod-1",
                "graph_id": "graph-release-replay",
                "status": "pending",
                "depends_on": ["lane-blueprint"],
            },
        ),
        memory_refs=("memory://conversation/conv-prod-1/feature-lineage",),
        required_checks=("uv run pytest tests/xmuse/test_release_evidence_pack.py -q",),
        review_profile="internal-adversarial",
        patch_forward_policy="review_failures_spawn_patch_forward_lane",
        rollback_constraints=("do not mutate feature_lanes.json",),
    )
    _write_json(path, contract.model_dump(mode="json"))
    return path


def _gate(
    *,
    gate_id: str,
    kind: str,
    status: str,
    proof_level: str,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": gate_id,
        "kind": kind,
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": f"{gate_id} evidence",
        "source_refs": [f"{kind}:source"],
        "artifacts": [f"/tmp/{gate_id}.json"],
    }
    payload.update(overrides)
    return payload


def test_release_evidence_pack_writes_readiness_audit_and_summary(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    supervisor = tmp_path / "supervisor-production-evidence.json"
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
            source_refs=["github:pr:43", "github:branch:main"],
        ),
    )
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            status="manual_gap",
            proof_level="manual_gap",
            summary="Ray/Codex runtime was not started.",
            next_action="Start the configured production provider bundle.",
        ),
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor heartbeat and checkpoint captured.",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="overnight-pack-test",
        section_artifacts={"supervisor": supervisor},
    )

    readiness_output = output.parent / "release-readiness.json"
    audit_output = output.parent / "proof-contamination-audit.json"
    replay_output = output.parent / "overnight-replay-bundle.json"
    assert output.exists()
    assert readiness_output.exists()
    assert audit_output.exists()
    assert replay_output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == pack
    assert pack["schema_version"] == "xmuse.release_evidence_pack.v1"
    assert pack["decision"] == "blocked"
    assert pack["release_readiness_decision"] == "blocked"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["overnight_replay_decision"] == "blocked"
    assert pack["overnight_replay_authority"] == "replay_index_only"
    assert pack["artifact_count"] == 2
    assert pack["blocker_count"] == 1
    assert pack["replay_blocker_count"] >= 1
    assert pack["finding_count"] == 0
    assert pack["readiness_report"] == str(readiness_output)
    assert pack["proof_contamination_audit"] == str(audit_output)
    assert pack["overnight_replay_bundle"] == str(replay_output)
    assert pack["blockers"][0]["gate_id"] == "real-provider-runtime"
    assert pack["source_reports"] == {
        "release_readiness": str(readiness_output),
        "proof_contamination_audit": str(audit_output),
        "overnight_replay_bundle": str(replay_output),
    }
    replay = json.loads(replay_output.read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert replay["run_id"] == "overnight-pack-test"
    assert replay["authority"] == "replay_index_only"
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["source_authority"] == "overnight_operator_supervisor"


def test_release_evidence_pack_converts_supervisor_snapshot_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    snapshot = _write_supervisor_snapshot(tmp_path / "supervisor", run_id="pack-supervisor")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-supervisor",
        supervisor_snapshot=snapshot,
    )

    supervisor_evidence = output.parent / "supervisor-production-evidence.json"
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert supervisor_evidence.exists()
    assert pack["source_reports"]["overnight_supervisor_evidence"] == str(
        supervisor_evidence
    )
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["source_authority"] == "overnight_operator_supervisor"
    assert sections["supervisor"]["artifacts"][0] == str(snapshot)


def test_release_evidence_pack_converts_memoryos_writeback_events_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    event_path = _write_memoryos_event(tmp_path / "events" / "blueprint-event.json")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-memoryos-governance",
        memoryos_writeback_events=(event_path,),
    )

    memoryos_evidence = output.parent / "memoryos-governance-production-evidence.json"
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert memoryos_evidence.exists()
    assert pack["source_reports"]["memoryos_governance_evidence"] == str(
        memoryos_evidence
    )
    assert sections["memory_governance"]["status"] == "ok"
    assert sections["memory_governance"]["proof_level"] == "contract_proof"
    assert sections["memory_governance"]["source_authority"] == (
        "memoryos_governance_policy"
    )
    assert sections["memory_governance"]["artifacts"] == [
        str(event_path),
        str(memoryos_evidence),
    ]


def test_release_evidence_pack_converts_memoryos_trace_into_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    trace = _write_memoryos_trace(tmp_path / "memoryos" / "memoryos-trace.json")

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-memoryos-live-gate",
        memoryos_live_trace=trace,
    )

    gate_path = artifacts / "live-memoryos.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "live-memoryos"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "live_service_proof"
    assert gate["artifacts"] == [str(trace)]
    assert pack["source_reports"]["memoryos_live_gate"] == str(gate_path)
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["decision"] == "blocked"


def test_release_evidence_pack_converts_real_provider_runtime_into_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    runtime = _write_real_provider_runtime(
        tmp_path / "provider" / "real-provider-runtime.json"
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-real-provider-gate",
        real_provider_runtime=runtime,
    )

    gate_path = artifacts / "real-provider-runtime.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "real-provider-runtime"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"
    assert gate["artifacts"] == [str(runtime)]
    assert pack["source_reports"]["real_provider_runtime_gate"] == str(gate_path)
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["decision"] == "blocked"


def test_release_evidence_pack_converts_natural_deliberation_into_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")
    runtime = _write_god_runtime(tmp_path / "transcript" / "god-runtime.json")

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-natural-deliberation-gate",
        natural_deliberation_transcript=transcript,
        natural_deliberation_god_runtime=runtime,
    )

    gate_path = artifacts / "natural-deliberation.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "natural-god-deliberation"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"
    assert gate["artifacts"] == [str(transcript), str(runtime)]
    assert pack["source_reports"]["natural_deliberation_gate"] == str(gate_path)
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["decision"] == "blocked"


def test_release_evidence_pack_converts_github_truth_into_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    truth = _write_github_server_truth(tmp_path / "github" / "github-truth.json")

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-github-server-truth",
        github_server_truth=truth,
        github_base_branch="main",
        github_expected_head_sha="head-pack-1",
    )

    gate_path = artifacts / "github-server-truth.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "github-server-truth"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_enforcement_proof"
    assert gate["artifacts"] == [str(truth)]
    assert gate["source_refs"] == [
        "github:pr:43",
        "github:branch:main",
        "github:head:head-pack-1",
        "github:expected-head:head-pack-1",
    ]
    assert pack["source_reports"]["github_server_truth_gate"] == str(gate_path)
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["decision"] == "blocked"


def test_release_evidence_pack_keeps_stale_github_truth_as_manual_gap(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    truth = _write_github_server_truth(
        tmp_path / "github" / "github-truth.json",
        head_sha="stale-head",
        expected_head_sha="fresh-head",
        head_sha_matches_expected=False,
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "pack.json",
        github_server_truth=truth,
        github_expected_head_sha="fresh-head",
    )

    gate = json.loads((artifacts / "github-server-truth.json").read_text())
    assert gate["status"] == "manual_gap"
    assert gate["proof_level"] == "manual_gap"
    assert "does not match expected current head fresh-head" in gate["summary"]
    assert pack["release_readiness_decision"] == "blocked"
    assert pack["blockers"][0]["gate_id"] == "github-server-truth"


def test_release_evidence_pack_converts_internal_review_into_release_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    review = _write_internal_review(tmp_path / "review" / "internal-review.json")

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "pack.json",
        internal_review_artifact=review,
        internal_review_expected_head_sha="head-pack-1",
    )

    gate_path = artifacts / "internal-review.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "internal-review"
    assert gate["kind"] == "internal_review"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "internal_review_proof"
    assert gate["artifacts"] == [str(review)]
    assert gate["source_refs"] == [
        "github:pr:43",
        "internal_review:review-pr43-head-pack-1",
    ]
    assert pack["source_reports"]["internal_review_gate"] == str(gate_path)
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_keeps_stale_internal_review_as_blocker(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    review = _write_internal_review(
        tmp_path / "review" / "internal-review.json",
        reviewed_head_sha="old-head",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "pack.json",
        internal_review_artifact=review,
        internal_review_expected_head_sha="fresh-head",
    )

    gate = json.loads((artifacts / "internal-review.json").read_text())
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "reviewed_head_sha mismatch" in gate["summary"]
    assert pack["release_readiness_decision"] == "blocked"
    assert pack["blockers"][0]["gate_id"] == "internal-review"


def test_release_evidence_pack_requires_runtime_for_natural_release_gate(
    tmp_path: Path,
) -> None:
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            natural_deliberation_transcript=transcript,
        )
    except ValueError as exc:
        assert "natural_deliberation_god_runtime is required" in str(exc)
    else:
        raise AssertionError("expected natural release gate runtime to be required")


def test_release_evidence_pack_converts_deliberation_transcript_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")
    runtime = _write_god_runtime(tmp_path / "transcript" / "god-runtime.json")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-natural-transcript",
        deliberation_transcript=transcript,
        god_runtime_artifact=runtime,
    )

    transcript_evidence = (
        output.parent / "deliberation-transcript-production-evidence.json"
    )
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert transcript_evidence.exists()
    assert pack["source_reports"]["deliberation_transcript_evidence"] == str(
        transcript_evidence
    )
    assert sections["deliberation_transcript"]["status"] == "ok"
    assert sections["deliberation_transcript"]["proof_level"] == "real_provider_proof"
    assert sections["deliberation_transcript"]["source_authority"] == (
        "operator_transcript_v1"
    )
    assert sections["deliberation_transcript"]["artifacts"] == [
        str(transcript),
        str(runtime),
        str(transcript_evidence),
    ]


def test_release_evidence_pack_converts_frozen_blueprint_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    blueprint = _write_blueprint(
        tmp_path / "blueprint" / "mission-blueprint.json",
        status=MissionBlueprintStatus.FROZEN,
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-frozen-blueprint",
        frozen_blueprint=blueprint,
    )

    blueprint_evidence = output.parent / "frozen-blueprint-production-evidence.json"
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert blueprint_evidence.exists()
    assert pack["source_reports"]["frozen_blueprint_evidence"] == str(
        blueprint_evidence
    )
    assert sections["frozen_blueprint"]["status"] == "ok"
    assert sections["frozen_blueprint"]["proof_level"] == "contract_proof"
    assert sections["frozen_blueprint"]["source_authority"] == "mission_blueprint_v1"
    assert sections["frozen_blueprint"]["artifacts"] == [
        str(blueprint),
        str(blueprint_evidence),
    ]


def test_release_evidence_pack_converts_feature_contracts_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    contract = _write_feature_contract(
        tmp_path / "feature" / "feature-owner-contract.json"
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-feature-lineage",
        feature_contracts=(contract,),
    )

    feature_evidence = output.parent / "feature-lineage-production-evidence.json"
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert feature_evidence.exists()
    assert pack["source_reports"]["feature_lineage_evidence"] == str(feature_evidence)
    assert sections["feature_lineage"]["status"] == "ok"
    assert sections["feature_lineage"]["proof_level"] == "contract_proof"
    assert sections["feature_lineage"]["source_authority"] == (
        "feature_owner_execution_contract"
    )
    assert sections["feature_lineage"]["artifacts"] == [
        str(contract),
        str(feature_evidence),
    ]


def test_release_evidence_pack_rejects_ambiguous_supervisor_sources(
    tmp_path: Path,
) -> None:
    supervisor = tmp_path / "supervisor-production-evidence.json"
    snapshot = _write_supervisor_snapshot(
        tmp_path / "supervisor",
        run_id="ambiguous-supervisor",
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            supervisor_snapshot=snapshot,
            section_artifacts={"supervisor": supervisor},
        )
    except ValueError as exc:
        assert "supervisor evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous supervisor source to be rejected")


def test_release_evidence_pack_rejects_ambiguous_memoryos_governance_sources(
    tmp_path: Path,
) -> None:
    event_path = _write_memoryos_event(tmp_path / "events" / "blueprint-event.json")
    memoryos_governance = tmp_path / "memoryos-governance-production-evidence.json"
    _write_section_evidence(
        memoryos_governance,
        section_id="memory_governance",
        status="ok",
        proof_level="contract_proof",
        source_authority="memoryos_governance_policy",
        source_refs=["memory-governance:plan:blueprint-event"],
        summary="MemoryOS governance captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            section_artifacts={"memory_governance": memoryos_governance},
            memoryos_writeback_events=(event_path,),
        )
    except ValueError as exc:
        assert "memory_governance evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous memory_governance source to be rejected")


def test_release_evidence_pack_rejects_ambiguous_deliberation_transcript_sources(
    tmp_path: Path,
) -> None:
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")
    deliberation = tmp_path / "deliberation-transcript-production-evidence.json"
    _write_section_evidence(
        deliberation,
        section_id="deliberation_transcript",
        status="ok",
        proof_level="real_provider_proof",
        source_authority="operator_transcript_v1",
        source_refs=["memory://conversation/conv-prod-1/transcript"],
        summary="Natural deliberation captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            section_artifacts={"deliberation_transcript": deliberation},
            deliberation_transcript=transcript,
        )
    except ValueError as exc:
        assert "deliberation_transcript evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError(
            "expected ambiguous deliberation_transcript source to be rejected"
        )


def test_release_evidence_pack_rejects_ambiguous_frozen_blueprint_sources(
    tmp_path: Path,
) -> None:
    blueprint = _write_blueprint(
        tmp_path / "blueprint" / "mission-blueprint.json",
        status=MissionBlueprintStatus.FROZEN,
    )
    blueprint_evidence = tmp_path / "frozen-blueprint-production-evidence.json"
    _write_section_evidence(
        blueprint_evidence,
        section_id="frozen_blueprint",
        status="ok",
        proof_level="contract_proof",
        source_authority="mission_blueprint_v1",
        source_refs=["mission_blueprint:bp-overnight:r3"],
        summary="Frozen blueprint captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            section_artifacts={"frozen_blueprint": blueprint_evidence},
            frozen_blueprint=blueprint,
        )
    except ValueError as exc:
        assert "frozen_blueprint evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous frozen_blueprint source to be rejected")


def test_release_evidence_pack_rejects_ambiguous_feature_lineage_sources(
    tmp_path: Path,
) -> None:
    contract = _write_feature_contract(
        tmp_path / "feature" / "feature-owner-contract.json"
    )
    feature_evidence = tmp_path / "feature-lineage-production-evidence.json"
    _write_section_evidence(
        feature_evidence,
        section_id="feature_lineage",
        status="ok",
        proof_level="contract_proof",
        source_authority="feature_owner_execution_contract",
        source_refs=["feature-owner:feature-replay-pack"],
        summary="Feature lineage captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            section_artifacts={"feature_lineage": feature_evidence},
            feature_contracts=(contract,),
        )
    except ValueError as exc:
        assert "feature_lineage evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous feature_lineage source to be rejected")


def test_release_evidence_pack_marks_contaminated_audit_as_terminal(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            status="ok",
            proof_level="real_provider_proof",
            summary="fake provider emitted stdout_fallback trace",
            source_refs=["provider:codex", "transport:stdout_fallback"],
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "evidence-pack.json",
    )

    assert pack["decision"] == "contaminated"
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "contaminated"
    assert pack["finding_count"] == 1
    assert pack["findings"][0]["code"] == "fake_marker_in_production_proof"


def test_release_evidence_pack_reports_not_evaluated_without_artifacts(
    tmp_path: Path,
) -> None:
    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "missing",
        output_path=tmp_path / "evidence-pack.json",
    )

    assert pack["decision"] == "not_evaluated"
    assert pack["artifact_count"] == 0
    assert pack["blockers"] == []
    assert pack["findings"] == []


def test_release_evidence_pack_cli_writes_pack(tmp_path: Path) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    _write_json(
        artifacts / "provider.json",
        _gate(
            gate_id="provider-soak",
            kind="real_provider",
            status="manual_gap",
            proof_level="manual_gap",
            summary="Provider soak was not supplied.",
        ),
    )

    assert main(["--artifacts-dir", str(artifacts), "--output", str(output)]) == 0
    pack = json.loads(output.read_text(encoding="utf-8"))
    assert pack["decision"] == "blocked"
    assert pack["blocker_count"] == 1
    assert pack["overnight_replay_bundle"] == str(
        output.parent / "overnight-replay-bundle.json"
    )


def test_release_evidence_pack_cli_accepts_replay_section_artifacts(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    supervisor = tmp_path / "supervisor.json"
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor captured.",
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--section-artifact",
                f"supervisor={supervisor}",
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["overnight_replay_decision"] == "blocked"
    assert replay["run_id"] == "overnight-cli-pack"
    assert sections["supervisor"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_supervisor_snapshot(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    snapshot = _write_supervisor_snapshot(
        tmp_path / "supervisor",
        run_id="overnight-cli-pack",
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--supervisor-snapshot",
                str(snapshot),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["overnight_supervisor_evidence"] == str(
        output.parent / "supervisor-production-evidence.json"
    )
    assert sections["supervisor"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_memoryos_writeback_event(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    event_path = _write_memoryos_event(tmp_path / "events" / "blueprint-event.json")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--memoryos-writeback-event",
                str(event_path),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["memoryos_governance_evidence"] == str(
        output.parent / "memoryos-governance-production-evidence.json"
    )
    assert sections["memory_governance"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_raw_live_gate_inputs(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    trace = _write_memoryos_trace(tmp_path / "memoryos" / "memoryos-trace.json")
    runtime = _write_real_provider_runtime(
        tmp_path / "provider" / "real-provider-runtime.json"
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--memoryos-live-trace",
                str(trace),
                "--real-provider-runtime",
                str(runtime),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    memoryos_gate = json.loads(
        (artifacts / "live-memoryos.json").read_text(encoding="utf-8")
    )
    provider_gate = json.loads(
        (artifacts / "real-provider-runtime.json").read_text(encoding="utf-8")
    )
    assert memoryos_gate["status"] == "ok"
    assert provider_gate["status"] == "ok"
    assert pack["source_reports"]["memoryos_live_gate"] == str(
        artifacts / "live-memoryos.json"
    )
    assert pack["source_reports"]["real_provider_runtime_gate"] == str(
        artifacts / "real-provider-runtime.json"
    )
    assert pack["artifact_count"] == 2
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_cli_accepts_natural_release_gate_input(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")
    runtime = _write_god_runtime(tmp_path / "transcript" / "god-runtime.json")

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--natural-deliberation-transcript",
                str(transcript),
                "--natural-deliberation-god-runtime",
                str(runtime),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    gate = json.loads(
        (artifacts / "natural-deliberation.json").read_text(encoding="utf-8")
    )
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"
    assert pack["source_reports"]["natural_deliberation_gate"] == str(
        artifacts / "natural-deliberation.json"
    )
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_cli_accepts_github_server_truth_input(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    truth = _write_github_server_truth(tmp_path / "github" / "github-truth.json")

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--github-server-truth",
                str(truth),
                "--github-base-branch",
                "main",
                "--github-expected-head-sha",
                "head-pack-1",
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    gate = json.loads(
        (artifacts / "github-server-truth.json").read_text(encoding="utf-8")
    )
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_enforcement_proof"
    assert pack["source_reports"]["github_server_truth_gate"] == str(
        artifacts / "github-server-truth.json"
    )
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_cli_accepts_internal_review_input(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    review = _write_internal_review(tmp_path / "review" / "internal-review.json")

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--internal-review-artifact",
                str(review),
                "--internal-review-expected-head-sha",
                "head-pack-1",
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    gate = json.loads((artifacts / "internal-review.json").read_text(encoding="utf-8"))
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "internal_review_proof"
    assert pack["source_reports"]["internal_review_gate"] == str(
        artifacts / "internal-review.json"
    )
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_cli_accepts_deliberation_transcript(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    transcript = _write_transcript(tmp_path / "transcript" / "natural-transcript.json")
    runtime = _write_god_runtime(tmp_path / "transcript" / "god-runtime.json")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--deliberation-transcript",
                str(transcript),
                "--god-runtime",
                str(runtime),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["deliberation_transcript_evidence"] == str(
        output.parent / "deliberation-transcript-production-evidence.json"
    )
    assert sections["deliberation_transcript"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_frozen_blueprint(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    blueprint = _write_blueprint(
        tmp_path / "blueprint" / "mission-blueprint.json",
        status=MissionBlueprintStatus.FROZEN,
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--frozen-blueprint",
                str(blueprint),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["frozen_blueprint_evidence"] == str(
        output.parent / "frozen-blueprint-production-evidence.json"
    )
    assert sections["frozen_blueprint"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_feature_contract(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    contract = _write_feature_contract(
        tmp_path / "feature" / "feature-owner-contract.json"
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--feature-contract",
                str(contract),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["feature_lineage_evidence"] == str(
        output.parent / "feature-lineage-production-evidence.json"
    )
    assert sections["feature_lineage"]["status"] == "ok"


def test_release_evidence_pack_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-release-evidence-pack"]
        == "xmuse.release_evidence_pack:main"
    )
