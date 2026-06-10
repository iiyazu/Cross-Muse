from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.platform.execution.subagent_runtime import (
    SubagentRuntimeContract,
    WriteScopeViolation,
)


def test_subagent_runtime_contract_serializes_prompt_envelope(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    envelope = contract.prompt_envelope()
    rendered = contract.render_worker_prompt()

    assert envelope["schema_version"] == "subagent_runtime_contract.v1"
    assert envelope["lane_id"] == "lane-1"
    assert envelope["write_scope"] == ["src/xmuse_core/chat/", "tests/xmuse/"]
    assert envelope["output_contract"]["status_values"] == [
        "completed",
        "blocked",
        "failed",
    ]
    assert "Subagent Runtime Contract" in rendered
    assert '"lane_id":"lane-1"' in rendered
    assert "Do not write outside write_scope." in rendered


def test_subagent_runtime_contract_rejects_out_of_scope_write(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    with pytest.raises(WriteScopeViolation) as exc:
        contract.validate_write_paths(["src/xmuse_core/providers/secret.py"])

    assert exc.value.path == "src/xmuse_core/providers/secret.py"
    assert exc.value.allowed_scope == ["src/xmuse_core/chat/", "tests/xmuse/"]


def test_subagent_runtime_contract_rejects_path_traversal(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    with pytest.raises(WriteScopeViolation):
        contract.validate_write_paths(["src/xmuse_core/chat/../../runtime_state.db"])


def test_subagent_runtime_contract_accepts_absolute_paths_inside_scope(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path)
    changed = tmp_path / "lane-wt" / "src" / "xmuse_core" / "chat" / "feature.py"

    assert contract.validate_write_paths([str(changed)]) == [
        "src/xmuse_core/chat/feature.py"
    ]


def test_subagent_runtime_contract_requires_acceptance_criteria(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="acceptance_criteria"):
        _contract(tmp_path, acceptance_criteria=[])


def _contract(
    tmp_path: Path,
    *,
    acceptance_criteria: list[str] | None = None,
) -> SubagentRuntimeContract:
    return SubagentRuntimeContract(
        lane_id="lane-1",
        feature_id="feature-1",
        worktree_path=tmp_path / "lane-wt",
        allowed_tools=["read", "edit", "uv_run"],
        write_scope=["src/xmuse_core/chat/", "tests/xmuse/"],
        acceptance_criteria=acceptance_criteria
        if acceptance_criteria is not None
        else ["Focused tests pass."],
        gate_profiles=["ruff", "pytest"],
        base_branch="main",
        parent_pr=42,
        source_context_refs=[
            "blueprint:bp-1",
            "lane:lane-1",
            "memory://conversation/conv-1/context",
        ],
        memory_context={
            "namespace": "memory://conversation/conv-1",
            "refs": ["memory://conversation/conv-1/context"],
        },
    )
