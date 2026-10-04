"""Host-verified completion for board owners.

An owner reports ``chat_room_board_report_progress(status="done")``; that claim
is only a record until this worker verifies it with evidence: the owner's
committed branch is exported, checked against the charter paths, and run
through the server-owned execution gates.  Failures wake the owner in the same
session with evidence; passes are reported to the charter's ``report_to``.

The worker never executes the charter's ``acceptance`` strings: they stay
descriptive text for the agent.  Only the fixed server-owned gate entrypoints
run, exactly as exact-patch runs do.  Gate output is digest-only inside the
sandbox (see ``room_execution_sandbox.run_gate``): a verification records
``gate_id``/``exit_code``/``reason_code`` per gate because output tails are
not retrievable without changing the sandbox boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_board import (
    MAX_VERIFICATION_ATTEMPTS,
    VERIFICATION_LEASE_TTL_S,
    RoomBoardStore,
    charter_outside_paths,
)
from xmuse_core.chat.room_execution_controller import (
    ExactPatchCandidate,
    RoomExecutionControllerError,
    stage_exact_patch,
    verify_stage_unchanged,
)
from xmuse_core.chat.room_execution_profiles import (
    RoomExecutionProfileError,
    build_execution_gate_plan,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_execution_sandbox import (
    RoomExecutionSandboxError,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    discover_sandbox_layout,
    run_gate,
)
from xmuse_core.chat.room_owner_clones import OwnerCloneError, OwnerCloneManager
from xmuse_core.chat.room_owner_ids import owner_id_for_participant

BOARD_VERIFICATION_RISK_POLICY = "room_board_verification/v1"
BOARD_VERIFICATION_WORKER_ID = "board-verification"
BOARD_VERIFICATION_GATE_FAILED = "board_verification_gate_failed"
BOARD_VERIFICATION_OUTSIDE_CHARTER = "board_verification_outside_charter"

# Staging failures that describe transient host-side state (a contended repo
# lock) rather than the owner's patch.  The job is released back to pending so a
# later pass retries it.
_TRANSIENT_STAGE_CODES = frozenset({"execution_repo_busy"})
# Clone/export failures that describe transient host git trouble rather than
# the patch content.  Deterministic content codes (empty, binary, too large,
# reserved path) fail the verification instead.
_TRANSIENT_CLONE_CODES = frozenset(
    {
        "owner_git_timeout",
        "owner_git_failed",
        "owner_patch_fetch_failed",
        "owner_clone_missing",
        "owner_clone_metadata_invalid",
    }
)


class BoardVerificationTransientError(RuntimeError):
    """A host-side hiccup: release the job for a later pass."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BoardVerificationOutcome:
    status: str
    reason_code: str | None
    head_commit: str | None
    patch_digest: str | None
    changed_paths: tuple[str, ...]
    gates: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]


def _failed(
    reason_code: str,
    *,
    head_commit: str | None = None,
    patch_digest: str | None = None,
    changed_paths: tuple[str, ...] = (),
    gates: tuple[dict[str, Any], ...] = (),
    evidence: dict[str, Any] | None = None,
) -> BoardVerificationOutcome:
    return BoardVerificationOutcome(
        status="failed",
        reason_code=reason_code,
        head_commit=head_commit,
        patch_digest=patch_digest,
        changed_paths=changed_paths,
        gates=gates,
        evidence=dict(evidence) if evidence is not None else {},
    )


class RoomBoardVerificationWorker:
    """Claim pending board verifications and verify them one job at a time.

    All blocking work (git, gates) runs in the caller's thread: the Chat API
    invokes :meth:`reconcile_once` via ``asyncio.to_thread``, never on the
    event loop.
    """

    def __init__(
        self,
        *,
        db_path: Path | str,
        clones_root: Path | str,
        xmuse_root: Path | str,
        execution_root: Path | str,
        execution_profile_id: str = "xmuse-monorepo/v2",
        worker_id: str = BOARD_VERIFICATION_WORKER_ID,
        lease_ttl_s: int = VERIFICATION_LEASE_TTL_S,
        max_attempts: int = MAX_VERIFICATION_ATTEMPTS,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("room_board_worker_id_required")
        self._db_path = Path(db_path)
        self._clones = OwnerCloneManager(Path(clones_root))
        self._xmuse_root = Path(xmuse_root)
        self._execution_root = Path(execution_root)
        # Fail fast on an unknown profile; the plan is rebuilt per job.
        self._profile = get_execution_gate_profile(execution_profile_id)
        self._worker_id = worker_id
        self._lease_ttl_s = lease_ttl_s
        self._max_attempts = max_attempts

    def reconcile_once(self, *, now: datetime | None = None) -> dict[str, int]:
        """Claim and verify a single pending job; individual failures stay durable."""

        store = RoomBoardStore(self._db_path)
        claimed = store.claim_next_board_verification(
            worker_id=self._worker_id,
            lease_ttl_s=self._lease_ttl_s,
            max_attempts=self._max_attempts,
            now=now,
        )
        if claimed is None:
            return {
                "board_verifications_claimed": 0,
                "board_verifications_passed": 0,
                "board_verifications_failed": 0,
                "board_verifications_dropped": 0,
                "board_verifications_abandoned": 0,
            }
        verification_id = str(claimed["verification_id"])
        lease_token = str(claimed["lease_token"])
        try:
            outcome = self._verify_claim(claimed)
        except BoardVerificationTransientError as exc:
            store.abandon_board_verification(
                verification_id=verification_id,
                lease_token=lease_token,
                reason_code=exc.code,
                now=now,
            )
            return {
                "board_verifications_claimed": 1,
                "board_verifications_passed": 0,
                "board_verifications_failed": 0,
                "board_verifications_dropped": 0,
                "board_verifications_abandoned": 1,
            }
        result = store.complete_board_verification(
            verification_id=verification_id,
            lease_token=lease_token,
            status=outcome.status,
            reason_code=outcome.reason_code,
            head_commit=outcome.head_commit,
            patch_digest=outcome.patch_digest,
            changed_paths=list(outcome.changed_paths),
            gates=[dict(item) for item in outcome.gates],
            evidence=dict(outcome.evidence),
            now=now,
        )
        terminal = str(result["status"])
        return {
            "board_verifications_claimed": 1,
            "board_verifications_passed": 1 if terminal == "passed" else 0,
            "board_verifications_failed": 1 if terminal == "failed" else 0,
            "board_verifications_dropped": 1 if terminal == "dropped" else 0,
            "board_verifications_abandoned": 0,
        }

    def _verify_claim(self, claimed: Mapping[str, Any]) -> BoardVerificationOutcome:
        conversation_id = str(claimed["conversation_id"])
        module_id = str(claimed["module_id"])
        participant_id = str(claimed["participant_id"])
        verification_id = str(claimed["verification_id"])
        store = RoomBoardStore(self._db_path)
        charter = store.get_module_charter(conversation_id, module_id)
        if (
            charter is None
            or charter["status"] != "active"
            or charter["owner_participant_id"] != participant_id
        ):
            return _failed("board_verification_charter_unknown")
        raw_charter = charter["charter"]
        patterns = raw_charter.get("paths", []) if isinstance(raw_charter, dict) else []
        patterns = [item for item in patterns if isinstance(item, str)]
        owner_id = owner_id_for_participant(conversation_id, participant_id)
        try:
            base_commit = self._clones.read_base_commit(owner_id)
        except OwnerCloneError as exc:
            if exc.code in _TRANSIENT_CLONE_CODES:
                raise BoardVerificationTransientError(exc.code) from exc
            return _failed(exc.code)
        try:
            patch = self._clones.export_patch(owner_id, base_commit=base_commit)
        except OwnerCloneError as exc:
            if exc.code in _TRANSIENT_CLONE_CODES:
                raise BoardVerificationTransientError(exc.code) from exc
            return _failed(exc.code)
        changed = tuple(sorted(set(patch.changed_paths)))
        patch_digest = f"sha256:{sha256(patch.unified_diff.encode('utf-8')).hexdigest()}"
        outside = charter_outside_paths(changed, patterns)
        if outside:
            return _failed(
                BOARD_VERIFICATION_OUTSIDE_CHARTER,
                head_commit=patch.head_commit,
                patch_digest=patch_digest,
                changed_paths=changed,
                evidence={"offending_paths": sorted(outside)},
            )
        try:
            repository_manifest_digest = build_repository_manifest_digest(
                self._execution_root, self._profile
            )
            toolchain_capability_digest = build_toolchain_capability_digest(
                self._execution_root, self._profile, gate_ids=self._profile.gate_ids
            )
        except (OSError, RoomExecutionSandboxError, RoomExecutionProfileError) as exc:
            raise BoardVerificationTransientError(
                getattr(exc, "code", "board_verification_evidence_unavailable")
                if isinstance(exc, (RoomExecutionSandboxError, RoomExecutionProfileError))
                else "board_verification_evidence_unavailable"
            ) from exc
        try:
            plan = build_execution_gate_plan(
                profile_id=self._profile.profile_id,
                changed_paths=changed,
                repository_manifest_digest=repository_manifest_digest,
                toolchain_capability_digest=toolchain_capability_digest,
            )
        except RoomExecutionProfileError as exc:
            return _failed(
                exc.code,
                head_commit=patch.head_commit,
                patch_digest=patch_digest,
                changed_paths=changed,
            )
        candidate = ExactPatchCandidate(
            candidate_id=verification_id,
            patch_text=patch.unified_diff,
            patch_sha256=patch_digest,
            candidate_digest=patch_digest,
            base_head=patch.base_commit,
            allowed_files=changed,
            policy_revision=1,
            risk_policy_revision=BOARD_VERIFICATION_RISK_POLICY,
        )
        try:
            with stage_exact_patch(
                xmuse_root=self._xmuse_root,
                execution_root=self._execution_root,
                run_id=verification_id,
                candidate=candidate,
                # Verification never promotes: the Human's checkout may have moved on
                # or be dirty; the stage only needs the owner's base commit.
                require_target_at_base=False,
            ) as staged:
                layout = discover_sandbox_layout(
                    stage=staged.stage,
                    execution_root=self._execution_root,
                    gate_ids=plan.gate_ids,
                    profile=self._profile,
                    expected_toolchain_capability_digest=toolchain_capability_digest,
                )
                try:
                    results = [run_gate(layout, gate_id) for gate_id in plan.gate_ids]
                finally:
                    layout.close()
                verify_stage_unchanged(staged)
        except RoomExecutionControllerError as exc:
            if exc.code in _TRANSIENT_STAGE_CODES:
                raise BoardVerificationTransientError(exc.code) from exc
            return _failed(
                exc.code,
                head_commit=patch.head_commit,
                patch_digest=patch_digest,
                changed_paths=changed,
            )
        except RoomExecutionSandboxError as exc:
            raise BoardVerificationTransientError(exc.code) from exc
        gates = tuple(
            {
                "gate_id": item.gate_id,
                "status": item.status,
                "exit_code": item.exit_code,
                "reason_code": item.reason_code,
            }
            for item in results
        )
        failed_gates = [item["gate_id"] for item in gates if item["status"] != "passed"]
        if failed_gates:
            return _failed(
                BOARD_VERIFICATION_GATE_FAILED,
                head_commit=patch.head_commit,
                patch_digest=patch_digest,
                changed_paths=changed,
                gates=gates,
                evidence={
                    "failed_gates": failed_gates,
                    "note": (
                        "Gate output is digest-only inside the execution sandbox: "
                        "only gate_id/exit_code/reason_code are recorded."
                    ),
                },
            )
        return BoardVerificationOutcome(
            status="passed",
            reason_code=None,
            head_commit=patch.head_commit,
            patch_digest=patch_digest,
            changed_paths=changed,
            gates=gates,
            evidence={},
        )


__all__ = [
    "BOARD_VERIFICATION_GATE_FAILED",
    "BOARD_VERIFICATION_OUTSIDE_CHARTER",
    "BOARD_VERIFICATION_RISK_POLICY",
    "BOARD_VERIFICATION_WORKER_ID",
    "BoardVerificationOutcome",
    "BoardVerificationTransientError",
    "RoomBoardVerificationWorker",
]
