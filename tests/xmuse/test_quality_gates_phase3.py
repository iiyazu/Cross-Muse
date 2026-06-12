from __future__ import annotations

import re
import tomllib
from pathlib import Path

from xmuse_core.providers.models import (
    AdapterKind,
    ProviderId,
    SupportLevel,
    TaskCapability,
)
from xmuse_core.providers.registry import build_default_provider_registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
QUALITY_DOC = PROJECT_ROOT / "docs" / "xmuse" / "quality-gates-and-provider-matrix.md"
PROVIDER_MATRIX = PROJECT_ROOT / "docs" / "xmuse" / "provider-matrix.md"
CONFIG_MATRIX = PROJECT_ROOT / "docs" / "xmuse" / "config-matrix.md"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

PRODUCTION_GROUPCHAT_ENV_BUNDLE = {
    "XMUSE_PEER_GOD_BACKEND",
    "XMUSE_EXECUTE_GOD_BACKEND",
    "XMUSE_REVIEW_GOD_BACKEND",
    "XMUSE_RAY_GOD_TRANSPORT",
    "XMUSE_RAY_GOD_EFFORT",
    "XMUSE_RAY_GOD_MCP",
    "XMUSE_DEPLOYMENT_PROFILE",
    "XMUSE_CHAT_API_URL",
    "XMUSE_CHAT_API_AUTH_TOKEN",
    "XMUSE_CHAT_API_KEY",
    "XMUSE_MCP_AUTH_TOKEN",
}

DEFAULT_CI_TEST_TARGETS = {
    "tests/xmuse/test_package_boundaries.py",
    "tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency",
    "tests/xmuse/test_provider_models.py",
    "tests/xmuse/test_provider_policy.py",
    "tests/xmuse/test_provider_support_level.py",
    "tests/xmuse/test_provider_read_contracts_module.py",
    "tests/xmuse/test_quality_gates_phase3.py",
    "tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection",
    "tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_names_from_env_example() -> set[str]:
    names: set[str] = set()
    for line in _read(ENV_EXAMPLE).splitlines():
        match = re.match(r"#\s*([A-Z][A-Z0-9_]+)(?:\s|=)", line)
        if match:
            names.add(match.group(1))
    return names


def test_ci_workflow_runs_ordered_minimal_phase3_gates_without_external_state() -> None:
    workflow = _read(CI_WORKFLOW)

    assert "uv sync" in workflow
    assert "uv run ruff check" in workflow
    assert "uv run pytest -q" in workflow
    assert "uv run mypy" in workflow

    assert workflow.index("uv run ruff check") < workflow.index("uv run pytest -q")
    assert workflow.index("uv run pytest -q") < workflow.index("uv run mypy")

    for target in DEFAULT_CI_TEST_TARGETS:
        assert target in workflow

    forbidden = (
        "../memoryOS",
        "/home/iiyatu/projects/python/memoryOS",
        "memoryos-lite",
        "DEEPSEEK_API_KEY",
        "test_real_ray_codex_app_server_mcp_writeback",
        "test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume",
    )
    for token in forbidden:
        assert token not in workflow


def test_type_check_gate_is_installed_scoped_and_documented() -> None:
    pyproject = tomllib.loads(_read(PYPROJECT))
    dev_deps = pyproject["dependency-groups"]["dev"]

    assert any(dep.startswith("mypy") for dep in dev_deps)
    assert "tool" in pyproject and "mypy" in pyproject["tool"]

    quality_doc = _read(QUALITY_DOC)
    assert "uv run mypy" in quality_doc
    assert "scoped type check" in quality_doc.lower()
    assert "documented exclusions" in quality_doc.lower()


def test_provider_matrix_docs_match_default_registry_support_levels() -> None:
    matrix = _read(PROVIDER_MATRIX)
    quality_doc = _read(QUALITY_DOC)
    registry = build_default_provider_registry()
    profiles = registry.list_profiles()

    codex_profiles = [profile for profile in profiles if profile.provider_id is ProviderId.CODEX]
    assert codex_profiles
    assert all(profile.support_level is SupportLevel.PRIMARY for profile in codex_profiles)
    assert all(profile.supports_mcp for profile in codex_profiles)
    assert "Codex = PRIMARY for real groupchat" in quality_doc

    opencode = registry.get("opencode.deepseek_flash_worker")
    assert opencode.support_level is SupportLevel.SECONDARY
    assert opencode.adapter_kind is AdapterKind.OPENCODE_CLI
    assert opencode.task_capabilities == (
        TaskCapability.BOUNDED_CODE_WRITING,
        TaskCapability.BOUNDED_DELIBERATION,
    )
    assert TaskCapability.REVIEW not in opencode.task_capabilities
    assert TaskCapability.TAKEOVER not in opencode.task_capabilities
    assert opencode.env_requirement_names == ("DEEPSEEK_API_KEY",)
    assert "OpenCode = SECONDARY bounded worker / bounded deliberation only" in quality_doc

    assert "Claude Code" in matrix
    assert "Launcher only" in matrix
    assert "claude" not in {profile.provider_id.value for profile in profiles}
    assert "Claude Code = launcher only / not provider adapter" in quality_doc

    assert "Fake (test)" in matrix
    assert "TEST ONLY" in matrix
    assert all(profile.support_level is not SupportLevel.TEST_ONLY for profile in profiles)
    assert "Fake = TEST ONLY and excluded from default registry" in quality_doc


def test_env_example_matches_config_matrix_and_has_no_default_ci_secret() -> None:
    config_matrix = _read(CONFIG_MATRIX)
    env_example = _read(ENV_EXAMPLE)
    quality_doc = _read(QUALITY_DOC)
    env_names = _env_names_from_env_example()

    for name in PRODUCTION_GROUPCHAT_ENV_BUNDLE:
        assert name in env_names
        assert name in config_matrix
        assert name in quality_doc

    assert "DEEPSEEK_API_KEY only required for OpenCode smoke" in quality_doc
    assert "DEEPSEEK_API_KEY" in env_names
    assert "must set for any runtime use" not in env_example
    assert "Default CI requires no provider secrets" in quality_doc

    for name in ("XMUSE_RUNTIME_BACKEND", "XMUSE_DEGRADED_LOCAL_GOD_MODE"):
        assert name in env_names
        assert name in config_matrix


def test_quality_doc_defines_focused_groups_and_excludes_real_soak_from_default_ci() -> None:
    quality_doc = _read(QUALITY_DOC)

    required_groups = (
        "installability/package boundary",
        "provider matrix/support level",
        "config/env docs consistency",
        "runtime health command smoke",
        "fake-provider groupchat smoke",
    )
    for group in required_groups:
        assert group in quality_doc

    for target in DEFAULT_CI_TEST_TARGETS:
        assert target in quality_doc

    assert "not default CI" in quality_doc
    assert "real Ray/Codex" in quality_doc
    assert "../memoryOS" in quality_doc
