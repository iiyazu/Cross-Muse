"""Durable room activity, observation, and participant outcome kernel."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.chat.room_batches import (
    batch_identity,
    batch_row_for_observation,
    create_observation_batch,
)
from xmuse_core.chat.room_controls import (
    assert_room_outcome_allowed,
    commit_room_outcome_attempt,
    record_room_claim_attempt,
)
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_candidates import (
    insert_execution_candidate_conn,
    prepare_execution_candidate_conn,
    record_proposal_assessments_conn,
)
from xmuse_core.chat.room_execution_contracts import (
    ExecutionPatch,
    normalize_execution_patch,
    normalize_proposal_assessments,
)
from xmuse_core.chat.room_kernel_schema import (
    create_room_kernel_schema as create_room_kernel_schema,
)
from xmuse_core.chat.room_memory_contracts import normalize_memory_candidates
from xmuse_core.chat.room_memory_governance_store import record_memory_candidates_conn

TOOL_NAME = "room_post_human_activity"
COMPLETION_TOOL_NAME = "room_complete_observation"
OUTCOME_ORDER = ("respond", "handoff", "propose", "defer", "noop")
OUTCOME_TYPES = set(OUTCOME_ORDER)
OUTCOME_PAYLOAD_FIELDS = frozenset(
    {
        "content",
        "mentioned_participant_ids",
        "target_participant_ids",
        "proposal_type",
        "references",
        "execution_patch",
        "wake_condition",
    }
)


def normalize_participant_outcome(
    outcome_type: str,
    outcome_payload: dict[str, Any] | None,
    max_causal_depth: int,
) -> dict[str, Any]:
    """Validate an outcome and return its canonical, authority-free payload."""
    if not isinstance(outcome_type, str) or outcome_type not in OUTCOME_TYPES:
        raise ValueError("room_observation_outcome_invalid")
    if (
        isinstance(max_causal_depth, bool)
        or not isinstance(max_causal_depth, int)
        or max_causal_depth <= 0
    ):
        raise ValueError("room_max_causal_depth_invalid")
    payload = {} if outcome_payload is None else outcome_payload
    if not isinstance(payload, dict):
        raise ValueError("room_observation_payload_invalid")
    if set(payload) - OUTCOME_PAYLOAD_FIELDS:
        raise ValueError("room_observation_payload_invalid")

    def text_field(name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"room_{name}_required")
        return value.strip()

    def string_list(name: str, *, required: bool = False) -> list[str]:
        value = payload.get(name, [] if not required else None)
        if not isinstance(value, list) or (required and not value):
            raise ValueError(f"room_{name}_invalid")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"room_{name}_invalid")
        result = [item.strip() for item in value]
        if len(result) != len(set(result)):
            raise ValueError(f"room_{name}_invalid")
        return result

    if outcome_type == "respond":
        return {
            "content": text_field("content"),
            "mentioned_participant_ids": string_list("mentioned_participant_ids"),
        }
    if outcome_type == "handoff":
        target_ids = string_list("target_participant_ids", required=True)
        mentioned_ids = string_list("mentioned_participant_ids")
        return {
            "content": text_field("content"),
            "target_participant_ids": target_ids,
            "mentioned_participant_ids": mentioned_ids,
            "priority_participant_ids": list(dict.fromkeys(target_ids + mentioned_ids)),
        }
    if outcome_type == "propose":
        result: dict[str, Any] = {
            "proposal_type": text_field("proposal_type"),
            "content": text_field("content"),
            "references": string_list("references"),
        }
        if "execution_patch" in payload:
            if result["proposal_type"] != "execution_patch":
                raise ValueError("room_execution_patch_proposal_type_invalid")
            patch = normalize_execution_patch(payload["execution_patch"])
            result["execution_patch"] = {
                "schema_version": patch.schema_version,
                "base_head": patch.base_head,
                "summary": patch.summary,
                "unified_diff": patch.unified_diff,
                "allowed_files": list(patch.allowed_files),
            }
            # A visible proposal is a bounded summary; exact bytes live only in
            # room_execution_candidates.unified_diff.
            result["content"] = patch.summary
        return result
    if outcome_type == "defer":
        return {"wake_condition": text_field("wake_condition")}
    return {}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _outcome_policy_conn(
    conn: sqlite3.Connection,
    *,
    observation: sqlite3.Row,
    source: dict[str, Any],
) -> dict[str, Any]:
    participant_id = observation["participant_id"]
    batch = batch_row_for_observation(conn, observation["observation_id"])
    if batch is not None:
        phase = str(batch["phase"])
        return {
            "schema_version": "room_outcome_policy/v1",
            "allowed_outcomes": list(OUTCOME_ORDER),
            "respond_available": True,
            "reason": ("human_root" if phase == "root" else "peer_batch_followup_available"),
            "observation_phase": phase,
        }
    source_payload = source.get("payload")
    payload: dict[str, Any] = source_payload if isinstance(source_payload, dict) else {}
    directed_ids = {
        item
        for field in ("mentioned_participant_ids", "target_participant_ids")
        for item in payload.get(field, [])
        if isinstance(item, str)
    }
    peer_speech = source.get("actor_kind") == "participant" and source.get("activity_type") in {
        "message.responded",
        "room.handoff",
    }
    explicitly_targeted = peer_speech and participant_id in directed_ids
    prior_response = conn.execute(
        """select 1
           from room_observations prior
           join room_activities prior_source
             on prior_source.activity_id = prior.activity_id
           where prior.conversation_id = ? and prior.participant_id = ?
             and prior.delivery_mode = 'active' and prior.status = 'completed'
             and prior.outcome_type = 'respond'
             and prior_source.correlation_id = ?
           limit 1""",
        (
            observation["conversation_id"],
            participant_id,
            source["correlation_id"],
        ),
    ).fetchone()
    respond_available = not (peer_speech and prior_response is not None and not explicitly_targeted)
    if not respond_available:
        reason = "untargeted_peer_speech_after_response"
    elif explicitly_targeted:
        reason = "explicit_peer_target"
    elif source.get("actor_kind") == "human":
        reason = "human_root"
    elif source.get("activity_type") == "proposal.created":
        reason = "proposal_activity"
    else:
        reason = "response_budget_available"
    return {
        "schema_version": "room_outcome_policy/v1",
        "allowed_outcomes": [
            outcome for outcome in OUTCOME_ORDER if outcome != "respond" or respond_available
        ],
        "respond_available": respond_available,
        "reason": reason,
    }


class RoomKernelStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    def post_human_activity(
        self,
        *,
        conversation_id: str,
        human_id: str,
        content: str,
        client_request_id: str,
        mentions: list[str] | None = None,
        display_mentions: list[str] | None = None,
        delivery_mode: str = "active",
    ) -> dict[str, Any]:
        if not isinstance(human_id, str) or not human_id.strip():
            raise ValueError("room_human_id_required")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("room_content_required")
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if delivery_mode not in {"active", "shadow"}:
            raise ValueError("room_delivery_mode_invalid")
        effective_mentions = list(mentions or [])
        effective_display_mentions = list(
            effective_mentions if display_mentions is None else display_mentions
        )
        caller = f"human:{human_id}"
        root = _json(
            {
                "actor_identity": caller,
                "conversation_id": conversation_id,
                "client_request_id": client_request_id,
            }
        )
        root_digest = sha256(root.encode()).hexdigest()
        causation_id = f"causation_{root_digest}"
        correlation_id = f"correlation_{root_digest}"
        semantic = {
            "conversation_id": conversation_id,
            "human_id": human_id,
            "content": content,
            "client_request_id": client_request_id,
            "mentions": effective_mentions,
            "delivery_mode": delivery_mode,
            "actor_kind": "human",
            "actor_identity": caller,
            "actor_participant_id": None,
            "author": human_id,
            "role": "human",
            "activity_type": "message.posted",
            "envelope_type": "message",
            "envelope_json": {"type": "message"},
            "visibility": "room",
            "audience": {"type": "room", "conversation_id": conversation_id},
            "causation_id": causation_id,
            "correlation_id": correlation_id,
        }
        fingerprint = sha256(_json(semantic).encode()).hexdigest()
        now = _now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                prior = conn.execute(
                    """select result_json from chat_request_log
                    where conversation_id = ? and tool_name = ?
                      and caller_identity = ? and client_request_id = ?""",
                    (conversation_id, TOOL_NAME, caller, client_request_id),
                ).fetchone()
                if prior is not None:
                    result = json.loads(prior["result_json"])
                    if result.get("request_fingerprint") != fingerprint:
                        raise ValueError("room_request_idempotency_conflict")
                    conn.rollback()
                    return result
                seq_row = conn.execute(
                    "select coalesce(max(seq), 0) + 1 as next_seq "
                    "from room_activities where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                seq = int(seq_row["next_seq"])
                activity_id = _id("activity")
                message_id: str | None = None
                message: dict[str, Any] | None = None
                if delivery_mode == "active":
                    message_id = _id("msg")
                    message = {
                        "id": message_id,
                        "conversation_id": conversation_id,
                        "author": human_id,
                        "role": "human",
                        "content": content,
                        "created_at": now,
                        "envelope_type": "message",
                        "envelope_json": {"type": "message"},
                        "mentions": effective_display_mentions,
                        "reply_to_message_id": None,
                    }
                    conn.execute(
                        """insert into messages
                        (id, conversation_id, author, role, content, created_at,
                         envelope_type, envelope_json, mentions_json, reply_to_message_id)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            message_id,
                            conversation_id,
                            human_id,
                            "human",
                            content,
                            now,
                            "message",
                            _json({"type": "message"}),
                            _json(effective_display_mentions),
                            None,
                        ),
                    )
                audience = semantic["audience"]
                payload = {"content": content, "mentions": effective_mentions}
                conn.execute(
                    """insert into room_activities
                    (activity_id, conversation_id, seq, activity_type, actor_kind,
                     actor_identity, actor_participant_id, causation_id, correlation_id,
                     visibility, audience_json, payload_json, materialized_message_id,
                     delivery_mode, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        activity_id,
                        conversation_id,
                        seq,
                        "message.posted",
                        "human",
                        caller,
                        None,
                        causation_id,
                        correlation_id,
                        "room",
                        _json(audience),
                        _json(payload),
                        message_id,
                        delivery_mode,
                        now,
                    ),
                )
                participant_rows = conn.execute(
                    "select participant_id from participants "
                    "where conversation_id = ? and status = 'active' "
                    "and cli_kind = 'codex' and role <> ? "
                    "order by rowid",
                    (conversation_id, INIT_GOD_ROLE),
                ).fetchall()
                priority_ids = {
                    mention.removeprefix("@participant:")
                    for mention in effective_mentions
                    if isinstance(mention, str) and mention.strip()
                }
                observations: list[dict[str, Any]] = []
                for participant in participant_rows:
                    observations.append(
                        self._insert_observation_conn(
                            conn,
                            conversation_id=conversation_id,
                            activity_id=activity_id,
                            participant_id=participant["participant_id"],
                            delivery_mode=delivery_mode,
                            now=now,
                            priority=(100 if participant["participant_id"] in priority_ids else 0),
                        )
                    )
                activity = self.get_activity(activity_id, conn=conn)
                result = {
                    "activity": activity,
                    "message": message,
                    "observations": observations,
                    "request_fingerprint": fingerprint,
                }
                conn.execute(
                    """insert into chat_request_log
                    (id, conversation_id, tool_name, caller_identity, client_request_id,
                     result_json, created_at) values (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _id("req"),
                        conversation_id,
                        TOOL_NAME,
                        caller,
                        client_request_id,
                        _json(result),
                        now,
                    ),
                )
                if delivery_mode == "active":
                    self._record_projection_event_conn(
                        conn,
                        conversation_id=conversation_id,
                        change="human.posted",
                        resource_ref=f"room:activity:{activity_id}",
                        source_ref=f"room:activity:{activity_id}",
                        payload={
                            "activity_id": activity_id,
                            "room_seq": seq,
                            "message_id": message_id,
                        },
                        client_action_id=client_request_id,
                        now=now,
                    )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _insert_observation_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        activity_id: str,
        participant_id: str,
        delivery_mode: str,
        now: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        observation = {
            "observation_id": _id("observation"),
            "conversation_id": conversation_id,
            "activity_id": activity_id,
            "participant_id": participant_id,
            "priority": priority,
            "delivery_mode": delivery_mode,
            "status": "pending" if delivery_mode == "active" else "shadowed",
            "lease_owner": None,
            "acquired_at": None,
            "expires_at": None,
            "lease_token": None,
            "attempt_count": 0,
            "control_state": "active",
            "control_seq": 0,
            "manual_retry_budget": 0,
            "current_attempt_id": None,
            "outcome_type": None,
            "outcome_payload": None,
            "outcome_actor_identity": None,
            "outcome_client_request_id": None,
            "produced_activity_id": None,
            "produced_message_id": None,
            "produced_proposal_id": None,
            "completed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """insert into room_observations
            (observation_id, conversation_id, activity_id, participant_id, priority,
             delivery_mode, status, lease_owner, acquired_at, expires_at, attempt_count,
             outcome_type, outcome_payload_json, completed_at, created_at, updated_at,
             lease_token, outcome_actor_identity, outcome_client_request_id,
             produced_activity_id, produced_message_id, produced_proposal_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation["observation_id"],
                observation["conversation_id"],
                observation["activity_id"],
                observation["participant_id"],
                observation["priority"],
                observation["delivery_mode"],
                observation["status"],
                observation["lease_owner"],
                observation["acquired_at"],
                observation["expires_at"],
                observation["attempt_count"],
                observation["outcome_type"],
                None,
                observation["completed_at"],
                observation["created_at"],
                observation["updated_at"],
                observation["lease_token"],
                None,
                None,
                None,
                None,
                None,
            ),
        )
        if delivery_mode == "active":
            conn.execute(
                """insert or ignore into room_participant_cursors
                (conversation_id, participant_id, last_acknowledged_seq, updated_at)
                values (?, ?, 0, ?)""",
                (conversation_id, participant_id, now),
            )
        return observation

    @staticmethod
    def _activity_from_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["audience"] = _decode(value.pop("audience_json"))
        value["payload"] = _decode(value.pop("payload_json"))
        return value

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["outcome_payload"] = _decode(value.pop("outcome_payload_json"))
        return value

    def get_activity(
        self, activity_id: str, *, conn: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        owned = conn is None
        active_conn = conn or self._connect()
        try:
            row = active_conn.execute(
                "select * from room_activities where activity_id = ?", (activity_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown room activity: {activity_id}")
            return self._activity_from_row(row)
        finally:
            if owned:
                active_conn.close()

    def list_activities(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from room_activities where conversation_id = ? order by seq",
                (conversation_id,),
            ).fetchall()
        return [self._activity_from_row(row) for row in rows]

    def latest_activity_seq(self, conversation_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "select coalesce(max(seq), 0) as seq from room_activities "
                "where conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["seq"])

    def list_observations(
        self, conversation_id: str, *, participant_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["conversation_id = ?"]
        params: list[str] = [conversation_id]
        if participant_id is not None:
            clauses.append("participant_id = ?")
            params.append(participant_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"select * from room_observations where {' and '.join(clauses)} "
                "order by (select seq from room_activities a "
                "where a.activity_id = room_observations.activity_id), rowid",
                params,
            ).fetchall()
        return [self._observation_from_row(row) for row in rows]

    def list_claimable_conversation_ids(
        self,
        *,
        max_attempts_per_observation: int,
        now: datetime | None = None,
    ) -> list[str]:
        """Return rooms whose durable participant frontier can be claimed now.

        The frontier is the oldest unresolved activity above each active
        participant's acknowledged cursor.  Later activities must not make a
        room look runnable when that frontier has exhausted its attempt budget.
        Stopping a participant removes its frontier from dispatch without
        destroying it; reactivation or a larger attempt budget makes it
        eligible again.
        """

        frontiers = self.list_claimable_room_participants(
            max_attempts_per_observation=max_attempts_per_observation,
            now=now,
        )
        return list(dict.fromkeys(conversation_id for conversation_id, _ in frontiers))

    def list_claimable_room_participants(
        self,
        *,
        max_attempts_per_observation: int,
        now: datetime | None = None,
    ) -> list[tuple[str, str]]:
        """Return each Room frontier together with the participant that owns it."""

        if (
            isinstance(max_attempts_per_observation, bool)
            or not isinstance(max_attempts_per_observation, int)
            or max_attempts_per_observation <= 0
        ):
            raise ValueError("room_max_attempts_invalid")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("room_observation_now_timezone_required")
        stamp = _timestamp(current)
        with self._connect() as conn:
            rows = conn.execute(
                """
                with unresolved as (
                    select o.conversation_id, o.participant_id, o.status,
                           o.expires_at, o.attempt_count, o.manual_retry_budget, a.seq,
                           a.actor_kind, a.activity_type, a.correlation_id,
                           row_number() over (
                               partition by o.conversation_id, o.participant_id
                               order by a.seq, o.rowid
                           ) as frontier_rank
                    from room_observations o
                    join room_activities a on a.activity_id = o.activity_id
                    join participants p
                      on p.conversation_id = o.conversation_id
                     and p.participant_id = o.participant_id
                    left join room_participant_cursors c
                      on c.conversation_id = o.conversation_id
                     and c.participant_id = o.participant_id
                    left join room_observation_attempts t
                      on t.attempt_id = o.current_attempt_id
                    where o.delivery_mode = 'active'
                      and o.status <> 'completed'
                      and o.control_state = 'active'
                      and not (
                          coalesce(t.provider_phase, 'not_started')
                              in ('ensure_started', 'cleanup_pending')
                          or (coalesce(t.provider_phase, 'not_started') = 'bound'
                              and t.state in ('claimed', 'delivering'))
                      )
                      and p.status = 'active'
                      and p.cli_kind = 'codex'
                      and p.role <> ?
                      and (
                          a.seq > coalesce(c.last_acknowledged_seq, 0)
                          or o.manual_retry_budget > 0
                      )
                )
                select conversation_id, participant_id, seq as frontier_seq
                from unresolved
                where frontier_rank = 1
                  and attempt_count < (? + manual_retry_budget)
                  and (
                      status = 'pending'
                      or (status = 'claimed' and expires_at <= ?)
                  )
                  and (
                      (actor_kind = 'human' and activity_type = 'message.posted')
                      or not exists (
                          select 1 from room_observations root_o
                          join room_activities root_a
                            on root_a.activity_id = root_o.activity_id
                          join participants root_p
                            on root_p.participant_id = root_o.participant_id
                          where root_o.conversation_id = unresolved.conversation_id
                            and root_a.correlation_id = unresolved.correlation_id
                            and root_a.actor_kind = 'human'
                            and root_a.activity_type = 'message.posted'
                            and root_o.delivery_mode = 'active'
                            and root_o.status <> 'completed'
                            and root_p.status = 'active'
                            and root_p.cli_kind = 'codex'
                            and root_o.control_state not in ('cancelled','exhausted')
                      )
                  )
                order by frontier_seq, conversation_id, participant_id
                """,
                (INIT_GOD_ROLE, max_attempts_per_observation, stamp),
            ).fetchall()
        return [
            (str(row["conversation_id"]), str(row["participant_id"]))
            for row in rows
        ]

    def get_participant_cursor(
        self, conversation_id: str, participant_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from room_participant_cursors "
                "where conversation_id = ? and participant_id = ?",
                (conversation_id, participant_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_participant_cursors(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from room_participant_cursors "
                "where conversation_id = ? order by participant_id",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _observation_activity_row_conn(
        conn: sqlite3.Connection, observation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            """select o.*, a.seq as activity_seq, a.activity_type, a.actor_kind,
                      a.correlation_id
               from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               where o.observation_id = ?""",
            (observation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        return row

    @staticmethod
    def _batch_member_ids_conn(conn: sqlite3.Connection, batch_id: str) -> list[str]:
        return [
            str(row["observation_id"])
            for row in conn.execute(
                "select observation_id from room_observation_batch_members "
                "where batch_id = ? order by ordinal",
                (batch_id,),
            )
        ]

    @staticmethod
    def _root_phase_terminal_conn(
        conn: sqlite3.Connection, *, conversation_id: str, correlation_id: str
    ) -> bool:
        row = conn.execute(
            """select count(*) as unresolved
               from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               join participants p on p.participant_id = o.participant_id
               where o.conversation_id = ? and a.correlation_id = ?
                 and a.actor_kind = 'human' and a.activity_type = 'message.posted'
                 and o.delivery_mode = 'active'
                 and o.status <> 'completed'
                 and p.status = 'active'
                 and p.cli_kind = 'codex'
                 and o.control_state not in ('cancelled','exhausted')""",
            (conversation_id, correlation_id),
        ).fetchone()
        return int(row["unresolved"]) == 0

    def _batch_view_conn(self, conn: sqlite3.Connection, batch: sqlite3.Row) -> dict[str, Any]:
        members = conn.execute(
            """select m.ordinal, m.observation_id, m.activity_id
               from room_observation_batch_members m
               where m.batch_id = ? order by m.ordinal""",
            (batch["batch_id"],),
        ).fetchall()
        result = batch_identity(batch)
        result["members"] = [
            {
                "ordinal": int(row["ordinal"]),
                "observation": self._observation_from_row(
                    conn.execute(
                        "select * from room_observations where observation_id = ?",
                        (row["observation_id"],),
                    ).fetchone()
                ),
                "activity": self._activity_from_conn(conn, row["activity_id"]),
            }
            for row in members
        ]
        return result

    @staticmethod
    def _safe_acknowledged_seq_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
    ) -> int:
        """Return the highest globally ordered prefix safe for this participant.

        A batch may contain same-correlation observations on both sides of another
        Human turn.  Completed later members are durable, but the cursor must stop
        immediately before the earliest unresolved observation from that turn.
        """

        cursor = conn.execute(
            """select last_acknowledged_seq from room_participant_cursors
               where conversation_id = ? and participant_id = ?""",
            (conversation_id, participant_id),
        ).fetchone()
        acknowledged = int(cursor["last_acknowledged_seq"]) if cursor is not None else 0
        unresolved = conn.execute(
            """select min(a.seq) as seq
               from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               where o.conversation_id = ? and o.participant_id = ?
                 and o.delivery_mode = 'active' and a.seq > ?
                 and o.status <> 'completed'
                 and o.control_state not in ('cancelled','exhausted')""",
            (conversation_id, participant_id, acknowledged),
        ).fetchone()
        if unresolved is not None and unresolved["seq"] is not None:
            return max(acknowledged, int(unresolved["seq"]) - 1)
        latest = conn.execute(
            """select max(a.seq) as seq
               from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               where o.conversation_id = ? and o.participant_id = ?
                 and o.delivery_mode = 'active'""",
            (conversation_id, participant_id),
        ).fetchone()
        latest_seq = int(latest["seq"]) if latest is not None and latest["seq"] else 0
        return max(acknowledged, latest_seq)

    def claim_next_observation(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Compatibility name for the batch-aware claim authority."""

        return self.claim_next_observation_batch(**kwargs)

    def claim_next_observation_batch(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        lease_owner: str,
        lease_ttl_s: int | float = 120,
        base_attempt_limit: int = 3,
        runner_generation: str | None = None,
        runner_boot_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(lease_owner, str) or not lease_owner.strip():
            raise ValueError("room_lease_owner_required")
        if lease_ttl_s <= 0:
            raise ValueError("room_lease_ttl_invalid")
        if (
            isinstance(base_attempt_limit, bool)
            or not isinstance(base_attempt_limit, int)
            or base_attempt_limit <= 0
        ):
            raise ValueError("room_max_attempts_invalid")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("room_observation_now_timezone_required")
        stamp = _timestamp(current)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                participant = conn.execute(
                    """select participant_id from participants
                    where conversation_id = ? and participant_id = ?
                      and status = 'active' and cli_kind = 'codex'""",
                    (conversation_id, participant_id),
                ).fetchone()
                if participant is None:
                    raise ValueError("room_participant_not_active")
                live = conn.execute(
                    """select * from room_observations
                    where conversation_id = ? and participant_id = ?
                    and delivery_mode = 'active' and status = 'claimed'
                    and control_state = 'active'
                    and expires_at > ? order by rowid limit 1""",
                    (conversation_id, participant_id, stamp),
                ).fetchone()
                if live is not None:
                    existing_batch = batch_row_for_observation(conn, live["observation_id"])
                    if existing_batch is None:
                        live_activity = conn.execute(
                            """select a.*, a.seq as activity_seq
                               from room_activities a where a.activity_id = ?""",
                            (live["activity_id"],),
                        ).fetchone()
                        assert live_activity is not None
                        existing_batch = create_observation_batch(
                            conn,
                            conversation_id=conversation_id,
                            participant_id=participant_id,
                            correlation_id=live_activity["correlation_id"],
                            phase=(
                                "root"
                                if live_activity["actor_kind"] == "human"
                                and live_activity["activity_type"] == "message.posted"
                                else "peer"
                            ),
                            members=[
                                self._observation_activity_row_conn(conn, live["observation_id"])
                            ],
                            created_at=stamp,
                        )
                    primary_id = str(existing_batch["primary_observation_id"])
                    live = conn.execute(
                        "select * from room_observations where observation_id = ?",
                        (primary_id,),
                    ).fetchone()
                    assert live is not None
                    if live["lease_owner"] != lease_owner:
                        conn.commit()
                        return None
                    attempt = record_room_claim_attempt(
                        conn,
                        observation_id=primary_id,
                        base_attempt_limit=base_attempt_limit,
                        runner_generation=runner_generation,
                        runner_boot_id=runner_boot_id,
                        now=current,
                    )
                    live = conn.execute(
                        "select * from room_observations where observation_id = ?",
                        (primary_id,),
                    ).fetchone()
                    activity = self._activity_from_conn(conn, live["activity_id"])
                    conn.commit()
                    return {
                        "observation": self._observation_from_row(live),
                        "activity": activity,
                        "attempt": attempt,
                        "batch": self._batch_view_conn(conn, existing_batch),
                    }
                cursor = conn.execute(
                    "select last_acknowledged_seq from room_participant_cursors "
                    "where conversation_id = ? and participant_id = ?",
                    (conversation_id, participant_id),
                ).fetchone()
                acknowledged = int(cursor["last_acknowledged_seq"]) if cursor else 0
                row = conn.execute(
                    """select o.*, a.seq from room_observations o
                    join room_activities a on a.activity_id = o.activity_id
                    where o.conversation_id = ? and o.participant_id = ?
                    and o.delivery_mode = 'active'
                    and o.control_state = 'active'
                    and o.attempt_count < (? + o.manual_retry_budget)
                    and not exists (
                        select 1 from room_observation_attempts t
                        where t.attempt_id = o.current_attempt_id
                          and (t.provider_phase in ('ensure_started', 'cleanup_pending')
                               or (t.provider_phase = 'bound'
                                   and t.state in ('claimed', 'delivering')))
                    )
                    and (a.seq > ? or o.manual_retry_budget > 0)
                    and (o.status = 'pending'
                    or (o.status = 'claimed' and o.expires_at <= ?))
                    order by a.seq, o.rowid limit 1""",
                    (
                        conversation_id,
                        participant_id,
                        base_attempt_limit,
                        acknowledged,
                        stamp,
                    ),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                batch = batch_row_for_observation(conn, row["observation_id"])
                source_row = self._observation_activity_row_conn(conn, row["observation_id"])
                phase = (
                    "root"
                    if source_row["actor_kind"] == "human"
                    and source_row["activity_type"] == "message.posted"
                    else "peer"
                )
                if batch is None:
                    if phase == "peer" and not self._root_phase_terminal_conn(
                        conn,
                        conversation_id=conversation_id,
                        correlation_id=source_row["correlation_id"],
                    ):
                        conn.commit()
                        return None
                    members = [source_row]
                    # A pre-batch claimed/attempted observation is an immutable singleton.
                    # Fresh unresolved peer observations may be coalesced up to the cutoff.
                    if (
                        phase == "peer"
                        and row["status"] == "pending"
                        and int(row["attempt_count"]) == 0
                    ):
                        members = conn.execute(
                            """select o.*, a.seq as activity_seq, a.activity_type,
                                      a.actor_kind, a.correlation_id
                               from room_observations o
                               join room_activities a on a.activity_id = o.activity_id
                               left join room_observation_batch_members bm
                                 on bm.observation_id = o.observation_id
                               where o.conversation_id = ? and o.participant_id = ?
                                 and a.correlation_id = ?
                                 and not (a.actor_kind = 'human'
                                          and a.activity_type = 'message.posted')
                                 and o.delivery_mode = 'active'
                                 and o.status = 'pending' and o.control_state = 'active'
                                 and o.attempt_count = 0 and bm.observation_id is null
                                 and (a.seq > ? or o.manual_retry_budget > 0)
                               order by a.seq, o.rowid limit 16""",
                            (
                                conversation_id,
                                participant_id,
                                source_row["correlation_id"],
                                acknowledged,
                            ),
                        ).fetchall()
                    batch = create_observation_batch(
                        conn,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        correlation_id=source_row["correlation_id"],
                        phase=phase,
                        members=list(members),
                        created_at=stamp,
                    )
                primary_id = str(batch["primary_observation_id"])
                token = _id("lease")
                expires = _timestamp(current + timedelta(seconds=lease_ttl_s))
                conn.execute(
                    """update room_observations set status = 'claimed',
                    lease_owner = ?, lease_token = ?, acquired_at = ?, expires_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                    where observation_id = ?""",
                    (lease_owner, token, stamp, expires, stamp, primary_id),
                )
                claimed = conn.execute(
                    "select * from room_observations where observation_id = ?",
                    (primary_id,),
                ).fetchone()
                attempt = record_room_claim_attempt(
                    conn,
                    observation_id=primary_id,
                    base_attempt_limit=base_attempt_limit,
                    runner_generation=runner_generation,
                    runner_boot_id=runner_boot_id,
                    now=current,
                )
                claimed = conn.execute(
                    "select * from room_observations where observation_id = ?",
                    (primary_id,),
                ).fetchone()
                activity = self._activity_from_conn(conn, claimed["activity_id"])
                self._record_projection_event_conn(
                    conn,
                    conversation_id=conversation_id,
                    change="observation.claimed",
                    resource_ref=f"room:observation:{primary_id}",
                    source_ref=f"room:observation:{primary_id}",
                    payload={
                        "observation_id": primary_id,
                        "observation_batch_id": batch["batch_id"],
                        "activity_id": claimed["activity_id"],
                        "room_seq": int(source_row["activity_seq"]),
                        "participant_id": participant_id,
                    },
                    client_action_id=None,
                    now=stamp,
                )
                conn.commit()
                return {
                    "observation": self._observation_from_row(claimed),
                    "activity": activity,
                    "attempt": attempt,
                    "batch": self._batch_view_conn(conn, batch),
                }
            except Exception:
                conn.rollback()
                raise

    def complete_observation(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        outcome_type: str,
        outcome_payload: dict[str, Any] | None = None,
        observation_batch_id: str | None = None,
        reply_to_activity_id: str | None = None,
        proposal_assessments: list[dict[str, Any]] | None = None,
        memory_candidates: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if outcome_type in {"respond", "handoff", "propose"}:
            raise ValueError("room_observation_outcome_invalid")
        return self.submit_participant_outcome(
            conversation_id=conversation_id,
            participant_id=participant_id,
            caller_identity=caller_identity,
            observation_id=observation_id,
            lease_token=lease_token,
            client_request_id=client_request_id,
            outcome_type=outcome_type,
            outcome_payload=outcome_payload,
            observation_batch_id=observation_batch_id,
            reply_to_activity_id=reply_to_activity_id,
            proposal_assessments=proposal_assessments,
            memory_candidates=memory_candidates,
            now=now,
        )

    def submit_participant_outcome(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        outcome_type: str,
        outcome_payload: dict[str, Any] | None = None,
        observation_batch_id: str | None = None,
        reply_to_activity_id: str | None = None,
        proposal_assessments: list[dict[str, Any]] | None = None,
        memory_candidates: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
        max_causal_depth: int = 4,
    ) -> dict[str, Any]:
        fields = (
            conversation_id,
            participant_id,
            caller_identity,
            observation_id,
            lease_token,
            client_request_id,
        )
        if any(not isinstance(item, str) or not item.strip() for item in fields):
            raise ValueError("room_observation_field_required")
        normalized = normalize_participant_outcome(outcome_type, outcome_payload, max_causal_depth)
        normalized_assessments = normalize_proposal_assessments(proposal_assessments)
        normalized_memory_candidates = normalize_memory_candidates(memory_candidates)
        assessment_payloads = [
            {
                "proposal_id": item.proposal_id,
                "candidate_digest": item.candidate_digest,
                "assessment": item.assessment,
                "rationale": item.rationale,
            }
            for item in normalized_assessments
        ]
        memory_candidate_payloads = [
            {
                "kind": item.kind,
                "content": item.content,
                "source_activity_ids": list(item.source_activity_ids),
            }
            for item in normalized_memory_candidates
        ]
        if observation_batch_id is not None and (
            not isinstance(observation_batch_id, str) or not observation_batch_id.strip()
        ):
            raise ValueError("room_observation_batch_id_invalid")
        if reply_to_activity_id is not None and (
            not isinstance(reply_to_activity_id, str) or not reply_to_activity_id.strip()
        ):
            raise ValueError("room_reply_to_activity_invalid")
        if reply_to_activity_id is not None and outcome_type not in {"respond", "handoff"}:
            raise ValueError("room_reply_to_activity_invalid")
        session, separator, bound = (
            caller_identity[4:].rpartition(":")
            if caller_identity.startswith("god:")
            else ("", "", "")
        )
        if not session or not separator or bound != participant_id:
            raise ValueError("room_observation_actor_forbidden")
        fingerprint = sha256(
            _json(
                {
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "outcome_type": outcome_type,
                    "outcome_payload": normalized,
                    "observation_batch_id": observation_batch_id,
                    "reply_to_activity_id": reply_to_activity_id,
                    "proposal_assessments": assessment_payloads,
                    "memory_candidates": memory_candidate_payloads,
                    "max_causal_depth": max_causal_depth,
                }
            ).encode()
        ).hexdigest()
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("room_observation_now_timezone_required")
        stamp = _timestamp(current)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                prior = conn.execute(
                    "select result_json from chat_request_log "
                    "where conversation_id = ? and tool_name = ? "
                    "and caller_identity = ? and client_request_id = ?",
                    (conversation_id, COMPLETION_TOOL_NAME, caller_identity, client_request_id),
                ).fetchone()
                if prior is not None:
                    result = json.loads(prior["result_json"])
                    if result.get("request_fingerprint") != fingerprint:
                        raise ValueError("room_observation_idempotency_conflict")
                    conn.commit()
                    return result
                participant = conn.execute(
                    "select participant_id, role, display_name, cli_kind, status "
                    "from participants "
                    "where conversation_id = ? and participant_id = ?",
                    (conversation_id, participant_id),
                ).fetchone()
                if participant is None:
                    raise ValueError("room_observation_actor_forbidden")
                submitted_row = conn.execute(
                    "select * from room_observations "
                    "where observation_id = ? and conversation_id = ? "
                    "and participant_id = ?",
                    (observation_id, conversation_id, participant_id),
                ).fetchone()
                batch = (
                    batch_row_for_observation(conn, submitted_row["observation_id"])
                    if submitted_row is not None
                    else None
                )
                if batch is not None:
                    observation_id = str(batch["primary_observation_id"])
                    row = conn.execute(
                        "select * from room_observations where observation_id = ?",
                        (observation_id,),
                    ).fetchone()
                else:
                    row = submitted_row
                if row is None or row["delivery_mode"] != "active":
                    raise ValueError("room_observation_actor_forbidden")
                if observation_batch_id is not None and (
                    batch is None or batch["batch_id"] != observation_batch_id
                ):
                    raise ValueError("room_observation_batch_mismatch")
                member_ids = (
                    self._batch_member_ids_conn(conn, str(batch["batch_id"]))
                    if batch is not None
                    else [observation_id]
                )
                member_activity_rows = conn.execute(
                    f"""select o.observation_id, a.* from room_observations o
                        join room_activities a on a.activity_id = o.activity_id
                        where o.observation_id in ({",".join("?" for _ in member_ids)})
                        order by a.seq""",
                    member_ids,
                ).fetchall()
                member_activity_ids = {str(item["activity_id"]) for item in member_activity_rows}
                if (
                    reply_to_activity_id is not None
                    and reply_to_activity_id not in member_activity_ids
                ):
                    raise ValueError("room_reply_to_activity_not_in_batch")
                if row["status"] == "completed":
                    raise ValueError("room_observation_already_completed")
                if participant["status"] != "active" or participant["cli_kind"] != "codex":
                    raise ValueError("room_participant_not_active")
                if (
                    row["status"] != "claimed"
                    or row["lease_token"] != lease_token
                    or not row["expires_at"]
                    or _parse_timestamp(row["expires_at"]) <= current
                ):
                    raise ValueError("room_observation_lease_lost")
                assert_room_outcome_allowed(
                    conn,
                    observation_id=observation_id,
                    lease_token=lease_token,
                )
                source = self._activity_from_conn(conn, row["activity_id"])
                phase = (
                    str(batch["phase"])
                    if batch is not None
                    else (
                        "root"
                        if source["actor_kind"] == "human"
                        and source["activity_type"] == "message.posted"
                        else "peer"
                    )
                )
                reply_source = (
                    self._activity_from_conn(conn, reply_to_activity_id)
                    if reply_to_activity_id is not None
                    else source
                )
                outcome_policy = _outcome_policy_conn(
                    conn,
                    observation=row,
                    source=source,
                )
                if outcome_type not in outcome_policy["allowed_outcomes"]:
                    raise ValueError("room_root_response_budget_exhausted")
                produced_activity = produced_message = produced_proposal = None
                execution_candidate: dict[str, Any] | None = None
                prepared_candidate: dict[str, Any] | None = None
                public_normalized = dict(normalized)
                downstream: list[dict[str, Any]] = []
                if outcome_type in {"respond", "handoff", "propose"}:
                    targets = normalized.get("priority_participant_ids", []) + normalized.get(
                        "mentioned_participant_ids", []
                    )
                    active_rows = conn.execute(
                        "select participant_id from participants "
                        "where conversation_id = ? and status = 'active' "
                        "and cli_kind = 'codex' and role <> ?",
                        (conversation_id, INIT_GOD_ROLE),
                    ).fetchall()
                    active_ids = {item["participant_id"] for item in active_rows}
                    target_ids = normalized.get("target_participant_ids", [])
                    if participant_id in target_ids or any(
                        item not in active_ids for item in targets
                    ):
                        raise ValueError("room_outcome_target_invalid")
                    seq = conn.execute(
                        "select coalesce(max(seq), 0) + 1 as next_seq "
                        "from room_activities where conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()["next_seq"]
                    activity_id = _id("activity")
                    depth = int(reply_source["causal_depth"]) + 1
                    materialized_message_id = None
                    materialized_proposal_id = None
                    if outcome_type in {"respond", "handoff"}:
                        materialized_message_id = _id("msg")
                        envelope = "message" if outcome_type == "respond" else "room_handoff"
                        message_envelope = {
                            "type": envelope,
                            "participant_id": participant_id,
                            "participant_role": participant["role"],
                            "display_name": participant["display_name"],
                            "proof_boundary": "identity_bound_room_outcome",
                        }
                        conn.execute(
                            "insert into messages "
                            "(id, conversation_id, author, role, content, created_at, "
                            "envelope_type, envelope_json, mentions_json, "
                            "reply_to_message_id) "
                            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                materialized_message_id,
                                conversation_id,
                                participant_id,
                                "assistant",
                                normalized["content"],
                                stamp,
                                envelope,
                                _json(message_envelope),
                                _json(
                                    [
                                        f"@participant:{item}"
                                        for item in normalized.get("mentioned_participant_ids", [])
                                    ]
                                ),
                                reply_source["materialized_message_id"],
                            ),
                        )
                        produced_message = {
                            "id": materialized_message_id,
                            "conversation_id": conversation_id,
                            "author": participant_id,
                            "role": "assistant",
                            "content": normalized["content"],
                            "created_at": stamp,
                            "envelope_type": envelope,
                            "envelope_json": message_envelope,
                            "mentions": [
                                f"@participant:{item}"
                                for item in normalized.get("mentioned_participant_ids", [])
                            ],
                            "reply_to_message_id": reply_source["materialized_message_id"],
                        }
                    else:
                        materialized_proposal_id = _id("prop")
                        conn.execute(
                            "insert into proposals "
                            "(id, conversation_id, author, proposal_type, content, "
                            "references_json, status, created_at, accepted_resolution_id) "
                            "values (?, ?, ?, ?, ?, ?, 'open', ?, null)",
                            (
                                materialized_proposal_id,
                                conversation_id,
                                participant_id,
                                normalized["proposal_type"],
                                normalized["content"],
                                _json(normalized["references"]),
                                stamp,
                            ),
                        )
                        produced_proposal = {
                            "id": materialized_proposal_id,
                            "conversation_id": conversation_id,
                            "author": participant_id,
                            "proposal_type": normalized["proposal_type"],
                            "content": normalized["content"],
                            "references": normalized["references"],
                            "status": "open",
                            "created_at": stamp,
                            "accepted_resolution_id": None,
                        }
                        if "execution_patch" in normalized:
                            patch: ExecutionPatch = normalize_execution_patch(
                                normalized["execution_patch"]
                            )
                            current_attempt_id = row["current_attempt_id"]
                            if not current_attempt_id:
                                raise ValueError("room_execution_source_attempt_missing")
                            prepared_candidate = prepare_execution_candidate_conn(
                                conn,
                                conversation_id=conversation_id,
                                author_participant_id=participant_id,
                                source_observation_id=observation_id,
                                source_batch_id=(str(batch["batch_id"]) if batch else None),
                                source_attempt_id=str(current_attempt_id),
                                source_activity_id=activity_id,
                                source_correlation_id=str(source["correlation_id"]),
                                proposal_id=materialized_proposal_id,
                                patch=patch,
                                direct_human_root=(
                                    phase == "root"
                                    and source["actor_kind"] == "human"
                                    and source["activity_type"] == "message.posted"
                                ),
                                stamp=stamp,
                            )
                            execution_candidate = dict(prepared_candidate["safe_reference"])
                            public_normalized.pop("execution_patch", None)
                            public_normalized["execution_candidate_ref"] = execution_candidate
                            produced_proposal["execution_candidate"] = execution_candidate
                    activity_payload = {
                        "outcome_type": outcome_type,
                        "source_observation_id": observation_id,
                        "source_observation_ids": member_ids,
                        "observation_batch_id": (batch["batch_id"] if batch is not None else None),
                        "observation_phase": phase,
                        "context_only": phase == "peer",
                        "downstream_mode": "context_only" if phase == "peer" else "active",
                        "reply_to_activity_id": reply_to_activity_id,
                        **public_normalized,
                    }
                    activity_type = {
                        "respond": "message.responded",
                        "handoff": "room.handoff",
                        "propose": "proposal.created",
                    }[outcome_type]
                    conn.execute(
                        "insert into room_activities "
                        "(activity_id, conversation_id, seq, activity_type, actor_kind, "
                        "actor_identity, actor_participant_id, causation_id, "
                        "correlation_id, visibility, audience_json, payload_json, "
                        "materialized_message_id, causal_depth, "
                        "materialized_proposal_id, delivery_mode, created_at) "
                        "values (?, ?, ?, ?, 'participant', ?, ?, ?, ?, 'room', "
                        "?, ?, ?, ?, ?, 'active', ?)",
                        (
                            activity_id,
                            conversation_id,
                            seq,
                            activity_type,
                            caller_identity,
                            participant_id,
                            reply_source["activity_id"],
                            source["correlation_id"],
                            _json({"type": "room", "conversation_id": conversation_id}),
                            _json(activity_payload),
                            materialized_message_id,
                            depth,
                            materialized_proposal_id,
                            stamp,
                        ),
                    )
                    if prepared_candidate is not None:
                        inserted = insert_execution_candidate_conn(conn, prepared_candidate)
                        if inserted != execution_candidate:
                            raise ValueError("room_execution_candidate_insert_conflict")
                    produced_activity = self._activity_from_conn(conn, activity_id)
                    if phase == "root" and depth < max_causal_depth:
                        priority_ids = set(
                            normalized.get("priority_participant_ids", [])
                            + normalized.get("mentioned_participant_ids", [])
                        )
                        for item in active_rows:
                            if item["participant_id"] != participant_id:
                                prior_peer_batch = conn.execute(
                                    """select 1 from room_observation_batches
                                       where conversation_id = ? and participant_id = ?
                                         and correlation_id = ? and phase = 'peer'
                                       limit 1""",
                                    (
                                        conversation_id,
                                        item["participant_id"],
                                        source["correlation_id"],
                                    ),
                                ).fetchone()
                                if prior_peer_batch is not None:
                                    continue
                                peer_count = conn.execute(
                                    """select count(*) as count
                                       from room_observations peer_o
                                       join room_activities peer_a
                                         on peer_a.activity_id = peer_o.activity_id
                                       where peer_o.conversation_id = ?
                                         and peer_o.participant_id = ?
                                         and peer_a.correlation_id = ?
                                         and not (peer_a.actor_kind = 'human'
                                                  and peer_a.activity_type = 'message.posted')
                                         and peer_o.delivery_mode = 'active'""",
                                    (
                                        conversation_id,
                                        item["participant_id"],
                                        source["correlation_id"],
                                    ),
                                ).fetchone()
                                if int(peer_count["count"]) >= 16:
                                    continue
                                downstream.append(
                                    self._insert_observation_conn(
                                        conn,
                                        conversation_id=conversation_id,
                                        activity_id=activity_id,
                                        participant_id=item["participant_id"],
                                        delivery_mode="active",
                                        now=stamp,
                                        priority=100
                                        if item["participant_id"] in priority_ids
                                        else 0,
                                    )
                                )
                current_attempt_id = row["current_attempt_id"]
                if not current_attempt_id:
                    raise ValueError("room_execution_source_attempt_missing")
                recorded_assessments = record_proposal_assessments_conn(
                    conn,
                    assessor_participant_id=participant_id,
                    source_attempt_id=str(current_attempt_id),
                    source_batch_id=(str(batch["batch_id"]) if batch else None),
                    batch_activity_ids=member_activity_ids,
                    assessments=normalized_assessments,
                    stamp=stamp,
                )
                recorded_memory_candidates = record_memory_candidates_conn(
                    conn,
                    conversation_id=conversation_id,
                    author_participant_id=participant_id,
                    source_observation_id=observation_id,
                    source_batch_id=(str(batch["batch_id"]) if batch else None),
                    source_attempt_id=str(current_attempt_id),
                    batch_activity_ids=member_activity_ids,
                    candidates=normalized_memory_candidates,
                    stamp=stamp,
                )
                commit_room_outcome_attempt(
                    conn,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    now=current,
                )
                conn.execute(
                    "update room_observations set status = 'completed', "
                    "outcome_type = ?, outcome_payload_json = ?, "
                    "outcome_actor_identity = ?, outcome_client_request_id = ?, "
                    "completed_at = ?, updated_at = ?, lease_owner = null, "
                    "lease_token = null, expires_at = null, "
                    "produced_activity_id = ?, produced_message_id = ?, "
                    "produced_proposal_id = ? where observation_id = ?",
                    (
                        outcome_type,
                        _json(public_normalized),
                        caller_identity,
                        client_request_id,
                        stamp,
                        stamp,
                        produced_activity["activity_id"] if produced_activity else None,
                        produced_message["id"] if produced_message else None,
                        produced_proposal["id"] if produced_proposal else None,
                        observation_id,
                    ),
                )
                safe_acknowledged_seq = self._safe_acknowledged_seq_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                )
                conn.execute(
                    "insert into room_participant_cursors "
                    "(conversation_id, participant_id, last_acknowledged_seq, "
                    "last_observation_id, updated_at) values (?, ?, ?, ?, ?) "
                    "on conflict(conversation_id, participant_id) do update set "
                    "last_acknowledged_seq = max(last_acknowledged_seq, "
                    "excluded.last_acknowledged_seq), "
                    "last_observation_id = excluded.last_observation_id, "
                    "updated_at = excluded.updated_at",
                    (
                        conversation_id,
                        participant_id,
                        safe_acknowledged_seq,
                        observation_id,
                        stamp,
                    ),
                )
                completed = self._observation_from_row(
                    conn.execute(
                        "select * from room_observations where observation_id = ?",
                        (observation_id,),
                    ).fetchone()
                )
                cursor = dict(
                    conn.execute(
                        "select * from room_participant_cursors "
                        "where conversation_id = ? and participant_id = ?",
                        (conversation_id, participant_id),
                    ).fetchone()
                )
                result = {
                    "observation": completed,
                    "cursor": cursor,
                    "produced_activity": produced_activity,
                    "produced_message": produced_message,
                    "produced_proposal": produced_proposal,
                    "execution_candidate": execution_candidate,
                    "proposal_assessments": recorded_assessments,
                    "memory_candidates": recorded_memory_candidates,
                    "downstream_observations": downstream,
                    "batch": self._batch_view_conn(conn, batch) if batch is not None else None,
                    "request_fingerprint": fingerprint,
                }
                self._insert_lifecycle_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                self._record_projection_event_conn(
                    conn,
                    conversation_id=conversation_id,
                    change="observation.completed",
                    resource_ref=f"room:observation:{observation_id}",
                    source_ref=f"room:observation:{observation_id}",
                    payload={
                        "observation_id": observation_id,
                        "observation_batch_id": (batch["batch_id"] if batch is not None else None),
                        "activity_id": source["activity_id"],
                        "room_seq": int(source["seq"]),
                        "participant_id": participant_id,
                        "outcome_type": outcome_type,
                        "produced_activity_id": (
                            produced_activity["activity_id"] if produced_activity else None
                        ),
                    },
                    client_action_id=client_request_id,
                    now=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _insert_lifecycle_request_log_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        caller_identity: str,
        client_request_id: str,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            "insert into chat_request_log "
            "(id, conversation_id, tool_name, caller_identity, client_request_id, "
            "result_json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
            (
                _id("req"),
                conversation_id,
                COMPLETION_TOOL_NAME,
                caller_identity,
                client_request_id,
                _json(result),
                created_at,
            ),
        )

    def _record_projection_event_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        change: str,
        resource_ref: str,
        source_ref: str,
        payload: dict[str, Any],
        client_action_id: str | None,
        now: str,
    ) -> None:
        """Append a non-authoritative invalidation in the caller's Room transaction."""
        row = conn.execute(
            "select coalesce(max(seq), 0) + 1 next_seq from chat_frontend_events "
            "where conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        event_payload = {
            "kind": "room_projection_changed",
            "change": change,
            **payload,
        }
        conn.execute(
            """insert into chat_frontend_events
            (event_id, conversation_id, seq, event_type, resource_ref,
             source_authority, source_ref, payload_json, client_action_id,
             created_at, projection_only, proof_boundary)
            values (?, ?, ?, 'projection.changed', ?, 'chat.db:room_kernel', ?, ?, ?, ?, 1,
                    'frontend_event_not_authority')""",
            (
                _id("fevt"),
                conversation_id,
                int(row["next_seq"]),
                resource_ref,
                source_ref,
                _json(event_payload),
                client_action_id,
                now,
            ),
        )

    def _activity_from_conn(self, conn: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
        row = conn.execute(
            "select * from room_activities where activity_id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            raise KeyError(activity_id)
        return self._activity_from_row(row)

    def get_observation(self, observation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from room_observations where observation_id = ?", (observation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown room observation: {observation_id}")
        return self._observation_from_row(row)

    def get_outcome_policy(self, observation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from room_observations where observation_id = ?",
                (observation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown room observation: {observation_id}")
            source = self._activity_from_conn(conn, row["activity_id"])
            return _outcome_policy_conn(conn, observation=row, source=source)

    def list_projection_events(
        self, conversation_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        after_seq = max(0, after_seq)
        limit = min(500, max(1, limit))
        with self._connect() as conn:
            rows = conn.execute(
                """select * from room_activities where conversation_id = ?
                and seq > ? and delivery_mode = 'active' and materialized_message_id is not null
                order by seq limit ?""",
                (conversation_id, after_seq, limit),
            ).fetchall()
        return [
            {
                "sequence": row["seq"],
                "activity_id": row["activity_id"],
                "conversation_id": conversation_id,
                "event_type": row["activity_type"],
                "message_id": row["materialized_message_id"],
                "payload": self._activity_from_row(row)["payload"],
                "derived": True,
                "authority": "room_activities",
                "projection_only": True,
                "proof_boundary": "derived_from_room_authority",
            }
            for row in rows
        ]
