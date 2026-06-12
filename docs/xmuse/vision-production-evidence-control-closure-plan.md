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

Treat this as an 8-10 hour production closure run. If a stage is blocked by a
configured live dependency, record the blocker and owner, then continue only to
independent stages. Do not silently downgrade production gates to demo paths.

| Window | Stage | Expected output |
| --- | --- | --- |
| 0:00-0:45 | S0 Production baseline | Env, branch, current proof state, configured live resources, and dirty state recorded. |
| 0:45-2:00 | S1 GOD/CLI registry | Manual GOD CLI registration and selection contract designed or implemented with tests. |
| 2:00-3:30 | S2 TUI full-control actions | Mutating TUI actions go through authorized action contracts, not projection writes. |
| 3:30-5:00 | S3 Auth/RBAC production gate | Operator/session capability and audit enforcement for write surfaces. |
| 5:00-6:30 | S4 Live evidence gates | MemoryOS, GitHub, Ray/Codex/OpenCode gates attempted using configured environment. |
| 6:30-7:45 | S5 Natural GOD transcript path | Natural transcript boundary tied to selected GOD CLI participants and freeze rules. |
| 7:45-9:00 | S6 Release readiness | Release gate aggregates live/server/provider/internal review evidence. |
| 9:00-10:00 | S7 Validation, docs, PR prep | Focused tests, ruff, diff check, walkthrough, commit/push/draft PR when green. |

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

## S1 - GOD/CLI Registry And Selection

Goal: make GOD participant selection explicit and product-ready.

Tasks:

- [ ] Add or extend a GOD/CLI registry contract in `src/xmuse_core/providers/`
  that records CLI id, display name, command family, provider profile,
  capabilities, allowed speech acts, persistence support, MCP/writeback support,
  health status, and proof level.
- [ ] Keep current OpenCode behavior bounded unless evidence proves peer-GOD
  parity. For this round, OpenCode may be selectable only under bounded
  capability labels unless production proof exists.
- [ ] Add TUI/provider-board read model support for registered GOD CLI choices.
- [ ] Add tests that reject unregistered or capability-incompatible GOD choices.

Acceptance:

- Operator can see which CLI can be chosen as GOD and why.
- GOD selection cannot bypass capability policy.
- OpenCode is not upgraded by assertion.

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

## S5 - Natural GOD Transcript And Freeze Path

Goal: connect selected GOD participants to a real natural deliberation path
without weakening freeze rules.

Tasks:

- [ ] Export natural transcript evidence only when real GOD/CLI participants
  produced the conversation.
- [ ] Preserve speech acts, source refs, target refs, blockers, participant CLI,
  provider profile, session id, and proof level.
- [ ] Keep deterministic replay labeled as `contract_proof`.
- [ ] Ensure unresolved blocking objections prevent freeze.
- [ ] Route freeze approval through the production TUI/action contract when
  implemented.

Acceptance:

- Natural transcript evidence is visibly separate from deterministic replay.
- Freeze cannot be completed from unresolved blockers or local-only proof.
- Transcript evidence links to blueprint, feature, and lane refs.

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
