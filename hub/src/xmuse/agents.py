"""Machine-local assistant registry (T8 H11): which agent CLIs this machine has, trial-verified.

One file per OS user next to the room registry (agents.json): vendor, CLI path, default model, install status,
last check. Credentials stay in each vendor's own login; xmuse never reads or stores them. The sidebar key and
 hubs.json live in the same directory (registry.py); this module only reads them, it never prints them.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, registry
from .doctor import cli_paths
from .tools import ToolError

VENDORS = ("opencode", "dsh", "claude")
CLAUDE_BILLING_NOTE = "claude -p 从 2026-06-15 起单独计费"
TRIAL_PROMPT = "Reply with exactly: OK"
TRIAL_TIMEOUT_S = 120
DETAIL_LIMIT = 300

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer)\s*[:=]\s*\S+")
_ENV_LINE = re.compile(r"^[A-Z_][A-Za-z0-9_]*=")


def path() -> Path:
    return registry.directory() / "agents.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> list[dict]:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        agents = data.get("agents", [])
        return [e for e in agents if isinstance(e, dict) and e.get("vendor") in VENDORS]
    except (OSError, ValueError, AttributeError):
        return []


def _save(entries: list[dict]) -> None:
    """Atomic write with owner-only permissions, mirroring registry._store/_restrict."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps({"agents": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
    registry._restrict(tmp)
    for _ in range(20):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:  # Windows: a reader has it open for a moment
            time.sleep(0.02)
    tmp.unlink(missing_ok=True)
    raise OSError(f"could not replace {p}")


def _version_of(cli: str, timeout: float = 10) -> str:
    """`<cli> --version`, first line; "" when it cannot be had. No credential can come from a version string,
    but the output is still capped."""
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if out.returncode != 0:
        return ""
    return (out.stdout.strip().splitlines() or [""])[0][:100]


def scan(cfg: dict | None = None, paths: dict[str, str | None] | None = None,
         version_of=None) -> list[dict]:
    """Rescan the three vendors. `paths` ({vendor: path|None}) and `version_of(path)` may be injected
    (tests); by default the real machine is inspected. An entry keeps its model, and an `ok` status with
    its check time, while its path does not change."""
    if paths is None:
        paths = cli_paths(cfg or {})
    if version_of is None:
        version_of = _version_of
    old = {e["vendor"]: e for e in _load()}
    now = _now_iso()
    out = []
    for vendor in VENDORS:
        p = paths.get(vendor)
        prev = old.get(vendor, {})
        if p:
            version = version_of(p) or ""
            if prev.get("path") == p:
                model = prev.get("model") or config.MODELS[vendor]
                if prev.get("status") == "ok":
                    status, checked_at, detail = "ok", prev.get("checked_at") or now, ""
                else:
                    status, checked_at, detail = "installed", now, ""
            else:
                model, status, checked_at, detail = config.MODELS[vendor], "installed", now, ""
        else:
            version, model, status, checked_at, detail = "", prev.get("model") or config.MODELS[vendor], \
                "missing", now, ""
        out.append({"vendor": vendor, "path": p or "", "version": version, "model": model, "status": status,
                    "checked_at": checked_at, "detail": detail,
                    "billing_note": CLAUDE_BILLING_NOTE if vendor == "claude" else ""})
    _save(out)
    return out


def usable() -> list[dict]:
    """Trial-verified entries, except claude (separately billed, never default)."""
    return [e for e in _load() if e.get("status") == "ok" and e.get("vendor") != "claude"]


def entries() -> list[dict]:
    """The stored table as-is (scan first when it may be stale)."""
    return _load()


def default_model(vendor: str) -> str:
    """The registry's model for a vendor, else the config default."""
    for e in _load():
        if e.get("vendor") == vendor and e.get("model"):
            return e["model"]
    return config.MODELS[vendor]


def _safe_detail(text: str) -> str:
    """An error summary with no credentials or environment values in it: secret-looking
    assignments are redacted, ALLCAPS VAR=value lines are dropped, then truncated."""
    lines = [ln for ln in str(text or "").strip().splitlines() if not _ENV_LINE.match(ln.strip())]
    return _SECRET.sub(r"\1: ***", "\n".join(lines).strip())[:DETAIL_LIMIT]


def _replace(entries: list[dict], entry: dict) -> list[dict]:
    """Swap one vendor's entry in, keeping file order (append when absent)."""
    out = [entry if e.get("vendor") == entry["vendor"] else e for e in entries]
    if not any(e.get("vendor") == entry["vendor"] for e in out):
        out.append(entry)
    return out


def _run_cmd(argv: list[str], cwd: str, timeout: float) -> tuple[int, str]:
    """Run an external trial command in an empty directory; (returncode, combined output)."""
    try:
        out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        return 127, f"not found: {e.filename}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout:g}s"
    except OSError as e:
        return 127, str(e)
    return out.returncode, (out.stdout + out.stderr)[-2000:]


def trial(vendor: str, model: str | None = None, run=None, dsh_run=None) -> dict:
    """One minimal round with the default (or given) model; records ok/failed on the entry.
    `run(argv, cwd, timeout)` executes the opencode trial (injected in tests); `dsh_run(agent, ws)`
    returns None when a dsh trial round works, else an error string. Without a dsh runner, dsh trials
    are reported installed/trial-unsupported (there is no bare dsh one-shot command)."""
    if vendor not in VENDORS:
        raise ToolError("bad_vendor", f"vendor must be one of: {', '.join(VENDORS)}")
    if vendor == "claude":
        raise ToolError("claude_billed", "claude -p is billed separately: confirm on the panel before a trial run")
    if model is not None and not isinstance(model, str):
        raise ToolError("bad_request", "model must be a string")
    by = {e["vendor"]: e for e in _load()}
    if not (by.get(vendor) or {}).get("path"):
        raise ToolError("not_installed", f"{vendor} is not installed")
    model = model or default_model(vendor)
    err: str | None
    if vendor == "opencode":
        run = run or _run_cmd
        cwd = tempfile.mkdtemp(prefix="xmuse-trial-")
        try:
            rc, text = run([by[vendor]["path"], "run", "-m", model, TRIAL_PROMPT], cwd, TRIAL_TIMEOUT_S)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        err = None if rc == 0 and "OK" in text else f"exit {rc}: {text.strip()[:200]}" if text.strip() \
            else f"exit {rc} with no output"
    else:  # dsh: through the adapter's minimal no-tools round (precheck)
        if dsh_run is None:
            entry = {**by[vendor], "status": "installed", "checked_at": _now_iso(),
                     "detail": "trial unsupported"}
            _save(_replace(_load(), entry))
            return entry
        try:
            err = dsh_run({"id": "trial-dsh", "model": model, "settings": {}}, None)
        except Exception as e:  # noqa: BLE001 - a trial must record, never raise
            err = str(e)
    entry = {**by[vendor], "model": model, "status": "ok" if err is None else "failed",
             "checked_at": _now_iso(), "detail": "" if err is None else _safe_detail(err)}
    _save(_replace(_load(), entry))
    return entry


def set_model(vendor: str, model: str) -> dict:
    """An explicit default model; back to installed so a trial re-verifies it."""
    if vendor not in VENDORS:
        raise ToolError("bad_vendor", f"vendor must be one of: {', '.join(VENDORS)}")
    if not isinstance(model, str) or not model.strip():
        raise ToolError("bad_request", "model must be a non-empty name")
    by = {e["vendor"]: e for e in _load()}
    prev = by.get(vendor, {})
    entry = {"vendor": vendor, "path": prev.get("path", ""), "version": prev.get("version", ""),
             "model": model.strip(), "status": "installed", "checked_at": _now_iso(), "detail": "",
             "billing_note": CLAUDE_BILLING_NOTE if vendor == "claude" else ""}
    _save(_replace(_load(), entry))
    return entry
