from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.platform.closure_objects import (
    CLOSURE_CONTROLLER_FRESH,
    CLOSURE_OBJECT_EVALUATOR_VERSION,
    CONDITION_ORDER,
    DEFAULT_CLOSURE_CHAIN,
    INDEPENDENT_REVIEW_VERDICT_PRESENT,
    PATCH_FORWARD_LINEAGE_PRESENT,
    RECOVERY_ALLOWS_PROGRESS,
    RECOVERY_ARTIFACT_PRESENT,
    RELEASE_HANDOFF_EVALUATED,
    REQUIRED_FORBIDDEN_CLAIMS,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    SERVER_TRUTH_PENDING,
    VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    ClosureCondition,
    ClosureMetadata,
    ClosureObject,
    ClosureObservedState,
    ClosureSpec,
    ClosureStatus,
    dedupe_text,
    string_list,
)
from xmuse_core.platform.god_room_review_handoff import (
    build_review_closure_handoff_evaluation,
)
from xmuse_core.platform.local_execution_candidate import (
    build_local_execution_candidate_lineage,
    build_validated_execution_candidate_boundary,
)
from xmuse_core.platform.runner_session import load_runner_session_lineage

RECOVERY_PROOF_SCHEMA_VERSION = "xmuse.local_runner_recovery_proof.v1"
LANE_RECOVERY_SCHEMA_VERSION = "xmuse.god_room_lane_recovery.v1"
REVIEW_CHAIN_PROOF_SCHEMA_VERSION = "xmuse.god_room_lane_review_chain_proof.v1"
RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION = "xmuse.release_evidence_candidates.v1"


def reconcile_closure(
    *,
    root: str | Path,
    graph_id: str,
    lane_id: str,
    name: str | None = None,
    generation: int = 1,
    previous_closure: ClosureObject | Mapping[str, Any] | str | Path | None = None,
    observed: ClosureObservedState | None = None,
    recovery_artifact: Mapping[str, Any] | str | Path | None = None,
    execution_candidates: Sequence[Mapping[str, Any] | str | Path] = (),
    review_closure: Mapping[str, Any] | str | Path | None = None,
    release_handoff: Mapping[str, Any] | str | Path | None = None,
) -> ClosureObject:
    """Reconcile current Wave D/E artifacts into a machine-readable closure object.

    This function is intentionally side-effect free. It reads the supplied
    artifacts, emits conditions, and preserves proof gaps. It does not create a
    queue, service, database record, or release truth.
    """

    xmuse_root = Path(root)
    current = observed or _observed_state(
        root=xmuse_root,
        recovery_artifact=recovery_artifact,
        execution_candidates=execution_candidates,
        review_closure=review_closure,
        release_handoff=release_handoff,
    )
    previous, previous_error = _load_previous_closure(previous_closure)
    controller_fresh = _closure_controller_fresh(
        previous,
        previous_error=previous_error,
        generation=generation,
    )

    recovery_present = _recovery_artifact_present(current.recovery_artifact)
    recovery_allows_progress = _recovery_allows_progress(
        current.recovery_artifact,
        lane_id=lane_id,
    )
    candidate_present = _validated_execution_candidate_present(
        current.execution_candidates,
        root=xmuse_root,
        refs=current.execution_candidate_refs,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    review_present = _independent_review_verdict_present(
        root=xmuse_root,
        review_closure=current.review_closure,
    )
    patch_forward_present = _patch_forward_lineage_present(
        release_handoff=current.release_handoff,
    )
    release_evaluated = _release_handoff_evaluated(
        current.release_handoff,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    forbidden_claims = _forbidden_claims(
        current.recovery_artifact,
        *current.execution_candidates,
        current.review_closure,
        current.release_handoff,
    )
    required_forbidden_claims_present = _required_forbidden_claims_present(
        review_closure=current.review_closure,
        release_handoff=current.release_handoff,
    )
    server_pending = _server_truth_pending(
        review_closure=current.review_closure,
        release_handoff=current.release_handoff,
    )

    conditions = (
        controller_fresh.with_observed_ref(None, generation),
        recovery_present.with_observed_ref(current.recovery_artifact_ref, generation),
        recovery_allows_progress.with_observed_ref(
            current.recovery_artifact_ref,
            generation,
        ),
        _with_observed_generation(candidate_present, generation),
        review_present.with_observed_ref(current.review_closure_ref, generation),
        patch_forward_present.with_observed_ref(current.release_handoff_ref, generation),
        release_evaluated.with_observed_ref(current.release_handoff_ref, generation),
        required_forbidden_claims_present.with_observed_ref(None, generation),
        _with_observed_generation(server_pending, generation),
    )
    manual_gaps = _condition_gaps(conditions)
    blocked_reasons = tuple(
        condition.reason for condition in conditions if condition.severity == "blocked"
    )
    observed_refs = dedupe_text(
        (
            current.recovery_artifact_ref,
            *current.execution_candidate_refs,
            current.review_closure_ref,
            current.release_handoff_ref,
        )
    )
    source_refs = _source_refs(
        current.recovery_artifact,
        *current.execution_candidates,
        current.review_closure,
        current.release_handoff,
    )
    target_refs = dedupe_text(
        (
            f"graph:{graph_id}",
            f"lane:{lane_id}",
            *_target_refs(
                current.recovery_artifact,
                *current.execution_candidates,
                current.review_closure,
                current.release_handoff,
            ),
        )
    )
    owner_refs = _owner_refs(
        current.recovery_artifact,
        *current.execution_candidates,
        current.review_closure,
        current.release_handoff,
    )
    phase = _phase(conditions)
    metadata = ClosureMetadata(
        name=name or f"closure:{graph_id}:{lane_id}",
        layer="WaveD-E/L8-L10",
        chain=DEFAULT_CLOSURE_CHAIN,
        source_refs=source_refs,
        target_refs=target_refs,
        owner_refs=owner_refs,
        generation=generation,
    )
    spec = ClosureSpec(
        desired_conditions=CONDITION_ORDER,
        proof_level="contract_proof",
        required_forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
    )
    status = ClosureStatus(
        phase=phase,
        proof_level="contract_proof",
        conditions=conditions,
        observed_refs=observed_refs,
        observed_generation=generation,
        manual_gaps=manual_gaps,
        forbidden_claims=forbidden_claims,
        blocked_reasons=blocked_reasons,
    )
    return ClosureObject(metadata=metadata, spec=spec, status=status)


def capture_closure_object(
    *,
    root: str | Path,
    graph_id: str,
    lane_id: str,
    output_path: str | Path,
    name: str | None = None,
    generation: int = 1,
    previous_closure: ClosureObject | Mapping[str, Any] | str | Path | None = None,
    recovery_artifact: Mapping[str, Any] | str | Path | None = None,
    execution_candidates: Sequence[Mapping[str, Any] | str | Path] = (),
    review_closure: Mapping[str, Any] | str | Path | None = None,
    release_handoff: Mapping[str, Any] | str | Path | None = None,
) -> ClosureObject:
    """Write a ClosureObject artifact from explicit observed inputs."""

    closure = reconcile_closure(
        root=root,
        graph_id=graph_id,
        lane_id=lane_id,
        name=name,
        generation=generation,
        previous_closure=previous_closure,
        recovery_artifact=recovery_artifact,
        execution_candidates=execution_candidates,
        review_closure=review_closure,
        release_handoff=release_handoff,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(closure.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return closure


def load_closure_observed_state(
    *,
    root: str | Path,
    recovery_artifact: str | Path | None = None,
    execution_candidates: Sequence[str | Path] = (),
    review_closure: str | Path | None = None,
    release_handoff: str | Path | None = None,
) -> ClosureObservedState:
    return _observed_state(
        root=Path(root),
        recovery_artifact=recovery_artifact,
        execution_candidates=execution_candidates,
        review_closure=review_closure,
        release_handoff=release_handoff,
    )


def _observed_state(
    *,
    root: Path,
    recovery_artifact: Mapping[str, Any] | str | Path | None,
    execution_candidates: Sequence[Mapping[str, Any] | str | Path],
    review_closure: Mapping[str, Any] | str | Path | None,
    release_handoff: Mapping[str, Any] | str | Path | None,
) -> ClosureObservedState:
    recovery_payload, recovery_ref = _load_payload(root, recovery_artifact)
    candidate_payloads: list[Mapping[str, Any]] = []
    candidate_refs: list[str] = []
    for candidate in execution_candidates:
        payload, ref = _load_payload(root, candidate)
        if payload is None:
            continue
        candidate_payloads.append(payload)
        if ref is not None:
            candidate_refs.append(ref)
    review_payload, review_ref = _load_payload(root, review_closure)
    release_payload, release_ref = _load_payload(root, release_handoff)
    return ClosureObservedState(
        recovery_artifact=recovery_payload,
        recovery_artifact_ref=recovery_ref,
        execution_candidates=tuple(candidate_payloads),
        execution_candidate_refs=tuple(candidate_refs),
        review_closure=review_payload,
        review_closure_ref=review_ref,
        release_handoff=release_payload,
        release_handoff_ref=release_ref,
    )


def _load_previous_closure(
    previous_closure: ClosureObject | Mapping[str, Any] | str | Path | None,
) -> tuple[ClosureObject | None, str | None]:
    if previous_closure is None:
        return None, None
    if isinstance(previous_closure, ClosureObject):
        return previous_closure, None
    payload: Mapping[str, Any] | None
    if isinstance(previous_closure, Mapping):
        payload = previous_closure
    else:
        path = Path(previous_closure)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"previous closure object could not be read: {exc}"
        if not isinstance(raw, Mapping):
            return None, "previous closure object must be a JSON object"
        payload = raw
    try:
        return ClosureObject.from_dict(payload), None
    except ValueError as exc:
        return None, f"previous closure object is invalid: {exc}"


def _load_payload(
    root: Path,
    artifact: Mapping[str, Any] | str | Path | None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    if artifact is None:
        return None, None
    if isinstance(artifact, Mapping):
        return artifact, None
    path = _artifact_path(root, artifact)
    if path is None or not path.is_file():
        return None, _artifact_ref(root, artifact)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, _artifact_ref(root, artifact)
    if not isinstance(payload, Mapping):
        return None, _artifact_ref(root, artifact)
    return payload, _artifact_ref(root, artifact)


def _artifact_path(root: Path, artifact: str | Path) -> Path | None:
    value = str(artifact).strip()
    if not value or "://" in value:
        return None
    for prefix in (
        "recovery_artifact:",
        "execution_artifact:",
        "candidate_artifact:",
        "review_closure_artifact:",
        "review_chain_proof_artifact:",
        "release_handoff_artifact:",
        "artifact:",
    ):
        if value.startswith(prefix):
            value = value.removeprefix(prefix).strip()
            break
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _artifact_ref(root: Path, artifact: str | Path) -> str:
    path = _artifact_path(root, artifact)
    if path is None:
        return str(artifact)
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(artifact)


@dataclass(frozen=True)
class _ConditionBuilder:
    type: str
    status: str
    severity: str
    reason: str
    proof_level: str = "contract_proof"
    source_refs: tuple[str, ...] = ()
    target_refs: tuple[str, ...] = ()

    def with_observed_ref(
        self,
        observed_ref: str | None,
        observed_generation: int | None = None,
    ) -> ClosureCondition:
        return ClosureCondition(
            type=self.type,
            status=self.status,  # type: ignore[arg-type]
            severity=self.severity,  # type: ignore[arg-type]
            reason=self.reason,
            proof_level=self.proof_level,
            source_refs=self.source_refs,
            target_refs=self.target_refs,
            observed_ref=observed_ref,
            observed_generation=observed_generation,
        )

def _condition(
    condition_type: str,
    status: str,
    severity: str,
    reason: str,
    *,
    proof_level: str = "contract_proof",
    source_refs: Sequence[object] = (),
    target_refs: Sequence[object] = (),
) -> _ConditionBuilder:
    return _ConditionBuilder(
        type=condition_type,
        status=status,
        severity=severity,
        reason=reason,
        proof_level=proof_level,
        source_refs=dedupe_text(source_refs),
        target_refs=dedupe_text(target_refs),
    )


def _closure_controller_fresh(
    previous_closure: ClosureObject | None,
    *,
    previous_error: str | None,
    generation: int,
) -> _ConditionBuilder:
    if previous_error is not None:
        return _condition(
            CLOSURE_CONTROLLER_FRESH,
            "unknown",
            "manual_gap",
            previous_error,
        )
    if previous_closure is None:
        return _condition(
            CLOSURE_CONTROLLER_FRESH,
            "true",
            "ok",
            "no previous closure object supplied",
        )
    evaluator_version = previous_closure.status.evaluator_version
    if evaluator_version != CLOSURE_OBJECT_EVALUATOR_VERSION:
        return _condition(
            CLOSURE_CONTROLLER_FRESH,
            "false",
            "blocked",
            (
                "previous closure object evaluator_version is stale: "
                f"{evaluator_version}"
            ),
        )
    previous_generation = max(
        previous_closure.metadata.generation,
        previous_closure.status.observed_generation,
    )
    if generation < previous_generation:
        return _condition(
            CLOSURE_CONTROLLER_FRESH,
            "false",
            "blocked",
            (
                "closure generation regressed from "
                f"{previous_generation} to {generation}"
            ),
        )
    if generation > previous_generation + 1:
        return _condition(
            CLOSURE_CONTROLLER_FRESH,
            "unknown",
            "manual_gap",
            (
                "closure generation skipped from "
                f"{previous_generation} to {generation}"
            ),
        )
    return _condition(
        CLOSURE_CONTROLLER_FRESH,
        "true",
        "ok",
        f"closure generation {generation} is fresh",
    )


def _recovery_artifact_present(
    recovery_artifact: Mapping[str, Any] | None,
) -> _ConditionBuilder:
    if recovery_artifact is None:
        return _condition(
            RECOVERY_ARTIFACT_PRESENT,
            "false",
            "manual_gap",
            "runner recovery artifact is missing",
        )
    schema_version = _text(recovery_artifact.get("schema_version"))
    if schema_version not in {RECOVERY_PROOF_SCHEMA_VERSION, LANE_RECOVERY_SCHEMA_VERSION}:
        return _condition(
            RECOVERY_ARTIFACT_PRESENT,
            "false",
            "blocked",
            "runner recovery artifact schema is unsupported",
        )
    if _text(recovery_artifact.get("source_authority")) is None:
        return _condition(
            RECOVERY_ARTIFACT_PRESENT,
            "false",
            "manual_gap",
            "runner recovery artifact missing source authority",
        )
    return _condition(
        RECOVERY_ARTIFACT_PRESENT,
        "true",
        "ok",
        "runner recovery artifact is present",
        proof_level=_proof_level(recovery_artifact),
        source_refs=string_list(recovery_artifact.get("source_refs")),
        target_refs=string_list(recovery_artifact.get("target_refs")),
    )


def _recovery_allows_progress(
    recovery_artifact: Mapping[str, Any] | None,
    *,
    lane_id: str,
) -> _ConditionBuilder:
    if recovery_artifact is None:
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "unknown",
            "manual_gap",
            "recovery decision is unavailable",
        )
    schema_version = _text(recovery_artifact.get("schema_version"))
    if schema_version not in {RECOVERY_PROOF_SCHEMA_VERSION, LANE_RECOVERY_SCHEMA_VERSION}:
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "false",
            "blocked",
            "unsupported recovery artifact cannot allow progress",
        )
    if schema_version == LANE_RECOVERY_SCHEMA_VERSION:
        return _lane_recovery_allows_progress(
            recovery_artifact,
            lane_id=lane_id,
        )
    candidate_selection = recovery_artifact.get("candidate_selection")
    if not isinstance(candidate_selection, Mapping):
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "unknown",
            "manual_gap",
            "recovery artifact missing candidate selection",
        )
    blocked_lane_ids = {
        *string_list(candidate_selection.get("excluded_recovery_blocked_lane_ids")),
        *string_list(candidate_selection.get("invalid_recovery_artifact_lane_ids")),
    }
    if lane_id in blocked_lane_ids:
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "false",
            "blocked",
            f"lane {lane_id} is blocked by durable recovery artifact",
            proof_level=_proof_level(recovery_artifact),
            source_refs=string_list(recovery_artifact.get("source_refs")),
            target_refs=(f"lane:{lane_id}",),
        )
    return _condition(
        RECOVERY_ALLOWS_PROGRESS,
        "true",
        "ok",
        f"lane {lane_id} is not blocked by observed recovery artifact",
        proof_level=_proof_level(recovery_artifact),
        source_refs=string_list(recovery_artifact.get("source_refs")),
        target_refs=(f"lane:{lane_id}",),
    )


def _lane_recovery_allows_progress(
    recovery_artifact: Mapping[str, Any],
    *,
    lane_id: str,
) -> _ConditionBuilder:
    decision = _mapping(recovery_artifact.get("decision"))
    if not decision:
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "unknown",
            "manual_gap",
            "lane recovery artifact missing decision",
        )
    if _text(decision.get("lane_id")) not in {None, lane_id}:
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "false",
            "blocked",
            "lane recovery artifact decision lane does not match target lane",
        )
    retry_allowed = decision.get("retry_allowed")
    if retry_allowed is not True:
        reason = _text(decision.get("decision")) or "retry_not_allowed"
        return _condition(
            RECOVERY_ALLOWS_PROGRESS,
            "false",
            "blocked",
            f"lane {lane_id} is blocked by durable recovery artifact: {reason}",
            proof_level=_proof_level(recovery_artifact),
            source_refs=string_list(recovery_artifact.get("source_refs"))
            or string_list(decision.get("source_refs")),
            target_refs=(f"lane:{lane_id}",),
        )
    return _condition(
        RECOVERY_ALLOWS_PROGRESS,
        "true",
        "ok",
        f"lane {lane_id} retry is allowed by durable recovery artifact",
        proof_level=_proof_level(recovery_artifact),
        source_refs=string_list(recovery_artifact.get("source_refs"))
        or string_list(decision.get("source_refs")),
        target_refs=(f"lane:{lane_id}",),
    )


def _validated_execution_candidate_present(
    candidates: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    refs: Sequence[str],
    graph_id: str,
    lane_id: str,
) -> ClosureCondition:
    issues: list[str] = []
    for index, artifact in enumerate(candidates):
        artifact_ref = refs[index] if index < len(refs) else f"candidate:{index}"
        try:
            lineage = build_local_execution_candidate_lineage(
                artifact=artifact,
                artifact_ref=artifact_ref,
                lane_id=lane_id,
                graph_id=graph_id,
            )
        except ValueError as exc:
            issues.append(str(exc))
            continue
        runner_session_lineage: Mapping[str, Any] | None = None
        runner_session_ref = _text(lineage.get("runner_session_ref"))
        if runner_session_ref is not None:
            try:
                runner_session_lineage = load_runner_session_lineage(
                    root=root,
                    artifact_ref=runner_session_ref,
                    session_id=_text(lineage.get("runner_session_id")),
                    run_id=_text(lineage.get("run_id")),
                    runner_id=_text(lineage.get("worker_id")),
                    candidate_artifact_ref=artifact_ref,
                    graph_id=graph_id,
                )
            except (FileNotFoundError, ValueError) as exc:
                issues.append(str(exc))
        boundary = build_validated_execution_candidate_boundary(
            candidate_lineage=lineage,
            runner_session_lineage=runner_session_lineage,
            graph_id=graph_id,
            lane_id=lane_id,
        )
        if boundary["status"] != "validated":
            issues.extend(string_list(boundary.get("issues")))
            continue
        return ClosureCondition(
            type=VALIDATED_EXECUTION_CANDIDATE_PRESENT,
            status="true",
            severity="ok",
            reason="bounded local execution candidate is present",
            proof_level=_proof_level(boundary),
            source_refs=string_list(boundary.get("worker_evidence_bundle_refs"))
            or string_list(lineage.get("source_refs")),
            target_refs=(f"graph:{graph_id}", f"lane:{lane_id}"),
            observed_ref=artifact_ref,
        )
    if candidates and issues:
        return ClosureCondition(
            type=VALIDATED_EXECUTION_CANDIDATE_PRESENT,
            status="false",
            severity="manual_gap",
            reason="; ".join(dedupe_text(issues)),
            observed_ref=None,
        )
    return ClosureCondition(
        type=VALIDATED_EXECUTION_CANDIDATE_PRESENT,
        status="false",
        severity="manual_gap",
        reason="validated local execution candidate is missing",
        observed_ref=None,
    )


def _independent_review_verdict_present(
    *,
    root: Path,
    review_closure: Mapping[str, Any] | None,
) -> _ConditionBuilder:
    if review_closure is None:
        return _condition(
            INDEPENDENT_REVIEW_VERDICT_PRESENT,
            "false",
            "manual_gap",
            "review closure artifact is missing",
        )
    evaluation = build_review_closure_handoff_evaluation(
        root=root,
        review_closure=review_closure,
    )
    status = _text(evaluation.get("status"))
    if status == "ready":
        return _condition(
            INDEPENDENT_REVIEW_VERDICT_PRESENT,
            "true",
            "ok",
            "review closure has independent verdict and candidate citation",
            proof_level="contract_proof",
            source_refs=string_list(evaluation.get("candidate_artifact_refs")),
            target_refs=(
                f"graph:{_text(evaluation.get('graph_id'))}",
                f"lane:{_text(evaluation.get('lane_id'))}",
            ),
        )
    severity = "blocked" if status == "blocked" else "manual_gap"
    return _condition(
        INDEPENDENT_REVIEW_VERDICT_PRESENT,
        "false",
        severity,
        "; ".join(string_list(evaluation.get("issues")))
        or "review closure handoff is not ready",
        proof_level="contract_proof",
        source_refs=string_list(evaluation.get("candidate_artifact_refs")),
        target_refs=(
            f"graph:{_text(evaluation.get('graph_id'))}",
            f"lane:{_text(evaluation.get('lane_id'))}",
        ),
    )


def _release_handoff_evaluated(
    release_handoff: Mapping[str, Any] | None,
    *,
    graph_id: str,
    lane_id: str,
) -> _ConditionBuilder:
    if release_handoff is None:
        return _condition(
            RELEASE_HANDOFF_EVALUATED,
            "false",
            "manual_gap",
            "release handoff artifact/report is missing",
        )
    schema_version = _text(release_handoff.get("schema_version"))
    if schema_version not in {
        REVIEW_CHAIN_PROOF_SCHEMA_VERSION,
        RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION,
        "xmuse.review_closure_handoff_evaluation.v1",
    }:
        return _condition(
            RELEASE_HANDOFF_EVALUATED,
            "false",
            "blocked",
            "release handoff schema is unsupported",
        )
    if schema_version == REVIEW_CHAIN_PROOF_SCHEMA_VERSION:
        if _text(release_handoff.get("status")) != "chain_ready":
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff status is not chain_ready",
            )
        if _text(release_handoff.get("proof_level")) != "contract_proof":
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff proof level is not contract_proof",
            )
        actual_graph_id = _text(release_handoff.get("graph_id"))
        if actual_graph_id is None:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff graph_id is missing",
            )
        if actual_graph_id != graph_id:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff graph_id does not match current closure graph",
            )
        terminal_lane = _text(release_handoff.get("terminal_lane_id"))
        if terminal_lane is None:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff terminal_lane_id is missing",
            )
        if terminal_lane != lane_id:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "release handoff terminal lane id does not match current closure lane",
            )
    if schema_version == "xmuse.review_closure_handoff_evaluation.v1":
        if _text(release_handoff.get("status")) != "ready":
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "review-closure handoff status is not ready",
            )
        actual_graph_id = _text(release_handoff.get("graph_id"))
        if actual_graph_id is None:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "review-closure handoff graph_id is missing",
            )
        if actual_graph_id != graph_id:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "review-closure handoff graph_id does not match current closure graph",
            )
        handoff_lane_id = _text(release_handoff.get("lane_id"))
        if handoff_lane_id is None:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "review-closure handoff lane_id is missing",
            )
        if handoff_lane_id != lane_id:
            return _condition(
                RELEASE_HANDOFF_EVALUATED,
                "false",
                "manual_gap",
                "review-closure handoff lane_id does not match current closure lane",
            )
    if _text(release_handoff.get("server_truth_status")) not in {None, "not_server_truth"}:
        return _condition(
            RELEASE_HANDOFF_EVALUATED,
            "false",
            "blocked",
            "release handoff overclaims server truth",
        )
    source_refs = dedupe_text(
        (
            *string_list(release_handoff.get("source_refs")),
            *string_list(release_handoff.get("candidate_artifact_refs")),
            *string_list(release_handoff.get("review_closure_candidate_artifact_refs")),
        )
    )
    if not source_refs:
        return _condition(
            RELEASE_HANDOFF_EVALUATED,
            "false",
            "manual_gap",
            "release handoff is missing source refs",
        )
    return _condition(
        RELEASE_HANDOFF_EVALUATED,
        "true",
        "ok",
        "release handoff has been evaluated without server-truth overclaim",
        proof_level="contract_proof",
        source_refs=source_refs,
        target_refs=string_list(release_handoff.get("target_refs")),
    )


def _patch_forward_lineage_present(
    *,
    release_handoff: Mapping[str, Any] | None,
) -> _ConditionBuilder:
    if release_handoff is None:
        return _condition(
            PATCH_FORWARD_LINEAGE_PRESENT,
            "false",
            "manual_gap",
            "review-chain proof with patch-forward lineage is missing",
        )
    schema_version = _text(release_handoff.get("schema_version"))
    if schema_version != REVIEW_CHAIN_PROOF_SCHEMA_VERSION:
        return _condition(
            PATCH_FORWARD_LINEAGE_PRESENT,
            "false",
            "manual_gap",
            "patch-forward lineage requires review-chain proof artifact",
        )
    issues: list[str] = []
    if _text(release_handoff.get("status")) != "chain_ready":
        issues.append("review-chain proof is not chain_ready")
    if _text(release_handoff.get("proof_level")) != "contract_proof":
        issues.append("review-chain proof proof level is not contract_proof")
    if _text(release_handoff.get("server_truth_status")) != "not_server_truth":
        issues.append("review-chain proof overclaims server truth")
    session = _mapping(release_handoff.get("local_execution_review_session"))
    if not session:
        issues.append("review-chain proof missing local execution review session")
    elif _text(session.get("status")) != "bounded_session_ready":
        issues.append("local execution review session is not bounded_session_ready")
    patch_boundary = _mapping(session.get("patch_forward_artifact_boundary"))
    patch_boundary_status = _text(patch_boundary.get("status"))
    if patch_boundary_status not in {
        "resolved",
        "resolved_with_retained_manual_gaps",
    }:
        issues.append("patch-forward artifact boundary is not resolved")
    artifact_validation = _mapping(session.get("session_artifact_validation"))
    if _text(artifact_validation.get("status")) != "validated":
        issues.append("session artifact validation is not validated")
    required_refs = (
        "patch_forward_artifact",
        "patch_lane_review_intake_artifact",
        "patch_lane_review_verdict_artifact",
    )
    missing_refs = [key for key in required_refs if _text(session.get(key)) is None]
    if missing_refs:
        issues.append(
            "review-chain proof missing patch-forward refs: "
            + ", ".join(missing_refs)
        )
    if issues:
        return _condition(
            PATCH_FORWARD_LINEAGE_PRESENT,
            "false",
            "manual_gap",
            "; ".join(dedupe_text(issues)),
        )
    source_refs = dedupe_text(
        (
            _text(release_handoff.get("review_closure_artifact")),
            _text(session.get("patch_forward_artifact")),
            _text(session.get("patch_lane_review_intake_artifact")),
            _text(session.get("patch_lane_review_verdict_artifact")),
            *string_list(session.get("candidate_artifact_refs")),
            *string_list(session.get("session_source_refs")),
        )
    )
    return _condition(
        PATCH_FORWARD_LINEAGE_PRESENT,
        "true",
        "ok",
        "review-chain proof carries bounded patch-forward lineage",
        proof_level="contract_proof",
        source_refs=source_refs,
        target_refs=(
            f"graph:{_text(release_handoff.get('graph_id'))}",
            f"lane:{_text(release_handoff.get('terminal_lane_id'))}",
        ),
    )


def _server_truth_pending(
    *,
    review_closure: Mapping[str, Any] | None,
    release_handoff: Mapping[str, Any] | None,
) -> ClosureCondition:
    server_truth_values = [
        _text((review_closure or {}).get("server_truth_status")),
        _text((release_handoff or {}).get("server_truth_status")),
    ]
    overclaims = [
        value for value in server_truth_values if value not in {None, "not_server_truth"}
    ]
    if overclaims:
        return ClosureCondition(
            type=SERVER_TRUTH_PENDING,
            status="false",
            severity="blocked",
            reason="server truth was claimed without server-side proof",
            proof_level="contract_proof",
            observed_ref=None,
        )
    return ClosureCondition(
        type=SERVER_TRUTH_PENDING,
        status="true",
        severity="ok",
        reason="server truth remains pending; no live/server proof is claimed",
        proof_level="contract_proof",
        observed_ref=None,
    )


def _required_forbidden_claims_present(
    *,
    review_closure: Mapping[str, Any] | None,
    release_handoff: Mapping[str, Any] | None,
) -> _ConditionBuilder:
    missing_by_artifact: list[str] = []
    for artifact_name, artifact in (
        ("review_closure", review_closure),
        ("release_handoff", release_handoff),
    ):
        if artifact is None:
            continue
        if not _requires_closure_forbidden_claims(artifact):
            continue
        claims = set(string_list(artifact.get("forbidden_claims")))
        missing = [claim for claim in REQUIRED_FORBIDDEN_CLAIMS if claim not in claims]
        if missing:
            missing_by_artifact.append(
                f"{artifact_name} missing forbidden claims: {', '.join(missing)}"
            )
    if missing_by_artifact:
        return _condition(
            REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
            "false",
            "manual_gap",
            "; ".join(missing_by_artifact),
        )
    return _condition(
        REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
        "true",
        "ok",
        "closure-level forbidden claims are preserved by observed handoff artifacts",
    )


def _requires_closure_forbidden_claims(artifact: Mapping[str, Any] | None) -> bool:
    if artifact is None:
        return False
    return _text(artifact.get("schema_version")) in {
        "xmuse.god_room_lane_review_closure.v1",
        "xmuse.review_closure_handoff_evaluation.v1",
        REVIEW_CHAIN_PROOF_SCHEMA_VERSION,
        RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION,
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _with_observed_generation(
    condition: ClosureCondition,
    observed_generation: int | None,
) -> ClosureCondition:
    return ClosureCondition(
        type=condition.type,
        status=condition.status,
        severity=condition.severity,
        reason=condition.reason,
        proof_level=condition.proof_level,
        source_refs=condition.source_refs,
        target_refs=condition.target_refs,
        observed_ref=condition.observed_ref,
        observed_generation=observed_generation,
    )


def _phase(conditions: Sequence[ClosureCondition]) -> str:
    if any(condition.severity == "blocked" for condition in conditions):
        return "blocked"
    if any(condition.severity == "manual_gap" for condition in conditions):
        return "manual_gap"
    return "release_handoff_evaluated"


def _condition_gaps(conditions: Sequence[ClosureCondition]) -> tuple[str, ...]:
    return dedupe_text(
        [
            condition.reason
            for condition in conditions
            if condition.severity == "manual_gap"
        ]
    )


def _forbidden_claims(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    claims: list[object] = [*REQUIRED_FORBIDDEN_CLAIMS]
    for artifact in artifacts:
        if artifact is None:
            continue
        claims.extend(string_list(artifact.get("forbidden_claims")))
    return dedupe_text(claims)


def _source_refs(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    refs: list[object] = []
    for artifact in artifacts:
        if artifact is None:
            continue
        refs.extend(string_list(artifact.get("source_refs")))
        refs.extend(string_list(artifact.get("candidate_artifact_refs")))
        refs.extend(string_list(artifact.get("cited_candidate_artifact_refs")))
    return dedupe_text(refs)


def _target_refs(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    refs: list[object] = []
    for artifact in artifacts:
        if artifact is None:
            continue
        refs.extend(string_list(artifact.get("target_refs")))
        for key in ("graph_id", "feature_graph_id"):
            if value := _text(artifact.get(key)):
                refs.append(f"graph:{value}")
        for key in ("lane_id", "failed_lane_id", "terminal_lane_id"):
            if value := _text(artifact.get(key)):
                refs.append(f"lane:{value}")
    return dedupe_text(refs)


def _owner_refs(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    refs: list[object] = []
    for artifact in artifacts:
        if artifact is None:
            continue
        for key in (
            "source_authority",
            "producer",
            "graph_status_source_authority",
            "review_truth_status",
            "execution_truth_status",
        ):
            if value := _text(artifact.get(key)):
                refs.append(f"{key}:{value}")
    return dedupe_text(refs)


def _proof_level(artifact: Mapping[str, Any]) -> str:
    return _text(artifact.get("proof_level")) or "contract_proof"


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None
