# XMuse Git And GitHub Behavior Policy

更新日期: 2026-06-16

本文固化 xmuse 开发中的 Git/GitHub 行为规范，目标是避免继续把所有生产闭环工作堆进
过重 PR，并保持 proof、review、CI、merge truth 的边界清楚。

## Core Rule

Use small, scoped PRs. Do not use one long-running PR as the default sink for
all future `/goal` work.

PRs are review and integration units, not proof authorities. CI success,
release evidence, local tests, worker output, and PR body text never become
GitHub review or merge truth.

Treat a long `/goal` as a sequence of medium reconcile slices, not as one
ever-growing PR. The preferred slice boundary follows the closure controller
path:

```text
Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff
```

Each PR should advance one producer/consumer boundary or one bounded refactor
needed by that path. A PR may carry docs/tests/runtime together only when they
describe the same authority/proof path.

## PR #43 Policy

PR #43 is currently too heavy and should be treated as a frozen umbrella /
historical integration PR unless the user explicitly instructs otherwise.

Allowed changes to PR #43:

- fix CI or merge conflicts;
- update necessary explanation or proof boundaries;
- prepare split-out work;
- preserve already-produced evidence without adding new scope.

Forbidden by default:

- pushing new production feature work into PR #43;
- using PR #43 as the default branch for every future goal;
- using PR #43 as closure proof or the default evidence sink for new layers;
- claiming PR #43 is merge-ready because local tests or CI passed;
- emitting `pr_merged` without GitHub server-side merge proof.

Do not re-check or report PR #43 in every `/goal` stage summary. Only refresh
PR #43 when the task is explicitly about that PR, a split-out stack needs its
base truth, or a merge/readiness claim would otherwise be ambiguous. For normal
production-slice work, report the current local branch/slice and future small-PR
target instead.

## Current Heavy Worktree Split Protocol

If the current worktree already contains broad multi-slice changes, stop adding
new production scope until the dirty diff is inventoried and split into scoped
PR candidates.

Use `docs/xmuse/current-worktree-slice-inventory.md` as the live split guide for
the current heavy branch. Each candidate slice must declare:

- target layer(s);
- authority/proof path;
- likely files;
- proof level;
- forbidden claims;
- focused validation.

Do not use the existence of a dirty branch, old PR, passing local tests, or
passing old CI as a reason to keep piling unrelated changes into the same PR.

## Small PR Policy

Future work should create small PRs by default:

- one PR per medium production slice;
- one L-layer slice, lineage, or producer-consumer path per PR;
- docs/tests/runtime changes may live together only when they belong to the same
  proof path;
- TUI/cockpit/release-evidence-only changes should not be bundled with upstream
  runtime authority changes unless they are required projections of that slice.

Recommended size:

- ideal: 300-800 effective diff lines;
- warning: over 1200 effective diff lines requires a split rationale;
- avoid: broad PRs mixing architecture migration, runtime closure, TUI,
  release evidence, and GitHub truth.

Recommended production split order:

1. closure controller / condition model shell;
2. L8 recovery producer consolidation;
3. L9 execution-candidate and session boundary consolidation;
4. L9 -> L10 release handoff aggregation;
5. L10 MemoryOS/GitHub truth projection after upstream handoff exists.

If a slice crosses L8/L9/L10 in one diff, split it unless there is a documented
migration reason and focused validation for each crossed boundary.

## Branch Policy

Default base is the latest stable branch or `main`, unless the user specifies a
different base.

If a new slice depends on unmerged PR #43 content, use a stacked PR and mark it
clearly:

```text
Stacked on PR #43; not independently mergeable until the base lands.
```

After the upstream base lands, rebase or retarget downstream PRs onto the stable
base and re-run validation.

## Commit Policy

Commits should be grouped by production slice, not by wall-clock session.

Each commit should be able to answer:

- what authority/proof path changed;
- what validation ran;
- what remains unproven.

Do not commit runtime state:

```text
*.db
*.sqlite3
*.jsonl
feature_lanes.json
xmuse/work/
xmuse/history/
xmuse/logs/
.goal-runs/
```

Do not use destructive history commands such as `git reset --hard` unless the
user explicitly asks for that operation.

## Push Policy

Default: do not push unless explicitly instructed by the user or by the active
goal.

Before push:

```bash
uv run pytest <focused tests> -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```

If core/runtime package boundaries changed, also run:

```bash
uv run pytest tests/xmuse/test_package_boundaries.py -q
```

After push:

- update the relevant PR body with proof boundaries, manual gaps, validation,
  and forbidden claims;
- inspect GitHub Actions for the pushed head;
- keep CI success separate from review truth and merge truth.

## PR Body Requirements

Each PR body should include:

- target layer or production slice;
- authority/proof path changed;
- proof level: `contract_proof`, `local_runtime_proof`, `opt_in_live_proof`,
  `server_side_truth`, or `manual_gap`;
- validation commands and results;
- manual gaps that remain;
- forbidden claims that remain forbidden;
- whether the PR is standalone or stacked.

## Merge Truth

`ready_for_replay` is not `ready_to_merge`.

`ready_to_merge` requires explicit review/merge readiness criteria for the PR.

`pr_merged` may only be claimed after GitHub server-side merge proof confirms
the PR is merged.

Do not infer GitHub review or merge truth from:

- local git state;
- local tests;
- worker self-report;
- release evidence pack;
- CI success alone;
- TUI/dashboard/read model state.
