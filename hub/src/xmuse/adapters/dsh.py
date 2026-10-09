"""dsh (DeepSeek Harness 0.2.0-rc.2, Windows only): one headless process per turn (M0-dsh §3).

- Each run gets a one-off `--patch` overlay in the hub state dir: explicit model, only the xmuse MCP
  server, and `disabled` rows for native tools the hub does not hand out (web, subagents, workflows,
  plugin manager, background jobs). Files and PowerShell stay: they run inside dsh's workspace-write
  sandbox, and anything that would need approval fails closed in headless mode. $DSH_HOME/profiles is
  never touched.
- Every path the Windows child sees is Windows-shaped. The workspace must be under C:\\ (dsh cannot
  write through \\\\wsl.localhost), and a session resumes only in the cwd it was created in.
- Clean env plus DSH_TELEMETRY_DISABLED=1 and ELECTRON_RUN_AS_NODE=1, listed in WSLENV: WSL drops
  variables a Win32 process is not told about (the M0-dsh runs set telemetry without WSLENV, so it
  never reached dsh).
- dsh refuses a second writer ("already owned"): back off (10 s, doubling) and after N refusals pause
  the agent for the human. An unknown session id is an error, never a new session: the hub retries
  the messages in a fresh session with a bootstrap pack.
- A user message whose source carries rpcId was typed in the desktop app: admission waits for its
  turn to end (session log, zstd JSONL).
"""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import zstandard

from ..config import SHIM
from ..env import clean_env
from .base import Presence, TurnEnd, TurnSpec, Usage

WIN_HOME = Path("/mnt/c/Users") / os.environ.get("USER", "")
APP = WIN_HOME / "AppData/Local/Programs/DeepSeek Harness"
CLIJS = r"resources\app.asar\dsh\node_modules\@deepseek-ai\dsh-desktop-host\lib\cli.js"
DISABLE = ["tool-web", "tool-subagent", "tool-subagent-fork", "tool-subagent-control", "tool-subagent-list-agents",
           "tool-workflow", "tool-plugin-manager", "tool-jobs"]
CODE_TOOLS = {"edit", "write", "pwsh", "bash"}
# ELECTRON_RUN_AS_NODE is what dsh.cmd sets: without it the exe starts as the desktop app and, with the app
# already open, hands off to it and exits 0 with no output.
ENV = {"DSH_TELEMETRY_DISABLED": "1", "ELECTRON_RUN_AS_NODE": "1", "WSLENV": "DSH_TELEMETRY_DISABLED:ELECTRON_RUN_AS_NODE"}
OWNED, UNKNOWN = "is already owned by an active write handle", "does not exist"


def to_win(p) -> str:
    s = str(p)
    if s.startswith("/mnt/c/"):
        return "C:\\" + s[len("/mnt/c/"):].replace("/", "\\")
    return "\\\\wsl.localhost\\" + os.environ.get("WSL_DISTRO_NAME", "Ubuntu-24.04") + s.replace("/", "\\")


def overlay(agent: dict, state: Path, mcp: bool = True) -> str:
    """The per-run --patch file. JSON is valid YAML, so no YAML writer is needed."""
    provider, model = agent["model"].split("/", 1)
    rows: list = [{"id": "agent-default-model", "name": "@deepseek-ai/dsh-agent-default-model",
                   "config": {"provider": provider, "model": model}}]
    if mcp:
        rows.append({"insert": [{"id": "mcp-xmuse", "name": "@deepseek-ai/dsh-mcp-client", "config": {
            "serverName": "xmuse", "transport": "stdio", "command": "node", "args": [to_win(SHIM)],
            "env": {"XMUSE_STATE": to_win(state), "XMUSE_AGENT": agent["id"]}, "failOnStartupError": True}}]})
    rows += [{"id": r, "disabled": True} for r in DISABLE]
    return json.dumps(rows, indent=1)


def parse(lines) -> tuple[dict, Usage]:
    """--json NDJSON of one run -> (info, usage). step_end usage is per step; dsh never reports cache writes."""
    info, u = {}, Usage()
    for line in lines:
        if not line.startswith("{"):
            continue
        o = json.loads(line)
        typ = o.get("type")
        if typ == "session":
            info["session"] = o.get("sessionId")
        elif typ == "error":
            msg = o.get("message", "")
            info["error"] = msg
            info["owned"], info["unknown"] = OWNED in msg, UNKNOWN in msg
        elif typ == "tool_call" and o.get("tool") in CODE_TOOLS:
            u.mode = "code"
        elif typ == "status" and o.get("phase") == "step_end" and o.get("usage"):
            s = o["usage"]
            u.input += s.get("inputTokens", 0)
            u.cache_read += s.get("cacheReadTokens", 0)
            u.output += s.get("outputTokens", 0)
            u.context = s.get("inputTokens", 0) + s.get("cacheReadTokens", 0)
            u.calls += 1
        elif typ == "status" and o.get("phase") == "turn_end":
            r = o.get("reason") or {}
            info["ok"] = r.get("kind") == "completed"
            if not info["ok"]:
                e = r.get("error") or {}
                info["error"] = f"{e.get('code', r.get('kind'))}: {e.get('message', '')}"
    return info, u


def human_turn(log: Path) -> bool:
    """A desktop-typed message (source.rpcId) with no turn/end after it."""
    if not log.exists():
        return False
    busy = False
    raw = zstandard.ZstdDecompressor().stream_reader(log.open("rb")).read().decode()
    for line in raw.splitlines():
        o = json.loads(line)
        if o.get("type") == "user/message" and ((o.get("data") or {}).get("source") or {}).get("rpcId"):
            busy = True
        elif o.get("type") == "turn/end":
            busy = False
    return busy


class DshHeadless:
    name = "dsh"

    def __init__(self, sink, state: Path, cfg: dict):
        self.sink, self.state = sink, state
        self.exe = cfg.get("dsh_exe", str(APP / "DeepSeek Harness.exe"))
        self.clijs = cfg.get("dsh_clijs", to_win(APP) + "\\" + CLIJS)
        self.backoff, self.refusals = cfg.get("dsh_backoff", 10), cfg.get("dsh_refusals", 4)
        self.runs: dict[int, dict] = {}

    def command(self, patch: Path, session: str | None) -> list[str]:
        return [self.exe, "--expose-internals", self.clijs, "--profile", "headless", "--patch", to_win(patch),
                "--json", *(["--session-id", session] if session else []), "-"]  # task text on stdin

    def run(self, cwd: Path, patch: Path, session: str | None, prompt: str, log: Path, st: dict | None = None):
        if not str(cwd).startswith("/mnt/c/"):
            raise RuntimeError(f"dsh needs a workspace under C:\\ (got {cwd})")
        with log.open("a") as out, log.with_suffix(".err").open("a") as err:
            p = subprocess.Popen(self.command(patch, session), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=err, text=True, encoding="utf-8", start_new_session=True,
                                 env=clean_env(ENV))
            if st is not None:
                st["p"] = p
            p.stdin.write(prompt)
            p.stdin.close()
            lines = []
            for line in p.stdout:
                out.write(line)
                lines.append(line)
        p.wait()
        info, usage = parse(lines)
        info["rc"] = p.returncode
        return info, usage

    def start(self, spec: TurnSpec) -> dict:
        patch = self.state / "runs" / f"turn-{spec.turn_id}.patch.yml"
        patch.write_text(overlay(spec.agent, self.state))
        st = self.runs[spec.turn_id] = {"stop": threading.Event()}
        threading.Thread(target=self._turn, args=(spec, patch, st), daemon=True).start()
        return {"handle": spec.session, "cwd": to_win(spec.cwd)}

    def _turn(self, spec: TurnSpec, patch: Path, st: dict) -> None:
        delay, total = self.backoff, Usage()
        for attempt in range(self.refusals + 1):
            try:
                info, usage = self.run(spec.cwd, patch, spec.session, spec.prompt, spec.run_log, st)
            except Exception as e:
                info, usage = {"error": f"start failed: {e}"}, Usage()
            total = usage if usage.calls else total
            if not info.get("owned") or attempt == self.refusals or st["stop"].wait(delay):
                break
            delay *= 2
        self.runs.pop(spec.turn_id, None)
        sid = info.get("session") or spec.session
        if st["stop"].is_set():
            end = TurnEnd(spec.turn_id, "interrupted", sid, total, "interrupted by hub")
        elif info.get("owned"):
            end = TurnEnd(spec.turn_id, "failed", sid, total, f"session {sid} held by another dsh process "
                                                             f"({self.refusals + 1} refusals)", requeue="hold")
        elif info.get("unknown"):
            end = TurnEnd(spec.turn_id, "failed", sid, total, info["error"], requeue="fresh")
        elif info.get("ok") and info.get("rc") == 0:
            end = TurnEnd(spec.turn_id, "succeeded", sid, total)
        else:
            tail = spec.run_log.with_suffix(".err").read_text()[-300:].strip() if spec.run_log.with_suffix(
                ".err").exists() else ""
            end = TurnEnd(spec.turn_id, "failed", sid, total, info.get("error") or f"exit {info.get('rc')}: {tail}")
        total.model = spec.agent["model"].split("/", 1)[1]
        self.sink.turn_ended(end)

    def interrupt(self, turn_id: int) -> None:
        st = self.runs.get(turn_id)
        if not st:
            return
        st["stop"].set()
        if st.get("p") and st["p"].poll() is None:
            try:
                os.killpg(st["p"].pid, signal.SIGKILL)  # the lease dies with the process (M0-dsh crash tests)
            except ProcessLookupError:
                pass


class DshDriver:
    vendor = "dsh"
    push = None  # no local push path into a live desktop session (gateway client is out of scope)

    def __init__(self, sink, state: Path, cfg: dict):
        self.state, self.ws = state, Path(cfg["workspace"])
        self.home = Path(cfg.get("dsh_home", WIN_HOME / ".dsh"))
        self.headless = DshHeadless(sink, state, cfg)

    def presence(self, agent: dict, session: str | None) -> Presence:
        logs = list(self.home.glob(f"sessions/*/{session}/session.v4.jsonl.zstd")) if session else []
        return Presence("free", bool(logs) and human_turn(logs[0]), False)

    def precheck(self, agent: dict, ws: Path) -> str | None:
        """One minimal run without tools: an unknown model or provider fails here (about 10 s, no tokens)."""
        patch = self.state / "runs" / f"precheck-{agent['id']}.patch.yml"
        patch.write_text(overlay(agent, self.state, mcp=False))
        log = self.state / "logs" / f"precheck-{agent['id']}.jsonl"
        info, _ = self.headless.run(ws, patch, None, "Reply with the single word OK.", log)
        return None if info.get("ok") and info["rc"] == 0 else info.get("error") or f"exit {info['rc']}"

    def on_hook(self, agent: dict, event: str, payload: dict) -> bool:
        return False

    @staticmethod
    def write_config(ws: Path, agent: dict, state: Path) -> list[Path]:
        return []  # the overlay is per run and lives in the state dir; skill and AGENTS.md come from init

    def attach_command(self, agent: dict, session: str | None) -> str:
        return (f"dsh has no terminal UI: open the DeepSeek Harness desktop app"
                f"{' at session ' + session if session else ''} (workspace {to_win(self.ws)}).")

    def close(self) -> None:
        for t in list(self.headless.runs):
            self.headless.interrupt(t)
