from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import shlex
import struct
import subprocess
import termios
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.platform.dashboard_details import _conversation_runtime_timeline_detail
from xmuse_core.runtime.paths import XMUSE_ROOT_ENV


@dataclass(frozen=True)
class TerminalCommandResult:
    exit_code: int
    output: str = ""


@dataclass(frozen=True)
class TerminalTuiDemoResult:
    written: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    missing_surfaces: list[str] = field(default_factory=list)


TerminalRunner = Callable[[Sequence[str], dict[str, str], float], TerminalCommandResult]

_REQUIRED_VISIBLE_SURFACES = (
    "init",
    "overview",
    "discussion",
    "blockers",
    "dispatch",
    "provider_writeback",
    "resume",
)
TERMINAL_TUI_DEMO_EVIDENCE_SOURCE = "xmuse_tui_terminal_demo_harness"
TERMINAL_TUI_DEMO_HARNESS_VERSION = 1


def record_terminal_tui_demo_evidence(
    *,
    xmuse_root: Path | str,
    conversation_id: str,
    command: str,
    exit_code: int,
    started_at: str,
    completed_at: str,
    terminal_run_id: str | None = None,
) -> TerminalTuiDemoResult:
    root = Path(xmuse_root)
    clean_conversation_id = conversation_id.strip()
    return _record_terminal_tui_demo_evidence_from_surfaces(
        root=root,
        conversation_id=clean_conversation_id,
        command=command,
        exit_code=exit_code,
        started_at=started_at,
        completed_at=completed_at,
        terminal_run_id=terminal_run_id or "",
        command_events=_persisted_tui_command_events(root, clean_conversation_id),
        inspector=build_conversation_inspector_payload(clean_conversation_id, root),
        runtime_timeline=_conversation_runtime_timeline_detail(root, clean_conversation_id),
    )


def _record_terminal_tui_demo_evidence_from_surfaces(
    *,
    root: Path,
    conversation_id: str,
    command: str,
    exit_code: int,
    started_at: str,
    completed_at: str,
    terminal_run_id: str,
    command_events: list[dict[str, Any]],
    inspector: dict[str, Any],
    runtime_timeline: dict[str, Any],
) -> TerminalTuiDemoResult:

    missing, visible_surfaces, observed_command_events = _terminal_demo_requirements(
        conversation_id=conversation_id,
        command=command,
        exit_code=exit_code,
        started_at=started_at,
        completed_at=completed_at,
        terminal_run_id=terminal_run_id,
        command_events=command_events,
        inspector=inspector,
        runtime_timeline=runtime_timeline,
    )
    if missing:
        return TerminalTuiDemoResult(written=False, missing_surfaces=missing)

    evidence = {
        "conversation_id": conversation_id,
        "mode": "terminal",
        "evidence_source": TERMINAL_TUI_DEMO_EVIDENCE_SOURCE,
        "harness_version": TERMINAL_TUI_DEMO_HARNESS_VERSION,
        "terminal_run_id": terminal_run_id,
        "command": command,
        "exit_code": exit_code,
        "started_at": started_at,
        "completed_at": completed_at,
        "scripted_inputs": terminal_tui_demo_scripted_inputs(conversation_id),
        "observed_command_event_ids": [
            str(event.get("event_id") or "") for event in observed_command_events
        ],
        "observed_command_events": observed_command_events,
        "visible_surfaces": [
            surface for surface in _REQUIRED_VISIBLE_SURFACES if surface in visible_surfaces
        ],
        "runtime_timeline_event_ids": _runtime_timeline_event_ids(runtime_timeline),
    }
    path = root / "tui_terminal_demo.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"terminal_tui_demo": evidence}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return TerminalTuiDemoResult(written=True, evidence=evidence)


def run_terminal_tui_demo(
    *,
    xmuse_root: Path | str,
    conversation_id: str,
    command: str = "uv run python -m xmuse.tui",
    timeout_s: float = 30.0,
    runner: TerminalRunner | None = None,
    chat_api_base_url: str | None = None,
) -> TerminalTuiDemoResult:
    started_at = _utc_now()
    terminal_run_id = f"terminal-tui-demo:{uuid.uuid4().hex}"
    env = dict(os.environ)
    if not env.get("TERM") or env.get("TERM") == "dumb":
        env["TERM"] = "xterm-256color"
    env[XMUSE_ROOT_ENV] = str(Path(xmuse_root).resolve())
    env["XMUSE_TUI_DEMO_CONVERSATION_ID"] = conversation_id.strip()
    env["XMUSE_TUI_TERMINAL_RUN_ID"] = terminal_run_id
    env["XMUSE_TUI_TERMINAL_DEMO_AUTORUN"] = "1"
    if chat_api_base_url:
        env["XMUSE_CHAT_API_URL"] = chat_api_base_url.rstrip("/")
    args = shlex.split(command)
    demo_runner = runner or _run_terminal_command
    result = demo_runner(
        args,
        env,
        timeout_s,
    )
    completed_at = _utc_now()
    return record_terminal_tui_demo_evidence(
        xmuse_root=xmuse_root,
        conversation_id=conversation_id,
        command=command,
        exit_code=result.exit_code,
        started_at=started_at,
        completed_at=completed_at,
        terminal_run_id=terminal_run_id,
    )


def is_terminal_tui_launch_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if parts == ["xmuse-tui"]:
        return True
    if parts == ["python", "-m", "xmuse.tui"]:
        return True
    return parts == ["uv", "run", "python", "-m", "xmuse.tui"]


def terminal_tui_demo_scripted_inputs(conversation_id: str) -> list[str]:
    clean_conversation_id = conversation_id.strip()
    if not clean_conversation_id:
        return []
    return [
        f"/resume {clean_conversation_id}",
        "/overview",
        "/discussion",
        "/blockers",
    ]


def _run_terminal_command(
    args: Sequence[str],
    env: dict[str, str],
    timeout_s: float,
) -> TerminalCommandResult:
    if not args:
        return TerminalCommandResult(exit_code=127, output="empty command")
    master_fd, slave_fd = pty.openpty()
    _set_pty_window_size(slave_fd, rows=40, cols=120)
    output = bytearray()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            list(args),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        deadline = time.monotonic() + timeout_s
        scripted_inputs = _scripted_terminal_inputs(env)
        command_inputs = scripted_inputs[:-1]
        quit_input = scripted_inputs[-1:] or ["\x11"]
        send_commands_at = time.monotonic() + min(3.0, max(0.5, timeout_s / 4))
        send_quit_at = send_commands_at + min(5.0, max(1.0, timeout_s / 4))
        sent_inputs = False
        sent_quit = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            now = time.monotonic()
            if not sent_inputs and now >= send_commands_at:
                for text in command_inputs:
                    os.write(master_fd, text.encode())
                    time.sleep(0.35)
                sent_inputs = True
            if sent_inputs and not sent_quit and now >= send_quit_at:
                for text in quit_input:
                    os.write(master_fd, text.encode())
                    time.sleep(0.1)
                sent_quit = True
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master_fd, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
        if process.poll() is None:
            os.write(master_fd, b"\x11")
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        return TerminalCommandResult(
            exit_code=_terminal_demo_exit_code(
                int(process.returncode or 0),
                sent_inputs=sent_inputs,
            ),
            output=output.decode(errors="replace"),
        )
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if process is None:
            try:
                os.close(slave_fd)
            except OSError:
                pass


def _scripted_terminal_inputs(env: dict[str, str]) -> list[str]:
    conversation_id = env.get("XMUSE_TUI_DEMO_CONVERSATION_ID", "").strip()
    commands = terminal_tui_demo_scripted_inputs(conversation_id)
    if not commands:
        return ["\x11"]
    return [f"{command}\x1b\r" for command in commands] + ["\x11"]


def _terminal_demo_exit_code(returncode: int, *, sent_inputs: bool) -> int:
    if sent_inputs and returncode in {-2, 130}:
        return 0
    return returncode


def _set_pty_window_size(fd: int, *, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(
            fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", int(rows), int(cols), 0, 0),
        )
    except OSError:
        return


def _terminal_demo_requirements(
    *,
    conversation_id: str,
    command: str,
    exit_code: int,
    started_at: str,
    completed_at: str,
    terminal_run_id: str,
    command_events: list[dict[str, Any]],
    inspector: dict[str, Any],
    runtime_timeline: dict[str, Any],
) -> tuple[list[str], set[str], list[dict[str, Any]]]:
    missing: list[str] = []
    clean_terminal_run_id = terminal_run_id.strip()
    if not clean_terminal_run_id:
        missing.append("terminal_run_id")
    if not is_terminal_tui_launch_command(command):
        missing.append("terminal_launch_command")
    if type(exit_code) is not int or exit_code != 0:
        missing.append("exit_code")
    observed_command_events = _terminal_run_command_events(
        conversation_id=conversation_id,
        terminal_run_id=clean_terminal_run_id,
        started_at=started_at,
        completed_at=completed_at,
        command_events=command_events,
    )
    surfaces = _visible_surfaces(
        conversation_id=conversation_id,
        started_at=started_at,
        completed_at=completed_at,
        terminal_run_id=clean_terminal_run_id,
        command_events=command_events,
        inspector=inspector,
    )
    for surface in _REQUIRED_VISIBLE_SURFACES:
        if surface not in surfaces:
            missing.append(surface)
    if not _runtime_timeline_event_ids(runtime_timeline):
        missing.append("runtime_timeline")
    required_commands = _required_terminal_demo_commands(conversation_id)
    observed_commands = {str(event.get("command") or "") for event in observed_command_events}
    for command_name in required_commands:
        if command_name not in observed_commands:
            missing.append(f"command_event:{command_name}")
    return missing, surfaces, observed_command_events


def _visible_surfaces(
    *,
    conversation_id: str,
    started_at: str,
    completed_at: str,
    terminal_run_id: str,
    command_events: list[dict[str, Any]],
    inspector: dict[str, Any],
) -> set[str]:
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    commands = {
        str(event.get("command") or "")
        for event in command_events
        if str(event.get("conversation_id") or "") == conversation_id
        and str(event.get("terminal_run_id") or "") == terminal_run_id
        and str(event.get("read_surface_authority") or "") == "chat_inspector"
        and str(event.get("surface_ref") or "") == f"chat_inspector:{conversation_id}"
        and _event_within_terminal_run(event, started=started, completed=completed)
    }
    surfaces: set[str] = set()
    participants = _dict(inspector.get("participants"))
    summary = _dict(participants.get("summary"))
    if int(summary.get("init") or 0) > 0:
        surfaces.add("init")
    if "/overview" in commands and _has_overview_surface(inspector):
        surfaces.add("overview")
    if "/discussion" in commands and isinstance(inspector.get("collaboration"), dict):
        surfaces.add("discussion")
    if "/blockers" in commands and isinstance(inspector.get("blockers"), dict):
        surfaces.add("blockers")
    if "/resume" in commands and _has_overview_surface(inspector):
        surfaces.add("resume")
    if _has_dispatch_surface(inspector):
        surfaces.add("dispatch")
    if _has_provider_writeback_surface(inspector):
        surfaces.add("provider_writeback")
    return surfaces


def _has_overview_surface(inspector: dict[str, Any]) -> bool:
    return any(
        isinstance(inspector.get(section), dict)
        for section in (
            "participants",
            "collaboration",
            "blockers",
            "dispatch_queue",
            "peer_latency",
        )
    )


def _has_dispatch_surface(inspector: dict[str, Any]) -> bool:
    queue = _dict(inspector.get("dispatch_queue"))
    entries = queue.get("entries")
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(entry, dict) and str(entry.get("status") or "") == "dispatched"
        for entry in entries
    )


def _has_provider_writeback_surface(inspector: dict[str, Any]) -> bool:
    latency = _dict(inspector.get("peer_latency"))
    turns = latency.get("recent_turns")
    turn_rows = turns if isinstance(turns, list) else []
    if any(
        isinstance(turn, dict) and str(turn.get("delivery_mode") or "") == "mcp_writeback"
        for turn in turn_rows
    ):
        return True
    queue = _dict(inspector.get("dispatch_queue"))
    entries = queue.get("entries")
    entry_rows = entries if isinstance(entries, list) else []
    return any(
        isinstance(entry, dict)
        and str(entry.get("dispatch_evidence") or "").startswith("mcp_writeback:")
        for entry in entry_rows
    )


def _terminal_run_command_events(
    *,
    conversation_id: str,
    terminal_run_id: str,
    started_at: str,
    completed_at: str,
    command_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not terminal_run_id:
        return []
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    observed = []
    for event in command_events:
        if str(event.get("conversation_id") or "") != conversation_id:
            continue
        if str(event.get("terminal_run_id") or "") != terminal_run_id:
            continue
        if str(event.get("read_surface_authority") or "") != "chat_inspector":
            continue
        if str(event.get("surface_ref") or "") != f"chat_inspector:{conversation_id}":
            continue
        if not str(event.get("event_id") or "").strip():
            continue
        if not _event_within_terminal_run(event, started=started, completed=completed):
            continue
        observed.append(dict(event))
    return observed


def _required_terminal_demo_commands(conversation_id: str) -> list[str]:
    commands = []
    for scripted_input in terminal_tui_demo_scripted_inputs(conversation_id):
        command, _, _ = scripted_input.partition(" ")
        commands.append(command)
    return commands


def _runtime_timeline_event_ids(runtime_timeline: dict[str, Any]) -> list[str]:
    events = runtime_timeline.get("events")
    if not isinstance(events, list):
        return []
    return [
        str(event.get("event_id") or "")
        for event in events
        if isinstance(event, dict) and str(event.get("event_id") or "").strip()
    ]


def _persisted_tui_command_events(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads((root / "tui_command_events.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = payload.get("command_events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return []
    return [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("conversation_id") or "") == conversation_id
    ]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _event_within_terminal_run(
    event: dict[str, Any],
    *,
    started: datetime | None,
    completed: datetime | None,
) -> bool:
    if started is None or completed is None:
        return False
    created = _parse_timestamp(str(event.get("created_at") or ""))
    return created is not None and started <= created <= completed


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
