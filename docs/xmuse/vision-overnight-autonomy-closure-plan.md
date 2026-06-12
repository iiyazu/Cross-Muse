# Vision Overnight Autonomy Closure Plan

> **For agentic workers:** This is the next long `/goal` handoff after the
> production evidence/control closure wave. Use stage manifests, TDD, focused
> validation, proof discipline, and independent Codex review. This plan is not
> evidence that overnight autonomy already exists.

**Goal:** Move xmuse from production evidence/control contracts toward a
repeatable overnight autonomy loop: durable GOD runtime continuity, natural
multi-GOD transcript evidence, feature-graph-first execution, MemoryOS
governance, fresh GitHub truth, TUI proof cockpit, and release evidence pack in
one auditable run.

**Architecture:** Keep the current two-phase product model: decentralized GOD
deliberation freezes a blueprint, then centralized feature/lane execution and
review proceed through durable contracts. Durable authority remains in chat and
envelope stores, GOD session records, frozen blueprint revisions, graph sets,
review artifacts, MemoryOS REST evidence, provider runtime manifests, and
GitHub server truth. TUI/dashboard are operator surfaces and projections; every
mutation must go through authenticated contract/API actions.

**Tech Stack:** Python, FastAPI, Textual, xmuse_core contracts, provider/GOD
registry, goal-stage harness, MemoryOS Lite REST compatibility, GitHub CLI/API
truth capture, Ray/Codex/OpenCode provider probes, pytest, ruff, uv.

---

Updated: 2026-06-12

Source reports:

```text
C:\tmp\deep-research-report_10.md
/mnt/c/tmp/deep-research-report_10.md
C:\tmp\outer-muse.md
/mnt/c/tmp/outer-muse.md
```

Short `/goal` prompt:

```text
docs/xmuse/vision-overnight-autonomy-closure-goal-prompt.md
```

## Starting Facts

The source reports correctly identify the next product pressure: xmuse has a
strong contract and evidence skeleton, but the next closure target is a natural
runtime loop that can be repeated, supervised, reviewed, and replayed.

The reports were written against older public baselines and should not be used
as current server truth. At this handoff, the current local/GitHub facts must be
rechecked by the next `/goal` runner. Known facts from this planning session:

- Branch: `vision-closure-deliberation-tui`.
- Current head: `4ed83bc82ae66b23e4c3d0613933b6f908739e12`.
- PR #43: draft/open/unmerged.
- GitHub Actions run `27424190281` succeeded for current head.
- `pr_merged` is not true; review truth and merge truth remain absent.
- Current shell exposed no `XMUSE_*`, `DEEPSEEK_API_KEY`, or MemoryOS live
  configuration. `gh`, `codex`, `opencode`, and Ray import were available.
- Historical live artifacts described in walkthroughs or PR body must not be
  reused as fresh proof without re-capture or explicit artifact validation.
- OpenCode remains a bounded worker unless durable registration, capability,
  persistence, MCP/writeback, review, provider proof, and GitHub truth are all
  independently proven.

## Product Direction

The next wave should not add another independent dashboard or more demo
fixtures. It should integrate existing production-control pieces into one
operator-ready autonomy loop:

```text
fresh truth map
-> natural GOD deliberation or precise manual_gap
-> frozen blueprint
-> feature graph owner / laneDAG execution plan
-> overnight supervisor with heartbeat/checkpoint/review fallback
-> MemoryOS trace and replay bundle
-> GitHub server truth and internal review boundary
-> TUI proof cockpit / release evidence pack
```

The reports' external inspiration is useful only as design pressure:

- persistent identity and cross-model review imply explicit GOD runtime records;
- manager/handoff patterns imply deliberation can be decentralized while
  execution remains centrally supervised;
- simple, composable agent workflows imply small state machines with evidence,
  not a broad rewrite;
- supervisor-worker patterns imply heartbeat, checkpoint, failure
  classification, and recovery contracts before distributed runtime expansion.

## Proof Vocabulary

Use these labels consistently in code, docs, UI, and artifacts:

| Label | Meaning |
| --- | --- |
| `contract_proof` | Deterministic local contract or fixture proves behavior. |
| `fake_runtime_proof` | Fake/local runtime path ran without live services. |
| `live_service_proof` | A live service returned evidence. |
| `server_side_enforcement_proof` | GitHub server settings/statuses prove enforcement. |
| `server_side_merge_proof` | GitHub merge event, merge commit, and merged timestamp prove merge fact. |
| `real_provider_proof` | Real Codex/OpenCode/Ray/MCP/provider runtime produced evidence. |
| `internal_review_proof` | Verified local/internal review artifact for single-maintainer workflow. |
| `manual_gap` | Required operator/admin/live evidence is missing or unavailable. |

Readiness is not completion. Never render `ready_to_freeze` as `frozen`,
`review_ready` as `review_complete`, `merge_ready` as `pr_merged`, or
`internal_review_proof` as GitHub server enforcement.

## Non-Goals

- Do not rebuild a browser frontend.
- Do not rewrite chat, MemoryOS interop, provider runtime, review plane, or TUI
  as broad refactors.
- Do not promote OpenCode, Ray actors, TUI projections, dashboard cards,
  `feature_lanes.json`, or provider subprocess memory to durable authority.
- Do not bypass Chat API/MCP/platform operator-action contracts for mutation.
- Do not claim fresh live/server/provider proof from old artifacts unless the
  artifact is explicitly validated against current head/configuration.
- Do not weaken GitHub merge truth. `pr_merged` still requires server-side
  merge proof.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- Do not create `xmuse/__init__.py`.

## Stage Budget

Treat this as an 8-10 hour production-grade closure run. If a live or external
dependency blocks, emit an honest blocker/manual_gap artifact and continue only
to independent stages.

| Window | Stage | Expected output |
| --- | --- | --- |
| 0:00-0:30 | S0 Baseline Truth | Branch, dirty state, PR/CI truth, env/probe state, current proof map. |
| 0:30-1:15 | S1 Evidence/Manifest Spine | Stage manifests and shared production evidence envelope for this run. |
| 1:15-2:30 | S2 GOD Runtime Continuity | GOD CLI/session continuity contract advanced; natural transcript path audited or gapped. |
| 2:30-3:45 | S3 Feature-Graph-First Execution | Feature owner/ready-set contract defined without making lanes a second authority. |
| 3:45-5:00 | S4 Overnight Supervisor Loop | Heartbeat/checkpoint/self-review/failure fallback integrated with stage results. |
| 5:00-6:15 | S5 Memory Governance And Replay | Memory layer/promotion/replay bundle path advanced through REST-first contracts. |
| 6:15-7:15 | S6 Fresh GitHub Truth And Review | Current PR/server truth re-captured or blocked; internal review boundary explicit. |
| 7:15-8:15 | S7 TUI Proof Cockpit | Operator-facing proof/replay/readiness control surface advanced through contracts. |
| 8:15-10:00 | S8 Live Soak, Validation, Docs, PR | Configured live gates attempted, release pack updated, focused tests and quality gates run. |

## S0 - Baseline Truth

Goal: reconcile the source reports with current repository and server facts
before changing behavior.

Tasks:

- Read `AGENTS.md`, `docs/xmuse/README.md`,
  `docs/xmuse/mainline-contracts.md`,
  `docs/xmuse/development-goal-worker-delegation-policy.md`,
  `docs/xmuse/goal-stage-harness.md`,
  `docs/xmuse/vision-production-evidence-control-closure-plan.md`,
  `docs/xmuse/vision-production-evidence-control-closure-walkthrough.md`,
  this plan, the short prompt, and the two source reports.
- Run `git status --short --branch`; preserve unrelated changes.
- Confirm `xmuse/__init__.py` is absent.
- Re-check PR #43 metadata and latest GitHub Actions for current head.
- Inventory configured live resources by key presence/probes only: MemoryOS
  Lite, GitHub auth, Ray/Codex, OpenCode/DeepSeek, MCP/Chat API ports, TUI
  operator token bundle.
- Record which facts are current, stale, contract-only, live/server-side, or
  `manual_gap`.

Acceptance:

- No behavior changes are made in S0.
- Stale report claims are corrected with exact current dates/SHAs.
- Missing configured resources have owner and next action.

## S1 - Evidence Envelope And Stage Manifest Spine

Goal: make this long goal replayable and reject natural-language-only
completion claims.

Tasks:

- Create stage manifests for each bounded implementation stage, or update the
  existing harness usage so every stage produces `result.json`.
- Use a shared `xmuse.production_evidence.v1` envelope for stage/action
  summaries:

```json
{
  "schema_version": "xmuse.production_evidence.v1",
  "stage_id": "S1",
  "action": "stage_manifest_prepared",
  "status": "ok",
  "proof_level": "contract_proof",
  "source_authority": "goal_stage_harness",
  "source_refs": [],
  "target_refs": [],
  "commands": [],
  "test_results": [],
  "artifacts": [],
  "blocked_reason": null,
  "owner": "codex",
  "next_action": null
}
```

- Keep `.goal-runs/` and runtime evidence directories ignored and uncommitted.
- Add tests only if schema parsing or redaction behavior changes.

Acceptance:

- No stage can advance based only on prose.
- Evidence envelopes do not become durable authority for lane/review/GitHub
  facts; they only summarize source authorities.

## S2 - GOD Runtime Continuity And Natural Transcript Spine

Goal: close the gap between selectable GOD CLI choices and repeatable natural
multi-GOD runtime evidence.

Tasks:

- Inspect `GodCliRegistration`, `GodCliSelectionStore`,
  `GodSessionRegistry`, provider session binding, and natural transcript export
  contracts.
- Advance the selected-GOD runtime view so each active GOD can expose:
  `god_id`, `cli_id`, provider profile, provider session id, capability scope,
  heartbeat/freshness, waiting reason, proof level, and source refs.
- Ensure bounded CLIs such as OpenCode remain bounded unless all peer-GOD proof
  prerequisites are present.
- Add or improve a natural transcript export path that reads durable
  chat/session state, never scrapes TUI rendering, and requires provider session
  metadata before `real_provider_proof`.
- If live natural transcript capture cannot run in the current environment,
  emit a `manual_gap` artifact with missing prerequisite, owner, and exact next
  action.

Acceptance:

- Operator can tell which selected GODs are active, stale, bounded, or blocked.
- Natural transcript export separates deterministic replay from real-provider
  multi-GOD evidence.
- Single-GOD, missing-session, deterministic, or blocked transcripts cannot
  satisfy production release gates.

Current implementation status:

- `build_selected_god_runtime_continuity_view` projects selected GOD CLI,
  registration, session, provider-session metadata, capability scope, proof
  level, and waiting reasons without upgrading bounded workers.
- `xmuse-natural-deliberation-gate-capture` accepts an optional
  `--god-runtime` artifact. When supplied, the natural-deliberation release
  gate requires every transcript GOD to have a peer-GOD-ready selected runtime
  row. Bounded OpenCode workers, missing runtime rows, or provider-session gaps
  block the gate as `manual_gap`.
- Natural transcript export still reads durable chat/session state and never
  scrapes TUI rendering. The old no-runtime-artifact gate path remains for
  compatibility, but production overnight evidence should attach runtime
  continuity before treating a transcript as release evidence.

## S3 - Feature-Graph-First Execution Owner

Goal: turn blueprint execution from lane-centric projection into a
feature-owner-driven default path without breaking existing lane contracts.

Tasks:

- Inspect blueprint freeze, feature plan, graph-set/laneDAG, projection, and
  `SubagentRuntimeContract` surfaces.
- Define or extend a feature owner contract that carries feature-level
  objective, allowed files, lane ready-set, memory refs, required checks,
  review profile, patch-forward policy, and rollback constraints.
- Keep lanes as internal execution/replay units under the feature owner. Do not
  make `feature_lanes.json` a new authority.
- Add focused contract tests for ready-set scheduling, dependency blocking, and
  no double-authority writes.
- If this stage is too large for the run, land a precise contract/design slice
  and explicitly defer scheduler implementation.

Acceptance:

- A frozen blueprint can map to feature owner responsibilities and laneDAG
  ready-set semantics.
- Existing lane/review/patch-forward lineage remains visible and replayable.
- LangGraph, Ray, TUI, and dashboard remain orchestration/projection surfaces,
  not status authorities.

## S4 - Overnight Supervisor Runtime Loop

Goal: make long `/goal` execution auditable, resumable, and able to continue
after bounded failures.

Tasks:

- Reuse `goal_stage_runner.py` and
  `src/xmuse_core/platform/overnight_operator_supervisor.py` where possible.
- Integrate heartbeat, stage journal, checkpoint/resume metadata, issue queue,
  focused validation record, self-review checkpoints, failure classification,
  and `manual_gap` fallback.
- Simulate 8-10 hours with virtual/logical time in tests; do not sleep in CI.
- Ensure stage status transitions use `ok`, `retry`, and `blocked` and respect
  stage `max_retries`.
- Add rules that a configured-but-failing live gate is a release blocker, while
  unconfigured optional resources become `manual_gap` with owner/next action.

Acceptance:

- Supervisor can explain what ran, what passed, what failed, what was skipped,
  why it moved on, and which artifacts support each claim.
- Heartbeat/review snapshot SLO checks are deterministic in tests.
- A failed live/auth/provider step does not erase independent work.

## S5 - Memory Governance And Replay Bundle

Goal: move MemoryOS from a live trace adapter into a governed memory/replay
plane for GOD collaboration.

Tasks:

- Read `docs/xmuse/memoryos-governance-contract.md`,
  `docs/xmuse/v6-session-vs-shared-memory-boundary.md`, MemoryOS Lite interop,
  tombstone/redaction tests, and release gate capture paths.
- Define or advance personal/task/shared/global memory layer policy:
  what stays in provider session binding, what goes to MemoryOS, what can be
  promoted, what must be tombstoned/redacted, and what requires review.
- Keep MemoryOS REST-first; never import `memoryos_lite` from `xmuse_core`.
- Build or extend a replay bundle that links deliberation transcript, frozen
  blueprint, feature/lane lineage, MemoryOS trace, GitHub truth, long-run
  heartbeat summary, and release readiness artifacts.
- If live MemoryOS is configured, attempt `xmuse-memoryos-live-trace-capture`;
  otherwise produce a precise `manual_gap`.

Acceptance:

- Memory promotion policy prevents "everything goes into memory" and
  "everything stays in provider session" extremes.
- Replay bundle preserves source refs and proof levels without upgrading weak
  evidence.
- Tombstoned/redacted source refs do not return as active memory.

Current implementation status:

- `plan_memoryos_governed_write` now defines a contract-level MemoryOS
  governance decision before any REST ingest request is built. It distinguishes
  personal/task/shared/global scopes, requires actor identity and source refs,
  blocks shared promotion without an explicit shared namespace and review, and
  keeps provider session continuity in `GodSessionRecord` /
  `ProviderSessionBindingStore` instead of mirroring live session state into
  MemoryOS.
- The governed write plan can be converted to `MemoryOSIngestRequest` only for
  allowed `ingest` or `promote_to_shared` decisions. Blocked decisions and
  provider-binding-only decisions do not produce write requests.
- `MemoryOSWritebackEvent` now routes through this governance plan before
  calling a MemoryOS client. Ordinary task writeback remains allowed, reviewed
  shared promotion can still write to the shared namespace, and unreviewed
  shared promotion returns a blocked result without writing MemoryOS state.
- The overnight replay bundle now requires a `memory_governance` section in
  addition to `memoryos_trace`, so replay can show both MemoryOS trace evidence
  and the policy decision that made a memory write/promotion acceptable.
- `uv run xmuse-overnight-replay-bundle-capture` builds a replay index from
  release gate artifacts and explicit `xmuse.production_evidence.v1` section
  artifacts. It fills unattached required sections with `manual_gap` instead of
  omitting them, so an overnight run can be replayed without prose-only gaps.
- `uv run xmuse-memoryos-governance-evidence-capture` exports governed
  MemoryOS writeback events or governed write plans into a replay-ready
  `xmuse.production_evidence.v1` artifact for the `memory_governance` section.
  It reuses the existing policy, preserves blocked shared-promotion decisions as
  `manual_gap`, and does not claim live MemoryOS trace proof.
- `uv run xmuse-frozen-blueprint-evidence-capture` exports a frozen
  `mission_blueprint.v1` artifact into replay-ready
  `xmuse.production_evidence.v1` for the `frozen_blueprint` section. Draft or
  otherwise unfrozen blueprints stay `manual_gap` and cannot start feature
  execution proof by rendering alone.
- `uv run xmuse-overnight-supervisor-evidence-capture` exports a supervisor
  snapshot into a replay-ready `xmuse.production_evidence.v1` artifact. This
  can satisfy the replay bundle's `supervisor` section with contract-level
  heartbeat/checkpoint evidence while preserving any live gate `manual_gap`
  artifacts as separate blockers.
- Existing redaction, tombstone filtering, REST-first MemoryOS Lite interop,
  and no-`memoryos_lite` package boundary rules remain in force. Live MemoryOS
  trace capture is still a configured live gate: when it is not configured, the
  run must emit `manual_gap` instead of pretending to have live proof.

## S6 - Fresh GitHub Truth And Review Boundary

Goal: make GitHub server truth a fresh capture step in the long run, not a stale
claim copied from old docs.

Tasks:

- Re-run read-only GitHub truth capture for the current PR/head when auth and
  repo visibility allow it.
- Include branch protection/ruleset/check truth, draft/merge state, review
  truth, merge truth, and exact head SHA in artifacts.
- Add stale-proof handling: old capture can inform docs but cannot satisfy
  current proof unless recaptured or validated for the current head.
- Keep internal review artifact semantics separate from GitHub server-side
  review enforcement.
- If capture exits nonzero because the PR is draft/unmerged, preserve the raw
  snapshot and gate artifact; do not convert it into failure unless a required
  configured gate failed.

Acceptance:

- `server_side_enforcement_proof` is only emitted from GitHub server evidence.
- `server_side_merge_proof` and `pr_merged` remain false until merge event,
  merge commit, merged timestamp, and required truth are present.
- Release readiness names GitHub blockers with owner and next action.

Current implementation status:

- `scripts/github_server_truth_capture.py` records the captured PR head SHA in
  the raw `github_server_side_truth_capture.v1` artifact. When the caller
  supplies `--expected-head-sha`, the artifact also records
  `expected_head_sha` and `head_sha_matches_expected`.
- A mismatched expected head keeps `can_emit_pr_merged` false and converts the
  GitHub server-truth release gate to `manual_gap`, even if branch/ruleset and
  check evidence were captured. This prevents stale GitHub artifacts from
  satisfying the current overnight run.
- `xmuse-live-gate-status-capture` accepts the same guard through
  `XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA` when it performs configured GitHub
  server-truth capture.
- The release gate source refs now include the actual GitHub head SHA, and
  include the expected head SHA when provided. These refs are evidence links,
  not merge truth.

## S7 - TUI Proof Cockpit And Operator Control

Goal: make TUI the operator cockpit for proof/replay/readiness without making
it an authority.

Tasks:

- Build on existing TUI vision read model, Provider Board, execution cockpit,
  GitHub truth panel, Memory trace drawer, release commands, and operator
  action routes.
- Add or advance proof-aware read models/widgets for:
  deliberation transcript, GOD runtime continuity, feature/ready-set state,
  MemoryOS trace, GitHub truth, release readiness, and replay bundle.
- Keep all mutating commands behind Chat API/MCP/platform operator-action
  contracts with idempotency, capability checks, and audit records.
- Ensure TUI does not read/write projection files as authority, infer proof
  levels, or satisfy release gates by rendering data.
- Add focused TUI adapter/navigation/widget tests.

Acceptance:

- Operator can see proof level, source authority, current blockers, and next
  action for the run.
- TUI can trigger allowed evidence/control actions through official contracts.
- Projection-only writes are rejected or absent in tests.

Current implementation status:

- The TUI proof cockpit read model now exposes replay section statuses, so
  operator-visible proof can distinguish `memory_governance`,
  `memoryos_trace`, GitHub truth, supervisor, and release readiness sections
  without deriving authority from the TUI itself.
- The proof cockpit widget renders replay section status/proof/source authority
  plus selected-GOD runtime counts and sample GOD rows. It can show ready peer
  GODs, bounded workers, provider-session gaps, and waiting reasons in the same
  operator surface as release/replay blockers.
- This remains a projection/read model. Rendering `memory_governance` or a
  ready GOD runtime row does not satisfy release gates, does not write lane or
  MemoryOS state, and does not promote bounded OpenCode to peer-GOD proof.

## S8 - Live Soak, Release Evidence Pack, Validation, And PR Prep

Goal: leave an auditable handoff and keep the PR honest.

Tasks:

- Attempt configured live gates:
  - MemoryOS Lite REST trace;
  - natural multi-GOD transcript;
  - real provider/Codex/Ray/OpenCode bounded runtime evidence;
  - GitHub server truth;
  - production token-bundle Chat API/MCP/TUI smoke if configured.
- Use `uv run xmuse-live-gate-status-capture`,
  `uv run xmuse-release-evidence-pack`,
  `uv run xmuse-release-readiness-capture`, and
  `uv run xmuse-proof-contamination-audit` where appropriate.
- Use `uv run xmuse-overnight-supervisor-evidence-capture --snapshot ...` to
  turn the durable supervisor snapshot into explicit replay section evidence.
- Use `uv run xmuse-memoryos-governance-evidence-capture --writeback-event ...`
  or `--plan ...` to turn MemoryOS governance decisions into explicit replay
  section evidence.
- Use `uv run xmuse-frozen-blueprint-evidence-capture --blueprint ...` to turn
  a frozen mission blueprint artifact into explicit replay section evidence.
- Use `uv run xmuse-overnight-replay-bundle-capture` to assemble the replay
  index from release gate artifacts and attached section evidence.
- Update walkthrough/evidence docs under `docs/xmuse/`.
- Run focused tests for every changed surface.
- Always run:

```bash
uv run ruff check .
git diff --check
uv run pytest tests/xmuse/test_package_boundaries.py -q
test ! -e xmuse/__init__.py
```

- If validation passes and the user has not forbidden it, commit, push, update
  PR #43 body, and inspect GitHub Actions. Do not auto-merge.

Acceptance:

- Final report lists changed files, validation results, proof captured,
  blocked live gates, TUI authority paths, GOD runtime state, MemoryOS/GitHub
  evidence, and PR status.
- No runtime/cache state is tracked.
- No production proof is stronger than its artifact.

## OpenCode Delegation

Read and follow
`docs/xmuse/development-goal-worker-delegation-policy.md`.

Codex remains outer controller, planner, reviewer, verifier, committer, and
final fact judge. OpenCode may only be used as a bounded worker for scoped,
low-risk, verifiable subtasks with explicit manifests and gates. OpenCode
self-report is never proof.

If invoked directly, use exactly:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

Do not use `deepseek-v4-flash:max`,
`opencode-go/deepseek-v4-flash:max`, `deepseek-v4-flash-max`, or
`opencode-go/deepseek-v4-flash-max`.

## Minimum Done Criteria

The run is successful only if it leaves at least one validated production slice
in each of these categories, or a precise blocked artifact for the categories
that cannot be completed in the current environment:

- current truth map with PR/CI/env/proof facts;
- stage evidence spine with replayable result artifacts;
- GOD runtime/natural transcript continuity improvement;
- feature-graph-first execution or explicit feature-owner contract slice;
- overnight supervisor heartbeat/checkpoint/manual_gap behavior;
- MemoryOS governance or replay bundle improvement;
- fresh GitHub truth capture or precise GitHub blocker;
- TUI proof cockpit/control surface improvement;
- release evidence pack/readiness/proof-contamination result;
- focused validation, ruff, diff check, package boundary, and
  `xmuse/__init__.py` boundary.

## Final Report Requirements

The final `/goal` report must include:

- stages completed and blocked;
- files changed;
- validation commands and results;
- current PR #43 and GitHub Actions state;
- live/server/provider evidence captured during this run;
- configured live gates that blocked release readiness;
- GOD CLI/runtime selection and OpenCode boundary state;
- TUI mutation/evidence authority paths;
- MemoryOS governance/replay evidence state;
- remaining production gaps and owners;
- commit, push, PR body update, and draft PR status.
