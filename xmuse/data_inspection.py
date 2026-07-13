"""Read-only SQLite evidence primitives for ``xmuse-data``.

The caller owns lifecycle/process checks and lock ordering.  This module never
creates a schema or opens a writable authority connection.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class DataInspectionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def readonly_connection(path: Path) -> Iterator[sqlite3.Connection]:
    if not path.is_file() or path.is_symlink():
        raise DataInspectionError("chat_db_missing", f"chat database is missing: {path}")
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("pragma query_only = on")
        connection.execute("pragma foreign_keys = on")
    except sqlite3.Error as exc:
        raise DataInspectionError("chat_db_corrupt", f"cannot open chat database: {path}") from exc
    try:
        yield connection
    finally:
        connection.close()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    quoted = table.replace('"', '""')
    return {str(row[1]) for row in conn.execute(f'pragma table_info("{quoted}")')}


def unique_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    quoted = table.replace('"', '""')
    keys: set[tuple[str, ...]] = set()
    for index in conn.execute(f'pragma index_list("{quoted}")'):
        if not bool(index[2]):
            continue
        name = str(index[1]).replace('"', '""')
        columns = tuple(str(row[2]) for row in conn.execute(f'pragma index_info("{name}")'))
        keys.add(columns)
    primary = [
        (int(row[5]), str(row[1]))
        for row in conn.execute(f'pragma table_info("{quoted}")')
        if int(row[5]) > 0
    ]
    if primary:
        keys.add(tuple(name for _position, name in sorted(primary)))
    return keys


def integrity_report(conn: sqlite3.Connection) -> dict[str, Any]:
    integrity_rows = [str(row[0]) for row in conn.execute("pragma integrity_check")]
    foreign_keys = [tuple(row) for row in conn.execute("pragma foreign_key_check")]
    return {
        "integrity": "ok" if integrity_rows == ["ok"] else "failed",
        "integrity_rows": integrity_rows,
        "foreign_key_violation_count": len(foreign_keys),
    }


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = [
        [row[0], row[1], row[2], row[3]]
        for row in conn.execute(
            """select type, name, tbl_name, coalesce(sql, '') from sqlite_schema
               where name not like 'sqlite_%' order by type, name"""
        )
    ]
    return sha256_bytes(canonical_bytes(rows))


def sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_sha256": sha256_bytes(value), "size": len(value)}
    return value


def table_order_fingerprints(path: Path) -> dict[str, str]:
    with readonly_connection(path) as conn:
        tables = [
            (str(row[0]), str(row[1] or ""))
            for row in conn.execute(
                """select name, sql from sqlite_schema
                   where type = 'table' and name not like 'sqlite_%' order by name"""
            )
        ]
        results: dict[str, str] = {}
        for table, sql in tables:
            quoted = table.replace('"', '""')
            info = list(conn.execute(f'pragma table_info("{quoted}")'))
            columns = [str(row[1]) for row in info]
            primary = [(int(row[5]), str(row[1])) for row in info if int(row[5]) > 0]
            if "without rowid" in sql.lower():
                order = ", ".join(
                    f'"{name.replace(chr(34), chr(34) * 2)}"' for _position, name in sorted(primary)
                )
            else:
                order = "rowid"
            digest = hashlib.sha256()
            digest.update(canonical_bytes(columns))
            query = f'select * from "{quoted}"' + (f" order by {order}" if order else "")
            for row in conn.execute(query):
                digest.update(canonical_bytes([sqlite_value(value) for value in row]))
                digest.update(b"\n")
            results[table] = digest.hexdigest()
        return results


__all__ = [
    "DataInspectionError",
    "canonical_bytes",
    "integrity_report",
    "readonly_connection",
    "schema_fingerprint",
    "sha256_bytes",
    "sha256_file",
    "sqlite_value",
    "table_columns",
    "table_order_fingerprints",
    "unique_keys",
]
