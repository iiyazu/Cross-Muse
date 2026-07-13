"""Trusted, versioned gate profiles for exact-patch Room execution.

Profiles select only stable gate identifiers.  They never carry argv, shell text,
or repository-provided commands.  A privileged caller resolves one immutable
plan from trusted repository and toolchain evidence before authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from xmuse_core.chat.room_execution_contracts import canonical_execution_path

EXECUTION_GATE_PROFILE_SCHEMA: Literal["room_execution_gate_profile/v1"] = (
    "room_execution_gate_profile/v1"
)

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".txt"})
_ROOT_DOC_PREFIXES = (
    "README",
    "CHANGELOG",
    "CONTRIBUTING",
    "LICENSE",
    "SECURITY",
    "CODE_OF_CONDUCT",
)
_PYTHON_PREFIXES = ("src/", "tests/", "scripts/")
_PYTHON_ROOT_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "mypy.ini",
        "pytest.ini",
        "ruff.toml",
        ".ruff.toml",
    }
)
_XMUSE_BACKEND_PREFIXES = ("xmuse/", *_PYTHON_PREFIXES)
_XMUSE_BACKEND_FILES = frozenset({*_PYTHON_ROOT_FILES, "AGENTS.md"})


class RoomExecutionProfileError(ValueError):
    """Stable rejection for an unknown or untrusted gate-profile plan."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionGateProfile:
    """Server-owned profile definition; it contains no executable command text."""

    schema_version: Literal["room_execution_gate_profile/v1"]
    profile_id: str
    revision: int
    profile_digest: str
    gate_ids: tuple[str, ...]
    path_policy_revision: str
    marker_policy_revision: str

    def safe_reference(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "revision": self.revision,
            "gate_ids": list(self.gate_ids),
        }


@dataclass(frozen=True)
class ExecutionGatePlan:
    """Exact trusted profile facts frozen into one authorization and run."""

    schema_version: Literal["room_execution_gate_profile/v1"]
    profile_id: str
    revision: int
    profile_digest: str
    gate_ids: tuple[str, ...]
    repository_manifest_digest: str
    toolchain_capability_digest: str
    gate_plan_digest: str

    def internal_mapping(self) -> dict[str, Any]:
        """Serialize complete trusted facts for the private controller boundary."""

        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "revision": self.revision,
            "profile_digest": self.profile_digest,
            "gate_ids": list(self.gate_ids),
            "repository_manifest_digest": self.repository_manifest_digest,
            "toolchain_capability_digest": self.toolchain_capability_digest,
            "gate_plan_digest": self.gate_plan_digest,
        }

    def safe_reference(self) -> dict[str, Any]:
        """Return the only profile fields suitable for browser projections."""

        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "revision": self.revision,
            "gate_ids": list(self.gate_ids),
        }


@dataclass(frozen=True)
class _ProfileSpec:
    profile_id: str
    revision: int
    gate_ids: tuple[str, ...]
    path_policy_revision: str
    marker_policy_revision: str


_PROFILE_SPECS = (
    _ProfileSpec(
        "docs/v1",
        1,
        ("patch_diff_check",),
        "docs_paths/v2",
        "no_repository_markers/v1",
    ),
    _ProfileSpec(
        "python-uv/v1",
        1,
        ("patch_diff_check", "python_uv_ruff", "python_uv_mypy", "python_uv_pytest"),
        "python_uv_paths/v2",
        "python_uv_markers/v1",
    ),
    _ProfileSpec(
        "xmuse-monorepo/v2",
        2,
        (
            "patch_diff_check",
            "backend_ruff",
            "backend_mypy",
            "backend_pytest",
            "frontend_typecheck",
            "frontend_lint",
            "frontend_vitest",
            "frontend_build",
        ),
        "xmuse_monorepo_paths/v3",
        "xmuse_monorepo_markers/v1",
    ),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _profile_from_spec(spec: _ProfileSpec) -> ExecutionGateProfile:
    facts = {
        "schema_version": EXECUTION_GATE_PROFILE_SCHEMA,
        "profile_id": spec.profile_id,
        "revision": spec.revision,
        "gate_ids": list(spec.gate_ids),
        "path_policy_revision": spec.path_policy_revision,
        "marker_policy_revision": spec.marker_policy_revision,
    }
    return ExecutionGateProfile(
        schema_version=EXECUTION_GATE_PROFILE_SCHEMA,
        profile_id=spec.profile_id,
        revision=spec.revision,
        profile_digest=_digest(facts),
        gate_ids=spec.gate_ids,
        path_policy_revision=spec.path_policy_revision,
        marker_policy_revision=spec.marker_policy_revision,
    )


EXECUTION_GATE_PROFILES = {
    profile.profile_id: profile for profile in map(_profile_from_spec, _PROFILE_SPECS)
}


def get_execution_gate_profile(profile_id: str) -> ExecutionGateProfile:
    """Resolve one fixed profile; repository content cannot define a profile."""

    try:
        return EXECUTION_GATE_PROFILES[profile_id]
    except (KeyError, TypeError) as exc:
        raise RoomExecutionProfileError("room_execution_gate_profile_unknown") from exc


def _is_documentation_path(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.casefold() not in _DOC_SUFFIXES:
        return False
    if path.startswith("docs/"):
        return True
    if len(pure.parts) != 1:
        return False
    stem = pure.name[: -len(pure.suffix)].upper()
    return any(
        stem == prefix
        or any(stem.startswith(f"{prefix}{separator}") for separator in (".", "-", "_"))
        for prefix in _ROOT_DOC_PREFIXES
    )


def _classify_paths(profile_id: str, paths: tuple[str, ...]) -> str:
    if not paths:
        raise RoomExecutionProfileError("room_execution_gate_paths_empty")
    docs: list[str] = []
    backend: list[str] = []
    frontend: list[str] = []
    unknown: list[str] = []
    for raw in paths:
        try:
            path = canonical_execution_path(raw)
        except ValueError as exc:
            raise RoomExecutionProfileError("room_execution_gate_path_invalid") from exc
        if profile_id == "python-uv/v1" and (
            path in _PYTHON_ROOT_FILES or path.startswith(_PYTHON_PREFIXES)
        ):
            backend.append(path)
        elif profile_id == "xmuse-monorepo/v2" and (
            path in _XMUSE_BACKEND_FILES or path.startswith(_XMUSE_BACKEND_PREFIXES)
        ):
            backend.append(path)
        elif profile_id == "xmuse-monorepo/v2" and path.startswith("frontend/"):
            frontend.append(path)
        elif _is_documentation_path(path):
            docs.append(path)
        else:
            unknown.append(path)
    if unknown:
        raise RoomExecutionProfileError("room_execution_gate_path_uncovered")
    if profile_id == "docs/v1" and (backend or frontend):
        raise RoomExecutionProfileError("room_execution_gate_path_uncovered")
    if backend and frontend:
        return "mixed"
    if backend:
        return "backend"
    if frontend:
        return "frontend"
    if docs:
        return "docs"
    raise RoomExecutionProfileError("room_execution_gate_path_uncovered")


def gate_ids_for_profile_paths(profile_id: str, paths: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve fixed gates for exact changed paths, rejecting every unknown path."""

    profile = get_execution_gate_profile(profile_id)
    kind = _classify_paths(profile_id, paths)
    if kind == "docs":
        return ("patch_diff_check",) if profile_id == "docs/v1" else profile.gate_ids
    if profile_id == "python-uv/v1":
        return profile.gate_ids
    backend = ("backend_ruff", "backend_mypy", "backend_pytest")
    frontend = (
        "frontend_typecheck",
        "frontend_lint",
        "frontend_vitest",
        "frontend_build",
    )
    if kind == "backend":
        return ("patch_diff_check", *backend)
    if kind == "frontend":
        return ("patch_diff_check", *frontend)
    if kind == "mixed":
        return ("patch_diff_check", *backend, *frontend)
    raise RoomExecutionProfileError("room_execution_gate_path_uncovered")


def build_execution_gate_plan(
    *,
    profile_id: str,
    changed_paths: tuple[str, ...],
    repository_manifest_digest: str,
    toolchain_capability_digest: str,
) -> ExecutionGatePlan:
    """Build a canonical immutable plan from privileged repository evidence."""

    profile = get_execution_gate_profile(profile_id)
    gate_ids = gate_ids_for_profile_paths(profile_id, changed_paths)
    for value in (repository_manifest_digest, toolchain_capability_digest):
        if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
            raise RoomExecutionProfileError("room_execution_gate_plan_digest_invalid")
    facts = {
        "schema_version": EXECUTION_GATE_PROFILE_SCHEMA,
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "profile_digest": profile.profile_digest,
        "gate_ids": list(gate_ids),
        "repository_manifest_digest": repository_manifest_digest,
        "toolchain_capability_digest": toolchain_capability_digest,
    }
    return ExecutionGatePlan(
        schema_version=EXECUTION_GATE_PROFILE_SCHEMA,
        profile_id=profile.profile_id,
        revision=profile.revision,
        profile_digest=profile.profile_digest,
        gate_ids=gate_ids,
        repository_manifest_digest=repository_manifest_digest,
        toolchain_capability_digest=toolchain_capability_digest,
        gate_plan_digest=_digest(facts),
    )


def validate_execution_gate_plan(
    plan: ExecutionGatePlan, *, changed_paths: tuple[str, ...]
) -> ExecutionGatePlan:
    """Reject forged, stale, reordered, or path-incomplete trusted-plan objects."""

    if not isinstance(plan, ExecutionGatePlan):
        raise RoomExecutionProfileError("room_execution_gate_plan_required")
    expected = build_execution_gate_plan(
        profile_id=plan.profile_id,
        changed_paths=changed_paths,
        repository_manifest_digest=plan.repository_manifest_digest,
        toolchain_capability_digest=plan.toolchain_capability_digest,
    )
    if plan != expected:
        raise RoomExecutionProfileError("room_execution_gate_plan_invalid")
    return plan


def execution_gate_plan_from_mapping(
    value: object, *, changed_paths: tuple[str, ...]
) -> ExecutionGatePlan:
    """Strictly hydrate and verify a complete private durable-plan mapping."""

    expected_keys = {
        "schema_version",
        "profile_id",
        "revision",
        "profile_digest",
        "gate_ids",
        "repository_manifest_digest",
        "toolchain_capability_digest",
        "gate_plan_digest",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise RoomExecutionProfileError("room_execution_gate_plan_invalid")
    gate_ids = value["gate_ids"]
    revision = value["revision"]
    if (
        value["schema_version"] != EXECUTION_GATE_PROFILE_SCHEMA
        or not isinstance(value["profile_id"], str)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or not isinstance(value["profile_digest"], str)
        or not isinstance(gate_ids, list)
        or not gate_ids
        or any(not isinstance(item, str) for item in gate_ids)
        or not isinstance(value["repository_manifest_digest"], str)
        or not isinstance(value["toolchain_capability_digest"], str)
        or not isinstance(value["gate_plan_digest"], str)
    ):
        raise RoomExecutionProfileError("room_execution_gate_plan_invalid")
    plan = ExecutionGatePlan(
        schema_version=EXECUTION_GATE_PROFILE_SCHEMA,
        profile_id=value["profile_id"],
        revision=revision,
        profile_digest=value["profile_digest"],
        gate_ids=tuple(gate_ids),
        repository_manifest_digest=value["repository_manifest_digest"],
        toolchain_capability_digest=value["toolchain_capability_digest"],
        gate_plan_digest=value["gate_plan_digest"],
    )
    return validate_execution_gate_plan(plan, changed_paths=changed_paths)
