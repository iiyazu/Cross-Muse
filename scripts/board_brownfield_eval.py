"""Brownfield board evaluation: N owners deliver a real task through the board.

Runs one Room over an external seed repository (for example the r15 remix
replay) with a lead, one OpenCode owner per planned module and, optionally, a
read-only Claude reviewer (``--reviewer claude`` turns on ``cross_family``
review).  The flow is the product's own:

1. The Human asks the lead to propose the exact planned split; the operator
   approves it.
2. The Human sends each owner its requirements (the plan's ``task`` text).
3. The host runs until nothing moves: owners claim ``done``, the host
   verifies every claim with the server-owned gate profile, the reviewer rules
   when reviews are on, and the host integrates accepted candidates into its
   integration branch.  No further Human message is sent.

At the end the integration branch's green head is exported as a plain git
repository (``<root>/result-repo``) so an independent scorer (the hidden
upstream tests) can grade exactly what the board delivered, and a JSON summary
with the board's own counters is written to ``--result``.

Plan file (JSON)::

    {"title": "...",
     "modules": [{"module_id": "a", "title": "tar-parser",
                  "paths": ["packages/tar-parser/**"], "task": "<markdown>"}]}

The seed must satisfy the execution profile's markers once its dependencies
are installed offline (``--install-command``, run in the execution root and in
every owner clone).  Real providers are called: this is never part of CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import board_owners_smoke as smoke  # noqa: E402
from xmuse.room_module_memory_worker import compose_module_memory_worker  # noqa: E402
from xmuse.room_runner import _agy_config  # noqa: E402
from xmuse_core.chat.participant_store import Participant, ParticipantStore  # noqa: E402
from xmuse_core.chat.room_acp_transport import (  # noqa: E402
    CLAUDE_ACP_PROFILE,
    ROOM_ACP_DEFAULT_COMMAND,
    AcpRoomObservationTransport,
    AcpTransportConfig,
)
from xmuse_core.chat.room_agent_stream import (  # noqa: E402
    RoomAgentStreamCache,
    RoomAgentStreamProjector,
)
from xmuse_core.chat.room_agy_sandbox import (  # noqa: E402
    resolve_agy_executable,
    resolve_agy_python3,
)
from xmuse_core.chat.room_agy_transport import AgyRoomObservationTransport  # noqa: E402
from xmuse_core.chat.room_api_models import (  # noqa: E402
    ParticipantInit,
    RoomCollaborationInit,
    RoomConversationCreate,
)
from xmuse_core.chat.room_application import RoomApplicationService  # noqa: E402
from xmuse_core.chat.room_board_integration import INTEGRATION_REF_PREFIX  # noqa: E402
from xmuse_core.chat.room_board_view import refresh_board_views  # noqa: E402
from xmuse_core.chat.room_controls import RoomObservationControlStore  # noqa: E402
from xmuse_core.chat.room_database import RoomDatabase  # noqa: E402
from xmuse_core.chat.room_execution_profiles import get_execution_gate_profile  # noqa: E402
from xmuse_core.chat.room_host import (  # noqa: E402
    LongTurnPolicy,
    RoomHostPolicy,
    RoomObservationTransport,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore  # noqa: E402
from xmuse_core.chat.room_module_memory import (  # noqa: E402
    IDLE_FLUSH_S,
    MODULE_MEMORY_ENV,
    ModuleMemoryStore,
)
from xmuse_core.chat.room_owner_clones import OwnerClone  # noqa: E402
from xmuse_core.chat.room_owner_transport import (  # noqa: E402
    OWNER_PREPARE_COMMAND_ENV,
    OWNER_PREPARE_TIMEOUT_ENV,
    RoomOwnerTransportRouter,
    build_owner_acp_transport_factory,
)
from xmuse_core.chat.room_setup import RoomSetupService  # noqa: E402
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore  # noqa: E402
from xmuse_core.skills.catalog import SkillCatalog  # noqa: E402

RESULT_SCHEMA_VERSION = "board_brownfield_result/v1"
DEFAULT_PROFILE_ID = "remix-monorepo/v1"
DEFAULT_INSTALL_COMMAND = "pnpm install --offline --frozen-lockfile --ignore-scripts"
DEFAULT_RUN_TIMEOUT_S = 3 * 3600.0
MODULE_ID_PREFIX = "owner-"


OWNER_CLIS = ("opencode", "antigravity")


def module_owner_clis(plan: Mapping[str, Any], default: str) -> dict[str, str]:
    """Module id -> owner provider; a module's ``owner_cli`` overrides the run default."""

    return {
        str(module["module_id"]): str(module.get("owner_cli") or default)
        for module in plan["modules"]
    }


def load_plan(path: Path) -> dict[str, Any]:
    """Load and validate a plan file (module ids, paths and task text)."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    modules = raw.get("modules") if isinstance(raw, Mapping) else None
    if not isinstance(modules, list) or not modules:
        raise ValueError("plan needs a non-empty modules list")
    seen: set[str] = set()
    for module in modules:
        if not isinstance(module, Mapping):
            raise ValueError("plan module must be an object")
        module_id = module.get("module_id")
        paths = module.get("paths")
        task = module.get("task")
        if not isinstance(module_id, str) or not module_id or module_id in seen:
            raise ValueError(f"plan module_id invalid or duplicated: {module_id!r}")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
            raise ValueError(f"plan module {module_id} needs paths")
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"plan module {module_id} needs task text")
        if module.get("owner_cli", "opencode") not in OWNER_CLIS:
            raise ValueError(f"plan module {module_id} owner_cli must be one of {OWNER_CLIS}")
        seen.add(module_id)
    return dict(raw)


def build_split_spec(plan: Mapping[str, Any], assignments: Mapping[str, str]) -> dict[str, Any]:
    """Return the exact split the lead must propose (no contracts, no dependencies)."""

    modules = [
        {
            "module_id": module["module_id"],
            "title": str(module.get("title") or module["module_id"])[:200],
            "paths": list(module["paths"]),
            "provides": [],
            "depends": [],
            "acceptance": [
                "Implement the requirements the Human sends you in this room, inside "
                "your module's paths. Run the affected packages' tests and typecheck, "
                "commit your work in your clone, report progress and report done.",
            ],
            "report_to": None,
        }
        for module in plan["modules"]
    ]
    return {"modules": modules, "assignments": dict(assignments), "contracts": []}


def build_split_message(spec: Mapping[str, Any]) -> str:
    payload = json.dumps(spec, indent=2, sort_keys=True)
    return (
        "Propose the module split for this room now. Call "
        "chat_room_board_propose_split with EXACTLY this split (modules, "
        f"assignments, contracts):\n{payload}\n"
        "After the split tool succeeds, submit a short outcome and stop."
    )


def build_task_message(module: Mapping[str, Any]) -> str:
    return (
        f"Requirements for your module `{module['module_id']}` "
        f"({module.get('title') or module['module_id']}):\n\n{str(module['task']).strip()}\n"
    )


def followup_text(item: Any) -> str:
    """A follow-up is a task string or `{"text": ..., "restart": bool}`."""

    return str(item["text"] if isinstance(item, Mapping) else item)


def followup_restarts(item: Any) -> bool:
    """With `--restart-owners`, owners restart before rounds marked `restart`."""

    return isinstance(item, Mapping) and bool(item.get("restart"))


def build_followup_message(module: Mapping[str, Any], text: str) -> str:
    return f"Next task for your module `{module['module_id']}`:\n\n{str(text).strip()}\n"


async def settle_module_memory(root: Path, *, timeout_s: float = 900.0) -> dict[str, Any]:
    """Wait until every module's pending activity has been curated.

    The worker thread flushes a quiet module after ``IDLE_FLUSH_S``; this only
    waits (it never curates itself, so the two never race on one window).
    """

    store = ModuleMemoryStore(root / "chat.db")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        horizon = datetime.now(UTC) + timedelta(seconds=IDLE_FLUSH_S + 1)
        pending = [
            module.module_id
            for module in store.active_modules()
            if store.next_window(module, now=horizon) is not None
        ]
        if not pending:
            return {"settled": True, "waited_s": round(timeout_s - (deadline - time.monotonic()))}
        await asyncio.sleep(10.0)
    return {"settled": False, "pending": pending}


def _run(argv: list[str], *, cwd: Path, timeout_s: float = 1800.0) -> str:
    result = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s, check=False
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-2000:]
        raise RuntimeError(f"{argv[0]} failed in {cwd}: {tail}")
    return result.stdout.strip()


def prepare_source_repo(seed: Path, source: Path, install: tuple[str, ...]) -> str:
    """Clone the seed (no hardlinks, no remote) and install its dependencies offline."""

    _run(["git", "clone", "-q", "--no-hardlinks", str(seed), str(source)], cwd=source.parent)
    _run(["git", "remote", "remove", "origin"], cwd=source)
    _run(["git", "config", "user.name", "brownfield seed"], cwd=source)
    _run(["git", "config", "user.email", "seed@example.invalid"], cwd=source)
    _run(list(install), cwd=source)
    head = _run(["git", "rev-parse", "HEAD"], cwd=source)
    smoke._mark("source_repo_ready", path=str(source), head=head)
    return head


def export_green_head(root: Path, conversation_id: str) -> dict[str, Any]:
    """Export the integration branch's green head as ``<root>/result-repo``."""

    mirror = root / "runtime" / "owner-clones" / ".mirror.git"
    ref = f"{INTEGRATION_REF_PREFIX}{conversation_id}"
    out = root / "result-repo"
    if not mirror.is_dir():
        return {"green_head": None, "result_repo": None, "reason": "no_mirror"}
    probe = subprocess.run(
        ["git", "--git-dir", str(mirror), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return {"green_head": None, "result_repo": None, "reason": "no_integration_branch"}
    green = probe.stdout.strip()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    _run(["git", "init", "-q"], cwd=out)
    _run(["git", "fetch", "-q", "--no-tags", str(mirror), f"{ref}:refs/heads/result"], cwd=out)
    _run(["git", "checkout", "-q", "result"], cwd=out)
    return {"green_head": green, "result_repo": str(out), "reason": None}


CLAUDE_ACP_DEFAULT_MODEL = "claude-acp-default"


def reviewer_participant(reviewer: str, agy_model: str) -> ParticipantInit:
    """The read-only cross-family reviewer; every non-codex participant names a model."""

    return ParticipantInit(
        role="reviewer",
        display_name="Reviewer",
        cli_kind=reviewer,  # type: ignore[arg-type]
        model=agy_model if reviewer == "antigravity" else CLAUDE_ACP_DEFAULT_MODEL,
    )


def collect_board_rows(root: Path, conversation_id: str) -> dict[str, Any]:
    """Verification, review and done-claim rows straight from ``chat.db``."""

    conn = smoke._connect_db(root)
    try:
        verifications = [
            {
                "module_id": row["module_id"],
                "status": row["status"],
                "reason_code": row["reason_code"],
                "created_at": row["created_at"],
            }
            for row in conn.execute(
                "select module_id, status, "
                "json_extract(result_json, '$.reason_code') as reason_code, created_at "
                "from room_board_verifications where conversation_id = ? "
                "order by created_at, rowid",
                (conversation_id,),
            ).fetchall()
        ]
        try:
            reviews = [
                dict(row)
                for row in conn.execute(
                    "select module_id, status, author_family, reviewer_kind, reviewer_family, "
                    "created_at, updated_at from room_board_reviews "
                    "where conversation_id = ? order by created_at, rowid",
                    (conversation_id,),
                ).fetchall()
            ]
        except Exception:
            reviews = []
    finally:
        conn.close()
    return {"verifications": verifications, "reviews": reviews}


def start_module_memory_worker(root: Path) -> tuple[threading.Event, threading.Thread]:
    """Run the module memory worker on a thread, as the Chat API's own loop would.

    Requires an already running MemoryOS sidecar (``XMUSE_MEMORYOS_URL`` and
    ``XMUSE_MEMORYOS_API_KEY``) whose profile can curate (an LLM key on its side).
    """

    os.environ[MODULE_MEMORY_ENV] = "on"
    worker = compose_module_memory_worker(xmuse_root=root, environ=os.environ)
    if worker is None:
        raise RuntimeError(
            "--module-memory needs XMUSE_MEMORYOS_URL and XMUSE_MEMORYOS_API_KEY "
            "of a running MemoryOS sidecar"
        )
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                counts = worker.reconcile_once()
            except Exception as exc:  # pragma: no cover - logged and retried
                smoke._mark("module_memory_error", error=f"{type(exc).__name__}: {exc}")
            else:
                if counts.get("module_memory_windows"):
                    smoke._mark("module_memory_reconciled", **counts)
            stop.wait(10.0)

    thread = threading.Thread(target=_loop, name="module-memory-worker", daemon=True)
    thread.start()
    return stop, thread


def module_memory_summary(root: Path, conversation_id: str) -> dict[str, Any]:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        runs = conn.execute(
            "select status, count(*) as n from room_module_memory_runs "
            "where conversation_id = ? group by status",
            (conversation_id,),
        ).fetchall()
        memories = conn.execute(
            "select kind, status, count(*) as n from room_module_memories "
            "where conversation_id = ? group by kind, status",
            (conversation_id,),
        ).fetchall()
    return {
        "runs": {str(row["status"]): int(row["n"]) for row in runs},
        "memories": {f"{row['kind']}:{row['status']}": int(row["n"]) for row in memories},
    }


async def run_eval(
    *,
    root: Path,
    mcp_url: str,
    seed: Path,
    plan: Mapping[str, Any],
    profile_id: str,
    install: tuple[str, ...],
    lead_model: str,
    owner_model: str,
    reviewer: str,
    run_timeout_s: float,
    phase_timeout_s: float,
    max_turn_s: float,
    owner_cli: str = "opencode",
    agy_model: str = smoke.AGY_DEFAULT_MODEL,
    module_memory: bool = False,
    restart_owners: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    clis = module_owner_clis(plan, owner_cli)
    models = {"opencode": owner_model, "antigravity": agy_model}
    source = root / "source-repo"
    seed_head = prepare_source_repo(seed, source, install)
    # Every owner clone gets the same offline install before its first turn.
    os.environ[OWNER_PREPARE_COMMAND_ENV] = shlex.join(install)
    os.environ.setdefault(OWNER_PREPARE_TIMEOUT_ENV, "1800")
    RoomDatabase(root / "chat.db").initialize()

    modules = list(plan["modules"])
    roles = [f"{MODULE_ID_PREFIX}{module['module_id']}" for module in modules]
    participants = [
        ParticipantInit(role="lead", display_name="Lead", cli_kind="opencode", model=lead_model),
        *[
            ParticipantInit(
                role=role,
                display_name=f"Owner {module['module_id']}",
                cli_kind=clis[str(module["module_id"])],  # type: ignore[arg-type]
                model=models[clis[str(module["module_id"])]],
                workspace_access="workspace_write",
            )
            for role, module in zip(roles, modules, strict=True)
        ],
    ]
    if reviewer != "none":
        participants.append(reviewer_participant(reviewer, agy_model))
    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title=str(plan.get("title") or "Brownfield board eval"),
            client_request_id=f"brownfield-{uuid.uuid4().hex}",
            collaboration=RoomCollaborationInit(
                mode="addressed",
                lead_role="lead",
                review_policy="off" if reviewer == "none" else "cross_family",
            ),
            initial_participants=participants,
        )
    )
    conversation_id = str(setup["id"])
    stored = ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
    by_role: dict[str, Participant] = {item.role: item for item in stored}
    lead = by_role["lead"]
    owner_of = {
        str(module["module_id"]): by_role[role] for role, module in zip(roles, modules, strict=True)
    }
    smoke._mark("room_created", conversation_id=conversation_id, owners=len(owner_of))

    kernel = RoomKernelStore(root / "chat.db")
    controls = RoomObservationControlStore(root / "chat.db")
    decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    settings = smoke._resolve_owner_settings(
        root=root,
        source_repo=source,
        mcp_url=mcp_url,
        owner_model=owner_model,
        # agy owner settings are only resolved for an antigravity frontend; OpenCode
        # owners are always available, so a mixed room resolves the agy side too.
        frontend_cli="antigravity" if "antigravity" in clis.values() else "opencode",
        agy_model=agy_model,
    )
    created: list[RoomObservationTransport] = []
    inner_factory = build_owner_acp_transport_factory(
        settings,
        registry_path=root / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
    )

    def _factory(participant: Participant, clone: OwnerClone) -> RoomObservationTransport | None:
        transport = inner_factory(participant, clone)
        if transport is not None:
            created.append(transport)
        return transport

    readonly: dict[str, RoomObservationTransport] = {}
    lead_transport = AcpRoomObservationTransport(
        config=smoke._build_readonly_opencode_config(
            root=root, workspace=source, mcp_url=mcp_url, model=lead_model
        ),
        registry_path=root / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
    )
    readonly["opencode"] = lead_transport
    created.append(lead_transport)
    if reviewer == "claude":
        override = os.environ.get("XMUSE_CLAUDE_ACP_COMMAND", "").strip()
        claude_transport = AcpRoomObservationTransport(
            config=AcpTransportConfig(
                workspace=source,
                command=tuple(shlex.split(override)) if override else ROOM_ACP_DEFAULT_COMMAND,
                room_mcp_url=mcp_url,
                profile=CLAUDE_ACP_PROFILE,
            ),
            registry_path=root / "god_sessions.json",
            control_store=controls,
            skill_decision_store=decisions,
            stream_projector=projector,
        )
        readonly["claude"] = claude_transport
        created.append(claude_transport)
    elif reviewer == "antigravity":
        agy = resolve_agy_executable()
        agy_python3 = resolve_agy_python3()
        if agy is None or agy_python3 is None:
            raise RuntimeError("agy reviewer requested but agy or its python3 was not found")
        agy_transport = AgyRoomObservationTransport(
            config=_agy_config(
                root=root,
                worktree=source,
                room_mcp_url=mcp_url,
                agy_executable=agy,
                model=agy_model,
                bridge_script=Path(__file__).resolve().parents[1] / "xmuse" / "room_mcp_stdio.py",
                python3=agy_python3,
            ),
            registry_path=root / "god_sessions.json",
            control_store=controls,
            skill_decision_store=decisions,
            stream_projector=projector,
        )
        readonly["antigravity"] = agy_transport
        created.append(agy_transport)
    router = RoomOwnerTransportRouter(readonly, settings=settings, transport_factory=_factory)
    host = RoomParticipantHost(
        root / "chat.db",
        router,
        policy=RoomHostPolicy(
            delivery_timeout_s=smoke.DELIVERY_TIMEOUT_S,
            cleanup_grace_s=smoke.CLEANUP_GRACE_S,
            lease_ttl_s=smoke.LEASE_TTL_S,
            participant_cooldown_s=0.0,
        ),
        control_store=controls,
        skill_catalog=SkillCatalog.load_bundled(),
        skill_decision_store=decisions,
        long_turn_policy=LongTurnPolicy(
            renew_interval_s=5,
            lease_chunk_s=60,
            stall_timeout_s=600,
            max_turn_s=int(max_turn_s),
        ),
        long_turn_selector=lambda item: True,
    )

    phases: dict[str, Any] = {}
    stops: list[tuple[threading.Event, threading.Thread]] = []
    human_messages = 0
    try:
        await projector.start()
        stops.append(
            smoke._start_verification_worker(
                root=root, execution_root=source, execution_profile_id=profile_id
            )
        )
        stops.append(
            smoke._start_integration_worker(
                root=root, execution_root=source, execution_profile_id=profile_id
            )
        )
        if module_memory:
            stops.append(start_module_memory_worker(root))
        spec = build_split_spec(
            plan, {module_id: owner.participant_id for module_id, owner in owner_of.items()}
        )
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content=build_split_message(spec),
            client_request_id=f"brownfield-split-{uuid.uuid4().hex}",
            mentions=[lead.participant_id],
        )
        human_messages += 1
        split_idle = await smoke._pump_until_idle(
            host=host,
            kernel=kernel,
            conversation_id=conversation_id,
            timeout_s=phase_timeout_s,
            label="split",
            root=root,
        )
        split_ids = smoke._proposed_split_ids(root, conversation_id)
        phases["split"] = {"idle": split_idle, "proposed": len(split_ids)}
        if not (split_idle and len(split_ids) == 1):
            phases["stopped"] = "split_failed"
        else:
            application = RoomApplicationService(root / "chat.db", root / "god_sessions.json")
            application.board_decide_split(
                conversation_id=conversation_id,
                split_id=split_ids[0],
                decision="approve",
                operator_identity=smoke.OPERATOR_IDENTITY,
            )
            refresh_board_views(root, conversation_id)
            for module in modules:
                owner = owner_of[str(module["module_id"])]
                kernel.post_human_activity(
                    conversation_id=conversation_id,
                    human_id="human",
                    content=build_task_message(module),
                    client_request_id=f"brownfield-task-{uuid.uuid4().hex}",
                    mentions=[owner.participant_id],
                )
                human_messages += 1
            smoke._mark("tasks_sent", modules=len(modules))
            remaining = max(60.0, run_timeout_s - (time.monotonic() - started))
            work_idle = await smoke._pump_until_idle(
                host=host,
                kernel=kernel,
                conversation_id=conversation_id,
                timeout_s=remaining,
                label="work",
                root=root,
                wait_for_reviews=reviewer != "none",
                wait_for_integration=True,
            )
            phases["work"] = {"idle": work_idle}
            rounds = max((len(module.get("followups") or []) for module in modules), default=0)
            for round_index in range(rounds):
                if module_memory:
                    phases[f"memory_settle_{round_index + 1}"] = await settle_module_memory(root)
                followers = [
                    module for module in modules if len(module.get("followups") or []) > round_index
                ]
                restarted = []
                if restart_owners:
                    for module in followers:
                        if not followup_restarts(module["followups"][round_index]):
                            continue
                        owner = owner_of[str(module["module_id"])]
                        if await router.restart_owner(conversation_id, owner.participant_id):
                            restarted.append(str(module["module_id"]))
                for module in followers:
                    owner = owner_of[str(module["module_id"])]
                    kernel.post_human_activity(
                        conversation_id=conversation_id,
                        human_id="human",
                        content=build_followup_message(
                            module, followup_text(module["followups"][round_index])
                        ),
                        client_request_id=f"brownfield-followup-{uuid.uuid4().hex}",
                        mentions=[owner.participant_id],
                    )
                    human_messages += 1
                smoke._mark("followups_sent", round=round_index + 1, restarted=restarted)
                remaining = max(60.0, run_timeout_s - (time.monotonic() - started))
                followup_idle = await smoke._pump_until_idle(
                    host=host,
                    kernel=kernel,
                    conversation_id=conversation_id,
                    timeout_s=remaining,
                    label=f"followup-{round_index + 1}",
                    root=root,
                    wait_for_reviews=reviewer != "none",
                    wait_for_integration=True,
                )
                phases[f"followup_{round_index + 1}"] = {
                    "idle": followup_idle,
                    "restarted": restarted,
                }
    finally:
        for stop, thread in stops:
            smoke._stop_verification_worker(stop, thread)
        for transport in created:
            aclose = getattr(transport, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception as exc:  # pragma: no cover - best-effort cleanup
                    smoke._mark("transport_close_error", error=f"{type(exc).__name__}: {exc}")
        await projector.shutdown()

    module_states = smoke.board_module_states(root, conversation_id)
    rows = collect_board_rows(root, conversation_id)
    export = export_green_head(root, conversation_id)
    integrated = sorted(
        module_id
        for module_id, info in module_states.items()
        if info.get("integration_status") == "integrated"
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "profile_id": profile_id,
        "seed_head": seed_head,
        "reviewer": reviewer,
        "module_memory": module_memory_summary(root, conversation_id) if module_memory else None,
        "restart_owners": restart_owners,
        "owner_cli": owner_cli,
        "owner_clis": clis,
        "models": {
            "lead": lead_model,
            "owners": {cli: models[cli] for cli in sorted(set(clis.values()))},
            "reviewer": agy_model if reviewer == "antigravity" else None,
        },
        "phases": phases,
        "human_messages": human_messages,
        "modules": module_states,
        "integrated_modules": integrated,
        "all_integrated": bool(module_states) and len(integrated) == len(module_states),
        "verifications": rows["verifications"],
        "reviews": rows["reviews"],
        "integration_jobs": smoke._collect_integration_jobs(root, conversation_id),
        "green_head": export["green_head"],
        "result_repo": export["result_repo"],
        "export_reason": export["reason"],
        "wall_seconds": time.monotonic() - started,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, help="seed git repository (read-only source)")
    parser.add_argument("--plan", required=True, help="plan JSON (modules, paths, task text)")
    parser.add_argument("--root", required=True, help="run root (must not exist)")
    parser.add_argument("--result", required=True, help="summary JSON path")
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--install-command", default=DEFAULT_INSTALL_COMMAND)
    parser.add_argument("--lead-model", default=smoke.DEFAULT_LEAD_MODEL)
    parser.add_argument("--owner-model", default=smoke.DEFAULT_OWNER_MODEL)
    parser.add_argument("--owner-cli", choices=["opencode", "antigravity"], default="opencode")
    parser.add_argument("--agy-model", default=smoke.AGY_DEFAULT_MODEL)
    parser.add_argument("--reviewer", choices=["none", "claude", "antigravity"], default="none")
    parser.add_argument("--run-timeout-s", type=float, default=DEFAULT_RUN_TIMEOUT_S)
    parser.add_argument("--phase-timeout-s", type=float, default=smoke.DEFAULT_PHASE_TIMEOUT_S)
    parser.add_argument("--max-turn-s", type=float, default=3600.0)
    parser.add_argument(
        "--restart-owners",
        action="store_true",
        help="restart owners (fresh provider session, same clone) before follow-up rounds marked restart",
    )
    parser.add_argument(
        "--module-memory",
        action="store_true",
        help="curate module memory through the MemoryOS sidecar (XMUSE_MEMORYOS_URL/API_KEY)",
    )
    args = parser.parse_args(argv)
    try:
        lead_model = smoke.validate_model(args.lead_model)
        owner_model = smoke.validate_model(args.owner_model)
        agy_model = smoke.validate_agy_model(args.agy_model)
        profile = get_execution_gate_profile(args.profile)
        plan = load_plan(Path(args.plan))
        if args.reviewer in module_owner_clis(plan, args.owner_cli).values():
            raise ValueError(f"a {args.reviewer} reviewer cannot review {args.reviewer} owners")
    except ValueError as exc:
        print(f"brownfield eval unavailable: {exc}", flush=True)
        return 2
    root = Path(args.root)
    if root.exists():
        print(f"brownfield eval: root already exists: {root}", flush=True)
        return 2
    root.mkdir(parents=True)
    result_path = Path(args.result)
    with smoke._serve_room_mcp(root) as mcp_url:
        summary = asyncio.run(
            run_eval(
                root=root,
                mcp_url=mcp_url,
                seed=Path(args.seed).resolve(),
                plan=plan,
                profile_id=profile.profile_id,
                install=tuple(shlex.split(args.install_command)),
                lead_model=lead_model,
                owner_model=owner_model,
                reviewer=args.reviewer,
                owner_cli=args.owner_cli,
                agy_model=agy_model,
                run_timeout_s=args.run_timeout_s,
                phase_timeout_s=args.phase_timeout_s,
                max_turn_s=args.max_turn_s,
                module_memory=args.module_memory,
                restart_owners=args.restart_owners,
            )
        )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "all_integrated": summary["all_integrated"],
                "integrated": summary["integrated_modules"],
                "green_head": summary["green_head"],
                "result": str(result_path),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
