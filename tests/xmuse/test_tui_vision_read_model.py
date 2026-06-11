from __future__ import annotations

from xmuse.tui.adapter.xmuse_adapter import StateDelta, XmuseAdapter
from xmuse.tui.state import AppState
from xmuse_core.platform.tui_vision_read_model import build_tui_vision_read_model


def test_tui_vision_read_model_summarizes_deliberation_speech_acts() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        messages=[
            {
                "id": "msg-propose",
                "conversation_id": "conv-1",
                "author": "architect",
                "envelope_json": {
                    "speech_act": "propose",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["memory://conversation/conv-1/source"],
                    "target_ref": "blueprint:conv-1:1",
                    "payload": {"summary": "freeze the scoped blueprint"},
                },
            },
            {
                "id": "msg-challenge",
                "conversation_id": "conv-1",
                "author": "review",
                "envelope_json": {
                    "act": "challenge",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["message:msg-propose"],
                    "target_refs": ["blueprint:conv-1:1"],
                    "blocking": True,
                    "payload": {"summary": "acceptance criteria are missing"},
                },
            },
        ],
    )

    deliberation = model["deliberation"]
    assert deliberation["proof_level"] == "contract_proof"
    assert deliberation["fact_state"] == "blocked"
    assert deliberation["speech_act_counts"] == {"challenge": 1, "propose": 1}
    assert deliberation["source_refs"] == [
        "message:msg-propose",
        "memory://conversation/conv-1/source",
        "message:msg-challenge",
    ]
    assert deliberation["target_refs"] == ["blueprint:conv-1:1"]
    assert deliberation["blockers"] == [
        {
            "message_id": "msg-challenge",
            "speech_act": "challenge",
            "reason": "acceptance criteria are missing",
            "source_refs": ["message:msg-propose"],
            "target_refs": ["blueprint:conv-1:1"],
        }
    ]
    assert deliberation["manual_gap_reason"] is None


def test_tui_vision_read_model_reports_blueprint_freeze_readiness_not_freeze_fact() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        messages=[
            {
                "id": "msg-decide",
                "conversation_id": "conv-1",
                "author": "architect",
                "envelope_json": {
                    "type": "decide",
                    "decision_scope": "blueprint.freeze",
                    "target_ref": "blueprint:conv-1:1",
                    "source_refs": ["message:msg-vote-review"],
                    "payload": {"decision": "freeze_ready"},
                },
            }
        ],
    )

    freeze = model["blueprint_freeze"]
    assert freeze["proof_level"] == "contract_proof"
    assert freeze["fact_state"] == "ready_to_freeze"
    assert freeze["ready_to_freeze"] is True
    assert freeze["frozen"] is False
    assert freeze["target_refs"] == ["blueprint:conv-1:1"]
    assert freeze["source_refs"] == ["message:msg-decide", "message:msg-vote-review"]
    assert freeze["blockers"] == []
    assert freeze["manual_gap_reason"] is None


def test_tui_vision_read_model_summarizes_lane_dag_projection() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        worklist_envelope={
            "source_authority": "feature_lanes_projection",
            "projection_revision": 7,
            "items": [
                {
                    "lane_id": "lane-a",
                    "plan_feature_id": "feature-a",
                    "ready": True,
                    "blocked": False,
                    "scoped_dependency_ids": [],
                },
                {
                    "lane_id": "lane-b",
                    "plan_feature_id": "feature-a",
                    "ready": False,
                    "blocked": True,
                    "scoped_dependency_ids": ["lane-a"],
                    "prompt_summary": "needs review evidence",
                },
            ],
            "graph_lineage": {
                "authoritative_graph_id": "graph-1",
                "checked_graph_ids": ["graph-1"],
                "degraded": False,
            },
        },
    )

    execution = model["execution"]
    assert execution["proof_level"] == "contract_proof"
    assert execution["fact_state"] == "blocked"
    assert execution["lane_count"] == 2
    assert execution["ready_lane_ids"] == ["lane-a"]
    assert execution["blocked_lane_ids"] == ["lane-b"]
    assert execution["dependency_edges"] == [
        {"lane_id": "lane-b", "depends_on": ["lane-a"]}
    ]
    assert execution["graph_lineage"]["authoritative_graph_id"] == "graph-1"
    assert execution["source_refs"] == ["feature_lanes_projection#projection_revision=7"]
    assert execution["target_refs"] == ["lane:lane-a", "lane:lane-b", "graph:graph-1"]
    assert execution["blockers"] == [
        {
            "lane_id": "lane-b",
            "reason": "needs review evidence",
            "source_refs": ["feature_lanes_projection#projection_revision=7"],
            "target_refs": ["lane:lane-b"],
        }
    ]


def test_tui_vision_read_model_summarizes_memory_trace_and_manual_gap() -> None:
    with_trace = build_tui_vision_read_model(
        conversation_id="conv-1",
        memory_trace={
            "session_id": "mem-session-1",
            "namespace": {"conversation_id": "conv-1"},
            "trace_events": [{"event": "retrieve"}, {"event": "drop"}],
            "source_refs": ["memory://conversation/conv-1/session/mem-session-1"],
            "token_estimate": 321,
            "proof_level": "live_service_proof",
        },
    )

    memory = with_trace["memory"]
    assert memory["proof_level"] == "live_service_proof"
    assert memory["fact_state"] == "observed"
    assert memory["session_id"] == "mem-session-1"
    assert memory["trace_events_count"] == 2
    assert memory["token_estimate"] == 321
    assert memory["source_refs"] == [
        "memory://conversation/conv-1/session/mem-session-1"
    ]
    assert memory["manual_gap_reason"] is None

    without_trace = build_tui_vision_read_model(conversation_id="conv-1")
    assert without_trace["memory"]["proof_level"] == "manual_gap"
    assert without_trace["memory"]["fact_state"] == "manual_gap"
    assert without_trace["memory"]["manual_gap_reason"] == "memory trace unavailable"


def test_tui_vision_read_model_preserves_github_truth_without_merging_readiness() -> None:
    ready = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_enforcement_proof",
            "can_emit_pr_merged": True,
            "required_checks": {"state": "success", "checks": ["pytest"]},
            "review_truth": {"approved": True, "blocking_reviews": []},
            "merge": {"merged": False, "merge_commit_sha": None},
            "source_refs": ["github://owner/repo/pull/42"],
        },
    )

    github = ready["github"]
    assert github["proof_level"] == "server_side_enforcement_proof"
    assert github["fact_state"] == "merge_ready"
    assert github["can_emit_pr_merged"] is True
    assert github["required_checks"] == {"state": "success", "checks": ["pytest"]}
    assert github["review_truth"] == {"approved": True, "blocking_reviews": []}
    assert github["merge"] == {"merged": False, "merge_commit_sha": None}
    assert github["source_refs"] == ["github://owner/repo/pull/42"]

    merged = build_tui_vision_read_model(
        github_truth={
            "proof_level": "server_side_merge_proof",
            "merge": {
                "merged": True,
                "merge_commit_sha": "abc123",
                "merged_at": "2026-06-11T00:00:00Z",
            },
            "source_refs": ["github://owner/repo/pull/42#merge"],
        },
    )
    assert merged["github"]["fact_state"] == "pr_merged"


def test_tui_vision_read_model_uses_inspector_optional_evidence() -> None:
    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        inspector={
            "memory_trace": {
                "session_id": "mem-session-2",
                "trace_events": [{"event": "ingest"}],
                "proof_level": "live_service_proof",
            },
            "github_truth": {
                "proof_level": "manual_gap",
                "manual_gap_reason": "branch protection snapshot unavailable",
            },
            "provider_runtime": [
                {
                    "provider_id": "codex-primary",
                    "runtime_kind": "codex",
                    "transport": "cli",
                    "session_continuity": "active",
                    "waiting_reason": None,
                }
            ],
        },
    )

    assert model["memory"]["session_id"] == "mem-session-2"
    assert model["github"]["manual_gap_reason"] == "branch protection snapshot unavailable"
    assert model["providers"]["items"] == [
        {
            "provider_id": "codex-primary",
            "runtime_kind": "codex",
            "transport": "cli",
            "session_continuity": "active",
            "heartbeat": None,
            "waiting_reason": None,
            "proof_level": "contract_proof",
        }
    ]


def test_state_delta_carries_vision_read_model_into_app_state() -> None:
    vision = build_tui_vision_read_model(conversation_id="conv-1")
    state = AppState()

    state.apply(StateDelta(vision=vision))

    assert state.vision == vision


async def test_adapter_poll_delta_includes_tui_vision_read_model(monkeypatch, tmp_path) -> None:
    adapter = XmuseAdapter(tmp_path)
    envelope = {
        "source_authority": "feature_lanes_projection",
        "projection_revision": 9,
        "items": [
            {
                "lane_id": "lane-a",
                "plan_feature_id": "feature-a",
                "ready": True,
                "blocked": False,
                "scoped_dependency_ids": [],
            }
        ],
    }

    monkeypatch.setattr(
        adapter,
        "poll_messages",
        lambda conv_id: (
            [
                {
                    "id": "msg-1",
                    "conversation_id": conv_id,
                    "envelope_json": {
                        "speech_act": "propose",
                        "target_ref": "blueprint:conv-1:1",
                    },
                }
            ],
            None,
        ),
    )

    async def _poll_worklist_envelope(conv_id: str | None = None):
        return envelope, None

    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "get_participants", lambda conv_id: [])
    monkeypatch.setattr(adapter, "get_conversation_inspector", lambda conv_id: {})

    delta = await adapter.poll_delta("conv-1")

    assert delta.vision["deliberation"]["speech_act_counts"] == {"propose": 1}
    assert delta.vision["execution"]["lane_count"] == 1
    assert delta.vision["execution"]["source_authority"] == "feature_lanes_projection"
