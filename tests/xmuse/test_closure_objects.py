from xmuse_core.platform.closure_objects import (
    CONDITION_ORDER,
    DEFAULT_CLOSURE_CHAIN,
    REQUIRED_FORBIDDEN_CLAIMS,
    SERVER_TRUTH_PENDING,
    ClosureCondition,
    ClosureMetadata,
    ClosureObject,
    ClosureSpec,
    ClosureStatus,
    closure_condition_by_type,
    dedupe_text,
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
    assert payload["spec"]["desired_conditions"] == list(CONDITION_ORDER)
    assert payload["spec"]["proof_level"] == "contract_proof"
    assert payload["status"]["conditions"][0]["type"] == SERVER_TRUTH_PENDING
    assert payload["status"]["forbidden_claims"] == list(REQUIRED_FORBIDDEN_CLAIMS)
    assert closure_condition_by_type(closure, SERVER_TRUTH_PENDING) == condition


def test_dedupe_text_preserves_first_seen_order_and_drops_empty_values() -> None:
    assert dedupe_text([" lane:a ", "", "lane:a", None, "lane:b"]) == (
        "lane:a",
        "lane:b",
    )
