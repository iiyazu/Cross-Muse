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
`.github/`, and `docs/xmuse/` changes to the repository owner. Branch protection
must be configured in GitHub to require CODEOWNER review before this becomes a
hard server-side merge gate.

## Merge-Ready Contract

Merge-ready is blocked when:

- any required check is missing or not `success`;
- `review_evidence_bundle` is empty;
- lane metadata omits blueprint, feature, lane, dependency, memory, rollback, or
  privacy context.

Patch-forward remains the expected response to review-required fixes.
