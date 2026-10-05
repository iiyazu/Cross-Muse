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
import unicodedata
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
INTEGRATION_DETAIL_SCHEMA_VERSION = "room_board_integration/v1"

MAX_CONSECUTIVE_FAILURES = 3

BOARD_VERIFICATION_WAITING_FOR_PROVIDER = "board_verification_waiting_for_provider"

# Integration reason codes (§3.11, §9). Duplicated from ``room_board`` (which
# owns the store) so this read-only derivation module stays importable from it.
BOARD_INTEGRATION_CONFLICT = "board_integration_conflict"
BOARD_INTEGRATION_GATE_FAILED = "board_integration_gate_failed"
BOARD_INTEGRATION_WAITING_FOR_DEPENDENCY = "board_integration_waiting_for_dependency"
BOARD_INTEGRATION_WOULD_DROP_ACCEPTED = "board_integration_would_drop_accepted"
BOARD_INTEGRATION_ATTEMPTS_EXHAUSTED = "board_integration_attempts_exhausted"

INTEGRATION_FINISHED_STATUSES = ("integrated", "conflicted", "gate_failed", "error")

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


_FINDING_DRIVE_RE = re.compile(r"^[A-Za-z]:")
MAX_REVIEW_FINDING_PATH_CHARS = 512


def is_valid_finding_path(path: Any) -> bool:
    """Return True when path satisfies the repository-relative finding path rule.

    §3.10: path is null or a repository-relative path of at most 512 characters
    with / separators — no leading /, no drive letter, no backslash, no . or ..
    segment, no control characters and no Unicode format characters (category Cf,
    which includes the bidirectional controls: a path must not be able to
    display as a different file name).
    """

    if path is None:
        return False
    if not isinstance(path, str):
        return False
    if not path or not path.strip() or len(path) > MAX_REVIEW_FINDING_PATH_CHARS:
        return False
    if path.startswith("/") or "\\" in path or _FINDING_DRIVE_RE.match(path) is not None:
        return False
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    if any(
        ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F or unicodedata.category(char) == "Cf"
        for char in path
    ):
        return False
    return True


def review_digest(
    *,
    review_id: str,
    verification_id: str,
    head_commit: str | None,
    patch_text: str | None,
) -> str:
    """Return the ``Review.digest`` decision guard for one review."""

    head = head_commit if isinstance(head_commit, str) else None
    patch = patch_text if isinstance(patch_text, str) else ""
    patch_sha256 = sha256(patch.encode("utf-8")).hexdigest()
    canonical = json.dumps(
        {
            "head_commit": head,
            "patch_sha256": patch_sha256,
            "review_id": review_id,
            "verification_id": verification_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _none_review() -> dict[str, Any]:
    return {
        "status": "none",
        "review_id": None,
        "verification_id": None,
        "digest": None,
        "rule_id": None,
        "author_family": None,
        "reviewer_kind": None,
        "reviewer_participant_id": None,
        "reviewer_family": None,
        "escalated_from": None,
        "findings_count": {"blocker": 0, "major": 0, "minor": 0},
        "decided_via": None,
        "updated_at": None,
        "actions": {},
    }


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


@dataclass(frozen=True)
class IntegrationItemFact:
    """One row of a frozen integration input set, reduced to derivation inputs."""

    module_id: str
    verification_id: str
    item_order: int
    role: str
    status: str
    applied_verification_id: str | None
    conflicts_total: int
    reason_code: str | None


@dataclass(frozen=True)
class IntegrationJobFact:
    """One integration job row, reduced to derivation inputs."""

    integration_id: str
    status: str
    reason_code: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    activity_id: str | None
    activity_seq: int | None
    green_after: str | None
    failed_gate_ids: list[str] = field(default_factory=list)
    items: list[IntegrationItemFact] = field(default_factory=list)


@dataclass(frozen=True)
class IntegrationFacts:
    """Everything the integration read model derives from (one derivation)."""

    candidates: dict[str, str] = field(default_factory=dict)
    jobs: list[IntegrationJobFact] = field(default_factory=list)  # newest first
    green_applied: dict[str, str] = field(default_factory=dict)
    green_head_commit: str | None = None
    verification_created: dict[str, str] = field(default_factory=dict)


def _none_module_integration() -> dict[str, Any]:
    return {
        "status": "none",
        "integration_id": None,
        "verification_id": None,
        "integrated_verification_id": None,
        "reason_code": None,
        "conflict_path_count": 0,
        "gate_ids": [],
        "updated_at": None,
    }


def _newest_including_job(
    facts: IntegrationFacts, module_id: str, verification_id: str, *, statuses: Sequence[str]
) -> IntegrationJobFact | None:
    """Return the newest job with the given status set holding the candidate."""

    wanted = set(statuses)
    for job in facts.jobs:
        if job.status not in wanted:
            continue
        for item in job.items:
            if item.module_id == module_id and item.verification_id == verification_id:
                return job
    return None


def derive_module_integration(module_id: str, facts: IntegrationFacts) -> dict[str, Any]:
    """Derive ``Module.integration`` (§3.11) without touching other axes.

    The candidate is the module's current accepted verification; the status
    describes that candidate in the latest job that included it. A candidate
    already inside the green head reads ``integrated`` even while a newer job
    also queues it; ``pending``/``running`` win over older finished jobs.
    """

    candidate = facts.candidates.get(module_id)
    integrated_vid = facts.green_applied.get(module_id)
    if candidate is None:
        return _none_module_integration()
    if integrated_vid is not None and candidate == integrated_vid:
        holder = _newest_including_job(
            facts,
            module_id,
            candidate,
            statuses=("pending", "running", *INTEGRATION_FINISHED_STATUSES),
        )
        return {
            "status": "integrated",
            "integration_id": holder.integration_id if holder is not None else None,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": None,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": (holder.finished_at or holder.updated_at) if holder is not None else None,
        }
    running = _newest_including_job(facts, module_id, candidate, statuses=("running",))
    if running is not None:
        return {
            "status": "running",
            "integration_id": running.integration_id,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": None,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": running.updated_at,
        }
    pending = _newest_including_job(facts, module_id, candidate, statuses=("pending",))
    if pending is not None:
        return {
            "status": "pending",
            "integration_id": pending.integration_id,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": None,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": pending.updated_at,
        }
    finished = _newest_including_job(
        facts, module_id, candidate, statuses=INTEGRATION_FINISHED_STATUSES
    )
    if finished is None:
        return {
            "status": "none",
            "integration_id": None,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": None,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": None,
        }
    stamp = finished.finished_at or finished.updated_at
    item = next(item for item in finished.items if item.module_id == module_id)
    if finished.status == "error":
        return {
            "status": "error",
            "integration_id": finished.integration_id,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": finished.reason_code,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": stamp,
        }
    if finished.status == "gate_failed" and item.role == "newcomer" and item.status == "applied":
        # A suspect: its own candidate was in the result the gates rejected.
        return {
            "status": "gate_failed",
            "integration_id": finished.integration_id,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": finished.reason_code or BOARD_INTEGRATION_GATE_FAILED,
            "conflict_path_count": 0,
            "gate_ids": list(finished.failed_gate_ids),
            "updated_at": stamp,
        }
    if item.status == "waiting":
        return {
            "status": "waiting",
            "integration_id": finished.integration_id,
            "verification_id": candidate,
            "integrated_verification_id": integrated_vid,
            "reason_code": item.reason_code or BOARD_INTEGRATION_WAITING_FOR_DEPENDENCY,
            "conflict_path_count": 0,
            "gate_ids": [],
            "updated_at": stamp,
        }
    applied = item.applied_verification_id
    return {
        "status": "conflicted",
        "integration_id": finished.integration_id,
        "verification_id": candidate,
        "integrated_verification_id": (
            applied if applied is not None and applied != candidate else integrated_vid
        ),
        "reason_code": item.reason_code or finished.reason_code or BOARD_INTEGRATION_CONFLICT,
        "conflict_path_count": item.conflicts_total,
        "gate_ids": [],
        "updated_at": stamp,
    }


def derive_room_integration(facts: IntegrationFacts) -> dict[str, Any]:
    """Derive the top-level ``RoomIntegration`` (§3.11)."""

    latest = facts.jobs[0] if facts.jobs else None
    return {
        "green_head_commit": facts.green_head_commit,
        "latest": (
            None
            if latest is None
            else {
                "integration_id": latest.integration_id,
                "status": latest.status,
                "reason_code": latest.reason_code,
                "module_count": len(latest.items),
                "finished_at": latest.finished_at,
            }
        ),
    }


def newest_finished_integration_job(facts: IntegrationFacts) -> IntegrationJobFact | None:
    """Return the newest finished job (pending/running jobs never count)."""

    for job in facts.jobs:
        if job.status in INTEGRATION_FINISHED_STATUSES:
            return job
    return None


def derive_integration_counters(module_id: str, facts: IntegrationFacts) -> dict[str, int]:
    """Derive the three integration counters for one module (§6)."""

    finished = [job for job in facts.jobs if job.status in INTEGRATION_FINISHED_STATUSES]
    conflicted = 0
    gate_failed = 0
    for job in finished:
        item = next((entry for entry in job.items if entry.module_id == module_id), None)
        if item is None:
            continue
        # A fallback is a conflict of the module's new candidate (§3.11 rule 3).
        if item.status in ("conflicted", "fell_back"):
            conflicted += 1
        # Suspects are the newcomers whose own candidate went into the failed result;
        # a fallback only put the already integrated version back.
        if job.status == "gate_failed" and item.role == "newcomer" and item.status == "applied":
            gate_failed += 1
    applied_vids = {
        item.applied_verification_id
        for job in finished
        if job.status == "integrated"
        for item in job.items
        if item.module_id == module_id and item.applied_verification_id is not None
    }
    created = facts.verification_created
    first_integrated = (
        min(applied_vids, key=lambda vid: created.get(vid, vid)) if applied_vids else None
    )
    first_created = created.get(first_integrated, first_integrated) if first_integrated else None
    rounds = 0
    seen: set[str] = set()
    for job in finished:
        item = next((entry for entry in job.items if entry.module_id == module_id), None)
        if item is None or item.status not in ("conflicted", "fell_back"):
            continue
        if item.verification_id in seen:
            continue
        seen.add(item.verification_id)
        if first_created is None or created.get(item.verification_id, item.verification_id) < (
            first_created
        ):
            rounds += 1
    return {
        "integrations_conflicted": conflicted,
        "integrations_gate_failed": gate_failed,
        "conflict_fix_rounds": rounds,
    }


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


def derive_module_accepted(
    *,
    state: str,
    reviews_capability: int,
    review_status: str,
) -> bool:
    """Derive Module.accepted (§4.4): verified AND (reviews == 0 OR review == endorsed)."""

    return (state == "verified") and (reviews_capability == 0 or review_status == "endorsed")


def compute_counters(
    verification_statuses: Sequence[str],
    *,
    done_reports: int,
    reviews_endorsed: int = 0,
    reviews_objected: int = 0,
    integrations_conflicted: int = 0,
    integrations_gate_failed: int = 0,
    conflict_fix_rounds: int = 0,
) -> dict[str, int]:
    """Per-module metrics over the module id's whole history (M1/M2 definitions)."""

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
        "reviews_endorsed": reviews_endorsed,
        "reviews_objected": reviews_objected,
        "integrations_conflicted": integrations_conflicted,
        "integrations_gate_failed": integrations_gate_failed,
        "conflict_fix_rounds": conflict_fix_rounds,
    }


def derive_module_attention(
    *,
    lifecycle: str,
    verification_status: str,
    escalated: bool,
    review_status: str = "none",
    review_reviewer_kind: str | None = None,
    is_stale: bool = False,
    integration_status: str = "none",
    integration_reported_after: bool = True,
) -> dict[str, Any]:
    """Per-module attention precedence (§3.8): the first matching row wins."""

    if verification_status == "error":
        return {"kind": "operator", "reason_code": "board_attention_verification_error"}
    if verification_status == "failed" and escalated and lifecycle == "done_claimed":
        return {"kind": "lead", "reason_code": "board_attention_verification_escalated"}
    if verification_status == "failed" and lifecycle == "done_claimed":
        return {"kind": "owner", "reason_code": "board_attention_verification_failed"}
    if review_status == "pending" and review_reviewer_kind == "operator":
        return {"kind": "operator", "reason_code": "board_attention_review_operator_pending"}
    if review_status == "objected" and lifecycle == "done_claimed":
        return {"kind": "owner", "reason_code": "board_attention_review_objected"}
    if integration_status == "conflicted" and not integration_reported_after:
        return {"kind": "owner", "reason_code": "board_attention_integration_conflict"}
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


def split_digest(bundle: Mapping[str, Any]) -> str:
    """Return the canonical ``sha256:<hex>`` digest of a stored split bundle.

    The same helper backs the ``Split.digest`` projection field and the
    operator approval guard (``expected_digest``), so the two can never drift.
    """

    return f"sha256:{sha256(_canonical(bundle).encode('utf-8')).hexdigest()}"


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
    "review_requested",
    "review",
    "integration",
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
    "board.review_requested": "review_requested",
    "board.review": "review",
    "board.integration": "integration",
}


def _actor(
    row: Mapping[str, Any],
    kind: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if kind == "review_requested":
        return {"kind": "infrastructure", "participant_id": None}
    if kind == "integration":
        return {"kind": "infrastructure", "participant_id": None}
    actor_kind = str(row.get("actor_kind", ""))
    if kind == "review":
        if actor_kind == "participant":
            pid = row.get("actor_participant_id") or (
                payload.get("reviewer_participant_id") if payload else None
            )
            return {"kind": "participant", "participant_id": str(pid) if pid else None}
        return {"kind": "operator", "participant_id": None}
    if actor_kind not in ("participant", "operator", "infrastructure"):
        actor_kind = "infrastructure"
    participant_id = row.get("actor_participant_id")
    return {
        "kind": actor_kind,
        "participant_id": str(participant_id)
        if actor_kind == "participant" and participant_id
        else None,
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
        grant_id = payload.get("grant_id")
        data = {
            "split_id": str(payload.get("split_id")),
            "decided_via": str(decided_via) if isinstance(decided_via, str) else None,
            "grant_id": str(grant_id) if isinstance(grant_id, str) else None,
        }
    elif kind == "charter_assigned":
        module_id = str(payload.get("module_id"))
        decided_via = payload.get("decided_via")
        grant_id = payload.get("grant_id")
        data = {
            "split_id": str(payload.get("split_id")),
            "owner_participant_id": str(payload.get("owner_participant_id")),
            "charter_version": int(payload.get("version", 0)),
            "decided_via": str(decided_via) if isinstance(decided_via, str) else None,
            "grant_id": str(grant_id) if isinstance(grant_id, str) else None,
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
    elif kind == "review_requested":
        module_id = str(payload.get("module_id")) if payload.get("module_id") is not None else None
        esc = payload.get("escalated_from")
        clean_esc = (
            {
                "participant_id": str(esc["participant_id"]),
                "family": str(esc["family"]),
                "reason_code": str(esc["reason_code"]),
                "at": str(esc["at"]),
            }
            if isinstance(esc, dict)
            else None
        )
        data = {
            "review_id": str(payload.get("review_id")),
            "verification_id": str(payload.get("verification_id")),
            "rule_id": str(payload.get("rule_id")),
            "author_family": str(payload.get("author_family")),
            "reviewer_kind": str(payload.get("reviewer_kind")),
            "reviewer_participant_id": (
                str(payload.get("reviewer_participant_id"))
                if payload.get("reviewer_participant_id") is not None
                else None
            ),
            "reviewer_family": (
                str(payload.get("reviewer_family"))
                if payload.get("reviewer_family") is not None
                else None
            ),
            "escalated_from": clean_esc,
        }
    elif kind == "review":
        module_id = str(payload.get("module_id")) if payload.get("module_id") is not None else None
        raw_findings = payload.get("findings", [])
        findings_list = raw_findings if isinstance(raw_findings, list) else []
        clean_findings = []
        for f in findings_list[:8]:
            if not isinstance(f, dict):
                continue
            p = f.get("path")
            clean_path = p if is_valid_finding_path(p) else None
            clean_findings.append(
                {
                    "severity": str(f.get("severity")),
                    "path": clean_path,
                    "text": agent_text(f.get("text"), max_chars=200),
                }
            )
        findings_count = {
            "blocker": sum(
                1 for f in findings_list if isinstance(f, dict) and f.get("severity") == "blocker"
            ),
            "major": sum(
                1 for f in findings_list if isinstance(f, dict) and f.get("severity") == "major"
            ),
            "minor": sum(
                1 for f in findings_list if isinstance(f, dict) and f.get("severity") == "minor"
            ),
        }
        decided_via = payload.get("decided_via")
        if not decided_via:
            decided_via = "board_tool" if activity_row.get("actor_kind") == "participant" else "web"
        data = {
            "review_id": str(payload.get("review_id")),
            "verdict": str(payload.get("verdict")),
            "findings_count": findings_count,
            "findings": clean_findings,
            "findings_total": len(findings_list),
            "summary": agent_text(payload.get("summary"), max_chars=400),
            "decided_via": str(decided_via),
        }
    elif kind == "integration":
        raw_conflicts = payload.get("conflicts", [])
        clean_conflicts = []
        for entry in raw_conflicts if isinstance(raw_conflicts, list) else []:
            if not isinstance(entry, dict):
                continue
            attributed = entry.get("attributed_module_ids", [])
            clean_conflicts.append(
                {
                    "module_id": str(entry.get("module_id")),
                    "conflict_path_count": int(entry.get("conflict_path_count", 0)),
                    "attributed_module_ids": [
                        str(item) for item in attributed if isinstance(item, str)
                    ],
                    "fell_back": bool(entry.get("fell_back", False)),
                }
            )
        integrated_ids = payload.get("integrated_module_ids", [])
        suspect_ids = payload.get("suspect_module_ids", [])
        waiting_ids = payload.get("waiting_module_ids", [])
        gate_ids = payload.get("gate_ids", [])
        data = {
            "integration_id": str(payload.get("integration_id")),
            "status": str(payload.get("status")),
            "reason_code": payload.get("reason_code"),
            "green_head_commit": payload.get("green_head_commit"),
            "integrated_module_ids": (
                [str(item) for item in integrated_ids if isinstance(item, str)]
                if isinstance(integrated_ids, list)
                else []
            ),
            "suspect_module_ids": (
                [str(item) for item in suspect_ids if isinstance(item, str)]
                if isinstance(suspect_ids, list)
                else []
            ),
            "conflicts": clean_conflicts,
            "waiting_module_ids": (
                [str(item) for item in waiting_ids if isinstance(item, str)]
                if isinstance(waiting_ids, list)
                else []
            ),
            "gate_ids": (
                [str(item) for item in gate_ids if isinstance(item, str)]
                if isinstance(gate_ids, list)
                else []
            ),
        }
    return {
        "seq": int(activity_row.get("seq", 0)),
        "kind": kind,
        "at": str(activity_row.get("created_at")),
        "module_id": module_id,
        "actor": _actor(activity_row, kind, payload),
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
        split_id = str(row["split_id"])
        digest = split_digest(bundle)
        splits.append(
            {
                "split_id": split_id,
                "status": status,
                "proposed_by_participant_id": str(row["proposed_by_participant_id"]),
                "created_at": str(row["created_at"]),
                "decided_at": None if decided_at is None else str(decided_at),
                "digest": digest,
                "decided_via": _decided_via_for_split(
                    conn, conversation_id, split_id, approved=status == "approved"
                ),
                "actions": {
                    "decide": {
                        "available": status == "proposed",
                        "method": "POST",
                        "href": f"/api/chat/operator/board-splits/{split_id}/decision",
                        "expected_digest": digest,
                        "allowed_decisions": ["approve", "reject"],
                    }
                },
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


def load_integration_facts(
    conn: sqlite3.Connection, conversation_id: str, *, reviews_on: bool
) -> IntegrationFacts:
    """Load every durable input of the integration read model (read-only).

    The candidate rule mirrors the job store: the latest ``passed``
    verification at or after the current charter, endorsed when the room
    reviews. Unknown tables (pre-integration databases) read as no jobs.
    """

    try:
        charter_rows = conn.execute(
            "select module_id, status, created_at from room_board_charters "
            "where conversation_id = ? order by module_id, version",
            (conversation_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return IntegrationFacts()
    latest_status: dict[str, str] = {}
    latest_created: dict[str, str] = {}
    for row in charter_rows:
        module_id = str(row["module_id"])
        latest_status[module_id] = str(row["status"])
        latest_created[module_id] = str(row["created_at"])
    active_created = {
        module_id: created
        for module_id, created in latest_created.items()
        if latest_status.get(module_id) == "active"
    }
    try:
        verification_rows = conn.execute(
            "select module_id, verification_id, status, created_at "
            "from room_board_verifications where conversation_id = ? "
            "order by created_at, rowid",
            (conversation_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        verification_rows = []
    endorsed: set[str] = set()
    if reviews_on:
        try:
            endorsed = {
                str(row["verification_id"])
                for row in conn.execute(
                    "select verification_id from room_board_reviews "
                    "where conversation_id = ? and status = 'endorsed'",
                    (conversation_id,),
                ).fetchall()
            }
        except sqlite3.OperationalError:
            endorsed = set()
    verification_created: dict[str, str] = {}
    candidates: dict[str, str] = {}
    for row in verification_rows:
        vid = str(row["verification_id"])
        verification_created[vid] = str(row["created_at"])
        module_id = str(row["module_id"])
        if module_id not in active_created:
            continue
        if str(row["status"]) != "passed":
            continue
        if str(row["created_at"]) < active_created[module_id]:
            continue
        if reviews_on and vid not in endorsed:
            continue
        candidates[module_id] = vid
    try:
        job_rows = conn.execute(
            "select *, rowid as rowid from room_board_integrations "
            "where conversation_id = ? order by created_at desc, rowid desc",
            (conversation_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return IntegrationFacts(candidates=candidates, verification_created=verification_created)
    try:
        activity_seqs = {
            str(row["activity_id"]): int(row["seq"])
            for row in conn.execute(
                "select activity_id, seq from room_activities "
                "where conversation_id = ? and activity_type = 'board.integration'",
                (conversation_id,),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        activity_seqs = {}
    jobs: list[IntegrationJobFact] = []
    for row in job_rows:
        integration_id = str(row["integration_id"])
        try:
            item_rows = conn.execute(
                "select * from room_board_integration_items where integration_id = ? "
                "order by item_order, module_id",
                (integration_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            item_rows = []
        gates_blob = _decode(row["gates_json"]) if row["gates_json"] else None
        raw_gates = gates_blob.get("gates") if isinstance(gates_blob, dict) else None
        failed_gate_ids = sorted(
            {
                str(entry.get("gate_id"))
                for entry in raw_gates
                if isinstance(entry, dict) and entry.get("status") != "passed"
            }
            if isinstance(raw_gates, list)
            else set()
        )
        activity_id = row["activity_id"] if row["activity_id"] is not None else None
        jobs.append(
            IntegrationJobFact(
                integration_id=integration_id,
                status=str(row["status"]),
                reason_code=(str(row["reason_code"]) if row["reason_code"] is not None else None),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
                finished_at=(str(row["finished_at"]) if row["finished_at"] is not None else None),
                activity_id=str(activity_id) if activity_id is not None else None,
                activity_seq=(
                    activity_seqs.get(str(activity_id)) if activity_id is not None else None
                ),
                green_after=(str(row["green_after"]) if row["green_after"] is not None else None),
                failed_gate_ids=failed_gate_ids,
                items=[
                    IntegrationItemFact(
                        module_id=str(item["module_id"]),
                        verification_id=str(item["verification_id"]),
                        item_order=int(item["item_order"]),
                        role=str(item["role"]),
                        status=str(item["status"]),
                        applied_verification_id=(
                            str(item["applied_verification_id"])
                            if item["applied_verification_id"] is not None
                            else None
                        ),
                        conflicts_total=int(item["conflicts_total"]),
                        reason_code=(
                            str(item["reason_code"]) if item["reason_code"] is not None else None
                        ),
                    )
                    for item in item_rows
                ],
            )
        )
    green_applied: dict[str, str] = {}
    green_head_commit: str | None = None
    for job in jobs:
        if job.status != "integrated":
            continue
        green_head_commit = job.green_after
        green_applied = {
            item.module_id: item.applied_verification_id
            for item in job.items
            if item.applied_verification_id is not None
        }
        break
    return IntegrationFacts(
        candidates=candidates,
        jobs=jobs,
        green_applied=green_applied,
        green_head_commit=green_head_commit,
        verification_created=verification_created,
    )


def build_integration_detail(
    conn: sqlite3.Connection,
    conversation_id: str,
    integration_id: str,
) -> dict[str, Any] | None:
    """Build the ``room_board_integration/v1`` dict, or None when unknown.

    Also None when the job belongs to another conversation: detail routes
    never reveal whether an id exists elsewhere. Conflict paths are the only
    repository paths that ever leave through this route (§2): at most 50
    listed entries, each validated like ``Finding.path``; ``conflicts_total``
    keeps the real count.
    """

    try:
        row = conn.execute(
            "select * from room_board_integrations where integration_id = ?",
            (integration_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or str(row["conversation_id"]) != conversation_id:
        return None
    try:
        item_rows = conn.execute(
            "select * from room_board_integration_items where integration_id = ? "
            "order by item_order, module_id",
            (integration_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    gates_blob = _decode(row["gates_json"]) if row["gates_json"] else None
    raw_gates = gates_blob.get("gates") if isinstance(gates_blob, dict) else []
    evidence = gates_blob.get("evidence") if isinstance(gates_blob, dict) else {}
    output_tails = evidence.get("output_tails") if isinstance(evidence, dict) else {}
    clean_gates: list[dict[str, Any]] = []
    if isinstance(raw_gates, list):
        for entry in raw_gates:
            if not isinstance(entry, dict):
                continue
            gate_id = str(entry.get("gate_id"))
            raw_tail = output_tails.get(gate_id) if isinstance(output_tails, dict) else None
            tail = (
                agent_text(raw_tail, max_chars=2000)
                if raw_tail is not None and entry.get("status") != "passed"
                else None
            )
            clean_gates.append(
                {
                    "gate_id": gate_id,
                    "status": str(entry.get("status")),
                    "exit_code": entry.get("exit_code"),
                    "reason_code": entry.get("reason_code"),
                    "output_tail": tail,
                }
            )
    items: list[dict[str, Any]] = []
    for position, item in enumerate(item_rows):
        stored_conflicts = _decode(str(item["conflicts_json"] or "[]")) or []
        listed: list[dict[str, Any]] = []
        for conflict in stored_conflicts if isinstance(stored_conflicts, list) else []:
            if not isinstance(conflict, dict) or len(listed) >= 50:
                continue
            path = conflict.get("path")
            if not is_valid_finding_path(path):
                continue
            attributed = conflict.get("attributed_module_ids") or []
            listed.append(
                {
                    "path": str(path),
                    "attributed_module_ids": [
                        str(entry) for entry in attributed if isinstance(entry, str)
                    ],
                }
            )
        applied = item["applied_verification_id"]
        items.append(
            {
                "module_id": str(item["module_id"]),
                "verification_id": str(item["verification_id"]),
                "order": position + 1,
                "role": str(item["role"]),
                "status": str(item["status"]),
                "applied_verification_id": str(applied) if applied is not None else None,
                "conflicts": listed,
                "conflicts_total": int(item["conflicts_total"]),
            }
        )
    status = str(row["status"])
    return {
        "schema_version": INTEGRATION_DETAIL_SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "integration_id": integration_id,
        "status": status,
        "reason_code": row["reason_code"],
        "green_head_commit": row["green_after"] if status == "integrated" else row["green_before"],
        "result_commit": row["result_commit"],
        "items": items,
        "gates": clean_gates,
        "attempt_count": int(row["attempt_count"]),
        "created_at": str(row["created_at"]),
        "finished_at": row["finished_at"],
    }


def build_board_projection(
    conn: sqlite3.Connection, conversation_id: str, *, now: datetime
) -> dict[str, Any]:
    """Build the ``room_board_projection/v2`` dict with read-only queries."""

    from xmuse_core.chat.room_collaboration import collaboration_policy_row

    policy = collaboration_policy_row(conn, conversation_id)
    lead = str(policy["lead_participant_id"]) if policy and policy["lead_participant_id"] else None
    review_policy = (
        str(policy["review_policy"])
        if policy and "review_policy" in policy.keys() and policy["review_policy"]
        else "off"
    )
    capabilities = {
        "verification": 1,
        "reviews": 1 if review_policy == "cross_family" else 0,
        "integrations": 1,
        "lessons": 0,
    }
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
    patch_by_verification: dict[str, str] = {}
    for row in verification_rows:
        module_id = str(row["module_id"])
        verifications_by_module.setdefault(module_id, []).append(_verification_fact(row))
        verification_statuses.setdefault(module_id, []).append(str(row["status"]))
        patch_by_verification[str(row["verification_id"])] = (
            str(row["patch_text"]) if row["patch_text"] else ""
        )

    review_rows = conn.execute(
        "select * from room_board_reviews where conversation_id = ? order by created_at, rowid",
        (conversation_id,),
    ).fetchall()
    reviews_by_verification: dict[str, sqlite3.Row] = {}
    reviews_by_module: dict[str, list[sqlite3.Row]] = {}
    for r_row in review_rows:
        reviews_by_verification[str(r_row["verification_id"])] = r_row
        reviews_by_module.setdefault(str(r_row["module_id"]), []).append(r_row)

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
    integration_facts = load_integration_facts(
        conn, conversation_id, reviews_on=review_policy == "cross_family"
    )
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
        curr_v_id = axis["verification_id"]
        r_row = reviews_by_verification.get(curr_v_id) if curr_v_id else None
        if (
            r_row is not None
            and str(r_row["status"]) in ("pending", "endorsed", "objected")
            and axis["status"] != "none"
        ):
            review_id = str(r_row["review_id"])
            r_status = str(r_row["status"])
            r_kind = str(r_row["reviewer_kind"])
            r_pid = (
                str(r_row["reviewer_participant_id"]) if r_row["reviewer_participant_id"] else None
            )
            r_fam = str(r_row["reviewer_family"]) if r_row["reviewer_family"] else None
            r_rule = str(r_row["rule_id"])
            r_author_fam = str(r_row["author_family"])
            raw_esc = _decode(str(r_row["escalation_json"])) if r_row["escalation_json"] else None
            r_esc = (
                {
                    "participant_id": str(raw_esc["participant_id"]),
                    "family": str(raw_esc["family"]),
                    "reason_code": str(raw_esc["reason_code"]),
                    "at": str(raw_esc["at"]),
                }
                if isinstance(raw_esc, dict)
                else None
            )
            r_decided_via = str(r_row["decided_via"]) if r_row["decided_via"] else None
            r_updated_at = str(r_row["updated_at"])
            verdict_data = _decode(str(r_row["verdict_json"])) if r_row["verdict_json"] else None
            findings = verdict_data.get("findings", []) if isinstance(verdict_data, dict) else []
            r_findings_count = {
                "blocker": sum(
                    1
                    for item in findings
                    if isinstance(item, dict) and item.get("severity") == "blocker"
                ),
                "major": sum(
                    1
                    for item in findings
                    if isinstance(item, dict) and item.get("severity") == "major"
                ),
                "minor": sum(
                    1
                    for item in findings
                    if isinstance(item, dict) and item.get("severity") == "minor"
                ),
            }
            raw_patch = patch_by_verification.get(curr_v_id, "")
            r_digest = review_digest(
                review_id=review_id,
                verification_id=curr_v_id,
                head_commit=axis["head_commit"],
                patch_text=raw_patch,
            )
            actions: dict[str, Any] = {}
            if r_status == "pending" and r_kind == "operator":
                actions = {
                    "decide": {
                        "available": True,
                        "method": "POST",
                        "href": f"/api/chat/operator/board-reviews/{review_id}/decision",
                        "expected_digest": r_digest,
                        "allowed_verdicts": ["endorse", "object"],
                    },
                    "material": {"available": True},
                }
            module_review = {
                "status": r_status,
                "review_id": review_id,
                "verification_id": curr_v_id,
                "digest": r_digest,
                "rule_id": r_rule,
                "author_family": r_author_fam,
                "reviewer_kind": r_kind,
                "reviewer_participant_id": r_pid,
                "reviewer_family": r_fam,
                "escalated_from": r_esc,
                "findings_count": r_findings_count,
                "decided_via": r_decided_via,
                "updated_at": r_updated_at,
                "actions": actions,
            }
        else:
            module_review = _none_review()

        mod_reviews = reviews_by_module.get(module_id, [])
        reviews_endorsed = sum(1 for r in mod_reviews if str(r["status"]) == "endorsed")
        reviews_objected = sum(1 for r in mod_reviews if str(r["status"]) == "objected")
        module_integration = derive_module_integration(module_id, integration_facts)
        integration_counters = derive_integration_counters(module_id, integration_facts)
        counters = compute_counters(
            verification_statuses.get(module_id, []),
            done_reports=done_counts.get(module_id, 0),
            reviews_endorsed=reviews_endorsed,
            reviews_objected=reviews_objected,
            **integration_counters,
        )
        state = derive_state(lifecycle, str(axis["status"]))
        accepted = derive_module_accepted(
            state=state,
            reviews_capability=int(capabilities["reviews"]),
            review_status=str(module_review["status"]),
        )
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
                "review": module_review,
                "accepted": accepted,
                "integration": module_integration,
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
        module_id = str(module["module_id"])
        integration_status = str(module["integration"]["status"])
        reported_after = True
        if integration_status == "conflicted":
            holder_id = module["integration"]["integration_id"]
            holder = (
                next(
                    (job for job in integration_facts.jobs if job.integration_id == holder_id),
                    None,
                )
                if isinstance(holder_id, str)
                else None
            )
            if holder is None or holder.activity_seq is None:
                reported_after = False
            else:
                reported_after = (
                    progress_seq_by_module_owner.get(module_id, -1) > holder.activity_seq
                )
        item = derive_module_attention(
            lifecycle=str(module["lifecycle"]),
            verification_status=str(module["verification"]["status"]),
            escalated=bool(module["verification"]["escalated"]),
            review_status=str(module["review"]["status"]),
            review_reviewer_kind=module["review"]["reviewer_kind"],
            is_stale=module_id in stale_module_ids,
            integration_status=integration_status,
            integration_reported_after=reported_after,
        )
        module["attention"] = item
        if item["kind"] != "none":
            attention.append(
                {
                    "kind": item["kind"],
                    "reason_code": item["reason_code"],
                    "module_id": module_id,
                    "split_id": None,
                    "integration_id": None,
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
                    "integration_id": None,
                }
            )
    newest_finished = newest_finished_integration_job(integration_facts)
    if newest_finished is not None and newest_finished.status == "error":
        attention.append(
            {
                "kind": "operator",
                "reason_code": "board_attention_integration_error",
                "module_id": None,
                "split_id": None,
                "integration_id": newest_finished.integration_id,
            }
        )
    elif newest_finished is not None and newest_finished.status == "gate_failed":
        attention.append(
            {
                "kind": "lead",
                "reason_code": "board_attention_integration_gate_failed",
                "module_id": None,
                "split_id": None,
                "integration_id": newest_finished.integration_id,
            }
        )
    _KIND_ORDER = {"operator": 0, "lead": 1, "owner": 2}
    attention.sort(
        key=lambda item: (
            _KIND_ORDER[str(item["kind"])],
            str(item["module_id"] or ""),
            str(item["split_id"] or ""),
            str(item["integration_id"] or ""),
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
        "capabilities": capabilities,
        "review_policy": review_policy,
        "integration": derive_room_integration(integration_facts),
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
    accepted_total = sum(
        1 for module in projection.get("modules", []) if module.get("accepted") is True
    )
    integrated_total = sum(
        1
        for module in projection.get("modules", [])
        if module.get("accepted") is True
        and isinstance(module.get("integration"), dict)
        and isinstance(module.get("verification"), dict)
        and module["integration"].get("integrated_verification_id") is not None
        and module["integration"].get("integrated_verification_id")
        == module["verification"].get("verification_id")
    )
    room_integration = projection.get("integration", {})
    if not isinstance(room_integration, dict):
        room_integration = {}
    room_latest = room_integration.get("latest")
    if not isinstance(room_latest, dict):
        room_latest = None
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "conversation_id": projection.get("conversation_id"),
        "server_time": projection.get("server_time"),
        "board_seq": projection.get("board_seq"),
        "revision": projection.get("revision"),
        "capabilities": dict(projection.get("capabilities", {})),
        "modules_total": len(list(projection.get("modules", []))),
        "counts": counts,
        "accepted_total": accepted_total,
        "integrated_total": integrated_total,
        "integration": {
            "status": room_latest.get("status") if room_latest is not None else None,
            "green_head_commit": room_integration.get("green_head_commit"),
        },
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
