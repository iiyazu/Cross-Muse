from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import (
    RoomAttemptSkillDecisionStore,
    RoomSkillDecisionError,
)
from xmuse_core.skills.models import RoomSkillActivation, SkillDecision

NOW = datetime(2026, 7, 11, 3, 0, tzinfo=UTC)


class _Catalog:
    def __init__(self, decision: SkillDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[str, str]] = []

    def select(self, *, participant_role: str, source_text: str) -> SkillDecision:
        self.calls.append((participant_role, source_text))
        return replace(self.decision, participant_role_snapshot=participant_role)


def _decision(*, selected: bool = True) -> SkillDecision:
    return SkillDecision(
        selector_version="xmuse.room_skill_selector/v1",
        participant_role_snapshot="ignored-by-authority-join",
        selection_input_sha256="input-hash",
        decision="selected" if selected else "none",
        skill_id="evidence-review" if selected else None,
        skill_version="1.0.0" if selected else None,
        skill_content_sha256="content-hash" if selected else None,
        skill_instructions_sha256=(
            f"sha256:{hashlib.sha256(b'Ground claims in evidence.').hexdigest()}"
            if selected
            else None
        ),
        catalog_sha256="catalog-hash",
        selection_reason="trigger" if selected else "no_match",
        matched_terms=("risk", "verify") if selected else (),
    )


def _claimed(
    tmp_path,
    *,
    content: str = "verify this risk",
    attempt_limit: int = 3,
    activity_override: tuple[str, str, dict[str, object]] | None = None,
):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("skill room")
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(path)
    posted = kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="alice",
        content=content,
        client_request_id="human-1",
    )
    if activity_override is not None:
        actor_kind, activity_type, payload = activity_override
        with sqlite3.connect(path) as conn:
            conn.execute(
                "update room_activities set actor_kind = ?, activity_type = ?, "
                "payload_json = ? where activity_id = ?",
                (
                    actor_kind,
                    activity_type,
                    json.dumps(payload),
                    posted["activity"]["activity_id"],
                ),
            )
    claim = kernel.claim_next_observation(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="host-1",
        lease_ttl_s=120,
        base_attempt_limit=attempt_limit,
        now=NOW,
    )
    assert claim is not None
    return path, conversation, participant, kernel, claim


def _skill_events(path) -> list[dict[str, object]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "select payload_json from chat_frontend_events "
            "where source_authority = 'room_attempt_skill_decisions' order by seq"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def test_bind_joins_durable_authority_and_exact_replay_emits_one_event(tmp_path):
    path, _, _, _, claim = _claimed(tmp_path)
    store = RoomAttemptSkillDecisionStore(path)
    catalog = _Catalog(_decision())
    attempt_id = claim["attempt"]["attempt_id"]

    first = store.bind_for_attempt(attempt_id=attempt_id, catalog=catalog, now=NOW)
    replay = store.bind_for_attempt(attempt_id=attempt_id, catalog=catalog, now=NOW)

    assert first == replay == store.get(attempt_id)
    assert first.selection.participant_role_snapshot == "review"
    assert catalog.calls == [("review", "verify this risk"), ("review", "verify this risk")]
    assert _skill_events(path) == [
        {
            "change": "attempt.skill_decided",
            "observation_id": claim["observation"]["observation_id"],
        }
    ]

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "select * from room_attempt_skill_decisions where attempt_id = ?", (attempt_id,)
        ).fetchone()
        assert row is not None
        assert "Ground claims" not in repr(row)
        columns = {
            item[1] for item in conn.execute("pragma table_info(room_attempt_skill_decisions)")
        }
        assert not {"body", "path", "provider_output", "lease_token"} & columns


def test_none_is_durable_and_changed_replay_conflicts(tmp_path):
    path, _, _, _, claim = _claimed(tmp_path, content="hello room")
    store = RoomAttemptSkillDecisionStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    bound = store.bind_for_attempt(
        attempt_id=attempt_id, catalog=_Catalog(_decision(selected=False)), now=NOW
    )

    assert bound.selection.decision == "none"
    assert bound.selection.matched_terms == ()
    with pytest.raises(RoomSkillDecisionError, match="room_skill_binding_conflict"):
        store.bind_for_attempt(attempt_id=attempt_id, catalog=_Catalog(_decision()), now=NOW)


def test_execution_infrastructure_activity_binds_stable_empty_source_to_none(tmp_path):
    path, _, _, _, claim = _claimed(
        tmp_path,
        activity_override=(
            "infrastructure",
            "execution.failed",
            {"reason_code": "execution_patch_apply_check_failed"},
        ),
    )
    store = RoomAttemptSkillDecisionStore(path)
    catalog = _Catalog(_decision(selected=False))

    record = store.bind_for_attempt(
        attempt_id=claim["attempt"]["attempt_id"],
        catalog=catalog,
        now=NOW,
    )

    assert record.selection.decision == "none"
    assert record.selection.selection_reason == "no_match"
    assert catalog.calls == [("review", "")]


@pytest.mark.parametrize(
    "activity_override",
    [
        ("human", "message.posted", {}),
        ("human", "execution.failed", {"content": "must not be trusted"}),
        ("infrastructure", "runtime.failed", {}),
    ],
)
def test_unknown_or_malformed_activity_source_remains_fail_closed(tmp_path, activity_override):
    path, _, _, _, claim = _claimed(tmp_path, activity_override=activity_override)

    with pytest.raises(RoomSkillDecisionError, match="room_skill_binding_lost"):
        RoomAttemptSkillDecisionStore(path).bind_for_attempt(
            attempt_id=claim["attempt"]["attempt_id"],
            catalog=_Catalog(_decision(selected=False)),
            now=NOW,
        )


def test_delivery_requires_decision_and_activation_must_match_ledger(tmp_path):
    path, _, _, _, claim = _claimed(tmp_path)
    controls = RoomObservationControlStore(path)
    store = RoomAttemptSkillDecisionStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    observation_id = claim["observation"]["observation_id"]
    lease_token = claim["observation"]["lease_token"]

    with pytest.raises(RoomControlError, match="room_skill_binding_lost"):
        controls.bind_delivery(
            observation_id=observation_id,
            attempt_id=attempt_id,
            lease_token=lease_token,
            delivery_task_id="task-1",
            provider_session_generation="generation-1",
        )

    record = store.bind_for_attempt(attempt_id=attempt_id, catalog=_Catalog(_decision()), now=NOW)
    activation = RoomSkillActivation(
        skill_id="evidence-review",
        version="1.0.0",
        content_sha256="content-hash",
        instructions_sha256=record.selection.skill_instructions_sha256 or "",
        catalog_sha256="catalog-hash",
        selection_reason="trigger",
        matched_terms=("risk", "verify"),
        instructions="Ground claims in evidence.",
    )
    assert store.assert_activation(attempt_id=attempt_id, activation=activation) == record
    with pytest.raises(RoomSkillDecisionError, match="room_skill_activation_mismatch"):
        store.assert_activation(
            attempt_id=attempt_id, activation=replace(activation, instructions="changed")
        )

    controls.bind_delivery(
        observation_id=observation_id,
        attempt_id=attempt_id,
        lease_token=lease_token,
        delivery_task_id="task-1",
        provider_session_generation="generation-1",
    )


def test_context_receipt_is_current_generation_guarded_and_hash_idempotent(tmp_path):
    path, _, _, _, claim = _claimed(tmp_path)
    store = RoomAttemptSkillDecisionStore(path)
    controls = RoomObservationControlStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    store.bind_for_attempt(attempt_id=attempt_id, catalog=_Catalog(_decision()), now=NOW)
    controls.bind_delivery(
        observation_id=claim["observation"]["observation_id"],
        attempt_id=attempt_id,
        lease_token=claim["observation"]["lease_token"],
        delivery_task_id="task-receipt",
        provider_session_generation=attempt_id,
        now=NOW,
    )

    submitted = store.mark_context_submitted(
        attempt_id=attempt_id, payload_sha256="payload-hash", now=NOW
    )
    replay = store.mark_context_submitted(
        attempt_id=attempt_id, payload_sha256="payload-hash", now=NOW + timedelta(seconds=1)
    )
    assert submitted == replay
    assert submitted.context_payload_sha256 == "payload-hash"
    assert len(_skill_events(path)) == 2
    with pytest.raises(RoomSkillDecisionError, match="room_skill_context_receipt_conflict"):
        store.mark_context_submitted(attempt_id=attempt_id, payload_sha256="other-hash", now=NOW)


def test_fail_unstarted_releases_lease_once_and_old_outcome_is_fenced(tmp_path):
    path, conversation, participant, kernel, claim = _claimed(tmp_path)
    controls = RoomObservationControlStore(path)
    store = RoomAttemptSkillDecisionStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    observation_id = claim["observation"]["observation_id"]
    lease_token = claim["observation"]["lease_token"]
    store.bind_for_attempt(attempt_id=attempt_id, catalog=_Catalog(_decision()), now=NOW)

    failed = controls.fail_unstarted_attempt(
        observation_id=observation_id,
        attempt_id=attempt_id,
        expected_lease_token=lease_token,
        reason_code="room_skill_catalog_drift",
        base_attempt_limit=3,
        now=NOW,
    )
    event_count = len(_skill_events(path))
    replay = controls.fail_unstarted_attempt(
        observation_id=observation_id,
        attempt_id=attempt_id,
        expected_lease_token=lease_token,
        reason_code="room_skill_catalog_drift",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )

    assert failed["observation_status"] == replay["observation_status"] == "pending"
    assert replay["current_attempt"]["state"] == "failed"
    assert len(_skill_events(path)) == event_count
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.complete_observation(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            caller_identity=f"god:session:{participant.participant_id}",
            observation_id=observation_id,
            lease_token=lease_token,
            client_request_id="late",
            outcome_type="noop",
        )
    assert (
        kernel.claim_next_observation(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            lease_owner="host-2",
            now=NOW + timedelta(seconds=1),
        )
        is not None
    )


def test_fail_unstarted_fails_closed_after_receipt_or_cancel(tmp_path):
    path, _, _, _, claim = _claimed(tmp_path)
    controls = RoomObservationControlStore(path)
    store = RoomAttemptSkillDecisionStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    observation_id = claim["observation"]["observation_id"]
    lease_token = claim["observation"]["lease_token"]
    store.bind_for_attempt(attempt_id=attempt_id, catalog=_Catalog(_decision()), now=NOW)
    controls.bind_delivery(
        observation_id=observation_id,
        attempt_id=attempt_id,
        lease_token=lease_token,
        delivery_task_id="task-submitted",
        provider_session_generation=attempt_id,
        now=NOW,
    )
    store.mark_context_submitted(attempt_id=attempt_id, payload_sha256="sent", now=NOW)
    with pytest.raises(RoomControlError, match="room_skill_unstarted_failure_lost"):
        controls.fail_unstarted_attempt(
            observation_id=observation_id,
            attempt_id=attempt_id,
            expected_lease_token=lease_token,
            reason_code="setup_failed",
            base_attempt_limit=3,
            now=NOW,
        )

    path2, _, _, _, claim2 = _claimed(tmp_path / "cancel")
    controls2 = RoomObservationControlStore(path2)
    controls2.request_cancel(
        observation_id=claim2["observation"]["observation_id"],
        client_action_id="cancel",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
        now=NOW,
    )
    with pytest.raises(RoomControlError, match="room_skill_unstarted_failure_lost"):
        controls2.fail_unstarted_attempt(
            observation_id=claim2["observation"]["observation_id"],
            attempt_id=claim2["attempt"]["attempt_id"],
            expected_lease_token=claim2["observation"]["lease_token"],
            reason_code="setup_failed",
            base_attempt_limit=3,
            now=NOW,
        )
