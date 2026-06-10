# GitHub Server-Side Gate

Updated: 2026-06-10

This document is the repository-side contract for GitHub settings that must be
configured on the server. Repository files can prove the desired configuration,
but only GitHub branch protection can enforce it at merge time.

## Required Status Checks

Configure branch protection for `main` with these required status checks:

```text
quality-gates
contract-smoke-gates
real-runtime-integration-gate
```

Settings:

- Require status checks to pass before merging.
- Require branches to be up to date before merging.
- Require conversation resolution before merging.
- Do not allow bypassing the above settings.

The named checks correspond to jobs in `.github/workflows/xmuse-ci.yml`.

## Required Review Policy

Settings:

- Require a pull request before merging.
- Require at least one approving review.
- Require review from Code Owners.
- Dismiss stale approvals when new commits are pushed.

`CODEOWNERS` covers `.github/`, `docs/xmuse/`, `src/xmuse_core/chat/`,
`src/xmuse_core/structuring/`, `src/xmuse_core/platform/`,
`src/xmuse_core/integrations/`, and `src/xmuse_core/providers/`.

## Required PR Evidence

`.github/pull_request_template.md` must keep the mainline evidence fields,
including:

- `blueprint_id`
- `feature_ids`
- `lane_ids`
- `depends_on_lanes`
- `review_evidence_bundle`
- `memory_impact`
- `provider_changes`
- `gate_profile`
- `rollback_plan`
- `privacy_impact`

`review_evidence_bundle` is a hard merge-readiness input. Local fake GitHub ops
must block merge-ready when this field is empty even if all checks pass.

## Proof Boundary

Contract proof:

- workflow job names exist in repository files;
- `CODEOWNERS` maps mainline areas;
- merge-readiness code requires checks and review evidence;
- tests bind the documented required checks to workflow job names.

Runtime proof:

- branch protection on GitHub `main` requires the checks above;
- a real PR cannot merge without CODEOWNER review and passing checks;
- a real PR with missing `review_evidence_bundle` is rejected by the merge
  process.
