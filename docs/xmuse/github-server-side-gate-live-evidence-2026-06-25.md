# GitHub Server-Side Gate Live Evidence - 2026-06-25

This artifact records authenticated GitHub evidence for the CI/CD gate update
that promoted `peer-chat-runtime-gate` to a required `main` branch check.

## Capture Context

- Repository: `iiyazu/Cross-Muse`
- Branch: `main`
- Merged PR: <https://github.com/iiyazu/Cross-Muse/pull/170>
- Merge commit: `cf8c243c9c1b3843d9838748a9ebbb5e2c98c740`
- Main workflow run: `28175465079`
- Capture mode: authenticated `gh` CLI read plus server-side branch protection
  update through GitHub API.

## Main CI Run

`gh run view 28175465079` reported `status=completed` and
`conclusion=success` for commit
`cf8c243c9c1b3843d9838748a9ebbb5e2c98c740`.

| Check | Status | Conclusion | Job id |
|---|---|---|---|
| `quality-gates` | `completed` | `success` | `83450511170` |
| `contract-smoke-gates` | `completed` | `success` | `83450510965` |
| `real-runtime-integration-gate` | `completed` | `success` | `83450510951` |
| `peer-chat-runtime-gate` | `completed` | `success` | `83450510977` |

## Branch Protection Update

After the main CI run succeeded, branch protection for `main` was updated with:

```json
{
  "strict": true,
  "checks": [
    {"context": "quality-gates", "app_id": 15368},
    {"context": "contract-smoke-gates", "app_id": 15368},
    {"context": "real-runtime-integration-gate", "app_id": 15368},
    {"context": "peer-chat-runtime-gate", "app_id": 15368}
  ]
}
```

The follow-up read of
`repos/iiyazu/Cross-Muse/branches/main/protection` reported:

- `required_status_checks.strict = true`
- Required check contexts:
  - `quality-gates`
  - `contract-smoke-gates`
  - `real-runtime-integration-gate`
  - `peer-chat-runtime-gate`
- Required checks are tied to GitHub Actions app id `15368`.

## Review Policy

This update did not change pull request review enforcement. The current
server-side review policy remains governed by the branch protection snapshot and
must not be inferred from local docs or xmuse internal review artifacts.

## Proof Boundary

This evidence proves:

- `peer-chat-runtime-gate` exists in the workflow merged to `main`;
- the exact `main` merge commit ran all four GitHub Actions jobs successfully;
- branch protection for `main` now requires all four checks.

This evidence does not prove:

- GitHub review truth for any specific PR;
- merge truth for future PRs;
- production-ready groupchat;
- natural peer GOD groupchat;
- live MemoryOS;
- live provider stability;
- full L8-L10 closure;
- full L1-L11 closure.
