"""Host-owned integration branch for accepted board work (M2b).

The host rebuilds one integration branch per room,
``refs/heads/xmuse/integration/<conversation_id>`` in the host-owned bare
mirror, from the accepted candidates (§3.11): start from the room base commit,
rebuild one commit per module with a three-way apply, dependency-first order
with incumbents before newcomers, fallback to the integrated older candidate
on conflict, rule 4 culprit pinning with restart, gates once on the result,
and rule 7 as the last resort. The branch moves only when every gate passes.

All git work happens in the host mirror and host-owned stages; the user's
checkout is never touched. A candidate's patch is its verification row's own
stored ``patch_text`` (the bytes a review covered), never a re-read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_board import (
    BOARD_INTEGRATION_CONFLICT,
    BOARD_INTEGRATION_GATE_FAILED,
    BOARD_INTEGRATION_WAITING_FOR_DEPENDENCY,
    BOARD_INTEGRATION_WOULD_DROP_ACCEPTED,
    INTEGRATION_LEASE_TTL_S,
    MAX_INTEGRATION_ATTEMPTS,
    RoomBoardStore,
    charter_path_allowed,
    integration_apply_order,
)
from xmuse_core.chat.room_board_projection import is_valid_finding_path
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
from xmuse_core.chat.room_owner_clones import _META_DIR_NAME, _MIRROR_DIR_NAME
from xmuse_core.chat.room_owner_ids import owner_id_for_participant

logger = logging.getLogger(__name__)

BOARD_INTEGRATION_WORKER_ID = "board-integration"
# Display-only evidence for gates: at most this many failing gates, each with
# at most this many bytes of sanitized output tail (same bounds as M1).
GATE_OUTPUT_TAIL_BYTES = 2048
MAX_EVIDENCE_TAIL_GATES = 3
# Conflict paths leave the server only through the §5.3 detail route (part B),
# repository-relative and validated like ``Finding.path``, at most 50 listed.
MAX_CONFLICT_PATHS_LISTED = 50
INTEGRATION_REF_PREFIX = "refs/heads/xmuse/integration/"
# Bounded automatic re-runs of an ``error`` job: once after 10 minutes, once
# after 30 minutes (plus once after a host restart, tracked in the store).
AUTO_RETRY_DELAYS_S = (600.0, 1800.0)


class BoardIntegrationTransientError(RuntimeError):
    """A host-side hiccup: release the job for a later pass."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _GatePlanFailed(RuntimeError):
    """The applied set selects no gates: recorded as a gate failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _IncumbentApplyFailed(RuntimeError):
    """An incumbent's patch did not apply: rule 4 pinning may rescue the job."""

    def __init__(
        self,
        module_id: str,
        conflict_paths: list[str],
        outcomes: dict[str, _ModuleOutcome],
        applied_at_candidate: dict[str, bool],
    ) -> None:
        self.module_id = module_id
        self.conflict_paths = list(conflict_paths)
        self.outcomes = dict(outcomes)
        self.applied_at_candidate = dict(applied_at_candidate)
        super().__init__(module_id)


@dataclass
class _ModuleOutcome:
    status: str  # applied | fell_back | conflicted | waiting | not_applied
    applied_verification_id: str | None = None
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    conflicts_total: int = 0
    reason_code: str | None = None


@dataclass(frozen=True)
class IntegrationRunOutcome:
    """Terminal engine result for one job (content, never transient)."""

    status: str  # integrated | conflicted | gate_failed
    reason_code: str | None
    result_commit: str | None
    gates: tuple[dict[str, Any], ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    items: tuple[dict[str, Any], ...] = ()


# ---------------------------------------------------------------------------
# git helpers (host mirror and host-owned stages only)
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }


def _git_argv(cwd: Path | None, args: Sequence[str]) -> list[str]:
    argv = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "protocol.file.allow=always",
    ]
    if cwd is not None:
        argv.extend(["-C", str(cwd)])
    argv.extend(args)
    return argv


def _run_git_raw(
    cwd: Path | None, args: Sequence[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            _git_argv(cwd, args),
            input=input_text,
            env=_git_env(),
            timeout=120,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BoardIntegrationTransientError("board_integration_git_unavailable") from exc
    except OSError as exc:
        raise BoardIntegrationTransientError("board_integration_git_unavailable") from exc


def _git(cwd: Path | None, *args: str, input_text: str | None = None) -> str:
    result = _run_git_raw(cwd, list(args), input_text=input_text)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip().replace("\n", " ")
        raise BoardIntegrationTransientError(f"board_integration_git_unavailable: {detail[:200]}")
    return result.stdout


_APPLY_CONFLICT_RES = (
    re.compile(r"^error:\s+patch failed:\s+(.+)$"),
    re.compile(r"^error:\s+(.+?):\s+already exists in (?:working directory|index)$"),
    re.compile(r"^error:\s+(.+?):\s+does not exist in index$"),
    re.compile(r"^Applied patch to '(.+)' with conflicts\.$"),
)


def parse_apply_conflicts(stderr: str) -> list[str]:
    """Return the repository-relative paths a failed ``git apply`` names."""

    found: list[str] = []
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("Applied patch to '") and line.endswith("with conflicts."):
            token = line[len("Applied patch to '") :].split("'")[0].strip()
            if token:
                found.append(token)
            continue
        if not line.startswith("error:"):
            continue
        error_token: str | None = None
        for pattern in _APPLY_CONFLICT_RES:
            match = pattern.match(line)
            if match is not None:
                error_token = match.group(1).strip().split(":")[0].strip()
                break
        if error_token is None:
            head = line[len("error:") :].strip().split(":")[0].strip()
            if head and " " not in head and "/" in head:
                error_token = head
        if (
            error_token
            and " " not in error_token
            and "\\" not in error_token
            and not error_token.startswith("-")
        ):
            found.append(error_token)
    ordered: list[str] = []
    for path in found:
        if path not in ordered:
            ordered.append(path)
    return ordered


def attribute_conflicts(
    paths: Sequence[str], charters: Mapping[str, Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Attribute conflict paths to charter ``paths`` matches.

    Returns ``(listed, total)``: at most ``MAX_CONFLICT_PATHS_LISTED`` valid
    entries with their ``attributed_module_ids``; ``total`` counts every path,
    including ones that fail the ``Finding.path`` rule (counted, never listed).
    """

    unique: list[str] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    listed: list[dict[str, Any]] = []
    for path in unique:
        if not is_valid_finding_path(path):
            continue
        if len(listed) >= MAX_CONFLICT_PATHS_LISTED:
            break
        attributed = sorted(
            module_id
            for module_id, info in charters.items()
            if charter_path_allowed(path, _charter_patterns(info))
        )
        listed.append({"path": path, "attributed_module_ids": attributed})
    return listed, len(unique)


def _charter_patterns(info: Mapping[str, Any]) -> list[str]:
    charter = info.get("charter")
    if not isinstance(charter, dict):
        return []
    patterns = charter.get("paths", [])
    return [item for item in patterns if isinstance(item, str)]


def _upstream_modules(module_id: str, providers: Mapping[str, Sequence[str]]) -> set[str]:
    """Return every module ``module_id`` transitively depends on."""

    seen: set[str] = set()
    frontier = [module_id]
    while frontier:
        current = frontier.pop()
        for provider in providers.get(current, []):
            if provider != module_id and provider not in seen:
                seen.add(provider)
                frontier.append(provider)
    return seen


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------


class RoomBoardIntegrationEngine:
    """Rebuild the room integration branch from frozen accepted candidates."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        clones_root: Path | str,
        xmuse_root: Path | str,
        execution_root: Path | str,
        execution_profile_id: str = "xmuse-monorepo/v2",
    ) -> None:
        self._db_path = Path(db_path)
        self._clones_root = Path(clones_root)
        self._xmuse_root = Path(xmuse_root)
        self._execution_root = Path(execution_root)
        # Fail fast on an unknown profile; the plan is rebuilt per job.
        self._profile = get_execution_gate_profile(execution_profile_id)

    # -- room base commit and mirror --------------------------------------

    def _room_base_commit(self, conversation_id: str, inputs: Mapping[str, Any]) -> str:
        """Return the room's base commit: the first owner clone's base.

        Owner metadata is host-owned; the clone itself is never inspected.
        Without any clone metadata, fall back to the oldest candidate's stored
        base commit.
        """

        meta_dir = self._clones_root / _META_DIR_NAME
        oldest: tuple[float, str] | None = None
        charters = inputs.get("charters", {})
        if meta_dir.is_dir() and isinstance(charters, dict):
            for info in charters.values():
                if not isinstance(info, dict):
                    continue
                owner = info.get("owner_participant_id")
                if not isinstance(owner, str) or not owner:
                    continue
                owner_id = owner_id_for_participant(conversation_id, owner)
                meta = meta_dir / f"{owner_id}.json"
                try:
                    payload = json.loads(meta.read_text(encoding="utf-8"))
                    base = payload.get("base_commit")
                    if not isinstance(base, str) or not base.strip():
                        continue
                    mtime = meta.stat().st_mtime
                except (OSError, ValueError):
                    continue
                if oldest is None or mtime < oldest[0]:
                    oldest = (mtime, base.strip())
        if oldest is not None:
            return oldest[1]
        verifications = inputs.get("verifications", {})
        bases: list[tuple[str, str]] = []
        if isinstance(verifications, dict):
            for module_id in sorted(verifications):
                info = verifications[module_id]
                if isinstance(info, dict) and isinstance(info.get("base_commit"), str):
                    bases.append((str(info.get("created_at", "")), str(info["base_commit"])))
        if bases:
            return sorted(bases)[0][1]
        raise BoardIntegrationTransientError("board_integration_base_unknown")

    def _mirror(self) -> Path:
        mirror = self._clones_root / _MIRROR_DIR_NAME
        if not mirror.is_dir():
            try:
                self._clones_root.mkdir(parents=True, exist_ok=True)
                _git(None, "init", "--bare", str(mirror))
            except BoardIntegrationTransientError as exc:
                raise BoardIntegrationTransientError(
                    "board_integration_mirror_unavailable"
                ) from exc
        return mirror

    def _mirror_head(self, mirror: Path, ref: str) -> str | None:
        result = _run_git_raw(mirror, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
        if result.returncode != 0:
            return None
        commit = result.stdout.strip()
        return commit or None

    # -- three-way apply ---------------------------------------------------

    def _try_apply(self, stage: Path, patch_text: str) -> list[str] | None:
        """Apply one stored patch; None on success, conflict paths on failure."""

        result = _run_git_raw(stage, ["apply", "--3way", "--index", "-"], input_text=patch_text)
        if result.returncode == 0:
            return None
        combined = f"{result.stdout}\n{result.stderr}"
        if (
            "patch failed" in combined
            or "already exists" in combined
            or "does not exist" in combined
            or "with conflicts" in combined
        ):
            paths = parse_apply_conflicts(combined)
            if not paths:
                raise BoardIntegrationTransientError(
                    "board_integration_stage_failed: apply failed without paths"
                )
            _run_git_raw(stage, ["reset", "-q", "--hard", "HEAD"])
            _run_git_raw(stage, ["clean", "-fdq"])
            return paths
        detail = (result.stderr or result.stdout or "git apply failed").strip().replace("\n", " ")
        raise BoardIntegrationTransientError(f"board_integration_stage_failed: {detail[:200]}")

    def _commit_applied(
        self, stage: Path, module_id: str, verification_id: str, *, integration_id: str
    ) -> None:
        _git(
            stage,
            "-c",
            "user.name=xmuse-integration",
            "-c",
            "user.email=infrastructure@localhost",
            "commit",
            "-q",
            "-m",
            f"integrate {module_id} {verification_id} ({integration_id})",
        )

    # -- apply phase (rules 1-4) -------------------------------------------

    def _run_apply_pass(
        self,
        *,
        stage: Path,
        integration_id: str,
        ordered: list[str],
        candidates: Mapping[str, str],
        patches: Mapping[str, str],
        roles: Mapping[str, str],
        providers: Mapping[str, Sequence[str]],
        green_applied: Mapping[str, str],
        pins: Mapping[str, str],
        charters: Mapping[str, Mapping[str, Any]],
    ) -> tuple[dict[str, _ModuleOutcome], dict[str, bool]]:
        """Apply every candidate in order; may raise ``_IncumbentApplyFailed``."""

        outcomes: dict[str, _ModuleOutcome] = {}
        applied_at_candidate: dict[str, bool] = {}
        for module_id in ordered:
            candidate = candidates[module_id]
            pinned = pins.get(module_id)
            if pinned == "left_out":
                # A rule 4 culprit without an older candidate stays out; its
                # conflicts are the incumbent's paths, recorded by the caller.
                outcomes[module_id] = _ModuleOutcome(status="conflicted")
                applied_at_candidate[module_id] = False
                continue
            if pinned is not None:
                failed = self._try_apply(stage, patches[pinned])
                if failed is not None:
                    # A pinned fallback that no longer applies is left out.
                    outcomes[module_id] = _ModuleOutcome(status="conflicted")
                else:
                    self._commit_applied(stage, module_id, pinned, integration_id=integration_id)
                    outcomes[module_id] = _ModuleOutcome(
                        status="conflicted", applied_verification_id=pinned
                    )
                applied_at_candidate[module_id] = False
                continue
            role = roles.get(module_id, "newcomer")
            if role == "newcomer" and any(
                provider not in applied_at_candidate or not applied_at_candidate[provider]
                for provider in providers.get(module_id, [])
            ):
                # Rule 3 closure: never build a newcomer on a dependency
                # version it was not verified with.
                fallback = green_applied.get(module_id)
                if (
                    fallback is not None
                    and fallback != candidate
                    and self._try_apply(stage, patches[fallback]) is None
                ):
                    self._commit_applied(stage, module_id, fallback, integration_id=integration_id)
                    outcomes[module_id] = _ModuleOutcome(
                        status="fell_back", applied_verification_id=fallback
                    )
                else:
                    outcomes[module_id] = _ModuleOutcome(
                        status="waiting",
                        reason_code=BOARD_INTEGRATION_WAITING_FOR_DEPENDENCY,
                    )
                applied_at_candidate[module_id] = False
                continue
            failed = self._try_apply(stage, patches[candidate])
            if failed is None:
                self._commit_applied(stage, module_id, candidate, integration_id=integration_id)
                outcomes[module_id] = _ModuleOutcome(
                    status="applied", applied_verification_id=candidate
                )
                applied_at_candidate[module_id] = True
                continue
            if role == "incumbent":
                # Rule 4 decides below; a newcomer never makes an incumbent
                # conflicted.
                raise _IncumbentApplyFailed(module_id, failed, outcomes, applied_at_candidate)
            listed, total = attribute_conflicts(failed, charters)
            fallback = green_applied.get(module_id)
            if (
                fallback is not None
                and fallback != candidate
                and self._try_apply(stage, patches[fallback]) is None
            ):
                self._commit_applied(stage, module_id, fallback, integration_id=integration_id)
                outcomes[module_id] = _ModuleOutcome(
                    status="fell_back",
                    applied_verification_id=fallback,
                    conflicts=listed,
                    conflicts_total=total,
                    reason_code=BOARD_INTEGRATION_CONFLICT,
                )
            else:
                outcomes[module_id] = _ModuleOutcome(
                    status="conflicted",
                    conflicts=listed,
                    conflicts_total=total,
                    reason_code=BOARD_INTEGRATION_CONFLICT,
                )
            applied_at_candidate[module_id] = False
        return outcomes, applied_at_candidate

    def _culprits(
        self,
        *,
        incumbent: str,
        conflict_paths: Sequence[str],
        ordered_before: Sequence[str],
        roles: Mapping[str, str],
        providers: Mapping[str, Sequence[str]],
        applied_at_candidate: Mapping[str, bool],
        charters: Mapping[str, Mapping[str, Any]],
    ) -> list[str]:
        """Newcomers applied before the incumbent that may have broken it."""

        upstream = _upstream_modules(incumbent, providers)
        culprits: list[str] = []
        for module_id in ordered_before:
            if roles.get(module_id) != "newcomer":
                continue
            if not applied_at_candidate.get(module_id, False):
                continue
            if module_id in upstream:
                culprits.append(module_id)
                continue
            if any(
                charter_path_allowed(path, _charter_patterns(charters.get(module_id, {})))
                for path in conflict_paths
                if is_valid_finding_path(path)
            ):
                culprits.append(module_id)
        return culprits

    # -- gates (rule 5) ----------------------------------------------------

    def _run_gates(
        self, *, stage: Path, changed_paths: Sequence[str]
    ) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        try:
            repository_manifest_digest = build_repository_manifest_digest(
                self._execution_root, self._profile
            )
            toolchain_capability_digest = build_toolchain_capability_digest(
                self._execution_root, self._profile, gate_ids=self._profile.gate_ids
            )
        except (OSError, RoomExecutionSandboxError, RoomExecutionProfileError) as exc:
            raise BoardIntegrationTransientError(
                getattr(exc, "code", "board_integration_stage_failed")
                if isinstance(exc, (RoomExecutionSandboxError, RoomExecutionProfileError))
                else "board_integration_stage_failed"
            ) from exc
        try:
            plan = build_execution_gate_plan(
                profile_id=self._profile.profile_id,
                changed_paths=tuple(changed_paths),
                repository_manifest_digest=repository_manifest_digest,
                toolchain_capability_digest=toolchain_capability_digest,
            )
        except RoomExecutionProfileError as exc:
            raise _GatePlanFailed(exc.code) from exc
        try:
            layout = discover_sandbox_layout(
                stage=stage,
                execution_root=self._execution_root,
                gate_ids=plan.gate_ids,
                profile=self._profile,
                expected_toolchain_capability_digest=toolchain_capability_digest,
            )
        except (OSError, RoomExecutionSandboxError) as exc:
            raise BoardIntegrationTransientError(
                getattr(exc, "code", "board_integration_stage_failed")
                if isinstance(exc, RoomExecutionSandboxError)
                else "board_integration_stage_failed"
            ) from exc
        try:
            results = [
                run_gate(layout, gate_id, output_tail_bytes=GATE_OUTPUT_TAIL_BYTES)
                for gate_id in plan.gate_ids
            ]
        except RoomExecutionSandboxError as exc:
            raise BoardIntegrationTransientError(exc.code) from exc
        finally:
            layout.close()
        clean = _run_git_raw(stage, ["status", "--porcelain"])
        if clean.returncode != 0 or clean.stdout.strip():
            raise BoardIntegrationTransientError("execution_gate_workspace_mutated")
        gates = tuple(
            {
                "gate_id": item.gate_id,
                "status": item.status,
                "exit_code": item.exit_code,
                "reason_code": item.reason_code,
            }
            for item in results
        )
        evidence: dict[str, Any] = {}
        if any(item["status"] != "passed" for item in gates):
            output_tails = {
                item.gate_id: item.output_tail
                for item in results
                if item.status != "passed" and item.output_tail
            }
            evidence = {
                "failed_gates": [item["gate_id"] for item in gates if item["status"] != "passed"],
                "output_tails": dict(list(output_tails.items())[:MAX_EVIDENCE_TAIL_GATES]),
            }
        return gates, evidence

    # -- one job (rules 1-7) -------------------------------------------------

    def run_job(
        self,
        *,
        conversation_id: str,
        integration_id: str,
        input_set: Sequence[Mapping[str, str]],
        items: Sequence[Mapping[str, Any]],
    ) -> IntegrationRunOutcome:
        """Rebuild the branch for one frozen input set (rules 1-7 in order)."""

        store = RoomBoardStore(self._db_path)
        inputs = store.board_integration_inputs(conversation_id)
        charters = inputs["charters"]
        providers: dict[str, list[str]] = {
            module_id: list(deps) for module_id, deps in inputs["providers"].items()
        }
        candidates = {item["module_id"]: item["verification_id"] for item in input_set}
        roles = {str(item["module_id"]): str(item["role"]) for item in items}
        green = inputs["green"]
        green_applied: dict[str, str] = dict(green["applied"]) if green is not None else {}
        green_commit = green["green_head_commit"] if green is not None else None

        # Every candidate plus every fallback older version the run may apply.
        wanted_vids = sorted(
            {vid for vid in candidates.values()}
            | {
                green_applied[module_id]
                for module_id in candidates
                if green_applied.get(module_id) not in (None, candidates[module_id])
            }
        )
        try:
            stored = store.board_integration_patches(wanted_vids)
        except ValueError as exc:
            raise BoardIntegrationTransientError("board_integration_stage_failed") from exc
        patches = {vid: stored[vid]["patch_text"] for vid in wanted_vids}
        changed_of = {vid: list(stored[vid]["changed_paths"]) for vid in wanted_vids}
        ordered = integration_apply_order(list(candidates), providers, roles)

        # An applied set equal to the green head runs no gates and moves nothing.
        if (
            green is not None
            and set(candidates) == set(green_applied)
            and all(
                candidates[module_id] == green_applied.get(module_id) for module_id in candidates
            )
        ):
            return IntegrationRunOutcome(
                status="integrated",
                reason_code=None,
                result_commit=green_commit,
                items=tuple(
                    {
                        "module_id": module_id,
                        "status": "applied",
                        "applied_verification_id": candidates[module_id],
                        "conflicts": [],
                        "conflicts_total": 0,
                        "reason_code": None,
                    }
                    for module_id in ordered
                ),
            )

        mirror = self._mirror()
        ref = f"{INTEGRATION_REF_PREFIX}{conversation_id}"
        base_commit = self._room_base_commit(conversation_id, inputs)
        if self._mirror_head(mirror, base_commit) is None:
            raise BoardIntegrationTransientError("board_integration_base_unknown")

        stage_parent = self._xmuse_root / "runtime" / "integration-stages"
        stage_parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix="stage-", dir=str(stage_parent)))
        try:
            _git(None, "clone", "--no-checkout", "--no-hardlinks", str(mirror), str(stage_dir))
            _git(stage_dir, "checkout", "--detach", "-q", base_commit)
            # Rule 4: pin culprits to their fallback (or leave them out) and
            # restart from the base, at most once per newcomer.
            pins: dict[str, str] = {}
            pin_conflicts: dict[str, tuple[list[dict[str, Any]], int]] = {}
            outcomes: dict[str, _ModuleOutcome] = {}
            newcomer_count = sum(1 for module_id in ordered if roles.get(module_id) == "newcomer")
            rule7: tuple[str, list[str]] | None = None
            for _ in range(newcomer_count + 1):
                _git(stage_dir, "reset", "--hard", "-q", base_commit)
                _run_git_raw(stage_dir, ["clean", "-fdq"])
                try:
                    outcomes, _ = self._run_apply_pass(
                        stage=stage_dir,
                        integration_id=integration_id,
                        ordered=ordered,
                        candidates=candidates,
                        patches=patches,
                        roles=roles,
                        providers=providers,
                        green_applied=green_applied,
                        pins=pins,
                        charters=charters,
                    )
                except _IncumbentApplyFailed as exc:
                    ordered_before = ordered[: ordered.index(exc.module_id)]
                    fresh = self._culprits(
                        incumbent=exc.module_id,
                        conflict_paths=exc.conflict_paths,
                        ordered_before=ordered_before,
                        roles=roles,
                        providers=providers,
                        applied_at_candidate=exc.applied_at_candidate,
                        charters=charters,
                    )
                    unpinned = [item for item in fresh if item not in pins]
                    if not unpinned:
                        rule7 = (exc.module_id, list(exc.conflict_paths))
                        outcomes = exc.outcomes
                        break
                    listed, total = attribute_conflicts(exc.conflict_paths, charters)
                    for culprit in unpinned:
                        fallback = green_applied.get(culprit)
                        pins[culprit] = (
                            fallback
                            if fallback is not None and fallback != candidates[culprit]
                            else "left_out"
                        )
                        pin_conflicts[culprit] = (listed, total)
                    continue
                break
            for module_id, (listed, total) in pin_conflicts.items():
                # Rule 4 culprits stay recorded as conflicted with the
                # incumbent's conflicting paths, whatever the final pass did.
                current = outcomes.get(module_id)
                if current is None:
                    continue
                current.conflicts = listed
                current.conflicts_total = total
                current.status = "conflicted"
                current.reason_code = BOARD_INTEGRATION_CONFLICT
            if rule7 is not None:
                # Rule 7 last resort: the base can no longer carry the green
                # head. No gates run and the branch stays.
                failed_module, failed_paths = rule7
                listed, total = attribute_conflicts(failed_paths, charters)
                outcomes[failed_module] = _ModuleOutcome(
                    status="conflicted",
                    conflicts=listed,
                    conflicts_total=total,
                    reason_code=BOARD_INTEGRATION_WOULD_DROP_ACCEPTED,
                )
                return IntegrationRunOutcome(
                    status="conflicted",
                    reason_code=BOARD_INTEGRATION_WOULD_DROP_ACCEPTED,
                    result_commit=None,
                    items=tuple(
                        {
                            "module_id": module_id,
                            "status": (
                                outcomes[module_id].status
                                if module_id in outcomes
                                else "not_applied"
                            ),
                            "applied_verification_id": (
                                outcomes[module_id].applied_verification_id
                                if module_id in outcomes
                                else None
                            ),
                            "conflicts": (
                                outcomes[module_id].conflicts if module_id in outcomes else []
                            ),
                            "conflicts_total": (
                                outcomes[module_id].conflicts_total if module_id in outcomes else 0
                            ),
                            "reason_code": (
                                outcomes[module_id].reason_code if module_id in outcomes else None
                            ),
                        }
                        for module_id in ordered
                    ),
                )
            applied_versions = {
                module_id: outcome.applied_verification_id
                for module_id, outcome in outcomes.items()
                if outcome.applied_verification_id is not None
            }
            if applied_versions == green_applied:
                # Every newcomer conflicted, fell back or waits: the result equals the
                # green head (or is empty before the first one), so no gate runs and
                # the branch does not move (contract §3.11 rule 5).
                return IntegrationRunOutcome(
                    status="integrated",
                    reason_code=None,
                    result_commit=green_commit,
                    items=tuple(
                        {
                            "module_id": module_id,
                            "status": outcomes[module_id].status,
                            "applied_verification_id": outcomes[module_id].applied_verification_id,
                            "conflicts": outcomes[module_id].conflicts,
                            "conflicts_total": outcomes[module_id].conflicts_total,
                            "reason_code": outcomes[module_id].reason_code,
                        }
                        for module_id in ordered
                    ),
                )
            union_paths = sorted(
                {path for vid in applied_versions.values() for path in changed_of[vid]}
            )
            try:
                gates, evidence = self._run_gates(stage=stage_dir, changed_paths=union_paths)
            except _GatePlanFailed as exc:
                return IntegrationRunOutcome(
                    status="gate_failed",
                    reason_code=BOARD_INTEGRATION_GATE_FAILED,
                    result_commit=None,
                    evidence={"plan_error": exc.code},
                    items=tuple(
                        {
                            "module_id": module_id,
                            "status": outcomes[module_id].status,
                            "applied_verification_id": outcomes[module_id].applied_verification_id,
                            "conflicts": outcomes[module_id].conflicts,
                            "conflicts_total": outcomes[module_id].conflicts_total,
                            "reason_code": outcomes[module_id].reason_code,
                        }
                        for module_id in ordered
                    ),
                )
            if any(gate["status"] != "passed" for gate in gates):
                # Rule 6: the branch stays; every applied newcomer is a
                # suspect, incumbents stay integrated.
                return IntegrationRunOutcome(
                    status="gate_failed",
                    reason_code=BOARD_INTEGRATION_GATE_FAILED,
                    result_commit=None,
                    gates=gates,
                    evidence=evidence,
                    items=tuple(
                        {
                            "module_id": module_id,
                            "status": outcomes[module_id].status,
                            "applied_verification_id": outcomes[module_id].applied_verification_id,
                            "conflicts": outcomes[module_id].conflicts,
                            "conflicts_total": outcomes[module_id].conflicts_total,
                            "reason_code": outcomes[module_id].reason_code,
                        }
                        for module_id in ordered
                    ),
                )
            result_commit = _git(stage_dir, "rev-parse", "HEAD").strip()
            _git(stage_dir, "push", "--force", "-q", "origin", f"HEAD:{ref}")
            return IntegrationRunOutcome(
                status="integrated",
                reason_code=None,
                result_commit=result_commit,
                gates=gates,
                evidence=evidence,
                items=tuple(
                    {
                        "module_id": module_id,
                        "status": outcomes[module_id].status,
                        "applied_verification_id": outcomes[module_id].applied_verification_id,
                        "conflicts": outcomes[module_id].conflicts,
                        "conflicts_total": outcomes[module_id].conflicts_total,
                        "reason_code": outcomes[module_id].reason_code,
                    }
                    for module_id in ordered
                ),
            )
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# worker: enqueue sweep + claim + run, off the Chat API background loop
# ---------------------------------------------------------------------------


class RoomBoardIntegrationWorker:
    """Enqueue changed input sets and run one integration job per tick.

    All blocking work (git, gates) runs in the caller's thread: the Chat API
    invokes :meth:`reconcile_once` via ``asyncio.to_thread``, never on the
    event loop, as a separate step after verification in the same loop.
    """

    def __init__(
        self,
        *,
        db_path: Path | str,
        clones_root: Path | str,
        xmuse_root: Path | str,
        execution_root: Path | str,
        execution_profile_id: str = "xmuse-monorepo/v2",
        worker_id: str = BOARD_INTEGRATION_WORKER_ID,
        lease_ttl_s: int = INTEGRATION_LEASE_TTL_S,
        max_attempts: int = MAX_INTEGRATION_ATTEMPTS,
        auto_retry_delays_s: Sequence[float] = AUTO_RETRY_DELAYS_S,
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("room_board_worker_id_required")
        self._engine = RoomBoardIntegrationEngine(
            db_path=db_path,
            clones_root=clones_root,
            xmuse_root=xmuse_root,
            execution_root=execution_root,
            execution_profile_id=execution_profile_id,
        )
        self._store = RoomBoardStore(db_path)
        self._worker_id = worker_id
        self._lease_ttl_s = lease_ttl_s
        self._max_attempts = max_attempts
        self._auto_retry_delays = tuple(auto_retry_delays_s)
        self._restart_retry_done = False

    def reconcile_once(self, *, now: datetime | None = None) -> dict[str, int]:
        """Enqueue changed sets, revive due retries, run one claimed job."""

        current_now = now or datetime.now(UTC)
        counts = {
            "board_integrations_enqueued": 0,
            "board_integrations_retried": 0,
            "board_integrations_claimed": 0,
            "board_integrations_integrated": 0,
            "board_integrations_conflicted": 0,
            "board_integrations_gate_failed": 0,
            "board_integrations_errored": 0,
            "board_integrations_abandoned": 0,
        }
        try:
            for conversation_id in self._store.rooms_with_board_charters():
                try:
                    if (
                        self._store.ensure_board_integration_enqueued(
                            conversation_id, now=current_now
                        )
                        is not None
                    ):
                        counts["board_integrations_enqueued"] += 1
                except Exception:
                    logger.exception("board integration enqueue failed")
            try:
                counts["board_integrations_retried"] += len(
                    self._store.revive_due_board_integrations(
                        now=current_now, delays_s=self._auto_retry_delays
                    )
                )
            except Exception:
                logger.exception("board integration retry failed")
            if not self._restart_retry_done:
                self._restart_retry_done = True
                try:
                    counts["board_integrations_retried"] += len(
                        self._store.revive_board_integrations_after_restart(
                            delays_s=self._auto_retry_delays
                        )
                    )
                except Exception:
                    logger.exception("board integration restart retry failed")
        except Exception:
            logger.exception("board integration sweep failed")
        claimed = self._store.claim_next_board_integration(
            worker_id=self._worker_id,
            lease_ttl_s=self._lease_ttl_s,
            max_attempts=self._max_attempts,
            now=current_now,
        )
        if claimed is None:
            return counts
        counts["board_integrations_claimed"] += 1
        integration_id = str(claimed["integration_id"])
        lease_token = str(claimed["lease_token"])
        try:
            outcome = self._engine.run_job(
                conversation_id=str(claimed["conversation_id"]),
                integration_id=integration_id,
                input_set=claimed["input_set"],
                items=claimed["items"],
            )
        except BoardIntegrationTransientError as exc:
            self._store.abandon_board_integration(
                integration_id=integration_id,
                lease_token=lease_token,
                reason_code=exc.code,
                now=current_now,
            )
            counts["board_integrations_abandoned"] += 1
            return counts
        result = self._store.complete_board_integration(
            integration_id=integration_id,
            lease_token=lease_token,
            status=outcome.status,
            reason_code=outcome.reason_code,
            green_after=(
                outcome.result_commit if outcome.status == "integrated" else claimed["green_before"]
            ),
            result_commit=outcome.result_commit,
            gates=[dict(item) for item in outcome.gates],
            evidence=dict(outcome.evidence),
            items=[dict(item) for item in outcome.items],
            now=current_now,
        )
        terminal = str(result["status"])
        if terminal == "integrated":
            counts["board_integrations_integrated"] += 1
        elif terminal == "conflicted":
            counts["board_integrations_conflicted"] += 1
        elif terminal == "gate_failed":
            counts["board_integrations_gate_failed"] += 1
        elif terminal == "error":
            counts["board_integrations_errored"] += 1
        return counts


__all__ = [
    "AUTO_RETRY_DELAYS_S",
    "BOARD_INTEGRATION_WORKER_ID",
    "BoardIntegrationTransientError",
    "IntegrationRunOutcome",
    "RoomBoardIntegrationEngine",
    "RoomBoardIntegrationWorker",
    "attribute_conflicts",
    "parse_apply_conflicts",
]
