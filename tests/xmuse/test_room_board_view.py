"""Behaviour tests for owner board views and the operator board API."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_board import RoomBoardStore, contract_digest
from xmuse_core.chat.room_board_view import (
    materialize_owner_board_view,
    refresh_board_views,
)
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_host import RoomObservationDelivery, RoomTransportResult
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_owner_transport import (
    OwnerWorkspaceWriteSettings,
    RoomOwnerTransportRouter,
    owner_id_for_participant,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(seconds=10)

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}


def _git(*args: str, cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), env=_GIT_ENV, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def _init_source(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / "a.txt").write_text("hello\n")
    _git("add", "a.txt", cwd=path)
    _git("commit", "-m", "initial", cwd=path)


def _board_room(tmp_path: Path, db_name: str = "chat.db", count: int = 3):
    db = tmp_path / db_name
    conversation = RoomTestStore(db).create_conversation("board room")
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(count)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    return db, conversation.id, members


def _claim(db: Path, conversation_id: str, participant, *, owner: str):
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=owner,
        lease_ttl_s=300.0,
        now=T0,
    )
    assert claimed is not None
    return claimed["observation"]


def _lease_kwargs(participant, observation, *, request_id: str) -> dict[str, Any]:
    return {
        "conversation_id": observation["conversation_id"],
        "participant_id": participant.participant_id,
        "caller_identity": f"god:testsess:{participant.participant_id}",
        "observation_id": observation["observation_id"],
        "lease_token": observation["lease_token"],
        "client_request_id": request_id,
        "now": NOW,
    }


def _split_payload(members):
    lead, owner_a, owner_b = members[0], members[1], members[2]
    modules = [
        {
            "module_id": "alpha",
            "title": "Alpha module",
            "paths": ["src/alpha/**"],
            "provides": ["api.alpha"],
            "depends": ["api.beta"],
            "acceptance": ["alpha works"],
            "report_to": lead.participant_id,
        },
        {
            "module_id": "beta",
            "title": "Beta module",
            "paths": ["src/beta/**"],
            "provides": ["api.beta"],
            "depends": ["api.alpha"],
            "acceptance": ["beta works"],
            "report_to": lead.participant_id,
        },
    ]
    assignments = {"alpha": owner_a.participant_id, "beta": owner_b.participant_id}
    contracts = [
        {
            "contract_id": "api.alpha",
            "provider_module_id": "alpha",
            "kind": "api_schema",
            "content": '{"alpha": 1}',
            "rationale": "alpha surface",
        },
        {
            "contract_id": "api.beta",
            "provider_module_id": "beta",
            "kind": "types",
            "content": "type Beta = string;",
            "rationale": "beta surface",
        },
    ]
    return modules, assignments, contracts


def _approved_board(tmp_path: Path):
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    obs_a = _claim(db, conversation_id, members[1], owner="host-a")
    obs_b = _claim(db, conversation_id, members[2], owner="host-b")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    decided = store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    assert decided["status"] == "approved"
    return {
        "db": db,
        "conversation_id": conversation_id,
        "members": members,
        "store": store,
        "leases": {
            members[0].participant_id: lead_obs,
            members[1].participant_id: obs_a,
            members[2].participant_id: obs_b,
        },
        "split_id": proposed["split_id"],
    }


# ---------------------------------------------------------------------------
# materialize
# ---------------------------------------------------------------------------


def test_materialize_writes_index_charter_and_exact_contracts(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    db, conversation_id, members = ctx["db"], ctx["conversation_id"], ctx["members"]
    owner_a = members[1]
    target = tmp_path / "board-a"
    target.mkdir()
    digest = materialize_owner_board_view(db, conversation_id, owner_a.participant_id, target)
    assert digest.startswith("sha256:")
    index = json.loads((target / "INDEX.json").read_text())
    assert index["schema_version"] == "room_board_view/v1"
    assert index["conversation_id"] == conversation_id
    assert index["participant_id"] == owner_a.participant_id
    assert index["board_seq"] > 0
    assert (
        digest
        == "sha256:"
        + __import__("hashlib").sha256((target / "INDEX.json").read_bytes()).hexdigest()
    )
    # Owner A owns alpha; sees its own charter fully and beta as a summary.
    assert [m["module_id"] for m in index["my_modules"]] == ["alpha"]
    assert index["my_modules"][0]["version"] == 1
    assert index["my_modules"][0]["charter"]["title"] == "Alpha module"
    assert [m["module_id"] for m in index["other_modules"]] == ["beta"]
    assert set(index["other_modules"][0]) >= {
        "module_id",
        "version",
        "owner_participant_id",
        "provides",
        "depends",
    }
    by_id = {c["contract_id"]: c for c in index["contracts"]}
    assert set(by_id) == {"api.alpha", "api.beta"}
    assert by_id["api.alpha"]["file"] == "contracts/api.alpha@v1.txt"
    assert (target / "contracts" / "api.alpha@v1.txt").read_text() == '{"alpha": 1}'
    assert (target / "contracts" / "api.beta@v1.txt").read_text() == "type Beta = string;"
    charter_md = (target / "charter.md").read_text()
    assert "alpha" in charter_md
    assert "Alpha module" in charter_md
    assert "src/alpha/**" in charter_md
    assert "api.alpha" in charter_md
    assert "api.beta" in charter_md
    assert "alpha works" in charter_md
    assert "beta" in charter_md  # other-modules table


def test_revision_replaces_file_and_deletes_stale_keeping_inode(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    db, conversation_id, members, store = (
        ctx["db"],
        ctx["conversation_id"],
        ctx["members"],
        ctx["store"],
    )
    owner_a, owner_b = members[1], members[2]
    leases = ctx["leases"]
    target = tmp_path / "board-a"
    target.mkdir()
    before_inode = target.stat().st_ino
    materialize_owner_board_view(db, conversation_id, owner_a.participant_id, target)
    assert (target / "contracts" / "api.alpha@v1.txt").exists()
    store.publish_contract(
        **_lease_kwargs(owner_a, leases[owner_a.participant_id], request_id="rev-1"),
        contract_id="api.alpha",
        kind="api_schema",
        content='{"alpha": 2}',
        base_version=1,
        rationale="revise",
    )
    materialize_owner_board_view(db, conversation_id, owner_b.participant_id, target)
    # Dependent owner B sees the revised contract under its new versioned name.
    assert (target / "contracts" / "api.alpha@v2.txt").read_text() == '{"alpha": 2}'
    assert not (target / "contracts" / "api.alpha@v1.txt").exists()
    assert target.stat().st_ino == before_inode
    index = json.loads((target / "INDEX.json").read_text())
    assert [c["file"] for c in index["contracts"] if c["contract_id"] == "api.alpha"] == [
        "contracts/api.alpha@v2.txt"
    ]


def test_symlink_in_contracts_is_removed_not_followed(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    db, conversation_id, members = ctx["db"], ctx["conversation_id"], ctx["members"]
    owner_a = members[1]
    target = tmp_path / "board-a"
    target.mkdir()
    materialize_owner_board_view(db, conversation_id, owner_a.participant_id, target)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = target / "contracts" / "evil.txt"
    link.symlink_to(outside)
    assert link.is_symlink()
    materialize_owner_board_view(db, conversation_id, owner_a.participant_id, target)
    assert not link.exists() or not link.is_symlink()
    assert outside.read_text() == "secret"
    # Only referenced contract files remain.
    names = sorted(p.name for p in (target / "contracts").iterdir())
    assert names == ["api.alpha@v1.txt", "api.beta@v1.txt"]


def test_non_owner_gets_owns_nothing_charter(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    db, conversation_id, members = ctx["db"], ctx["conversation_id"], ctx["members"]
    lead = members[0]
    target = tmp_path / "board-lead"
    target.mkdir()
    materialize_owner_board_view(db, conversation_id, lead.participant_id, target)
    index = json.loads((target / "INDEX.json").read_text())
    assert index["my_modules"] == []
    assert len(index["other_modules"]) == 2
    assert index["contracts"] == []
    charter_md = (target / "charter.md").read_text()
    assert "owns nothing" in charter_md.lower()


def test_refresh_only_touches_existing_owner_dirs(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    conversation_id, members = ctx["conversation_id"], ctx["members"]
    owner_a, owner_b = members[1], members[2]
    board_root = tmp_path / "runtime" / "board"
    owner_a_id = owner_id_for_participant(conversation_id, owner_a.participant_id)
    owner_b_id = owner_id_for_participant(conversation_id, owner_b.participant_id)
    dir_a = board_root / owner_a_id
    dir_a.mkdir(parents=True)
    # dir_b does not exist; refresh must skip it without creating it.
    refreshed = refresh_board_views(tmp_path, conversation_id)
    assert refreshed == [owner_a_id]
    assert (dir_a / "INDEX.json").exists()
    assert not (board_root / owner_b_id).exists()
    # A symlink at the owner path is not a real directory: skipped.
    link = board_root / owner_b_id
    link.symlink_to(dir_a, target_is_directory=True)
    refreshed = refresh_board_views(tmp_path, conversation_id)
    assert refreshed == [owner_a_id]
    assert link.is_symlink()


# ---------------------------------------------------------------------------
# owner router
# ---------------------------------------------------------------------------


class _RecordingTransport:
    def __init__(self, board_dir: Path | None = None) -> None:
        self.deliveries: list[RoomObservationDelivery] = []
        self.board_dir = board_dir
        self.saw_index_at_deliver: bool | None = None

    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult:
        if self.board_dir is not None:
            self.saw_index_at_deliver = (self.board_dir / "INDEX.json").exists()
        self.deliveries.append(delivery)
        return RoomTransportResult("finished")


def _writer_participant(tmp_path: Path, db: Path, conversation_id: str) -> Participant:
    return ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="writer",
        display_name="Writer",
        cli_kind="claude",  # type: ignore[arg-type]
        model="test-model",
        workspace_access="workspace_write",  # type: ignore[arg-type]
    )


def _delivery_for(participant: Participant) -> RoomObservationDelivery:
    return RoomObservationDelivery(
        conversation_id=participant.conversation_id,
        participant=participant,
        observation={"observation_id": "observation-1"},
        source_activity={"activity_id": "activity-1"},
        recent_activities=(),
        active_participants=(),
        transport_request_id="room-observation:request-1",
        outcome_client_request_id="room-outcome:request-1",
    )


def _owner_settings(tmp_path: Path, source: Path, board_root: Path) -> OwnerWorkspaceWriteSettings:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return OwnerWorkspaceWriteSettings(
        clones_root=tmp_path / "owner-clones",
        source_repo=source,
        xmuse_root=tmp_path,
        home=home,
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
        bwrap=tmp_path / "bwrap",
        claude_agent_argv=("claude-stub",),
        board_root=board_root,
    )


async def test_owner_router_materializes_before_transport(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _init_source(source)
    db, conversation_id, _members = _board_room(tmp_path)
    writer = _writer_participant(tmp_path, db, conversation_id)
    board_root = tmp_path / "runtime" / "board"
    settings = _owner_settings(tmp_path, source, board_root)
    owner_id = owner_id_for_participant(conversation_id, writer.participant_id)
    board_dir = board_root / owner_id
    dedicated = _RecordingTransport(board_dir=board_dir)
    router = RoomOwnerTransportRouter(
        {"claude": _RecordingTransport()},
        settings=settings,
        transport_factory=lambda participant, clone: dedicated,
    )
    result = await router.deliver(_delivery_for(writer), timeout_s=5.0)
    assert result.status == "finished"
    assert dedicated.deliveries
    assert dedicated.saw_index_at_deliver is True
    assert (board_dir / "INDEX.json").exists()


async def test_owner_router_materialize_failure_still_delivers(
    tmp_path: Path, monkeypatch: Any
) -> None:
    source = tmp_path / "source"
    _init_source(source)
    db, conversation_id, _members = _board_room(tmp_path)
    writer = _writer_participant(tmp_path, db, conversation_id)
    settings = _owner_settings(tmp_path, source, tmp_path / "runtime" / "board")
    dedicated = _RecordingTransport()
    router = RoomOwnerTransportRouter(
        {"claude": _RecordingTransport()},
        settings=settings,
        transport_factory=lambda participant, clone: dedicated,
    )
    import xmuse_core.chat.room_board_view as board_view

    def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(board_view, "materialize_owner_board_view", _boom)
    result = await router.deliver(_delivery_for(writer), timeout_s=5.0)
    assert result.status == "finished"
    assert dedicated.deliveries


# ---------------------------------------------------------------------------
# MCP refresh
# ---------------------------------------------------------------------------


def _mcp_call(client: TestClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/mcp/room",
        json={
            "jsonrpc": "2.0",
            "id": name,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_mcp_publish_refreshes_dependent_owner_dir(tmp_path: Path) -> None:
    from xmuse.room_mcp_server import create_app

    db = tmp_path / "chat.db"
    registry = tmp_path / "god_sessions.json"
    conversation = RoomTestStore(db).create_conversation("board room")
    conversation_id = conversation.id
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation_id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(3)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation_id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    sessions = {}
    for index, member in enumerate(members):
        sessions[member.participant_id] = GodSessionRegistry(registry).create(
            member.role,
            member.display_name,
            "codex",
            f"addr-{index}",
            f"inbox-{index}",
            conversation_id,
            member.participant_id,
        )
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    _claim(db, conversation_id, members[1], owner="host-a")
    _claim(db, conversation_id, members[2], owner="host-b")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    # Dependent owner B already has a board dir; publisher A revises via MCP.
    owner_b = members[1]
    owner_b_id = owner_id_for_participant(conversation_id, owner_b.participant_id)
    board_dir_b = tmp_path / "runtime" / "board" / owner_b_id
    board_dir_b.mkdir(parents=True)
    materialize_owner_board_view(db, conversation_id, owner_b.participant_id, board_dir_b)
    assert (board_dir_b / "contracts" / "api.beta@v1.txt").exists()

    owner_a = members[2]
    real_now = datetime.now(UTC)
    fresh = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=owner_a.participant_id,
        lease_owner="host-fresh",
        lease_ttl_s=300.0,
        now=real_now,
    )
    assert fresh is not None
    obs_publisher = fresh["observation"]
    client = TestClient(create_app(tmp_path))
    result = _mcp_call(
        client,
        "chat_room_board_publish_contract",
        {
            "conversation_id": conversation_id,
            "participant_id": owner_a.participant_id,
            "god_session_id": sessions[owner_a.participant_id].god_session_id,
            "observation_id": obs_publisher["observation_id"],
            "lease_token": obs_publisher["lease_token"],
            "client_request_id": "mcp-rev-1",
            "contract_id": "api.beta",
            "kind": "types",
            "content": "type Beta = number;",
            "base_version": 1,
            "rationale": "revise via mcp",
        },
    )
    assert result["isError"] is False
    assert (board_dir_b / "contracts" / "api.beta@v2.txt").read_text() == "type Beta = number;"


# ---------------------------------------------------------------------------
# operator API
# ---------------------------------------------------------------------------


def _api_client(tmp_path: Path) -> TestClient:
    from xmuse.chat_api import create_app

    return TestClient(
        create_app(
            tmp_path,
            auth_token="operator-secret",
            workroom_runtime_inspector=lambda *_args: {
                "state": "ready",
                "code": "ready",
                "ready": True,
            },
        )
    )


def _headers() -> dict[str, str]:
    return {"X-XMuse-Operator-Token": "operator-secret"}


def test_board_projection_shape_and_contract_fetch(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    conversation_id = ctx["conversation_id"]
    client = _api_client(tmp_path)
    response = client.get(f"/api/chat/conversations/{conversation_id}/board")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["schema_version"] == "room_board_projection/v1"
    assert {c["module_id"] for c in payload["charters"]} == {"alpha", "beta"}
    assert {c["contract_id"] for c in payload["contracts"]} == {"api.alpha", "api.beta"}
    latest = next(c for c in payload["contracts"] if c["contract_id"] == "api.alpha")
    assert latest["version"] == 1
    assert latest["digest"] == contract_digest('{"alpha": 1}')
    assert latest["provider_module_id"] == "alpha"
    assert latest["kind"] == "api_schema"
    assert len(payload["activities"]) >= 3
    assert all(a["activity_type"].startswith("board.") for a in payload["activities"])
    assert client.get("/api/chat/conversations/missing/board").status_code == 404

    fetched = client.get(f"/api/chat/conversations/{conversation_id}/board/contracts/api.alpha")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == '{"alpha": 1}'
    assert fetched.json()["version"] == 1
    assert (
        client.get(
            f"/api/chat/conversations/{conversation_id}/board/contracts/api.missing"
        ).status_code
        == 404
    )


def test_board_decision_auth_approve_conflict_and_reject(tmp_path: Path) -> None:
    db, conversation_id, members = _board_room(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="api-propose"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    split_id = proposed["split_id"]
    client = _api_client(tmp_path)
    path = f"/api/chat/operator/board-splits/{split_id}/decision"
    body = {"conversation_id": conversation_id, "decision": "approve"}
    assert client.post(path, json=body).status_code == 401
    assert (
        client.post(path, json=body, headers={"X-XMuse-Operator-Token": "wrong"}).status_code == 401
    )
    approved = client.post(path, json=body, headers=_headers())
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    with RoomDatabase(db).connect() as conn:
        assert (
            conn.execute(
                "select count(*) from room_board_charters where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 2
        )
    second = client.post(path, json=body, headers=_headers())
    assert second.status_code == 409

    # Reject path: a fresh split on the same conversation rejects cleanly.
    proposed2 = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="api-propose-2"),
        modules=[modules[0]],
        assignments={"alpha": assignments["alpha"]},
        contracts=[contracts[0]],
    )
    # Use a conflicting fresh split: approving while alpha is active is 409,
    # but rejecting works.
    rejected = client.post(
        f"/api/chat/operator/board-splits/{proposed2['split_id']}/decision",
        json={"conversation_id": conversation_id, "decision": "reject"},
        headers=_headers(),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
