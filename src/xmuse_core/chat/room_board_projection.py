"""Room board read model v2: pure derivation over plain data + builders.

``chat.db`` is the only authority. Everything here is a read-only projection:
pure functions take small plain-data shapes (dataclasses below), and the
loader/builders read an open ``sqlite3.Connection`` into those shapes. No
function here opens a connection, writes state, or reads the clock.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

PROJECTION_SCHEMA_VERSION = "room_board_projection/v2"
METRICS_VERSION = "board_metrics/v1"
SUMMARY_SCHEMA_VERSION = "room_board_summary/v1"
EVENTS_SCHEMA_VERSION = "room_board_events/v1"
CONTRACT_SCHEMA_VERSION = "room_board_contract/v2"

MAX_CONSECUTIVE_FAILURES = 3

BOARD_VERIFICATION_WAITING_FOR_PROVIDER = "board_verification_waiting_for_provider"

LIFECYCLES = (
    "assigned",
    "claimed",
    "working",
    "blocked",
    "ready_for_review",
    "done_claimed",
)
VERIFICATION_STATUSES = (
    "none",
    "waiting_for_provider",
    "pending",
    "running",
    "passed",
    "failed",
    "error",
)
STATES = (
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
)


# ---------------------------------------------------------------------------
# agent text
# ---------------------------------------------------------------------------

_BIDI_RE = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _strip_unsafe(value: str) -> str:
    """Remove ANSI escape sequences, bidi controls, and C0/C1 controls."""

    cleaned = _ANSI_OSC_RE.sub("", value)
    cleaned = _ANSI_CSI_RE.sub("", cleaned)
    cleaned = _BIDI_RE.sub("", cleaned)
    return _CONTROL_RE.sub("", cleaned)


def sanitize_text(value: Any) -> str:
    """Strip unsafe characters from agent-authored text (no truncation)."""

    if not isinstance(value, str):
        return ""
    return _strip_unsafe(value)


def agent_text(value: Any, *, max_chars: int) -> dict[str, Any]:
    """Wrap one agent-authored string so consumers cannot render it by accident."""

    cleaned = sanitize_text(value)
    truncated = len(cleaned) > max_chars
    return {
        "text": cleaned[:max_chars],
        "untrusted": True,
        "truncated": truncated,
    }


def _maybe_agent_text(value: Any, *, max_chars: int) -> dict[str, Any] | None:
    """Wrap a non-empty rationale-like field, else None."""

    if not isinstance(value, str) or not value.strip():
        return None
    return agent_text(value, max_chars=max_chars)


# ---------------------------------------------------------------------------
# plain-data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressFact:
    """One progress report row, reduced to derivation inputs."""

    status: str
    participant_id: str
    created_at: str
    seq: int


@dataclass(frozen=True)
class StackedRef:
    module_id: str
    verification_id: str


@dataclass(frozen=True)
class VerificationFact:
    """One verification job row, reduced to derivation inputs."""

    verification_id: str
    status: str
    reason_code: str | None
    gate_ids: list[str] = field(default_factory=list)
    stacked: list[StackedRef] = field(default_factory=list)
    head_commit: str | None = None
    changed_path_count: int = 0
    created_at: str = ""
    updated_at: str | None = None


@dataclass(frozen=True)
class RevisedContract:
    contract_id: str
    revised_version: int
    revised_seq: int
    provider_module_id: str


@dataclass(frozen=True)
class CharterDependency:
    module_id: str
    owner_participant_id: str
    depends: list[str] = field(default_factory=list)


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


# ---------------------------------------------------------------------------
# pure derivation
# ---------------------------------------------------------------------------


def derive_lifecycle(
    *,
    claimed_at: str | None,
    charter_created_at: str,
    owner_participant_id: str,
    reports: Sequence[ProgressFact],
) -> str:
    """Derive what the owner says: latest in-charter report wins."""

    charter_ts = _parse_ts(charter_created_at)
    latest: ProgressFact | None = None
    for report in reports:
        if report.participant_id != owner_participant_id:
            continue
        if _parse_ts(report.created_at) < charter_ts:
            continue
        if latest is None or _parse_ts(report.created_at) >= _parse_ts(latest.created_at):
            latest = report
    if latest is None:
        return "claimed" if claimed_at is not None else "assigned"
    if latest.status == "done":
        return "done_claimed"
    return latest.status


def compute_escalated(trailing_terminal_statuses: Sequence[str]) -> bool:
    """True when the newest-first terminal run holds enough failures."""

    consecutive = 0
    for status in trailing_terminal_statuses:
        if status != "failed":
            break
        consecutive += 1
    return consecutive >= MAX_CONSECUTIVE_FAILURES


def _none_verification() -> dict[str, Any]:
    return {
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


def derive_verification_axis(
    *,
    charter_created_at: str,
    jobs: Sequence[VerificationFact],
) -> dict[str, Any]:
    """Derive what the host proved from in-charter, non-superseded jobs."""

    charter_ts = _parse_ts(charter_created_at)
    scoped = [
        job
        for job in jobs
        if job.created_at and _parse_ts(job.created_at) >= charter_ts and job.status != "superseded"
    ]
    if not scoped:
        return _none_verification()
    # The loader passes rows ordered by (created_at, rowid); a stable sort
    # keeps that rowid order for equal timestamps, so the last item is the
    # latest row per the (created_at, rowid) rule.
    ordered = sorted(scoped, key=lambda job: _parse_ts(job.created_at))
    latest = ordered[-1]
    trailing = [job.status for job in reversed(ordered) if job.status in ("passed", "failed")]
    status = latest.status
    if status == "pending" and latest.reason_code == BOARD_VERIFICATION_WAITING_FOR_PROVIDER:
        status = "waiting_for_provider"
    escalated = status == "failed" and compute_escalated(trailing)
    return {
        "status": status,
        "verification_id": latest.verification_id,
        "reason_code": latest.reason_code,
        "escalated": escalated,
        "gate_ids": list(latest.gate_ids) if status == "failed" else [],
        "stacked": [
            {"module_id": ref.module_id, "verification_id": ref.verification_id}
            for ref in latest.stacked
        ],
        "head_commit": latest.head_commit,
        "changed_path_count": latest.changed_path_count,
        "updated_at": latest.updated_at,
    }


def derive_state(lifecycle: str, verification_status: str) -> str:
    """Derive the single compact-UI value from the two independent axes."""

    if lifecycle != "done_claimed":
        return lifecycle
    return {
        "passed": "verified",
        "failed": "verification_failed",
        "error": "verification_error",
        "pending": "verifying",
        "running": "verifying",
        "waiting_for_provider": "waiting_for_provider",
        "none": "done_claimed",
    }[verification_status]


def compute_counters(verification_statuses: Sequence[str], *, done_reports: int) -> dict[str, int]:
    """Per-module metrics over the module id's whole history (M1 definitions)."""

    counts = {"passed": 0, "failed": 0, "superseded": 0, "errored": 0}
    first_pass: int | None = None
    statuses = list(verification_statuses)
    for index, status in enumerate(statuses):
        if status == "passed":
            counts["passed"] += 1
            if first_pass is None:
                first_pass = index
        elif status == "failed":
            counts["failed"] += 1
        elif status == "superseded":
            counts["superseded"] += 1
        elif status == "error":
            counts["errored"] += 1
        # Deferred pending jobs are not counted.
    window = statuses if first_pass is None else statuses[:first_pass]
    rework_rounds = sum(1 for status in window if status == "failed")
    return {
        "done_reports": done_reports,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "superseded": counts["superseded"],
        "errored": counts["errored"],
        "rework_rounds": rework_rounds,
    }


def derive_module_attention(
    *,
    lifecycle: str,
    verification_status: str,
    escalated: bool,
    is_stale: bool,
) -> dict[str, Any]:
    """Per-module attention precedence: the first matching row wins."""

    if verification_status == "error":
        return {"kind": "operator", "reason_code": "board_attention_verification_error"}
    if verification_status == "failed" and escalated and lifecycle == "done_claimed":
        return {"kind": "lead", "reason_code": "board_attention_verification_escalated"}
    if verification_status == "failed" and lifecycle == "done_claimed":
        return {"kind": "owner", "reason_code": "board_attention_verification_failed"}
    if lifecycle == "blocked":
        return {"kind": "lead", "reason_code": "board_attention_module_blocked"}
    if is_stale:
        return {"kind": "owner", "reason_code": "board_attention_contract_stale"}
    return {"kind": "none", "reason_code": None}


def compute_stale_dependents(
    *,
    revised: Sequence[RevisedContract],
    charters: Sequence[CharterDependency],
    latest_progress_seq: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Measurable contract drift: dependents without a post-revision report."""

    stale: list[dict[str, Any]] = []
    for contract in revised:
        for charter in charters:
            if charter.module_id == contract.provider_module_id:
                continue
            if contract.contract_id not in charter.depends:
                continue
            if latest_progress_seq.get(charter.module_id, -1) > contract.revised_seq:
                continue
            stale.append(
                {
                    "contract_id": contract.contract_id,
                    "revised_version": contract.revised_version,
                    "revised_seq": contract.revised_seq,
                    "module_id": charter.module_id,
                    "owner_participant_id": charter.owner_participant_id,
                }
            )
    stale.sort(key=lambda item: (item["contract_id"], item["module_id"]))
    return stale


# ---------------------------------------------------------------------------
# loader helpers
# ---------------------------------------------------------------------------


def _decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) and value else None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _contract_digest(content: str) -> str:
    return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"


def _stamp(value: datetime) -> str:
    current = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return current.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _activity_rows_by_id(conn: sqlite3.Connection, conversation_id: str) -> dict[str, sqlite3.Row]:
    # Progress and contract rows only ever point at board activities; skip the
    # (potentially huge) rest of the Room timeline and its payloads.
    rows = conn.execute(
        "select activity_id, seq from room_activities "
        "where conversation_id = ? and activity_type like 'board.%'",
        (conversation_id,),
    ).fetchall()
    return {str(row["activity_id"]): row for row in rows}


def compute_revision(projection: Mapping[str, Any]) -> str:
    """``<board_seq>:<12 hex>`` over the canonical projection sans volatile keys."""

    body = {
        key: value
        for key, value in projection.items()
        if key not in ("server_time", "events", "revision")
    }
    digest = sha256(_canonical(body).encode("utf-8")).hexdigest()[:12]
    return f"{projection['board_seq']}:{digest}"


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

_EVENT_KINDS = (
    "split_proposed",
    "split_rejected",
    "charter_assigned",
    "claimed",
    "contract_published",
    "contract_revised",
    "progress",
    "question",
    "verification",
)

_ACTIVITY_TO_EVENT = {
    "board.split_proposed": "split_proposed",
    "board.split_rejected": "split_rejected",
    "board.charter_assigned": "charter_assigned",
    "board.claimed": "claimed",
    "board.contract_published": "contract_published",
    "board.contract_revised": "contract_revised",
    "board.progress": "progress",
    "board.question": "question",
    "board.verification": "verification",
}


def _actor(row: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(row.get("actor_kind", ""))
    if kind not in ("participant", "operator", "infrastructure"):
        kind = "infrastructure"
    participant_id = row.get("actor_participant_id")
    return {
        "kind": kind,
        "participant_id": str(participant_id) if kind == "participant" and participant_id else None,
    }


def project_event(activity_row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one activity row to a v2 event, or None for unknown kinds.

    Never copies ``payload.content`` or the raw payload object.
    """

    activity_type = str(activity_row.get("activity_type", ""))
    kind = _ACTIVITY_TO_EVENT.get(activity_type)
    if kind is None:
        return None
    payload = activity_row.get("payload")
    if payload is None:
        raw = activity_row.get("payload_json")
        payload = _decode(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        return None
    module_id: str | None = None
    data: dict[str, Any] = {}
    if kind == "split_proposed":
        modules = payload.get("modules", [])
        data = {
            "split_id": str(payload.get("split_id")),
            "module_ids": [
                str(item.get("module_id")) for item in modules if isinstance(item, dict)
            ],
        }
    elif kind == "split_rejected":
        decided_via = payload.get("decided_via")
        data = {
            "split_id": str(payload.get("split_id")),
            "decided_via": str(decided_via) if isinstance(decided_via, str) else None,
        }
    elif kind == "charter_assigned":
        module_id = str(payload.get("module_id"))
        decided_via = payload.get("decided_via")
        data = {
            "split_id": str(payload.get("split_id")),
            "owner_participant_id": str(payload.get("owner_participant_id")),
            "charter_version": int(payload.get("version", 0)),
            "decided_via": str(decided_via) if isinstance(decided_via, str) else None,
        }
    elif kind == "claimed":
        module_id = str(payload.get("module_id"))
        data = {}
    elif kind in ("contract_published", "contract_revised"):
        module_id = str(payload.get("provider_module_id"))
        data = {
            "contract_id": str(payload.get("contract_id")),
            "version": int(payload.get("version", 0)),
            "kind": str(payload.get("kind")),
            "digest": str(payload.get("digest")),
            "rationale": _maybe_agent_text(payload.get("rationale"), max_chars=400),
        }
    elif kind == "progress":
        module_id = str(payload.get("module_id"))
        claims = payload.get("claims", [])
        clean_claims = (
            [str(item) for item in claims if isinstance(item, str)]
            if isinstance(claims, list)
            else []
        )
        data = {
            "status": str(payload.get("status")),
            "summary": agent_text(payload.get("summary"), max_chars=400),
            "claims": [agent_text(item, max_chars=200) for item in clean_claims[:8]],
            "claims_total": len(clean_claims),
        }
    elif kind == "question":
        data = {
            "target_participant_id": str(payload.get("target_participant_id")),
            "question": agent_text(payload.get("question"), max_chars=400),
        }
    elif kind == "verification":
        module_id = str(payload.get("module_id"))
        gates = payload.get("gates", [])
        gate_ids = (
            [
                str(item.get("gate_id"))
                for item in gates
                if isinstance(item, dict) and item.get("status") != "passed"
            ]
            if isinstance(gates, list)
            else []
        )
        stacked = payload.get("stacked", [])
        clean_stacked = (
            [
                {
                    "module_id": str(item.get("module_id")),
                    "verification_id": str(item.get("verification_id")),
                }
                for item in stacked
                if isinstance(item, dict)
            ]
            if isinstance(stacked, list)
            else []
        )
        escalated = payload.get("escalated")
        data = {
            "verification_id": str(payload.get("verification_id")),
            "status": str(payload.get("status")),
            "reason_code": payload.get("reason_code"),
            "gate_ids": gate_ids,
            "escalated": bool(escalated) if isinstance(escalated, bool) else False,
            "stacked": clean_stacked,
        }
    return {
        "seq": int(activity_row.get("seq", 0)),
        "kind": kind,
        "at": str(activity_row.get("created_at")),
        "module_id": module_id,
        "actor": _actor(activity_row),
        "data": data,
    }


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _board_seq(conn: sqlite3.Connection, conversation_id: str) -> int:
    row = conn.execute(
        "select coalesce(max(seq), 0) from room_activities "
        "where conversation_id = ? and activity_type like 'board.%'",
        (conversation_id,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _decided_via_for_split(
    conn: sqlite3.Connection, conversation_id: str, split_id: str, *, approved: bool
) -> str | None:
    """Read decided_via from the split's decision events (null when absent)."""

    if approved:
        rows = conn.execute(
            """select payload_json from room_activities
               where conversation_id = ? and activity_type = 'board.charter_assigned'
               order by seq""",
            (conversation_id,),
        ).fetchall()
        for candidate in rows:
            payload = _decode(candidate["payload_json"])
            if isinstance(payload, dict) and payload.get("split_id") == split_id:
                decided_via = payload.get("decided_via")
                return str(decided_via) if isinstance(decided_via, str) else None
        return None
    rows = conn.execute(
        """select payload_json from room_activities
           where conversation_id = ? and activity_type = 'board.split_rejected'
           order by seq""",
        (conversation_id,),
    ).fetchall()
    for candidate in rows:
        payload = _decode(candidate["payload_json"])
        if isinstance(payload, dict) and payload.get("split_id") == split_id:
            decided_via = payload.get("decided_via")
            return str(decided_via) if isinstance(decided_via, str) else None
    return None


def _load_split_view(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select * from room_board_splits where conversation_id = ? order by created_at, split_id",
        (conversation_id,),
    ).fetchall()
    splits: list[dict[str, Any]] = []
    for row in rows:
        bundle = _decode(row["split_json"])
        if not isinstance(bundle, dict):
            continue
        modules = bundle.get("modules", [])
        assignments = bundle.get("assignments", {})
        specs = bundle.get("contracts", [])
        if not isinstance(modules, list) or not isinstance(assignments, dict):
            continue
        status = str(row["status"])
        decided_at = row["decided_at"]
        split_modules: list[dict[str, Any]] = []
        for charter in modules:
            if not isinstance(charter, dict):
                continue
            module_id = str(charter.get("module_id"))
            split_modules.append(
                {
                    "module_id": module_id,
                    "title": agent_text(charter.get("title"), max_chars=120),
                    "owner_participant_id": str(assignments.get(module_id)),
                    "paths": list(charter.get("paths", [])),
                    "provides": list(charter.get("provides", [])),
                    "depends": list(charter.get("depends", [])),
                }
            )
        split_contracts: list[dict[str, Any]] = []
        for spec in specs if isinstance(specs, list) else []:
            if not isinstance(spec, dict):
                continue
            split_contracts.append(
                {
                    "contract_id": str(spec.get("contract_id")),
                    "provider_module_id": str(spec.get("provider_module_id")),
                    "kind": str(spec.get("kind")),
                    "digest": _contract_digest(str(spec.get("content", ""))),
                }
            )
        split_contracts.sort(key=lambda item: item["contract_id"])
        splits.append(
            {
                "split_id": str(row["split_id"]),
                "status": status,
                "proposed_by_participant_id": str(row["proposed_by_participant_id"]),
                "created_at": str(row["created_at"]),
                "decided_at": None if decided_at is None else str(decided_at),
                "digest": f"sha256:{sha256(_canonical(bundle).encode('utf-8')).hexdigest()}",
                "decided_via": _decided_via_for_split(
                    conn, conversation_id, str(row["split_id"]), approved=status == "approved"
                ),
                "modules": split_modules,
                "contracts": split_contracts,
            }
        )
    return splits


def _verification_fact(row: sqlite3.Row) -> VerificationFact:
    result = _decode(row["result_json"]) if row["result_json"] else None
    gates = result.get("gates") if isinstance(result, dict) else None
    gate_ids = (
        [
            str(item.get("gate_id"))
            for item in gates
            if isinstance(item, dict) and item.get("status") != "passed"
        ]
        if isinstance(gates, list)
        else []
    )
    stacked = result.get("stacked") if isinstance(result, dict) else None
    refs = (
        [
            StackedRef(
                module_id=str(item.get("module_id")),
                verification_id=str(item.get("verification_id")),
            )
            for item in stacked
            if isinstance(item, dict)
        ]
        if isinstance(stacked, list)
        else []
    )
    reason = result.get("reason_code") if isinstance(result, dict) else None
    changed = _decode(row["changed_paths_json"] or "[]")
    changed_count = len(changed) if isinstance(changed, list) else 0
    return VerificationFact(
        verification_id=str(row["verification_id"]),
        status=str(row["status"]),
        reason_code=str(reason) if isinstance(reason, str) else None,
        gate_ids=gate_ids,
        stacked=refs,
        head_commit=str(row["head_commit"]) if row["head_commit"] else None,
        changed_path_count=changed_count,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


def build_board_projection(
    conn: sqlite3.Connection, conversation_id: str, *, now: datetime
) -> dict[str, Any]:
    """Build the ``room_board_projection/v2`` dict with read-only queries."""

    from xmuse_core.chat.room_collaboration import collaboration_policy_row

    policy = collaboration_policy_row(conn, conversation_id)
    lead = str(policy["lead_participant_id"]) if policy and policy["lead_participant_id"] else None
    participant_rows = conn.execute(
        "select * from participants where conversation_id = ? order by participant_id",
        (conversation_id,),
    ).fetchall()
    participants = [
        {
            "participant_id": str(row["participant_id"]),
            "display_name": str(row["display_name"]),
            "provider_kind": str(row["cli_kind"]),
            "model_family": str(row["cli_kind"]),
            "role_preset": row["role_template_id"] if row["role_template_id"] is not None else None,
            "is_lead": lead is not None and str(row["participant_id"]) == lead,
        }
        for row in participant_rows
    ]

    charter_rows = conn.execute(
        "select * from room_board_charters where conversation_id = ? order by module_id, version",
        (conversation_id,),
    ).fetchall()
    latest_charters: dict[str, sqlite3.Row] = {}
    for row in charter_rows:
        latest_charters[str(row["module_id"])] = row

    activity_by_id = _activity_rows_by_id(conn, conversation_id)

    progress_rows = conn.execute(
        "select *, rowid as rowid from room_board_progress where conversation_id = ? "
        "order by created_at, rowid",
        (conversation_id,),
    ).fetchall()
    progress_by_module: dict[str, list[ProgressFact]] = {}
    progress_seq_by_module_owner: dict[str, int] = {}
    done_counts: dict[str, int] = {}
    # Owner is fixed per charter version; resolve from the latest charter.
    for row in progress_rows:
        module_id = str(row["module_id"])
        activity = activity_by_id.get(str(row["activity_id"]))
        seq = int(activity["seq"]) if activity is not None else 0
        fact = ProgressFact(
            status=str(row["status"]),
            participant_id=str(row["participant_id"]),
            created_at=str(row["created_at"]),
            seq=seq,
        )
        progress_by_module.setdefault(module_id, []).append(fact)
        if fact.status == "done":
            done_counts[module_id] = done_counts.get(module_id, 0) + 1

    verification_rows = conn.execute(
        "select *, rowid as rowid from room_board_verifications where conversation_id = ? "
        "order by created_at, rowid",
        (conversation_id,),
    ).fetchall()
    verifications_by_module: dict[str, list[VerificationFact]] = {}
    verification_statuses: dict[str, list[str]] = {}
    for row in verification_rows:
        module_id = str(row["module_id"])
        verifications_by_module.setdefault(module_id, []).append(_verification_fact(row))
        verification_statuses.setdefault(module_id, []).append(str(row["status"]))

    contract_rows = conn.execute(
        "select * from room_board_contracts where conversation_id = ? "
        "order by contract_id, version",
        (conversation_id,),
    ).fetchall()
    contracts_by_id: dict[str, list[sqlite3.Row]] = {}
    for row in contract_rows:
        contracts_by_id.setdefault(str(row["contract_id"]), []).append(row)
    contracts = [
        {
            "contract_id": contract_id,
            "latest_version": int(versions[-1]["version"]),
            "versions_count": len(versions),
            "digest": str(versions[-1]["digest"]),
            "provider_module_id": str(versions[-1]["provider_module_id"]),
            "kind": str(versions[-1]["kind"]),
            "author_participant_id": str(versions[-1]["author_participant_id"]),
            "updated_at": str(versions[-1]["created_at"]),
        }
        for contract_id, versions in sorted(contracts_by_id.items())
    ]

    revised = [
        RevisedContract(
            contract_id=contract_id,
            revised_version=int(versions[-1]["version"]),
            revised_seq=int(activity_by_id[str(versions[-1]["activity_id"])]["seq"])
            if versions[-1]["activity_id"] is not None
            and str(versions[-1]["activity_id"]) in activity_by_id
            else 0,
            provider_module_id=str(versions[-1]["provider_module_id"]),
        )
        for contract_id, versions in contracts_by_id.items()
        if len(versions) >= 2
    ]

    modules: list[dict[str, Any]] = []
    charter_deps: list[CharterDependency] = []
    for module_id in sorted(latest_charters):
        row = latest_charters[module_id]
        if str(row["status"]) != "active":
            continue
        body = _decode(row["charter_json"])
        body = body if isinstance(body, dict) else {}
        owner = str(row["owner_participant_id"])
        report_to = body.get("report_to")
        charter_deps.append(
            CharterDependency(
                module_id=module_id,
                owner_participant_id=owner,
                depends=list(body.get("depends", []))
                if isinstance(body.get("depends"), list)
                else [],
            )
        )
        for fact in progress_by_module.get(module_id, []):
            if fact.participant_id != owner:
                continue
            known = progress_seq_by_module_owner.get(module_id, -1)
            if fact.seq > known:
                progress_seq_by_module_owner[module_id] = fact.seq
        lifecycle = derive_lifecycle(
            claimed_at=str(row["claimed_at"]) if row["claimed_at"] is not None else None,
            charter_created_at=str(row["created_at"]),
            owner_participant_id=owner,
            reports=progress_by_module.get(module_id, []),
        )
        axis = derive_verification_axis(
            charter_created_at=str(row["created_at"]),
            jobs=verifications_by_module.get(module_id, []),
        )
        counters = compute_counters(
            verification_statuses.get(module_id, []),
            done_reports=done_counts.get(module_id, 0),
        )
        state = derive_state(lifecycle, str(axis["status"]))
        modules.append(
            {
                "module_id": module_id,
                "title": agent_text(body.get("title"), max_chars=120),
                "owner_participant_id": owner,
                "report_to": str(report_to) if isinstance(report_to, str) and report_to else None,
                "charter_version": int(row["version"]),
                "paths": list(body.get("paths", [])) if isinstance(body.get("paths"), list) else [],
                "provides": list(body.get("provides", []))
                if isinstance(body.get("provides"), list)
                else [],
                "depends": list(body.get("depends", []))
                if isinstance(body.get("depends"), list)
                else [],
                "lifecycle": lifecycle,
                "verification": axis,
                "counters": counters,
                "state": state,
                "attention": {"kind": "none", "reason_code": None},
            }
        )

    stale = compute_stale_dependents(
        revised=revised,
        charters=charter_deps,
        latest_progress_seq=progress_seq_by_module_owner,
    )
    stale_module_ids = {item["module_id"] for item in stale}
    attention: list[dict[str, Any]] = []
    for module in modules:
        item = derive_module_attention(
            lifecycle=str(module["lifecycle"]),
            verification_status=str(module["verification"]["status"]),
            escalated=bool(module["verification"]["escalated"]),
            is_stale=module["module_id"] in stale_module_ids,
        )
        module["attention"] = item
        if item["kind"] != "none":
            attention.append(
                {
                    "kind": item["kind"],
                    "reason_code": item["reason_code"],
                    "module_id": module["module_id"],
                    "split_id": None,
                }
            )

    splits = _load_split_view(conn, conversation_id)
    for split in splits:
        if str(split["status"]) == "proposed":
            attention.append(
                {
                    "kind": "operator",
                    "reason_code": "board_attention_split_pending",
                    "module_id": None,
                    "split_id": split["split_id"],
                }
            )
    _KIND_ORDER = {"operator": 0, "lead": 1, "owner": 2}
    attention.sort(
        key=lambda item: (
            _KIND_ORDER[str(item["kind"])],
            str(item["module_id"] or ""),
            str(item["split_id"] or ""),
        )
    )

    board_seq = _board_seq(conn, conversation_id)
    event_rows = conn.execute(
        "select * from room_activities where conversation_id = ? "
        "and activity_type like 'board.%' order by seq desc limit 50",
        (conversation_id,),
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in reversed(event_rows):
        mapping = dict(row)
        mapping["payload"] = _decode(row["payload_json"])
        event = project_event(mapping)
        if event is not None:
            events.append(event)

    projection = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "metrics_version": METRICS_VERSION,
        "conversation_id": conversation_id,
        "server_time": _stamp(now),
        "board_seq": board_seq,
        "revision": "",
        "capabilities": {"verification": 1, "reviews": 0, "integrations": 0, "lessons": 0},
        "participants": participants,
        "modules": modules,
        "contracts": contracts,
        "splits": splits,
        "stale_dependents": stale,
        "attention": attention,
        "events": events,
    }
    projection["revision"] = compute_revision(projection)
    return projection


def build_board_summary(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the ``room_board_summary/v1`` dict from a projection dict."""

    counts = {state: 0 for state in STATES}
    for module in projection.get("modules", []):
        state = str(module.get("state"))
        if state in counts:
            counts[state] += 1
    attention = list(projection.get("attention", []))
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "conversation_id": projection.get("conversation_id"),
        "server_time": projection.get("server_time"),
        "board_seq": projection.get("board_seq"),
        "revision": projection.get("revision"),
        "capabilities": dict(projection.get("capabilities", {})),
        "modules_total": len(list(projection.get("modules", []))),
        "counts": counts,
        "attention_total": len(attention),
        "attention": attention[:5],
    }


def board_events_page(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    after_seq: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Return one ``room_board_events/v1`` page (no waiting)."""

    clamped = max(1, min(int(limit), 200))
    start = max(0, int(after_seq))
    board_seq = _board_seq(conn, conversation_id)
    rows = conn.execute(
        "select * from room_activities where conversation_id = ? "
        "and activity_type like 'board.%' and seq > ? order by seq asc limit ?",
        (conversation_id, start, clamped + 1),
    ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows[:clamped]:
        mapping = dict(row)
        mapping["payload"] = _decode(row["payload_json"])
        event = project_event(mapping)
        if event is not None:
            events.append(event)
    revision = compute_revision(
        {**build_board_projection(conn, conversation_id, now=datetime.now(UTC))}
    )
    return {
        "schema_version": EVENTS_SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "board_seq": board_seq,
        "revision": revision,
        "events": events,
        "has_more": len(rows) > clamped,
        "reset": start > board_seq,
    }


def build_contract_detail(
    conn: sqlite3.Connection,
    conversation_id: str,
    contract_id: str,
    version: int | None,
) -> dict[str, Any] | None:
    """Build the ``room_board_contract/v2`` dict, or None when unknown."""

    rows = conn.execute(
        "select * from room_board_contracts where conversation_id = ? and contract_id = ? "
        "order by version",
        (conversation_id, contract_id),
    ).fetchall()
    if not rows:
        return None
    if version is None:
        target = rows[-1]
    else:
        target = next((row for row in rows if int(row["version"]) == version), None)
        if target is None:
            return None
    versions = [
        {
            "version": int(row["version"]),
            "digest": str(row["digest"]),
            "author_participant_id": str(row["author_participant_id"]),
            "created_at": str(row["created_at"]),
            "rationale": _maybe_agent_text(row["rationale"], max_chars=400),
        }
        for row in rows
    ]
    latest = rows[-1]
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "contract_id": contract_id,
        "provider_module_id": str(latest["provider_module_id"]),
        "kind": str(latest["kind"]),
        "versions": versions,
        "version": int(target["version"]),
        "content": {
            "text": sanitize_text(target["content"]),
            "untrusted": True,
            "truncated": False,
        },
    }
