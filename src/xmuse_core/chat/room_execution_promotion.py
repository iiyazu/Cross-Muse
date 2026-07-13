"""Connection-level primitives for the Room execution promotion journal.

The caller owns the SQLite transaction, bound-run/controller guards, policy checks,
and terminal run authority.  This module never observes or mutates a workspace.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from .room_execution_common import (
    RoomExecutionStoreError,
    decode_json,
    json_value,
    require_digest,
)
from .room_execution_contracts import canonical_execution_path

PromotionResolution = Literal["applied", "not_applied", "ambiguous"]
FinalizeAmbiguous = Callable[[sqlite3.Connection, sqlite3.Row, str, str], sqlite3.Row]


def normalize_promotion_entries(
    candidate: sqlite3.Row,
    file_entries: Sequence[Mapping[str, Any]],
) -> str:
    """Validate and canonically encode exact promotion pre/post images."""

    if not isinstance(file_entries, Sequence) or isinstance(file_entries, (str, bytes)):
        raise RoomExecutionStoreError("room_execution_promotion_entries_invalid")
    normalized: list[dict[str, str | None]] = []
    change_types = {
        str(item["path"]): str(item["change_type"])
        for item in decode_json(candidate["files_json"], [])
    }
    for item in file_entries:
        if not isinstance(item, Mapping) or set(item) != {
            "path",
            "pre_sha256",
            "post_sha256",
        }:
            raise RoomExecutionStoreError("room_execution_promotion_entries_invalid")
        path = canonical_execution_path(item["path"])
        pre = (
            None
            if item["pre_sha256"] is None
            else require_digest(item["pre_sha256"], "room_execution_promotion_digest_invalid")
        )
        post = (
            None
            if item["post_sha256"] is None
            else require_digest(item["post_sha256"], "room_execution_promotion_digest_invalid")
        )
        change_type = change_types.get(path)
        valid = (
            (change_type == "modify" and pre is not None and post is not None)
            or (change_type == "add" and pre is None and post is not None)
            or (change_type == "delete" and pre is not None and post is None)
        )
        if not valid:
            raise RoomExecutionStoreError("room_execution_promotion_entries_mismatch")
        normalized.append({"path": path, "pre_sha256": pre, "post_sha256": post})
    allowed = set(decode_json(candidate["allowed_files_json"], []))
    if {item["path"] for item in normalized} != allowed or len(normalized) != len(allowed):
        raise RoomExecutionStoreError("room_execution_promotion_entries_mismatch")
    return json_value(sorted(normalized, key=lambda item: item["path"]))


def prepare_promotion_journal_conn(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    journal_id: str,
    execution_generation: int,
    target_head: str,
    pre_manifest_digest: str,
    post_manifest_digest: str,
    file_entries_json: str,
    stamp: str,
) -> sqlite3.Row:
    """Insert a prepared journal and move an already-guarded run to promoting."""

    if (
        conn.execute(
            "select 1 from room_execution_promotion_journal where run_id = ?", (run_id,)
        ).fetchone()
        is not None
    ):
        raise RoomExecutionStoreError("room_execution_promotion_journal_conflict")
    conn.execute(
        """insert into room_execution_promotion_journal
           (journal_id, run_id, execution_generation, target_head,
            pre_manifest_digest, post_manifest_digest, file_entries_json,
            status, prepared_at, updated_at)
           values (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)""",
        (
            journal_id,
            run_id,
            execution_generation,
            target_head,
            pre_manifest_digest,
            post_manifest_digest,
            file_entries_json,
            stamp,
            stamp,
        ),
    )
    conn.execute(
        """update room_execution_runs set state = 'promoting',
           revision = revision + 1, updated_at = ? where run_id = ?""",
        (stamp, run_id),
    )
    return _required_run(conn, run_id)


def mark_promotion_applying_conn(
    conn: sqlite3.Connection, *, run_id: str, stamp: str
) -> sqlite3.Row:
    """Fence prepared -> applying for an already-bound promoting run."""

    journal = conn.execute(
        "select * from room_execution_promotion_journal where run_id = ?", (run_id,)
    ).fetchone()
    if journal is None or journal["status"] != "prepared":
        raise RoomExecutionStoreError("room_execution_promotion_journal_guard_mismatch")
    conn.execute(
        "update room_execution_promotion_journal set status = 'applying', "
        "updated_at = ? where run_id = ?",
        (stamp, run_id),
    )
    conn.execute(
        "update room_execution_runs set revision = revision + 1, updated_at = ? where run_id = ?",
        (stamp, run_id),
    )
    return _required_run(conn, run_id)


def resolve_promotion_journal_conn(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    observed_manifest_digest: str,
    stamp: str,
    finalize_ambiguous: FinalizeAmbiguous,
) -> tuple[PromotionResolution, sqlite3.Row]:
    """Resolve an applying journal from exact observed bytes.

    ``finalize_ambiguous`` keeps terminal run authority with the Store composition
    root.  It must return the updated run row after durably blocking the run.
    """

    run_id = str(run["run_id"])
    journal = conn.execute(
        "select * from room_execution_promotion_journal where run_id = ?", (run_id,)
    ).fetchone()
    if journal is None or journal["status"] != "applying":
        raise RoomExecutionStoreError("room_execution_promotion_journal_guard_mismatch")
    if observed_manifest_digest == journal["post_manifest_digest"]:
        resolution: PromotionResolution = "applied"
        conn.execute(
            """update room_execution_promotion_journal set status = 'applied',
               observed_manifest_digest = ?, applied_at = ?, updated_at = ?
               where run_id = ?""",
            (observed_manifest_digest, stamp, stamp, run_id),
        )
        _bump_run(conn, run_id, stamp)
        updated = _required_run(conn, run_id)
    elif observed_manifest_digest == journal["pre_manifest_digest"]:
        resolution = "not_applied"
        conn.execute(
            """update room_execution_promotion_journal set status = 'prepared',
               observed_manifest_digest = ?, updated_at = ? where run_id = ?""",
            (observed_manifest_digest, stamp, run_id),
        )
        _bump_run(conn, run_id, stamp)
        updated = _required_run(conn, run_id)
    else:
        resolution = "ambiguous"
        conn.execute(
            """update room_execution_promotion_journal set status = 'ambiguous',
               observed_manifest_digest = ?, updated_at = ? where run_id = ?""",
            (observed_manifest_digest, stamp, run_id),
        )
        updated = finalize_ambiguous(conn, run, observed_manifest_digest, stamp)
    return resolution, updated


def _bump_run(conn: sqlite3.Connection, run_id: str, stamp: str) -> None:
    conn.execute(
        "update room_execution_runs set revision = revision + 1, updated_at = ? where run_id = ?",
        (stamp, run_id),
    )


def _required_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run_id,)
    ).fetchone()
    if updated is None:
        raise RoomExecutionStoreError("room_execution_run_missing")
    return updated
