from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverFollowupReviewApplicationRecord,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureReviewVerdict,
    ReworkPacket,
)

SCHEMA_VERSION = "xmuse.feature_graph_artifacts.v1"
_ARTIFACT_COLLECTION_KEYS = {
    "evidence_bundles": "bundle_id",
    "review_verdicts": "verdict_id",
    "rework_packets": "rework_id",
    "patch_forward_plans": "plan_id",
    "patch_forward_gate_results": "result_id",
    "patch_forward_merge_guard_handoffs": "handoff_id",
    "patch_forward_merge_guard_decisions": "decision_id",
    "blocked_review_plans": "plan_id",
    "takeover_plans": "plan_id",
    "takeover_decisions": "decision_id",
    "takeover_handoffs": "handoff_id",
    "takeover_outcomes": "outcome_id",
    "takeover_review_handoffs": "review_handoff_id",
    "takeover_followup_review_applications": "application_id",
}


class FeatureGraphArtifactStore:
    """Durable store for feature-level worker/reviewer artifacts.

    Execution status stays in ``FeatureGraphStatusStore``. This store only
    persists artifacts that workers and reviewers return to the coordinator.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def save_evidence_bundle(
        self,
        bundle: FeatureEvidenceBundle,
    ) -> FeatureEvidenceBundle:
        validated = FeatureEvidenceBundle.model_validate(bundle.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("evidence_bundles", [])
            if not isinstance(rows, list):
                raise ValueError("evidence_bundles must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("evidence_bundles entries must be objects")
            for row in rows:
                if row.get("bundle_id") != validated.bundle_id:
                    continue
                existing = FeatureEvidenceBundle.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature evidence bundle replay conflict: {validated.bundle_id}"
                    )
                return existing
            payload["evidence_bundles"] = _upsert_by_key(
                rows,
                key="bundle_id",
                value=validated.bundle_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_evidence_bundle(self, bundle_id: str) -> FeatureEvidenceBundle:
        for row in self.list_evidence_bundles():
            if row.bundle_id == bundle_id:
                return row
        raise KeyError(f"feature evidence bundle not found: {bundle_id}")

    def list_evidence_bundles(self) -> list[FeatureEvidenceBundle]:
        with self._locked_file():
            rows = self._read_collection_unlocked("evidence_bundles")
        return [FeatureEvidenceBundle.model_validate(row) for row in rows]

    def list_evidence_bundles_for_feature_graph(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
    ) -> list[FeatureEvidenceBundle]:
        return [
            bundle
            for bundle in self.list_evidence_bundles()
            if bundle.graph_set_id == graph_set_id
            and bundle.feature_graph_id == feature_graph_id
        ]

    def save_review_verdict(
        self,
        verdict: FeatureReviewVerdict,
    ) -> FeatureReviewVerdict:
        validated = FeatureReviewVerdict.model_validate(verdict.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("review_verdicts", [])
            if not isinstance(rows, list):
                raise ValueError("review_verdicts must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("review_verdicts entries must be objects")
            for row in rows:
                if row.get("verdict_id") != validated.verdict_id:
                    continue
                existing = FeatureReviewVerdict.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature review verdict replay conflict: {validated.verdict_id}"
                    )
                return existing
            payload["review_verdicts"] = _upsert_by_key(
                rows,
                key="verdict_id",
                value=validated.verdict_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_review_verdict(self, verdict_id: str) -> FeatureReviewVerdict:
        for row in self.list_review_verdicts():
            if row.verdict_id == verdict_id:
                return row
        raise KeyError(f"feature review verdict not found: {verdict_id}")

    def list_review_verdicts(self) -> list[FeatureReviewVerdict]:
        with self._locked_file():
            rows = self._read_collection_unlocked("review_verdicts")
        return [FeatureReviewVerdict.model_validate(row) for row in rows]

    def list_review_verdicts_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[FeatureReviewVerdict]:
        return [
            verdict
            for verdict in self.list_review_verdicts()
            if verdict.evidence_bundle_id == evidence_bundle_id
        ]

    def save_rework_packet(self, packet: ReworkPacket) -> ReworkPacket:
        validated = ReworkPacket.model_validate(packet.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("rework_packets", [])
            if not isinstance(rows, list):
                raise ValueError("rework_packets must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("rework_packets entries must be objects")
            for row in rows:
                if row.get("rework_id") != validated.rework_id:
                    continue
                existing = ReworkPacket.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature rework packet replay conflict: {validated.rework_id}"
                    )
                return existing
            payload["rework_packets"] = _upsert_by_key(
                rows,
                key="rework_id",
                value=validated.rework_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_rework_packet(self, rework_id: str) -> ReworkPacket:
        for row in self.list_rework_packets():
            if row.rework_id == rework_id:
                return row
        raise KeyError(f"feature rework packet not found: {rework_id}")

    def list_rework_packets(self) -> list[ReworkPacket]:
        with self._locked_file():
            rows = self._read_collection_unlocked("rework_packets")
        return [ReworkPacket.model_validate(row) for row in rows]

    def list_rework_packets_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[ReworkPacket]:
        return [
            packet
            for packet in self.list_rework_packets()
            if packet.evidence_bundle_id == evidence_bundle_id
        ]

    def save_patch_forward_plan(
        self,
        plan: FeatureGraphPatchForwardPlan,
    ) -> FeatureGraphPatchForwardPlan:
        validated = FeatureGraphPatchForwardPlan.model_validate(plan.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("patch_forward_plans", [])
            if not isinstance(rows, list):
                raise ValueError("patch_forward_plans must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("patch_forward_plans entries must be objects")
            for row in rows:
                if row.get("plan_id") != validated.plan_id:
                    continue
                existing = FeatureGraphPatchForwardPlan.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature patch-forward plan replay conflict: {validated.plan_id}"
                    )
                return existing
            payload["patch_forward_plans"] = _upsert_by_key(
                rows,
                key="plan_id",
                value=validated.plan_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_patch_forward_plan(self, plan_id: str) -> FeatureGraphPatchForwardPlan:
        for row in self.list_patch_forward_plans():
            if row.plan_id == plan_id:
                return row
        raise KeyError(f"feature patch-forward plan not found: {plan_id}")

    def list_patch_forward_plans(self) -> list[FeatureGraphPatchForwardPlan]:
        with self._locked_file():
            rows = self._read_collection_unlocked("patch_forward_plans")
        return [FeatureGraphPatchForwardPlan.model_validate(row) for row in rows]

    def list_patch_forward_plans_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[FeatureGraphPatchForwardPlan]:
        return [
            plan
            for plan in self.list_patch_forward_plans()
            if plan.evidence_bundle_id == evidence_bundle_id
        ]

    def save_patch_forward_gate_result(
        self,
        result: FeatureGraphPatchForwardGateResult,
    ) -> FeatureGraphPatchForwardGateResult:
        validated = FeatureGraphPatchForwardGateResult.model_validate(
            result.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("patch_forward_gate_results", [])
            if not isinstance(rows, list):
                raise ValueError("patch_forward_gate_results must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("patch_forward_gate_results entries must be objects")
            for row in rows:
                if row.get("result_id") != validated.result_id:
                    continue
                existing = FeatureGraphPatchForwardGateResult.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        "feature patch-forward gate result replay conflict: "
                        f"{validated.result_id}"
                    )
                return existing
            payload["patch_forward_gate_results"] = _upsert_by_key(
                rows,
                key="result_id",
                value=validated.result_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_patch_forward_gate_result(
        self,
        result_id: str,
    ) -> FeatureGraphPatchForwardGateResult:
        for row in self.list_patch_forward_gate_results():
            if row.result_id == result_id:
                return row
        raise KeyError(f"feature patch-forward gate result not found: {result_id}")

    def list_patch_forward_gate_results(self) -> list[FeatureGraphPatchForwardGateResult]:
        with self._locked_file():
            rows = self._read_collection_unlocked("patch_forward_gate_results")
        return [FeatureGraphPatchForwardGateResult.model_validate(row) for row in rows]

    def list_patch_forward_gate_results_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[FeatureGraphPatchForwardGateResult]:
        return [
            result
            for result in self.list_patch_forward_gate_results()
            if result.evidence_bundle_id == evidence_bundle_id
        ]

    def list_patch_forward_gate_results_for_plan(
        self,
        plan_id: str,
    ) -> list[FeatureGraphPatchForwardGateResult]:
        return [
            result
            for result in self.list_patch_forward_gate_results()
            if result.plan_id == plan_id
        ]

    def save_patch_forward_merge_guard_handoff(
        self,
        handoff: FeatureGraphPatchForwardMergeGuardHandoff,
    ) -> FeatureGraphPatchForwardMergeGuardHandoff:
        validated = FeatureGraphPatchForwardMergeGuardHandoff.model_validate(
            handoff.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("patch_forward_merge_guard_handoffs", [])
            if not isinstance(rows, list):
                raise ValueError("patch_forward_merge_guard_handoffs must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError(
                    "patch_forward_merge_guard_handoffs entries must be objects"
                )
            for row in rows:
                if row.get("handoff_id") != validated.handoff_id:
                    continue
                existing = FeatureGraphPatchForwardMergeGuardHandoff.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        "feature patch-forward merge guard handoff replay conflict: "
                        f"{validated.handoff_id}"
                    )
                return existing
            payload["patch_forward_merge_guard_handoffs"] = _upsert_by_key(
                rows,
                key="handoff_id",
                value=validated.handoff_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_patch_forward_merge_guard_handoff(
        self,
        handoff_id: str,
    ) -> FeatureGraphPatchForwardMergeGuardHandoff:
        for row in self.list_patch_forward_merge_guard_handoffs():
            if row.handoff_id == handoff_id:
                return row
        raise KeyError(f"feature patch-forward merge guard handoff not found: {handoff_id}")

    def list_patch_forward_merge_guard_handoffs(
        self,
    ) -> list[FeatureGraphPatchForwardMergeGuardHandoff]:
        with self._locked_file():
            rows = self._read_collection_unlocked("patch_forward_merge_guard_handoffs")
        return [FeatureGraphPatchForwardMergeGuardHandoff.model_validate(row) for row in rows]

    def list_patch_forward_merge_guard_handoffs_for_gate_result(
        self,
        gate_result_id: str,
    ) -> list[FeatureGraphPatchForwardMergeGuardHandoff]:
        return [
            handoff
            for handoff in self.list_patch_forward_merge_guard_handoffs()
            if handoff.gate_result_id == gate_result_id
        ]

    def save_patch_forward_merge_guard_decision(
        self,
        decision: FeatureGraphPatchForwardMergeGuardDecision,
    ) -> FeatureGraphPatchForwardMergeGuardDecision:
        validated = FeatureGraphPatchForwardMergeGuardDecision.model_validate(
            decision.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("patch_forward_merge_guard_decisions", [])
            if not isinstance(rows, list):
                raise ValueError("patch_forward_merge_guard_decisions must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError(
                    "patch_forward_merge_guard_decisions entries must be objects"
                )
            for row in rows:
                if row.get("decision_id") != validated.decision_id:
                    continue
                existing = FeatureGraphPatchForwardMergeGuardDecision.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        "feature patch-forward merge guard decision replay conflict: "
                        f"{validated.decision_id}"
                    )
                return existing
            payload["patch_forward_merge_guard_decisions"] = _upsert_by_key(
                rows,
                key="decision_id",
                value=validated.decision_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_patch_forward_merge_guard_decision(
        self,
        decision_id: str,
    ) -> FeatureGraphPatchForwardMergeGuardDecision:
        for row in self.list_patch_forward_merge_guard_decisions():
            if row.decision_id == decision_id:
                return row
        raise KeyError(
            f"feature patch-forward merge guard decision not found: {decision_id}"
        )

    def list_patch_forward_merge_guard_decisions(
        self,
    ) -> list[FeatureGraphPatchForwardMergeGuardDecision]:
        with self._locked_file():
            rows = self._read_collection_unlocked("patch_forward_merge_guard_decisions")
        return [FeatureGraphPatchForwardMergeGuardDecision.model_validate(row) for row in rows]

    def list_patch_forward_merge_guard_decisions_for_handoff(
        self,
        handoff_id: str,
    ) -> list[FeatureGraphPatchForwardMergeGuardDecision]:
        return [
            decision
            for decision in self.list_patch_forward_merge_guard_decisions()
            if decision.handoff_id == handoff_id
        ]

    def save_blocked_review_plan(
        self,
        plan: FeatureGraphBlockedReviewPlan,
    ) -> FeatureGraphBlockedReviewPlan:
        validated = FeatureGraphBlockedReviewPlan.model_validate(plan.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("blocked_review_plans", [])
            if not isinstance(rows, list):
                raise ValueError("blocked_review_plans must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("blocked_review_plans entries must be objects")
            for row in rows:
                if row.get("plan_id") != validated.plan_id:
                    continue
                existing = FeatureGraphBlockedReviewPlan.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature blocked review plan replay conflict: {validated.plan_id}"
                    )
                return existing
            payload["blocked_review_plans"] = _upsert_by_key(
                rows,
                key="plan_id",
                value=validated.plan_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_blocked_review_plan(self, plan_id: str) -> FeatureGraphBlockedReviewPlan:
        for row in self.list_blocked_review_plans():
            if row.plan_id == plan_id:
                return row
        raise KeyError(f"feature blocked review plan not found: {plan_id}")

    def list_blocked_review_plans(self) -> list[FeatureGraphBlockedReviewPlan]:
        with self._locked_file():
            rows = self._read_collection_unlocked("blocked_review_plans")
        return [FeatureGraphBlockedReviewPlan.model_validate(row) for row in rows]

    def list_blocked_review_plans_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[FeatureGraphBlockedReviewPlan]:
        return [
            plan
            for plan in self.list_blocked_review_plans()
            if plan.evidence_bundle_id == evidence_bundle_id
        ]

    def save_takeover_plan(
        self,
        plan: FeatureGraphTakeoverPlan,
    ) -> FeatureGraphTakeoverPlan:
        validated = FeatureGraphTakeoverPlan.model_validate(plan.model_dump(mode="json"))
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("takeover_plans", [])
            if not isinstance(rows, list):
                raise ValueError("takeover_plans must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("takeover_plans entries must be objects")
            for row in rows:
                if row.get("plan_id") != validated.plan_id:
                    continue
                existing = FeatureGraphTakeoverPlan.model_validate(row)
                if existing != validated:
                    raise ValueError(
                        f"feature takeover plan replay conflict: {validated.plan_id}"
                    )
                return existing
            payload["takeover_plans"] = _upsert_by_key(
                rows,
                key="plan_id",
                value=validated.plan_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_takeover_plan(self, plan_id: str) -> FeatureGraphTakeoverPlan:
        for row in self.list_takeover_plans():
            if row.plan_id == plan_id:
                return row
        raise KeyError(f"feature takeover plan not found: {plan_id}")

    def list_takeover_plans(self) -> list[FeatureGraphTakeoverPlan]:
        with self._locked_file():
            rows = self._read_collection_unlocked("takeover_plans")
        return [FeatureGraphTakeoverPlan.model_validate(row) for row in rows]

    def list_takeover_plans_for_evidence_bundle(
        self,
        evidence_bundle_id: str,
    ) -> list[FeatureGraphTakeoverPlan]:
        return [
            plan
            for plan in self.list_takeover_plans()
            if plan.evidence_bundle_id == evidence_bundle_id
        ]

    def save_takeover_decision(
        self,
        decision: FeatureGraphTakeoverDecision,
    ) -> FeatureGraphTakeoverDecision:
        validated = FeatureGraphTakeoverDecision.model_validate(
            decision.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            return self._save_immutable_artifact_unlocked(
                payload,
                collection="takeover_decisions",
                key="decision_id",
                value=validated.decision_id,
                validated=validated,
                model_type=FeatureGraphTakeoverDecision,
                conflict_message=(
                    f"feature takeover decision replay conflict: {validated.decision_id}"
                ),
            )

    def get_takeover_decision(
        self,
        decision_id: str,
    ) -> FeatureGraphTakeoverDecision:
        for row in self.list_takeover_decisions():
            if row.decision_id == decision_id:
                return row
        raise KeyError(f"feature takeover decision not found: {decision_id}")

    def list_takeover_decisions(self) -> list[FeatureGraphTakeoverDecision]:
        with self._locked_file():
            rows = self._read_collection_unlocked("takeover_decisions")
        return [FeatureGraphTakeoverDecision.model_validate(row) for row in rows]

    def list_takeover_decisions_for_plan(
        self,
        plan_id: str,
    ) -> list[FeatureGraphTakeoverDecision]:
        return [
            decision
            for decision in self.list_takeover_decisions()
            if decision.plan_id == plan_id
        ]

    def save_takeover_handoff(
        self,
        handoff: FeatureGraphTakeoverHandoff,
    ) -> FeatureGraphTakeoverHandoff:
        validated = FeatureGraphTakeoverHandoff.model_validate(
            handoff.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            return self._save_immutable_artifact_unlocked(
                payload,
                collection="takeover_handoffs",
                key="handoff_id",
                value=validated.handoff_id,
                validated=validated,
                model_type=FeatureGraphTakeoverHandoff,
                conflict_message=(
                    f"feature takeover handoff replay conflict: {validated.handoff_id}"
                ),
            )

    def get_takeover_handoff(
        self,
        handoff_id: str,
    ) -> FeatureGraphTakeoverHandoff:
        for row in self.list_takeover_handoffs():
            if row.handoff_id == handoff_id:
                return row
        raise KeyError(f"feature takeover handoff not found: {handoff_id}")

    def list_takeover_handoffs(self) -> list[FeatureGraphTakeoverHandoff]:
        with self._locked_file():
            rows = self._read_collection_unlocked("takeover_handoffs")
        return [FeatureGraphTakeoverHandoff.model_validate(row) for row in rows]

    def list_takeover_handoffs_for_decision(
        self,
        decision_id: str,
    ) -> list[FeatureGraphTakeoverHandoff]:
        return [
            handoff
            for handoff in self.list_takeover_handoffs()
            if handoff.decision_id == decision_id
        ]

    def save_takeover_outcome(
        self,
        outcome: FeatureGraphTakeoverOutcome,
    ) -> FeatureGraphTakeoverOutcome:
        validated = FeatureGraphTakeoverOutcome.model_validate(
            outcome.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            return self._save_immutable_artifact_unlocked(
                payload,
                collection="takeover_outcomes",
                key="outcome_id",
                value=validated.outcome_id,
                validated=validated,
                model_type=FeatureGraphTakeoverOutcome,
                conflict_message=(
                    f"feature takeover outcome replay conflict: {validated.outcome_id}"
                ),
            )

    def get_takeover_outcome(
        self,
        outcome_id: str,
    ) -> FeatureGraphTakeoverOutcome:
        for row in self.list_takeover_outcomes():
            if row.outcome_id == outcome_id:
                return row
        raise KeyError(f"feature takeover outcome not found: {outcome_id}")

    def list_takeover_outcomes(self) -> list[FeatureGraphTakeoverOutcome]:
        with self._locked_file():
            rows = self._read_collection_unlocked("takeover_outcomes")
        return [FeatureGraphTakeoverOutcome.model_validate(row) for row in rows]

    def list_takeover_outcomes_for_handoff(
        self,
        handoff_id: str,
    ) -> list[FeatureGraphTakeoverOutcome]:
        return [
            outcome
            for outcome in self.list_takeover_outcomes()
            if outcome.handoff_id == handoff_id
        ]

    def save_takeover_review_handoff(
        self,
        handoff: FeatureGraphTakeoverReviewHandoff,
    ) -> FeatureGraphTakeoverReviewHandoff:
        validated = FeatureGraphTakeoverReviewHandoff.model_validate(
            handoff.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            return self._save_immutable_artifact_unlocked(
                payload,
                collection="takeover_review_handoffs",
                key="review_handoff_id",
                value=validated.review_handoff_id,
                validated=validated,
                model_type=FeatureGraphTakeoverReviewHandoff,
                conflict_message=(
                    "feature takeover review handoff replay conflict: "
                    f"{validated.review_handoff_id}"
                ),
            )

    def get_takeover_review_handoff(
        self,
        review_handoff_id: str,
    ) -> FeatureGraphTakeoverReviewHandoff:
        for row in self.list_takeover_review_handoffs():
            if row.review_handoff_id == review_handoff_id:
                return row
        raise KeyError(f"feature takeover review handoff not found: {review_handoff_id}")

    def list_takeover_review_handoffs(self) -> list[FeatureGraphTakeoverReviewHandoff]:
        with self._locked_file():
            rows = self._read_collection_unlocked("takeover_review_handoffs")
        return [FeatureGraphTakeoverReviewHandoff.model_validate(row) for row in rows]

    def list_takeover_review_handoffs_for_outcome(
        self,
        outcome_id: str,
    ) -> list[FeatureGraphTakeoverReviewHandoff]:
        return [
            handoff
            for handoff in self.list_takeover_review_handoffs()
            if handoff.outcome_id == outcome_id
        ]

    def save_takeover_followup_review_application(
        self,
        application: FeatureGraphTakeoverFollowupReviewApplicationRecord,
    ) -> FeatureGraphTakeoverFollowupReviewApplicationRecord:
        validated = FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
            application.model_dump(mode="json")
        )
        with self._locked_file():
            payload = self._read_payload_unlocked()
            rows = payload.get("takeover_followup_review_applications", [])
            if not isinstance(rows, list):
                raise ValueError("takeover_followup_review_applications must be a list")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("takeover_followup_review_applications entries must be objects")
            for row in rows:
                if row.get("application_id") != validated.application_id:
                    continue
                existing = FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
                    row
                )
                if existing != validated:
                    raise ValueError(
                        "takeover follow-up review application replay conflict: "
                        f"{validated.application_id}"
                    )
                return existing
            payload["takeover_followup_review_applications"] = _upsert_by_key(
                rows,
                key="application_id",
                value=validated.application_id,
                row=validated.model_dump(mode="json"),
            )
            self._write_payload_unlocked(payload)
        return validated

    def get_takeover_followup_review_application(
        self,
        application_id: str,
    ) -> FeatureGraphTakeoverFollowupReviewApplicationRecord:
        for row in self.list_takeover_followup_review_applications():
            if row.application_id == application_id:
                return row
        raise KeyError(
            f"feature takeover follow-up review application not found: {application_id}"
        )

    def list_takeover_followup_review_applications(
        self,
    ) -> list[FeatureGraphTakeoverFollowupReviewApplicationRecord]:
        with self._locked_file():
            rows = self._read_collection_unlocked(
                "takeover_followup_review_applications"
            )
        return [
            FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(row)
            for row in rows
        ]

    def list_takeover_followup_review_applications_for_handoff(
        self,
        review_handoff_id: str,
    ) -> list[FeatureGraphTakeoverFollowupReviewApplicationRecord]:
        return [
            application
            for application in self.list_takeover_followup_review_applications()
            if application.review_handoff_id == review_handoff_id
        ]

    def _read_payload_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _empty_payload()
        return {
            **_empty_payload(),
            **payload,
            "schema_version": SCHEMA_VERSION,
        }

    def _read_collection_unlocked(self, name: str) -> list[dict[str, Any]]:
        payload = self._read_payload_unlocked()
        rows = payload.get(name, [])
        if not isinstance(rows, list):
            raise ValueError(f"{name} must be a list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"{name} entries must be objects")
        _raise_if_artifact_collection_replay_conflicts(name, rows)
        return rows

    def _save_immutable_artifact_unlocked(
        self,
        payload: dict[str, Any],
        *,
        collection: str,
        key: str,
        value: str,
        validated: Any,
        model_type: Any,
        conflict_message: str,
    ) -> Any:
        rows = payload.get(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"{collection} entries must be objects")
        for row in rows:
            if row.get(key) != value:
                continue
            existing = model_type.model_validate(row)
            if existing != validated:
                raise ValueError(conflict_message)
            return existing
        payload[collection] = _upsert_by_key(
            rows,
            key=key,
            value=value,
            row=validated.model_dump(mode="json"),
        )
        self._write_payload_unlocked(payload)
        return validated

    def _write_payload_unlocked(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {
            "schema_version": SCHEMA_VERSION,
            "evidence_bundles": list(payload.get("evidence_bundles", [])),
            "review_verdicts": list(payload.get("review_verdicts", [])),
            "rework_packets": list(payload.get("rework_packets", [])),
            "patch_forward_plans": list(payload.get("patch_forward_plans", [])),
            "patch_forward_gate_results": list(
                payload.get("patch_forward_gate_results", [])
            ),
            "patch_forward_merge_guard_handoffs": list(
                payload.get("patch_forward_merge_guard_handoffs", [])
            ),
            "patch_forward_merge_guard_decisions": list(
                payload.get("patch_forward_merge_guard_decisions", [])
            ),
            "blocked_review_plans": list(payload.get("blocked_review_plans", [])),
            "takeover_plans": list(payload.get("takeover_plans", [])),
            "takeover_decisions": list(payload.get("takeover_decisions", [])),
            "takeover_handoffs": list(payload.get("takeover_handoffs", [])),
            "takeover_outcomes": list(payload.get("takeover_outcomes", [])),
            "takeover_review_handoffs": list(
                payload.get("takeover_review_handoffs", [])
            ),
            "takeover_followup_review_applications": list(
                payload.get("takeover_followup_review_applications", [])
            ),
        }
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    @contextmanager
    def _locked_file(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _empty_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_bundles": [],
        "review_verdicts": [],
        "rework_packets": [],
        "patch_forward_plans": [],
        "patch_forward_gate_results": [],
        "patch_forward_merge_guard_handoffs": [],
        "patch_forward_merge_guard_decisions": [],
        "blocked_review_plans": [],
        "takeover_plans": [],
        "takeover_decisions": [],
        "takeover_handoffs": [],
        "takeover_outcomes": [],
        "takeover_review_handoffs": [],
        "takeover_followup_review_applications": [],
    }


def _upsert_by_key(
    rows: Any,
    *,
    key: str,
    value: str,
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    existing = rows if isinstance(rows, list) else []
    updated = [
        existing_row
        for existing_row in existing
        if isinstance(existing_row, dict) and existing_row.get(key) != value
    ]
    updated.append(row)
    return updated


def _raise_if_artifact_collection_replay_conflicts(
    collection: str,
    rows: list[dict[str, Any]],
) -> None:
    key = _ARTIFACT_COLLECTION_KEYS.get(collection)
    if key is None:
        return
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str):
            continue
        existing = seen.get(value)
        if existing is None:
            seen[value] = row
            continue
        if existing == row:
            raise ValueError(
                "duplicate feature graph artifact identity: "
                f"{collection}:{key}:{value}"
            )
        raise ValueError(
            "feature graph artifact replay conflict: "
            f"{collection}:{key}:{value}"
        )
