# Current Worktree Handoff Inventory

更新日期: 2026-06-17

本文是当前 `vision-closure-deliberation-tui` worktree 的快速交接入口。它不是
closure proof，不是 PR #43 readiness，也不是 merge truth。细粒度历史仍以
`docs/xmuse/production-closure-gap-ledger.md` 为准；行为规范仍以
`docs/xmuse/goal-behavior-contract.md`、
`docs/xmuse/anti-tdd-abuse-policy.md` 和
`docs/xmuse/github-git-behavior-policy.md` 为准。

## Current Truth

- Branch: `vision-closure-deliberation-tui`
- Latest implementation head before this docs-only sync:
  `b5225b962b363d5cb2b60459735781333ade0bdf`
- Remote tracking head / PR #43 head:
  `2c03b2492e9e0a618f21e19120192b0a46765dbf`
- Local branch state before this docs-only sync: clean, ahead of
  `origin/vision-closure-deliberation-tui` by 5 commits.
- PR #43 last checked from GitHub: draft/open/unmerged, merge state `CLEAN`,
  review decision empty.
- Latest GitHub Actions truth: `xmuse CI` run `27630501256`, success, for
  pushed head `2c03b2492e9e0a618f21e19120192b0a46765dbf` only.
- Local ahead commits after that pushed head have no GitHub Actions truth until
  pushed and rechecked.

If this document is committed, `git rev-parse HEAD` will be one docs-only commit
after the implementation head above. Treat the implementation state as
`b5225b962b363d5cb2b60459735781333ade0bdf` plus the docs sync commit.

## Local-Only Commits Since Remote Head

These commits are local proof/admission hardening work. They are not remote CI
verified and must not be reported as PR #43 server truth until pushed and
checked.

1. `267ac887b899649a8b6ab6152321df879f249425`
   `test(closure): align operator github truth fixture`
   - Aligns operator-action GitHub truth fixture expectations with the current
     server-truth model, including workflow-run identity.
2. `a99d9499984d8544523944f9b0cc623997625db3`
   `refactor(closure): reuse review-chain handoff admission`
   - Routes runtime closure evidence capture through the shared L9/L10
     review-chain handoff evaluator instead of duplicating admission logic.
3. `ebc5cb4e71a04083d99b5961cac9945215592fac`
   `refactor(closure): reuse review-chain handoff for patch lineage`
   - Routes file-backed patch-forward lineage reconciliation through the same
     shared L10 handoff evaluation.
4. `c751db94f190daec1163e15f16b4fd90ca73a751`
   `fix(closure): reject stale observed generation`
   - Tightens `ClosureObject` admission so complete status cannot cite a stale
     `observed_generation`.
5. `b5225b962b363d5cb2b60459735781333ade0bdf`
   `fix(closure): require condition observed generation`
   - Tightens complete condition chains so each observed condition must carry
     current `observed_generation`.

## Latest Local Verification

For the latest local implementation head
`b5225b962b363d5cb2b60459735781333ade0bdf`:

```text
uv run pytest tests/xmuse/test_closure_objects.py \
  tests/xmuse/test_closure_reconciler.py \
  tests/xmuse/test_release_evidence_candidates.py -q
# 78 passed

uv run ruff check .
# passed

git diff --check
# passed

test ! -e xmuse/__init__.py
# passed
```

This is local verification only. It does not establish GitHub review truth,
merge truth, `pr_merged`, live MemoryOS trace, natural peer-GOD deliberation, or
overnight readiness.

## Current Goal Result Boundary

The last long goal did not complete the full
`C:\tmp\deep-research-report_x3.md` vision. It reached a clean stop point after
L9/L10 false-closure and admission hardening:

- shared L9/L10 review-chain handoff evaluation is reused by runtime closure
  evidence capture and patch-forward lineage reconciliation;
- nested server-truth overclaims are blocked at the last pushed head;
- closure status and complete condition chains now require current observed
  generation before they can be admitted as complete;
- local focused gates and lint passed for the latest implementation head.

Remaining forbidden claims:

- PR #43 is not merged.
- Local ahead commits are not GitHub Actions verified.
- CI success is not review truth or merge truth.
- Worker output remains candidate evidence, not independent review truth.
- Release evidence aggregation is not live MemoryOS trace.
- TUI/dashboard/read models remain projection/control surfaces, not durable
  authority.
- OpenCode remains bounded worker/candidate patch/reviewer unless a future
  L2-L5 proof upgrade explicitly promotes it.

## GitHub / Git Handling

Do not use PR #43 as the default sink for new work. It is a heavy historical
umbrella context. Before any push, choose one of these paths explicitly:

1. Push the current branch to PR #43 only if the user asks to update that PR.
   Then update the PR body and inspect the Actions run for the pushed head.
2. Prefer a smaller branch/PR for the next scoped closure slice when feasible.
   Keep the branch focused on one authority/proof path.
3. If work depends on PR #43 context, label it stacked and do not claim
   standalone merge readiness.

Never push runtime/cache state such as `*.db`, `*.sqlite3`, `*.jsonl`,
`feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.

## Next Clean Cursor

Start the next session with truth refresh, then pick a bounded slice. Do not
resume by broad TDD or by expanding projection surfaces.

Recommended first decision:

- If the goal is repository hygiene: decide whether to split the 5 local
  commits plus docs sync away from PR #43, or push to PR #43 with explicit user
  approval.
- If the goal is more x3 implementation: continue with a small L9/L10
  admission/reconciliation slice or a later Wave E slice only after confirming
  upstream proof boundaries in the ledger.

Minimum validation before claiming a new slice:

```text
uv run pytest <focused tests> -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```
