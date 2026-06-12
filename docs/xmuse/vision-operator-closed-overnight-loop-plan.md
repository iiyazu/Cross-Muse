# Vision Operator-Closed Overnight Loop Plan

> **For agentic workers:** This is an 8 hour `/goal` handoff. Implement as
> vertical slices with tests, proof discipline, docs, and a final review. Do not
> treat this plan as evidence that the loop already exists.

**Goal:** Move xmuse from a read-only TUI visibility wave toward an
operator-closed overnight loop: the cockpit can trigger evidence-oriented
actions, inspect laneDAG blockers, supervise long runtime work, and produce
auditable artifacts without overstating live proof.

**Architecture:** Durable authority remains in chat/envelope stores, frozen
blueprint revisions, graph sets, review artifacts, MemoryOS REST evidence,
provider runtime manifests, and GitHub server truth captures. TUI/dashboard
surfaces remain projections and command entry points; they must not become
direct state authority.

**Tech Stack:** Python, Textual, FastAPI read surfaces, xmuse_core contracts,
MemoryOS Lite REST compatibility, GitHub CLI/API evidence capture, provider
runtime manifests, pytest, ruff, uv.

---

Updated: 2026-06-12

Source report:

```text
C:\tmp\deep-research-report_08.md
/mnt/c/tmp/deep-research-report_08.md
```

Short `/goal` prompt:

```text
docs/xmuse/vision-operator-closed-overnight-loop-goal-prompt.md
```

## Context

`deep-research-report_08` concludes that the
`vision-closure-deliberation-tui` wave was successful as a TUI visibility wave,
but it was not full xmuse vision closure. It made deliberation, blueprint
freeze, execution, MemoryOS, GitHub truth, and provider runtime projections
visible. It did not yet turn the TUI into an operator cockpit, prove natural
multi-GOD runtime transcripts, run live MemoryOS Lite, soak real providers, or
close mainline GitHub truth.

This next overnight run should not be another UI polish pass. It should create
the smallest useful operator loop:

```text
read current truth
-> trigger or import evidence-oriented actions
-> inspect laneDAG blockers and lineage
-> supervise 8h work with checkpoints and manual_gap fallback
-> emit an auditable walkthrough/evidence pack
```

The run may improve TUI screens, command surfaces, read models, provider
manifests, and docs. It must not claim live/server-side/real-provider proof
unless the artifact is captured.

## Starting Point

Known handoff state from the previous session:

- Branch: `vision-closure-deliberation-tui`
- HEAD: `584e2b6f627b8e680a3ae2b70ed6abb3457b366d`
- Remote branch: `origin/vision-closure-deliberation-tui`
- PR: not created at handoff time
- Existing validation: focused TUI/read-model and contract suites passed; ruff
  passed; `git diff --check` passed; `xmuse/__init__.py` did not exist

The goal runner must verify this state in S0 instead of assuming it is still
current.

## Proof Vocabulary

Use these labels consistently in code, UI, docs, and artifacts:

| Label | Meaning |
| --- | --- |
| `contract_proof` | Deterministic local contract or fixture proves behavior. |
| `fake_runtime_proof` | Fake/local runtime path ran without live services. |
| `live_service_proof` | A live service returned evidence. |
| `server_side_enforcement_proof` | GitHub server settings/statuses prove enforcement. |
| `server_side_merge_proof` | GitHub merge event, merge commit, and merged timestamp prove merge fact. |
| `real_provider_proof` | Real Codex/OpenCode/Ray/MCP/provider runtime produced evidence. |
| `manual_gap` | Required operator/admin/live evidence is missing or unavailable. |

Readiness is not completion. Never render `ready_to_freeze` as `frozen`,
`review_ready` as `review_complete`, `merge_ready` as `pr_merged`, or local
evidence as server-side fact.

## Non-Goals

- Do not rebuild a browser frontend.
- Do not convert OpenCode into peer-GOD production authority by assertion.
- Do not make TUI cards, dashboard rows, `feature_lanes.json`, or Ray actors
  durable authority.
- Do not rewrite chat, structuring, orchestration, MemoryOS, or provider layers
  as broad refactors.
- Do not require secrets, live services, real providers, or GitHub admin access
  in default tests.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- Do not open or merge a PR before the operator loop has a focused validation
  story. PR prep is a final-stage activity only.

## 8 Hour Budget

Treat 8 hours as a hard planning budget, not a promise that every stretch item
will fit.

| Window | Focus | Expected output |
| --- | --- | --- |
| 0:00-0:30 | S0 truth map | Current branch, dirty state, proof state, and stale assumptions recorded. |
| 0:30-2:00 | S1 TUI actuation | One or more evidence actions are callable and tested. |
| 2:00-3:30 | S2 laneDAG drill-down | Blockers, dependencies, review verdicts, and patch-forward lineage are easier to inspect. |
| 3:30-5:30 | S3 overnight supervisor | Heartbeat, stage journal, checkpoint/resume, and manual_gap fallback exist as a bounded runtime loop or contract harness. |
| 5:30-7:00 | S4 opt-in live soak harness | Live/provider/MemoryOS/GitHub proof can be attempted when configured and cleanly gapped when unavailable. |
| 7:00-8:00 | S5 validation and docs | Focused tests, ruff, diff check, walkthrough/evidence pack, and next backlog. |

If a stage is blocked, emit a `manual_gap` artifact and move to the next highest
value stage. Do not spend the whole night waiting on auth, secrets, live
services, or external admin state.

## Work Packages

### S0 - Current-State Truth Map

Goal: establish the real starting point before changing behavior.

- [ ] Read `AGENTS.md`, `docs/xmuse/README.md`, this plan, the short prompt,
  `docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md`,
  `docs/xmuse/vision-galaxy-live-evidence-plan.md`, and the source report.
- [ ] Run `git status --short --branch`; preserve unrelated worktree changes.
- [ ] Confirm whether `xmuse/__init__.py` is absent.
- [ ] Inspect current TUI action/navigation surfaces, lane detail screens,
  supervisor/self-evolution modules, provider inventory, MemoryOS Lite
  interop, and GitHub truth capture.
- [ ] Record proven facts, contract-only facts, fake/local facts, and
  `manual_gap` items in the eventual walkthrough/evidence artifact.

Acceptance:

- No behavior changes are made in S0.
- Current assumptions from the report are either confirmed or corrected.
- The goal runner knows which files are safe to touch.

### S1 - TUI Actuation For Evidence Actions

Goal: make the TUI or slash-command surface able to trigger or import evidence
without claiming the evidence is stronger than it is.

Required actions, in priority order:

1. Export or load a deliberation transcript artifact from durable
   message/envelope stores.
2. Refresh or load GitHub truth evidence from the existing capture contract.
3. Refresh or load MemoryOS Lite trace evidence through REST-compatible
   surfaces.
4. Navigate from deliberation blockers or source refs into freeze, feature, or
   lane detail.

Implementation guidance:

- Prefer existing command and read-model patterns over inventing a new control
  plane.
- If full TUI keyboard interaction is too large, implement the core action
  service and expose it through the smallest existing command surface first.
- Every action result must carry proof level, source refs, artifact path or
  `manual_gap_reason`, and a timestamp.
- Refreshing evidence is not the same as asserting a completed fact.

Acceptance:

- Focused tests prove action results distinguish success, partial evidence, and
  `manual_gap`.
- TUI/dashboard remains a projection plus command entry point, not authority.
- Transcript export does not scrape rendered TUI text.

### S2 - LaneDAG Drill-Down And Operator Navigation

Goal: turn lane/feature screens into useful operator drill-down paths.

- [ ] Show dependencies, gate predecessors, touched areas, review verdicts,
  patch-forward lineage, merge blockers, and source refs where the existing
  contracts provide them.
- [ ] Link or route from feature board to lane detail and from blockers/source
  refs to the relevant detail view when feasible.
- [ ] Preserve `feature_lanes.json` as projection/queue only.
- [ ] Keep review readiness, review decision, merge readiness, and merge fact
  separate.

Acceptance:

- A reader can trace a blocked or ready lane back to the blueprint/source refs.
- Patch-forward and review lineage are visible when supplied by existing data.
- Missing lineage is shown as `manual_gap` or absent data, not hidden success.

### S3 - Overnight Supervisor Contract And Runtime Loop

Goal: make an 8 hour goal run auditable, resumable, and able to continue after
bounded failures.

Minimum supervisor behavior:

- heartbeat
- stage journal
- checkpoint/resume metadata
- issue discovery queue
- focused validation record
- self-review checkpoints every 45-60 minutes or at each stage boundary
- failure classification
- `manual_gap` artifact emission
- automatic move to the next high-value task when blocked

Implementation guidance:

- Reuse existing `src/xmuse_core/self_evolution/`,
  `src/xmuse_core/platform/`, or goal-stage harness concepts when they fit.
- Store durable state only in approved contract/artifact paths. Do not track
  runtime DBs or logs.
- The loop does not need to run for 8 real hours inside tests. Tests should
  simulate stage transitions, checkpoint/resume, and blocked fallback.

Acceptance:

- The supervisor can explain what stage ran, what passed, what failed, what was
  skipped, and why it moved on.
- A failed live/auth/provider step does not stop the whole overnight loop.
- The supervisor does not write lane status directly unless it goes through an
  approved contract.

### S4 - Opt-In Live Soak Harness

Goal: allow live evidence attempts when configured, while keeping default tests
no-secrets and no-live.

Evidence targets:

- natural or operator-supplied multi-GOD transcript
- MemoryOS Lite REST trace
- provider/Codex/OpenCode/Ray/MCP runtime heartbeat or session continuity
- GitHub checks, review truth, branch protection, or merge event truth

Rules:

- Default tests must skip live calls.
- Live attempts require explicit environment/config flags.
- Missing live prerequisites produce `manual_gap` artifacts with next actions.
- OpenCode stays bounded/secondary unless persistent session, writeback,
  MemoryOS trace, review evidence, and GitHub truth are all proven.
- If invoking OpenCode, use exactly:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Acceptance:

- Contract/fake tests can parse live-style artifacts without live services.
- Live evidence, when present, is labeled no stronger than its source.
- Lack of secrets/auth/admin rights is recorded as `manual_gap`, not failure to
  complete the whole wave.

### S5 - Evidence Pack, Docs, Validation, And PR Readiness

Goal: leave the next session with a complete, auditable handoff.

- [ ] Create or update an evidence/walkthrough doc under `docs/xmuse/`.
- [ ] Update `docs/xmuse/README.md` for any new stable plan, prompt, or
  evidence artifact.
- [ ] Record proof-level changes and remaining manual gaps.
- [ ] Run focused tests for every changed surface.
- [ ] Run `uv run ruff check .`.
- [ ] Run `git diff --check`.
- [ ] Run `uv run pytest tests/xmuse/test_package_boundaries.py -q` if any
  import boundaries moved.
- [ ] Prepare PR-ready notes if the branch is ready. If GitHub auth is
  unavailable, record the gap without claiming a PR exists.

Acceptance:

- Final report names changed files, validation commands/results, proof-level
  changes, and remaining manual gaps.
- No runtime state is tracked.
- `xmuse/__init__.py` remains absent.

## Behavior Rules

### Execution Discipline

- Use `uv run` for pytest, ruff, mypy, scripts, and Python entrypoints.
- Work in vertical slices: failing test, implementation, focused validation,
  doc/artifact update, self-review.
- Keep changes scoped to the operator-closed overnight loop.
- Do not perform unrelated cleanup, history rewriting, broad formatting, or
  large architecture rewrites.
- Preserve unrelated worktree changes. Do not use `git reset --hard` or
  destructive checkout commands.

### Hourly Self-Review

Every 45-60 minutes or at each stage boundary, check:

- Is the current work still serving the overnight operator loop?
- Did any projection become accidental authority?
- Did any readiness state become a completed fact?
- Did any live claim appear without a live artifact?
- Did any runtime state, DB, jsonl, or ignored path become tracked?
- Did any package boundary move require `test_package_boundaries.py`?

Record the answer in the stage journal or final walkthrough.

### Blocked Work

When blocked by auth, live service, GitHub admin state, provider availability, or
unclear external facts:

1. emit a `manual_gap` artifact or doc entry;
2. record the command/config attempted when safe;
3. record the missing prerequisite;
4. record the next action;
5. move to the next high-value local/contract task.

Do not wait for human input during the overnight goal unless continuing would
risk data loss, secrets exposure, destructive git changes, or false proof.

### Authority Boundaries

- Durable authority remains in graph sets, stores, review artifacts, MemoryOS
  REST evidence, and GitHub server truth.
- TUI, dashboard cards, `feature_lanes.json`, and runtime health views are
  projections.
- LangGraph may orchestrate workflows but must not write lane status directly.
- Ray actors are not durable state authority.
- `xmuse/` may import `xmuse_core.*`; `xmuse_core` must not import runtime
  `xmuse/` or `memoryos_lite`.
- `xmuse/__init__.py` must not exist.

### Proof Discipline

- Label every evidence claim with the strongest proven level and no stronger.
- Use `manual_gap` when operator/admin/live evidence is missing.
- Do not describe deterministic fixtures as natural multi-GOD proof.
- Do not describe fake/default MemoryOS tests as live MemoryOS proof.
- Do not describe provider inventory as real provider runtime soak.
- Do not describe local checks or merge readiness as GitHub merge fact.
- Reserve `pr_merged` for server-side merge evidence.

## Minimum Done Criteria

The 8 hour run is successful if it leaves:

- at least one evidence-oriented TUI/command action implemented or clearly
  gapped;
- materially better laneDAG/blocker/review/patch-forward drill-down, or a
  precise blocked artifact explaining why not;
- an overnight supervisor contract or harness with simulated tests for
  heartbeat, checkpoints, and blocked fallback;
- an opt-in live soak path that defaults to no-live tests and emits
  `manual_gap` when prerequisites are absent;
- docs/evidence artifacts that distinguish contract, fake, live, server-side,
  real-provider, and manual gaps;
- focused validation and ruff results;
- no new package-boundary, runtime-state, or proof-label violations.

## Stretch Criteria

Only attempt these after the minimum done criteria are satisfied:

- create a PR if GitHub auth and branch state allow it;
- capture a real live MemoryOS Lite trace;
- capture real provider/session heartbeat evidence;
- capture authenticated GitHub server-side truth refresh;
- run a longer local supervisor soak outside the unit tests.
