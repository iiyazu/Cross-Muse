"""Module memory (``docs/contracts/module_memory_v1.md``).

Windows from a module's activities, storing curate responses with
supersession and the cursor, retry/skip, rendering into the owner's board
view, and the switch: off writes nothing and calls nothing.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.board_scenarios import build_scenario
from xmuse.memoryos_http_client import MemoryOSAdapterError
from xmuse.room_module_memory_worker import (
    RoomModuleMemoryWorker,
    compose_module_memory_worker,
)
from xmuse_core.chat.room_board_view import materialize_owner_board_view
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
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


def test_worker_curates_stores_and_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XMUSE_MODULE_MEMORY", "on")
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


def test_switch_off_ignores_existing_memories_in_the_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    window = store.next_window(_alpha(db))
    assert window is not None
    store.store_result(window, _lesson(window.last_seq))
    owner = _owner_of_alpha(db, conversation_id)
    monkeypatch.delenv("XMUSE_MODULE_MEMORY", raising=False)
    target = tmp_path / "view"
    target.mkdir()
    materialize_owner_board_view(db, conversation_id, owner, target)
    assert not (target / "memory.md").exists()
    assert "memory.md" not in (target / "charter.md").read_text(encoding="utf-8")


def test_malformed_and_self_superseding_memories_are_rejected(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    window = store.next_window(_alpha(db))
    assert window is not None
    response = _lesson(window.last_seq)
    response["memories"] += [
        {"id": "mem_bad", "kind": "lesson", "statement": "x", "topic_key": "t", "version": "v"},
        {"id": "mem_odd", "kind": "opinion", "statement": "x", "topic_key": "t"},
        {
            "id": "mem_self",
            "kind": "fact",
            "statement": "Self",
            "topic_key": "t",
            "version": 1,
            "occurrences": 0,
            "supersedes_id": "mem_self",
        },
        {
            "id": "mem_ghost",
            "kind": "fact",
            "statement": "Ghost",
            "topic_key": "t",
            "version": 1,
            "occurrences": 0,
            "supersedes_id": "mem_missing",
        },
    ]
    result = store.store_result(window, response)
    assert result["stored"] == 4 and result["rejected"] == 2
    rows = {row["memory_id"]: row for row in store.memories(conversation_id, "alpha")}
    assert rows["mem_self"]["status"] == "active"
    assert rows["mem_self"]["supersedes_id"] is None
    assert rows["mem_ghost"]["supersedes_id"] is None


def test_a_retry_resends_the_same_window(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    start = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    window = store.next_window(_alpha(db), now=start)
    assert window is not None
    store.record_failure(window, "memoryos_unavailable", now=start)
    owner = _alpha(db).owner_participant_id
    for index in range(3):
        RoomKernelStore(db).post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content=f"note {index} for the owner",
            client_request_id=f"retry-note-{index}",
            mentions=[owner],
        )
    retry = store.next_window(_alpha(db), now=start + timedelta(seconds=31))
    assert retry is not None
    assert (retry.first_seq, retry.last_seq) == (window.first_seq, window.last_seq)


def test_human_messages_to_the_owner_flush_after_twelve(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    # Drain the failure windows first.
    while (window := store.next_window(_alpha(db))) is not None:
        store.store_result(window, {"memories": []})
    owner = _alpha(db).owner_participant_id
    for index in range(11):
        RoomKernelStore(db).post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content=f"Decision {index}: amounts are decimal strings",
            client_request_id=f"flush-{index}",
            mentions=[owner],
        )
    assert store.next_window(_alpha(db)) is None
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Decision 11: amounts are decimal strings",
        client_request_id="flush-11",
        mentions=[owner],
    )
    window = store.next_window(_alpha(db))
    assert window is not None
    assert len(window.activities) == 12
    assert {item["type"] for item in window.activities} == {"message"}
    assert {item["speaker"] for item in window.activities} == {"human"}


def test_review_objection_becomes_a_review_window(tmp_path: Path) -> None:
    ctx = build_scenario("review_objected", tmp_path)
    db = tmp_path / "chat.db"
    if Path(ctx["db"]) != db:
        shutil.copy(ctx["db"], db)
    RoomDatabase(db).initialize()
    store = ModuleMemoryStore(db)
    types = set()
    for module in store.active_modules():
        while (window := store.next_window(module)) is not None:
            types |= {item["type"] for item in window.activities}
            store.store_result(window, {"memories": []})
    assert "review_objection" in types


# --- backlog-1: an empty success is a violation, not a silent pass ---


def _runs_rows(db: Path, conversation_id: str) -> list[dict[str, Any]]:
    with RoomDatabase(db).connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "select * from room_module_memory_runs where conversation_id = ?"
                " order by created_at",
                (conversation_id,),
            )
        ]


def _cursor_last_seq(db: Path, conversation_id: str, module_id: str) -> int | None:
    with RoomDatabase(db).connect() as conn:
        row = conn.execute(
            "select last_seq from room_module_memory_cursors"
            " where conversation_id = ? and module_id = ?",
            (conversation_id, module_id),
        ).fetchone()
    return int(row[0]) if row is not None else None


def test_empty_response_marks_run_empty_and_advances_cursor(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    module = _alpha(db)
    window = store.next_window(module)
    assert window is not None
    result = store.store_result(window, {"memories": []})
    assert result["stored"] == 0 and result["rejected"] == 0
    rows = _runs_rows(db, conversation_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "empty"
    assert rows[0]["error_code"] == "curate_empty"
    assert rows[0]["first_seq"] == window.first_seq
    assert rows[0]["last_seq"] == window.last_seq
    assert ModuleMemoryStore(db).memories(conversation_id, "alpha") == []
    # The cursor still advances past exactly this window.
    assert _cursor_last_seq(db, conversation_id, "alpha") == window.last_seq


def test_empty_window_warns_and_never_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db, conversation_id = _failed_board(tmp_path)

    class _Empty:
        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            return {"memories": []}

    with caplog.at_level("WARNING", logger="xmuse.room_module_memory_worker"):
        counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=_Empty()).reconcile_once()
    assert counts["module_memory_failed"] == 0
    assert any("recorded as empty" in record.message for record in caplog.records)
    rows = _runs_rows(db, conversation_id)
    assert rows and all(row["status"] == "empty" for row in rows)
    assert all(row["error_code"] == "curate_empty" for row in rows)


def test_store_exception_is_recorded_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, conversation_id = _failed_board(tmp_path)

    def _boom(self: ModuleMemoryStore, window: Any, response: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ModuleMemoryStore, "store_result", _boom)

    class _Ok:
        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            return _lesson(6)

    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=_Ok()).reconcile_once()
    assert counts["module_memory_failed"] >= 1
    rows = _runs_rows(db, conversation_id)
    assert rows and rows[0]["status"] == "failed"


def _canned_lesson(request: dict[str, Any]) -> dict[str, Any]:
    last = request["window"][-1]
    return {
        "schema_version": "memoryos_curate/v1",
        "scope_id": request.get("scope_id", "replay"),
        "memories": [
            {
                "id": f"mem_replay_{int(last['seq'])}",
                "kind": "lesson",
                "topic_key": "replay.probe",
                "statement": f"Replayed lesson for the window ending at seq {int(last['seq'])}.",
                "version": int(last["seq"]),
                "occurrences": 1,
                "sources": [{"activity_id": str(last["id"]), "quote": str(last["text"])[:200]}],
                "supersedes_id": None,
            }
        ],
        "assignments": [],
        "unaccounted": [],
        "diagnostics": {"llm_calls": 0},
    }


def test_recorded_fixture_requests_replay_and_land(tmp_path: Path) -> None:
    fixture_dir = os.environ.get("CURATE_FIXTURE_DIR", "")
    if not fixture_dir or not Path(fixture_dir).is_dir():
        pytest.skip("CURATE_FIXTURE_DIR not set")
    files = sorted(
        p
        for p in Path(fixture_dir).glob("*.json")
        if p.name != "MANIFEST.json" and p.name != "SHA256SUMS"
    )
    assert files, "no recorded fixtures to replay"
    for path in files:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request.get("profile") == "module"
        assert isinstance(request.get("scope_id"), str) and request["scope_id"]
        items = request.get("window")
        assert isinstance(items, list) and items
        for item in items:
            for key in ("id", "seq", "type", "speaker", "text"):
                assert key in item, f"{path.name} item misses {key}"
        # One scratch board per fixture: the scenario builder uses
        # deterministic ids and must not share a directory.
        sub = tmp_path / path.stem
        sub.mkdir()
        db, _conversation_id = _failed_board(sub)
        store = ModuleMemoryStore(db)
        window = store.next_window(_alpha(db))
        assert window is not None
        result = store.store_result(window, _canned_lesson(request))
        assert result["stored"] == 1, path.name


# --- backlog-2: empty successes are resent up to twice, then recorded ---


def _scripted_client(script: list[str], lesson_seq: int = 6) -> Any:
    """Fake curate client following a script of 'empty' and 'lesson' sends."""

    calls: list[dict[str, Any]] = []

    class _Scripted:
        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            calls.append(request)
            kind = script[min(len(calls) - 1, len(script) - 1)]
            if kind == "lesson":
                window = request["window"]
                return _lesson_for_seq(window)
            return {"memories": []}

    client = _Scripted()
    client.calls = calls  # type: ignore[attr-defined]
    return client


def _lesson_for_seq(window: list[dict[str, Any]]) -> dict[str, Any]:
    last = window[-1]
    base = _lesson(int(last["seq"]))
    base["memories"][0]["sources"] = [
        {"activity_id": str(last["id"]), "quote": str(last["text"])[:200]}
    ]
    return base


def test_empty_window_resent_twice_then_recorded_empty(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    client = _scripted_client(["empty", "empty", "empty"])
    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=client).reconcile_once()
    assert len(client.calls) == 3
    assert counts["module_memory_stored"] == 0
    rows = _runs_rows(db, conversation_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "empty"
    assert rows[0]["error_code"] == "curate_empty"


def test_retry_stops_at_first_storable_response(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    client = _scripted_client(["empty", "empty", "lesson"])
    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=client).reconcile_once()
    assert len(client.calls) == 3
    assert counts["module_memory_stored"] >= 1
    rows = _runs_rows(db, conversation_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "done"


def test_first_try_success_sends_once(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    void = _runs_rows(db, conversation_id)
    assert void == []
    client = _scripted_client(["lesson"])
    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=client).reconcile_once()
    assert len(client.calls) == 1
    assert counts["module_memory_stored"] >= 1


def test_transport_failure_during_retry_uses_backoff_path(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {"memories": []}
            raise MemoryOSAdapterError("memoryos_unavailable")

    client = _Flaky()
    counts = RoomModuleMemoryWorker(xmuse_root=tmp_path, client=client).reconcile_once()
    assert client.calls == 2
    assert counts["module_memory_failed"] >= 1
    rows = _runs_rows(db, conversation_id)
    assert rows and rows[0]["status"] == "failed"


# --- backlog-3: after two consecutive empty windows the next one escalates ---


def _hand_window(conversation_id: str, module_id: str, owner: str, first: int, last: int) -> Any:
    from xmuse_core.chat.room_module_memory import ModuleRef, Window

    return Window(
        module=ModuleRef(conversation_id, module_id, owner),
        activities=[{"id": f"a{seq}"} for seq in range(first, last + 1)],
        context=[],
        first_seq=first,
        last_seq=last,
        active=[],
    )


def test_consecutive_empty_windows_counts_and_resets(tmp_path: Path) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    owner = _alpha(db).owner_participant_id
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 0
    store.store_result(_hand_window(conversation_id, "alpha", owner, 1, 5), {"memories": []})
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 1
    store.store_result(_hand_window(conversation_id, "alpha", owner, 6, 10), {"memories": []})
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 2
    window = _hand_window(conversation_id, "alpha", owner, 11, 15)
    store.store_result(window, _lesson(15))
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 0
    store.store_result(_hand_window(conversation_id, "alpha", owner, 16, 20), {"memories": []})
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 1
    store.record_failure(_hand_window(conversation_id, "alpha", owner, 21, 25), "x")
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 0


def _post_humans(db: Path, conversation_id: str, owner: str, start: int, count: int) -> None:
    for index in range(count):
        RoomKernelStore(db).post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content=f"Note {start + index}: keep the Decimal migration in mind",
            client_request_id=f"esc-{start + index}",
            mentions=[owner],
        )


def _insert_failure(
    db: Path, tmpl: dict[str, Any], conversation_id: str, seq: int, aid: str
) -> None:
    import sqlite3 as _sqlite3

    row = dict(tmpl)
    row.update(activity_id=aid, conversation_id=conversation_id, seq=seq)
    conn = _sqlite3.connect(db)
    try:
        cols = [d[0] for d in conn.execute("select * from room_activities limit 0").description]
        conn.execute(
            "insert into room_activities ({}) values ({})".format(
                ",".join(cols), ",".join("?" * len(cols))
            ),
            [row[k] for k in cols],
        )
        conn.commit()
    finally:
        conn.close()


def _failure_template(db: Path) -> dict[str, Any]:
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db)
    try:
        cols = [d[0] for d in conn.execute("select * from room_activities limit 0").description]
        row = conn.execute(
            "select * from room_activities where activity_type = 'board.verification'"
            " limit 1"
        ).fetchone()
        assert row is not None
        return dict(zip(cols, row, strict=True))
    finally:
        conn.close()


def _wipe_activities(db: Path, conversation_id: str) -> None:
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db)
    try:
        conn.execute("delete from room_activities where conversation_id = ?", (conversation_id,))
        conn.commit()
    finally:
        conn.close()


def test_escalated_context_at_two_not_after(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db, conversation_id = _failed_board(tmp_path)
    store = ModuleMemoryStore(db)
    owner = _alpha(db).owner_participant_id
    tmpl = _failure_template(db)
    _wipe_activities(db, conversation_id)
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 0
    # Streak 1: twelve human messages flush by count, stored empty.
    _post_humans(db, conversation_id, owner, 0, 12)
    first = store.next_window(_alpha(db))
    assert first is not None and len(first.activities) == 12
    store.store_result(first, {"memories": []})
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 1
    # Streak 2: one failure after the cursor, stored empty.
    _insert_failure(db, tmpl, conversation_id, first.last_seq + 1, "act_esc_2")
    second = store.next_window(_alpha(db))
    assert second is not None and second.activities[-1]["type"] == "gate_failure"
    store.store_result(second, {"memories": []})
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 2

    requests: list[dict[str, Any]] = []

    class _Empty:
        def curate(self, request: dict[str, Any]) -> dict[str, Any]:
            requests.append(request)
            if request.get("scope_id") != "alpha":
                return _lesson(1)
            return {"memories": []}

    def _alpha_requests() -> list[dict[str, Any]]:
        return [r for r in requests if r.get("scope_id") == "alpha"]

    _insert_failure(db, tmpl, conversation_id, second.last_seq + 1, "act_esc_3")
    with caplog.at_level("WARNING", logger="xmuse.room_module_memory_worker"):
        RoomModuleMemoryWorker(xmuse_root=tmp_path, client=_Empty()).reconcile_once()
    assert any("escalating context" in r.message for r in caplog.records)
    # The empty budget resends the same window up to three times; every send
    # carries the escalated context.
    assert len(_alpha_requests()) == 3
    assert all(len(r["context"]) > 8 for r in _alpha_requests())
    assert store.consecutive_empty_windows(conversation_id, "alpha") == 3
    # A third consecutive empty does not escalate again: default cap returns.
    with RoomDatabase(db).connect() as conn:
        top = conn.execute("select max(seq) from room_activities").fetchone()[0]
    _insert_failure(db, tmpl, conversation_id, int(top) + 1, "act_esc_4")
    requests.clear()
    RoomModuleMemoryWorker(xmuse_root=tmp_path, client=_Empty()).reconcile_once()
    assert len(_alpha_requests()) == 3
    assert all(len(r["context"]) == 8 for r in _alpha_requests())
