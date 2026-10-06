"""Module memory (``docs/contracts/module_memory_v1.md``).

Windows from a module's activities, storing curate responses with
supersession and the cursor, retry/skip, rendering into the owner's board
view, and the switch: off writes nothing and calls nothing.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.xmuse.board_scenarios import build_scenario
from xmuse.memoryos_http_client import MemoryOSAdapterError
from xmuse.room_module_memory_worker import (
    RoomModuleMemoryWorker,
    compose_module_memory_worker,
)
from xmuse_core.chat.room_board_view import materialize_owner_board_view
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_module_memory import (
    MAX_ATTEMPTS,
    ModuleMemoryStore,
    ModuleRef,
    module_memory_enabled,
    render_memory_md,
)


def _failed_board(tmp_path: Path) -> tuple[Path, str]:
    ctx = build_scenario("verification_failed_rework", tmp_path)
    db = tmp_path / "chat.db"
    if Path(ctx["db"]) != db:
        shutil.copy(ctx["db"], db)
    RoomDatabase(db).initialize()
    return db, str(ctx["conversation_id"])


def _alpha(db: Path) -> ModuleRef:
    modules = ModuleMemoryStore(db).active_modules()
    return next(module for module in modules if module.module_id == "alpha")


def _lesson(window_last: int, *, memory_id: str = "mem_lesson1", supersedes: str | None = None):
    return {
        "schema_version": "memoryos_curate/v1",
        "scope_id": "alpha",
        "memories": [
            {
                "id": memory_id,
                "kind": "lesson",
                "topic_key": "alpha.diff_check",
                "statement": "Run git diff --check before reporting done.",
                "version": window_last,
                "occurrences": 2,
                "sources": [{"activity_id": "a1", "quote": "Diff check failed"}],
                "supersedes_id": supersedes,
            },
            {
                "id": "mem_decision1",
                "kind": "decision",
                "topic_key": "alpha.money",
                "statement": "Money is a decimal string.",
                "version": window_last,
                "occurrences": 0,
                "sources": [{"activity_id": "a1", "quote": "x"}],
                "supersedes_id": None,
            },
        ],
        "assignments": [],
        "unaccounted": [],
        "diagnostics": {"llm_calls": 1},
    }


def test_switch_is_off_unless_explicitly_on() -> None:
    assert not module_memory_enabled({})
    assert not module_memory_enabled({"XMUSE_MODULE_MEMORY": "1"})
    assert module_memory_enabled({"XMUSE_MODULE_MEMORY": "on"})
    assert compose_module_memory_worker(xmuse_root=Path("/nope"), environ={}) is None
    # On, but without a sidecar: stays off instead of failing the Room.
    assert (
        compose_module_memory_worker(
            xmuse_root=Path("/nope"), environ={"XMUSE_MODULE_MEMORY": "on"}
        )
        is None
    )


def test_failed_verification_makes_a_gate_failure_window(tmp_path: Path) -> None:
    db, _conversation_id = _failed_board(tmp_path)
    window = ModuleMemoryStore(db).next_window(_alpha(db))
    assert window is not None
    request = window.curate_request()
    assert request["profile"] == "module" and request["scope_id"] == "alpha"
    assert request["window"][-1]["type"] == "gate_failure"
    assert "patch_diff_check" in request["window"][-1]["text"]
    assert "Diff check failed" in request["window"][-1]["text"]
    assert all(item["type"] != "gate_failure" for item in request["window"][:-1])
    # The other module's activity never enters alpha's window.
    beta = next(m for m in ModuleMemoryStore(db).active_modules() if m.module_id == "beta")
    beta_window = ModuleMemoryStore(db).next_window(beta)
    assert beta_window is None or all(
        item["type"] != "gate_failure" for item in beta_window.activities
    )


def test_store_result_supersedes_and_advances_the_cursor(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    window = store.next_window(_alpha(db))
    assert window is not None
    assert store.store_result(window, _lesson(window.last_seq))["stored"] == 2

    second = store.next_window(_alpha(db))
    assert second is not None, "the second failed verification makes its own window"
    assert second.first_seq > window.last_seq
    assert {item["id"] for item in second.active} == {"mem_lesson1", "mem_decision1"}
    reworded = _lesson(second.last_seq, memory_id="mem_lesson2", supersedes="mem_lesson1")
    reworded["memories"] = reworded["memories"][:1]
    store.store_result(second, reworded)

    rows = {row["memory_id"]: row for row in store.memories(conversation_id, "alpha")}
    assert rows["mem_lesson1"]["status"] == "superseded"
    assert rows["mem_lesson1"]["superseded_by"] == "mem_lesson2"
    assert rows["mem_lesson2"]["status"] == "active"
    assert store.next_window(_alpha(db)) is None
    # A replayed response stores nothing twice.
    assert store.store_result(second, reworded)["stored"] == 0


def test_failures_back_off_then_skip(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    start = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    window = store.next_window(_alpha(db), now=start)
    assert window is not None
    assert store.record_failure(window, "memoryos_unavailable", now=start) == "failed"
    assert store.next_window(_alpha(db), now=start + timedelta(seconds=5)) is None
    retry = store.next_window(_alpha(db), now=start + timedelta(seconds=31))
    assert retry is not None and retry.first_seq == window.first_seq
    for attempt in range(2, MAX_ATTEMPTS + 1):
        status = store.record_failure(retry, "memoryos_unavailable", now=start)
        assert status == ("skipped" if attempt == MAX_ATTEMPTS else "failed")
    with RoomDatabase(db).connect(readonly=True) as conn:
        runs = conn.execute(
            "select status, error_code from room_module_memory_runs where conversation_id = ?",
            (conversation_id,),
        ).fetchall()
    assert [(row["status"], row["error_code"]) for row in runs] == [
        ("skipped", "memoryos_unavailable")
    ]
    after = store.next_window(_alpha(db), now=start + timedelta(hours=1))
    assert after is not None and after.first_seq > window.last_seq


def test_render_memory_md_orders_lessons_and_lists_superseded() -> None:
    assert render_memory_md("alpha", []) is None
    text = render_memory_md(
        "alpha",
        [
            {
                "memory_id": "m1",
                "kind": "lesson",
                "statement": "Old lesson",
                "occurrences": 1,
                "version": 1,
                "status": "superseded",
                "superseded_by": "m2",
            },
            {
                "memory_id": "m2",
                "kind": "lesson",
                "statement": "New lesson",
                "occurrences": 3,
                "version": 2,
                "status": "active",
                "superseded_by": None,
            },
            {
                "memory_id": "m3",
                "kind": "lesson",
                "statement": "Rare lesson",
                "occurrences": 1,
                "version": 3,
                "status": "active",
                "superseded_by": None,
            },
            {
                "memory_id": "m4",
                "kind": "decision",
                "statement": "Use decimals",
                "occurrences": 0,
                "version": 2,
                "status": "active",
                "superseded_by": None,
            },
        ],
    )
    assert text is not None
    assert text.index("New lesson") < text.index("Rare lesson")
    assert "No longer true: Old lesson. Now: New lesson" in text
    assert "(decision) Use decimals" in text


def _owner_of_alpha(db: Path, conversation_id: str) -> str:
    return _alpha(db).owner_participant_id


def test_board_view_unchanged_without_memories(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    target = tmp_path / "view"
    target.mkdir()
    materialize_owner_board_view(db, conversation_id, _owner_of_alpha(db, conversation_id), target)
    assert not (target / "memory.md").exists()
    assert "memory.md" not in (target / "charter.md").read_text(encoding="utf-8")


def test_worker_curates_stores_and_renders(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    owner = _owner_of_alpha(db, conversation_id)

    class _Client:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            self.requests.append(request)
            if request["scope_id"] != "alpha":
                return {"schema_version": "memoryos_curate/v1", "memories": []}
            return _lesson(request["window"][-1]["seq"], memory_id=f"mem_{len(self.requests)}")

    client = _Client()
    worker = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=client)
    counts = worker.reconcile_once()
    assert counts["module_memory_windows"] >= 1
    assert counts["module_memory_stored"] >= 1
    assert any(request["scope_id"] == "alpha" for request in client.requests)

    target = tmp_path / "view"
    target.mkdir()
    materialize_owner_board_view(db, conversation_id, owner, target)
    memory = (target / "memory.md").read_text(encoding="utf-8")
    assert "Run git diff --check before reporting done." in memory
    assert ".xmuse/memory.md" in (target / "charter.md").read_text(encoding="utf-8")


def test_worker_records_sidecar_failures_without_raising(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)

    class _Down:
        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            raise MemoryOSAdapterError("memoryos_unavailable")

    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=_Down()).reconcile_once()
    assert counts["module_memory_failed"] >= 1
    assert ModuleMemoryStore(db).memories(conversation_id, "alpha") == []
