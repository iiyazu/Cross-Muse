from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_bridge import ChatDispatchBridge
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.chat.v14_closure_evidence import (
    collect_v14_closure_evidence,
    validate_v14_closure_evidence,
)
from xmuse_core.platform.dashboard_details import _conversation_runtime_timeline_detail


class _ClosureDispatchGodLayer:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.sent: list[tuple[str, str, str, str, str | None]] = []

    async def ensure_conversation_session(self, **kwargs):
        participant_id = str(kwargs["participant_id"])
        return type("Record", (), {"god_session_id": f"god-{participant_id}"})()

    async def send_message(
        self,
        god_session_id,
        message_type,
        prompt,
        context,
        request_id=None,
    ) -> None:
        self.sent.append((god_session_id, message_type, prompt, context, request_id))

    async def receive_message(self, god_session_id):
        context = json.loads(self.sent[-1][3])
        inbox_item = context["inbox_item"]
        participant_id = context["participant_id"]
        message = ChatStore(self._db_path).add_message(
            inbox_item["conversation_id"],
            author=participant_id,
            role="assistant",
            content="DISPATCH_COMPLETED\nDispatched through execute provider.",
            envelope_type="dispatch_result",
            envelope_json={
                "type": "dispatch_result",
                "source_inbox_item_id": inbox_item["id"],
            },
        )
        ChatInboxStore(self._db_path).mark_read(
            inbox_item["id"],
            responded_message_id=message.id,
        )
        PeerTurnLatencyTraceStore(self._db_path).record_mcp_tool_stage(
            conversation_id=inbox_item["conversation_id"],
            inbox_item_id=inbox_item["id"],
            tool_name="chat_post_message",
            called_at=time.monotonic(),
        )
        return type("Message", (), {"type": "result", "status": "success"})()


def _complete_evidence() -> dict:
    conversation_id = "conv-v14"
    dispatch_inbox_id = "inbox-dispatch-1"
    return {
        "conversation_id": conversation_id,
        "bootstrap": {
            "conversation_id": conversation_id,
            "status": "bootstrapped",
            "preset_id": "architect-review-execute",
            "participant_plan": ["architect", "review", "execute"],
            "apply_id": "bootstrap-apply:conv-v14:proposal",
        },
        "inspector": {
            "conversation": {"id": conversation_id},
            "participants": {
                "summary": {"init": 1, "architect": 1, "review": 1, "execute": 1},
            },
            "collaboration": {
                "runs": [
                    {
                        "run_id": "collab-v14",
                        "status": "done",
                        "orchestration_mode": "peer_consensus",
                        "targets": ["review", "execute"],
                        "response_count": 2,
                        "blocker_count": 1,
                        "responses": [
                            {
                                "response_id": "resp-review",
                                "run_id": "collab-v14",
                                "target": "review",
                                "status": "received",
                                "content": "Review veto was resolved.",
                                "created_at": "2026-06-05T00:00:00Z",
                            },
                            {
                                "response_id": "resp-execute",
                                "run_id": "collab-v14",
                                "target": "execute",
                                "status": "received",
                                "content": (
                                    '{"type":"execute_feasibility_verdict",'
                                    '"status":"executable",'
                                    '"summary":"dispatchable",'
                                    '"evidence_refs":['
                                    '"proposal:proposal-v14",'
                                    '"artifact:lane_graph"]}'
                                ),
                                "created_at": "2026-06-05T00:00:00Z",
                            },
                        ],
                    }
                ],
                "dispatch_gates": [
                    {
                        "event_id": "gate-blocked",
                        "run_id": "collab-v14",
                        "decision": "blocked_active_veto",
                        "proposal_ref": "proposal:proposal-v14",
                        "artifact_ref": "artifact:lane_graph",
                        "execute_confirmed": True,
                        "policy_allows_real_provider": True,
                        "created_at": "2026-06-05T00:00:01Z",
                    },
                    {
                        "event_id": "gate-allowed",
                        "run_id": "collab-v14",
                        "decision": "allowed",
                        "proposal_ref": "proposal:proposal-v14",
                        "artifact_ref": "artifact:lane_graph",
                        "execute_confirmed": True,
                        "policy_allows_real_provider": True,
                        "created_at": "2026-06-05T00:00:03Z",
                    },
                ],
            },
            "blockers": {
                "items": [
                    {
                        "blocker_id": "blocker-v14",
                        "run_id": "collab-v14",
                        "issuer": "review",
                        "severity": "veto",
                        "reason": "Read surface missing blocker state.",
                        "affected_ref": "dispatch:proposal-v14",
                        "suggested_fix": "Expose blocker state.",
                        "active": False,
                        "blocks_dispatch": True,
                        "resolution_evidence": "tui:blocker-state-visible",
                        "resolved_by": "architect",
                        "resolved_at": "2026-06-05T00:00:02Z",
                    }
                ],
            },
            "dispatch_queue": {
                "entries": [
                    {
                        "entry_id": "dispatch-v14",
                        "source": "agent",
                        "target": "execute",
                        "status": "dispatched",
                        "auto_execute": True,
                        "proposal_id": "proposal-v14",
                        "resolution_id": "resolution-v14",
                        "collaboration_run_id": "collab-v14",
                        "artifact_ref": "artifact:lane_graph",
                        "dispatch_policy": "real_provider_allowed",
                        "provider_run_ref": "provider:execute:part-execute",
                        "dispatch_evidence": f"mcp_writeback:{dispatch_inbox_id}",
                    }
                ],
            },
            "peer_latency": {
                "recent_turns": [
                    {
                        "inbox_item_id": dispatch_inbox_id,
                        "target_role": "execute",
                        "delivery_mode": "mcp_writeback",
                        "degraded_reason": None,
                        "stage_timings": {
                            "ray_actor_delivery_start": {"at": 1.0},
                            "codex_app_server_turn_start": {"at": 2.0},
                            "chat_post_message": {"at": 3.0},
                            "trace_persisted": {"at": 4.0},
                        },
                    }
                ],
            },
        },
        "runtime_timeline": {
            "conversation_id": conversation_id,
            "source_authority": "chat_inspector",
            "events": [
                {
                    "event_id": "bootstrap-v14",
                    "event_type": "bootstrap",
                    "status": "bootstrapped",
                },
                {
                    "event_id": "collab-v14",
                    "event_type": "collaboration_run",
                    "status": "done",
                    "refs": {"run_id": "collab-v14"},
                },
                {
                    "event_id": "blocker-v14",
                    "event_type": "blocker_resolved",
                    "status": "resolved",
                    "refs": {"run_id": "collab-v14"},
                },
                {
                    "event_id": "gate-blocked",
                    "event_type": "dispatch_gate",
                    "status": "blocked_active_veto",
                    "refs": {
                        "run_id": "collab-v14",
                        "proposal_ref": "proposal:proposal-v14",
                        "artifact_ref": "artifact:lane_graph",
                    },
                },
                {
                    "event_id": "gate-allowed",
                    "event_type": "dispatch_gate",
                    "status": "allowed",
                    "refs": {
                        "run_id": "collab-v14",
                        "proposal_ref": "proposal:proposal-v14",
                        "artifact_ref": "artifact:lane_graph",
                    },
                },
                {
                    "event_id": "dispatch-v14",
                    "event_type": "dispatch_queue",
                    "status": "dispatched",
                    "refs": {
                        "entry_id": "dispatch-v14",
                        "dispatch_evidence": f"mcp_writeback:{dispatch_inbox_id}",
                    },
                },
                {
                    "event_id": dispatch_inbox_id,
                    "event_type": "provider_writeback",
                    "status": "mcp_writeback",
                    "refs": {
                        "inbox_item_id": dispatch_inbox_id,
                        "dispatch_queue_entry_id": "dispatch-v14",
                    },
                },
            ],
        },
        "runner_operations": {
            "chat_dispatch_bridge": {
                "status": "observed",
                "total": 1,
                "queued": 0,
                "processing": 0,
                "dispatched": 1,
                "failed": 0,
                "latest": {
                    "entry_id": "dispatch-v14",
                    "conversation_id": conversation_id,
                    "status": "dispatched",
                    "source": "agent",
                    "target": "execute",
                    "auto_execute": True,
                    "proposal_id": "proposal-v14",
                    "resolution_id": "resolution-v14",
                    "collaboration_run_id": "collab-v14",
                    "artifact_ref": "artifact:lane_graph",
                    "dispatch_evidence": f"mcp_writeback:{dispatch_inbox_id}",
                },
            },
        },
        "provider_session_reused": True,
        "official_tui_main_path": {
            "conversation_id": conversation_id,
            "changed_paths": [
                "xmuse/tui/slash_commands.py",
                "xmuse/tui/adapter/xmuse_adapter.py",
            ],
            "code_modifications": [
                {
                    "path": "xmuse/tui/slash_commands.py",
                    "dispatch_entry_id": "dispatch-v14",
                    "provider_run_ref": "provider:execute:part-execute",
                    "changed_at": "2026-06-05T00:00:04Z",
                    "before_sha256": "0" * 64,
                    "after_sha256": "1" * 64,
                    "diff_summary": "wired official TUI read-surface commands",
                }
            ],
            "command_events": [
                {
                    "command": command,
                    "conversation_id": conversation_id,
                    "read_surface_authority": "chat_inspector",
                    "surface_ref": "chat_inspector:conv-v14",
                    "created_at": "2026-06-05T00:00:04Z",
                }
                for command in ("/new", "/overview", "/discussion", "/blockers")
            ],
            "runtime_timeline_event_ids": [
                "bootstrap-v14",
                "collab-v14",
                "blocker-v14",
                "gate-blocked",
                "gate-allowed",
                "dispatch-v14",
                dispatch_inbox_id,
            ],
        },
        "terminal_tui_demo": {
            "conversation_id": conversation_id,
            "mode": "terminal",
            "evidence_source": "xmuse_tui_terminal_demo_harness",
            "harness_version": 1,
            "terminal_run_id": "terminal-run-v14",
            "command": "uv run python -m xmuse.tui",
            "exit_code": 0,
            "started_at": "2026-06-05T00:00:04Z",
            "completed_at": "2026-06-05T00:00:08Z",
            "scripted_inputs": [
                "/resume conv-v14",
                "/overview",
                "/discussion",
                "/blockers",
            ],
            "observed_command_events": [
                {
                    "event_id": f"terminal-event-{index}",
                    "terminal_run_id": "terminal-run-v14",
                    "command": command,
                    "conversation_id": conversation_id,
                    "read_surface_authority": "chat_inspector",
                    "surface_ref": "chat_inspector:conv-v14",
                    "created_at": "2026-06-05T00:00:05Z",
                }
                for index, command in enumerate(
                    ("/resume", "/overview", "/discussion", "/blockers"),
                    start=1,
                )
            ],
            "observed_command_event_ids": [
                f"terminal-event-{index}" for index in range(1, 5)
            ],
            "visible_surfaces": [
                "init",
                "overview",
                "discussion",
                "blockers",
                "dispatch",
                "provider_writeback",
                "resume",
            ],
            "runtime_timeline_event_ids": [
                "bootstrap-v14",
                "collab-v14",
                "blocker-v14",
                "gate-blocked",
                "gate-allowed",
                "dispatch-v14",
                dispatch_inbox_id,
            ],
        },
        "process_cleanup": {
            "leftover_codex_app_server": False,
            "leftover_raylet": False,
            "leftover_gcs_server": False,
            "leftover_ray_worker": False,
        },
    }


def test_v14_closure_evidence_accepts_full_structured_runtime_trace() -> None:
    report = validate_v14_closure_evidence(_complete_evidence())

    assert report["ok"] is True
    assert report["missing"] == []
    assert {gate["name"]: gate["ok"] for gate in report["gates"]} == {
        "fresh_bootstrap": True,
        "structured_collaboration": True,
        "review_veto_lifecycle": True,
        "dispatch_gate_lifecycle": True,
        "agent_auto_dispatch": True,
        "real_provider_mcp_writeback": True,
        "tui_dashboard_read_surface": True,
        "restart_resume": True,
        "process_cleanup": True,
        "official_tui_main_path": True,
        "terminal_tui_demo": True,
    }


def test_v14_closure_evidence_rejects_stdout_fallback_and_leftovers() -> None:
    evidence = _complete_evidence()
    evidence["inspector"]["peer_latency"]["recent_turns"][0]["delivery_mode"] = (
        "stdout_fallback"
    )
    evidence["inspector"]["peer_latency"]["recent_turns"][0]["degraded_reason"] = (
        "stdout_fallback"
    )
    evidence["process_cleanup"]["leftover_raylet"] = True

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "real_provider_mcp_writeback" in report["missing"]
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_requires_runner_dispatch_bridge_operations() -> None:
    evidence = _complete_evidence()
    evidence.pop("runner_operations")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "agent_auto_dispatch" in report["missing"]


def test_v14_closure_evidence_rejects_runner_dispatch_conversation_mismatch() -> None:
    evidence = _complete_evidence()
    evidence["runner_operations"]["chat_dispatch_bridge"]["latest"]["conversation_id"] = (
        "conv-other"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "agent_auto_dispatch" in report["missing"]


def test_v14_closure_evidence_rejects_malformed_runner_dispatch_counts() -> None:
    evidence = _complete_evidence()
    evidence["runner_operations"]["chat_dispatch_bridge"]["dispatched"] = "unknown"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "agent_auto_dispatch" in report["missing"]


def test_v14_closure_evidence_requires_terminal_tui_demo() -> None:
    evidence = _complete_evidence()
    evidence.pop("terminal_tui_demo")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_textual_run_test_as_terminal_demo() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["mode"] = "textual_run_test"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_non_launch_terminal_demo_command() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["command"] = "echo xmuse.tui"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_boolean_terminal_demo_exit_code() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["exit_code"] = False

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_requires_terminal_demo_harness_provenance() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"].pop("evidence_source")
    evidence["terminal_tui_demo"].pop("harness_version")
    evidence["terminal_tui_demo"].pop("scripted_inputs")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_incomplete_terminal_demo_script() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["scripted_inputs"] = [
        "/resume conv-v14",
        "/overview",
        "/discussion",
    ]

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_terminal_demo_script_with_empty_extra() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["scripted_inputs"].append("")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_requires_terminal_run_command_events() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"].pop("observed_command_events")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_terminal_run_id_mismatch() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["observed_command_events"][0]["terminal_run_id"] = (
        "other-run"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_rejects_terminal_command_event_outside_run_window() -> None:
    evidence = _complete_evidence()
    evidence["terminal_tui_demo"]["observed_command_events"][0]["created_at"] = (
        "2026-06-05T00:00:03Z"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_evidence_accepts_runner_cleanup_health_payload() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "status": "clean",
        "leftovers": [],
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is True, report


def test_v14_closure_evidence_rejects_runner_cleanup_leftovers() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "status": "dirty",
        "leftovers": [
            {
                "code": "leftover_codex_app_server",
                "service": "codex_app_server",
                "count": 1,
                "action": "report_only",
            },
            {
                "code": "leftover_ray_worker",
                "service": "ray_worker",
                "count": 2,
                "action": "report_only",
            },
        ],
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_rejects_dirty_runner_cleanup_without_leftover_rows() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "status": "dirty",
        "leftovers": [],
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_rejects_contradictory_mixed_cleanup_payload() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "leftover_codex_app_server": False,
        "leftover_raylet": False,
        "leftover_gcs_server": False,
        "leftover_ray_worker": False,
        "status": "dirty",
        "leftovers": [
            {
                "code": "leftover_unknown_service",
                "service": "unknown_service",
                "count": 1,
                "action": "report_only",
            },
        ],
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_rejects_malformed_mixed_cleanup_payload() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "leftover_codex_app_server": False,
        "leftover_raylet": False,
        "leftover_gcs_server": False,
        "leftover_ray_worker": False,
        "status": "dirty",
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_rejects_non_dict_runner_cleanup_leftover_rows() -> None:
    evidence = _complete_evidence()
    evidence["process_cleanup"] = {
        "status": "clean",
        "leftovers": ["leftover_raylet"],
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "process_cleanup" in report["missing"]


def test_v14_closure_evidence_rejects_stitched_unrelated_runtime_evidence() -> None:
    evidence = _complete_evidence()
    evidence["inspector"]["dispatch_queue"]["entries"][0]["collaboration_run_id"] = (
        "collab-other"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "agent_auto_dispatch" in report["missing"]
    assert "real_provider_mcp_writeback" in report["missing"]


def test_v14_closure_evidence_rejects_allowed_gate_before_veto_resolution() -> None:
    evidence = _complete_evidence()
    evidence["inspector"]["collaboration"]["dispatch_gates"][1]["created_at"] = (
        "2026-06-05T00:00:01Z"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "dispatch_gate_lifecycle" in report["missing"]


def test_v14_closure_evidence_rejects_weak_collaboration_and_hollow_writeback() -> None:
    evidence = _complete_evidence()
    run = evidence["inspector"]["collaboration"]["runs"][0]
    run["responses"] = []
    turn = evidence["inspector"]["peer_latency"]["recent_turns"][0]
    turn["target_role"] = "architect"
    turn["stage_timings"]["chat_post_message"] = {}

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "structured_collaboration" in report["missing"]
    assert "real_provider_mcp_writeback" in report["missing"]


def test_v14_closure_evidence_rejects_boolean_mcp_stage_timing() -> None:
    evidence = _complete_evidence()
    turn = evidence["inspector"]["peer_latency"]["recent_turns"][0]
    turn["stage_timings"]["ray_actor_delivery_start"]["at"] = True

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "real_provider_mcp_writeback" in report["missing"]


def test_v14_closure_evidence_rejects_infinite_mcp_stage_timing() -> None:
    evidence = _complete_evidence()
    turn = evidence["inspector"]["peer_latency"]["recent_turns"][0]
    turn["stage_timings"]["trace_persisted"]["at"] = float("inf")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "real_provider_mcp_writeback" in report["missing"]


def test_v14_closure_evidence_rejects_nan_mcp_stage_timing() -> None:
    evidence = _complete_evidence()
    turn = evidence["inspector"]["peer_latency"]["recent_turns"][0]
    turn["stage_timings"]["trace_persisted"]["at"] = float("nan")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "real_provider_mcp_writeback" in report["missing"]


def test_v14_closure_evidence_rejects_freeform_execute_response() -> None:
    evidence = _complete_evidence()
    responses = evidence["inspector"]["collaboration"]["runs"][0]["responses"]
    responses[1]["content"] = "looks executable to me"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "structured_collaboration" in report["missing"]


def test_v14_closure_evidence_rejects_blocked_execute_verdict() -> None:
    evidence = _complete_evidence()
    responses = evidence["inspector"]["collaboration"]["runs"][0]["responses"]
    responses[1]["content"] = (
        '{"type":"execute_feasibility_verdict",'
        '"status":"blocked",'
        '"summary":"not dispatchable",'
        '"evidence_refs":["proposal:proposal-v14"]}'
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "structured_collaboration" in report["missing"]


def test_v14_closure_evidence_rejects_execute_verdict_for_wrong_proposal() -> None:
    evidence = _complete_evidence()
    responses = evidence["inspector"]["collaboration"]["runs"][0]["responses"]
    responses[1]["content"] = (
        '{"type":"execute_feasibility_verdict",'
        '"status":"executable",'
        '"summary":"dispatchable",'
        '"evidence_refs":["proposal:other"]}'
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "structured_collaboration" in report["missing"]


def test_v14_closure_evidence_rejects_malformed_gate_timestamps() -> None:
    evidence = _complete_evidence()
    evidence["inspector"]["collaboration"]["dispatch_gates"][0]["created_at"] = "a"
    evidence["inspector"]["blockers"]["items"][0]["resolved_at"] = "b"
    evidence["inspector"]["collaboration"]["dispatch_gates"][1]["created_at"] = "c"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "dispatch_gate_lifecycle" in report["missing"]


def test_v14_closure_evidence_rejects_naive_gate_timestamps() -> None:
    evidence = _complete_evidence()
    evidence["inspector"]["collaboration"]["dispatch_gates"][0]["created_at"] = (
        "2026-06-05T00:00:01"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "dispatch_gate_lifecycle" in report["missing"]


def test_v14_closure_evidence_rejects_uncorrelated_runtime_timeline() -> None:
    evidence = _complete_evidence()
    evidence["runtime_timeline"]["conversation_id"] = "conv-other"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "tui_dashboard_read_surface" in report["missing"]


def test_v14_closure_evidence_rejects_tui_proof_missing_chain_event_ids() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"]["runtime_timeline_event_ids"] = [
        "bootstrap-v14",
        "collab-v14",
        "gate-blocked",
        "gate-allowed",
    ]

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_tui_proof_with_unlinked_surface_ref() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"]["command_events"][0]["surface_ref"] = (
        "runtime-timeline:unlinked"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_tui_proof_authority_surface_mismatch() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"]["command_events"][0]["read_surface_authority"] = (
        "chat_inspector"
    )
    evidence["official_tui_main_path"]["command_events"][0]["surface_ref"] = (
        "dashboard_runtime_timeline:conv-v14"
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_bare_tui_main_path_boolean() -> None:
    evidence = _complete_evidence()
    evidence.pop("official_tui_main_path")
    evidence["official_tui_main_path_modified"] = True

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_weak_tui_command_proof() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"] = {
        "changed_paths": ["xmuse/tui/slash_commands.py"],
        "exercised_commands": ["/new", "/overview", "/discussion", "/blockers"],
        "read_surface_authority": "chat_inspector",
    }

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_tui_path_without_code_modifications() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"].pop("code_modifications")

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_code_modification_outside_formal_tui_path() -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"]["code_modifications"][0]["path"] = "README.md"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


@pytest.mark.parametrize(
    "field",
    [
        "dispatch_entry_id",
        "provider_run_ref",
        "changed_at",
        "before_sha256",
        "after_sha256",
        "diff_summary",
    ],
)
def test_v14_closure_evidence_rejects_incomplete_tui_code_modification(
    field: str,
) -> None:
    evidence = _complete_evidence()
    evidence["official_tui_main_path"]["code_modifications"][0].pop(field)

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_uncorrelated_tui_code_modification() -> None:
    evidence = _complete_evidence()
    modification = evidence["official_tui_main_path"]["code_modifications"][0]
    modification["dispatch_entry_id"] = "dispatch-other"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_evidence_rejects_stale_tui_command_proof() -> None:
    evidence = _complete_evidence()
    for event in evidence["official_tui_main_path"]["command_events"]:
        event["created_at"] = "2026-06-04T23:59:59Z"

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "official_tui_main_path" in report["missing"]


def test_v14_closure_collector_uses_official_surfaces_for_validator_payload(
    tmp_path: Path,
) -> None:
    conversation_id = _build_official_surface_closure_fixture(tmp_path)
    timeline = _conversation_runtime_timeline_detail(tmp_path, conversation_id)
    timeline_event_ids = [
        str(event["event_id"])
        for event in timeline["events"]
        if str(event.get("event_id") or "").strip()
    ]
    _write_terminal_tui_demo(tmp_path, conversation_id, timeline_event_ids)

    evidence = collect_v14_closure_evidence(
        xmuse_root=tmp_path,
        conversation_id=conversation_id,
        provider_session_reused=True,
        official_tui_main_path={
            "changed_paths": [
                "xmuse/tui/slash_commands.py",
                "xmuse/tui/adapter/xmuse_adapter.py",
            ],
            "code_modifications": _official_tui_code_modifications(
                tmp_path,
                conversation_id,
            ),
            "command_events": [
                {
                    "command": command,
                    "conversation_id": conversation_id,
                    "read_surface_authority": "chat_inspector",
                    "surface_ref": f"chat_inspector:{conversation_id}",
                    "created_at": "2099-01-01T00:00:00Z",
                }
                for command in ("/new", "/overview", "/discussion", "/blockers")
            ],
            "runtime_timeline_event_ids": timeline_event_ids,
        },
        process_cleanup={
            "leftover_codex_app_server": False,
            "leftover_raylet": False,
            "leftover_gcs_server": False,
            "leftover_ray_worker": False,
        },
    )

    assert evidence["conversation_id"] == conversation_id
    assert evidence["inspector"]["conversation"]["id"] == conversation_id
    assert evidence["runtime_timeline"]["source_authority"] == "chat_inspector"
    assert validate_v14_closure_evidence(evidence)["ok"] is True


def test_v14_closure_collector_rejects_terminal_demo_without_run_events(
    tmp_path: Path,
) -> None:
    conversation_id = _build_official_surface_closure_fixture(tmp_path)
    timeline = _conversation_runtime_timeline_detail(tmp_path, conversation_id)
    timeline_event_ids = [
        str(event["event_id"])
        for event in timeline["events"]
        if str(event.get("event_id") or "").strip()
    ]
    _write_terminal_tui_demo(tmp_path, conversation_id, timeline_event_ids)
    (tmp_path / "tui_command_events.json").unlink()

    evidence = collect_v14_closure_evidence(
        xmuse_root=tmp_path,
        conversation_id=conversation_id,
        provider_session_reused=True,
        official_tui_main_path={
            "changed_paths": [
                "xmuse/tui/slash_commands.py",
                "xmuse/tui/adapter/xmuse_adapter.py",
            ],
            "command_events": [
                {
                    "command": command,
                    "conversation_id": conversation_id,
                    "read_surface_authority": "chat_inspector",
                    "surface_ref": f"chat_inspector:{conversation_id}",
                    "created_at": "2099-01-01T00:00:00Z",
                }
                for command in ("/new", "/overview", "/discussion", "/blockers")
            ],
            "runtime_timeline_event_ids": timeline_event_ids,
        },
        process_cleanup={
            "leftover_codex_app_server": False,
            "leftover_raylet": False,
            "leftover_gcs_server": False,
            "leftover_ray_worker": False,
        },
    )

    report = validate_v14_closure_evidence(evidence)

    assert report["ok"] is False
    assert "terminal_tui_demo" in report["missing"]


def test_v14_closure_collector_uses_persisted_tui_command_proof(
    tmp_path: Path,
) -> None:
    conversation_id = _build_official_surface_closure_fixture(tmp_path)
    timeline = _conversation_runtime_timeline_detail(tmp_path, conversation_id)
    timeline_event_ids = [
        str(event["event_id"])
        for event in timeline["events"]
        if str(event.get("event_id") or "").strip()
    ]
    _write_terminal_tui_demo(tmp_path, conversation_id, timeline_event_ids)
    terminal_events = json.loads(
        (tmp_path / "tui_command_events.json").read_text(encoding="utf-8")
    )["command_events"]
    (tmp_path / "tui_command_events.json").write_text(
        json.dumps(
            {
                "command_events": terminal_events + [
                    {
                        "command": command,
                        "conversation_id": conversation_id,
                        "read_surface_authority": "chat_inspector",
                        "surface_ref": f"chat_inspector:{conversation_id}",
                        "created_at": "2099-01-01T00:00:00Z",
                    }
                    for command in ("/new", "/overview", "/discussion", "/blockers")
                ]
            }
        ),
        encoding="utf-8",
    )

    evidence = collect_v14_closure_evidence(
        xmuse_root=tmp_path,
        conversation_id=conversation_id,
        provider_session_reused=True,
        official_tui_main_path={
            "changed_paths": ["xmuse/tui/slash_commands.py"],
            "code_modifications": _official_tui_code_modifications(
                tmp_path,
                conversation_id,
            ),
        },
        process_cleanup={
            "leftover_codex_app_server": False,
            "leftover_raylet": False,
            "leftover_gcs_server": False,
            "leftover_ray_worker": False,
        },
    )

    official_command_events = [
        event
        for event in evidence["official_tui_main_path"]["command_events"]
        if not event.get("terminal_run_id")
    ]
    assert [
        event["command"]
        for event in official_command_events
    ] == ["/new", "/overview", "/discussion", "/blockers"]
    assert evidence["official_tui_main_path"]["runtime_timeline_event_ids"]
    assert validate_v14_closure_evidence(evidence)["ok"] is True


@pytest.mark.asyncio
async def test_v14_closure_collector_accepts_official_api_approval_and_dispatch_bridge(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={
            "title": "V14 official API closure",
            "init_mode": "deterministic",
        },
    )
    assert created.status_code == 201
    conversation = created.json()
    conversation_id = conversation["id"]
    architect = next(
        participant
        for participant in conversation["participants"]
        if participant["role"] == "architect"
    )

    run_response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/requests",
        json={
            "goal": "Prove V14 official API closure.",
            "initiator": "architect",
            "targets": ["review", "execute"],
            "callback_target": "architect",
            "question": "Review and confirm execute feasibility.",
            "context_refs": ["artifact:lane_graph"],
            "idempotency_key": "v14-official-api-closure",
            "timeout_s": 480,
            "orchestration_mode": "peer_consensus",
        },
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["run"]["run_id"]

    proposal_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": architect["participant_id"],
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Official API closure path",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-official-api-closure",
                            "prompt": "Exercise official V14 closure read surfaces.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                    "resolution_content": {
                        "type": "lane_graph",
                        "summary": "Official API closure path",
                        "lanes": [
                            {
                                "feature_id": "lane-v14-official-api-closure",
                                "prompt": "Exercise official V14 closure read surfaces.",
                                "depends_on": [],
                                "capabilities": ["code"],
                            }
                        ],
                    },
                }
            ),
            "references": [f"collaboration:{run_id}"],
        },
    )
    assert proposal_response.status_code == 201
    proposal_id = proposal_response.json()["id"]

    review_response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/responses",
        json={
            "target": "review",
            "content": "Review requires blocker state before dispatch.",
            "status": "received",
        },
    )
    assert review_response.status_code == 200
    execute_response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/responses",
        json={
            "target": "execute",
            "content": json.dumps(
                {
                    "type": "execute_feasibility_verdict",
                    "status": "executable",
                    "summary": "Official API closure can dispatch.",
                    "evidence_refs": [
                        f"proposal:{proposal_id}",
                        "artifact:lane_graph",
                    ],
                }
            ),
            "status": "received",
        },
    )
    assert execute_response.status_code == 200

    blocker_response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/blockers",
        json={
            "issuer": "review",
            "severity": "veto",
            "reason": "Blocker visibility must be proven before dispatch.",
            "affected_ref": f"proposal:{proposal_id}",
            "suggested_fix": "Exercise official TUI/read surfaces.",
            "blocks_dispatch": True,
        },
    )
    assert blocker_response.status_code == 201
    blocker_id = blocker_response.json()["blocker"]["blocker_id"]

    blocked_approval = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["architect", "review", "execute"],
            "approval_mode": "auto",
            "goal_summary": "Blocked V14 closure approval.",
            "content": {"type": "lane_graph", "title": "Official API closure path"},
        },
    )
    assert blocked_approval.status_code == 400
    assert blocked_approval.json()["detail"] == {
        "code": "dispatch_gate_blocked",
        "message": "blocked_active_veto",
    }

    resolved = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/blockers/{blocker_id}/resolve",
        json={
            "resolved_by": "architect",
            "resolution_evidence": "tui:overview-discussion-blockers-read-surface",
        },
    )
    assert resolved.status_code == 200

    approved = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["architect", "review", "execute"],
            "approval_mode": "auto",
            "goal_summary": "Approved V14 official API closure lane graph.",
            "content": {"type": "lane_graph", "title": "Official API closure path"},
        },
    )
    assert approved.status_code == 200

    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=_ClosureDispatchGodLayer(tmp_path / "chat.db"),
        worktree=tmp_path,
        bridge_id="v14-official-api-closure",
        response_wait_s=0.5,
    )
    dispatch_outcome = await bridge.tick_once(conversation_id=conversation_id)
    assert dispatch_outcome.claimed == 1
    assert dispatch_outcome.dispatched == 1

    timeline = _conversation_runtime_timeline_detail(tmp_path, conversation_id)
    timeline_event_ids = [
        str(event["event_id"])
        for event in timeline["events"]
        if str(event.get("event_id") or "").strip()
    ]
    _write_terminal_tui_demo(tmp_path, conversation_id, timeline_event_ids)
    evidence = collect_v14_closure_evidence(
        xmuse_root=tmp_path,
        conversation_id=conversation_id,
        provider_session_reused=True,
        official_tui_main_path={
            "changed_paths": [
                "xmuse/tui/slash_commands.py",
                "xmuse/tui/adapter/xmuse_adapter.py",
            ],
            "code_modifications": _official_tui_code_modifications(
                tmp_path,
                conversation_id,
            ),
            "command_events": [
                {
                    "command": command,
                    "conversation_id": conversation_id,
                    "read_surface_authority": "chat_inspector",
                    "surface_ref": f"chat_inspector:{conversation_id}",
                    "created_at": "2099-01-01T00:00:00Z",
                }
                for command in ("/new", "/overview", "/discussion", "/blockers")
            ],
            "runtime_timeline_event_ids": timeline_event_ids,
        },
        process_cleanup={
            "leftover_codex_app_server": False,
            "leftover_raylet": False,
            "leftover_gcs_server": False,
            "leftover_ray_worker": False,
        },
    )

    report = validate_v14_closure_evidence(evidence)
    assert report["ok"] is True, report


def test_conversation_inspector_exposes_collaboration_responses_for_closure_evidence(
    tmp_path: Path,
) -> None:
    conversation_id = _build_official_surface_closure_fixture(tmp_path)

    inspector = build_conversation_inspector_payload(conversation_id, tmp_path)

    run = inspector["collaboration"]["runs"][0]
    assert run["response_count"] == 2
    responses = run["responses"]
    assert [
        {
            "target": response["target"],
            "status": response["status"],
        }
        for response in responses
    ] == [
        {
            "target": "review",
            "status": "received",
        },
        {
            "target": "execute",
            "status": "received",
        },
    ]
    assert responses[0]["content"] == "Resolved after blocker visibility was added."
    assert responses[0]["run_id"] == run["run_id"]
    assert responses[0]["response_id"].startswith("collab_resp_")
    assert responses[0]["created_at"]
    execute_verdict = json.loads(responses[1]["content"])
    assert execute_verdict["type"] == "execute_feasibility_verdict"
    assert execute_verdict["status"] == "executable"
    assert execute_verdict["summary"] == "dispatchable"
    assert any(
        str(ref).startswith("proposal:") for ref in execute_verdict["evidence_refs"]
    )
    assert "artifact:lane_graph" in execute_verdict["evidence_refs"]


def _write_terminal_tui_demo(
    root: Path,
    conversation_id: str,
    timeline_event_ids: list[str],
) -> None:
    terminal_run_id = "terminal-run-v14"
    command_events = [
        {
            "event_id": f"terminal-event-{index}",
            "terminal_run_id": terminal_run_id,
            "command": command,
            "conversation_id": conversation_id,
            "read_surface_authority": "chat_inspector",
            "surface_ref": f"chat_inspector:{conversation_id}",
            "created_at": "2099-01-01T00:00:01Z",
        }
        for index, command in enumerate(
            ("/resume", "/overview", "/discussion", "/blockers"),
            start=1,
        )
    ]
    (root / "tui_command_events.json").write_text(
        json.dumps({"command_events": command_events}),
        encoding="utf-8",
    )
    (root / "tui_terminal_demo.json").write_text(
        json.dumps(
            {
                "terminal_tui_demo": {
                    "conversation_id": conversation_id,
                    "mode": "terminal",
                    "evidence_source": "xmuse_tui_terminal_demo_harness",
                    "harness_version": 1,
                    "terminal_run_id": terminal_run_id,
                    "command": "uv run python -m xmuse.tui",
                    "exit_code": 0,
                    "started_at": "2099-01-01T00:00:00Z",
                    "completed_at": "2099-01-01T00:00:05Z",
                    "scripted_inputs": [
                        f"/resume {conversation_id}",
                        "/overview",
                        "/discussion",
                        "/blockers",
                    ],
                    "observed_command_event_ids": [
                        event["event_id"] for event in command_events
                    ],
                    "observed_command_events": command_events,
                    "visible_surfaces": [
                        "init",
                        "overview",
                        "discussion",
                        "blockers",
                        "dispatch",
                        "provider_writeback",
                        "resume",
                    ],
                    "runtime_timeline_event_ids": timeline_event_ids,
                },
            }
        ),
        encoding="utf-8",
    )


def _official_tui_code_modifications(
    root: Path,
    conversation_id: str,
) -> list[dict[str, str]]:
    entry = next(
        item
        for item in ChatDispatchQueueStore(root / "chat.db").list_entries(conversation_id)
        if item.status == "dispatched"
    )
    return [
        {
            "path": "xmuse/tui/slash_commands.py",
            "dispatch_entry_id": entry.entry_id,
            "provider_run_ref": str(entry.provider_run_ref),
            "changed_at": "2099-01-01T00:00:00Z",
            "before_sha256": "0" * 64,
            "after_sha256": "1" * 64,
            "diff_summary": "wired official TUI read-surface commands",
        }
    ]


def _build_official_surface_closure_fixture(tmp_path: Path) -> str:
    db_path = tmp_path / "chat.db"
    peer = PeerChatService(db_path)
    created = peer.create_conversation(
        title="V14 official surface closure",
        init_mode="deterministic",
    )
    conversation_id = str(created["conversation"]["id"])
    participants = created["participants"]
    architect = next(item for item in participants if item["role"] == "architect")

    collaboration = ChatCollaborationStore(db_path)
    run = collaboration.create_request(
        conversation_id=conversation_id,
        goal="Prove V14 TUI runtime closure evidence.",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Review and confirm execute feasibility.",
        context_refs=["artifact:lane_graph"],
        idempotency_key="v14-official-surface",
        timeout_s=480,
    )
    proposal = ChatStore(db_path).create_proposal(
        conversation_id=conversation_id,
        author=str(architect["participant_id"]),
        proposal_type="lane_graph",
        content=json.dumps(
            {
                "type": "lane_graph",
                "resolution_content": {
                    "type": "lane_graph",
                    "title": "TUI runtime closure path",
                },
            }
        ),
        references=[f"collaboration:{run.run_id}"],
    )
    collaboration.record_response(
        run.run_id,
        target="review",
        content="Resolved after blocker visibility was added.",
        response_status="received",
    )
    collaboration.record_response(
        run.run_id,
        target="execute",
        content=(
            '{"type":"execute_feasibility_verdict",'
            '"status":"executable",'
            '"summary":"dispatchable",'
            f'"evidence_refs":["proposal:{proposal.id}","artifact:lane_graph"]'
            "}"
        ),
        response_status="received",
    )
    blocker = collaboration.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Blocker state is not visible enough.",
        affected_ref=f"proposal:{proposal.id}",
        suggested_fix="Expose blocker state through official read surfaces.",
        blocks_dispatch=True,
    )
    collaboration.evaluate_dispatch_gate(
        conversation_id=conversation_id,
        run_id=run.run_id,
        proposal_ref=f"proposal:{proposal.id}",
        artifact_ref="artifact:lane_graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )
    collaboration.resolve_blocker(
        blocker.blocker_id,
        resolved_by="architect",
        resolution_evidence="tui:blockers-command-and-runtime-card",
    )
    collaboration.evaluate_dispatch_gate(
        conversation_id=conversation_id,
        run_id=run.run_id,
        proposal_ref=f"proposal:{proposal.id}",
        artifact_ref="artifact:lane_graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )
    _pin_v14_fixture_times(db_path, blocker.blocker_id)

    resolution = ChatStore(db_path).approve_proposal(
        proposal.id,
        approved_by=["architect", "review", "execute"],
        approval_mode="auto",
        goal_summary="Approved V14 closure lane graph.",
        content={"type": "lane_graph", "title": "TUI runtime closure path"},
    )
    queue = ChatDispatchQueueStore(db_path)
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id=run.run_id,
        artifact_ref="artifact:lane_graph",
    )
    queue.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="v14-test-bridge",
    )
    inbox_id = "inbox-v14-dispatch"
    queue.mark_dispatched(
        entry.entry_id,
        provider_run_ref="provider:execute:part-execute",
        dispatch_evidence=f"mcp_writeback:{inbox_id}",
    )
    PeerTurnLatencyTraceStore(db_path).record(
        conversation_id=conversation_id,
        inbox_item_id=inbox_id,
        participant_id="part-execute",
        target_role="execute",
        message_created_at="2026-06-05T00:00:03Z",
        inbox_claimed_at="2026-06-05T00:00:03Z",
        delivery_started_at=1.0,
        provider_turn_started_at=2.0,
        first_delta_at=None,
        writeback_at=4.0,
        total_latency_ms=3000,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        stage_timings={
            "ray_actor_delivery_start": {"at": 1.0},
            "codex_app_server_turn_start": {"at": 2.0},
            "chat_post_message": {"at": 3.0},
            "trace_persisted": {"at": 4.0},
        },
    )
    return conversation_id


def _pin_v14_fixture_times(db_path: Path, blocker_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            update collaboration_responses
            set created_at = '2026-06-05T00:00:02Z'
            """
        )
        conn.execute(
            """
            update collaboration_dispatch_gate_events
            set created_at = '2026-06-05T00:00:01Z'
            where decision = 'blocked_active_veto'
            """
        )
        conn.execute(
            """
            update collaboration_blockers
            set resolved_at = '2026-06-05T00:00:02Z'
            where blocker_id = ?
            """,
            (blocker_id,),
        )
        conn.execute(
            """
            update collaboration_dispatch_gate_events
            set created_at = '2026-06-05T00:00:03Z'
            where decision = 'allowed'
            """
        )
