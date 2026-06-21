# GitHub Server-Side Gate Live Evidence - 2026-06-21

This artifact records authenticated read-only GitHub evidence for production
closure P0. It updates issue #37 and replaces the older blocker that local
`gh api` was not authenticated.

## Capture Context

- Repository: `iiyazu/Cross-Muse`
- Branch: `main`
- Checked commit: `07ca068018d3ddfd89393548d349ac2a2698df8a`
- Workflow run: `27901191467`
- Capture mode: authenticated read-only `gh api`
- Issue update: <https://github.com/iiyazu/Cross-Muse/issues/37#issuecomment-4761653435>

## Branch Protection

`repos/iiyazu/Cross-Muse/branches/main/protection` was readable.

Observed branch protection facts:

- `required_status_checks.strict = true`
- Required check contexts:
  - `quality-gates`
  - `contract-smoke-gates`
  - `real-runtime-integration-gate`
- Required checks are tied to GitHub Actions app id `15368`.
- `enforce_admins.enabled = true`
- `allow_force_pushes.enabled = false`
- `allow_deletions.enabled = false`
- `required_pull_request_reviews = null`

Implication: GitHub server-side required-check enforcement is proven for the
documented checks. GitHub PR review / CodeOwner enforcement is not enabled and
must not be claimed.

## Rulesets

`repos/iiyazu/Cross-Muse/rulesets` was readable and returned `0` rulesets.

Implication: no ruleset currently adds or overrides branch protection review or
status-check policy for `main`.

## Workflow And Check Runs

`repos/iiyazu/Cross-Muse/actions/workflows` was readable.

Observed workflow:

- id: `292595023`
- name: `xmuse CI`
- path: `.github/workflows/xmuse-ci.yml`
- state: `active`

Check runs for commit `07ca068018d3ddfd89393548d349ac2a2698df8a`:

| Check | Status | Conclusion | App | Job id |
|---|---|---|---|---|
| `quality-gates` | `completed` | `success` | `github-actions` | `82561681297` |
| `contract-smoke-gates` | `completed` | `success` | `github-actions` | `82561681313` |
| `real-runtime-integration-gate` | `completed` | `success` | `github-actions` | `82561681328` |

Combined commit statuses for this commit are empty (`total_count = 0`). The
repository relies on GitHub check-runs, not legacy statuses, for these required
checks.

## CODEOWNERS And Review Policy

`CODEOWNERS` exists and maps the mainline areas to `@iiyazu`, including
`.github/`, `docs/xmuse/`, `src/xmuse_core/chat/`,
`src/xmuse_core/structuring/`, `src/xmuse_core/platform/`,
`src/xmuse_core/integrations/`, and `src/xmuse_core/providers/`.

Because branch protection reports `required_pull_request_reviews = null`,
CODEOWNERS is ownership documentation in the current server policy, not an
active GitHub CodeOwner review gate. The xmuse production policy therefore
accepts verified internal review truth when GitHub does not require PR review.

## Closure Status

P0 is closed for:

- authenticated GitHub read access;
- branch protection readability;
- server-required status checks;
- workflow/check-run visibility;
- explicit documentation that GitHub PR/CodeOwner review enforcement is absent.

P0 does not claim:

- GitHub CodeOwner/PR review enforcement;
- production readiness;
- accepted terminal closure for a demand without producer-backed
  `server_side_merge_proof`.
