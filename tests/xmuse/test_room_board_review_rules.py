"""Comprehensive tests for room board review rules, store, policy, and escalation.

Task M2a-v2 Part A requirement coverage:
- Policy off vs cross_family (verification passed creates review only on cross_family)
- Review digest binding (pure function, patch byte sensitivity)
- Verdict limits and path validation (both participant and operator paths)
- Operator check order (asserting nothing changed on failure)
- Truncated material refuses endorse but allows object
- Marker function (bidi, ESC, NUL, DEL, \\t/\\n kept, count) and marker-safe truncation
- Cross-conversation isolation (review_material, review_detail, verification_detail)
- Material excludes stacked patches
- Escalation: 3 reasons, idempotency, former reviewer rejected, activity appended, wakes nobody
- Re-applying assign_cross_family_reviewer to rule_inputs matches picked_participant_id
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_api_models import (
    ParticipantInit,
    RoomCollaborationInit,
    RoomConversationCreate,
)
from xmuse_core.chat.room_board import (
    BOARD_REVIEW_RULE_ID,
    MAX_VERIFICATION_PATCH_BYTES,
    RoomBoardStore,
    _truncate_marked_patch,
    assign_cross_family_reviewer,
    mark_hidden_characters,
    normalize_review_findings,
    normalize_review_path,
    normalize_review_summary,
    normalize_review_verdict,
    review_digest,
)
from xmuse_core.chat.room_board_verification import (
    RoomBoardVerificationWorker,
)
from xmuse_core.chat.room_collaboration import (
    write_room_collaboration_policy_conn,
)
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_setup import RoomSetupError, RoomSetupService

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(seconds=10)
DIGEST_A = "sha256:" + "a" * 64


def _create_test_room(
    tmp_path: Path,
    *,
    review_policy: str = "cross_family",
    extra_family: bool = True,
):
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("review-test-room")
    participants = ParticipantStore(db)
    lead = participants.add(
        conversation_id=conversation.id,
        role="lead",
        display_name="Lead",
        cli_kind="opencode",
        model="m",
    )
    author = participants.add(
        conversation_id=conversation.id,
        role="backend",
        display_name="Backend",
        cli_kind="opencode",
        model="m",
    )
    members = [lead, author]
    if extra_family:
        reviewer = participants.add(
            conversation_id=conversation.id,
            role="frontend",
            display_name="Frontend",
            cli_kind="claude",
            model="m",
        )
        members.append(reviewer)
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=lead.participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy=review_policy,
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    return db, conversation.id, members


def _claim_obs(db: Path, conversation_id: str, participant, *, owner: str):
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=owner,
        lease_ttl_s=300.0,
        now=T0,
    )
    assert claimed is not None
    return claimed["observation"]


def _lease_kwargs(participant, observation, *, request_id: str) -> dict[str, Any]:
    return {
        "conversation_id": observation["conversation_id"],
        "participant_id": participant.participant_id,
        "caller_identity": f"god:testsess:{participant.participant_id}",
        "observation_id": observation["observation_id"],
        "lease_token": observation["lease_token"],
        "client_request_id": request_id,
        "now": NOW,
    }


def _setup_board(tmp_path: Path, *, review_policy: str = "cross_family", extra_family: bool = True):
    db, conversation_id, members = _create_test_room(
        tmp_path, review_policy=review_policy, extra_family=extra_family
    )
    store = RoomBoardStore(db)
    leases = {
        member.participant_id: _claim_obs(db, conversation_id, member, owner=f"host-{i}")
        for i, member in enumerate(members)
    }
    lead, author = members[0], members[1]
    modules = [
        {
            "module_id": "alpha",
            "title": "Alpha",
            "paths": ["src/alpha/**"],
            "provides": ["api.alpha"],
            "depends": [],
            "acceptance": ["alpha ok"],
            "report_to": lead.participant_id,
        },
    ]
    assignments = {"alpha": author.participant_id}
    contracts = [
        {
            "contract_id": "api.alpha",
            "provider_module_id": "alpha",
            "kind": "api_schema",
            "content": '{"alpha": 1}',
            "rationale": "alpha",
        },
    ]
    proposed = store.propose_split(
        **_lease_kwargs(lead, leases[lead.participant_id], request_id="p1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    return {
        "db": db,
        "conversation_id": conversation_id,
        "members": members,
        "store": store,
        "leases": leases,
    }


def _pass_alpha(ctx, request_id: str, *, patch_text: str = "diff --git a/a.py b/a.py\n"):
    owner = ctx["members"][1]
    reported = ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id=request_id),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    result = ctx["store"].complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=["src/alpha/a.py"],
        gates=[{"gate_id": "pytest", "status": "passed", "exit_code": 0}],
        evidence={},
        patch_text=patch_text,
        now=NOW + timedelta(seconds=30),
    )
    return reported, result


# ---------------------------------------------------------------------------
# 1. review_policy (off vs cross_family) and RoomSetup idempotency
# ---------------------------------------------------------------------------


def test_review_policy_off_vs_on(tmp_path: Path) -> None:
    # 1. Policy off: passed verification creates no review
    off_dir = tmp_path / "off"
    ctx_off = _setup_board(off_dir, review_policy="off")
    _, result_off = _pass_alpha(ctx_off, "done-off")
    assert result_off.get("review_id") is None
    assert ctx_off["store"].review_policy(ctx_off["conversation_id"]) == "off"
    with RoomDatabase(ctx_off["db"]).connect(readonly=True) as conn:
        count = conn.execute("select count(*) from room_board_reviews").fetchone()[0]
        assert count == 0

    # 2. Policy on: passed verification creates one pending review
    on_dir = tmp_path / "on"
    ctx_on = _setup_board(on_dir, review_policy="cross_family")
    _, result_on = _pass_alpha(ctx_on, "done-on")
    assert result_on.get("review_id") is not None
    assert ctx_on["store"].review_policy(ctx_on["conversation_id"]) == "cross_family"
    with RoomDatabase(ctx_on["db"]).connect(readonly=True) as conn:
        count = conn.execute("select count(*) from room_board_reviews").fetchone()[0]
        assert count == 1


def test_room_setup_idempotency_fingerprint_includes_review_policy(tmp_path: Path) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    setup_service = RoomSetupService(tmp_path)
    participants = [
        ParticipantInit(role="lead", display_name="Lead", cli_kind="codex", model="m1"),
        ParticipantInit(role="worker", display_name="Worker", cli_kind="codex", model="m2"),
    ]
    req1 = RoomConversationCreate(
        title="Setup Room",
        client_request_id="req-same-id",
        initial_participants=participants,
        collaboration=RoomCollaborationInit(mode="broadcast", review_policy="off"),
    )
    res1 = setup_service.create_conversation(req1)

    # Identical replay returns exact same result
    res1_replay = setup_service.create_conversation(req1)
    assert res1_replay["id"] == res1["id"]

    # Different review_policy with same client_request_id raises idempotency conflict
    req2 = RoomConversationCreate(
        title="Setup Room",
        client_request_id="req-same-id",
        initial_participants=participants,
        collaboration=RoomCollaborationInit(mode="broadcast", review_policy="cross_family"),
    )
    with pytest.raises(RoomSetupError) as exc_info:
        setup_service.create_conversation(req2)
    assert exc_info.value.code == "room_setup_idempotency_conflict"


# ---------------------------------------------------------------------------
# 2. Review.digest binding pure function
# ---------------------------------------------------------------------------


def test_review_digest_pure_function() -> None:
    d1 = review_digest(
        review_id="rev_1",
        verification_id="ver_1",
        head_commit="commit_1",
        patch_text="diff --git a/x.py b/x.py\n+hello\n",
    )
    assert d1.startswith("sha256:")
    assert len(d1) == 7 + 64
    # Pinned to the contract formula: sha256 of the compact sorted-key JSON of
    # {review_id, verification_id, head_commit, patch_sha256}.
    assert d1 == "sha256:969d607a6c79c65af65031e6611a7430b11c21d41d0910a031a68c8e284a73b2"

    # Different patch byte gives different digest
    d2 = review_digest(
        review_id="rev_1",
        verification_id="ver_1",
        head_commit="commit_1",
        patch_text="diff --git a/x.py b/x.py\n+hallo\n",
    )
    assert d1 != d2

    # Different head commit gives different digest
    d3 = review_digest(
        review_id="rev_1",
        verification_id="ver_1",
        head_commit="commit_2",
        patch_text="diff --git a/x.py b/x.py\n+hello\n",
    )
    assert d1 != d3

    # Different verification_id gives different digest
    d4 = review_digest(
        review_id="rev_1",
        verification_id="ver_2",
        head_commit="commit_1",
        patch_text="diff --git a/x.py b/x.py\n+hello\n",
    )
    assert d1 != d4

    # Identical inputs give identical digest
    d1_again = review_digest(
        review_id="rev_1",
        verification_id="ver_1",
        head_commit="commit_1",
        patch_text="diff --git a/x.py b/x.py\n+hello\n",
    )
    assert d1 == d1_again


# ---------------------------------------------------------------------------
# 3. Marker function and marker-safe truncation
# ---------------------------------------------------------------------------


def test_mark_hidden_characters_and_counts() -> None:
    # ESC, NUL, DEL, bidi controls replaced; \n and \t kept
    sample = (
        "hello\tworld\n"
        "\x1b[31mred\x1b[0m\n"  # 2 ESC characters
        "null\x00del\x7f\n"  # NUL + DEL
        "bidi\u200ehere\u202e\n"  # 2 bidi characters (LRM + RLO)
        "arabic\u061cmark\n"  # ALM
        "isolate\u2066test\u2069"  # LRI + PDI
    )
    marked, count = mark_hidden_characters(sample)
    assert count == 9
    assert "\t" in marked
    assert "\n" in marked
    assert "<U+001B>" in marked
    assert "<U+0000>" in marked
    assert "<U+007F>" in marked
    assert "<U+200E>" in marked
    assert "<U+202E>" in marked
    assert "<U+061C>" in marked
    assert "<U+2066>" in marked
    assert "<U+2069>" in marked
    assert "\x1b" not in marked
    assert "\x00" not in marked
    assert "\x7f" not in marked
    assert "\u200e" not in marked


def test_marker_safe_truncation() -> None:
    # 1. Fits within limit -> no truncation
    text = "line1\nline2\n"
    res, trunc = _truncate_marked_patch(text, limit=100)
    assert res == text
    assert trunc is False

    # 2. Line boundary truncation
    lines = ["a" * 50 + "\n", "b" * 50 + "\n", "c" * 50 + "\n"]
    multiline = "".join(lines)
    cut, trunc = _truncate_marked_patch(multiline, limit=110)
    assert trunc is True
    assert cut == lines[0] + lines[1]
    assert cut.endswith("\n")

    # 3. Single line longer than limit with marker -> never cuts inside a marker
    marker_line = "prefix_" + "<U+202E>" + "_suffix"
    # Marker is 8 bytes: <U+202E>. prefix_ is 7 bytes. Total before marker is 7.
    # If limit is 10, prefix_ (7) fits, but marker (8) would need 15.
    # It must NOT cut as prefix_<U+...
    cut, trunc = _truncate_marked_patch(marker_line, limit=10)
    assert trunc is True
    assert cut == "prefix_"
    assert "<" not in cut


# ---------------------------------------------------------------------------
# 4. Verdict limits and path-rule rejection (both paths)
# ---------------------------------------------------------------------------


def test_verdict_limits_and_path_validation(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family")
    _, result = _pass_alpha(ctx, "done-limits")
    reviewer = ctx["members"][2]
    review_id = result["review_id"]
    lease = _lease_kwargs(reviewer, ctx["leases"][reviewer.participant_id], request_id="rev-lim")

    # Summary validation: blank or > 4000
    with pytest.raises(ValueError, match="room_board_review_summary_invalid"):
        normalize_review_summary("")
    with pytest.raises(ValueError, match="room_board_review_summary_invalid"):
        normalize_review_summary("   ")
    with pytest.raises(ValueError, match="room_board_review_summary_invalid"):
        normalize_review_summary("x" * 4001)
    assert normalize_review_summary("  valid summary  ") == "valid summary"

    # Path validation:
    assert normalize_review_path(None) is None
    assert normalize_review_path("src/core/main.py") == "src/core/main.py"
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("/abs/path.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("C:drive.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("D:/drive.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("back\\slash.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo/./bar.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo/../bar.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo//bar.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo/bar/")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo/\x00/bar.py")
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("foo/\u202ebar.py")  # category Cf
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_path("a/" * 260)  # > 512 chars

    # Findings limits: > 32 findings
    too_many = [{"severity": "minor", "text": f"nit {i}"} for i in range(33)]
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_findings(too_many)

    # Finding text: blank or > 1000
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_findings([{"severity": "minor", "text": ""}])
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_findings([{"severity": "minor", "text": "x" * 1001}])

    # Finding severity invalid:
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_findings([{"severity": "critical", "text": "bad"}])

    # Object without blocker or major:
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_verdict("object", [])
    with pytest.raises(ValueError, match="room_board_review_findings_invalid"):
        normalize_review_verdict("object", [{"severity": "minor", "text": "nit"}])
    assert (
        normalize_review_verdict("object", [{"severity": "major", "text": "big bug"}]) == "object"
    )
    assert (
        normalize_review_verdict("object", [{"severity": "blocker", "text": "block"}]) == "object"
    )
    assert normalize_review_verdict("endorse", []) == "endorse"

    # Tested via participant review tool path
    with pytest.raises(ValueError, match="room_board_review_summary_invalid"):
        ctx["store"].review(
            **lease,
            review_id=review_id,
            verdict="endorse",
            summary="",
            findings=[],
        )


# ---------------------------------------------------------------------------
# 5. Operator check order and nothing-changed invariant
# ---------------------------------------------------------------------------


def test_operator_check_order_and_invariants(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=False)
    _, result = _pass_alpha(ctx, "done-op")
    review_id = result["review_id"]
    store = ctx["store"]
    conv_id = ctx["conversation_id"]

    # Initial state
    material = store.review_material(conv_id, review_id)
    valid_digest = material["digest"]

    def _assert_review_unchanged():
        row = store.review_detail(conv_id, review_id)
        assert row["review"]["status"] == "pending"
        assert row["review"]["reviewer_kind"] == "operator"
        with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
            act_count = conn.execute(
                "select count(*) from room_activities where activity_type = 'board.review'"
            ).fetchone()[0]
            assert act_count == 0

    # Check 1: limits (invalid summary / findings)
    with pytest.raises(ValueError, match="room_board_review_summary_invalid"):
        store.decide_review(
            conversation_id=conv_id,
            review_id=review_id,
            verdict="endorse",
            summary="",
            findings=[],
            expected_digest=valid_digest,
            operator_identity="operator:local",
        )
    _assert_review_unchanged()

    # Check 2: decided_via must be web
    with pytest.raises(ValueError, match="room_board_decided_via_invalid"):
        store.decide_review(
            conversation_id=conv_id,
            review_id=review_id,
            verdict="endorse",
            summary="looks good",
            findings=[],
            expected_digest=valid_digest,
            operator_identity="operator:local",
            decided_via="cli",
        )
    _assert_review_unchanged()

    # Check 3: review exists in that conversation (other conversation is unknown)
    other_conv = RoomTestStore(ctx["db"]).create_conversation("other")
    with pytest.raises(ValueError, match="room_board_review_unknown"):
        store.decide_review(
            conversation_id=other_conv.id,
            review_id=review_id,
            verdict="endorse",
            summary="looks good",
            findings=[],
            expected_digest=valid_digest,
            operator_identity="operator:local",
        )
    _assert_review_unchanged()

    # Check 4: pending and reviewer_kind == operator
    # If we temporarily simulate non-operator or non-pending
    with RoomDatabase(ctx["db"]).connect() as conn:
        conn.execute(
            "update room_board_reviews set reviewer_kind = 'participant' where review_id = ?",
            (review_id,),
        )
        conn.commit()
    with pytest.raises(ValueError, match="room_board_review_not_pending"):
        store.decide_review(
            conversation_id=conv_id,
            review_id=review_id,
            verdict="endorse",
            summary="looks good",
            findings=[],
            expected_digest=valid_digest,
            operator_identity="operator:local",
        )
    with RoomDatabase(ctx["db"]).connect() as conn:
        conn.execute(
            "update room_board_reviews set reviewer_kind = 'operator' where review_id = ?",
            (review_id,),
        )
        conn.commit()
    _assert_review_unchanged()

    # Check 5: expected_digest required and equal
    with pytest.raises(ValueError, match="room_board_review_digest_mismatch"):
        store.decide_review(
            conversation_id=conv_id,
            review_id=review_id,
            verdict="endorse",
            summary="looks good",
            findings=[],
            expected_digest="sha256:wrong",
            operator_identity="operator:local",
        )
    _assert_review_unchanged()


# ---------------------------------------------------------------------------
# 6. Truncated material: refuses endorse, allows object
# ---------------------------------------------------------------------------


def test_truncated_material_refuses_endorse_allows_object(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=False)
    # Generate patch that fits under MAX_VERIFICATION_PATCH_BYTES (200,000)
    # but whose marked representation exceeds REVIEW_MATERIAL_PATCH_LIMIT_BYTES (256 KiB)
    large_patch = "diff --git a/big.py b/big.py\n" + ("+\x01" * 80 + "\n") * 1000
    assert len(large_patch.encode("utf-8")) < MAX_VERIFICATION_PATCH_BYTES

    _, result = _pass_alpha(ctx, "done-big", patch_text=large_patch)
    review_id = result["review_id"]
    store = ctx["store"]
    conv_id = ctx["conversation_id"]

    material = store.review_material(conv_id, review_id)
    assert material["patch"]["truncated"] is True
    valid_digest = material["digest"]

    # Endorse must be refused
    with pytest.raises(ValueError, match="room_board_review_material_incomplete"):
        store.decide_review(
            conversation_id=conv_id,
            review_id=review_id,
            verdict="endorse",
            summary="tried to endorse truncated",
            findings=[],
            expected_digest=valid_digest,
            operator_identity="operator:local",
        )
    # Verify review is still pending
    detail = store.review_detail(conv_id, review_id)
    assert detail["review"]["status"] == "pending"

    # Object is allowed!
    decided = store.decide_review(
        conversation_id=conv_id,
        review_id=review_id,
        verdict="object",
        summary="cannot read entire patch",
        findings=[{"severity": "blocker", "text": "patch is too large"}],
        expected_digest=valid_digest,
        operator_identity="operator:local",
    )
    assert decided["status"] == "objected"
    assert decided["verdict"] == "object"


# ---------------------------------------------------------------------------
# 7. Material excludes stacked patches and cross-conversation isolation
# ---------------------------------------------------------------------------


def test_material_excludes_stacked_patches_and_cross_conversation(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=False)
    alpha_own_patch = "diff --git a/a.py b/a.py\n+alpha own code\n"
    reported, result = _pass_alpha(ctx, "done-stacked", patch_text=alpha_own_patch)
    review_id = result["review_id"]
    ver_id = reported["verification_id"]
    store = ctx["store"]
    conv_id = ctx["conversation_id"]

    # Simulate stacked verification result: beta's patch stacked
    with RoomDatabase(ctx["db"]).connect() as conn:
        res = json.loads(
            conn.execute(
                "select result_json from room_board_verifications where verification_id = ?",
                (ver_id,),
            ).fetchone()[0]
        )
        res["stacked"] = [{"module_id": "beta", "verification_id": "ver_beta_1"}]
        conn.execute(
            "update room_board_verifications set result_json = ? where verification_id = ?",
            (json.dumps(res), ver_id),
        )
        conn.commit()

    # Operator review_material returns ONLY alpha's patch text
    mat = store.review_material(conv_id, review_id)
    assert mat["patch"]["text"] == alpha_own_patch
    assert "beta" not in mat["patch"]["text"]

    # Participant tool read _review_material_conn returns ONLY alpha's patch
    author = ctx["members"][1]
    with RoomDatabase(ctx["db"]).connect() as conn:
        p_mat = store._review_material_conn(
            conn,
            conversation_id=conv_id,
            participant_id=author.participant_id,
            review_id=review_id,
        )
    assert p_mat["patch_text"] == alpha_own_patch

    # Cross-conversation isolation tests
    other_conv = RoomTestStore(ctx["db"]).create_conversation("isolated")
    with pytest.raises(ValueError, match="room_board_review_unknown"):
        store.review_material(other_conv.id, review_id)
    with pytest.raises(ValueError, match="room_board_review_unknown"):
        store.review_detail(other_conv.id, review_id)
    with pytest.raises(ValueError, match="room_board_verification_unknown"):
        store.verification_detail(other_conv.id, ver_id)


# ---------------------------------------------------------------------------
# 8. Detail routes and rule_inputs re-application
# ---------------------------------------------------------------------------


def test_review_detail_rule_inputs_reapplication(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=True)
    _, result = _pass_alpha(ctx, "done-detail")
    review_id = result["review_id"]
    store = ctx["store"]
    conv_id = ctx["conversation_id"]

    detail = store.review_detail(conv_id, review_id)
    rule_inputs = detail["rule_inputs"]
    assert rule_inputs["rule_id"] == BOARD_REVIEW_RULE_ID
    assert "eligible" in rule_inputs
    assert rule_inputs["picked_participant_id"] is not None

    # Re-apply assign_cross_family_reviewer to rule_inputs and assert exact match
    picked = assign_cross_family_reviewer(
        author_participant_id=rule_inputs["author_participant_id"],
        author_family=rule_inputs["author_family"],
        candidates=rule_inputs["eligible"],
        pending_loads={item["participant_id"]: item["pending"] for item in rule_inputs["eligible"]},
        last_reviewer_id=rule_inputs["last_reviewer_participant_id"],
    )
    assert picked == rule_inputs["picked_participant_id"]


def test_verification_detail_with_output_tails(tmp_path: Path) -> None:
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=False)
    owner = ctx["members"][1]
    reported = ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-tail"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    ver_id = reported["verification_id"]
    tail_text = "FAILED test_fail.py - AssertionError: 1 != 2"
    ctx["store"].complete_board_verification(
        verification_id=ver_id,
        lease_token=claimed["lease_token"],
        status="failed",
        reason_code="board_verification_gate_failed",
        head_commit="b" * 40,
        patch_digest=DIGEST_A,
        changed_paths=["src/alpha/a.py"],
        gates=[
            {
                "gate_id": "pytest",
                "status": "failed",
                "exit_code": 1,
                "reason_code": "execution_gate_failed",
            }
        ],
        evidence={"output_tails": {"pytest": tail_text}},
        patch_text="diff\n",
        now=NOW + timedelta(seconds=30),
    )

    detail = ctx["store"].verification_detail(ctx["conversation_id"], ver_id)
    assert detail["status"] == "failed"
    assert detail["reason_code"] == "board_verification_gate_failed"
    assert len(detail["gates"]) == 1
    assert detail["gates"][0]["gate_id"] == "pytest"
    assert detail["gates"][0]["output_tail"] == {
        "text": tail_text,
        "truncated": False,
        "untrusted": True,
    }


# ---------------------------------------------------------------------------
# 9. Escalation (§3.10)
# ---------------------------------------------------------------------------


def test_escalation_three_reasons_and_idempotency(tmp_path: Path) -> None:
    # --- Scenario 1: reviewer unavailable (stopped participant) ---
    s1_dir = tmp_path / "s1"
    ctx1 = _setup_board(s1_dir, review_policy="cross_family", extra_family=True)
    _, res1 = _pass_alpha(ctx1, "done-esc-1")
    rev1_id = res1["review_id"]
    reviewer1 = ctx1["members"][2]
    # Stop reviewer participant
    ParticipantStore(ctx1["db"]).update_status(reviewer1.participant_id, "stopped")

    escalated1 = ctx1["store"].escalate_stale_reviews(
        now=NOW + timedelta(seconds=60), response_seconds=3600
    )
    assert len(escalated1) == 1
    assert escalated1[0]["review_id"] == rev1_id
    assert escalated1[0]["reason_code"] == "board_review_reviewer_unavailable"

    # Detail reflects operator assignee and escalation info
    det1 = ctx1["store"].review_detail(ctx1["conversation_id"], rev1_id)
    assert det1["review"]["reviewer_kind"] == "operator"
    assert det1["review"]["reviewer_participant_id"] is None
    assert det1["review"]["escalated_from"]["reason_code"] == "board_review_reviewer_unavailable"
    assert det1["review"]["escalated_from"]["participant_id"] == reviewer1.participant_id

    # Reactivate reviewer1 and verify that calling review(...) is rejected (no longer assignee)!
    ParticipantStore(ctx1["db"]).update_status(reviewer1.participant_id, "active")
    with pytest.raises(ValueError, match="room_board_review_forbidden"):
        ctx1["store"].review(
            **_lease_kwargs(
                reviewer1, ctx1["leases"][reviewer1.participant_id], request_id="rev-old-1"
            ),
            review_id=rev1_id,
            verdict="endorse",
            summary="too late",
            findings=[],
        )

    # Idempotency: second call does nothing
    escalated1_again = ctx1["store"].escalate_stale_reviews(
        now=NOW + timedelta(seconds=120), response_seconds=3600
    )
    assert len(escalated1_again) == 0

    # --- Scenario 2: reviewer no verdict (delivery completed without verdict) ---
    s2_dir = tmp_path / "s2"
    ctx2 = _setup_board(s2_dir, review_policy="cross_family", extra_family=True)
    _, res2 = _pass_alpha(ctx2, "done-esc-2")
    rev2_id = res2["review_id"]
    reviewer2 = ctx2["members"][2]
    req_act_2 = res2["review_request_activity_id"]

    # Mark the observation completed without calling review(...)
    with RoomDatabase(ctx2["db"]).connect() as conn:
        conn.execute(
            "update room_observations set status = 'completed' "
            "where activity_id = ? and participant_id = ?",
            (req_act_2, reviewer2.participant_id),
        )
        conn.commit()

    escalated2 = ctx2["store"].escalate_stale_reviews(
        now=NOW + timedelta(seconds=60), response_seconds=3600
    )
    assert len(escalated2) == 1
    assert escalated2[0]["review_id"] == rev2_id
    assert escalated2[0]["reason_code"] == "board_review_reviewer_no_verdict"

    # --- Scenario 3: reviewer unresponsive (timeout) ---
    s3_dir = tmp_path / "s3"
    ctx3 = _setup_board(s3_dir, review_policy="cross_family", extra_family=True)
    _, res3 = _pass_alpha(ctx3, "done-esc-3")
    rev3_id = res3["review_id"]

    # With now < created_at + 3600 -> not escalated
    esc_early = ctx3["store"].escalate_stale_reviews(
        now=NOW + timedelta(seconds=500), response_seconds=3600
    )
    assert len(esc_early) == 0

    # With now >= created_at + 3600 -> escalated
    # Review was created at NOW + 30s, so NOW + 3635s is created_at + 3605s >= 3600s
    esc_late = ctx3["store"].escalate_stale_reviews(
        now=NOW + timedelta(seconds=3635), response_seconds=3600
    )
    assert len(esc_late) == 1
    assert esc_late[0]["review_id"] == rev3_id
    assert esc_late[0]["reason_code"] == "board_review_reviewer_unresponsive"

    # Wakes nobody: check observations count for the escalation activity
    with RoomDatabase(ctx3["db"]).connect(readonly=True) as conn:
        obs_count = conn.execute(
            "select count(*) from room_observations where activity_id = ?",
            (esc_late[0]["activity_id"],),
        ).fetchone()[0]
        assert obs_count == 0


def test_verification_worker_reconcile_calls_escalation(tmp_path: Path) -> None:
    # Test background loop wiring via RoomBoardVerificationWorker.reconcile_once
    ctx = _setup_board(tmp_path, review_policy="cross_family", extra_family=True)
    _, res = _pass_alpha(ctx, "done-worker-esc")
    rev_id = res["review_id"]

    worker = RoomBoardVerificationWorker(
        db_path=ctx["db"],
        clones_root=tmp_path / "clones",
        xmuse_root=tmp_path,
        execution_root=tmp_path / "exec",
        execution_profile_id="python-uv/v1",
    )

    # Tick at T0 + 5000 seconds (exceeding default 3600s)
    future_now = NOW + timedelta(seconds=5000)
    worker.reconcile_once(now=future_now)

    detail = ctx["store"].review_detail(ctx["conversation_id"], rev_id)
    assert detail["review"]["reviewer_kind"] == "operator"
    assert detail["review"]["escalated_from"]["reason_code"] == "board_review_reviewer_unresponsive"
