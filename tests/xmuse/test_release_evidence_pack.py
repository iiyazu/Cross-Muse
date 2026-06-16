from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.integrations.memoryos_events import MemoryOSWritebackEvent
from xmuse_core.integrations.memoryos_namespace import conversation_namespace
from xmuse_core.platform.god_room_review_chain_proof import (
    GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS,
    capture_god_room_review_chain_proof,
)
from xmuse_core.platform.local_execution_candidate import (
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
)
from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
from xmuse_core.platform.runner_recovery_proof import (
    build_runner_recovery_proof_lineage,
)
from xmuse_core.structuring.feature_owner_contract import (
    build_feature_owner_execution_contract,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    compile_blueprint_freeze_from_god_room_events,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _attach_review_closure_candidate_lineage(
    *,
    root: Path,
    review_closure: Path,
    candidate_ref: str,
    conversation_id: str,
    graph_id: str = "graph-runtime",
    lane_id: str = "lane-runtime-evidence-patch",
) -> None:
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["cited_candidate_artifact_lineage"] = [
        load_local_execution_candidate_lineage(
            root=root,
            artifact_ref=candidate_ref,
            lane_id=lane_id,
            graph_id=graph_id,
            conversation_id=conversation_id,
        )
    ]
    _write_json(review_closure, payload)


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


def _write_local_execution_candidate(
    path: Path,
    *,
    conversation_id: str,
    graph_id: str = "graph-runtime",
    lane_id: str = "lane-runtime-evidence-patch",
    source_event_lineage: list[dict[str, object]] | None = None,
) -> Path:
    graph_status_source_event_lineage = source_event_lineage or []
    root = path.parent.parent.parent
    candidate_ref = str(path.relative_to(root))
    _write_json(
        path,
        {
            "schema_version": "xmuse.local_execution_candidate.v1",
            "candidate_id": f"candidate-{lane_id}",
            "source_authority": "local_execution_candidate_capture",
            "producer": "platform_runner_dispatch",
            "conversation_id": conversation_id,
            "proof_level": "local_runtime_proof",
            "status": "candidate_only",
            "candidate_truth_status": "candidate_only",
            "graph_id": graph_id,
            "graph_set_id": f"{graph_id}-graph-set",
            "feature_graph_id": f"{graph_id}-feature-runtime",
            "feature_graph_status_id": f"fgs:{graph_id}-feature-runtime:reviewing",
            "feature_graph_status": "reviewing",
            "graph_status_source_authority": "feature_graph_status_store",
            "graph_status_lineage": {
                "source_authority": "feature_graph_status_store",
                "graph_set_id": f"{graph_id}-graph-set",
                "feature_graph_id": f"{graph_id}-feature-runtime",
                "status_id": f"fgs:{graph_id}-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": [lane_id],
                "source_event_lineage": graph_status_source_event_lineage,
            },
            "lane_id": lane_id,
            "run_id": "platform-runner:run-1",
            "worker_id": "platform-runner",
            "runner_session_id": "runner-session-1",
            "runner_session_ref": "work/runner_sessions/runner-session-1.json",
            "source_refs": ["worker-candidate:patch-reviewed"],
            "output_refs": [str(path)],
            "changed_file_refs": [],
            "verification_refs": [
                "uv run pytest tests/xmuse/test_release_evidence_pack.py -q"
            ],
            "manual_gaps": [
                "review_truth_not_proven",
                "server_truth_not_proven",
                "github_truth_not_checked",
                "live_memoryos_trace_not_proven",
            ],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )
    _write_json(
        root / "work" / "runner_sessions" / "runner-session-1.json",
        {
            "schema_version": "xmuse.runner_session.v1",
            "source_authority": "platform_runner_session_boundary",
            "session_id": "runner-session-1",
            "run_id": "platform-runner:run-1",
            "runner_id": "platform-runner",
            "status": "session_completed",
            "proof_level": "local_runtime_proof",
            "started_at": "2026-06-15T00:00:00Z",
            "completed_at": "2026-06-15T00:01:00Z",
            "graph_id": graph_id,
            "resolution_id": "resolution-runtime",
            "writer_lease_id": "lease-runtime",
            "candidate_artifact_refs": [candidate_ref],
            "candidate_lane_ids": [lane_id],
            "candidate_count": 1,
            "manual_gaps": [
                "review_truth_not_proven",
                "server_truth_not_proven",
                "github_truth_not_checked",
                "live_memoryos_trace_not_proven",
                "overnight_safe_recovery_not_proven",
            ],
            "forbidden_claims": [
                "runner_session_is_review_truth",
                "runner_session_is_server_truth",
                "runner_session_is_live_invocation_proof",
                "runner_session_is_graph_wide_closure",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        },
    )
    return path


def _write_graph_authority(
    *,
    root: Path,
    conversation_id: str,
    source_event_lineage: list[dict[str, object]],
    graph_id: str = "graph-runtime",
    lane_id: str = "lane-runtime-evidence-patch",
) -> None:
    graph_set_id = f"{graph_id}-graph-set"
    feature_graph_id = f"{graph_id}-feature-runtime"
    _write_json(
        root / "graph_sets" / f"{conversation_id}--{graph_set_id}.json",
        {
            "id": graph_set_id,
            "version": 1,
            "source_refs": [f"lane_dag:{graph_id}"],
            "source_event_lineage": source_event_lineage,
            "feature_plan": {
                "id": f"{graph_id}-feature-plan",
                "conversation_id": conversation_id,
                "resolution_id": "resolution-runtime",
                "version": 1,
                "features": [
                    {
                        "feature_id": "feature-runtime",
                        "title": "Runtime evidence",
                        "goal": "Review runtime evidence.",
                        "acceptance_criteria": ["Review candidate evidence."],
                        "dependencies": [],
                        "graph_id": feature_graph_id,
                        "expected_touched_areas": [],
                        "blueprint_refs": ["blueprint:runtime"],
                    }
                ],
            },
            "graphs": [
                {
                    "id": feature_graph_id,
                    "conversation_id": conversation_id,
                    "resolution_id": "resolution-runtime",
                    "version": 1,
                    "status": "planned",
                    "source_refs": [f"lane_dag:{graph_id}"],
                    "lanes": [
                        {
                            "feature_id": lane_id,
                            "title": lane_id,
                            "prompt": f"Execute {lane_id}",
                            "task_type": "execute",
                            "priority": 0,
                            "capabilities": ["code"],
                            "depends_on": [],
                            "gate_profile": None,
                            "gate_profiles": [],
                            "source_lane_id": None,
                            "feature_group": "feature-runtime",
                            "blueprint_refs": ["blueprint:runtime"],
                            "acceptance_criteria": ["Review candidate evidence."],
                            "expected_touched_areas": [],
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        root / "feature_graph_statuses.json",
        {
            "schema_version": "xmuse.feature_graph_statuses.v1",
            "statuses": [
                {
                    "status_id": f"fgs:{feature_graph_id}:merged",
                    "conversation_id": conversation_id,
                    "planning_run_id": "planning-runtime",
                    "graph_set_id": graph_set_id,
                    "graph_set_version": 1,
                    "feature_plan_id": f"{graph_id}-feature-plan",
                    "feature_plan_version": 1,
                    "feature_id": "feature-runtime",
                    "feature_graph_id": feature_graph_id,
                    "blueprint_proof_level": "contract_proof",
                    "source_event_lineage": source_event_lineage,
                    "status": "merged",
                    "ready_lane_ids": [],
                    "active_lane_ids": [],
                    "completed_lane_ids": [lane_id],
                    "blocked_lane_ids": [],
                    "projection_lane_ids": [],
                    "feature_lanes_projection_ref": None,
                    "provider_session_binding_degradations": [],
                    "updated_at": "2026-06-15T00:00:00Z",
                }
            ],
            "events": [],
        },
    )


def _write_review_chain_proof_artifact(
    path: Path,
    *,
    server_truth_status: str = "not_server_truth",
    forbidden_claims: list[str] | None = None,
) -> Path:
    claims = forbidden_claims or [
        "worker_output_is_review_truth",
        "end_to_end_execution_review_closure",
        "ready_to_merge",
        "pr_merged",
        "github_review_truth",
        "live_memoryos",
        "server_side_truth",
        "overnight_readiness",
    ]
    _write_json(
        path,
        {
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "source_authority": (
                "god_room_lane_review_closure_artifact+"
                "local_execution_candidate_lineage+"
                "shared_god_room_review_closure_handoff_gate"
            ),
            "status": "chain_ready",
            "proof_level": "contract_proof",
            "server_truth_status": server_truth_status,
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "review_closure_artifact": "review-closure.json",
            "runner_recovery_proof_lineage": {
                "status": "target_lane_recovery_blocked",
                "proof_level": "local_runtime_proof",
                "artifact_ref": "reports/runner-recovery-proof.json",
                "source_refs": ["reports/lane-recovery/lane-runtime-evidence.json"],
            },
            "release_evidence_handoff": {
                "review_closure_artifact_gate_ready": True,
                "review_closure_candidate_artifact_refs": [
                    "artifacts/lane-runtime-evidence-patch/result.json"
                ],
                "review_closure_candidate_artifact_ref_count": 1,
            },
            "manual_gaps": [
                "live_memoryos_trace_not_proven",
                "github_truth_not_checked",
                "server_truth_not_proven",
                "release_evidence_export_not_attempted",
            ],
            "forbidden_claims": claims,
        },
    )
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
        "pull_request_state": "open",
        "draft": True,
        "mergeable": True,
        "mergeable_state": "clean",
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
        "review_scope": "full_pr_current_head",
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


def _write_production_baseline(path: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": "xmuse.production_baseline.v1",
        "stage_id": "S0",
        "action": "production_baseline_capture",
        "status": "blocked",
        "proof_level": "contract_proof",
        "source_authority": "local_repository_and_environment",
        "generated_at": "2026-06-12T00:00:00Z",
        "repo_root": "/workspace/xmuse",
        "git": {
            "head_sha": "head-pack-1",
            "branch": "vision-closure-deliberation-tui",
            "dirty": False,
            "status_returncode": 0,
            "dirty_entries": [],
        },
        "package_boundary": {
            "xmuse_init_absent": True,
            "status": "ok",
            "source_refs": ["path:xmuse/__init__.py"],
            "blockers": [],
        },
        "env_keys_present": ["XMUSE_GITHUB_TRUTH_REPO"],
        "live_resources": {
            "github": {
                "configured": True,
                "available": True,
                "blockers": ["github_server_truth_capture_pending"],
            },
            "memoryos_lite": {
                "configured": False,
                "available": False,
                "blockers": ["memoryos_lite_live_environment_missing"],
            },
        },
        "blockers": [
            "github_server_truth_capture_pending",
            "memoryos_lite_live_environment_missing",
        ],
        "owner": "operator",
        "next_action": "Resolve or record S0 blockers.",
    }
    payload.update(overrides)
    _write_json(path, payload)
    return path


def _write_goal_stage_result(
    path: Path,
    *,
    stage_id: str = "S1",
    status: str = "ok",
) -> Path:
    payload = {
        "stage_id": stage_id,
        "status": status,
        "engine": "opencode",
        "issues": [],
        "review_decision": "pass" if status == "ok" else status,
        "retry_hint": None,
        "evidence_dir": str(path.parent / f"{path.name}.evidence"),
        "agent_output_path": str(path),
        "command": [
            "opencode",
            "run",
            "--model",
            "opencode-go/deepseek-v4-flash",
            "--variant",
            "max",
        ],
        "agent_stdout_path": str(
            path.parent / f"{path.name}.evidence" / "engine_output.txt"
        ),
        "returncode": 0 if status == "ok" else 2,
        "attempt": 1,
        "timestamp_utc": "2026-06-12T00:00:00Z",
    }
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
            attempted_command="uv run xmuse-real-provider-runtime-gate-capture",
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
    assert pack["proof_level_summary"] == {
        "manual_gap": 1,
        "server_side_enforcement_proof": 1,
    }
    assert pack["release_gates"] == [
        {
            "gate_id": "github-server-truth",
            "kind": "github_server_truth",
            "status": "ok",
            "proof_level": "server_side_enforcement_proof",
            "configured": True,
            "required": True,
            "owner": "operator",
            "summary": "github-server-truth evidence",
            "attempted_command": None,
            "next_action": None,
            "source_ref_count": 2,
            "artifact_count": 1,
        },
        {
            "gate_id": "real-provider-runtime",
            "kind": "real_provider",
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "configured": True,
            "required": True,
            "owner": "operator",
            "summary": "Ray/Codex runtime was not started.",
            "attempted_command": "uv run xmuse-real-provider-runtime-gate-capture",
            "next_action": "Start the configured production provider bundle.",
            "source_ref_count": 1,
            "artifact_count": 1,
        },
    ]
    assert pack["recovery_queue_count"] == len(pack["recovery_queue"])
    assert {
        "source": "release_readiness",
        "kind": "release_gate",
        "id": "real-provider-runtime",
        "owner": "operator",
        "reason": (
            "real-provider-runtime status is manual_gap: "
            "Ray/Codex runtime was not started."
        ),
        "next_action": "Start the configured production provider bundle.",
        "artifact": str(readiness_output),
    } in pack["recovery_queue"]
    assert {
        "source": "overnight_replay_bundle",
        "kind": "replay_section",
        "id": "stage_evidence",
        "owner": "operator",
        "reason": "stage_evidence replay evidence was not attached.",
        "next_action": "Attach or capture stage_evidence production evidence.",
        "artifact": str(replay_output),
    } in pack["recovery_queue"]
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


def test_release_evidence_pack_attaches_production_baseline_truth_map(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    baseline = _write_production_baseline(
        tmp_path / "baseline" / "production-baseline.json"
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
        run_id="pack-production-baseline",
        production_baseline=baseline,
    )

    assert pack["source_reports"]["production_baseline"] == str(baseline)
    assert pack["production_baseline"] == {
        "artifact": str(baseline),
        "schema_version": "xmuse.production_baseline.v1",
        "status": "blocked",
        "proof_level": "contract_proof",
        "head_sha": "head-pack-1",
        "dirty": False,
        "xmuse_init_absent": True,
        "blockers": [
            "github_server_truth_capture_pending",
            "memoryos_lite_live_environment_missing",
        ],
    }
    assert {
        "source": "production_baseline",
        "kind": "production_resource",
        "id": "github",
        "owner": "operator",
        "reason": "github_server_truth_capture_pending",
        "next_action": "Resolve or record S0 blockers.",
        "artifact": str(baseline),
    } in pack["recovery_queue"]
    assert {
        "source": "production_baseline",
        "kind": "production_resource",
        "id": "memoryos_lite",
        "owner": "operator",
        "reason": "memoryos_lite_live_environment_missing",
        "next_action": "Resolve or record S0 blockers.",
        "artifact": str(baseline),
    } in pack["recovery_queue"]
    assert pack["decision"] == "blocked"
    assert pack["release_readiness_decision"] == "ready"


def test_release_evidence_pack_converts_goal_stage_results_to_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    stage_result = _write_goal_stage_result(tmp_path / "goal" / "S1.result.json")
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
        run_id="pack-stage-evidence",
        goal_stage_results=(stage_result,),
    )

    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert "stage_evidence" in sections
    assert sections["stage_evidence"]["status"] == "ok"
    assert sections["stage_evidence"]["source_authority"] == "goal_stage_harness"
    assert sections["stage_evidence"]["source_refs"] == [
        "goal_run:pack-stage-evidence",
        "goal_stage:S1",
        f"goal_stage_result:{stage_result}",
    ]
    assert pack["source_reports"]["goal_stage_evidence"] == str(
        output.parent / "goal-stage-production-evidence.json"
    )


def test_release_evidence_pack_rejects_invalid_production_baseline_schema(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    _write_json(baseline, {"schema_version": "xmuse.production_evidence.v1"})

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            production_baseline=baseline,
        )
    except ValueError as exc:
        assert "production baseline artifact has unsupported schema" in str(exc)
    else:
        raise AssertionError("expected invalid production baseline schema to fail")


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
    assert pack["real_provider_runtime"] == {
        "authority": "real_provider_runtime_release_gate",
        "status": "ok",
        "proof_level": "real_provider_proof",
        "gate_artifact": str(gate_path),
        "runtime_artifact": str(runtime),
        "run_id": "real-provider-pack-run",
        "conversation_id": "conv-prod-1",
        "provider_id": "codex",
        "runtime_backend": "ray",
        "transport": "codex-app-server",
        "provider_session_id": "codex-thread-prod-1",
        "mcp_writeback": True,
        "provider_session_reused": True,
        "fresh_provider_session_id": "codex-thread-prod-1",
        "resumed_provider_session_id": "codex-thread-prod-1",
        "turn_count": 2,
        "phases": ["fresh", "resume"],
        "mcp_writeback_turn_count": 2,
        "degraded_turn_count": 0,
        "blocker_count": 0,
    }
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
    assert pack["github_truth"] == {
        "authority": "github_truth_release_gate",
        "status": "ok",
        "proof_level": "server_side_enforcement_proof",
        "gate_artifact": str(gate_path),
        "truth_artifact": str(truth),
        "repo": "iiyazu/Cross-Muse",
        "pull_request_number": 43,
        "pull_request_state": "open",
        "draft": True,
        "mergeable": True,
        "mergeable_state": "clean",
        "head_sha": "head-pack-1",
        "expected_head_sha": "head-pack-1",
        "head_sha_matches_expected": True,
        "required_check_count": 3,
        "check_run_count": 3,
        "expected_source_app": "github-actions",
        "server_enforcement": "branch_protection",
        "review_truth": "missing",
        "merge_truth": "missing",
        "merged": False,
        "can_emit_pr_merged": False,
        "gap_reason": "missing server-side truth: review_truth, merge_truth",
        "capture_mode": "opt_in_read_only_gh_api",
    }
    assert pack["artifact_count"] == 1
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["decision"] == "blocked"


def test_release_evidence_pack_recomputes_github_merge_truth(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    truth = _write_github_server_truth(
        tmp_path / "github" / "github-truth.json",
        can_emit_pr_merged=True,
        merged=True,
        merge_commit_sha="raw-merge-claim",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-github-server-truth",
        github_server_truth=truth,
        github_base_branch="main",
        github_expected_head_sha="head-pack-1",
    )

    gate = json.loads((artifacts / "github-server-truth.json").read_text())
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_enforcement_proof"
    assert gate["next_action"] == (
        "Resolve remaining GitHub truth gap before pr_merged: "
        "missing server-side truth: review_truth, merge_truth."
    )
    assert pack["github_truth"]["merge_truth"] == "missing"
    assert pack["github_truth"]["merged"] is False
    assert pack["github_truth"]["can_emit_pr_merged"] is False


def test_release_evidence_pack_accepts_server_side_merge_truth(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    truth = _write_github_server_truth(
        tmp_path / "github" / "github-truth.json",
        proof_level="server_side_merge_proof",
        workflow_run_id=211,
        check_suite_id=210,
        review_event_id=789,
        reviewer_login="reviewer",
        merge_commit_sha="merge-sha-1",
        merged_at="2026-06-14T15:00:00Z",
        merge_event_id=456,
        gap_reason=None,
        can_emit_pr_merged=True,
        merged=True,
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-github-server-truth",
        github_server_truth=truth,
        github_base_branch="main",
        github_expected_head_sha="head-pack-1",
    )

    gate = json.loads((artifacts / "github-server-truth.json").read_text())
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_merge_proof"
    assert gate["next_action"] == "No GitHub server-truth action required."
    assert pack["github_truth"]["proof_level"] == "server_side_merge_proof"
    assert pack["github_truth"]["review_truth"] == "github_review"
    assert pack["github_truth"]["merge_truth"] == "pr_merged"
    assert pack["github_truth"]["merged"] is True
    assert pack["github_truth"]["can_emit_pr_merged"] is True


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
        "internal_review_scope:full_pr_current_head",
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


def test_release_evidence_pack_can_require_missing_internal_review_as_blocker(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "pack.json",
        internal_review_expected_head_sha="fresh-head",
    )

    gate_path = artifacts / "internal-review.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "internal-review"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "Internal review artifact does not exist" in gate["summary"]
    assert gate["artifacts"] == [str(artifacts / "internal-review-input.json")]
    assert pack["source_reports"]["internal_review_gate"] == str(gate_path)
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


def test_release_evidence_pack_converts_god_room_runtime_closure_into_replay_section(
    tmp_path: Path,
) -> None:
    participants = tmp_path / "god-room-participants.json"
    _write_json(
        participants,
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                    cli_id="codex",
                ).model_dump(mode="json"),
                GodRoomParticipant(
                    participant_id="part-review",
                    god_id="god-review",
                    cli_id="opencode",
                ).model_dump(mode="json"),
            ]
        },
    )
    events = [
        _god_room_event("evt-propose"),
        _god_room_event(
            "evt-review-provider-speak",
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-propose",
        ),
        _god_room_event(
            "evt-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-review-provider-speak",
            payload={
                "freeze_target_ref": "blueprint:bp-runtime:1",
                "goal": "Close runtime evidence.",
                "scope": ["release evidence pack"],
                "acceptance_contracts": ["Runtime closure is indexed."],
            },
        ),
    ]
    events_path = tmp_path / "god-room-events.json"
    _write_json(
        events_path,
        {"events": [event.model_dump(mode="json") for event in events]},
    )
    freeze = compile_blueprint_freeze_from_god_room_events(
        blueprint_id="bp-runtime",
        revision=1,
        events=events,
    )
    freeze_path = tmp_path / "god-room-blueprint-freeze.json"
    _write_json(freeze_path, freeze.model_dump(mode="json"))
    lane_dag = tmp_path / "lane-dag.json"
    _write_json(
        lane_dag,
        {
            "blueprint_ref": "blueprint:bp-runtime:1",
            "source_event_lineage": [
                {
                    "event_id": "evt-review-provider-speak",
                    "event_type": "speak",
                    "participant_id": "part-review",
                    "god_id": "god-review",
                    "proof_level": "opt_in_live_proof",
                    "source_authority": "god_room_event_store+provider_response",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "target_participant_ids": [],
                    "source_refs": [
                        "god-room-event:evt-propose",
                        "provider_response_artifact:"
                        "reports/provider-responses/provider-response-1.json",
                    ],
                    "forbidden_claims": ["natural_groupchat_closure"],
                }
            ],
            "lane_contracts": [
                {
                    "lane_id": "lane-runtime-evidence",
                    "feature_id": "feature-runtime",
                    "owner": "codex",
                    "required_checks": [
                        "uv run pytest tests/xmuse/test_release_evidence_pack.py -q"
                    ],
                }
            ],
            "recovery_decisions": [],
        },
    )
    trace = tmp_path / "memory-trace.json"
    _write_json(
        trace,
        {
            "trace_anchors": [
                {
                    "anchor_uri": "memory://conversation/conv-1/traces/trace-1",
                    "source_refs": ["blueprint:bp-runtime:1"],
                }
            ]
        },
    )
    tui = tmp_path / "tui-vision.json"
    _write_json(
        tui,
        {
            "execution": {"lane_contracts": [{"lane_id": "lane-runtime-evidence"}]},
            "memory": {"trace_anchors": [{"trace_id": "trace-1"}]},
        },
    )
    speaker_attempt = tmp_path / "speaker-attempt.json"
    _write_json(
        speaker_attempt,
        {
            "schema_version": "xmuse.god_room_speaker_attempt.v1",
            "status": "ready_for_provider_attempt",
            "proof_level": "contract_proof",
            "source_authority": (
                "god_room_event_store+selected_god_runtime_continuity"
            ),
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "selected_event_id": "evt-propose",
            "decision_reason": "round_robin",
            "target_participant_id": "part-review",
            "target_god_id": "god-review",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-review",
            "source_refs": [
                "god-room-event:evt-propose",
                "provider_session:provider-thread-review",
            ],
        },
    )
    speaker_response = tmp_path / "speaker-response.json"
    _write_json(
        speaker_response,
        {
            "schema_version": "xmuse.god_room_speaker_response.v1",
            "status": "speak_event_appended",
            "proof_level": "real_provider_proof",
            "source_authority": (
                "god_room_event_store+selected_god_runtime_continuity+"
                "provider_response"
            ),
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "selected_event_id": "evt-propose",
            "target_participant_id": "part-review",
            "target_god_id": "god-review",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-review",
            "provider_response_artifact_ref": (
                "reports/provider-responses/provider-response-1.json"
            ),
            "append_status": "created",
            "source_refs": [
                "god-room-event:evt-propose",
                "provider_session:provider-thread-review",
                "provider-run:codex:provider-response-1",
            ],
            "speaker_attempt": json.loads(speaker_attempt.read_text(encoding="utf-8")),
            "provider_response": {
                "schema_version": "xmuse.god_room_provider_speech_response.v1",
                "response_id": "provider-response-1",
                "status": "completed",
                "proof_level": "real_provider_proof",
                "target_participant_id": "part-review",
                "provider_profile_ref": "codex.god",
                "provider_session_id": "provider-thread-review",
                "content": "Review GOD responded.",
                "source_refs": ["provider-run:codex:provider-response-1"],
            },
            "speak_event": {
                "version": "xmuse.god_room_event.v1",
                "event_id": "evt-review-provider-speak",
                "room_id": "room-1",
                "conversation_id": "conv-1",
                "participant_id": "part-review",
                "god_id": "god-review",
                "actor_kind": "god",
                "event_type": "speak",
                "timestamp_utc": "2026-06-13T10:02:00Z",
                "content": "Review GOD responded.",
                "target_participant_ids": [],
                "causal_parent_id": "evt-propose",
                "source_refs": ["provider-run:codex:provider-response-1"],
                "cli_id": "codex",
                "provider_profile": "codex.god",
                "payload": {"body": "Review GOD responded."},
            },
        },
    )
    multi_turn_run = tmp_path / "multi-turn-provider-speech-run.json"
    _write_json(
        multi_turn_run,
        {
            "schema_version": "xmuse.god_room_multi_turn_provider_speech_run.v1",
            "status": "completed",
            "proof_level": "opt_in_live_proof",
            "source_authority": (
                "god_room_event_store+room_selected_god_binding+"
                "provider_invocation+provider_response_capture"
            ),
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "max_turns": 1,
            "turn_count": 1,
            "initial_after_event_id": "evt-propose",
            "final_after_event_id": "evt-review-provider-speak",
            "turns": [
                {
                    "turn_number": 1,
                    "after_event_id": "evt-propose",
                    "appended_event_id": "evt-review-provider-speak",
                    "artifacts": {
                        "provider_response": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "speaker_response": (
                            "reports/god_room_speaker_responses/"
                            "speaker-response-1.json"
                        ),
                    },
                    "speaker_response": {"status": "speak_event_appended"},
                    "provider_response": {"response_id": "provider-response-1"},
                }
            ],
            "manual_gaps": [
                "natural_multi_god_groupchat_not_proven",
                "peer_god_live_proof_not_proven",
            ],
            "forbidden_claims": [
                "peer_god_live_proof",
                "natural_groupchat_closure",
                "autonomous_provider_speech_closure",
                "ready_to_merge",
                "pr_merged",
                "provider_invocation_live_proof_beyond_returned_turn_artifacts",
            ],
        },
    )
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_local_execution_candidate(
        tmp_path / candidate_ref,
        conversation_id="conv-1",
        source_event_lineage=[
            {
                "event_id": "evt-review-provider-speak",
                "event_type": "speak",
                "participant_id": "part-review",
                "god_id": "god-review",
                "proof_level": "opt_in_live_proof",
                "source_authority": "feature_graph_status_store",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/provider-response-1.json"
                ),
                "source_refs": [
                    "god-room-event:evt-review-provider-speak",
                    "provider_response_artifact:"
                    "reports/provider-responses/provider-response-1.json",
                ],
                "forbidden_claims": ["natural_groupchat_closure"],
            }
        ],
    )
    runner_recovery_ref = "reports/runner-recovery-proof.json"
    runner_recovery_proof = {
        "schema_version": "xmuse.local_runner_recovery_proof.v1",
        "run_id": "run-runtime-closure-recovery",
        "runner_id": "platform-runner",
        "generated_at": "2026-06-14T23:10:00Z",
        "status": "ok",
        "proof_level": "local_runtime_proof",
        "source_authority": (
            "platform_runner_candidate_selection"
            "+shared_runner_health_model"
            "+lane_recovery_artifact"
        ),
        "lanes_path": str(tmp_path / "feature_lanes.json"),
        "xmuse_root": str(tmp_path),
        "filters": {
            "graph_id": "graph-runtime",
            "resolution_id": "resolution-runtime-closure-recovery",
        },
        "candidate_selection": {
            "source_authority": "platform_runner._candidate_lanes",
            "candidate_lane_ids": ["lane-runtime-evidence-patch"],
            "excluded_recovery_blocked_lane_ids": ["lane-runtime-evidence"],
            "invalid_recovery_artifact_lane_ids": [],
            "lane_count": 2,
        },
        "runner_supervisor": {
            "source_authority": "run_health.build_run_health_model",
            "recovery": {
                "blocked_count": 1,
                "blocked_lanes": [
                    {
                        "lane_id": "lane-runtime-evidence",
                        "artifact_ref": (
                            "reports/lane-recovery/lane-runtime-evidence.json"
                        ),
                    }
                ],
                "source_refs": [
                    "reports/lane-recovery/lane-runtime-evidence.json"
                ],
            },
        },
        "source_refs": ["reports/lane-recovery/lane-runtime-evidence.json"],
        "target_refs": [
            "lane:lane-runtime-evidence",
            "lane:lane-runtime-evidence-patch",
        ],
        "manual_gaps": [
            "live_long_running_runner_recovery_session_not_proven",
            "overnight_safe_recovery_not_proven",
            "review_truth_not_proven",
            "server_truth_not_proven",
        ],
        "forbidden_claims": [
            "overnight_safe_recovery",
            "end_to_end_execution_review_closure",
            "worker_output_is_review_truth",
            "ready_to_merge",
            "pr_merged",
        ],
    }
    _write_json(tmp_path / runner_recovery_ref, runner_recovery_proof)
    _write_json(
        tmp_path / "reports/lane-recovery/lane-runtime-evidence.json",
        {
            "schema_version": "xmuse.lane_recovery.v1",
            "lane_id": "lane-runtime-evidence",
            "status": "blocked",
        },
    )
    runner_recovery_lineage = build_runner_recovery_proof_lineage(
        proof=runner_recovery_proof,
        artifact_ref=runner_recovery_ref,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence",
    )
    patch_forward_ref = (
        "reports/god_room_patch_forward/"
        "graph-runtime.lane-runtime-evidence.patch-forward.json"
    )
    patch_intake_ref = (
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    )
    patch_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
    )
    patch_forward_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence.review-verdict.json"
    )
    patch_forward_evidence_refs = [
        patch_forward_verdict_ref,
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence.review-intake.json",
        "worker-candidate:patch-needed",
    ]
    _write_json(
        tmp_path / patch_forward_ref,
        {
            "schema_version": "xmuse.god_room_lane_patch_forward.v1",
            "proof_level": "contract_proof",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "patch_lane_id": "lane-runtime-evidence-patch",
            "review_verdict_artifact": patch_forward_verdict_ref,
            "patch_forward_link": {
                "failed_lane_id": "lane-runtime-evidence",
                "patch_lane_id": "lane-runtime-evidence-patch",
                "verdict_ref": (
                    "god_room_review_verdict:god_room_review_patch_forward"
                ),
                "evidence_refs": patch_forward_evidence_refs,
            },
            "patch_lane_contract": {
                "lane_id": "lane-runtime-evidence-patch",
                "feature_id": "feature-runtime-evidence",
                "owner": "codex",
                "inputs": [
                    "lane:lane-runtime-evidence",
                    *patch_forward_evidence_refs,
                ],
                "outputs": [
                    "artifact://lane-runtime-evidence-patch/"
                    "patch-forward-evidence.json"
                ],
                "dependency_refs": ["lane:lane-runtime-evidence"],
                "required_checks": ["focused-pytest"],
                "allowed_files": [],
                "rollback_constraints": ["preserve failed lane evidence"],
                "review_profile": "patch-forward-review",
                "memory_refs": [],
                "budget": {
                    "max_attempts": 3,
                    "max_consecutive_same_failure": 2,
                    "max_runtime_seconds": None,
                    "retry_backoff_seconds": 0,
                    "source_refs": [],
                },
                "source_refs": patch_forward_evidence_refs,
            },
        },
    )
    _write_json(
        tmp_path / patch_forward_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence",
            "review_verdict": {
                "id": "god_room_review_patch_forward",
                "lane_id": "lane-runtime-evidence",
                "decision": "patch-forward",
                "summary": "Patch-forward required.",
                "evidence_refs": patch_forward_evidence_refs[1:],
            },
        },
    )
    _write_json(
        tmp_path / patch_intake_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_intake.v1",
            "source_authority": "feature_graph_status_store+lane_dag_artifact",
            "proof_level": "contract_proof",
            "review_truth_status": "pending_independent_review",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "feature_graph_status": {
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": [
                    {
                        "event_id": "evt-review-provider-speak",
                        "event_type": "speak",
                        "participant_id": "part-review",
                        "god_id": "god-review",
                        "proof_level": "opt_in_live_proof",
                        "source_authority": "feature_graph_status_store",
                        "provider_response_artifact_ref": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "source_refs": [
                            "god-room-event:evt-review-provider-speak",
                            "provider_response_artifact:"
                            "reports/provider-responses/provider-response-1.json",
                        ],
                        "forbidden_claims": ["natural_groupchat_closure"],
                    }
                ],
            },
            "lane_id": "lane-runtime-evidence-patch",
            "blueprint_proof_level": "contract_proof",
            "source_event_lineage": [
                {
                    "event_id": "evt-review-provider-speak",
                    "event_type": "speak",
                    "participant_id": "part-review",
                    "god_id": "god-review",
                    "proof_level": "opt_in_live_proof",
                    "source_authority": "feature_graph_status_store",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "source_refs": [
                        "god-room-event:evt-review-provider-speak",
                        "provider_response_artifact:"
                        "reports/provider-responses/provider-response-1.json",
                    ],
                    "forbidden_claims": ["natural_groupchat_closure"],
                }
            ],
            "candidate_truth_status": "candidate_only",
            "execution_artifact_refs": [candidate_ref],
        },
    )
    _write_json(
        tmp_path / patch_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence-patch",
            "reviewer_id": "review-god",
            "review_plane_verdict_ref": (
                "review-plane:lane-runtime-evidence-patch:verdict-1"
            ),
            "review_verdict": {
                "id": "god_room_review_patch_merge",
                "lane_id": "lane-runtime-evidence-patch",
                "decision": "merge",
                "summary": "Patch lane reviewed.",
                "evidence_refs": [
                    patch_intake_ref,
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
            },
        },
    )
    review_closure = tmp_path / "review-closure.json"
    _write_json(
        review_closure,
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "source_authority": (
                "god_room_lane_patch_forward_artifact+"
                "patch_lane_review_verdict_artifact+"
                "local_runner_recovery_proof_artifact"
            ),
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "candidate_input_ready",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "source_event_lineage": [
                {
                    "event_id": "evt-review-provider-speak",
                    "event_type": "speak",
                    "participant_id": "part-review",
                    "god_id": "god-review",
                    "proof_level": "opt_in_live_proof",
                    "source_authority": "feature_graph_status_store",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "source_refs": [
                        "god-room-event:evt-review-provider-speak",
                        "provider_response_artifact:"
                        "reports/provider-responses/provider-response-1.json",
                    ],
                    "forbidden_claims": ["natural_groupchat_closure"],
                }
            ],
            "patch_forward_artifact": patch_forward_ref,
            "patch_lane_review_intake_artifact": patch_intake_ref,
            "patch_lane_review_verdict_artifact": patch_verdict_ref,
            "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_artifact_refs": [candidate_ref],
            "cited_candidate_artifact_lineage": [
                load_local_execution_candidate_lineage(
                    root=tmp_path,
                    artifact_ref=candidate_ref,
                    lane_id="lane-runtime-evidence-patch",
                    graph_id="graph-runtime",
                    conversation_id="conv-1",
                )
            ],
            "runner_recovery_proof_lineage": runner_recovery_lineage,
            "terminal_review_verdict": {
                "id": "god_room_review_patch_merge",
                "lane_id": "lane-runtime-evidence-patch",
                "decision": "merge",
                "summary": "Patch lane reviewed.",
                "evidence_refs": [
                    patch_intake_ref,
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
            },
            "review_plane_sync_status": "review_plane_store_updated",
            "review_plane_verdict_ref": (
                "review-plane:lane-runtime-evidence-patch:verdict-1"
            ),
            "graph_status_source_authority": "feature_graph_status_store",
            "graph_status_merge_status": "verified_merged",
            "terminal_feature_graph_status": {
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:merged",
                "status": "merged",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": [
                    {
                        "event_id": "evt-review-provider-speak",
                        "event_type": "speak",
                        "participant_id": "part-review",
                        "god_id": "god-review",
                        "proof_level": "opt_in_live_proof",
                        "source_authority": "feature_graph_status_store",
                        "provider_response_artifact_ref": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "source_refs": [
                            "god-room-event:evt-review-provider-speak",
                            "provider_response_artifact:"
                            "reports/provider-responses/provider-response-1.json",
                        ],
                        "forbidden_claims": ["natural_groupchat_closure"],
                    }
                ],
            },
            "manual_gaps": [
                "review_plane_store_not_updated",
                "lane_status_not_updated",
                "release_evidence_not_linked",
                "github_truth_not_checked",
            ],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )
    _write_graph_authority(
        root=tmp_path,
        conversation_id="conv-1",
        source_event_lineage=[
            {
                "event_id": "evt-review-provider-speak",
                "event_type": "speak",
                "participant_id": "part-review",
                "god_id": "god-review",
                "proof_level": "opt_in_live_proof",
                "source_authority": "feature_graph_status_store",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/provider-response-1.json"
                ),
                "source_refs": [
                    "god-room-event:evt-review-provider-speak",
                    "provider_response_artifact:"
                    "reports/provider-responses/provider-response-1.json",
                ],
                "forbidden_claims": ["natural_groupchat_closure"],
            }
        ],
    )
    review_chain_proof = tmp_path / "review-chain-proof.json"
    chain_proof = capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=review_chain_proof,
    )
    assert chain_proof["status"] == "chain_ready"

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-closure-pack",
        god_room_participants=participants,
        god_room_events=events_path,
        god_room_blueprint_freeze=freeze_path,
        god_room_lane_dag=lane_dag,
        god_room_memory_trace=trace,
        god_room_tui_projection=tui,
        god_room_speaker_attempt=speaker_attempt,
        god_room_speaker_response=speaker_response,
        god_room_multi_turn_provider_speech_run=multi_turn_run,
        god_room_review_closure=review_closure,
        god_room_review_chain_proof=review_chain_proof,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    assert pack["source_reports"]["god_room_runtime_closure_evidence"].endswith(
        "god-room-runtime-closure-production-evidence.json"
    )
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert "github truth artifact is missing" in closure["blocked_reason"]
    assert closure["details"]["god_room_runtime_closure"]["room_replay"]["status"] == "ok"
    assert closure["details"]["god_room_runtime_closure"]["lane_dag"][
        "lane_contract_count"
    ] == 1
    assert closure["details"]["god_room_runtime_closure"]["lane_dag"][
        "source_event_lineage_count"
    ] == 1
    assert closure["details"]["god_room_runtime_closure"]["lane_dag"][
        "source_event_lineage_event_types"
    ] == {"speak": 1}
    assert closure["details"]["god_room_runtime_closure"]["lane_dag"][
        "source_event_lineage_proof_levels"
    ] == {"opt_in_live_proof": 1}
    assert closure["details"]["god_room_runtime_closure"]["speaker_attempt"][
        "status"
    ] == "ready_for_provider_attempt"
    assert closure["details"]["god_room_runtime_closure"]["speaker_response"][
        "status"
    ] == "speak_event_appended"
    assert closure["details"]["god_room_runtime_closure"][
        "multi_turn_provider_speech"
    ]["status"] == "completed"
    assert closure["details"]["god_room_runtime_closure"][
        "multi_turn_provider_speech"
    ]["appended_event_ids"] == ["evt-review-provider-speak"]
    assert (
        "provider_response_artifact:reports/provider-responses/provider-response-1.json"
        in closure["source_refs"]
    )
    assert "god-room-event:evt-review-provider-speak" in closure["source_refs"]
    assert closure["details"]["god_room_runtime_closure"]["review_closure"][
        "status"
    ] == "candidate_input_ready"
    assert closure["details"]["god_room_runtime_closure"]["review_closure"][
        "execution_truth_status"
    ] == "candidate_reviewed"
    assert closure["details"]["god_room_runtime_closure"]["review_closure"][
        "server_truth_status"
    ] == "not_server_truth"
    assert closure["details"]["god_room_runtime_closure"]["review_closure"][
        "source_event_lineage_count"
    ] == 1
    assert closure["details"]["god_room_runtime_closure"]["review_closure"][
        "source_event_lineage_proof_levels"
    ] == {"opt_in_live_proof": 1}
    assert "worker-candidate:patch-reviewed" in closure["source_refs"]
    assert closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "status"
    ] == "chain_ready"
    assert closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "proof_level"
    ] == "contract_proof"
    assert closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "server_truth_status"
    ] == "not_server_truth"
    assert closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "candidate_artifact_ref_count"
    ] == 1
    assert closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "bounded_session_gate"
    ]["status"] == "verified"
    session = closure["details"]["god_room_runtime_closure"]["review_chain_proof"][
        "local_execution_review_session"
    ]
    assert session["status"] == "bounded_session_ready"
    assert session["proof_level"] == "contract_proof"
    assert session["session_truth_status"] == "bounded_local_execution_review_session"
    assert session["server_truth_status"] == "not_server_truth"
    assert session["schema_version"] == "xmuse.local_execution_review_session.v1"
    assert session["session_id"] == (
        "local-execution-review-session:"
        "graph-runtime:lane-runtime-evidence:lane-runtime-evidence-patch"
    )
    assert session["session_artifact_ref_count"] >= 5
    assert session["session_source_ref_count"] >= 5
    assert session["session_scope_boundary"]["status"] == "verified"
    assert session["candidate_count"] == 1
    assert session["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert session["session_artifact_validation"]["status"] == "validated"
    assert session["session_artifact_validation"]["artifact_count"] == 4
    assert session["session_artifact_validation"]["issue_count"] == 0
    assert "server_side_truth" in closure["details"]["god_room_runtime_closure"][
        "review_chain_proof"
    ]["forbidden_claims"]
    review_chain_source_ref = (
        "god-room-review-chain-proof:graph-runtime:"
        "lane-runtime-evidence:lane-runtime-evidence-patch"
    )
    assert review_chain_source_ref in closure["source_refs"]
    assert f"review_chain_proof_artifact:{review_chain_proof}" in closure["source_refs"]
    linkage = pack["god_room_review_chain_release_linkage"]
    assert linkage["schema_version"] == (
        "xmuse.god_room_review_chain_release_linkage.v1"
    )
    assert linkage["status"] == "linked_to_replay_bundle"
    assert linkage["proof_level"] == "contract_proof"
    assert linkage["server_truth_status"] == "not_server_truth"
    assert linkage["review_chain_proof_artifact"] == str(review_chain_proof)
    assert linkage["runtime_closure_evidence_report"] == pack["source_reports"][
        "god_room_runtime_closure_evidence"
    ]
    assert linkage["replay_bundle"] == pack["overnight_replay_bundle"]
    assert linkage["replay_section_id"] == "god_room_runtime_closure"
    assert linkage["review_chain_proof_status"] == "chain_ready"
    assert linkage["bounded_session_gate_status"] == "verified"
    assert linkage["current_handoff_gate_ready"] is True
    assert review_chain_source_ref in linkage["source_refs"]
    assert f"review_chain_proof_artifact:{review_chain_proof}" in linkage[
        "source_refs"
    ]
    assert "god-room-event:evt-review-provider-speak" in linkage["source_refs"]
    assert (
        "provider_response_artifact:reports/provider-responses/provider-response-1.json"
        in linkage["source_refs"]
    )
    assert linkage["resolved_manual_gaps"] == [
        "release_evidence_export_not_attempted",
        "release_evidence_not_linked",
    ]
    assert "server_truth_not_proven" in linkage["retained_manual_gaps"]
    assert linkage["affects_pack_decision"] is False
    for claim in GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS:
        assert claim in linkage["forbidden_claims"]
    assert "ready_to_merge" in linkage["forbidden_claims"]
    assert "pr_merged" in linkage["forbidden_claims"]


def test_release_evidence_pack_reports_missing_expected_review_chain_for_closure(
    tmp_path: Path,
) -> None:
    review_closure = tmp_path / "review-closure.json"
    _write_json(
        review_closure,
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "candidate_input_ready",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "candidate_refs": ["worker-candidate:patch-reviewed"],
            "cited_candidate_refs": ["worker-candidate:patch-reviewed"],
            "manual_gaps": ["release_evidence_not_linked"],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-closure-pack-missing-chain",
        god_room_review_closure=review_closure,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    review_chain = closure["details"]["god_room_runtime_closure"][
        "review_chain_proof"
    ]
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert (
        "GOD room review chain proof artifact is expected but missing"
        in closure["blocked_reason"]
    )
    assert review_chain["status"] == "manual_gap"
    assert review_chain["optional"] is False
    assert review_chain["expected"] is True
    assert "god_room_review_chain_proof_artifact_missing" in review_chain[
        "manual_gaps"
    ]
    assert "worker_output_is_review_truth" in review_chain["forbidden_claims"]
    assert "god_room_review_chain_release_linkage" not in pack


def test_release_evidence_pack_rejects_review_chain_when_current_handoff_fails(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_local_execution_candidate(
        tmp_path / candidate_ref,
        conversation_id="conv-1",
    )
    review_closure = tmp_path / "review-closure.json"
    _write_json(
        review_closure,
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_refs": [
                "worker-candidate:patch-reviewed",
                candidate_ref,
            ],
            "cited_candidate_artifact_refs": [candidate_ref],
            "manual_gaps": [
                "review_plane_store_not_updated",
                "lane_status_not_updated",
                "release_evidence_not_linked",
                "github_truth_not_checked",
            ],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )
    _attach_review_closure_candidate_lineage(
        root=tmp_path,
        review_closure=review_closure,
        candidate_ref=candidate_ref,
        conversation_id="conv-1",
    )
    review_chain_proof = tmp_path / "review-chain-proof.json"
    _write_review_chain_proof_artifact(review_chain_proof)
    chain_proof = json.loads(review_chain_proof.read_text(encoding="utf-8"))
    verified_boundary = {"status": "verified", "proof_level": "contract_proof"}
    chain_proof.update(
        {
            "xmuse_root": str(tmp_path),
            "candidate_lineage": {
                "candidate_artifact_refs": [candidate_ref],
                "producers": ["platform_runner_dispatch"],
            },
            "local_execution_review_session": {
                "schema_version": "xmuse.local_execution_review_session.v1",
                "session_id": (
                    "local-execution-review-session:"
                    "graph-runtime:lane-runtime-evidence:"
                    "lane-runtime-evidence-patch"
                ),
                "status": "bounded_session_ready",
                "proof_level": "contract_proof",
                "session_truth_status": "bounded_local_execution_review_session",
                "execution_truth_status": "candidate_reviewed",
                "review_truth_status": "independent_review_artifact",
                "server_truth_status": "not_server_truth",
                "candidate_count": 1,
                "candidate_artifact_refs": [candidate_ref],
                "candidate_producers": ["platform_runner_dispatch"],
                "session_artifact_refs": [
                    "review-closure.json",
                    candidate_ref,
                    "reports/runner-recovery-proof.json",
                ],
                "session_source_refs": [
                    "god-room-review-chain-session:"
                    "graph-runtime:lane-runtime-evidence:"
                    "lane-runtime-evidence-patch",
                    candidate_ref,
                ],
                "session_artifact_validation": {
                    "status": "validated",
                    "proof_level": "contract_proof",
                },
                "session_scope_boundary": verified_boundary,
                "runner_session_boundary": {
                    **verified_boundary,
                    "runner_session_refs": [
                        "work/runner_sessions/runner-session-1.json"
                    ],
                    "candidate_artifact_refs": [candidate_ref],
                },
                "graph_wide_lane_accounting_boundary": {
                    **verified_boundary,
                    "candidate_artifact_refs": [candidate_ref],
                },
                "runner_recovery_lineage_boundary": verified_boundary,
                "review_intake_graph_status_boundary": verified_boundary,
                "candidate_graph_status_boundary": verified_boundary,
                "candidate_artifact_ref_boundary": {
                    **verified_boundary,
                    "closure_cited_candidate_artifact_refs": [candidate_ref],
                    "resolved_candidate_artifact_refs": [candidate_ref],
                },
                "candidate_lineage_boundary": {
                    **verified_boundary,
                    "closure_candidate_artifact_refs": [candidate_ref],
                    "resolved_candidate_artifact_refs": [candidate_ref],
                },
                "worker_evidence_bundle_citation_boundary": {
                    **verified_boundary,
                    "citation_status": "not_required",
                },
                "reviewer_independence": verified_boundary,
            },
        }
    )
    assert chain_proof["status"] == "chain_ready"
    _write_json(review_chain_proof, chain_proof)
    (tmp_path / "work" / "runner_sessions" / "runner-session-1.json").unlink()

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-chain-stale-current-handoff-pack",
        god_room_review_chain_proof=review_chain_proof,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    details = closure["details"]["god_room_runtime_closure"]["review_chain_proof"]
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert (
        "GOD room review chain proof current review-closure handoff is not "
        "gate-ready: GOD room review closure runner session artifact is not "
        "readable: work/runner_sessions/runner-session-1.json"
    ) in closure["blocked_reason"]
    assert details["status"] == "chain_ready"
    assert details["bounded_session_gate"]["status"] == "verified"
    assert details["current_handoff_gate_ready"] is False
    assert details["current_handoff_summary"] == (
        "GOD room review closure runner session artifact is not readable: "
        "work/runner_sessions/runner-session-1.json"
    )
    assert details["current_handoff_candidate_artifact_refs"] == [candidate_ref]
    assert details["current_handoff_candidate_artifact_ref_count"] == 1
    assert (
        "god-room-review-chain-proof:graph-runtime:"
        "lane-runtime-evidence:lane-runtime-evidence-patch"
    ) not in closure["source_refs"]
    assert f"review_chain_proof_artifact:{review_chain_proof}" not in closure[
        "source_refs"
    ]
    linkage = pack["god_room_review_chain_release_linkage"]
    assert linkage["status"] == "manual_gap"
    assert linkage["proof_level"] == "manual_gap"
    assert linkage["review_chain_proof_status"] == "chain_ready"
    assert linkage["bounded_session_gate_status"] == "verified"
    assert linkage["current_handoff_gate_ready"] is False
    assert linkage["source_refs"] == []
    assert linkage["resolved_manual_gaps"] == []
    assert "release_evidence_export_not_attempted" in linkage["retained_manual_gaps"]
    assert linkage["blocked_reason"] == (
        "review chain proof was not indexed into replay source refs"
    )
    assert "ready_to_merge" in linkage["forbidden_claims"]


def test_release_evidence_pack_fail_closes_review_chain_proof_server_truth_overclaim(
    tmp_path: Path,
) -> None:
    participants = tmp_path / "god-room-participants.json"
    _write_json(
        participants,
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                    cli_id="codex",
                ).model_dump(mode="json")
            ]
        },
    )
    events_path = tmp_path / "god-room-events.json"
    _write_json(
        events_path,
        {
            "events": [
                _god_room_event("evt-overclaim-context").model_dump(mode="json")
            ]
        },
    )
    review_chain_proof = _write_review_chain_proof_artifact(
        tmp_path / "review-chain-proof.json",
        server_truth_status="server_side_truth",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-chain-overclaim-pack",
        god_room_participants=participants,
        god_room_events=events_path,
        god_room_review_chain_proof=review_chain_proof,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    details = closure["details"]["god_room_runtime_closure"]["review_chain_proof"]
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert "GOD room review chain proof overclaims server truth" in closure[
        "blocked_reason"
    ]
    assert details["status"] == "chain_ready"
    assert details["server_truth_status"] == "server_side_truth"
    assert "server_side_truth" in details["forbidden_claims"]
    assert "god-room-event:evt-overclaim-context" in closure["source_refs"]
    linkage = pack["god_room_review_chain_release_linkage"]
    assert linkage["status"] == "manual_gap"
    assert linkage["source_refs"] == []
    assert linkage["source_ref_count"] == 0
    assert linkage["blocked_reason"] == (
        "review chain proof was not indexed into replay source refs"
    )


def test_release_evidence_pack_fail_closes_review_chain_proof_missing_forbidden_claim(
    tmp_path: Path,
) -> None:
    review_chain_proof = _write_review_chain_proof_artifact(
        tmp_path / "review-chain-proof.json",
        forbidden_claims=[
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "ready_to_merge",
            "pr_merged",
            "github_review_truth",
            "live_memoryos",
            "overnight_readiness",
        ],
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-chain-missing-claim-pack",
        god_room_review_chain_proof=review_chain_proof,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    details = closure["details"]["god_room_runtime_closure"]["review_chain_proof"]
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert "GOD room review chain proof missing forbidden claim: server_side_truth" in (
        closure["blocked_reason"]
    )
    assert details["status"] == "chain_ready"
    assert "server_side_truth" not in details["forbidden_claims"]


def test_release_evidence_pack_fail_closes_review_chain_proof_missing_bounded_session(
    tmp_path: Path,
) -> None:
    review_chain_proof = _write_review_chain_proof_artifact(
        tmp_path / "review-chain-proof.json",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "pack.json",
        run_id="runtime-chain-missing-session-pack",
        god_room_review_chain_proof=review_chain_proof,
    )

    replay = json.loads(Path(pack["overnight_replay_bundle"]).read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    details = closure["details"]["god_room_runtime_closure"]["review_chain_proof"]
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert "local_execution_review_session is missing" in closure["blocked_reason"]
    assert details["status"] == "chain_ready"
    assert details["bounded_session_gate"]["status"] == "manual_gap"
    assert details["local_execution_review_session"]["status"] == "not_provided"


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
    assert {
        "source": "proof_contamination_audit",
        "kind": "proof_finding",
        "id": "real-provider-runtime",
        "owner": "operator",
        "reason": (
            "fake_marker_in_production_proof: Production proof contains "
            "fake/local/stdout contamination marker: fake."
        ),
        "next_action": (
            "Replace the contaminated artifact with live/server-side evidence "
            "and remove fake/local/stdout fallback sources."
        ),
        "artifact": str(tmp_path / "proof-contamination-audit.json"),
    } in pack["recovery_queue"]


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


def test_release_evidence_pack_cli_accepts_production_baseline(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    baseline = _write_production_baseline(tmp_path / "baseline.json")
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
                "--production-baseline",
                str(baseline),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    assert pack["source_reports"]["production_baseline"] == str(baseline)
    assert pack["production_baseline"]["head_sha"] == "head-pack-1"


def test_release_evidence_pack_cli_accepts_goal_stage_results(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    stage_result = _write_goal_stage_result(tmp_path / "goal" / "S1.result.json")
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
                "overnight-cli-stage",
                "--goal-stage-result",
                str(stage_result),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["goal_stage_evidence"] == str(
        output.parent / "goal-stage-production-evidence.json"
    )
    assert sections["stage_evidence"]["status"] == "ok"
    assert sections["stage_evidence"]["source_refs"] == [
        "goal_run:overnight-cli-stage",
        "goal_stage:S1",
        f"goal_stage_result:{stage_result}",
    ]


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


def test_release_evidence_pack_cli_accepts_god_room_review_closure(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    review_closure = tmp_path / "god-room" / "review-closure.json"
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    patch_forward_ref = (
        "reports/god_room_patch_forward/"
        "graph-runtime.lane-runtime-evidence.patch-forward.json"
    )
    patch_intake_ref = (
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    )
    patch_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
    )
    patch_forward_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence.review-verdict.json"
    )
    patch_forward_evidence_refs = [
        patch_forward_verdict_ref,
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence.review-intake.json",
        "worker-candidate:patch-needed",
    ]
    _write_json(
        review_closure,
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "candidate_input_ready",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "conversation_id": "conv-1",
            "source_event_lineage": [
                {
                    "event_id": "evt-provider-speak",
                    "event_type": "speak",
                    "participant_id": "part-review",
                    "god_id": "god-review",
                    "proof_level": "opt_in_live_proof",
                    "source_authority": "feature_graph_status_store",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "source_refs": [
                        "god-room-event:evt-provider-speak",
                        "provider_response_artifact:"
                        "reports/provider-responses/provider-response-1.json",
                    ],
                    "forbidden_claims": ["natural_groupchat_closure"],
                }
            ],
            "patch_forward_artifact": patch_forward_ref,
            "patch_lane_review_intake_artifact": patch_intake_ref,
            "patch_lane_review_verdict_artifact": patch_verdict_ref,
            "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_artifact_refs": [candidate_ref],
            "terminal_review_verdict": {
                "id": "god_room_review_patch_merge",
                "decision": "merge",
                "evidence_refs": [
                    patch_intake_ref,
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
            },
            "review_plane_sync_status": "review_plane_store_updated",
            "review_plane_verdict_ref": (
                "review-plane:lane-runtime-evidence-patch:verdict-1"
            ),
            "graph_status_source_authority": "feature_graph_status_store",
            "graph_status_merge_status": "verified_merged",
            "terminal_feature_graph_status": {
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:merged",
                "status": "merged",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": [
                    {
                        "event_id": "evt-provider-speak",
                        "event_type": "speak",
                        "participant_id": "part-review",
                        "god_id": "god-review",
                        "proof_level": "opt_in_live_proof",
                        "source_authority": "feature_graph_status_store",
                        "provider_response_artifact_ref": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "source_refs": [
                            "god-room-event:evt-provider-speak",
                            "provider_response_artifact:"
                            "reports/provider-responses/provider-response-1.json",
                        ],
                        "forbidden_claims": ["natural_groupchat_closure"],
                    }
                ],
            },
            "runner_recovery_proof_lineage": {
                "schema_version": "xmuse.local_runner_recovery_proof_lineage.v1",
                "artifact_ref": "reports/runner-recovery-proof.json",
                "source_authority": (
                    "platform_runner_candidate_selection"
                    "+shared_runner_health_model"
                    "+lane_recovery_artifact"
                ),
                "status": "target_lane_recovery_blocked",
                "proof_level": "local_runtime_proof",
                "graph_id": "graph-runtime",
                "lane_id": "lane-runtime-evidence",
                "filtered_graph_id": "graph-runtime",
                "candidate_lane_ids": ["lane-runtime-evidence-patch"],
                "excluded_recovery_blocked_lane_ids": ["lane-runtime-evidence"],
                "invalid_recovery_artifact_lane_ids": [],
                "source_refs": ["reports/lane-recovery/lane-runtime-evidence.json"],
                "target_refs": [
                    "lane:lane-runtime-evidence",
                    "lane:lane-runtime-evidence-patch",
                ],
                "manual_gaps": [
                    "review_truth_not_proven",
                    "server_truth_not_proven",
                    "overnight_safe_recovery_not_proven",
                ],
                "forbidden_claims": [
                    "overnight_safe_recovery",
                    "end_to_end_execution_review_closure",
                    "worker_output_is_review_truth",
                    "ready_to_merge",
                    "pr_merged",
                ],
            },
            "manual_gaps": [
                "review_plane_store_not_updated",
                "lane_status_not_updated",
                "release_evidence_not_linked",
                "github_truth_not_checked",
            ],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )
    _write_json(
        review_closure.parent / "reports/runner-recovery-proof.json",
        {
            "schema_version": "xmuse.local_runner_recovery_proof.v1",
            "status": "ok",
            "proof_level": "local_runtime_proof",
            "source_authority": (
                "platform_runner_candidate_selection"
                "+shared_runner_health_model"
                "+lane_recovery_artifact"
            ),
        },
    )
    _write_json(
        review_closure.parent / "reports/lane-recovery/lane-runtime-evidence.json",
        {
            "schema_version": "xmuse.lane_recovery.v1",
            "lane_id": "lane-runtime-evidence",
            "status": "blocked",
        },
    )
    _write_local_execution_candidate(
        review_closure.parent / candidate_ref,
        conversation_id="conv-1",
        source_event_lineage=[
            {
                "event_id": "evt-provider-speak",
                "event_type": "speak",
                "participant_id": "part-review",
                "god_id": "god-review",
                "proof_level": "opt_in_live_proof",
                "source_authority": "feature_graph_status_store",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/provider-response-1.json"
                ),
                "source_refs": [
                    "god-room-event:evt-provider-speak",
                    "provider_response_artifact:"
                    "reports/provider-responses/provider-response-1.json",
                ],
                "forbidden_claims": ["natural_groupchat_closure"],
            }
        ],
    )
    _attach_review_closure_candidate_lineage(
        root=review_closure.parent,
        review_closure=review_closure,
        candidate_ref=candidate_ref,
        conversation_id="conv-1",
    )
    _write_json(
        review_closure.parent / patch_forward_ref,
        {
            "schema_version": "xmuse.god_room_lane_patch_forward.v1",
            "proof_level": "contract_proof",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "patch_lane_id": "lane-runtime-evidence-patch",
            "review_verdict_artifact": patch_forward_verdict_ref,
            "patch_forward_link": {
                "failed_lane_id": "lane-runtime-evidence",
                "patch_lane_id": "lane-runtime-evidence-patch",
                "verdict_ref": (
                    "god_room_review_verdict:god_room_review_patch_forward"
                ),
                "evidence_refs": patch_forward_evidence_refs,
            },
            "patch_lane_contract": {
                "lane_id": "lane-runtime-evidence-patch",
                "feature_id": "feature-runtime-evidence",
                "owner": "codex",
                "inputs": [
                    "lane:lane-runtime-evidence",
                    *patch_forward_evidence_refs,
                ],
                "outputs": [
                    "artifact://lane-runtime-evidence-patch/"
                    "patch-forward-evidence.json"
                ],
                "dependency_refs": ["lane:lane-runtime-evidence"],
                "required_checks": ["focused-pytest"],
                "allowed_files": [],
                "rollback_constraints": ["preserve failed lane evidence"],
                "review_profile": "patch-forward-review",
                "memory_refs": [],
                "budget": {
                    "max_attempts": 3,
                    "max_consecutive_same_failure": 2,
                    "max_runtime_seconds": None,
                    "retry_backoff_seconds": 0,
                    "source_refs": [],
                },
                "source_refs": patch_forward_evidence_refs,
            },
        },
    )
    _write_json(
        review_closure.parent / patch_forward_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence",
            "review_verdict": {
                "id": "god_room_review_patch_forward",
                "lane_id": "lane-runtime-evidence",
                "decision": "patch-forward",
                "summary": "Patch-forward required.",
                "evidence_refs": patch_forward_evidence_refs[1:],
            },
        },
    )
    _write_json(
        review_closure.parent / patch_intake_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_intake.v1",
            "source_authority": "feature_graph_status_store+lane_dag_artifact",
            "proof_level": "contract_proof",
            "review_truth_status": "pending_independent_review",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "feature_graph_status": {
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": [
                    {
                        "event_id": "evt-provider-speak",
                        "event_type": "speak",
                        "participant_id": "part-review",
                        "god_id": "god-review",
                        "proof_level": "opt_in_live_proof",
                        "source_authority": "feature_graph_status_store",
                        "provider_response_artifact_ref": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "source_refs": [
                            "god-room-event:evt-provider-speak",
                            "provider_response_artifact:"
                            "reports/provider-responses/provider-response-1.json",
                        ],
                        "forbidden_claims": ["natural_groupchat_closure"],
                    }
                ],
            },
            "lane_id": "lane-runtime-evidence-patch",
            "blueprint_proof_level": "contract_proof",
            "source_event_lineage": [
                {
                    "event_id": "evt-provider-speak",
                    "event_type": "speak",
                    "participant_id": "part-review",
                    "god_id": "god-review",
                    "proof_level": "opt_in_live_proof",
                    "source_authority": "feature_graph_status_store",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "source_refs": [
                        "god-room-event:evt-provider-speak",
                        "provider_response_artifact:"
                        "reports/provider-responses/provider-response-1.json",
                    ],
                    "forbidden_claims": ["natural_groupchat_closure"],
                }
            ],
            "candidate_truth_status": "candidate_only",
            "execution_artifact_refs": [candidate_ref],
        },
    )
    _write_json(
        review_closure.parent / patch_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-1",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence-patch",
            "reviewer_id": "review-god",
            "review_plane_verdict_ref": (
                "review-plane:lane-runtime-evidence-patch:verdict-1"
            ),
            "review_verdict": {
                "id": "god_room_review_patch_merge",
                "decision": "merge",
                "evidence_refs": [
                    patch_intake_ref,
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
            },
        },
    )
    _write_graph_authority(
        root=review_closure.parent,
        conversation_id="conv-1",
        source_event_lineage=[
            {
                "event_id": "evt-provider-speak",
                "event_type": "speak",
                "participant_id": "part-review",
                "god_id": "god-review",
                "proof_level": "opt_in_live_proof",
                "source_authority": "feature_graph_status_store",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/provider-response-1.json"
                ),
                "source_refs": [
                    "god-room-event:evt-provider-speak",
                    "provider_response_artifact:"
                    "reports/provider-responses/provider-response-1.json",
                ],
                "forbidden_claims": ["natural_groupchat_closure"],
            }
        ],
    )
    review_chain_proof = tmp_path / "god-room" / "review-chain-proof.json"
    chain_proof = capture_god_room_review_chain_proof(
        root=review_closure.parent,
        review_closure_artifact=review_closure,
        output_path=review_chain_proof,
    )
    assert chain_proof["status"] == "chain_ready"
    events_path = tmp_path / "god-room" / "events.json"
    _write_json(
        events_path,
        {
            "events": [
                _god_room_event("evt-propose").model_dump(mode="json"),
                _god_room_event(
                    "evt-provider-speak",
                    participant_id="part-review",
                    god_id="god-review",
                    causal_parent_id="evt-propose",
                ).model_dump(mode="json"),
            ]
        },
    )
    multi_turn_run = tmp_path / "god-room" / "multi-turn-provider-speech-run.json"
    _write_json(
        multi_turn_run,
        {
            "schema_version": "xmuse.god_room_multi_turn_provider_speech_run.v1",
            "status": "completed",
            "proof_level": "opt_in_live_proof",
            "source_authority": (
                "god_room_event_store+room_selected_god_binding+"
                "provider_invocation+provider_response_capture"
            ),
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "turn_count": 1,
            "turns": [
                {
                    "turn_number": 1,
                    "after_event_id": "evt-propose",
                    "appended_event_id": "evt-provider-speak",
                    "artifacts": {
                        "provider_response": (
                            "reports/provider-responses/provider-response-1.json"
                        ),
                        "speaker_response": (
                            "reports/god_room_speaker_responses/"
                            "speaker-response-1.json"
                        ),
                    },
                    "speaker_response": {"status": "speak_event_appended"},
                    "provider_response": {"response_id": "provider-response-1"},
                }
            ],
            "manual_gaps": [
                "natural_multi_god_groupchat_not_proven",
                "peer_god_live_proof_not_proven",
            ],
            "forbidden_claims": [
                "peer_god_live_proof",
                "natural_groupchat_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        },
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "review-closure-cli-pack",
                "--god-room-events",
                str(events_path),
                "--god-room-multi-turn-provider-speech-run",
                str(multi_turn_run),
                "--god-room-review-closure",
                str(review_closure),
                "--god-room-review-chain-proof",
                str(review_chain_proof),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    closure = sections["god_room_runtime_closure"]
    runtime_details = closure["details"]["god_room_runtime_closure"]
    details = runtime_details["review_closure"]
    assert pack["source_reports"]["god_room_runtime_closure_evidence"] == str(
        output.parent / "god-room-runtime-closure-production-evidence.json"
    )
    assert closure["status"] == "manual_gap"
    assert closure["proof_level"] == "manual_gap"
    assert details["status"] == "candidate_input_ready"
    assert details["proof_level"] == "contract_proof"
    assert details["server_truth_status"] == "not_server_truth"
    assert details["source_event_lineage_count"] == 1
    assert details["source_event_lineage_event_types"] == {"speak": 1}
    assert details["runner_recovery_proof_lineage"]["status"] == (
        "target_lane_recovery_blocked"
    )
    assert details["runner_recovery_proof_lineage"]["proof_level"] == (
        "local_runtime_proof"
    )
    assert "ready_to_merge" in details["forbidden_claims"]
    chain_details = runtime_details["review_chain_proof"]
    assert chain_details["status"] == "chain_ready"
    assert chain_details["proof_level"] == "contract_proof"
    assert chain_details["server_truth_status"] == "not_server_truth"
    assert chain_details["release_handoff_gate_ready"] is True
    assert chain_details["candidate_artifact_ref_count"] == 1
    assert chain_details["bounded_session_gate"]["status"] == "verified"
    assert "server_side_truth" in chain_details["forbidden_claims"]
    assert runtime_details["multi_turn_provider_speech"]["status"] == "completed"
    assert runtime_details["multi_turn_provider_speech"]["appended_event_ids"] == [
        "evt-provider-speak"
    ]
    assert "worker-candidate:patch-reviewed" in closure["source_refs"]
    assert (
        "runner_recovery_proof_artifact:reports/runner-recovery-proof.json"
        in closure["source_refs"]
    )
    assert "reports/lane-recovery/lane-runtime-evidence.json" in closure[
        "source_refs"
    ]


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


def test_release_evidence_pack_cli_can_require_missing_internal_review(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--internal-review-expected-head-sha",
                "head-pack-1",
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    gate = json.loads((artifacts / "internal-review.json").read_text(encoding="utf-8"))
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "Internal review artifact does not exist" in gate["summary"]
    assert pack["source_reports"]["internal_review_gate"] == str(
        artifacts / "internal-review.json"
    )
    assert pack["release_readiness_decision"] == "blocked"


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


def _god_room_event(
    event_id: str,
    *,
    event_type: GodRoomEventKind = GodRoomEventKind.SPEAK,
    participant_id: str = "part-architect",
    god_id: str = "god-architect",
    causal_parent_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id="room-1",
        conversation_id="conv-1",
        participant_id=participant_id,
        god_id=god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc="2026-06-13T10:00:00Z",
        content=str((payload or {}).get("goal") or "Close runtime evidence."),
        causal_parent_id=causal_parent_id,
        source_refs=[f"message:{event_id}"],
        cli_id="codex",
        provider_profile="codex",
        payload=payload or {"body": "Close runtime evidence."},
    )
