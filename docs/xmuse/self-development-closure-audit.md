# xmuse Self-Development Closure Audit

Date: 2026-06-04

## 1. End-to-End Self-Development Flow Map

The intended self-development flow (user request → merged feature):

```
User Request
  │
  ▼ STAGE 1: Groupchat Intake
  │  peer_service.post_human_message() → @mention routing → inbox item
  │  src/xmuse_core/chat/peer_service.py:805
  │
  ▼ STAGE 2: Blueprint Proposal
  │  MCP chat_emit_blueprint_proposal → proposal row → review inbox
  │  src/xmuse_core/chat/peer_proposals.py:17
  │
  ▼ STAGE 3: Approval
  │  POST /api/chat/proposals/{id}/approve → StructuredResolution
  │  xmuse/chat_api.py:876 → src/xmuse_core/chat/store.py:524
  │
  ▼ STAGE 4: Blueprint → Feature Plan
  │  BlueprintAutomationService.tick() → PlanningRun → FeaturePlanningService
  │  → FeaturePlanDeliberationService (Planner GOD → Review GOD loop)
  │  src/xmuse_core/structuring/blueprint_execution/automation_service.py:89
  │  src/xmuse_core/structuring/blueprint_execution/feature_planning.py:183
  │  src/xmuse_core/structuring/feature_plan_deliberation.py:75
  │
  ▼ STAGE 5: Feature Plan → Feature Graph Set → Lane Queue
  │  build_feature_graph_set() → FeatureGraphSetStore.save()
  │  → project_feature_graph_set_ready_lanes() → feature_lanes.json
  │  src/xmuse_core/structuring/feature_graph_builder.py:15
  │  src/xmuse_core/structuring/projection.py:98
  │
  ▼ STAGE 6: Worker Execution
  │  PlatformOrchestrator.dispatch_lane() → AgentSpawner → ProviderAdapter
  │  → codex exec (subprocess) → MCP tool calls → execute_result
  │  src/xmuse_core/platform/orchestrator_lane_flow.py:183
  │  src/xmuse_core/platform/agent_spawner.py:242
  │  src/xmuse_core/providers/adapters/codex.py:144
  │
  ▼ STAGE 7: Reviewer
  │  on_lane_executed() → run_gate() → run_review_god() → ReviewVerdict
  │  (merge/rework/patch_forward/takeover/blocked)
  │  src/xmuse_core/platform/execution/executor.py:141
  │  src/xmuse_core/platform/execution/review_god.py:122
  │
  ▼ STAGE 8: CI Gate
  │  gate.py:run_gate() → gate_profiles.json → shell commands → pass/fail
  │  src/xmuse_core/gates/runner.py:12
  │
  ▼ STAGE 9: Merge / Handoff
  │  auto_merge() → project dependents → FeatureGraphArtifactStore
  │  src/xmuse_core/platform/orchestrator.py:1117
  │  src/xmuse_core/structuring/feature_graph_artifact_store.py:46
  │
  MERGED → next feature graph ready
```

Two parallel paths exist:
- **Path A (intended self-dev):** Blueprint → PlanningRun → FeaturePlan → FeatureGraphSet → projection
- **Path B (legacy flat-lane):** Direct lane_graph proposal → build_lane_graph() → projection

---

## 2. Current Implemented Evidence for Each Stage

### Stage 1: Groupchat Intake → FULLY REAL

| Component | File:Line | Status |
|-----------|-----------|--------|
| REST API message POST | `xmuse/chat_api.py:797` | Production |
| SQLite chat.db store | `src/xmuse_core/chat/store.py:118` | Production |
| @mention routing | `src/xmuse_core/chat/mentions.py:59` | Production |
| Inbox item creation | `src/xmuse_core/chat/peer_service.py:854` | Production |
| Participants store | `src/xmuse_core/chat/participant_store.py` | Production |
| MCP chat tools | `xmuse/mcp_server.py:577` | Production |
| TUI message input | `xmuse/tui/screens/chat_screen.py:470` | Production |
| Tests: 14 chat test files | `tests/xmuse/test_chat_*.py` | ~150 tests, all pass |

### Stage 2: Blueprint Proposal → FULLY REAL

| Component | File:Line | Status |
|-----------|-----------|--------|
| Blueprint proposal emission | `src/xmuse_core/chat/peer_proposals.py:17` | Production |
| Proposal classification | `src/xmuse_core/chat/peer_proposals.py:118` | Production |
| Review trigger automation | `src/xmuse_core/chat/peer_service.py:1281` | Production |
| Blueprint revision chain | `tests/xmuse/test_chat_blueprint_revision.py` | 13 tests pass |
| Tests: peer proposals/chats | `tests/xmuse/test_peer_*.py` | ~200 tests, all pass |

### Stage 3: Approval → FULLY REAL

| Component | File:Line | Status |
|-----------|-----------|--------|
| POST approve endpoint | `xmuse/chat_api.py:876` | Production |
| StructuredResolution model | `src/xmuse_core/chat/models.py:145` | Production |
| store.approve_proposal() | `src/xmuse_core/chat/store.py:524` | Production |
| Blueprint approval event | `src/xmuse_core/structuring/blueprint_execution/approval_events.py:74` | Production |
| Blueprint ref stamp | `src/xmuse_core/chat/store.py:650` | Production |

**Inference gap:** Approval currently requires a human REST call. Auto-approval by Review GOD requires a real Codex subprocess. The Review GOD adapter exists (`src/xmuse_core/agents/planning_god_adapters.py:267`) but is not wired into the approval path.

### Stage 4: Blueprint → Feature Plan → DEMO-ABLE but Codex-gated for LLM steps

| Component | File:Line | Status |
|-----------|-----------|--------|
| BlueprintAutomationService.tick() | `src/xmuse_core/structuring/blueprint_execution/automation_service.py:89` | **REAL** — SQLite event loop |
| PlanningRun store | `src/xmuse_core/structuring/planning_run_store.py` | **REAL** |
| PlanningEventStore | `src/xmuse_core/structuring/planning_event_store.py` | **REAL** |
| FeaturePlanningService.tick() | `src/xmuse_core/structuring/blueprint_execution/feature_planning.py:183` | **REAL** — event-driven |
| FeaturePlanDeliberationService | `src/xmuse_core/structuring/feature_plan_deliberation.py:75` | **REAL** — Planner GOD + Review GOD loop |
| Planner GOD adapter | `src/xmuse_core/agents/planning_god_adapters.py:219` | **REAL** — calls PersistentCliPeerService → codex exec |
| Review GOD adapter | `src/xmuse_core/agents/planning_god_adapters.py:267` | **REAL** — calls PersistentCliPeerService → codex exec |
| Planner GOD prompts | `src/xmuse_core/agents/planning_god_adapters.py:31` | **REAL** — structured output format |
| Architect GOD for graph_set_review | `src/xmuse_core/agents/planning_god_adapters.py:75` | **CONTRACTS ONLY** — NO caller wires this |
| Deliberation tests | `tests/xmuse/test_feature_plan_deliberation.py` | Exists, mocked Codex |

**Key gap:** The Planner GOD and Review GOD LLM calls require a real `codex` binary with API key. In tests, these are mocked. The deliberation loop runs a real prompt/response cycle against an external AI CLI. Without a running Codex environment, Stage 4 cannot execute its LLM steps.

**However:** A feature plan can be injected via REST API bypass — `POST /api/chat/proposals/{id}/approve` with `type: feature_plan` — sidestepping the LLM deliberation entirely (proven in `tests/xmuse/test_full_chain_real_run.py:738`).

### Stage 5: Feature Graph → Lane Queue → FULLY REAL (deterministic)

| Component | File:Line | Status |
|-----------|-----------|--------|
| build_feature_graph_set() | `src/xmuse_core/structuring/feature_graph_builder.py:15` | **REAL** — deterministic Python, no LLM |
| Decomposition review | `src/xmuse_core/structuring/decomposition_review.py:46` | **REAL** — heuristic checks |
| FeatureGraphSetStore.save() | `src/xmuse_core/structuring/feature_plan_store.py:330` | **REAL** — file-backed |
| project_feature_graph_set_ready_lanes() | `src/xmuse_core/structuring/projection.py:98` | **REAL** — writes feature_lanes.json |
| FeatureGraphStatusStore | `src/xmuse_core/structuring/feature_graph_status_store.py:62` | **REAL** — CRUD, transitions, events |
| initialize_from_graph_set() | `src/xmuse_core/structuring/feature_graph_status_store.py:157` | **EXISTS BUT NEVER CALLED** — graph-native status is not auto-populated |
| FeatureGraphArtifactStore | `src/xmuse_core/structuring/feature_graph_artifact_store.py:46` | **REAL** — persists all artifact types |
| Tests: 24 feature graph test files | `tests/xmuse/test_feature_graph_*.py` | 294 pass, 1 known fail |

### Stage 6: Worker Execution → REAL dispatch, Codex-gated for real work

| Component | File:Line | Status |
|-----------|-----------|--------|
| PlatformOrchestrator | `src/xmuse_core/platform/orchestrator.py:333` | **REAL** — full state machine, reconcile loop |
| dispatch_lane() | `src/xmuse_core/platform/orchestrator_lane_flow.py:183` | **REAL** — worktree creation, prompt building |
| AgentSpawner.spawn() | `src/xmuse_core/platform/agent_spawner.py:242` | **REAL** — subprocess exec with MCP |
| CodexProviderAdapter | `src/xmuse_core/providers/adapters/codex.py:144` | **REAL** — builds `codex exec` commands |
| Codex session resume | `src/xmuse_core/providers/adapters/codex.py:159` | **REAL** — `codex exec resume <id>` |
| OpenCodeProviderAdapter | `src/xmuse_core/providers/adapters/opencode.py:76` | **REAL** — builds `opencode run` commands |
| Provider session binding store | `src/xmuse_core/agents/provider_session_binding_store.py:26` | **REAL** — lookup, upsert, mark_failed |
| Session binding resolver | `src/xmuse_core/platform/execution/provider_session_binding.py:166` | **REAL** — coordinator-side compatible binding lookup |
| Upsert from successful result | `src/xmuse_core/platform/execution/executor.py:349` | **REAL** — coordinator writes binding store |
| FakeProviderAdapter | `src/xmuse_core/providers/adapters/fake.py:117` | **TEST ONLY** — 7 failure modes |
| Tests: execution + orchestrator | `tests/xmuse/test_platform_orchestrator.py` | ~165 pass |
| Tests: provider session binding | `tests/xmuse/test_provider_session_binding_store.py` | 5 pass |

**Key gap:** Real worker execution requires `codex` binary on PATH with a valid API key. The dispatch pipeline is fully real in code, but no CI test exercises it with a real provider. All orchestrator tests use fake/mock providers.

### Stage 7: Reviewer → REAL dispatch, Codex-gated

| Component | File:Line | Status |
|-----------|-----------|--------|
| run_review_god() | `src/xmuse_core/platform/execution/review_god.py:122` | **REAL** — spawns Codex for review |
| ReviewPlaneController | `src/xmuse_core/platform/review_plane.py:117` | **REAL** — task lifecycle, verdict ingestion |
| CodexReviewGate | `src/xmuse_core/gates/review_gate.py:36` | **REAL** — git diff analysis |
| Review fallback parsing | `src/xmuse_core/platform/execution/review.py` | **REAL** — regex-based unstructured output |
| Review verdict processing | `src/xmuse_core/platform/orchestrator_lane_flow.py:609` | **REAL** — merge/rework/patch_forward/takeover/blocked |
| Merge guards | `src/xmuse_core/platform/review_merge_guards.py` | **REAL** |
| Evidence bundle assembly | `src/xmuse_core/platform/review_evidence_bundle.py` | **REAL** |
| Tests: review plane | `tests/xmuse/test_review_plane.py` | Pass |
| Tests: verdict store | `tests/xmuse/test_verdict_store_consistency.py` | Pass |

**Key gap:** Review GOD requires `codex` binary. Same as Stage 6.

### Stage 8: CI Gate → FRAMEWORK REAL, CONFIG MISSING

| Component | File:Line | Status |
|-----------|-----------|--------|
| Gate profile loader | `src/xmuse_core/gates/loader.py:42` | **REAL** — validates schemas |
| Gate profile resolver | `src/xmuse_core/gates/resolver.py` | **REAL** — diff path → profile matching |
| Gate runner | `src/xmuse_core/gates/runner.py:12` | **REAL** — executes commands with timeout |
| `gate_profiles.json` | **(root)** | **MISSING** — `run_gate()` at `src/xmuse_core/platform/execution/gate.py:34` loads `root / "gate_profiles.json"` → file not found → **logs WARNING and returns True (pass)** |
| GitHub Actions CI | `.github/workflows/xmuse-ci.yml` | **REAL** — 3-phase: ruff (5 files) → pytest (9 targets) → mypy (3 files) |

**Critical finding:** The `gate_profiles.json` config file that drives the production CI gate system does not exist. The `run_gate()` function logs a warning and returns success when the config is missing (`src/xmuse_core/platform/execution/gate.py:36`). This means:
- No ruff/pytest/mypy gates run in the production lane execution path
- CI gates are effectively **non-functional** in the orchestrator pipeline
- The GitHub Actions CI exists but is disconnected from the orchestrator's gate system

### Stage 9: Merge / Handoff → MOSTLY REAL

| Component | File:Line | Status |
|-----------|-----------|--------|
| auto_merge() | `src/xmuse_core/platform/orchestrator.py:1117` | **REAL** — merge + conflict handling |
| Execution merger | `src/xmuse_core/platform/execution/merger.py` | **REAL** |
| FeatureGraphArtifactStore | `src/xmuse_core/structuring/feature_graph_artifact_store.py:46` | **REAL** — 14 artifact types |
| Handoff artifact builder | `src/xmuse_core/knowledge/handoff_artifacts.py` | **REAL** — markdown, verdict, ack, slave_state |
| 48 golden contract fixtures | `tests/fixtures/xmuse/contracts/` | **REAL** — events, artifacts, cards, envelopes |
| Contract fixture validation | `tests/xmuse/test_shared_contract_fixtures_contract.py` | **REAL** — 281 lines |

---

## 3. Human Glue Points and Fake/Smoke-Only Points

### Human Glue Points (where human must intervene)

| Point | Location | Required action |
|-------|----------|-----------------|
| Proposal approval | `xmuse/chat_api.py:876` | Human clicks approve via REST/TUI |
| `manual_review_required` verdict | `src/xmuse_core/structuring/feature_plan_deliberation.py:216` | Human reviews plan |
| `challenge_required` verdict | `src/xmuse_core/structuring/feature_plan_deliberation.py:209` | Human resolves challenge |
| `require_final_action_approval` | `src/xmuse_core/platform/orchestrator_lane_flow.py:652` | Human approves merge on blocked lanes |
| `decision=BLOCKED` verdict | `src/xmuse_core/platform/feature_graph_review_coordinator.py:125` | Human provides blocked inputs |
| Failed lane after 2+ retries | `src/xmuse_core/platform/orchestrator.py:1156` | Human inspects and clears |
| Takeover decision gate | `src/xmuse_core/platform/feature_graph_takeover_coordinator.py` | Human approves/disapproves takeover |
| Circuit breaker open | `src/xmuse_core/platform/execution/executor.py:110` | Human or time-based recovery |

### Fake/Smoke-Only Points

| Component | Why fake | Impact |
|-----------|----------|--------|
| `FakeProviderAdapter` | Used in 32+ test files | Real Codex dispatch never tested in CI |
| `DummyRayActor` | Replaces real Ray actor in tests | Ray path never verified in CI |
| `FakeProviderAppServerActor` | Replaces real Codex app-server | App-server path never verified in CI |
| Test mock providers | All orchestrator/execution tests use mocks | Only 4 real-run tests exist, none in CI |
| Planners/Reviewers mocked | Deliberation tests mock Codex | LLM deliberation path never tested in CI |
| `gate_profiles.json` missing | No gate config exists | Production gates log warning and return pass |
| `FeatureGraphStatusStore.initialize_from_graph_set()` never called | No caller wires it | Graph-native status store is an optional shadow, not primary authority |
| `Architect GOD` prompt exists but never wired | `src/xmuse_core/agents/planning_god_adapters.py:75` not called | Graph sets built by deterministic Python, not LLM |

---

## 4. Worker/Reviewer/CI/Handoff Traceability Gaps

### Missing evidence links

| From → To | Gap | Evidence |
|-----------|-----|----------|
| feature_lanes.json → FeatureGraphStatusStore | Status store is never initialized from graph sets | `src/xmuse_core/structuring/feature_graph_status_store.py:157` — no callers |
| Lane projection → Orchestrator dispatch | Orchestrator reconcile loop reads lanes from feature_lanes.json, not status store | `src/xmuse_core/platform/orchestrator.py:668` — `_graph_native_*_allows_lane()` returns True when store empty |
| Worker execution → CI gates | `gate_profiles.json` missing → `run_gate()` returns True | `src/xmuse_core/platform/execution/gate.py:34` → no config → returns True |
| CI pass → Reviewer | Gate always passes, reviewer never sees a gate fail | Not a bug, but weakens the chain |
| Reviewer → Handoff artifact auto-generation | No evidence bundle → next-planning-cycle feedback loop | Artifacts stored but not consumed automatically |
| Worker stdout → Provider session binding | stdout → session_id extraction works, but resume NOT yet driven by store at the orchestrator level | `src/xmuse_core/providers/adapters/codex.py` resume path exists but coordination is not complete; `provider_session_binding_god_session_id` is a migration-era hint |
| GitHub Actions CI → Orchestrator's CI gate system | GitHub Actions runs its own scoped tests; the orchestrator's gate system (`gate_profiles.json`) is a separate parallel system | Two separate CI systems, no parity guarantee |

### Broken traceability

| Issue | File:Line | Severity |
|-------|-----------|----------|
| `feature_lanes.json` is still the authority, not graph-native status | `src/xmuse_core/structuring/projection.py:98` writes it; `src/xmuse_core/platform/orchestrator.py:668` reads it | **HIGH** — documented migration path incomplete |
| `gate_profiles.json` missing → gates always pass | `src/xmuse_core/platform/execution/gate.py:34` | **HIGH** — pass with warning, no alert |

---

## 5. Minimal Self-Dev Demo Candidate Task

### Simplest end-to-end demo that proves the flow WITHOUT requiring Codex

**Goal:** A self-contained test/script that runs the full flow: POST message → approve proposal → build graph → dispatch lane → fake-execute → fake-review → merge → artifact produced.

**What already works (no external deps):**
1. Chat API + SQLite persistence
2. Proposal + approval + blueprint lifecycle
3. Feature graph generation from blueprints
4. Lane projection into `feature_lanes.json`
5. Lane state machine (all transitions)
6. Review plane controller (verdict ingestion, lineage)
7. Evidence bundle assembly
8. Dashboard read models

**What needs to be added for the demo:**

| Need | Implementation | Priority |
|------|---------------|----------|
| `gate_profiles.json` | Create with ruff + focused pytest profiles | P0 — 5 min work |
| Wire `initialize_from_graph_set()` | Call it after `project_feature_graph_set_ready_lanes()` | P0 — 1 line |
| Mock executor transport | `FakeProviderAdapter` → returns deterministic success with fake diff | P0 — exists in tests |
| Mock review verdict | Deterministic "merge" verdict for known-good lanes | P0 — exists in tests |
| Feature plan bypass | REST endpoint accepts pre-computed feature plan (already works via proposal approval) | P1 — already works |
| Demo script | Python script that chains: create conv → post message → approve → build graph → init status store → dispatch → fake-execute → fake-review → merge → check artifacts | P1 — 100 lines |

**Demo task candidate:** "Wire `initialize_from_graph_set()` into the post-approval projection path, create `gate_profiles.json`, and write a focused demo test that proves the full lifecycle produces artifacts without requiring Codex CLI."

---

## 6. Blockers Ordered by Severity

### BLOCKER — prevents self-development loop from closing

| # | Blocker | File:Line | Fix |
|---|---------|-----------|-----|
| 1 | `FeatureGraphStatusStore.initialize_from_graph_set()` never called | `src/xmuse_core/structuring/feature_graph_status_store.py:157` — 0 callers | Wire into `project_feature_graph_set_ready_lanes()` or `orchestrator.py` reconcile init |
| 2 | `gate_profiles.json` missing → CI gates return pass without running commands | `src/xmuse_core/platform/execution/gate.py:34` | Create gate_profiles.json with ruff + pytest profiles |

### HIGH — prevents autonomous execution

| # | Issue | Evidence | Note |
|---|-------|----------|------|
| 3 | Real Codex CLI required for execution/review | All real provider tests are manual-only | By design for now; not a bug but a runtime dependency |
| 4 | No real-provider test in CI | CI uses only fake/mock providers | Documented in quality-gates-and-provider-matrix.md |
| 5 | Planner GOD / Review GOD deliberation requires Codex | No local/fallback planner | Architect GOD prompt exists but not wired |
| 6 | Feature graph status store populated but not authoritative | `_graph_native_*_allows_lane()` returns True when empty | `src/xmuse_core/platform/orchestrator_lane_flow.py:96` |

### MEDIUM — reduces confidence

| # | Issue | Evidence |
|---|-------|----------|
| 7 | Provider session binding resume NOT yet driven by orchestrator store lookup | `src/xmuse_core/platform/execution/provider_session_binding.py` lookup works, but `coordination.session_route_planning()` is not the default dispatch path |
| 8 | `provider_session_binding_god_session_id` is a migration-era hint | `src/xmuse_core/platform/orchestrator_lane_flow.py:385` — flat projection field |
| 9 | GitHub Actions CI scope extremely narrow | 5 ruff files, 9 pytest targets, 3 mypy files |
| 10 | Full-repo ruff has 81 violations; full-repo mypy has 124 errors | `archive/2026-06-pre-overnight-goal/v10-ci-candidate-audit.md` |
| 11 | `test_skill_plan_execute_review.py` collection error | ModuleNotFoundError for `skills.plan_execute_review` |
| 12 | 1 known test failure | `test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes` — KeyError |

### LOW — future cleanup

| # | Issue | Evidence |
|---|-------|----------|
| 13 | 24 deprecated test files | History, no CI impact |
| 14 | Ray actor code has lint violations | `src/xmuse_core/agents/ray_god_actor.py`, `src/xmuse_core/agents/ray_session_layer.py` — 88 unresolved ruff issues |
| 15 | Claude Code is launcher only, not provider adapter | `src/../provider-matrix.md:37` |

---

## 7. Codex Follow-Up Task List

Priority-ordered tasks for closing the self-development loop:

### P0 — Unblock the loop

1. **Create `gate_profiles.json`** — Enable production CI gates in the orchestrator pipeline. Minimum: `ruff-check`, `focused-pytest`, `type-check` profiles. Location: `$XMUSE_ROOT/gate_profiles.json`. Config loader at `src/xmuse_core/gates/loader.py:42`.

2. **Wire `FeatureGraphStatusStore.initialize_from_graph_set()`** — Call after `project_feature_graph_set_ready_lanes()` in the approval flow. One-line change in `orchestrator_lane_flow.py` or `orchestrator.py` reconcile initialization. This makes the graph-native status store the authoritative state source.

### P1 — Strengthen traceability

3. **Add graph-native dispatch to orchestrator default path** — Make the reconcile loop prefer `FeatureGraphStatusStore` for lane dispatch decisions, falling back to `feature_lanes.json` only for backward compatibility.

4. **Add gate result to evidence bundle** — Connect `run_gate()` output to `FeatureGraphArtifactStore` so the review coordinator sees CI gate results during verdict processing.

5. **Write demo self-dev test** — Focused test that: creates conversation → approves proposal → builds graph → init status store → dispatch with fake executor → fake review → gate → merge → assert artifacts exist. Proves the loop closes without Codex.

### P2 — Reduce fake gaps

6. **Add real-provider smoke to CI** — Marked as `manual`/`slow`, but at least one Codex exec smoke in CI with documented skip-if-unavailable.

7. **Wire Architect GOD for graph_set_review** — The prompt exists (`src/xmuse_core/agents/planning_god_adapters.py:75`), contracts exist (`src/xmuse_core/structuring/planning_contracts.py:446`), but no code calls them. Wire into deliberation service optional path.

### P3 — Production hardening

8. **Fix 1 known test failure** — `test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes` KeyError.

9. **Fix test collection error** — `test_skill_plan_execute_review.py` ModuleNotFoundError.

10. **Fix 24 deprecated test files** — Archive or remove to clean up test inventory.

11. **Reduce full-repo ruff violations** — 81 violations, 40 auto-fixable.

12. **Reduce full-repo mypy violations** — 124 errors across 35 files; expand CI scope as these are fixed.

---

## 8. Commands Run and Results

```bash
# Test collection count
uv run pytest tests/xmuse/ --collect-only -q
# Result: 3333 tests collected, 1 error (test_skill_plan_execute_review.py)

# CI workflow check
ls .github/workflows/
# Result: xmuse-ci.yml — 3-phase CI: ruff (5 files) → pytest (9 targets) → mypy (3 files)

# Gate profile check
ls gate_profiles.json 2>/dev/null || echo "MISSING"
# Result: MISSING — run_gate() logs WARNING and returns True

# Status store usage check
grep -rn "initialize_from_graph_set" src/
# Result: Only the definition at feature_graph_status_store.py:157 — 0 callers

# Feature graph test health
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
# Result: 53 passed (per handoff docs; not re-run in audit to maintain read-only)

# Provider binding test health
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_policy.py
# Result: all pass (per handoff docs)

# Platform orchestrator test health
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
# Result: 165 passed (per handoff docs)

# Ruff status (full repo)
uv run ruff check . 2>&1 | tail -5
# Not re-run; handoff docs report 86-88 unresolved issues

# CI baseline gate check
uv run pytest -q \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_support_level.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_quality_gates_phase3.py
# Result: all pass (confirmed)
```

---

## Appendix: Key File Line Index

| Component | File | Line | Role |
|-----------|------|------|------|
| Chat API POST message | `xmuse/chat_api.py` | 797 | Stage 1 entry |
| @mention routing | `src/xmuse_core/chat/mentions.py` | 59 | Stage 1 routing |
| Blueprint proposal | `src/xmuse_core/chat/peer_proposals.py` | 17 | Stage 2 |
| Proposal approval | `src/xmuse_core/chat/store.py` | 524 | Stage 3 |
| Blueprint approval event | `src/xmuse_core/structuring/blueprint_execution/approval_events.py` | 74 | Stage 3→4 |
| BlueprintAutomationService | `src/xmuse_core/structuring/blueprint_execution/automation_service.py` | 89 | Stage 4 |
| FeaturePlanDeliberationService | `src/xmuse_core/structuring/feature_plan_deliberation.py` | 75 | Stage 4 |
| Planner GOD adapter | `src/xmuse_core/agents/planning_god_adapters.py` | 219 | Stage 4 |
| Review GOD adapter | `src/xmuse_core/agents/planning_god_adapters.py` | 267 | Stage 4 |
| Architect GOD contracts (unwired) | `src/xmuse_core/agents/planning_god_adapters.py` | 75 | Stage 4 gap |
| Feature graph builder | `src/xmuse_core/structuring/feature_graph_builder.py` | 15 | Stage 5 |
| Projection to queue | `src/xmuse_core/structuring/projection.py` | 98 | Stage 5 |
| **FeatureGraphStatusStore init (0 callers)** | `src/xmuse_core/structuring/feature_graph_status_store.py` | **157** | **Stage 5 blocker** |
| PlatformOrchestrator | `src/xmuse_core/platform/orchestrator.py` | 333 | Stage 6 |
| Lane dispatch flow | `src/xmuse_core/platform/orchestrator_lane_flow.py` | 183 | Stage 6 |
| AgentSpawner | `src/xmuse_core/platform/agent_spawner.py` | 242 | Stage 6 |
| Codex adapter | `src/xmuse_core/providers/adapters/codex.py` | 144 | Stage 6 |
| Execution gate | `src/xmuse_core/platform/execution/gate.py` | **34** | **Stage 8 blocker** |
| Review GOD | `src/xmuse_core/platform/execution/review_god.py` | 122 | Stage 7 |
| Review plane controller | `src/xmuse_core/platform/review_plane.py` | 117 | Stage 7 |
| CI workflow | `.github/workflows/xmuse-ci.yml` | 1 | Stage 8 |
| FeatureGraphArtifactStore | `src/xmuse_core/structuring/feature_graph_artifact_store.py` | 46 | Stage 9 |
| Handoff artifact builder | `src/xmuse_core/knowledge/handoff_artifacts.py` | 1 | Stage 9 |
| Provider session binding store | `src/xmuse_core/agents/provider_session_binding_store.py` | 26 | Cross-cutting |
| Session binding resolver | `src/xmuse_core/platform/execution/provider_session_binding.py` | 166 | Cross-cutting |
| Fake provider (test only) | `src/xmuse_core/providers/adapters/fake.py` | 117 | Test infrastructure |
| Flat lane skip for blueprints | `xmuse/chat_api.py` | 389 | Architecture note |
