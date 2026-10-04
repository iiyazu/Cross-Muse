#!/usr/bin/env python3
"""One-shot live smoke of board module ownership with a mid-flight contract revision.

This is not part of CI.  It builds a fresh temporary ``XMUSE_ROOT`` plus a
fresh temporary source git repository, serves the real Room MCP app on an
ephemeral loopback port, and drives three real agents (a read-only lead and
two ``workspace_write`` owners) through the durable Room host with a real
``RoomParticipantHost`` driving a ``RoomOwnerTransportRouter``.

The run proves module ownership with a mid-flight contract revision: the lead
proposes a two-module split, the script approves it as operator, both owners
claim and implement their charters, then the backend owner publishes contract
``api.greeting`` v2 which wakes the dependent frontend owner; the frontend
realigns in the same provider session.  The script prints timed delivery
evidence plus one JSON summary.  Agent child processes are always terminated
before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn

from xmuse.room_mcp_server import create_app
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_acp_transport import (
    OPENCODE_ACP_PROFILE,
    ROOM_ACP_DEFAULT_COMMAND,
    AcpRoomObservationTransport,
    AcpTransportConfig,
)
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_agy_sandbox import (
    AGY_DEFAULT_MODEL,
    resolve_agy_executable,
    resolve_agy_python3,
)
from xmuse_core.chat.room_api_models import (
    ParticipantInit,
    RoomCollaborationInit,
    RoomConversationCreate,
)
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_host import (
    LongTurnPolicy,
    RoomHostPolicy,
    RoomObservationTransport,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_opencode_sandbox import (
    build_opencode_sandbox_command,
    resolve_bwrap_executable,
    resolve_opencode_executable,
)
from xmuse_core.chat.room_owner_clones import OwnerClone
from xmuse_core.chat.room_owner_ids import owner_id_for_participant
from xmuse_core.chat.room_owner_transport import (
    OwnerWorkspaceWriteSettings,
    RoomOwnerTransportRouter,
    build_owner_acp_transport_factory,
    resolve_owner_masked_paths,
    resolve_owner_prepare_command,
    resolve_owner_prepare_timeout_s,
)
from xmuse_core.chat.room_setup import RoomSetupService
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

ALLOWED_MODELS = (
    "opencode-go/muse-spark-1.3-contributor",
    "opencode-go/muse-spark-1.2-contributor",
)
DEFAULT_LEAD_MODEL = "opencode-go/muse-spark-1.2-contributor"
DEFAULT_OWNER_MODEL = "opencode-go/muse-spark-1.3-contributor"
ALLOWED_FRONTEND_CLIS = ("opencode", "claude", "antigravity")

CONTRACT_V1_CONTENT = (
    "api/greeting.py defines greet(name: str) -> dict returning "
    '{"message": "Hello, <name>!"}. '
    "client/render.py defines render(name: str) -> str that calls "
    "api.greeting.greet and returns the message."
)
CONTRACT_V2_CONTENT = (
    "api/greeting.py defines greet(name: str) -> dict returning "
    '{"message": ..., "lang": "en"}. '
    "client/render.py defines render(name: str) -> str that calls "
    'api.greeting.greet and returns "<message> [en]".'
)

OPERATOR_IDENTITY = "operator:smoke"
DEFAULT_PHASE_TIMEOUT_S = 1200.0
DELIVERY_TIMEOUT_S = 30.0
CLEANUP_GRACE_S = 5.0
LEASE_TTL_S = 40.0
IDLE_SETTLE_S = 5.0
PUMP_SLEEP_S = 0.25

_START = time.monotonic()


def _mark(event: str, **fields: object) -> None:
    elapsed = time.monotonic() - _START
    detail = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    print(f"[board-smoke {elapsed:8.2f}s] {event} {detail}", flush=True)


def validate_model(value: str) -> str:
    """Return the stripped model or raise when it is not an allowed smoke model."""

    model = value.strip()
    if model not in ALLOWED_MODELS:
        raise ValueError(f"unsupported model {value!r}; expected one of {sorted(ALLOWED_MODELS)}")
    return model


def validate_agy_model(value: str) -> str:
    """Return the stripped agy model or raise when it is not a gemini model."""

    model = value.strip()
    if not model.startswith("gemini-"):
        raise ValueError(
            f"unsupported agy model {value!r}; expected a name starting with 'gemini-'"
        )
    return model


def resolve_smoke_claude_argv(frontend_cli: str) -> tuple[str, ...] | None:
    """Return the owner Claude agent argv, or None for a non-Claude frontend."""

    if frontend_cli != "claude":
        return None
    override = os.environ.get("XMUSE_CLAUDE_ACP_COMMAND", "").strip()
    if override:
        return tuple(shlex.split(override))
    return tuple(ROOM_ACP_DEFAULT_COMMAND)


def build_split_spec(*, backend_id: str, frontend_id: str) -> dict[str, Any]:
    """Return the exact module split the lead must propose."""

    modules = [
        {
            "module_id": "backend",
            "title": "Backend API",
            "paths": ["api/**"],
            "provides": ["api.greeting"],
            "depends": [],
            "acceptance": ["python -m pytest -q api"],
            "report_to": None,
        },
        {
            "module_id": "frontend",
            "title": "Frontend client",
            "paths": ["client/**"],
            "provides": [],
            "depends": ["api.greeting"],
            "acceptance": ["python -m pytest -q client"],
            "report_to": None,
        },
    ]
    return {
        "modules": modules,
        "assignments": {"backend": backend_id, "frontend": frontend_id},
        "contracts": [
            {
                "contract_id": "api.greeting",
                "provider_module_id": "backend",
                "kind": "protocol",
                "content": CONTRACT_V1_CONTENT,
                "rationale": "initial greeting protocol",
            }
        ],
    }


def build_split_human_message(*, backend_id: str, frontend_id: str) -> str:
    """Return the Human instruction that tells the lead to propose the split."""

    spec = build_split_spec(backend_id=backend_id, frontend_id=frontend_id)
    payload = json.dumps(spec, indent=2, sort_keys=True)
    return (
        "Propose the module split for this room now. Call "
        "chat_room_board_propose_split with EXACTLY this split (modules, "
        f"assignments, contracts):\n{payload}\n"
        "After the split tool succeeds, submit a short outcome and stop."
    )


def build_revise_human_message() -> str:
    """Return the Human instruction that tells the backend owner to revise the contract."""

    return (
        "Revise contract api.greeting to v2 now. FIRST publish the revised "
        "contract with chat_room_board_publish_contract using base_version=1 "
        f"and exactly this content:\n{CONTRACT_V2_CONTENT}\n"
        "ONLY after the publish succeeds, update api/greeting.py in your "
        'workspace so greet returns {"message": ..., "lang": "en"}, add or '
        "update a pytest test, run the backend acceptance, commit, report "
        "progress, and submit an outcome. Do not skip the publish step."
    )


def build_git_argv(args: list[str]) -> list[str]:
    """Return hardened git argv mirroring ``OwnerCloneManager._run_git``."""

    return ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args]


def owner_clone_path(root: Path, conversation_id: str, participant_id: str) -> Path:
    """Return the expected owner clone directory for one owner participant."""

    return (
        root
        / "runtime"
        / "owner-clones"
        / owner_id_for_participant(conversation_id, participant_id)
    )


def frontend_session_reused(
    charter_session_ids: list[str], revision_session_ids: list[str]
) -> bool:
    """Return True when the charter and revision attempts share one provider session."""

    charter = {session_id for session_id in charter_session_ids if session_id}
    revision = {session_id for session_id in revision_session_ids if session_id}
    return bool(charter & revision)


def compute_board_smoke_checks(evidence: dict[str, Any]) -> dict[str, bool]:
    """Compute the per-condition checks for the final ``ok`` verdict."""

    return {
        "split_approved": bool(evidence.get("split_approved")),
        "backend_charter_claimed": bool(evidence.get("backend_charter_claimed")),
        "frontend_charter_claimed": bool(evidence.get("frontend_charter_claimed")),
        "contract_v2_published_by_backend": bool(evidence.get("contract_v2_published_by_backend")),
        "frontend_completed_revision": bool(evidence.get("frontend_completed_revision")),
        "frontend_render_mentions_lang": bool(evidence.get("frontend_render_mentions_lang")),
    }


def board_smoke_ok(evidence: dict[str, Any]) -> bool:
    """Return the final ``ok`` verdict for fabricated or collected evidence."""

    return all(compute_board_smoke_checks(evidence).values())


@contextmanager
def _serve_room_mcp(root: Path) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(root),
            host="127.0.0.1",
            port=0,
            log_level="warning",
            access_log=False,
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("room mcp server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp/room"
    _mark("room_mcp_ready", url=url)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _run_git(args: list[str], *, cwd: Path) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
    }
    result = subprocess.run(
        build_git_argv(args),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=60.0,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _create_source_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init"], cwd=path)
    _run_git(["config", "user.name", "smoke owner"], cwd=path)
    _run_git(["config", "user.email", "smoke-owner@example.com"], cwd=path)
    _run_git(["config", "commit.gpgsign", "false"], cwd=path)
    (path / "README.md").write_text("# board smoke source\n", encoding="utf-8")
    (path / "api").mkdir(exist_ok=True)
    (path / "api" / "__init__.py").write_text("", encoding="utf-8")
    (path / "client").mkdir(exist_ok=True)
    (path / "client" / "__init__.py").write_text("", encoding="utf-8")
    _run_git(["add", "README.md", "api/__init__.py", "client/__init__.py"], cwd=path)
    _run_git(["commit", "-m", "initial"], cwd=path)
    head = _run_git(["rev-parse", "HEAD"], cwd=path)
    _mark("source_repo_ready", path=str(path), head=head)
    return head


def _resolve_owner_settings(
    *,
    root: Path,
    source_repo: Path,
    mcp_url: str,
    owner_model: str,
    frontend_cli: str,
    agy_model: str = AGY_DEFAULT_MODEL,
) -> OwnerWorkspaceWriteSettings:
    bwrap = resolve_bwrap_executable()
    if bwrap is None:
        raise RuntimeError("bubblewrap executable not found for the board smoke")
    opencode_exe = resolve_opencode_executable()
    if opencode_exe is None:
        raise RuntimeError("opencode executable not found for the board smoke")
    try:
        prepare_command = resolve_owner_prepare_command()
    except ValueError as exc:
        raise RuntimeError(f"invalid {exc}") from exc
    try:
        prepare_timeout_s = resolve_owner_prepare_timeout_s()
    except ValueError as exc:
        raise RuntimeError(f"invalid {exc}") from exc
    agy_executable: Path | None = None
    agy_bridge_script: Path | None = None
    agy_python3: Path | None = None
    if frontend_cli == "antigravity":
        agy_executable = resolve_agy_executable()
        if agy_executable is None:
            raise RuntimeError("agy executable not found for the board smoke")
        agy_python3 = resolve_agy_python3()
        if agy_python3 is None:
            raise RuntimeError("system python3 outside HOME not found for the board smoke")
        agy_bridge_script = Path(__file__).resolve().parent.parent / "xmuse" / "room_mcp_stdio.py"
        if not agy_bridge_script.is_file():
            raise RuntimeError("room mcp stdio bridge not found for the board smoke")
    return OwnerWorkspaceWriteSettings(
        clones_root=root / "runtime" / "owner-clones",
        source_repo=source_repo,
        xmuse_root=root,
        home=Path(str(os.environ.get("HOME") or Path.home())),
        room_mcp_url=mcp_url,
        bwrap=bwrap,
        claude_agent_argv=resolve_smoke_claude_argv(frontend_cli),
        opencode_argv=(str(opencode_exe), "acp"),
        opencode_default_model=owner_model,
        agy_executable=agy_executable,
        agy_default_model=agy_model if frontend_cli == "antigravity" else None,
        agy_bridge_script=agy_bridge_script,
        agy_python3=agy_python3,
        extra_masked_paths=resolve_owner_masked_paths(),
        prepare_command=prepare_command,
        prepare_timeout_s=prepare_timeout_s,
        board_root=root / "runtime" / "board",
    )


def _build_readonly_opencode_config(
    *, root: Path, workspace: Path, mcp_url: str, model: str
) -> AcpTransportConfig:
    """Build the sandboxed read-only OpenCode route for the lead.

    This mirrors ``xmuse/room_runner.py`` ``_opencode_acp_config``: the same
    ``OPENCODE_ACP_PROFILE``, the same ``build_opencode_sandbox_command``
    read-only bubblewrap confinement, and the same ``(root,)`` mask so the
    agent cannot read any Room's ``chat.db`` or session bindings.
    """

    opencode = resolve_opencode_executable()
    if opencode is None:
        raise RuntimeError("opencode executable not found for the board smoke")
    bwrap = resolve_bwrap_executable()
    if bwrap is None:
        raise RuntimeError("bubblewrap executable not found for the board smoke")
    command = build_opencode_sandbox_command(
        bwrap=bwrap,
        opencode=opencode,
        home=Path(str(os.environ.get("HOME") or Path.home())),
        workspace=workspace,
        masked_paths=(root,),
    )
    return AcpTransportConfig(
        workspace=workspace,
        command=command,
        room_mcp_url=mcp_url,
        profile=OPENCODE_ACP_PROFILE,
        default_model=model,
    )


def _connect_db(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(root / "chat.db"), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _is_idle(kernel: RoomKernelStore, conversation_id: str) -> bool:
    return all(
        item.get("status") not in ("pending", "claimed")
        for item in kernel.list_observations(conversation_id)
    )


async def _pump_until_idle(
    *,
    host: RoomParticipantHost,
    kernel: RoomKernelStore,
    conversation_id: str,
    timeout_s: float,
    label: str,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = await host.pump_once(conversation_id=conversation_id)
        for item in result.deliveries:
            _mark(
                f"{label}_delivery",
                participant_id=item.participant_id,
                state=item.state,
                reason=item.reason,
                attempt_count=item.attempt_count,
                transport_status=item.transport_status,
                outcome_type=item.outcome_type,
                diagnostic=item.diagnostic_text,
            )
        if _is_idle(kernel, conversation_id):
            await asyncio.sleep(IDLE_SETTLE_S)
            if _is_idle(kernel, conversation_id):
                _mark(f"{label}_idle")
                return True
        else:
            _mark(
                f"{label}_waiting",
                observations=[
                    {
                        "participant_id": item.get("participant_id"),
                        "status": item.get("status"),
                        "attempt_count": item.get("attempt_count"),
                    }
                    for item in kernel.list_observations(conversation_id)
                ],
            )
        await asyncio.sleep(PUMP_SLEEP_S)
    _mark(f"{label}_timeout", timeout_s=timeout_s)
    return False


def _completed_observation_ids(root: Path, conversation_id: str, participant_id: str) -> set[str]:
    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select observation_id from room_observations "
            "where conversation_id = ? and participant_id = ? and status = 'completed'",
            (conversation_id, participant_id),
        ).fetchall()
        return {str(row["observation_id"]) for row in rows}
    finally:
        conn.close()


def _observation_source_activity_type(root: Path, observation_id: str) -> str | None:
    conn = _connect_db(root)
    try:
        row = conn.execute(
            "select a.activity_type from room_observations o "
            "join room_activities a on a.activity_id = o.activity_id "
            "where o.observation_id = ?",
            (observation_id,),
        ).fetchone()
        return str(row["activity_type"]) if row is not None else None
    finally:
        conn.close()


def _proposed_split_ids(root: Path, conversation_id: str) -> list[str]:
    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select split_id from room_board_splits "
            "where conversation_id = ? and status = 'proposed' order by created_at",
            (conversation_id,),
        ).fetchall()
        return [str(row["split_id"]) for row in rows]
    finally:
        conn.close()


def _contract_versions(root: Path, conversation_id: str, contract_id: str) -> list[dict[str, Any]]:
    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select version, digest, author_participant_id from room_board_contracts "
            "where conversation_id = ? and contract_id = ? order by version",
            (conversation_id, contract_id),
        ).fetchall()
        return [
            {
                "version": int(row["version"]),
                "digest": str(row["digest"]),
                "author_participant_id": str(row["author_participant_id"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _attempt_provider_sessions(
    root: Path, conversation_id: str, participant_id: str, observation_id: str
) -> list[str]:
    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select provider_session_id from room_observation_attempts "
            "where conversation_id = ? and participant_id = ? and observation_id = ? "
            "order by attempt_number",
            (conversation_id, participant_id, observation_id),
        ).fetchall()
        return [str(row["provider_session_id"]) for row in rows if row["provider_session_id"]]
    finally:
        conn.close()


def _collect_evidence(
    *,
    root: Path,
    conversation_id: str,
    by_role: dict[str, Participant],
) -> dict[str, Any]:
    backend = by_role["backend"]
    frontend = by_role["frontend"]
    conn = _connect_db(root)
    try:
        splits = [
            {
                "split_id": str(row["split_id"]),
                "status": str(row["status"]),
                "proposed_by": str(row["proposed_by_participant_id"]),
                "approved_by": row["approved_by"],
                "decided_at": row["decided_at"],
            }
            for row in conn.execute(
                "select * from room_board_splits where conversation_id = ? order by created_at",
                (conversation_id,),
            ).fetchall()
        ]
        charters = [
            {
                "module_id": str(row["module_id"]),
                "version": int(row["version"]),
                "owner_participant_id": str(row["owner_participant_id"]),
                "status": str(row["status"]),
                "claimed_at": row["claimed_at"],
            }
            for row in conn.execute(
                "select * from room_board_charters where conversation_id = ? "
                "order by module_id, version",
                (conversation_id,),
            ).fetchall()
        ]
        contracts = [
            {
                "contract_id": str(row["contract_id"]),
                "version": int(row["version"]),
                "digest": str(row["digest"]),
                "provider_module_id": str(row["provider_module_id"]),
                "kind": str(row["kind"]),
                "author_participant_id": str(row["author_participant_id"]),
            }
            for row in conn.execute(
                "select * from room_board_contracts where conversation_id = ? "
                "order by contract_id, version",
                (conversation_id,),
            ).fetchall()
        ]
        progress = [
            {
                "module_id": str(row["module_id"]),
                "participant_id": str(row["participant_id"]),
                "status": str(row["status"]),
                "summary": str(row["summary"]),
                "created_at": str(row["created_at"]),
            }
            for row in conn.execute(
                "select * from room_board_progress where conversation_id = ? order by created_at",
                (conversation_id,),
            ).fetchall()
        ]
        board_activities = []
        for row in conn.execute(
            "select seq, activity_type, actor_kind, actor_identity, "
            "actor_participant_id, audience_json, created_at from room_activities "
            "where conversation_id = ? and activity_type like 'board.%' order by seq",
            (conversation_id,),
        ).fetchall():
            audience: Any = None
            try:
                audience = json.loads(str(row["audience_json"]))
            except (ValueError, TypeError):
                audience = None
            board_activities.append(
                {
                    "seq": int(row["seq"]),
                    "type": str(row["activity_type"]),
                    "actor_kind": str(row["actor_kind"]),
                    "actor_identity": str(row["actor_identity"]),
                    "actor_participant_id": row["actor_participant_id"],
                    "audience": audience,
                    "created_at": str(row["created_at"]),
                }
            )
        participants: dict[str, Any] = {}
        for role, participant in by_role.items():
            observations = []
            for row in conn.execute(
                "select o.observation_id, o.status, o.outcome_type, a.activity_type "
                "from room_observations o join room_activities a "
                "on a.activity_id = o.activity_id "
                "where o.conversation_id = ? and o.participant_id = ? "
                "order by a.seq, o.rowid",
                (conversation_id, participant.participant_id),
            ).fetchall():
                observation_id = str(row["observation_id"])
                sessions = _attempt_provider_sessions(
                    root, conversation_id, participant.participant_id, observation_id
                )
                observations.append(
                    {
                        "observation_id": observation_id,
                        "source_activity_type": str(row["activity_type"]),
                        "status": str(row["status"]),
                        "outcome_type": row["outcome_type"],
                        "provider_session_ids": sessions,
                    }
                )
            participants[role] = {
                "participant_id": participant.participant_id,
                "cli_kind": participant.cli_kind,
                "model": participant.model,
                "workspace_access": participant.workspace_access,
                "observations": observations,
            }
    finally:
        conn.close()

    clones: dict[str, Any] = {}
    for role, participant in (("backend", backend), ("frontend", frontend)):
        clone_dir = owner_clone_path(root, conversation_id, participant.participant_id)
        try:
            git_log = _run_git(["log", "--oneline"], cwd=clone_dir)
        except Exception as exc:
            git_log = f"unavailable: {exc}"
        files: dict[str, str | None] = {}
        for name in ("api/greeting.py", "client/render.py"):
            candidate = clone_dir / name
            try:
                files[name] = candidate.read_text(encoding="utf-8") if candidate.is_file() else None
            except OSError as exc:
                files[name] = f"unreadable: {exc}"
        clones[role] = {
            "owner_id": owner_id_for_participant(conversation_id, participant.participant_id),
            "path": str(clone_dir),
            "git_log": git_log,
            "files": files,
        }

    frontend_board_dir = (root / "runtime" / "board").joinpath(
        owner_id_for_participant(conversation_id, frontend.participant_id)
    )
    frontend_index_contracts: Any = "unavailable"
    index_path = frontend_board_dir / "INDEX.json"
    try:
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            frontend_index_contracts = index.get("contracts")
    except (OSError, ValueError) as exc:
        frontend_index_contracts = f"unreadable: {exc}"

    charter_sessions: list[str] = []
    revision_sessions: list[str] = []
    frontend_completed_revision = False
    for entry in participants["frontend"]["observations"]:
        if (
            entry["source_activity_type"] == "board.charter_assigned"
            and entry["status"] == "completed"
        ):
            charter_sessions.extend(entry["provider_session_ids"])
        if (
            entry["source_activity_type"] == "board.contract_revised"
            and entry["status"] == "completed"
        ):
            frontend_completed_revision = True
            revision_sessions.extend(entry["provider_session_ids"])

    contract_v2_by_backend = any(
        item["contract_id"] == "api.greeting"
        and item["version"] == 2
        and item["author_participant_id"] == backend.participant_id
        for item in contracts
    )
    charter_claimed = {str(item["module_id"]): item["claimed_at"] is not None for item in charters}
    render_text = (clones["frontend"]["files"] or {}).get("client/render.py") or ""
    evidence: dict[str, Any] = {
        "splits": splits,
        "charters": charters,
        "contracts": contracts,
        "progress": progress,
        "board_activities": board_activities,
        "participants": participants,
        "clones": clones,
        "frontend_board_index_contracts": frontend_index_contracts,
        "split_approved": any(item["status"] == "approved" for item in splits),
        "backend_charter_claimed": bool(charter_claimed.get("backend")),
        "frontend_charter_claimed": bool(charter_claimed.get("frontend")),
        "contract_v2_published_by_backend": contract_v2_by_backend,
        "frontend_completed_revision": frontend_completed_revision,
        "frontend_render_mentions_lang": ("lang" in render_text or "[en]" in render_text),
        "frontend_charter_session_ids": charter_sessions,
        "frontend_revision_session_ids": revision_sessions,
    }
    evidence["frontend_session_reused"] = frontend_session_reused(
        charter_sessions, revision_sessions
    )
    return evidence


async def _run_smoke(
    *,
    root: Path,
    mcp_url: str,
    lead_model: str,
    owner_model: str,
    frontend_cli: str,
    agy_model: str,
    phase_timeout_s: float,
) -> int:
    source_repo = root / "source-repo"
    _create_source_repo(source_repo)
    _mark(
        "root",
        path=str(root),
        lead_model=lead_model,
        owner_model=owner_model,
        frontend_cli=frontend_cli,
    )
    RoomDatabase(root / "chat.db").initialize()

    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title="Board owners smoke",
            client_request_id=f"board-owners-smoke-{uuid.uuid4().hex}",
            collaboration=RoomCollaborationInit(mode="addressed", lead_role="lead"),
            initial_participants=[
                ParticipantInit(
                    role="lead",
                    display_name="Lead",
                    cli_kind="opencode",
                    model=lead_model,
                ),
                ParticipantInit(
                    role="backend",
                    display_name="Backend Owner",
                    cli_kind="opencode",
                    model=owner_model,
                    workspace_access="workspace_write",
                ),
                ParticipantInit(
                    role="frontend",
                    display_name="Frontend Owner",
                    cli_kind=frontend_cli,  # type: ignore[arg-type]
                    model=(
                        owner_model
                        if frontend_cli == "opencode"
                        else (agy_model if frontend_cli == "antigravity" else None)
                    ),
                    workspace_access="workspace_write",
                ),
            ],
        )
    )
    conversation_id = str(setup["id"])
    stored = ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
    by_role = {item.role: item for item in stored}
    for role in ("lead", "backend", "frontend"):
        if role not in by_role:
            print(f"board smoke missing participant role: {role}", flush=True)
            return 1
    lead = by_role["lead"]
    backend = by_role["backend"]
    frontend = by_role["frontend"]
    _mark(
        "room_created",
        conversation_id=conversation_id,
        lead_id=lead.participant_id,
        backend_id=backend.participant_id,
        frontend_id=frontend.participant_id,
    )

    kernel = RoomKernelStore(root / "chat.db")
    controls = RoomObservationControlStore(root / "chat.db")
    decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    try:
        settings = _resolve_owner_settings(
            root=root,
            source_repo=source_repo,
            mcp_url=mcp_url,
            owner_model=owner_model,
            frontend_cli=frontend_cli,
            agy_model=agy_model,
        )
        readonly_config = _build_readonly_opencode_config(
            root=root, workspace=source_repo, mcp_url=mcp_url, model=lead_model
        )
    except RuntimeError as exc:
        print(f"board smoke unavailable: {exc}", flush=True)
        return 2
    _mark(
        "owner_settings",
        clones_root=str(settings.clones_root),
        source_repo=str(settings.source_repo),
        board_root=str(settings.board_root),
    )
    created: list[RoomObservationTransport] = []
    inner_factory = build_owner_acp_transport_factory(
        settings,
        registry_path=root / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
    )

    def _factory(
        factory_participant: Participant, clone: OwnerClone
    ) -> RoomObservationTransport | None:
        created_transport = inner_factory(factory_participant, clone)
        if created_transport is not None:
            created.append(created_transport)
        return created_transport

    readonly_transport = AcpRoomObservationTransport(
        config=readonly_config,
        registry_path=root / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
    )
    created.append(readonly_transport)
    transport = RoomOwnerTransportRouter(
        {"opencode": readonly_transport},
        settings=settings,
        transport_factory=_factory,
    )
    host = RoomParticipantHost(
        root / "chat.db",
        transport,
        policy=RoomHostPolicy(
            delivery_timeout_s=DELIVERY_TIMEOUT_S,
            cleanup_grace_s=CLEANUP_GRACE_S,
            lease_ttl_s=LEASE_TTL_S,
            participant_cooldown_s=0.0,
        ),
        control_store=controls,
        skill_catalog=SkillCatalog.load_bundled(),
        skill_decision_store=decisions,
        long_turn_policy=LongTurnPolicy(
            renew_interval_s=5,
            lease_chunk_s=60,
            stall_timeout_s=300,
            max_turn_s=1200,
        ),
        # Every participant gets long-turn leases: the lead's split turn easily
        # outlives the short base delivery timeout.
        long_turn_selector=lambda item: True,
    )

    phases_ok = True
    try:
        await projector.start()
        # Phase 1: split proposal by the lead.
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content=build_split_human_message(
                backend_id=backend.participant_id, frontend_id=frontend.participant_id
            ),
            client_request_id=f"board-owners-smoke-split-{uuid.uuid4().hex}",
            mentions=[lead.participant_id],
        )
        _mark("split_requested", lead_id=lead.participant_id)
        split_idle = await _pump_until_idle(
            host=host,
            kernel=kernel,
            conversation_id=conversation_id,
            timeout_s=phase_timeout_s,
            label="split",
        )
        split_ids = _proposed_split_ids(root, conversation_id)
        split_ok = split_idle and len(split_ids) == 1
        _mark("split_phase", idle=split_idle, proposed=split_ids, ok=split_ok)
        phases_ok = phases_ok and split_ok

        # Phase 2: operator approval wakes both owners.
        backend_done_before: set[str] = set()
        frontend_done_before: set[str] = set()
        if split_ok:
            application = RoomApplicationService(root / "chat.db", root / "god_sessions.json")
            decision = application.board_decide_split(
                conversation_id=conversation_id,
                split_id=split_ids[0],
                decision="approve",
                operator_identity=OPERATOR_IDENTITY,
            )
            _mark("split_approved", split_id=split_ids[0], result=decision)
            refreshed = refresh_board_views(root, conversation_id)
            _mark("board_views_refreshed", owners=refreshed)
            backend_done_before = _completed_observation_ids(
                root, conversation_id, backend.participant_id
            )
            frontend_done_before = _completed_observation_ids(
                root, conversation_id, frontend.participant_id
            )
            charter_idle = await _pump_until_idle(
                host=host,
                kernel=kernel,
                conversation_id=conversation_id,
                timeout_s=phase_timeout_s,
                label="charter",
            )
            backend_done = (
                _completed_observation_ids(root, conversation_id, backend.participant_id)
                - backend_done_before
            )
            frontend_done = (
                _completed_observation_ids(root, conversation_id, frontend.participant_id)
                - frontend_done_before
            )
            charter_ok = charter_idle and bool(backend_done) and bool(frontend_done)
            _mark(
                "charter_phase",
                idle=charter_idle,
                backend_done=sorted(backend_done),
                frontend_done=sorted(frontend_done),
                ok=charter_ok,
            )
            phases_ok = phases_ok and charter_ok
        else:
            _mark("approve_skipped", reason="split phase failed")

        # Phase 3: backend revises the contract; the frontend must realign.
        if phases_ok:
            revision_before = _completed_observation_ids(
                root, conversation_id, frontend.participant_id
            )
            kernel.post_human_activity(
                conversation_id=conversation_id,
                human_id="human",
                content=build_revise_human_message(),
                client_request_id=f"board-owners-smoke-revise-{uuid.uuid4().hex}",
                mentions=[backend.participant_id],
            )
            _mark("revise_requested", backend_id=backend.participant_id)
            revise_idle = await _pump_until_idle(
                host=host,
                kernel=kernel,
                conversation_id=conversation_id,
                timeout_s=phase_timeout_s,
                label="revise",
            )
            versions = _contract_versions(root, conversation_id, "api.greeting")
            has_v2 = any(item["version"] == 2 for item in versions)
            revision_new = (
                _completed_observation_ids(root, conversation_id, frontend.participant_id)
                - revision_before
            )
            frontend_revised = any(
                _observation_source_activity_type(root, observation_id) == "board.contract_revised"
                for observation_id in revision_new
            )
            revise_ok = revise_idle and has_v2 and frontend_revised
            _mark(
                "revise_phase",
                idle=revise_idle,
                versions=versions,
                revision_new=sorted(revision_new),
                frontend_revised=frontend_revised,
                ok=revise_ok,
            )
            phases_ok = phases_ok and revise_ok
        else:
            _mark("revise_skipped", reason="earlier phase failed")
    finally:
        for created_transport in created:
            aclose = getattr(created_transport, "aclose", None)
            if callable(aclose):
                await aclose()
        await host.shutdown()
        await projector.shutdown()

    evidence = _collect_evidence(root=root, conversation_id=conversation_id, by_role=by_role)
    checks = compute_board_smoke_checks(evidence)
    summary = {
        "ok": phases_ok and board_smoke_ok(evidence),
        "checks": checks,
        "phases_ok": phases_ok,
        "frontend_session_reused": evidence["frontend_session_reused"],
        "conversation_id": conversation_id,
        "evidence": evidence,
    }
    for activity in evidence["board_activities"]:
        _mark(
            "board_activity",
            seq=activity["seq"],
            type=activity["type"],
            actor=activity["actor_identity"],
            audience=activity["audience"],
        )
    for role, info in evidence["participants"].items():
        _mark(
            "participant_state",
            role=role,
            observations=[
                {
                    "source": item["source_activity_type"],
                    "status": item["status"],
                    "outcome_type": item["outcome_type"],
                    "sessions": item["provider_session_ids"],
                }
                for item in info["observations"]
            ],
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str), flush=True)
    _mark("smoke_result", ok=bool(summary["ok"]))
    return 0 if summary["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-model", default=DEFAULT_LEAD_MODEL)
    parser.add_argument("--owner-model", default=DEFAULT_OWNER_MODEL)
    parser.add_argument("--agy-model", default=AGY_DEFAULT_MODEL)
    parser.add_argument("--frontend-cli", choices=list(ALLOWED_FRONTEND_CLIS), default="opencode")
    parser.add_argument("--phase-timeout-s", type=float, default=DEFAULT_PHASE_TIMEOUT_S)
    parser.add_argument(
        "--keep-root",
        action="store_true",
        help="do not delete the temporary root on exit",
    )
    args = parser.parse_args()
    try:
        lead_model = validate_model(args.lead_model)
        owner_model = validate_model(args.owner_model)
        agy_model = validate_agy_model(args.agy_model)
    except ValueError as exc:
        print(f"board smoke unavailable: {exc}", flush=True)
        return 2
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root = Path(tempfile.mkdtemp(prefix="xmuse-board-owners-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        with _serve_room_mcp(root) as mcp_url:
            return asyncio.run(
                _run_smoke(
                    root=root,
                    mcp_url=mcp_url,
                    lead_model=lead_model,
                    owner_model=owner_model,
                    frontend_cli=args.frontend_cli,
                    agy_model=agy_model,
                    phase_timeout_s=args.phase_timeout_s,
                )
            )
    finally:
        print(f"smoke root: {root}", flush=True)
        if args.keep_root:
            print(f"kept smoke root: {root}", flush=True)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
