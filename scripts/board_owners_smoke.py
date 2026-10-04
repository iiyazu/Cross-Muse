#!/usr/bin/env python3
"""One-shot live smoke of board module ownership with host-verified completion.

This is not part of CI.  It builds a fresh temporary ``XMUSE_ROOT`` plus a
fresh temporary source git repository, serves the real Room MCP app on an
ephemeral loopback port, and drives three real agents (a read-only lead and
two ``workspace_write`` owners) through the durable Room host with a real
``RoomParticipantHost`` driving a ``RoomOwnerTransportRouter``.

A background thread runs the real ``RoomBoardVerificationWorker`` (the same
worker the Chat API runs) against the smoke's ``chat.db`` so every owner
``done`` report is verified with evidence while the smoke pumps deliveries.

Three scenarios are supported (``--scenario``); every summary carries
``verification_loop``, the organic claim -> verify -> rework measurement:

* ``revision`` (default): the lead proposes a two-module split, the script
  approves it as operator, both owners claim and implement their charters,
  then the backend owner publishes contract ``api.greeting`` v2 which wakes
  the dependent frontend owner; the frontend realigns in the same provider
  session.
* ``verify``: split and charters only.  It passes when every module ends
  host-verified and every verification wake-up reused the owner's session,
  whatever false claims happened on the way (those are the measurement).
* ``false-done``: split and charters proceed as above, then a Human drill
  message tells the backend owner to commit a contract-breaking stub and
  report ``done`` without running tests.  The host verification fails with
  gate evidence, wakes the owner in the same provider session, and the owner
  must fix and report ``done`` again until verification passes.  No further
  Human message is sent after the drill.  Observed 2026-10-04: OpenCode
  owners decline to sabotage their own module even when the drill is framed
  as an operator-authorized calibration, so ``verify`` is the measured path.

The script prints timed delivery evidence plus one JSON summary.  Agent child
processes are always terminated before exit.
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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
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
from xmuse_core.chat.room_board_verification import (
    BOARD_VERIFICATION_GATE_FAILED,
    RoomBoardVerificationWorker,
)
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_profiles import get_execution_gate_profile
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
    "src/api/greeting.py defines greet(name: str) -> dict returning "
    '{"message": "Hello, <name>!"}. '
    "src/client/render.py defines render(name: str) -> str that calls "
    "api.greeting.greet and returns the message."
)
CONTRACT_V2_CONTENT = (
    "src/api/greeting.py defines greet(name: str) -> dict returning "
    '{"message": ..., "lang": "en"}. '
    "src/client/render.py defines render(name: str) -> str that calls "
    'api.greeting.greet and returns "<message> [en]".'
)

ALLOWED_SCENARIOS = ("revision", "verify", "false-done", "review")
DEFAULT_SCENARIO = "revision"
# Smallest fixed profile whose gates run pytest on changed Python paths: the
# seed below satisfies its markers and local toolchain capability offline.
DEFAULT_EXECUTION_PROFILE_ID = "python-uv/v1"

SEED_PROJECT_NAME = "board-smoke-seed"
SEED_PYPROJECT_TOML = """\
[project]
name = "board-smoke-seed"
version = "0.1.0"
description = "Tiny verifiable seed for the board owners smoke"
requires-python = ">=3.11"
dependencies = [
    "packaging>=24",
]

[dependency-groups]
dev = [
    "mypy>=1.18",
    "pytest>=9.0.3",
    "ruff>=0.15.12",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/api", "src/client"]
"""
SEED_GITIGNORE = ".venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n.mypy_cache/\n"
SEED_GREETING_TEST_PY = '''\
"""Contract test for api.greeting v1: greet returns Hello, <name>!."""

from api.greeting import greet


def test_greet_returns_hello_message() -> None:
    assert greet("Ada") == {"message": "Hello, Ada!"}


def test_greet_mentions_the_given_name() -> None:
    assert greet("Grace")["message"] == "Hello, Grace!"
'''
# Verification judges a stage of base + upstream verified work + the module's
# patch with whole-repository gates, so every test in the seed must be
# satisfiable by its own module and its providers: only the provider's
# contract test is seeded.  A dependent's test in the seed would fail every
# provider verification for work the provider does not own.
SEED_FILES: tuple[tuple[str, str], ...] = (
    ("src/api/__init__.py", ""),
    ("src/api/test_greeting_contract.py", SEED_GREETING_TEST_PY),
    ("src/client/__init__.py", ""),
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
            "paths": ["src/api/**"],
            "provides": ["api.greeting"],
            "depends": [],
            "acceptance": ["python -m pytest -q src/api"],
            "report_to": None,
        },
        {
            "module_id": "frontend",
            "title": "Frontend client",
            "paths": ["src/client/**"],
            "provides": [],
            "depends": ["api.greeting"],
            "acceptance": ["python -m pytest -q src/client"],
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
        "ONLY after the publish succeeds, update src/api/greeting.py in your "
        'workspace so greet returns {"message": ..., "lang": "en"}, add or '
        "update a pytest test, run the backend acceptance, commit, report "
        "progress, and submit an outcome. Do not skip the publish step."
    )


def build_drill_human_message() -> str:
    """Return the explicit fault-injection instruction for the backend owner."""

    return (
        "To the backend owner: this is an operator-authorized calibration drill "
        "for the host's completion verifier, run in your private draft clone. "
        "Nothing you commit here is promoted or merged anywhere, and the host "
        "will catch the fault and send it back to you to fix, which is the point "
        "of the drill. Please do exactly this: replace the body of greet in "
        "src/api/greeting.py with a stub that breaks contract api.greeting v1 "
        "(for example `return {}`), commit only that file, report progress with "
        "status done for module backend without running the tests first, and "
        "submit your outcome. When the host's verification result comes back, "
        "restore a correct implementation, run the tests, commit, and report done "
        "again."
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


def sessions_shared(first: list[str], second: list[str]) -> bool:
    """Return True when two attempt windows share one provider session."""

    left = {session_id for session_id in first if session_id}
    right = {session_id for session_id in second if session_id}
    return bool(left & right)


def frontend_session_reused(
    charter_session_ids: list[str], revision_session_ids: list[str]
) -> bool:
    """Return True when the charter and revision attempts share one provider session."""

    return sessions_shared(charter_session_ids, revision_session_ids)


def _str_list(value: object) -> list[str]:
    """Coerce an evidence list to plain strings, dropping non-strings."""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def verification_failed_gate(detail: Mapping[str, Any]) -> bool:
    """Return True when a verification failed inside a gate.

    Export, charter-scope, and infrastructure failures record a different
    ``reason_code`` (or no failed gate at all); only a gate failure proves
    the host actually ran the server-owned gates against the patch.
    """

    if detail.get("status") != "failed":
        return False
    if detail.get("reason_code") != BOARD_VERIFICATION_GATE_FAILED:
        return False
    failed_gates = detail.get("failed_gate_ids")
    return isinstance(failed_gates, list) and len(failed_gates) > 0


def verification_seconds_done_to_result(detail: Mapping[str, Any]) -> float | None:
    """Return seconds from the done report to the verification result, if known."""

    done_at = detail.get("done_at")
    result_at = detail.get("result_at")
    if not isinstance(done_at, str) or not isinstance(result_at, str):
        return None
    try:
        start = datetime.fromisoformat(done_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(result_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - start).total_seconds()


def summarize_module_verifications(details: list[dict[str, Any]]) -> dict[str, int]:
    """Summarize one module's verification history with projection semantics.

    Counters mirror ``RoomBoardStore`` projection stats: only ``passed`` and
    ``failed`` rows count, and ``rework_rounds`` is the number of failures
    before the first pass (or all failures when nothing passed yet).
    """

    passed = sum(1 for item in details if item.get("status") == "passed")
    failed = sum(1 for item in details if item.get("status") == "failed")
    first_pass = next(
        (index for index, item in enumerate(details) if item.get("status") == "passed"),
        None,
    )
    if first_pass is None:
        rework_rounds = failed
    else:
        rework_rounds = sum(1 for item in details[:first_pass] if item.get("status") == "failed")
    return {
        "verifications_passed": passed,
        "verifications_failed": failed,
        "rework_rounds": rework_rounds,
    }


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


def compute_false_done_checks(evidence: Mapping[str, Any]) -> dict[str, bool]:
    """Compute the M1 false-done checks over the drill-window verifications.

    The window holds backend verifications created after the drill Human
    message (earliest first): the drill's ``done`` must fail in a gate, the
    failure must wake the owner, the woken attempt must reuse the drill
    provider session, and the latest window verification must pass.
    """

    raw = evidence.get("backend_drill_verifications")
    drills: list[Any] = list(raw) if isinstance(raw, list) else []
    first_failed = len(drills) > 0 and verification_failed_gate(drills[0])
    last = drills[-1] if drills else None
    last_passed = last is not None and last.get("status") == "passed"
    return {
        "first_verification_failed": bool(first_failed),
        "owner_woken_by_verification": bool(evidence.get("backend_woken_by_verification")),
        "owner_session_reused": sessions_shared(
            _str_list(evidence.get("backend_drill_session_ids")),
            _str_list(evidence.get("backend_woken_session_ids")),
        ),
        "final_verification_passed": bool(last_passed),
    }


def false_done_ok(evidence: Mapping[str, Any]) -> bool:
    """Return the final ``ok`` verdict for false-done evidence."""

    return all(compute_false_done_checks(evidence).values())


def compute_verification_loop(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Measure the organic claim -> verify -> rework loop of one run.

    Per module: ``done`` claims, whether the first verification passed, false
    claims (a verification that failed in a gate), whether the module ends
    verified, and whether every verification wake-up reused the session the
    owner had during its charter turn.  Totals sum the modules.
    """

    raw_modules = evidence.get("module_verifications")
    modules = raw_modules if isinstance(raw_modules, Mapping) else {}
    raw_participants = evidence.get("participants")
    participants = raw_participants if isinstance(raw_participants, Mapping) else {}
    per_module: dict[str, dict[str, Any]] = {}
    for module_id, info in sorted(modules.items()):
        details = info.get("verifications") if isinstance(info, Mapping) else None
        rows = [item for item in details or [] if isinstance(item, Mapping)]
        terminal = [item for item in rows if item.get("status") in ("passed", "failed")]
        observations = []
        participant = participants.get(module_id)
        if isinstance(participant, Mapping):
            observations = [
                item for item in participant.get("observations") or [] if isinstance(item, Mapping)
            ]
        charter_sessions = {
            session
            for item in observations
            if item.get("source_activity_type") == "board.charter_assigned"
            for session in _str_list(item.get("provider_session_ids"))
        }
        woken = [
            item
            for item in observations
            if item.get("source_activity_type") == "board.verification"
        ]
        per_module[str(module_id)] = {
            "claims": int(info.get("done_reports") or 0) if isinstance(info, Mapping) else 0,
            "first_try_pass": bool(terminal) and terminal[0].get("status") == "passed",
            "false_claims": sum(1 for item in rows if verification_failed_gate(item)),
            "verified": bool(terminal) and terminal[-1].get("status") == "passed",
            "wakes": len(woken),
            "wakes_reused_session": all(
                sessions_shared(
                    sorted(charter_sessions), _str_list(item.get("provider_session_ids"))
                )
                for item in woken
            ),
        }
    return {
        "modules": per_module,
        "claims": sum(item["claims"] for item in per_module.values()),
        "first_try_passes": sum(1 for item in per_module.values() if item["first_try_pass"]),
        "false_claims": sum(item["false_claims"] for item in per_module.values()),
        "all_verified": bool(per_module) and all(item["verified"] for item in per_module.values()),
        "wakes_reused_session": all(item["wakes_reused_session"] for item in per_module.values()),
    }


def compute_verify_checks(evidence: Mapping[str, Any]) -> dict[str, bool]:
    """Checks for the ``verify`` scenario: every module ends host-verified and
    every verification wake-up stayed in the owner's session."""
    loop = compute_verification_loop(evidence)
    return {
        "all_modules_verified": bool(loop["all_verified"]),
        "wakes_reused_session": bool(loop["wakes_reused_session"]),
    }


def compute_review_loop(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Measure the verify -> review -> fix loop of one run.

    Per module: reviews created, endorsed, objected, whether the module ends
    endorsed, and whether every objection was followed by a newer done report
    (a fix cycle).  Totals sum the modules.
    """

    raw_modules = evidence.get("module_reviews")
    modules = raw_modules if isinstance(raw_modules, Mapping) else {}
    raw_verifications = evidence.get("module_verifications")
    verifications = raw_verifications if isinstance(raw_verifications, Mapping) else {}
    per_module: dict[str, dict[str, Any]] = {}
    for module_id, info in sorted(modules.items()):
        details = info.get("reviews") if isinstance(info, Mapping) else None
        rows = [item for item in details or [] if isinstance(item, Mapping)]
        terminal = [item for item in rows if item.get("status") in ("endorsed", "objected")]
        vinfo = verifications.get(module_id) if isinstance(verifications, Mapping) else None
        vdetails = vinfo.get("verifications") if isinstance(vinfo, Mapping) else None
        vrows = [item for item in vdetails or [] if isinstance(item, Mapping)]
        done_reports = int(info.get("done_reports") or 0) if isinstance(info, Mapping) else 0
        objections = [item for item in rows if item.get("status") == "objected"]
        objections_fixed = True
        for item in objections:
            verdict_at = item.get("verdict_at")
            followed = any(
                isinstance(vrow.get("done_at"), str)
                and isinstance(verdict_at, str)
                and str(vrow.get("done_at")) > str(verdict_at)
                for vrow in vrows
            )
            if not followed:
                # The latest objection may still be awaiting its fix; only an
                # objection that is not the latest review needs a successor.
                is_latest = rows and rows[-1].get("review_id") == item.get("review_id")
                if not is_latest:
                    objections_fixed = False
                    break
                # A latest objection with no newer done is not yet fixed.
                objections_fixed = False
                break
        if not objections:
            objections_fixed = True
        per_module[str(module_id)] = {
            "reviews": len(rows),
            "endorsed": sum(1 for item in rows if item.get("status") == "endorsed"),
            "objected": len(objections),
            "pending": sum(1 for item in rows if item.get("status") == "pending"),
            "endorsed_final": bool(terminal) and terminal[-1].get("status") == "endorsed",
            "objections_fixed": objections_fixed,
            "done_reports": done_reports,
        }
    return {
        "modules": per_module,
        "reviews": sum(item["reviews"] for item in per_module.values()),
        "endorsed": sum(item["endorsed"] for item in per_module.values()),
        "objected": sum(item["objected"] for item in per_module.values()),
        "objections_fixed": all(item["objections_fixed"] for item in per_module.values()),
        "all_endorsed": bool(per_module)
        and all(item["endorsed_final"] for item in per_module.values()),
    }


def compute_review_checks(evidence: Mapping[str, Any]) -> dict[str, bool]:
    """Checks for the ``review`` scenario."""

    loop = compute_review_loop(evidence)
    verify = compute_verification_loop(evidence)
    raw_modules = evidence.get("module_reviews")
    modules = raw_modules if isinstance(raw_modules, Mapping) else {}
    cross_family = True
    for _module_id, info in modules.items():
        details = info.get("reviews") if isinstance(info, Mapping) else None
        for item in details or []:
            if not isinstance(item, Mapping):
                continue
            if item.get("status") == "superseded":
                continue
            author_family = item.get("author_family")
            reviewer_family = item.get("reviewer_family")
            reviewer_kind = item.get("reviewer_kind")
            if reviewer_kind == "operator":
                continue
            if (
                not isinstance(author_family, str)
                or not isinstance(reviewer_family, str)
                or not author_family
                or author_family == reviewer_family
            ):
                cross_family = False
    return {
        "all_modules_verified": bool(verify["all_verified"]),
        "all_modules_endorsed": bool(loop["all_endorsed"]),
        "reviewers_cross_family": bool(cross_family and loop["reviews"] > 0),
        "objections_fixed": bool(loop["objections_fixed"]),
    }


def review_ok(evidence: Mapping[str, Any]) -> bool:
    """Return the final ``ok`` verdict for review evidence."""

    return all(compute_review_checks(evidence).values())


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


def _run_uv(args: list[str], *, cwd: Path) -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv executable not found for the board smoke seed")
    result = subprocess.run(
        [uv, *args],
        cwd=str(cwd),
        env={**os.environ, "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
        timeout=300.0,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RuntimeError(f"uv {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _check_seed_toolchain(path: Path) -> None:
    """Fail fast when the seed venv cannot satisfy the execution profile."""

    venv = path / ".venv"
    missing = [
        name for name in ("bin/python3", "bin/ruff", "pyvenv.cfg") if not (venv / name).is_file()
    ]
    site_packages: Path | None = None
    if not missing:
        candidates = tuple(
            entry for entry in (venv / "lib").glob("python*/site-packages") if entry.is_dir()
        )
        if len(candidates) != 1:
            missing.append("lib/python*/site-packages")
        else:
            site_packages = candidates[0]
    if site_packages is not None:
        for name in ("mypy", "pytest"):
            matches = sorted(site_packages.glob(f"{name}-*.dist-info/METADATA"))
            if len(matches) != 1:
                missing.append(f"lib/python*/site-packages/{name}-*.dist-info/METADATA")
    if missing:
        raise RuntimeError(
            "board smoke seed toolchain incomplete for "
            f"{DEFAULT_EXECUTION_PROFILE_ID}: missing {sorted(missing)}"
        )


def _create_source_repo(path: Path) -> str:
    """Create the verifiable seed repository for ``python-uv/v1``.

    The seed is a minimal ``src/``-layout Python project (the only layout the
    profile's path policy covers) with a contract test the backend module
    must satisfy.  Markers (``pyproject.toml`` + ``uv.lock`` with an editable
    root package) and the local toolchain capability (``.venv`` with the
    ``ruff`` binary and ``mypy``/``pytest`` distributions) are built fully
    offline via ``uv lock --offline`` / ``uv sync --offline`` from the local
    uv cache, so the host verification worker can run the server-owned gates
    without network access.
    """

    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init"], cwd=path)
    _run_git(["config", "user.name", "smoke owner"], cwd=path)
    _run_git(["config", "user.email", "smoke-owner@example.com"], cwd=path)
    _run_git(["config", "commit.gpgsign", "false"], cwd=path)
    (path / "README.md").write_text("# board smoke source\n", encoding="utf-8")
    (path / ".gitignore").write_text(SEED_GITIGNORE, encoding="utf-8")
    (path / "pyproject.toml").write_text(SEED_PYPROJECT_TOML, encoding="utf-8")
    for relative, content in SEED_FILES:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _run_uv(["lock", "--offline"], cwd=path)
    _run_git(
        [
            "add",
            "README.md",
            ".gitignore",
            "pyproject.toml",
            "uv.lock",
            *[relative for relative, _content in SEED_FILES],
        ],
        cwd=path,
    )
    _run_git(["commit", "-m", "initial"], cwd=path)
    _run_uv(["sync", "--offline", "--locked"], cwd=path)
    _check_seed_toolchain(path)
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


def _start_verification_worker(
    *, root: Path, execution_root: Path, execution_profile_id: str
) -> tuple[threading.Event, threading.Thread]:
    """Start the real board verification worker on a background thread.

    The smoke does not start the Chat API, so it runs
    ``RoomBoardVerificationWorker(...).reconcile_once()`` itself every ~1 s
    until the smoke ends.  Blocking git/gate work stays off the pump event
    loop, exactly as the Chat API's ``asyncio.to_thread`` offload does.
    """

    worker = RoomBoardVerificationWorker(
        db_path=root / "chat.db",
        clones_root=root / "runtime" / "owner-clones",
        xmuse_root=root,
        execution_root=execution_root,
        execution_profile_id=execution_profile_id,
    )
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                result = worker.reconcile_once()
            except Exception as exc:
                _mark("board_verification_error", error=f"{type(exc).__name__}: {exc}")
            else:
                if result.get("board_verifications_claimed"):
                    _mark("board_verification_reconciled", **result)
            stop.wait(1.0)

    thread = threading.Thread(target=_loop, name="board-verification", daemon=True)
    thread.start()
    _mark("board_verification_worker_started", profile_id=execution_profile_id)
    return stop, thread


def _stop_verification_worker(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=30.0)
    _mark("board_verification_worker_stopped", alive=thread.is_alive())


def _has_active_verifications(root: Path, conversation_id: str) -> bool:
    conn = _connect_db(root)
    try:
        row = conn.execute(
            "select count(*) as total from room_board_verifications "
            "where conversation_id = ? and status in ('pending', 'running')",
            (conversation_id,),
        ).fetchone()
        return int(row["total"]) > 0
    finally:
        conn.close()


def _has_pending_reviews(root: Path, conversation_id: str) -> bool:
    conn = _connect_db(root)
    try:
        try:
            row = conn.execute(
                "select count(*) as total from room_board_reviews "
                "where conversation_id = ? and status = 'pending'",
                (conversation_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        return int(row["total"]) > 0
    finally:
        conn.close()


def _verification_ids(root: Path, conversation_id: str) -> set[str]:
    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select verification_id from room_board_verifications where conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        return {str(row["verification_id"]) for row in rows}
    finally:
        conn.close()


async def _pump_until_idle(
    *,
    host: RoomParticipantHost,
    kernel: RoomKernelStore,
    conversation_id: str,
    timeout_s: float,
    label: str,
    root: Path,
    wait_for_reviews: bool = False,
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
        if (
            _is_idle(kernel, conversation_id)
            and not _has_active_verifications(root, conversation_id)
            and not (wait_for_reviews and _has_pending_reviews(root, conversation_id))
        ):
            await asyncio.sleep(IDLE_SETTLE_S)
            if (
                _is_idle(kernel, conversation_id)
                and not _has_active_verifications(root, conversation_id)
                and not (wait_for_reviews and _has_pending_reviews(root, conversation_id))
            ):
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


TERMINAL_VERIFICATION_STATUSES = ("passed", "failed", "error")


def _collect_verification_rows(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    """Return joined verification/progress rows ordered oldest first."""

    conn = _connect_db(root)
    try:
        rows = conn.execute(
            "select v.verification_id, v.module_id, v.status, v.created_at, "
            "v.updated_at, v.result_json, p.created_at as done_at "
            "from room_board_verifications v left join room_board_progress p "
            "on p.progress_id = v.progress_id "
            "where v.conversation_id = ? order by v.created_at, v.verification_id",
            (conversation_id,),
        ).fetchall()
        collected: list[dict[str, Any]] = []
        for row in rows:
            result: Any = None
            if row["result_json"]:
                try:
                    result = json.loads(str(row["result_json"]))
                except ValueError:
                    result = None
            collected.append(
                {
                    "verification_id": str(row["verification_id"]),
                    "module_id": str(row["module_id"]),
                    "status": str(row["status"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
                    "result": result,
                    "done_at": str(row["done_at"]) if row["done_at"] else None,
                }
            )
        return collected
    finally:
        conn.close()


def build_verification_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build one per-verification evidence entry from a joined row.

    The entry carries ``(status, reason_code, failed gate ids, seconds from
    done report to result)``; pending/running rows have no result yet.
    """

    status = str(row.get("status"))
    result_raw = row.get("result")
    result: dict[str, Any] = dict(result_raw) if isinstance(result_raw, Mapping) else {}
    gates_raw = result.get("gates")
    gates: list[Any] = list(gates_raw) if isinstance(gates_raw, list) else []
    failed_gate_ids = [
        str(gate.get("gate_id"))
        for gate in gates
        if isinstance(gate, Mapping)
        and isinstance(gate.get("gate_id"), str)
        and gate.get("status") != "passed"
    ]
    reason_code = result.get("reason_code")
    done_at = row.get("done_at") or row.get("created_at")
    updated_at = row.get("updated_at")
    detail: dict[str, Any] = {
        "verification_id": str(row.get("verification_id")),
        "module_id": str(row.get("module_id")),
        "status": status,
        "reason_code": str(reason_code) if isinstance(reason_code, str) else None,
        "failed_gate_ids": failed_gate_ids,
        "done_at": str(done_at) if isinstance(done_at, str) else None,
        "result_at": (
            str(updated_at)
            if status in TERMINAL_VERIFICATION_STATUSES and isinstance(updated_at, str)
            else None
        ),
        "done_to_result_s": None,
    }
    detail["done_to_result_s"] = verification_seconds_done_to_result(detail)
    return detail


def build_module_verification_summary(
    *, module_id: str, details: list[dict[str, Any]], done_reports: int
) -> dict[str, Any]:
    """Summarize one module's verifications with projection counters."""

    summary: dict[str, Any] = {
        "module_id": module_id,
        "done_reports": done_reports,
        **summarize_module_verifications(details),
        "verifications": details,
    }
    return summary


def build_review_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build one per-review evidence entry from a joined review row."""

    return {
        "review_id": str(row.get("review_id")),
        "module_id": str(row.get("module_id")),
        "verification_id": str(row.get("verification_id")),
        "status": str(row.get("status")),
        "author_participant_id": str(row.get("author_participant_id")),
        "author_family": row.get("author_family"),
        "reviewer_kind": str(row.get("reviewer_kind")),
        "reviewer_participant_id": row.get("reviewer_participant_id"),
        "reviewer_family": row.get("reviewer_family"),
        "created_at": str(row.get("created_at")),
        "verdict_at": row.get("updated_at"),
    }


def _collect_module_reviews(
    root: Path, conversation_id: str, done_reports: Mapping[str, int]
) -> dict[str, dict[str, Any]]:
    """Collect per-module review histories ordered oldest first."""

    conn = _connect_db(root)
    try:
        try:
            rows = conn.execute(
                "select review_id, module_id, verification_id, status, "
                "author_participant_id, author_family, reviewer_kind, "
                "reviewer_participant_id, reviewer_family, created_at, updated_at "
                "from room_board_reviews where conversation_id = ? "
                "order by created_at, review_id",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        grouped: dict[str, list[dict[str, Any]]] = {
            "backend": [],
            "frontend": [],
        }
        for row in rows:
            detail = build_review_detail(dict(row))
            if detail["module_id"] in grouped:
                grouped[detail["module_id"]].append(detail)
        return {
            module_id: {
                "module_id": module_id,
                "done_reports": int(done_reports.get(module_id, 0)),
                "reviews": details,
            }
            for module_id, details in grouped.items()
        }
    finally:
        conn.close()


def _collect_evidence(
    *,
    root: Path,
    conversation_id: str,
    by_role: dict[str, Participant],
    drill: dict[str, Any] | None = None,
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
        for name in ("src/api/greeting.py", "src/client/render.py"):
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
    render_text = (clones["frontend"]["files"] or {}).get("src/client/render.py") or ""
    verification_rows = _collect_verification_rows(root, conversation_id)
    details_by_module: dict[str, list[dict[str, Any]]] = {
        "backend": [],
        "frontend": [],
    }
    for row in verification_rows:
        if row["module_id"] in details_by_module:
            details_by_module[row["module_id"]].append(build_verification_detail(row))
    done_reports = {
        module_id: sum(
            1 for item in progress if item["module_id"] == module_id and item["status"] == "done"
        )
        for module_id in ("backend", "frontend")
    }
    module_verifications = {
        module_id: build_module_verification_summary(
            module_id=module_id,
            details=details_by_module[module_id],
            done_reports=done_reports[module_id],
        )
        for module_id in ("backend", "frontend")
    }
    module_reviews = _collect_module_reviews(root, conversation_id, done_reports)
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
        "module_verifications": module_verifications,
        "module_reviews": module_reviews,
    }
    evidence["frontend_session_reused"] = frontend_session_reused(
        charter_sessions, revision_sessions
    )
    if drill is not None:
        pre_ids = drill.get("pre_verification_ids")
        known: set[str] = set(pre_ids) if isinstance(pre_ids, set) else set()
        window = [
            item
            for item in details_by_module["backend"]
            if str(item["verification_id"]) not in known
        ]
        drill_observation_ids = _str_list(drill.get("drill_observation_ids"))
        drill_sessions: list[str] = []
        for observation_id in drill_observation_ids:
            drill_sessions.extend(
                _attempt_provider_sessions(
                    root, conversation_id, backend.participant_id, observation_id
                )
            )
        woken_sessions: list[str] = []
        woken = False
        for entry in participants["backend"]["observations"]:
            if (
                entry["source_activity_type"] == "board.verification"
                and entry["status"] == "completed"
            ):
                woken = True
                woken_sessions.extend(_str_list(entry["provider_session_ids"]))
        evidence["backend_drill_verifications"] = window
        evidence["backend_woken_by_verification"] = woken
        evidence["backend_drill_session_ids"] = drill_sessions
        evidence["backend_woken_session_ids"] = woken_sessions
        evidence["backend_rework_rounds"] = module_verifications["backend"]["rework_rounds"]
    return evidence


async def _run_drill_phase(
    *,
    host: RoomParticipantHost,
    kernel: RoomKernelStore,
    root: Path,
    conversation_id: str,
    backend_id: str,
    phase_timeout_s: float,
    phases_ok: bool,
) -> dict[str, Any]:
    """Run the false-done fault-injection drill after the charter phase.

    Posts the drill Human message (no further Human message follows in this
    phase: the fix must be driven only by the host's ``board.verification``
    wake-up), then pumps until observations are idle and no verification is
    pending or running.  The drill's ``done`` must fail verification, the
    failure wakes the owner, and the owner's fix must pass a second
    verification.
    """

    drill: dict[str, Any] = {
        "phase_ok": False,
        "pre_verification_ids": set(),
        "drill_observation_ids": [],
    }
    if not phases_ok:
        _mark("drill_skipped", reason="earlier phase failed")
        return drill
    pre_ids = _verification_ids(root, conversation_id)
    posted = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content=build_drill_human_message(),
        client_request_id=f"board-owners-smoke-drill-{uuid.uuid4().hex}",
        mentions=[backend_id],
    )
    observations = posted.get("observations") if isinstance(posted, dict) else None
    drill_observation_ids = (
        [
            str(item.get("observation_id"))
            for item in observations
            if isinstance(item, dict) and item.get("observation_id")
        ]
        if isinstance(observations, list)
        else []
    )
    drill["pre_verification_ids"] = pre_ids
    drill["drill_observation_ids"] = drill_observation_ids
    _mark("drill_requested", backend_id=backend_id, observations=drill_observation_ids)
    drill_idle = await _pump_until_idle(
        host=host,
        kernel=kernel,
        conversation_id=conversation_id,
        timeout_s=phase_timeout_s,
        label="drill",
        root=root,
    )
    window = [
        row
        for row in _collect_verification_rows(root, conversation_id)
        if row["module_id"] == "backend" and row["verification_id"] not in pre_ids
    ]
    terminal = [row for row in window if row["status"] in TERMINAL_VERIFICATION_STATUSES]
    drill_ok = drill_idle and len(terminal) >= 2
    _mark(
        "drill_phase",
        idle=drill_idle,
        window=[{"id": row["verification_id"], "status": row["status"]} for row in window],
        ok=drill_ok,
    )
    drill["phase_ok"] = drill_ok
    return drill


async def _run_smoke(
    *,
    root: Path,
    mcp_url: str,
    lead_model: str,
    owner_model: str,
    frontend_cli: str,
    agy_model: str,
    phase_timeout_s: float,
    scenario: str,
    execution_profile_id: str,
) -> int:
    source_repo = root / "source-repo"
    if scenario == "review" and frontend_cli == "opencode":
        print(
            "board smoke review unavailable: the two owners must be of different "
            "families (backend is opencode; rerun with --frontend-cli claude or "
            "antigravity)",
            flush=True,
        )
        return 2
    try:
        _create_source_repo(source_repo)
    except RuntimeError as exc:
        print(f"board smoke unavailable: {exc}", flush=True)
        return 2
    _mark(
        "root",
        path=str(root),
        lead_model=lead_model,
        owner_model=owner_model,
        frontend_cli=frontend_cli,
        scenario=scenario,
        execution_profile_id=execution_profile_id,
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
    verification_stop: threading.Event | None = None
    verification_thread: threading.Thread | None = None
    drill: dict[str, Any] | None = None
    try:
        await projector.start()
        verification_stop, verification_thread = _start_verification_worker(
            root=root,
            execution_root=source_repo,
            execution_profile_id=execution_profile_id,
        )
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
            root=root,
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
                root=root,
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

        # Phase 3 (revision): backend revises the contract; the frontend
        # must realign.
        if scenario == "review":
            if phases_ok:
                review_idle = await _pump_until_idle(
                    host=host,
                    kernel=kernel,
                    conversation_id=conversation_id,
                    timeout_s=phase_timeout_s,
                    label="review",
                    root=root,
                    wait_for_reviews=True,
                )
                pending = _has_pending_reviews(root, conversation_id)
                review_ok_phase = review_idle and not pending
                _mark(
                    "review_phase",
                    idle=review_idle,
                    pending_reviews=pending,
                    ok=review_ok_phase,
                )
                phases_ok = phases_ok and review_ok_phase
            else:
                _mark("review_skipped", reason="earlier phase failed")
        elif scenario == "false-done":
            drill = await _run_drill_phase(
                host=host,
                kernel=kernel,
                root=root,
                conversation_id=conversation_id,
                backend_id=backend.participant_id,
                phase_timeout_s=phase_timeout_s,
                phases_ok=phases_ok,
            )
            phases_ok = phases_ok and bool(drill["phase_ok"])
        elif scenario == "revision" and phases_ok:
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
                root=root,
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
        elif scenario == "revision":
            _mark("revise_skipped", reason="earlier phase failed")
    finally:
        if verification_stop is not None and verification_thread is not None:
            _stop_verification_worker(verification_stop, verification_thread)
        for created_transport in created:
            aclose = getattr(created_transport, "aclose", None)
            if callable(aclose):
                await aclose()
        await host.shutdown()
        await projector.shutdown()

    evidence = _collect_evidence(
        root=root,
        conversation_id=conversation_id,
        by_role=by_role,
        drill=drill if scenario == "false-done" else None,
    )
    if scenario == "false-done":
        checks: dict[str, bool] = compute_false_done_checks(evidence)
        smoke_ok = phases_ok and false_done_ok(evidence)
        summary = {
            "ok": smoke_ok,
            "scenario": scenario,
            "checks": checks,
            "phases_ok": phases_ok,
            "backend_rework_rounds": evidence.get("backend_rework_rounds"),
            "owner_session_reused": checks["owner_session_reused"],
            "verification_loop": compute_verification_loop(evidence),
            "conversation_id": conversation_id,
            "evidence": evidence,
        }
    elif scenario == "verify":
        checks = compute_verify_checks(evidence)
        summary = {
            "ok": phases_ok and all(checks.values()),
            "scenario": scenario,
            "checks": checks,
            "phases_ok": phases_ok,
            "verification_loop": compute_verification_loop(evidence),
            "conversation_id": conversation_id,
            "evidence": evidence,
        }
    elif scenario == "review":
        checks = compute_review_checks(evidence)
        review_loop = compute_review_loop(evidence)
        summary = {
            "ok": phases_ok and all(checks.values()),
            "scenario": scenario,
            "checks": checks,
            "phases_ok": phases_ok,
            "verification_loop": compute_verification_loop(evidence),
            "review_loop": review_loop,
            "conversation_id": conversation_id,
            "evidence": evidence,
        }
    else:
        checks = compute_board_smoke_checks(evidence)
        summary = {
            "ok": phases_ok and board_smoke_ok(evidence),
            "scenario": scenario,
            "checks": checks,
            "phases_ok": phases_ok,
            "frontend_session_reused": evidence["frontend_session_reused"],
            "verification_loop": compute_verification_loop(evidence),
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
    parser.add_argument("--scenario", choices=list(ALLOWED_SCENARIOS), default=DEFAULT_SCENARIO)
    parser.add_argument("--execution-profile", default=DEFAULT_EXECUTION_PROFILE_ID)
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
        execution_profile = get_execution_gate_profile(args.execution_profile)
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
                    scenario=args.scenario,
                    execution_profile_id=execution_profile.profile_id,
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
