from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class WriteScopeViolation(ValueError):
    def __init__(self, path: str, allowed_scope: list[str]) -> None:
        self.path = path
        self.allowed_scope = allowed_scope
        super().__init__(f"path outside write_scope: {path}")


class SubagentRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "subagent_runtime_contract.v1"
    blueprint_id: str | None = None
    lane_id: str
    feature_id: str
    depends_on: list[str] = Field(default_factory=list)
    worktree_path: Path
    allowed_files: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(min_length=1)
    write_scope: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    required_checks: list[str] = Field(default_factory=list)
    gate_profiles: list[str] = Field(default_factory=list)
    base_branch: str
    parent_pr: int | str | None = None
    source_context_refs: list[str] = Field(default_factory=list)
    memory_context_ref: str | None = None
    memory_context: dict[str, Any] = Field(default_factory=dict)
    rollback_plan: str = "Revert the feature branch or patch-forward from review evidence."
    review_profile: str = "default"

    @field_validator("lane_id", "feature_id", "base_branch", "rollback_plan", "review_profile")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("blueprint_id", "memory_context_ref")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator(
        "depends_on",
        "allowed_files",
        "allowed_tools",
        "write_scope",
        "acceptance_criteria",
        "required_checks",
        "gate_profiles",
        "source_context_refs",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]

    @field_validator("write_scope")
    @classmethod
    def _normalize_write_scope(cls, values: list[str]) -> list[str]:
        normalized = [_normalize_scope(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("write_scope must not contain duplicates")
        return normalized

    @field_serializer("worktree_path")
    def _serialize_worktree_path(self, value: Path) -> str:
        return str(value)

    def validate_write_paths(self, paths: list[str | Path]) -> list[str]:
        normalized: list[str] = []
        for path in paths:
            relative_path = self._relative_changed_path(path)
            if not _is_in_write_scope(relative_path, self.write_scope):
                raise WriteScopeViolation(relative_path, list(self.write_scope))
            normalized.append(relative_path)
        return normalized

    def prompt_envelope(self) -> dict[str, Any]:
        return {
            **self.model_dump(mode="json"),
            "output_contract": {
                "schema_version": "subagent_worker_result.v1",
                "status_values": ["completed", "blocked", "failed"],
                "required_fields": [
                    "lane_id",
                    "status",
                    "changed_files",
                    "tests_run",
                    "evidence_refs",
                    "summary",
                ],
            },
            "forbidden_actions": [
                "Do not write outside write_scope.",
                "Do not write durable xmuse state directly.",
                "Do not mutate feature_lanes.json or lane status.",
                "Do not create autonomous GOD chains.",
            ],
        }

    def stable_json(self) -> str:
        return json.dumps(
            self.prompt_envelope(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def render_worker_prompt(self) -> str:
        return "\n".join(
            [
                "# Subagent Runtime Contract",
                "",
                "Use this JSON contract as the only authority for the worker task.",
                "",
                "```json",
                self.stable_json(),
                "```",
                "",
                "Return only a result matching `subagent_worker_result.v1`.",
            ]
        )

    def _relative_changed_path(self, path: str | Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve().relative_to(self.worktree_path.resolve())
            except ValueError as exc:
                raise WriteScopeViolation(str(path), list(self.write_scope)) from exc
        relative = candidate.as_posix()
        if relative.startswith("../") or relative == ".." or "/../" in relative:
            raise WriteScopeViolation(relative, list(self.write_scope))
        return relative.removeprefix("./")


def _normalize_scope(value: str) -> str:
    scope = _require_non_empty(value).replace("\\", "/").removeprefix("./")
    if scope.startswith("../") or scope == ".." or "/../" in scope:
        raise ValueError("write_scope must not escape the worktree")
    return scope


def _is_in_write_scope(path: str, scopes: list[str]) -> bool:
    return any(
        path == scope.rstrip("/") or path.startswith(scope.rstrip("/") + "/")
        for scope in scopes
    )


def _require_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must be non-empty")
    return value
