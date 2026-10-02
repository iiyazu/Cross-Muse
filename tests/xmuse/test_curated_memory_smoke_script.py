from __future__ import annotations

from typing import Any

from scripts import curated_memory_smoke as smoke


def _candidate(
    candidate_id: str,
    *,
    proposer_kind: str = smoke.CURATOR_PROPOSER_KIND,
    kind: str = smoke.PROJECT_RULE_KIND,
    supersedes_candidate_id: str | None = None,
    superseded_by_candidate_id: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "proposer_kind": proposer_kind,
        "kind": kind,
        "content": "every HTTP error response uses the JSON envelope",
        "approval_state": "pending",
        "publish_state": "not_queued",
        "supersedes_candidate_id": supersedes_candidate_id,
        "superseded_by_candidate_id": superseded_by_candidate_id,
    }


def test_select_curator_candidate_filters_by_proposer_kind_and_kind() -> None:
    candidates = [
        _candidate("participant-rule", proposer_kind="participant"),
        _candidate("curator-fact", kind="room_fact"),
        _candidate("curator-rule"),
    ]

    assert smoke.select_curator_candidate(candidates, kind="project_rule") == candidates[2]
    assert smoke.select_curator_candidate(candidates, kind="room_fact") == candidates[1]
    assert smoke.select_curator_candidate([_candidate("curator-rule")], kind="room_fact") is None
    assert smoke.curator_candidates(candidates) == candidates[1:]


def test_select_curator_candidate_requires_the_exact_supersede_target() -> None:
    candidates = [_candidate("first"), _candidate("second", supersedes_candidate_id="first")]

    selected = smoke.select_curator_candidate(
        candidates, kind="project_rule", supersedes_candidate_id="first"
    )
    assert selected is not None
    assert selected["candidate_id"] == "second"
    assert (
        smoke.select_curator_candidate(
            [_candidate("first")], kind="project_rule", supersedes_candidate_id="first"
        )
        is None
    )


def test_candidate_document_id_uses_the_curated_candidate_namespace() -> None:
    assert smoke.candidate_document_id("memory_candidate_1") == (
        "xmuse-room-memory-candidate-memory_candidate_1"
    )


def test_parse_item_document_ids_tolerates_untrusted_receipts() -> None:
    assert smoke.parse_item_document_ids("not json") == []
    assert smoke.parse_item_document_ids('{"document_id": "one"}') == []
    assert smoke.parse_item_document_ids(
        '[{"document_id": "doc-b"}, {"item_id": "missing-document"}, {"document_id": "doc-a"}]'
    ) == ["doc-a", "doc-b"]


def test_recall_checks_accept_the_updated_document_only() -> None:
    new_document = smoke.candidate_document_id("second")
    old_document = smoke.candidate_document_id("first")
    receipts = [
        {"status": "ok", "document_ids": [new_document]},
        {"status": "empty", "document_ids": []},
    ]

    checks = smoke.recall_checks(
        receipts,
        speech_text="The envelope is {code, message, Details, trace_id}.",
        new_document_id=new_document,
        old_document_id=old_document,
    )

    assert checks == {
        "answer_mentions_details": True,
        "recall_status_ok": True,
        "new_document_cited": True,
        "old_document_absent": True,
    }


def test_recall_checks_reject_a_superseded_citation_and_missing_answer() -> None:
    new_document = smoke.candidate_document_id("second")
    old_document = smoke.candidate_document_id("first")
    receipts = [{"status": "source_rejected", "document_ids": [old_document]}]

    checks = smoke.recall_checks(
        receipts,
        speech_text="The evidence is absent.",
        new_document_id=new_document,
        old_document_id=old_document,
    )

    assert not any(checks.values())


def test_supersede_checks_require_both_candidate_directions() -> None:
    old = _candidate("first", superseded_by_candidate_id="second")
    new = _candidate("second", supersedes_candidate_id="first")

    assert smoke.supersede_checks(old, new) == {
        "new_supersedes_old": True,
        "old_superseded_by_new": True,
    }
    assert not all(smoke.supersede_checks(_candidate("first"), new).values())
