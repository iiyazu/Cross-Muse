"""Cluster and draft-artifact helpers for Xmuse error knowledge."""

from __future__ import annotations

from typing import Any

from xmuse_core.knowledge.maintainer_contracts import (
    DETERMINISTIC_INVARIANTS,
    NON_PROMOTABLE_PREFIXES,
    source_digest_for_refs,
    unique_source_refs,
)


def add_record_to_cluster(cluster: dict[str, Any], record: dict[str, Any]) -> None:
    occurrence = {
        "record_id": record["record_id"],
        "feature_id": record["feature_id"],
        "source_digest": record["source_ref"]["digest"],
        "source_path": record["source_ref"]["path"],
        "root_cause_status": record["root_cause_status"],
        "deterministic_invariant": record.get("deterministic_invariant"),
        "verification_evidence": record.get("verification_evidence", False),
    }
    source_run_id = record["source_ref"].get("source_run_id")
    if source_run_id:
        occurrence["source_run_id"] = source_run_id
    if not any(item["record_id"] == occurrence["record_id"] for item in cluster["occurrences"]):
        cluster["occurrences"].append(occurrence)
    if not any(
        ref["path"] == record["source_ref"]["path"]
        and ref["digest"] == record["source_ref"]["digest"]
        for ref in cluster["source_refs"]
    ):
        cluster["source_refs"].append(record["source_ref"])


def recompute_cluster(cluster: dict[str, Any], *, now: str, run_id: str) -> None:
    occurrences = cluster["occurrences"]
    feature_ids = sorted({item["feature_id"] for item in occurrences})
    source_digests = sorted({item["source_digest"] for item in occurrences})
    source_run_ids = sorted(
        {item["source_run_id"] for item in occurrences if item.get("source_run_id")}
    )
    cluster["last_seen_at"] = now
    cluster["last_knowledge_run_id"] = run_id
    cluster["occurrence_count"] = len(occurrences)
    cluster["feature_ids"] = feature_ids
    cluster["feature_count"] = len(feature_ids)
    cluster["source_digest_count"] = len(source_digests)
    cluster["source_run_ids"] = source_run_ids
    cluster["source_run_count"] = len(source_run_ids)
    cluster["root_cause_status"] = (
        "confirmed"
        if any(item["root_cause_status"] == "confirmed" for item in occurrences)
        else "suspected"
    )

    blockers: list[str] = []
    stage = "observed"
    if len(occurrences) >= 2:
        stage = "method_candidate"
        if len(feature_ids) < 2:
            blockers.append("same-feature recurrence is not cross-feature evidence")
        if str(cluster["fingerprint"]).startswith(NON_PROMOTABLE_PREFIXES):
            if "same-feature recurrence is not cross-feature evidence" not in blockers:
                blockers.append("environment or baseline findings require independent evidence")
        allowlisted = any(
            item.get("deterministic_invariant") in DETERMINISTIC_INVARIANTS
            for item in occurrences
        )
        if (
            not str(cluster["fingerprint"]).startswith(NON_PROMOTABLE_PREFIXES)
            and len(feature_ids) > 1
            and (len(source_run_ids) > 1 or allowlisted or len(occurrences) >= 2)
        ):
            stage = "method_created"
            blockers = []
    cluster["promotion_stage"] = stage
    cluster["promotion_blockers"] = blockers
    cluster["source_refs"] = unique_source_refs(cluster["source_refs"])
    cluster["source_digest"] = source_digest_for_refs(cluster["source_refs"])


def render_method(cluster: dict[str, Any], method_id: str) -> str:
    sources = "\n".join(
        f"- `{ref['path']}` ({ref['digest']})" for ref in cluster["source_refs"]
    )
    return "\n".join(
        [
            f"# Draft Method: {method_id}",
            "",
            "Status: draft/quarantined. This is local Xmuse knowledge only.",
            "",
            f"Cluster: `{cluster['cluster_id']}`",
            f"Fingerprint: `{cluster['fingerprint']}`",
            f"Occurrences: {cluster['occurrence_count']}",
            "",
            "Suggested local method:",
            "1. Verify the cited control-plane artifact first.",
            "2. Repair from the deterministic blocker or confirmed evidence.",
            "3. Keep Master approval and merge gates unchanged.",
            "",
            "Sources:",
            sources,
            "",
        ]
    )


def render_skill_proposal(method: dict[str, Any], proposal_id: str) -> str:
    return "\n".join(
        [
            f"# Draft Skill Proposal: {proposal_id}",
            "",
            "Status: draft/quarantined. This proposal is not installed or active.",
            "",
            f"Source method: `{method['method_id']}`",
            "",
            "Proposal:",
            (
                "Capture the repeated Xmuse control-plane repair pattern as a "
                "future skill only after human review."
            ),
            "",
        ]
    )
