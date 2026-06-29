from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
LEGACY_PROOF_ARCHIVE = (
    PROJECT_ROOT / "docs" / "xmuse" / "archive" / "2026-06-proof-closure-legacy"
)
PLAN_DOC = LEGACY_PROOF_ARCHIVE / "vision-runtime-evidence-closure-plan.md"
PROMPT_DOC = LEGACY_PROOF_ARCHIVE / "vision-runtime-evidence-closure-goal-prompt.md"
README = PROJECT_ROOT / "docs" / "xmuse" / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_default_ci_includes_self_iteration_runtime_evidence_proof() -> None:
    workflow = _read(CI_WORKFLOW)
    contract_job = workflow[workflow.index("contract-smoke-gates:") :]

    for target in (
        "tests/xmuse/test_self_iteration_runtime_closure.py",
        "tests/xmuse/test_vision_runtime_evidence_closure.py",
        "src/xmuse_core/platform/execution/subagent_runtime.py",
        "src/xmuse_core/self_iteration/runtime_closure.py",
    ):
        assert target in contract_job

    assert "quality-gates:" in workflow
    assert "contract-smoke-gates:" in workflow
    assert "real-runtime-integration-gate:" in workflow
    assert "secrets." not in contract_job


def test_vision_runtime_evidence_docs_define_proof_level_boundaries() -> None:
    plan = _read(PLAN_DOC)
    prompt = _read(PROMPT_DOC)
    readme = _read(README)
    plan_ref = (
        "docs/xmuse/archive/2026-06-proof-closure-legacy/"
        "vision-runtime-evidence-closure-plan.md"
    )
    archive_ref = "docs/xmuse/archive/2026-06-proof-closure-legacy/"

    for fragment in (
        "contract_proof",
        "fake_runtime_proof",
        "live_service_proof",
        "server_side_enforcement_proof",
        "real_provider_proof",
        "manual_gap",
        "Do not write `pr_merged` for fake/local merge readiness.",
        "Keep the deterministic fixture as contract proof.",
        "Live tests skip cleanly unless explicit env vars are set.",
    ):
        assert fragment in plan

    assert plan_ref in prompt
    assert archive_ref in readme
    assert "not current `/goal` entrypoints" in readme
