# Vision Production Evidence-Control Closure Plan

> **For agentic workers:** This is a production-grade `/goal` handoff. Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`
> task-by-task. This plan is not a demo plan and must not treat contract-only
> evidence as production runtime proof.

**Goal:** Turn xmuse from a contract-rich operator loop into a production-grade
autonomous development platform where GOD/CLI participants can be registered and
selected, the TUI can operate the full workflow through authorized contracts,
and live MemoryOS/GitHub/provider gates participate in release readiness.

**Architecture:** Durable authority remains in chat/envelope stores, GOD
session records, frozen blueprint revisions, graph sets, review artifacts,
MemoryOS REST evidence, provider runtime manifests, and GitHub server truth.
TUI/dashboard are no longer read-only in product intent, but every mutating
operation must call an authenticated contract/API action; they must never write
projection files or internal state directly.

**Tech Stack:** Python, Textual, FastAPI, xmuse_core contracts, provider/GOD
registry, MemoryOS Lite REST compatibility, GitHub CLI/API evidence capture,
Ray/Codex/OpenCode runtime probes, MCP permissions, pytest, ruff, uv.

---

Updated: 2026-06-12

Source report:

```text
C:\tmp\deep-research-report_09.md
/mnt/c/tmp/deep-research-report_09.md
```

Short `/goal` prompt:

```text
docs/xmuse/vision-production-evidence-control-closure-goal-prompt.md
```

## Confirmed Product Decisions

The operator confirmed these decisions before this plan was written:

- OpenCode stays bounded for this implementation round, but the final product
  must let the user manually register and choose which CLI can act as a GOD.
- TUI is the xmuse user interaction surface and must support full workflow
  operation, not just read-only observation.
- Commit, push, and draft PR creation are allowed after validation. Automatic
  merge is not allowed without separate explicit authorization.
- Currently configured live environments should be used. If a configured live
  gate fails, treat it as a release blocker, not as a cosmetic gap.
- Verified internal review artifact may count as internal review truth for a
  single-maintainer workflow, but it must not be mislabeled as GitHub
  server-side enforcement.
- Existing MemoryOS retention/tombstone direction stays in force.
- Auth/RBAC should move toward production implementation in this round.
- Live gates should be promoted toward release gating. Fake/local paths remain
  useful for tests but are not release proof.

## Production Meaning

For this plan, "production-grade" means:

- mutating actions are authenticated, authorized, audited, and idempotent;
- TUI can operate the product through official actions, not by editing
  projections or runtime state files;
- provider/GOD registration is explicit, capability-scoped, and visible to the
  operator;
- live MemoryOS, GitHub, and provider/Ray gates are attempted when configured;
- release readiness requires live/server/provider evidence or a named blocker;
- every proof label is honest and cannot be escalated by local files;
- runtime state remains ignored and is not committed.

## Non-Goals

- Do not rebuild a browser frontend.
- Do not claim full peer-GOD status for OpenCode or any CLI until registration,
  capability, persistence, writeback, review, and GitHub truth evidence exist.
- Do not let TUI, dashboard cards, `feature_lanes.json`, Ray actors, or provider
  subprocesses become durable authority.
- Do not bypass Chat API/MCP/API contracts for mutations.
- Do not weaken GitHub merge truth. `pr_merged` still requires server-side merge
  proof.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- Do not create `xmuse/__init__.py`.

## Proof Vocabulary

Use these labels consistently:

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

## Stage Budget

Treat this as tonight's 8 hour production closure run. If a stage is blocked by
a configured live dependency, record the blocker and owner, then continue only
to independent stages. Do not silently downgrade production gates to demo paths.
If a stage cannot be completed within the 8 hour target, land the strongest
validated production slice and record the next production slice explicitly.

| Window | Stage | Expected output |
| --- | --- | --- |
| 0:00-0:30 | S0 Production baseline | Env, branch, current proof state, configured live resources, and dirty state recorded. |
| 0:30-1:30 | S1 GOD/CLI registry | Manual GOD CLI registration and selection contract advanced with tests. |
| 1:30-2:45 | S2 TUI full-control actions | Mutating TUI actions go through authorized action contracts, not projection writes. |
| 2:45-3:45 | S3 Auth/RBAC production gate | Operator/session capability and audit enforcement for write surfaces. |
| 3:45-5:00 | S4 Live evidence gates | MemoryOS, GitHub, Ray/Codex/OpenCode gates attempted using configured environment. |
| 5:00-6:00 | S5 Natural GOD transcript path | Natural transcript boundary tied to selected GOD CLI participants and freeze rules. |
| 6:00-7:15 | S6 Release readiness | Release gate aggregates live/server/provider/internal review evidence. |
| 7:15-8:00 | S7 Validation, docs, PR prep | Focused tests, ruff, diff check, walkthrough, commit/push/draft PR when green. |

## S0 - Production Baseline

Goal: establish the real production starting point before behavior changes.

Tasks:

- [ ] Read `AGENTS.md`, `docs/xmuse/README.md`,
  `docs/xmuse/mainline-contracts.md`,
  `docs/xmuse/provider-matrix.md`,
  `docs/xmuse/memoryos-governance-contract.md`,
  `docs/xmuse/mcp-permission-model.md`,
  `docs/xmuse/production-operations.md`,
  `docs/xmuse/vision-operator-closed-overnight-loop-walkthrough.md`, and this
  plan.
- [ ] Run `git status --short --branch` and preserve unrelated worktree
  changes.
- [ ] Confirm `xmuse/__init__.py` is absent.
- [ ] Inventory configured live resources: MemoryOS Lite URL/flags, GitHub auth,
  Ray/Codex runtime, OpenCode/DeepSeek env, MCP/Chat API ports.
- [ ] Record which configured live gates are available, unavailable, or
  failing.

Acceptance:

- No production gate is silently skipped.
- Missing or failing configured resources have owner and next action.
- Runtime state remains untracked.

Current implementation status:

- `uv run xmuse-production-baseline-capture` writes a redacted
  `xmuse.production_baseline.v1` S0 truth-map artifact, defaulting to
  `xmuse/work/release_readiness/production-baseline.json`.
- The artifact records git branch/head/dirty state, `xmuse/__init__.py`
  absence, known production env key presence, and probes for GitHub auth,
  Codex, OpenCode, and Ray import visibility.
- It inventories MemoryOS Lite, GitHub truth target, provider runtime, natural
  GOD deliberation, Chat API auth, and MCP auth readiness with blocker ids,
  owner, and next action. Secret-like env values and probe output are redacted.
- This is S0 `contract_proof` only. It does not call live MemoryOS, does not
  run providers, does not collect GitHub server truth, and does not satisfy
  release readiness. Configured-but-uncaptured live inputs remain
  `manual_gap` blockers for S4/S6.

## S1 - GOD/CLI Registry And Selection

Goal: make GOD participant selection explicit and product-ready.

Tasks:

- [x] Add or extend a GOD/CLI registry contract in `src/xmuse_core/providers/`
  that records CLI id, display name, command family, provider profile,
  capabilities, allowed speech acts, persistence support, MCP/writeback support,
  proof refs, registration source, and proof level.
- [x] Keep current OpenCode behavior bounded unless evidence proves peer-GOD
  parity. For this round, OpenCode may be selectable only under bounded
  capability labels unless production proof exists.
- [x] Add TUI/provider-board read model support for registered GOD CLI choices.
- [x] Add tests that reject unregistered or capability-incompatible GOD choices.

Acceptance:

- Operator can see which CLI can be chosen as GOD and why.
- GOD selection cannot bypass capability policy.
- OpenCode is not upgraded by assertion.

Current implementation status:

- `GodCliRegistration` now carries `proof_refs`; manual `peer_god`
  registration requires `real_provider_proof`, proof refs, persistent sessions,
  MCP writeback, and state-write permission.
- `GodCliRegistrationStore` writes ignored runtime state to
  `god_cli_registrations.json` with operator audit metadata. This is the
  durable manual registration store for CLI choices, not release proof.
- `register_god_cli` is an operator action requiring `register_god_cli`
  capability. It records an audit row and persists the manual registration
  through the store.
- `select_god_cli` selects from the effective registry: built-ins plus durable
  manual registrations. Selection still requires `peer_god` capability.
- TUI `/god register <key=value...>` and `/god select <cli_id>` route through
  the Chat API operator action endpoint first, then local contract fallback only
  when Chat API is unavailable.
- Provider Board merges manual GOD CLI registrations into its projection with
  `manual_gap` heartbeat and `registration_kind=manual`.
- This status does not create live provider proof. `proof_refs` are recorded
  references supplied by an authorized operator; release readiness still needs
  independent real-provider runtime gate artifacts.

## S2 - TUI Full-Control Action Surface

Goal: make TUI the real xmuse operation surface while keeping authority in
contracts and durable stores.

Tasks:

- [ ] Define an operator action contract for mutating workflow operations:
  create conversation, register/select GOD, request blueprint freeze,
  approve/reject freeze, enqueue/retry/abort lane, patch-forward, refresh live
  evidence, request review, prepare PR, and capture release gate.
- [ ] Route TUI commands through Chat API/MCP/platform action handlers with
  idempotency keys and audit records.
- [ ] Ensure TUI never edits `feature_lanes.json`, graph stores, review records,
  MemoryOS bindings, or GitHub truth files directly.
- [ ] Display source authority, proof level, audit id, and result state for each
  action.

Acceptance:

- TUI can perform at least one production mutating action through an authorized
  contract path.
- Projection-only writes are rejected in tests.
- Failed actions return precise blocked/manual_gap/operator-denied states.

Current implementation status:

- `/god register <key=value...>` routes manual GOD CLI registration through the
  Chat API operator action endpoint first, then local contract fallback only
  when Chat API is unavailable. It requires `register_god_cli` and does not
  write provider board/read-model state directly.
- `/god select <cli_id>` routes GOD CLI selection through the Chat API operator
  action endpoint first, then the same local contract service only when Chat API
  is unavailable.
- `/release refresh` routes live-gate status capture through the same operator
  action path. It requires `release_gate`, writes audit evidence, and emits
  honest `manual_gap`/blocked status artifacts without satisfying live gates.
- `/release pack` routes release evidence pack capture through the same
  operator action path. It requires `release_gate`, writes audit evidence, and
  only permits paths under `xmuse/work/release_readiness`. It can attach a
  `baseline=...` / `production_baseline=...` S0 truth-map artifact to the pack
  summary without turning that baseline into a release gate or readiness proof.
- `/release export github repo=<owner/repo> pr=<number> expected_head=<sha>`
  routes fresh GitHub server-truth capture through the same operator action
  path. It requires `release_gate`, writes a raw read-only GitHub snapshot plus
  `github-server-truth` release gate under `xmuse/work/release_readiness`, and
  does not create review truth, merge truth, or `pr_merged`.
- `/lane retry <lane_id> <current_status> [reason]` and
  `/lane abort <lane_id> <current_status> [reason]` route guarded lane control
  through the same operator action path. They require `workflow_write`, require
  current-status guard input, stamp mutation audit metadata, and use
  `LaneStateMachine` transition rules.
- `/freeze target_ref=<ref> blueprint_id=<id> goal=<goal> scope=<items>
  acceptance=<items>` routes blueprint freeze through the same operator action
  path. It requires `chat_freeze_blueprint`, calls the existing deliberation
  freeze contract, writes the same durable mission blueprint resolution, and
  leaves unresolved blocking objections as blockers.
- TUI command events record `operator_action_contract` as their read-surface
  authority. They do not write projections or release facts directly.
- Ordinary TUI Chat API write methods now forward the production operator auth
  envelope from `XMUSE_CHAT_API_KEY`, `XMUSE_TUI_OPERATOR_ID`,
  `XMUSE_TUI_OPERATOR_ROLE`, and `XMUSE_TUI_OPERATOR_CAPABILITIES`. Covered
  write paths are message post, group conversation creation, bootstrap proposal
  create/apply, proposal approval, and participant add/remove.

## S3 - Auth/RBAC Production Gate

Goal: move write surfaces from declarative permission categories toward
production enforcement.

Recommended model:

```text
operator identity
-> session-scoped capability
-> signed/idempotent action request
-> audit log
-> contract handler
-> durable authority write
```

Tasks:

- [ ] Add an operator capability model for write/admin actions.
- [ ] Enforce deny-by-default for Chat API/MCP write routes unless capability
  and audit requirements are satisfied.
- [ ] Keep read-only routes available under existing local trust assumptions
  until broader API auth is fully wired.
- [ ] Add negative tests for unauthenticated or capability-mismatched writes.
- [ ] Add positive tests for a signed/operator-scoped write action.

Acceptance:

- Write surfaces are not open by default.
- Every production write produces an audit trail.
- Existing GOD identity checks remain in force and are not confused with API
  authentication.

Current implementation status:

- Chat API mutating routes have opt-in token plus role/capability gating through
  `XMUSE_CHAT_API_AUTH_TOKEN` / `XMUSE_CHAT_API_KEY`.
- MCP mutating `tools/call` routes have opt-in token plus role/capability
  gating through `XMUSE_MCP_AUTH_TOKEN` / `XMUSE_MCP_API_KEY`.
- TUI no longer treats only operator actions as authenticated writes. Its direct
  Chat API write calls use the same `X-XMUSE-API-Key`,
  `X-XMuse-Operator-Id`, `X-XMuse-Operator-Role`, and
  `X-XMuse-Operator-Capabilities` headers when auth is configured. The TUI
  forwards configured capabilities; it does not fabricate route authorization.
- Workflow write operator actions use `workflow_write` capability and require
  state guards. The first implemented actions are `retry_lane` and
  `abort_lane`; mismatched guards are blocked and leave lane state unchanged.
- `XMUSE_DEPLOYMENT_PROFILE=production` makes Chat API and MCP startup fail
  closed when write auth tokens are missing.
- Read-only HTTP/MCP routes still follow the local trust policy.
- Remaining production hardening is live-service proof that the configured
  production processes were started with the token bundle and exercised by a
  real operator/TUI session.

## S4 - Live Evidence Gates

Goal: promote configured live gates from optional smoke to release-readiness
evidence.

Targets:

- MemoryOS Lite REST trace and continuity.
- GitHub branch protection/rulesets/checks/review/merge truth.
- Ray/Codex GOD session health and MCP writeback.
- OpenCode health and bounded execution/deliberation evidence.

Tasks:

- [ ] Detect configured live resources in S0 and attempt each configured gate.
- [ ] Emit `live_service_proof`, `server_side_enforcement_proof`,
  `server_side_merge_proof`, or `real_provider_proof` only from captured live
  evidence.
- [ ] Mark configured live gate failures as release blockers with owner and next
  action.
- [ ] Keep fake/local tests for default CI, but exclude them from release proof.

Acceptance:

- Release gate output distinguishes fake/local, live service, server-side, real
  provider, and manual gap evidence.
- A configured failing live gate blocks release readiness.
- No credential or runtime state is committed.

Current implementation status:

- `uv run xmuse-live-gate-status-capture` writes required live-gate status
  artifacts for MemoryOS, GitHub server truth, provider runtime, and natural
  GOD deliberation.
- The command records configured/missing state and blocker next actions without
  writing secret values.
- `uv run xmuse-memoryos-live-trace-capture` runs the explicit opt-in
  MemoryOS Lite REST capture path: namespace/session binding, ingest,
  build-context, trace fetch, and `xmuse.memoryos_lite_trace.v1` artifact
  writing. It does not import `memoryos_lite` and it writes `manual_gap` when
  the live environment is unconfigured or trace evidence is unavailable.
- It emits `manual_gap` proof for uncaptured gates. When
  `XMUSE_GITHUB_TRUTH_REPO` and `XMUSE_GITHUB_TRUTH_PULL_REQUEST` are set, it
  runs the opt-in read-only GitHub server truth collector and can write a
  `github_server_truth` gate with `server_side_enforcement_proof`; it still
  cannot create review truth, merge truth, or `pr_merged`.
- The same GitHub target can be supplied per invocation with
  `--github-repo`, `--github-pull-request`, `--github-base-branch`, repeated
  `--github-required-check`, and `--github-expected-head-sha`; these flags only
  populate the capture input and do not weaken merge/review truth semantics.
- A captured raw `github_server_side_truth_capture.v1` snapshot can also be
  handed to `uv run xmuse-release-evidence-pack --github-server-truth SNAPSHOT`
  with `--github-expected-head-sha HEAD`. The pack only converts the explicit
  snapshot through the same GitHub server-truth gate builder; it does not call
  GitHub and stale snapshots remain `manual_gap`.
- `export_github_server_truth` is the audited operator-action/TUI path for the
  same fresh read-only capture. It writes
  `github-server-truth-snapshot.json` and
  `artifacts/github-server-truth.json` under the release readiness root and
  preserves `can_emit_pr_merged=false` until server-side merge proof exists.
- When `XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT`,
  `XMUSE_NATURAL_GOD_TRANSCRIPT_PATH`,
  `XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT`, or
  `XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT` point at existing artifacts, it
  validates and converts them through the same release-gate contracts as the
  standalone gate capture commands. Natural deliberation conversion requires
  both transcript and selected-GOD runtime continuity artifacts. Missing,
  invalid, fake/local, blocked, or stale artifacts remain blockers.
- `xmuse-live-gate-status-capture` does not create live MemoryOS, real
  provider, or natural transcript proof by itself; it converts supplied
  artifacts and writes blocker status for missing proof.
- `uv run xmuse-real-provider-runtime-gate-capture` converts an explicit
  `xmuse.real_provider_runtime.v1` soak artifact into the `real_provider`
  release gate. It requires `real_provider_proof`, MCP writeback, real
  non-fake transport/backend metadata, ordered stage timings, and
  restart/resume provider-session reuse.
  The gate artifact also carries a read-only `real_provider_runtime` detail
  projection with provider id, runtime backend, transport, provider session id,
  MCP writeback, restart/resume, turn phases, degraded-turn count, and blocker
  count. This detail is for replay/TUI auditability only; it does not replace
  the release gate status/proof-level checks.
- `uv run xmuse-memoryos-live-gate-capture` converts an explicit
  `xmuse.memoryos_lite_trace.v1` artifact into the `live_memoryos` release gate.
  It requires `live_service_proof`, a `memory://` namespace, session id,
  non-empty trace events, source refs, and no unresolved blockers.
  The gate artifact carries read-only `memoryos_trace` details for namespace,
  session id, trace-event count, event kinds, estimated tokens, source-ref
  count, blocker count, and live-service proof flag. Replay bundles preserve
  those details for the proof cockpit without replacing the live gate.

## S5 - Natural GOD Transcript And Freeze Path

Goal: connect selected GOD participants to a real natural deliberation path
without weakening freeze rules.

Tasks:

- [x] Export natural transcript evidence only when real GOD/CLI participants
  produced the conversation.
- [x] Preserve speech acts, source refs, target refs, blockers, participant CLI,
  provider profile, session id, and proof level.
- [x] Keep deterministic replay labeled as `contract_proof`.
- [x] Ensure unresolved blocking objections prevent freeze.
- [x] Route freeze approval through the production TUI/action contract when
  implemented.

Acceptance:

- Natural transcript evidence is visibly separate from deterministic replay.
- Freeze cannot be completed from unresolved blockers or local-only proof.
- Transcript evidence links to blueprint, feature, and lane refs.

Current implementation status:

- `uv run xmuse-natural-deliberation-transcript-capture` exports
  `xmuse.operator_transcript.v1` from durable `chat.db` and `god_sessions.json`.
  It only accepts `god_speech_act` envelopes from assistant GOD participants,
  links provider/profile/session metadata, and keeps deterministic
  `deliberation` replay as `manual_gap`.
- `uv run xmuse-natural-deliberation-gate-capture` converts an
  `xmuse.operator_transcript.v1` artifact into a `natural_deliberation` release
  gate. It emits `real_provider_proof` only for explicit natural, real-provider,
  multi-GOD transcript evidence with provider session metadata.
- Deterministic replay, single-GOD transcript evidence, missing provider session
  metadata, and unresolved blockers remain blocked and cannot satisfy release
  readiness.
- `freeze_blueprint` is now an audited operator action. Chat API injects the
  existing `/api/chat/conversations/{id}/freeze-blueprint` contract as the
  freeze handler, TUI `/freeze` routes through `run_operator_control_action`,
  and local fallback without a handler blocks instead of bypassing Chat API.

## S6 - Release Readiness Gate

Goal: create one release-readiness decision surface for operator review.

Required inputs:

- focused test results;
- ruff/diff-check results;
- package boundary status;
- TUI action audit records;
- internal review artifact;
- live MemoryOS evidence or blocker;
- GitHub server truth evidence or blocker;
- real provider/Ray/Codex/OpenCode evidence or blocker;
- proof contamination audit.

Current implementation status:

- `uv run xmuse-live-gate-status-capture` can pre-populate live gate blocker
  artifacts that the readiness capture command will evaluate. With explicit
  `XMUSE_GITHUB_TRUTH_*` target configuration, the same command also captures
  GitHub server enforcement truth through the read-only collector. With
  explicit live artifact path configuration, it also validates and converts
  MemoryOS, natural deliberation, and real-provider runtime artifacts through
  their existing gate builders.
- The `refresh_live_gate_status` operator action now returns `gate_statuses`,
  `blockers`, and `release_decision` derived from those generated release gate
  artifacts. TUI `/release refresh` renders the summary without reading or
  mutating release state directly.
- TUI `/release export natural|provider|memoryos|github` now routes through the
  audited operator action contract with `release_gate`. The matching
  `export_natural_deliberation_transcript`,
  `export_real_provider_runtime_soak`, `export_memoryos_live_trace`, and
  `export_github_server_truth` actions write both raw evidence artifacts and
  release gate artifacts under `xmuse/work/release_readiness`; weak inputs
  remain blocked/manual-gap proof. MemoryOS export writes the blocked
  `xmuse.memoryos_lite_trace.v1` manual-gap trace when the live REST environment
  is unconfigured, so release replay keeps an explicit missing-prerequisite
  input. GitHub export captures read-only server truth and may satisfy
  `server_side_enforcement_proof`, but it still cannot synthesize review truth,
  merge truth, or `pr_merged`.
- TUI `/release candidates` now routes through
  `inspect_release_evidence_candidates` with `release_gate`, reads durable
  chat/session/GOD selection/GOD registration/peer-latency state plus redacted
  MemoryOS env presence, and reports which export inputs are ready or missing
  before an operator attempts a live evidence capture. Natural candidates now
  expose transcript readiness and selected-GOD runtime readiness separately;
  combined natural `export_ready` requires both, so missing selected runtime
  continuity is visible before `/release attempt natural`. Natural candidates
  also include `proof_boundary=candidate_report_is_not_natural_deliberation_proof`,
  required transcript/runtime schemas, required `real_provider_proof`, source
  authority, and the suggested `attempt_release_evidence` operator action.
  This makes the next action visible without treating transcript readiness,
  selected-runtime readiness, or TUI rendering as natural release proof.
  Real-provider candidates now include
  `proof_boundary=candidate_report_is_not_release_proof`, the required
  `xmuse.real_provider_runtime.v1` schema, required `real_provider_proof`,
  source authority, and the suggested `attempt_release_evidence` operator
  action payload hints. This makes the next action visible without treating
  peer-latency traces, provider inventory, or TUI rendering as release proof.
  Live-MemoryOS candidates similarly include
  `proof_boundary=candidate_report_is_not_live_memoryos_proof`, required schema
  `xmuse.memoryos_lite_trace.v1`, required proof `live_service_proof`,
  redacted source authority, and `attempt_release_evidence` hints without
  leaking env values or task content/query text into the candidate report.
  GitHub server-truth candidates include
  `proof_boundary=candidate_report_is_not_github_server_truth_proof`, required
  gate kind `github_server_truth`, required `server_side_enforcement_proof`,
  source authority, and the suggested `attempt_release_evidence` payload hints
  for repo, PR number, optional expected head, base branch, and required checks.
  This makes the next action visible without calling GitHub, writing a
  server-truth artifact, or treating candidate readiness as `pr_merged`.
- TUI `/release attempt [natural|provider|memoryos|github|all]` now routes through
  `attempt_release_evidence` with `release_gate`. The action writes a
  `release-evidence-attempt.json` attempt report under
  `xmuse/work/release_readiness`, reuses the durable candidate report, and calls
  the existing export actions only for export-ready inputs. Not-ready natural
  GOD transcripts, missing peer latency traces, missing MemoryOS live
  configuration, missing GitHub target fields, missing runtime metadata,
  fake/local labels, and blocked live captures remain blocked `manual_gap`
  rows and do not satisfy release readiness. When the GitHub target is present,
  the attempt action invokes `export_github_server_truth` and records the
  resulting gate status without converting it into merge truth.
  Blocked attempt rows now carry candidate `next_action` guidance, and the TUI
  renders compact `attempt[kind]=blocked next=... blockers=...` lines. This
  improves operator recovery without changing the attempt proof level or gate
  status.
- `uv run python scripts/github_server_truth_capture.py --release-gate-output`
  can write a `github_server_truth` release gate artifact from the raw GitHub
  server truth snapshot. This can satisfy `server_side_enforcement_proof`
  without weakening `pr_merged`, which still requires merge truth.
- `uv run xmuse-internal-review-gate-capture` converts an approved
  `xmuse.internal_review.v1` artifact for the current head SHA into an
  `internal_review_proof` release gate only when it declares
  `review_scope=full_pr_current_head`. It blocks mismatched heads, missing or
  partial review scope, and open critical/important findings.
- GitHub truth capture reuses the same structured internal review validation
  before treating an internal review artifact as `review_truth`; a file that
  merely exists, stale head evidence, reviewer mismatch, or partial-scope review
  remains a `manual_gap`.
- A captured structured internal review artifact can also be handed to
  `uv run xmuse-release-evidence-pack --internal-review-artifact REVIEW` with
  `--internal-review-expected-head-sha HEAD`. The pack only converts the
  explicit artifact through the same internal review gate validator; it does
  not create GitHub server-side review enforcement or merge truth.
- `uv run xmuse-natural-deliberation-gate-capture` converts an explicit natural
  GOD transcript artifact into the `natural_deliberation` release gate. It
  requires selected-GOD runtime continuity and blocks deterministic replay,
  missing session metadata, single-GOD transcript evidence, bounded or missing
  selected runtime, and unresolved blockers.
- `uv run xmuse-natural-deliberation-transcript-capture` is the production path
  for producing that transcript artifact from durable chat/session state. It
  does not synthesize live GOD messages; the conversation must already have
  real `god_speech_act` messages and provider session metadata.
- `uv run xmuse-god-runtime-continuity-capture` now exports
  `xmuse.god_runtime_continuity.v1` from durable `god_cli_selections.json`,
  `god_cli_registrations.json`, and `god_sessions.json`. This gives the
  natural deliberation gate and release evidence pack a repeatable selected-GOD
  runtime artifact without reading TUI/dashboard projections or Ray actor
  memory.
- TUI `/release export god-runtime ...` now routes through the audited
  `export_god_runtime_continuity` operator action and the same durable-store
  capture helper. The TUI path requires `release_gate`, writes under release
  readiness, and does not allow alternate projection/session paths.
- TUI/operator `export_natural_deliberation_transcript` now captures the same
  selected-GOD runtime continuity artifact by default and passes it to the
  natural deliberation release gate. Operators can still pass
  `god_runtime=skip` for compatibility-only replay, but production release
  evidence should keep the default selected-runtime binding so bounded workers,
  stale heartbeats, or missing selected runtime rows remain gate blockers.
- Selected-GOD runtime continuity now includes durable session heartbeat
  metadata from `god_sessions.json`. Stale or invalid heartbeats keep the
  runtime row blocked/manual-gap and prevent `peer_god_ready`, so natural
  deliberation release evidence cannot rely on a selected GOD whose session has
  gone stale.
- `uv run xmuse-real-provider-runtime-gate-capture` converts a real provider
  runtime soak artifact into the `real_provider` release gate. It blocks
  contract/fake proof, stdout fallback, missing MCP writeback, missing ordered
  stage timings, and missing restart/resume evidence.
  Release evidence packs now summarize the generated/attached
  `real_provider_runtime` detail so the TUI proof cockpit can display runtime
  provider/session continuity without treating the projection as authority.
- `uv run xmuse-real-provider-runtime-soak-capture` is the production path for
  producing that runtime artifact from durable peer latency traces and
  `god_sessions.json` provider session metadata. It requires operator-selected
  fresh/resume inbox trace ids and keeps probes, stdout fallback, fake/local
  backend labels, degraded turns, and missing provider session reuse as
  `manual_gap`.
- `uv run xmuse-memoryos-live-gate-capture` converts a live MemoryOS Lite trace
  artifact into the `live_memoryos` release gate. It blocks contract/fake proof,
  empty trace events, invalid namespace/session evidence, and unresolved
  blockers.
  Overnight replay bundles preserve the gate's `memoryos_trace` detail so the
  proof cockpit can show namespace/session/event/token context while keeping
  release readiness tied to the live gate.
- `uv run xmuse-memoryos-live-trace-capture` is the production path for
  producing that trace artifact from a configured MemoryOS Lite service. It
  performs create/ingest/build-context/trace through REST when configured and
  keeps unconfigured or failed trace capture as blocked `manual_gap`, not fake
  live evidence.
- `uv run xmuse-release-readiness-capture` reads JSON release gate artifacts
  from an artifact directory, writes a redacted report, and evaluates the gates
  with the same proof-level rules as `evaluate_release_readiness`.
- Release readiness capture deduplicates artifacts by `gate_id` and keeps the
  strongest non-blocking proof, so stronger live/server artifacts replace
  earlier status-capture blockers.
- The status capture command is `contract_proof`; it does not create live
  MemoryOS, GitHub, provider, or natural transcript proof by itself.
- `uv run xmuse-proof-contamination-audit` scans release gate artifacts for
  proof contamination: weak proof on `ok` production gates, fake/fixture/stdout
  markers in production proof, and `pr_merged` claims without server-side merge
  proof.
- `uv run xmuse-release-evidence-pack` writes one operator handoff report plus
  nested release-readiness, proof-contamination, and overnight replay-bundle
  reports for the same artifact directory. It accepts replay section artifacts
  and tombstoned source refs, but remains an aggregation command only; it does
  not create live proof or replace the underlying authorities.
- The release evidence pack now includes a top-level `recovery_queue` built
  from the S0 production baseline blockers, proof-contamination findings,
  release-readiness blockers, and overnight replay blockers. Each item records
  source, kind, id, owner, reason, next action, and the source report artifact
  so the overnight operator can continue recovery work without treating the
  pack as release, lane, review, GitHub, or MemoryOS authority.
- The same release pack command can accept `--production-baseline` and attach a
  redacted `xmuse.production_baseline.v1` S0 truth map to the top-level pack
  summary and `source_reports`. This keeps the starting git/env/resource/blocker
  map in the handoff artifact, but does not make baseline inventory a release
  gate, replay section, live proof, or readiness input.
- The same release pack command can accept repeated `--goal-stage-result`
  inputs and convert goal-stage runner `result.json` files into the replay
  bundle's `stage_evidence` section. This makes the long `/goal` stage spine
  replayable without treating stage results as lane status, review truth,
  GitHub truth, release readiness proof, or live runtime proof.
- The same release pack command can accept `--supervisor-snapshot` and convert
  a durable `xmuse.overnight_supervisor.v1` snapshot into replay-ready
  supervisor production evidence before building the nested replay bundle. This
  removes a manual handoff step but remains contract-level supervisor evidence,
  not live overnight proof.
- `uv run xmuse-overnight-supervisor` supports dependency-aware high-value
  fallback selection through `--stage-priority` and `--stage-depends-on`.
  Blocked live/auth/provider stages no longer force dependent release-pack
  stages to start; the supervisor journals skipped/waiting dependencies and
  starts the highest-priority ready independent stage. This keeps release
  blockers intact while allowing independent overnight work to continue.
- The supervisor virtual-time soak now persists `virtual_soaks` in the durable
  snapshot. `xmuse-overnight-supervisor-evidence-capture` includes the latest
  virtual-soak SLO in replay-ready supervisor evidence; violated heartbeat or
  self-review SLOs remain `manual_gap` with scheduling next action. The TUI
  proof cockpit projects the same virtual-soak summary and blocker as read-only
  operator evidence.
- The supervisor now treats repeated failure at the same stage/function boundary
  as refactor evidence, not as an invitation to keep stacking retries. The
  third matching failure classification writes a `refactor_required` issue,
  blocks the running stage, and emits `failure_refactor_escalation` production
  evidence with the next action to refactor before retrying.
- The same supervisor can import a goal-stage runner `result.json` through
  `uv run xmuse-overnight-supervisor --resume import-stage-result RESULT.json`.
  It records `goal_stage_results`, writes a
  `goal_stage_result_imported` production-evidence envelope sourced from
  `goal_stage_harness`, and turns `blocked` results into supervisor blockers
  with dependency-aware fallback. This makes stage-harness output replayable in
  the supervisor snapshot without making `result.json` authoritative for lane
  status, review truth, GitHub truth, release readiness, or live runtime proof.
- Imported `retry` goal-stage results now feed the same repeated-failure policy:
  the third retry import for the same stage records `goal_stage_retry` as
  refactor evidence, blocks the stage, and requires boundary refactor before
  another retry.
- The TUI proof cockpit can now project the same supervisor `goal_stage_results`
  as read-only operator evidence, including summary counts, per-stage status,
  proof level, engine, result artifact refs, blocker reason, and fallback target.
  The projection remains non-authoritative and cannot complete release gates or
  upgrade bounded worker proof by itself.
- The same release pack command can also accept repeated
  `--memoryos-governance-plan` and `--memoryos-writeback-event` inputs, convert
  them through `xmuse-memoryos-governance-evidence-capture`, and attach the
  generated artifact as the replay bundle's `memory_governance` section. This
  reduces handoff friction after governed MemoryOS writes, but remains
  contract-level governance evidence and does not create live MemoryOS trace
  proof. The generated artifact now also includes structured
  `memory_governance` details with decision counts, per-plan scope/event,
  namespace targets, review state, write-request eligibility, blockers, and
  next action. Replay bundles and the TUI proof cockpit can project those
  details as read-only operator context without writing MemoryOS state.
- The same release pack command can accept `--deliberation-transcript` and
  `--god-runtime`, convert them through
  `xmuse-deliberation-transcript-evidence-capture`, and attach the generated
  artifact as the replay bundle's `deliberation_transcript` section. This
  reduces handoff friction after natural transcript export, but missing runtime
  continuity remains blocked/manual-gap evidence. The existing natural
  deliberation gate rules also block deterministic replay, single-GOD
  transcripts, missing provider session metadata, bounded selected runtime, and
  unresolved blockers. The generated replay evidence now includes structured
  `deliberation_transcript` details for message/GOD counts, speech-act counts,
  natural/real-provider flags, selected-runtime artifact presence, peer-GOD
  readiness, missing provider-session GOD ids, and blocker count. The proof
  cockpit may render those details as operator context, but they cannot replace
  selected-GOD runtime continuity or satisfy the natural release gate by
  themselves.
- The same release pack command can separately accept
  `--natural-deliberation-transcript` and
  `--natural-deliberation-god-runtime`, convert them through
  `xmuse-natural-deliberation-gate-capture`, and write
  `natural-deliberation.json` under `--artifacts-dir` before readiness/audit.
  This is the release-gate path, not the replay-section path; it requires
  selected-GOD runtime continuity so bounded OpenCode-style workers or missing
  runtime rows cannot satisfy release readiness.
- Prefer producing that selected-GOD runtime continuity input with
  `uv run xmuse-god-runtime-continuity-capture` against the durable selection,
  registration, and session stores for the same conversation. Do not hand-edit
  the artifact or derive it from TUI/dashboard projection output. Operators can
  trigger the same capture from TUI with `/release export god-runtime`, which
  still routes through the release-gate capability contract rather than writing
  projection state.
- The same release pack command can accept `--frozen-blueprint` and repeated
  `--feature-contract` inputs, convert them through
  `xmuse-frozen-blueprint-evidence-capture` and
  `xmuse-feature-lineage-evidence-capture`, and attach the generated artifacts
  as the replay bundle's `frozen_blueprint` and `feature_lineage` sections.
  This reduces handoff friction after blueprint freeze and feature graph owner
  planning, but remains contract-level replay evidence and does not make TUI
  rendering, `feature_lanes.json`, or lane projections authoritative. The
  generated feature-lineage evidence includes structured lane-set and blocker
  details for operator scheduling; replay bundles preserve those details but
  still cannot write graph or lane status. The TUI proof cockpit projects the
  same details as read-only operator context, not as graph/lane authority.
- The same release pack command can accept `--memoryos-live-trace` and
  `--real-provider-runtime`, convert those raw live/provider artifacts through
  the existing `xmuse-memoryos-live-gate-capture` and
  `xmuse-real-provider-runtime-gate-capture` validators, and write the generated
  release gate artifacts under `--artifacts-dir` before readiness/audit. This
  reduces handoff friction but does not start live services, run providers, or
  upgrade contract/fake/local evidence into live/provider proof.
- The same release pack command can accept `--github-server-truth`, convert the
  explicit raw GitHub server truth snapshot through the existing release-gate
  builder, and write `github-server-truth.json` under `--artifacts-dir` before
  readiness/audit. This reduces handoff friction after a fresh capture, but the
  pack does not perform GitHub API calls and does not create review truth, merge
  truth, or `pr_merged`.
- The TUI proof cockpit can project the same raw GitHub server truth boundary
  as read-only operator context. It shows repo/PR, current and expected head,
  check/check-run counts, expected source app, branch-protection/ruleset source,
  review truth state, merge truth state, `can_emit_pr_merged`, merged flag,
  capture mode, and gap reason, without upgrading the release gate or emitting
  `pr_merged`.
- The same release pack command can accept `--internal-review-artifact`,
  convert the explicit structured internal review artifact through the existing
  internal review gate validator, and write `internal-review.json` under
  `--artifacts-dir` before readiness/audit. This reduces handoff friction after
  an independent current-head review, but the proof remains
  `internal_review_proof` and must not be rendered as GitHub enforcement.

Acceptance:

- Release readiness can be `ready`, `blocked`, or `not_evaluated`.
- `ready` requires no configured live gate blockers.
- `blocked` names owner, failing gate, attempted command, and next action.
- `not_evaluated` is never rendered as `ready`.

## S7 - Validation, Walkthrough, And PR Prep

Goal: finish with evidence, not claims.

Required validation:

```bash
uv run ruff check .
git diff --check
uv run pytest tests/xmuse/test_package_boundaries.py -q
```

Run focused pytest for every changed surface. Include these when relevant:

```bash
uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_navigation.py -q
uv run pytest tests/xmuse/test_memoryos_lite_interop.py -q
uv run pytest tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_github_server_gate_contract.py -q
uv run pytest tests/xmuse/test_goal_stage_runner.py -q
uv run pytest tests/xmuse/test_mcp_server.py tests/xmuse/test_production_hardening.py tests/xmuse/test_depth_hardening_contracts.py -q
uv run pytest tests/xmuse/test_production_hardening.py tests/xmuse/test_mainline_contract_docs.py -q
uv run pytest tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_opencode.py -q
```

Completion:

- [ ] Update docs and README entries.
- [ ] Produce a walkthrough/evidence artifact that lists live evidence captured
  and release blockers.
- [ ] Commit and push if validation passes.
- [ ] Create a draft PR if GitHub auth and repository state allow it.
- [ ] Do not merge automatically.

## Behavior Rules

- Use `uv run` for pytest, ruff, mypy, scripts, and Python entrypoints.
- Use `rg` for search.
- Preserve unrelated worktree changes.
- Prefer tests before implementation for behavior changes.
- Keep edits scoped and follow existing xmuse/xmuse_core boundaries.
- Do not import runtime `xmuse/` from `xmuse_core`.
- Do not import `memoryos_lite` directly from `xmuse_core`.
- Keep MemoryOS REST-first.
- Keep Ray actors as runtime resources, not durable authority.
- Keep `feature_lanes.json` as projection/queue only.
- Treat configured live gate failures as release blockers.
- Treat unconfigured external dependencies as `manual_gap` only when the gap
  records owner, next action, and exact missing prerequisite.
- Treat repeated failure of the same function or stage boundary as a
  `refactor_required` supervisor issue; stop local retry loops until the
  boundary has been refactored and revalidated.
- Never use fake/local/contract evidence as release proof.
- Never render readiness as completed fact.
- Never auto-merge.

## Evidence Envelope

Every production stage or action should emit or update a structured envelope
with at least:

```json
{
  "schema_version": "xmuse.production_evidence.v1",
  "stage_id": "S4",
  "action": "github_server_truth_capture",
  "status": "ok",
  "proof_level": "server_side_enforcement_proof",
  "source_authority": "github_api",
  "source_refs": ["pr:123"],
  "target_refs": ["release_gate:vision-production-evidence-control-closure"],
  "commands": ["uv run python scripts/github_server_truth_capture.py ..."],
  "test_results": [],
  "artifacts": [],
  "blocked_reason": null,
  "owner": "operator",
  "next_action": null
}
```

The envelope is a reporting format. It must not become a replacement for the
durable authority that owns each fact.

## Final Report Requirements

The final `/goal` report must include:

- stages completed and stages blocked;
- files changed;
- tests and validation commands with results;
- live/server/provider evidence captured;
- configured live gates that blocked release readiness;
- TUI write actions implemented and their authority path;
- GOD CLI registration/selection state;
- Auth/RBAC enforcement state;
- remaining production gaps and owners;
- commit, push, and draft PR status.
