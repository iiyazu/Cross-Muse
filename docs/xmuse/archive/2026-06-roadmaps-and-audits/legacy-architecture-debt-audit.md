# Legacy / Architecture Debt Audit for xmuse

Date: 2026-06-04

Type: Read-only source audit. No production code or tests modified.

---

## 1. Authoritative Main Paths vs Legacy Paths

### 1.1 Current Main Path (Active Production)

| Component | Path | Evidence |
|---|---|---|
| Chat API (FastAPI) | `xmuse/chat_api.py` | Entrypoint in pyproject.toml, actively used |
| MCP Server (FastAPI) | `xmuse/mcp_server.py` | Entrypoint, actively used |
| Platform Runner | `xmuse/platform_runner.py` | Entrypoint, actively used — 1439 lines |
| TUI (Textual) | `xmuse/tui/` | Entrypoint, actively developed (V3 in progress) |
| Dashboard API | `xmuse/dashboard_api.py` | Actively used, 1021 lines |
| Core library | `src/xmuse_core/` | All runtime imports use `xmuse_core.*` |
| Provider system | `src/xmuse_core/providers/` | Active: Codex (PRIMARY), OpenCode (SECONDARY) |
| GOD session layer | `src/xmuse_core/agents/ray_session_layer.py` | Active Ray-based groupchat |
| Feature graph system | `src/xmuse_core/structuring/` | Active: graph-native execution status |
| Chat store/services | `src/xmuse_core/chat/` | Active: sqlite3 `chat.db` |
| Self-evolution | `src/xmuse_core/self_evolution/` | Active: controller, watcher, decomposer |
| Orchestrator | `src/xmuse_core/platform/orchestrator.py` | Active coordinator, 1301 lines |

### 1.2 Legacy / Deprecated Paths (Still On Disk)

| Component | Path | Lines | Status |
|---|---|---|---|
| **master_loop.py** | `xmuse/master_loop.py` | 996 | Still referenced by `scheduler_monitor.sh` and tests. Actively reads legacy env vars. But NOT imported by current production code (`platform_runner.py` replaced it). |
| **hermes_reporter.py** | `xmuse/hermes_reporter.py` | 327 | Legacy. Only called by `scheduler_monitor.sh`. Reads `XMUSE_LOOP_ROOT`, `XMUSE_REPORT_ONLY`. |
| **hermes_loop.py** | `xmuse/hermes_loop.py` | 2 | Self-declared deprecated (`# DEPRECATED. Use god_launcher.sh`). |
| **hermes_hardening.py** | `xmuse/hermes_hardening.py` | 856 | Legacy re-exporter/wrapper. Only called by other legacy scripts. |
| **slave_job_runner.py** | `xmuse/slave_job_runner.py` | 591 | Legacy. Replaced by platform runner execution system. |
| **multi_lane_dispatcher.py** | `xmuse/multi_lane_dispatcher.py` | 213 | Legacy. Builds dispatch plans from old `master_state.json`. |
| **integrated_test_runner.py** | `xmuse/integrated_test_runner.py` | 349 | Legacy. Only used by `scheduler_monitor.sh`. |
| **master_merge_runner.py** | `xmuse/master_merge_runner.py` | 425 | Legacy merge processing. |
| **master_review_runner.py** | `xmuse/master_review_runner.py` | 319 | Legacy review processing. |
| **overnight_runner.sh** | `xmuse/overnight_runner.sh` | 85 | Shell script, legacy multi-round runner. |
| **scheduler_monitor.sh** | `xmuse/scheduler_monitor.sh` | 194 | **Keystone legacy scheduler** — orchestrates all the above scripts. |
| **start_scheduler_monitor.sh** | `xmuse/start_scheduler_monitor.sh` | 36 | Launch wrapper. |
| **god_launcher.sh** | `xmuse/god_launcher.sh` | 194 | Legacy Hermes God launcher (flock-based). |
| **codex_node_launcher.sh** | `xmuse/codex_node_launcher.sh` | 29 | Legacy worker node launcher. |
| **bootstrap_gate.sh** | `xmuse/bootstrap_gate.sh` | 36 | One-off quality gate script. |
| **scripts/inject_frontend_vision_proposal.py** | `xmuse/scripts/inject_frontend_vision_proposal.py` | 338 | One-off injection script. |
| **scripts/inject_frontend_vision_v2.py** | `xmuse/scripts/inject_frontend_vision_v2.py` | 269 | One-off injection script. |
| **self_evolution_checkpoint.py** | `xmuse/self_evolution_checkpoint.py` | 279 | Deprecated — self-evolution monitoring now in `SelfEvolutionController`. |
| **self_evolution_runner.py** | `xmuse/self_evolution_runner.py` | 52 | Deprecated CLI — `SelfEvolutionController` used directly. |
| **xmuse_main.py** | `xmuse/xmuse_main.py` | 24 | Backward compat wrapper for master_loop. |
| **xmuse_error_knowledge.py** | `xmuse/xmuse_error_knowledge.py` | 990 | Standalone error knowledge file, not imported by current production code. |
| **error_knowledge.py** | `xmuse/error_knowledge.py` | 252 | Standalone error knowledge file. |
| **auto_discovery.py** | `xmuse/auto_discovery.py` | 470 | **ACTIVE** — still called by `master_loop.py` as subprocess. |
| **runner_supervisor.py** | `xmuse/runner_supervisor.py` | 63 | **ACTIVE** — thin CLI wrapper for core runner supervisor. |

**Total legacy lines in `xmuse/`**: ~5,700 lines of code across 22 files + 2 directories of runtime data.

### 1.3 Legacy Core Library Modules

| Component | Path | Lines | Status |
|---|---|---|---|
| **sidecar/** | `src/xmuse_core/sidecar/` (8 files) | ~700 | **DORMANT** — no runtime callers, only test importers. `memoryos_adapter.py` contains LiveMemoryOSSidecarAdapter with zero production callers. |
| **hermes/** | `src/xmuse_core/hermes/` (6 files) | ~800 | **ACTIVE-BY-DEPENDENCY-ONLY** — only imported by `xmuse/hermes_hardening.py` (itself legacy). No active `platform.*` or `self_evolution.*` code imports hermes. |
| **master_loop_\*** | `src/xmuse_core/platform/master_loop_*.py` (6 files) | ~500 | **ORPHANED** — modules exist but are NOT exported by `platform/__init__.py`. Only directly accessible via import path. |

---

## 2. master_loop / hermes / sidecar / native / Historical Isolation Assessment

### 2.1 master_loop

**Current status**: `xmuse/master_loop.py` (996 lines) is NOT imported by any current production Python code. Its role as platform orchestrator has been supplanted by `xmuse/platform_runner.py` + `src/xmuse_core/platform/orchestrator.py`.

**Still reads legacy env vars**: `XMUSE_REVIEW_GATE` (line 273), `XMUSE_REVIEW_CODEX_CMD` (line 279), `XMUSE_REVIEW_MODEL` (line 280), `XMUSE_REVIEW_TIMEOUT_S` (line 281).

**Callers**: `scheduler_monitor.sh` (line 52), `overnight_runner.sh` (line 52), plus 8 test files.

**Recommendation**: ISOLATE — do not archive until `scheduler_monitor.sh` is archived. The `src/xmuse_core/platform/master_loop_*.py` modules should be quarantined since they are no longer part of the public platform API.

### 2.2 hermes

**Current status**: `src/xmuse_core/hermes/` (6 files, ~800 lines) has zero active production importers from `platform.*` or `self_evolution.*`. Only imported via `xmuse/hermes_hardening.py` (itself legacy).

**Callers**: Legacy `xmuse/` scripts only (`master_merge_runner.py`, `master_review_runner.py`, `integrated_test_runner.py`, `hermes_reporter.py`). Shell scripts via `god_launcher.sh`.

**Tests**: `test_hermes_modules.py`, `test_hermes_master_state.py`, `test_hermes_hardening.py`, `test_hermes_reporter.py` (4 files, 4,561 lines total).

**Recommendation**: QUARANTINE. Move to `xmuse/legacy/src/xmuse_core/hermes/` when the legacy `xmuse/` scripts are archived. Tests should follow.

### 2.3 sidecar

**Current status**: `src/xmuse_core/sidecar/` (8 files, ~700 lines) has zero runtime callers. Only test files import it.

- `memoryos_adapter.py` — `LiveMemoryOSSidecarAdapter` and `FakeMemoryOSSidecarAdapter`
- `recall_lab.py` — recall/eval lab
- `replay_packet.py`, `replay_exporter.py` — replay functionality
- `ingest_projection.py`, `taxonomy.py`, `recall_eval.py`

**Callers**: Test files only: `test_sidecar_recall_lab.py`, `test_sidecar_recall_eval.py`, `test_sidecar_replay_exporter.py`, `test_sidecar_replay_packet.py`, `test_sidecar_taxonomy.py`, `test_v6_independent_smoke.py`.

**Recommendation**: ARCHIVE/QUARANTINE. Move to `xmuse/legacy/src/xmuse_core/sidecar/`. These are v6-era recall/eval components from the MemoryOS sidecar integration.

### 2.4 "native" runtime

**Current status**: There is NO `xmuse_core.native` module. No native runtime implementation exists. The file `tests/xmuse/test_native_historical_isolation.py` is misnamed — it tests Ray fallback behavior via importlib, not a native runtime.

**Recommendation**: RETAIN the test file but RENAME to clarify it tests Ray fallback. A native runtime implementation is a post-Path-A concern.

### 2.5 Historical test isolation

| Legacy Test Module | Files | Lines | Status |
|---|---|---|---|
| test_master_loop*.py | 8 files | 1,860 | Tests legacy `xmuse/master_loop.py`. Still collect/pass but test deprecated code. |
| test_hermes_*.py | 4 files | 4,561 | Tests `src/xmuse_core/hermes/*`. Active-but-legacy. |
| test_sidecar_*.py | 5 files | 1,243 | Tests dormant `src/xmuse_core/sidecar/*`. |
| test_overnight_runner.py | 1 file | 46 | Tests legacy shell script. |
| test_v6_independent_smoke.py | 1 file | 264 | Tests sidecar modules. Misnamed. |
| test_native_historical_isolation.py | 1 file | 456 | Tests Ray fallback. Misnamed. |

**Total historical test lines**: ~8,430 lines across 20 files.

---

## 3. Package Boundary: `xmuse/` vs `src/xmuse_core/`

### 3.1 Boundary Status: CLEAN

| Criterion | Status | Evidence |
|---|---|---|
| `xmuse/__init__.py` absent | PASS | Does not exist, per AGENTS.md constraint |
| `xmuse/` → `xmuse_core.*` imports | PASS | 111 import statements across all runtime files, all target `xmuse_core.*` |
| `xmuse_core/` → `xmuse.*` imports | PASS | Zero occurrences — core never imports from app layer |
| `xmuse/` → `xmuse/` non-TUI cross-imports | PASS | Runtime root files only import `xmuse_core.*` and stdlib/3rd-party |
| `xmuse/tui/` intra-package imports | NORMAL | Uses fully qualified `xmuse.tui.*` paths. No relative imports. |
| `pyproject.toml` memoryOS deps | PASS | No `memoryos`, `memoryos-lite`, or `memoryos_lite` |
| `uv.lock` memoryOS refs | PASS | Zero matches |
| Boundary test coverage | COMPREHENSIVE | 11 rules in `test_package_boundaries.py` (306 lines), all enforced |

### 3.2 Minor Boundary Findings

| Issue | Location | Assessment |
|---|---|---|
| Stale string ref to `src/memoryos_lite/` | `src/xmuse_core/agents/quality_gate.py:274` | Dead code — directory doesn't exist in standalone repo |
| Stale string ref to `src/memoryos_lite/**` | `xmuse/contracts/knowledge_maintainer_template.json:54` | Dead config — pattern never matches |
| `HANDOFF.md` stale repo path | `xmuse/HANDOFF.md:4` | Still points to `/home/iiyatu/projects/python/memoryOS` |
| `src/memoryos_lite/` in `split-export-manifest.json` | `docs/xmuse/split-export-manifest.json:36` | Correctly listed as memoryOS-owned root (directory doesn't exist in this repo) |

### 3.3 MemoryOSClient is correctly isolated

`src/xmuse_core/agents/memoryos_client.py` defines `MemoryOSClient` — an HTTP client to `http://127.0.0.1:8000`. This is a **protocol adapter**, not a Python import dependency. It follows the allowed pattern from `memoryos-file-separation.md`: optional MemoryOS integration behind explicit URL/protocol adapter. Not a boundary violation.

---

## 4. Large Files and Duplicate Implementation Hotspots

### 4.1 Largest Source Files (>800 lines)

| # | File | Lines | Issue |
|---|---|---|---|
| 1 | `src/xmuse_core/structuring/feature_review_contracts.py` | 1,854 | 35 Pydantic model classes with repetitive validators. Should split into sub-modules. |
| 2 | `xmuse/platform_runner.py` | 1,439 | CLI + health + cleanup + God layer management mixed. |
| 3 | `src/xmuse_core/chat/peer_service.py` | 1,337 | God-class: conversations, MCP calls, proposals, inbox, participants, forks. 58 methods. |
| 4 | `src/xmuse_core/platform/orchestrator.py` | 1,301 | God-class: review gating, takeovers, worktrees, provider bindings, recovery, MCP. 65 methods. |
| 5 | `src/xmuse_core/platform/execution/review_god.py` | 1,168 | All top-level functions. No class organization. |
| 6 | `src/xmuse_core/platform/execution/executor.py` | 1,132 | 3 classes, mixes session logic with provider bindings. |
| 7 | `xmuse/mcp_server.py` | 1,106 | FastAPI server + tool dispatch + schemas. |
| 8 | `xmuse/chat_api.py` | 1,070 | FastAPI server + routes + DB connections. |
| 9 | `src/xmuse_core/structuring/feature_graph_status_store.py` | 1,049 | 49 methods in one class. Manageable but high method count. |
| 10 | `src/xmuse_core/chat/store.py` | 1,047 | ChatStore with 34 methods. |
| 11 | `src/xmuse_core/platform/read_contracts.py` | 1,023 | 43 top-level functions. No class grouping. |
| 12 | `xmuse/dashboard_api.py` | 1,021 | FastAPI server + routes. |
| 13 | `src/xmuse_core/structuring/models.py` | 998 | Model zoo, overlaps conceptually with `feature_review_contracts.py`. |
| 14 | `xmuse/master_loop.py` | 996 | **Legacy** — not active production path. |
| 15 | `src/xmuse_core/platform/run_health.py` | 985 | All top-level functions. Mixes model-building with helpers. |
| 16 | `src/xmuse_core/platform/dashboard_details.py` | 985 | 46 functions, tight coupling to sibling modules. |
| 17 | `xmuse/xmuse_error_knowledge.py` | 990 | **Legacy** — not imported by production code. |
| 18 | `src/xmuse_core/structuring/feature_graph_artifact_store.py` | 971 | 66 methods — highest method count in codebase. |
| 19 | `src/xmuse_core/self_evolution/_controller_runtime.py` | 946 | 50 methods in one class. |
| 20 | `src/xmuse_core/platform/lane_context.py` | 875 | 45 top-level functions. |

### 4.2 Largest Test Files (>1000 lines)

| # | File | Lines | Tests | Note |
|---|---|---|---|---|
| 1 | `test_platform_orchestrator.py` | 9,085 | 235 | Mirrors orchestrator god-class. Largest file in repo. |
| 2 | `test_self_evolution.py` | 3,999 | 68 | Self-evolution integration tests. |
| 3 | `test_dashboard_api.py` | 3,248 | 130 | Dashboard API endpoint tests. |
| 4 | `test_hermes_master_state.py` | 2,434 | — | Hermes master state tests **(legacy)**. |
| 5 | `test_platform_runner.py` | 2,321 | — | Runner integration tests. |
| 6 | `test_chat_api.py` | 2,032 | — | Chat API endpoint tests. |
| 7 | `test_review_plane_orchestrator_integration.py` | 2,025 | — | Integration tests. |
| 8 | `test_feature_graph_status_store.py` | 1,943 | — | Status store tests. |
| 9 | `test_peer_chat_dashboard.py` | 1,610 | — | Peer chat dashboard. |
| 10 | `test_state_normalizer.py` | 1,522 | — | State normalizer tests. |

Total test code: **101,943 lines across 231 test files**.

### 4.3 Hotspot: Duplicate Utility Functions

| Duplicate Pattern | Count | Files | Risk |
|---|---|---|---|
| `_utc_now()` / `utc_now()` / `_utc_timestamp()` | **33** | store.py, participant_store.py, inbox_store.py, stream_store.py, _controller_runtime.py, audit_writer.py, budget/window.py, orchestrator.py, state_machine.py, event_bus.py, +23 more | HIGH — each with slight variations (`replace(microsecond=0)` vs not, `replace("+00:00", "Z")` vs not) |
| `_read_json()` / `read_json()` | **17** | dashboard_details.py, dashboard_audit_details.py, dashboard_graph_authority.py, dashboard_graph_state.py, event_bus.py, state_machine.py, automation_service.py, +10 more | HIGH — different error handling (some catch JSONDecodeError, some don't) |
| `_write_json()` | **4** | event_bus.py, state_machine.py, dashboard_details.py, automation_service.py | MEDIUM — one variant (automation_service.py:51) lacks atomic tmp write |
| `_require_text()` | **12** | god_identity.py, execution_cards.py, takeover_action_refs.py, adapters/base.py, goal_contract.py, +7 more | LOW — trivial validator but still duplicated |

### 4.4 Duplicate `XMUSE_CODEX_MODEL` Reads

Read in **5 independent locations**:
- `src/xmuse_core/chat/driver.py:101`
- `src/xmuse_core/platform/execution/executor.py:748`
- `src/xmuse_core/platform/execution/review_god.py:1165`
- `src/xmuse_core/platform/agent_spawner.py:119`
- `src/xmuse_core/self_evolution/peer_chat_decomposer.py:100`

### 4.5 Multiple `feature_lanes.json` Access Paths

The authoritative `LaneProjectionSyncer` is bypassed by at least **7 other code paths**:
- `xmuse/chat_api.py:516` — `_read_json_file(base_dir / "feature_lanes.json")`
- `xmuse/chat_api.py:558` — writes directly
- `xmuse/master_loop.py:959-967` — own `_read_lanes_json` / `_write_lanes_json`
- `src/xmuse_core/chat/inspector_builder.py:119` — reads directly
- `src/xmuse_core/self_evolution/_controller_runtime.py:676` — own `_read_lanes`
- `src/xmuse_core/self_evolution/evidence/aggregator.py:327` — own `_read_lanes`
- `src/xmuse_core/self_evolution/adapters/lanes_reader.py:25` — lanes_path reader

### 4.6 Multiple Health Check Implementations

| Endpoint | File | Function |
|---|---|---|
| Platform runner health | `xmuse/platform_runner.py:867` | `health_once()` |
| MCP server health | `xmuse/mcp_server.py:1035` | `health()` |
| Chat API health | `xmuse/chat_api.py:588` | `health()` |
| Dashboard API health | `xmuse/dashboard_api.py:106` | `health()` |
| Routing server health | `src/xmuse_core/routing/server.py:38` | `health()` |
| Core health model | `src/xmuse_core/platform/run_health.py` | `build_run_health_model*` |

### 4.7 `chat.db` Path Construction

No centralized function for `chat.db` path — each entry point independently does `xmuse_root / "chat.db"`. Found at:
- `xmuse/chat_api.py:66`
- `xmuse/mcp_server.py:893`
- `xmuse/platform_runner.py:204`
- `src/xmuse_core/platform/dashboard_details.py:200`
- `src/xmuse_core/platform/read_contracts.py:709`
- `src/xmuse_core/chat/store.py:789-793`

---

## 5. MemoryOS-Context Remnants in Docs / History / Fixtures

### 5.1 Rated by Severity

| Severity | File | Issue |
|---|---|---|
| **HIGH** | `xmuse/HANDOFF.md:4` | Stale repo path: `/home/iiyatu/projects/python/memoryOS` |
| **HIGH** | `xmuse/CODEX_GOAL_HANDOFF.md:4` | Stale repo path: `/home/iiyatu/projects/python/memoryOS` |
| **MEDIUM** | `docs/xmuse/session-prompts/` (10 files) | All reference `/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/` — historical completion flags |
| **MEDIUM** | `xmuse/FRONTEND_CONTEXT.md:37-53` | MemoryOS API section with 14 endpoint descriptions (doc is self-marked partly outdated) |
| **MEDIUM** | `xmuse/prompts/master_god_prompt.md:3,33-34` | References "Hermes Master God... MemoryOS" — confirm if actively used |
| **LOW** | `pyproject.toml:4` | Description: "built on MemoryOS" (accurate provenance) |
| **LOW** | `xmuse/approvals/memoryos-redis-cache-probe/` | Directory name — gitignored runtime artifact |
| **LOW** | `tests/fixtures/xmuse/contracts/artifacts/*.json` (2 files) | Worktree path strings containing "memoryOS" — fixture data, not dependency |
| **INFO** | `docs/xmuse/archive/plans/*.md` (3 files) | Historical artifacts with old memoryOS paths — properly archived |
| **INFO** | `docs/xmuse/memoryos-file-separation.md` | Dedicated separation document — by design |
| **INFO** | `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-legacy-coupling-inventory.md` | Legacy coupling inventory — by design |
| **INFO** | `walkthrough-maintenance-notes.md` | 13 memoryOS refs — architecturally correct (describes external memory layer) |

### 5.2 Files With NO MemoryOS References (Clean)

- `docs/xmuse/README.md` — 1 reference to `memoryos-file-separation.md` (correct index)
- `docs/xmuse/解耦开发协议.md` — core architecture doc, clean
- `docs/xmuse/quality-gates-and-provider-matrix.md` — clean
- `docs/xmuse/provider-matrix.md` — clean
- `docs/xmuse/config-matrix.md` — clean (minor: `WORKTREE_BASE` constant has "memoryOS" in path string)
- `docs/xmuse/tui-slash-command-handoff.md` — 1 repo path reference, historical
- `xmuse/FRONTEND_API.md`, `FRONTEND_API_INCREMENTAL.md`, `FRONTEND_IMPLEMENTATION_GUIDE.md`, `FRONTEND_VISION.md` — clean
- `xmuse/god_prompts/*` — clean
- `xmuse/contracts/*` — clean
- All `tests/fixtures/xmuse/contracts/cards/`, `events/`, `interfaces/`, `read_envelopes/` — clean

### 5.3 `xmuse/history/` Contents

| Entry | Size | Type |
|---|---|---|
| 21 entries total | ~1.9 GB | Runtime snapshots, recovery data, old lane projections, feature archives |
| `compact_wsl_vhdx_20260602.ps1` | 1 file | Reference PowerShell script |
| `runtime_archive_2026-05-31_pre_a_b/` | Multiple | Pre-Path-A runtime state |
| Various `*_20260601T*Z/` | Multiple | Outer god recovery, requeue, hard stop data |

All runtime state. Properly gitignored (`xmuse/history/` in `.gitignore`).

---

## 6. Keep / Archive / Isolate / Refactor Priority Table

### 6.1 ARCHIVE (Remove from main path, move to archive)

| Priority | Item | Lines | Depends On |
|---|---|---|---|
| P0 | `xmuse/scheduler_monitor.sh` + `start_scheduler_monitor.sh` | 230 | — |
| P0 | `xmuse/hermes_reporter.py` | 327 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/hermes_loop.py` | 2 | — |
| P0 | `xmuse/slave_job_runner.py` | 591 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/multi_lane_dispatcher.py` | 213 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/integrated_test_runner.py` | 349 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/master_merge_runner.py` | 425 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/master_review_runner.py` | 319 | Archive scheduler_monitor.sh first |
| P0 | `xmuse/hermes_hardening.py` | 856 | Archive all hermes callers first |
| P0 | `xmuse/god_launcher.sh` | 194 | Archive scheduler_monitor.sh + hermes_reporter.py first |
| P0 | `xmuse/codex_node_launcher.sh` | 29 | Archive multi_lane_dispatcher.py first |
| P0 | `xmuse/overnight_runner.sh` | 85 | — |
| P0 | `xmuse/bootstrap_gate.sh` | 36 | — |
| P0 | `xmuse/scripts/inject_frontend_vision_proposal.py` | 338 | — |
| P0 | `xmuse/scripts/inject_frontend_vision_v2.py` | 269 | — |
| P0 | `xmuse/self_evolution_checkpoint.py` | 279 | — |
| P0 | `xmuse/self_evolution_runner.py` | 52 | — |
| P0 | `xmuse/xmuse_main.py` | 24 | — |
| **P0 total** | | **4,618** | |

### 6.2 QUARANTINE (Move to `xmuse/legacy/` subtree, retain for test reference)

| Priority | Item | Lines | Notes |
|---|---|---|---|
| P1 | `src/xmuse_core/sidecar/` (8 files) | ~700 | 5 test files dependent. Move as unit. |
| P1 | `src/xmuse_core/hermes/` (6 files) | ~800 | 4 test files dependent. Move as unit. |
| P1 | `src/xmuse_core/platform/master_loop_*.py` (6 files) | ~500 | Orphaned from public API. 8 test files dependent. |
| P1 | `xmuse/master_loop.py` | 996 | Core legacy orchestrator. 8 test files dependent. |
| P1 | `xmuse/auto_discovery.py` | 470 | Called by master_loop.py; quarantine together. |
| **P1 total** | | **~3,466** | |

### 6.3 ISOLATE (Leave in place but mark as legacy, add boundary tests)

| Priority | Item | Lines | Notes |
|---|---|---|---|
| P2 | `xmuse/xmuse_error_knowledge.py` | 990 | Not imported by production code. Dead code. |
| P2 | `xmuse/error_knowledge.py` | 252 | Not imported by production code. Dead code. |
| P2 | Legacy env vars: `XMUSE_REVIEW_GATE`, `XMUSE_REVIEW_CODEX_CMD`, `XMUSE_REVIEW_MODEL`, `XMUSE_REVIEW_TIMEOUT_S` | — | Still actively read by `master_loop.py`. Document as legacy after archiving master_loop. |
| **P2 total** | | **1,242** | |

### 6.4 REFACTOR (Improve structure without changing behavior)

| Priority | Item | Current State | Action |
|---|---|---|---|
| P3 | `_utc_now()` 29 duplicates | Each file defines its own | Centralize to `src/xmuse_core/runtime/` |
| P3 | `_read_json()` 15 duplicates | Different error handling | Centralize to `src/xmuse_core/runtime/` |
| P3 | `_write_json()` 4 duplicates | Atomic vs non-atomic mix | Centralize, ensure all use atomic write |
| P3 | `feature_lanes.json` 7+ access paths | Some bypass `LaneProjectionSyncer` | Enforce single access point |
| P3 | `chat.db` path 5+ constructions | Not centralized | Centralize path resolution |
| P3 | `XMUSE_CODEX_MODEL` 5 reads | Scattered | Centralize to `runtime/settings.py` |
| P4 | `platform/orchestrator.py` (1,301 lines) | God-class with 65 methods | Split into domain-specific services |
| P4 | `chat/peer_service.py` (1,337 lines) | God-class with 58 methods | Split conversations/MCP/proposals/inbox |
| P4 | `structuring/feature_review_contracts.py` (1,854 lines) | 35 models in one file | Split into domain model files |
| P4 | `structuring/feature_graph_artifact_store.py` (971 lines) | 66 methods in one class | Split into smaller stores |
| P4 | `test_platform_orchestrator.py` (9,085 lines) | Single largest file | Split into focused test modules |

### 6.5 RETAIN (Keep as-is, current main path)

| Item | Lines | Reason |
|---|---|---|
| `xmuse/chat_api.py` | 1,070 | Active entrypoint |
| `xmuse/mcp_server.py` | 1,106 | Active entrypoint |
| `xmuse/platform_runner.py` | 1,439 | Active entrypoint |
| `xmuse/dashboard_api.py` | 1,021 | Active entrypoint |
| `xmuse/tui/` | ~4,000 total | Active TUI application |
| `src/xmuse_core/providers/` | ~2,500 total | Active provider system |
| `src/xmuse_core/chat/` | ~3,500 total | Active chat services |
| `src/xmuse_core/structuring/` | ~5,500 total | Active feature graph system |
| `src/xmuse_core/platform/` (excl. master_loop_*) | ~8,000 total | Active platform services |
| `src/xmuse_core/self_evolution/` | ~3,000 total | Active self-evolution system |
| `src/xmuse_core/agents/` (excl. sidecar) | ~2,500 total | Active agent system |

---

## 7. Codex Follow-Up Task List

### Phase: Installability Remediation (Path A Phase 1)

- [ ] Remove `python-dotenv` from `pyproject.toml` and prune `uv.lock` (zero imports)
- [ ] Run `uv run ruff check . --fix` to auto-fix 41 errors (I001, F401, UP037, UP035, UP012)
- [ ] Fix 2 production F401: `src/xmuse_core/providers/__init__.py:42`, `src/xmuse_core/skills/review_gate.py:11`
- [ ] Fix 33 E501 line-too-long violations (mostly in `xmuse/scripts/`)
- [ ] Fix 4 E741 ambiguous variable name (`l`) violations in scripts

### Phase: Runtime Operations (Path A Phase 2)

- [ ] Update `xmuse/HANDOFF.md:4` — repo path from memoryOS to xmuse
- [ ] Update `xmuse/CODEX_GOAL_HANDOFF.md:4` — same repo path fix
- [ ] Update `pyproject.toml:4` — description to "standalone sibling of memoryOS"
- [ ] Mark or archive `docs/xmuse/session-prompts/` — historical completion flags
- [ ] Archive or purge `xmuse/FRONTEND_CONTEXT.md:37-53` MemoryOS API section
- [ ] Clean `xmuse/history/` (1.9 GB of runtime snapshots — gitignored, safe to delete)

### Phase: Quality Gates (Path A Phase 3)

- [ ] Add full-repo ruff gate baseline with zero-tolerance for new errors
- [ ] Add `uv build` as hard gate
- [ ] Add focused pytest groups as CI gates (start with core models + package boundaries)
- [ ] Add `docs/xmuse/provider-matrix.md` and `config-matrix.md` drift detection tests
- [ ] Add `tests/xmuse/test_quality_gates_phase3.py` enforcement

### Phase: Depth Hardening (Path A Phase 4)

- [ ] Centralize `_utc_now()` to `src/xmuse_core/runtime/` — 29 implementations
- [ ] Centralize `_read_json()` to `src/xmuse_core/runtime/` — 15 implementations
- [ ] Centralize `_write_json()` — ensure all use atomic tmp-file replace
- [ ] Centralize `chat.db` path resolution
- [ ] Centralize `XMUSE_CODEX_MODEL` reads to `runtime/settings.py`
- [ ] Enforce single access point for `feature_lanes.json` (via `LaneProjectionSyncer`)

### Phase: Legacy Code Removal (Post-Path-A)

- [ ] After `scheduler_monitor.sh` archived: archive 10 dependent legacy files (P0 items in §6.1)
- [ ] After legacy scripts archived: quarantine `src/xmuse_core/sidecar/`, `hermes/`, `master_loop_*`
- [ ] After quarantine complete: move `xmuse/master_loop.py` + `auto_discovery.py`
- [ ] After archiving complete: remove ~8,430 lines of corresponding test code
- [ ] After test removal: remove legacy env var references from `docs/xmuse/config-matrix.md`

### Phase: God-Class Refactoring (Low Priority, Post-Path-A)

- [ ] Split `platform/orchestrator.py` (1,301 lines, 65 methods)
- [ ] Split `chat/peer_service.py` (1,337 lines, 58 methods)
- [ ] Split `structuring/feature_review_contracts.py` (1,854 lines, 35 models)
- [ ] Split `structuring/feature_graph_artifact_store.py` (971 lines, 66 methods)
- [ ] Split `test_platform_orchestrator.py` (9,085 lines, 235 tests)

---

## 8. Commands Run and Results

### Environment

```
repo root: /home/iiyatu/projects/python/xmuse
python: 3.11.15 (uv managed)
ruff: 0.15.x (via uv)
```

### Source Exploration Commands

```bash
# File sizes
wc -l src/xmuse_core/**/*.py xmuse/*.py src/xmuse_core/**/**/*.py 2>/dev/null | sort -rn | head -40

# Test file sizes
wc -l tests/xmuse/*.py | sort -rn | head -40

# MemoryOS references in code
rg -n "memoryos|memory_os|MemoryOS" src/xmuse_core/ xmuse/ tests/xmuse/ --type py 2>/dev/null
rg -rn "memoryos|memory_os|MemoryOS" docs/xmuse/ --type md 2>/dev/null

# memoryOS Python imports
rg -n "memoryos.lite\|memoryOS\|memoryos_lite\|from memoryos\|import memoryos" src/xmuse_core/ xmuse/ tests/xmuse/ --type py 2>/dev/null

# n_lite references in source
rg -rn "n_lite\|memoryos_lite\|../memoryOS" src/xmuse_core/ --type py 2>/dev/null

# pyproject.toml dependency check
rg -n "memoryos\|n.lite" pyproject.toml

# Legacy test files
ls tests/xmuse/test_master_loop*.py tests/xmuse/test_hermes_*.py tests/xmuse/test_sidecar_*.py tests/xmuse/test_overnight_runner*.py tests/xmuse/test_native_*.py tests/xmuse/test_v6_*.py 2>/dev/null

# UV lock memoryOS check
rg -i "memory" uv.lock

# Directory listing
ls xmuse/ | head -60
ls src/xmuse_core/sidecar/
ls xmuse/legacy/root-loop/
ls docs/xmuse/ | sort
```

### Audit Commands

```bash
# Ruff lint baseline
uv run ruff check . 2>&1

# Package boundary test
uv run pytest -q tests/xmuse/test_package_boundaries.py 2>&1

# Entry point verification
rg -n "console_scripts\|entry.points" pyproject.toml

# Dead code patterns
rg -c "TODO" src/xmuse_core/ xmuse/ tests/xmuse/ --type py 2>/dev/null
rg -c "FIXME" src/xmuse_core/ xmuse/ tests/xmuse/ --type py 2>/dev/null
```

### Results Summary

| # | Command | Exit | Key Result |
|---|---|---|---|
| 1 | `uv run ruff check .` | 0 | 81 errors (33 E501, 19 I001, 15 F401, 4 E741, etc.) — 40 auto-fixable |
| 2 | `uv build` | 0 | Wheel builds successfully, no memoryOS dependency |
| 3 | `rg -n "memoryos|MemoryOS" src/ --type py` | 0 | Zero memoryOS imports in production code |
| 4 | `rg -rn "memoryos" pyproject.toml uv.lock` | 0 | No memoryOS in dependencies or lock file |
| 5 | Legacy test file count | 0 | 20 files, ~8,430 lines (master_loop, hermes, sidecar, overnight, v6, native) |
| 6 | `python-dotenv` usage check | 0 | Zero imports in any .py file — dead dependency |
| 7 | Large files (>800 lines) | 0 | 20 in `src/xmuse_core/` + 5 in `xmuse/` |
| 8 | Test files (>1000 lines) | 0 | 20 files, largest is `test_platform_orchestrator.py` (9,085 lines) |

---

## Appendix: Key Facts

- **Total code lines**: src/xmuse_core/~57,284 + xmuse/~14,707 + tests/~101,943 = ~174,000
- **Total test files**: 231 in `tests/xmuse/`
- **Legacy lines to archive**: ~5,700 (xmuse/ scripts) + ~3,500 (quarantine candidates) = ~9,200
- **Legacy env vars to deprecate**: 10 (all XMUSE_MONITOR_*, XMUSE_LOOP_ROOT, XMUSE_REPORT_ONLY, XMUSE_CODEX_IDLE_TIMEOUT_SECONDS, XMUSE_CODEX_ATTEMPT, XMUSE_CODEX_REASONING_EFFORT, XMUSE_MAX_HOURS)
- **Active env vars to retain**: XMUSE_REVIEW_GATE, XMUSE_REVIEW_CODEX_CMD, XMUSE_REVIEW_MODEL, XMUSE_REVIEW_TIMEOUT_S (all in master_loop.py — legacy but still active)
- **Dead dependency**: `python-dotenv` (declared in pyproject.toml, zero imports)
- **Duplicate utility functions**: _utc_now / _utc_timestamp (33x), _read_json (17x), _require_text (12x), _write_json (4x)
- **Multiple feature_lanes.json access paths**: 7+
- **Disk cleanup opportunity**: ~1.9 GB in `xmuse/history/`
- **Package boundary**: Clean — no violations
- **MemoryOS refs in current code**: Protocol adapter only (`MemoryOSClient` HTTP client), no Python import dependencies
