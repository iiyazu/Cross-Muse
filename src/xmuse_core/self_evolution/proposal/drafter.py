from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from xmuse_core.self_evolution.dedup.identity import (
    dedup_identity,
    dedup_signal_refs,
)
from xmuse_core.self_evolution.dedup.identity import (
    has_duplicate_evolution as _has_duplicate_evolution,
)
from xmuse_core.self_evolution.models import (
    EvolutionProposal,
    EvolutionProposalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore

if TYPE_CHECKING:
    from xmuse_core.self_evolution.decomposer import TrackDecomposer

__all__ = [
    "blueprint_ref",
    "blueprint_set_id",
    "candidate_lane_id",
    "candidate_prompt",
    "dedup_signal_refs",
    "draft",
    "has_duplicate_evolution",
    "select_target_track",
]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def draft(
    *,
    evidence: StructuredEvidenceBundle,
    target_track: str,
    decomposer: TrackDecomposer,
    store: SelfEvolutionStore,
    author_session_id: str = "god-session-architect",
    blueprint_set_id: str = "xmuse-self-evolution-v0",
    blueprint_ref: str = "blueprint.md",
    fallback_lane_id: str | None = None,
    fallback_prompt: str | None = None,
) -> EvolutionProposal:
    """Draft an evolution proposal for a target track without controller state."""
    target_tracks = [target_track] if target_track else ["graph_authority"]
    primary_track = target_tracks[0]
    candidate_lanes = decomposer.decompose(primary_track, evidence)
    if not candidate_lanes:
        candidate_lanes = [
            {
                "feature_id": fallback_lane_id or candidate_lane_id(evidence, target_tracks),
                "title": "Bootstrap the next xmuse self-evolution improvement",
                "prompt": fallback_prompt or candidate_prompt(evidence, target_tracks),
                "priority": 100,
                "capabilities": ["code", "test"],
                "depends_on": [],
                "task_type": "execute",
                "gate_profiles": ["xmuse-core"],
                "feature_group": primary_track,
            }
        ]
    candidate_lanes = _candidate_lanes_with_blueprint_refs(candidate_lanes, blueprint_ref)
    proposal = EvolutionProposal(
        proposal_id=_new_id("evprop"),
        source_run_id=evidence.source_run_id,
        blueprint_set_id=blueprint_set_id,
        target_track_ids=target_tracks,
        status=EvolutionProposalStatus.AWAITING_REVIEW,
        draft_version=1,
        author_session_id=author_session_id,
        scope_summary=_compose_scope_summary(target_tracks),
        why_now=evidence.summary,
        evidence_bundle_id=evidence.bundle_id,
        candidate_graph={
            "lanes": candidate_lanes,
            "self_evolution": {
                "source_run_id": evidence.source_run_id,
                "evidence_bundle_id": evidence.bundle_id,
                "blueprint_set_id": blueprint_set_id,
                "target_track_ids": target_tracks,
            },
        },
        review_status="awaiting_review",
        created_at=_utc_now(),
    )
    return store.save_proposal(proposal)


def blueprint_set_id(blueprint: str) -> str:
    return _extract_blueprint_field(blueprint, "blueprint_set_id") or (
        "xmuse-self-evolution-v0"
    )


def blueprint_ref(blueprint_path: Path, *, root: Path) -> str:
    try:
        return blueprint_path.relative_to(root).as_posix()
    except ValueError:
        try:
            return blueprint_path.relative_to(root.parent).as_posix()
        except ValueError:
            return blueprint_path.as_posix()


def candidate_lane_id(
    evidence: StructuredEvidenceBundle,
    target_tracks: list[str],
) -> str:
    raw = f"self-evolution-{target_tracks[0]}-{evidence.source_run_id}"
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-").lower()
    return slug[:120]


def candidate_prompt(
    evidence: StructuredEvidenceBundle,
    target_tracks: list[str],
) -> str:
    return (
        "Implement the next xmuse self-evolution improvement for tracks "
        f"{', '.join(target_tracks)}. Use evidence bundle {evidence.bundle_id}. "
        f"Focus first on evidence signals: {signal_summary(evidence.signal_refs)}. "
        "Preserve chat -> proposal -> approved resolution -> lane graph -> execution "
        "as the mainline, and add focused tests for the touched substrate."
    )


def select_target_track(
    evidence: StructuredEvidenceBundle,
    blueprint: str,
    *,
    store: SelfEvolutionStore,
) -> str:
    if evidence.run_terminal_status.value == "blocked_for_input":
        return "clarification_recovery"
    track_order = _blueprint_track_order(blueprint)
    if not track_order:
        return "graph_authority"
    landed_counts = _landed_track_counts(store)
    return min(
        track_order,
        key=lambda track: (landed_counts.get(track, 0), track_order.index(track)),
    )


def has_duplicate_evolution(
    proposal: EvolutionProposal,
    *,
    store: SelfEvolutionStore,
) -> bool:
    dedup_key = dedup_identity(proposal, store=store)[0]
    return _has_duplicate_evolution(proposal, dedup_key, store=store)


def _candidate_lanes_with_blueprint_refs(
    lanes: list[dict],
    blueprint_ref: str,
) -> list[dict]:
    stamped: list[dict] = []
    for lane in lanes:
        lane_payload = dict(lane)
        refs = lane_payload.get("blueprint_refs")
        if isinstance(refs, list):
            ref_values = [str(ref).strip() for ref in refs if str(ref).strip()]
        else:
            ref_values = []
        if blueprint_ref and blueprint_ref not in ref_values:
            ref_values.append(blueprint_ref)
        lane_payload["blueprint_refs"] = ref_values
        stamped.append(lane_payload)
    return stamped


def _compose_scope_summary(target_tracks: list[str]) -> str:
    if not target_tracks:
        return "Advance xmuse autonomous delivery through the next blueprint track."
    primary = target_tracks[0]
    return (
        f"Advance xmuse blueprint track '{primary}' for autonomous delivery: "
        f"address its next milestone with focused tests and lane evidence."
    )


def signal_summary(signal_refs: list[str]) -> str:
    if not signal_refs:
        return "none"
    return "; ".join(signal_refs[:4])


def _extract_blueprint_field(blueprint: str, field_name: str) -> str | None:
    match = re.search(rf"- `{re.escape(field_name)}`:\s*`([^`]+)`", blueprint)
    return match.group(1) if match else None


def _blueprint_track_order(blueprint: str) -> list[str]:
    priority_block = re.search(
        r"##\s*Priority\s*Policy.*?(?=\n##\s)",
        blueprint,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if priority_block:
        ordered = re.findall(r"\d+\.\s+`([a-z0-9_]+)`", priority_block.group(0))
        if ordered:
            return ordered
    track_block = re.search(
        r"##\s*Tracks(.*?)(?=\n##\s|\Z)",
        blueprint,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if track_block:
        return re.findall(r"###\s+([a-z0-9_]+)", track_block.group(1))
    return []


def _landed_track_counts(store: SelfEvolutionStore) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in store.list_lineage():
        for track in record.target_track_ids:
            counts[track] = counts.get(track, 0) + 1
    return counts
