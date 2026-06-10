# xmuse Schema Migration Strategy

Date: 2026-06-04

Scope: Path A Phase 4 contract closure. This document defines migration stance,
old-state handling, and cleanup classification. It does not implement destructive
migrations, a migration framework, auth middleware, or a cleanup daemon.

## Inventory Corrections

The V11 inventory was useful but had overclaims:

- `feature_graph_statuses.json`, `feature_graph_artifacts.json`, and
  `provider_session_bindings.json` have a `schema_version` field, but current
  read paths do not consistently reject unknown versions. They are classified as
  version present but unenforced, not fully migration-ready.
- `chat.db` does not enable WAL explicitly in `ChatStore._connect()`. Any WAL
  checkpoint or cleanup policy is future work and must not be assumed.
- Durable artifacts include feature plans, graph sets, lane graphs, audit events,
  and final-action holds. They were missing from the initial inventory and are
  included below.
- Cleanup must distinguish automated cleanup, graceful shutdown, stale lane
  repair, and report-only detection. `leftover_*` health entries are
  report-only detection with `action=report_only`.

Destructive migrations are out of scope; destructive migrations are out of scope
for every V11 default gate. V11 defines contracts only: old state can be
detected and either migrated additively or explicitly rejected.

## Durable Store Matrix

| Store | Authority | Version status | Risk | V11 stance |
| --- | --- | --- | --- | --- |
| chat.db | Chat, participants, inbox, proposals, traces | version absent | high | stance: additive-only now; add explicit version table before destructive migrations; old unknown layout must be detected or rejected |
| god_sessions.json | GOD session registry and provider session id resume | version absent | high | stance: additive-only fields only; add root schema_version before changing record semantics; malformed old state must be rejected |
| feature_graph_statuses.json | Graph-native execution status | version present but unenforced | high | stance: treat as high until read path rejects unknown version; additive-only changes require version enforcement |
| feature_graph_artifacts.json | Worker/reviewer graph artifacts | version present but unenforced | high | stance: treat as high until read path rejects unknown version; additive-only changes require version enforcement |
| planning_runs.sqlite3 | Planning run metadata | version absent | high | stance: additive-only now; add PRAGMA user_version or schema table before destructive migrations; old state must be rejected if incompatible |
| planning_events.sqlite3 | Planning event log | version absent | high | stance: additive-only now; add PRAGMA user_version or schema table before destructive migrations; old state must be rejected if incompatible |
| provider_session_bindings.json | Provider-native resume bindings | version present but unenforced | medium | stance: enforce schema_version before expanding fields; stale records are retained until retention policy exists |
| feature_lanes.json | Migration-era lane projection, not authority | schema version absent; projection_revision only | high legacy | stance: projection/legacy; do not harden as authority; additive-only compatibility; stale projection state may be regenerated or rejected |
| active_sessions.json | Legacy runtime session projection | version absent | high legacy | stance: legacy/read-model; do not harden for V11; consumers must tolerate missing or malformed state by explicit rejection |
| error_knowledge.json | Passive error knowledge/read model | version mixed | medium legacy | stance: read-model; no destructive migration; malformed entries skipped or rejected by reader |
| coordinator_incidents.jsonl | Append-only coordinator incident log | version absent | low | stance: report-only/read-model; optional future rotation |
| provider_selection_records.jsonl | Append-only provider selection audit/read model | version absent | low | stance: report-only/read-model; append-only audit log; optional future rotation |
| feature_lanes.json.writer_lease.json | Runner writer lease | ephemeral lease | ephemeral | stance: ephemeral; expired writer lease can be reclaimed; physical lock files need not be deleted |
| feature_plans/*.json | Approved feature plan artifact | model-shaped JSON, version absent | high | stance: additive-only now; add schema_version before changing artifact shape; old state must be rejected if incompatible |
| feature_plans/*.deliberation.json | Feature-plan deliberation artifact | model-shaped JSON, version absent | high | stance: additive-only now; add schema_version before changing deliberation shape; old state must be rejected if incompatible |
| graph_sets/*.json | Feature graph set artifact | model-shaped JSON, version absent | high | stance: additive-only now; add schema_version before changing graph-set shape; old state must be rejected if incompatible |
| lane_graphs/*.json | Lane graph artifact | model-shaped JSON, version absent | high | stance: additive-only now; add schema_version before changing lane graph shape; old state must be rejected if incompatible |
| audit_events.json | Operator/review event audit log | version absent | high | stance: append-only/additive-only; add schema_version before changing event envelope; malformed old state must be rejected |
| final_actions.json | Final action holds/operator decisions | version absent | high | stance: additive-only now; add schema_version before changing hold semantics; old state must be rejected if incompatible |

## Old State Handling

- Additive migrations may add nullable fields, new tables, indexes, or new JSON
  keys while preserving existing readers.
- Destructive changes include renames, deletions, type changes, and semantic
  reinterpretation of existing fields. They require a future migration plan and
  are not implemented in V11.
- Version absent high-risk stores must not be described as migration-ready.
- Version present but unenforced stores must reject unknown versions before they
  can be used as authoritative migration anchors.
- Projection/read-model stores are not durable authority and should be
  regenerated or rejected rather than migrated destructively.

## Cleanup Contract

V11 cleanup classification:

| Category | Current behavior | Examples |
| --- | --- | --- |
| automated cleanup | Actively stops owned resources during normal shutdown | runner task cancellation, GOD layer shutdown, writer lease release |
| graceful shutdown | Component-owned shutdown method closes child resources | Codex app-server transport termination, Ray actor shutdown |
| stale lane repair | Changes stale lane state after timeout detection | dispatched lane repair to `exec_failed` |
| report-only detection | Reports leftovers without killing processes | `leftover_codex_app_server`, `leftover_raylet`, `leftover_gcs_server`, `leftover_ray_worker` with `action=report_only` |

Report-only detection is intentionally non-destructive in V11. Automated process
killing, WAL checkpointing, log rotation, stale provider binding pruning, and
cleanup daemons are future hardening work.
