"""Widget tests."""
from rich.panel import Panel

from xmuse.tui.widgets.blueprint_freeze_panel import render_blueprint_freeze_panel
from xmuse.tui.widgets.card_renderer import CARD_STYLES, render_card
from xmuse.tui.widgets.deliberation_cockpit import render_deliberation_cockpit
from xmuse.tui.widgets.execution_cockpit import render_execution_cockpit
from xmuse.tui.widgets.github_truth_panel import render_github_truth_panel
from xmuse.tui.widgets.memory_trace_drawer import render_memory_trace_drawer
from xmuse.tui.widgets.message_log import MessageLog
from xmuse.tui.widgets.proof_cockpit import render_proof_cockpit


def test_render_card_returns_panel():
    card = {"card_type": "run_progress", "summary": "3/5 merged"}
    result = render_card(card)
    assert isinstance(result, Panel)


def test_render_card_no_drill():
    card = {"card_type": "run_terminal", "summary": "done"}
    result = render_card(card)
    assert isinstance(result, Panel)


def test_render_card_default_style():
    card = {"card_type": "unknown_type", "summary": "test"}
    result = render_card(card)
    assert isinstance(result, Panel)


def test_render_card_prefers_card_title_for_peer_status():
    card = {
        "card_type": "peer_pending",
        "title": "Architect GOD is thinking",
        "summary": "Architect GOD 正在处理这条消息。",
    }

    result = render_card(card)

    assert "Architect GOD is thinking" in str(result.title)


def test_runtime_closure_card_types_have_explicit_styles():
    for card_type in [
        "runtime_bootstrap",
        "runtime_discussion",
        "runtime_blocker",
        "runtime_dispatch_gate",
        "runtime_dispatch_queue",
        "runtime_provider_writeback",
    ]:
        assert card_type in CARD_STYLES


def test_message_log_writes_message_body_with_content_width(monkeypatch):
    log = MessageLog()
    writes = []

    class _Size:
        width = 42

    monkeypatch.setattr(type(log), "size", property(lambda self: _Size()))
    monkeypatch.setattr(log, "scroll_end", lambda animate=False: None)

    def _write(content, width=None, expand=False, shrink=True, scroll_end=None, animate=False):
        writes.append({"content": content, "width": width})
        return log

    monkeypatch.setattr(log, "write", _write)

    log.append_message(
        author="architect-god",
        role="assistant",
        content="this is a very long message that should wrap inside the center pane",
    )

    assert writes[1]["width"] == 40


def test_message_log_enables_wrapped_selectable_text():
    log = MessageLog()

    assert log.wrap is True
    assert log.allow_select is True


def test_deliberation_cockpit_renders_speech_acts_and_blockers() -> None:
    panel = render_deliberation_cockpit(
        {
            "deliberation": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "speech_act_counts": {"challenge": 1, "propose": 1},
                "blockers": [
                    {
                        "message_id": "msg-challenge",
                        "speech_act": "challenge",
                        "reason": "acceptance criteria are missing",
                        "target_refs": ["blueprint:conv-1:1"],
                        "source_refs": ["message:msg-propose"],
                    }
                ],
                "target_refs": ["blueprint:conv-1:1"],
                "source_refs": ["message:msg-propose", "message:msg-challenge"],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "contract_proof" in rendered
    assert "blocked" in rendered
    assert "challenge: 1" in rendered
    assert "acceptance criteria are missing" in rendered
    assert "blueprint:conv-1:1" in rendered


def test_deliberation_cockpit_renders_manual_gap() -> None:
    panel = render_deliberation_cockpit(None)

    rendered = panel.renderable.plain
    assert "manual_gap" in rendered
    assert "No deliberation evidence" in rendered


def test_blueprint_freeze_panel_renders_readiness_without_freeze_fact() -> None:
    panel = render_blueprint_freeze_panel(
        {
            "blueprint_freeze": {
                "proof_level": "contract_proof",
                "fact_state": "ready_to_freeze",
                "ready_to_freeze": True,
                "frozen": False,
                "source_refs": ["message:msg-decide"],
                "target_refs": ["blueprint:conv-1:1"],
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "ready_to_freeze" in rendered
    assert "Frozen: no" in rendered
    assert "message:msg-decide" in rendered
    assert "blueprint:conv-1:1" in rendered


def test_execution_cockpit_renders_lane_dag_and_blockers() -> None:
    panel = render_execution_cockpit(
        {
            "execution": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "lane_count": 2,
                "ready_lane_ids": ["lane-a"],
                "blocked_lane_ids": ["lane-b"],
                "dependency_edges": [{"lane_id": "lane-b", "depends_on": ["lane-a"]}],
                "blockers": [{"lane_id": "lane-b", "reason": "needs review evidence"}],
                "review_items": [
                    {
                        "lane_id": "lane-b",
                        "decision": "rework",
                        "summary": "Review found missing evidence.",
                        "verdict_id": "verdict-b",
                    }
                ],
                "patch_forward_lineage": [
                    {"source_lane_id": "lane-b", "patch_lane_id": "lane-c"}
                ],
                "target_refs": ["lane:lane-a", "lane:lane-b", "graph:graph-1"],
                "source_refs": ["feature_lanes_projection#projection_revision=7"],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "blocked" in rendered
    assert "Lanes: 2" in rendered
    assert "lane-b <- lane-a" in rendered
    assert "needs review evidence" in rendered
    assert "lane-b rework" in rendered
    assert "verdict-b" in rendered
    assert "lane-b -> lane-c" in rendered


def test_memory_trace_drawer_renders_trace_and_manual_gap() -> None:
    panel = render_memory_trace_drawer(
        {
            "memory": {
                "proof_level": "live_service_proof",
                "fact_state": "observed",
                "session_id": "mem-session-1",
                "namespace_uri": "memory://conversation/conv-1",
                "namespace": {"conversation_id": "conv-1", "god_id": "architect"},
                "trace_events_count": 2,
                "pinned_core_count": 1,
                "active_task_pages_count": 2,
                "recent_messages_count": 3,
                "retrieved_pages_count": 4,
                "dropped_pages_count": 5,
                "token_estimate": 321,
                "source_refs": ["memory://conversation/conv-1/session/mem-session-1"],
                "target_refs": ["memory_session:mem-session-1"],
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "live_service_proof" in rendered
    assert "mem-session-1" in rendered
    assert "memory://conversation/conv-1" in rendered
    assert "conversation_id=conv-1" in rendered
    assert "Trace events: 2" in rendered
    assert "Pinned core: 1" in rendered
    assert "Active task pages: 2" in rendered
    assert "Recent messages: 3" in rendered
    assert "Retrieved pages: 4" in rendered
    assert "Dropped pages: 5" in rendered
    assert "Tokens: 321" in rendered


def test_github_truth_panel_separates_readiness_from_merged_fact() -> None:
    panel = render_github_truth_panel(
        {
            "github": {
                "proof_level": "server_side_enforcement_proof",
                "fact_state": "merge_ready",
                "can_emit_pr_merged": True,
                "required_checks": {"state": "success", "checks": ["quality-gates"]},
                "review_truth": {"approved": True, "blocking_reviews": []},
                "merge": {"merged": False, "merge_commit_sha": None},
                "source_refs": ["github://owner/repo/pull/42"],
                "target_refs": [],
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "merge_ready" in rendered
    assert "pr_merged" not in rendered
    assert "quality-gates" in rendered
    assert "github://owner/repo/pull/42" in rendered


def test_proof_cockpit_renders_replay_and_release_blockers() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "authority": "replay_index_only",
                "replay_decision": "blocked",
                "release_decision": "blocked",
                "proof_contamination_decision": "clean",
                "section_count": 2,
                "artifact_count": 4,
                "blocker_count": 2,
                "finding_count": 0,
                "proof_level_summary": {
                    "contract_proof": 3,
                    "manual_gap": 1,
                },
                "blockers": [
                    {
                        "kind": "replay_section",
                        "id": "memoryos_trace",
                        "reason": "MemoryOS Lite was not configured",
                    },
                    {
                        "kind": "release_gate",
                        "id": "real-provider-runtime",
                        "reason": "provider soak missing",
                    },
                ],
                "artifacts": ["artifact://release-readiness.json"],
                "source_refs": ["github:pr:43"],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "blocked" in rendered
    assert "replay_index_only" in rendered
    assert "Replay: blocked" in rendered
    assert "Release: blocked" in rendered
    assert "Proof contamination: clean" in rendered
    assert "contract_proof=3" in rendered
    assert "manual_gap=1" in rendered
    assert "replay_section memoryos_trace: MemoryOS Lite was not configured" in rendered
    assert "release_gate real-provider-runtime: provider soak missing" in rendered
    assert "artifact://release-readiness.json" in rendered
    assert "github:pr:43" in rendered


def test_proof_cockpit_renders_section_statuses_and_god_runtime() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "section_statuses": [
                    {
                        "section_id": "memory_governance",
                        "status": "ok",
                        "proof_level": "contract_proof",
                        "source_authority": "memoryos_governance_policy",
                    },
                    {
                        "section_id": "memoryos_trace",
                        "status": "manual_gap",
                        "proof_level": "manual_gap",
                        "source_authority": "memoryos_rest",
                    },
                ],
                "blockers": [],
                "manual_gap_reason": None,
            },
            "god_runtime": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "items": [
                    {
                        "god_id": "codex.god",
                        "cli_id": "codex.god",
                        "peer_god_ready": True,
                        "bounded": False,
                        "provider_session_ready": True,
                        "proof_level": "contract_proof",
                        "waiting_reason": None,
                    },
                    {
                        "god_id": "opencode-worker",
                        "cli_id": "opencode.deepseek_flash_worker",
                        "peer_god_ready": False,
                        "bounded": True,
                        "provider_session_ready": True,
                        "proof_level": "contract_proof",
                        "waiting_reason": "selected CLI lacks peer_god capability",
                    },
                ],
            },
        }
    )

    rendered = panel.renderable.plain
    assert "Sections:" in rendered
    assert "memory_governance ok/contract_proof via memoryos_governance_policy" in rendered
    assert "memoryos_trace manual_gap/manual_gap via memoryos_rest" in rendered
    assert "GOD runtime: ready=1; bounded=1; blocked=1; total=2" in rendered
    assert "codex.god codex.god ready contract_proof" in rendered
    assert (
        "opencode-worker opencode.deepseek_flash_worker bounded contract_proof: "
        "selected CLI lacks peer_god capability"
    ) in rendered


def test_proof_cockpit_renders_github_truth_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "github_truth": {
                    "repo": "iiyazu/Cross-Muse",
                    "pull_request_number": 43,
                    "proof_level": "manual_gap",
                    "head_sha": "head-current",
                    "expected_head_sha": "head-current",
                    "head_sha_matches_expected": True,
                    "workflow_run_id": "27457543932",
                    "required_check_count": 3,
                    "check_run_count": 3,
                    "expected_source_app": "github-actions",
                    "server_enforcement": "branch_protection",
                    "review_truth": "missing",
                    "merge_truth": "missing",
                    "merged": False,
                    "can_emit_pr_merged": False,
                    "gap_reason": (
                        "missing server-side truth: review_truth, merge_truth"
                    ),
                    "capture_mode": "opt_in_read_only_gh_api",
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "GitHub truth: iiyazu/Cross-Muse#43 manual_gap head=head-current "
        "expected=head-current match=yes"
    ) in rendered
    assert (
        "checks=3; check_runs=3; app=github-actions; "
        "enforcement=branch_protection"
    ) in rendered
    assert "review=missing; merge=missing; can_emit_pr_merged=no; merged=no" in rendered
    assert "workflow=27457543932; capture=opt_in_read_only_gh_api" in rendered
    assert "gap=missing server-side truth: review_truth, merge_truth" in rendered


def test_proof_cockpit_renders_goal_stage_results() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "stage_result_summary": {
                    "ok": 1,
                    "blocked": 1,
                    "retry": 0,
                    "manual_gap": 0,
                    "total": 2,
                },
                "stage_results": [
                    {
                        "stage_id": "S1",
                        "status": "ok",
                        "proof_level": "contract_proof",
                        "engine": "opencode",
                        "source_authority": "goal_stage_harness",
                    },
                    {
                        "stage_id": "S4",
                        "status": "blocked",
                        "proof_level": "manual_gap",
                        "engine": "codex",
                        "source_authority": "goal_stage_harness",
                        "blocked_reason": "GitHub review truth missing",
                        "next_stage_id": "S7",
                    },
                ],
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "Goal stages: ok=1; blocked=1; retry=0; manual_gap=0; total=2" in rendered
    assert "S1 ok/contract_proof via goal_stage_harness (opencode)" in rendered
    assert (
        "S4 blocked/manual_gap via goal_stage_harness (codex): "
        "GitHub review truth missing -> S7"
    ) in rendered


def test_proof_cockpit_renders_virtual_soak_slo() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "virtual_soak_summary": {
                    "ok": 0,
                    "violated": 1,
                    "total": 1,
                },
                "latest_virtual_soak": {
                    "run_id": "overnight-stage-spine",
                    "total_minutes": 480,
                    "slo_status": "violated",
                    "slo_violations": ["heartbeat gap 20m exceeds 15m"],
                },
                "blockers": [
                    {
                        "kind": "virtual_soak",
                        "id": "overnight-stage-spine",
                        "reason": "heartbeat gap 20m exceeds 15m",
                        "next_action": (
                            "Reduce heartbeat/self-review intervals or fix "
                            "supervisor scheduling, then rerun the overnight "
                            "virtual soak."
                        ),
                    }
                ],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "Virtual soak: ok=0; violated=1; total=1" in rendered
    assert (
        "Latest soak: overnight-stage-spine 480m SLO=violated: "
        "heartbeat gap 20m exceeds 15m"
    ) in rendered
    assert (
        "virtual_soak overnight-stage-spine: heartbeat gap 20m exceeds 15m "
        "next=Reduce heartbeat/self-review intervals or fix supervisor "
        "scheduling, then rerun the overnight virtual soak."
    ) in rendered


def test_proof_cockpit_renders_recovery_queue() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "recovery_queue": [
                    {
                        "source": "release_readiness",
                        "kind": "release_gate",
                        "id": "real-provider-runtime",
                        "reason": "real provider runtime soak was not captured",
                        "next_action": "Run provider soak.",
                        "artifact": "artifact://release-readiness.json",
                    },
                    {
                        "source": "overnight_replay_bundle",
                        "kind": "replay_section",
                        "id": "memoryos_trace",
                        "reason": "MemoryOS Lite was not configured",
                        "next_action": "Enable MemoryOS Lite.",
                        "artifact": "artifact://overnight-replay-bundle.json",
                    },
                ],
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "Recovery queue:" in rendered
    assert (
        "release_readiness release_gate real-provider-runtime: real provider "
        "runtime soak was not captured next=Run provider soak. "
        "artifact=artifact://release-readiness.json"
    ) in rendered
    assert (
        "overnight_replay_bundle replay_section memoryos_trace: MemoryOS Lite "
        "was not configured next=Enable MemoryOS Lite. "
        "artifact=artifact://overnight-replay-bundle.json"
    ) in rendered


def test_proof_cockpit_renders_feature_lineage_lane_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "feature_lineage": {
                    "authority": "feature_owner_execution_contract",
                    "contract_count": 1,
                    "lane_count": 3,
                    "ready_lane_count": 1,
                    "blocked_lane_count": 1,
                    "completed_lane_count": 1,
                    "blocker_count": 1,
                    "features": [
                        {
                            "feature_id": "feature-runtime-loop",
                            "feature_graph_id": "graph-runtime",
                            "ready_lane_ids": ["lane-heartbeat"],
                            "blocked_lane_ids": ["lane-replay"],
                            "completed_lane_ids": ["lane-docs"],
                            "lane_blockers": [
                                {
                                    "lane_id": "lane-replay",
                                    "blocker_type": "dependency_unsatisfied",
                                    "blocker_ref": "lane:lane-heartbeat",
                                    "blocker_status": "pending",
                                }
                            ],
                        }
                    ],
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "Feature lineage: contracts=1; lanes=3; ready=1; blocked=1; completed=1" in rendered
    assert "feature-runtime-loop graph-runtime ready=lane-heartbeat blocked=lane-replay" in rendered
    assert "lane-replay dependency_unsatisfied lane:lane-heartbeat status=pending" in rendered


def test_proof_cockpit_renders_memory_governance_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "memory_governance": {
                    "authority": "memoryos_governance_policy",
                    "plan_count": 2,
                    "ingest_count": 1,
                    "promote_to_shared_count": 0,
                    "provider_session_binding_only_count": 0,
                    "blocked_count": 1,
                    "live_trace_proof": False,
                    "write_policy": "governed_rest_ingest_only",
                    "plans": [
                        {
                            "plan_id": "task-write",
                            "scope": "task",
                            "event_kind": "blueprint_frozen",
                            "status": "ok",
                            "decision": "ingest",
                            "target_namespace_uri": "memory://conversation/conv-1",
                            "write_request_allowed": True,
                        },
                        {
                            "plan_id": "blocked-shared",
                            "scope": "shared",
                            "event_kind": "decision_rationale",
                            "status": "blocked",
                            "decision": "blocked",
                            "target_namespace_uri": "memory://conversation/conv-1",
                            "shared_namespace_uri": (
                                "memory://global/shared/iiyazu/Cross-Muse"
                            ),
                            "write_request_allowed": False,
                            "blocked_reason": (
                                "shared promotion requires explicit review"
                            ),
                        },
                    ],
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "Memory governance: plans=2; ingest=1; promote=0; "
        "provider_binding=0; blocked=1; live_trace=no"
    ) in rendered
    assert "task-write task ingest ok write=yes -> memory://conversation/conv-1" in rendered
    assert (
        "blocked-shared shared blocked blocked write=no -> "
        "memory://conversation/conv-1 shared=memory://global/shared/iiyazu/Cross-Muse"
    ) in rendered
    assert "reason=shared promotion requires explicit review" in rendered


def test_proof_cockpit_renders_memoryos_trace_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "memoryos_trace": {
                    "authority": "memoryos_live_release_gate",
                    "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
                    "session_id": "ses-live-1",
                    "trace_event_count": 3,
                    "event_kinds": [
                        "session_created",
                        "ingest",
                        "context_built",
                    ],
                    "estimated_tokens": 96,
                    "source_ref_count": 5,
                    "blocker_count": 1,
                    "live_service_proof": True,
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "MemoryOS trace: ses-live-1 live=yes events=3; tokens=96; "
        "source_refs=5; blockers=1"
    ) in rendered
    assert "namespace=memory://conversation/conv-live/god-review/thread-1" in rendered
    assert "events=session_created, ingest, context_built" in rendered


def test_proof_cockpit_renders_deliberation_transcript_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "deliberation_transcript": {
                    "authority": "operator_transcript_v1",
                    "conversation_id": "conv-prod-1",
                    "message_count": 3,
                    "distinct_god_count": 2,
                    "god_ids": ["architect-god", "review-god"],
                    "speech_act_counts": {
                        "challenge": 1,
                        "evidence": 1,
                        "propose": 1,
                    },
                    "natural_deliberation": True,
                    "real_provider_proof": True,
                    "runtime_required": True,
                    "runtime_artifact_attached": False,
                    "runtime_peer_god_ready_count": 0,
                    "runtime_blocked_count": 2,
                    "missing_provider_session_god_ids": ["review-god"],
                    "blocker_count": 1,
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "Deliberation transcript: conv-prod-1 messages=3; gods=2; "
        "natural=yes; real_provider=yes"
    ) in rendered
    assert (
        "runtime_required=yes; runtime_artifact=no; runtime_ready=0; "
        "runtime_blocked=2"
    ) in rendered
    assert "acts=challenge=1; evidence=1; propose=1" in rendered
    assert "missing_sessions=review-god" in rendered
    assert "blockers=1" in rendered


def test_proof_cockpit_renders_real_provider_runtime_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "real_provider_runtime": {
                    "authority": "real_provider_runtime_release_gate",
                    "status": "blocked",
                    "proof_level": "real_provider_proof",
                    "gate_artifact": "artifact://real-provider-runtime-gate.json",
                    "runtime_artifact": "artifact://real-provider-runtime.json",
                    "run_id": "real-soak-pr43",
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
                    "blocker_count": 1,
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "Real provider runtime: codex ray/codex-app-server "
        "blocked/real_provider_proof run=real-soak-pr43"
    ) in rendered
    assert (
        "session=codex-thread-prod-1; mcp_writeback=yes; "
        "restart_resume=yes; turns=2"
    ) in rendered
    assert "phases=fresh, resume; degraded=0; blockers=1" in rendered
    assert (
        "artifacts gate=artifact://real-provider-runtime-gate.json "
        "runtime=artifact://real-provider-runtime.json"
    ) in rendered


def test_proof_cockpit_renders_supervisor_details() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "supervisor": {
                    "authority": "overnight_operator_supervisor",
                    "run_id": "overnight-prod",
                    "current_stage_id": "S7",
                    "selected_stage_id": "S6",
                    "stage_count": 7,
                    "heartbeat_count": 9,
                    "checkpoint_count": 4,
                    "manual_gap_count": 1,
                    "self_review_count": 3,
                    "blocked_fallback_count": 2,
                    "virtual_soak_count": 1,
                    "latest_heartbeat_stage_id": "S7",
                    "latest_checkpoint_stage_id": "S6",
                    "latest_blocked_stage_id": "S4",
                    "latest_virtual_soak_run_id": "overnight-prod-soak",
                    "latest_virtual_soak_slo_status": "violated",
                },
                "blockers": [],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert (
        "Supervisor: overnight-prod stages=7; heartbeats=9; checkpoints=4; "
        "manual_gaps=1"
    ) in rendered
    assert (
        "current=S7; selected=S6; self_reviews=3; "
        "blocked_fallbacks=2; virtual_soaks=1"
    ) in rendered
    assert (
        "latest heartbeat=S7; checkpoint=S6; blocked=S4; "
        "soak=overnight-prod-soak/violated"
    ) in rendered


def test_proof_cockpit_renders_god_runtime_heartbeat_freshness() -> None:
    panel = render_proof_cockpit(
        {
            "proof_cockpit": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "blockers": [],
                "manual_gap_reason": None,
            },
            "god_runtime": {
                "proof_level": "manual_gap",
                "fact_state": "blocked",
                "items": [
                    {
                        "god_id": "codex.god",
                        "cli_id": "codex.god",
                        "peer_god_ready": False,
                        "bounded": False,
                        "provider_session_ready": True,
                        "heartbeat_freshness": "stale",
                        "proof_level": "manual_gap",
                        "waiting_reason": "GOD session heartbeat stale",
                    },
                ],
            },
        }
    )

    rendered = panel.renderable.plain
    assert (
        "codex.god codex.god blocked manual_gap "
        "heartbeat=stale: GOD session heartbeat stale"
    ) in rendered


def test_proof_cockpit_renders_manual_gap() -> None:
    panel = render_proof_cockpit(None)

    rendered = panel.renderable.plain
    assert "manual_gap" in rendered
    assert "No proof cockpit evidence" in rendered


class TestRunHealthCounts:
    def test_extracts_counts_subdict(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        result = _run_health_counts({"counts": {"live": 1, "stale": 0}})
        assert result == {"live": 1, "stale": 0}

    def test_falls_back_to_plain_dict(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        result = _run_health_counts({"live": 1})
        assert result == {"live": 1}

    def test_empty_on_none(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        assert _run_health_counts(None) == {}


class TestParticipantStatusSymbol:
    def test_active_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("active") == "●"

    def test_stopped_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("stopped") == "◆"

    def test_unknown_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("") == "○"
        assert _participant_status_symbol("thinking") == "○"
        assert _participant_status_symbol("failed") == "○"


class TestXmuHeader:
    def test_header_style_connected_by_live(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 2, "stale": 0, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "connected"

    def test_header_style_degraded_by_errors(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 0}}
        state.has_errors = True
        assert _connection_style_for(state) == "degraded"

    def test_header_style_degraded_by_fallback(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 1}}
        assert _connection_style_for(state) == "degraded"

    def test_header_style_degraded_by_stale(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 1, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "degraded"

    def test_header_style_idle(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "idle"

    def test_header_style_fallback_plain_run_health(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"live": 1}
        assert _connection_style_for(state) == "connected"


class TestMessageLogSearch:
    def test_search_finds_matching_messages(self):
        log = MessageLog()
        log.append_message(author="user", content="hello world", role="user")
        log.append_message(author="architect", content="plan for error handling", role="assistant")
        log.append_message(author="user", content="another message", role="user")
        results = log.search("error")
        assert "error" in results
        assert "hello" not in results

    def test_search_no_match_returns_none(self):
        log = MessageLog()
        log.append_message(author="user", content="hello world", role="user")
        results = log.search("zzzzz")
        assert results is None

    def test_clear_search_restores_all(self):
        log = MessageLog()
        log.append_message(author="user", content="hello", role="user")
        log.append_message(author="architect", content="world", role="assistant")
        log.search("hello")
        log.clear_search()
        assert log._search_query == ""

    def test_search_case_insensitive(self):
        log = MessageLog()
        log.append_message(author="user", content="Hello World", role="user")
        results = log.search("hello")
        assert "Hello" in results

    def test_search_matches_author(self):
        log = MessageLog()
        log.append_message(author="architect-god", content="plan", role="assistant")
        log.append_message(author="user", content="question", role="user")
        results = log.search("architect")
        assert "plan" in results
        assert "question" not in results
