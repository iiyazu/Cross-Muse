from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
README = PROJECT_ROOT / "docs" / "xmuse" / "README.md"
GOAL_DOC = PROJECT_ROOT / "docs" / "xmuse" / "deep-research-03-next-goal.md"
RUNTIME_GATE_DOC = PROJECT_ROOT / "docs" / "xmuse" / "real-runtime-integration-gate.md"
BROAD_SUITE_DEBT_DOC = PROJECT_ROOT / "docs" / "xmuse" / "broad-suite-baseline-debt.md"

REAL_RUNTIME_GATE_TARGETS = {
    "tests/xmuse/test_github_server_gate_contract.py",
    "tests/xmuse/test_memoryos_lite_interop.py",
    "tests/xmuse/test_real_runtime_integration_gate.py",
    "tests/xmuse/test_package_boundaries.py",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_real_runtime_gate_workflow_is_no_secrets_and_focused() -> None:
    workflow = _read(CI_WORKFLOW)
    runtime_job = workflow[workflow.index("real-runtime-integration-gate:") :]

    assert "real-runtime-integration-gate:" in runtime_job
    assert "uv sync --frozen --all-groups" in runtime_job
    assert "uv run ruff check" in runtime_job
    assert "uv run pytest -q" in runtime_job
    assert "uv run mypy" in runtime_job

    for target in REAL_RUNTIME_GATE_TARGETS:
        assert target in runtime_job

    for forbidden in (
        "secrets.",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "../memoryOS",
        "test_real_ray_codex_app_server_mcp_writeback",
    ):
        assert forbidden not in runtime_job


def test_deep_research_03_docs_define_contract_vs_runtime_proof() -> None:
    goal_doc = _read(GOAL_DOC)
    gate_doc = _read(RUNTIME_GATE_DOC)
    readme = _read(README)

    for fragment in (
        "GitHub server-side gate",
        "MemoryOS Lite interop",
        "Provider / CLI / Ray soak layering",
        "Broad-suite baseline debt registry",
        "contract proof",
        "runtime proof",
    ):
        assert fragment in goal_doc

    for fragment in (
        "Contract proof",
        "Runtime proof",
        "XMUSE_LIVE_MEMORYOS_LITE",
        "XMUSE_MEMORYOS_LITE_URL",
        "fake contract",
        "live opt-in",
        "quality-gates",
        "contract-smoke-gates",
        "real-runtime-integration-gate",
    ):
        assert fragment in gate_doc

    assert "docs/xmuse/deep-research-03-next-goal.md" in readme
    assert "docs/xmuse/real-runtime-integration-gate.md" in readme
    assert "docs/xmuse/broad-suite-baseline-debt.md" in readme


def test_broad_suite_debt_registry_names_known_gaps_with_repro_commands() -> None:
    debt_doc = _read(BROAD_SUITE_DEBT_DOC)

    for fragment in (
        "DR03-DEBT-001",
        "DR03-DEBT-002",
        "DR03-DEBT-003",
        "DR03-DEBT-004",
        "uv run ruff format --check .",
        "uv run pytest -q tests/xmuse/test_chat_api.py",
        "XMUSE_LIVE_MEMORYOS_LITE=1",
        "real provider / Ray / Codex",
        "Owner file",
        "Priority",
        "Current failure summary",
        "The contract smoke gate is not a broad-suite green claim",
    ):
        assert fragment in debt_doc
