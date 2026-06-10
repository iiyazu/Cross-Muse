from __future__ import annotations

from xmuse_core.knowledge import cluster_artifacts


def test_cluster_module_adds_occurrences_and_recomputes_promotion() -> None:
    cluster = {
        "cluster_id": "cluster-1",
        "fingerprint": "ack_non_usable",
        "summary": "ACK level is blocked",
        "occurrences": [],
        "source_refs": [],
    }
    record_a = {
        "record_id": "error-a",
        "feature_id": "alpha",
        "fingerprint": "ack_non_usable",
        "summary": "ACK level is blocked",
        "source_ref": {"path": "a", "digest": "sha256:a"},
        "root_cause_status": "confirmed",
        "deterministic_invariant": "ack_non_usable",
        "verification_evidence": False,
    }
    record_b = {
        "record_id": "error-b",
        "feature_id": "beta",
        "fingerprint": "ack_non_usable",
        "summary": "ACK level is blocked",
        "source_ref": {"path": "b", "digest": "sha256:b", "source_run_id": "run-b"},
        "root_cause_status": "suspected",
        "deterministic_invariant": "ack_non_usable",
        "verification_evidence": True,
    }

    cluster_artifacts.add_record_to_cluster(cluster, record_a)
    cluster_artifacts.add_record_to_cluster(cluster, record_b)
    cluster_artifacts.recompute_cluster(cluster, now="2026-05-25T00:00:00Z", run_id="run-1")

    assert cluster["occurrence_count"] == 2
    assert cluster["feature_ids"] == ["alpha", "beta"]
    assert cluster["source_run_ids"] == ["run-b"]
    assert cluster["root_cause_status"] == "confirmed"
    assert cluster["promotion_stage"] == "method_created"
    assert cluster["promotion_blockers"] == []


def test_cluster_module_renders_draft_artifacts() -> None:
    cluster = {
        "cluster_id": "cluster-1",
        "fingerprint": "ack_non_usable",
        "occurrence_count": 2,
        "source_refs": [{"path": "xmuse/work/features/a/ack.json", "digest": "sha256:a"}],
    }
    method = {
        "method_id": "method-1",
    }

    method_body = cluster_artifacts.render_method(cluster, "method-1")
    proposal_body = cluster_artifacts.render_skill_proposal(method, "proposal-1")

    assert "# Draft Method: method-1" in method_body
    assert "xmuse/work/features/a/ack.json" in method_body
    assert "# Draft Skill Proposal: proposal-1" in proposal_body
    assert "Source method: `method-1`" in proposal_body
