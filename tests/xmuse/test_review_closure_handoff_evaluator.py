from __future__ import annotations

import json
from pathlib import Path

from tests.xmuse.closure_test_fixtures import (
    release_handoff_payload as _release_handoff_payload,
)
from tests.xmuse.closure_test_fixtures import (
    review_closure_payload as _review_closure_payload,
)
from xmuse_core.platform.god_room_review_handoff import (
    REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION,
    build_release_handoff_gate_evaluation_for_closure,
    build_review_closure_handoff_evaluation,
    load_and_evaluate_review_closure_handoff,
)
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
)


def test_review_closure_handoff_evaluation_marks_ready_contract_handoff(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["schema_version"] == (
        REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION
    )
    assert evaluation["status"] == "ready"
    assert evaluation["review_truth_status"] == "independent_review_artifact"
    assert evaluation["execution_truth_status"] == "candidate_reviewed"
    assert evaluation["server_truth_status"] == "not_server_truth"
    assert evaluation["required_forbidden_claims_present"] is True
    assert evaluation["candidate_ref_count"] == 2
    assert evaluation["cited_candidate_ref_count"] == 2
    assert evaluation["candidate_artifact_ref_count"] == 1
    assert evaluation["source_event_lineage_count"] == 1
    assert evaluation["source_event_lineage_refs"] == [
        "god-room-event:evt-review-provider-speak",
        "provider_response_artifact:reports/provider-response-1.json",
        "god-room-event:evt-review-provider-speak:source",
    ]
    assert evaluation["issues"] == []


def test_review_closure_handoff_evaluation_preserves_manual_gap_forbidden_claims(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["forbidden_claims"] = [
        claim
        for claim in review_closure["forbidden_claims"]
        if claim != "live_memoryos"
    ]

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["status"] == "manual_gap"
    assert evaluation["required_forbidden_claims_present"] is False
    assert evaluation["missing_forbidden_claims"] == ["live_memoryos"]
    assert "review_closure_handoff_not_ready" in evaluation["manual_gaps"]
    assert any("missing forbidden claims" in issue for issue in evaluation["issues"])


def test_review_closure_handoff_evaluation_blocks_server_truth_overclaim(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["server_truth_status"] = "github_review_truth"

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["status"] == "blocked"
    assert evaluation["server_truth_status"] == "github_review_truth"
    assert "review_closure_handoff_not_ready" in evaluation["manual_gaps"]
    assert any("overclaims server truth" in issue for issue in evaluation["issues"])


def test_release_handoff_gate_rejects_review_closure_graph_scope_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["graph_id"] = "graph-other"

    gate = build_release_handoff_gate_evaluation_for_closure(
        release_handoff=_release_handoff_payload(),
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        review_closure=review_closure,
    )

    assert gate["status"] == "false"
    assert gate["severity"] == "manual_gap"
    assert gate["reason"] == (
        "release handoff graph_id does not match review closure graph_id"
    )


def test_release_handoff_gate_rejects_review_closure_lane_scope_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["terminal_lane_id"] = "lane-other"

    gate = build_release_handoff_gate_evaluation_for_closure(
        release_handoff=_release_handoff_payload(),
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        review_closure=review_closure,
    )

    assert gate["status"] == "false"
    assert gate["severity"] == "manual_gap"
    assert gate["reason"] == (
        "release handoff lane scope does not match review closure lane scope"
    )


def test_release_handoff_gate_rejects_missing_required_forbidden_claims() -> None:
    handoff = _release_handoff_payload()
    handoff["forbidden_claims"] = ["ready_to_merge"]

    gate = build_release_handoff_gate_evaluation_for_closure(
        release_handoff=handoff,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    )

    assert gate["status"] == "false"
    assert gate["severity"] == "manual_gap"
    assert "release handoff missing forbidden claims" in gate["reason"]
    assert "live_memoryos" in gate["reason"]
    assert "github_review_truth" in gate["reason"]


def test_release_handoff_gate_accepts_scoped_release_evidence_candidates() -> None:
    gate = build_release_handoff_gate_evaluation_for_closure(
        release_handoff={
            "schema_version": "xmuse.release_evidence_candidates.v1",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence-patch",
            "server_truth_status": "not_server_truth",
            "source_refs": ["release-evidence-candidate:graph-runtime"],
            "forbidden_claims": list(LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS),
        },
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    )

    assert gate["status"] == "true"
    assert gate["severity"] == "ok"
    assert gate["source_refs"] == ["release-evidence-candidate:graph-runtime"]


def test_release_handoff_gate_rejects_unscoped_release_evidence_candidates() -> None:
    gate = build_release_handoff_gate_evaluation_for_closure(
        release_handoff={
            "schema_version": "xmuse.release_evidence_candidates.v1",
            "server_truth_status": "not_server_truth",
            "source_refs": ["release-evidence-candidate:graph-runtime"],
            "forbidden_claims": list(LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS),
        },
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    )

    assert gate["status"] == "false"
    assert gate["severity"] == "manual_gap"
    assert gate["reason"] == "release evidence candidate handoff graph_id is missing"


def test_load_and_evaluate_review_closure_handoff_uses_artifact_ref(
    tmp_path: Path,
) -> None:
    review_closure_path = tmp_path / "review-closure.json"
    review_closure_path.write_text(
        json.dumps(_review_closure_payload(tmp_path), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    evaluation = load_and_evaluate_review_closure_handoff(
        root=tmp_path,
        review_closure_ref="review-closure.json",
    )

    assert evaluation["schema_version"] == (
        REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION
    )
    assert evaluation["status"] == "ready"
    assert evaluation["candidate_artifact_ref_count"] == 1
    assert evaluation["source_ref_count"] > 0


def test_load_and_evaluate_review_closure_handoff_rejects_escaping_ref(
    tmp_path: Path,
) -> None:
    evaluation = load_and_evaluate_review_closure_handoff(
        root=tmp_path,
        review_closure_ref="../review-closure.json",
    )

    assert evaluation["schema_version"] == (
        REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION
    )
    assert evaluation["status"] == "manual_gap"
    assert evaluation["handoff_gate_ready"] is False
    assert evaluation["handoff_summary"] == (
        "GOD room review closure artifact escapes xmuse root."
    )
    assert "review_closure_handoff_not_ready" in evaluation["manual_gaps"]
