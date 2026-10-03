"""Durable Room coordination board: charters, contracts, progress, questions.

Every board write appends at least one ``board.`` activity to
``room_activities`` and updates the ``room_board_*`` tables in the same
``BEGIN IMMEDIATE`` transaction. Agent-facing writes are bound to a live
observation lease exactly like participant outcomes and are idempotent per
``(tool_name, caller_identity, client_request_id)``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_agent_kinds import ROOM_AGENT_CLI_KINDS
from xmuse_core.chat.room_batches import canonical_observation_id
from xmuse_core.chat.room_collaboration import collaboration_policy_row
from xmuse_core.chat.room_database import RoomDatabase

TOOL_READ = "chat_room_board_read"
TOOL_PROPOSE_SPLIT = "chat_room_board_propose_split"
TOOL_CLAIM = "chat_room_board_claim"
TOOL_PUBLISH_CONTRACT = "chat_room_board_publish_contract"
TOOL_REPORT_PROGRESS = "chat_room_board_report_progress"
TOOL_ASK = "chat_room_board_ask"

BOARD_ACTIVITY_SCHEMA_VERSION = "room_board_activity/v1"
BOARD_INBOX_LIMIT = 50
MAX_CONTRACT_CONTENT_BYTES = 65536

MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
CONTRACT_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
CHARTER_KEYS = frozenset(
    {"module_id", "title", "paths", "provides", "depends", "acceptance", "report_to"}
)
SPLIT_CONTRACT_KEYS = frozenset(
    {"contract_id", "provider_module_id", "kind", "content", "rationale"}
)
CONTRACT_KINDS = ("api_schema", "types", "protocol", "text")
PROGRESS_STATUSES = ("working", "blocked", "ready_for_review", "done")
WAKE_STATUSES = ("blocked", "ready_for_review")


def contract_digest(content: str) -> str:
    """Return the ``sha256:<hex>`` digest of contract content."""

    return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"


def normalize_charter(value: Any) -> dict[str, Any]:
    """Validate an untrusted charter dict and return its canonical form."""

    if not isinstance(value, dict):
        raise ValueError("room_board_charter_invalid: charter must be an object")
    unknown = set(value) - CHARTER_KEYS
    if unknown:
        raise ValueError(
            f"room_board_charter_invalid: unknown keys {sorted(str(item) for item in unknown)}"
        )
    module_id = value.get("module_id")
    if not isinstance(module_id, str) or not MODULE_ID_RE.match(module_id):
        raise ValueError("room_board_charter_invalid: module_id invalid")
    title = value.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ValueError("room_board_charter_invalid: title invalid")
    paths = value.get("paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise ValueError("room_board_charter_invalid: paths invalid")
    clean_paths: list[str] = []
    for entry in paths:
        if not isinstance(entry, str) or not entry:
            raise ValueError("room_board_charter_invalid: paths invalid")
        if entry.startswith("/") or "\\" in entry or ".." in entry.split("/"):
            raise ValueError("room_board_charter_invalid: paths must be relative POSIX globs")
        clean_paths.append(entry)
    provides = _normalize_contract_id_list(value.get("provides", []), "provides")
    depends = _normalize_contract_id_list(value.get("depends", []), "depends")
    acceptance_raw = value.get("acceptance", [])
    if not isinstance(acceptance_raw, list) or len(acceptance_raw) > 16:
        raise ValueError("room_board_charter_invalid: acceptance invalid")
    acceptance: list[str] = []
    for entry in acceptance_raw:
        if not isinstance(entry, str) or not entry.strip() or len(entry.strip()) > 500:
            raise ValueError("room_board_charter_invalid: acceptance invalid")
        acceptance.append(entry.strip())
    report_to = value.get("report_to")
    if report_to is not None and (not isinstance(report_to, str) or not report_to.strip()):
        raise ValueError("room_board_charter_invalid: report_to invalid")
    return {
        "module_id": module_id,
        "title": title.strip(),
        "paths": clean_paths,
        "provides": provides,
        "depends": depends,
        "acceptance": acceptance,
        "report_to": report_to.strip() if isinstance(report_to, str) else None,
    }


def _normalize_contract_id_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(f"room_board_charter_invalid: {field} invalid")
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not CONTRACT_ID_RE.match(entry):
            raise ValueError(f"room_board_charter_invalid: {field} invalid")
        result.append(entry)
    if len(set(result)) != len(result):
        raise ValueError(f"room_board_charter_invalid: {field} must be unique")
    return result


def normalize_split_contract(value: Any) -> dict[str, Any]:
    """Validate one contract spec inside a split proposal."""

    if not isinstance(value, dict):
        raise ValueError("room_board_contract_invalid: contract must be an object")
    unknown = set(value) - SPLIT_CONTRACT_KEYS
    if unknown:
        raise ValueError(
            f"room_board_contract_invalid: unknown keys {sorted(str(item) for item in unknown)}"
        )
    contract_id = value.get("contract_id")
    if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
        raise ValueError("room_board_contract_invalid: contract_id invalid")
    provider = value.get("provider_module_id")
    if not isinstance(provider, str) or not MODULE_ID_RE.match(provider):
        raise ValueError("room_board_contract_invalid: provider_module_id invalid")
    kind = value.get("kind")
    if kind not in CONTRACT_KINDS:
        raise ValueError("room_board_contract_invalid: kind invalid")
    content = value.get("content")
    if not isinstance(content, str):
        raise ValueError("room_board_contract_invalid: content invalid")
    if len(content.encode("utf-8")) > MAX_CONTRACT_CONTENT_BYTES:
        raise ValueError("room_board_content_too_large")
    rationale = value.get("rationale", "")
    if not isinstance(rationale, str):
        raise ValueError("room_board_contract_invalid: rationale invalid")
    return {
        "contract_id": contract_id,
        "provider_module_id": provider,
        "kind": kind,
        "content": content,
        "rationale": rationale,
    }


def parse_contract_ref(value: Any) -> tuple[str, int | None]:
    """Split a ``contract_id`` or ``contract_id@version`` reference."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("room_board_contract_ref_invalid")
    ref = value.strip()
    if "@" in ref:
        contract_id, _, version_text = ref.rpartition("@")
        if (
            not CONTRACT_ID_RE.match(contract_id)
            or not version_text.isdigit()
            or int(version_text) <= 0
        ):
            raise ValueError("room_board_contract_ref_invalid")
        return contract_id, int(version_text)
    if not CONTRACT_ID_RE.match(ref):
        raise ValueError("room_board_contract_ref_invalid")
    return ref, None


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


def _current_stamp(now: datetime | None) -> tuple[datetime, str]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("room_observation_now_timezone_required")
    return current, _timestamp(current)


class RoomBoardStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    @staticmethod
    def _activity_from_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["audience"] = _decode(value.pop("audience_json"))
        value["payload"] = _decode(value.pop("payload_json"))
        return value

    def _activity_from_conn(self, conn: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
        row = conn.execute(
            "select * from room_activities where activity_id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            raise KeyError(activity_id)
        return self._activity_from_row(row)

    @staticmethod
    def _lead_participant_id(conn: sqlite3.Connection, conversation_id: str) -> str | None:
        policy = collaboration_policy_row(conn, conversation_id)
        if policy is None:
            return None
        lead = policy["lead_participant_id"]
        return str(lead) if lead is not None else None

    @staticmethod
    def _get_participant_conn(
        conn: sqlite3.Connection, *, conversation_id: str, participant_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "select * from participants where conversation_id = ? and participant_id = ?",
            (conversation_id, participant_id),
        ).fetchone()
        if row is None:
            raise ValueError("room_observation_actor_forbidden")
        if row["status"] != "active" or row["cli_kind"] not in ROOM_AGENT_CLI_KINDS:
            raise ValueError("room_participant_not_active")
        return row

    @staticmethod
    def _check_caller_binding(caller_identity: str, participant_id: str) -> None:
        if not isinstance(caller_identity, str) or not caller_identity:
            raise ValueError("room_observation_actor_forbidden")
        if caller_identity.startswith("god:"):
            bound = caller_identity[4:].rpartition(":")[2]
            if not bound or bound != participant_id:
                raise ValueError("room_observation_actor_forbidden")

    def _check_lease_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        current: datetime,
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        self._get_participant_conn(
            conn, conversation_id=conversation_id, participant_id=participant_id
        )
        self._check_caller_binding(caller_identity, participant_id)
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ValueError("room_observation_lease_lost")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_observation_lease_lost")
        canonical_id = canonical_observation_id(conn, observation_id)
        row = conn.execute(
            "select * from room_observations where observation_id = ?", (canonical_id,)
        ).fetchone()
        if (
            row is None
            or row["conversation_id"] != conversation_id
            or row["participant_id"] != participant_id
            or row["status"] != "claimed"
            or row["control_state"] != "active"
            or row["lease_token"] != lease_token
            or not row["expires_at"]
            or _parse_timestamp(str(row["expires_at"])) <= current
        ):
            raise ValueError("room_observation_lease_lost")
        # Same attempt fence as lease renewal: only the live current attempt that
        # holds this exact token may coordinate; a failed attempt may not.
        attempt = (
            conn.execute(
                "select state, lease_token_digest from room_observation_attempts "
                "where attempt_id = ?",
                (row["current_attempt_id"],),
            ).fetchone()
            if row["current_attempt_id"]
            else None
        )
        if (
            attempt is None
            or attempt["state"] not in {"claimed", "delivering"}
            or attempt["lease_token_digest"] != sha256(lease_token.encode()).hexdigest()
        ):
            raise ValueError("room_observation_lease_lost")
        source = self._activity_from_conn(conn, str(row["activity_id"]))
        return row, source

    @staticmethod
    def _check_idempotency_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        prior = conn.execute(
            """select result_json from chat_request_log
               where conversation_id = ? and tool_name = ?
                 and caller_identity = ? and client_request_id = ?""",
            (conversation_id, tool_name, caller_identity, client_request_id),
        ).fetchone()
        if prior is None:
            return None
        result = json.loads(str(prior["result_json"]))
        if result.get("request_fingerprint") != fingerprint:
            raise ValueError("room_board_idempotency_conflict")
        return result

    @staticmethod
    def _write_request_log_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """insert into chat_request_log
               (id, conversation_id, tool_name, caller_identity, client_request_id,
                result_json, created_at) values (?, ?, ?, ?, ?, ?, ?)""",
            (
                _id("req"),
                conversation_id,
                tool_name,
                caller_identity,
                client_request_id,
                _json(result),
                created_at,
            ),
        )

    def _insert_board_activity_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        activity_type: str,
        actor_kind: str,
        actor_identity: str,
        actor_participant_id: str | None,
        causation_id: str,
        causal_depth: int,
        audience_participant_ids: list[str],
        payload: dict[str, Any],
        stamp: str,
    ) -> dict[str, Any]:
        seq = int(
            conn.execute(
                "select coalesce(max(seq), 0) + 1 from room_activities where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )
        activity_id = _id("activity")
        correlation_id = f"board_correlation_{sha256(activity_id.encode()).hexdigest()}"
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, materialized_message_id,
                causal_depth, materialized_proposal_id, delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'room', ?, ?, null, ?, null,
                       'active', ?)""",
            (
                activity_id,
                conversation_id,
                seq,
                activity_type,
                actor_kind,
                actor_identity,
                actor_participant_id,
                causation_id,
                correlation_id,
                _json(
                    {
                        "type": "board",
                        "conversation_id": conversation_id,
                        "participant_ids": list(audience_participant_ids),
                    }
                ),
                _json(payload),
                causal_depth,
                stamp,
            ),
        )
        return self._activity_from_conn(conn, activity_id)

    @staticmethod
    def _wake_participants_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        activity_id: str,
        participant_ids: list[str],
        stamp: str,
        priority: int = 100,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for participant_id in dict.fromkeys(participant_ids):
            observation_id = _id("observation")
            conn.execute(
                """insert into room_observations
                   (observation_id, conversation_id, activity_id, participant_id,
                    priority, delivery_mode, status, attempt_count, created_at, updated_at)
                   values (?, ?, ?, ?, ?, 'active', 'pending', 0, ?, ?)""",
                (
                    observation_id,
                    conversation_id,
                    activity_id,
                    participant_id,
                    priority,
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                """insert or ignore into room_participant_cursors
                   (conversation_id, participant_id, last_acknowledged_seq, updated_at)
                   values (?, ?, 0, ?)""",
                (conversation_id, participant_id, stamp),
            )
            observations.append(
                {
                    "observation_id": observation_id,
                    "conversation_id": conversation_id,
                    "activity_id": activity_id,
                    "participant_id": participant_id,
                    "priority": priority,
                    "status": "pending",
                }
            )
        return observations

    @staticmethod
    def _current_charter_conn(
        conn: sqlite3.Connection, *, conversation_id: str, module_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """select * from room_board_charters
               where conversation_id = ? and module_id = ?
               order by version desc limit 1""",
            (conversation_id, module_id),
        ).fetchone()

    @staticmethod
    def _active_charter_owner_map(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            "select * from room_board_charters where conversation_id = ? order by module_id",
            (conversation_id,),
        ).fetchall()
        current: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = str(row["module_id"])
            if key not in current or int(row["version"]) > int(current[key]["version"]):
                current[key] = row
        return {
            module_id: {
                "owner_participant_id": str(row["owner_participant_id"]),
                "status": str(row["status"]),
                "version": int(row["version"]),
                "charter": _decode(str(row["charter_json"])),
            }
            for module_id, row in current.items()
        }

    @staticmethod
    def _latest_contract_conn(
        conn: sqlite3.Connection, *, conversation_id: str, contract_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """select * from room_board_contracts
               where conversation_id = ? and contract_id = ?
               order by version desc limit 1""",
            (conversation_id, contract_id),
        ).fetchone()

    def read(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_ref: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
                charters = [
                    {
                        "module_id": module_id,
                        "version": info["version"],
                        "owner_participant_id": info["owner_participant_id"],
                        "status": info["status"],
                        "charter": info["charter"],
                    }
                    for module_id, info in sorted(charter_map.items())
                ]
                contract_rows = conn.execute(
                    "select * from room_board_contracts where conversation_id = ? "
                    "order by contract_id, version",
                    (conversation_id,),
                ).fetchall()
                latest: dict[str, sqlite3.Row] = {}
                for row in contract_rows:
                    latest[str(row["contract_id"])] = row
                contracts = [
                    {
                        "contract_id": str(row["contract_id"]),
                        "version": int(row["version"]),
                        "digest": str(row["digest"]),
                        "provider_module_id": str(row["provider_module_id"]),
                        "kind": str(row["kind"]),
                    }
                    for _, row in sorted(latest.items())
                ]
                cursor_row = conn.execute(
                    "select last_seen_seq from room_board_cursors "
                    "where conversation_id = ? and participant_id = ?",
                    (conversation_id, participant_id),
                ).fetchone()
                cursor_seq = int(cursor_row["last_seen_seq"]) if cursor_row else 0
                candidate_rows = conn.execute(
                    """select * from room_activities
                       where conversation_id = ? and seq > ?
                         and activity_type like 'board.%'
                       order by seq""",
                    (conversation_id, cursor_seq),
                ).fetchall()
                inbox: list[dict[str, Any]] = []
                # The cursor advances past every scanned activity, not only the
                # ones addressed to the caller, so foreign traffic never stalls it.
                last_scanned_seq = cursor_seq
                for row in candidate_rows:
                    activity = self._activity_from_row(row)
                    audience = activity.get("audience")
                    recipients = (
                        audience.get("participant_ids")
                        if isinstance(audience, dict) and audience.get("type") == "board"
                        else None
                    )
                    if isinstance(recipients, list) and participant_id in recipients:
                        if len(inbox) >= BOARD_INBOX_LIMIT:
                            break
                        inbox.append(activity)
                    last_scanned_seq = int(activity["seq"])
                if last_scanned_seq > cursor_seq:
                    last_seq = last_scanned_seq
                    conn.execute(
                        """insert into room_board_cursors
                           (conversation_id, participant_id, last_seen_seq, updated_at)
                           values (?, ?, ?, ?)
                           on conflict(conversation_id, participant_id) do update set
                             last_seen_seq = max(last_seen_seq, excluded.last_seen_seq),
                             updated_at = excluded.updated_at""",
                        (conversation_id, participant_id, last_seq, stamp),
                    )
                    cursor_seq = last_seq
                contract: dict[str, Any] | None = None
                if contract_ref is not None:
                    wanted_id, wanted_version = parse_contract_ref(contract_ref)
                    if wanted_version is None:
                        found = self._latest_contract_conn(
                            conn, conversation_id=conversation_id, contract_id=wanted_id
                        )
                    else:
                        found = conn.execute(
                            """select * from room_board_contracts
                               where conversation_id = ? and contract_id = ?
                                 and version = ?""",
                            (conversation_id, wanted_id, wanted_version),
                        ).fetchone()
                    if found is None:
                        raise ValueError("room_board_contract_unknown")
                    contract = {
                        "contract_id": str(found["contract_id"]),
                        "version": int(found["version"]),
                        "provider_module_id": str(found["provider_module_id"]),
                        "kind": str(found["kind"]),
                        "content": str(found["content"]),
                        "digest": str(found["digest"]),
                        "author_participant_id": str(found["author_participant_id"]),
                        "rationale": found["rationale"],
                        "activity_id": found["activity_id"],
                        "created_at": str(found["created_at"]),
                    }
                conn.commit()
                return {
                    "charters": charters,
                    "contracts": contracts,
                    "inbox": inbox,
                    "contract": contract,
                    "cursor_seq": cursor_seq,
                }
            except Exception:
                conn.rollback()
                raise

    def propose_split(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        modules: list[dict[str, Any]],
        assignments: dict[str, str],
        contracts: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(modules, list) or not modules:
            raise ValueError("room_board_modules_required")
        normalized_modules = [normalize_charter(item) for item in modules]
        module_ids = [item["module_id"] for item in normalized_modules]
        if len(set(module_ids)) != len(module_ids):
            raise ValueError("room_board_module_duplicate")
        if not isinstance(assignments, dict) or set(assignments) != set(module_ids):
            raise ValueError("room_board_assignment_invalid")
        for assignee in assignments.values():
            if not isinstance(assignee, str) or not assignee.strip():
                raise ValueError("room_board_assignment_invalid")
        if not isinstance(contracts, list):
            raise ValueError("room_board_contract_invalid: contracts must be a list")
        normalized_contracts = [normalize_split_contract(item) for item in contracts]
        contract_ids = [item["contract_id"] for item in normalized_contracts]
        if len(set(contract_ids)) != len(contract_ids):
            raise ValueError("room_board_contract_duplicate")
        for spec in normalized_contracts:
            if spec["provider_module_id"] not in module_ids:
                raise ValueError("room_board_contract_provider_unknown")
        for charter in normalized_modules:
            for wanted in charter["provides"]:
                if not any(
                    spec["contract_id"] == wanted
                    and spec["provider_module_id"] == charter["module_id"]
                    for spec in normalized_contracts
                ):
                    raise ValueError("room_board_contract_missing")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_PROPOSE_SPLIT,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "modules": normalized_modules,
                    "assignments": assignments,
                    "contracts": normalized_contracts,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PROPOSE_SPLIT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                if self._lead_participant_id(conn, conversation_id) != participant_id:
                    raise ValueError("room_board_lead_required")
                report_targets = [
                    str(item["report_to"]) for item in normalized_modules if item["report_to"]
                ]
                for assignee in [*assignments.values(), *report_targets]:
                    row = conn.execute(
                        "select * from participants "
                        "where conversation_id = ? and participant_id = ?",
                        (conversation_id, assignee),
                    ).fetchone()
                    if row is None:
                        raise ValueError("room_board_assignee_unknown")
                    if row["status"] != "active" or row["cli_kind"] not in ROOM_AGENT_CLI_KINDS:
                        raise ValueError("room_board_assignee_inactive")
                split_id = _id("split")
                payload_contracts = [
                    {
                        "contract_id": spec["contract_id"],
                        "provider_module_id": spec["provider_module_id"],
                        "kind": spec["kind"],
                        "digest": contract_digest(spec["content"]),
                        "rationale": spec["rationale"],
                    }
                    for spec in normalized_contracts
                ]
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.split_proposed",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "split_id": split_id,
                        "modules": normalized_modules,
                        "assignments": assignments,
                        "contracts": payload_contracts,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_splits
                       (split_id, conversation_id, proposed_by_participant_id, status,
                        split_json, activity_id, approved_by, decided_at, created_at)
                       values (?, ?, ?, 'proposed', ?, ?, null, null, ?)""",
                    (
                        split_id,
                        conversation_id,
                        participant_id,
                        _json(
                            {
                                "modules": normalized_modules,
                                "assignments": assignments,
                                "contracts": normalized_contracts,
                            }
                        ),
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                result = {
                    "split_id": split_id,
                    "status": "proposed",
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "modules": list(module_ids),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PROPOSE_SPLIT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def decide_split(
        self,
        *,
        conversation_id: str,
        split_id: str,
        decision: str,
        operator_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if decision not in ("approve", "reject"):
            raise ValueError("room_board_decision_invalid")
        if not isinstance(operator_identity, str) or not operator_identity.strip():
            raise ValueError("room_operator_identity_required")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                split = conn.execute(
                    "select * from room_board_splits where split_id = ? and conversation_id = ?",
                    (split_id, conversation_id),
                ).fetchone()
                if split is None:
                    raise ValueError("room_board_split_unknown")
                if str(split["status"]) != "proposed":
                    raise ValueError("room_board_split_decided")
                proposal = self._activity_from_conn(conn, str(split["activity_id"]))
                bundle = _decode(str(split["split_json"]))
                normalized_modules = list(bundle["modules"])
                assignments = dict(bundle["assignments"])
                normalized_contracts = list(bundle["contracts"])
                if decision == "reject":
                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_type="board.split_rejected",
                        actor_kind="operator",
                        actor_identity=operator_identity,
                        actor_participant_id=None,
                        causation_id=str(split["activity_id"]),
                        causal_depth=int(proposal["causal_depth"]) + 1,
                        audience_participant_ids=[str(split["proposed_by_participant_id"])],
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "split_id": split_id,
                            "decision": "rejected",
                        },
                        stamp=stamp,
                    )
                    conn.execute(
                        "update room_board_splits set status = 'rejected', "
                        "approved_by = ?, decided_at = ? "
                        "where split_id = ? and conversation_id = ?",
                        (operator_identity, stamp, split_id, conversation_id),
                    )
                    conn.commit()
                    return {
                        "split_id": split_id,
                        "status": "rejected",
                        "activity_id": str(activity["activity_id"]),
                        "activity_seq": int(activity["seq"]),
                    }
                for charter in normalized_modules:
                    existing = conn.execute(
                        """select 1 from room_board_charters
                           where conversation_id = ? and module_id = ?
                             and status = 'active' limit 1""",
                        (conversation_id, charter["module_id"]),
                    ).fetchone()
                    if existing is not None:
                        raise ValueError("room_board_charter_active")
                activity_ids: list[str] = []
                for charter in normalized_modules:
                    module_id = str(charter["module_id"])
                    owner = str(assignments[module_id])
                    conn.execute(
                        """insert into room_board_charters
                           (conversation_id, module_id, version, split_id,
                            owner_participant_id, status, charter_json, claimed_at,
                            created_at)
                           values (?, ?, 1, ?, ?, 'active', ?, null, ?)""",
                        (
                            conversation_id,
                            module_id,
                            split_id,
                            owner,
                            _json(charter),
                            stamp,
                        ),
                    )
                    module_contracts = [
                        spec
                        for spec in normalized_contracts
                        if spec["provider_module_id"] == module_id
                    ]
                    for spec in module_contracts:
                        conn.execute(
                            """insert into room_board_contracts
                               (conversation_id, contract_id, version, provider_module_id,
                                kind, content, digest, author_participant_id, rationale,
                                activity_id, created_at)
                               values (?, ?, 1, ?, ?, ?, ?, ?, ?, null, ?)""",
                            (
                                conversation_id,
                                spec["contract_id"],
                                module_id,
                                spec["kind"],
                                spec["content"],
                                contract_digest(spec["content"]),
                                owner,
                                spec["rationale"],
                                stamp,
                            ),
                        )
                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_type="board.charter_assigned",
                        actor_kind="operator",
                        actor_identity=operator_identity,
                        actor_participant_id=None,
                        causation_id=str(split["activity_id"]),
                        causal_depth=int(proposal["causal_depth"]) + 1,
                        audience_participant_ids=[owner],
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "split_id": split_id,
                            "module_id": module_id,
                            "version": 1,
                            "owner_participant_id": owner,
                            "charter": charter,
                            "contracts": [
                                {
                                    "contract_id": spec["contract_id"],
                                    "version": 1,
                                    "digest": contract_digest(spec["content"]),
                                    "kind": spec["kind"],
                                    "provider_module_id": module_id,
                                }
                                for spec in module_contracts
                            ],
                        },
                        stamp=stamp,
                    )
                    activity_ids.append(str(activity["activity_id"]))
                    for spec in module_contracts:
                        conn.execute(
                            "update room_board_contracts set activity_id = ? "
                            "where conversation_id = ? and contract_id = ? and version = 1",
                            (str(activity["activity_id"]), conversation_id, spec["contract_id"]),
                        )
                    self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=[owner],
                        stamp=stamp,
                    )
                conn.execute(
                    "update room_board_splits set status = 'approved', approved_by = ?, "
                    "decided_at = ? where split_id = ? and conversation_id = ?",
                    (operator_identity, stamp, split_id, conversation_id),
                )
                conn.commit()
                return {
                    "split_id": split_id,
                    "status": "approved",
                    "modules": [str(item["module_id"]) for item in normalized_modules],
                    "contracts": [
                        {"contract_id": str(spec["contract_id"]), "version": 1}
                        for spec in normalized_contracts
                    ],
                    "activity_ids": activity_ids,
                }
            except Exception:
                conn.rollback()
                raise

    def claim(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(module_id, str) or not module_id:
            raise ValueError("room_board_module_unknown")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_CLAIM,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "module_id": module_id,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_CLAIM,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                if charter is None or str(charter["status"]) != "active":
                    raise ValueError("room_board_module_unknown")
                if str(charter["owner_participant_id"]) != participant_id:
                    raise ValueError("room_board_not_owner")
                version = int(charter["version"])
                if charter["claimed_at"] is not None:
                    original = self._find_claim_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        module_id=module_id,
                        version=version,
                    )
                    result = {
                        "module_id": module_id,
                        "version": version,
                        "claimed_at": str(charter["claimed_at"]),
                        "activity_id": original,
                        "activity_seq": None,
                        "request_fingerprint": fingerprint,
                    }
                    if original is not None:
                        try:
                            activity = self._activity_from_conn(conn, original)
                            result["activity_seq"] = int(activity["seq"])
                        except KeyError:
                            pass
                    self._write_request_log_conn(
                        conn,
                        conversation_id=conversation_id,
                        tool_name=TOOL_CLAIM,
                        caller_identity=caller_identity,
                        client_request_id=client_request_id,
                        result=result,
                        created_at=stamp,
                    )
                    conn.commit()
                    return result
                conn.execute(
                    """update room_board_charters set claimed_at = ?
                       where conversation_id = ? and module_id = ? and version = ?""",
                    (stamp, conversation_id, module_id, version),
                )
                lead = self._lead_participant_id(conn, conversation_id)
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.claimed",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[lead] if lead else [participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "module_id": module_id,
                        "version": version,
                        "owner_participant_id": participant_id,
                    },
                    stamp=stamp,
                )
                result = {
                    "module_id": module_id,
                    "version": version,
                    "claimed_at": stamp,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_CLAIM,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _find_claim_activity_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        module_id: str,
        version: int,
    ) -> str | None:
        rows = conn.execute(
            """select activity_id, payload_json from room_activities
               where conversation_id = ? and activity_type = 'board.claimed'
               order by seq desc limit 20""",
            (conversation_id,),
        ).fetchall()
        for row in rows:
            payload = _decode(str(row["payload_json"]))
            if (
                isinstance(payload, dict)
                and payload.get("module_id") == module_id
                and int(payload.get("version", -1)) == version
            ):
                return str(row["activity_id"])
        return None

    def publish_contract(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_id: str,
        kind: str,
        content: str,
        base_version: int | None,
        rationale: str = "",
        provider_module_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
            raise ValueError("room_board_contract_id_invalid")
        if kind not in CONTRACT_KINDS:
            raise ValueError("room_board_contract_kind_invalid")
        if not isinstance(content, str):
            raise ValueError("room_board_contract_invalid: content invalid")
        if len(content.encode("utf-8")) > MAX_CONTRACT_CONTENT_BYTES:
            raise ValueError("room_board_content_too_large")
        if base_version is not None and (
            isinstance(base_version, bool) or not isinstance(base_version, int) or base_version <= 0
        ):
            raise ValueError("room_board_contract_version_invalid")
        if not isinstance(rationale, str):
            raise ValueError("room_board_contract_invalid: rationale invalid")
        if provider_module_id is not None and (
            not isinstance(provider_module_id, str) or not MODULE_ID_RE.match(provider_module_id)
        ):
            raise ValueError("room_board_contract_provider_invalid")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_PUBLISH_CONTRACT,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "contract_id": contract_id,
                    "kind": kind,
                    "content": content,
                    "base_version": base_version,
                    "rationale": rationale,
                    "provider_module_id": provider_module_id,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PUBLISH_CONTRACT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                lead = self._lead_participant_id(conn, conversation_id)
                is_lead = lead is not None and lead == participant_id
                latest = self._latest_contract_conn(
                    conn, conversation_id=conversation_id, contract_id=contract_id
                )
                if base_version is None:
                    if latest is not None:
                        raise ValueError(
                            "room_board_contract_conflict: contract "
                            f"{contract_id} already at version {int(latest['version'])}"
                        )
                    provider = self._resolve_new_contract_provider_conn(
                        conn,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        contract_id=contract_id,
                        provider_module_id=provider_module_id,
                        is_lead=is_lead,
                    )
                    version = 1
                else:
                    if latest is None:
                        raise ValueError("room_board_contract_unknown")
                    if int(latest["version"]) != base_version:
                        raise ValueError(
                            "room_board_contract_conflict: contract "
                            f"{contract_id} latest version is {int(latest['version'])}"
                        )
                    provider = str(latest["provider_module_id"])
                    if not is_lead:
                        owner_row = self._current_charter_conn(
                            conn, conversation_id=conversation_id, module_id=provider
                        )
                        if (
                            owner_row is None
                            or str(owner_row["status"]) != "active"
                            or str(owner_row["owner_participant_id"]) != participant_id
                        ):
                            raise ValueError("room_board_not_owner")
                    version = int(latest["version"]) + 1
                digest = contract_digest(content)
                audience = self._dependent_owner_ids_conn(
                    conn,
                    conversation_id=conversation_id,
                    contract_id=contract_id,
                    exclude_participant_id=participant_id,
                )
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type=(
                        "board.contract_published" if version == 1 else "board.contract_revised"
                    ),
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=audience,
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "contract_id": contract_id,
                        "version": version,
                        "digest": digest,
                        "provider_module_id": provider,
                        "kind": kind,
                        "rationale": rationale,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_contracts
                       (conversation_id, contract_id, version, provider_module_id,
                        kind, content, digest, author_participant_id, rationale,
                        activity_id, created_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        conversation_id,
                        contract_id,
                        version,
                        provider,
                        kind,
                        content,
                        digest,
                        participant_id,
                        rationale,
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                self._wake_participants_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_id=str(activity["activity_id"]),
                    participant_ids=audience,
                    stamp=stamp,
                )
                result = {
                    "contract_id": contract_id,
                    "version": version,
                    "digest": digest,
                    "provider_module_id": provider,
                    "kind": kind,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PUBLISH_CONTRACT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _resolve_new_contract_provider_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
        contract_id: str,
        provider_module_id: str | None,
        is_lead: bool,
    ) -> str:
        charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
        owned_providing = sorted(
            module_id
            for module_id, info in charter_map.items()
            if info["owner_participant_id"] == participant_id
            and info["status"] == "active"
            and contract_id in (info["charter"].get("provides", []))
        )
        if provider_module_id is not None:
            info = charter_map.get(provider_module_id)
            if info is None or info["status"] != "active":
                raise ValueError("room_board_module_unknown")
            if not is_lead and (
                info["owner_participant_id"] != participant_id
                or contract_id not in info["charter"].get("provides", [])
            ):
                raise ValueError("room_board_not_owner")
            return provider_module_id
        if owned_providing:
            return owned_providing[0]
        if is_lead:
            raise ValueError("room_board_contract_provider_required")
        raise ValueError("room_board_not_owner")

    def _dependent_owner_ids_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        contract_id: str,
        exclude_participant_id: str,
    ) -> list[str]:
        charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
        owners: list[str] = []
        for module_id in sorted(charter_map):
            info = charter_map[module_id]
            if info["status"] != "active":
                continue
            charter = info["charter"]
            depends = charter.get("depends", []) if isinstance(charter, dict) else []
            owner = str(info["owner_participant_id"])
            if contract_id in depends and owner != exclude_participant_id and owner not in owners:
                owners.append(owner)
        return owners

    def report_progress(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
        status: str,
        summary: str,
        claims: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(module_id, str) or not module_id:
            raise ValueError("room_board_module_unknown")
        if status not in PROGRESS_STATUSES:
            raise ValueError("room_board_status_invalid")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            raise ValueError("room_board_summary_invalid")
        clean_claims = self._normalize_progress_claims(claims)
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_REPORT_PROGRESS,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "module_id": module_id,
                    "status": status,
                    "summary": summary,
                    "claims": clean_claims,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REPORT_PROGRESS,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                if charter is None or str(charter["status"]) != "active":
                    raise ValueError("room_board_module_unknown")
                if str(charter["owner_participant_id"]) != participant_id:
                    raise ValueError("room_board_not_owner")
                charter_body = _decode(str(charter["charter_json"]))
                report_to = (
                    charter_body.get("report_to") if isinstance(charter_body, dict) else None
                )
                lead = self._lead_participant_id(conn, conversation_id)
                recipient = report_to or lead
                progress_id = _id("progress")
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.progress",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[recipient] if recipient else [],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "progress_id": progress_id,
                        "module_id": module_id,
                        "status": status,
                        "summary": summary,
                        "claims": clean_claims,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_progress
                       (progress_id, conversation_id, module_id, participant_id,
                        status, summary, claims_json, activity_id, created_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        progress_id,
                        conversation_id,
                        module_id,
                        participant_id,
                        status,
                        summary,
                        _json(clean_claims),
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                woken: list[dict[str, Any]] = []
                if status in WAKE_STATUSES and recipient:
                    woken = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=[recipient],
                        stamp=stamp,
                    )
                result = {
                    "progress_id": progress_id,
                    "module_id": module_id,
                    "status": status,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken],
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REPORT_PROGRESS,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _normalize_progress_claims(claims: list[str] | None) -> list[str]:
        if claims is None:
            return []
        if not isinstance(claims, list) or len(claims) > 32:
            raise ValueError("room_board_claims_invalid")
        cleaned: list[str] = []
        for entry in claims:
            if not isinstance(entry, str) or not entry.strip() or len(entry.strip()) > 500:
                raise ValueError("room_board_claims_invalid")
            cleaned.append(entry.strip())
        return cleaned

    def ask(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        target_participant_id: str,
        question: str,
        references: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(target_participant_id, str) or not target_participant_id.strip():
            raise ValueError("room_board_target_unknown")
        if target_participant_id == participant_id:
            raise ValueError("room_board_ask_self")
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            raise ValueError("room_board_question_invalid")
        clean_references = self._normalize_references(references)
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_ASK,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "target_participant_id": target_participant_id,
                    "question": question,
                    "references": clean_references,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_ASK,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                target = conn.execute(
                    "select * from participants where conversation_id = ? and participant_id = ?",
                    (conversation_id, target_participant_id),
                ).fetchone()
                if (
                    target is None
                    or target["status"] != "active"
                    or target["cli_kind"] not in ROOM_AGENT_CLI_KINDS
                ):
                    raise ValueError("room_board_target_unknown")
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.question",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[target_participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "target_participant_id": target_participant_id,
                        "question": question,
                        "references": clean_references,
                    },
                    stamp=stamp,
                )
                self._wake_participants_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_id=str(activity["activity_id"]),
                    participant_ids=[target_participant_id],
                    stamp=stamp,
                )
                result = {
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "target_participant_id": target_participant_id,
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_ASK,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _normalize_references(references: list[str] | None) -> list[str]:
        if references is None:
            return []
        if not isinstance(references, list) or len(references) > 16:
            raise ValueError("room_board_references_invalid")
        for entry in references:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError("room_board_references_invalid")
        return list(references)

    def owner_view(self, conversation_id: str, participant_id: str) -> dict[str, Any]:
        """Pure read of one owner's board slice (no lease, no writes)."""

        with self._connect() as conn:
            charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
            my_modules: list[dict[str, Any]] = []
            other_modules: list[dict[str, Any]] = []
            for module_id in sorted(charter_map):
                info = charter_map[module_id]
                if str(info["status"]) != "active":
                    continue
                body = info["charter"] if isinstance(info["charter"], dict) else {}
                provides = list(body.get("provides", [])) if isinstance(body, dict) else []
                depends = list(body.get("depends", [])) if isinstance(body, dict) else []
                if str(info["owner_participant_id"]) == participant_id:
                    my_modules.append(
                        {
                            "module_id": module_id,
                            "version": int(info["version"]),
                            "owner_participant_id": str(info["owner_participant_id"]),
                            "status": str(info["status"]),
                            "charter": body,
                        }
                    )
                else:
                    other_modules.append(
                        {
                            "module_id": module_id,
                            "version": int(info["version"]),
                            "owner_participant_id": str(info["owner_participant_id"]),
                            "provides": provides,
                            "depends": depends,
                        }
                    )
            wanted: set[str] = set()
            for entry in my_modules:
                charter = entry.get("charter")
                if not isinstance(charter, dict):
                    continue
                for key in ("provides", "depends"):
                    items = charter.get(key, [])
                    if isinstance(items, list):
                        for contract_id in items:
                            if isinstance(contract_id, str):
                                wanted.add(contract_id)
            contracts: list[dict[str, Any]] = []
            for contract_id in sorted(wanted):
                row = self._latest_contract_conn(
                    conn, conversation_id=conversation_id, contract_id=contract_id
                )
                if row is None:
                    continue
                contracts.append(
                    {
                        "contract_id": str(row["contract_id"]),
                        "version": int(row["version"]),
                        "digest": str(row["digest"]),
                        "provider_module_id": str(row["provider_module_id"]),
                        "kind": str(row["kind"]),
                        "content": str(row["content"]),
                        "author_participant_id": str(row["author_participant_id"]),
                        "rationale": row["rationale"],
                        "activity_id": row["activity_id"],
                        "created_at": str(row["created_at"]),
                    }
                )
            seq_row = conn.execute(
                "select coalesce(max(seq), 0) from room_activities "
                "where conversation_id = ? and activity_type like 'board.%'",
                (conversation_id,),
            ).fetchone()
            board_seq = int(seq_row[0]) if seq_row is not None else 0
            return {
                "conversation_id": conversation_id,
                "participant_id": participant_id,
                "board_seq": board_seq,
                "my_modules": my_modules,
                "other_modules": other_modules,
                "contracts": contracts,
            }

    def board_projection(self, conversation_id: str) -> dict[str, Any]:
        """Operator projection: splits, current charters, latest contracts/progress."""

        with self._connect() as conn:
            split_rows = conn.execute(
                "select * from room_board_splits where conversation_id = ? "
                "order by created_at, split_id",
                (conversation_id,),
            ).fetchall()
            splits: list[dict[str, Any]] = []
            for split in split_rows:
                bundle = _decode(str(split["split_json"]))
                modules = bundle.get("modules", []) if isinstance(bundle, dict) else []
                assignments = bundle.get("assignments", {}) if isinstance(bundle, dict) else {}
                specs = bundle.get("contracts", []) if isinstance(bundle, dict) else []
                summaries: list[dict[str, Any]] = []
                for spec in specs if isinstance(specs, list) else []:
                    if not isinstance(spec, dict):
                        continue
                    summaries.append(
                        {
                            "contract_id": str(spec.get("contract_id")),
                            "provider_module_id": str(spec.get("provider_module_id")),
                            "kind": str(spec.get("kind")),
                            "digest": contract_digest(str(spec.get("content", ""))),
                        }
                    )
                summaries.sort(key=lambda item: str(item["contract_id"]))
                decided_at = split["decided_at"]
                splits.append(
                    {
                        "split_id": str(split["split_id"]),
                        "status": str(split["status"]),
                        "proposed_by_participant_id": str(split["proposed_by_participant_id"]),
                        "created_at": str(split["created_at"]),
                        "decided_at": None if decided_at is None else str(decided_at),
                        "modules": modules,
                        "assignments": assignments,
                        "contracts": summaries,
                    }
                )
            charter_rows = conn.execute(
                "select * from room_board_charters where conversation_id = ? "
                "order by module_id, version",
                (conversation_id,),
            ).fetchall()
            latest_charters: dict[str, sqlite3.Row] = {}
            for row in charter_rows:
                latest_charters[str(row["module_id"])] = row
            charters: list[dict[str, Any]] = []
            for module_id in sorted(latest_charters):
                row = latest_charters[module_id]
                claimed_at = row["claimed_at"]
                charters.append(
                    {
                        "module_id": str(row["module_id"]),
                        "version": int(row["version"]),
                        "owner_participant_id": str(row["owner_participant_id"]),
                        "status": str(row["status"]),
                        "charter": _decode(str(row["charter_json"])),
                        "split_id": str(row["split_id"]),
                        "claimed_at": None if claimed_at is None else str(claimed_at),
                        "created_at": str(row["created_at"]),
                    }
                )
            contract_rows = conn.execute(
                "select * from room_board_contracts where conversation_id = ? "
                "order by contract_id, version",
                (conversation_id,),
            ).fetchall()
            latest_contracts: dict[str, sqlite3.Row] = {}
            for row in contract_rows:
                latest_contracts[str(row["contract_id"])] = row
            contracts: list[dict[str, Any]] = []
            for contract_id in sorted(latest_contracts):
                row = latest_contracts[contract_id]
                contracts.append(
                    {
                        "contract_id": str(row["contract_id"]),
                        "id": str(row["contract_id"]),
                        "version": int(row["version"]),
                        "digest": str(row["digest"]),
                        "provider_module_id": str(row["provider_module_id"]),
                        "kind": str(row["kind"]),
                        "author_participant_id": str(row["author_participant_id"]),
                        "author": str(row["author_participant_id"]),
                        "created_at": str(row["created_at"]),
                    }
                )
            progress_rows = conn.execute(
                "select * from room_board_progress where conversation_id = ? "
                "order by created_at, progress_id",
                (conversation_id,),
            ).fetchall()
            latest_progress: dict[str, sqlite3.Row] = {}
            for row in progress_rows:
                latest_progress[str(row["module_id"])] = row
            progress: list[dict[str, Any]] = []
            for module_id in sorted(latest_progress):
                row = latest_progress[module_id]
                progress.append(
                    {
                        "progress_id": str(row["progress_id"]),
                        "module_id": str(row["module_id"]),
                        "participant_id": str(row["participant_id"]),
                        "status": str(row["status"]),
                        "summary": str(row["summary"]),
                        "claims": _decode(str(row["claims_json"])),
                        "activity_id": row["activity_id"],
                        "created_at": str(row["created_at"]),
                    }
                )
            activity_rows = conn.execute(
                "select * from room_activities where conversation_id = ? "
                "and activity_type like 'board.%' order by seq desc limit 50",
                (conversation_id,),
            ).fetchall()
            activities: list[dict[str, Any]] = []
            for row in reversed(activity_rows):
                audience = _decode(row["audience_json"]) if row["audience_json"] else None
                participant_ids = (
                    audience.get("participant_ids") if isinstance(audience, dict) else None
                )
                if not isinstance(participant_ids, list):
                    participant_ids = []
                activities.append(
                    {
                        "activity_id": str(row["activity_id"]),
                        "seq": int(row["seq"]),
                        "activity_type": str(row["activity_type"]),
                        "actor_participant_id": row["actor_participant_id"],
                        "audience_participant_ids": list(participant_ids),
                        "audience": list(participant_ids),
                        "payload": _decode(str(row["payload_json"])),
                        "created_at": str(row["created_at"]),
                    }
                )
            return {
                "schema_version": "room_board_projection/v1",
                "conversation_id": conversation_id,
                "splits": splits,
                "charters": charters,
                "contracts": contracts,
                "progress": progress,
                "activities": activities,
            }

    def board_contract_detail(
        self,
        conversation_id: str,
        contract_id: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one contract with content, or None when unknown."""

        with self._connect() as conn:
            if version is None:
                row = self._latest_contract_conn(
                    conn, conversation_id=conversation_id, contract_id=contract_id
                )
            else:
                row = conn.execute(
                    """select * from room_board_contracts
                       where conversation_id = ? and contract_id = ? and version = ?""",
                    (conversation_id, contract_id, version),
                ).fetchone()
            if row is None:
                return None
            return {
                "contract_id": str(row["contract_id"]),
                "id": str(row["contract_id"]),
                "version": int(row["version"]),
                "digest": str(row["digest"]),
                "provider_module_id": str(row["provider_module_id"]),
                "kind": str(row["kind"]),
                "content": str(row["content"]),
                "author_participant_id": str(row["author_participant_id"]),
                "author": str(row["author_participant_id"]),
                "rationale": row["rationale"],
                "activity_id": row["activity_id"],
                "created_at": str(row["created_at"]),
            }
