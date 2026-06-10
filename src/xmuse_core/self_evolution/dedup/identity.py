"""Proposal deduplication extracted from SelfEvolutionController.

A proposal's dedup identity is a stable digest of its evidence signals and
source lineage. ``has_duplicate_evolution`` blocks re-landing an equivalent
proposal; ``record_dedup_continue`` persists the continuation record. The
store is passed explicitly so these functions stay free of controller state.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from xmuse_core.self_evolution.models import (
    EvolutionDedupRecord,
    EvolutionDedupStatus,
    EvolutionProposal,
    EvolutionProposalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dedup_signal_refs(signal_refs: list[str]) -> list[str]:
    """Strip volatile gate-report refs and normalize lane signals for hashing."""
    refs: list[str] = []
    for signal in signal_refs:
        if (
            signal.startswith("gate_report:")
            or signal.startswith("gate_report_resolution:")
            or signal.startswith("gate_report_diagnostic:")
            or signal.startswith("gate_report_result:")
        ):
            continue
        if signal.startswith("lane_signal:"):
            refs.append(_dedup_lane_signal_ref(signal))
        else:
            refs.append(signal)
    return refs


def _dedup_lane_signal_ref(signal: str) -> str:
    try:
        payload = json.loads(signal.removeprefix("lane_signal:"))
    except json.JSONDecodeError:
        return signal
    if not isinstance(payload, dict):
        return signal
    payload.pop("manual_recovery", None)
    payload.pop("review_fallback", None)
    payload.pop("review_fallback_reason", None)
    payload.pop("review_recovery_reason", None)
    payload.pop("review_risks", None)
    payload.pop("review_scope_refs", None)
    return f"lane_signal:{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"


def _maybe_get_evidence_bundle(
    bundle_id: str,
    *,
    store: SelfEvolutionStore,
) -> StructuredEvidenceBundle | None:
    for bundle in store.list_evidence_bundles():
        if bundle.bundle_id == bundle_id:
            return bundle
    return None


def dedup_identity(
    proposal: EvolutionProposal,
    *,
    store: SelfEvolutionStore,
) -> tuple[str, str, str]:
    """Return (dedup_key, signal_fingerprint, source_lineage_key) for a proposal."""
    evidence = _maybe_get_evidence_bundle(proposal.evidence_bundle_id, store=store)
    signal_payload = {
        "run_terminal_status": (
            evidence.run_terminal_status.value if evidence is not None else None
        ),
        "signal_refs": (
            sorted(dedup_signal_refs(evidence.signal_refs)) if evidence is not None else []
        ),
        "target_track_ids": sorted(proposal.target_track_ids),
    }
    lineage_payload = {
        "source_run_id": proposal.source_run_id,
        "source_resolution_id": evidence.source_resolution_id if evidence is not None else None,
        "verdict_refs": sorted(evidence.verdict_refs) if evidence is not None else [],
        "lineage_refs": sorted(evidence.lineage_refs) if evidence is not None else [],
        "target_track_ids": sorted(proposal.target_track_ids),
    }
    signal_fingerprint = _stable_digest(signal_payload)
    source_lineage_key = _stable_digest(lineage_payload)
    dedup_key = _stable_digest(
        {
            "signal_fingerprint": signal_fingerprint,
            "source_lineage_key": source_lineage_key,
        }
    )
    return dedup_key, signal_fingerprint, source_lineage_key


def has_duplicate_evolution(
    proposal: EvolutionProposal,
    dedup_key: str,
    *,
    store: SelfEvolutionStore,
) -> bool:
    """True if an equivalent proposal already continued or landed."""
    for record in store.list_dedup_records():
        if (
            record.dedup_key == dedup_key
            and record.last_proposal_id != proposal.proposal_id
            and record.status == EvolutionDedupStatus.CONTINUED
        ):
            return True
    for existing in store.list_proposals():
        if (
            existing.proposal_id != proposal.proposal_id
            and existing.status == EvolutionProposalStatus.LANDED
            and dedup_identity(existing, store=store)[0] == dedup_key
        ):
            return True
    return False


def record_dedup_continue(
    *,
    dedup_key: str,
    signal_fingerprint: str,
    source_lineage_key: str,
    proposal: EvolutionProposal,
    store: SelfEvolutionStore,
) -> None:
    """Persist (or refresh) the continuation dedup record for a proposal."""
    now = _utc_now()
    previous = next(
        (record for record in store.list_dedup_records() if record.dedup_key == dedup_key),
        None,
    )
    record = EvolutionDedupRecord(
        dedup_key=dedup_key,
        signal_fingerprint=signal_fingerprint,
        source_lineage_key=source_lineage_key,
        target_track_ids=list(proposal.target_track_ids),
        first_seen_at=previous.first_seen_at if previous is not None else now,
        last_seen_at=now,
        last_proposal_id=proposal.proposal_id,
        status=EvolutionDedupStatus.CONTINUED,
    )
    store.save_dedup_record(record)
