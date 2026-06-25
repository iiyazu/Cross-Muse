# GitHub Review And Merge Contract

GitHub is a first-class review and merge control plane for the xmuse mainline.
It is not only an archive target for completed work.

## Required PR Fields

Every lane or feature PR must provide:

- `blueprint_id`
- `feature_ids`
- `lane_ids`
- `depends_on_lanes`
- `memory_impact`
- `new_artifacts`
- `provider_changes`
- `gate_profile`
- `review_evidence_bundle`
- `rollback_plan`
- `privacy_impact`

The repository template at `.github/pull_request_template.md` mirrors this list.

## Branch Protection

`docs/xmuse/github-server-side-gate.md` is the server-side configuration
contract for branch protection on `main`. It binds the required GitHub checks to
the workflow job names:

- `quality-gates`
- `contract-smoke-gates`
- `real-runtime-integration-gate`
- `peer-chat-runtime-gate`

Repository tests can prove that this desired configuration is documented and
kept in sync with workflow files. GitHub branch protection must still be enabled
on the server before it becomes runtime enforcement.

Branch protection is the GitHub-side enforcement layer; xmuse internal review
evidence is the platform-side review layer.

## Required Checks

The default local evidence bundle for a contract PR is:

```text
uv run ruff check .
uv run pytest <focused contract tests>
uv run pytest tests/xmuse/test_package_boundaries.py
```

CI or branch protection may enforce these as named status checks. The fake
GitHub contract treats a PR as merge-ready only when all required checks are
successful and review evidence is present.

## Ownership

`CODEOWNERS` maps chat, structuring, platform, integrations, providers,
`.github/`, and `docs/xmuse/` changes to the repository owner. In
single-maintainer mode, `CODEOWNERS` documents ownership while xmuse internal
review evidence provides the independent review record. If GitHub branch
protection is configured to require PR review or Code Owner review, that
server-side requirement must also be satisfied and cannot be replaced by
internal evidence.

## Merge-Ready Contract

Merge-ready is blocked when:

- any required check is missing or not `success`;
- `review_evidence_bundle` is empty;
- GitHub requires PR review and no accepted GitHub review event exists;
- lane metadata omits blueprint, feature, lane, dependency, memory, rollback, or
  privacy context.

Patch-forward remains the expected response to review-required fixes.
