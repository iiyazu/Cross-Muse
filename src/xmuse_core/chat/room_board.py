"""Durable Room coordination board: charters, contracts, progress, questions.

Every board write appends at least one ``board.`` activity to
``room_activities`` and updates the ``room_board_*`` tables in the same
``BEGIN IMMEDIATE`` transaction. Agent-facing writes are bound to a live
observation lease exactly like participant outcomes and are idempotent per
``(tool_name, caller_identity, client_request_id)``.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_agent_kinds import ROOM_AGENT_CLI_KINDS
from xmuse_core.chat.room_batches import canonical_observation_id
from xmuse_core.chat.room_board_projection import (
    MAX_CONSECUTIVE_FAILURES,
    ProgressFact,
    VerificationFact,
    agent_text,
    build_board_projection,
    build_contract_detail,
    compute_counters,
    derive_lifecycle,
    derive_state,
    derive_verification_axis,
    is_valid_finding_path,
    review_digest,
    split_digest,
)
from xmuse_core.chat.room_collaboration import (
    collaboration_policy_row,
    review_policy_for_conversation,
)
from xmuse_core.chat.room_database import RoomDatabase

TOOL_READ = "chat_room_board_read"
TOOL_PROPOSE_SPLIT = "chat_room_board_propose_split"
TOOL_CLAIM = "chat_room_board_claim"
TOOL_PUBLISH_CONTRACT = "chat_room_board_publish_contract"
TOOL_REPORT_PROGRESS = "chat_room_board_report_progress"
TOOL_ASK = "chat_room_board_ask"
TOOL_REVIEW = "chat_room_board_review"

BOARD_REVIEW_RULE_ID = "cross_family/v1"
BOARD_REVIEW_STATUSES = ("pending", "endorsed", "objected", "superseded")
BOARD_REVIEW_VERDICTS = ("endorse", "object")
BOARD_REVIEW_SEVERITIES = ("blocker", "major", "minor")
BOARD_REVIEW_REASONS = (
    "board_review_reviewer_unavailable",
    "board_review_reviewer_no_verdict",
    "board_review_reviewer_unresponsive",
)
BOARD_REVIEW_RESPONSE_SECONDS_DEFAULT = 3600
MAX_REVIEW_SUMMARY_CHARS = 4000
MAX_REVIEW_FINDINGS = 32
MAX_REVIEW_FINDING_TEXT_CHARS = 1000
MAX_REVIEW_FINDING_PATH_CHARS = 512
# The operator review material route (§8.2) returns at most this many UTF-8
# bytes of marked patch text; markers may grow the text beyond the stored size.
REVIEW_MATERIAL_PATCH_LIMIT_BYTES = 256 * 1024

BOARD_ACTIVITY_SCHEMA_VERSION = "room_board_activity/v1"
BOARD_INBOX_LIMIT = 50
MAX_CONTRACT_CONTENT_BYTES = 65536
MAX_VERIFICATION_ATTEMPTS = 3
MAX_INTEGRATION_ATTEMPTS = 3
INTEGRATION_LEASE_TTL_S = 1800
BOARD_INTEGRATION_STATUSES = (
    "pending",
    "running",
    "integrated",
    "conflicted",
    "gate_failed",
    "error",
)
BOARD_INTEGRATION_ITEM_STATUSES = ("applied", "fell_back", "conflicted", "waiting", "not_applied")
BOARD_INTEGRATION_CONFLICT = "board_integration_conflict"
BOARD_INTEGRATION_GATE_FAILED = "board_integration_gate_failed"
BOARD_INTEGRATION_WAITING_FOR_DEPENDENCY = "board_integration_waiting_for_dependency"
BOARD_INTEGRATION_WOULD_DROP_ACCEPTED = "board_integration_would_drop_accepted"
BOARD_INTEGRATION_ATTEMPTS_EXHAUSTED = "board_integration_attempts_exhausted"
# Room for a few bounded gate output tails plus JSON escaping.
MAX_VERIFICATION_EVIDENCE_BYTES = 16384
VERIFICATION_LEASE_TTL_S = 1800
VERIFICATION_STATUSES = ("pending", "running", "passed", "failed", "superseded", "error")
BOARD_VERIFICATION_WAITING_FOR_PROVIDER = "board_verification_waiting_for_provider"
BOARD_VERIFICATION_BASE_MISMATCH = "board_verification_base_mismatch"
BOARD_VERIFICATION_DEPENDENCY_OVERLAP = "board_verification_dependency_overlap"
VERIFICATION_DEFERRAL_DELAY_S = 15
MAX_VERIFICATION_PATCH_BYTES = 200_000

MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
CONTRACT_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
DECIDED_VIA_RE = re.compile(r"^(web|cli|plugin:[a-z0-9][a-z0-9_-]{0,31})$")
CHARTER_KEYS = frozenset(
    {"module_id", "title", "paths", "provides", "depends", "acceptance", "report_to"}
)
SPLIT_CONTRACT_KEYS = frozenset(
    {"contract_id", "provider_module_id", "kind", "content", "rationale"}
)
CONTRACT_KINDS = ("api_schema", "types", "protocol", "text")
PROGRESS_STATUSES = ("working", "blocked", "ready_for_review", "done")
WAKE_STATUSES = ("blocked", "ready_for_review")


def contract_digest(content: str) -> str:
    """Return the ``sha256:<hex>`` digest of contract content."""

    return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"


def charter_path_allowed(path: str, patterns: Sequence[str]) -> bool:
    """Return True when a repo-relative path falls inside charter ``paths`` globs.

    Matching is ``fnmatch``-style POSIX matching against the charter's relative
    glob list.  The host-owned board view (``.xmuse/``) is never allowed, even
    when a glob would match it.
    """

    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or "\\" in path:
        return False
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    if path == ".xmuse" or path.startswith(".xmuse/"):
        return False
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            continue
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.endswith("/**"):
            stem = pattern[:-3]
            if path == stem or path.startswith(stem + "/"):
                return True
    return False


def charter_outside_paths(changed_paths: Sequence[str], patterns: Sequence[str]) -> list[str]:
    """Return the changed paths that fall outside the charter ``paths`` globs."""

    return [path for path in changed_paths if not charter_path_allowed(path, patterns)]


def split_dependency_cycle(
    modules: Sequence[dict[str, Any]], contracts: Sequence[dict[str, Any]]
) -> list[str] | None:
    """Return one module dependency cycle in a split, or None when it is acyclic.

    A module depends on the provider module of every contract in its charter
    ``depends``.  Verification stacks providers' verified work under their
    dependents, so a cycle would leave every module in it waiting on another
    forever; a shared interface belongs in a module of its own.
    """

    provider_of = {str(spec["contract_id"]): str(spec["provider_module_id"]) for spec in contracts}
    edges: dict[str, list[str]] = {}
    for charter in modules:
        module_id = str(charter["module_id"])
        edges[module_id] = sorted(
            {
                provider_of[contract_id]
                for contract_id in charter.get("depends", [])
                if contract_id in provider_of and provider_of[contract_id] != module_id
            }
        )
    state: dict[str, int] = {}  # 1 = on the current path, 2 = done
    path: list[str] = []

    def visit(module_id: str) -> list[str] | None:
        state[module_id] = 1
        path.append(module_id)
        for provider in edges.get(module_id, []):
            if state.get(provider) == 1:
                return [*path[path.index(provider) :], provider]
            if provider not in state:
                found = visit(provider)
                if found is not None:
                    return found
        path.pop()
        state[module_id] = 2
        return None

    for module_id in sorted(edges):
        if module_id not in state:
            found = visit(module_id)
            if found is not None:
                return found
    return None


def integration_apply_order(
    module_ids: Sequence[str],
    providers: Mapping[str, Sequence[str]],
    roles: Mapping[str, str],
) -> list[str]:
    """Order integration candidates: dependencies first, incumbents, module id.

    Among the candidates whose in-set dependencies are all placed, incumbents
    (modules of the previous green head whose candidate did not change) go
    before newcomers, then by ``module_id`` — so a conflict between modules
    without a dependency path lands on the newcomer. A dependency cycle (which
    splits reject, but later contract edits could still arrange) falls back to
    the same role/id order instead of stalling.
    """

    in_set = set(module_ids)
    ordered: list[str] = []
    placed: set[str] = set()
    remaining = set(module_ids)
    while remaining:
        ready = sorted(
            (
                module_id
                for module_id in remaining
                if all(item in placed for item in providers.get(module_id, []) if item in in_set)
            ),
            key=lambda item: (0 if roles.get(item) == "incumbent" else 1, item),
        )
        if not ready:
            ready = sorted(
                remaining,
                key=lambda item: (0 if roles.get(item) == "incumbent" else 1, item),
            )
        module_id = ready[0]
        ordered.append(module_id)
        placed.add(module_id)
        remaining.discard(module_id)
    return ordered


def normalize_charter(value: Any) -> dict[str, Any]:
    """Validate an untrusted charter dict and return its canonical form."""

    if not isinstance(value, dict):
        raise ValueError("room_board_charter_invalid: charter must be an object")
    unknown = set(value) - CHARTER_KEYS
    if unknown:
        raise ValueError(
            f"room_board_charter_invalid: unknown keys {sorted(str(item) for item in unknown)}"
        )
    module_id = value.get("module_id")
    if not isinstance(module_id, str) or not MODULE_ID_RE.match(module_id):
        raise ValueError("room_board_charter_invalid: module_id invalid")
    title = value.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise ValueError("room_board_charter_invalid: title invalid")
    paths = value.get("paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise ValueError("room_board_charter_invalid: paths invalid")
    clean_paths: list[str] = []
    for entry in paths:
        if not isinstance(entry, str) or not entry:
            raise ValueError("room_board_charter_invalid: paths invalid")
        if entry.startswith("/") or "\\" in entry or ".." in entry.split("/"):
            raise ValueError("room_board_charter_invalid: paths must be relative POSIX globs")
        clean_paths.append(entry)
    provides = _normalize_contract_id_list(value.get("provides", []), "provides")
    depends = _normalize_contract_id_list(value.get("depends", []), "depends")
    acceptance_raw = value.get("acceptance", [])
    if not isinstance(acceptance_raw, list) or len(acceptance_raw) > 16:
        raise ValueError("room_board_charter_invalid: acceptance invalid")
    acceptance: list[str] = []
    for entry in acceptance_raw:
        if not isinstance(entry, str) or not entry.strip() or len(entry.strip()) > 500:
            raise ValueError("room_board_charter_invalid: acceptance invalid")
        acceptance.append(entry.strip())
    report_to = value.get("report_to")
    if report_to is not None and (not isinstance(report_to, str) or not report_to.strip()):
        raise ValueError("room_board_charter_invalid: report_to invalid")
    return {
        "module_id": module_id,
        "title": title.strip(),
        "paths": clean_paths,
        "provides": provides,
        "depends": depends,
        "acceptance": acceptance,
        "report_to": report_to.strip() if isinstance(report_to, str) else None,
    }


def _normalize_contract_id_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError(f"room_board_charter_invalid: {field} invalid")
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not CONTRACT_ID_RE.match(entry):
            raise ValueError(f"room_board_charter_invalid: {field} invalid")
        result.append(entry)
    if len(set(result)) != len(result):
        raise ValueError(f"room_board_charter_invalid: {field} must be unique")
    return result


def normalize_split_contract(value: Any) -> dict[str, Any]:
    """Validate one contract spec inside a split proposal."""

    if not isinstance(value, dict):
        raise ValueError("room_board_contract_invalid: contract must be an object")
    unknown = set(value) - SPLIT_CONTRACT_KEYS
    if unknown:
        raise ValueError(
            f"room_board_contract_invalid: unknown keys {sorted(str(item) for item in unknown)}"
        )
    contract_id = value.get("contract_id")
    if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
        raise ValueError("room_board_contract_invalid: contract_id invalid")
    provider = value.get("provider_module_id")
    if not isinstance(provider, str) or not MODULE_ID_RE.match(provider):
        raise ValueError("room_board_contract_invalid: provider_module_id invalid")
    kind = value.get("kind")
    if kind not in CONTRACT_KINDS:
        raise ValueError("room_board_contract_invalid: kind invalid")
    content = value.get("content")
    if not isinstance(content, str):
        raise ValueError("room_board_contract_invalid: content invalid")
    if len(content.encode("utf-8")) > MAX_CONTRACT_CONTENT_BYTES:
        raise ValueError("room_board_content_too_large")
    rationale = value.get("rationale", "")
    if not isinstance(rationale, str):
        raise ValueError("room_board_contract_invalid: rationale invalid")
    return {
        "contract_id": contract_id,
        "provider_module_id": provider,
        "kind": kind,
        "content": content,
        "rationale": rationale,
    }


def parse_contract_ref(value: Any) -> tuple[str, int | None]:
    """Split a ``contract_id`` or ``contract_id@version`` reference."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("room_board_contract_ref_invalid")
    ref = value.strip()
    if "@" in ref:
        contract_id, _, version_text = ref.rpartition("@")
        if (
            not CONTRACT_ID_RE.match(contract_id)
            or not version_text.isdigit()
            or int(version_text) <= 0
        ):
            raise ValueError("room_board_contract_ref_invalid")
        return contract_id, int(version_text)
    if not CONTRACT_ID_RE.match(ref):
        raise ValueError("room_board_contract_ref_invalid")
    return ref, None


def assign_cross_family_reviewer(
    *,
    author_participant_id: str,
    author_family: str,
    candidates: Sequence[dict[str, Any]],
    pending_loads: Mapping[str, int] | None = None,
    last_reviewer_id: str | None = None,
) -> str | None:
    """Pick a cross-family reviewer under rule ``cross_family/v1``.

    ``candidates`` holds active agent participants other than the author as
    ``{"participant_id": ..., "family": ...}`` (families are admitted
    ``cli_kind`` values).  Only candidates whose family differs from the
    author's are eligible; the author never reviews its own work and nobody
    volunteers.  Ordering is continuity (the module's last reviewer first),
    then fewest pending reviews assigned, then ``participant_id``.  None means
    no other family is present and a Human must review instead.
    """

    if not isinstance(author_participant_id, str) or not author_participant_id:
        raise ValueError("room_board_review_author_invalid")
    if not isinstance(author_family, str) or not author_family:
        raise ValueError("room_board_review_author_invalid")
    eligible: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        participant_id = entry.get("participant_id")
        family = entry.get("family")
        if not isinstance(participant_id, str) or not participant_id:
            continue
        if not isinstance(family, str) or not family:
            continue
        if participant_id == author_participant_id:
            continue
        if family == author_family:
            continue
        eligible.append({"participant_id": participant_id, "family": family})
    if not eligible:
        return None
    loads = dict(pending_loads) if isinstance(pending_loads, Mapping) else {}
    eligible_ids = {item["participant_id"] for item in eligible}
    if isinstance(last_reviewer_id, str) and last_reviewer_id and last_reviewer_id in eligible_ids:
        return last_reviewer_id

    def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
        raw = loads.get(item["participant_id"], 0)
        load = raw if isinstance(raw, int) and raw >= 0 else 0
        return (load, str(item["participant_id"]))

    return str(sorted(eligible, key=_sort_key)[0]["participant_id"])


def normalize_review_summary(value: Any) -> str:
    """Validate an untrusted review summary and return it trimmed.

    The summary is required for both verdicts: 1-4000 characters after
    trimming. A violation rejects the whole verdict, never truncates.
    """

    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > MAX_REVIEW_SUMMARY_CHARS
    ):
        raise ValueError("room_board_review_summary_invalid")
    return value.strip()


_REVIEW_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def normalize_review_path(value: Any) -> str | None:
    """Validate an untrusted review finding path, or return None for null.

    A present path is a repository-relative POSIX path: at most 512
    characters, no leading ``/``, no drive letter, no backslash, no ``.`` or
    ``..`` segment, no control characters and no Unicode format characters (Cf).
    A violation rejects the whole verdict, never truncates.
    """

    if value is None:
        return None
    if not is_valid_finding_path(value):
        raise ValueError("room_board_review_findings_invalid")
    return value


def normalize_review_findings(value: Any) -> list[dict[str, Any]]:
    """Validate untrusted review findings and return their canonical form."""

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REVIEW_FINDINGS:
        raise ValueError("room_board_review_findings_invalid")
    cleaned: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("room_board_review_findings_invalid")
        unknown = set(entry) - {"path", "severity", "text"}
        if unknown:
            raise ValueError("room_board_review_findings_invalid")
        severity = entry.get("severity")
        if severity not in BOARD_REVIEW_SEVERITIES:
            raise ValueError("room_board_review_findings_invalid")
        text = entry.get("text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.strip()) > MAX_REVIEW_FINDING_TEXT_CHARS
        ):
            raise ValueError("room_board_review_findings_invalid")
        finding: dict[str, Any] = {
            "severity": severity,
            "text": text.strip(),
        }
        clean_path = normalize_review_path(entry.get("path"))
        if clean_path is not None:
            finding["path"] = clean_path
        cleaned.append(finding)
    return cleaned


def normalize_review_verdict(verdict: Any, findings: Sequence[dict[str, Any]]) -> str:
    """Validate a review verdict against its findings."""

    if verdict not in BOARD_REVIEW_VERDICTS:
        raise ValueError("room_board_review_verdict_invalid")
    if verdict == "object" and not any(
        isinstance(item, dict) and item.get("severity") in ("blocker", "major") for item in findings
    ):
        raise ValueError(
            "room_board_review_findings_invalid: object requires a blocker_or_major finding"
        )
    return str(verdict)


# Bidirectional controls a reviewer must see rather than be steered by.
_REVIEW_BIDI_CONTROLS = frozenset(
    {
        0x061C,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    }
)

_REVIEW_MARKER_RE = re.compile(r"<U\+[0-9A-F]{4,}>")


def _is_hidden_review_char(code: int) -> bool:
    if code < 0x20 or 0x7F <= code <= 0x9F:
        return True
    return code in _REVIEW_BIDI_CONTROLS


def mark_hidden_characters(text: str) -> tuple[str, int]:
    """Make hidden characters visible for the operator review material route.

    Every C0/C1 control except ``\\n`` and ``\\t`` (this includes ESC, so ANSI
    escapes become visible), DEL, and every bidirectional control becomes
    ``<U+XXXX>`` (uppercase hex, at least 4 digits). Returns the marked text
    and the replacement count. This differs from ``AgentText`` sanitizing on
    purpose: a reviewer must see the code as it is (Trojan Source).
    """

    if not isinstance(text, str):
        raise ValueError("room_board_review_material_invalid")
    marked: list[str] = []
    count = 0
    for char in text:
        code = ord(char)
        if char in ("\n", "\t") or not _is_hidden_review_char(code):
            marked.append(char)
        else:
            marked.append(f"<U+{code:04X}>")
            count += 1
    return "".join(marked), count


def _truncate_marked_patch(marked: str, limit: int) -> tuple[str, bool]:
    """Cut marked patch text so its UTF-8 size fits ``limit`` bytes.

    Cuts only at a line boundary; when a single line alone exceeds the limit
    it cuts at a marker or code point boundary instead, never inside a marker
    or a code point. Returns the cut text and whether it was truncated.
    """

    if len(marked.encode("utf-8")) <= limit:
        return marked, False
    lines = marked.split("\n")
    parts: list[str] = []
    size = 0
    total = len(lines)
    for index, line in enumerate(lines):
        chunk = line if index == total - 1 else line + "\n"
        chunk_bytes = len(chunk.encode("utf-8"))
        if size + chunk_bytes > limit:
            break
        parts.append(chunk)
        size += chunk_bytes
    if parts:
        return "".join(parts), True
    head = lines[0] if lines else ""
    atoms: list[str] = []
    size = 0
    pos = 0
    for match in _REVIEW_MARKER_RE.finditer(head):
        for char in head[pos : match.start()]:
            char_bytes = len(char.encode("utf-8"))
            if size + char_bytes > limit:
                return "".join(atoms), True
            atoms.append(char)
            size += char_bytes
        marker = match.group(0)
        marker_bytes = len(marker.encode("utf-8"))
        if size + marker_bytes > limit:
            return "".join(atoms), True
        atoms.append(marker)
        size += marker_bytes
        pos = match.end()
    for char in head[pos:]:
        char_bytes = len(char.encode("utf-8"))
        if size + char_bytes > limit:
            break
        atoms.append(char)
        size += char_bytes
    return "".join(atoms), True


def _material_patch_parts(patch_text: str | None) -> tuple[str, int, bool, int]:
    """Return ``(text, bytes_total, truncated, hidden_char_count)`` for material."""

    raw = patch_text if isinstance(patch_text, str) else ""
    marked, hidden_char_count = mark_hidden_characters(raw)
    text, truncated = _truncate_marked_patch(marked, REVIEW_MATERIAL_PATCH_LIMIT_BYTES)
    return text, len(raw.encode("utf-8")), truncated, hidden_char_count


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def board_activity_content(activity_type: str, payload: dict[str, Any]) -> str:
    """Render the visible text of one board event.

    Delivery context and Skill selection read an activity's ``content``; a board
    event addressed to an owner must say what happened and what to do next.
    """

    if activity_type == "board.split_proposed":
        modules = ", ".join(str(item.get("module_id")) for item in payload.get("modules", []))
        return f"The lead proposed a module split ({modules}); it awaits operator approval."
    if activity_type == "board.split_rejected":
        return f"The operator rejected split {payload.get('split_id')}."
    if activity_type == "board.charter_assigned":
        charter = payload.get("charter") or {}
        contracts = ", ".join(
            f"{item.get('contract_id')}@v{item.get('version')}"
            for item in payload.get("contracts", [])
        )
        return (
            f"The operator approved the split: you now own module {payload.get('module_id')} "
            f"(charter v{payload.get('version')}, paths {', '.join(charter.get('paths', []))}; "
            f"provides {', '.join(charter.get('provides', [])) or 'nothing'}; depends on "
            f"{', '.join(charter.get('depends', [])) or 'nothing'}"
            + (f"; initial contracts {contracts}" if contracts else "")
            + "). Your charter and contracts are in .xmuse/. Read the board, claim the "
            "module, implement it inside its paths against the contracts, run its acceptance "
            "checks, commit, report progress, and submit your outcome."
        )
    if activity_type == "board.claimed":
        return f"Module {payload.get('module_id')} was claimed by its owner."
    if activity_type in {"board.contract_published", "board.contract_revised"}:
        verb = "revised" if activity_type == "board.contract_revised" else "published"
        rationale = payload.get("rationale") or ""
        return (
            f"Contract {payload.get('contract_id')} was {verb}: it is now version "
            f"{payload.get('version')} (provided by module {payload.get('provider_module_id')})."
            + (f" Rationale: {rationale}" if rationale else "")
            + " Read it (chat_room_board_read with contract_ref "
            f"'{payload.get('contract_id')}@{payload.get('version')}', or .xmuse/contracts/), "
            "realign the module you own to it, run its checks, commit, and report progress."
        )
    if activity_type == "board.progress":
        claims = "; ".join(str(item) for item in payload.get("claims", []))
        return (
            f"Progress on module {payload.get('module_id')}: {payload.get('status')} - "
            f"{payload.get('summary')}" + (f" Claims: {claims}" if claims else "")
        )
    if activity_type == "board.question":
        return f"Question for you: {payload.get('question')}"
    if activity_type == "board.verification":
        module_id = payload.get("module_id")
        status = payload.get("status")
        reason = payload.get("reason_code")
        if status == "passed":
            return (
                f"Module {module_id} verification passed: the host verified your "
                f"committed branch against the server gates ({reason or 'gates green'})."
            )
        if status == "failed":
            failing = [
                str(item.get("gate_id"))
                for item in payload.get("gates", [])
                if isinstance(item, dict) and item.get("status") != "passed"
            ]
            detail = f" Failing gates: {', '.join(failing)}." if failing else ""
            evidence = payload.get("evidence")
            tails = evidence.get("output_tails") if isinstance(evidence, dict) else None
            tail_text = ""
            if isinstance(tails, dict):
                for gate_id, tail in tails.items():
                    if isinstance(tail, str) and tail:
                        fence = "`" * max(
                            3, 1 + max((len(m) for m in re.findall(r"`+", tail)), default=0)
                        )
                        tail_text = f"\nOutput tail of {gate_id}:\n{fence}\n{tail}\n{fence}"
                        break
            return (
                f"Module {module_id} verification failed ({reason}).{detail} "
                "Fix the failure inside your charter paths, commit, and report "
                f"done again.{tail_text}"
            )
        return f"Module {module_id} verification {status} ({reason})."
    if activity_type == "board.review_requested":
        reviewer = payload.get("reviewer_participant_id") or "the operator"
        return (
            f"Module {payload.get('module_id')} passed verification "
            f"({payload.get('verification_id')}); {reviewer} must review it: read the "
            f"material with chat_room_board_read using review_id "
            f"{payload.get('review_id')}, judge it against the charter and contracts, "
            "and answer with chat_room_board_review."
        )
    if activity_type == "board.review":
        findings = payload.get("findings") or []
        count = len(findings) if isinstance(findings, list) else 0
        if payload.get("verdict") == "object":
            return (
                f"Module {payload.get('module_id')} review objected by "
                f"{payload.get('reviewer_participant_id')} ({count} findings): "
                f"{payload.get('summary') or ''} Fix inside your charter paths, "
                "commit, and report done again."
            )
        return (
            f"Module {payload.get('module_id')} review endorsed by "
            f"{payload.get('reviewer_participant_id') or payload.get('reviewer_kind')}: "
            f"{payload.get('summary') or ''}"
        )
    if activity_type == "board.integration":
        status = payload.get("status")
        integrated = payload.get("integrated_module_ids") or []
        waiting = payload.get("waiting_module_ids") or []
        conflicts = payload.get("conflicts") or []
        conflicted = [item.get("module_id") for item in conflicts if isinstance(item, dict)]
        if status == "integrated":
            detail = f"integrated {len(integrated)} module(s)"
            if conflicted:
                detail += f"; conflicted: {', '.join(str(item) for item in conflicted)}"
            if waiting:
                detail += f"; waiting: {', '.join(str(item) for item in waiting)}"
            return f"Integration {payload.get('integration_id')} {detail}."
        if status == "gate_failed":
            suspects = payload.get("suspect_module_ids") or []
            return (
                f"Integration {payload.get('integration_id')} failed its gates "
                f"(suspects: {', '.join(str(item) for item in suspects)}). "
                "The branch stays at the previous green head."
            )
        if status == "conflicted":
            return (
                f"Integration {payload.get('integration_id')} is conflicted "
                f"({payload.get('reason_code')}); the branch stays at the previous "
                "green head. Rework the conflicted modules inside their charter "
                "paths, commit, and report done again."
            )
        return (
            f"Integration {payload.get('integration_id')} ended "
            f"{status} ({payload.get('reason_code')})."
        )
    return activity_type


def _current_stamp(now: datetime | None) -> tuple[datetime, str]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("room_observation_now_timezone_required")
    return current, _timestamp(current)


class RoomBoardStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    @staticmethod
    def _activity_from_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["audience"] = _decode(value.pop("audience_json"))
        value["payload"] = _decode(value.pop("payload_json"))
        return value

    def _activity_from_conn(self, conn: sqlite3.Connection, activity_id: str) -> dict[str, Any]:
        row = conn.execute(
            "select * from room_activities where activity_id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            raise KeyError(activity_id)
        return self._activity_from_row(row)

    @staticmethod
    def _lead_participant_id(conn: sqlite3.Connection, conversation_id: str) -> str | None:
        policy = collaboration_policy_row(conn, conversation_id)
        if policy is None:
            return None
        lead = policy["lead_participant_id"]
        return str(lead) if lead is not None else None

    @staticmethod
    def _get_participant_conn(
        conn: sqlite3.Connection, *, conversation_id: str, participant_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "select * from participants where conversation_id = ? and participant_id = ?",
            (conversation_id, participant_id),
        ).fetchone()
        if row is None:
            raise ValueError("room_observation_actor_forbidden")
        if row["status"] != "active" or row["cli_kind"] not in ROOM_AGENT_CLI_KINDS:
            raise ValueError("room_participant_not_active")
        return row

    @staticmethod
    def _check_caller_binding(caller_identity: str, participant_id: str) -> None:
        if not isinstance(caller_identity, str) or not caller_identity:
            raise ValueError("room_observation_actor_forbidden")
        if caller_identity.startswith("god:"):
            bound = caller_identity[4:].rpartition(":")[2]
            if not bound or bound != participant_id:
                raise ValueError("room_observation_actor_forbidden")

    def _check_lease_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        current: datetime,
    ) -> tuple[sqlite3.Row, dict[str, Any]]:
        self._get_participant_conn(
            conn, conversation_id=conversation_id, participant_id=participant_id
        )
        self._check_caller_binding(caller_identity, participant_id)
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ValueError("room_observation_lease_lost")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_observation_lease_lost")
        canonical_id = canonical_observation_id(conn, observation_id)
        row = conn.execute(
            "select * from room_observations where observation_id = ?", (canonical_id,)
        ).fetchone()
        if (
            row is None
            or row["conversation_id"] != conversation_id
            or row["participant_id"] != participant_id
            or row["status"] != "claimed"
            or row["control_state"] != "active"
            or row["lease_token"] != lease_token
            or not row["expires_at"]
            or _parse_timestamp(str(row["expires_at"])) <= current
        ):
            raise ValueError("room_observation_lease_lost")
        # Same attempt fence as lease renewal: only the live current attempt that
        # holds this exact token may coordinate; a failed attempt may not.
        attempt = (
            conn.execute(
                "select state, lease_token_digest from room_observation_attempts "
                "where attempt_id = ?",
                (row["current_attempt_id"],),
            ).fetchone()
            if row["current_attempt_id"]
            else None
        )
        if (
            attempt is None
            or attempt["state"] not in {"claimed", "delivering"}
            or attempt["lease_token_digest"] != sha256(lease_token.encode()).hexdigest()
        ):
            raise ValueError("room_observation_lease_lost")
        source = self._activity_from_conn(conn, str(row["activity_id"]))
        return row, source

    @staticmethod
    def _check_idempotency_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        prior = conn.execute(
            """select result_json from chat_request_log
               where conversation_id = ? and tool_name = ?
                 and caller_identity = ? and client_request_id = ?""",
            (conversation_id, tool_name, caller_identity, client_request_id),
        ).fetchone()
        if prior is None:
            return None
        result = json.loads(str(prior["result_json"]))
        if result.get("request_fingerprint") != fingerprint:
            raise ValueError("room_board_idempotency_conflict")
        return result

    @staticmethod
    def _write_request_log_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        result: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """insert into chat_request_log
               (id, conversation_id, tool_name, caller_identity, client_request_id,
                result_json, created_at) values (?, ?, ?, ?, ?, ?, ?)""",
            (
                _id("req"),
                conversation_id,
                tool_name,
                caller_identity,
                client_request_id,
                _json(result),
                created_at,
            ),
        )

    def _insert_board_activity_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        activity_type: str,
        actor_kind: str,
        actor_identity: str,
        actor_participant_id: str | None,
        causation_id: str,
        causal_depth: int,
        audience_participant_ids: list[str],
        payload: dict[str, Any],
        stamp: str,
    ) -> dict[str, Any]:
        seq = int(
            conn.execute(
                "select coalesce(max(seq), 0) + 1 from room_activities where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )
        activity_id = _id("activity")
        correlation_id = f"board_correlation_{sha256(activity_id.encode()).hexdigest()}"
        payload = {**payload, "content": board_activity_content(activity_type, payload)}
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, materialized_message_id,
                causal_depth, materialized_proposal_id, delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'room', ?, ?, null, ?, null,
                       'active', ?)""",
            (
                activity_id,
                conversation_id,
                seq,
                activity_type,
                actor_kind,
                actor_identity,
                actor_participant_id,
                causation_id,
                correlation_id,
                _json(
                    {
                        "type": "board",
                        "conversation_id": conversation_id,
                        "participant_ids": list(audience_participant_ids),
                    }
                ),
                _json(payload),
                causal_depth,
                stamp,
            ),
        )
        return self._activity_from_conn(conn, activity_id)

    @staticmethod
    def _wake_participants_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        activity_id: str,
        participant_ids: list[str],
        stamp: str,
        priority: int = 100,
    ) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for participant_id in dict.fromkeys(participant_ids):
            observation_id = _id("observation")
            conn.execute(
                """insert into room_observations
                   (observation_id, conversation_id, activity_id, participant_id,
                    priority, delivery_mode, status, attempt_count, created_at, updated_at)
                   values (?, ?, ?, ?, ?, 'active', 'pending', 0, ?, ?)""",
                (
                    observation_id,
                    conversation_id,
                    activity_id,
                    participant_id,
                    priority,
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                """insert or ignore into room_participant_cursors
                   (conversation_id, participant_id, last_acknowledged_seq, updated_at)
                   values (?, ?, 0, ?)""",
                (conversation_id, participant_id, stamp),
            )
            observations.append(
                {
                    "observation_id": observation_id,
                    "conversation_id": conversation_id,
                    "activity_id": activity_id,
                    "participant_id": participant_id,
                    "priority": priority,
                    "status": "pending",
                }
            )
        return observations

    @staticmethod
    def _current_charter_conn(
        conn: sqlite3.Connection, *, conversation_id: str, module_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """select * from room_board_charters
               where conversation_id = ? and module_id = ?
               order by version desc limit 1""",
            (conversation_id, module_id),
        ).fetchone()

    @staticmethod
    def _active_charter_owner_map(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            "select * from room_board_charters where conversation_id = ? order by module_id",
            (conversation_id,),
        ).fetchall()
        current: dict[str, sqlite3.Row] = {}
        for row in rows:
            key = str(row["module_id"])
            if key not in current or int(row["version"]) > int(current[key]["version"]):
                current[key] = row
        return {
            module_id: {
                "owner_participant_id": str(row["owner_participant_id"]),
                "status": str(row["status"]),
                "version": int(row["version"]),
                "charter": _decode(str(row["charter_json"])),
            }
            for module_id, row in current.items()
        }

    @staticmethod
    def _latest_contract_conn(
        conn: sqlite3.Connection, *, conversation_id: str, contract_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            """select * from room_board_contracts
               where conversation_id = ? and contract_id = ?
               order by version desc limit 1""",
            (conversation_id, contract_id),
        ).fetchone()

    def read(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_ref: str | None = None,
        review_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
                charter_rows = {
                    str(row["module_id"]): row
                    for row in conn.execute(
                        "select * from room_board_charters where conversation_id = ? "
                        "order by module_id, version",
                        (conversation_id,),
                    ).fetchall()
                }
                charters = []
                for module_id, info in sorted(charter_map.items()):
                    charter_row = charter_rows.get(module_id)
                    lifecycle: str | None = None
                    state: str | None = None
                    if charter_row is not None:
                        lifecycle, state = self._module_lifecycle_state_conn(
                            conn,
                            conversation_id=conversation_id,
                            module_id=module_id,
                            charter_row=charter_row,
                        )
                    charters.append(
                        {
                            "module_id": module_id,
                            "version": info["version"],
                            "owner_participant_id": info["owner_participant_id"],
                            "status": info["status"],
                            "charter": info["charter"],
                            "lifecycle": lifecycle,
                            "state": state,
                        }
                    )
                contract_rows = conn.execute(
                    "select * from room_board_contracts where conversation_id = ? "
                    "order by contract_id, version",
                    (conversation_id,),
                ).fetchall()
                latest: dict[str, sqlite3.Row] = {}
                for row in contract_rows:
                    latest[str(row["contract_id"])] = row
                contracts = [
                    {
                        "contract_id": str(row["contract_id"]),
                        "version": int(row["version"]),
                        "digest": str(row["digest"]),
                        "provider_module_id": str(row["provider_module_id"]),
                        "kind": str(row["kind"]),
                    }
                    for _, row in sorted(latest.items())
                ]
                cursor_row = conn.execute(
                    "select last_seen_seq from room_board_cursors "
                    "where conversation_id = ? and participant_id = ?",
                    (conversation_id, participant_id),
                ).fetchone()
                cursor_seq = int(cursor_row["last_seen_seq"]) if cursor_row else 0
                candidate_rows = conn.execute(
                    """select * from room_activities
                       where conversation_id = ? and seq > ?
                         and activity_type like 'board.%'
                       order by seq""",
                    (conversation_id, cursor_seq),
                ).fetchall()
                inbox: list[dict[str, Any]] = []
                # The cursor advances past every scanned activity, not only the
                # ones addressed to the caller, so foreign traffic never stalls it.
                last_scanned_seq = cursor_seq
                for row in candidate_rows:
                    activity = self._activity_from_row(row)
                    audience = activity.get("audience")
                    recipients = (
                        audience.get("participant_ids")
                        if isinstance(audience, dict) and audience.get("type") == "board"
                        else None
                    )
                    if isinstance(recipients, list) and participant_id in recipients:
                        if len(inbox) >= BOARD_INBOX_LIMIT:
                            break
                        inbox.append(activity)
                    last_scanned_seq = int(activity["seq"])
                if last_scanned_seq > cursor_seq:
                    last_seq = last_scanned_seq
                    conn.execute(
                        """insert into room_board_cursors
                           (conversation_id, participant_id, last_seen_seq, updated_at)
                           values (?, ?, ?, ?)
                           on conflict(conversation_id, participant_id) do update set
                             last_seen_seq = max(last_seen_seq, excluded.last_seen_seq),
                             updated_at = excluded.updated_at""",
                        (conversation_id, participant_id, last_seq, stamp),
                    )
                    cursor_seq = last_seq
                contract: dict[str, Any] | None = None
                if contract_ref is not None:
                    wanted_id, wanted_version = parse_contract_ref(contract_ref)
                    if wanted_version is None:
                        found = self._latest_contract_conn(
                            conn, conversation_id=conversation_id, contract_id=wanted_id
                        )
                    else:
                        found = conn.execute(
                            """select * from room_board_contracts
                               where conversation_id = ? and contract_id = ?
                                 and version = ?""",
                            (conversation_id, wanted_id, wanted_version),
                        ).fetchone()
                    if found is None:
                        raise ValueError("room_board_contract_unknown")
                    contract = {
                        "contract_id": str(found["contract_id"]),
                        "version": int(found["version"]),
                        "provider_module_id": str(found["provider_module_id"]),
                        "kind": str(found["kind"]),
                        "content": str(found["content"]),
                        "digest": str(found["digest"]),
                        "author_participant_id": str(found["author_participant_id"]),
                        "rationale": found["rationale"],
                        "activity_id": found["activity_id"],
                        "created_at": str(found["created_at"]),
                    }
                conn.commit()
                result: dict[str, Any] = {
                    "charters": charters,
                    "contracts": contracts,
                    "inbox": inbox,
                    "contract": contract,
                    "cursor_seq": cursor_seq,
                }
                if review_id is not None:
                    result["review_material"] = self._review_material_conn(
                        conn,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        review_id=review_id,
                    )
                return result
            except Exception:
                conn.rollback()
                raise

    def propose_split(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        modules: list[dict[str, Any]],
        assignments: dict[str, str],
        contracts: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(modules, list) or not modules:
            raise ValueError("room_board_modules_required")
        normalized_modules = [normalize_charter(item) for item in modules]
        module_ids = [item["module_id"] for item in normalized_modules]
        if len(set(module_ids)) != len(module_ids):
            raise ValueError("room_board_module_duplicate")
        if not isinstance(assignments, dict) or set(assignments) != set(module_ids):
            raise ValueError("room_board_assignment_invalid")
        for assignee in assignments.values():
            if not isinstance(assignee, str) or not assignee.strip():
                raise ValueError("room_board_assignment_invalid")
        if not isinstance(contracts, list):
            raise ValueError("room_board_contract_invalid: contracts must be a list")
        normalized_contracts = [normalize_split_contract(item) for item in contracts]
        contract_ids = [item["contract_id"] for item in normalized_contracts]
        if len(set(contract_ids)) != len(contract_ids):
            raise ValueError("room_board_contract_duplicate")
        for spec in normalized_contracts:
            if spec["provider_module_id"] not in module_ids:
                raise ValueError("room_board_contract_provider_unknown")
        for charter in normalized_modules:
            for wanted in charter["provides"]:
                if not any(
                    spec["contract_id"] == wanted
                    and spec["provider_module_id"] == charter["module_id"]
                    for spec in normalized_contracts
                ):
                    raise ValueError("room_board_contract_missing")
        cycle = split_dependency_cycle(normalized_modules, normalized_contracts)
        if cycle is not None:
            raise ValueError(f"room_board_split_dependency_cycle: {' -> '.join(cycle)}")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_PROPOSE_SPLIT,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "modules": normalized_modules,
                    "assignments": assignments,
                    "contracts": normalized_contracts,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PROPOSE_SPLIT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                if self._lead_participant_id(conn, conversation_id) != participant_id:
                    raise ValueError("room_board_lead_required")
                report_targets = [
                    str(item["report_to"]) for item in normalized_modules if item["report_to"]
                ]
                for assignee in [*assignments.values(), *report_targets]:
                    row = conn.execute(
                        "select * from participants "
                        "where conversation_id = ? and participant_id = ?",
                        (conversation_id, assignee),
                    ).fetchone()
                    if row is None:
                        raise ValueError("room_board_assignee_unknown")
                    if row["status"] != "active" or row["cli_kind"] not in ROOM_AGENT_CLI_KINDS:
                        raise ValueError("room_board_assignee_inactive")
                # At most one split awaits approval: a newer proposal (for example
                # from a retried lead attempt) supersedes any older pending one.
                conn.execute(
                    "update room_board_splits set status = 'superseded', decided_at = ? "
                    "where conversation_id = ? and status = 'proposed'",
                    (stamp, conversation_id),
                )
                split_id = _id("split")
                payload_contracts = [
                    {
                        "contract_id": spec["contract_id"],
                        "provider_module_id": spec["provider_module_id"],
                        "kind": spec["kind"],
                        "digest": contract_digest(spec["content"]),
                        "rationale": spec["rationale"],
                    }
                    for spec in normalized_contracts
                ]
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.split_proposed",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "split_id": split_id,
                        "modules": normalized_modules,
                        "assignments": assignments,
                        "contracts": payload_contracts,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_splits
                       (split_id, conversation_id, proposed_by_participant_id, status,
                        split_json, activity_id, approved_by, decided_at, created_at)
                       values (?, ?, ?, 'proposed', ?, ?, null, null, ?)""",
                    (
                        split_id,
                        conversation_id,
                        participant_id,
                        _json(
                            {
                                "modules": normalized_modules,
                                "assignments": assignments,
                                "contracts": normalized_contracts,
                            }
                        ),
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                result = {
                    "split_id": split_id,
                    "status": "proposed",
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "modules": list(module_ids),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PROPOSE_SPLIT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def decide_split(
        self,
        *,
        conversation_id: str,
        split_id: str,
        decision: str,
        operator_identity: str,
        decided_via: str = "web",
        grant_id: str | None = None,
        expected_digest: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if decision not in ("approve", "reject"):
            raise ValueError("room_board_decision_invalid")
        if not isinstance(operator_identity, str) or not operator_identity.strip():
            raise ValueError("room_operator_identity_required")
        if not isinstance(decided_via, str) or not DECIDED_VIA_RE.match(decided_via):
            raise ValueError("room_board_decided_via_invalid")
        if decided_via.startswith("plugin:"):
            if not isinstance(grant_id, str) or not grant_id:
                raise ValueError(
                    "room_board_grant_id_invalid: grant_id required for plugin decisions"
                )
        elif grant_id is not None:
            raise ValueError("room_board_grant_id_invalid: grant_id only for plugin decisions")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                split = conn.execute(
                    "select * from room_board_splits where split_id = ? and conversation_id = ?",
                    (split_id, conversation_id),
                ).fetchone()
                if split is None:
                    raise ValueError("room_board_split_unknown")
                if str(split["status"]) != "proposed":
                    raise ValueError("room_board_split_decided")
                proposal = self._activity_from_conn(conn, str(split["activity_id"]))
                bundle = _decode(str(split["split_json"]))
                if expected_digest is not None and expected_digest != split_digest(bundle):
                    raise ValueError("room_board_split_digest_mismatch")
                normalized_modules = list(bundle["modules"])
                assignments = dict(bundle["assignments"])
                normalized_contracts = list(bundle["contracts"])
                if decision == "reject":
                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_type="board.split_rejected",
                        actor_kind="operator",
                        actor_identity=operator_identity,
                        actor_participant_id=None,
                        causation_id=str(split["activity_id"]),
                        causal_depth=int(proposal["causal_depth"]) + 1,
                        audience_participant_ids=[str(split["proposed_by_participant_id"])],
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "split_id": split_id,
                            "decision": "rejected",
                            "decided_via": decided_via,
                            "grant_id": grant_id,
                        },
                        stamp=stamp,
                    )
                    conn.execute(
                        "update room_board_splits set status = 'rejected', "
                        "approved_by = ?, decided_at = ? "
                        "where split_id = ? and conversation_id = ?",
                        (operator_identity, stamp, split_id, conversation_id),
                    )
                    conn.commit()
                    return {
                        "split_id": split_id,
                        "status": "rejected",
                        "activity_id": str(activity["activity_id"]),
                        "activity_seq": int(activity["seq"]),
                    }
                for charter in normalized_modules:
                    existing = conn.execute(
                        """select 1 from room_board_charters
                           where conversation_id = ? and module_id = ?
                             and status = 'active' limit 1""",
                        (conversation_id, charter["module_id"]),
                    ).fetchone()
                    if existing is not None:
                        raise ValueError("room_board_charter_active")
                activity_ids: list[str] = []
                for charter in normalized_modules:
                    module_id = str(charter["module_id"])
                    owner = str(assignments[module_id])
                    conn.execute(
                        """insert into room_board_charters
                           (conversation_id, module_id, version, split_id,
                            owner_participant_id, status, charter_json, claimed_at,
                            created_at)
                           values (?, ?, 1, ?, ?, 'active', ?, null, ?)""",
                        (
                            conversation_id,
                            module_id,
                            split_id,
                            owner,
                            _json(charter),
                            stamp,
                        ),
                    )
                    module_contracts = [
                        spec
                        for spec in normalized_contracts
                        if spec["provider_module_id"] == module_id
                    ]
                    for spec in module_contracts:
                        conn.execute(
                            """insert into room_board_contracts
                               (conversation_id, contract_id, version, provider_module_id,
                                kind, content, digest, author_participant_id, rationale,
                                activity_id, created_at)
                               values (?, ?, 1, ?, ?, ?, ?, ?, ?, null, ?)""",
                            (
                                conversation_id,
                                spec["contract_id"],
                                module_id,
                                spec["kind"],
                                spec["content"],
                                contract_digest(spec["content"]),
                                owner,
                                spec["rationale"],
                                stamp,
                            ),
                        )
                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_type="board.charter_assigned",
                        actor_kind="operator",
                        actor_identity=operator_identity,
                        actor_participant_id=None,
                        causation_id=str(split["activity_id"]),
                        causal_depth=int(proposal["causal_depth"]) + 1,
                        audience_participant_ids=[owner],
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "split_id": split_id,
                            "module_id": module_id,
                            "version": 1,
                            "owner_participant_id": owner,
                            "decided_via": decided_via,
                            "grant_id": grant_id,
                            "charter": charter,
                            "contracts": [
                                {
                                    "contract_id": spec["contract_id"],
                                    "version": 1,
                                    "digest": contract_digest(spec["content"]),
                                    "kind": spec["kind"],
                                    "provider_module_id": module_id,
                                }
                                for spec in module_contracts
                            ],
                        },
                        stamp=stamp,
                    )
                    activity_ids.append(str(activity["activity_id"]))
                    for spec in module_contracts:
                        conn.execute(
                            "update room_board_contracts set activity_id = ? "
                            "where conversation_id = ? and contract_id = ? and version = 1",
                            (str(activity["activity_id"]), conversation_id, spec["contract_id"]),
                        )
                    self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=[owner],
                        stamp=stamp,
                    )
                conn.execute(
                    "update room_board_splits set status = 'approved', approved_by = ?, "
                    "decided_at = ? where split_id = ? and conversation_id = ?",
                    (operator_identity, stamp, split_id, conversation_id),
                )
                conn.commit()
                return {
                    "split_id": split_id,
                    "status": "approved",
                    "modules": [str(item["module_id"]) for item in normalized_modules],
                    "contracts": [
                        {"contract_id": str(spec["contract_id"]), "version": 1}
                        for spec in normalized_contracts
                    ],
                    "activity_ids": activity_ids,
                }
            except Exception:
                conn.rollback()
                raise

    def claim(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(module_id, str) or not module_id:
            raise ValueError("room_board_module_unknown")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_CLAIM,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "module_id": module_id,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_CLAIM,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                if charter is None or str(charter["status"]) != "active":
                    raise ValueError("room_board_module_unknown")
                if str(charter["owner_participant_id"]) != participant_id:
                    raise ValueError("room_board_not_owner")
                version = int(charter["version"])
                if charter["claimed_at"] is not None:
                    original = self._find_claim_activity_conn(
                        conn,
                        conversation_id=conversation_id,
                        module_id=module_id,
                        version=version,
                    )
                    result = {
                        "module_id": module_id,
                        "version": version,
                        "claimed_at": str(charter["claimed_at"]),
                        "activity_id": original,
                        "activity_seq": None,
                        "request_fingerprint": fingerprint,
                    }
                    if original is not None:
                        try:
                            activity = self._activity_from_conn(conn, original)
                            result["activity_seq"] = int(activity["seq"])
                        except KeyError:
                            pass
                    self._write_request_log_conn(
                        conn,
                        conversation_id=conversation_id,
                        tool_name=TOOL_CLAIM,
                        caller_identity=caller_identity,
                        client_request_id=client_request_id,
                        result=result,
                        created_at=stamp,
                    )
                    conn.commit()
                    return result
                conn.execute(
                    """update room_board_charters set claimed_at = ?
                       where conversation_id = ? and module_id = ? and version = ?""",
                    (stamp, conversation_id, module_id, version),
                )
                lead = self._lead_participant_id(conn, conversation_id)
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.claimed",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[lead] if lead else [participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "module_id": module_id,
                        "version": version,
                        "owner_participant_id": participant_id,
                    },
                    stamp=stamp,
                )
                result = {
                    "module_id": module_id,
                    "version": version,
                    "claimed_at": stamp,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_CLAIM,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _find_claim_activity_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        module_id: str,
        version: int,
    ) -> str | None:
        rows = conn.execute(
            """select activity_id, payload_json from room_activities
               where conversation_id = ? and activity_type = 'board.claimed'
               order by seq desc limit 20""",
            (conversation_id,),
        ).fetchall()
        for row in rows:
            payload = _decode(str(row["payload_json"]))
            if (
                isinstance(payload, dict)
                and payload.get("module_id") == module_id
                and int(payload.get("version", -1)) == version
            ):
                return str(row["activity_id"])
        return None

    def publish_contract(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_id: str,
        kind: str,
        content: str,
        base_version: int | None,
        rationale: str = "",
        provider_module_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(contract_id, str) or not CONTRACT_ID_RE.match(contract_id):
            raise ValueError("room_board_contract_id_invalid")
        if kind not in CONTRACT_KINDS:
            raise ValueError("room_board_contract_kind_invalid")
        if not isinstance(content, str):
            raise ValueError("room_board_contract_invalid: content invalid")
        if len(content.encode("utf-8")) > MAX_CONTRACT_CONTENT_BYTES:
            raise ValueError("room_board_content_too_large")
        if base_version is not None and (
            isinstance(base_version, bool) or not isinstance(base_version, int) or base_version <= 0
        ):
            raise ValueError("room_board_contract_version_invalid")
        if not isinstance(rationale, str):
            raise ValueError("room_board_contract_invalid: rationale invalid")
        if provider_module_id is not None and (
            not isinstance(provider_module_id, str) or not MODULE_ID_RE.match(provider_module_id)
        ):
            raise ValueError("room_board_contract_provider_invalid")
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_PUBLISH_CONTRACT,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "contract_id": contract_id,
                    "kind": kind,
                    "content": content,
                    "base_version": base_version,
                    "rationale": rationale,
                    "provider_module_id": provider_module_id,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PUBLISH_CONTRACT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                lead = self._lead_participant_id(conn, conversation_id)
                is_lead = lead is not None and lead == participant_id
                latest = self._latest_contract_conn(
                    conn, conversation_id=conversation_id, contract_id=contract_id
                )
                if base_version is None:
                    if latest is not None:
                        raise ValueError(
                            "room_board_contract_conflict: contract "
                            f"{contract_id} already at version {int(latest['version'])}"
                        )
                    provider = self._resolve_new_contract_provider_conn(
                        conn,
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        contract_id=contract_id,
                        provider_module_id=provider_module_id,
                        is_lead=is_lead,
                    )
                    version = 1
                else:
                    if latest is None:
                        raise ValueError("room_board_contract_unknown")
                    if int(latest["version"]) != base_version:
                        raise ValueError(
                            "room_board_contract_conflict: contract "
                            f"{contract_id} latest version is {int(latest['version'])}"
                        )
                    provider = str(latest["provider_module_id"])
                    if not is_lead:
                        owner_row = self._current_charter_conn(
                            conn, conversation_id=conversation_id, module_id=provider
                        )
                        if (
                            owner_row is None
                            or str(owner_row["status"]) != "active"
                            or str(owner_row["owner_participant_id"]) != participant_id
                        ):
                            raise ValueError("room_board_not_owner")
                    version = int(latest["version"]) + 1
                digest = contract_digest(content)
                audience = self._dependent_owner_ids_conn(
                    conn,
                    conversation_id=conversation_id,
                    contract_id=contract_id,
                    exclude_participant_id=participant_id,
                )
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type=(
                        "board.contract_published" if version == 1 else "board.contract_revised"
                    ),
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=audience,
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "contract_id": contract_id,
                        "version": version,
                        "digest": digest,
                        "provider_module_id": provider,
                        "kind": kind,
                        "rationale": rationale,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_contracts
                       (conversation_id, contract_id, version, provider_module_id,
                        kind, content, digest, author_participant_id, rationale,
                        activity_id, created_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        conversation_id,
                        contract_id,
                        version,
                        provider,
                        kind,
                        content,
                        digest,
                        participant_id,
                        rationale,
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                self._wake_participants_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_id=str(activity["activity_id"]),
                    participant_ids=audience,
                    stamp=stamp,
                )
                result = {
                    "contract_id": contract_id,
                    "version": version,
                    "digest": digest,
                    "provider_module_id": provider,
                    "kind": kind,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_PUBLISH_CONTRACT,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _resolve_new_contract_provider_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
        contract_id: str,
        provider_module_id: str | None,
        is_lead: bool,
    ) -> str:
        charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
        owned_providing = sorted(
            module_id
            for module_id, info in charter_map.items()
            if info["owner_participant_id"] == participant_id
            and info["status"] == "active"
            and contract_id in (info["charter"].get("provides", []))
        )
        if provider_module_id is not None:
            info = charter_map.get(provider_module_id)
            if info is None or info["status"] != "active":
                raise ValueError("room_board_module_unknown")
            if not is_lead and (
                info["owner_participant_id"] != participant_id
                or contract_id not in info["charter"].get("provides", [])
            ):
                raise ValueError("room_board_not_owner")
            return provider_module_id
        if owned_providing:
            return owned_providing[0]
        if is_lead:
            raise ValueError("room_board_contract_provider_required")
        raise ValueError("room_board_not_owner")

    def _dependent_owner_ids_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        contract_id: str,
        exclude_participant_id: str,
    ) -> list[str]:
        charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
        owners: list[str] = []
        for module_id in sorted(charter_map):
            info = charter_map[module_id]
            if info["status"] != "active":
                continue
            charter = info["charter"]
            depends = charter.get("depends", []) if isinstance(charter, dict) else []
            owner = str(info["owner_participant_id"])
            if contract_id in depends and owner != exclude_participant_id and owner not in owners:
                owners.append(owner)
        return owners

    def report_progress(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
        status: str,
        summary: str,
        claims: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(module_id, str) or not module_id:
            raise ValueError("room_board_module_unknown")
        if status not in PROGRESS_STATUSES:
            raise ValueError("room_board_status_invalid")
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            raise ValueError("room_board_summary_invalid")
        clean_claims = self._normalize_progress_claims(claims)
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_REPORT_PROGRESS,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "module_id": module_id,
                    "status": status,
                    "summary": summary,
                    "claims": clean_claims,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REPORT_PROGRESS,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                if charter is None or str(charter["status"]) != "active":
                    raise ValueError("room_board_module_unknown")
                if str(charter["owner_participant_id"]) != participant_id:
                    raise ValueError("room_board_not_owner")
                charter_body = _decode(str(charter["charter_json"]))
                report_to = (
                    charter_body.get("report_to") if isinstance(charter_body, dict) else None
                )
                lead = self._lead_participant_id(conn, conversation_id)
                recipient = report_to or lead
                progress_id = _id("progress")
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.progress",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[recipient] if recipient else [],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "progress_id": progress_id,
                        "module_id": module_id,
                        "status": status,
                        "summary": summary,
                        "claims": clean_claims,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    """insert into room_board_progress
                       (progress_id, conversation_id, module_id, participant_id,
                        status, summary, claims_json, activity_id, created_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        progress_id,
                        conversation_id,
                        module_id,
                        participant_id,
                        status,
                        summary,
                        _json(clean_claims),
                        str(activity["activity_id"]),
                        stamp,
                    ),
                )
                woken: list[dict[str, Any]] = []
                if status in WAKE_STATUSES and recipient:
                    woken = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=[recipient],
                        stamp=stamp,
                    )
                verification_id: str | None = None
                if status == "done":
                    # A newer done claim supersedes older still-pending jobs; a
                    # running job whose result arrives late is dropped as stale.
                    conn.execute(
                        "update room_board_verifications set status = 'superseded', "
                        "lease_owner = null, lease_token = null, lease_expires_at = null, "
                        "updated_at = ? where conversation_id = ? and module_id = ? "
                        "and status = 'pending'",
                        (stamp, conversation_id, module_id),
                    )
                    conn.execute(
                        "update room_board_reviews set status = 'superseded', "
                        "updated_at = ? where conversation_id = ? and module_id = ? "
                        "and status = 'pending'",
                        (stamp, conversation_id, module_id),
                    )
                    verification_id = _id("boardverify")
                    conn.execute(
                        """insert into room_board_verifications
                           (verification_id, conversation_id, module_id, participant_id,
                            progress_id, status, attempt_count, changed_paths_json,
                            created_at, updated_at)
                           values (?, ?, ?, ?, ?, 'pending', 0, '[]', ?, ?)""",
                        (
                            verification_id,
                            conversation_id,
                            module_id,
                            participant_id,
                            progress_id,
                            stamp,
                            stamp,
                        ),
                    )
                result = {
                    "progress_id": progress_id,
                    "module_id": module_id,
                    "status": status,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken],
                    "verification_id": verification_id,
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REPORT_PROGRESS,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _verification_view(row: sqlite3.Row) -> dict[str, Any]:
        mapping = dict(row)
        return {
            "verification_id": str(row["verification_id"]),
            "conversation_id": str(row["conversation_id"]),
            "module_id": str(row["module_id"]),
            "participant_id": str(row["participant_id"]),
            "progress_id": str(row["progress_id"]),
            "status": str(row["status"]),
            "attempt_count": int(row["attempt_count"]),
            "lease_token": row["lease_token"],
            "lease_expires_at": row["lease_expires_at"],
            "head_commit": row["head_commit"],
            "patch_digest": row["patch_digest"],
            "changed_paths": _decode(str(row["changed_paths_json"] or "[]")),
            "result": _decode(row["result_json"]) if row["result_json"] else None,
            "activity_id": row["activity_id"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "not_before": mapping.get("not_before"),
        }

    @staticmethod
    def _module_verification_stats_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, dict[str, Any]]:
        """Summarize verification state per module (latest row plus counters)."""

        try:
            ver_rows = conn.execute(
                "select * from room_board_verifications where conversation_id = ? "
                "order by created_at, verification_id",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        by_module: dict[str, list[sqlite3.Row]] = {}
        for row in ver_rows:
            by_module.setdefault(str(row["module_id"]), []).append(row)
        try:
            done_rows = conn.execute(
                "select module_id, count(*) as total from room_board_progress "
                "where conversation_id = ? and status = 'done' group by module_id",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            done_rows = []
        done_reports = {str(row["module_id"]): int(row["total"]) for row in done_rows}
        stats: dict[str, dict[str, Any]] = {}
        for module_id, rows in by_module.items():
            latest = rows[-1]
            counters = compute_counters(
                [str(row["status"]) for row in rows],
                done_reports=done_reports.get(module_id, 0),
            )
            latest_result = _decode(latest["result_json"]) if latest["result_json"] else None
            stats[module_id] = {
                "status": str(latest["status"]),
                "verification_id": str(latest["verification_id"]),
                "reason_code": (
                    latest_result.get("reason_code") if isinstance(latest_result, dict) else None
                ),
                "result": latest_result,
                "head_commit": latest["head_commit"],
                "changed_paths": _decode(str(latest["changed_paths_json"] or "[]")),
                "created_at": str(latest["created_at"]),
                "done_reports": counters["done_reports"],
                "verifications_passed": counters["passed"],
                "verifications_failed": counters["failed"],
                "rework_rounds": counters["rework_rounds"],
            }
        return stats

    @staticmethod
    def _module_lifecycle_state_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        module_id: str,
        charter_row: sqlite3.Row,
    ) -> tuple[str, str]:
        """Derive (lifecycle, state) with the projection's pure functions."""

        owner = str(charter_row["owner_participant_id"])
        progress_rows = conn.execute(
            "select * from room_board_progress where conversation_id = ? and module_id = ? "
            "order by created_at, rowid",
            (conversation_id, module_id),
        ).fetchall()
        reports = [
            ProgressFact(
                status=str(row["status"]),
                participant_id=str(row["participant_id"]),
                created_at=str(row["created_at"]),
                seq=0,
            )
            for row in progress_rows
        ]
        verification_rows = conn.execute(
            "select * from room_board_verifications where conversation_id = ? and module_id = ? "
            "order by created_at, rowid",
            (conversation_id, module_id),
        ).fetchall()
        jobs = []
        for row in verification_rows:
            decoded_result = _decode(row["result_json"]) if row["result_json"] else None
            reason = (
                decoded_result.get("reason_code")
                if isinstance(decoded_result, dict)
                and isinstance(decoded_result.get("reason_code"), str)
                else None
            )
            jobs.append(
                VerificationFact(
                    verification_id=str(row["verification_id"]),
                    status=str(row["status"]),
                    reason_code=reason,
                    created_at=str(row["created_at"]),
                )
            )
        claimed_at = charter_row["claimed_at"]
        lifecycle = derive_lifecycle(
            claimed_at=None if claimed_at is None else str(claimed_at),
            charter_created_at=str(charter_row["created_at"]),
            owner_participant_id=owner,
            reports=reports,
        )
        axis = derive_verification_axis(
            charter_created_at=str(charter_row["created_at"]),
            jobs=jobs,
        )
        return lifecycle, derive_state(lifecycle, str(axis["status"]))

    def get_module_charter(self, conversation_id: str, module_id: str) -> dict[str, Any] | None:
        """Return the current charter for one module, or None when unknown."""

        with self._connect() as conn:
            row = self._current_charter_conn(
                conn, conversation_id=conversation_id, module_id=module_id
            )
            if row is None:
                return None
            body = _decode(str(row["charter_json"]))
            report_to = body.get("report_to") if isinstance(body, dict) else None
            return {
                "module_id": str(row["module_id"]),
                "version": int(row["version"]),
                "owner_participant_id": str(row["owner_participant_id"]),
                "status": str(row["status"]),
                "charter": body,
                "report_to": report_to if isinstance(report_to, str) else None,
            }

    def provider_modules_for_module(self, conversation_id: str, module_id: str) -> list[str]:
        """Return sorted provider module ids for one module's charter ``depends``.

        Each entry is the ``provider_module_id`` of the latest version of a
        contract listed in the module's current charter ``depends``, excluding
        the module itself.  Contracts with no versions yet contribute nothing.
        """

        with self._connect() as conn:
            return self._provider_modules_conn(
                conn, conversation_id=conversation_id, module_id=module_id
            )

    @staticmethod
    def _provider_modules_conn(
        conn: sqlite3.Connection, *, conversation_id: str, module_id: str
    ) -> list[str]:
        charter = RoomBoardStore._current_charter_conn(
            conn, conversation_id=conversation_id, module_id=module_id
        )
        if charter is None:
            return []
        body = _decode(str(charter["charter_json"]))
        depends = body.get("depends", []) if isinstance(body, dict) else []
        providers: set[str] = set()
        for contract_id in depends if isinstance(depends, list) else []:
            if not isinstance(contract_id, str) or not contract_id:
                continue
            latest = RoomBoardStore._latest_contract_conn(
                conn, conversation_id=conversation_id, contract_id=contract_id
            )
            if latest is None:
                continue
            provider = str(latest["provider_module_id"])
            if provider and provider != module_id:
                providers.add(provider)
        return sorted(providers)

    def _review_material_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        participant_id: str,
        review_id: str,
    ) -> dict[str, Any]:
        review = conn.execute(
            "select * from room_board_reviews where review_id = ? and conversation_id = ?",
            (review_id, conversation_id),
        ).fetchone()
        if review is None:
            raise ValueError("room_board_review_unknown")
        allowed = {str(review["author_participant_id"])}
        if review["reviewer_participant_id"]:
            allowed.add(str(review["reviewer_participant_id"]))
        if participant_id not in allowed:
            raise ValueError("room_board_review_forbidden")
        module_id = str(review["module_id"])
        verification_id = str(review["verification_id"])
        charter = self._current_charter_conn(
            conn, conversation_id=conversation_id, module_id=module_id
        )
        charter_body = _decode(str(charter["charter_json"])) if charter is not None else None
        wanted: set[str] = set()
        if isinstance(charter_body, dict):
            for key in ("provides", "depends"):
                items = charter_body.get(key, [])
                if isinstance(items, list):
                    for contract_id in items:
                        if isinstance(contract_id, str) and contract_id:
                            wanted.add(contract_id)
        contracts: list[dict[str, Any]] = []
        for contract_id in sorted(wanted):
            row = self._latest_contract_conn(
                conn, conversation_id=conversation_id, contract_id=contract_id
            )
            if row is None:
                continue
            contracts.append(
                {
                    "contract_id": str(row["contract_id"]),
                    "version": int(row["version"]),
                    "digest": str(row["digest"]),
                    "provider_module_id": str(row["provider_module_id"]),
                    "kind": str(row["kind"]),
                    "content": str(row["content"]),
                }
            )
        verification = conn.execute(
            "select * from room_board_verifications where verification_id = ?",
            (verification_id,),
        ).fetchone()
        gates: list[dict[str, Any]] = []
        stacked_ids: list[str] = []
        patch_text: str | None = None
        changed_paths: list[str] = []
        if verification is not None:
            result = _decode(verification["result_json"]) if verification["result_json"] else None
            if isinstance(result, dict):
                raw_gates = result.get("gates")
                if isinstance(raw_gates, list):
                    gates = [dict(item) for item in raw_gates if isinstance(item, dict)]
                raw_stacked = result.get("stacked")
                if isinstance(raw_stacked, list):
                    stacked_ids = [
                        str(item.get("module_id"))
                        for item in raw_stacked
                        if isinstance(item, dict) and item.get("module_id")
                    ]
            raw_patch = verification["patch_text"]
            if isinstance(raw_patch, str) and raw_patch:
                encoded = raw_patch.encode("utf-8")
                if len(encoded) > MAX_VERIFICATION_PATCH_BYTES:
                    raise ValueError("room_board_verification_patch_too_large")
                patch_text = raw_patch
            raw_changed = _decode(str(verification["changed_paths_json"] or "[]"))
            if isinstance(raw_changed, list):
                changed_paths = [str(item) for item in raw_changed if isinstance(item, str)]
        upstream = self._provider_modules_conn(
            conn, conversation_id=conversation_id, module_id=module_id
        )
        return {
            "review_id": review_id,
            "module_id": module_id,
            "verification_id": verification_id,
            "status": str(review["status"]),
            "author_participant_id": str(review["author_participant_id"]),
            "charter": charter_body,
            "charter_version": int(charter["version"]) if charter is not None else None,
            "contracts": contracts,
            "gates": gates,
            "stacked_module_ids": stacked_ids or upstream,
            "upstream_module_ids": upstream,
            "changed_paths": changed_paths,
            "patch_text": patch_text,
        }

    def latest_passed_board_verification(
        self, conversation_id: str, module_id: str
    ) -> dict[str, Any] | None:
        """Return the latest ``passed`` verification for one module, if any."""

        with self._connect() as conn:
            rows = conn.execute(
                "select * from room_board_verifications where conversation_id = ? "
                "and module_id = ? order by created_at, verification_id",
                (conversation_id, module_id),
            ).fetchall()
        latest: dict[str, Any] | None = None
        for row in rows:
            if str(row["status"]) != "passed":
                continue
            mapping = dict(row)
            result = _decode(mapping.get("result_json")) if mapping.get("result_json") else None
            base_commit = None
            if isinstance(result, dict):
                raw_base = result.get("base_commit")
                if isinstance(raw_base, str) and raw_base:
                    base_commit = raw_base
            changed = _decode(str(mapping.get("changed_paths_json") or "[]"))
            latest = {
                "verification_id": str(mapping["verification_id"]),
                "module_id": str(mapping["module_id"]),
                "head_commit": mapping["head_commit"],
                "patch_digest": mapping["patch_digest"],
                "patch_text": mapping.get("patch_text"),
                "changed_paths": list(changed) if isinstance(changed, list) else [],
                "base_commit": base_commit,
                "created_at": str(mapping["created_at"]),
                "result": result,
            }
        return latest

    def has_newer_unresolved_verification(
        self,
        conversation_id: str,
        module_id: str,
        *,
        after_created_at: str,
        after_verification_id: str,
    ) -> bool:
        """Return True when a ``pending``/``running`` job is newer than a pass."""

        with self._connect() as conn:
            row = conn.execute(
                "select 1 from room_board_verifications where conversation_id = ? "
                "and module_id = ? and status in ('pending', 'running') "
                "and (created_at, verification_id) > (?, ?) limit 1",
                (
                    conversation_id,
                    module_id,
                    after_created_at,
                    after_verification_id,
                ),
            ).fetchone()
            return row is not None

    @staticmethod
    def _active_agent_review_candidates_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> list[dict[str, Any]]:
        from xmuse_core.chat.participant_store import INIT_GOD_ROLE

        rows = conn.execute(
            "select participant_id, cli_kind from participants "
            "where conversation_id = ? and status = 'active' and role <> ? "
            "order by participant_id",
            (conversation_id, INIT_GOD_ROLE),
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            kind = str(row["cli_kind"])
            if kind not in ROOM_AGENT_CLI_KINDS:
                continue
            candidates.append({"participant_id": str(row["participant_id"]), "family": kind})
        return candidates

    @staticmethod
    def _pending_review_loads_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, int]:
        try:
            rows = conn.execute(
                "select reviewer_participant_id, count(*) as total from room_board_reviews "
                "where conversation_id = ? and status = 'pending' "
                "and reviewer_participant_id is not null "
                "group by reviewer_participant_id",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {str(row["reviewer_participant_id"]): int(row["total"]) for row in rows}

    @staticmethod
    def _last_module_reviewer_conn(
        conn: sqlite3.Connection, *, conversation_id: str, module_id: str
    ) -> str | None:
        try:
            row = conn.execute(
                "select reviewer_participant_id from room_board_reviews "
                "where conversation_id = ? and module_id = ? "
                "and reviewer_participant_id is not null "
                "order by created_at desc, review_id desc limit 1",
                (conversation_id, module_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row["reviewer_participant_id"] is None:
            return None
        return str(row["reviewer_participant_id"])

    def _create_review_for_pass_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        module_id: str,
        verification_id: str,
        verification_activity_id: str,
        verification_causal_depth: int,
        stamp: str,
    ) -> dict[str, Any] | None:
        # Reviews open only when the room was created with
        # ``review_policy: cross_family``; with ``off`` a passed verification
        # stands on its own and no review row is ever written.
        if review_policy_for_conversation(conn, conversation_id) != "cross_family":
            return None
        ver_row = conn.execute(
            "select participant_id from room_board_verifications where verification_id = ?",
            (verification_id,),
        ).fetchone()
        author_id = str(ver_row["participant_id"]) if ver_row is not None else ""
        author_row = conn.execute(
            "select cli_kind from participants where conversation_id = ? and participant_id = ?",
            (conversation_id, author_id),
        ).fetchone()
        author_family = str(author_row["cli_kind"]) if author_row is not None else ""
        candidates = self._active_agent_review_candidates_conn(
            conn, conversation_id=conversation_id
        )
        loads = self._pending_review_loads_conn(conn, conversation_id=conversation_id)
        last_reviewer = self._last_module_reviewer_conn(
            conn, conversation_id=conversation_id, module_id=module_id
        )
        eligible_inputs = [
            {
                "participant_id": item["participant_id"],
                "family": item["family"],
                "pending": int(loads.get(item["participant_id"], 0)),
            }
            for item in candidates
            if item["participant_id"] != author_id and item["family"] != author_family
        ]
        eligible_inputs.sort(key=lambda item: str(item["participant_id"]))
        picked = assign_cross_family_reviewer(
            author_participant_id=author_id,
            author_family=author_family,
            candidates=candidates,
            pending_loads=loads,
            last_reviewer_id=last_reviewer,
        )
        rule_inputs = {
            "author_id": author_id,
            "author_family": author_family,
            "eligible": eligible_inputs,
            "pending_loads": {item["participant_id"]: item["pending"] for item in eligible_inputs},
            "last_reviewer_id": last_reviewer,
            "picked_participant_id": picked,
        }
        review_id = _id("boardreview")
        if picked is None:
            reviewer_kind = "operator"
            reviewer_id: str | None = None
            reviewer_family: str | None = None
        else:
            reviewer_kind = "participant"
            reviewer_id = picked
            reviewer_family = next(
                (str(item["family"]) for item in candidates if item["participant_id"] == picked),
                None,
            )
        conn.execute(
            """insert into room_board_reviews
               (review_id, conversation_id, module_id, verification_id,
                author_participant_id, author_family, reviewer_kind,
                reviewer_participant_id, reviewer_family, rule_id, rule_inputs_json,
                status, verdict_json, request_activity_id, verdict_activity_id,
                created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', null, null, null, ?, ?)""",
            (
                review_id,
                conversation_id,
                module_id,
                verification_id,
                author_id,
                author_family,
                reviewer_kind,
                reviewer_id,
                reviewer_family,
                BOARD_REVIEW_RULE_ID,
                _json(rule_inputs),
                stamp,
                stamp,
            ),
        )
        charter = self._current_charter_conn(
            conn, conversation_id=conversation_id, module_id=module_id
        )
        body = _decode(str(charter["charter_json"])) if charter is not None else None
        report_to = body.get("report_to") if isinstance(body, dict) else None
        lead = self._lead_participant_id(conn, conversation_id)
        if reviewer_kind == "participant" and reviewer_id:
            audience = [reviewer_id]
        else:
            fallback = report_to if isinstance(report_to, str) and report_to else lead
            audience = [fallback] if fallback else []
        request_activity = self._insert_board_activity_conn(
            conn,
            conversation_id=conversation_id,
            activity_type="board.review_requested",
            actor_kind="infrastructure",
            actor_identity="infrastructure:board-review",
            actor_participant_id=None,
            causation_id=verification_activity_id,
            causal_depth=verification_causal_depth + 1,
            audience_participant_ids=audience,
            payload={
                "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                "review_id": review_id,
                "module_id": module_id,
                "verification_id": verification_id,
                "author_participant_id": author_id,
                "author_family": author_family,
                "reviewer_kind": reviewer_kind,
                "reviewer_participant_id": reviewer_id,
                "reviewer_family": reviewer_family,
                "rule_id": BOARD_REVIEW_RULE_ID,
            },
            stamp=stamp,
        )
        conn.execute(
            "update room_board_reviews set request_activity_id = ? where review_id = ?",
            (str(request_activity["activity_id"]), review_id),
        )
        woken: list[dict[str, Any]] = []
        if reviewer_kind == "participant" and reviewer_id:
            woken = self._wake_participants_conn(
                conn,
                conversation_id=conversation_id,
                activity_id=str(request_activity["activity_id"]),
                participant_ids=[reviewer_id],
                stamp=stamp,
            )
        return {
            "review_id": review_id,
            "reviewer_kind": reviewer_kind,
            "reviewer_participant_id": reviewer_id,
            "reviewer_family": reviewer_family,
            "request_activity_id": str(request_activity["activity_id"]),
            "request_activity_seq": int(request_activity["seq"]),
            "woken_participant_ids": [item["participant_id"] for item in woken],
        }

    @staticmethod
    def _module_review_stats_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, dict[str, Any]]:
        """Summarize review state per module (latest row plus counters)."""

        try:
            rows = conn.execute(
                "select * from room_board_reviews where conversation_id = ? "
                "order by created_at, review_id",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        by_module: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_module.setdefault(str(row["module_id"]), []).append(row)
        stats: dict[str, dict[str, Any]] = {}
        for module_id, items in by_module.items():
            latest = items[-1]
            verdict_data = _decode(str(latest["verdict_json"])) if latest["verdict_json"] else None
            if isinstance(verdict_data, dict):
                raw_findings = verdict_data.get("findings")
                if isinstance(raw_findings, list):
                    sanitized_findings = []
                    for item in raw_findings:
                        if isinstance(item, dict):
                            item_copy = dict(item)
                            raw_p = item_copy.get("path")
                            item_copy["path"] = raw_p if is_valid_finding_path(raw_p) else None
                            sanitized_findings.append(item_copy)
                        else:
                            sanitized_findings.append(item)
                    verdict_data["findings"] = sanitized_findings
            stats[module_id] = {
                "status": str(latest["status"]),
                "review_id": str(latest["review_id"]),
                "verification_id": str(latest["verification_id"]),
                "reviewer_kind": str(latest["reviewer_kind"]),
                "reviewer_participant_id": latest["reviewer_participant_id"],
                "reviewer_family": latest["reviewer_family"],
                "verdict": verdict_data,
                "reviews_endorsed": sum(1 for item in items if str(item["status"]) == "endorsed"),
                "reviews_objected": sum(1 for item in items if str(item["status"]) == "objected"),
            }
        return stats

    def claim_next_board_verification(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = VERIFICATION_LEASE_TTL_S,
        max_attempts: int = MAX_VERIFICATION_ATTEMPTS,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Claim one pending verification with a lease (``pending→running`` CAS).

        Expired ``running`` rows return to ``pending`` on the next claim; rows
        that exhausted ``max_attempts`` become ``error`` instead of being
        claimed again.
        """

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("room_board_worker_id_required")
        if (
            isinstance(lease_ttl_s, bool)
            or not isinstance(lease_ttl_s, int)
            or not 5 <= lease_ttl_s <= 7200
        ):
            raise ValueError("room_board_lease_ttl_invalid")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ValueError("room_board_max_attempts_invalid")
        if max_attempts < 1:
            raise ValueError("room_board_max_attempts_invalid")
        current, stamp = _current_stamp(now)
        expires = _timestamp(current + timedelta(seconds=lease_ttl_s))
        lease_token = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    "update room_board_verifications set status = 'pending', "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "updated_at = ? where status = 'running' and lease_expires_at is not null "
                    "and lease_expires_at <= ?",
                    (stamp, stamp),
                )
                # Rows that exhausted their attempt budget become ``error``
                # with a durable ``board.verification`` activity each, in the
                # same transaction. A row already ``error`` is never selected
                # again, so this is idempotent.
                exhausted = conn.execute(
                    "select * from room_board_verifications "
                    "where status = 'pending' and attempt_count >= ? "
                    "order by created_at, rowid",
                    (max_attempts,),
                ).fetchall()
                error_result_json = _json(
                    {
                        "status": "error",
                        "reason_code": "board_verification_attempts_exhausted",
                    }
                )
                for expired in exhausted:
                    progress = conn.execute(
                        "select * from room_board_progress where progress_id = ?",
                        (str(expired["progress_id"]),),
                    ).fetchone()
                    if progress is None:
                        continue
                    source = self._activity_from_conn(conn, str(progress["activity_id"]))
                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=str(expired["conversation_id"]),
                        activity_type="board.verification",
                        actor_kind="infrastructure",
                        actor_identity="infrastructure:board-verification",
                        actor_participant_id=None,
                        causation_id=str(progress["activity_id"]),
                        causal_depth=int(source["causal_depth"]) + 1,
                        audience_participant_ids=[str(expired["participant_id"])],
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "verification_id": str(expired["verification_id"]),
                            "progress_id": str(expired["progress_id"]),
                            "module_id": str(expired["module_id"]),
                            "status": "error",
                            "reason_code": "board_verification_attempts_exhausted",
                            "head_commit": expired["head_commit"],
                            "changed_paths": [],
                            "gates": [],
                            "evidence": {},
                            "stacked": [],
                            "escalated": False,
                        },
                        stamp=stamp,
                    )
                    conn.execute(
                        "update room_board_verifications set status = 'error', "
                        "lease_owner = null, lease_token = null, lease_expires_at = null, "
                        "result_json = ?, activity_id = ?, updated_at = ? "
                        "where verification_id = ? and status = 'pending'",
                        (
                            error_result_json,
                            str(activity["activity_id"]),
                            stamp,
                            str(expired["verification_id"]),
                        ),
                    )
                row = conn.execute(
                    "select * from room_board_verifications where status = 'pending' "
                    "and (not_before is null or not_before <= ?) "
                    "order by created_at, verification_id limit 1",
                    (stamp,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                changed = conn.execute(
                    "update room_board_verifications set status = 'running', "
                    "attempt_count = attempt_count + 1, lease_owner = ?, lease_token = ?, "
                    "lease_expires_at = ?, updated_at = ? "
                    "where verification_id = ? and status = 'pending'",
                    (
                        worker_id,
                        lease_token,
                        expires,
                        stamp,
                        str(row["verification_id"]),
                    ),
                ).rowcount
                if changed != 1:
                    conn.commit()
                    return None
                claimed = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (str(row["verification_id"]),),
                ).fetchone()
                assert claimed is not None
                result = self._verification_view(claimed)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def complete_board_verification(
        self,
        *,
        verification_id: str,
        lease_token: str,
        status: str,
        reason_code: str | None,
        head_commit: str | None,
        patch_digest: str | None,
        changed_paths: list[str],
        gates: list[dict[str, Any]],
        evidence: dict[str, Any] | None,
        now: datetime | None = None,
        patch_text: str | None = None,
        stacked: list[dict[str, Any]] | None = None,
        base_commit: str | None = None,
    ) -> dict[str, Any]:
        """Record a terminal verification result with a ``board.verification`` activity.

        The job lease is re-checked and a newer ``done`` report for the same
        module wins: a stale result is dropped as ``superseded`` without an
        activity.  Failures wake the owner so the next delivery reuses its
        session; the third consecutive failure also wakes the lead/report_to.
        """

        if status not in ("passed", "failed", "error"):
            raise ValueError("room_board_verification_status_invalid")
        if status != "passed" and (not isinstance(reason_code, str) or not reason_code.strip()):
            raise ValueError("room_board_verification_reason_required")
        if reason_code is not None and (
            not isinstance(reason_code, str) or not reason_code.strip()
        ):
            raise ValueError("room_board_verification_reason_required")
        if not isinstance(changed_paths, list) or any(
            not isinstance(item, str) for item in changed_paths
        ):
            raise ValueError("room_board_verification_paths_invalid")
        clean_gates: list[dict[str, Any]] = []
        for entry in gates:
            if not isinstance(entry, dict) or not isinstance(entry.get("gate_id"), str):
                raise ValueError("room_board_verification_gates_invalid")
            exit_code = entry.get("exit_code")
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                raise ValueError("room_board_verification_gates_invalid")
            gate_status = entry.get("status")
            if gate_status not in ("passed", "failed", "cancelled"):
                raise ValueError("room_board_verification_gates_invalid")
            gate_reason = entry.get("reason_code")
            if gate_reason is not None and not isinstance(gate_reason, str):
                raise ValueError("room_board_verification_gates_invalid")
            clean_gates.append(
                {
                    "gate_id": str(entry["gate_id"]),
                    "status": str(gate_status),
                    "exit_code": exit_code,
                    "reason_code": gate_reason,
                }
            )
        clean_evidence = dict(evidence) if evidence is not None else {}
        if len(_json(clean_evidence).encode("utf-8")) > MAX_VERIFICATION_EVIDENCE_BYTES:
            raise ValueError("room_board_verification_evidence_too_large")
        if patch_text is not None:
            if not isinstance(patch_text, str) or not patch_text.strip():
                raise ValueError("room_board_verification_patch_invalid")
            if len(patch_text.encode("utf-8")) > MAX_VERIFICATION_PATCH_BYTES:
                raise ValueError("room_board_verification_patch_too_large")
        clean_stacked: list[dict[str, Any]] = []
        if stacked is not None:
            if not isinstance(stacked, list):
                raise ValueError("room_board_verification_stacked_invalid")
            for entry in stacked:
                if not isinstance(entry, dict):
                    raise ValueError("room_board_verification_stacked_invalid")
                module = entry.get("module_id")
                vid = entry.get("verification_id")
                head = entry.get("head_commit")
                if (
                    not isinstance(module, str)
                    or not module
                    or not isinstance(vid, str)
                    or not vid
                    or not isinstance(head, str)
                    or not head
                ):
                    raise ValueError("room_board_verification_stacked_invalid")
                clean_stacked.append(
                    {
                        "module_id": module,
                        "verification_id": vid,
                        "head_commit": head,
                    }
                )
        if base_commit is not None and (
            not isinstance(base_commit, str) or not base_commit.strip()
        ):
            raise ValueError("room_board_verification_base_invalid")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_board_verification_lease_lost")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (verification_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_verification_unknown")
                if str(row["status"]) == "superseded":
                    conn.commit()
                    return {
                        "verification_id": verification_id,
                        "status": "dropped",
                        "activity_id": None,
                        "activity_seq": None,
                        "woken_participant_ids": [],
                        "escalated": False,
                    }
                if (
                    str(row["status"]) != "running"
                    or row["lease_token"] != lease_token
                    or (
                        row["lease_expires_at"] is not None
                        and str(row["lease_expires_at"]) <= stamp
                    )
                ):
                    raise ValueError("room_board_verification_lease_lost")
                conversation_id = str(row["conversation_id"])
                module_id = str(row["module_id"])
                owner_id = str(row["participant_id"])
                progress_id = str(row["progress_id"])
                # A newer done report wins: this result is stale.
                newer = conn.execute(
                    "select 1 from room_board_verifications "
                    "where conversation_id = ? and module_id = ? and verification_id != ? "
                    "and (created_at, verification_id) > (?, ?) limit 1",
                    (
                        conversation_id,
                        module_id,
                        verification_id,
                        str(row["created_at"]),
                        verification_id,
                    ),
                ).fetchone()
                if newer is not None:
                    conn.execute(
                        "update room_board_verifications set status = 'superseded', "
                        "lease_owner = null, lease_token = null, lease_expires_at = null, "
                        "updated_at = ? where verification_id = ?",
                        (stamp, verification_id),
                    )
                    conn.commit()
                    return {
                        "verification_id": verification_id,
                        "status": "dropped",
                        "activity_id": None,
                        "activity_seq": None,
                        "woken_participant_ids": [],
                        "escalated": False,
                    }
                progress = conn.execute(
                    "select * from room_board_progress where progress_id = ?",
                    (progress_id,),
                ).fetchone()
                if progress is None:
                    raise ValueError("room_board_verification_progress_unknown")
                source = self._activity_from_conn(conn, str(progress["activity_id"]))
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                charter_body = (
                    _decode(str(charter["charter_json"])) if charter is not None else None
                )
                report_to = (
                    charter_body.get("report_to") if isinstance(charter_body, dict) else None
                )
                if not isinstance(report_to, str) or not report_to:
                    report_to = None
                lead = self._lead_participant_id(conn, conversation_id)
                escalated = False
                audience: list[str] = []
                wake: list[str] = []
                if status == "failed":
                    history = conn.execute(
                        "select status from room_board_verifications "
                        "where conversation_id = ? and module_id = ? "
                        "and status in ('passed', 'failed') "
                        "order by created_at desc, verification_id desc limit 10",
                        (conversation_id, module_id),
                    ).fetchall()
                    consecutive = 1
                    for item in history:
                        if str(item["status"]) == "failed":
                            consecutive += 1
                        else:
                            break
                    audience = [owner_id]
                    wake = [owner_id]
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        escalated = True
                        escalation = report_to or lead
                        if escalation and escalation not in audience:
                            audience.append(escalation)
                            wake.append(escalation)
                elif status == "passed":
                    target = report_to or lead
                    audience = [target] if target else []
                else:
                    audience = [owner_id]
                payload = {
                    "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                    "verification_id": verification_id,
                    "progress_id": progress_id,
                    "module_id": module_id,
                    "status": status,
                    "reason_code": reason_code,
                    "head_commit": head_commit,
                    "changed_paths": list(changed_paths),
                    "gates": clean_gates,
                    "evidence": clean_evidence,
                    "stacked": clean_stacked,
                    "escalated": escalated,
                }
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.verification",
                    actor_kind="infrastructure",
                    actor_identity="infrastructure:board-verification",
                    actor_participant_id=None,
                    causation_id=str(progress["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=audience,
                    payload=payload,
                    stamp=stamp,
                )
                result_json = _json(
                    {
                        "status": status,
                        "reason_code": reason_code,
                        "head_commit": head_commit,
                        "patch_digest": patch_digest,
                        "changed_paths": list(changed_paths),
                        "gates": clean_gates,
                        "evidence": clean_evidence,
                        "stacked": clean_stacked,
                        "base_commit": base_commit,
                    }
                )
                conn.execute(
                    "update room_board_verifications set status = ?, attempt_count = ?, "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "not_before = null, "
                    "head_commit = ?, patch_digest = ?, changed_paths_json = ?, "
                    "patch_text = coalesce(?, patch_text), "
                    "result_json = ?, activity_id = ?, updated_at = ? "
                    "where verification_id = ?",
                    (
                        status,
                        int(row["attempt_count"]),
                        head_commit,
                        patch_digest,
                        _json(list(changed_paths)),
                        patch_text,
                        result_json,
                        str(activity["activity_id"]),
                        stamp,
                        verification_id,
                    ),
                )
                woken: list[dict[str, Any]] = []
                if wake:
                    woken = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=wake,
                        stamp=stamp,
                    )
                review_info: dict[str, Any] | None = None
                if status == "passed":
                    review_info = self._create_review_for_pass_conn(
                        conn,
                        conversation_id=conversation_id,
                        module_id=module_id,
                        verification_id=verification_id,
                        verification_activity_id=str(activity["activity_id"]),
                        verification_causal_depth=int(activity["causal_depth"]),
                        stamp=stamp,
                    )
                    if review_info is not None:
                        for item in review_info.get("woken_participant_ids", []):
                            if item not in [entry["participant_id"] for entry in woken]:
                                woken.append(
                                    {
                                        "participant_id": item,
                                    }
                                )
                conn.commit()
                result: dict[str, Any] = {
                    "verification_id": verification_id,
                    "status": status,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken],
                    "escalated": escalated,
                }
                if review_info is not None:
                    result["review_id"] = review_info["review_id"]
                    result["reviewer_kind"] = review_info["reviewer_kind"]
                    result["reviewer_participant_id"] = review_info["reviewer_participant_id"]
                    result["review_request_activity_id"] = review_info["request_activity_id"]
                return result
            except Exception:
                conn.rollback()
                raise

    def abandon_board_verification(
        self,
        *,
        verification_id: str,
        lease_token: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Release a claimed job back to ``pending`` after a transient host error.

        The attempt budget is enforced on the next claim: exhausted jobs become
        ``error`` there instead of being claimed again.
        """

        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValueError("room_board_verification_reason_required")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_board_verification_lease_lost")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (verification_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_verification_unknown")
                if str(row["status"]) == "superseded":
                    conn.commit()
                    return {"verification_id": verification_id, "status": "dropped"}
                if str(row["status"]) != "running" or row["lease_token"] != lease_token:
                    raise ValueError("room_board_verification_lease_lost")
                conn.execute(
                    "update room_board_verifications set status = 'pending', "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "result_json = ?, updated_at = ? where verification_id = ?",
                    (
                        _json({"status": "pending", "reason_code": reason_code}),
                        stamp,
                        verification_id,
                    ),
                )
                conn.commit()
                return {"verification_id": verification_id, "status": "pending"}
            except Exception:
                conn.rollback()
                raise

    def defer_board_verification(
        self,
        *,
        verification_id: str,
        lease_token: str,
        providers: list[str],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Defer a claimed job until its provider modules have passed.

        The job returns to ``pending`` without consuming an attempt (the
        claim's increment is undone), records a waiting ``result_json``, and
        sets ``not_before`` so the next claim skips it for a short backoff.  No
        activity is written and nobody is woken.
        """

        if not isinstance(providers, list) or not providers:
            raise ValueError("room_board_verification_providers_required")
        clean_providers = sorted({item for item in providers if isinstance(item, str) and item})
        if not clean_providers:
            raise ValueError("room_board_verification_providers_required")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_board_verification_lease_lost")
        current, stamp = _current_stamp(now)
        not_before = _timestamp(current + timedelta(seconds=VERIFICATION_DEFERRAL_DELAY_S))
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (verification_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_verification_unknown")
                if str(row["status"]) == "superseded":
                    conn.commit()
                    return {"verification_id": verification_id, "status": "dropped"}
                if str(row["status"]) != "running" or row["lease_token"] != lease_token:
                    raise ValueError("room_board_verification_lease_lost")
                conn.execute(
                    "update room_board_verifications set status = 'pending', "
                    "attempt_count = case when attempt_count > 0 "
                    "then attempt_count - 1 else 0 end, "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "result_json = ?, not_before = ?, updated_at = ? "
                    "where verification_id = ?",
                    (
                        _json(
                            {
                                "status": "pending",
                                "reason_code": BOARD_VERIFICATION_WAITING_FOR_PROVIDER,
                                "providers": clean_providers,
                            }
                        ),
                        not_before,
                        stamp,
                        verification_id,
                    ),
                )
                conn.commit()
                return {
                    "verification_id": verification_id,
                    "status": "pending",
                    "not_before": not_before,
                    "providers": clean_providers,
                }
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _normalize_progress_claims(claims: list[str] | None) -> list[str]:
        if claims is None:
            return []
        if not isinstance(claims, list) or len(claims) > 32:
            raise ValueError("room_board_claims_invalid")
        cleaned: list[str] = []
        for entry in claims:
            if not isinstance(entry, str) or not entry.strip() or len(entry.strip()) > 500:
                raise ValueError("room_board_claims_invalid")
            cleaned.append(entry.strip())
        return cleaned

    def ask(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        target_participant_id: str,
        question: str,
        references: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(target_participant_id, str) or not target_participant_id.strip():
            raise ValueError("room_board_target_unknown")
        if target_participant_id == participant_id:
            raise ValueError("room_board_ask_self")
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            raise ValueError("room_board_question_invalid")
        clean_references = self._normalize_references(references)
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_ASK,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "target_participant_id": target_participant_id,
                    "question": question,
                    "references": clean_references,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_ASK,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                target = conn.execute(
                    "select * from participants where conversation_id = ? and participant_id = ?",
                    (conversation_id, target_participant_id),
                ).fetchone()
                if (
                    target is None
                    or target["status"] != "active"
                    or target["cli_kind"] not in ROOM_AGENT_CLI_KINDS
                ):
                    raise ValueError("room_board_target_unknown")
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.question",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=str(source["activity_id"]),
                    causal_depth=int(source["causal_depth"]) + 1,
                    audience_participant_ids=[target_participant_id],
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "target_participant_id": target_participant_id,
                        "question": question,
                        "references": clean_references,
                    },
                    stamp=stamp,
                )
                self._wake_participants_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_id=str(activity["activity_id"]),
                    participant_ids=[target_participant_id],
                    stamp=stamp,
                )
                result = {
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "target_participant_id": target_participant_id,
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_ASK,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _normalize_references(references: list[str] | None) -> list[str]:
        if references is None:
            return []
        if not isinstance(references, list) or len(references) > 16:
            raise ValueError("room_board_references_invalid")
        for entry in references:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError("room_board_references_invalid")
        return list(references)

    def review(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        caller_identity: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        review_id: str,
        verdict: str,
        summary: str,
        findings: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(client_request_id, str) or not client_request_id.strip():
            raise ValueError("room_client_request_id_required")
        if not isinstance(review_id, str) or not review_id.strip():
            raise ValueError("room_board_review_unknown")
        clean_summary = normalize_review_summary(summary)
        clean_findings = normalize_review_findings(findings)
        clean_verdict = normalize_review_verdict(verdict, clean_findings)
        fingerprint = sha256(
            _json(
                {
                    "tool": TOOL_REVIEW,
                    "conversation_id": conversation_id,
                    "participant_id": participant_id,
                    "caller_identity": caller_identity,
                    "observation_id": observation_id,
                    "client_request_id": client_request_id,
                    "review_id": review_id,
                    "verdict": clean_verdict,
                    "summary": clean_summary,
                    "findings": clean_findings,
                }
            ).encode()
        ).hexdigest()
        current, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                replay = self._check_idempotency_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REVIEW,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    conn.commit()
                    return replay
                _, source = self._check_lease_conn(
                    conn,
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    caller_identity=caller_identity,
                    observation_id=observation_id,
                    lease_token=lease_token,
                    current=current,
                )
                stored = conn.execute(
                    "select * from room_board_reviews where review_id = ? and conversation_id = ?",
                    (review_id, conversation_id),
                ).fetchone()
                if stored is None:
                    raise ValueError("room_board_review_unknown")
                if str(stored["status"]) != "pending":
                    raise ValueError("room_board_review_decided")
                if (
                    str(stored["reviewer_kind"]) != "participant"
                    or str(stored["reviewer_participant_id"]) != participant_id
                ):
                    raise ValueError("room_board_review_forbidden")
                module_id = str(stored["module_id"])
                author_id = str(stored["author_participant_id"])
                verdict_json = _json(
                    {
                        "verdict": clean_verdict,
                        "summary": summary.strip(),
                        "findings": clean_findings,
                        "reviewer_participant_id": participant_id,
                        "decided_via": "board_tool",
                    }
                )
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                body = _decode(str(charter["charter_json"])) if charter is not None else None
                report_to = body.get("report_to") if isinstance(body, dict) else None
                lead = self._lead_participant_id(conn, conversation_id)
                if clean_verdict == "endorse":
                    target = report_to if isinstance(report_to, str) and report_to else lead
                    audience = [target] if target else []
                    wake: list[str] = []
                    new_status = "endorsed"
                else:
                    audience = [author_id]
                    extra = report_to if isinstance(report_to, str) and report_to else lead
                    if extra and extra not in audience:
                        audience.append(extra)
                    wake = [author_id]
                    new_status = "objected"
                causation = str(stored["request_activity_id"] or source["activity_id"])
                try:
                    cause = self._activity_from_conn(conn, causation)
                    depth = int(cause["causal_depth"]) + 1
                except KeyError:
                    causation = str(source["activity_id"])
                    depth = int(source["causal_depth"]) + 1
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.review",
                    actor_kind="participant",
                    actor_identity=caller_identity,
                    actor_participant_id=participant_id,
                    causation_id=causation,
                    causal_depth=depth,
                    audience_participant_ids=audience,
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "review_id": review_id,
                        "module_id": module_id,
                        "verification_id": str(stored["verification_id"]),
                        "verdict": clean_verdict,
                        "summary": summary.strip(),
                        "findings": clean_findings,
                        "reviewer_participant_id": participant_id,
                        "reviewer_family": stored["reviewer_family"],
                        "author_participant_id": author_id,
                    },
                    stamp=stamp,
                )
                conn.execute(
                    "update room_board_reviews set status = ?, verdict_json = ?, "
                    "verdict_activity_id = ?, decided_via = 'board_tool', "
                    "updated_at = ? where review_id = ?",
                    (
                        new_status,
                        verdict_json,
                        str(activity["activity_id"]),
                        stamp,
                        review_id,
                    ),
                )
                woken: list[dict[str, Any]] = []
                if wake:
                    woken = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=wake,
                        stamp=stamp,
                    )
                result = {
                    "review_id": review_id,
                    "module_id": module_id,
                    "status": new_status,
                    "verdict": clean_verdict,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken],
                    "request_fingerprint": fingerprint,
                }
                self._write_request_log_conn(
                    conn,
                    conversation_id=conversation_id,
                    tool_name=TOOL_REVIEW,
                    caller_identity=caller_identity,
                    client_request_id=client_request_id,
                    result=result,
                    created_at=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def decide_review(
        self,
        *,
        conversation_id: str,
        review_id: str,
        verdict: str,
        summary: str,
        findings: list[dict[str, Any]] | None = None,
        expected_digest: str,
        operator_identity: str,
        decided_via: str = "web",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(operator_identity, str) or not operator_identity.strip():
            raise ValueError("room_operator_identity_required")

        # 1. Limits: summary, findings, verdict
        clean_summary = normalize_review_summary(summary)
        clean_findings = normalize_review_findings(findings)
        clean_verdict = normalize_review_verdict(verdict, clean_findings)

        # 2. decided_via must be exactly "web"
        if decided_via != "web":
            raise ValueError("room_board_decided_via_invalid")

        if not isinstance(review_id, str) or not review_id.strip():
            raise ValueError("room_board_review_unknown")

        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                # 3. Review exists in conversation_id
                stored = conn.execute(
                    "select * from room_board_reviews where review_id = ? and conversation_id = ?",
                    (review_id, conversation_id),
                ).fetchone()
                if stored is None:
                    raise ValueError("room_board_review_unknown")

                # 4. Pending and reviewer_kind == operator
                if str(stored["status"]) != "pending" or str(stored["reviewer_kind"]) != "operator":
                    raise ValueError("room_board_review_not_pending")

                v_row = conn.execute(
                    "select head_commit, patch_text from room_board_verifications "
                    "where verification_id = ?",
                    (str(stored["verification_id"]),),
                ).fetchone()
                head_commit = (
                    str(v_row["head_commit"])
                    if v_row is not None and v_row["head_commit"] is not None
                    else None
                )
                raw_patch = (
                    str(v_row["patch_text"])
                    if v_row is not None and v_row["patch_text"] is not None
                    else ""
                )
                actual_digest = review_digest(
                    review_id=review_id,
                    verification_id=str(stored["verification_id"]),
                    head_commit=head_commit,
                    patch_text=raw_patch,
                )

                # 5. expected_digest required and equal
                if (
                    not isinstance(expected_digest, str)
                    or not expected_digest.strip()
                    or expected_digest != actual_digest
                ):
                    raise ValueError("room_board_review_digest_mismatch")

                # 6. endorse refused when the material would be truncated
                if clean_verdict == "endorse":
                    _, _, truncated, _ = _material_patch_parts(raw_patch)
                    if truncated:
                        raise ValueError("room_board_review_material_incomplete")

                module_id = str(stored["module_id"])
                author_id = str(stored["author_participant_id"])
                new_status = "endorsed" if clean_verdict == "endorse" else "objected"
                charter = self._current_charter_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                body = _decode(str(charter["charter_json"])) if charter is not None else None
                report_to = body.get("report_to") if isinstance(body, dict) else None
                lead = self._lead_participant_id(conn, conversation_id)
                if clean_verdict == "endorse":
                    target = report_to if isinstance(report_to, str) and report_to else lead
                    audience = [target] if target else []
                    wake: list[str] = []
                else:
                    audience = [author_id]
                    extra = report_to if isinstance(report_to, str) and report_to else lead
                    if extra and extra not in audience:
                        audience.append(extra)
                    wake = [author_id]
                causation = str(stored["request_activity_id"])
                cause = self._activity_from_conn(conn, causation)
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.review",
                    actor_kind="operator",
                    actor_identity=operator_identity,
                    actor_participant_id=None,
                    causation_id=causation,
                    causal_depth=int(cause["causal_depth"]) + 1,
                    audience_participant_ids=audience,
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "review_id": review_id,
                        "module_id": module_id,
                        "verification_id": str(stored["verification_id"]),
                        "verdict": clean_verdict,
                        "summary": clean_summary,
                        "findings": clean_findings,
                        "reviewer_kind": "operator",
                        "author_participant_id": author_id,
                        "decided_via": decided_via,
                        "operator_identity": operator_identity,
                    },
                    stamp=stamp,
                )
                verdict_json = _json(
                    {
                        "verdict": clean_verdict,
                        "summary": clean_summary,
                        "findings": clean_findings,
                        "decided_via": decided_via,
                        "operator_identity": operator_identity,
                    }
                )
                conn.execute(
                    "update room_board_reviews set status = ?, verdict_json = ?, "
                    "verdict_activity_id = ?, decided_via = ?, operator_identity = ?, "
                    "updated_at = ? where review_id = ?",
                    (
                        new_status,
                        verdict_json,
                        str(activity["activity_id"]),
                        decided_via,
                        operator_identity,
                        stamp,
                        review_id,
                    ),
                )
                woken: list[dict[str, Any]] = []
                if wake:
                    woken = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=wake,
                        stamp=stamp,
                    )
                conn.commit()
                return {
                    "review_id": review_id,
                    "module_id": module_id,
                    "status": new_status,
                    "verdict": clean_verdict,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken],
                }
            except Exception:
                conn.rollback()
                raise

    def review_material(self, conversation_id: str, review_id: str) -> dict[str, Any]:
        """Fetch material for operator review (``room_board_review_material/v1``)."""
        with self._connect() as conn:
            stored = conn.execute(
                "select * from room_board_reviews where review_id = ? and conversation_id = ?",
                (review_id, conversation_id),
            ).fetchone()
            if stored is None:
                raise ValueError("room_board_review_unknown")
            if str(stored["reviewer_kind"]) != "operator":
                raise ValueError("room_board_review_not_operator")
            ver_row = conn.execute(
                "select head_commit, patch_text from room_board_verifications "
                "where verification_id = ?",
                (str(stored["verification_id"]),),
            ).fetchone()
            head_commit = (
                str(ver_row["head_commit"])
                if ver_row is not None and ver_row["head_commit"] is not None
                else None
            )
            raw_patch = (
                str(ver_row["patch_text"])
                if ver_row is not None and ver_row["patch_text"] is not None
                else ""
            )
            digest = review_digest(
                review_id=review_id,
                verification_id=str(stored["verification_id"]),
                head_commit=head_commit,
                patch_text=raw_patch,
            )
            text, bytes_total, truncated, hidden_char_count = _material_patch_parts(raw_patch)
            return {
                "schema_version": "room_board_review_material/v1",
                "review_id": review_id,
                "verification_id": str(stored["verification_id"]),
                "head_commit": head_commit or "",
                "digest": digest,
                "patch": {
                    "text": text,
                    "bytes_total": bytes_total,
                    "truncated": truncated,
                    "hidden_char_count": hidden_char_count,
                },
            }

    def escalate_stale_reviews(
        self,
        now: datetime,
        response_seconds: int,
    ) -> list[dict[str, Any]]:
        """Move stale pending participant reviews to the operator (§3.10)."""
        escalated: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                pending_reviews = conn.execute(
                    "select * from room_board_reviews "
                    "where status = 'pending' and reviewer_kind = 'participant' "
                    "order by created_at, review_id"
                ).fetchall()
                stamp = _timestamp(now)
                for review in pending_reviews:
                    conv_id = str(review["conversation_id"])
                    reviewer_id = str(review["reviewer_participant_id"])
                    request_act_id = (
                        str(review["request_activity_id"])
                        if review["request_activity_id"]
                        else None
                    )

                    reason_code: str | None = None

                    p_row = conn.execute(
                        "select status from participants "
                        "where participant_id = ? and conversation_id = ?",
                        (reviewer_id, conv_id),
                    ).fetchone()
                    if p_row is None or str(p_row["status"]) != "active":
                        reason_code = "board_review_reviewer_unavailable"
                    elif request_act_id:
                        obs = conn.execute(
                            "select status, control_state, attempt_count from room_observations "
                            "where activity_id = ? and participant_id = ? and conversation_id = ?",
                            (request_act_id, reviewer_id, conv_id),
                        ).fetchone()
                        if obs is not None and str(obs["control_state"]) in {
                            "exhausted",
                            "cancelled",
                        }:
                            reason_code = "board_review_reviewer_unavailable"
                        elif obs is not None and str(obs["status"]) == "completed":
                            reason_code = "board_review_reviewer_no_verdict"

                    if reason_code is None:
                        created = _parse_timestamp(str(review["created_at"]))
                        if (now - created).total_seconds() >= response_seconds:
                            reason_code = "board_review_reviewer_unresponsive"

                    if reason_code is None:
                        continue

                    old_reviewer_id = reviewer_id
                    old_reviewer_family = (
                        str(review["reviewer_family"]) if review["reviewer_family"] else None
                    )
                    escalation_obj = {
                        "participant_id": old_reviewer_id,
                        "family": old_reviewer_family,
                        "reason_code": reason_code,
                        "at": stamp,
                    }

                    module_id = str(review["module_id"])
                    charter = self._current_charter_conn(
                        conn, conversation_id=conv_id, module_id=module_id
                    )
                    charter_body = (
                        _decode(str(charter["charter_json"])) if charter is not None else None
                    )
                    report_to = (
                        charter_body.get("report_to") if isinstance(charter_body, dict) else None
                    )
                    lead = self._lead_participant_id(conn, conv_id)
                    fallback = report_to if isinstance(report_to, str) and report_to else lead
                    audience = [fallback] if fallback else []

                    causation = request_act_id or str(review["verification_id"])
                    try:
                        cause = self._activity_from_conn(conn, causation)
                        causal_depth = int(cause["causal_depth"]) + 1
                    except KeyError:
                        causation = str(review["review_id"])
                        causal_depth = 1

                    activity = self._insert_board_activity_conn(
                        conn,
                        conversation_id=conv_id,
                        activity_type="board.review_requested",
                        actor_kind="infrastructure",
                        actor_identity="infrastructure:board-review",
                        actor_participant_id=None,
                        causation_id=causation,
                        causal_depth=causal_depth,
                        audience_participant_ids=audience,
                        payload={
                            "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                            "review_id": str(review["review_id"]),
                            "module_id": module_id,
                            "verification_id": str(review["verification_id"]),
                            "author_participant_id": str(review["author_participant_id"]),
                            "author_family": str(review["author_family"]),
                            "reviewer_kind": "operator",
                            "reviewer_participant_id": None,
                            "reviewer_family": None,
                            "rule_id": str(review["rule_id"]),
                            "escalated_from": escalation_obj,
                        },
                        stamp=stamp,
                    )

                    conn.execute(
                        """update room_board_reviews
                           set reviewer_kind = 'operator',
                               reviewer_participant_id = null,
                               reviewer_family = null,
                               escalation_json = ?,
                               request_activity_id = ?,
                               updated_at = ?
                           where review_id = ?""",
                        (
                            _json(escalation_obj),
                            str(activity["activity_id"]),
                            stamp,
                            str(review["review_id"]),
                        ),
                    )

                    escalated.append(
                        {
                            "review_id": str(review["review_id"]),
                            "conversation_id": conv_id,
                            "module_id": module_id,
                            "reason_code": reason_code,
                            "escalated_from": escalation_obj,
                            "activity_id": str(activity["activity_id"]),
                            "activity_seq": int(activity["seq"]),
                        }
                    )
                conn.commit()
                return escalated
            except Exception:
                conn.rollback()
                raise

    def review_detail(self, conversation_id: str, review_id: str) -> dict[str, Any]:
        """Fetch review detail for one review (§5.1)."""
        with self._connect() as conn:
            row = conn.execute(
                "select * from room_board_reviews where review_id = ? and conversation_id = ?",
                (review_id, conversation_id),
            ).fetchone()
            if row is None:
                raise ValueError("room_board_review_unknown")

            ver_row = conn.execute(
                "select head_commit, patch_text from room_board_verifications "
                "where verification_id = ?",
                (str(row["verification_id"]),),
            ).fetchone()
            head_commit = (
                str(ver_row["head_commit"])
                if ver_row is not None and ver_row["head_commit"] is not None
                else None
            )
            raw_patch = (
                str(ver_row["patch_text"])
                if ver_row is not None and ver_row["patch_text"] is not None
                else ""
            )
            digest = review_digest(
                review_id=review_id,
                verification_id=str(row["verification_id"]),
                head_commit=head_commit,
                patch_text=raw_patch,
            )

            verdict_data = _decode(str(row["verdict_json"])) if row["verdict_json"] else None
            raw_summary = verdict_data.get("summary") if verdict_data else None
            summary = agent_text(raw_summary, max_chars=4000) if raw_summary is not None else None
            findings_raw = verdict_data.get("findings", []) if verdict_data else []

            findings_count = {
                "blocker": sum(
                    1
                    for item in findings_raw
                    if isinstance(item, dict) and item.get("severity") == "blocker"
                ),
                "major": sum(
                    1
                    for item in findings_raw
                    if isinstance(item, dict) and item.get("severity") == "major"
                ),
                "minor": sum(
                    1
                    for item in findings_raw
                    if isinstance(item, dict) and item.get("severity") == "minor"
                ),
            }

            clean_findings: list[dict[str, Any]] = []
            if isinstance(findings_raw, list):
                for item in findings_raw[:32]:
                    if isinstance(item, dict):
                        raw_p = item.get("path")
                        p = raw_p if is_valid_finding_path(raw_p) else None
                        clean_findings.append(
                            {
                                "severity": str(item.get("severity")),
                                "path": p,
                                "text": agent_text(item.get("text"), max_chars=1000),
                            }
                        )

            review_obj = {
                "status": str(row["status"]),
                "review_id": review_id,
                "verification_id": str(row["verification_id"]),
                "digest": digest,
                "rule_id": str(row["rule_id"]),
                "author_family": str(row["author_family"]),
                "reviewer_kind": str(row["reviewer_kind"]),
                "reviewer_participant_id": (
                    str(row["reviewer_participant_id"])
                    if row["reviewer_participant_id"] is not None
                    else None
                ),
                "reviewer_family": (
                    str(row["reviewer_family"]) if row["reviewer_family"] is not None else None
                ),
                "escalated_from": (
                    _decode(str(row["escalation_json"])) if row["escalation_json"] else None
                ),
                "findings_count": findings_count,
                "decided_via": str(row["decided_via"]) if row["decided_via"] else None,
                "updated_at": str(row["updated_at"]),
            }

            raw_inputs = _decode(str(row["rule_inputs_json"])) if row["rule_inputs_json"] else {}
            rule_inputs = {
                "rule_id": str(row["rule_id"]),
                "author_participant_id": str(
                    raw_inputs.get("author_participant_id")
                    or raw_inputs.get("author_id")
                    or row["author_participant_id"]
                ),
                "author_family": str(raw_inputs.get("author_family") or row["author_family"]),
                "eligible": [
                    {
                        "participant_id": str(item["participant_id"]),
                        "family": str(item["family"]),
                        "pending": int(item.get("pending", 0)),
                    }
                    for item in raw_inputs.get("eligible", [])
                ],
                "last_reviewer_participant_id": (
                    raw_inputs.get("last_reviewer_participant_id")
                    or raw_inputs.get("last_reviewer_id")
                ),
                "picked_participant_id": raw_inputs.get("picked_participant_id"),
            }

            decided_at = (
                str(row["updated_at"]) if str(row["status"]) in ("endorsed", "objected") else None
            )

            return {
                "schema_version": "room_board_review/v1",
                "conversation_id": conversation_id,
                "module_id": str(row["module_id"]),
                "review": review_obj,
                "head_commit": head_commit or "",
                "summary": summary,
                "findings": clean_findings,
                "rule_inputs": rule_inputs,
                "created_at": str(row["created_at"]),
                "decided_at": decided_at,
            }

    def verification_detail(self, conversation_id: str, verification_id: str) -> dict[str, Any]:
        """Fetch verification detail for one verification (§5.2)."""
        with self._connect() as conn:
            row = conn.execute(
                "select * from room_board_verifications "
                "where verification_id = ? and conversation_id = ?",
                (verification_id, conversation_id),
            ).fetchone()
            if row is None:
                raise ValueError("room_board_verification_unknown")

            result = _decode(str(row["result_json"])) if row["result_json"] else {}
            evidence = result.get("evidence") if isinstance(result, dict) else {}
            output_tails = evidence.get("output_tails") if isinstance(evidence, dict) else {}
            raw_gates = result.get("gates") if isinstance(result, dict) else []
            clean_gates: list[dict[str, Any]] = []
            if isinstance(raw_gates, list):
                for item in raw_gates:
                    if isinstance(item, dict):
                        gid = str(item.get("gate_id"))
                        raw_tail = output_tails.get(gid) if isinstance(output_tails, dict) else None
                        tail = (
                            agent_text(raw_tail, max_chars=2000) if raw_tail is not None else None
                        )
                        clean_gates.append(
                            {
                                "gate_id": gid,
                                "status": str(item.get("status")),
                                "exit_code": (
                                    int(item["exit_code"])
                                    if item.get("exit_code") is not None
                                    else None
                                ),
                                "reason_code": (
                                    str(item["reason_code"])
                                    if item.get("reason_code") is not None
                                    else None
                                ),
                                "output_tail": tail,
                            }
                        )

            raw_changed = _decode(str(row["changed_paths_json"] or "[]"))
            changed_path_count = len(raw_changed) if isinstance(raw_changed, list) else 0

            raw_stacked = result.get("stacked") if isinstance(result, dict) else []
            clean_stacked = (
                [
                    {
                        "module_id": str(item.get("module_id")),
                        "verification_id": str(item.get("verification_id")),
                    }
                    for item in raw_stacked
                    if isinstance(item, dict)
                ]
                if isinstance(raw_stacked, list)
                else []
            )

            reason_code = result.get("reason_code") if isinstance(result, dict) else None

            return {
                "schema_version": "room_board_verification/v1",
                "conversation_id": conversation_id,
                "module_id": str(row["module_id"]),
                "verification_id": verification_id,
                "status": str(row["status"]),
                "reason_code": str(reason_code) if reason_code is not None else None,
                "head_commit": (
                    str(row["head_commit"]) if row["head_commit"] is not None else None
                ),
                "changed_path_count": changed_path_count,
                "stacked": clean_stacked,
                "gates": clean_gates,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }

    def review_policy(self, conversation_id: str) -> str:
        """Return the room's review policy (``off`` | ``cross_family``)."""
        with self._connect() as conn:
            return review_policy_for_conversation(conn, conversation_id)

    def owner_view(self, conversation_id: str, participant_id: str) -> dict[str, Any]:
        """Pure read of one owner's board slice (no lease, no writes)."""

        with self._connect() as conn:
            charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
            verification_stats = self._module_verification_stats_conn(
                conn, conversation_id=conversation_id
            )
            review_stats = self._module_review_stats_conn(conn, conversation_id=conversation_id)
            my_modules: list[dict[str, Any]] = []
            other_modules: list[dict[str, Any]] = []
            for module_id in sorted(charter_map):
                info = charter_map[module_id]
                if str(info["status"]) != "active":
                    continue
                body = info["charter"] if isinstance(info["charter"], dict) else {}
                provides = list(body.get("provides", [])) if isinstance(body, dict) else []
                depends = list(body.get("depends", [])) if isinstance(body, dict) else []
                review_entry = review_stats.get(module_id) or {
                    "status": None,
                    "review_id": None,
                    "verification_id": None,
                    "reviewer_kind": None,
                    "reviewer_participant_id": None,
                    "reviewer_family": None,
                    "verdict": None,
                    "reviews_endorsed": 0,
                    "reviews_objected": 0,
                }
                if str(info["owner_participant_id"]) == participant_id:
                    charter_row = conn.execute(
                        """select * from room_board_charters
                           where conversation_id = ? and module_id = ?
                           order by version desc limit 1""",
                        (conversation_id, module_id),
                    ).fetchone()
                    assert charter_row is not None
                    lifecycle, state = self._module_lifecycle_state_conn(
                        conn,
                        conversation_id=conversation_id,
                        module_id=module_id,
                        charter_row=charter_row,
                    )
                    my_modules.append(
                        {
                            "module_id": module_id,
                            "version": int(info["version"]),
                            "owner_participant_id": str(info["owner_participant_id"]),
                            "status": str(info["status"]),
                            "charter": body,
                            "lifecycle": lifecycle,
                            "state": state,
                            "verification": verification_stats.get(module_id)
                            or {
                                "status": None,
                                "verification_id": None,
                                "reason_code": None,
                                "result": None,
                                "head_commit": None,
                                "changed_paths": [],
                                "created_at": None,
                                "done_reports": 0,
                                "verifications_passed": 0,
                                "verifications_failed": 0,
                                "rework_rounds": 0,
                            },
                            "review": review_entry,
                        }
                    )
                else:
                    other_modules.append(
                        {
                            "module_id": module_id,
                            "version": int(info["version"]),
                            "owner_participant_id": str(info["owner_participant_id"]),
                            "provides": provides,
                            "depends": depends,
                        }
                    )
            wanted: set[str] = set()
            for entry in my_modules:
                charter = entry.get("charter")
                if not isinstance(charter, dict):
                    continue
                for key in ("provides", "depends"):
                    items = charter.get(key, [])
                    if isinstance(items, list):
                        for contract_id in items:
                            if isinstance(contract_id, str):
                                wanted.add(contract_id)
            contracts: list[dict[str, Any]] = []
            for contract_id in sorted(wanted):
                row = self._latest_contract_conn(
                    conn, conversation_id=conversation_id, contract_id=contract_id
                )
                if row is None:
                    continue
                contracts.append(
                    {
                        "contract_id": str(row["contract_id"]),
                        "version": int(row["version"]),
                        "digest": str(row["digest"]),
                        "provider_module_id": str(row["provider_module_id"]),
                        "kind": str(row["kind"]),
                        "content": str(row["content"]),
                        "author_participant_id": str(row["author_participant_id"]),
                        "rationale": row["rationale"],
                        "activity_id": row["activity_id"],
                        "created_at": str(row["created_at"]),
                    }
                )
            seq_row = conn.execute(
                "select coalesce(max(seq), 0) from room_activities "
                "where conversation_id = ? and activity_type like 'board.%'",
                (conversation_id,),
            ).fetchone()
            board_seq = int(seq_row[0]) if seq_row is not None else 0
            return {
                "conversation_id": conversation_id,
                "participant_id": participant_id,
                "board_seq": board_seq,
                "my_modules": my_modules,
                "other_modules": other_modules,
                "contracts": contracts,
            }

    def board_projection(
        self, conversation_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Operator projection: the ``room_board_projection/v2`` read model."""

        with self._connect() as conn:
            return build_board_projection(
                conn,
                conversation_id,
                now=now or datetime.now(UTC),
            )

    def board_contract_detail(
        self,
        conversation_id: str,
        contract_id: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one contract with content (``room_board_contract/v2``), or None."""

        with self._connect() as conn:
            return build_contract_detail(conn, conversation_id, contract_id, version)

    # -- integration jobs (M2b): durable job, lease, retries, green head ----

    @staticmethod
    def _integration_candidates_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> list[dict[str, str]]:
        """Return the frozen input set: latest accepted verification per module.

        The candidate is the module's latest ``passed`` verification at or after
        the current charter's ``created_at`` (never a newer unverified ``done``),
        endorsed when the room reviews (``capabilities.reviews == 1``).
        """

        rows = conn.execute(
            "select * from room_board_charters where conversation_id = ? "
            "order by module_id, version",
            (conversation_id,),
        ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["module_id"])] = row
        reviews_on = review_policy_for_conversation(conn, conversation_id) == "cross_family"
        endorsed: set[str] = set()
        if reviews_on:
            try:
                endorsed = {
                    str(item["verification_id"])
                    for item in conn.execute(
                        "select verification_id from room_board_reviews "
                        "where conversation_id = ? and status = 'endorsed'",
                        (conversation_id,),
                    ).fetchall()
                }
            except sqlite3.OperationalError:
                endorsed = set()
        candidates: list[dict[str, str]] = []
        for module_id in sorted(latest):
            charter = latest[module_id]
            if str(charter["status"]) != "active":
                continue
            charter_created = str(charter["created_at"])
            picked: str | None = None
            for verification in conn.execute(
                "select verification_id, status, created_at from room_board_verifications "
                "where conversation_id = ? and module_id = ? order by created_at, rowid",
                (conversation_id, module_id),
            ).fetchall():
                if str(verification["status"]) != "passed":
                    continue
                if str(verification["created_at"]) < charter_created:
                    continue
                if reviews_on and str(verification["verification_id"]) not in endorsed:
                    continue
                picked = str(verification["verification_id"])
            if picked is not None:
                candidates.append({"module_id": module_id, "verification_id": picked})
        return candidates

    @staticmethod
    def _integration_candidate_set_key(candidates: Sequence[Mapping[str, str]]) -> str:
        return _json(
            [
                {
                    "module_id": str(item["module_id"]),
                    "verification_id": str(item["verification_id"]),
                }
                for item in sorted(candidates, key=lambda item: str(item["module_id"]))
            ]
        )

    @staticmethod
    def _latest_integration_job_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> sqlite3.Row | None:
        try:
            return conn.execute(
                "select *, rowid as rowid from room_board_integrations "
                "where conversation_id = ? order by created_at desc, rowid desc limit 1",
                (conversation_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None

    @staticmethod
    def _green_head_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> dict[str, Any] | None:
        """Return the current green head: latest ``integrated`` job and its set."""

        try:
            row = conn.execute(
                "select *, rowid as rowid from room_board_integrations "
                "where conversation_id = ? and status = 'integrated' "
                "order by created_at desc, rowid desc limit 1",
                (conversation_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        applied = {
            str(item["module_id"]): str(item["applied_verification_id"])
            for item in conn.execute(
                "select module_id, applied_verification_id from room_board_integration_items "
                "where integration_id = ? and applied_verification_id is not null",
                (str(row["integration_id"]),),
            ).fetchall()
        }
        return {
            "integration_id": str(row["integration_id"]),
            "green_head_commit": row["green_after"],
            "applied": applied,
            "input_set": _decode(str(row["input_set_json"] or "[]")) or [],
        }

    @staticmethod
    def _integration_items_conn(
        conn: sqlite3.Connection, *, integration_id: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "module_id": str(row["module_id"]),
                "verification_id": str(row["verification_id"]),
                "item_order": int(row["item_order"]),
                "role": str(row["role"]),
                "status": str(row["status"]),
                "applied_verification_id": (
                    str(row["applied_verification_id"])
                    if row["applied_verification_id"] is not None
                    else None
                ),
                "conflicts": _decode(str(row["conflicts_json"] or "[]")) or [],
                "conflicts_total": int(row["conflicts_total"]),
                "reason_code": row["reason_code"],
            }
            for row in conn.execute(
                "select * from room_board_integration_items where integration_id = ? "
                "order by item_order, module_id",
                (integration_id,),
            ).fetchall()
        ]

    @staticmethod
    def _integration_order_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        module_ids: list[str],
        roles: Mapping[str, str],
    ) -> list[str]:
        """Dependency-first order; incumbents before newcomers, then module id."""

        in_set = set(module_ids)
        providers = {
            module_id: [
                item
                for item in RoomBoardStore._provider_modules_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                if item in in_set
            ]
            for module_id in module_ids
        }
        return integration_apply_order(module_ids, providers, roles)

    def ensure_board_integration_enqueued(
        self, conversation_id: str, *, now: datetime | None = None
    ) -> str | None:
        """Enqueue one job when the accepted input set changed (worker loop).

        At most one ``pending`` job waits behind a ``running`` one; a set change
        during a running job enqueues the next, otherwise nothing is enqueued.
        """

        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                candidates = self._integration_candidates_conn(
                    conn, conversation_id=conversation_id
                )
                if not candidates:
                    conn.commit()
                    return None
                waiting = conn.execute(
                    "select 1 from room_board_integrations where conversation_id = ? "
                    "and status = 'pending' limit 1",
                    (conversation_id,),
                ).fetchone()
                if waiting is not None:
                    conn.commit()
                    return None
                latest = self._latest_integration_job_conn(conn, conversation_id=conversation_id)
                wanted = self._integration_candidate_set_key(candidates)
                if latest is not None and str(latest["input_set_json"]) == wanted:
                    conn.commit()
                    return None
                green = self._green_head_conn(conn, conversation_id=conversation_id)
                green_applied = green["applied"] if green is not None else {}
                roles = {
                    item["module_id"]: (
                        "incumbent"
                        if green_applied.get(item["module_id"]) == item["verification_id"]
                        else "newcomer"
                    )
                    for item in candidates
                }
                ordered = self._integration_order_conn(
                    conn,
                    conversation_id=conversation_id,
                    module_ids=[item["module_id"] for item in candidates],
                    roles=roles,
                )
                by_module = {item["module_id"]: item["verification_id"] for item in candidates}
                integration_id = _id("boardintegration")
                conn.execute(
                    """insert into room_board_integrations
                        (integration_id, conversation_id, status, reason_code,
                         input_set_json, attempt_count, not_before, auto_retry_count,
                         restart_retry_done, green_before, green_after, result_commit,
                         gates_json, activity_id, created_at, updated_at, finished_at)
                        values (?, ?, 'pending', null, ?, 0, null, 0, 0, ?, null, null,
                                null, null, ?, ?, null)""",
                    (
                        integration_id,
                        conversation_id,
                        wanted,
                        green["green_head_commit"] if green is not None else None,
                        stamp,
                        stamp,
                    ),
                )
                for order, module_id in enumerate(ordered):
                    conn.execute(
                        """insert into room_board_integration_items
                            (integration_id, conversation_id, module_id, verification_id,
                             item_order, role, status, applied_verification_id,
                             conflicts_json, conflicts_total, reason_code, created_at)
                            values (?, ?, ?, ?, ?, ?, 'not_applied', null, '[]', 0, null, ?)""",
                        (
                            integration_id,
                            conversation_id,
                            module_id,
                            by_module[module_id],
                            order,
                            roles[module_id],
                            stamp,
                        ),
                    )
                conn.commit()
                return integration_id
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _integration_view(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "integration_id": str(row["integration_id"]),
            "conversation_id": str(row["conversation_id"]),
            "status": str(row["status"]),
            "reason_code": row["reason_code"],
            "input_set": _decode(str(row["input_set_json"] or "[]")) or [],
            "attempt_count": int(row["attempt_count"]),
            "lease_token": row["lease_token"],
            "lease_expires_at": row["lease_expires_at"],
            "not_before": row["not_before"],
            "auto_retry_count": int(row["auto_retry_count"] or 0),
            "restart_retry_done": int(row["restart_retry_done"] or 0),
            "green_before": row["green_before"],
            "green_after": row["green_after"],
            "result_commit": row["result_commit"],
            "gates": _decode(str(row["gates_json"])) if row["gates_json"] else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "finished_at": row["finished_at"],
        }

    def _write_integration_error_conn(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        stamp: str,
    ) -> dict[str, Any]:
        """Mark an attempts-exhausted job ``error`` with its activity."""

        conversation_id = str(row["conversation_id"])
        green = self._green_head_conn(conn, conversation_id=conversation_id)
        causation, depth = self._integration_causation_conn(conn, conversation_id=conversation_id)
        activity = self._insert_board_activity_conn(
            conn,
            conversation_id=conversation_id,
            activity_type="board.integration",
            actor_kind="infrastructure",
            actor_identity="infrastructure:board-integration",
            actor_participant_id=None,
            causation_id=causation,
            causal_depth=depth,
            audience_participant_ids=[],
            payload={
                "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                "integration_id": str(row["integration_id"]),
                "status": "error",
                "reason_code": BOARD_INTEGRATION_ATTEMPTS_EXHAUSTED,
                "green_head_commit": green["green_head_commit"] if green is not None else None,
                "integrated_module_ids": sorted(green["applied"] if green is not None else {}),
                "suspect_module_ids": [],
                "conflicts": [],
                "waiting_module_ids": [],
                "gate_ids": [],
            },
            stamp=stamp,
        )
        conn.execute(
            "update room_board_integrations set status = 'error', "
            "reason_code = ?, lease_owner = null, lease_token = null, "
            "lease_expires_at = null, not_before = ?, activity_id = ?, "
            "finished_at = ?, updated_at = ? "
            "where integration_id = ? and status = 'pending'",
            (
                BOARD_INTEGRATION_ATTEMPTS_EXHAUSTED,
                stamp,
                str(activity["activity_id"]),
                stamp,
                stamp,
                str(row["integration_id"]),
            ),
        )
        return {
            "integration_id": str(row["integration_id"]),
            "status": "error",
            "activity_id": str(activity["activity_id"]),
        }

    def claim_next_board_integration(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = INTEGRATION_LEASE_TTL_S,
        max_attempts: int = MAX_INTEGRATION_ATTEMPTS,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Claim one pending integration job with a lease (``pending→running``).

        Expired ``running`` rows return to ``pending`` on the next claim; rows
        that exhausted ``max_attempts`` become ``error`` with an activity.
        """

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("room_board_worker_id_required")
        if (
            isinstance(lease_ttl_s, bool)
            or not isinstance(lease_ttl_s, int)
            or not 5 <= lease_ttl_s <= 7200
        ):
            raise ValueError("room_board_lease_ttl_invalid")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ValueError("room_board_max_attempts_invalid")
        if max_attempts < 1:
            raise ValueError("room_board_max_attempts_invalid")
        current, stamp = _current_stamp(now)
        expires = _timestamp(current + timedelta(seconds=lease_ttl_s))
        lease_token = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    "update room_board_integrations set status = 'pending', "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "updated_at = ? where status = 'running' and lease_expires_at is not null "
                    "and lease_expires_at <= ?",
                    (stamp, stamp),
                )
                exhausted = conn.execute(
                    "select * from room_board_integrations "
                    "where status = 'pending' and attempt_count >= ? "
                    "order by created_at, rowid",
                    (max_attempts,),
                ).fetchall()
                for expired in exhausted:
                    self._write_integration_error_conn(conn, row=expired, stamp=stamp)
                row = conn.execute(
                    "select * from room_board_integrations where status = 'pending' "
                    "and (not_before is null or not_before <= ?) "
                    "order by created_at, rowid limit 1",
                    (stamp,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                changed = conn.execute(
                    "update room_board_integrations set status = 'running', "
                    "attempt_count = attempt_count + 1, lease_owner = ?, lease_token = ?, "
                    "lease_expires_at = ?, updated_at = ? "
                    "where integration_id = ? and status = 'pending'",
                    (
                        worker_id,
                        lease_token,
                        expires,
                        stamp,
                        str(row["integration_id"]),
                    ),
                ).rowcount
                if changed != 1:
                    conn.commit()
                    return None
                claimed = conn.execute(
                    "select * from room_board_integrations where integration_id = ?",
                    (str(row["integration_id"]),),
                ).fetchone()
                assert claimed is not None
                result = self._integration_view(claimed)
                result["items"] = self._integration_items_conn(
                    conn, integration_id=str(row["integration_id"])
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def abandon_board_integration(
        self,
        *,
        integration_id: str,
        lease_token: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Release a claimed job back to ``pending`` after a transient failure."""

        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValueError("room_board_integration_reason_required")
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_board_integration_lease_lost")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_board_integrations where integration_id = ?",
                    (integration_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_integration_unknown")
                if str(row["status"]) in ("integrated", "conflicted", "gate_failed", "error"):
                    conn.commit()
                    return {"integration_id": integration_id, "status": str(row["status"])}
                if str(row["status"]) != "running" or row["lease_token"] != lease_token:
                    raise ValueError("room_board_integration_lease_lost")
                conn.execute(
                    "update room_board_integrations set status = 'pending', "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "reason_code = ?, updated_at = ? where integration_id = ?",
                    (reason_code, stamp, integration_id),
                )
                conn.commit()
                return {"integration_id": integration_id, "status": "pending"}
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _integration_causation_conn(
        conn: sqlite3.Connection, *, conversation_id: str
    ) -> tuple[str, int]:
        """Causation for a ``board.integration`` activity: newest board activity."""

        row = conn.execute(
            "select activity_id, causal_depth from room_activities "
            "where conversation_id = ? and activity_type like 'board.%' "
            "order by seq desc limit 1",
            (conversation_id,),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "select activity_id, causal_depth from room_activities "
                "where conversation_id = ? order by seq desc limit 1",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise ValueError("room_board_integration_causation_unknown")
        return str(row["activity_id"]), int(row["causal_depth"]) + 1

    def complete_board_integration(
        self,
        *,
        integration_id: str,
        lease_token: str,
        status: str,
        reason_code: str | None,
        green_after: str | None,
        result_commit: str | None,
        gates: list[dict[str, Any]],
        evidence: dict[str, Any] | None,
        items: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record a terminal integration result with its ``board.integration``.

        The activity (actor ``infrastructure``) and the terminal state commit
        atomically; wakes follow §3.11 conflict attribution (conflict: owners
        plus lead/report_to; gate_failed: lead; integrated/error: nobody).
        """

        if status not in ("integrated", "conflicted", "gate_failed", "error"):
            raise ValueError("room_board_integration_status_invalid")
        if status != "integrated" and (not isinstance(reason_code, str) or not reason_code.strip()):
            raise ValueError("room_board_integration_reason_required")
        if not isinstance(items, list) or not items:
            raise ValueError("room_board_integration_items_invalid")
        clean_gates: list[dict[str, Any]] = []
        for entry in gates:
            if not isinstance(entry, dict) or not isinstance(entry.get("gate_id"), str):
                raise ValueError("room_board_integration_gates_invalid")
            exit_code = entry.get("exit_code")
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                raise ValueError("room_board_integration_gates_invalid")
            gate_status = entry.get("status")
            if gate_status not in ("passed", "failed", "cancelled"):
                raise ValueError("room_board_integration_gates_invalid")
            clean_gates.append(
                {
                    "gate_id": str(entry["gate_id"]),
                    "status": str(gate_status),
                    "exit_code": exit_code,
                    "reason_code": entry.get("reason_code"),
                }
            )
        clean_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError("room_board_integration_items_invalid")
            module_id = entry.get("module_id")
            item_status = entry.get("status")
            if (
                not isinstance(module_id, str)
                or not module_id
                or item_status not in BOARD_INTEGRATION_ITEM_STATUSES
                or module_id in seen
            ):
                raise ValueError("room_board_integration_items_invalid")
            seen.add(module_id)
            conflicts = entry.get("conflicts") or []
            if not isinstance(conflicts, list):
                raise ValueError("room_board_integration_items_invalid")
            clean_conflicts: list[dict[str, Any]] = []
            for conflict in conflicts:
                if not isinstance(conflict, dict) or not isinstance(conflict.get("path"), str):
                    raise ValueError("room_board_integration_items_invalid")
                attributed = conflict.get("attributed_module_ids") or []
                if not isinstance(attributed, list) or any(
                    not isinstance(item, str) for item in attributed
                ):
                    raise ValueError("room_board_integration_items_invalid")
                clean_conflicts.append(
                    {"path": str(conflict["path"]), "attributed_module_ids": list(attributed)}
                )
            conflicts_total = entry.get("conflicts_total", len(clean_conflicts))
            if (
                isinstance(conflicts_total, bool)
                or not isinstance(conflicts_total, int)
                or conflicts_total < len(clean_conflicts)
            ):
                raise ValueError("room_board_integration_items_invalid")
            applied = entry.get("applied_verification_id")
            if applied is not None and (not isinstance(applied, str) or not applied):
                raise ValueError("room_board_integration_items_invalid")
            item_reason = entry.get("reason_code")
            if item_reason is not None and (
                not isinstance(item_reason, str) or not item_reason.strip()
            ):
                raise ValueError("room_board_integration_items_invalid")
            clean_items.append(
                {
                    "module_id": module_id,
                    "status": str(item_status),
                    "applied_verification_id": applied,
                    "conflicts": clean_conflicts,
                    "conflicts_total": conflicts_total,
                    "reason_code": item_reason,
                }
            )
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("room_board_integration_lease_lost")
        _, stamp = _current_stamp(now)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_board_integrations where integration_id = ?",
                    (integration_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_integration_unknown")
                if str(row["status"]) in ("integrated", "conflicted", "gate_failed", "error"):
                    conn.commit()
                    return {"integration_id": integration_id, "status": str(row["status"])}
                if (
                    str(row["status"]) != "running"
                    or row["lease_token"] != lease_token
                    or (
                        row["lease_expires_at"] is not None
                        and str(row["lease_expires_at"]) <= stamp
                    )
                ):
                    raise ValueError("room_board_integration_lease_lost")
                conversation_id = str(row["conversation_id"])
                stored = {
                    item["module_id"]: item
                    for item in self._integration_items_conn(conn, integration_id=integration_id)
                }
                if set(stored) != {item["module_id"] for item in clean_items}:
                    raise ValueError("room_board_integration_items_invalid")
                candidate_of = {
                    item["module_id"]: item["verification_id"] for item in stored.values()
                }
                for item in clean_items:
                    conn.execute(
                        "update room_board_integration_items set status = ?, "
                        "applied_verification_id = ?, conflicts_json = ?, "
                        "conflicts_total = ?, reason_code = ? "
                        "where integration_id = ? and module_id = ?",
                        (
                            item["status"],
                            item["applied_verification_id"],
                            _json(item["conflicts"]),
                            item["conflicts_total"],
                            item["reason_code"],
                            integration_id,
                            item["module_id"],
                        ),
                    )
                if status == "integrated":
                    green_head = green_after
                    integrated_ids = sorted(
                        item["module_id"]
                        for item in clean_items
                        if item["applied_verification_id"] is not None
                    )
                else:
                    green_head = row["green_before"]
                    previous = self._green_head_conn(conn, conversation_id=conversation_id)
                    integrated_ids = sorted(previous["applied"]) if previous is not None else []
                suspect_ids = (
                    sorted(
                        item["module_id"]
                        for item in clean_items
                        if item["status"] in ("applied", "fell_back")
                        and stored[item["module_id"]]["role"] == "newcomer"
                    )
                    if status == "gate_failed"
                    else []
                )
                conflict_entries: list[dict[str, Any]] = []
                for item in sorted(clean_items, key=lambda entry: entry["module_id"]):
                    if item["status"] not in ("conflicted", "fell_back"):
                        continue
                    attributed_union = sorted(
                        {
                            attributed
                            for conflict in item["conflicts"]
                            for attributed in conflict["attributed_module_ids"]
                        }
                    )
                    conflict_entries.append(
                        {
                            "module_id": item["module_id"],
                            "conflict_path_count": item["conflicts_total"],
                            "attributed_module_ids": attributed_union,
                            "fell_back": (
                                item["applied_verification_id"] is not None
                                and item["applied_verification_id"]
                                != candidate_of[item["module_id"]]
                            ),
                        }
                    )
                waiting_ids = sorted(
                    item["module_id"] for item in clean_items if item["status"] == "waiting"
                )
                failed_gate_ids = sorted(
                    {entry["gate_id"] for entry in clean_gates if entry["status"] != "passed"}
                )
                charter_map = self._active_charter_owner_map(conn, conversation_id=conversation_id)
                lead = self._lead_participant_id(conn, conversation_id)
                wake: list[str] = []
                if status == "gate_failed":
                    if lead:
                        wake = [lead]
                elif status == "conflicted":
                    woken: set[str] = set()
                    for item in clean_items:
                        if item["status"] not in ("conflicted", "fell_back", "waiting"):
                            continue
                        info = charter_map.get(item["module_id"])
                        if info is not None and info["status"] == "active":
                            woken.add(str(info["owner_participant_id"]))
                            charter = info["charter"]
                            report_to = (
                                charter.get("report_to") if isinstance(charter, dict) else None
                            )
                            if isinstance(report_to, str) and report_to:
                                woken.add(report_to)
                            elif lead:
                                woken.add(lead)
                    for entry in conflict_entries:
                        for attributed in entry["attributed_module_ids"]:
                            info = charter_map.get(attributed)
                            if info is not None and info["status"] == "active":
                                woken.add(str(info["owner_participant_id"]))
                    wake = sorted(woken)
                causation, depth = self._integration_causation_conn(
                    conn, conversation_id=conversation_id
                )
                activity = self._insert_board_activity_conn(
                    conn,
                    conversation_id=conversation_id,
                    activity_type="board.integration",
                    actor_kind="infrastructure",
                    actor_identity="infrastructure:board-integration",
                    actor_participant_id=None,
                    causation_id=causation,
                    causal_depth=depth,
                    audience_participant_ids=list(wake),
                    payload={
                        "schema_version": BOARD_ACTIVITY_SCHEMA_VERSION,
                        "integration_id": integration_id,
                        "status": status,
                        "reason_code": reason_code,
                        "green_head_commit": green_head,
                        "integrated_module_ids": integrated_ids,
                        "suspect_module_ids": suspect_ids,
                        "conflicts": conflict_entries,
                        "waiting_module_ids": waiting_ids,
                        "gate_ids": failed_gate_ids,
                    },
                    stamp=stamp,
                )
                gates_json = _json({"gates": clean_gates, "evidence": evidence or {}})
                if len(gates_json.encode("utf-8")) > MAX_VERIFICATION_EVIDENCE_BYTES:
                    raise ValueError("room_board_integration_evidence_too_large")
                conn.execute(
                    "update room_board_integrations set status = ?, reason_code = ?, "
                    "lease_owner = null, lease_token = null, lease_expires_at = null, "
                    "not_before = null, green_after = ?, result_commit = ?, "
                    "gates_json = ?, activity_id = ?, finished_at = ?, updated_at = ? "
                    "where integration_id = ?",
                    (
                        status,
                        reason_code,
                        green_head,
                        result_commit,
                        gates_json,
                        str(activity["activity_id"]),
                        stamp,
                        stamp,
                        integration_id,
                    ),
                )
                woken_rows: list[dict[str, Any]] = []
                if wake:
                    woken_rows = self._wake_participants_conn(
                        conn,
                        conversation_id=conversation_id,
                        activity_id=str(activity["activity_id"]),
                        participant_ids=wake,
                        stamp=stamp,
                    )
                conn.commit()
                return {
                    "integration_id": integration_id,
                    "status": status,
                    "activity_id": str(activity["activity_id"]),
                    "activity_seq": int(activity["seq"]),
                    "woken_participant_ids": [item["participant_id"] for item in woken_rows],
                }
            except Exception:
                conn.rollback()
                raise

    def revive_due_board_integrations(
        self,
        *,
        now: datetime | None = None,
        delays_s: Sequence[float] = (600.0, 1800.0),
    ) -> list[str]:
        """Requeue ``error`` jobs whose automatic retry delay elapsed (bounded).

        Only the room's latest job is revived, with the same frozen set; each
        delay is consumed once, so an ``error`` job re-runs at most
        ``len(delays_s)`` times before staying ``error`` until the set changes.
        """

        if not isinstance(delays_s, Sequence) or any(
            not isinstance(item, (int, float)) or isinstance(item, bool) or item <= 0
            for item in delays_s
        ):
            raise ValueError("room_board_integration_delays_invalid")
        current, stamp = _current_stamp(now)
        revived: list[str] = []
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                rooms = conn.execute(
                    "select distinct conversation_id from room_board_integrations"
                ).fetchall()
                for entry in rooms:
                    conversation_id = str(entry["conversation_id"])
                    latest = self._latest_integration_job_conn(
                        conn, conversation_id=conversation_id
                    )
                    if latest is None or str(latest["status"]) != "error":
                        continue
                    used = int(latest["auto_retry_count"] or 0)
                    if used >= len(delays_s) or latest["finished_at"] is None:
                        continue
                    due_at = _parse_timestamp(str(latest["finished_at"])) + timedelta(
                        seconds=float(delays_s[used])
                    )
                    if due_at.tzinfo is None:
                        due_at = due_at.replace(tzinfo=UTC)
                    if current < due_at:
                        continue
                    conn.execute(
                        "update room_board_integrations set status = 'pending', "
                        "reason_code = null, attempt_count = 0, not_before = null, "
                        "auto_retry_count = auto_retry_count + 1, finished_at = null, "
                        "updated_at = ? where integration_id = ? and status = 'error'",
                        (stamp, str(latest["integration_id"])),
                    )
                    revived.append(str(latest["integration_id"]))
                conn.commit()
                return revived
            except Exception:
                conn.rollback()
                raise

    def revive_board_integrations_after_restart(
        self,
        *,
        delays_s: Sequence[float] = (600.0, 1800.0),
    ) -> list[str]:
        """Requeue each room's latest ``error`` job once after a host restart.

        Only jobs whose timed retries are exhausted are eligible, so restarts
        never multiply the bounded automatic re-runs.
        """

        _, stamp = _current_stamp(None)
        revived: list[str] = []
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                rooms = conn.execute(
                    "select distinct conversation_id from room_board_integrations"
                ).fetchall()
                for entry in rooms:
                    conversation_id = str(entry["conversation_id"])
                    latest = self._latest_integration_job_conn(
                        conn, conversation_id=conversation_id
                    )
                    if latest is None or str(latest["status"]) != "error":
                        continue
                    if int(latest["restart_retry_done"] or 0) != 0:
                        continue
                    if int(latest["auto_retry_count"] or 0) < len(tuple(delays_s)):
                        continue
                    conn.execute(
                        "update room_board_integrations set status = 'pending', "
                        "reason_code = null, attempt_count = 0, not_before = null, "
                        "restart_retry_done = 1, finished_at = null, updated_at = ? "
                        "where integration_id = ? and status = 'error'",
                        (stamp, str(latest["integration_id"])),
                    )
                    revived.append(str(latest["integration_id"]))
                conn.commit()
                return revived
            except Exception:
                conn.rollback()
                raise

    def board_integration_inputs(self, conversation_id: str) -> dict[str, Any]:
        """Read everything the integration engine needs (no writes, no clock)."""

        with self._connect() as conn:
            rows = conn.execute(
                "select * from room_board_charters where conversation_id = ? "
                "order by module_id, version",
                (conversation_id,),
            ).fetchall()
            latest: dict[str, sqlite3.Row] = {}
            for row in rows:
                latest[str(row["module_id"])] = row
            charters: dict[str, dict[str, Any]] = {}
            for module_id, row in sorted(latest.items()):
                if str(row["status"]) != "active":
                    continue
                body = _decode(str(row["charter_json"]))
                charters[module_id] = {
                    "owner_participant_id": str(row["owner_participant_id"]),
                    "version": int(row["version"]),
                    "created_at": str(row["created_at"]),
                    "charter": body if isinstance(body, dict) else {},
                }
            candidates = self._integration_candidates_conn(conn, conversation_id=conversation_id)
            wanted = {item["module_id"] for item in candidates}
            verifications: dict[str, dict[str, Any]] = {}
            for item in candidates:
                row = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (item["verification_id"],),
                ).fetchone()
                if row is None:
                    continue
                result = _decode(row["result_json"]) if row["result_json"] else {}
                base_commit = None
                if isinstance(result, dict):
                    raw_base = result.get("base_commit")
                    if isinstance(raw_base, str) and raw_base:
                        base_commit = raw_base
                changed = _decode(str(row["changed_paths_json"] or "[]"))
                verifications[item["module_id"]] = {
                    "verification_id": item["verification_id"],
                    "patch_text": row["patch_text"],
                    "changed_paths": list(changed) if isinstance(changed, list) else [],
                    "base_commit": base_commit,
                    "head_commit": row["head_commit"],
                    "created_at": str(row["created_at"]),
                }
            missing = [module_id for module_id in wanted if module_id not in verifications]
            if missing:
                raise ValueError("room_board_integration_candidate_unknown")
            providers = {
                module_id: self._provider_modules_conn(
                    conn, conversation_id=conversation_id, module_id=module_id
                )
                for module_id in charters
            }
            green = self._green_head_conn(conn, conversation_id=conversation_id)
            latest_job = self._latest_integration_job_conn(conn, conversation_id=conversation_id)
            return {
                "conversation_id": conversation_id,
                "charters": charters,
                "candidates": candidates,
                "verifications": verifications,
                "providers": providers,
                "green": green,
                "latest_job": (
                    self._integration_view(latest_job) if latest_job is not None else None
                ),
                "reviews_on": review_policy_for_conversation(conn, conversation_id)
                == "cross_family",
            }

    def rooms_with_board_charters(self) -> list[str]:
        """Return every conversation holding board charters (enqueue sweep)."""

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "select distinct conversation_id from room_board_charters order by "
                    "conversation_id"
                ).fetchall()
            except sqlite3.OperationalError:
                return []
            return [str(row["conversation_id"]) for row in rows]

    def board_integration_patches(
        self, verification_ids: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        """Return stored patch bytes for candidate and fallback verifications."""

        with self._connect() as conn:
            patches: dict[str, dict[str, Any]] = {}
            for verification_id in verification_ids:
                row = conn.execute(
                    "select * from room_board_verifications where verification_id = ?",
                    (verification_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("room_board_integration_candidate_unknown")
                result = _decode(row["result_json"]) if row["result_json"] else {}
                base_commit = None
                if isinstance(result, dict):
                    raw_base = result.get("base_commit")
                    if isinstance(raw_base, str) and raw_base:
                        base_commit = raw_base
                changed = _decode(str(row["changed_paths_json"] or "[]"))
                patch_text = row["patch_text"]
                if not isinstance(patch_text, str) or not patch_text.strip():
                    raise ValueError("room_board_integration_candidate_unknown")
                patches[verification_id] = {
                    "patch_text": patch_text,
                    "changed_paths": list(changed) if isinstance(changed, list) else [],
                    "base_commit": base_commit,
                    "head_commit": row["head_commit"],
                }
            return patches

    def get_board_integration(self, integration_id: str) -> dict[str, Any] | None:
        """Return one job with its items, or None when unknown."""

        with self._connect() as conn:
            try:
                row = conn.execute(
                    "select * from room_board_integrations where integration_id = ?",
                    (integration_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
            if row is None:
                return None
            result = self._integration_view(row)
            result["items"] = self._integration_items_conn(conn, integration_id=integration_id)
            return result
