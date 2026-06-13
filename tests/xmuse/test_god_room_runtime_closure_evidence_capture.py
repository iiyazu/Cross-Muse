from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.platform.god_room_runtime_closure_evidence_capture import (
    capture_god_room_runtime_closure_evidence,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    compile_blueprint_freeze_from_god_room_events,
)


def test_god_room_runtime_closure_evidence_indexes_contracts_without_merge_upgrade(
    tmp_path: Path,
) -> None:
    participants_path = _write_json(
        tmp_path / "participants.json",
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                    cli_id="codex",
                    role="architect",
                ).model_dump(mode="json"),
                GodRoomParticipant(
                    participant_id="part-review",
                    god_id="god-review",
                    cli_id="opencode",
                    role="review",
                ).model_dump(mode="json"),
            ]
        },
    )
    events = [
        _event("evt-propose"),
        _event(
            "evt-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-propose",
            payload={
                "freeze_target_ref": "blueprint:bp-god-room-runtime:1",
                "goal": "Close GOD room runtime evidence.",
                "scope": ["GOD room replay", "release evidence pack"],
                "acceptance_contracts": ["Replay pack indexes closure evidence."],
                "repo_areas": ["src/xmuse_core/platform"],
            },
        ),
    ]
    events_path = _write_json(
        tmp_path / "events.json",
        {"events": [event.model_dump(mode="json") for event in events]},
    )
    freeze = compile_blueprint_freeze_from_god_room_events(
        blueprint_id="bp-god-room-runtime",
        revision=1,
        events=events,
    )
    freeze_path = _write_json(
        tmp_path / "blueprint-freeze.json",
        freeze.model_dump(mode="json"),
    )
    lane_dag_path = _write_json(
        tmp_path / "lane-dag.json",
        {
            "blueprint_ref": "blueprint:bp-god-room-runtime:1",
            "lane_contracts": [
                {
                    "lane_id": "lane-replay-evidence",
                    "feature_id": "feature-runtime-closure",
                    "owner": "codex",
                    "required_checks": [
                        "uv run pytest tests/xmuse/test_release_evidence_pack.py -q"
                    ],
                    "memory_refs": [
                        "memory://conversation/conv-1/blueprints/bp-god-room-runtime"
                    ],
                }
            ],
            "recovery_decisions": [
                {
                    "lane_id": "lane-replay-evidence",
                    "decision": "refactor_required",
                    "retry_allowed": False,
                    "failure_class": "demo_runtime_path",
                }
            ],
        },
    )
    trace_path = _write_json(
        tmp_path / "memory-trace.json",
        {
            "trace_anchors": [
                {
                    "anchor_kind": "blueprint",
                    "anchor_uri": (
                        "memory://conversation/conv-1/blueprints/"
                        "bp-god-room-runtime/traces/trace-blueprint"
                    ),
                    "proof_level": "contract_proof",
                    "source_refs": ["blueprint:bp-god-room-runtime:1"],
                }
            ]
        },
    )
    tui_path = _write_json(
        tmp_path / "tui-vision.json",
        {
            "execution": {
                "lane_contracts": [{"lane_id": "lane-replay-evidence"}],
                "recovery_decisions": [{"lane_id": "lane-replay-evidence"}],
            },
            "memory": {
                "trace_anchors": [{"trace_id": "trace-blueprint"}],
            },
        },
    )
    speaker_attempt_path = _write_json(
        tmp_path / "speaker-attempt.json",
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
            "provider_session_kind": "provider_thread",
            "provider_binding_status": "active",
            "effective_session_status": "provider_bound_active",
            "blocked_reason": None,
            "source_refs": [
                "god-room-event:evt-propose",
                "god_cli_selection:conv-1",
                "provider_session:provider-thread-review",
            ],
            "provider_attempt": {
                "prompt_contract": "god_room_next_speaker",
                "delivery_mode": "provider_session_resume",
                "requires_fresh_provider_response": True,
            },
        },
    )
    github_path = _write_json(
        tmp_path / "github-truth.json",
        {
            "pull_request_number": 43,
            "merged": False,
            "can_emit_pr_merged": False,
            "head_sha_matches_expected": True,
        },
    )
    readiness_path = _write_json(
        tmp_path / "release-readiness.json",
        {
            "decision": "blocked",
            "blockers": [{"gate_id": "live-memoryos", "reason": "manual_gap"}],
        },
    )
    output = tmp_path / "god-room-runtime-closure-evidence.json"

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=output,
        participants_artifact=participants_path,
        events_artifact=events_path,
        blueprint_freeze_artifact=freeze_path,
        lane_dag_artifact=lane_dag_path,
        memory_trace_artifact=trace_path,
        tui_projection_artifact=tui_path,
        speaker_attempt_artifact=speaker_attempt_path,
        github_truth_artifact=github_path,
        release_readiness_artifact=readiness_path,
    )

    details = evidence["god_room_runtime_closure"]
    assert evidence["schema_version"] == "xmuse.production_evidence.v1"
    assert evidence["stage_id"] == "S8"
    assert evidence["action"] == "god_room_runtime_closure_indexed"
    assert evidence["status"] == "ok"
    assert evidence["proof_level"] == "contract_proof"
    assert evidence["source_authority"] == "god_room_runtime_closure_contract"
    assert details["room_replay"]["status"] == "ok"
    assert details["room_replay"]["event_count"] == 2
    assert details["blueprint_freeze"]["status"] == "frozen"
    assert details["lane_dag"]["lane_contract_count"] == 1
    assert details["lane_dag"]["refactor_required_count"] == 1
    assert details["memory_trace"]["trace_anchor_count"] == 1
    assert details["tui_projection"]["lane_contract_count"] == 1
    assert details["speaker_attempt"]["status"] == "ready_for_provider_attempt"
    assert details["speaker_attempt"]["provider_session_id"] == (
        "provider-thread-review"
    )
    assert details["github_truth"]["merged"] is False
    assert details["github_truth"]["can_emit_pr_merged"] is False
    assert details["github_truth"]["merge_truth"] == "missing"
    assert details["release_readiness"]["decision"] == "blocked"
    assert json.loads(output.read_text(encoding="utf-8")) == evidence


def test_god_room_runtime_closure_evidence_reports_manual_gap_for_missing_room_inputs(
    tmp_path: Path,
) -> None:
    output = tmp_path / "closure-evidence.json"

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=output,
    )

    details = evidence["god_room_runtime_closure"]
    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert "god room participants artifact is missing" in evidence["blocked_reason"]
    assert details["missing_inputs"] == [
        "god_room_participants",
        "god_room_events",
        "blueprint_freeze",
        "lane_dag",
        "memory_trace",
        "tui_projection",
        "github_truth",
        "release_readiness",
    ]


def test_god_room_runtime_closure_evidence_blocks_empty_room_artifacts(
    tmp_path: Path,
) -> None:
    participants = _write_json(tmp_path / "participants.json", {"participants": []})
    events = _write_json(tmp_path / "events.json", {"events": []})

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=tmp_path / "closure-evidence.json",
        participants_artifact=participants,
        events_artifact=events,
    )

    assert evidence["status"] == "manual_gap"
    assert "god room replay requires participants and events" in evidence[
        "blocked_reason"
    ]
    assert evidence["god_room_runtime_closure"]["room_replay"]["status"] == (
        "manual_gap"
    )


def _event(
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
        content=str((payload or {}).get("goal") or "Close the runtime evidence path."),
        causal_parent_id=causal_parent_id,
        source_refs=[f"message:{event_id}"],
        cli_id="codex",
        provider_profile="codex",
        payload=payload or {"body": "Close the runtime evidence path."},
    )


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
