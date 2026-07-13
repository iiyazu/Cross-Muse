"""Strict, authority-free contracts for exact Room execution patches.

This module deliberately knows nothing about subprocesses or the workspace.  It
only accepts a bounded textual patch and produces canonical metadata that the
durable execution ledger can bind to a proposal.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

EXECUTION_PATCH_SCHEMA: Literal["room_execution_patch/v1"] = "room_execution_patch/v1"
EXECUTION_RISK_POLICY_REVISION = "room_execution_low_risk/v1"
MAX_EXECUTION_PATCH_BYTES = 200 * 1024
MAX_EXECUTION_PATCH_FILES = 32
MAX_EXECUTION_SUMMARY_BYTES = 4 * 1024
MAX_ASSESSMENTS_PER_OUTCOME = 16
MAX_ASSESSMENT_RATIONALE_BYTES = 2 * 1024

_HEAD_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN_PATCH_HEADERS = (
    "rename from ",
    "rename to ",
    "similarity index ",
    "dissimilarity index ",
    "copy from ",
    "copy to ",
    "old mode ",
    "new mode ",
)


class RoomExecutionContractError(ValueError):
    """Stable validation failure for an untrusted execution contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionPatchFile:
    path: str
    change_type: Literal["modify", "add", "delete"]
    hunk_count: int


@dataclass(frozen=True)
class ExecutionPatch:
    schema_version: Literal["room_execution_patch/v1"]
    base_head: str
    summary: str
    unified_diff: str
    allowed_files: tuple[str, ...]
    files: tuple[ExecutionPatchFile, ...]
    candidate_digest: str
    patch_sha256: str
    patch_bytes: int

    @property
    def modify_only(self) -> bool:
        return all(item.change_type == "modify" for item in self.files)

    def safe_reference(self) -> dict[str, Any]:
        """Return metadata safe for Room activities, request logs, and browsers."""

        return {
            "schema_version": self.schema_version,
            "base_head": self.base_head,
            "summary": self.summary,
            "allowed_files": list(self.allowed_files),
            "candidate_digest": self.candidate_digest,
            "patch_sha256": self.patch_sha256,
            "patch_bytes": self.patch_bytes,
            "file_count": len(self.files),
            "modify_only": self.modify_only,
        }


@dataclass(frozen=True)
class ProposalAssessment:
    proposal_id: str
    candidate_digest: str
    assessment: Literal["endorse", "object", "abstain"]
    rationale: str


@dataclass(frozen=True)
class ExecutionWorkspaceGuard:
    """Trusted workspace facts supplied by the privileged application/controller."""

    base_head: str
    workspace_clean: bool
    target_files_digest: str
    existing_regular_files: frozenset[str]


@dataclass(frozen=True)
class ExecutionRiskEvaluation:
    """Trusted server-side policy result; never accepted from an Agent or browser."""

    approved: bool
    policy_revision: str
    evidence_digest: str
    reason_code: str | None = None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _bounded_text(value: object, *, code: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise RoomExecutionContractError(code)
    result = value.strip()
    if not result or len(result.encode("utf-8")) > maximum or _CONTROL_RE.search(result):
        raise RoomExecutionContractError(code)
    return result


def canonical_execution_path(value: object) -> str:
    """Validate one exact POSIX repository-relative path without normalizing it."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise RoomExecutionContractError("room_execution_patch_path_invalid")
    if (
        "\\" in value
        or _CONTROL_RE.search(value)
        or unicodedata.normalize("NFC", value) != value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        raise RoomExecutionContractError("room_execution_patch_path_invalid")
    path = PurePosixPath(value)
    parts = path.parts
    if (
        not parts
        or str(path) != value
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].casefold() == ".git"
        or any(part.casefold() == ".git" for part in parts)
        or (len(parts[0]) >= 2 and parts[0][1] == ":")
    ):
        raise RoomExecutionContractError("room_execution_patch_path_invalid")
    if path.name.casefold() == ".gitmodules":
        raise RoomExecutionContractError("room_execution_patch_submodule_forbidden")
    return value


def _diff_header_paths(line: str) -> tuple[str, str]:
    try:
        tokens = shlex.split(line, posix=True)
    except ValueError as exc:
        raise RoomExecutionContractError("room_execution_patch_diff_invalid") from exc
    if len(tokens) != 4 or tokens[:2] != ["diff", "--git"]:
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    old, new = tokens[2:]
    if not old.startswith("a/") or not new.startswith("b/"):
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    return canonical_execution_path(old[2:]), canonical_execution_path(new[2:])


def _file_header_path(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    value = line[len(prefix) :]
    if "\t" in value:
        value = value.split("\t", 1)[0]
    if value == "/dev/null":
        return None
    expected = "a/" if prefix == "--- " else "b/"
    if not value.startswith(expected):
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    return canonical_execution_path(value[2:])


def _parse_unified_diff(value: object) -> tuple[str, tuple[ExecutionPatchFile, ...]]:
    if not isinstance(value, str):
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RoomExecutionContractError("room_execution_patch_diff_invalid") from exc
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    raw = normalized.encode("utf-8")
    if not normalized or len(raw) > MAX_EXECUTION_PATCH_BYTES:
        raise RoomExecutionContractError("room_execution_patch_size_invalid")
    if "\x00" in normalized or "GIT binary patch" in normalized:
        raise RoomExecutionContractError("room_execution_patch_binary_forbidden")
    if re.search(r"^Binary files .+ differ$", normalized, flags=re.MULTILINE):
        raise RoomExecutionContractError("room_execution_patch_binary_forbidden")
    if "Subproject commit " in normalized:
        raise RoomExecutionContractError("room_execution_patch_submodule_forbidden")

    lines = normalized.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("diff --git ")]
    if not starts or starts[0] != 0 or len(starts) > MAX_EXECUTION_PATCH_FILES:
        raise RoomExecutionContractError("room_execution_patch_diff_invalid")
    starts.append(len(lines))
    files: list[ExecutionPatchFile] = []
    seen: set[str] = set()
    for position in range(len(starts) - 1):
        block = lines[starts[position] : starts[position + 1]]
        old_header, new_header = _diff_header_paths(block[0])
        if old_header != new_header:
            raise RoomExecutionContractError("room_execution_patch_rename_forbidden")
        if any(line.startswith(_FORBIDDEN_PATCH_HEADERS) for line in block[1:]):
            raise RoomExecutionContractError("room_execution_patch_metadata_forbidden")
        for line in block[1:]:
            if line.startswith(("new file mode ", "deleted file mode ")) and not line.endswith(
                "100644"
            ):
                raise RoomExecutionContractError("room_execution_patch_mode_forbidden")
            if line.startswith("index ") and line.endswith((" 120000", " 160000")):
                raise RoomExecutionContractError("room_execution_patch_mode_forbidden")
        old_index = next((i for i, line in enumerate(block) if line.startswith("--- ")), None)
        if old_index is None or old_index + 1 >= len(block):
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        old_path = _file_header_path(block[old_index], "--- ")
        new_path = _file_header_path(block[old_index + 1], "+++ ")
        if old_path is None and new_path is None:
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        path = new_path or old_path
        assert path is not None
        if old_path not in {None, old_header} or new_path not in {None, new_header}:
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        if path != old_header or path != new_header or path in seen:
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        hunk_count = sum(1 for line in block[old_index + 2 :] if _HUNK_RE.fullmatch(line))
        if hunk_count == 0:
            raise RoomExecutionContractError("room_execution_patch_mode_only_forbidden")
        change_type: Literal["modify", "add", "delete"]
        if old_path is None:
            change_type = "add"
        elif new_path is None:
            change_type = "delete"
        else:
            change_type = "modify"
        if change_type == "add" and "new file mode 100644" not in block:
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        if change_type == "delete" and "deleted file mode 100644" not in block:
            raise RoomExecutionContractError("room_execution_patch_diff_invalid")
        seen.add(path)
        files.append(ExecutionPatchFile(path, change_type, hunk_count))
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized, tuple(files)


def normalize_execution_patch(value: object) -> ExecutionPatch:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "base_head",
        "summary",
        "unified_diff",
        "allowed_files",
    }:
        raise RoomExecutionContractError("room_execution_patch_invalid")
    if value["schema_version"] != EXECUTION_PATCH_SCHEMA:
        raise RoomExecutionContractError("room_execution_patch_schema_invalid")
    base_head = value["base_head"]
    if not isinstance(base_head, str) or _HEAD_RE.fullmatch(base_head) is None:
        raise RoomExecutionContractError("room_execution_patch_base_head_invalid")
    summary = _bounded_text(
        value["summary"],
        code="room_execution_patch_summary_invalid",
        maximum=MAX_EXECUTION_SUMMARY_BYTES,
    )
    raw_allowed = value["allowed_files"]
    if (
        not isinstance(raw_allowed, list)
        or not raw_allowed
        or len(raw_allowed) > MAX_EXECUTION_PATCH_FILES
    ):
        raise RoomExecutionContractError("room_execution_patch_allowed_files_invalid")
    allowed = tuple(canonical_execution_path(item) for item in raw_allowed)
    if len(set(allowed)) != len(allowed):
        raise RoomExecutionContractError("room_execution_patch_allowed_files_invalid")
    unified_diff, files = _parse_unified_diff(value["unified_diff"])
    parsed_paths = tuple(item.path for item in files)
    if set(parsed_paths) != set(allowed) or len(parsed_paths) != len(allowed):
        raise RoomExecutionContractError("room_execution_patch_allowed_files_mismatch")
    canonical_allowed = tuple(sorted(allowed))
    digest = _digest(
        {
            "schema_version": EXECUTION_PATCH_SCHEMA,
            "base_head": base_head,
            "summary": summary,
            "unified_diff": unified_diff,
            "allowed_files": canonical_allowed,
        }
    )
    return ExecutionPatch(
        schema_version=EXECUTION_PATCH_SCHEMA,
        base_head=base_head,
        summary=summary,
        unified_diff=unified_diff,
        allowed_files=canonical_allowed,
        files=tuple(sorted(files, key=lambda item: item.path)),
        candidate_digest=digest,
        patch_sha256=f"sha256:{hashlib.sha256(unified_diff.encode('utf-8')).hexdigest()}",
        patch_bytes=len(unified_diff.encode("utf-8")),
    )


def normalize_proposal_assessments(value: object) -> tuple[ProposalAssessment, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ASSESSMENTS_PER_OUTCOME:
        raise RoomExecutionContractError("room_execution_assessments_invalid")
    result: list[ProposalAssessment] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "proposal_id",
            "candidate_digest",
            "assessment",
            "rationale",
        }:
            raise RoomExecutionContractError("room_execution_assessment_invalid")
        proposal_id = _bounded_text(
            raw["proposal_id"], code="room_execution_assessment_invalid", maximum=256
        )
        digest = raw["candidate_digest"]
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise RoomExecutionContractError("room_execution_assessment_digest_invalid")
        assessment = raw["assessment"]
        if assessment not in {"endorse", "object", "abstain"}:
            raise RoomExecutionContractError("room_execution_assessment_invalid")
        rationale = _bounded_text(
            raw["rationale"],
            code="room_execution_assessment_rationale_invalid",
            maximum=MAX_ASSESSMENT_RATIONALE_BYTES,
        )
        if proposal_id in seen:
            raise RoomExecutionContractError("room_execution_assessment_duplicate")
        seen.add(proposal_id)
        result.append(ProposalAssessment(proposal_id, digest, assessment, rationale))
    return tuple(result)


def low_risk_patch_eligible(patch: ExecutionPatch) -> bool:
    """Apply the immutable built-in ceiling before a trusted evaluator can approve."""

    if patch.patch_bytes > 64 * 1024 or len(patch.files) > 5 or not patch.modify_only:
        return False
    forbidden_names = {
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "poetry.lock",
        "dockerfile",
    }
    forbidden_parts = {
        ".github",
        ".gitlab",
        "ci",
        "deploy",
        "deployment",
        "auth",
        "migrations",
        "migration",
        "runtime",
        "harness",
        "policy",
        "policies",
    }
    for item in patch.files:
        path = PurePosixPath(item.path)
        lowered = {part.casefold() for part in path.parts}
        backend_code = item.path.startswith(
            ("src/xmuse_core/", "xmuse/", "tests/xmuse/", "scripts/")
        ) and path.suffix.casefold() in {".py", ".pyi"}
        frontend_code = item.path.startswith(
            ("frontend/src/", "frontend/tests/", "frontend/e2e/")
        ) and path.suffix.casefold() in {".ts", ".tsx", ".css"}
        if not (backend_code or frontend_code):
            return False
        if path.name.casefold() in forbidden_names or lowered & forbidden_parts:
            return False
        if path.suffix.casefold() in {".lock", ".toml"} and "test" not in lowered:
            return False
        if "database" in lowered or "schema" in lowered:
            return False
    return True
