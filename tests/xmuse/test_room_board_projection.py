"""Behaviour tests for the room board read model v2."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tests.xmuse.board_scenarios import (
    INJECTION_PROMPT,
    INTEGRATION_SCENARIOS,
    NOW,
    REVIEW_SCENARIOS,
    SCENARIOS,
    SERVER_TIME,
    _approved_board,
    _itime,
    _report_done,
    _round,
    _round_time,
    build_scenario,
)
from xmuse_core.chat.room_board_projection import (
    CharterDependency,
    IntegrationFacts,
    IntegrationItemFact,
    IntegrationJobFact,
    ProgressFact,
    RevisedContract,
    StackedRef,
    VerificationFact,
    agent_text,
    board_events_page,
    build_board_projection,
    build_board_summary,
    build_contract_detail,
    build_integration_detail,
    compute_counters,
    compute_escalated,
    compute_revision,
    compute_stale_dependents,
    derive_lifecycle,
    derive_module_accepted,
    derive_module_attention,
    derive_module_integration,
    derive_state,
    derive_verification_axis,
    load_integration_facts,
    newest_finished_integration_job,
    project_event,
    sanitize_text,
)
from xmuse_core.chat.room_board_view import materialize_owner_board_view
from xmuse_core.chat.room_database import RoomDatabase

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "docs" / "contracts" / "fixtures" / "board_v2"
SCHEMA_DIR = ROOT / "docs" / "contracts" / "schemas"

CHARTER_TS = "2026-01-01T00:00:00.000000Z"
LATER_TS = "2026-01-02T00:00:00.000000Z"

BIDI_CHARS = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"


def _fact(status: str, created_at: str = LATER_TS, participant: str = "owner") -> ProgressFact:
    return ProgressFact(status=status, participant_id=participant, created_at=created_at, seq=1)


def _job(
    status: str,
    created_at: str = LATER_TS,
    *,
    reason: str | None = None,
    gates: list[str] | None = None,
) -> VerificationFact:
    return VerificationFact(
        verification_id=f"vid-{status}-{created_at}",
        status=status,
        reason_code=reason,
        gate_ids=list(gates or []),
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# agent text
# ---------------------------------------------------------------------------


def test_agent_text_strips_controls_ansi_and_bidi() -> None:
    wrapped = agent_text("a\x00b\x07c\nstill\there\x1b[31mred\x1b[0m", max_chars=400)
    assert wrapped["untrusted"] is True
    assert wrapped["truncated"] is False
    # Only the escape sequences go; the text they styled stays.
    assert wrapped["text"] == "abc\nstill\therered"
    assert "\x1b" not in wrapped["text"]


def test_agent_text_strips_osc_and_bidi() -> None:
    wrapped = agent_text("x\x1b]0;title\x07yab\u202edef\u2066ghi", max_chars=400)
    assert wrapped == {"text": "xyabdefghi", "untrusted": True, "truncated": False}


def test_agent_text_truncates_on_code_point_boundary() -> None:
    wrapped = agent_text("héllo🍝orld", max_chars=6)
    assert wrapped["text"] == "héllo🍝"
    assert wrapped["truncated"] is True
    assert wrapped["untrusted"] is True


@pytest.mark.parametrize("value", [None, 42, True, ["x"], {"text": "x"}])
def test_agent_text_non_string_is_empty(value: Any) -> None:
    assert agent_text(value, max_chars=10) == {
        "text": "",
        "untrusted": True,
        "truncated": False,
    }


def test_sanitize_text_matches_agent_text_without_truncation() -> None:
    assert sanitize_text("a\x1b[1mb\u202ec") == "abc"
    assert sanitize_text(None) == ""
    assert sanitize_text(7) == ""


# ---------------------------------------------------------------------------
# lifecycle / state table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lifecycle",
    ["assigned", "claimed", "working", "blocked", "ready_for_review"],
)
@pytest.mark.parametrize(
    "axis",
    ["none", "waiting_for_provider", "pending", "running", "passed", "failed", "error"],
)
def test_state_without_done_claim_is_lifecycle(lifecycle: str, axis: str) -> None:
    assert derive_state(lifecycle, axis) == lifecycle


@pytest.mark.parametrize(
    ("axis", "expected"),
    [
        ("passed", "verified"),
        ("failed", "verification_failed"),
        ("error", "verification_error"),
        ("pending", "verifying"),
        ("running", "verifying"),
        ("waiting_for_provider", "waiting_for_provider"),
        ("none", "done_claimed"),
    ],
)
def test_state_with_done_claim_follows_axis(axis: str, expected: str) -> None:
    assert derive_state("done_claimed", axis) == expected


@pytest.mark.parametrize(
    ("reports", "claimed_at", "expected"),
    [
        ([], None, "assigned"),
        ([], "2026-01-01T00:00:01.000000Z", "claimed"),
        ([_fact("working")], None, "working"),
        ([_fact("blocked")], None, "blocked"),
        ([_fact("ready_for_review")], None, "ready_for_review"),
        ([_fact("done")], None, "done_claimed"),
        # Reports by another participant do not count.
        ([_fact("working", participant="stranger")], None, "assigned"),
        # Reports before the charter do not count.
        ([_fact("working", created_at="2025-12-31T00:00:00.000000Z")], None, "assigned"),
        # Latest report wins.
        ([_fact("done"), _fact("working")], None, "working"),
        ([_fact("working"), _fact("done")], None, "done_claimed"),
    ],
)
def test_derive_lifecycle_table(
    reports: list[ProgressFact], claimed_at: str | None, expected: str
) -> None:
    assert (
        derive_lifecycle(
            claimed_at=claimed_at,
            charter_created_at=CHARTER_TS,
            owner_participant_id="owner",
            reports=reports,
        )
        == expected
    )


# ---------------------------------------------------------------------------
# verification axis
# ---------------------------------------------------------------------------


def test_verification_axis_none_without_jobs() -> None:
    assert derive_verification_axis(charter_created_at=CHARTER_TS, jobs=[]) == {
        "status": "none",
        "verification_id": None,
        "reason_code": None,
        "escalated": False,
        "gate_ids": [],
        "stacked": [],
        "head_commit": None,
        "changed_path_count": 0,
        "updated_at": None,
    }


def test_verification_axis_skips_superseded_and_pre_charter() -> None:
    axis = derive_verification_axis(
        charter_created_at=CHARTER_TS,
        jobs=[
            _job("passed", created_at="2025-12-31T00:00:00.000000Z"),
            _job("failed", reason="old"),
            _job("superseded", created_at="2026-01-03T00:00:00.000000Z"),
        ],
    )
    assert axis["status"] == "failed"
    assert axis["reason_code"] == "old"


def test_verification_axis_maps_waiting_and_latest_wins() -> None:
    axis = derive_verification_axis(
        charter_created_at=CHARTER_TS,
        jobs=[
            _job("failed", created_at="2026-01-02T00:00:00.000000Z", reason="x"),
            VerificationFact(
                verification_id="wait-1",
                status="pending",
                reason_code="board_verification_waiting_for_provider",
                created_at="2026-01-03T00:00:00.000000Z",
            ),
        ],
    )
    assert axis["status"] == "waiting_for_provider"
    assert axis["verification_id"] == "wait-1"
    assert axis["reason_code"] == "board_verification_waiting_for_provider"


def test_verification_axis_gate_ids_only_for_failed() -> None:
    failed = derive_verification_axis(
        charter_created_at=CHARTER_TS,
        jobs=[_job("failed", reason="g", gates=["gate-a", "gate-b"])],
    )
    assert failed["gate_ids"] == ["gate-a", "gate-b"]
    passed = derive_verification_axis(
        charter_created_at=CHARTER_TS,
        jobs=[_job("passed", gates=["gate-a"])],
    )
    assert passed["gate_ids"] == []
    assert passed["reason_code"] is None


def test_verification_axis_projects_stacked_head_and_count() -> None:
    axis = derive_verification_axis(
        charter_created_at=CHARTER_TS,
        jobs=[
            VerificationFact(
                verification_id="v1",
                status="failed",
                reason_code="g",
                gate_ids=[],
                stacked=[StackedRef(module_id="backend", verification_id="vb")],
                head_commit="c" * 40,
                changed_path_count=3,
                created_at=LATER_TS,
                updated_at="2026-01-04T00:00:00.000000Z",
            )
        ],
    )
    assert axis["stacked"] == [{"module_id": "backend", "verification_id": "vb"}]
    assert axis["head_commit"] == "c" * 40
    assert axis["changed_path_count"] == 3
    assert axis["updated_at"] == "2026-01-04T00:00:00.000000Z"


def test_done_claimed_with_none_axis_stays_done_claimed() -> None:
    lifecycle = derive_lifecycle(
        claimed_at=None,
        charter_created_at=CHARTER_TS,
        owner_participant_id="owner",
        reports=[_fact("done")],
    )
    axis = derive_verification_axis(charter_created_at=CHARTER_TS, jobs=[])
    assert lifecycle == "done_claimed"
    assert derive_state(lifecycle, str(axis["status"])) == "done_claimed"


# ---------------------------------------------------------------------------
# counters / escalation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "done_reports", "expected"),
    [
        ([], 0, (0, 0, 0, 0, 0, 0)),
        (["passed"], 1, (1, 1, 0, 0, 0, 0)),
        (["failed", "failed"], 2, (2, 0, 2, 0, 0, 2)),
        (["failed", "failed", "passed"], 3, (3, 1, 2, 0, 0, 2)),
        (["failed", "passed", "failed"], 3, (3, 1, 2, 0, 0, 1)),
        (["pending", "running"], 1, (1, 0, 0, 0, 0, 0)),
        (["superseded", "superseded", "error"], 2, (2, 0, 0, 2, 1, 0)),
        (["failed", "superseded", "error", "passed"], 2, (2, 1, 1, 1, 1, 1)),
    ],
)
def test_compute_counters_table(
    statuses: list[str], done_reports: int, expected: tuple[int, ...]
) -> None:
    assert compute_counters(statuses, done_reports=done_reports) == {
        "done_reports": expected[0],
        "passed": expected[1],
        "failed": expected[2],
        "superseded": expected[3],
        "errored": expected[4],
        "rework_rounds": expected[5],
        "reviews_endorsed": 0,
        "reviews_objected": 0,
        "integrations_conflicted": 0,
        "integrations_gate_failed": 0,
        "conflict_fix_rounds": 0,
    }


def test_compute_counters_integration_kwargs() -> None:
    assert compute_counters(
        ["passed"],
        done_reports=1,
        integrations_conflicted=2,
        integrations_gate_failed=1,
        conflict_fix_rounds=3,
    ) == {
        "done_reports": 1,
        "passed": 1,
        "failed": 0,
        "superseded": 0,
        "errored": 0,
        "rework_rounds": 0,
        "reviews_endorsed": 0,
        "reviews_objected": 0,
        "integrations_conflicted": 2,
        "integrations_gate_failed": 1,
        "conflict_fix_rounds": 3,
    }


@pytest.mark.parametrize(
    ("trailing", "expected"),
    [
        ([], False),
        (["failed"], False),
        (["failed", "failed"], False),
        (["failed", "failed", "failed"], True),
        (["failed", "failed", "failed", "failed"], True),
        (["passed", "failed", "failed"], False),
        (["failed", "failed", "passed"], False),
    ],
)
def test_compute_escalated_table(trailing: list[str], expected: bool) -> None:
    assert compute_escalated(trailing) is expected


# ---------------------------------------------------------------------------
# attention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lifecycle", "axis", "escalated", "stale", "kind", "reason"),
    [
        ("working", "error", False, False, "operator", "board_attention_verification_error"),
        ("done_claimed", "failed", True, False, "lead", "board_attention_verification_escalated"),
        ("done_claimed", "failed", False, True, "owner", "board_attention_verification_failed"),
        ("blocked", "none", False, True, "lead", "board_attention_module_blocked"),
        ("working", "none", False, True, "owner", "board_attention_contract_stale"),
        ("working", "none", False, False, "none", None),
        ("done_claimed", "passed", False, False, "none", None),
        ("ready_for_review", "pending", False, False, "none", None),
        # Precedence: error beats everything; blocked beats a stale flag, and a
        # failed verification only holds attention while the owner has not
        # filed a newer report (lifecycle left done_claimed).
        ("blocked", "error", False, True, "operator", "board_attention_verification_error"),
        ("blocked", "failed", True, True, "lead", "board_attention_module_blocked"),
    ],
)
def test_attention_precedence_table(
    lifecycle: str, axis: str, escalated: bool, stale: bool, kind: str, reason: str | None
) -> None:
    assert derive_module_attention(
        lifecycle=lifecycle,
        verification_status=axis,
        escalated=escalated,
        is_stale=stale,
    ) == {"kind": kind, "reason_code": reason}


def test_failed_stops_being_attention_after_newer_report() -> None:
    lifecycle = derive_lifecycle(
        claimed_at=None,
        charter_created_at=CHARTER_TS,
        owner_participant_id="owner",
        reports=[_fact("done"), _fact("working", created_at="2026-01-05T00:00:00.000000Z")],
    )
    assert lifecycle == "working"
    assert derive_state(lifecycle, "failed") == "working"
    assert derive_module_attention(
        lifecycle=lifecycle,
        verification_status="failed",
        escalated=False,
        is_stale=False,
    ) == {"kind": "none", "reason_code": None}


@pytest.mark.parametrize(
    ("state", "reviews_capability", "review_status", "expected"),
    [
        ("verified", 0, "none", True),
        ("verified", 0, "pending", True),
        ("verified", 0, "objected", True),
        ("verified", 1, "endorsed", True),
        ("verified", 1, "pending", False),
        ("verified", 1, "objected", False),
        ("verified", 1, "superseded", False),
        ("verified", 1, "none", False),
        ("done_claimed", 0, "none", False),
        ("done_claimed", 1, "endorsed", False),
        ("verification_failed", 0, "none", False),
        ("verification_failed", 1, "endorsed", False),
        ("working", 1, "endorsed", False),
    ],
)
def test_derive_module_accepted_table(
    state: str, reviews_capability: int, review_status: str, expected: bool
) -> None:
    assert (
        derive_module_accepted(
            state=state,
            reviews_capability=reviews_capability,
            review_status=review_status,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("lifecycle", "v_status", "escalated", "rev_status", "rev_kind", "stale", "kind", "reason"),
    [
        # Error beats review
        (
            "done_claimed",
            "error",
            False,
            "pending",
            "operator",
            False,
            "operator",
            "board_attention_verification_error",
        ),
        # Escalated failed beats review
        (
            "done_claimed",
            "failed",
            True,
            "pending",
            "operator",
            False,
            "lead",
            "board_attention_verification_escalated",
        ),
        # Failed verification beats review
        (
            "done_claimed",
            "failed",
            False,
            "pending",
            "operator",
            False,
            "owner",
            "board_attention_verification_failed",
        ),
        # Review operator pending wins when passed
        (
            "done_claimed",
            "passed",
            False,
            "pending",
            "operator",
            False,
            "operator",
            "board_attention_review_operator_pending",
        ),
        # Review operator pending beats blocked
        (
            "blocked",
            "passed",
            False,
            "pending",
            "operator",
            False,
            "operator",
            "board_attention_review_operator_pending",
        ),
        # Review participant pending is NOT attention: blocked wins
        (
            "blocked",
            "passed",
            False,
            "pending",
            "participant",
            False,
            "lead",
            "board_attention_module_blocked",
        ),
        # Review participant pending is NOT attention: stale wins
        (
            "working",
            "passed",
            False,
            "pending",
            "participant",
            True,
            "owner",
            "board_attention_contract_stale",
        ),
        # Review participant pending with none: none
        ("done_claimed", "passed", False, "pending", "participant", False, "none", None),
        # Review objected with done_claimed wins
        (
            "done_claimed",
            "passed",
            False,
            "objected",
            "participant",
            False,
            "owner",
            "board_attention_review_objected",
        ),
        # Review objected with done_claimed beats blocked
        (
            "done_claimed",
            "passed",
            False,
            "objected",
            "operator",
            False,
            "owner",
            "board_attention_review_objected",
        ),
        # Review objected stops being attention when owner filed newer report (lifecycle working)
        ("working", "passed", False, "objected", "participant", False, "none", None),
        (
            "working",
            "passed",
            False,
            "objected",
            "participant",
            True,
            "owner",
            "board_attention_contract_stale",
        ),
        # Review endorsed is not attention
        ("done_claimed", "passed", False, "endorsed", "participant", False, "none", None),
        # Review superseded is not attention
        ("done_claimed", "passed", False, "superseded", "participant", False, "none", None),
    ],
)
def test_attention_review_precedence_table(
    lifecycle: str,
    v_status: str,
    escalated: bool,
    rev_status: str,
    rev_kind: str | None,
    stale: bool,
    kind: str,
    reason: str | None,
) -> None:
    assert derive_module_attention(
        lifecycle=lifecycle,
        verification_status=v_status,
        escalated=escalated,
        review_status=rev_status,
        review_reviewer_kind=rev_kind,
        is_stale=stale,
    ) == {"kind": kind, "reason_code": reason}


# ---------------------------------------------------------------------------
# stale dependents
# ---------------------------------------------------------------------------


def test_stale_dependents_table() -> None:
    revised = [
        RevisedContract(
            contract_id="api.backend",
            revised_version=2,
            revised_seq=17,
            provider_module_id="backend",
        )
    ]
    charters = [
        CharterDependency(module_id="backend", owner_participant_id="o1", depends=["api.frontend"]),
        CharterDependency(module_id="frontend", owner_participant_id="o2", depends=["api.backend"]),
        CharterDependency(module_id="sidecar", owner_participant_id="o3", depends=["api.backend"]),
    ]
    # Provider excluded; frontend reported before the revision; sidecar after.
    stale = compute_stale_dependents(
        revised=revised,
        charters=charters,
        latest_progress_seq={"frontend": 10, "sidecar": 18},
    )
    assert stale == [
        {
            "contract_id": "api.backend",
            "revised_version": 2,
            "revised_seq": 17,
            "module_id": "frontend",
            "owner_participant_id": "o2",
        }
    ]
    # A report exactly at the revision seq is still stale (must be greater).
    assert (
        compute_stale_dependents(
            revised=revised, charters=charters, latest_progress_seq={"frontend": 17}
        )[0]["module_id"]
        == "frontend"
    )
    # No revised contract, no staleness.
    assert compute_stale_dependents(revised=[], charters=charters, latest_progress_seq={}) == []


# ---------------------------------------------------------------------------
# project_event
# ---------------------------------------------------------------------------


def test_project_event_unknown_kind_is_none() -> None:
    assert project_event({"activity_type": "board.future", "payload": {}}) is None
    assert project_event({"activity_type": "chat.message", "payload": {}}) is None


def test_project_event_never_copies_content_or_payload() -> None:
    event = project_event(
        {
            "seq": 3,
            "activity_type": "board.progress",
            "actor_kind": "participant",
            "actor_participant_id": "p1",
            "created_at": CHARTER_TS,
            "payload": {
                "module_id": "alpha",
                "status": "done",
                "summary": "s",
                "claims": ["c"] * 10,
                "content": "host text to agents",
                "lease_token": "secret",
            },
        }
    )
    assert event is not None
    assert event["data"]["claims_total"] == 10
    assert len(event["data"]["claims"]) == 8
    dumped = json.dumps(event)
    assert "host text to agents" not in dumped
    assert "secret" not in dumped
    assert event["actor"] == {"kind": "participant", "participant_id": "p1"}


def test_project_event_actor_mapping() -> None:
    base = {"seq": 1, "activity_type": "board.claimed", "created_at": CHARTER_TS}
    operator = project_event(
        {**base, "actor_kind": "operator", "payload": {"module_id": "m", "version": 1}}
    )
    assert operator is not None
    assert operator["actor"] == {"kind": "operator", "participant_id": None}
    infra = project_event(
        {
            **base,
            "activity_type": "board.verification",
            "actor_kind": "infrastructure",
            "payload": {
                "module_id": "m",
                "verification_id": "v",
                "status": "passed",
                "reason_code": None,
                "gates": [],
                "escalated": False,
                "stacked": [],
            },
        }
    )
    assert infra is not None
    assert infra["actor"] == {"kind": "infrastructure", "participant_id": None}


def test_project_event_decision_grant_id() -> None:
    base = {"seq": 1, "actor_kind": "operator", "created_at": CHARTER_TS}
    rejected = project_event(
        {
            **base,
            "activity_type": "board.split_rejected",
            "payload": {
                "split_id": "s1",
                "decided_via": "plugin:claude-code",
                "grant_id": "grant_1",
            },
        }
    )
    assert rejected is not None
    assert rejected["data"] == {
        "split_id": "s1",
        "decided_via": "plugin:claude-code",
        "grant_id": "grant_1",
    }
    assigned = project_event(
        {
            **base,
            "seq": 2,
            "activity_type": "board.charter_assigned",
            "payload": {
                "split_id": "s1",
                "module_id": "alpha",
                "version": 1,
                "owner_participant_id": "p1",
                "decided_via": "web",
                "grant_id": None,
            },
        }
    )
    assert assigned is not None
    assert assigned["module_id"] == "alpha"
    assert assigned["data"] == {
        "split_id": "s1",
        "owner_participant_id": "p1",
        "charter_version": 1,
        "decided_via": "web",
        "grant_id": None,
    }


def test_project_event_decision_grant_id_missing_projects_null() -> None:
    # Rows written before grant_id existed carry no key; they project null.
    base = {"seq": 1, "actor_kind": "operator", "created_at": CHARTER_TS}
    rejected = project_event(
        {
            **base,
            "activity_type": "board.split_rejected",
            "payload": {"split_id": "s1", "decided_via": "web"},
        }
    )
    assert rejected is not None
    assert rejected["data"] == {"split_id": "s1", "decided_via": "web", "grant_id": None}
    assigned = project_event(
        {
            **base,
            "seq": 2,
            "activity_type": "board.charter_assigned",
            "payload": {
                "split_id": "s1",
                "module_id": "alpha",
                "version": 1,
                "owner_participant_id": "p1",
                "decided_via": "cli",
            },
        }
    )
    assert assigned is not None
    assert assigned["data"] == {
        "split_id": "s1",
        "owner_participant_id": "p1",
        "charter_version": 1,
        "decided_via": "cli",
        "grant_id": None,
    }


# ---------------------------------------------------------------------------
# fixtures: regeneration + schema validation
# ---------------------------------------------------------------------------


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _triple(ctx: dict[str, Any]) -> dict[str, Any]:
    with RoomDatabase(ctx["db"]).connect() as conn:
        projection = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
        summary = build_board_summary(projection)
        events_page = board_events_page(conn, ctx["conversation_id"], after_seq=0, limit=100)
    return {"projection": projection, "summary": summary, "events_page": events_page}


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("name", SCENARIOS)
def test_board_fixture_reproduces_and_validates(tmp_path: Path, name: str) -> None:
    ctx = build_scenario(name, tmp_path)
    triple = _triple(ctx)
    text = _dump(triple)
    target = FIXTURE_DIR / f"{name}.json"
    if os.environ.get("UPDATE_BOARD_FIXTURES") == "1":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    assert target.exists(), f"missing fixture {target}; generate with UPDATE_BOARD_FIXTURES=1"
    assert target.read_text(encoding="utf-8") == text

    projection_schema = _load_schema("room_board_projection.v2.json")
    summary_schema = _load_schema("room_board_summary.v1.json")
    events_schema = _load_schema("room_board_events.v1.json")
    jsonschema.validate(triple["projection"], projection_schema)
    jsonschema.validate(triple["summary"], summary_schema)
    jsonschema.validate(triple["events_page"], events_schema)

    if name in REVIEW_SCENARIOS:
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            rev_row = conn.execute(
                "select review_id from room_board_reviews where conversation_id = ? "
                "order by created_at desc, rowid desc limit 1",
                (ctx["conversation_id"],),
            ).fetchone()
        assert rev_row is not None
        review_id = str(rev_row["review_id"])
        review_data = ctx["store"].review_detail(ctx["conversation_id"], review_id)
        review_target = FIXTURE_DIR / f"{name}.review.json"
        review_text = _dump(review_data)
        if os.environ.get("UPDATE_BOARD_FIXTURES") == "1":
            review_target.write_text(review_text, encoding="utf-8")
        assert review_target.exists(), f"missing review fixture {review_target}"
        assert review_target.read_text(encoding="utf-8") == review_text
        review_schema = _load_schema("room_board_review.v1.json")
        jsonschema.validate(review_data, review_schema)

    if name == "review_operator_pending":
        material_data = ctx["store"].review_material(ctx["conversation_id"], review_id)
        material_target = FIXTURE_DIR / f"{name}.material.json"
        material_text = _dump(material_data)
        if os.environ.get("UPDATE_BOARD_FIXTURES") == "1":
            material_target.write_text(material_text, encoding="utf-8")
        assert material_target.exists(), f"missing material fixture {material_target}"
        assert material_target.read_text(encoding="utf-8") == material_text
        material_schema = _load_schema("room_board_review_material.v1.json")
        jsonschema.validate(material_data, material_schema)

    if name == "verification_failed_rework":
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            ver_row = conn.execute(
                "select verification_id from room_board_verifications "
                "where conversation_id = ? and status = 'failed' "
                "order by created_at desc, rowid desc limit 1",
                (ctx["conversation_id"],),
            ).fetchone()
        assert ver_row is not None
        verification_id = str(ver_row["verification_id"])
        ver_data = ctx["store"].verification_detail(ctx["conversation_id"], verification_id)
        ver_target = FIXTURE_DIR / f"{name}.verification.json"
        ver_text = _dump(ver_data)
        if os.environ.get("UPDATE_BOARD_FIXTURES") == "1":
            ver_target.write_text(ver_text, encoding="utf-8")
        assert ver_target.exists(), f"missing verification fixture {ver_target}"
        assert ver_target.read_text(encoding="utf-8") == ver_text
        ver_schema = _load_schema("room_board_verification.v1.json")
        jsonschema.validate(ver_data, ver_schema)

    if name in INTEGRATION_SCENARIOS:
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            job_row = conn.execute(
                "select integration_id from room_board_integrations "
                "where conversation_id = ? order by created_at desc, rowid desc limit 1",
                (ctx["conversation_id"],),
            ).fetchone()
        assert job_row is not None, f"integration scenario {name} has no job"
        job_id = str(job_row["integration_id"])
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            int_data = build_integration_detail(conn, ctx["conversation_id"], job_id)
        assert int_data is not None
        int_target = FIXTURE_DIR / f"{name}.integration.json"
        int_text = _dump(int_data)
        if os.environ.get("UPDATE_BOARD_FIXTURES") == "1":
            int_target.write_text(int_text, encoding="utf-8")
        assert int_target.exists(), f"missing integration fixture {int_target}"
        assert int_target.read_text(encoding="utf-8") == int_text
        int_schema = _load_schema("room_board_integration.v1.json")
        jsonschema.validate(int_data, int_schema)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _module(fixture: dict[str, Any], module_id: str) -> dict[str, Any]:
    return next(item for item in fixture["projection"]["modules"] if item["module_id"] == module_id)


def test_fixture_empty() -> None:
    fixture = _fixture("empty")
    assert fixture["projection"]["modules"] == []
    assert fixture["projection"]["board_seq"] == 0
    assert fixture["projection"]["events"] == []
    counts = fixture["summary"]["counts"]
    assert set(counts) == {
        "assigned",
        "claimed",
        "working",
        "blocked",
        "ready_for_review",
        "done_claimed",
        "verifying",
        "waiting_for_provider",
        "verified",
        "verification_failed",
        "verification_error",
    }
    assert all(value == 0 for value in counts.values())
    assert fixture["summary"]["attention"] == []


def test_fixture_split_pending_attention() -> None:
    fixture = _fixture("split_pending")
    assert fixture["projection"]["modules"] == []
    assert fixture["projection"]["attention"] == [
        {
            "kind": "operator",
            "reason_code": "board_attention_split_pending",
            "module_id": None,
            "split_id": fixture["projection"]["splits"][0]["split_id"],
            "integration_id": None,
        }
    ]


def test_fixture_lifecycle_mix_states() -> None:
    fixture = _fixture("lifecycle_mix")
    states = {item["module_id"]: item["state"] for item in fixture["projection"]["modules"]}
    assert states == {
        "m-assigned": "assigned",
        "m-blocked": "blocked",
        "m-claimed": "claimed",
        "m-ready": "ready_for_review",
        "m-working": "working",
    }
    counts = fixture["summary"]["counts"]
    assert counts["assigned"] == 1
    assert counts["blocked"] == 1
    assert counts["working"] == 1
    assert counts["ready_for_review"] == 1


def test_fixture_verifying_and_waiting() -> None:
    fixture = _fixture("verifying_and_waiting")
    assert _module(fixture, "alpha")["state"] == "verifying"
    assert _module(fixture, "beta")["state"] == "waiting_for_provider"
    assert _module(fixture, "beta")["verification"]["status"] == "waiting_for_provider"


def test_fixture_verified() -> None:
    fixture = _fixture("verified")
    module = _module(fixture, "alpha")
    assert module["state"] == "verified"
    assert module["verification"]["status"] == "passed"
    assert module["counters"]["rework_rounds"] == 0


def test_fixture_failed_rework() -> None:
    fixture = _fixture("verification_failed_rework")
    module = _module(fixture, "alpha")
    assert module["state"] == "verification_failed"
    assert module["counters"] == {
        "done_reports": 2,
        "passed": 0,
        "failed": 2,
        "superseded": 0,
        "errored": 0,
        "rework_rounds": 2,
        "reviews_endorsed": 0,
        "reviews_objected": 0,
        "integrations_conflicted": 0,
        "integrations_gate_failed": 0,
        "conflict_fix_rounds": 0,
    }
    assert module["verification"]["gate_ids"] == ["patch_diff_check"]
    assert module["attention"] == {
        "kind": "owner",
        "reason_code": "board_attention_verification_failed",
    }


def test_fixture_escalated() -> None:
    fixture = _fixture("verification_escalated")
    module = _module(fixture, "alpha")
    assert module["verification"]["escalated"] is True
    assert module["attention"] == {
        "kind": "lead",
        "reason_code": "board_attention_verification_escalated",
    }
    events = [event for event in fixture["projection"]["events"] if event["kind"] == "verification"]
    assert len(events) == 3
    assert [event["data"]["escalated"] for event in events] == [False, False, True]


def test_fixture_error() -> None:
    fixture = _fixture("verification_error")
    module = _module(fixture, "alpha")
    assert module["state"] == "verification_error"
    assert module["verification"]["status"] == "error"
    assert module["counters"]["errored"] == 1
    assert module["attention"] == {
        "kind": "operator",
        "reason_code": "board_attention_verification_error",
    }


def test_fixture_superseded_done() -> None:
    fixture = _fixture("superseded_done")
    module = _module(fixture, "alpha")
    assert module["state"] == "verified"
    assert module["counters"]["superseded"] == 1
    assert module["counters"]["done_reports"] == 2


def test_fixture_contract_revised_stale_dependent() -> None:
    fixture = _fixture("contract_revised_stale_dependent")
    assert fixture["projection"]["stale_dependents"] == [
        {
            "contract_id": "api.backend",
            "revised_version": 2,
            "revised_seq": fixture["projection"]["stale_dependents"][0]["revised_seq"],
            "module_id": "frontend",
            "owner_participant_id": _module(fixture, "frontend")["owner_participant_id"],
        }
    ]
    assert _module(fixture, "frontend")["attention"] == {
        "kind": "owner",
        "reason_code": "board_attention_contract_stale",
    }
    assert _module(fixture, "sidecar")["attention"] == {"kind": "none", "reason_code": None}


# ---------------------------------------------------------------------------
# integration (§3.11): derivation units, fixtures, invariants
# ---------------------------------------------------------------------------


def _integration_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.integration.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("lifecycle", "v_status", "stale", "integration_status", "reported_after", "kind", "reason"),
    [
        (
            "working",
            "passed",
            False,
            "conflicted",
            False,
            "owner",
            "board_attention_integration_conflict",
        ),
        ("working", "passed", False, "conflicted", True, "none", None),
        ("working", "passed", False, "integrated", False, "none", None),
        ("working", "passed", False, "pending", False, "none", None),
        ("working", "passed", False, "running", False, "none", None),
        ("working", "passed", False, "gate_failed", False, "none", None),
        ("working", "passed", False, "error", False, "none", None),
        ("working", "passed", False, "waiting", False, "none", None),
        ("working", "passed", False, "none", False, "none", None),
        # A failed verification still beats an integration conflict.
        (
            "done_claimed",
            "failed",
            False,
            "conflicted",
            False,
            "owner",
            "board_attention_verification_failed",
        ),
        # The conflict row sits above blocked and stale rows.
        (
            "blocked",
            "passed",
            False,
            "conflicted",
            False,
            "owner",
            "board_attention_integration_conflict",
        ),
        (
            "working",
            "passed",
            True,
            "conflicted",
            False,
            "owner",
            "board_attention_integration_conflict",
        ),
        ("working", "passed", True, "conflicted", True, "owner", "board_attention_contract_stale"),
    ],
)
def test_attention_integration_conflict_table(
    lifecycle: str,
    v_status: str,
    stale: bool,
    integration_status: str,
    reported_after: bool,
    kind: str,
    reason: str | None,
) -> None:
    assert derive_module_attention(
        lifecycle=lifecycle,
        verification_status=v_status,
        escalated=False,
        is_stale=stale,
        integration_status=integration_status,
        integration_reported_after=reported_after,
    ) == {"kind": kind, "reason_code": reason}


def test_integration_conflict_attention_clears_after_owner_progress(tmp_path: Path) -> None:
    ctx = build_scenario("integration_conflicted", tmp_path)
    with RoomDatabase(ctx["db"]).connect() as conn:
        before = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    assert _module({"projection": before}, "mb")["attention"] == {
        "kind": "owner",
        "reason_code": "board_attention_integration_conflict",
    }
    owner = next(
        member
        for member in ctx["members"]
        if member.participant_id == _module({"projection": before}, "mb")["owner_participant_id"]
    )
    ctx["store"].report_progress(
        **ctx["lease_kwargs"](owner, "rep-after-conflict", now=_itime(120)),
        module_id="mb",
        status="working",
        summary="realigning after the conflict",
        claims=[],
    )
    with RoomDatabase(ctx["db"]).connect() as conn:
        after = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    assert _module({"projection": after}, "mb")["attention"] == {
        "kind": "none",
        "reason_code": None,
    }
    assert all(
        item.get("module_id") != "mb"
        for item in after["attention"]
        if item.get("reason_code") == "board_attention_integration_conflict"
    )


def _synthetic_job(
    integration_id: str,
    status: str,
    items: list[IntegrationItemFact],
    *,
    reason: str | None = None,
    finished_at: str | None = "2026-01-02T00:00:00.000000Z",
    activity_seq: int | None = 9,
    failed_gate_ids: list[str] | None = None,
) -> IntegrationJobFact:
    return IntegrationJobFact(
        integration_id=integration_id,
        status=status,
        reason_code=reason,
        created_at="2026-01-01T00:00:00.000000Z",
        updated_at="2026-01-02T00:00:00.000000Z",
        finished_at=finished_at if status not in ("pending", "running") else None,
        activity_id=None,
        activity_seq=activity_seq,
        green_after=None,
        failed_gate_ids=failed_gate_ids or [],
        items=items,
    )


def _synthetic_item(
    module_id: str,
    verification_id: str,
    status: str,
    *,
    role: str = "newcomer",
    applied: str | None = None,
    total: int = 0,
    reason: str | None = None,
) -> IntegrationItemFact:
    return IntegrationItemFact(
        module_id=module_id,
        verification_id=verification_id,
        item_order=0,
        role=role,
        status=status,
        applied_verification_id=applied,
        conflicts_total=total,
        reason_code=reason,
    )


def test_derive_module_integration_table() -> None:
    empty = IntegrationFacts()
    assert derive_module_integration("m", empty) == {
        "status": "none",
        "integration_id": None,
        "verification_id": None,
        "integrated_verification_id": None,
        "reason_code": None,
        "conflict_path_count": 0,
        "gate_ids": [],
        "updated_at": None,
    }
    # A candidate with no job yet: known, but nothing queued.
    no_job = IntegrationFacts(candidates={"m": "v1"})
    assert derive_module_integration("m", no_job)["status"] == "none"
    assert derive_module_integration("m", no_job)["verification_id"] == "v1"
    # Running wins over an older pending job holding the same candidate.
    active = IntegrationFacts(
        candidates={"m": "v1"},
        jobs=[
            _synthetic_job("j-pending", "pending", [_synthetic_item("m", "v1", "not_applied")]),
            _synthetic_job("j-run", "running", [_synthetic_item("m", "v1", "not_applied")]),
        ],
    )
    assert derive_module_integration("m", active)["status"] == "running"
    assert derive_module_integration("m", active)["integration_id"] == "j-run"
    # A candidate inside the green head reads integrated even while queued.
    green = IntegrationFacts(
        candidates={"m": "v1"},
        green_applied={"m": "v1"},
        green_head_commit="c" * 40,
        jobs=[
            _synthetic_job("j-pending", "pending", [_synthetic_item("m", "v1", "not_applied")]),
            _synthetic_job(
                "j-green",
                "integrated",
                [_synthetic_item("m", "v1", "applied", role="newcomer", applied="v1")],
            ),
        ],
    )
    assert derive_module_integration("m", green)["status"] == "integrated"
    assert derive_module_integration("m", green)["integrated_verification_id"] == "v1"
    # A gate_failed suspect carries the job's failed gates.
    gate_failed = IntegrationFacts(
        candidates={"m": "v2"},
        jobs=[
            _synthetic_job(
                "j-gate",
                "gate_failed",
                [_synthetic_item("m", "v2", "applied", applied="v2")],
                reason="board_integration_gate_failed",
                failed_gate_ids=["patch_diff_check"],
            ),
        ],
    )
    derived = derive_module_integration("m", gate_failed)
    assert derived["status"] == "gate_failed"
    assert derived["gate_ids"] == ["patch_diff_check"]
    # An error job marks its newcomers error.
    error = IntegrationFacts(
        candidates={"m": "v1"},
        jobs=[
            _synthetic_job(
                "j-err",
                "error",
                [_synthetic_item("m", "v1", "not_applied")],
                reason="board_integration_attempts_exhausted",
            ),
        ],
    )
    assert derive_module_integration("m", error)["status"] == "error"
    # A fell-back candidate is conflicted with the older version integrated.
    fell_back = IntegrationFacts(
        candidates={"m": "v2"},
        green_applied={"m": "v1"},
        green_head_commit="c" * 40,
        verification_created={"v1": "2026-01-01T00:00:00.000000Z"},
        jobs=[
            _synthetic_job(
                "j-ok",
                "integrated",
                [_synthetic_item("m", "v2", "fell_back", applied="v1", total=2)],
            ),
        ],
    )
    derived = derive_module_integration("m", fell_back)
    assert derived["status"] == "conflicted"
    assert derived["integrated_verification_id"] == "v1"
    assert derived["conflict_path_count"] == 2
    # Newest finished job rules: pending/running never count.
    assert newest_finished_integration_job(active) is None
    assert newest_finished_integration_job(green) is not None
    assert newest_finished_integration_job(green).integration_id == "j-green"


def test_project_event_integration_whitelist() -> None:
    event = project_event(
        {
            "seq": 9,
            "activity_type": "board.integration",
            "actor_kind": "infrastructure",
            "created_at": CHARTER_TS,
            "payload": {
                "integration_id": "j1",
                "status": "conflicted",
                "reason_code": "board_integration_conflict",
                "green_head_commit": "c" * 40,
                "integrated_module_ids": ["ma"],
                "suspect_module_ids": [],
                "conflicts": [
                    {
                        "module_id": "mb",
                        "conflict_path_count": 3,
                        "attributed_module_ids": ["ma", "mb"],
                        "fell_back": False,
                        "path": "docs/secret.txt",
                    }
                ],
                "waiting_module_ids": ["mc"],
                "gate_ids": [],
                "schema_version": "room_board_activity/v1",
                "evidence": {"output_tails": {"g": "x"}},
            },
        }
    )
    assert event is not None
    assert event["kind"] == "integration"
    assert event["module_id"] is None
    assert event["actor"] == {"kind": "infrastructure", "participant_id": None}
    assert set(event["data"]) == {
        "integration_id",
        "status",
        "reason_code",
        "green_head_commit",
        "integrated_module_ids",
        "suspect_module_ids",
        "conflicts",
        "waiting_module_ids",
        "gate_ids",
    }
    assert event["data"]["conflicts"] == [
        {
            "module_id": "mb",
            "conflict_path_count": 3,
            "attributed_module_ids": ["ma", "mb"],
            "fell_back": False,
        }
    ]


def test_integration_fixtures_invariants() -> None:
    for name in SCENARIOS:
        fixture = _fixture(name)
        projection, summary = fixture["projection"], fixture["summary"]
        assert summary["integrated_total"] <= summary["accepted_total"], name
        assert summary["integration"] == {
            "status": projection["integration"]["latest"]["status"]
            if projection["integration"]["latest"] is not None
            else None,
            "green_head_commit": projection["integration"]["green_head_commit"],
        }, name
        assert summary["integrated_total"] == sum(
            1
            for module in projection["modules"]
            if module["accepted"] is True
            and module["integration"]["integrated_verification_id"] is not None
            and module["integration"]["integrated_verification_id"]
            == module["verification"]["verification_id"]
        ), name
        for module in projection["modules"]:
            integration = module["integration"]
            if integration["status"] == "integrated":
                assert integration["integrated_verification_id"] is not None, name
                assert (
                    integration["integrated_verification_id"] == integration["verification_id"]
                ), name
        if name in INTEGRATION_SCENARIOS:
            sidecar = _integration_fixture(name)
            assert (
                sidecar["integration_id"] == projection["integration"]["latest"]["integration_id"]
            )
            for module in projection["modules"]:
                integration = module["integration"]
                if (
                    integration["status"] == "conflicted"
                    and integration["integration_id"] == sidecar["integration_id"]
                ):
                    item = next(
                        entry
                        for entry in sidecar["items"]
                        if entry["module_id"] == module["module_id"]
                    )
                    assert integration["conflict_path_count"] == item["conflicts_total"], name


def test_integration_green_head_accepted(tmp_path: Path) -> None:
    for name in INTEGRATION_SCENARIOS:
        ctx = build_scenario(name, tmp_path)
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            facts = load_integration_facts(
                conn,
                ctx["conversation_id"],
                reviews_on=ctx["store"].review_policy(ctx["conversation_id"]) == "cross_family",
            )
            ver_rows = {
                str(row["verification_id"]): row
                for row in conn.execute(
                    "select verification_id, status from room_board_verifications "
                    "where conversation_id = ?",
                    (ctx["conversation_id"],),
                ).fetchall()
            }
            endorsed = {
                str(row["verification_id"])
                for row in conn.execute(
                    "select verification_id from room_board_reviews "
                    "where conversation_id = ? and status = 'endorsed'",
                    (ctx["conversation_id"],),
                ).fetchall()
            }
        reviews_on = ctx["store"].review_policy(ctx["conversation_id"]) == "cross_family"
        for module_id, vid in facts.green_applied.items():
            assert vid in ver_rows, (name, module_id)
            assert ver_rows[vid]["status"] == "passed", (name, module_id)
            if reviews_on:
                assert vid in endorsed, (name, module_id)


def test_conflict_paths_only_in_integration_sidecars() -> None:
    for name in SCENARIOS:
        fixture = _fixture(name)
        for module in fixture["projection"]["modules"]:
            assert "conflicts" not in module["integration"], name
            assert "path" not in module["integration"], name
        for event in fixture["projection"]["events"]:
            if event["kind"] != "integration":
                continue
            for conflict in event["data"]["conflicts"]:
                assert "path" not in conflict, name
        for event in fixture["events_page"]["events"]:
            if event["kind"] != "integration":
                continue
            for conflict in event["data"]["conflicts"]:
                assert "path" not in conflict, name
        dumped_summary = json.dumps(fixture["summary"])
        assert '"conflicts"' not in dumped_summary, name
    for name in INTEGRATION_SCENARIOS:
        sidecar = _integration_fixture(name)

        def listed_paths(value: Any) -> list[str]:
            found: list[str] = []
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "path" and isinstance(item, str):
                        found.append(item)
                    else:
                        found.extend(listed_paths(item))
            elif isinstance(value, list):
                for item in value:
                    found.extend(listed_paths(item))
            return found

        for path in listed_paths(sidecar):
            assert not path.startswith("/"), (name, path)
            assert not DRIVE_RE.match(path), (name, path)


def test_existing_scenarios_change_only_by_section_10_fields() -> None:
    """Pin the compatible-additions list: old scenarios gain exactly the keys
    §10 names (capabilities.integrations, top-level integration,
    Module.integration, AttentionItem.integration_id, the three counters, the
    summary's integrated_total/integration, and revision) and nothing else."""

    others = [name for name in SCENARIOS if name not in INTEGRATION_SCENARIOS]
    assert others, "expected pre-integration scenarios"
    for name in others:
        fixture = _fixture(name)
        projection, summary = fixture["projection"], fixture["summary"]
        assert set(projection) == {
            "attention",
            "board_seq",
            "capabilities",
            "contracts",
            "conversation_id",
            "events",
            "integration",
            "metrics_version",
            "modules",
            "participants",
            "review_policy",
            "revision",
            "schema_version",
            "server_time",
            "splits",
            "stale_dependents",
        }, name
        assert set(projection["capabilities"]) == {
            "verification",
            "reviews",
            "integrations",
            "lessons",
        }, name
        assert projection["capabilities"]["integrations"] == 1, name
        assert set(summary) == {
            "accepted_total",
            "attention",
            "attention_total",
            "board_seq",
            "capabilities",
            "conversation_id",
            "counts",
            "integrated_total",
            "integration",
            "modules_total",
            "revision",
            "schema_version",
            "server_time",
        }, name
        for module in projection["modules"]:
            assert set(module) == {
                "accepted",
                "attention",
                "charter_version",
                "counters",
                "depends",
                "integration",
                "lifecycle",
                "module_id",
                "owner_participant_id",
                "paths",
                "provides",
                "report_to",
                "review",
                "state",
                "title",
                "verification",
            }, name
            assert set(module["counters"]) == {
                "done_reports",
                "errored",
                "failed",
                "passed",
                "reviews_endorsed",
                "reviews_objected",
                "rework_rounds",
                "superseded",
                "integrations_conflicted",
                "integrations_gate_failed",
                "conflict_fix_rounds",
            }, name
        for item in projection["attention"] + summary["attention"]:
            assert set(item) == {
                "kind",
                "reason_code",
                "module_id",
                "split_id",
                "integration_id",
            }, name
    fixture = _fixture("integration_integrated")
    assert fixture["projection"]["integration"]["latest"]["status"] == "pending"
    assert fixture["summary"]["integration"]["status"] == "pending"
    assert fixture["summary"]["accepted_total"] == 2
    # Only the newer candidate lags: m2 is already integrated at its current
    # verification, m1 waits with its older version in the branch.
    m1, m2 = _module(fixture, "m1"), _module(fixture, "m2")
    assert m1["integration"]["status"] == "pending"
    assert m1["integration"]["integrated_verification_id"] != m1["integration"]["verification_id"]
    assert m2["integration"]["status"] == "integrated"
    assert m2["integration"]["integrated_verification_id"] == m2["integration"]["verification_id"]
    assert fixture["summary"]["integrated_total"] == 1
    assert fixture["projection"]["attention"] == []


def test_fixture_integration_pending_running() -> None:
    fixture = _fixture("integration_pending_running")
    assert _module(fixture, "m1")["integration"]["status"] == "running"
    assert _module(fixture, "m2")["integration"]["status"] == "pending"
    assert fixture["summary"]["integrated_total"] == 0
    assert fixture["projection"]["attention"] == []


def test_fixture_integration_conflicted() -> None:
    fixture = _fixture("integration_conflicted")
    assert _module(fixture, "ma")["integration"]["status"] == "integrated"
    mb = _module(fixture, "mb")
    assert mb["integration"]["status"] == "conflicted"
    assert mb["integration"]["reason_code"] == "board_integration_conflict"
    assert mb["integration"]["conflict_path_count"] == 1
    assert mb["integration"]["integrated_verification_id"] is None
    assert mb["counters"]["integrations_conflicted"] == 1
    assert mb["counters"]["conflict_fix_rounds"] == 1
    mc = _module(fixture, "mc")
    assert mc["integration"]["status"] == "waiting"
    assert mc["integration"]["reason_code"] == "board_integration_waiting_for_dependency"
    assert mb["attention"] == {
        "kind": "owner",
        "reason_code": "board_attention_integration_conflict",
    }
    sidecar = _integration_fixture("integration_conflicted")
    assert sidecar["status"] == "integrated"
    conflicts = next(entry for entry in sidecar["items"] if entry["module_id"] == "mb")["conflicts"]
    assert conflicts == [{"path": "docs/shared.txt", "attributed_module_ids": ["ma", "mb"]}]
    event = next(
        event
        for event in fixture["projection"]["events"]
        if event["kind"] == "integration"
        and event["data"]["integration_id"] == sidecar["integration_id"]
    )
    assert event["module_id"] is None
    assert event["actor"] == {"kind": "infrastructure", "participant_id": None}
    assert event["data"]["conflicts"] == [
        {
            "module_id": "mb",
            "conflict_path_count": 1,
            "attributed_module_ids": ["ma", "mb"],
            "fell_back": False,
        }
    ]
    assert event["data"]["waiting_module_ids"] == ["mc"]


def test_fixture_integration_fallback_to_incumbent() -> None:
    fixture = _fixture("integration_fallback_to_incumbent")
    m1 = _module(fixture, "m1")
    assert m1["integration"]["status"] == "conflicted"
    assert m1["integration"]["integrated_verification_id"] is not None
    assert m1["integration"]["integrated_verification_id"] != m1["integration"]["verification_id"]
    assert _module(fixture, "m2")["integration"]["status"] == "integrated"
    assert fixture["summary"]["integrated_total"] == 1
    sidecar = _integration_fixture("integration_fallback_to_incumbent")
    assert sidecar["status"] == "integrated"
    assert sidecar["green_head_commit"] == fixture["projection"]["integration"]["green_head_commit"]


def test_fixture_integration_dependency_upgrade() -> None:
    fixture = _fixture("integration_dependency_upgrade")
    # The upgraded newcomer is the pinned culprit; the incumbent it depends
    # on stays integrated: a newcomer never makes an incumbent conflicted.
    assert _module(fixture, "m1")["integration"]["status"] == "conflicted"
    assert _module(fixture, "m2")["integration"]["status"] == "integrated"
    assert _module(fixture, "m1")["counters"]["integrations_conflicted"] == 1


def test_fixture_integration_gate_failed() -> None:
    fixture = _fixture("integration_gate_failed")
    m2 = _module(fixture, "m2")
    assert m2["integration"]["status"] == "gate_failed"
    assert m2["integration"]["reason_code"] == "board_integration_gate_failed"
    assert m2["integration"]["gate_ids"] == ["patch_diff_check"]
    assert m2["counters"]["integrations_gate_failed"] == 1
    assert _module(fixture, "m1")["integration"]["status"] == "integrated"
    room_items = [item for item in fixture["projection"]["attention"] if item["integration_id"]]
    assert room_items == [
        {
            "kind": "lead",
            "reason_code": "board_attention_integration_gate_failed",
            "module_id": None,
            "split_id": None,
            "integration_id": fixture["projection"]["integration"]["latest"]["integration_id"],
        }
    ]
    sidecar = _integration_fixture("integration_gate_failed")
    assert sidecar["status"] == "gate_failed"
    assert sidecar["result_commit"] is None
    assert sidecar["gates"][0]["status"] == "failed"
    assert sidecar["gates"][0]["output_tail"]["untrusted"] is True


def test_fixture_integration_error() -> None:
    fixture = _fixture("integration_error")
    assert _module(fixture, "m1")["integration"]["status"] == "error"
    assert (
        _module(fixture, "m1")["integration"]["reason_code"]
        == "board_integration_attempts_exhausted"
    )
    room_items = [item for item in fixture["projection"]["attention"] if item["integration_id"]]
    assert room_items == [
        {
            "kind": "operator",
            "reason_code": "board_attention_integration_error",
            "module_id": None,
            "split_id": None,
            "integration_id": fixture["projection"]["integration"]["latest"]["integration_id"],
        }
    ]


def test_fixture_review_endorsed_integrated() -> None:
    fixture = _fixture("review_endorsed_integrated")
    assert fixture["projection"]["capabilities"]["reviews"] == 1
    module = _module(fixture, "m1")
    assert module["review"]["status"] == "endorsed"
    assert module["accepted"] is True
    assert module["integration"]["status"] == "integrated"
    assert fixture["summary"]["integrated_total"] == 1


def test_mcp_read_charters_carry_integration(tmp_path: Path) -> None:
    ctx = build_scenario("integration_fallback_to_incumbent", tmp_path)
    store = ctx["store"]
    owner = ctx["members"][1]
    view = store.read(
        conversation_id=ctx["conversation_id"],
        participant_id=owner.participant_id,
        caller_identity=f"god:testsess:{owner.participant_id}",
        observation_id=ctx["leases"][owner.participant_id]["observation_id"],
        lease_token=ctx["leases"][owner.participant_id]["lease_token"],
        client_request_id="read-integration-1",
        now=NOW,
    )
    charters = {item["module_id"]: item for item in view["charters"]}
    assert charters["m1"]["integration"]["status"] == "conflicted"
    assert charters["m1"]["integration"]["conflict_path_count"] == 1
    assert charters["m2"]["integration"]["status"] == "integrated"
    dumped = json.dumps(view)
    assert '"conflicts"' not in dumped


def test_owner_view_carries_integration_and_markdown(tmp_path: Path) -> None:
    ctx = build_scenario("integration_gate_failed", tmp_path)
    owner = ctx["members"][2]
    view = ctx["store"].owner_view(
        conversation_id=ctx["conversation_id"], participant_id=owner.participant_id
    )
    mine = next(item for item in view["my_modules"] if item["module_id"] == "m2")
    assert mine["integration"]["status"] == "gate_failed"
    assert "conflicts" not in mine["integration"]
    assert "path" not in mine["integration"]
    target = tmp_path / "board-view"
    target.mkdir()
    materialize_owner_board_view(ctx["db"], ctx["conversation_id"], owner.participant_id, target)
    charter_md = (target / "charter.md").read_text(encoding="utf-8")
    assert "- Integration: gate_failed" in charter_md
    assert "docs/" not in charter_md.split("- Integration:")[1].split("\n")[0]


def test_revision_changes_when_integration_claimed_without_new_activity(
    tmp_path: Path,
) -> None:
    ctx = build_scenario("verified", tmp_path)
    store = ctx["store"]
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=NOW) is not None
    with RoomDatabase(ctx["db"]).connect() as conn:
        before = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    # Claiming pending -> running writes no activity, but flips the revision.
    claimed = store.claim_next_board_integration(worker_id="w1", now=NOW)
    assert claimed is not None
    with RoomDatabase(ctx["db"]).connect() as conn:
        after = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    assert after["board_seq"] == before["board_seq"]
    assert after["revision"] != before["revision"]
    assert after["revision"].startswith(f"{after['board_seq']}:")
    running = next(item for item in after["modules"] if item["module_id"] == "alpha")
    assert running["integration"]["status"] == "running"


def test_integration_detail_counts_invalid_paths_without_listing(tmp_path: Path) -> None:
    ctx = build_scenario("verified", tmp_path)
    store = ctx["store"]
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=NOW) is not None
    claimed = store.claim_next_board_integration(worker_id="w1", now=NOW)
    assert claimed is not None
    assert any(item["module_id"] == "alpha" for item in claimed["items"])
    store.complete_board_integration(
        integration_id=str(claimed["integration_id"]),
        lease_token=str(claimed["lease_token"]),
        status="conflicted",
        reason_code="board_integration_conflict",
        green_after=claimed["green_before"],
        result_commit=None,
        gates=[],
        evidence={},
        items=[
            {
                "module_id": "alpha",
                "status": "conflicted",
                "applied_verification_id": None,
                "conflicts": [
                    {"path": "src/alpha/a.py", "attributed_module_ids": ["alpha"]},
                    {"path": "src/\u202ereversed.py", "attributed_module_ids": []},
                ],
                "conflicts_total": 2,
                "reason_code": "board_integration_conflict",
            }
        ],
        now=NOW,
    )
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        detail = build_integration_detail(
            conn, ctx["conversation_id"], str(claimed["integration_id"])
        )
    assert detail is not None
    item = detail["items"][0]
    # The bidirectional-control path is counted in conflicts_total but never
    # listed, exactly like an invalid Finding.path.
    assert item["conflicts_total"] == 2
    assert item["conflicts"] == [{"path": "src/alpha/a.py", "attributed_module_ids": ["alpha"]}]
    with RoomDatabase(ctx["db"]).connect() as conn:
        projection = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    module = next(item for item in projection["modules"] if item["module_id"] == "alpha")
    assert module["integration"]["conflict_path_count"] == 2
    event = next(event for event in projection["events"] if event["kind"] == "integration")
    assert event["data"]["conflicts"][0]["conflict_path_count"] == 2
    assert "path" not in event["data"]["conflicts"][0]


# ---------------------------------------------------------------------------
# injection_text
# ---------------------------------------------------------------------------


def test_injection_fixture_sanitizes_and_wraps() -> None:
    fixture = _fixture("injection_text")
    dumped = json.dumps(fixture)
    assert "\x1b" not in dumped
    for char in BIDI_CHARS:
        assert char not in dumped
    assert INJECTION_PROMPT in dumped

    def walk(value: Any, path: tuple[str, ...], in_text: bool) -> None:
        if isinstance(value, dict):
            text_child = value.get("text") if value.get("untrusted") is True else None
            for key, item in value.items():
                walk(item, (*path, key), in_text=(key == "text" and text_child is not None))
            if text_child is not None:
                assert isinstance(text_child, str)
                assert value["truncated"] in (True, False)
            return
        if isinstance(value, list):
            for item in value:
                walk(item, (*path, "[]"), in_text)
            return
        if isinstance(value, str) and INJECTION_PROMPT in value:
            assert in_text, f"injection outside AgentText.text at {path}"

    walk(fixture, (), False)

    alpha = _module(fixture, "alpha")
    assert alpha["title"]["untrusted"] is True
    assert alpha["title"]["truncated"] is True
    assert len(alpha["title"]["text"]) == 120
    progress = next(
        event for event in fixture["projection"]["events"] if event["kind"] == "progress"
    )
    assert len(progress["data"]["claims"]) == 8
    assert progress["data"]["claims_total"] == 10
    for claim in progress["data"]["claims"]:
        assert claim["untrusted"] is True
        assert len(claim["text"]) == 200
        assert claim["truncated"] is True
    assert len(progress["data"]["summary"]["text"]) == 400
    assert progress["data"]["summary"]["truncated"] is True
    question = next(
        event for event in fixture["projection"]["events"] if event["kind"] == "question"
    )
    assert len(question["data"]["question"]["text"]) == 400
    assert question["data"]["question"]["truncated"] is True
    dumped_summary = json.dumps(fixture["summary"])
    assert '"untrusted"' not in dumped_summary
    assert '"text"' not in dumped_summary


def test_injection_lengths_bounded() -> None:
    fixture = _fixture("injection_text")

    def texts(value: Any) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            if value.get("untrusted") is True and isinstance(value.get("text"), str):
                found.append(value["text"])
            for item in value.values():
                found.extend(texts(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(texts(item))
        return found

    for text in texts(fixture["projection"]):
        assert len(text) <= 65536
    assert texts(fixture["summary"]) == []


# ---------------------------------------------------------------------------
# privacy walk over every fixture
# ---------------------------------------------------------------------------

FORBIDDEN_KEYS = frozenset(
    {
        "patch_digest",
        "patch_text",
        "base_commit",
        "payload",
        "content",
        "lease_token",
        "evidence",
        "audience",
        "id",
        "author",
        "changed_paths",
    }
)
DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")

EVENT_DATA_KEYS = {
    "split_proposed": {"split_id", "module_ids"},
    "split_rejected": {"split_id", "decided_via", "grant_id"},
    "charter_assigned": {
        "split_id",
        "owner_participant_id",
        "charter_version",
        "decided_via",
        "grant_id",
    },
    "claimed": set(),
    "contract_published": {"contract_id", "version", "kind", "digest", "rationale"},
    "contract_revised": {"contract_id", "version", "kind", "digest", "rationale"},
    "progress": {"status", "summary", "claims", "claims_total"},
    "question": {"target_participant_id", "question"},
    "verification": {
        "verification_id",
        "status",
        "reason_code",
        "gate_ids",
        "escalated",
        "stacked",
    },
    "review_requested": {
        "review_id",
        "verification_id",
        "rule_id",
        "author_family",
        "reviewer_kind",
        "reviewer_participant_id",
        "reviewer_family",
        "escalated_from",
    },
    "review": {
        "review_id",
        "verdict",
        "findings_count",
        "findings",
        "findings_total",
        "summary",
        "decided_via",
    },
    "integration": {
        "integration_id",
        "status",
        "reason_code",
        "green_head_commit",
        "integrated_module_ids",
        "suspect_module_ids",
        "conflicts",
        "waiting_module_ids",
        "gate_ids",
    },
}


def _walk_privacy(value: Any, path: str) -> None:
    if path.endswith(".patch.text") or path.endswith("patch.text"):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in FORBIDDEN_KEYS, f"forbidden key {key} at {path}"
            _walk_privacy(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_privacy(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if path.endswith(".href"):
            # Split.actions.decide.href is a server-owned API route, not a
            # host absolute path; contract §3.5 requires the /api/... shape.
            assert value.startswith("/api/"), f"unexpected href at {path}: {value[:60]}"
        else:
            assert not value.startswith("/"), f"absolute path at {path}: {value[:60]}"
        assert not DRIVE_RE.match(value), f"drive path at {path}: {value[:60]}"


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_privacy(name: str) -> None:
    fixture = _fixture(name)
    _walk_privacy(fixture, "$")
    for event in fixture["projection"]["events"]:
        assert set(event["data"]) == EVENT_DATA_KEYS[event["kind"]], event
    for event in fixture["events_page"]["events"]:
        assert set(event["data"]) == EVENT_DATA_KEYS[event["kind"]], event


def test_route_fixtures_privacy() -> None:
    for path in sorted(FIXTURE_DIR.glob("*.review.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        _walk_privacy(doc, "$")
    for path in sorted(FIXTURE_DIR.glob("*.material.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        _walk_privacy(doc, "$")
    for path in sorted(FIXTURE_DIR.glob("*.verification.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        _walk_privacy(doc, "$")
    for path in sorted(FIXTURE_DIR.glob("*.integration.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        _walk_privacy(doc, "$")


# ---------------------------------------------------------------------------
# revision
# ---------------------------------------------------------------------------


def test_revision_stable_for_equal_state_and_ignores_server_time(tmp_path: Path) -> None:
    ctx = build_scenario("verified", tmp_path)
    with RoomDatabase(ctx["db"]).connect() as conn:
        first = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
        second = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
        assert compute_revision(first) == first["revision"] == second["revision"]
        later = build_board_projection(
            conn, ctx["conversation_id"], now=SERVER_TIME + timedelta(hours=3)
        )
        assert later["revision"] == first["revision"]
        assert later["server_time"] != first["server_time"]


def test_revision_changes_when_running_without_new_activity(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    reported = _report_done(ctx, 1, "done-1")
    with RoomDatabase(ctx["db"]).connect() as conn:
        before = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    # Claiming pending -> running writes no activity, but flips the revision.
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    assert claimed["verification_id"] == reported["verification_id"]
    with RoomDatabase(ctx["db"]).connect() as conn:
        after = build_board_projection(conn, ctx["conversation_id"], now=SERVER_TIME)
    assert after["board_seq"] == before["board_seq"]
    assert after["revision"] != before["revision"]
    assert after["revision"].startswith(f"{after['board_seq']}:")
    running = next(item for item in after["modules"] if item["module_id"] == "alpha")
    assert running["state"] == "verifying"


# ---------------------------------------------------------------------------
# backend changes: escalated payload + exhaustion activity
# ---------------------------------------------------------------------------


def test_verification_payload_carries_escalated(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    for index in range(3):
        _reported, result = _round(
            ctx,
            f"done-{index + 1}",
            status="failed",
            reason="owner_patch_empty",
            now=_round_time(index),
        )
    assert result["escalated"] is True
    with RoomDatabase(ctx["db"]).connect() as conn:
        row = conn.execute(
            "select * from room_activities where activity_id = ?",
            (result["activity_id"],),
        ).fetchone()
    payload = json.loads(str(row["payload_json"]))
    assert payload["escalated"] is True
    assert payload["status"] == "failed"


def test_attempt_exhaustion_writes_error_activity(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    store = ctx["store"]
    owner = ctx["members"][1]
    reported = _report_done(ctx, 1, "done-1", now=_round_time(0))
    claimed = store.claim_next_board_verification(
        worker_id="w1", lease_ttl_s=60, max_attempts=1, now=_round_time(0)
    )
    assert claimed is not None
    store.abandon_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        reason_code="transient",
        now=_round_time(0) + timedelta(seconds=10),
    )
    assert (
        store.claim_next_board_verification(
            worker_id="w1", lease_ttl_s=60, max_attempts=1, now=_round_time(0)
        )
        is None
    )
    with RoomDatabase(ctx["db"]).connect() as conn:
        row = conn.execute(
            "select * from room_board_verifications where verification_id = ?",
            (reported["verification_id"],),
        ).fetchone()
        assert row["status"] == "error"
        activity = conn.execute(
            "select * from room_activities where activity_id = ?", (row["activity_id"],)
        ).fetchone()
        assert activity is not None
        observations = conn.execute(
            "select * from room_observations where activity_id = ?",
            (row["activity_id"],),
        ).fetchall()
    assert activity["actor_kind"] == "infrastructure"
    assert activity["actor_identity"] == "infrastructure:board-verification"
    payload = json.loads(str(activity["payload_json"]))
    assert payload["status"] == "error"
    assert payload["reason_code"] == "board_verification_attempts_exhausted"
    assert payload["gates"] == []
    assert payload["evidence"] == {}
    assert payload["stacked"] == []
    assert payload["changed_paths"] == []
    assert payload["head_commit"] == row["head_commit"]
    assert payload["escalated"] is False
    audience = json.loads(str(activity["audience_json"]))
    assert audience["participant_ids"] == [owner.participant_id]
    # No wake: nobody gets an observation for the exhaustion activity.
    assert observations == []
    # Idempotent: a second claim pass writes nothing new.
    with RoomDatabase(ctx["db"]).connect() as conn:
        before = conn.execute(
            "select count(*) from room_activities where activity_type = 'board.verification'"
        ).fetchone()[0]
    assert (
        store.claim_next_board_verification(
            worker_id="w1", lease_ttl_s=60, max_attempts=1, now=_round_time(1)
        )
        is None
    )
    with RoomDatabase(ctx["db"]).connect() as conn:
        after = conn.execute(
            "select count(*) from room_activities where activity_type = 'board.verification'"
        ).fetchone()[0]
    assert after == before


# ---------------------------------------------------------------------------
# MCP read / owner view / events page / contract detail
# ---------------------------------------------------------------------------


def test_mcp_read_charters_carry_lifecycle_and_state(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    store = ctx["store"]
    owner = ctx["members"][1]
    view = store.read(
        conversation_id=ctx["conversation_id"],
        participant_id=owner.participant_id,
        caller_identity=f"god:testsess:{owner.participant_id}",
        observation_id=ctx["leases"][owner.participant_id]["observation_id"],
        lease_token=ctx["leases"][owner.participant_id]["lease_token"],
        client_request_id="read-1",
        now=NOW,
    )
    charters = {item["module_id"]: item for item in view["charters"]}
    assert charters["alpha"]["lifecycle"] == "assigned"
    assert charters["alpha"]["state"] == "assigned"
    assert set(charters["alpha"]) >= {
        "module_id",
        "version",
        "owner_participant_id",
        "status",
        "charter",
        "lifecycle",
        "state",
    }


def test_owner_view_and_markdown_carry_state(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner = ctx["members"][1]
    view = ctx["store"].owner_view(
        conversation_id=ctx["conversation_id"], participant_id=owner.participant_id
    )
    mine = next(item for item in view["my_modules"] if item["module_id"] == "alpha")
    assert mine["lifecycle"] == "assigned"
    assert mine["state"] == "assigned"
    target = tmp_path / "board-view"
    target.mkdir()
    materialize_owner_board_view(ctx["db"], ctx["conversation_id"], owner.participant_id, target)
    assert "- State: assigned" in (target / "charter.md").read_text(encoding="utf-8")


def test_events_page_pagination_and_reset(tmp_path: Path) -> None:
    ctx = build_scenario("verified", tmp_path)
    with RoomDatabase(ctx["db"]).connect() as conn:
        full = board_events_page(conn, ctx["conversation_id"], after_seq=0, limit=100)
        assert full["has_more"] is False
        assert full["reset"] is False
        assert [event["seq"] for event in full["events"]] == sorted(
            event["seq"] for event in full["events"]
        )
        first = board_events_page(conn, ctx["conversation_id"], after_seq=0, limit=2)
        assert len(first["events"]) == 2
        assert first["has_more"] is True
        second = board_events_page(
            conn, ctx["conversation_id"], after_seq=first["events"][-1]["seq"], limit=100
        )
        assert [event["seq"] for event in second["events"]] == [
            event["seq"] for event in full["events"][2:]
        ]
        ahead = board_events_page(
            conn, ctx["conversation_id"], after_seq=full["board_seq"] + 10, limit=100
        )
        assert ahead["events"] == []
        assert ahead["reset"] is True
        assert ahead["revision"] == full["revision"]


def test_contract_detail_shape_and_versions(tmp_path: Path) -> None:
    ctx = build_scenario("contract_revised_stale_dependent", tmp_path)
    with RoomDatabase(ctx["db"]).connect() as conn:
        detail = build_contract_detail(conn, ctx["conversation_id"], "api.backend", None)
    assert detail is not None
    assert detail["schema_version"] == "room_board_contract/v2"
    assert detail["version"] == 2
    assert [entry["version"] for entry in detail["versions"]] == [1, 2]
    assert detail["content"] == {
        "text": '{"backend": 2}',
        "untrusted": True,
        "truncated": False,
    }
    with RoomDatabase(ctx["db"]).connect() as conn:
        pinned = build_contract_detail(conn, ctx["conversation_id"], "api.backend", 1)
        assert pinned is not None
        assert pinned["version"] == 1
        assert pinned["content"]["text"] == '{"backend": 1}'
        assert build_contract_detail(conn, ctx["conversation_id"], "api.missing", None) is None
        assert build_contract_detail(conn, ctx["conversation_id"], "api.backend", 9) is None


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------


def test_board_projection_performance(tmp_path: Path) -> None:
    from tests.xmuse.room_fixtures import RoomTestStore

    db = tmp_path / "perf.db"
    conversation = RoomTestStore(db).create_conversation("perf room")
    with RoomDatabase(db).connect() as conn:
        start_seq = int(
            conn.execute(
                "select coalesce(max(seq), 0) from room_activities where conversation_id = ?",
                (conversation.id,),
            ).fetchone()[0]
        )
        rows = [
            (
                f"activity_perf_{index:05d}",
                conversation.id,
                start_seq + index + 1,
                "board.progress",
                "participant",
                "god:testsess:perf",
                None,
                "causation_perf",
                f"board_correlation_perf_{index:05d}",
                "room",
                json.dumps(
                    {
                        "type": "board",
                        "conversation_id": conversation.id,
                        "participant_ids": [],
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "room_board_activity/v1",
                        "progress_id": f"progress_{index:05d}",
                        "module_id": "alpha",
                        "status": "working",
                        "summary": f"steady {index}",
                        "claims": [],
                        "content": "perf",
                    }
                ),
                0,
                "active",
                "2026-01-01T00:00:00.000000Z",
            )
            for index in range(10_000)
        ]
        conn.executemany(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, causal_depth,
                delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
    # Wall-clock bounds on shared CI are noisy: take the best of several runs so a
    # scheduler hiccup cannot fail the test, while an algorithmic regression over
    # 10,000 activities (every run slow) still does.
    build_samples: list[float] = []
    page_samples: list[float] = []
    with RoomDatabase(db).connect() as conn:
        for _ in range(5):
            begin = time.perf_counter()
            projection = build_board_projection(conn, conversation.id, now=SERVER_TIME)
            summary = build_board_summary(projection)
            build_samples.append((time.perf_counter() - begin) * 1000)
            assert summary["modules_total"] == 0
            assert projection["board_seq"] == start_seq + 10_000
            assert len(projection["events"]) == 50
            begin = time.perf_counter()
            page = board_events_page(conn, conversation.id, after_seq=0, limit=100)
            page_samples.append((time.perf_counter() - begin) * 1000)
            assert len(page["events"]) == 100
    # The events page builds the full projection once to derive its revision, so
    # its bound is the projection bound plus the page read.
    assert min(build_samples) < 250, f"projection+summary samples ms: {build_samples}"
    assert min(page_samples) < 250, f"events page samples ms: {page_samples}"
