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

Updated: 2026-06-13

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

Current implementation status:

- `uv run xmuse-goal-stage-evidence-capture --stage-result RESULT.json`
  converts one or more goal-stage runner `result.json` files into a replay-ready
  `xmuse.production_evidence.v1` artifact for the `stage_evidence` section.
  Non-`ok` stage results stay blocked `manual_gap` with owner and next action.
- The overnight replay bundle now requires a `stage_evidence` section alongside
  deliberation, blueprint, feature lineage, MemoryOS, GitHub, supervisor, and
  readiness sections. Missing stage evidence is represented as a replay
  `manual_gap`, not hidden in prose.
- `uv run xmuse-release-evidence-pack --goal-stage-result RESULT.json` converts
  goal-stage results into `goal-stage-production-evidence.json` before building
  the nested replay bundle. The pack only indexes prompt/manifest/result/output
  artifacts; it does not make `result.json` authoritative for lane status,
  review truth, GitHub truth, release readiness, or live runtime proof.
- TUI `/release pack stage=goal/S1.result.json` routes the same handoff through
  the audited operator action path and release-root path guard.
- `uv run xmuse-overnight-supervisor --resume import-stage-result RESULT.json`
  imports one goal-stage runner result into the durable supervisor snapshot as
  `goal_stage_results` plus a `goal_stage_result_imported` production-evidence
  envelope sourced from `goal_stage_harness`. `ok` results complete only that
  supervisor stage as `contract_proof`; `blocked` results stay `manual_gap`,
  record issue/failure rows, and can trigger dependency-aware fallback to the
  next ready independent stage.
- The TUI proof cockpit read model can project those supervisor
  `goal_stage_results` as a read-only long `/goal` stage spine with summary
  counts, result artifact refs, blockers, and fallback targets. This keeps stage
  harness evidence visible to the operator without turning TUI rendering into
  release readiness, lane status, review truth, GitHub truth, or live runtime
  proof.

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
- `GodSessionRegistry.record_heartbeat(...)` persists
  `last_heartbeat_at_utc` in durable `god_sessions.json`, and the selected-GOD
  runtime view reports heartbeat freshness against an explicit TTL. Fresh
  heartbeats keep otherwise-ready selected GODs usable; stale or invalid
  heartbeats become `manual_gap` blockers and make `peer_god_ready=false`.
- `uv run xmuse-god-runtime-continuity-capture` exports the selected-GOD
  runtime continuity artifact from durable `god_cli_selections.json`,
  `god_cli_registrations.json`, and `god_sessions.json`. This makes the
  runtime-continuity input repeatable for overnight evidence packs without
  treating TUI/dashboard projections, feature lane projections, Ray actor
  memory, or provider subprocess state as authority.
- TUI `/release export god-runtime ...` calls the audited
  `export_god_runtime_continuity` operator action for the same capture. This
  gives the overnight operator console a write path for the supporting runtime
  artifact while preserving durable-store authority and `release_gate`
  capability checks.
- `xmuse-natural-deliberation-gate-capture` now requires a
  `--god-runtime` artifact for an ok production gate. The natural-deliberation
  release gate requires every transcript GOD to have a peer-GOD-ready selected
  runtime row. Missing runtime evidence, bounded OpenCode workers, missing
  runtime rows, or provider-session gaps block the gate as `manual_gap`.
- Natural transcript export still reads durable chat/session state and never
  scrapes TUI rendering. The TUI/operator natural export path now captures
  selected-GOD runtime continuity by default and binds it into the natural
  release gate. `god_runtime=skip` remains for compatibility-only replay, but
  production overnight evidence should keep the default runtime binding before
  treating a transcript as release evidence.

## S3 - Feature-Graph-First Execution Owner

Goal: turn blueprint execution from lane-centric projection into a
feature-owner-driven default path without breaking existing lane contracts.

Tasks:

- Inspect blueprint freeze, feature plan, graph-set/laneDAG, projection, and
  `SubagentRuntimeContract` surfaces.
- Define or extend a feature owner contract that carries feature-level
  objective, allowed files, lane ready-set, memory refs, required checks,
  review profile, patch-forward policy, and rollback constraints.
- The `xmuse.feature_owner_execution_contract.v2` contract must include
  graph-native ready-set provenance, explicit lane blocker reasons, and a
  read-only status write policy so blocked lanes are replayable without making
  TUI/dashboard projections, LangGraph, Ray, or `feature_lanes.json`
  authoritative.
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
- Add a repeated-failure rule: if the same stage/function boundary fails three
  times, stop retrying local fixes and emit a `refactor_required` issue plus
  production evidence before another attempt.

Acceptance:

- Supervisor can explain what ran, what passed, what failed, what was skipped,
  why it moved on, and which artifacts support each claim.
- Heartbeat/review snapshot SLO checks are deterministic in tests.
- A failed live/auth/provider step does not erase independent work.

Current implementation status:

- `uv run xmuse-overnight-supervisor` now exposes the existing
  `OvernightSupervisor` contract as a resumable operator command. It can start
  stages, record heartbeats, write checkpoint production-evidence envelopes,
  record periodic self-review checkpoints, record `manual_gap` artifacts,
  record configured blockers with issue/failure classification, complete
  stages, move to the next pending stage, and print the durable snapshot. This
  makes the supervisor harness usable from long `/goal` scripts without making
  it a lane status authority or live 8 hour proof.
- The supervisor snapshot now persists `self_reviews` as
  `xmuse.overnight_self_review.v1` rows and emits matching
  `xmuse.production_evidence.v1` envelopes with `action=self_review`,
  `kind=self_review`, `configured=true`, and `required=true`. The deterministic
  SLO marker treats review intervals over 60 minutes as `violated`; it remains
  contract-level evidence unless attached to fresh live/provider/server
  artifacts.
- The `blocked-fallback` command records a configured blocker as
  `status=blocked` with `proof_level=manual_gap`, creates an issue queue row,
  records a failure classification, writes an `xmuse.stage_fallback.v1`
  artifact, and can start the next pending independent stage. This preserves
  release blockers while allowing the overnight run to keep useful momentum.
- Repeated failure classification now escalates to refactor policy. On the
  third matching failure for the same stage and failure class, the supervisor
  marks the stage blocked, writes a `refactor_required` issue queue row, and
  emits `failure_refactor_escalation` production evidence with the next action
  to refactor the failing boundary before retrying.
- Supervisor stages can now carry priority and dependency metadata. The Python
  API accepts `OvernightSupervisorStage(priority=..., depends_on=(...))`, and
  the CLI accepts `--stage-priority STAGE=INT` plus
  `--stage-depends-on STAGE=DEP1,DEP2`. When a fallback blocks a stage, the
  supervisor skips pending stages whose dependencies are blocked or not yet
  complete, journals `stage_selection_skipped` /
  `stage_selection_waiting`, and starts the highest-priority ready independent
  stage instead of blindly starting the next declaration.
- The supervisor now has a deterministic virtual-time soak path through
  `OvernightSupervisor.simulate_virtual_soak(...)` and
  `uv run xmuse-overnight-supervisor simulate`. A CI/local run can compress
  8 hours into logical minutes, emit heartbeat/checkpoint/self-review rows with
  `logical_minute`, inject configured blockers, verify heartbeat and
  self-review SLOs, and continue to the next pending stage without sleeping or
  using live credentials.
- The same supervisor can import `scripts/goal_stage_runner.py` outputs through
  `OvernightSupervisor.import_goal_stage_result(...)` and
  `uv run xmuse-overnight-supervisor --resume import-stage-result RESULT.json`.
  This closes the local handoff between the stage harness and the overnight
  snapshot: prompt/manifest/result/engine-output paths become replayable
  supervisor evidence, while non-`ok` stage results remain blockers or retry
  requests and do not become lane status, review truth, GitHub truth, release
  readiness proof, or live runtime proof. Repeated imported retry results for
  the same stage now escalate through `goal_stage_retry` to
  `refactor_required` on the third occurrence.
- `.github/workflows/xmuse-ci.yml` includes
  `tests/xmuse/test_overnight_operator_supervisor.py` in the contract smoke
  gate, so the no-secrets virtual soak state machine is exercised by CI.
- `uv run xmuse-overnight-supervisor-evidence-capture` still performs the
  explicit conversion from the durable supervisor snapshot into replay-ready
  `xmuse.production_evidence.v1` for the replay bundle's `supervisor` section.

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
- Attempt `xmuse-memoryos-live-trace-capture` for the current namespace. When
  live MemoryOS is unconfigured, the command still writes a blocked
  `xmuse.memoryos_lite_trace.v1` `manual_gap` artifact so replay can cite the
  exact missing prerequisite instead of omitting the section input.

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
  artifacts. It fills unattached required sections, including `stage_evidence`,
  with `manual_gap` instead of omitting them, so an overnight run can be
  replayed without prose-only gaps.
- `uv run xmuse-release-evidence-pack` now writes the same overnight replay
  bundle as a nested `replay_index_only` source report alongside release
  readiness and proof-contamination reports. Section artifacts and tombstoned
  source refs can be supplied through the pack command, but the pack remains an
  aggregation surface and does not upgrade release or replay proof.
- `uv run xmuse-release-evidence-pack --supervisor-snapshot <snapshot>` now
  converts an `xmuse.overnight_supervisor.v1` snapshot into replay-ready
  supervisor production evidence before assembling the nested replay bundle.
  This reduces handoff friction after a long `/goal` run while keeping the
  snapshot conversion explicit and contract-level.
- `uv run xmuse-release-evidence-pack --memoryos-governance-plan <plan>` and
  `--memoryos-writeback-event <event>` now convert governed MemoryOS policy
  inputs into replay-ready `memory_governance` production evidence before
  assembling the nested replay bundle. This reduces handoff friction after
  governed writeback events while keeping MemoryOS governance separate from
  live MemoryOS trace proof.
- `uv run xmuse-release-evidence-pack --deliberation-transcript <transcript>`
  and `--god-runtime <runtime>` now convert an
  `xmuse.operator_transcript.v1` artifact into replay-ready
  `deliberation_transcript` production evidence before assembling the nested
  replay bundle. Missing selected-GOD runtime continuity remains
  blocked/manual-gap evidence. The conversion reuses the natural deliberation
  release-gate rules, so deterministic replay, single-GOD transcripts, missing
  provider session metadata, bounded selected runtime, or unresolved blockers
  remain weak/blocked evidence.
- `uv run xmuse-release-evidence-pack --frozen-blueprint <blueprint>` now
  converts a `mission_blueprint.v1` artifact into replay-ready
  `frozen_blueprint` production evidence before assembling the nested replay
  bundle. Draft or otherwise unfrozen blueprints remain `manual_gap`, so the
  pack cannot turn readiness or a rendered blueprint into freeze proof.
- `uv run xmuse-frozen-blueprint-export` now exports a
  `mission_blueprint.v1` artifact from durable `chat.db` resolution authority.
  It accepts either an explicit approved freeze resolution id or the latest
  frozen blueprint for a conversation, and rejects non-`deliberation_freeze`
  approvals, non-blueprint content, or non-frozen blueprint status.
- `uv run xmuse-release-evidence-pack --feature-contract <contract>` now
  converts serialized `xmuse.feature_owner_execution_contract.v2` artifacts
  into replay-ready `feature_lineage` production evidence before assembling the
  nested replay bundle. Missing, invalid, opaque blocked-lane, or
  projection-authority contracts remain `manual_gap`; graph-native feature
  owner contracts stay the authority.
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
- `uv run xmuse-deliberation-transcript-evidence-capture` exports an
  `xmuse.operator_transcript.v1` artifact into replay-ready
  `xmuse.production_evidence.v1` for the `deliberation_transcript` section. It
  reuses the natural deliberation release-gate rules, so deterministic replay,
  single-GOD transcripts, missing provider session metadata, bounded selected
  runtime, or unresolved blockers cannot be upgraded by replay indexing.
- `uv run xmuse-feature-owner-contract-export` exports serialized
  `xmuse.feature_owner_execution_contract.v2` artifacts directly from graph-set
  JSON authority. It does not read `feature_lanes.json`, does not write lane
  status, and requires allowed-file evidence from graph-set
  `expected_touched_areas` or explicit `--allowed-file` arguments.
- `uv run xmuse-feature-lineage-evidence-capture` exports serialized
  `xmuse.feature_owner_execution_contract.v2` artifacts into replay-ready
  `xmuse.production_evidence.v1` for the `feature_lineage` section. It keeps
  feature owner and graph-native ready-set contracts as authority, preserves
  lane lineage refs, and leaves missing or rejected contracts as `manual_gap`.
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
- Require internal review artifacts to declare `review_scope=full_pr_current_head`;
  latest-commit or partial-scope reviews are useful evidence but cannot satisfy
  the release gate.
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
- `uv run xmuse-live-gate-status-capture` can also receive the GitHub target
  explicitly through `--github-repo`, `--github-pull-request`,
  `--github-base-branch`, repeated `--github-required-check`, and
  `--github-expected-head-sha`. These flags only populate the same
  `XMUSE_GITHUB_TRUTH_*` capture inputs for this invocation; they do not create
  review truth, merge truth, or `pr_merged`.
- TUI `/release export github repo=<owner/repo> pr=<number>
  expected_head=<sha>` calls the audited `export_github_server_truth` operator
  action. It performs the same read-only GitHub capture, writes a raw snapshot
  and `github-server-truth` gate under the release readiness root, and preserves
  `can_emit_pr_merged=false` unless full server-side merge proof exists.
- `/release attempt github` and `/release attempt all` include GitHub server
  truth in the attempt report. Missing repo/PR target fields become
  `manual_gap` blockers; present targets invoke the same read-only export path.
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
- Use `uv run xmuse-frozen-blueprint-export --chat-db ... --conversation-id ...`
  or `--resolution-id ...` to export the frozen `mission_blueprint.v1` artifact
  from durable chat resolution authority.
- Use `uv run xmuse-frozen-blueprint-evidence-capture --blueprint ...` to turn
  a frozen mission blueprint artifact into explicit replay section evidence.
- Use `uv run xmuse-deliberation-transcript-evidence-capture --transcript ...`
  to turn an exported operator transcript into explicit deliberation transcript
  replay section evidence.
- Use `uv run xmuse-feature-lineage-evidence-capture --contract ...` to turn
  feature owner execution contracts into explicit feature/lane lineage replay
  section evidence.
- Use `uv run xmuse-overnight-replay-bundle-capture` to assemble the replay
  index from release gate artifacts and attached section evidence.
- Or use `uv run xmuse-release-evidence-pack --section-artifact SECTION=PATH`
  to produce the release-readiness, proof-contamination, and overnight replay
  reports in one operator handoff pack.
- When goal-stage runner results exist, prefer
  `uv run xmuse-release-evidence-pack --goal-stage-result RESULT.json` for the
  final handoff pack; do not pass it together with an explicit
  `--section-artifact stage_evidence=...`.
- When a supervisor snapshot exists, prefer
  `uv run xmuse-release-evidence-pack --supervisor-snapshot SNAPSHOT` for the
  final handoff pack; do not pass both `--supervisor-snapshot` and an explicit
  `--section-artifact supervisor=...`.
- When a natural transcript and selected GOD runtime continuity artifact exist,
  produce the runtime artifact with
  `uv run xmuse-god-runtime-continuity-capture --conversation-id <id>` against
  the durable stores for that same conversation, then
  prefer `uv run xmuse-release-evidence-pack --deliberation-transcript TRANSCRIPT`
  plus `--god-runtime RUNTIME` for the final handoff pack; do not pass those
  inputs together with an explicit
  `--section-artifact deliberation_transcript=...`.
- When using the TUI/operator export path, `/release export natural
  target_ref=blueprint:<id> ttl=<seconds>` already captures the default
  selected-GOD runtime artifact under the release readiness root and passes it
  to the natural gate. Use `god_runtime=skip` only for compatibility tests, not
  for production release evidence.
- `/release candidates` now exposes natural transcript readiness and
  selected-GOD runtime readiness separately. Its natural `export_ready` requires
  both, so missing selected runtime continuity, transcript GODs absent from the
  selected runtime view, stale heartbeats, or bounded/non-peer GOD sessions are
  visible before `/release attempt natural` starts. The TUI operator result
  prints compact candidate lines for natural transcript/runtime readiness,
  provider readiness, MemoryOS readiness, and selected-GOD runtime blockers
  without writing durable state.
- When the same natural transcript should participate in release readiness,
  also pass `--natural-deliberation-transcript TRANSCRIPT` plus
  `--natural-deliberation-god-runtime RUNTIME`. This writes
  `natural-deliberation.json` under `--artifacts-dir` through the same natural
  gate validator, and it requires selected-GOD runtime continuity so bounded
  workers cannot satisfy the release gate.
- When governed MemoryOS write plans or writeback events exist, prefer
  `uv run xmuse-release-evidence-pack --memoryos-governance-plan PLAN` or
  `--memoryos-writeback-event EVENT` for the final handoff pack; do not pass
  those inputs together with an explicit
  `--section-artifact memory_governance=...`.
- When a live MemoryOS Lite trace artifact exists, prefer
  `uv run xmuse-release-evidence-pack --memoryos-live-trace TRACE` for the final
  handoff pack. The pack writes `live-memoryos.json` under `--artifacts-dir`
  through the same live gate validator and blocks contract/fake/empty traces.
- When a real provider runtime artifact exists, prefer
  `uv run xmuse-release-evidence-pack --real-provider-runtime RUNTIME` for the
  final handoff pack. The pack writes `real-provider-runtime.json` under
  `--artifacts-dir` through the same real-provider gate validator and blocks
  fake/local/stdout fallback artifacts.
- When a raw GitHub server truth snapshot exists, prefer
  `uv run xmuse-release-evidence-pack --github-server-truth SNAPSHOT --github-expected-head-sha HEAD`
  for the final handoff pack. The pack writes `github-server-truth.json` under
  `--artifacts-dir` through the same GitHub server-truth gate builder, but it
  does not call GitHub itself. A stale head remains `manual_gap`, and
  `server_side_enforcement_proof` still does not create review truth, merge
  truth, or `pr_merged`.
- When a structured internal review artifact exists for the current head,
  prefer
  `uv run xmuse-release-evidence-pack --internal-review-artifact REVIEW --internal-review-expected-head-sha HEAD`
  for the final handoff pack. The pack writes `internal-review.json` under
  `--artifacts-dir` through the same internal review gate validator. This can
  satisfy the `internal_review` release gate as `internal_review_proof`, but it
  does not create GitHub server-side review enforcement or merge truth.
- If the structured current-head review artifact is still missing, pass
  `--internal-review-expected-head-sha HEAD` without
  `--internal-review-artifact` to make the pack write a blocked
  `internal-review` `manual_gap` gate instead of omitting the review gap.
- When a frozen mission blueprint artifact exists, prefer
  `uv run xmuse-release-evidence-pack --frozen-blueprint BLUEPRINT` for the
  final handoff pack; do not pass it together with an explicit
  `--section-artifact frozen_blueprint=...`.
- When feature owner execution contract artifacts exist, prefer repeated
  `--feature-contract CONTRACT` inputs on `uv run xmuse-release-evidence-pack`
  for the final handoff pack; do not pass them together with an explicit
  `--section-artifact feature_lineage=...`.
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
