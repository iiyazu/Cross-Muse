from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.execution.github_ops import CheckStatus, evaluate_merge_readiness

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
SERVER_GATE_DOC = PROJECT_ROOT / "docs" / "xmuse" / "github-server-side-gate.md"
MERGE_CONTRACT_DOC = PROJECT_ROOT / "docs" / "xmuse" / "github-review-merge-contract.md"
CODEOWNERS = PROJECT_ROOT / "CODEOWNERS"

REQUIRED_SERVER_CHECKS = {
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_branch_protection_doc_matches_workflow_job_names_and_ownership() -> None:
    workflow = _read(CI_WORKFLOW)
    server_doc = _read(SERVER_GATE_DOC)
    merge_doc = _read(MERGE_CONTRACT_DOC)
    codeowners = _read(CODEOWNERS)

    for check_name in REQUIRED_SERVER_CHECKS:
        assert f"{check_name}:" in workflow
        assert check_name in server_doc

    for fragment in (
        "Require status checks to pass before merging",
        "Require branches to be up to date before merging",
        "Require review from Code Owners",
        "Require conversation resolution before merging",
        "Do not allow bypassing the above settings",
        "review_evidence_bundle",
        ".github/pull_request_template.md",
        "CODEOWNERS",
    ):
        assert fragment in server_doc

    assert "Branch protection" in merge_doc
    assert ".github/" in codeowners
    assert "src/xmuse_core/integrations/" in codeowners
    assert "docs/xmuse/" in codeowners


def test_merge_readiness_contract_uses_server_side_required_checks() -> None:
    checks = [
        CheckStatus(name="quality-gates", status="success"),
        CheckStatus(name="contract-smoke-gates", status="success"),
        CheckStatus(name="real-runtime-integration-gate", status="success"),
    ]

    ready = evaluate_merge_readiness(
        checks,
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=["review:evidence:1"],
    )
    missing = evaluate_merge_readiness(
        checks[:2],
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=["review:evidence:1"],
    )
    no_evidence = evaluate_merge_readiness(
        checks,
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=[],
    )

    assert ready.merge_ready is True
    assert missing.merge_ready is False
    assert missing.failing_checks == ["real-runtime-integration-gate"]
    assert no_evidence.merge_ready is False
    assert no_evidence.missing_evidence == ["review_evidence_bundle"]
