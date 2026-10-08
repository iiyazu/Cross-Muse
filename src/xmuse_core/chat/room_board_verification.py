"""Host-verified completion for board owners.

An owner reports ``chat_room_board_report_progress(status="done")``; that claim
is only a record until this worker verifies it with evidence: the owner's
committed branch is exported, checked against the charter paths, and run
through the server-owned execution gates.  Failures wake the owner in the same
session with evidence; passes are reported to the charter's ``report_to``.

The worker never executes the charter's ``acceptance`` strings: they stay
descriptive text for the agent.  Only the fixed server-owned gate entrypoints
run, exactly as exact-patch runs do.  A failed gate's evidence carries a
sanitized, bounded tail of its output (``run_gate(output_tail_bytes=...)``) so
the owner can see what failed; digests are computed exactly as before.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_board import (
    BOARD_VERIFICATION_BASE_MISMATCH,
    BOARD_VERIFICATION_DEPENDENCY_OVERLAP,
    BOARD_VERIFICATION_WAITING_FOR_PROVIDER,
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
    affected_packages,
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

logger = logging.getLogger(__name__)

BOARD_VERIFICATION_RISK_POLICY = "room_board_verification/v1"
BOARD_VERIFICATION_WORKER_ID = "board-verification"
BOARD_VERIFICATION_GATE_FAILED = "board_verification_gate_failed"
BOARD_VERIFICATION_OUTSIDE_CHARTER = "board_verification_outside_charter"
# Display-only evidence for the owner: at most this many failing gates, each
# with at most this many bytes of sanitized output tail.
GATE_OUTPUT_TAIL_BYTES = 2048
MAX_EVIDENCE_TAIL_GATES = 3

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


class BoardVerificationDeferred(RuntimeError):
    """A provider module is not ready: defer the job without an attempt."""

    def __init__(self, providers: list[str]) -> None:
        self.providers = sorted({str(item) for item in providers if item})
        super().__init__(BOARD_VERIFICATION_WAITING_FOR_PROVIDER)


@dataclass(frozen=True)
class BoardVerificationOutcome:
    status: str
    reason_code: str | None
    head_commit: str | None
    patch_digest: str | None
    changed_paths: tuple[str, ...]
    gates: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    stacked: tuple[dict[str, Any], ...] = ()
    patch_text: str | None = None
    base_commit: str | None = None


def _failed(
    reason_code: str,
    *,
    head_commit: str | None = None,
    patch_digest: str | None = None,
    changed_paths: tuple[str, ...] = (),
    gates: tuple[dict[str, Any], ...] = (),
    evidence: dict[str, Any] | None = None,
    stacked: tuple[dict[str, Any], ...] = (),
    patch_text: str | None = None,
    base_commit: str | None = None,
) -> BoardVerificationOutcome:
    return BoardVerificationOutcome(
        status="failed",
        reason_code=reason_code,
        head_commit=head_commit,
        patch_digest=patch_digest,
        changed_paths=changed_paths,
        gates=gates,
        evidence=dict(evidence) if evidence is not None else {},
        stacked=stacked,
        patch_text=patch_text,
        base_commit=base_commit,
    )


def combine_verification_patches(patches: list[str]) -> str:
    """Combine provider patches and the dependent patch into one diff."""

    parts: list[str] = []
    for patch in patches:
        if not patch:
            continue
        text = patch if patch.endswith("\n") else patch + "\n"
        parts.append(text)
    return "".join(parts)


def patch_text_paths(patch_text: str) -> list[str]:
    """Return the sorted paths named by ``diff --git`` headers of one patch."""

    paths: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        old, separator, new = line[len("diff --git a/") :].partition(" b/")
        if separator:
            paths.update(item for item in (old, new) if item)
    return sorted(paths)


def upstream_modules(store: RoomBoardStore, conversation_id: str, module_id: str) -> list[str]:
    """Return every module ``module_id`` transitively depends on, sorted."""

    seen: set[str] = set()
    frontier = [module_id]
    while frontier:
        current = frontier.pop()
        for provider in store.provider_modules_for_module(conversation_id, current):
            if provider != module_id and provider not in seen:
                seen.add(provider)
                frontier.append(provider)
    return sorted(seen)


def find_overlapping_paths(path_groups: list[list[str]]) -> list[str]:
    """Return sorted paths touched by more than one stacked patch."""

    counts: dict[str, int] = {}
    for group in path_groups:
        for path in sorted(set(group)):
            counts[path] = counts.get(path, 0) + 1
    return sorted(path for path, total in counts.items() if total > 1)


def _board_review_response_seconds() -> int:
    raw = os.environ.get("XMUSE_BOARD_REVIEW_RESPONSE_SECONDS")
    if raw is not None:
        try:
            val = int(raw.strip())
            if val > 0:
                return val
        except ValueError:
            pass
    return 3600


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
        current_now = now or datetime.now(UTC)
        try:
            store.escalate_stale_reviews(
                now=current_now,
                response_seconds=_board_review_response_seconds(),
            )
        except Exception:
            logger.exception("board review escalation failed")
        claimed = store.claim_next_board_verification(
            worker_id=self._worker_id,
            lease_ttl_s=self._lease_ttl_s,
            max_attempts=self._max_attempts,
            now=current_now,
        )
        if claimed is None:
            return {
                "board_verifications_claimed": 0,
                "board_verifications_passed": 0,
                "board_verifications_failed": 0,
                "board_verifications_dropped": 0,
                "board_verifications_abandoned": 0,
                "board_verifications_deferred": 0,
            }
        verification_id = str(claimed["verification_id"])
        lease_token = str(claimed["lease_token"])
        try:
            outcome = self._verify_claim(claimed)
        except BoardVerificationDeferred as exc:
            store.defer_board_verification(
                verification_id=verification_id,
                lease_token=lease_token,
                providers=list(exc.providers),
                now=now,
            )
            return {
                "board_verifications_claimed": 1,
                "board_verifications_passed": 0,
                "board_verifications_failed": 0,
                "board_verifications_dropped": 0,
                "board_verifications_abandoned": 0,
                "board_verifications_deferred": 1,
            }
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
                "board_verifications_deferred": 0,
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
            patch_text=outcome.patch_text,
            stacked=[dict(item) for item in outcome.stacked],
            base_commit=outcome.base_commit,
        )
        terminal = str(result["status"])
        return {
            "board_verifications_claimed": 1,
            "board_verifications_passed": 1 if terminal == "passed" else 0,
            "board_verifications_failed": 1 if terminal == "failed" else 0,
            "board_verifications_dropped": 1 if terminal == "dropped" else 0,
            "board_verifications_abandoned": 0,
            "board_verifications_deferred": 0,
        }

    def _module_predecessors(
        self,
        store: RoomBoardStore,
        conversation_id: str,
        participant_id: str,
        module_id: str,
        head_commit: str,
    ) -> list[dict[str, Any]]:
        """This owner's earlier modules whose verified head the current head builds on.

        Oldest first; the last one is the module start. Only verified work that
        is an ancestor of the latest such head counts, so a module whose head
        later moved away (a rework the owner did not build on) is left out.
        """

        earlier = [
            item
            for item in store.owner_passed_board_verifications(
                conversation_id, participant_id, exclude_module_id=module_id
            )
            if isinstance(item.get("head_commit"), str)
            and item["head_commit"]
            and self._clones.is_ancestor(str(item["head_commit"]), head_commit)
        ]
        if not earlier:
            return []
        start = str(earlier[-1]["head_commit"])
        return [
            item for item in earlier if self._clones.is_ancestor(str(item["head_commit"]), start)
        ]

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
            # The owner's whole tree against the room base: what the stage runs.
            full_patch = self._clones.export_patch(owner_id, base_commit=base_commit)
            patch = full_patch
            predecessors = self._module_predecessors(
                store, conversation_id, participant_id, module_id, full_patch.head_commit
            )
            if predecessors:
                # Module start: one clone serves every module of this owner, so a
                # later module's own patch (the bytes reviewed and integrated) is
                # what was committed after the work its earlier modules were
                # verified with. The stage still runs the owner's whole tree.
                patch = self._clones.export_patch(
                    owner_id, base_commit=str(predecessors[-1]["head_commit"])
                )
        except OwnerCloneError as exc:
            if exc.code in _TRANSIENT_CLONE_CODES:
                raise BoardVerificationTransientError(exc.code) from exc
            return _failed(exc.code)
        own_changed = tuple(sorted(set(patch.changed_paths)))
        own_digest = f"sha256:{sha256(patch.unified_diff.encode('utf-8')).hexdigest()}"
        outside = charter_outside_paths(own_changed, patterns)
        if outside:
            return _failed(
                BOARD_VERIFICATION_OUTSIDE_CHARTER,
                head_commit=patch.head_commit,
                patch_digest=own_digest,
                changed_paths=own_changed,
                evidence={"offending_paths": sorted(outside)},
                base_commit=base_commit,
            )
        # Every upstream module, not only direct providers: a provider's code may
        # need its own providers' code (splits are acyclic, see propose_split).
        providers = upstream_modules(store, conversation_id, module_id)
        stacked: list[dict[str, Any]] = []
        provider_texts: list[str] = []
        provider_path_groups: list[list[str]] = []
        # The owner's earlier modules are already in the owner's tree, which the
        # stage runs whole (``full_patch``). A provider that is also a predecessor
        # is not stacked again and never counts as an overlap: building on it is
        # the point.
        predecessor_ids = {str(item["module_id"]) for item in predecessors}
        owner_changed = sorted(set(full_patch.changed_paths))
        for item in predecessors:
            stacked.append(
                {
                    "module_id": str(item["module_id"]),
                    "verification_id": str(item["verification_id"]),
                    "head_commit": str(item["head_commit"] or ""),
                    "kind": "predecessor",
                }
            )
        providers = [item for item in providers if item not in predecessor_ids]
        if providers:
            blocked: list[str] = []
            latest_by_provider: dict[str, dict[str, Any]] = {}
            for provider_id in providers:
                latest = store.latest_passed_board_verification(conversation_id, provider_id)
                if latest is None:
                    blocked.append(provider_id)
                    continue
                if store.has_newer_unresolved_verification(
                    conversation_id,
                    provider_id,
                    after_created_at=str(latest["created_at"]),
                    after_verification_id=str(latest["verification_id"]),
                ):
                    blocked.append(provider_id)
                    continue
                latest_by_provider[provider_id] = latest
            if blocked:
                raise BoardVerificationDeferred(blocked)
            for provider_id in providers:
                latest = latest_by_provider[provider_id]
                text = latest.get("patch_text")
                if not isinstance(text, str) or not text.strip():
                    return _failed(
                        "board_verification_provider_patch_missing",
                        head_commit=patch.head_commit,
                        patch_digest=own_digest,
                        changed_paths=own_changed,
                        base_commit=base_commit,
                    )
                provider_base = latest.get("base_commit")
                if (
                    isinstance(provider_base, str)
                    and provider_base
                    and provider_base != base_commit
                ):
                    return _failed(
                        BOARD_VERIFICATION_BASE_MISMATCH,
                        head_commit=patch.head_commit,
                        patch_digest=own_digest,
                        changed_paths=own_changed,
                        evidence={
                            "base_commit": base_commit,
                            "provider_bases": {
                                provider: latest_by_provider[provider].get("base_commit")
                                for provider in providers
                            },
                        },
                        base_commit=base_commit,
                    )
                # A passed verification records the union of every stacked path;
                # only the provider's own patch bytes are stacked, so its own
                # paths come from that patch.
                paths = patch_text_paths(text)
                provider_texts.append(text)
                provider_path_groups.append(sorted(set(paths)))
                stacked.append(
                    {
                        "module_id": provider_id,
                        "verification_id": str(latest["verification_id"]),
                        "head_commit": str(latest["head_commit"] or ""),
                    }
                )
            overlapping = find_overlapping_paths([*provider_path_groups, owner_changed])
            if overlapping:
                return _failed(
                    BOARD_VERIFICATION_DEPENDENCY_OVERLAP,
                    head_commit=patch.head_commit,
                    patch_digest=own_digest,
                    changed_paths=tuple(
                        sorted(set(own_changed) | {p for g in provider_path_groups for p in g})
                    ),
                    evidence={"overlapping_paths": overlapping},
                    stacked=tuple(stacked),
                    base_commit=base_commit,
                )
        stacked_tuple = tuple(stacked)
        if provider_texts:
            combined_text = combine_verification_patches([*provider_texts, full_patch.unified_diff])
            combined_changed = tuple(
                sorted(set(owner_changed) | {p for g in provider_path_groups for p in g})
            )
        else:
            combined_text = full_patch.unified_diff
            combined_changed = tuple(owner_changed)
        combined_digest = f"sha256:{sha256(combined_text.encode('utf-8')).hexdigest()}"
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
                changed_paths=combined_changed,
                repository_manifest_digest=repository_manifest_digest,
                toolchain_capability_digest=toolchain_capability_digest,
            )
        except RoomExecutionProfileError as exc:
            return _failed(
                exc.code,
                head_commit=patch.head_commit,
                patch_digest=own_digest,
                changed_paths=combined_changed,
                stacked=stacked_tuple,
                patch_text=patch.unified_diff,
                base_commit=base_commit,
            )
        candidate = ExactPatchCandidate(
            candidate_id=verification_id,
            patch_text=combined_text,
            patch_sha256=combined_digest,
            candidate_digest=combined_digest,
            # The room base: the stage is the execution root's worktree there,
            # and the owner's whole tree (``full_patch``) applies on it.
            base_head=full_patch.base_commit,
            allowed_files=combined_changed,
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
                    gate_packages=affected_packages(self._profile.profile_id, combined_changed),
                )
                try:
                    results = [
                        run_gate(layout, gate_id, output_tail_bytes=GATE_OUTPUT_TAIL_BYTES)
                        for gate_id in plan.gate_ids
                    ]
                finally:
                    layout.close()
                verify_stage_unchanged(staged)
        except RoomExecutionControllerError as exc:
            if exc.code in _TRANSIENT_STAGE_CODES:
                raise BoardVerificationTransientError(exc.code) from exc
            return _failed(
                exc.code,
                head_commit=patch.head_commit,
                patch_digest=own_digest,
                changed_paths=combined_changed,
                stacked=stacked_tuple,
                patch_text=patch.unified_diff,
                base_commit=base_commit,
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
            # Tails of the first failing gates only, so the evidence stays bounded.
            output_tails = {
                item.gate_id: item.output_tail
                for item in results
                if item.status != "passed" and item.output_tail
            }
            output_tails = dict(list(output_tails.items())[:MAX_EVIDENCE_TAIL_GATES])
            return _failed(
                BOARD_VERIFICATION_GATE_FAILED,
                head_commit=patch.head_commit,
                patch_digest=own_digest,
                changed_paths=combined_changed,
                gates=gates,
                evidence={"failed_gates": failed_gates, "output_tails": output_tails},
                stacked=stacked_tuple,
                patch_text=patch.unified_diff,
                base_commit=base_commit,
            )
        return BoardVerificationOutcome(
            status="passed",
            reason_code=None,
            head_commit=patch.head_commit,
            patch_digest=own_digest,
            changed_paths=combined_changed,
            gates=gates,
            evidence={},
            stacked=stacked_tuple,
            patch_text=patch.unified_diff,
            base_commit=base_commit,
        )


__all__ = [
    "BOARD_VERIFICATION_GATE_FAILED",
    "BOARD_VERIFICATION_OUTSIDE_CHARTER",
    "BOARD_VERIFICATION_RISK_POLICY",
    "BOARD_VERIFICATION_WORKER_ID",
    "BoardVerificationDeferred",
    "BoardVerificationOutcome",
    "BoardVerificationTransientError",
    "RoomBoardVerificationWorker",
    "combine_verification_patches",
    "find_overlapping_paths",
]
