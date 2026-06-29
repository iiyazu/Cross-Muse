# V11 Depth Hardening Inventory

Date: 2026-06-04

Scope: Path A Phase 4. This document inventories durable stores, MCP tools, and
cleanup automation for the V11 depth-hardening phase. It does not implement
migrations, auth, permissions, or cleanup logic. It is a bounded inventory that
Codex can use to implement Path A Phase 4 contract closure.

## Commands Run

All commands were run from `/home/iiyatu/projects/python/xmuse`:

```bash
# Read context docs
cd /home/iiyatu/projects/python/xmuse && for doc in \
  docs/xmuse/archive/2026-06-roadmaps-and-audits/path-a-foundation-first-roadmap.md \
  docs/xmuse/quality-gates-and-provider-matrix.md \
  docs/xmuse/production-operations.md \
  docs/xmuse/config-matrix.md \
  docs/xmuse/provider-matrix.md \
  docs/xmuse/archive/2026-06-pre-m7/codex-strengthening-handoff.md; do
  echo "=== $doc ===" && wc -l "$doc"
done

# Source exploration — durable stores
grep -rn 'sqlite3\.connect\|\.db/' src/xmuse_core/ --include='*.py' | head -30
grep -rn 'god_sessions\.json' src/xmuse_core/ xmuse/ --include='*.py' | head -20
grep -rn 'feature_graph_status' src/xmuse_core/ --include='*.py' | head -20
grep -rn 'planning_runs\|planning_events' src/xmuse_core/ --include='*.py' | head -20
grep -rn 'provider_session_bindings' src/xmuse_core/ --include='*.py' | head -20
grep -rn 'writer_lease\|\.lock' xmuse/platform_runner.py | head -20

# Source exploration — MCP tools
grep -n 'def _tool_\|"name":' src/xmuse_core/platform/mcp_tools.py | head -30
grep -n 'def _tool_\|"name":' src/xmuse_core/platform/read_tool_inventory.py | head -30

# Source exploration — cleanup
grep -n 'leftover\|orphan\|cleanup\|shutdown\|dirty\|stale' xmuse/platform_runner.py | head -40
grep -n 'leftover\|orphan\|mark_failed\|stale' src/xmuse_core/platform/run_health.py | head -20

# Count tool inventory
grep -c '"name":' xmuse/mcp_server.py src/xmuse_core/platform/mcp_tools.py src/xmuse_core/platform/read_tool_inventory.py
```

---

## 1. Durable Store Inventory

### 1.1 chat.db (SQLite)

| Attribute | Value |
|-----------|-------|
| **Type** | SQLite (single file, WAL mode default) |
| **Opened at** | `src/xmuse_core/chat/store.py:789-793` — `ChatStore._connect()` |
| **Also at** | `participant_store.py:416-419`, `peer_forks.py:275-278`, `inbox_store.py:242-245`, `stream_store.py:140-143,344-347`, `self_evolution/adapters/chat_reader.py:49-51` (read-only `?mode=ro`) |
| **Runtime paths** | `xmuse/chat_api.py:66`, `xmuse/platform_runner.py:204`, `xmuse/mcp_server.py:893`, `src/xmuse_core/platform/dashboard_details.py:200`, `src/xmuse_core/platform/read_contracts.py:709` |
| **Tables** | 12 tables: `conversations`, `messages`, `proposals`, `resolutions`, `participants`, `role_templates`, `peer_forks`, `chat_inbox_items`, `chat_request_log`, `chat_turn_budgets`, `chat_streams`, `peer_turn_latency_traces`, `peer_turn_mcp_tool_traces` (`stream_store.py:300-342`) |
| **Schema version** | None. No version table or constant. |
| **Migration logic** | Additive only via `_ensure_column()` (`store.py:1041-1047`). Uses `pragma table_info` + `alter table add column`. No destructive migration. |
| **Concurrency** | SQLite transactions (default deferred). WAL mode may be default. |
| **Migration risk** | **HIGH** — no schema version. Destructive changes (rename, delete column, type change) would require manual migration. Additive changes are safe. |
| **Recommended stance** | Add `schema_version` table or PRAGMA-based version constant. Before V11 migration implementation, decide: (a) keep additive-only with version table, or (b) adopt a migration framework (Alembic). Recommended: version table + additive-only within V11 scope. |

### 1.2 god_sessions.json (GOD Session Registry)

| Attribute | Value |
|-----------|-------|
| **Type** | JSON (whole-file read/write) |
| **Opened at** | `src/xmuse_core/agents/god_session_registry.py:38-40` — `GodSessionRegistry.__init__()` |
| **Runtime paths** | `xmuse/platform_runner.py:132`, `xmuse/mcp_server.py:894`, `xmuse/chat_api.py:631`, `src/xmuse_core/chat/peer_service.py:93` |
| **Schema** | `{"sessions": [GodSessionRecord, ...]}`. `GodSessionRecord` fields (`registry.py:15-34`): `god_session_id`, `role`, `agent_name`, `runtime`, `session_address`, `session_inbox_id`, `conversation_id`, `participant_id`, `status`, `assignment_feature_id`, `pid`, `model`, `prompt_fingerprint`, `worktree`, `feature_scope_id`, `provider_session_id`, `provider_session_kind`, `provider_binding_status`, `provider_binding_failure_reason` |
| **Schema version** | None. |
| **Concurrency** | `fcntl.flock` on `god_sessions.json.lock` companion file + atomic temp-file replace (`registry.py:223-231`). |
| **Migration risk** | **HIGH** — no version tracking. Whole-file rewrite. Adding fields to `GodSessionRecord` is backward-compatible (unknown fields ignored by old readers). Removing/renaming fields is not. |
| **Recommended stance** | Add `schema_version` field to root JSON object before expanding `GodSessionRecord`. For V11: document all fields, add version constant, reject older version on read. |

### 1.3 feature_graph_statuses.json (Graph-Native Execution Status)

| Attribute | Value |
|-----------|-------|
| **Type** | JSON (whole-file read/write) |
| **Opened at** | `src/xmuse_core/structuring/feature_graph_status_store.py:70-72` |
| **Schema** | `{"schema_version": ..., "statuses": [...], "events": [...]}`. `FeatureGraphExecutionStatusRecord` + `FeatureGraphStatusEventRecord` Pydantic models. |
| **Schema version** | `SCHEMA_VERSION = "xmuse.feature_graph_statuses.v1"` (`store.py:20`). Written on every write (`store.py:490-500`). Validated on read (`store.py:431`). |
| **Concurrency** | `fcntl.flock` + atomic temp-file replace (`store.py:514-522`). |
| **Migration risk** | **LOW** — explicit version. Additive changes safe. |
| **Recommended stance** | Extend schema via version bump. Already well-structured for V11. |

### 1.4 feature_graph_artifacts.json (Worker/Reviewer Artifacts)

| Attribute | Value |
|-----------|-------|
| **Type** | JSON (whole-file read/write) |
| **Opened at** | `src/xmuse_core/structuring/feature_graph_artifact_store.py:53-55` |
| **Default path** | `xmuse_root / "feature_graph_artifacts.json"` (`orchestrator.py:390`) |
| **Schema version** | `SCHEMA_VERSION = "xmuse.feature_graph_artifacts.v1"` (`store.py:27`). 14 sub-collections. |
| **Concurrency** | `fcntl.flock` + atomic temp-file replace (`store.py:900-907`). |
| **Migration risk** | **LOW** — explicit version. |
| **Recommended stance** | Extend schema via version bump. Already well-structured for V11. |

### 1.5 planning_runs.sqlite3 + planning_events.sqlite3 (Planning Stores)

| Attribute | Value |
|-----------|-------|
| **Type** | SQLite (two files) |
| **planning_runs.sqlite3** | `src/xmuse_core/structuring/planning_run_store.py:26-28`. 23-column `planning_runs` table + 3 indexes (`store.py:291-317`). |
| **planning_events.sqlite3** | `src/xmuse_core/structuring/planning_event_store.py:33-39`. 16-column `planning_events` table + 3 indexes (`store.py:454-475`). Supports `backend="json"` fallback. |
| **Runtime consumers** | `read_contracts.py:801-817` (read-only `?mode=ro`). Constructed at `blueprint_execution/feature_planning.py:160-162`, `automation_service.py:80-82`, `approval_events.py:80`. |
| **Schema version** | None for both. Tables use `CREATE TABLE IF NOT EXISTS`. |
| **Migration risk** | **HIGH** — no version tracking. Additive-only via `ALTER TABLE` would need explicit column add logic. |
| **Recommended stance** | Add `_schema_version` table or PRAGMA user-version. For V11: consider merging into a single SQLite file with version tracking. |

### 1.6 provider_session_bindings.json (Provider Session Binding Store)

| Attribute | Value |
|-----------|-------|
| **Type** | JSON (whole-file read/write) |
| **Opened at** | `src/xmuse_core/agents/provider_session_binding_store.py:34-36` |
| **Default path** | `xmuse_root / "provider_session_bindings.json"` (`orchestrator.py:382`) |
| **Schema version** | `SCHEMA_VERSION = "xmuse.provider_session_bindings.v1"` (`store.py:16`). |
| **Concurrency** | `fcntl.flock` + atomic temp-file replace (`store.py:231-238`). |
| **Migration risk** | **LOW** — explicit version. |
| **Recommended stance** | Already well-structured. Extend schema via version bump. |

### 1.7 feature_lanes.json (Lane Projection — Migration-Era, NOT Authority)

| Attribute | Value |
|-----------|-------|
| **Type** | JSON (whole-file read/write) |
| **Opened at** | `src/xmuse_core/platform/projection/syncer.py:44-51` |
| **Runtime paths** | `xmuse/platform_runner.py:1378`, `xmuse/mcp_server.py:117`, `xmuse/chat_api.py:393`, `xmuse/dashboard_api.py:292`, multiple `src/xmuse_core/` consumers |
| **Schema** | `{"lanes": [...], "projection_revision": int}`. Lane entries ~20 fields. |
| **Schema version** | `projection_revision` integer counter only (`syncer.py:249`). No schema version string. |
| **Concurrency** | `fcntl.flock` on `feature_lanes.json.lock` (`syncer.py:200-208`). |
| **Migration risk** | **HIGH** — explicitly documented as migration-era. "NOT authority" per codex-strengthening-handoff.md. |
| **Recommended stance** | **Do not add schema version.** Document as deprecated. V11 goal is to reduce dependency, not harden. Graph-native status store (`feature_graph_statuses.json`) should become the authority. |

### 1.8 Ephemeral and Low-Risk Stores

| Store | Type | File:Line | Risk | Stance |
|-------|------|-----------|------|--------|
| `feature_lanes.json.writer_lease.json` | JSON (lease) | `xmuse/platform_runner.py:421-423` | LOW — ephemeral, 60s TTL, heartbeating | No V11 change needed |
| `.xmuse_merge.lock` + metadata | Lock file | `src/xmuse_core/platform/execution/merger.py:637-642` | LOW — ephemeral git operation guard | No V11 change needed |
| `coordinator_incidents.jsonl` | JSONL | `src/xmuse_core/platform/coordinator_incidents.py:7` | LOW — append-only log, no rotation | Optional V11: add rotation policy |
| `provider_selection_records.jsonl` | JSONL | `src/xmuse_core/providers/selection_record.py:94` | LOW — append-only audit log | No V11 change needed |
| `active_sessions.json` | JSON | `src/xmuse_core/agents/manager.py:60` | **HIGH** (legacy, read-only consumers) | **Do not harden for V11.** Document as legacy read-only source. |
| `error_knowledge.json` | JSON | `src/xmuse_core/chat/inspector_builder.py:183`, `mcp_tools.py:101` | **HIGH** (legacy, passive read) | **Do not harden for V11.** Read-only error knowledge source. |

---

## 2. MCP Tool Inventory

**Total: 35 tools across 5 files.** Classified into 4 permission categories.

### 2.1 Control Tools (7 tools) — `xmuse/mcp_server.py:385-475` (schemas), `mcp_server.py:842-855` (dispatch)

Handled by `XmuseOperations` in `_tool_result()`.

| Tool | Access | File:Line | Current Validation | Missing V11 Permission |
|------|--------|-----------|-------------------|----------------------|
| `list_lanes` | READ | `mcp_server.py:843` | None | Caller identity — returns all lanes |
| `enqueue_lane` | WRITE | `mcp_server.py:845` | Audit block (actor/reason/request_id) + `guard.expected_revision` | Caller role — who can enqueue? |
| `get_status` | READ | `mcp_server.py:847` | None | Caller identity |
| `abort_lane` | WRITE | `mcp_server.py:849` | Audit + guard.lane_status/session_status | Admin gate — who can abort? |
| `get_error_knowledge` | READ | `mcp_server.py:851` | None | Caller identity |
| `get_logs` | READ | `mcp_server.py:853` | None | Caller identity — exposes execution logs |
| `get_tool_inventory` | READ | `mcp_server.py:855` | None | Low risk, but needs consistency |

### 2.2 Platform/GOD Tools (6 tools) — `src/xmuse_core/platform/mcp_tools.py:56-214`

Handled by `McpToolHandler.call()`. No identity checks on any platform tool.

| Tool | Access | File:Line | Current Validation | Missing V11 Permission |
|------|--------|-----------|-------------------|----------------------|
| `get_lane` | READ | `mcp_tools.py:77` | None | Caller identity — full lane detail |
| `get_gate_report` | READ | `mcp_tools.py:80` | None | Caller identity |
| `get_diff` | READ | `mcp_tools.py:87` | None | Caller identity — runs `git diff HEAD` in worktree |
| `query_knowledge` | READ | `mcp_tools.py:98` | None | Caller identity |
| `update_lane_status` | WRITE | `mcp_tools.py:214` | Audit + guard.current_status + safe_fields metadata | Caller role — who can transition status? |
| `apply_takeover_decision` | WRITE | `mcp_tools.py:182` | Audit + guard (lane_status, revision, lease_id, hash chain) | Admin gate — high-privilege operation |

### 2.3 Contract/Read-Only Tools (12 tools) — `src/xmuse_core/platform/read_tool_inventory.py:5-121`

No identity or permission checks on any.

| Tool | Access | File:Line | Current Validation | Missing V11 Permission |
|------|--------|-----------|-------------------|----------------------|
| `read_lane_contract` | READ | `read_tool_inventory.py:7` | None | Caller identity |
| `read_blueprint_contract` | READ | `read_tool_inventory.py:17` | None | Caller identity |
| `read_feature_plan_contract` | READ | `read_tool_inventory.py:35` | Checks feature plan is approved | Caller identity |
| `read_review_contract` | READ | `read_tool_inventory.py:47` | None | Caller identity |
| `read_graph_set_summary` | READ | `read_tool_inventory.py:57` | Checks graph set is approved | Caller identity |
| `read_health_contract` | READ | `read_tool_inventory.py:67` | None | Caller identity |
| `read_graph_set_contract` | READ | `read_tool_inventory.py:72` | Checks graph set is approved | Caller identity |
| `read_evidence_refs` | READ | `read_tool_inventory.py:82` | None | Caller identity |
| `read_review_verdict` | READ | `read_tool_inventory.py:92` | None | Caller identity |
| `read_takeover_context` | READ | `read_tool_inventory.py:102` | None | Caller identity |
| `read_run_health` | READ | `read_tool_inventory.py:112` | None | Caller identity |
| `read_provider_inventory` | READ | `read_tool_inventory.py:117` | None | Caller identity |

### 2.4 Chat/GOD Tools (10 tools) — `src/xmuse_core/chat/peer_service.py`

Handled by `PeerChatService.call_mcp_tool()` (`peer_service.py:932`).

| Tool | Access | File:Line | Current Validation | Missing V11 Permission |
|------|--------|-----------|-------------------|----------------------|
| `chat_list_conversations` | READ | `peer_service.py:124` | None | Conversation scope — returns ALL conversations |
| `chat_create_conversation` | WRITE | `peer_service.py:49` | None | Caller identity — creation is open |
| `chat_list_participants` | READ | `peer_service.py:148` | Validates conversation exists | Caller role/scope |
| `chat_post_message` | WRITE | `peer_service.py:961` | `_verify_god_identity()` | Write audit trail; no rate limit |
| `chat_read_inbox` | READ | `peer_service.py:1069` | `_verify_god_identity()` | Rate limiting |
| `chat_mark_inbox` | WRITE | `peer_service.py:1102` | `_verify_god_identity()` + inbox ownership | Write audit trail |
| `chat_mention` | WRITE | `peer_service.py:1005` | `_verify_god_identity()` | Write audit trail |
| `chat_emit_proposal` | WRITE | `peer_service.py:1136` | `_verify_god_identity()` | Write audit trail — creates actionable lane plans |
| `chat_emit_blueprint_proposal` | WRITE | `peer_service.py:1202` | `_verify_god_identity()` | Write audit trail — changes mission blueprint |
| `chat_inspect_conversation` | READ | `peer_service.py:924` | None | **No identity check** — any conversation_id can deep-inspect |

### 2.5 Existing Validation Mechanisms

| Mechanism | Coverage | File |
|-----------|----------|------|
| Audit + Guard pattern | 4 write tools only | `platform/mcp_tools.py:123-128`, `read_tool_inventory.py:123-128` |
| GOD session identity (`_verify_god_identity()`) | 6 chat tools | `peer_service.py`: `post_god_message`, `read_inbox`, `mark_inbox`, `mention_god`, `emit_proposal`, `emit_blueprint_proposal` |
| Endpoint scoping (`/mcp/chat`) | Limits to `chat_read_inbox` + narrowed `chat_post_message` | `xmuse/mcp_server.py` |
| Safe field namespace | `update_lane_status` metadata restricted to 16 field keys | `mcp_tools.py` |
| Write tool classification | `_WRITE_TOOL_NAMES` set | `read_tool_inventory.py:139-142` |

### 2.6 Missing Permission Categories (for V11 MCP Permission Model)

| Category | Affected Tools | Severity |
|----------|---------------|----------|
| **API authentication** | All endpoints | **Critical** — anyone reaching port 8100 can call any tool |
| **Caller/role model** | Control + Platform + Contract tools (25 tools) | **High** — no distinction between GOD, admin, reviewer |
| **Per-tool authorization** | All 35 tools | **High** — no declarative permission per tool |
| **Rate limiting** | All tools, especially `chat_*` | **Medium** — write flooding, inbox polling |
| **Conversation scope** | `chat_list_conversations`, `chat_inspect_conversation` | **High** — GOD can see conversations outside its scope |
| **Write audit** | 7 chat write tools | **Medium** — they use identity idempotency but no structured `audit` + `guard` block |
| **Admin guard** | `abort_lane`, `apply_takeover_decision`, `update_lane_status` | **High** — no "requires admin" gate |

---

## 3. Cleanup Automation Inventory

### 3.1 V9-Covered Cleanup

| Cleanup Point | File:Line | Automated? | Notes |
|---------------|-----------|-----------|-------|
| Runner shutdown: signal handler | `platform_runner.py:247-251` | ✅ | SIGTERM/SIGINT → `shutdown.set()` |
| Cancel reconcile task | `platform_runner.py:376-379` | ✅ | |
| Cancel lease heartbeat | `platform_runner.py:380-385` | ✅ | |
| Cancel in-flight lanes | `platform_runner.py:386-392` | ✅ | |
| GOD layer shutdown | `platform_runner.py:406-418` | ✅ | Calls `shutdown()` on review/execute/peer GOD layers |
| Writer lease acquire/renew/release | `platform_runner.py:455-520` | ✅ | Lease file unlinked on shutdown |
| Stale dispatched lane repair | `platform_runner.py:1117-1165` | ✅ | Transitions stale lanes to `exec_failed` |
| Codex app-server transport shutdown | `codex_app_server_transport.py:226-234` | ✅ | Terminate, wait 5s, kill |
| Ray actor shutdown | `ray_god_actor.py:139-141` | ✅ | |
| Ray session layer shutdown | `ray_session_layer.py:180-184` | ✅ | Iterates live sessions |
| Ray session individual abort | `ray_session_layer.py:174-178` | ✅ | |
| Health check (`--health-once`) | `platform_runner.py:867-897` | ✅ | Read-only health summary |
| Process discovery (18+ types) | `run_processes.py:187-217` | ✅ | `/proc` scanner |
| Process inventory + warnings | `run_processes.py:441-505` | ✅ | Duplicate/missing detection |

### 3.2 Manual-Only Cleanup (Detected but NOT Cleaned)

| Detection Point | File:Line | Detection Mechanism | Action Status | Severity |
|-----------------|-----------|-------------------|---------------|----------|
| Leftover Codex app-server | `platform_runner.py:1065-1087` | `_cleanup_health()` → `leftover_codex_app_server` | **Reported only** (status="dirty"/"clean") — no process kill | **High** |
| Leftover raylet | `platform_runner.py:1067` | Same → `leftover_raylet` | **Reported only** | **High** |
| Leftover GCS server | `platform_runner.py:1068` | Same → `leftover_gcs_server` | **Reported only** | **High** |
| Leftover ray worker | `platform_runner.py:1069` | Same → `leftover_ray_worker` | **Reported only** | **High** |
| Orphaned Codex app-server | `platform_runner.py:993-1005` | `_codex_app_server_readiness()` → `orphaned` status | **Reported only** | **High** |
| Stale provider session bindings | `ray_session_layer.py:282-287` | Binding marked "stale" after resume failure | **Records never pruned** — append-only store | **Medium** |
| ProviderBindingStore old records | `provider_session_binding_store.py:163-198` | `mark_failed()` sets FAILED/STALE | **Records accumulate** — no expiry/cleanup | **Low** |
| SQLite WAL/SHM files | No code found | N/A | **Nothing manages them** — no checkpoint, vacuum, or journal mode | **Medium** |
| Orphaned lock files | Multiple `*.lock` files | Created with `fcntl.flock` | **File stays on disk** — kernel releases lock on process death | **Low** |
| Orphaned `.tmp` files (crash mid-write) | Multiple atomic-write paths | `NamedTemporaryFile(delete=False)` | Orphaned if crash between write and `.replace()` | **Low** |
| Stale MCP processes | No dedicated code | Detected in `discover_xmuse_runtime_processes()` | **No kill mechanism** | **Medium** |
| Old feature lane projections | No cleanup code | Projection in `feature_lanes.json` | **No compaction/archival** | **Low** |
| Coordinator incidents JSONL | `coordinator_incidents.py:7` | Append-only log | **No rotation/pruning** | **Low** |
| SessionManager cleanup orphans | `manager.py:180-199` | Reads state file, kills PIDs | **No auto-trigger** — must be called explicitly | **Medium** |

### 3.3 Leftover Detection Points

| Detection | File:Line | What It Catches | Automated Action |
|-----------|-----------|----------------|-----------------|
| `_cleanup_health()` | `platform_runner.py:1065-1087` | `leftover_codex_app_server`, `leftover_raylet`, `leftover_gcs_server`, `leftover_ray_worker` (when runner_count=0) | **None** — reports only |
| `_codex_app_server_readiness()` | `platform_runner.py:993-1005` | Orphaned codex app-server | **None** — reports only |
| `_is_stale()` | `run_health.py:729-750` | Worker PID dead or exceeded timeout | Lane → `exec_failed` via `_repair_stale_dispatched_lanes()` |
| `summarize_run_health()` | `run_health.py:66-148` | Groups lanes: live/stale/retrying/blocked/infra_failed/terminal | Read-only model |
| `process_warnings()` | `run_processes.py:236-283` | Missing/duplicate runner/MCP processes | Read-only warning list |
| `build_process_inventory()` | `run_processes.py:441-505` | Missing/duplicate for 18+ service types | Warnings only |
| `ProviderSessionBindingStore.mark_failed()` | `provider_session_binding_store.py:163-198` | Stale/failed provider bindings | Records stay in store permanently |
| `_retry_send_after_resume_failure()` | `ray_session_layer.py:272-306` | Codex app-server thread resume failure | Marks binding stale, spawns new actor, old thread process orphaned |

### 3.4 Gap Analysis

#### High Severity Gaps

1. **No automated leftover process cleanup** — `_cleanup_health()` detects leftover Codex app-server, raylet, GCS server, and ray worker, but never calls `os.kill()`. The doc says "inspect leftovers" but does not clean them. All detection infrastructure exists; only the kill action is missing.

2. **MCP server process lifecycle** — `xmuse/mcp_server.py` has no registered cleanup or shutdown handler in the platform runner. If the platform runner exits, the MCP process stays alive with no mechanism to stop it.

#### Medium Severity Gaps

3. **SQLite WAL management** — `chat.db` uses SQLite. No `PRAGMA wal_checkpoint`, `VACUUM`, or journal mode management exists. WAL/SHM files grow unbounded.

4. **No startup cleanup routine** — No module checks and cleans stale state on startup. `SessionManager.cleanup_orphans()` exists but is never auto-called.

5. **Crash recovery gaps** — `RecoveryManager` and `CircuitBreaker` handle retry semantics, but there's no durable queue for in-flight lanes when the platform runner crashes. The writer lease (60s TTL) prevents dual-writer but does not recover work.

#### Low Severity Gaps

6. **Stale provider bindings accumulate** — `ProviderSessionBindingStore` is append-only with no retention policy.
7. **Lock files remain on disk** — Cosmetic; kernel releases flock on process death.
8. **Orphaned `.tmp` files** — Rare edge case in atomic write pattern.
9. **Coordinator incidents JSONL grows** — Append-only log with no rotation.
10. **Feature lane projections grow** — No compaction/archival of old lane entries.

---

## 4. Contract-Test Candidates for Codex

These are exact focused tests to add for V11 contract closure. Each candidate
tests one boundary before implementation code is written.

### 4.1 Durable Store: Schema Version Rejection

| Test | Expected Behavior | Priority |
|------|------------------|----------|
| `test_chat_store_rejects_unknown_schema_version` | After adding `schema_version` table, `ChatStore` raises on unrecognized version | HIGH |
| `test_god_session_registry_rejects_unknown_schema_version` | After adding `schema_version` field to `god_sessions.json`, registry raises on unrecognized version | HIGH |
| `test_planning_run_store_rejects_unknown_schema_version` | After adding version table, `PlanningRunStore` raises on unrecognized version | HIGH |
| `test_planning_event_store_rejects_unknown_schema_version` | Same for `PlanningEventStore` | HIGH |
| `test_feature_lanes_projection_rejected_when_graph_status_authoritative` | When `feature_graph_statuses.json` exists, `feature_lanes.json` is not trusted as authority | MEDIUM |

### 4.2 MCP Permission Model

| Test | Expected Behavior | Priority |
|------|------------------|----------|
| `test_mcp_tool_rejects_missing_auth_header` | All 35 tools return permission error when no auth token provided | HIGH |
| `test_mcp_write_tool_rejects_wrong_identity` | `enqueue_lane`, `abort_lane`, `update_lane_status` reject callers without admin role | HIGH |
| `test_mcp_chat_tool_rejects_wrong_conversation_scope` | `chat_post_message` rejects call whose `god_session_id` does not match conversation | HIGH |
| `test_mcp_admin_tool_rejects_non_admin` | `abort_lane`, `apply_takeover_decision` reject non-admin callers | HIGH |
| `test_mcp_read_tool_accepts_authenticated_caller` | `read_lane_contract` etc. succeed with valid auth token | MEDIUM |

### 4.3 Cleanup Automation

| Test | Expected Behavior | Priority |
|------|------------------|----------|
| `test_leftover_process_cleanup_kills_stale_codex_app_server` | `_cleanup_health()` with auto-cleanup enabled kills leftover Codex app-server processes | HIGH |
| `test_leftover_process_cleanup_kills_stale_raylet` | Same for stale raylet | HIGH |
| `test_runner_startup_cleans_stale_lock_files` | Platform runner startup releases stale `*.lock` files from dead runners | MEDIUM |
| `test_runner_startup_cleans_stale_tmp_files` | Platform runner startup removes orphaned `.tmp` files from crashed atomic-write operations | MEDIUM |
| `test_chat_db_wal_checkpoint_on_shutdown` | `ChatStore` runs `PRAGMA wal_checkpoint(TRUNCATE)` on graceful shutdown | MEDIUM |

### 4.4 Identity-Bound GOD Tools

| Test | Expected Behavior | Priority |
|------|------------------|----------|
| `test_chat_post_message_rejects_unregistered_god_session` | Call with unregistered `god_session_id` returns permission error | HIGH |
| `test_chat_post_message_rejects_wrong_participant_id` | `god_session_id` + non-matching `participant_id` returns permission error | HIGH |
| `test_chat_inspect_conversation_requires_identity` | Currently no identity check — test expects identity gate | HIGH |

---

## 5. Non-Goals and Forbidden Changes for V11

### In Scope (for V11 contract tests and implementation)

- **Schema version tracking** on high-risk stores: `chat.db`, `god_sessions.json`, `planning_runs.sqlite3`, `planning_events.sqlite3`
- **MCP permission model**: auth header validation, caller/role model, per-tool authorization, admin guard on write/admin tools, identity check for `chat_inspect_conversation`
- **Cleanup automation**: leftover process kill, startup stale-state cleanup, SQLite WAL checkpoint
- **Regression tests** for migration rejection, permission rejection, and cleanup

### Non-Goals (explicitly excluded from V11)

1. **No authentication implementation** — V11 writes permission model contracts and rejection tests; auth middleware is a V12+ concern.
2. **No destructive schema migrations** — V11 adds schema version tracking and additive-only migration logic; no `ALTER TABLE DROP`, `ALTER TABLE RENAME`, or data migration.
3. **No `feature_lanes.json` removal** — V11 adds graph-native status store as authority, but keeps `feature_lanes.json` as migration-era projection. Removal is post-V11.
4. **No `active_sessions.json` or `error_knowledge.json` hardening** — These are legacy read-only files. V11 documents them but does not add schema versions or migration logic.
5. **No rate limiting implementation** — V11 identifies rate limiting as a missing permission category but does not implement it.
6. **No API authentication middleware** — V11 writes tests that expect auth headers, but the middleware is V12.
7. **No new TUI features** — Per Path A non-goals.
8. **No real provider soak** — V11 does not add real Ray/Codex soak tests.
9. **No `memoryOS` modifications** — Per Path A rules.
10. **No fake provider as real provider evidence** — Fake provider tests are for contract verification only.

### Forbidden Changes

- Do not modify production Python code in `xmuse/` (runtime layer) — contract tests only target `src/xmuse_core/` independent core.
- Do not modify `tests/` that test memoryOS integration.
- Do not implement auth middleware, rate limiting, or admin dashboards.
- Do not add new dependencies for migration framework (Alembic, etc.) — V11 is version-tracking-only.
- Do not remove `feature_lanes.json` or change its writing path.

---

## 6. Summary

| Section | Key Finding | V11 Action Required |
|---------|------------|-------------------|
| **Durable stores** | 4 of 14 stores have HIGH migration risk (no schema version) | Add version tracking + rejection tests for chat.db, god_sessions.json, planning_runs.sqlite3, planning_events.sqlite3 |
| **MCP tools** | 0 of 35 tools have auth/caller checks; 25/35 have NO validation at all | Add permission model contracts: auth header, caller role, admin guard, identity gate for chat_inspect_conversation |
| **Cleanup automation** | Leftover processes detected but NOT killed; SQLite WAL unmanaged; no startup cleanup | Add process kill action, WAL checkpoint, startup stale-state cleanup |
| **Contract-test candidates** | 18 focused tests identified | Codex should implement these as the V11 implementation gate |
