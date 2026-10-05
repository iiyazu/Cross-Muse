"""Opt-in status hook for the agy and dsh hosts.

Read-only like the rest of this package: two loopback GETs at most
(rooms are not listed; only the bound room's board summary is read).
Output is one structured line only: the existing ``status_line`` text
prefixed ``[xmuse] `` plus up to three ``label target`` operator
attention entries. Agent-authored text never leaves this module.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from . import api, binding, labels
from .render import status_line
from .sanitize import safe, safe_id

HOOK_TIMEOUT = 3.0
RATE_LIMIT_SECONDS = 30.0
MAX_LINE_CHARS = 300
MAX_STDIN_BYTES = 65536
MAX_ATTENTION_SHOWN = 3

VALID_HOSTS = ("agy", "dsh")
VALID_DSH_EVENTS = ("UserPromptSubmit", "SessionStart")
DEFAULT_DSH_EVENT = "UserPromptSubmit"


def state_dir() -> Path:
    """Directory holding the hook state file (0700)."""
    raw = os.environ.get("XDG_STATE_HOME", "")
    if raw.strip() != "":
        base = Path(raw).expanduser()
    else:
        base = Path.home() / ".local" / "state"
    return base / "xmuse-ctl"


def state_path() -> Path:
    """Full path of the hook state file."""
    return state_dir() / "hook-state.json"


def load_hook_state() -> dict[str, dict[str, object]]:
    """Read ``{conversation_id: {"signature": str, "at": float}}``.

    An unreadable or corrupt file reads as empty.
    """
    path = state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or key == "" or not isinstance(value, dict):
            continue
        signature = value.get("signature")
        at = value.get("at")
        if not isinstance(signature, str):
            continue
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            continue
        out[key] = {"signature": signature, "at": float(at)}
    return out


def save_hook_state(state: dict[str, dict[str, object]]) -> None:
    """Write hook state atomically; file 0600, directory 0700."""
    target_dir = state_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(target_dir, 0o700)
    tmp = target_dir / ("hook-state.json.tmp." + str(os.getpid()))
    try:
        tmp.write_text(
            json.dumps(state, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, target_dir / "hook-state.json")
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def read_payload() -> dict[str, object]:
    """Read one JSON object from stdin (cap 64 KiB).

    Malformed or oversized input reads as ``{}``; the content is
    otherwise ignored except for the working-directory hints.
    """
    try:
        stream = sys.stdin
        # A person running the command by hand has no payload to send;
        # hosts always pipe one. Never wait on a terminal.
        if stream.isatty():
            return {}
        buf = getattr(stream, "buffer", None)
        if buf is not None:
            try:
                raw = buf.read(MAX_STDIN_BYTES + 1)
            except OSError:
                return {}
            if raw is None:
                return {}
            if isinstance(raw, str):
                data = raw.encode("utf-8")
            else:
                data = bytes(raw)
        else:
            try:
                text = stream.read(MAX_STDIN_BYTES + 1)
            except OSError:
                return {}
            if text is None:
                return {}
            if isinstance(text, bytes):
                data = bytes(text)
            else:
                data = str(text).encode("utf-8")
    except ValueError:
        return {}
    if len(data) > MAX_STDIN_BYTES:
        return {}
    if not data.strip():
        return {}
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(obj, dict):
        return {}
    return obj


def resolve_cwd(payload: dict[str, object], host: str) -> str:
    """Pick the directory whose binding selects the room.

    For dsh the payload's ``cwd`` wins when present, for agy the first
    of ``workspacePaths``; otherwise the process cwd applies.
    """
    try:
        if host == "dsh":
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and cwd != "":
                return cwd
        elif host == "agy":
            paths = payload.get("workspacePaths")
            if isinstance(paths, list):
                for entry in paths:
                    if isinstance(entry, str) and entry != "":
                        return entry
    except AttributeError:
        pass
    try:
        return os.getcwd()
    except OSError:
        return ""


def operator_items(summary: dict[str, object]) -> list[dict[str, object]]:
    """Operator attention items of a normalized summary, in order."""
    attention = summary.get("attention")
    if not isinstance(attention, list):
        return []
    out: list[dict[str, object]] = []
    for item in attention:
        if isinstance(item, dict) and item.get("kind") == "operator":
            out.append(item)
    return out


def attention_signature(items: list[dict[str, object]]) -> str:
    """Stable signature of the operator attention set.

    The sorted list of ``reason_code|module_id|split_id`` of operator
    items; empty when there is nothing for the operator.
    """
    parts: list[str] = []
    for item in items:
        reason = item.get("reason_code")
        module_id = item.get("module_id")
        split_id = item.get("split_id")
        reason_text = reason if isinstance(reason, str) else "?"
        module_text = module_id if isinstance(module_id, str) else ""
        split_text = split_id if isinstance(split_id, str) else ""
        parts.append(reason_text + "|" + module_text + "|" + split_text)
    return "\n".join(sorted(parts))


def _attention_target(item: dict[str, object]) -> str:
    module_id = item.get("module_id")
    if isinstance(module_id, str) and module_id != "":
        return safe_id(module_id)
    split_id = item.get("split_id")
    if isinstance(split_id, str) and split_id != "":
        return safe(split_id, 64)
    # Room-level integration items carry only an integration_id: no target.
    return ""


def hook_line(summary: dict[str, object]) -> str | None:
    """Build the one injectable line, or None when there is nothing.

    The line is the existing ``status_line`` text prefixed ``[xmuse] ``,
    plus up to three ``label target`` operator entries. Only counts,
    state codes, reason-code labels and ids enter; total length holds
    at 300 characters.
    """
    items = operator_items(summary)
    if not items:
        return None
    line = "[xmuse] " + status_line(summary)
    entries: list[str] = []
    for item in items[:MAX_ATTENTION_SHOWN]:
        label = labels.reason_label(item.get("reason_code"))
        if label == "":
            label = "待处理"
        target = _attention_target(item)
        entries.append(label if target == "" else label + " " + target)
    if entries:
        line += "; " + "; ".join(entries)
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS]
    return line


def _api_base(api_base: str | None) -> str:
    raw = api_base or os.environ.get("XMUSE_API_BASE", "") or api.DEFAULT_API_BASE
    return raw.strip()


def _fetch_summary(base: str, conversation_id: str) -> dict[str, object] | None:
    try:
        payload = api.get_json(base, api.summary_path(conversation_id), timeout=HOOK_TIMEOUT)
    except (api.Offline, api.UnknownRoom, api.BadShape, ValueError, OSError):
        return None
    except Exception:
        return None
    try:
        return api.normalize_summary(payload)
    except Exception:
        return None


def run_hook(host: str, event: str, api_base: str | None = None) -> dict[str, object]:
    """Compute the hook output object; ``{}`` means nothing to say.

    Every failure path (unbound room, offline server, bad shape, rate
    limit, unchanged attention, unwritable state) yields ``{}``.
    """
    if host not in VALID_HOSTS:
        return {}
    if host == "dsh" and event not in VALID_DSH_EVENTS:
        return {}
    payload = read_payload()
    cwd = resolve_cwd(payload, host)
    if cwd == "":
        return {}
    try:
        room = binding.load_bindings().get(cwd)
    except OSError:
        return {}
    except ValueError:
        return {}
    if room is None:
        return {}
    base = _api_base(api_base)
    if not api.is_loopback_base(base):
        return {}
    summary = _fetch_summary(base, room)
    if summary is None:
        return {}
    return _emit(host, event, room, summary)


def _emit(host: str, event: str, room: str, summary: dict[str, object]) -> dict[str, object]:
    items = operator_items(summary)
    try:
        state = load_hook_state()
    except OSError:
        state = {}
    except ValueError:
        state = {}
    if not items:
        # Nothing waits for the operator any more: forget the last
        # signature so the same item reappearing later is announced again.
        if room in state:
            del state[room]
            try:
                save_hook_state(state)
            except (OSError, ValueError):
                pass
        return {}
    signature = attention_signature(items)
    now = time.time()
    entry = state.get(room)
    if isinstance(entry, dict):
        last_signature = entry.get("signature")
        last_at = entry.get("at")
        if last_signature == signature:
            return {}
        if isinstance(last_at, (int, float)) and not isinstance(last_at, bool):
            try:
                if now - float(last_at) < RATE_LIMIT_SECONDS:
                    return {}
            except (TypeError, ValueError, OverflowError):
                return {}
    line = hook_line(summary)
    if line is None:
        return {}
    state[room] = {"signature": signature, "at": now}
    try:
        save_hook_state(state)
    except OSError:
        return {}
    except ValueError:
        return {}
    if host == "agy":
        return {"injectSteps": [{"ephemeralMessage": line}]}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": line}}


def main_hook(host: str, event: str, api_base: str | None = None) -> int:
    """Entry point for the ``hook`` subcommand; always exits 0.

    Prints exactly one JSON object on stdout and nothing on stderr.
    """
    try:
        output = run_hook(host, event, api_base)
    except Exception:
        output = {}
    if not isinstance(output, dict):
        output = {}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0
