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
    NOW,
    SCENARIOS,
    SERVER_TIME,
    _approved_board,
    _report_done,
    _round,
    _round_time,
    build_scenario,
)
from xmuse_core.chat.room_board_projection import (
    CharterDependency,
    ProgressFact,
    RevisedContract,
    StackedRef,
    VerificationFact,
    agent_text,
    board_events_page,
    build_board_projection,
    build_board_summary,
    build_contract_detail,
    compute_counters,
    compute_escalated,
    compute_revision,
    compute_stale_dependents,
    derive_lifecycle,
    derive_module_attention,
    derive_state,
    derive_verification_axis,
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
    "split_rejected": {"split_id", "decided_via"},
    "charter_assigned": {"split_id", "owner_participant_id", "charter_version", "decided_via"},
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
}


def _walk_privacy(value: Any, path: str) -> None:
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
