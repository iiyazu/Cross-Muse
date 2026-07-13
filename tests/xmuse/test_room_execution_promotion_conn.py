from __future__ import annotations

import json
import sqlite3

import pytest

from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_promotion import (
    mark_promotion_applying_conn,
    normalize_promotion_entries,
    prepare_promotion_journal_conn,
    resolve_promotion_journal_conn,
)

PRE = "sha256:" + "1" * 64
POST = "sha256:" + "2" * 64
OTHER = "sha256:" + "3" * 64
STAMP = "2026-07-13T00:00:00.000000Z"


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        create table room_execution_runs (
            run_id text primary key,
            state text not null,
            revision integer not null,
            updated_at text not null
        );
        create table room_execution_promotion_journal (
            journal_id text primary key,
            run_id text not null unique references room_execution_runs(run_id),
            execution_generation integer not null,
            target_head text not null,
            pre_manifest_digest text not null,
            post_manifest_digest text not null,
            file_entries_json text not null,
            status text not null,
            observed_manifest_digest text,
            prepared_at text not null,
            applied_at text,
            updated_at text not null
        );
        insert into room_execution_runs values ('run-1', 'ready_to_promote', 4, 'old');
        """
    )
    return conn


def _candidate(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        """select
             ? as files_json,
             ? as allowed_files_json""",
        (
            json.dumps(
                [
                    {"path": "src/a.py", "change_type": "modify"},
                    {"path": "src/b.py", "change_type": "add"},
                ]
            ),
            json.dumps(["src/a.py", "src/b.py"]),
        ),
    ).fetchone()


def _entries() -> list[dict[str, str | None]]:
    return [
        {"path": "src/b.py", "pre_sha256": None, "post_sha256": POST},
        {"path": "src/a.py", "pre_sha256": PRE, "post_sha256": POST},
    ]


def _prepare(conn: sqlite3.Connection) -> sqlite3.Row:
    entries_json = normalize_promotion_entries(_candidate(conn), _entries())
    return prepare_promotion_journal_conn(
        conn,
        run_id="run-1",
        journal_id="journal-1",
        execution_generation=3,
        target_head="a" * 40,
        pre_manifest_digest=PRE,
        post_manifest_digest=POST,
        file_entries_json=entries_json,
        stamp=STAMP,
    )


def test_normalizes_entries_in_path_order_and_requires_exact_candidate_files() -> None:
    conn = _connection()
    normalized = json.loads(normalize_promotion_entries(_candidate(conn), _entries()))
    assert [entry["path"] for entry in normalized] == ["src/a.py", "src/b.py"]

    with pytest.raises(RoomExecutionStoreError) as raised:
        normalize_promotion_entries(_candidate(conn), _entries()[:1])
    assert raised.value.code == "room_execution_promotion_entries_mismatch"

    invalid = _entries()
    invalid[1] = {"path": "src/a.py", "pre_sha256": None, "post_sha256": POST}
    with pytest.raises(RoomExecutionStoreError) as raised:
        normalize_promotion_entries(_candidate(conn), invalid)
    assert raised.value.code == "room_execution_promotion_entries_mismatch"


def test_prepare_and_mark_applying_change_only_journal_and_run_revision() -> None:
    conn = _connection()
    prepared = _prepare(conn)
    assert (prepared["state"], prepared["revision"]) == ("promoting", 5)
    journal = conn.execute(
        "select * from room_execution_promotion_journal where run_id = 'run-1'"
    ).fetchone()
    assert journal["status"] == "prepared"
    assert json.loads(journal["file_entries_json"])[0]["path"] == "src/a.py"

    applying = mark_promotion_applying_conn(conn, run_id="run-1", stamp=STAMP)
    assert (applying["state"], applying["revision"]) == ("promoting", 6)
    assert (
        conn.execute("select status from room_execution_promotion_journal").fetchone()[0]
        == "applying"
    )


def test_prepare_rejects_duplicate_journal_and_applying_requires_prepared() -> None:
    conn = _connection()
    _prepare(conn)
    with pytest.raises(RoomExecutionStoreError) as raised:
        _prepare(conn)
    assert raised.value.code == "room_execution_promotion_journal_conflict"

    mark_promotion_applying_conn(conn, run_id="run-1", stamp=STAMP)
    with pytest.raises(RoomExecutionStoreError) as raised:
        mark_promotion_applying_conn(conn, run_id="run-1", stamp=STAMP)
    assert raised.value.code == "room_execution_promotion_journal_guard_mismatch"


@pytest.mark.parametrize(
    ("observed", "resolution", "journal_status"),
    [(POST, "applied", "applied"), (PRE, "not_applied", "prepared")],
)
def test_resolves_exact_post_or_pre_image(
    observed: str, resolution: str, journal_status: str
) -> None:
    conn = _connection()
    _prepare(conn)
    mark_promotion_applying_conn(conn, run_id="run-1", stamp=STAMP)

    def unexpected_finalize(
        _conn: sqlite3.Connection,
        _run: sqlite3.Row,
        _digest: str,
        _stamp: str,
    ) -> sqlite3.Row:
        raise AssertionError("exact image must not invoke terminal authority")

    run = conn.execute("select * from room_execution_runs where run_id = 'run-1'").fetchone()
    actual, updated = resolve_promotion_journal_conn(
        conn,
        run=run,
        observed_manifest_digest=observed,
        stamp=STAMP,
        finalize_ambiguous=unexpected_finalize,
    )
    assert actual == resolution
    assert updated["revision"] == 7
    journal = conn.execute("select * from room_execution_promotion_journal").fetchone()
    assert journal["status"] == journal_status
    assert journal["observed_manifest_digest"] == observed
    assert (journal["applied_at"] is not None) is (resolution == "applied")


def test_ambiguous_image_delegates_terminal_run_authority_to_callback() -> None:
    conn = _connection()
    _prepare(conn)
    mark_promotion_applying_conn(conn, run_id="run-1", stamp=STAMP)
    callback_calls: list[tuple[str, str]] = []

    def finalize(
        callback_conn: sqlite3.Connection,
        run: sqlite3.Row,
        observed: str,
        stamp: str,
    ) -> sqlite3.Row:
        callback_calls.append((observed, stamp))
        callback_conn.execute(
            "update room_execution_runs set state = 'blocked', revision = revision + 1 "
            "where run_id = ?",
            (run["run_id"],),
        )
        return callback_conn.execute(
            "select * from room_execution_runs where run_id = ?", (run["run_id"],)
        ).fetchone()

    run = conn.execute("select * from room_execution_runs where run_id = 'run-1'").fetchone()
    resolution, updated = resolve_promotion_journal_conn(
        conn,
        run=run,
        observed_manifest_digest=OTHER,
        stamp=STAMP,
        finalize_ambiguous=finalize,
    )
    assert resolution == "ambiguous"
    assert updated["state"] == "blocked"
    assert callback_calls == [(OTHER, STAMP)]
    assert (
        conn.execute("select status from room_execution_promotion_journal").fetchone()[0]
        == "ambiguous"
    )


def test_resolve_requires_an_applying_journal() -> None:
    conn = _connection()
    run = _prepare(conn)
    with pytest.raises(RoomExecutionStoreError) as raised:
        resolve_promotion_journal_conn(
            conn,
            run=run,
            observed_manifest_digest=POST,
            stamp=STAMP,
            finalize_ambiguous=lambda *_args: run,
        )
    assert raised.value.code == "room_execution_promotion_journal_guard_mismatch"
