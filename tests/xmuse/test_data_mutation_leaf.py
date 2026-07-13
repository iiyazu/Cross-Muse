from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse.data_mutation import DataMutationError, safe_operation_paths, vacuum_into


def _payload(operation_id: str = "restore-" + "a" * 32) -> dict[str, object]:
    return {
        "schema_version": "xmuse_data_operation/v1",
        "operation_id": operation_id,
        "staging_dir": f".xmuse-data-stage-{operation_id}",
        "rollback_dir": f".xmuse-data-rollback-{operation_id}",
    }


def test_operation_paths_are_rederived_and_reject_escape_or_symlink(tmp_path: Path) -> None:
    payload = _payload()
    paths = safe_operation_paths(
        tmp_path,
        payload,
        expected_schema="xmuse_data_operation/v1",
    )
    assert paths.staging.parent == tmp_path
    assert paths.rollback.parent == tmp_path

    for key, value in (
        ("schema_version", "future"),
        ("operation_id", "../../escape"),
        ("staging_dir", "../escape"),
        ("rollback_dir", "/tmp/escape"),
    ):
        invalid = {**payload, key: value}
        with pytest.raises(DataMutationError) as rejected:
            safe_operation_paths(
                tmp_path,
                invalid,
                expected_schema="xmuse_data_operation/v1",
            )
        assert rejected.value.code == "data_operation_incomplete"

    paths.staging.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DataMutationError):
        safe_operation_paths(
            tmp_path,
            payload,
            expected_schema="xmuse_data_operation/v1",
        )


def test_vacuum_into_preserves_rows_without_replacing_source(tmp_path: Path) -> None:
    source = tmp_path / "chat.db"
    destination = tmp_path / "compacted.db"
    with sqlite3.connect(source) as conn:
        conn.execute("create table facts(id integer primary key, value text)")
        conn.executemany("insert into facts(value) values (?)", [("a",), ("b",)])
    source_before = source.read_bytes()

    vacuum_into(source, destination)

    assert source.read_bytes() == source_before
    with sqlite3.connect(destination) as conn:
        assert conn.execute("select value from facts order by id").fetchall() == [("a",), ("b",)]
