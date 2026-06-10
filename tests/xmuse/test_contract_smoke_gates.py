from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.production_readiness import PRODUCTION_SLO_TARGETS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
CONTRACT_DOC = PROJECT_ROOT / "docs" / "xmuse" / "contract-smoke-gates.md"
README = PROJECT_ROOT / "docs" / "xmuse" / "README.md"

CONTRACT_SMOKE_TARGETS = {
    "tests/xmuse/test_mainline_contract_docs.py",
    "tests/xmuse/test_deliberation_protocol_v2.py",
    "tests/xmuse/test_god_speech_act_contract.py",
    "tests/xmuse/test_deliberation_engine.py",
    "tests/xmuse/test_deliberation_chat_api.py",
    "tests/xmuse/test_mission_blueprint_v1.py",
    "tests/xmuse/test_lane_planner_v2.py",
    "tests/xmuse/test_blueprint_lane_dag_service.py",
    "tests/xmuse/test_feature_graph_patch_forward.py",
    "tests/xmuse/test_github_ops_contract.py",
    "tests/xmuse/test_memoryos_rest_integration.py",
    "tests/xmuse/test_memoryos_event_writeback.py",
    "tests/xmuse/test_production_hardening.py",
    "tests/xmuse/test_contract_smoke_gates.py",
    "tests/xmuse/test_package_boundaries.py",
}

EXPECTED_SLO_KEYS = {
    "blueprint_freeze_p95_seconds",
    "ready_lane_dispatch_p95_seconds",
    "memory_search_p95_ms_sqlite_poc",
    "feature_pr_cycle_p95_minutes_excluding_human_wait",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_contract_smoke_workflow_has_no_secret_dependent_mainline_gate() -> None:
    workflow = _read(CI_WORKFLOW)
    contract_job = workflow[workflow.index("contract-smoke-gates:") :]

    assert "contract-smoke-gates:" in contract_job
    assert "uv run ruff check ." in contract_job
    assert "uv run ruff format --check" in contract_job
    assert "uv run pytest -q" in contract_job
    assert "uv run mypy" in contract_job

    assert contract_job.index("uv run ruff check .") < contract_job.index("uv run pytest -q")
    assert contract_job.index("uv run pytest -q") < contract_job.index("uv run mypy")

    for target in CONTRACT_SMOKE_TARGETS:
        assert target in contract_job

    forbidden_tokens = (
        "secrets.",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "test_real_ray_codex_app_server_mcp_writeback",
        "../memoryOS",
    )
    for token in forbidden_tokens:
        assert token not in contract_job


def test_contract_smoke_doc_records_gate_layers_and_known_baseline_exclusions() -> None:
    doc = _read(CONTRACT_DOC)
    readme = _read(README)

    for fragment in (
        "lint+format+typecheck",
        "Protocol contracts",
        "Blueprint and laneDAG contracts",
        "GitHub merge gate contracts",
        "REST-first MemoryOS contracts",
        "Integration smoke",
        "Performance smoke",
        "Known broad-suite baseline gaps are not hidden",
        "tests/xmuse/test_chat_api.py",
        "uv run ruff format --check .",
        "no-secrets PR gate",
    ):
        assert fragment in doc

    assert "docs/xmuse/contract-smoke-gates.md" in readme


def test_production_slo_targets_are_explicit_positive_smoke_thresholds() -> None:
    assert set(PRODUCTION_SLO_TARGETS) == EXPECTED_SLO_KEYS
    assert all(isinstance(value, int) for value in PRODUCTION_SLO_TARGETS.values())
    assert all(value > 0 for value in PRODUCTION_SLO_TARGETS.values())
