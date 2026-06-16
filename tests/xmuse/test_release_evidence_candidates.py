from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.platform.closure_objects import REQUIRED_FORBIDDEN_CLAIMS
from xmuse_core.platform.closure_reconciler import reconcile_closure
from xmuse_core.platform.god_room_review_chain_proof import (
    capture_god_room_review_chain_proof,
)
from xmuse_core.platform.local_execution_candidate import (
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def test_release_evidence_candidates_identify_ready_natural_and_provider_inputs(
    tmp_path: Path,
) -> None:
    conversation_id = _seed_natural_conversation(tmp_path)
    _seed_selected_god_runtime(tmp_path, conversation_id)
    _seed_provider_traces(tmp_path, conversation_id)

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id=conversation_id,
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "repo": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "pull_request_number": 43,
            "expected_head_sha": "4ed83bc82ae66b23e4c3d0613933b6f908739e12",
            "base_branch": "main",
            "required_checks": ["xmuse CI"],
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-1",
            "content": "live evidence",
            "query": "production evidence",
        },
    )

    natural = report["natural_deliberation"]["conversations"][0]
    provider = report["real_provider_runtime"]
    memoryos = report["live_memoryos"]
    github = report["github_server_truth"]
    assert report["schema_version"] == "xmuse.release_evidence_candidates.v1"
    assert natural["conversation_id"] == conversation_id
    assert natural["export_ready"] is True
    assert natural["transcript_export_ready"] is True
    assert natural["selected_god_runtime"]["peer_god_ready_count"] == 2
    assert natural["selected_god_runtime"]["blockers"] == []
    assert natural["god_speech_act_count"] == 2
    assert natural["distinct_god_count"] == 2
    assert natural["blockers"] == []
    assert natural["proof_boundary"] == (
        "candidate_report_is_not_natural_deliberation_proof"
    )
    assert natural["required_transcript_schema"] == "xmuse.operator_transcript.v1"
    assert natural["required_runtime_schema"] == "xmuse.god_runtime_continuity.v1"
    assert natural["required_proof_level"] == "real_provider_proof"
    assert natural["source_authority"] == [
        "chat_store.messages.god_speech_act",
        "god_session_registry.provider_session_bindings",
        "god_cli_selection_store",
        "god_cli_registry",
    ]
    assert natural["suggested_operator_action"] == {
        "action": "attempt_release_evidence",
        "kind": "natural_deliberation",
        "required_payload_keys": ["conversation_id"],
        "payload_hints": {"conversation_id": conversation_id},
    }
    assert provider["trace_table_present"] is True
    assert provider["export_ready"] is True
    assert provider["suggested_fresh_inbox_item_id"] == "inbox-fresh"
    assert provider["suggested_resume_inbox_item_id"] == "inbox-resume"
    assert provider["proof_boundary"] == "candidate_report_is_not_release_proof"
    assert provider["required_artifact_schema"] == "xmuse.real_provider_runtime.v1"
    assert provider["required_proof_level"] == "real_provider_proof"
    assert provider["source_authority"] == [
        "chat_store.peer_turn_latency_traces",
        "god_session_registry.provider_session_bindings",
    ]
    assert provider["suggested_operator_action"] == {
        "action": "attempt_release_evidence",
        "kind": "real_provider_runtime",
        "required_payload_keys": [
            "conversation_id",
            "runtime_backend",
            "transport",
        ],
        "payload_hints": {
            "conversation_id": conversation_id,
            "fresh_inbox_item_id": "inbox-fresh",
            "resume_inbox_item_id": "inbox-resume",
        },
    }
    assert memoryos["export_ready"] is True
    assert memoryos["configured"] is True
    assert memoryos["missing_env_keys"] == []
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"
    assert memoryos["required_artifact_schema"] == "xmuse.memoryos_lite_trace.v1"
    assert memoryos["required_proof_level"] == "live_service_proof"
    assert memoryos["source_authority"] == [
        "redacted_environment_presence",
        "operator_release_candidate_payload",
    ]
    assert memoryos["suggested_operator_action"] == {
        "action": "attempt_release_evidence",
        "kind": "live_memoryos",
        "required_payload_keys": [
            "repo_id",
            "workspace_id",
            "god_id",
            "conversation_id",
            "thread_id",
            "blueprint_id",
            "feature_id",
            "lane_id",
            "content",
            "query",
        ],
        "payload_hints": {
            "conversation_id": conversation_id,
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-1",
        },
    }
    assert github["export_ready"] is True
    assert github["proof_boundary"] == (
        "candidate_report_is_not_github_server_truth_proof"
    )
    assert github["required_gate_kind"] == "github_server_truth"
    assert github["required_proof_level"] == "server_side_enforcement_proof"
    assert github["source_authority"] == [
        "operator_release_candidate_payload",
        "github_server_truth_export_action",
    ]
    assert github["missing_payload_keys"] == []
    assert github["blockers"] == []
    assert github["can_emit_pr_merged"] is False
    assert github["suggested_operator_action"] == {
        "action": "attempt_release_evidence",
        "kind": "github_server_truth",
        "required_payload_keys": ["repo", "pull_request_number"],
        "payload_hints": {
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "expected_head_sha": "4ed83bc82ae66b23e4c3d0613933b6f908739e12",
            "base_branch": "main",
            "required_checks": ["xmuse CI"],
        },
    }


def test_release_evidence_candidates_seed_memoryos_refs_from_review_closure(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json"
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "source_refs": ["operator:manual-context"],
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["export_ready"] is True
    assert memoryos["review_closure_artifact_configured"] is True
    assert memoryos["review_closure_artifact_gate_ready"] is True
    assert memoryos["review_closure_source_ref_count"] == 9
    assert memoryos["review_closure_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert memoryos["review_closure_candidate_artifact_ref_count"] == 1
    assert memoryos["review_closure_handoff_evaluation"]["schema_version"] == (
        "xmuse.review_closure_handoff_evaluation.v1"
    )
    assert memoryos["review_closure_handoff_evaluation"]["status"] == "ready"
    assert memoryos["review_closure_handoff_evaluation"]["candidate_ref_count"] == 2
    assert memoryos["review_closure_handoff_evaluation"][
        "cited_candidate_ref_count"
    ] == 2
    assert memoryos["review_closure_handoff_evaluation"][
        "source_event_lineage_count"
    ] == 1
    assert "god_room_review_closure_artifact" in memoryos["source_authority"]
    assert payload_hints["source_refs"] == [
        "operator:manual-context",
        (
            "god-room-review-closure:graph-runtime:"
            "lane-runtime-evidence:lane-runtime-evidence-patch"
        ),
        "lane:lane-runtime-evidence",
        "lane:lane-runtime-evidence-patch",
        "god-room-event:evt-provider-speak",
        (
            "reports/god_room_patch_forward/"
            "graph-runtime.lane-runtime-evidence.patch-forward.json"
        ),
        (
            "reports/god_room_review_intake/"
            "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
        ),
        (
            "reports/god_room_review_verdicts/"
            "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
        ),
        "worker-candidate:patch-reviewed",
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    assert payload_hints["source_event_lineage_refs"] == [
        "god-room-event:evt-provider-speak"
    ]
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"


def test_release_evidence_candidates_seed_memoryos_refs_from_runner_recovery_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_gate_ready"] is True
    assert memoryos["review_closure_source_ref_count"] == 11
    assert memoryos["review_closure_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert "god-room-event:evt-provider-speak" in payload_hints["source_refs"]
    assert (
        "runner_recovery_proof_artifact:reports/runner-recovery-proof.json"
        in payload_hints["source_refs"]
    )
    assert "reports/lane-recovery/lane-runtime-evidence.json" in payload_hints[
        "source_refs"
    ]
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"


def test_release_evidence_candidates_seed_memoryos_refs_from_review_chain_proof(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "source_refs": ["operator:manual-context"],
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_chain_proof_artifact_configured"] is True
    assert memoryos["review_chain_proof_artifact_gate_ready"] is True
    assert memoryos["review_chain_proof_handoff_evaluation"]["schema_version"] == (
        "xmuse.review_chain_proof_l10_handoff_evaluation.v1"
    )
    assert memoryos["review_chain_proof_handoff_evaluation"]["status"] == "ready"
    assert memoryos["review_chain_proof_bounded_session_gate_status"] == "verified"
    assert memoryos["review_chain_proof_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert memoryos["review_chain_proof_candidate_artifact_ref_count"] == 1
    assert memoryos["review_chain_proof_patch_forward_artifact_refs"] == [
        (
            "reports/god_room_patch_forward/"
            "graph-runtime.lane-runtime-evidence.patch-forward.json"
        ),
        (
            "reports/god_room_review_intake/"
            "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
        ),
        (
            "reports/god_room_review_verdicts/"
            "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
        ),
    ]
    assert memoryos["review_chain_proof_patch_forward_artifact_ref_count"] == 3
    assert "god_room_review_chain_proof_artifact" in memoryos["source_authority"]
    assert (
        "god-room-review-chain-proof:graph-runtime:"
        "lane-runtime-evidence:lane-runtime-evidence-patch"
    ) in payload_hints["source_refs"]
    assert "review_chain_proof_artifact:review-chain-proof.json" in payload_hints[
        "source_refs"
    ]
    assert "artifacts/lane-runtime-evidence-patch/result.json" in payload_hints[
        "source_refs"
    ]
    assert (
        "reports/god_room_patch_forward/"
        "graph-runtime.lane-runtime-evidence.patch-forward.json"
    ) in payload_hints["source_refs"]
    assert (
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    ) in payload_hints["source_refs"]
    assert (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
    ) in payload_hints["source_refs"]
    assert "god-room-event:evt-provider-speak" in payload_hints["source_refs"]
    assert (
        "runner_recovery_proof_artifact:reports/runner-recovery-proof.json"
        in payload_hints["source_refs"]
    )
    assert payload_hints["source_event_lineage_refs"] == [
        "god-room-event:evt-provider-speak"
    ]
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"


def test_release_evidence_candidates_reject_review_chain_when_current_handoff_fails(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    (tmp_path / "work" / "runner_sessions" / "runner-session-1.json").unlink()

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert memoryos["review_chain_proof_artifact_summary"] == (
        "GOD room review chain proof current review-closure handoff is not "
        "gate-ready: GOD room review closure runner session artifact is not "
        "readable: work/runner_sessions/runner-session-1.json"
    )
    assert memoryos["review_chain_proof_candidate_artifact_refs"] == []
    assert memoryos["review_chain_proof_candidate_artifact_ref_count"] == 0
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_chain_proof_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_chain_proof_missing_bounded_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    del proof["local_execution_review_session"]
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert (
        memoryos["review_chain_proof_bounded_session_gate_status"] == "manual_gap"
    )
    assert "local_execution_review_session is missing" in memoryos[
        "review_chain_proof_artifact_summary"
    ]
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_chain_proof_artifact" not in memoryos["source_authority"]


def test_release_evidence_candidates_reject_review_chain_proof_missing_session_refs(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    proof["local_execution_review_session"]["session_artifact_refs"] = []
    proof["local_execution_review_session"]["session_source_refs"] = []
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert "local_execution_review_session has no session artifact refs" in memoryos[
        "review_chain_proof_artifact_summary"
    ]
    assert "local_execution_review_session has no session source refs" in memoryos[
        "review_chain_proof_artifact_summary"
    ]
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_review_chain_proof_manual_candidate_producer(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    proof["candidate_lineage"]["producers"] = ["manual_cli_capture"]
    proof["local_execution_review_session"]["candidate_producers"] = [
        "manual_cli_capture"
    ]
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert (
        "candidate producers do not prove platform runner dispatch"
        in memoryos["review_chain_proof_artifact_summary"]
    )
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_review_chain_proof_unverified_boundary(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    session = proof["local_execution_review_session"]
    session["candidate_lineage_boundary"]["status"] = "manual_gap"
    session["candidate_lineage_boundary"]["proof_level"] = "manual_gap"
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert "candidate_lineage_boundary is not verified" in memoryos[
        "review_chain_proof_artifact_summary"
    ]
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_review_chain_proof_candidate_ref_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    proof["local_execution_review_session"]["candidate_artifact_refs"] = [
        "artifacts/other/result.json"
    ]
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert "candidate artifact refs do not match release evidence handoff refs" in (
        memoryos["review_chain_proof_artifact_summary"]
    )
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_review_chain_proof_missing_candidate_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    del proof["candidate_lineage"]
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert "candidate lineage has no candidate artifact refs" in memoryos[
        "review_chain_proof_artifact_summary"
    ]
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_manual_gap_review_chain_proof(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        create_candidate_artifact=False,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_configured"] is True
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert memoryos["review_chain_proof_artifact_summary"] == (
        "GOD room review chain proof is not chain_ready."
    )
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_chain_proof_artifact" not in memoryos["source_authority"]


def test_release_evidence_candidates_reject_review_chain_proof_missing_forbidden_claim(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    proof = json.loads(chain_proof.read_text(encoding="utf-8"))
    proof["forbidden_claims"] = [
        claim
        for claim in proof["forbidden_claims"]
        if claim != "end_to_end_execution_review_closure"
    ]
    chain_proof.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_chain_proof": str(chain_proof),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is False
    assert memoryos["review_chain_proof_artifact_summary"] == (
        "GOD room review chain proof missing forbidden claims: "
        "end_to_end_execution_review_closure"
    )
    assert "god_room_review_chain_proof_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_reject_review_closure_without_resolvable_candidate_artifact(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        create_candidate_artifact=False,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["export_ready"] is True
    assert memoryos["review_closure_artifact_configured"] is True
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure has no valid cited candidate evidence artifact."
    )
    assert memoryos["review_closure_candidate_artifact_refs"] == []
    assert memoryos["review_closure_candidate_artifact_ref_count"] == 0
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_invalid_candidate_artifact(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
    )
    candidate_path = (
        review_closure.parent / "artifacts" / "lane-runtime-evidence-patch" / "result.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["forbidden_claims"] = ["ready_to_merge"]
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure has an invalid cited candidate evidence artifact: "
        "local execution candidate artifact "
        "artifacts/lane-runtime-evidence-patch/result.json is invalid: "
        "local execution candidate missing forbidden claims"
    )
    assert memoryos["review_closure_candidate_artifact_refs"] == []
    assert memoryos["review_closure_candidate_artifact_ref_count"] == 0
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_invalid_runner_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
    )
    session_path = tmp_path / "work" / "runner_sessions" / "runner-session-1.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    session["candidate_artifact_refs"] = []
    session["candidate_count"] = 0
    session_path.write_text(
        json.dumps(session, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure runner session artifact is invalid: "
        "runner session does not include candidate artifact ref"
    )
    assert memoryos["review_closure_candidate_artifact_refs"] == []
    assert memoryos["review_closure_candidate_artifact_ref_count"] == 0
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_missing_runner_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
    )
    (tmp_path / "work" / "runner_sessions" / "runner-session-1.json").unlink()

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure runner session artifact is not readable: "
        "work/runner_sessions/runner-session-1.json"
    )
    assert memoryos["review_closure_candidate_artifact_refs"] == []
    assert memoryos["review_closure_candidate_artifact_ref_count"] == 0
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_missing_forbidden_claim(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
    )
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    closure["forbidden_claims"] = [
        claim for claim in closure["forbidden_claims"] if claim != "live_memoryos"
    ]
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure missing forbidden claims: live_memoryos"
    )
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_candidate_scope_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
    )
    candidate_path = (
        review_closure.parent / "artifacts" / "lane-runtime-evidence-patch" / "result.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["conversation_id"] = "conv-other"
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure has an invalid cited candidate evidence artifact: "
        "local execution candidate artifact "
        "artifacts/lane-runtime-evidence-patch/result.json is invalid: "
        "local execution candidate conversation_id does not match review scope"
    )
    assert memoryos["review_closure_candidate_artifact_refs"] == []
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]


def test_release_evidence_candidates_seed_memoryos_refs_from_runtime_closure(
    tmp_path: Path,
) -> None:
    runtime_closure = _write_god_room_runtime_closure_evidence(
        tmp_path / "runtime-closure.json"
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "source_refs": ["operator:manual-context"],
            "god_room_runtime_closure": str(runtime_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["export_ready"] is True
    assert memoryos["runtime_closure_artifact_configured"] is True
    assert memoryos["runtime_closure_artifact_gate_ready"] is True
    assert memoryos["runtime_closure_current_handoff_gate_ready"] is None
    assert memoryos["runtime_closure_source_ref_count"] == 4
    assert "god_room_runtime_closure_evidence" in memoryos["source_authority"]
    assert payload_hints["source_refs"] == [
        "operator:manual-context",
        "god-room-event:evt-provider-speak",
        "provider_response_artifact:reports/provider-responses/provider-response-1.json",
        (
            "speaker_response_artifact:reports/god_room_speaker_responses/"
            "speaker-response-1.json"
        ),
        "lane:lane-runtime-evidence-patch",
    ]
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"


def test_release_evidence_candidates_reject_stale_runtime_closure_handoff(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        create_candidate_artifact=False,
    )
    runtime_closure = _write_god_room_runtime_closure_evidence(
        tmp_path / "runtime-closure.json",
        review_closure_artifact=review_closure,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_runtime_closure": str(runtime_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["runtime_closure_artifact_configured"] is True
    assert memoryos["runtime_closure_artifact_gate_ready"] is False
    assert memoryos["runtime_closure_current_handoff_gate_ready"] is False
    assert memoryos["runtime_closure_current_handoff_candidate_artifact_refs"] == []
    assert memoryos["runtime_closure_current_handoff_candidate_artifact_ref_count"] == 0
    assert memoryos["runtime_closure_artifact_summary"] == (
        "GOD room runtime closure evidence current review-closure handoff is "
        "not gate-ready: GOD room review closure has no valid cited candidate "
        "evidence artifact."
    )
    assert "god_room_runtime_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_runtime_closure_evidence" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_seed_memoryos_refs_from_closure_object(
    tmp_path: Path,
) -> None:
    closure_path = tmp_path / "closure-object.json"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "source_authority": "review_closure_handoff_evaluation",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "source_refs": [
                "god-room-review-closure:graph-runtime:failed:terminal",
                "lane:lane-runtime-evidence-patch",
            ],
            "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
        },
    )
    closure_path.write_text(
        json.dumps(closure.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "closure_object": str(closure_path),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["closure_object_artifact_configured"] is True
    assert memoryos["closure_object_artifact_gate_ready"] is True
    assert memoryos["closure_object_phase"] == "manual_gap"
    assert memoryos["closure_object_source_ref_count"] >= 2
    assert memoryos["closure_object_target_ref_count"] >= 2
    assert "lane:lane-runtime-evidence-patch" in memoryos[
        "closure_object_target_refs"
    ]
    assert memoryos["closure_object_owner_ref_count"] == 1
    assert memoryos["closure_object_forbidden_claim_count"] >= len(
        REQUIRED_FORBIDDEN_CLAIMS
    )
    assert "closure_object_artifact" in memoryos["source_authority"]
    assert "closure_object_artifact_not_ready" not in memoryos["blockers"]
    assert "god-room-review-closure:graph-runtime:failed:terminal" in payload_hints[
        "source_refs"
    ]
    assert "lane:lane-runtime-evidence-patch" in payload_hints["source_refs"]
    assert "graph:graph-runtime" in payload_hints["target_refs"]
    assert "lane:lane-runtime-evidence-patch" in payload_hints["target_refs"]


def test_release_evidence_candidates_reject_stale_closure_object(
    tmp_path: Path,
) -> None:
    closure_path = tmp_path / "closure-object.json"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "source_authority": "review_closure_handoff_evaluation",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "source_refs": [
                "god-room-review-closure:graph-runtime:failed:terminal",
            ],
            "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
        },
    ).to_dict()
    closure["status"]["evaluator_version"] = "xmuse.closure_controller.v0"
    closure_path.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "closure_object": str(closure_path),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["closure_object_artifact_configured"] is True
    assert memoryos["closure_object_artifact_gate_ready"] is False
    assert memoryos["closure_object_artifact_summary"] == (
        "ClosureObject evaluator_version is stale"
    )
    assert "closure_object_artifact_not_ready" in memoryos["blockers"]
    assert "closure_object_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints
    assert "target_refs" not in payload_hints


def test_release_evidence_candidates_reject_runtime_closure_proof_overclaim(
    tmp_path: Path,
) -> None:
    runtime_closure = _write_god_room_runtime_closure_evidence(
        tmp_path / "runtime-closure.json",
        proof_level="server_side_truth",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_runtime_closure": str(runtime_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["runtime_closure_artifact_configured"] is True
    assert memoryos["runtime_closure_artifact_gate_ready"] is False
    assert memoryos["runtime_closure_artifact_summary"] == (
        "GOD room runtime closure evidence overclaims proof level."
    )
    assert "god_room_runtime_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_runtime_closure_evidence" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_reject_review_closure_server_truth_overclaim(
    tmp_path: Path,
) -> None:
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        server_truth_status="github_review_truth",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-runtime-evidence-patch",
            "content": "live evidence",
            "query": "production evidence",
            "god_room_review_closure": str(review_closure),
        },
    )

    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["review_closure_artifact_configured"] is True
    assert memoryos["review_closure_artifact_gate_ready"] is False
    assert memoryos["review_closure_artifact_summary"] == (
        "GOD room review closure overclaims server truth."
    )
    assert "god_room_review_closure_artifact_not_ready" in memoryos["blockers"]
    assert "god_room_review_closure_artifact" not in memoryos["source_authority"]
    assert "source_refs" not in payload_hints


def test_release_evidence_candidates_require_selected_runtime_for_natural_export(
    tmp_path: Path,
) -> None:
    conversation_id = _seed_natural_conversation(tmp_path)

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id=conversation_id,
        env={},
        memoryos_payload={},
    )

    natural = report["natural_deliberation"]["conversations"][0]
    assert natural["transcript_export_ready"] is True
    assert natural["export_ready"] is False
    assert "selected_god_runtime_missing" in natural["blockers"]
    assert natural["proof_boundary"] == (
        "candidate_report_is_not_natural_deliberation_proof"
    )
    assert natural["required_transcript_schema"] == "xmuse.operator_transcript.v1"
    assert natural["required_runtime_schema"] == "xmuse.god_runtime_continuity.v1"
    assert natural["required_proof_level"] == "real_provider_proof"
    assert natural["next_action"] == (
        "Capture a natural multi-GOD transcript and selected GOD runtime "
        "continuity, then run attempt_release_evidence for natural_deliberation."
    )
    assert natural["selected_god_runtime"]["fact_state"] == "manual_gap"
    assert natural["selected_god_runtime"]["manual_gap_reason"] == (
        "selected GOD CLI unavailable"
    )


def test_release_evidence_candidates_report_current_gaps_without_secrets(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation("Gaps")

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id=conversation.id,
        env={"XMUSE_MEMORYOS_LITE_URL": "http://example.test?token=secret-token"},
        memoryos_payload={},
    )

    natural = report["natural_deliberation"]["conversations"][0]
    provider = report["real_provider_runtime"]
    memoryos = report["live_memoryos"]
    github = report["github_server_truth"]
    assert natural["export_ready"] is False
    assert "natural_god_speech_act_messages_missing" in natural["blockers"]
    assert provider["trace_table_present"] is False
    assert provider["export_ready"] is False
    assert "peer_turn_latency_traces_table_missing" in provider["blockers"]
    assert provider["proof_boundary"] == "candidate_report_is_not_release_proof"
    assert provider["required_artifact_schema"] == "xmuse.real_provider_runtime.v1"
    assert provider["required_proof_level"] == "real_provider_proof"
    assert provider["next_action"] == (
        "Capture fresh and resume MCP writeback provider turns, then run "
        "attempt_release_evidence for real_provider_runtime with real "
        "runtime_backend and transport labels."
    )
    assert memoryos["configured"] is False
    assert "XMUSE_LIVE_MEMORYOS_LITE" in memoryos["missing_env_keys"]
    assert memoryos["proof_boundary"] == "candidate_report_is_not_live_memoryos_proof"
    assert memoryos["required_artifact_schema"] == "xmuse.memoryos_lite_trace.v1"
    assert memoryos["required_proof_level"] == "live_service_proof"
    assert memoryos["next_action"] == (
        "Configure live MemoryOS Lite and provide a complete task payload, then "
        "run attempt_release_evidence for live_memoryos to capture a live trace."
    )
    assert github["export_ready"] is False
    assert github["missing_payload_keys"] == ["repo", "pull_request_number"]
    assert github["blockers"] == ["github_server_truth_target_missing"]
    assert github["proof_boundary"] == (
        "candidate_report_is_not_github_server_truth_proof"
    )
    assert github["required_gate_kind"] == "github_server_truth"
    assert github["required_proof_level"] == "server_side_enforcement_proof"
    assert github["next_action"] == (
        "Provide repo and pull_request_number, then run attempt_release_evidence "
        "for github_server_truth to capture read-only GitHub server truth."
    )
    assert "token=secret-token" not in str(report)


def test_release_evidence_candidates_surface_existing_memoryos_trace_artifact(
    tmp_path: Path,
) -> None:
    trace_artifact = _write_memoryos_trace_artifact(tmp_path / "memoryos-trace.json")

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-1",
        env={"XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT": str(trace_artifact)},
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-1",
            "content": "live evidence",
            "query": "production evidence",
        },
    )

    memoryos = report["live_memoryos"]
    assert memoryos["configured"] is True
    assert memoryos["export_ready"] is False
    assert memoryos["missing_env_keys"] == [
        "XMUSE_LIVE_MEMORYOS_LITE",
        "XMUSE_MEMORYOS_LITE_URL",
    ]
    assert memoryos["missing_payload_keys"] == []
    assert memoryos["artifact_configured"] is True
    assert memoryos["artifact_gate_ready"] is True
    assert memoryos["artifact_path"] == str(trace_artifact)
    assert memoryos["artifact_gate_status"] == "ok"
    assert memoryos["artifact_proof_level"] == "live_service_proof"
    assert memoryos["artifact_trace_id"] == "xmuse-memoryos-trace:candidate-1"
    assert memoryos["artifact_trace_event_count"] == 1
    assert memoryos["artifact_source_ref_count"] == 4
    assert memoryos["artifact_upstream_source_ref_count"] == 2
    assert memoryos["artifact_target_ref_count"] == 2
    assert memoryos["source_authority"] == [
        "redacted_environment_presence",
        "operator_release_candidate_payload",
        "memoryos_live_trace_artifact",
        "memoryos_live_release_gate",
    ]
    assert memoryos["suggested_existing_artifact_action"] == {
        "action": "capture_release_evidence_pack",
        "kind": "live_memoryos",
        "payload_hints": {"memoryos_live_trace": str(trace_artifact)},
    }


def test_release_evidence_candidates_cli_reports_existing_memoryos_artifact_ready(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from xmuse.release_evidence_candidates import main

    trace_artifact = _write_memoryos_trace_artifact(tmp_path / "memoryos-trace.json")
    output = tmp_path / "candidates.json"
    monkeypatch.setenv("XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT", str(trace_artifact))

    exit_code = main(["--xmuse-root", str(tmp_path), "--output", str(output)])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["memoryos_export_ready"] is False
    assert summary["memoryos_artifact_ready"] is True
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["live_memoryos"]["artifact_gate_ready"] is True


def test_release_evidence_candidates_surface_existing_natural_artifacts(
    tmp_path: Path,
) -> None:
    transcript = _write_natural_transcript_artifact(tmp_path / "natural-transcript.json")
    runtime = _write_god_runtime_artifact(tmp_path / "god-runtime.json")

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id="conv-prod-1",
        env={
            "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH": str(transcript),
            "XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT": str(runtime),
        },
        memoryos_payload={},
    )

    natural = report["natural_deliberation"]
    assert natural["export_ready"] is False
    assert natural["artifact_configured"] is True
    assert natural["runtime_artifact_configured"] is True
    assert natural["artifact_gate_ready"] is True
    assert natural["artifact_gate_status"] == "ok"
    assert natural["artifact_proof_level"] == "real_provider_proof"
    assert natural["artifact_message_count"] == 2
    assert natural["artifact_distinct_god_count"] == 2
    assert natural["artifact_runtime_peer_god_ready_count"] == 2
    assert natural["artifact_path"] == str(transcript)
    assert natural["runtime_artifact_path"] == str(runtime)
    assert natural["source_authority"] == [
        "natural_deliberation_transcript_artifact",
        "selected_god_runtime_artifact",
        "natural_deliberation_release_gate",
    ]
    assert natural["suggested_existing_artifact_action"] == {
        "action": "capture_release_evidence_pack",
        "kind": "natural_deliberation",
        "payload_hints": {
            "natural_deliberation_transcript": str(transcript),
            "natural_deliberation_god_runtime": str(runtime),
        },
    }


def test_release_evidence_candidates_cli_reports_existing_natural_artifact_ready(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from xmuse.release_evidence_candidates import main

    transcript = _write_natural_transcript_artifact(tmp_path / "natural-transcript.json")
    runtime = _write_god_runtime_artifact(tmp_path / "god-runtime.json")
    output = tmp_path / "candidates.json"
    monkeypatch.setenv("XMUSE_NATURAL_GOD_TRANSCRIPT_PATH", str(transcript))
    monkeypatch.setenv("XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT", str(runtime))

    exit_code = main(["--xmuse-root", str(tmp_path), "--output", str(output)])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["natural_export_ready"] is False
    assert summary["natural_artifact_ready"] is True
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["natural_deliberation"]["artifact_gate_ready"] is True


def test_release_evidence_candidates_cli_writes_operator_candidate_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from xmuse.release_evidence_candidates import main

    conversation = ChatStore(tmp_path / "chat.db").create_conversation("CLI candidates")
    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json"
    )
    output = tmp_path / "candidates.json"
    monkeypatch.setenv("XMUSE_LIVE_MEMORYOS_LITE", "1")
    monkeypatch.setenv("XMUSE_MEMORYOS_LITE_URL", "http://memoryos-lite.example")

    exit_code = main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--conversation-id",
            conversation.id,
            "--repo-id",
            "iiyazu/Cross-Muse",
            "--workspace-id",
            "xmuse",
            "--god-id",
            "review",
            "--thread-id",
            "thread-1",
            "--blueprint-id",
            "bp-1",
            "--feature-id",
            "feature-1",
            "--lane-id",
            "lane-1",
            "--content",
            "live evidence",
            "--query",
            "production evidence",
            "--god-room-review-closure",
            str(review_closure),
            "--github-repo",
            "iiyazu/Cross-Muse",
            "--github-pull-request",
            "43",
            "--github-base-branch",
            "main",
            "--github-expected-head-sha",
            "1c1b3eb5fb1c970c12f4f5dc0607b656ea2b6045",
            "--github-required-check",
            "quality-gates",
            "--github-required-check",
            "contract-smoke-gates",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "xmuse.release_evidence_candidates.v1"
    assert report["conversation_id"] == conversation.id
    assert report["live_memoryos"]["configured"] is True
    assert report["live_memoryos"]["suggested_operator_action"]["payload_hints"] == {
        "conversation_id": conversation.id,
        "repo_id": "iiyazu/Cross-Muse",
        "workspace_id": "xmuse",
        "god_id": "review",
        "thread_id": "thread-1",
        "blueprint_id": "bp-1",
        "feature_id": "feature-1",
        "lane_id": "lane-1",
        "source_refs": [
            (
                "god-room-review-closure:graph-runtime:"
                "lane-runtime-evidence:lane-runtime-evidence-patch"
            ),
            "lane:lane-runtime-evidence",
            "lane:lane-runtime-evidence-patch",
            "god-room-event:evt-provider-speak",
            (
                "reports/god_room_patch_forward/"
                "graph-runtime.lane-runtime-evidence.patch-forward.json"
            ),
            (
                "reports/god_room_review_intake/"
                "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
            ),
            (
                "reports/god_room_review_verdicts/"
                "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
            ),
            "worker-candidate:patch-reviewed",
            "artifacts/lane-runtime-evidence-patch/result.json",
        ],
        "source_event_lineage_refs": ["god-room-event:evt-provider-speak"],
    }
    assert report["github_server_truth"]["export_ready"] is True
    assert report["github_server_truth"]["suggested_operator_action"][
        "payload_hints"
    ] == {
        "repo": "iiyazu/Cross-Muse",
        "pull_request_number": 43,
        "expected_head_sha": "1c1b3eb5fb1c970c12f4f5dc0607b656ea2b6045",
        "base_branch": "main",
        "required_checks": ["quality-gates", "contract-smoke-gates"],
    }


def test_release_evidence_candidates_cli_accepts_review_chain_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from xmuse.release_evidence_candidates import main

    review_closure = _write_god_room_review_closure_artifact(
        tmp_path / "review-closure.json",
        include_runner_recovery_lineage=True,
    )
    chain_proof = tmp_path / "review-chain-proof.json"
    capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=chain_proof,
    )
    output = tmp_path / "candidates.json"
    monkeypatch.setenv("XMUSE_LIVE_MEMORYOS_LITE", "1")
    monkeypatch.setenv("XMUSE_MEMORYOS_LITE_URL", "http://memoryos-lite.example")

    exit_code = main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--conversation-id",
            "conv-1",
            "--repo-id",
            "iiyazu/Cross-Muse",
            "--workspace-id",
            "xmuse",
            "--god-id",
            "review",
            "--thread-id",
            "thread-1",
            "--blueprint-id",
            "bp-1",
            "--feature-id",
            "feature-1",
            "--lane-id",
            "lane-runtime-evidence-patch",
            "--content",
            "live evidence",
            "--query",
            "production evidence",
            "--god-room-review-chain-proof",
            str(chain_proof),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    memoryos = report["live_memoryos"]
    assert memoryos["review_chain_proof_artifact_gate_ready"] is True
    assert "god_room_review_chain_proof_artifact" in memoryos["source_authority"]


def test_release_evidence_candidates_cli_accepts_closure_object(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from xmuse.release_evidence_candidates import main

    closure_path = tmp_path / "closure-object.json"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "source_authority": "review_closure_handoff_evaluation",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "source_refs": [
                "god-room-review-closure:graph-runtime:failed:terminal",
                "lane:lane-runtime-evidence-patch",
            ],
            "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
        },
    )
    closure_path.write_text(
        json.dumps(closure.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "candidates.json"
    monkeypatch.setenv("XMUSE_LIVE_MEMORYOS_LITE", "1")
    monkeypatch.setenv("XMUSE_MEMORYOS_LITE_URL", "http://memoryos-lite.example")

    exit_code = main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--conversation-id",
            "conv-1",
            "--repo-id",
            "iiyazu/Cross-Muse",
            "--workspace-id",
            "xmuse",
            "--god-id",
            "review",
            "--thread-id",
            "thread-1",
            "--blueprint-id",
            "bp-1",
            "--feature-id",
            "feature-1",
            "--lane-id",
            "lane-runtime-evidence-patch",
            "--content",
            "live evidence",
            "--query",
            "production evidence",
            "--closure-object",
            str(closure_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    memoryos = report["live_memoryos"]
    payload_hints = memoryos["suggested_operator_action"]["payload_hints"]
    assert memoryos["closure_object_artifact_gate_ready"] is True
    assert memoryos["closure_object_owner_ref_count"] == 1
    assert memoryos["closure_object_target_ref_count"] >= 2
    assert "closure_object_artifact" in memoryos["source_authority"]
    assert "lane:lane-runtime-evidence-patch" in payload_hints["source_refs"]


def test_release_evidence_candidates_accepts_github_server_truth_artifact(
    tmp_path: Path,
) -> None:
    github_truth = _write_github_server_truth_artifact(
        tmp_path / "github-truth.json",
        head_sha="head-123",
        expected_head_sha="head-123",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        env={},
        memoryos_payload={
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "base_branch": "main",
            "expected_head_sha": "head-123",
            "required_checks": [
                "quality-gates",
                "contract-smoke-gates",
                "real-runtime-integration-gate",
            ],
            "github_server_truth_artifact": str(github_truth),
        },
    )

    github = report["github_server_truth"]
    assert github["export_ready"] is True
    assert github["artifact_configured"] is True
    assert github["artifact_gate_ready"] is True
    assert github["artifact_gate_status"] == "ok"
    assert github["artifact_proof_level"] == "server_side_enforcement_proof"
    assert github["artifact_can_emit_pr_merged"] is False
    assert github["can_emit_pr_merged"] is False
    assert github["artifact_gap_reason"] == (
        "missing server-side truth: review_truth, merge_truth"
    )
    assert github["source_authority"] == [
        "operator_release_candidate_payload",
        "github_server_truth_export_action",
        "github_server_truth_artifact",
        "github_server_truth_release_gate",
    ]
    assert github["suggested_existing_artifact_action"] == {
        "action": "capture_release_evidence_pack",
        "kind": "github_server_truth",
        "payload_hints": {"github_server_truth": str(github_truth)},
    }
    assert "github_server_truth_artifact_not_ready" not in github["blockers"]
    assert github["proof_boundary"] == (
        "candidate_report_is_not_github_server_truth_proof"
    )


def test_release_evidence_candidates_rejects_github_truth_head_mismatch(
    tmp_path: Path,
) -> None:
    github_truth = _write_github_server_truth_artifact(
        tmp_path / "github-truth.json",
        head_sha="old-head",
        expected_head_sha="old-head",
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        env={},
        memoryos_payload={
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "base_branch": "main",
            "expected_head_sha": "new-head",
            "github_server_truth_artifact": str(github_truth),
        },
    )

    github = report["github_server_truth"]
    assert github["artifact_configured"] is True
    assert github["artifact_gate_ready"] is False
    assert github["artifact_gate_status"] == "manual_gap"
    assert github["artifact_proof_level"] == "manual_gap"
    assert github["artifact_can_emit_pr_merged"] is False
    assert github["can_emit_pr_merged"] is False
    assert github["artifact_head_sha"] == "old-head"
    assert github["artifact_expected_head_sha"] == "new-head"
    assert github["artifact_head_sha_matches_expected"] is False
    assert "github_server_truth_artifact_not_ready" in github["blockers"]
    assert "github_server_truth_artifact" not in github["source_authority"]
    assert "suggested_existing_artifact_action" not in github


def test_release_evidence_candidates_recomputes_github_merge_truth(
    tmp_path: Path,
) -> None:
    github_truth = _write_github_server_truth_artifact(
        tmp_path / "github-truth.json",
        head_sha="head-123",
        expected_head_sha="head-123",
        can_emit_pr_merged=True,
    )

    report = build_release_evidence_candidate_report(
        tmp_path,
        env={},
        memoryos_payload={
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "base_branch": "main",
            "expected_head_sha": "head-123",
            "github_server_truth_artifact": str(github_truth),
        },
    )

    github = report["github_server_truth"]
    assert github["artifact_gate_ready"] is True
    assert github["artifact_can_emit_pr_merged"] is False
    assert github["can_emit_pr_merged"] is False
    assert github["artifact_gap_reason"] == (
        "missing server-side truth: review_truth, merge_truth"
    )


def test_release_evidence_candidates_cli_accepts_github_truth_artifact(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_candidates import main

    github_truth = _write_github_server_truth_artifact(
        tmp_path / "github-truth.json",
        head_sha="head-cli",
        expected_head_sha="head-cli",
    )
    output = tmp_path / "candidates.json"

    exit_code = main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--github-repo",
            "iiyazu/Cross-Muse",
            "--github-pull-request",
            "43",
            "--github-base-branch",
            "main",
            "--github-expected-head-sha",
            "head-cli",
            "--github-server-truth-artifact",
            str(github_truth),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    github = report["github_server_truth"]
    assert github["artifact_gate_ready"] is True
    assert github["artifact_proof_level"] == "server_side_enforcement_proof"
    assert github["can_emit_pr_merged"] is False


def test_release_evidence_candidates_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-release-evidence-candidates"]
        == "xmuse.release_evidence_candidates:main"
    )


def _seed_selected_god_runtime(tmp_path: Path, conversation_id: str) -> None:
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conversation_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="operator-action:select-codex",
        idempotency_key=f"select:{conversation_id}:codex.god",
        selected_at_utc="2026-06-13T00:00:00Z",
    )


def _seed_natural_conversation(tmp_path: Path) -> str:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Candidates")
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    reviewer = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="opencode-prod",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    architect_session = registry.create(
        role="architect",
        agent_name="architect-god",
        runtime="codex",
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        model="gpt-5.5",
    )
    reviewer_session = registry.create(
        role="review",
        agent_name="review-god",
        runtime="codex",
        session_address="@review",
        session_inbox_id="inbox-review",
        conversation_id=conversation.id,
        participant_id=reviewer.participant_id,
        model="gpt-5.5-review",
    )
    registry.update_provider_binding(
        architect_session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.record_heartbeat(
        architect_session.god_session_id,
        heartbeat_at_utc=_utcnow(),
        status="active",
    )
    registry.update_provider_binding(
        reviewer_session.god_session_id,
        provider_session_id="opencode-thread-1",
        provider_session_kind="opencode_session",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.record_heartbeat(
        reviewer_session.god_session_id,
        heartbeat_at_utc=_utcnow(),
        status="active",
    )
    chat.add_message(
        conversation_id=conversation.id,
        author=architect.participant_id,
        role="assistant",
        content="I propose freezing bp-1.",
        envelope_type="god_speech_act",
        envelope_json=_speech(
            message_id="speech-1",
            conversation_id=conversation.id,
            sender_god="architect-god",
        ),
    )
    chat.add_message(
        conversation_id=conversation.id,
        author=reviewer.participant_id,
        role="assistant",
        content="I vote approve.",
        envelope_type="god_speech_act",
        envelope_json=_speech(
            message_id="speech-2",
            conversation_id=conversation.id,
            sender_god="review-god",
        ),
    )
    return conversation.id


def _seed_provider_traces(tmp_path: Path, conversation_id: str) -> None:
    db = tmp_path / "chat.db"
    participant = ParticipantStore(db).list_by_conversation(conversation_id)[0]
    traces = PeerTurnLatencyTraceStore(db)
    for inbox_id, offset in (("inbox-fresh", 0.0), ("inbox-resume", 10.0)):
        traces.record(
            conversation_id=conversation_id,
            inbox_item_id=inbox_id,
            participant_id=participant.participant_id,
            target_role="architect",
            message_created_at="2026-06-12T00:00:00Z",
            inbox_claimed_at="2026-06-12T00:00:01Z",
            delivery_started_at=offset + 1.0,
            provider_turn_started_at=offset + 2.0,
            first_delta_at=None,
            writeback_at=offset + 4.0,
            total_latency_ms=3000,
            delivery_mode="mcp_writeback",
            degraded_reason=None,
            stage_timings={
                "ray_actor_delivery_start": {"at": offset + 1.0},
                "codex_app_server_turn_start": {"at": offset + 2.0},
                "chat_post_message": {"at": offset + 3.0},
                "trace_persisted": {"at": offset + 4.0},
            },
        )


def _speech(
    *,
    message_id: str,
    conversation_id: str,
    sender_god: str,
) -> dict[str, object]:
    message = GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id=conversation_id,
        thread_id="thread-1",
        sender_god=sender_god,
        targets=["blueprint:bp-1"],
        speech_act=GodSpeechAct.VOTE,
        references=["blueprint:bp-1"],
        lane_scope="lane:lane-1",
        confidence=0.91,
        memory_refs=[],
        payload={"decision_scope": "blueprint.freeze", "vote": "approve"},
    )
    return {
        "schema_version": 1,
        "type": "god_speech_act",
        "message": message.model_dump(mode="json"),
    }


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_memoryos_trace_artifact(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.memoryos_lite_trace.v1",
                "trace_id": "xmuse-memoryos-trace:candidate-1",
                "proof_level": "live_service_proof",
                "fact_state": "observed",
                "namespace_uri": "memory://repo/iiyazu/Cross-Muse/workspace/xmuse",
                "session_id": "ses-live",
                "trace_events": [
                    {
                        "kind": "ingest",
                        "source": "memoryos-lite",
                        "metadata": {"xmuse_source_refs": ["github:pr:43"]},
                    }
                ],
                "source_refs": ["conversation:conv-1"],
                "target_refs": [
                    "memoryos:namespace:memory://repo/iiyazu/Cross-Muse/workspace/xmuse",
                    "memoryos:session:ses-live",
                ],
                "estimated_tokens": 128,
                "blockers": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_github_server_truth_artifact(
    path: Path,
    *,
    head_sha: str,
    expected_head_sha: str,
    can_emit_pr_merged: bool = False,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "github_server_side_truth_capture.v1",
                "repo": "iiyazu/Cross-Muse",
                "pull_request_number": 43,
                "required_checks": [
                    "quality-gates",
                    "contract-smoke-gates",
                    "real-runtime-integration-gate",
                ],
                "proof_level": "manual_gap",
                "pull_request_state": "open",
                "draft": True,
                "mergeable": True,
                "mergeable_state": "clean",
                "head_sha": head_sha,
                "workflow_run_id": 81288711769,
                "check_run_ids": [81288711769, 81288711727, 81288711726],
                "expected_source_app": "github-actions",
                "branch_protection_snapshot": {
                    "required_status_checks": {
                        "checks": [
                            {"context": "quality-gates"},
                            {"context": "contract-smoke-gates"},
                            {"context": "real-runtime-integration-gate"},
                        ]
                    },
                    "required_conversation_resolution": {"enabled": True},
                },
                "ruleset_snapshot": None,
                "review_event_id": None,
                "reviewer_login": None,
                "code_owner_review_verified": False,
                "internal_review_artifact": None,
                "internal_reviewer": None,
                "internal_reviewed_head_sha": None,
                "internal_review_verified": False,
                "merge_commit_sha": "merge-candidate",
                "merged_at": None,
                "merge_event_id": None,
                "gap_reason": "missing server-side truth: review_truth, merge_truth",
                "expected_head_sha": expected_head_sha,
                "head_sha_matches_expected": head_sha == expected_head_sha,
                "can_emit_pr_merged": can_emit_pr_merged,
                "merged": can_emit_pr_merged,
                "capture_mode": "opt_in_read_only_gh_api",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_room_review_closure_artifact(
    path: Path,
    *,
    server_truth_status: str = "not_server_truth",
    include_runner_recovery_lineage: bool = False,
    create_candidate_artifact: bool = True,
) -> Path:
    source_event_lineage = [
        {
            "event_id": "evt-provider-speak",
            "event_type": "speak",
            "participant_id": "part-review",
            "god_id": "god-review",
            "proof_level": "contract_proof",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    candidate_artifact_ref = "artifacts/lane-runtime-evidence-patch/result.json"
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
    payload: dict[str, object] = {
        "schema_version": "xmuse.god_room_lane_review_closure.v1",
        "proof_level": "contract_proof",
        "review_truth_status": "independent_review_artifact",
        "execution_truth_status": "candidate_reviewed",
        "server_truth_status": server_truth_status,
        "release_evidence_handoff_status": "candidate_input_ready",
        "conversation_id": "conv-runtime",
        "graph_id": "graph-runtime",
        "failed_lane_id": "lane-runtime-evidence",
        "terminal_lane_id": "lane-runtime-evidence-patch",
        "patch_forward_artifact": patch_forward_ref,
        "patch_lane_review_intake_artifact": patch_intake_ref,
        "patch_lane_review_verdict_artifact": patch_verdict_ref,
        "candidate_refs": [
            "worker-candidate:patch-reviewed",
            candidate_artifact_ref,
        ],
        "cited_candidate_refs": [
            "worker-candidate:patch-reviewed",
            candidate_artifact_ref,
        ],
        "cited_candidate_artifact_refs": [candidate_artifact_ref],
        "terminal_review_verdict": {
            "id": "god-room-review-verdict-merge",
            "decision": "merge",
            "evidence_refs": [
                patch_intake_ref,
                "worker-candidate:patch-reviewed",
                candidate_artifact_ref,
            ]
        },
        "review_plane_sync_status": "review_plane_store_updated",
        "review_plane_verdict_ref": (
            "review-plane:lane-runtime-evidence-patch:verdict-1"
        ),
        "graph_status_source_authority": "feature_graph_status_store",
        "graph_status_merge_status": "verified_merged",
        "source_event_lineage": source_event_lineage,
        "terminal_feature_graph_status": {
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "status_id": "fgs:graph-runtime-feature-runtime:merged",
            "status": "merged",
            "blueprint_proof_level": "contract_proof",
            "active_lane_ids": [],
            "completed_lane_ids": ["lane-runtime-evidence-patch"],
            "source_event_lineage": source_event_lineage,
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
    }
    if include_runner_recovery_lineage:
        _write_session_artifact(
            path.parent / "reports/runner-recovery-proof.json",
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
        _write_session_artifact(
            path.parent / "reports/lane-recovery/lane-runtime-evidence.json",
            {
                "schema_version": "xmuse.lane_recovery.v1",
                "lane_id": "lane-runtime-evidence",
                "status": "blocked",
            },
        )
        payload["runner_recovery_proof_lineage"] = {
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
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    if create_candidate_artifact:
        candidate_path = path.parent / candidate_artifact_ref
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(
            json.dumps(
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
                    "feature_graph_status_id": (
                        "fgs:graph-runtime-feature-runtime:reviewing"
                    ),
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
                        "source_event_lineage": source_event_lineage,
                    },
                    "lane_id": "lane-runtime-evidence-patch",
                    "run_id": "platform-runner:run-1",
                    "worker_id": "platform-runner",
                    "runner_session_id": "runner-session-1",
                    "runner_session_ref": "work/runner_sessions/runner-session-1.json",
                    "source_refs": ["worker-candidate:patch-reviewed"],
                    "output_refs": [candidate_artifact_ref],
                    "changed_file_refs": [],
                    "verification_refs": [
                        "uv run pytest tests/xmuse/test_release_evidence_candidates.py -q",
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
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        payload["cited_candidate_artifact_lineage"] = [
            load_local_execution_candidate_lineage(
                root=path.parent,
                artifact_ref=candidate_artifact_ref,
                lane_id="lane-runtime-evidence-patch",
                graph_id="graph-runtime",
                conversation_id="conv-runtime",
            )
        ]
        _write_session_artifact(
            path.parent / "work" / "runner_sessions" / "runner-session-1.json",
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
                "candidate_artifact_refs": [candidate_artifact_ref],
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
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_session_artifact(
            path.parent / patch_forward_ref,
            {
                "schema_version": "xmuse.god_room_lane_patch_forward.v1",
                "proof_level": "contract_proof",
                "conversation_id": "conv-runtime",
                "graph_id": "graph-runtime",
                "failed_lane_id": "lane-runtime-evidence",
                "patch_lane_id": "lane-runtime-evidence-patch",
                "review_verdict_artifact": patch_forward_verdict_ref,
                "patch_forward_link": {
                    "failed_lane_id": "lane-runtime-evidence",
                    "patch_lane_id": "lane-runtime-evidence-patch",
                    "verdict_ref": (
                        "god_room_review_verdict:"
                        "god-room-review-verdict-patch-forward"
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
        _write_session_artifact(
            path.parent / patch_forward_verdict_ref,
            {
                "schema_version": "xmuse.god_room_lane_review_verdict.v1",
                "proof_level": "contract_proof",
                "review_truth_status": "independent_review_artifact",
                "server_truth_status": "not_server_truth",
                "conversation_id": "conv-runtime",
                "graph_id": "graph-runtime",
                "lane_id": "lane-runtime-evidence",
                "review_verdict": {
                    "id": "god-room-review-verdict-patch-forward",
                    "decision": "patch-forward",
                    "evidence_refs": patch_forward_evidence_refs[1:],
                },
            },
        )
        _write_session_artifact(
            path.parent / patch_intake_ref,
            {
                "schema_version": "xmuse.god_room_lane_review_intake.v1",
                "source_authority": "feature_graph_status_store+lane_dag_artifact",
                "proof_level": "contract_proof",
                "review_truth_status": "pending_independent_review",
                "conversation_id": "conv-runtime",
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
                    "source_event_lineage": source_event_lineage,
                },
                "lane_id": "lane-runtime-evidence-patch",
                "blueprint_proof_level": "contract_proof",
                "source_event_lineage": source_event_lineage,
                "candidate_truth_status": "candidate_only",
                "execution_artifact_refs": [candidate_artifact_ref],
            },
        )
        _write_session_artifact(
            path.parent / patch_verdict_ref,
            {
                "schema_version": "xmuse.god_room_lane_review_verdict.v1",
                "proof_level": "contract_proof",
                "review_truth_status": "independent_review_artifact",
                "server_truth_status": "not_server_truth",
                "conversation_id": "conv-runtime",
                "graph_id": "graph-runtime",
                "lane_id": "lane-runtime-evidence-patch",
                "reviewer_id": "review-god",
                "review_plane_verdict_ref": (
                    "review-plane:lane-runtime-evidence-patch:verdict-1"
                ),
                "review_verdict": {
                    "id": "god-room-review-verdict-merge",
                    "decision": "merge",
                    "evidence_refs": [
                        patch_intake_ref,
                        "worker-candidate:patch-reviewed",
                        candidate_artifact_ref,
                    ],
                },
            },
        )
    _write_graph_authority(
        root=path.parent,
        conversation_id="conv-runtime",
        source_event_lineage=source_event_lineage,
        completed_lane_ids=["lane-runtime-evidence-patch"],
        graph_set_lane_ids=["lane-runtime-evidence-patch"],
    )
    return path


def _write_graph_authority(
    *,
    root: Path,
    conversation_id: str,
    source_event_lineage: list[dict[str, object]],
    completed_lane_ids: list[str],
    graph_set_lane_ids: list[str],
) -> None:
    _write_session_artifact(
        root / "graph_sets" / f"{conversation_id}--graph-runtime-graph-set.json",
        {
            "id": "graph-runtime-graph-set",
            "version": 1,
            "source_refs": ["lane_dag:graph-runtime"],
            "source_event_lineage": source_event_lineage,
            "feature_plan": {
                "id": "graph-runtime-feature-plan",
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
                        "graph_id": "graph-runtime-feature-runtime",
                        "expected_touched_areas": [],
                        "blueprint_refs": ["blueprint:runtime"],
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-runtime-feature-runtime",
                    "conversation_id": conversation_id,
                    "resolution_id": "resolution-runtime",
                    "version": 1,
                    "status": "planned",
                    "source_refs": ["lane_dag:graph-runtime"],
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
                        for lane_id in graph_set_lane_ids
                    ],
                }
            ],
        },
    )
    _write_session_artifact(
        root / "feature_graph_statuses.json",
        {
            "schema_version": "xmuse.feature_graph_statuses.v1",
            "statuses": [
                {
                    "status_id": "fgs:graph-runtime-feature-runtime:merged",
                    "conversation_id": conversation_id,
                    "planning_run_id": "planning-runtime",
                    "graph_set_id": "graph-runtime-graph-set",
                    "graph_set_version": 1,
                    "feature_plan_id": "graph-runtime-feature-plan",
                    "feature_plan_version": 1,
                    "feature_id": "feature-runtime",
                    "feature_graph_id": "graph-runtime-feature-runtime",
                    "blueprint_proof_level": "contract_proof",
                    "source_event_lineage": source_event_lineage,
                    "status": "merged",
                    "ready_lane_ids": [],
                    "active_lane_ids": [],
                    "completed_lane_ids": completed_lane_ids,
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


def _write_session_artifact(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_god_room_runtime_closure_evidence(
    path: Path,
    *,
    proof_level: str = "contract_proof",
    review_closure_artifact: Path | None = None,
) -> Path:
    artifacts = ["reports/god-room-runtime-closure.json"]
    source_refs = [
        "god-room-event:evt-provider-speak",
        (
            "provider_response_artifact:"
            "reports/provider-responses/provider-response-1.json"
        ),
        (
            "speaker_response_artifact:"
            "reports/god_room_speaker_responses/speaker-response-1.json"
        ),
        "lane:lane-runtime-evidence-patch",
    ]
    review_closure_details: dict[str, object] | None = None
    if review_closure_artifact is not None:
        artifacts.append(str(review_closure_artifact))
        source_refs.extend(
            [
                (
                    "god-room-review-closure:"
                    "graph-runtime:lane-runtime-evidence:"
                    "lane-runtime-evidence-patch"
                ),
                "artifacts/lane-runtime-evidence-patch/result.json",
            ]
        )
        review_closure_details = {
            "status": "candidate_input_ready",
            "proof_level": "contract_proof",
            "current_handoff_gate_ready": True,
        }
    god_room_runtime_closure: dict[str, object] = {
        "authority": "god_room_runtime_closure_contract",
        "multi_turn_provider_speech": {
            "status": "completed",
            "proof_level": "opt_in_live_proof",
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
        "github_truth": {"merge_truth": "missing"},
    }
    if review_closure_details is not None:
        god_room_runtime_closure["review_closure"] = review_closure_details
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.production_evidence.v1",
                "stage_id": "S8",
                "action": "god_room_runtime_closure_indexed",
                "status": "manual_gap",
                "proof_level": proof_level,
                "source_authority": "god_room_runtime_closure_contract",
                "source_refs": source_refs,
                "target_refs": ["lane:lane-runtime-evidence-patch"],
                "commands": [],
                "test_results": [],
                "artifacts": artifacts,
                "blocked_reason": "github truth artifact is missing",
                "owner": "codex",
                "next_action": "Attach missing server truth when available.",
                "generated_at": "2026-06-14T11:30:00Z",
                "god_room_runtime_closure": god_room_runtime_closure,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_natural_transcript_artifact(path: Path) -> Path:
    path.write_text(
        json.dumps(
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
                        "provider_id": "codex",
                        "provider_profile": "codex-prod",
                        "session_id": "codex-session-2",
                        "speech_act": "vote",
                        "decision_scope": "blueprint.freeze",
                        "source_refs": ["message:msg-1"],
                        "target_refs": ["blueprint:prod:1"],
                        "blocking": False,
                    },
                ],
                "blockers": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_god_runtime_artifact(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.god_runtime_continuity.v1",
                "conversation_id": "conv-prod-1",
                "proof_level": "real_provider_proof",
                "fact_state": "observed",
                "source_refs": ["god_cli_selection:conv-prod-1"],
                "items": [
                    {
                        "god_id": "architect-god",
                        "cli_id": "codex.god",
                        "peer_god_ready": True,
                        "bounded": False,
                        "provider_session_ready": True,
                        "proof_level": "real_provider_proof",
                        "source_refs": ["god_session:architect"],
                    },
                    {
                        "god_id": "review-god",
                        "cli_id": "codex.god",
                        "peer_god_ready": True,
                        "bounded": False,
                        "provider_session_ready": True,
                        "proof_level": "real_provider_proof",
                        "source_refs": ["god_session:review"],
                    },
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
