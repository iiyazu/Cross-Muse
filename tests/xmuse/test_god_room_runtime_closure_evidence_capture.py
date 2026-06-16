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
from xmuse_core.platform.local_execution_candidate import (
    load_local_execution_candidate_lineage,
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
            "evt-review-provider-speak",
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-propose",
        ),
        _event(
            "evt-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-review-provider-speak",
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
    speaker_response_path = _write_json(
        tmp_path / "speaker-response.json",
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
            "provider_session_kind": "provider_thread",
            "provider_response_artifact_ref": (
                "reports/provider-responses/provider-response-1.json"
            ),
            "append_status": "created",
            "event_type": "speak",
            "blocked_reason": None,
            "source_refs": [
                "god-room-event:evt-propose",
                "provider_session:provider-thread-review",
                "provider-run:codex:provider-response-1",
            ],
            "speaker_attempt": json.loads(
                speaker_attempt_path.read_text(encoding="utf-8")
            ),
            "provider_response": {
                "schema_version": "xmuse.god_room_provider_speech_response.v1",
                "response_id": "provider-response-1",
                "status": "completed",
                "proof_level": "real_provider_proof",
                "target_participant_id": "part-review",
                "provider_profile_ref": "codex.god",
                "provider_session_id": "provider-thread-review",
                "provider_session_kind": "provider_thread",
                "content": "Review GOD responded from the selected provider session.",
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
                "content": "Review GOD responded from the selected provider session.",
                "target_participant_ids": [],
                "causal_parent_id": "evt-propose",
                "source_refs": [
                    "god-room-event:evt-propose",
                    "provider-run:codex:provider-response-1",
                ],
                "cli_id": "codex",
                "provider_profile": "codex.god",
                "payload": {
                    "body": "Review GOD responded from the selected provider session.",
                    "provider_response_id": "provider-response-1",
                },
            },
        },
    )
    multi_turn_path = _write_json(
        tmp_path / "multi-turn-provider-speech-run.json",
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
            "blocked_reason": None,
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
                    "provider_response": {
                        "response_id": "provider-response-1",
                        "status": "completed",
                    },
                    "speaker_response": json.loads(
                        speaker_response_path.read_text(encoding="utf-8")
                    ),
                }
            ],
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
        speaker_response_artifact=speaker_response_path,
        multi_turn_provider_speech_run_artifact=multi_turn_path,
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
    assert details["room_replay"]["event_count"] == 3
    assert details["blueprint_freeze"]["status"] == "frozen"
    assert details["lane_dag"]["lane_contract_count"] == 1
    assert details["lane_dag"]["refactor_required_count"] == 1
    assert details["memory_trace"]["trace_anchor_count"] == 1
    assert details["tui_projection"]["lane_contract_count"] == 1
    assert details["speaker_attempt"]["status"] == "ready_for_provider_attempt"
    assert details["speaker_attempt"]["provider_session_id"] == (
        "provider-thread-review"
    )
    assert details["speaker_response"]["status"] == "speak_event_appended"
    assert details["speaker_response"]["proof_level"] == "real_provider_proof"
    assert details["speaker_response"]["appended_event_id"] == (
        "evt-review-provider-speak"
    )
    assert details["speaker_response"]["appended_event_type"] == "speak"
    assert details["speaker_response"]["speak_event_id"] == (
        "evt-review-provider-speak"
    )
    assert details["speaker_response"]["provider_response_id"] == (
        "provider-response-1"
    )
    assert details["multi_turn_provider_speech"]["status"] == "completed"
    assert details["multi_turn_provider_speech"]["proof_level"] == "opt_in_live_proof"
    assert details["multi_turn_provider_speech"]["indexed_turn_count"] == 1
    assert details["multi_turn_provider_speech"]["appended_event_ids"] == [
        "evt-review-provider-speak"
    ]
    assert details["multi_turn_provider_speech"]["appended_event_types"] == {
        "speak": 1
    }
    assert details["multi_turn_provider_speech"]["provider_response_artifacts"] == [
        "reports/provider-responses/provider-response-1.json"
    ]
    assert "provider_response_artifact:reports/provider-responses/provider-response-1.json" in (
        evidence["source_refs"]
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


def test_god_room_runtime_closure_evidence_reports_expected_review_chain_gap(
    tmp_path: Path,
) -> None:
    evidence = capture_god_room_runtime_closure_evidence(
        run_id="runtime-closure-review-chain-expected",
        output_path=tmp_path / "evidence.json",
        review_chain_proof_expected=True,
    )

    review_chain = evidence["god_room_runtime_closure"]["review_chain_proof"]
    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert (
        "GOD room review chain proof artifact is expected but missing"
        in evidence["blocked_reason"]
    )
    assert review_chain["status"] == "manual_gap"
    assert review_chain["proof_level"] == "manual_gap"
    assert review_chain["optional"] is False
    assert review_chain["expected"] is True
    assert "god_room_review_chain_proof_artifact_missing" in review_chain[
        "manual_gaps"
    ]
    assert "worker_output_is_review_truth" in review_chain["forbidden_claims"]


def test_god_room_runtime_closure_evidence_rejects_unready_review_handoff(
    tmp_path: Path,
) -> None:
    review_closure = _write_json(
        tmp_path / "review-closure.json",
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "not_ready",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "candidate_refs": ["worker-candidate:patch-reviewed"],
            "cited_candidate_refs": ["worker-candidate:patch-reviewed"],
            "terminal_review_verdict": {
                "evidence_refs": ["worker-candidate:patch-reviewed"],
            },
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

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="runtime-closure-unready-review-handoff",
        output_path=tmp_path / "evidence.json",
        review_closure_artifact=review_closure,
    )

    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert (
        "GOD room review closure release handoff is not candidate_input_ready"
        in evidence["blocked_reason"]
    )
    assert evidence["god_room_runtime_closure"]["review_closure"]["status"] == (
        "not_ready"
    )


def test_god_room_runtime_closure_evidence_rederives_review_handoff(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    review_closure = _write_json(
        tmp_path / "review-closure.json",
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "candidate_input_ready",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_refs": [
                "worker-candidate:patch-reviewed",
                candidate_ref,
            ],
            "cited_candidate_artifact_refs": [candidate_ref],
            "terminal_review_verdict": {
                "evidence_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            },
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

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="runtime-closure-stale-review-handoff",
        output_path=tmp_path / "evidence.json",
        review_closure_artifact=review_closure,
    )

    review_closure_details = evidence["god_room_runtime_closure"]["review_closure"]
    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert (
        "GOD room review closure current handoff is not gate-ready"
        in evidence["blocked_reason"]
    )
    assert review_closure_details["status"] == "candidate_input_ready"
    assert review_closure_details["current_handoff_gate_ready"] is False
    assert review_closure_details["current_handoff_candidate_artifact_refs"] == []
    assert review_closure_details["current_handoff_source_ref_count"] == 0
    assert candidate_ref not in evidence["source_refs"]


def test_god_room_runtime_closure_evidence_accepts_rederived_review_handoff_refs(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_platform_runner_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    candidate_lineage = load_local_execution_candidate_lineage(
        root=tmp_path,
        artifact_ref=candidate_ref,
        lane_id="lane-runtime-evidence-patch",
        graph_id="graph-runtime",
        conversation_id="conv-runtime",
        required_producer="platform_runner_dispatch",
    )
    review_closure = _write_json(
        tmp_path / "review-closure.json",
        {
            "schema_version": "xmuse.god_room_lane_review_closure.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "execution_truth_status": "candidate_reviewed",
            "server_truth_status": "not_server_truth",
            "release_evidence_handoff_status": "candidate_input_ready",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            "cited_candidate_refs": [
                "worker-candidate:patch-reviewed",
                candidate_ref,
            ],
            "cited_candidate_artifact_refs": [candidate_ref],
            "cited_candidate_artifact_lineage": [candidate_lineage],
            "source_event_lineage": [
                {
                    "event_id": "evt-review-provider-speak",
                    "event_type": "speak",
                    "proof_level": "opt_in_live_proof",
                    "provider_response_artifact_ref": (
                        "reports/provider-responses/provider-response-1.json"
                    ),
                    "source_refs": [
                        "god-room-event:evt-review-provider-speak",
                    ],
                }
            ],
            "terminal_review_verdict": {
                "evidence_refs": ["worker-candidate:patch-reviewed", candidate_ref],
            },
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

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="runtime-closure-ready-review-handoff",
        output_path=tmp_path / "evidence.json",
        review_closure_artifact=review_closure,
    )

    review_closure_details = evidence["god_room_runtime_closure"]["review_closure"]
    assert evidence["status"] == "manual_gap"
    assert review_closure_details["current_handoff_gate_ready"] is True
    assert review_closure_details["handoff_evaluation"]["schema_version"] == (
        "xmuse.review_closure_handoff_evaluation.v1"
    )
    assert review_closure_details["handoff_evaluation"]["status"] == "ready"
    assert review_closure_details["handoff_evaluation"]["candidate_ref_count"] == 2
    assert review_closure_details["handoff_evaluation"]["cited_candidate_ref_count"] == 2
    assert review_closure_details["handoff_evaluation"]["source_event_lineage_count"] == 1
    assert review_closure_details["current_handoff_candidate_artifact_refs"] == [
        candidate_ref
    ]
    assert review_closure_details["current_handoff_source_ref_count"] >= 1
    assert candidate_ref in evidence["source_refs"]
    assert "god-room-event:evt-review-provider-speak" in evidence["source_refs"]


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


def test_god_room_runtime_closure_evidence_rejects_unreplayed_speaker_response(
    tmp_path: Path,
) -> None:
    participants_path = _write_json(
        tmp_path / "participants.json",
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                ).model_dump(mode="json"),
                GodRoomParticipant(
                    participant_id="part-review",
                    god_id="god-review",
                ).model_dump(mode="json"),
            ]
        },
    )
    events_path = _write_json(
        tmp_path / "events.json",
        {"events": [_event("evt-propose").model_dump(mode="json")]},
    )
    speaker_attempt = {
        "schema_version": "xmuse.god_room_speaker_attempt.v1",
        "status": "ready_for_provider_attempt",
        "proof_level": "contract_proof",
        "source_authority": "god_room_event_store+selected_god_runtime_continuity",
        "conversation_id": "conv-1",
        "room_id": "room-1",
        "selected_event_id": "evt-propose",
        "decision_reason": "round_robin",
        "target_participant_id": "part-review",
        "target_god_id": "god-review",
        "provider_profile_ref": "codex.god",
        "provider_session_id": "provider-thread-review",
        "source_refs": ["god-room-event:evt-propose"],
    }
    speaker_response_path = _write_json(
        tmp_path / "speaker-response.json",
        {
            "schema_version": "xmuse.god_room_speaker_response.v1",
            "status": "speak_event_appended",
            "proof_level": "real_provider_proof",
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "selected_event_id": "evt-propose",
            "target_participant_id": "part-review",
            "target_god_id": "god-review",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-review",
            "provider_response_artifact_ref": "reports/provider-response.json",
            "append_status": "created",
            "source_refs": ["god-room-event:evt-propose"],
            "speaker_attempt": speaker_attempt,
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
            "speak_event": _event(
                "evt-review-provider-speak",
                participant_id="part-review",
                god_id="god-review",
                causal_parent_id="evt-propose",
            ).model_dump(mode="json"),
        },
    )

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=tmp_path / "closure-evidence.json",
        participants_artifact=participants_path,
        events_artifact=events_path,
        speaker_response_artifact=speaker_response_path,
    )

    details = evidence["god_room_runtime_closure"]["speaker_response"]
    assert details["status"] == "manual_gap"
    assert details["proof_level"] == "manual_gap"
    assert details["speak_event_id"] == "evt-review-provider-speak"
    assert details["blocked_reason"] == (
        "speaker response appended event is missing from god room events"
    )


def test_god_room_runtime_closure_evidence_indexes_provider_backed_question_response(
    tmp_path: Path,
) -> None:
    participants_path = _write_json(
        tmp_path / "participants.json",
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                ).model_dump(mode="json"),
                GodRoomParticipant(
                    participant_id="part-review",
                    god_id="god-review",
                ).model_dump(mode="json"),
            ]
        },
    )
    question_event = _event(
        "evt-review-provider-question",
        event_type=GodRoomEventKind.QUESTION,
        participant_id="part-review",
        god_id="god-review",
        causal_parent_id="evt-propose",
        target_participant_ids=["part-architect"],
        payload={
            "body": "Can the architect prove this question is provider-backed?",
            "provider_response_id": "provider-response-question-1",
            "provider_response_artifact_ref": (
                "reports/provider-responses/provider-response-question-1.json"
            ),
            "proof_level": "real_provider_proof",
        },
    ).model_copy(
        update={
            "source_refs": [
                "god-room-event:evt-propose",
                "provider_response_artifact:"
                "reports/provider-responses/provider-response-question-1.json",
            ]
        }
    )
    events_path = _write_json(
        tmp_path / "events.json",
        {
            "events": [
                _event("evt-propose").model_dump(mode="json"),
                question_event.model_dump(mode="json"),
            ]
        },
    )
    speaker_attempt = {
        "schema_version": "xmuse.god_room_speaker_attempt.v1",
        "status": "ready_for_provider_attempt",
        "proof_level": "contract_proof",
        "source_authority": "god_room_event_store+selected_god_runtime_continuity",
        "conversation_id": "conv-1",
        "room_id": "room-1",
        "selected_event_id": "evt-propose",
        "decision_reason": "round_robin",
        "target_participant_id": "part-review",
        "target_god_id": "god-review",
        "provider_profile_ref": "codex.god",
        "provider_session_id": "provider-thread-review",
        "source_refs": ["god-room-event:evt-propose"],
    }
    speaker_response_path = _write_json(
        tmp_path / "speaker-response-question.json",
        {
            "schema_version": "xmuse.god_room_speaker_response.v1",
            "status": "event_appended",
            "proof_level": "real_provider_proof",
            "conversation_id": "conv-1",
            "room_id": "room-1",
            "selected_event_id": "evt-propose",
            "target_participant_id": "part-review",
            "target_god_id": "god-review",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-review",
            "provider_response_artifact_ref": (
                "reports/provider-responses/provider-response-question-1.json"
            ),
            "append_status": "created",
            "event_type": "question",
            "target_participant_ids": ["part-architect"],
            "source_refs": ["god-room-event:evt-propose"],
            "speaker_attempt": speaker_attempt,
            "provider_response": {
                "schema_version": "xmuse.god_room_provider_speech_response.v1",
                "response_id": "provider-response-question-1",
                "status": "completed",
                "proof_level": "real_provider_proof",
                "target_participant_id": "part-review",
                "provider_profile_ref": "codex.god",
                "provider_session_id": "provider-thread-review",
                "content": "Can the architect prove this question is provider-backed?",
                "source_refs": ["provider-run:codex:provider-response-question-1"],
            },
            "appended_event": question_event.model_dump(mode="json"),
            "speak_event": None,
        },
    )

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=tmp_path / "closure-evidence.json",
        participants_artifact=participants_path,
        events_artifact=events_path,
        speaker_response_artifact=speaker_response_path,
    )

    details = evidence["god_room_runtime_closure"]["speaker_response"]
    assert details["status"] == "event_appended"
    assert details["proof_level"] == "real_provider_proof"
    assert details["appended_event_id"] == "evt-review-provider-question"
    assert details["appended_event_type"] == "question"
    assert details["speak_event_id"] is None
    assert details["provider_response_id"] == "provider-response-question-1"


def test_god_room_runtime_closure_evidence_rejects_unreplayed_multi_turn_event(
    tmp_path: Path,
) -> None:
    participants_path = _write_json(
        tmp_path / "participants.json",
        {
            "participants": [
                GodRoomParticipant(
                    participant_id="part-architect",
                    god_id="god-architect",
                ).model_dump(mode="json"),
                GodRoomParticipant(
                    participant_id="part-review",
                    god_id="god-review",
                ).model_dump(mode="json"),
            ]
        },
    )
    events_path = _write_json(
        tmp_path / "events.json",
        {"events": [_event("evt-propose").model_dump(mode="json")]},
    )
    multi_turn_path = _write_json(
        tmp_path / "multi-turn-provider-speech-run.json",
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
                    "appended_event_id": "evt-missing-provider-speak",
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

    evidence = capture_god_room_runtime_closure_evidence(
        run_id="overnight-runtime-closure",
        output_path=tmp_path / "closure-evidence.json",
        participants_artifact=participants_path,
        events_artifact=events_path,
        multi_turn_provider_speech_run_artifact=multi_turn_path,
    )

    details = evidence["god_room_runtime_closure"]["multi_turn_provider_speech"]
    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert (
        "multi-turn provider speech run appended event is missing "
        "from god room events: evt-missing-provider-speak"
    ) in evidence["blocked_reason"]
    assert details["status"] == "completed"
    assert details["proof_level"] == "opt_in_live_proof"
    assert details["appended_event_ids"] == ["evt-missing-provider-speak"]


def _event(
    event_id: str,
    *,
    event_type: GodRoomEventKind = GodRoomEventKind.SPEAK,
    participant_id: str = "part-architect",
    god_id: str = "god-architect",
    causal_parent_id: str | None = None,
    target_participant_ids: list[str] | None = None,
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
        target_participant_ids=target_participant_ids or [],
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


def _write_platform_runner_candidate(root: Path, candidate_ref: str) -> None:
    _write_json(
        root / candidate_ref,
        {
            "schema_version": "xmuse.local_execution_candidate.v1",
            "candidate_id": "candidate-lane-runtime-evidence-patch",
            "source_authority": "local_execution_candidate_capture",
            "producer": "platform_runner_dispatch",
            "conversation_id": "conv-runtime",
            "proof_level": "local_runtime_proof",
            "status": "candidate_only",
            "candidate_truth_status": "candidate_only",
            "graph_id": "graph-runtime",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "feature_graph_status_id": "fgs:graph-runtime-feature-runtime:reviewing",
            "feature_graph_status": "reviewing",
            "graph_status_source_authority": "feature_graph_status_store",
            "graph_status_lineage": {
                "source_authority": "feature_graph_status_store",
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": [],
            },
            "lane_id": "lane-runtime-evidence-patch",
            "run_id": "platform-runner:run-1",
            "worker_id": "platform-runner",
            "runner_session_id": "runner-session-1",
            "runner_session_ref": "work/runner_sessions/runner-session-1.json",
            "source_refs": ["worker-candidate:patch-reviewed"],
            "output_refs": [candidate_ref],
            "changed_file_refs": [],
            "verification_refs": [
                "uv run pytest "
                "tests/xmuse/test_god_room_runtime_closure_evidence_capture.py -q",
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


def _write_runner_session(root: Path, candidate_ref: str) -> None:
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
            "graph_id": "graph-runtime",
            "resolution_id": "resolution-runtime",
            "writer_lease_id": "lease-runtime",
            "candidate_artifact_refs": [candidate_ref],
            "candidate_lane_ids": ["lane-runtime-evidence-patch"],
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
