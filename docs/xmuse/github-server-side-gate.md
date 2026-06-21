# GitHub Server-Side Gate

Updated: 2026-06-21

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

## Review Evidence Policy

The xmuse mainline follows a Clowder-style review split:

- GitHub branch protection enforces server-side status checks and merge facts.
- xmuse records independent internal review evidence in `review_evidence_bundle`.
- If GitHub branch protection or an applicable ruleset also requires PR review,
  GitHub review truth is mandatory and internal evidence cannot replace it.
- If GitHub does not require PR review, a verified xmuse internal review artifact
  can satisfy `review_truth`.

`CODEOWNERS` covers `.github/`, `docs/xmuse/`, `src/xmuse_core/chat/`,
`src/xmuse_core/structuring/`, `src/xmuse_core/platform/`,
`src/xmuse_core/integrations/`, and `src/xmuse_core/providers/`. It documents
ownership but is not required to be the active review gate in single-maintainer
mode.

As of the 2026-06-21 live evidence capture, GitHub branch protection for `main`
does not require pull request reviews (`required_pull_request_reviews = null`).
That is an explicit policy state, not CodeOwner review enforcement. Production
closure therefore uses verified xmuse internal review truth when GitHub does not
require PR review, and must not claim GitHub CodeOwner/PR review enforcement
unless branch protection or an applicable ruleset later proves it.

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
- `GitHubServerSideTruthEvidence` can represent missing server-side evidence as
  `manual_gap` without allowing `pr_merged`.

Runtime proof:

- branch protection on GitHub `main` requires the checks above;
- a real PR cannot merge without passing checks;
- `review_truth` is either GitHub review truth when GitHub requires it, or
  verified xmuse internal review truth when GitHub does not require it;
- a real PR with missing `review_evidence_bundle` is rejected by the merge
  process.

Current live evidence is recorded in
`docs/xmuse/github-server-side-gate-live-evidence-2026-06-21.md`.

## Server-Side Truth Evidence Model

`src/xmuse_core/platform/execution/github_ops.py` defines
`GitHubServerSideTruthEvidence` for collecting server-side facts. This model is
only evidence structure; it does not query or mutate GitHub settings.

`server_side_merge_proof` requires all of:

- workflow run identity plus check suite or check run identity;
- successful check run identities covering every documented required check;
- expected source GitHub App for checks;
- branch protection or ruleset snapshot;
- review truth:
  - GitHub review event identity, reviewer identity, and Code Owner review
    verification when server-side GitHub review is required; or
  - verified xmuse internal review artifact, reviewer identity, and reviewed head
    SHA when GitHub review is not required;
- merge commit SHA, `merged_at`, and merge event identity.

`build_github_server_side_truth_gap(...)` records the current unauthenticated or
missing-evidence state as `manual_gap`. `can_emit_pr_merged(...)` returns true
only for `server_side_merge_proof` that has status-check identity, server
enforcement truth, review truth, and real merge truth fields.

`FakeGitHubServerSideTruthCollector` is a contract-only scaffold for tests and
local development. It may mirror workflow, check, ruleset, and review field
shapes, but it always returns `contract_proof`, strips merge commit/merged event
fields, and therefore cannot make `can_emit_pr_merged(...)` true.

`GitHubServerSideTruthSnapshot` and
`build_github_server_side_truth_from_snapshot(...)` normalize read-only
server-derived evidence that an operator or future live collector has already
captured. A complete snapshot can become `server_side_merge_proof`; an incomplete
snapshot remains `manual_gap` even when some merge fields are present. This
normalizer does not call GitHub APIs and does not mutate repository settings.

`ReadOnlyGitHubServerSideTruthCollector` is an opt-in wrapper around an injected
client that fetches a `GitHubServerSideTruthSnapshot`. It has no default GitHub
network client, reads no credentials by itself, and falls back to `manual_gap`
when the client cannot provide a snapshot.

`GitHubCliServerSideTruthClient` is an opt-in `gh api` implementation of that
client protocol. It uses read-only `gh api` calls for PR state, reviews, branch
protection, repository rulesets, and check runs, then returns a snapshot for the
collector to normalize. Rulesets only contribute enforcement and review truth
when an active branch ruleset explicitly applies to the target base branch
through `conditions.ref_name.include` / `exclude`. Tests inject a fake runner;
default CI does not call GitHub.

Manual operator capture can use:

```bash
uv run python scripts/github_server_truth_capture.py \
  --repo iiyazu/Cross-Muse \
  --pull-request <number> \
  --internal-review-artifact <path> \
  --internal-reviewer <xmuse-reviewer-id> \
  --internal-reviewed-head-sha <sha> \
  --output /tmp/xmuse-github-server-truth.json
```

The script writes evidence JSON with `capture_mode:
opt_in_read_only_gh_api`. It returns exit `0` only when the captured server
snapshot can emit `pr_merged`; otherwise it writes `manual_gap` evidence and
returns exit `2`.

Local workflow files, PR template fields, and CODEOWNERS coverage remain contract
proof. They do not by themselves prove server-side enforcement.
