"""`xmuse-workroom pair`: issue a plugin grant from the human's terminal.

Contract ``main_window_control_v1`` section 3. The human runs this in their own
terminal; it reads the running generation's operator token file, issues a grant
through the operator route, prints the pairing code, and then reports who
exchanged the code. It refuses to run without a terminal on stdin and stdout,
so an agent's shell tool cannot obtain a code in the normal path. The code and
the token are never logged or written anywhere.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from xmuse.operator_auth import OPERATOR_TOKEN_HEADER
from xmuse.workroom_operator_token import OperatorTokenFileError, read_operator_token
from xmuse_core.chat.room_plugin_grants import HOST_RE, SCOPES
from xmuse_core.runtime.root_contract import RuntimeRootPaths

DEFAULT_API_BASE = "http://127.0.0.1:8201"
EXCHANGE_POLL_S = 2.0

HttpCall = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


def _urllib_http(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (loopback only)
            raw = response.read()
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


@dataclass
class PairDependencies:
    stdin_isatty: Callable[[], bool]
    stdout_isatty: Callable[[], bool]
    http: HttpCall = _urllib_http
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    out: TextIO | None = None
    api_base: str = DEFAULT_API_BASE
    read_token: Callable[[Path], str] = field(default=read_operator_token)


class PairError(Exception):
    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def _print(deps: PairDependencies, line: str) -> None:
    print(line, file=deps.out, flush=True)


def _operator_call(
    deps: PairDependencies,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers = {OPERATOR_TOKEN_HEADER: token}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    return deps.http(method, deps.api_base.rstrip("/") + path, headers, data)


def _detail_code(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            return str(detail["code"])
    return "unexpected_response"


def resolve_rooms(deps: PairDependencies, prefixes: Sequence[str]) -> list[str]:
    if not prefixes:
        return []
    status, payload = deps.http("GET", deps.api_base.rstrip("/") + "/api/chat/rooms", {}, None)
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(rooms, list):
        raise PairError("workroom_not_running", 3)
    ids = [
        str(item["conversation_id"])
        for item in rooms
        if isinstance(item, dict) and isinstance(item.get("conversation_id"), str)
    ]
    resolved: list[str] = []
    for prefix in prefixes:
        matches = [room_id for room_id in ids if room_id.startswith(prefix)]
        if len(matches) != 1:
            raise PairError("room_prefix_ambiguous" if matches else "room_prefix_unknown", 4)
        if matches[0] not in resolved:
            resolved.append(matches[0])
    return resolved


def run_pair(
    *,
    root: Path,
    host: str,
    room_prefixes: Sequence[str],
    scopes: Sequence[str] | None,
    ttl_seconds: int | None,
    revoke: bool,
    list_only: bool,
    deps: PairDependencies,
    pending: bool = False,
) -> int:
    try:
        if pending:
            return _run_pending(room_prefixes=room_prefixes, deps=deps)
        return _run_pair(
            root=root,
            host=host,
            room_prefixes=room_prefixes,
            scopes=scopes,
            ttl_seconds=ttl_seconds,
            revoke=revoke,
            list_only=list_only,
            deps=deps,
        )
    except PairError as exc:
        _print(deps, f"xmuse pair: {exc.code}")
        return exc.exit_code


def _run_pair(
    *,
    root: Path,
    host: str,
    room_prefixes: Sequence[str],
    scopes: Sequence[str] | None,
    ttl_seconds: int | None,
    revoke: bool,
    list_only: bool,
    deps: PairDependencies,
) -> int:
    if not HOST_RE.match(host):
        raise PairError("plugin_grant_host_invalid", 2)
    # T16: a pairing code is shown only on a human's terminal. Checked before the
    # token is read or anything is sent.
    if not (deps.stdin_isatty() and deps.stdout_isatty()):
        raise PairError("plugin_pair_tty_required", 2)
    try:
        token = deps.read_token(RuntimeRootPaths.resolve(root, fallback=root).operator_token)
    except OperatorTokenFileError as exc:
        raise PairError(exc.code, 3 if exc.code == "workroom_not_running" else 2) from None
    except OSError:
        raise PairError("workroom_not_running", 3) from None

    if revoke:
        status, payload = _operator_call(
            deps, token, "POST", "/api/chat/operator/plugin-grants/revoke-host", {"host": host}
        )
        if status != 200:
            raise PairError(_detail_code(payload), 1)
        _print(deps, f"revoked {len(payload.get('grants', []))} grant(s) of {host}")
        return 0

    if list_only:
        query = urllib.parse.urlencode({"host": host})
        status, payload = _operator_call(
            deps, token, "GET", f"/api/chat/operator/plugin-grants?{query}"
        )
        if status != 200:
            raise PairError(_detail_code(payload), 1)
        for grant in payload.get("grants", []):
            if grant.get("status") not in ("active", "pending"):
                continue
            room_list = ",".join(grant.get("conversation_ids", [])) or "-"
            _print(
                deps,
                f"{grant['grant_id']} {grant['status']} expires {grant['expires_at']} "
                f"scopes {','.join(grant.get('scopes', []))} rooms {room_list}",
            )
        return 0

    chosen = sorted(scopes) if scopes else sorted(SCOPES)
    if any(scope not in SCOPES for scope in chosen):
        raise PairError("plugin_grant_scope_invalid", 2)
    rooms = resolve_rooms(deps, room_prefixes)
    body: dict[str, Any] = {"host": host, "scopes": chosen, "conversation_ids": rooms}
    if ttl_seconds is not None:
        body["ttl_seconds"] = ttl_seconds
    status, payload = _operator_call(deps, token, "POST", "/api/chat/operator/plugin-grants", body)
    if status != 201 or not isinstance(payload, dict):
        raise PairError(_detail_code(payload), 1)
    grant = payload["grant"]
    _print(deps, f"pairing code  {payload['pairing_code']}   (single use, expires in 120 s)")
    _print(deps, f"host {host}  scopes {','.join(grant['scopes'])}")
    _print(deps, f"rooms {','.join(grant['conversation_ids']) or '(none yet)'}")
    _print(deps, "type the code into the xmuse pane of your main window (never into a prompt)")
    return _report_exchange(deps, token, host, str(grant["grant_id"]))


def _plain(value: Any, limit: int = 120) -> str:
    """Agent-authored text for a terminal: printable characters only, one line, bounded."""

    text = "".join(ch if ch.isprintable() else " " for ch in str(value))
    return text[:limit]


def _digest_prefix(digest: Any) -> str:
    text = str(digest or "")
    return text.removeprefix("sha256:")[:6] or "?"


def _run_pending(*, room_prefixes: Sequence[str], deps: PairDependencies) -> int:
    """Print what waits for the Human, with the digest prefix the pane's confirm asks for.

    The pane never shows the digest next to its confirm field, so whatever drives the
    pane cannot read it there; this terminal-only listing is where the Human reads it.
    """

    if not (deps.stdin_isatty() and deps.stdout_isatty()):
        raise PairError("plugin_pair_tty_required", 2)
    base = deps.api_base.rstrip("/")
    if room_prefixes:
        rooms = resolve_rooms(deps, room_prefixes)
    else:
        status, payload = deps.http("GET", base + "/api/chat/rooms", {}, None)
        listed = payload.get("rooms") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(listed, list):
            raise PairError("workroom_not_running", 3)
        rooms = [
            str(item["conversation_id"])
            for item in listed
            if isinstance(item, dict) and isinstance(item.get("conversation_id"), str)
        ]
    shown = 0
    for room in rooms:
        status, board = deps.http(
            "GET", f"{base}/api/chat/conversations/{urllib.parse.quote(room)}/board", {}, None
        )
        if status != 200 or not isinstance(board, dict):
            continue
        names = {
            str(p.get("participant_id")): _plain(p.get("display_name"), 48)
            for p in board.get("participants", [])
            if isinstance(p, dict)
        }
        for split in board.get("splits", []):
            if not isinstance(split, dict) or split.get("status") != "proposed":
                continue
            shown += 1
            _print(deps, f"room {room}  split {split.get('split_id')}")
            _print(deps, f"  confirm with: {_digest_prefix(split.get('digest'))}")
            for module in split.get("modules", []):
                if not isinstance(module, dict):
                    continue
                paths = " ".join(_plain(path, 80) for path in module.get("paths", [])[:8])
                owner = names.get(str(module.get("owner_participant_id")), "?")
                _print(deps, f"  module {_plain(module.get('module_id'), 48)}  owner {owner}")
                _print(deps, f"    paths {paths}")
        for module in board.get("modules", []):
            review = module.get("review") if isinstance(module, dict) else None
            if (
                not isinstance(review, dict)
                or review.get("status") != "pending"
                or review.get("reviewer_kind") != "operator"
            ):
                continue
            shown += 1
            _print(deps, f"room {room}  review {review.get('review_id')}")
            _print(deps, f"  confirm with: {_digest_prefix(review.get('digest'))}")
            _print(deps, f"  module {_plain(module.get('module_id'), 48)}")
    if shown == 0:
        _print(deps, "nothing waits for you")
    else:
        _print(deps, "module ids and paths are agent-authored; check them before you confirm")
    return 0


def _report_exchange(deps: PairDependencies, token: str, host: str, grant_id: str) -> int:
    """Wait for the exchange so a code used by someone else is visible at once."""

    query = urllib.parse.urlencode({"host": host})
    deadline = deps.monotonic() + 125
    while deps.monotonic() < deadline:
        deps.sleep(EXCHANGE_POLL_S)
        status, payload = _operator_call(
            deps, token, "GET", f"/api/chat/operator/plugin-grants?{query}"
        )
        if status != 200 or not isinstance(payload, dict):
            continue
        grant = next(
            (item for item in payload.get("grants", []) if item.get("grant_id") == grant_id),
            None,
        )
        if grant is None:
            continue
        if grant.get("activated_at"):
            _print(deps, f"exchanged by {grant['host']} at {grant['activated_at']}")
            _print(deps, "not you? run: xmuse-workroom pair --revoke")
            return 0
        if grant.get("status") in ("expired", "revoked"):
            _print(deps, f"{grant['status']} unused")
            return 1
    _print(deps, "expired unused")
    return 1
