"""Read-only board HTTP client.

Only GET requests to ``{base}/api/chat/...``: the rooms list and the
board summary / projection / events pages. No auth header, no body.
Responses are normalized defensively: unknown fields ignored, unknown
enum values kept as opaque strings, missing review fields mean "none".
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_BASE = "http://127.0.0.1:8201"
DEFAULT_WEB_BASE = "http://127.0.0.1:3000"

_LOOPBACK_HOSTS = frozenset(["127.0.0.1", "localhost", "::1"])

ROOMS_PATH = "/api/chat/rooms"

COUNT_KEYS = [
    "assigned",
    "claimed",
    "working",
    "blocked",
    "ready_for_review",
    "done_claimed",
    "verifying",
    "waiting_for_provider",
    "verified",
    "verification_failed",
    "verification_error",
]


class Offline(Exception):
    """The server could not be reached."""


class BadShape(Exception):
    """The response was not usable JSON of the expected shape."""


class UnknownRoom(Exception):
    """The server answered 404 for this room."""


def is_loopback_base(base: object) -> bool:
    """Accept only http loopback URLs; refuse before anything is sent."""
    if not isinstance(base, str):
        return False
    try:
        parsed = urllib.parse.urlparse(base.strip())
    except ValueError:
        return False
    if parsed.scheme != "http":
        return False
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def board_path(conversation_id: str) -> str:
    """Path of the board projection for one room."""
    return "/api/chat/conversations/" + urllib.parse.quote(conversation_id, safe="") + "/board"


def summary_path(conversation_id: str) -> str:
    """Path of the board summary for one room."""
    return board_path(conversation_id) + "/summary"


def get_json(
    base: str,
    path: str,
    query: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> object:
    """GET one JSON document; raise Offline, UnknownRoom or BadShape."""
    url = base.strip().rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UnknownRoom(path) from exc
        raise BadShape("http " + str(exc.code)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Offline(str(exc)) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadShape("not json") from exc


def web_room_link(web_base: str, conversation_id: str) -> str:
    """Link to the room page in the Web UI."""
    base = web_base.strip().rstrip("/")
    link = base + "/rooms/" + urllib.parse.quote(conversation_id, safe="")
    return link if len(link) <= 2048 else ""


def _as_record(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value  # type: ignore[return-value]
    return None


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _flag(value: object) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value >= 1 else 0
    return 0


def sort_rooms_newest(rooms: list[dict[str, str]]) -> list[dict[str, str]]:
    """Newest first by updated_at, mirroring the mod."""
    return sorted(rooms, key=lambda room: room["updated_at"], reverse=True)


def normalize_rooms(payload: object) -> list[dict[str, str]] | None:
    """Normalize the rooms list; None when the payload is unusable."""
    root = _as_record(payload)
    if root is None:
        return None
    out: list[dict[str, str]] = []
    for item in _as_list(root.get("rooms"))[:200]:
        record = _as_record(item)
        if record is None:
            continue
        room_id = _as_str(record.get("conversation_id"))
        if room_id is None or room_id == "":
            continue
        updated = _as_str(record.get("updated_at")) or ""
        title = _as_str(record.get("title")) or ""
        out.append({"conversation_id": room_id, "updated_at": updated, "title": title})
    return out


def normalize_attention(value: object) -> list[dict[str, str | None]]:
    """Normalize attention items; unknown values stay visible."""
    out: list[dict[str, str | None]] = []
    for item in _as_list(value)[:50]:
        record = _as_record(item)
        if record is None:
            continue
        kind = _as_str(record.get("kind")) or "?"
        reason = _as_str(record.get("reason_code")) or "?"
        module_id = _as_str(record.get("module_id"))
        split_id = _as_str(record.get("split_id"))
        integration_id = _as_str(record.get("integration_id"))
        out.append(
            {
                "kind": kind,
                "reason_code": reason,
                "module_id": module_id,
                "split_id": split_id,
                "integration_id": integration_id,
            }
        )
    return out


def _normalize_integration_state(value: object) -> dict[str, str | None]:
    """Summary room integration {status, green_head_commit}; none when missing."""
    record = _as_record(value)
    if record is None:
        return {"status": None, "green_head_commit": None}
    status = _as_str(record.get("status"))
    head = _as_str(record.get("green_head_commit"))
    return {
        "status": status if status not in (None, "") else None,
        "green_head_commit": head if head not in (None, "") else None,
    }


def _normalize_room_integration(value: object) -> dict[str, str | None]:
    """Projection room integration: latest status plus the green head."""
    record = _as_record(value)
    if record is None:
        return {"status": None, "green_head_commit": None}
    head = _as_str(record.get("green_head_commit"))
    latest = _as_record(record.get("latest"))
    status = _as_str(latest.get("status")) if latest is not None else None
    return {
        "status": status if status not in (None, "") else None,
        "green_head_commit": head if head not in (None, "") else None,
    }


def _normalize_module_integration(value: object) -> dict[str, object]:
    """Per-module integration fields; the none values on bad shapes."""
    none: dict[str, object] = {
        "status": "none",
        "verification_id": None,
        "integrated_verification_id": None,
        "conflict_path_count": 0,
        "reason_code": None,
    }
    record = _as_record(value)
    if record is None:
        return none
    raw_status = _as_str(record.get("status"))
    status = raw_status if raw_status not in (None, "") else "none"
    verification_id = _as_str(record.get("verification_id"))
    old_id = _as_str(record.get("integrated_verification_id"))
    reason = _as_str(record.get("reason_code"))
    raw_count = record.get("conflict_path_count")
    if isinstance(raw_count, bool):
        count = 0
    elif isinstance(raw_count, (int, float)):
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            count = 0
    else:
        count = 0
    return {
        "status": status,
        "verification_id": verification_id,
        "integrated_verification_id": old_id,
        "conflict_path_count": count,
        "reason_code": reason,
    }


def _accepted_from_summary(reviews: int, counts: dict[str, int], accepted_raw: object) -> int:
    # Frozen definition: while reviews are off every verified module
    # counts as accepted; with reviews on a missing value counts nothing.
    if reviews == 0:
        return counts.get("verified", 0)
    if isinstance(accepted_raw, bool):
        return 0
    if isinstance(accepted_raw, (int, float)):
        return max(0, int(accepted_raw))
    return 0


def normalize_summary(payload: object) -> dict[str, object] | None:
    """Normalize the board summary; None when required fields miss."""
    root = _as_record(payload)
    if root is None:
        return None
    room_id = _as_str(root.get("conversation_id"))
    revision = _as_str(root.get("revision"))
    if room_id is None or room_id == "" or revision is None or revision == "":
        return None
    raw_counts = _as_record(root.get("counts")) or {}
    counts = {key: _count(raw_counts.get(key)) for key in COUNT_KEYS}
    attention = normalize_attention(root.get("attention"))
    caps = _as_record(root.get("capabilities")) or {}
    reviews = _flag(caps.get("reviews"))
    integrations = _flag(caps.get("integrations"))
    accepted_total = _accepted_from_summary(reviews, counts, root.get("accepted_total"))
    integrated_raw = root.get("integrated_total")
    if isinstance(integrated_raw, bool):
        integrated_total = 0
    elif isinstance(integrated_raw, (int, float)):
        try:
            integrated_total = max(0, int(integrated_raw))
        except (TypeError, ValueError):
            integrated_total = 0
    else:
        integrated_total = 0
    return {
        "conversation_id": room_id,
        "revision": revision,
        "board_seq": _count(root.get("board_seq")),
        "modules_total": _count(root.get("modules_total")),
        "counts": counts,
        "attention": attention,
        "attention_total": max(len(attention), _count(root.get("attention_total"))),
        "accepted_total": accepted_total,
        "reviews": reviews,
        "integrations": integrations,
        "integrated_total": integrated_total,
        "integration": _normalize_integration_state(root.get("integration")),
    }


def _normalize_review(value: object) -> dict[str, object]:
    none: dict[str, object] = {
        "status": "none",
        "reviewer_kind": None,
        "escalated": False,
        "blocker": 0,
        "major": 0,
        "minor": 0,
    }
    record = _as_record(value)
    if record is None:
        return none
    raw_status = _as_str(record.get("status"))
    status = raw_status if raw_status is not None and raw_status != "" else "none"
    findings = _as_record(record.get("findings_count")) or {}
    escalated_from = record.get("escalated_from")
    return {
        "status": status,
        "reviewer_kind": _as_str(record.get("reviewer_kind")),
        "escalated": escalated_from is not None,
        "blocker": _count(findings.get("blocker")),
        "major": _count(findings.get("major")),
        "minor": _count(findings.get("minor")),
    }


def normalize_board(payload: object) -> dict[str, object] | None:
    """Normalize the board projection; None when required fields miss."""
    root = _as_record(payload)
    if root is None:
        return None
    revision = _as_str(root.get("revision"))
    room_id = _as_str(root.get("conversation_id"))
    if revision is None or revision == "" or room_id is None or room_id == "":
        return None
    owners: dict[str, dict[str, str]] = {}
    for item in _as_list(root.get("participants"))[:200]:
        record = _as_record(item)
        if record is None:
            continue
        participant_id = _as_str(record.get("participant_id"))
        if participant_id is None or participant_id == "":
            continue
        display = _as_str(record.get("display_name")) or "?"
        kind = _as_str(record.get("provider_kind")) or "?"
        owners[participant_id] = {"display": display, "kind": kind}
    modules: list[dict[str, object]] = []
    for item in _as_list(root.get("modules"))[:200]:
        record = _as_record(item)
        if record is None:
            continue
        module_id = _as_str(record.get("module_id"))
        if module_id is None or module_id == "":
            continue
        owner_id = _as_str(record.get("owner_participant_id"))
        owner = owners.get(owner_id) if owner_id is not None else None
        counters = _as_record(record.get("counters")) or {}
        attention = _as_record(record.get("attention"))
        review = _normalize_review(record.get("review"))
        state_raw = record.get("state")
        lifecycle_raw = record.get("lifecycle")
        modules.append(
            {
                "module_id": module_id,
                "state": state_raw if isinstance(state_raw, str) else "?",
                "lifecycle": lifecycle_raw if isinstance(lifecycle_raw, str) else "?",
                "owner_id": owner_id,
                "owner_display": owner["display"] if owner is not None else "?",
                "provider_kind": owner["kind"] if owner is not None else "?",
                "done_reports": _count(counters.get("done_reports")),
                "passed": _count(counters.get("passed")),
                "failed": _count(counters.get("failed")),
                "rework_rounds": _count(counters.get("rework_rounds")),
                "attention_kind": _as_str(attention.get("kind")) if attention else "none",
                "attention_reason": _as_str(attention.get("reason_code")) if attention else None,
                "accepted": record.get("accepted") is True,
                "review": review,
                "integration": _normalize_module_integration(record.get("integration")),
            }
        )
    modules.sort(key=lambda module: str(module["module_id"]))
    caps = _as_record(root.get("capabilities")) or {}
    reviews = _flag(caps.get("reviews"))
    integrations = _flag(caps.get("integrations"))
    # Same frozen definition as the summary.
    if reviews == 0:
        accepted_total = len([m for m in modules if m["state"] == "verified"])
    else:
        accepted_total = len([m for m in modules if m["accepted"] is True])
    splits: list[dict[str, str]] = []
    proposed: list[str] = []
    for item in _as_list(root.get("splits"))[:50]:
        record = _as_record(item)
        if record is None:
            continue
        split_id = _as_str(record.get("split_id"))
        if split_id is None or split_id == "":
            continue
        status = _as_str(record.get("status")) or "?"
        splits.append({"split_id": split_id, "status": status})
        if status == "proposed":
            proposed.append(split_id)
    # §3.11: accepted modules whose integrated version is their current candidate.
    integrated_total = 0
    for m in modules:
        integration = m.get("integration")
        if not (m["accepted"] is True and isinstance(integration, dict)):
            continue
        integrated_id = integration.get("integrated_verification_id")
        if integrated_id is not None and integrated_id == integration.get("verification_id"):
            integrated_total += 1
    return {
        "conversation_id": room_id,
        "revision": revision,
        "board_seq": _count(root.get("board_seq")),
        "reviews": reviews,
        "integrations": integrations,
        "accepted_total": accepted_total,
        "integrated_total": integrated_total,
        "integration": _normalize_room_integration(root.get("integration")),
        "modules": modules,
        "splits": splits[:10],
        "proposed_splits": proposed[:10],
        "attention": normalize_attention(root.get("attention")),
    }


def _normalize_event(item: object) -> dict[str, object] | None:
    record = _as_record(item)
    if record is None:
        return None
    kind = _as_str(record.get("kind")) or "?"
    actor = _as_record(record.get("actor")) or {}
    data = _as_record(record.get("data")) or {}
    return {
        "seq": _count(record.get("seq")),
        "kind": kind,
        "at": _as_str(record.get("at")) or "",
        "module_id": _as_str(record.get("module_id")),
        "actor_kind": _as_str(actor.get("kind")) or "?",
        "actor_participant_id": _as_str(actor.get("participant_id")),
        "data": data,
    }


def normalize_events_page(payload: object) -> dict[str, object] | None:
    """Normalize an events page; None when the payload is unusable."""
    root = _as_record(payload)
    if root is None:
        return None
    events: list[dict[str, object]] = []
    for item in _as_list(root.get("events"))[:200]:
        event = _normalize_event(item)
        if event is not None:
            events.append(event)
    events.sort(key=lambda event: int(event["seq"]))
    revision = _as_str(root.get("revision"))
    return {
        "conversation_id": _as_str(root.get("conversation_id")) or "",
        "board_seq": _count(root.get("board_seq")),
        "revision": revision,
        "events": events,
        "has_more": root.get("has_more") is True,
        "reset": root.get("reset") is True,
    }
