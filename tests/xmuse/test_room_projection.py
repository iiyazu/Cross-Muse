from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import xmuse_core.chat.room_projection as room_projection_module
from xmuse.chat_api import create_app
from xmuse_core.chat.participant_store import (
    ParticipantStore,
    insert_participant_conn,
    prepare_participant,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_projection import (
    build_room_chat_projection,
    build_room_list_projection,
)


def _room(tmp_path, *, duplicate_roles: bool = False):
    path = tmp_path / "chat.db"
    database = RoomDatabase(path)
    database.initialize()
    conversation_id = "conv_projection"
    created_at = "2026-07-01T00:00:00Z"
    first = prepare_participant(
        conversation_id=conversation_id,
        role="review",
        display_name="Reviewer one",
        cli_kind="codex",
        model="gpt-5",
        created_at=created_at,
    )
    second = prepare_participant(
        conversation_id=conversation_id,
        role="review" if duplicate_roles else "architect",
        display_name="Reviewer two" if duplicate_roles else "Architect",
        cli_kind="codex",
        model="gpt-5",
        created_at=created_at,
    )
    with database.connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            "insert into conversations(id, title, created_at) values (?, ?, ?)",
            (conversation_id, "Projection room", created_at),
        )
        insert_participant_conn(conn, first)
        insert_participant_conn(conn, second)
        conn.commit()
    return path, conversation_id, first, second


def _insert_conversation(path, conversation_id, title):
    database = RoomDatabase(path)
    database.initialize()
    with database.connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            "insert into conversations(id, title, created_at) values (?, ?, ?)",
            (conversation_id, title, "2026-07-01T00:00:00Z"),
        )
        conn.commit()


def _complete(
    store: RoomKernelStore,
    *,
    conversation_id: str,
    participant_id: str,
    lease_owner: str,
    request_id: str,
    outcome_type: str,
    payload: dict | None = None,
):
    claim = store.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant_id,
        lease_owner=lease_owner,
    )
    assert claim is not None
    return store.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=participant_id,
        caller_identity=f"god:{lease_owner}:{participant_id}",
        observation_id=claim["observation"]["observation_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request_id,
        outcome_type=outcome_type,
        outcome_payload=payload,
    )


def _insert_skill_decision(
    path,
    *,
    attempt_id: str,
    skill_id: str,
    submitted: bool,
    matched_terms: list[str],
):
    now = "2026-07-10T10:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """create table if not exists room_attempt_skill_decisions (
                   attempt_id text primary key references room_observation_attempts(attempt_id),
                   selector_version text not null,
                   participant_role_snapshot text not null,
                   selection_input_sha256 text,
                   decision text not null,
                   skill_id text,
                   skill_version text,
                   skill_content_sha256 text,
                   skill_instructions_sha256 text,
                   catalog_sha256 text not null,
                   selection_reason text not null,
                   matched_terms_json text not null,
                   context_payload_sha256 text,
                   context_submitted_at text,
                   created_at text not null,
                   updated_at text not null
               )"""
        )
        conn.execute(
            """insert into room_attempt_skill_decisions
               (attempt_id, selector_version, participant_role_snapshot,
                selection_input_sha256, decision, skill_id, skill_version,
                skill_content_sha256, skill_instructions_sha256, catalog_sha256,
                selection_reason, matched_terms_json, context_payload_sha256,
                context_submitted_at, created_at, updated_at)
               values (?, 'xmuse.room_skill_selector/v1', 'review', 'sha256:input',
                       'selected', ?, '1.0.0', ?, 'sha256:instructions',
                       'sha256:catalog', 'trigger', ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                skill_id,
                f"sha256:{skill_id}-content",
                json.dumps(matched_terms, ensure_ascii=False),
                "sha256:private-context-payload" if submitted else None,
                now if submitted else None,
                now,
                now,
            ),
        )


def test_room_projection_exposes_causal_timeline_frontiers_and_settlement(tmp_path):
    path, conversation_id, reviewer, architect = _room(tmp_path)
    store = RoomKernelStore(path)
    posted = store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="Please decide independently",
        client_request_id="human-1",
        mentions=[reviewer.participant_id],
    )

    active = build_room_chat_projection(conversation_id, tmp_path)
    assert active["schema_version"] == "room_chat_projection/v3"
    assert active["status"] == "active"
    assert active["latest_visible_room_seq"] == 1
    assert all(
        "skill_decision" not in (item["frontier"].get("current_attempt") or {})
        for item in active["participants"]
    )
    assert active["timeline_items"][0]["message_id"] == posted["message"]["id"]
    assert {item["state"] for item in active["turns"][0]["participants"]} == {"pending"}
    assert {
        item["participant_id"]: item["frontier"]["priority"] for item in active["participants"]
    } == {reviewer.participant_id: 100, architect.participant_id: 0}

    response = _complete(
        store,
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="review-session",
        request_id="review-response",
        outcome_type="respond",
        payload={"content": "I should answer."},
    )
    _complete(
        store,
        conversation_id=conversation_id,
        participant_id=architect.participant_id,
        lease_owner="architect-session",
        request_id="architect-root-noop",
        outcome_type="noop",
    )
    _complete(
        store,
        conversation_id=conversation_id,
        participant_id=architect.participant_id,
        lease_owner="architect-session",
        request_id="architect-downstream-noop",
        outcome_type="noop",
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "update participants set role = 'renamed', display_name = 'Renamed reviewer' "
            "where participant_id = ?",
            (reviewer.participant_id,),
        )

    settled = build_room_chat_projection(conversation_id, tmp_path)
    assert settled["status"] == "settled"
    assert settled["active_turn_count"] == 0
    assert settled["timeline_items"][-1]["content"] == "I should answer."
    assert settled["timeline_items"][-1]["actor"]["participant_id"] == reviewer.participant_id
    assert settled["timeline_items"][-1]["actor"]["identity"] == (
        f"participant:{reviewer.participant_id}"
    )
    assert "review-session" not in json.dumps(settled)
    assert settled["timeline_items"][-1]["actor"]["role"] == "review"
    assert settled["timeline_items"][-1]["actor"]["display_name"] == "Reviewer one"
    assert settled["timeline_items"][-1]["proof_boundary"] == "identity_bound_room_outcome"
    assert response["produced_activity"]["correlation_id"] == posted["activity"]["correlation_id"]
    outcomes = {
        item["participant_id"]: item["last_completed_outcome"]["outcome_type"]
        for item in settled["participants"]
    }
    assert outcomes == {reviewer.participant_id: "respond", architect.participant_id: "noop"}
    response_counts = {
        item["participant_id"]: item["response_count"]
        for item in settled["turns"][0]["participants"]
    }
    assert response_counts == {reviewer.participant_id: 1, architect.participant_id: 0}


def test_room_projection_v3_exposes_batch_counts_context_tail_and_reply_labels(tmp_path):
    path, conversation_id, reviewer, architect = _room(tmp_path)
    kernel = RoomKernelStore(path)
    posted = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="请审视后转交",
        client_request_id="projection-v3-root",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="reviewer-v3",
    )
    assert claim is not None
    assert claim["batch"]["member_count"] == 1
    observation_id = claim["observation"]["observation_id"]
    message_id = "msg_projection_context_tail"
    activity_id = "activity_projection_context_tail"
    stamp = "2026-07-10T10:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """insert into messages
               (id, conversation_id, author, role, content, created_at,
                envelope_type, envelope_json, mentions_json, reply_to_message_id)
               values (?, ?, ?, 'assistant', ?, ?, 'room_handoff', ?, '[]', ?)""",
            (
                message_id,
                conversation_id,
                reviewer.participant_id,
                "请 Architect 继续核验。",
                stamp,
                json.dumps(
                    {
                        "type": "room_handoff",
                        "participant_id": reviewer.participant_id,
                        "participant_role": "review",
                        "display_name": "Reviewer one",
                        "proof_boundary": "identity_bound_room_outcome",
                    }
                ),
                posted["message"]["id"],
            ),
        )
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, materialized_message_id,
                causal_depth, materialized_proposal_id, delivery_mode, created_at)
               values (?, ?, 2, 'room.handoff', 'participant', ?, ?, ?, ?,
                       'room', ?, ?, ?, 1, null, 'active', ?)""",
            (
                activity_id,
                conversation_id,
                f"god:reviewer-v3:{reviewer.participant_id}",
                reviewer.participant_id,
                posted["activity"]["activity_id"],
                posted["activity"]["correlation_id"],
                json.dumps({"type": "room", "conversation_id": conversation_id}),
                json.dumps(
                    {
                        "outcome_type": "handoff",
                        "source_observation_id": observation_id,
                        "observation_batch_id": claim["batch"]["batch_id"],
                        "observation_phase": "peer",
                        "reply_to_activity_id": posted["activity"]["activity_id"],
                        "target_participant_ids": [architect.participant_id],
                        "context_only": True,
                    }
                ),
                message_id,
                stamp,
            ),
        )
        conn.execute(
            """update room_observations
               set status = 'completed', outcome_type = 'handoff', completed_at = ?,
                   updated_at = ?, lease_owner = null, lease_token = null,
                   expires_at = null, produced_activity_id = ?, produced_message_id = ?
               where observation_id = ?""",
            (stamp, stamp, activity_id, message_id, observation_id),
        )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    reviewer_view = next(
        item
        for item in projection["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    outcome = reviewer_view["last_completed_outcome"]
    assert outcome == {
        **outcome,
        "batch_id": claim["batch"]["batch_id"],
        "phase": "root",
        "member_count": 1,
        "attempt_count": 1,
        "context_only_tail": True,
        "member_activity_refs": [
            {
                "activity_id": posted["activity"]["activity_id"],
                "room_seq": 1,
            }
        ],
        "coverage": {
            "mode": "batch",
            "cutoff_room_seq": 1,
            "included_member_count": 1,
            "omitted_member_count": 0,
        },
    }
    tail = projection["timeline_items"][-1]
    assert tail["context_only_tail"] is True
    assert tail["reply_to_activity_id"] == posted["activity"]["activity_id"]
    assert tail["reply_to_message_id"] == posted["message"]["id"]
    assert tail["reply_target_display_name"] == "alice"
    assert tail["target_participant_ids"] == [architect.participant_id]
    assert tail["handoff_targets"] == ["Architect"]
    turn = projection["turns"][0]
    assert turn["observation_count"] == 2
    assert turn["attempt_count"] == 1
    assert turn["skill_decision_count"] == 0
    assert build_room_list_projection(tmp_path)["rooms"][0]["latest_visible_room_seq"] == 2


def test_room_projection_v3_uses_singleton_evidence_without_batch_tables(tmp_path):
    path, conversation_id, reviewer, _ = _room(tmp_path)
    posted = RoomKernelStore(path).post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="旧数据库仍可读取",
        client_request_id="projection-v3-old-db",
    )
    with sqlite3.connect(path) as conn:
        conn.execute("drop table room_observation_batch_members")
        conn.execute("drop table room_observation_batches")

    projection = build_room_chat_projection(conversation_id, tmp_path)
    frontier = next(
        item["frontier"]
        for item in projection["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert frontier["batch_id"] is None
    assert frontier["phase"] == "root"
    assert frontier["member_count"] == 1
    assert frontier["member_activity_refs"] == [
        {"activity_id": posted["activity"]["activity_id"], "room_seq": 1}
    ]
    assert frontier["attempt_count"] == 0
    assert frontier["coverage"] == {
        "mode": "singleton_fallback",
        "cutoff_room_seq": 1,
        "included_member_count": 1,
        "omitted_member_count": 0,
    }


def test_room_projection_canonicalizes_real_multi_member_peer_batch_outcome(tmp_path):
    path, conversation_id, reviewer, architect = _room(tmp_path)
    critic = ParticipantStore(path).add(
        conversation_id=conversation_id,
        role="critic",
        display_name="Critic",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(path)
    posted = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="三位成员先独立回应再综合",
        client_request_id="projection-real-batch-root",
    )
    members = [reviewer, architect, critic]
    root_claims = [
        kernel.claim_next_observation_batch(
            conversation_id=conversation_id,
            participant_id=member.participant_id,
            lease_owner=f"root-{index}",
        )
        for index, member in enumerate(members)
    ]
    assert all(claim is not None for claim in root_claims)
    for index, (member, claim) in enumerate(zip(members, root_claims, strict=True)):
        assert claim is not None
        outcome_type = "propose" if index == 1 else "respond"
        outcome_payload = (
            {
                "proposal_type": "review_plan",
                "content": "Architect proposal",
                "references": [],
            }
            if outcome_type == "propose"
            else {"content": f"root response {index}"}
        )
        kernel.submit_participant_outcome(
            conversation_id=conversation_id,
            participant_id=member.participant_id,
            caller_identity=f"god:root-{index}:{member.participant_id}",
            observation_id=claim["observation"]["observation_id"],
            observation_batch_id=claim["batch"]["batch_id"],
            lease_token=claim["observation"]["lease_token"],
            client_request_id=f"projection-root-response-{index}",
            outcome_type=outcome_type,
            outcome_payload=outcome_payload,
        )

    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="reviewer-peer-batch",
    )
    assert peer is not None
    assert peer["batch"]["phase"] == "peer"
    assert peer["batch"]["member_count"] == 2
    proposal_member = next(
        item
        for item in peer["batch"]["members"]
        if item["activity"]["activity_type"] == "proposal.created"
    )
    reply_target = proposal_member["activity"]["activity_id"]
    completed = kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        caller_identity=f"god:reviewer-peer-batch:{reviewer.participant_id}",
        observation_id=peer["observation"]["observation_id"],
        observation_batch_id=peer["batch"]["batch_id"],
        lease_token=peer["observation"]["lease_token"],
        client_request_id="projection-peer-response",
        outcome_type="respond",
        outcome_payload={"content": "one synthesized peer follow-up"},
        reply_to_activity_id=reply_target,
    )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    turn = next(
        item
        for item in projection["turns"]
        if item["correlation_id"] == posted["activity"]["correlation_id"]
    )
    reviewer_turn = next(
        item for item in turn["participants"] if item["participant_id"] == reviewer.participant_id
    )
    global_reviewer = next(
        item
        for item in projection["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    expected_primary = peer["batch"]["primary_observation_id"]
    assert reviewer_turn["observation_count"] == 3
    assert reviewer_turn["response_count"] == 2
    assert reviewer_turn["latest_outcome"]["observation_id"] == expected_primary
    assert (
        reviewer_turn["latest_outcome"]["produced_activity_id"]
        == completed["produced_activity"]["activity_id"]
    )
    assert reviewer_turn["latest_outcome"]["phase"] == "peer"
    assert reviewer_turn["latest_outcome"]["member_count"] == 2
    assert reviewer_turn["latest_outcome"]["attempt_count"] == 1
    assert reviewer_turn["latest_outcome"]["context_only_tail"] is True
    assert global_reviewer["last_completed_outcome"] == reviewer_turn["latest_outcome"]
    assert turn["observation_count"] == 9
    assert turn["attempt_count"] == 4
    assert projection["timeline_items"][-1]["context_only_tail"] is True
    assert projection["timeline_items"][-1]["reply_to_activity_id"] == reply_target
    assert projection["timeline_items"][-1]["reply_to_message_id"] is None
    assert projection["timeline_items"][-1]["reply_target_display_name"] == "Architect"


def test_room_projection_reports_expired_claim_and_stopped_exclusion(tmp_path):
    path, conversation_id, reviewer, architect = _room(tmp_path)
    store = RoomKernelStore(path)
    start = datetime(2026, 7, 10, tzinfo=UTC)
    store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="observe",
        client_request_id="expired-claim",
    )
    store.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="review-session",
        lease_ttl_s=5,
        now=start,
    )
    ParticipantStore(path).update_status(architect.participant_id, "stopped")

    projection = build_room_chat_projection(
        conversation_id,
        tmp_path,
        now=start + timedelta(seconds=6),
    )
    assert projection["status"] == "attention"
    assert projection["attention_turn_count"] == 1
    turn = projection["turns"][0]
    assert turn["excluded_stopped_count"] == 1
    states = {item["participant_id"]: item["state"] for item in turn["participants"]}
    assert states == {
        reviewer.participant_id: "runtime_recovery",
        architect.participant_id: "stopped",
    }


def test_room_projection_exposes_only_safe_attempt_recovery_facts(tmp_path):
    path, conversation_id, reviewer, _ = _room(tmp_path)
    store = RoomKernelStore(path)
    store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="recover this delivery",
        client_request_id="attempt-recovery",
    )
    claim = store.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="private-lease-owner",
    )
    assert claim is not None
    observation_id = claim["observation"]["observation_id"]
    attempt_id = claim["attempt"]["attempt_id"]
    with sqlite3.connect(path) as conn:
        conn.execute(
            """update room_observation_attempts
               set runner_generation = 'private-runner-generation',
                   runner_boot_id = 'private-runner-boot',
                   god_session_id = 'private-god-session',
                   provider_session_id = 'private-provider-session',
                   recovery_state = 'fenced',
                   recovery_reason_code = 'room_runner_boot_lost',
                   recovery_started_at = '2026-07-10T10:00:00Z'
               where attempt_id = ?""",
            (attempt_id,),
        )

    fenced = build_room_chat_projection(conversation_id, tmp_path)
    assert fenced["status"] == "attention"
    assert fenced["attention_turn_count"] == 1
    assert build_room_list_projection(tmp_path)["rooms"][0]["status"] == "attention"
    participant = next(
        item for item in fenced["participants"] if item["participant_id"] == reviewer.participant_id
    )
    assert participant["state"] == "runtime_recovery"
    assert participant["frontier"]["current_attempt"]["recovery"] == {
        "state": "fenced",
        "reason_code": "room_runner_boot_lost",
        "started_at": "2026-07-10T10:00:00Z",
        "completed_at": None,
        "next_action": "cleanup_pending",
    }
    assert (
        next(
            item
            for item in fenced["turns"][0]["participants"]
            if item["participant_id"] == reviewer.participant_id
        )["state"]
        == "runtime_recovery"
    )
    encoded = json.dumps(fenced)
    for private_value in (
        "private-runner-generation",
        "private-runner-boot",
        "private-lease-owner",
        "private-god-session",
        "private-provider-session",
    ):
        assert private_value not in encoded

    with sqlite3.connect(path) as conn:
        conn.execute(
            "update room_observation_attempts set recovery_state = 'cleanup_pending' "
            "where attempt_id = ?",
            (attempt_id,),
        )
    cleanup_pending = build_room_chat_projection(conversation_id, tmp_path)
    cleanup_participant = next(
        item
        for item in cleanup_pending["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert cleanup_participant["state"] == "runtime_recovery"
    assert (
        cleanup_participant["frontier"]["current_attempt"]["recovery"]["next_action"]
        == "cleanup_pending"
    )

    with sqlite3.connect(path) as conn:
        conn.execute(
            """update room_observation_attempts
               set recovery_state = 'recovered',
                   recovery_completed_at = '2026-07-10T10:00:05Z'
               where attempt_id = ?""",
            (attempt_id,),
        )
        conn.execute(
            """update room_observations set status = 'pending', control_state = 'active',
                   lease_owner = null, lease_token = null, acquired_at = null,
                   expires_at = null where observation_id = ?""",
            (observation_id,),
        )
    recovered = build_room_chat_projection(conversation_id, tmp_path)
    recovered_frontier = next(
        item["frontier"]
        for item in recovered["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert recovered_frontier["current_attempt"]["recovery"]["next_action"] == "will_retry"

    with sqlite3.connect(path) as conn:
        conn.execute(
            "update room_observations set control_state = 'exhausted' where observation_id = ?",
            (observation_id,),
        )
    exhausted = build_room_chat_projection(conversation_id, tmp_path)
    exhausted_frontier = next(
        item["frontier"]
        for item in exhausted["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert exhausted_frontier["current_attempt"]["recovery"]["next_action"] == "will_exhaust"


def test_room_projection_exposes_safe_root_and_latest_skill_evidence(tmp_path):
    path, conversation_id, reviewer, architect = _room(tmp_path)
    kernel = RoomKernelStore(path)
    posted = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="请审计并验证这个方案",
        client_request_id="skill-root",
    )
    root_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="review-root",
    )
    assert root_claim is not None
    _insert_skill_decision(
        path,
        attempt_id=root_claim["attempt"]["attempt_id"],
        skill_id="evidence-review",
        submitted=False,
        matched_terms=["审计", "验证"],
    )

    active = build_room_chat_projection(conversation_id, tmp_path)
    expected_selected = {
        "skill_id": "evidence-review",
        "version": "1.0.0",
        "content_sha256": "sha256:evidence-review-content",
        "selection_reason": "trigger",
        "matched_terms": ["审计", "验证"],
        "context_status": "selected",
        "context_submitted_at": None,
    }
    reviewer_global = next(
        item for item in active["participants"] if item["participant_id"] == reviewer.participant_id
    )
    reviewer_turn = next(
        item
        for item in active["turns"][0]["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert reviewer_global["frontier"]["current_attempt"]["skill_decision"] == expected_selected
    assert reviewer_turn["frontier"]["current_attempt"]["skill_decision"] == expected_selected
    assert reviewer_turn["root_skill_decision"] == expected_selected

    kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        caller_identity=f"god:review-root:{reviewer.participant_id}",
        observation_id=root_claim["observation"]["observation_id"],
        lease_token=root_claim["observation"]["lease_token"],
        client_request_id="skill-root-response",
        outcome_type="respond",
        outcome_payload={"content": "需要补充证据。"},
    )
    architect_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=architect.participant_id,
        lease_owner="architect-root",
    )
    assert architect_claim is not None
    kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=architect.participant_id,
        caller_identity=f"god:architect-root:{architect.participant_id}",
        observation_id=architect_claim["observation"]["observation_id"],
        lease_token=architect_claim["observation"]["lease_token"],
        client_request_id="architect-root-response",
        outcome_type="respond",
        outcome_payload={"content": "我补充一条下游活动。"},
    )
    downstream_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="review-downstream",
    )
    assert downstream_claim is not None
    assert downstream_claim["observation"]["activity_id"] != posted["activity"]["activity_id"]
    _insert_skill_decision(
        path,
        attempt_id=downstream_claim["attempt"]["attempt_id"],
        skill_id="implementation-planning",
        submitted=True,
        matched_terms=["方案"],
    )
    kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        caller_identity=f"god:review-downstream:{reviewer.participant_id}",
        observation_id=downstream_claim["observation"]["observation_id"],
        lease_token=downstream_claim["observation"]["lease_token"],
        client_request_id="skill-downstream-noop",
        outcome_type="noop",
    )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    reviewer_global = next(
        item
        for item in projection["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    reviewer_turn = next(
        item
        for item in projection["turns"][0]["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    expected_submitted = {
        "skill_id": "implementation-planning",
        "version": "1.0.0",
        "content_sha256": "sha256:implementation-planning-content",
        "selection_reason": "trigger",
        "matched_terms": ["方案"],
        "context_status": "submitted",
        "context_submitted_at": "2026-07-10T10:00:00Z",
    }
    assert reviewer_global["last_completed_outcome"]["skill_decision"] == expected_submitted
    assert reviewer_turn["latest_outcome"]["skill_decision"] == expected_submitted
    assert reviewer_turn["root_skill_decision"] == expected_selected
    serialized = json.dumps(projection, ensure_ascii=False)
    assert "sha256:private-context-payload" not in serialized
    assert root_claim["attempt"]["attempt_id"] not in serialized
    assert "skill_instructions" not in serialized
    assert "Skill 已选择" not in serialized


def test_room_projection_paginates_by_room_seq(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)
    store = RoomKernelStore(path)
    for index in range(5):
        store.post_human_activity(
            conversation_id=conversation_id,
            human_id="alice",
            content=f"message {index + 1}",
            client_request_id=f"page-{index + 1}",
        )

    latest = build_room_chat_projection(conversation_id, tmp_path, limit=2)
    older = build_room_chat_projection(conversation_id, tmp_path, limit=2, before_room_seq=4)
    newer = build_room_chat_projection(conversation_id, tmp_path, limit=2, after_room_seq=2)
    assert [item["room_seq"] for item in latest["timeline_items"]] == [4, 5]
    assert latest["page"]["has_older"] is True
    assert [item["room_seq"] for item in older["timeline_items"]] == [2, 3]
    assert older["page"] == {
        "mode": "before",
        "limit": 2,
        "before_room_seq": 4,
        "after_room_seq": None,
        "has_older": True,
        "has_newer": True,
        "next_before_room_seq": 2,
        "next_after_room_seq": 3,
    }
    assert [item["room_seq"] for item in newer["timeline_items"]] == [3, 4]
    assert "compatibility_items" not in latest
    assert "compatibility_total" not in latest


def test_room_list_is_batched_summary_and_mentions_fall_back_on_collision(tmp_path):
    path, conversation_id, first, second = _room(tmp_path, duplicate_roles=True)
    RoomKernelStore(path).post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="hello",
        client_request_id="list-room",
    )

    projection = build_room_list_projection(tmp_path)
    room = projection["rooms"][0]
    assert projection["schema_version"] == "room_list_projection/v1"
    assert room["status"] == "active"
    assert room["latest_visible_room_seq"] == 1
    assert room["latest_visible_item"]["content"] == "hello"
    assert {item["mention_handle"] for item in room["participants"]} == {
        f"@participant:{first.participant_id}",
        f"@participant:{second.participant_id}",
    }


def test_room_api_contract_events_and_idempotent_human_response(tmp_path):
    client = TestClient(create_app(tmp_path, workroom_runtime_starter=lambda *_: {"state": "stub"}))
    created = client.post(
        "/api/chat/conversations",
        json={
            "title": "API room",
            "initial_participants": [
                {
                    "role": "review",
                    "display_name": "Review",
                    "cli_kind": "codex",
                    "model": "gpt-5",
                }
            ],
        },
    ).json()
    conversation_id = created["id"]
    body = {"message": "hello API", "client_request_id": "api-room-message"}
    first = client.post(f"/api/chat/threads/{conversation_id}/messages", json=body)
    replay = client.post(f"/api/chat/threads/{conversation_id}/messages", json=body)

    assert first.status_code == replay.status_code == 201
    assert first.json()["client_request_id"] == "api-room-message"
    assert first.json()["activity_id"] == replay.json()["activity_id"]
    assert first.json()["room_activity_seq"] == 1
    assert first.json()["message"]["created_at"]
    events = client.get(f"/api/chat/conversations/{conversation_id}/events?after_seq=0").json()[
        "events"
    ]
    room_events = [
        event for event in events if event["payload"].get("kind") == "room_projection_changed"
    ]
    assert len(room_events) == 1
    assert room_events[0]["payload"] == {
        "kind": "room_projection_changed",
        "change": "human.posted",
        "activity_id": first.json()["activity_id"],
        "room_seq": 1,
        "message_id": first.json()["message"]["id"],
    }
    assert client.get("/api/chat/rooms").status_code == 200
    assert (
        client.get(f"/api/chat/conversations/{conversation_id}/room-projection").status_code == 200
    )
    assert (
        client.get(
            f"/api/chat/conversations/{conversation_id}/room-projection"
            "?before_room_seq=2&after_room_seq=0"
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/chat/conversations/{conversation_id}/room-projection?limit=101"
        ).status_code
        == 422
    )
    assert client.get("/api/chat/conversations/missing/room-projection").status_code == 404


def test_room_read_routes_do_not_mutate_schema_or_authority(tmp_path):
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "Read only", "client_request_id": "read-only-room"},
    ).json()
    path = tmp_path / "chat.db"

    def snapshot():
        with sqlite3.connect(path) as conn:
            return (
                conn.execute("pragma schema_version").fetchone()[0],
                tuple(
                    conn.execute(
                        "select name, sql from sqlite_schema "
                        "where name not like 'sqlite_%' order by type, name"
                    ).fetchall()
                ),
                conn.execute("select count(*) from conversations").fetchone()[0],
                conn.execute("select count(*) from room_setup_requests").fetchone()[0],
            )

    before = snapshot()
    for _ in range(3):
        assert client.get("/api/chat/rooms").status_code == 200
        assert (
            client.get(f"/api/chat/conversations/{created['id']}/room-projection").status_code
            == 200
        )
        assert client.get(f"/api/chat/conversations/{created['id']}/events").status_code == 200
        assert client.get("/api/chat/runtime/operations").status_code == 200
    assert snapshot() == before


def test_room_read_routes_do_not_recreate_database_deleted_after_startup(tmp_path):
    client = TestClient(create_app(tmp_path))
    path = tmp_path / "chat.db"
    path.unlink()

    rooms = client.get("/api/chat/rooms")
    events = client.get("/api/chat/conversations/missing/events")

    assert rooms.status_code == events.status_code == 503
    assert rooms.json()["detail"]["code"] == "room_database_unavailable"
    assert events.json()["detail"]["code"] == "room_database_unavailable"
    assert not path.exists()


def test_room_read_routes_return_stable_503_for_a_damaged_database(tmp_path):
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "Damage", "client_request_id": "damaged-room"},
    ).json()
    path = tmp_path / "chat.db"
    path.write_bytes(b"not-a-sqlite-database")

    responses = [
        client.get("/api/chat/rooms"),
        client.get(f"/api/chat/conversations/{created['id']}/room-projection"),
        client.get(f"/api/chat/conversations/{created['id']}/events"),
        client.get("/api/chat/runtime/operations"),
    ]

    assert {response.status_code for response in responses} == {503}
    assert {response.json()["detail"]["code"] for response in responses} == {
        "room_database_unavailable"
    }


def test_human_actor_and_empty_page_cursors(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)
    posted = RoomKernelStore(path).post_human_activity(
        conversation_id=conversation_id,
        human_id="Current human",
        content="durable room message",
        client_request_id="human-identity",
    )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    item = projection["timeline_items"][0]
    assert item["actor"] == {
        "kind": "human",
        "identity": "human:Current human",
        "participant_id": None,
        "role": "human",
        "display_name": "Current human",
    }
    assert item["message_id"] == posted["message"]["id"]
    assert "compatibility_items" not in projection
    assert "compatibility_total" not in projection
    assert projection["event_cursor"] == projection["latest_visible_room_seq"]
    summary = build_room_list_projection(tmp_path)["rooms"][0]
    assert summary["latest_visible_item"]["actor"] == item["actor"]

    past_end = build_room_chat_projection(conversation_id, tmp_path, after_room_seq=99)
    assert past_end["timeline_items"] == []
    assert past_end["page"] == {
        "mode": "after",
        "limit": 60,
        "before_room_seq": None,
        "after_room_seq": 99,
        "has_older": True,
        "has_newer": False,
        "next_before_room_seq": 100,
        "next_after_room_seq": 99,
    }
    before_first = build_room_chat_projection(conversation_id, tmp_path, before_room_seq=1)
    assert before_first["timeline_items"] == []
    assert before_first["page"]["has_older"] is False
    assert before_first["page"]["has_newer"] is True
    assert before_first["page"]["next_after_room_seq"] == 0


def test_control_descriptors_follow_durable_attempt_state(tmp_path):
    path, conversation_id, reviewer, _ = _room(tmp_path)
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="review this",
        client_request_id="controlled-frontier",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer.participant_id,
        lease_owner="host-1",
    )
    assert claim is not None
    observation_id = claim["observation"]["observation_id"]
    controls = RoomObservationControlStore(path)

    claimed = build_room_chat_projection(conversation_id, tmp_path)
    frontier = next(
        item["frontier"]
        for item in claimed["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    authority = controls.projection(observation_id)
    assert frontier["current_attempt"]["state"] == "claimed"
    assert frontier["current_attempt"]["recovery"] == {
        "state": "none",
        "reason_code": None,
        "started_at": None,
        "completed_at": None,
        "next_action": "none",
    }
    assert "recovery_state" not in frontier["current_attempt"]
    assert "current_attempt_id" not in frontier
    assert "attempt_id" not in frontier["current_attempt"]
    assert frontier["actions"]["cancel"] == {
        "available": authority["actions"]["cancel"]["available"],
        "method": "POST",
        "href": f"/api/chat/operator/room-observations/{observation_id}/cancel",
        "expected_state": authority["actions"]["cancel"]["expected_state"],
        "expected_attempt_count": authority["actions"]["cancel"]["expected_attempt_count"],
        "expected_control_seq": authority["actions"]["cancel"]["expected_control_seq"],
    }
    assert frontier["actions"]["retry"]["available"] is False
    assert frontier["actions"]["retry"]["href"] is None

    requested = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-frontier",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )
    cancelling = build_room_chat_projection(conversation_id, tmp_path)
    frontier = next(
        item["frontier"]
        for item in cancelling["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    assert cancelling["status"] == "attention"
    assert frontier["control_state"] == "cancel_requested"
    assert frontier["current_attempt"]["state"] == "cancel_requested"
    assert frontier["actions"]["cancel"]["available"] is False
    assert frontier["actions"]["cancel"]["href"] is None

    pending = controls.mark_cancel_pending(
        observation_id=observation_id,
        attempt_id=claim["attempt"]["attempt_id"],
        expected_control_seq=requested["projection"]["control_seq"],
    )
    cancelled_result = controls.mark_cancelled(
        observation_id=observation_id,
        attempt_id=claim["attempt"]["attempt_id"],
        expected_control_seq=pending["control_seq"],
    )
    assert cancelled_result["projection_event"]["source_ref"] == observation_id
    assert claim["attempt"]["attempt_id"] not in json.dumps(cancelled_result["projection_event"])
    cancelled = build_room_chat_projection(conversation_id, tmp_path)
    frontier = next(
        item["frontier"]
        for item in cancelled["participants"]
        if item["participant_id"] == reviewer.participant_id
    )
    authority = controls.projection(observation_id)
    assert frontier["control_state"] == "cancelled"
    assert frontier["actions"]["retry"]["available"] is True
    assert frontier["actions"]["retry"]["href"].endswith("/retry")
    assert frontier["actions"]["retry"]["expected_control_seq"] == authority["control_seq"]


def test_stopped_observations_are_globally_excluded_not_hidden_by_turn_window(tmp_path):
    path, conversation_id, first, second = _room(tmp_path)
    kernel = RoomKernelStore(path)
    for index in range(10):
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="alice",
            content=f"turn {index}",
            client_request_id=f"stopped-turn-{index}",
        )
    participants = ParticipantStore(path)
    participants.update_status(first.participant_id, "stopped")
    participants.update_status(second.participant_id, "stopped")

    projection = build_room_chat_projection(conversation_id, tmp_path)
    assert projection["status"] == "settled"
    assert projection["active_turn_count"] == 0
    assert projection["attention_turn_count"] == 0
    assert projection["excluded_stopped_count"] == 20
    assert len(projection["turns"]) == 8
    assert {item["unresolved_count"] for item in projection["participants"]} == {10}
    assert all(turn["status"] == "settled" for turn in projection["turns"])
    assert build_room_list_projection(tmp_path)["rooms"][0]["status"] == "settled"


def test_retired_provider_history_is_visible_without_blocking_room_state(tmp_path):
    path, conversation_id, historical, current = _room(tmp_path)
    RoomKernelStore(path).post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="historical provider boundary",
        client_request_id="historical-provider",
    )
    ParticipantStore(path).update_status(current.participant_id, "stopped")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "update participants set cli_kind = 'a2a', model = 'historical' "
            "where participant_id = ?",
            (historical.participant_id,),
        )

    projection = build_room_chat_projection(conversation_id, tmp_path)
    historical_view = next(
        item
        for item in projection["participants"]
        if item["participant_id"] == historical.participant_id
    )
    room = build_room_list_projection(tmp_path)["rooms"][0]

    assert projection["status"] == "settled"
    assert projection["active_turn_count"] == 0
    assert projection["attention_turn_count"] == 0
    assert projection["excluded_stopped_count"] == 2
    assert historical_view["status"] == "stopped"
    assert historical_view["frontier"] is None
    assert room["participant_count"] == 2
    assert room["active_participant_count"] == 0


def test_room_projection_is_bounded_for_ten_thousand_activities(tmp_path, monkeypatch):
    path = tmp_path / "chat.db"
    conversation_id = "conv_large"
    _insert_conversation(path, conversation_id, "Large room")
    created_at = "2026-07-10T00:00:00Z"
    message_rows = []
    activity_rows = []
    for seq in range(1, 10_001):
        message_id = f"msg_large_{seq}"
        activity_id = f"activity_large_{seq}"
        message_rows.append(
            (
                message_id,
                conversation_id,
                "Load tester",
                "human",
                f"message {seq}",
                created_at,
                "message",
                "{}",
                "[]",
                None,
            )
        )
        activity_rows.append(
            (
                activity_id,
                conversation_id,
                seq,
                "message.posted",
                "human",
                "human:Load tester",
                None,
                f"causation_{seq}",
                f"correlation_{seq}",
                "room",
                json.dumps({"type": "room", "conversation_id": conversation_id}),
                json.dumps({"content": f"message {seq}", "mentions": []}),
                message_id,
                0,
                None,
                "active",
                created_at,
            )
        )
    with sqlite3.connect(path) as conn:
        conn.executemany(
            """insert into messages
            (id, conversation_id, author, role, content, created_at, envelope_type,
             envelope_json, mentions_json, reply_to_message_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            message_rows,
        )
        conn.executemany(
            """insert into room_activities
            (activity_id, conversation_id, seq, activity_type, actor_kind,
             actor_identity, actor_participant_id, causation_id, correlation_id,
             visibility, audience_json, payload_json, materialized_message_id,
             causal_depth, materialized_proposal_id, delivery_mode, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            activity_rows,
        )

    statements: list[str] = []
    original_connect = room_projection_module._connect

    def tracked_connect(db_path):
        conn = original_connect(db_path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(room_projection_module, "_connect", tracked_connect)
    projection = build_room_chat_projection(conversation_id, tmp_path, limit=100)
    read_statements = [
        statement
        for statement in statements
        if statement.lstrip().lower().startswith(("select", "with"))
    ]
    assert statements[0].strip().lower() == "begin"
    assert len(read_statements) <= 20
    assert len(projection["timeline_items"]) == 100
    assert [
        projection["timeline_items"][0]["room_seq"],
        projection["timeline_items"][-1]["room_seq"],
    ] == [9_901, 10_000]
    assert len(projection["turns"]) == 8
    assert projection["page"]["has_older"] is True
    assert len(json.dumps(projection)) < 200_000


def test_room_list_query_count_does_not_grow_with_rooms(tmp_path, monkeypatch):
    path = tmp_path / "chat.db"
    _insert_conversation(path, "conv_list_0", "Room 0")
    statements: list[str] = []
    original_connect = room_projection_module._connect

    def tracked_connect(db_path):
        conn = original_connect(db_path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(room_projection_module, "_connect", tracked_connect)
    first_projection = build_room_list_projection(tmp_path)
    first_reads = [
        statement
        for statement in statements
        if statement.lstrip().lower().startswith(("select", "with"))
    ]
    statements.clear()
    database = RoomDatabase(path)
    with database.connect() as conn:
        conn.execute("begin immediate")
        conn.executemany(
            "insert into conversations(id, title, created_at) values (?, ?, ?)",
            [
                (f"conv_list_{index}", f"Room {index}", "2026-07-01T00:00:00Z")
                for index in range(1, 24)
            ],
        )
        conn.commit()
    projection = build_room_list_projection(tmp_path)
    many_reads = [
        statement
        for statement in statements
        if statement.lstrip().lower().startswith(("select", "with"))
    ]
    assert len(first_projection["rooms"]) == 1
    assert len(projection["rooms"]) == 24
    assert len(many_reads) == len(first_reads)
    assert len(many_reads) <= 6
