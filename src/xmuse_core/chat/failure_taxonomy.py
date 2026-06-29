from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FAILURE_TAXONOMY_VERSION = "natural_groupchat_durable_failure_taxonomy/v1"


@dataclass(frozen=True, slots=True)
class DurableFailureClass:
    class_id: str
    label: str
    producer: str
    consumer: str
    condition: str
    proof_level: str
    failure_boundary: str
    next_recovery_action: str

    def to_projection(self) -> dict[str, str]:
        return {
            "taxonomy": FAILURE_TAXONOMY_VERSION,
            "class_id": self.class_id,
            "label": self.label,
            "producer": self.producer,
            "consumer": self.consumer,
            "condition": self.condition,
            "proof_level": self.proof_level,
            "failure_boundary": self.failure_boundary,
            "next_recovery_action": self.next_recovery_action,
        }


FAILURE_CLASSES: tuple[DurableFailureClass, ...] = (
    DurableFailureClass(
        class_id="provider_turn_no_writeback_or_timeout",
        label="provider turn no-writeback or timeout",
        producer="provider adapter / chat dispatch bridge",
        consumer="chat.db writeback reconciliation",
        condition="provider turn failed to produce durable message, callback, or timeout result",
        proof_level="durable xmuse authority gap",
        failure_boundary="provider_writeback_boundary",
        next_recovery_action=(
            "inspect provider run, reconcile writeback, or retry the turn with durable "
            "timeout evidence"
        ),
    ),
    DurableFailureClass(
        class_id="collaboration_callback_or_proposal_failure",
        label="collaboration callback/proposal failure",
        producer="chat collaboration store / proposal writer",
        consumer="proposal review and dispatch gate",
        condition="collaboration callback or proposal artifact is missing, failed, or unresolved",
        proof_level="chat.db collaboration/proposal authority",
        failure_boundary="collaboration_proposal_boundary",
        next_recovery_action=(
            "replay callback normalization or recreate/relink the durable proposal"
        ),
    ),
    DurableFailureClass(
        class_id="review_trigger_timeout_or_rejected_verdict",
        label="review-trigger timeout or rejected verdict",
        producer="review trigger / review_plane.json",
        consumer="proposal approval and dispatch gate",
        condition="review trigger timed out, verdict is missing, or verdict rejects the proposal",
        proof_level="durable review verdict authority",
        failure_boundary="review_trigger_verdict_boundary",
        next_recovery_action=(
            "rerun review trigger or route rejected verdict back to proposal repair"
        ),
    ),
    DurableFailureClass(
        class_id="lane_execution_failure",
        label="lane execution failure",
        producer="dispatch bridge / lane executor",
        consumer="acceptance spine execution evidence",
        condition="lane worker failed to produce durable execution evidence",
        proof_level="durable dispatch or execution evidence gap",
        failure_boundary="lane_execution_boundary",
        next_recovery_action=(
            "inspect dispatch failure, worker blocker, and lane execution evidence"
        ),
    ),
    DurableFailureClass(
        class_id="docs_or_code_gate_failure",
        label="docs/code gate failure",
        producer="gate runner",
        consumer="review verdict producer",
        condition="docs or code gate report is failed, missing, or underscoped",
        proof_level="durable gate report",
        failure_boundary="gate_report_boundary",
        next_recovery_action="repair scoped docs/code changes and rerun the selected gate profile",
    ),
    DurableFailureClass(
        class_id="branch_behind_or_stale_base_pr_creation",
        label="branch-behind or stale-base PR creation",
        producer="final-action PR producer",
        consumer="GitHub PR server facts",
        condition="PR creation or update observed branch-behind or stale-base facts",
        proof_level="GitHub server fact / durable final-action gap",
        failure_boundary="pr_creation_stale_base_boundary",
        next_recovery_action=(
            "refresh base, rebase or recreate PR branch, then recapture server facts"
        ),
    ),
    DurableFailureClass(
        class_id="exact_head_ci_failure",
        label="exact-head CI failure",
        producer="GitHub checks API",
        consumer="guarded merge gate",
        condition="required CI is missing, failed, or not for the exact PR head SHA",
        proof_level="GitHub server check-run truth",
        failure_boundary="exact_head_ci_boundary",
        next_recovery_action=(
            "capture exact-head check runs after fixing or rerunning required checks"
        ),
    ),
    DurableFailureClass(
        class_id="guarded_merge_rejection",
        label="guarded merge rejection",
        producer="GitHub merge API / final-action gate",
        consumer="main CI observer",
        condition=(
            "guarded merge is rejected by match-head, protection, review, or "
            "mergeability rules"
        ),
        proof_level="GitHub server merge truth",
        failure_boundary="guarded_merge_boundary",
        next_recovery_action="resolve merge gate reason and retry with current head/server facts",
    ),
    DurableFailureClass(
        class_id="main_ci_failure",
        label="main CI failure",
        producer="GitHub Actions main workflow",
        consumer="post-merge closure observer",
        condition="post-merge main CI is missing, failed, or does not match merge commit head",
        proof_level="GitHub server main-CI truth",
        failure_boundary="main_ci_boundary",
        next_recovery_action=(
            "inspect main CI run, repair regression, and recapture post-merge evidence"
        ),
    ),
    DurableFailureClass(
        class_id="memoryos_unavailable_or_ingest_failure",
        label="MemoryOS unavailable or ingest failure",
        producer="MemoryOS sidecar",
        consumer="supporting context projection",
        condition="optional MemoryOS recall or ingest is unavailable, degraded, or failed",
        proof_level="sidecar continuity attempt evidence",
        failure_boundary="memoryos_sidecar_boundary",
        next_recovery_action="inspect sidecar configuration/endpoint and retry recall or ingest",
    ),
    DurableFailureClass(
        class_id="frontend_projection_gap",
        label="frontend projection gap",
        producer="frontend peer-chat UX projection",
        consumer="operator",
        condition="read-only projection cannot resolve an existing durable authority ref",
        proof_level="read-only projection gap",
        failure_boundary="frontend_projection_boundary",
        next_recovery_action="repair projection reader or relink the missing authority source ref",
    ),
)


def catalog_by_class_id() -> dict[str, DurableFailureClass]:
    return {failure_class.class_id: failure_class for failure_class in FAILURE_CLASSES}


def classify_failure_boundary(boundary: dict[str, Any]) -> dict[str, str]:
    catalog = catalog_by_class_id()
    class_id = _class_id_for_boundary(boundary)
    return catalog[class_id].to_projection()


def _class_id_for_boundary(boundary: dict[str, Any]) -> str:
    text = _boundary_text(boundary)
    proof_boundary = str(boundary.get("proof_boundary") or "").lower()
    kind = str(boundary.get("kind") or "").lower()

    if "memoryos" in text or "sidecar" in text:
        return "memoryos_unavailable_or_ingest_failure"
    if "main_ci" in text or "main ci" in text:
        return "main_ci_failure"
    if "branch_behind" in text or "branch-behind" in text or "stale" in text:
        return "branch_behind_or_stale_base_pr_creation"
    if "guarded" in text or "merge_reject" in text or "match-head" in text:
        return "guarded_merge_rejection"
    if "exact_head" in text or "exact-head" in text or "check_run" in text:
        return "exact_head_ci_failure"
    if "github_gate" in proof_boundary or "github_gate" in kind:
        return "exact_head_ci_failure"
    if "review" in text and ("timeout" in text or "reject" in text or "verdict" in text):
        return "review_trigger_timeout_or_rejected_verdict"
    if "proposal" in text or "collaboration" in text or "callback" in text:
        return "collaboration_callback_or_proposal_failure"
    if "provider" in text or "writeback" in text or "no-writeback" in text:
        return "provider_turn_no_writeback_or_timeout"
    if "gate_failed" in text or "gate failure" in text:
        return "docs_or_code_gate_failure"
    if "gate" in text and ("docs" in text or "code" in text or "report" in text):
        return "docs_or_code_gate_failure"
    if "lane" in text or "execution" in text or "dispatch" in text or "worker" in text:
        return "lane_execution_failure"
    return "frontend_projection_gap"


def _boundary_text(boundary: dict[str, Any]) -> str:
    fields = (
        "kind",
        "status",
        "producer",
        "consumer",
        "condition",
        "proof_boundary",
        "next_recovery_action",
        "ref",
    )
    return " ".join(str(boundary.get(field) or "") for field in fields).lower()
