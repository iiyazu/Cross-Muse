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
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import board_owners_smoke as smoke  # noqa: E402
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
                "select module_id, status, reason_code, created_at "
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
) -> dict[str, Any]:
    started = time.monotonic()
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
                cli_kind="opencode",
                model=owner_model,
                workspace_access="workspace_write",
            )
            for role, module in zip(roles, modules, strict=True)
        ],
    ]
    if reviewer == "claude":
        participants.append(
            ParticipantInit(role="reviewer", display_name="Reviewer", cli_kind="claude")
        )
    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title=str(plan.get("title") or "Brownfield board eval"),
            client_request_id=f"brownfield-{uuid.uuid4().hex}",
            collaboration=RoomCollaborationInit(
                mode="addressed",
                lead_role="lead",
                review_policy="cross_family" if reviewer == "claude" else "off",
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
        frontend_cli="opencode",
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
    host = RoomParticipantHost(
        root / "chat.db",
        RoomOwnerTransportRouter(readonly, settings=settings, transport_factory=_factory),
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
                wait_for_reviews=reviewer == "claude",
                wait_for_integration=True,
            )
            phases["work"] = {"idle": work_idle}
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
        "models": {"lead": lead_model, "owners": owner_model},
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
    parser.add_argument("--reviewer", choices=["none", "claude"], default="none")
    parser.add_argument("--run-timeout-s", type=float, default=DEFAULT_RUN_TIMEOUT_S)
    parser.add_argument("--phase-timeout-s", type=float, default=smoke.DEFAULT_PHASE_TIMEOUT_S)
    parser.add_argument("--max-turn-s", type=float, default=3600.0)
    args = parser.parse_args(argv)
    try:
        lead_model = smoke.validate_model(args.lead_model)
        owner_model = smoke.validate_model(args.owner_model)
        profile = get_execution_gate_profile(args.profile)
        plan = load_plan(Path(args.plan))
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
                run_timeout_s=args.run_timeout_s,
                phase_timeout_s=args.phase_timeout_s,
                max_turn_s=args.max_turn_s,
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
