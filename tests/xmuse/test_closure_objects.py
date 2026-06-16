from xmuse_core.platform.closure_objects import (
    CLOSURE_CONTROLLER_FRESH,
    CLOSURE_OBJECT_EVALUATOR_VERSION,
    CONDITION_ORDER,
    DEFAULT_CLOSURE_CHAIN,
    RELEASE_HANDOFF_EVALUATED,
    REQUIRED_FORBIDDEN_CLAIMS,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    SERVER_TRUTH_PENDING,
    ClosureCondition,
    ClosureMetadata,
    ClosureObject,
    ClosureSpec,
    ClosureStatus,
    closure_condition_by_type,
    dedupe_text,
    evaluate_closure_object_l10_admission,
)


def test_closure_object_serializes_metadata_spec_status_contract() -> None:
    condition = ClosureCondition(
        type=SERVER_TRUTH_PENDING,
        status="true",
        severity="ok",
        reason="server truth remains pending",
    )
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("candidate:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure_reconciler",),
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=(condition,),
            manual_gaps=("review closure artifact is missing",),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    payload = closure.to_dict()

    assert payload["apiVersion"] == "xmuse.io/v1"
    assert payload["kind"] == "ClosureObject"
    assert payload["metadata"]["chain"] == list(DEFAULT_CLOSURE_CHAIN)
    assert payload["metadata"]["generation"] == 1
    assert payload["spec"]["desired_conditions"] == list(CONDITION_ORDER)
    assert payload["spec"]["proof_level"] == "contract_proof"
    assert payload["status"]["observed_generation"] == 1
    assert payload["status"]["evaluator_version"] == CLOSURE_OBJECT_EVALUATOR_VERSION
    assert payload["status"]["conditions"][0]["type"] == SERVER_TRUTH_PENDING
    assert payload["status"]["conditions"][0]["observed_generation"] is None
    assert payload["status"]["forbidden_claims"] == list(REQUIRED_FORBIDDEN_CLAIMS)
    assert closure_condition_by_type(closure, SERVER_TRUTH_PENDING) == condition


def test_closure_object_round_trips_from_serialized_contract() -> None:
    condition = ClosureCondition(
        type=CLOSURE_CONTROLLER_FRESH,
        status="true",
        severity="ok",
        reason="closure generation 2 is fresh",
        observed_generation=2,
    )
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("candidate:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure_reconciler",),
            generation=2,
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=(condition,),
            observed_generation=2,
            manual_gaps=("review closure artifact is missing",),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    parsed = ClosureObject.from_dict(closure.to_dict())

    assert parsed == closure
    assert closure_condition_by_type(parsed, CLOSURE_CONTROLLER_FRESH) == condition


def test_dedupe_text_preserves_first_seen_order_and_drops_empty_values() -> None:
    assert dedupe_text([" lane:a ", "", "lane:a", None, "lane:b"]) == (
        "lane:a",
        "lane:b",
    )


def _admission_condition(condition_type: str) -> ClosureCondition:
    if condition_type in {
        CLOSURE_CONTROLLER_FRESH,
        REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
        SERVER_TRUTH_PENDING,
    }:
        return ClosureCondition(
            type=condition_type,
            status="true",
            severity="ok",
            reason=f"{condition_type} is satisfied",
        )
    if condition_type == RELEASE_HANDOFF_EVALUATED:
        return ClosureCondition(
            type=condition_type,
            status="true",
            severity="ok",
            reason="release handoff was evaluated",
        )
    return ClosureCondition(
        type=condition_type,
        status="false",
        severity="manual_gap",
        reason=f"{condition_type} remains a manual gap",
    )


def test_closure_object_l10_admission_accepts_fresh_forbidden_boundary() -> None:
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("handoff:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure-controller",),
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=tuple(
                _admission_condition(condition_type)
                for condition_type in CONDITION_ORDER
            ),
            observed_refs=("candidate:a", "handoff:a"),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    admission = evaluate_closure_object_l10_admission(closure)

    assert admission.gate_ready is True
    assert admission.summary == "ClosureObject can seed MemoryOS source refs."
    assert admission.phase == "manual_gap"
    assert admission.source_refs == ("handoff:a", "candidate:a")
    assert admission.source_ref_count == 2
    assert admission.target_refs == ("lane:lane-a",)
    assert admission.target_ref_count == 1
    assert admission.owner_refs == ("source_authority:closure-controller",)
    assert admission.owner_ref_count == 1
    assert admission.forbidden_claim_count == len(REQUIRED_FORBIDDEN_CLAIMS)


def test_closure_object_l10_admission_rejects_stale_or_weakened_boundary() -> None:
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("handoff:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure-controller",),
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=(
                ClosureCondition(
                    type=CLOSURE_CONTROLLER_FRESH,
                    status="false",
                    severity="blocked",
                    reason="closure evaluator is stale",
                ),
                ClosureCondition(
                    type=REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
                    status="false",
                    severity="manual_gap",
                    reason="required forbidden claims are missing",
                ),
                ClosureCondition(
                    type=SERVER_TRUTH_PENDING,
                    status="true",
                    severity="ok",
                    reason="server truth remains pending",
                ),
            ),
            evaluator_version="xmuse.closure_controller.v0",
            forbidden_claims=("live_memoryos",),
        ),
    )

    admission = evaluate_closure_object_l10_admission(closure)

    assert admission.gate_ready is False
    assert admission.source_refs == ()
    assert admission.source_ref_count == 0
    assert admission.target_refs == ()
    assert admission.target_ref_count == 0
    assert admission.owner_refs == ()
    assert admission.owner_ref_count == 0
    assert admission.forbidden_claim_count == 1
    assert admission.issues == (
        (
            "ClosureObject status missing desired conditions: "
            "RecoveryArtifactPresent, RecoveryAllowsProgress, "
            "ValidatedExecutionCandidatePresent, IndependentReviewVerdictPresent, "
            "PatchForwardLineagePresent, ReleaseHandoffEvaluated"
        ),
        "ClosureObject evaluator_version is stale",
        "ClosureObject controller freshness is not ok",
        "ClosureObject required forbidden claims are not preserved",
        (
            "ClosureObject missing forbidden claims: github_review_truth, "
            "ready_to_merge, pr_merged, worker_output_is_review_truth"
        ),
    )


def test_closure_object_l10_admission_requires_complete_condition_chain() -> None:
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("handoff:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure-controller",),
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=(
                _admission_condition(CLOSURE_CONTROLLER_FRESH),
                _admission_condition(REQUIRED_FORBIDDEN_CLAIMS_PRESENT),
                _admission_condition(SERVER_TRUTH_PENDING),
            ),
            observed_refs=("candidate:a", "handoff:a"),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    admission = evaluate_closure_object_l10_admission(closure)

    assert admission.gate_ready is False
    assert admission.source_refs == ()
    assert admission.target_refs == ()
    assert admission.owner_refs == ()
    assert admission.issues == (
        (
            "ClosureObject status missing desired conditions: "
            "RecoveryArtifactPresent, RecoveryAllowsProgress, "
            "ValidatedExecutionCandidatePresent, IndependentReviewVerdictPresent, "
            "PatchForwardLineagePresent, ReleaseHandoffEvaluated"
        ),
    )


def test_closure_object_l10_admission_requires_complete_spec_chain() -> None:
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
            source_refs=("handoff:a",),
            target_refs=("lane:lane-a",),
            owner_refs=("source_authority:closure-controller",),
        ),
        spec=ClosureSpec(
            desired_conditions=(
                CLOSURE_CONTROLLER_FRESH,
                REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
                SERVER_TRUTH_PENDING,
            )
        ),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=tuple(
                _admission_condition(condition_type)
                for condition_type in CONDITION_ORDER
            ),
            observed_refs=("candidate:a", "handoff:a"),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    admission = evaluate_closure_object_l10_admission(closure)

    assert admission.gate_ready is False
    assert admission.source_refs == ()
    assert admission.target_refs == ()
    assert admission.owner_refs == ()
    assert admission.issues == (
        (
            "ClosureObject spec missing required desired conditions: "
            "RecoveryArtifactPresent, RecoveryAllowsProgress, "
            "ValidatedExecutionCandidatePresent, IndependentReviewVerdictPresent, "
            "PatchForwardLineagePresent, ReleaseHandoffEvaluated"
        ),
    )


def test_closure_object_l10_admission_requires_stable_refs() -> None:
    closure = ClosureObject(
        metadata=ClosureMetadata(
            name="closure:graph-a:lane-a",
            layer="WaveD-E/L8-L10",
        ),
        spec=ClosureSpec(),
        status=ClosureStatus(
            phase="manual_gap",
            conditions=tuple(
                _admission_condition(condition_type)
                for condition_type in CONDITION_ORDER
            ),
            forbidden_claims=REQUIRED_FORBIDDEN_CLAIMS,
        ),
    )

    admission = evaluate_closure_object_l10_admission(closure)

    assert admission.gate_ready is False
    assert admission.source_refs == ()
    assert admission.source_ref_count == 0
    assert admission.target_refs == ()
    assert admission.target_ref_count == 0
    assert admission.owner_refs == ()
    assert admission.owner_ref_count == 0
    assert admission.issues == (
        "ClosureObject source refs are missing",
        "ClosureObject target refs are missing",
        "ClosureObject owner refs are missing",
    )
