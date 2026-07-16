"""Local lifecycle composition for exact-patch Room execution.

The Chat API is the only long-lived coordinator.  It may discover durable runs and
start a narrow one-shot controller, but it never receives a patch or command from
the browser.  Controllers recover all authority from ``chat.db`` and are fenced by
their durable process identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_execution_contracts import (
    EXECUTION_RISK_POLICY_REVISION,
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
    low_risk_patch_eligible,
    normalize_execution_patch,
)
from xmuse_core.chat.room_execution_controller import (
    RoomExecutionControllerError,
    build_workspace_guard,
    candidate_from_mapping,
)
from xmuse_core.chat.room_execution_profiles import (
    ExecutionGatePlan,
    ExecutionGateProfile,
    RoomExecutionProfileError,
    build_execution_gate_plan,
    gate_ids_for_profile_paths,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_execution_runtime_store import RoomExecutionRuntimeStore
from xmuse_core.chat.room_execution_sandbox import (
    RoomExecutionSandboxError,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
)
from xmuse_core.chat.room_execution_supervisor import (
    ExecutionControllerSupervisorConfig,
    StartedExecutionController,
    ensure_execution_controller,
    stop_execution_controller,
)
from xmuse_core.chat.room_runtime import read_process_start_identity


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _kill_switch_enabled() -> bool:
    return os.environ.get("XMUSE_ENABLE_AGENT_CONSENSUS_EXECUTION", "").strip() == "1"


class RoomExecutionRuntime:
    """Reconcile consensus authorization and one-shot controller processes."""

    def __init__(
        self,
        *,
        root: Path,
        execution_root: Path,
        launcher_root: Path,
        execution_profile_id: str = "xmuse-monorepo/v2",
        generation: str | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.execution_root = execution_root.expanduser().resolve()
        self.launcher_root = launcher_root.expanduser().resolve()
        self.execution_profile: ExecutionGateProfile = get_execution_gate_profile(
            execution_profile_id
        )
        self.generation = (
            generation
            or os.environ.get("XMUSE_WORKROOM_GENERATION", "").strip()
            or f"direct-{os.getpid()}"
        )
        self.store = RoomExecutionRuntimeStore(self.root / "chat.db")
        self.supervisor = ExecutionControllerSupervisorConfig(
            repo_root=self.launcher_root,
            xmuse_root=self.root,
            execution_worktree=self.execution_root,
            generation=self.generation,
        )
        self._consensus_enabled = _kill_switch_enabled()
        self._lock = threading.Lock()
        self._controller_lock = threading.Lock()
        self._starting_controllers: dict[str, StartedExecutionController] = {}

    @property
    def consensus_kill_switch_enabled(self) -> bool:
        return self._consensus_enabled

    def decision_context(
        self, candidate_id: str
    ) -> tuple[ExecutionWorkspaceGuard, None, ExecutionGatePlan]:
        """Build manual-execution guards from trusted target filesystem facts."""

        candidate = self._candidate(candidate_id)
        exact = candidate_from_mapping(candidate)
        gate_plan = self._gate_plan(exact.allowed_files)
        return build_workspace_guard(self.execution_root, exact), None, gate_plan

    def profile_status(self) -> dict[str, Any]:
        """Return only fixed profile identity and safe capability readiness."""

        safe = self.execution_profile.safe_reference()
        try:
            self._full_profile_evidence()
        except (OSError, RoomExecutionProfileError, RoomExecutionSandboxError) as exc:
            code = getattr(exc, "code", None)
            safe["readiness"] = {
                "state": "blocked",
                "ready": False,
                "code": (
                    code
                    if isinstance(code, str) and len(code) <= 200
                    else "room_execution_gate_profile_unavailable"
                ),
            }
            return safe
        safe["readiness"] = {"state": "ready", "ready": True, "code": "ready"}
        return safe

    def start_run(self, run_id: str) -> None:
        with self._controller_lock:
            prior = self._starting_controllers.get(run_id)
            if prior is not None and prior.process.poll() is None:
                return
            self._starting_controllers.pop(run_id, None)
            started = ensure_execution_controller(self.store, self.supervisor, run_id=run_id)
            if started is not None:
                self._starting_controllers[run_id] = started

    def reconcile_once(self) -> dict[str, int]:
        """Single-flight bounded reconciliation; individual failures remain durable."""

        if not self._lock.acquire(blocking=False):
            return {"consensus_checked": 0, "controllers_checked": 0}
        consensus_checked = 0
        controllers_checked = 0
        started_run_ids: set[str] = set()
        try:
            for candidate_id in self._endorsed_candidate_ids(limit=20):
                consensus_checked += 1
                try:
                    candidate = self._candidate(candidate_id)
                    exact = candidate_from_mapping(candidate)
                    try:
                        workspace_guard = build_workspace_guard(self.execution_root, exact)
                    except RoomExecutionControllerError:
                        workspace_guard = ExecutionWorkspaceGuard(
                            base_head=str(candidate.get("base_head") or ""),
                            workspace_clean=False,
                            target_files_digest=f"sha256:{'0' * 64}",
                            existing_regular_files=frozenset(),
                        )
                    risk = self._risk_evaluation(candidate)
                    try:
                        gate_plan = self._gate_plan(exact.allowed_files)
                    except (
                        OSError,
                        RoomExecutionProfileError,
                        RoomExecutionSandboxError,
                    ):
                        gate_plan = None
                    result = self.store.reconcile_consensus_candidate(
                        candidate_id=candidate_id,
                        kill_switch_enabled=self.consensus_kill_switch_enabled,
                        workspace_guard=workspace_guard,
                        risk_evaluation=risk,
                        gate_plan=gate_plan,
                    )
                    run = result.get("run")
                    if isinstance(run, Mapping) and isinstance(run.get("run_id"), str):
                        candidate_run_id = str(run["run_id"])
                        self.start_run(candidate_run_id)
                        started_run_ids.add(candidate_run_id)
                except Exception:
                    # Consensus is optional automation.  Its durable candidate remains
                    # visible as manual-required or can be retried after a transient guard.
                    continue

            for binding in self.store.list_controller_recovery(limit=500):
                binding_run_id = binding.get("run_id")
                if not isinstance(binding_run_id, str) or not binding_run_id:
                    continue
                controllers_checked += 1
                if binding_run_id in started_run_ids:
                    continue
                try:
                    self.start_run(binding_run_id)
                except Exception:
                    # The controller/store owns terminal evidence.  A later pass may
                    # safely retry only unbound or confirmed-dead durable work.
                    continue
            return {
                "consensus_checked": consensus_checked,
                "controllers_checked": controllers_checked,
            }
        finally:
            self._lock.release()

    def stop_all(self) -> dict[str, int]:
        """Identity-fenced shutdown for controllers owned by this Workroom PGID."""

        stopped = 0
        pending = 0
        targets: set[tuple[int, str]] = set()
        for binding in self.store.list_controller_recovery(limit=500):
            run_id = binding.get("run_id")
            if not isinstance(run_id, str):
                continue
            pid = binding.get("controller_pid")
            identity = binding.get("controller_start_identity")
            if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(identity, str):
                pending += 1
                continue
            if read_process_start_identity(pid) != identity:
                continue
            targets.add((pid, identity))
        with self._controller_lock:
            for started in self._starting_controllers.values():
                if started.process.poll() is None:
                    targets.add((started.pid, started.start_identity))
            self._starting_controllers.clear()
        for pid, identity in sorted(targets):
            if stop_execution_controller(pid=pid, start_identity=identity):
                stopped += 1
            else:
                pending += 1
        return {"stopped": stopped, "pending": pending}

    def _candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.store.get_candidate(candidate_id, include_patch=True)
        if candidate is None:
            raise KeyError(candidate_id)
        return candidate

    def _risk_evaluation(self, candidate: Mapping[str, Any]) -> ExecutionRiskEvaluation:
        patch = normalize_execution_patch(
            {
                "schema_version": "room_execution_patch/v1",
                "base_head": candidate.get("base_head"),
                "summary": candidate.get("summary"),
                "unified_diff": candidate.get("unified_diff"),
                "allowed_files": candidate.get("allowed_files"),
            }
        )
        approved = low_risk_patch_eligible(patch)
        reason = None if approved else "consensus_low_risk_policy_rejected"
        evidence = {
            "schema_version": "room_execution_risk_evidence/v1",
            "candidate_digest": patch.candidate_digest,
            "policy_revision": EXECUTION_RISK_POLICY_REVISION,
            "approved": approved,
            "reason_code": reason,
        }
        return ExecutionRiskEvaluation(
            approved=approved,
            policy_revision=EXECUTION_RISK_POLICY_REVISION,
            evidence_digest=_digest(evidence),
            reason_code=reason,
        )

    def _gate_plan(self, allowed_files: tuple[str, ...]) -> ExecutionGatePlan:
        gate_ids_for_profile_paths(self.execution_profile.profile_id, allowed_files)
        repository_manifest_digest, toolchain_capability_digest = self._full_profile_evidence()
        return build_execution_gate_plan(
            profile_id=self.execution_profile.profile_id,
            changed_paths=allowed_files,
            repository_manifest_digest=repository_manifest_digest,
            toolchain_capability_digest=toolchain_capability_digest,
        )

    def _full_profile_evidence(self) -> tuple[str, str]:
        """Prove the configured profile's complete local capability surface.

        Candidate plans freeze a path-selected gate subset, while their capability
        digest covers the complete configured profile.  Authorization, later drift
        checks, and the readiness projected to the browser therefore share one
        fail-closed capability boundary.
        """

        repository_manifest_digest = build_repository_manifest_digest(
            self.execution_root, self.execution_profile
        )
        toolchain_capability_digest = build_toolchain_capability_digest(
            self.execution_root,
            self.execution_profile,
            gate_ids=self.execution_profile.gate_ids,
        )
        return repository_manifest_digest, toolchain_capability_digest

    def _endorsed_candidate_ids(self, *, limit: int) -> list[str]:
        return self.store.list_endorsed_candidate_ids(limit=limit)
