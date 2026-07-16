from __future__ import annotations

import ast
import hashlib
import sqlite3
import time
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse.data_doctor import doctor_data
from xmuse_core.chat.room_database import ROOM_SCHEMA_ID
from xmuse_core.runtime.root_contract import CHAT_DB_NAME


def _stopped_probe(_root: Path) -> dict[str, object]:
    return {
        "managed": {"state": "stopped", "manager_live": False, "services": []},
        "inventory": {"services": []},
        "global_inventory": {"services": []},
    }


def _files(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("compat_only", [False, True])
def test_doctor_reads_current_and_compat_v1_without_creating_files(
    tmp_path: Path,
    compat_only: bool,
) -> None:
    root = tmp_path / ("compat" if compat_only else "current")
    database = root / CHAT_DB_NAME
    CompatDataTestStore(database).create_conversation("Doctor authority")
    if compat_only:
        with sqlite3.connect(database) as conn:
            conn.execute("delete from chat_schema_meta where schema_id = ?", (ROOM_SCHEMA_ID,))
    before = _files(root)

    exit_code, projection = doctor_data(root, probe=_stopped_probe)

    assert exit_code == 0
    assert projection["schema_version"] == "xmuse_data_doctor/v1"
    assert projection["state"] == "degraded"
    schema = next(item for item in projection["checks"] if item["name"] == "chat_schema")
    assert schema["status"] == "ok"
    assert schema["detail"]["compatible"] is True
    assert _files(root) == before
    assert not (root / "god_sessions.json.lock").exists()


def test_doctor_remains_bounded_for_ten_thousand_activities(tmp_path: Path) -> None:
    root = tmp_path / "ten-thousand"
    store = CompatDataTestStore(root / CHAT_DB_NAME)
    conversation = store.create_conversation("Bounded doctor")
    rows = [
        (
            f"activity-{index}",
            conversation.id,
            index,
            "message.posted",
            "human",
            "human",
            f"cause-{index}",
            f"correlation-{index}",
            "room",
            "[]",
            "{}",
            "active",
            "2026-07-16T00:00:00Z",
        )
        for index in range(1, 10_001)
    ]
    with sqlite3.connect(root / CHAT_DB_NAME) as conn:
        conn.executemany(
            """insert into room_activities(
                   activity_id, conversation_id, seq, activity_type, actor_kind,
                   actor_identity, causation_id, correlation_id, visibility,
                   audience_json, payload_json, delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    started = time.monotonic()
    exit_code, projection = doctor_data(root, probe=_stopped_probe)

    assert exit_code == 0
    assert projection["state"] == "degraded"
    assert time.monotonic() - started < 30


def test_doctor_module_has_no_write_side_capabilities() -> None:
    module = Path(__file__).resolve().parents[2] / "xmuse" / "data_doctor.py"
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "xmuse.data_mutation" not in imports
    assert "xmuse.workroom" not in imports
    assert {"mkdir", "write_text", "write_bytes", "commit", "execute_script"}.isdisjoint(calls)
    assert "open" not in {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
