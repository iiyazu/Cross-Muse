#!/usr/bin/env python3
"""One-shot live smoke of one workspace_write owner participant (OpenCode).

This is not part of CI.  It builds a fresh temporary ``XMUSE_ROOT`` plus a
fresh temporary source git repository, serves the real Room MCP app on an
ephemeral loopback port, and lets one tiny Human turn complete end-to-end
through the durable Room host with a real ``RoomParticipantHost`` driving a
``RoomOwnerTransportRouter`` over an empty route map.

The single OpenCode participant is declared ``workspace_write``, so the
router confines it to its own owner clone under bubblewrap with full native
tools.  The host renews the attempt lease in fenced slices (long-turn
policy), the agent commits ``OWNER.md`` inside its clone and reports the
commit through the room outcome tool, and the script prints timed delivery
evidence plus one JSON summary.  Agent child processes are always terminated
before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn

from xmuse.room_mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_api_models import ParticipantInit, RoomConversationCreate
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_host import (
    LongTurnPolicy,
    RoomHostDeliveryOutcome,
    RoomHostPolicy,
    RoomObservationTransport,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_opencode_sandbox import (
    resolve_bwrap_executable,
    resolve_opencode_executable,
)
from xmuse_core.chat.room_owner_clones import OwnerClone, OwnerCloneError, OwnerCloneManager
from xmuse_core.chat.room_owner_transport import (
    OwnerWorkspaceWriteSettings,
    RoomOwnerTransportRouter,
    build_owner_acp_transport_factory,
    owner_id_for_participant,
    resolve_owner_masked_paths,
    resolve_owner_prepare_command,
    resolve_owner_prepare_timeout_s,
)
from xmuse_core.chat.room_projection import build_room_chat_projection
from xmuse_core.chat.room_setup import RoomSetupService
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

HUMAN_PROMPT = (
    "In your workspace, create a file named OWNER.md containing exactly this "
    "single line: owned by the smoke owner. Then run "
    '`git add OWNER.md && git commit -m "owner smoke"`. Finally, report the '
    "new commit hash through the room outcome tool and stop."
)
DEFAULT_MODEL = "opencode-go/muse-spark-1.3-contributor"
DEFAULT_TIMEOUT_S = 1200.0
# Short base lease so the first long-turn renewal slice (5s) already extends
# the claim-time expiry; the owner turn itself runs under max_turn_s.
DELIVERY_TIMEOUT_S = 30.0
CLEANUP_GRACE_S = 5.0
LEASE_TTL_S = 40.0
WATCH_POLL_S = 1.0

_START = time.monotonic()


def _mark(event: str, **fields: object) -> None:
    elapsed = time.monotonic() - _START
    detail = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    print(f"[smoke {elapsed:8.2f}s] {event} {detail}", flush=True)


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
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
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
    (path / "README.md").write_text("# smoke source\n", encoding="utf-8")
    _run_git(["add", "README.md"], cwd=path)
    _run_git(["commit", "-m", "initial"], cwd=path)
    head = _run_git(["rev-parse", "HEAD"], cwd=path)
    _mark("source_repo_ready", path=str(path), head=head)
    return head


def _resolve_owner_settings(
    *, root: Path, source_repo: Path, mcp_url: str, model: str
) -> OwnerWorkspaceWriteSettings:
    bwrap = resolve_bwrap_executable()
    if bwrap is None:
        raise RuntimeError("bubblewrap executable not found for the owner smoke")
    opencode_exe = resolve_opencode_executable()
    if opencode_exe is None:
        raise RuntimeError("opencode executable not found for the owner smoke")
    try:
        prepare_command = resolve_owner_prepare_command()
    except ValueError as exc:
        raise RuntimeError(f"invalid {exc}") from exc
    try:
        prepare_timeout_s = resolve_owner_prepare_timeout_s()
    except ValueError as exc:
        raise RuntimeError(f"invalid {exc}") from exc
    return OwnerWorkspaceWriteSettings(
        clones_root=root / "runtime" / "owner-clones",
        source_repo=source_repo,
        xmuse_root=root,
        home=Path(str(os.environ.get("HOME") or Path.home())),
        room_mcp_url=mcp_url,
        bwrap=bwrap,
        opencode_argv=(str(opencode_exe), "acp"),
        opencode_default_model=model,
        extra_masked_paths=resolve_owner_masked_paths(),
        prepare_command=prepare_command,
        prepare_timeout_s=prepare_timeout_s,
    )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _LeaseWatcher:
    """Poll chat.db for the first and latest attempt expiry of one observation."""

    def __init__(self, db_path: Path, conversation_id: str, participant_id: str) -> None:
        self._db_path = db_path
        self._conversation_id = conversation_id
        self._participant_id = participant_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.claim_expires_at: str | None = None
        self.claim_seen_s: float | None = None
        self.latest_expires_at: str | None = None
        self.attempt_id: str | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                row = self._read_row()
            except Exception:
                row = None
            if row is not None:
                attempt_id, expires_at = row
                if expires_at:
                    if self.claim_expires_at is None:
                        self.claim_expires_at = expires_at
                        self.claim_seen_s = time.monotonic() - _START
                    self.latest_expires_at = expires_at
                    self.attempt_id = attempt_id or self.attempt_id
            self._stop.wait(WATCH_POLL_S)

    def _read_row(self) -> tuple[str | None, str | None] | None:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        try:
            conn.row_factory = sqlite3.Row
            found = conn.execute(
                "select current_attempt_id, expires_at from room_observations "
                "where conversation_id = ? and participant_id = ? "
                "order by rowid limit 1",
                (self._conversation_id, self._participant_id),
            ).fetchone()
            if found is None:
                return None
            return (str(found["current_attempt_id"] or "") or None, found["expires_at"])
        finally:
            conn.close()


async def _run_smoke(
    *,
    root: Path,
    mcp_url: str,
    model: str,
    timeout_s: float,
) -> int:
    source_repo = root / "source-repo"
    source_head = _create_source_repo(source_repo)
    _mark("root", path=str(root), model=model)
    RoomDatabase(root / "chat.db").initialize()

    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title="Owner workspace smoke",
            client_request_id=f"owner-workspace-smoke-{uuid.uuid4().hex}",
            initial_participants=[
                ParticipantInit(
                    role="build",
                    display_name="Smoke Owner",
                    cli_kind="opencode",
                    model=model,
                    workspace_access="workspace_write",
                )
            ],
        )
    )
    conversation_id = str(setup["id"])
    participant = next(
        item
        for item in ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
        if item.cli_kind == "opencode"
    )
    _mark(
        "room_created",
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        cli_kind=participant.cli_kind,
        model=participant.model,
        workspace_access=participant.workspace_access,
    )

    kernel = RoomKernelStore(root / "chat.db")
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content=HUMAN_PROMPT,
        client_request_id=f"owner-workspace-smoke-human-{uuid.uuid4().hex}",
    )
    human_posted_s = time.monotonic() - _START
    _mark("human_posted", content=HUMAN_PROMPT)

    controls = RoomObservationControlStore(root / "chat.db")
    decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    try:
        settings = _resolve_owner_settings(
            root=root, source_repo=source_repo, mcp_url=mcp_url, model=model
        )
    except RuntimeError as exc:
        print(f"owner smoke unavailable: {exc}", flush=True)
        return 2
    _mark(
        "owner_settings",
        clones_root=str(settings.clones_root),
        source_repo=str(settings.source_repo),
        bwrap=str(settings.bwrap),
        opencode_argv=list(settings.opencode_argv or ()),
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

    transport = RoomOwnerTransportRouter(
        {},
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
        long_turn_selector=lambda item: item.workspace_access == "workspace_write",
    )

    watcher = _LeaseWatcher(root / "chat.db", conversation_id, participant.participant_id)
    final: RoomHostDeliveryOutcome | None = None
    settled_s: float | None = None
    try:
        await projector.start()
        watcher.start()
        _mark("pump_start", timeout_s=timeout_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = await host.pump_once(conversation_id=conversation_id)
            for item in result.deliveries:
                _mark(
                    "delivery",
                    participant_id=item.participant_id,
                    state=item.state,
                    reason=item.reason,
                    attempt_count=item.attempt_count,
                    transport_status=item.transport_status,
                    outcome_type=item.outcome_type,
                    diagnostic=item.diagnostic_text,
                )
                final = item
            if final is not None:
                break
            _mark("no_work", observations=_observation_states(kernel, conversation_id))
            await asyncio.sleep(0.25)
        settled_s = time.monotonic() - _START
    finally:
        watcher.stop()
        for created_transport in created:
            aclose = getattr(created_transport, "aclose", None)
            if callable(aclose):
                await aclose()
        await host.shutdown()
        await projector.shutdown()

    summary = _build_summary(
        root=root,
        conversation_id=conversation_id,
        participant=participant,
        source_repo=source_repo,
        source_head=source_head,
        final=final,
        watcher=watcher,
        human_posted_s=human_posted_s,
        settled_s=settled_s if settled_s is not None else time.monotonic() - _START,
    )
    _print_evidence(root, conversation_id, participant.participant_id)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str), flush=True)
    _mark("smoke_result", ok=bool(summary["ok"]))
    return 0 if summary["ok"] else 1


def _observation_states(kernel: RoomKernelStore, conversation_id: str) -> list[dict[str, object]]:
    return [
        {
            "participant_id": item["participant_id"],
            "status": item["status"],
            "attempt_count": item["attempt_count"],
        }
        for item in kernel.list_observations(conversation_id)
    ]


def _final_attempt_expiry(root: Path, conversation_id: str, participant_id: str) -> str | None:
    conn = sqlite3.connect(str(root / "chat.db"), timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        observation = conn.execute(
            "select current_attempt_id, expires_at from room_observations "
            "where conversation_id = ? and participant_id = ? "
            "order by rowid limit 1",
            (conversation_id, participant_id),
        ).fetchone()
        if observation is None:
            return None
        attempt_id = observation["current_attempt_id"]
        if attempt_id:
            attempt = conn.execute(
                "select expires_at from room_observation_attempts where attempt_id = ?",
                (str(attempt_id),),
            ).fetchone()
            if attempt is not None and attempt["expires_at"]:
                return str(attempt["expires_at"])
        expires_at = observation["expires_at"]
        return str(expires_at) if expires_at else None
    finally:
        conn.close()


def _source_state(source_repo: Path) -> dict[str, Any]:
    head = _run_git(["rev-parse", "HEAD"], cwd=source_repo)
    status = _run_git(["status", "--porcelain"], cwd=source_repo)
    return {
        "head": head,
        "clean": not status.strip(),
        "owner_md_present": (source_repo / "OWNER.md").exists(),
    }


def _build_summary(
    *,
    root: Path,
    conversation_id: str,
    participant: Participant,
    source_repo: Path,
    source_head: str,
    final: RoomHostDeliveryOutcome | None,
    watcher: _LeaseWatcher,
    human_posted_s: float,
    settled_s: float,
) -> dict[str, Any]:
    outcome_committed = (
        final is not None and final.state == "completed" and final.outcome_type is not None
    )
    owner_id = owner_id_for_participant(conversation_id, participant.participant_id)
    clones = OwnerCloneManager(root / "runtime" / "owner-clones")
    clone_commit = False
    patch_has_owner_md = False
    head_commit: str | None = None
    changed_paths: list[str] = []
    patch_error: str | None = None
    try:
        patch = clones.export_patch(owner_id, base_commit=source_head)
    except OwnerCloneError as exc:
        patch_error = exc.code
    else:
        head_commit = patch.head_commit
        changed_paths = list(patch.changed_paths)
        clone_commit = patch.head_commit != source_head
        patch_has_owner_md = "OWNER.md" in patch.changed_paths
    try:
        after = _source_state(source_repo)
    except RuntimeError as exc:
        after = {"head": None, "clean": False, "owner_md_present": True, "error": str(exc)}
    source_unchanged = (
        after.get("head") == source_head
        and bool(after.get("clean"))
        and not bool(after.get("owner_md_present"))
    )
    final_expires_at = _final_attempt_expiry(root, conversation_id, participant.participant_id)
    claim_expires_at = watcher.claim_expires_at or final_expires_at
    claim_dt = _parse_ts(claim_expires_at)
    final_dt = _parse_ts(final_expires_at)
    lease_renewed = claim_dt is not None and final_dt is not None and final_dt > claim_dt
    checks = {
        "outcome_committed": bool(outcome_committed),
        "clone_commit": clone_commit,
        "patch_has_owner_md": patch_has_owner_md,
        "source_unchanged": source_unchanged,
        "lease_renewed": lease_renewed,
    }
    projection = build_room_chat_projection(conversation_id, root)
    timeline = [
        {
            "kind": item["kind"],
            "room_seq": item["room_seq"],
            "actor_kind": item["actor"]["kind"],
            "actor_name": item["actor"]["display_name"],
            "content": item["content"],
        }
        for item in projection["timeline_items"]
    ]
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "conversation_id": conversation_id,
        "participant_id": participant.participant_id,
        "model": participant.model,
        "delivery_state": final.state if final is not None else "no_delivery",
        "outcome_type": final.outcome_type if final is not None else None,
        "owner_id": owner_id,
        "source_head": source_head,
        "source_after": after,
        "head_commit": head_commit,
        "changed_paths": changed_paths,
        "patch_error": patch_error,
        "claim_expires_at": claim_expires_at,
        "final_expires_at": final_expires_at,
        "timings": {
            "human_posted_s": human_posted_s,
            "claim_first_seen_s": watcher.claim_seen_s,
            "settled_s": settled_s,
        },
        "timeline": timeline,
    }


def _print_evidence(root: Path, conversation_id: str, participant_id: str) -> None:
    projection = build_room_chat_projection(conversation_id, root)
    for item in projection["timeline_items"]:
        actor = item["actor"]
        _mark(
            "timeline_item",
            kind=item["kind"],
            room_seq=item["room_seq"],
            actor_kind=actor["kind"],
            actor_name=actor["display_name"],
            role=actor["role"],
            content=item["content"],
        )
    for item in projection["participants"]:
        outcome = item.get("last_completed_outcome") or {}
        _mark(
            "participant_state",
            display_name=item["display_name"],
            role=item["role"],
            state=item["state"],
            last_outcome_type=outcome.get("outcome_type"),
        )
    try:
        record = GodSessionRegistry(root / "god_sessions.json").find_by_conversation_participant(
            conversation_id,
            participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    except Exception as exc:  # evidence only; absence is reported, not raised
        _mark("god_session_unavailable", error=f"{type(exc).__name__}: {exc}")
        return
    _mark(
        "god_session",
        provider_session_kind=record.provider_session_kind,
        provider_session_id=record.provider_session_id,
        provider_binding_status=record.provider_binding_status,
        provider_binding_failure_reason=record.provider_binding_failure_reason,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--keep-root",
        action="store_true",
        help="do not delete the temporary root on exit",
    )
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root = Path(tempfile.mkdtemp(prefix="xmuse-owner-workspace-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        with _serve_room_mcp(root) as mcp_url:
            return asyncio.run(
                _run_smoke(
                    root=root,
                    mcp_url=mcp_url,
                    model=args.model,
                    timeout_s=args.timeout_s,
                )
            )
    finally:
        if args.keep_root:
            print(f"kept smoke root: {root}", flush=True)
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
