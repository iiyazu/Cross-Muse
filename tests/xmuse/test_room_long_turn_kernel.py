from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _claimed(
    tmp_path: Path, *, lease_ttl_s: float = 100.0, now: datetime | None = None
) -> tuple[Path, RoomKernelStore, str, str, dict]:
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("room")
    participant = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="owner",
        display_name="P",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="h",
        content="hi",
        client_request_id="h1",
    )
    claimed = kernel.claim_next_observation_batch(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="owner-1",
        lease_ttl_s=lease_ttl_s,
        base_attempt_limit=3,
        now=now or T0,
    )
    assert claimed is not None
    return db, kernel, conversation.id, participant.participant_id, claimed


def _rows(db: Path, observation_id: str, attempt_id: str) -> tuple[dict, dict]:
    with RoomDatabase(db).connect() as conn:
        obs = conn.execute(
            "select * from room_observations where observation_id = ?",
            (observation_id,),
        ).fetchone()
        attempt = conn.execute(
            "select * from room_observation_attempts where attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    return dict(obs), dict(attempt)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def test_renew_extends_observation_and_attempt(tmp_path: Path) -> None:
    db, kernel, _cid, _pid, claimed = _claimed(tmp_path)
    observation, attempt = claimed["observation"], claimed["attempt"]
    token = observation["lease_token"]

    renewed = kernel.renew_observation_lease(
        observation_id=observation["observation_id"],
        attempt_id=attempt["attempt_id"],
        lease_token=token,
        now=T0 + timedelta(seconds=10),
        lease_ttl_s=200,
    )
    assert renewed == _stamp(T0 + timedelta(seconds=210))

    obs_row, attempt_row = _rows(db, observation["observation_id"], attempt["attempt_id"])
    assert obs_row["expires_at"] == renewed
    assert attempt_row["expires_at"] == renewed
    assert obs_row["lease_token"] == token
    assert obs_row["status"] == "claimed"


def test_renew_rejects_wrong_token_and_wrong_attempt(tmp_path: Path) -> None:
    db, kernel, _cid, _pid, claimed = _claimed(tmp_path)
    observation, attempt = claimed["observation"], claimed["attempt"]
    before_obs, before_attempt = _rows(db, observation["observation_id"], attempt["attempt_id"])

    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=observation["observation_id"],
            attempt_id=attempt["attempt_id"],
            lease_token="lease_nope",
            now=T0 + timedelta(seconds=1),
            lease_ttl_s=200,
        )
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=observation["observation_id"],
            attempt_id="room_attempt_nope",
            lease_token=observation["lease_token"],
            now=T0 + timedelta(seconds=1),
            lease_ttl_s=200,
        )
    after_obs, after_attempt = _rows(db, observation["observation_id"], attempt["attempt_id"])
    assert after_obs["expires_at"] == before_obs["expires_at"]
    assert after_attempt["expires_at"] == before_attempt["expires_at"]


def test_renew_rejects_superseded_attempt(tmp_path: Path) -> None:
    db, kernel, cid, pid, first = _claimed(tmp_path, lease_ttl_s=100)
    # Let the first lease lapse, then claim again: the second claim supersedes
    # the first attempt with a fresh token.
    second = kernel.claim_next_observation_batch(
        conversation_id=cid,
        participant_id=pid,
        lease_owner="owner-1",
        lease_ttl_s=100,
        base_attempt_limit=3,
        now=T0 + timedelta(seconds=101),
    )
    assert second is not None
    assert second["attempt"]["attempt_id"] != first["attempt"]["attempt_id"]

    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=first["observation"]["observation_id"],
            attempt_id=first["attempt"]["attempt_id"],
            lease_token=first["observation"]["lease_token"],
            now=T0 + timedelta(seconds=102),
            lease_ttl_s=200,
        )
    # The current attempt still renews.
    renewed = kernel.renew_observation_lease(
        observation_id=second["observation"]["observation_id"],
        attempt_id=second["attempt"]["attempt_id"],
        lease_token=second["observation"]["lease_token"],
        now=T0 + timedelta(seconds=102),
        lease_ttl_s=200,
    )
    assert renewed == _stamp(T0 + timedelta(seconds=302))


def test_renew_rejects_already_expired_lease_without_resurrecting(tmp_path: Path) -> None:
    db, kernel, _cid, _pid, claimed = _claimed(tmp_path, lease_ttl_s=100)
    observation, attempt = claimed["observation"], claimed["attempt"]
    before = _rows(db, observation["observation_id"], attempt["attempt_id"])[0]["expires_at"]

    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=observation["observation_id"],
            attempt_id=attempt["attempt_id"],
            lease_token=observation["lease_token"],
            now=T0 + timedelta(seconds=101),
            lease_ttl_s=200,
        )
    after = _rows(db, observation["observation_id"], attempt["attempt_id"])[0]["expires_at"]
    assert after == before


def test_renew_rejects_pending_and_completed_observations(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("room")
    participant = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="owner",
        display_name="P",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="h",
        content="hi",
        client_request_id="h1",
    )
    pending = kernel.list_observations(conversation.id)[0]
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=pending["observation_id"],
            attempt_id="room_attempt_nope",
            lease_token="lease_nope",
            now=T0,
            lease_ttl_s=100,
        )

    claimed = kernel.claim_next_observation_batch(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="owner-1",
        lease_ttl_s=100,
        base_attempt_limit=3,
        now=T0,
    )
    assert claimed is not None
    kernel.submit_participant_outcome(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session-1:{participant.participant_id}",
        observation_id=claimed["observation"]["observation_id"],
        lease_token=claimed["observation"]["lease_token"],
        client_request_id="outcome-1",
        outcome_type="noop",
        outcome_payload={},
        now=T0 + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.renew_observation_lease(
            observation_id=claimed["observation"]["observation_id"],
            attempt_id=claimed["attempt"]["attempt_id"],
            lease_token=claimed["observation"]["lease_token"],
            now=T0 + timedelta(seconds=2),
            lease_ttl_s=100,
        )


def test_renew_never_shortens_an_expiry(tmp_path: Path) -> None:
    db, kernel, _cid, _pid, claimed = _claimed(tmp_path, lease_ttl_s=1000)
    observation, attempt = claimed["observation"], claimed["attempt"]

    renewed = kernel.renew_observation_lease(
        observation_id=observation["observation_id"],
        attempt_id=attempt["attempt_id"],
        lease_token=observation["lease_token"],
        now=T0 + timedelta(seconds=10),
        lease_ttl_s=60,
    )
    assert renewed == observation["expires_at"]
    obs_row, attempt_row = _rows(db, observation["observation_id"], attempt["attempt_id"])
    assert obs_row["expires_at"] == observation["expires_at"]
    assert attempt_row["expires_at"] == observation["expires_at"]


def test_renew_validates_inputs(tmp_path: Path) -> None:
    _db, kernel, _cid, _pid, claimed = _claimed(tmp_path)
    observation, attempt = claimed["observation"], claimed["attempt"]
    naive = datetime(2026, 1, 1, 0, 0, 10)
    with pytest.raises(ValueError, match="room_observation_now_timezone_required"):
        kernel.renew_observation_lease(
            observation_id=observation["observation_id"],
            attempt_id=attempt["attempt_id"],
            lease_token=observation["lease_token"],
            now=naive,
            lease_ttl_s=100,
        )
    with pytest.raises(ValueError, match="room_lease_ttl_invalid"):
        kernel.renew_observation_lease(
            observation_id=observation["observation_id"],
            attempt_id=attempt["attempt_id"],
            lease_token=observation["lease_token"],
            now=T0,
            lease_ttl_s=0,
        )
