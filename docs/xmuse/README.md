# xmuse implementation map

Implementation and fresh tests are authoritative; this file is a navigation aid.

## Room Collaboration Protocol

The default chain below is xmuse's durable, logically decentralized collaboration protocol.
It is not Google A2A. A future Google A2A adapter could only attach an opt-in remote
participant; it must not replace Room observation, causality, attempts, or outcomes.

## Product chain

```text
POST /api/chat/conversations
  -> RoomSetupService: conversation + roster + idempotency receipt

POST /api/chat/threads/{conversation_id}/messages
  -> RoomKernelStore: human activity + per-participant observations
  -> RoomParticipantHost / isolated Room Runner
  -> correlation root barrier + immutable peer batch (one attempt/outcome)
  -> participant-bound read-only Codex room_v1 session
  -> bundled Skills
  -> /mcp/room chat_room_submit_outcome
  -> durable outcome + bounded projections

optional MemoryOS
  -> transaction-local visible activity / approved candidate outbox
  -> archive ingest + Room session attachments
  -> source-validated, bounded memory_evidence (failure never blocks Room outcome)
```

| Module | Responsibility |
| --- | --- |
| `xmuse/chat_api.py` | Room-only HTTP composition. |
| `xmuse/chat_api_room_setup.py` | Atomic Room and roster creation. |
| `xmuse/chat_api_room_messages.py` | Human speech write path. |
| `xmuse/chat_api_room_projection.py` | Bounded Room list, timeline, and events. |
| `xmuse/chat_api_agent_streams.py` | Disposable, authority-reproved Room Agent preview SSE. |
| `xmuse/chat_api_room_controls.py` | Observation-local cancel/retry. |
| `xmuse/chat_api_operations.py` | Safe incidents plus guarded Room Runtime and Memory index recovery. |
| `xmuse/chat_api_executions.py` | Bounded execution projections and guarded operator actions. |
| `xmuse/chat_api_execution_runtime.py` | Consensus and one-shot controller reconciliation. |
| `xmuse/chat_api_memory.py` | Safe memory projection and guarded candidate resolution. |
| `xmuse/memoryos_adapter.py` | Strict HTTP-only archive/recall adapter; no MemoryOS package import. |
| `xmuse/room_execution_controller.py` | Internal process entrypoint; accepts only root/worktree/run ID. |
| `xmuse/room_runner.py` | Host process lock, receipt, heartbeat, and pump lifecycle. |
| `xmuse/room_mcp_server.py` | `/health` and `/mcp/room`; one outcome tool. |
| `xmuse/workroom.py` | Local Chat API/frontend lifecycle and optional derived MemoryOS sidecar. |
| `xmuse/data_cli.py` | Offline doctor, backup, restore, and compact. |
| `src/xmuse_core/chat/room_database.py` | Room schema and SQLite connection policy. |
| `src/xmuse_core/chat/room_batches.py` | Immutable observation batches and canonical membership. |
| `src/xmuse_core/chat/room_kernel.py` | Activity, observations, leases, causality, and outcomes. |
| `src/xmuse_core/chat/room_controls.py` | Attempts, fencing, cleanup, and retry. |
| `src/xmuse_core/chat/room_host.py` | Fair participant delivery and recovery. |
| `src/xmuse_core/chat/room_projection.py` | `room_chat_projection/v3`. |
| `src/xmuse_core/chat/room_agent_stream.py` | Single-writer preview cache and safe projection. |
| `src/xmuse_core/chat/room_operations.py` | Operational projection and action ledger. |
| `src/xmuse_core/chat/room_execution_contracts.py` | Strict unified-diff and assessment contracts. |
| `src/xmuse_core/chat/room_execution_store.py` | Candidate, vote, authorization, run, gate, and promotion authority. |
| `src/xmuse_core/chat/room_execution_controller.py` | Exact staging, guard checks, promotion, and crash classification. |
| `src/xmuse_core/chat/room_execution_sandbox.py` | Fixed networkless Bubblewrap gate surface. |
| `src/xmuse_core/chat/room_execution_projection.py` | Safe bounded Inspector read models. |
| `src/xmuse_core/chat/room_memory_contracts.py` | Bounded Agent candidate and receipt contracts. |
| `src/xmuse_core/chat/room_memory_schema.py` | Memory authority schema, additive migrations, and deterministic backfills. |
| `src/xmuse_core/chat/room_memory_binding_conn.py` | DB-neutral caller-transaction binding materialization. |
| `src/xmuse_core/chat/room_memory_delivery_store.py` | Archive bindings, attachments, outbox leases, and delivery state. |
| `src/xmuse_core/chat/room_memory_governance_store.py` | Source-bound candidates and guarded operator decisions. |
| `src/xmuse_core/chat/room_memory_recall_store.py` | Source proof, recall requests, receipts, and context binding. |
| `src/xmuse_core/chat/room_memory_rebuild_store.py` | Durable guarded rebuild action and transactional derived-index replay reset. |
| `src/xmuse_core/chat/room_memory_ports.py` | Narrow persistence ports consumed by optional memory adapters. |
| `src/xmuse_core/chat/room_memory_runtime.py` | Sidecar-neutral Host evidence protocol. |
| `src/xmuse_core/chat/room_memory_projection.py` | `room_memory_projection/v1` safe read model. |
| `src/xmuse_core/chat/room_memory_diversity.py` | Bounded multi-topic recall dogfood result contract. |
| `src/xmuse_core/chat/memoryos_supervisor.py` | Optional sidecar command, environment, receipt, and safe status. |
| `src/xmuse_core/chat/room_soak_chaos.py` | Fixed soak profiles, strict aggregate evidence, and `room_soak_chaos_result/v1` gates. |
| `src/xmuse_core/chat/room_soak_ci.py` | Deterministic 12-Room production Kernel/Host CI simulation. |
| `src/xmuse_core/agents/room_codex_launcher.py` | Isolated persistent Codex launcher. |
| `src/xmuse_core/chat/room_codex_schema.py` | Durable native-action stages and safe migration/backfill rules. |
| `src/xmuse_core/chat/room_codex_bridge.py` | Guarded native capability and action ledger boundary. |
| `src/xmuse_core/chat/room_codex_native_runtime.py` | Participant session singleflight, recovery, and dispatch fencing. |
| `src/xmuse_core/chat/room_goal_memory_soak.py` | Fixed v0.1 release profile and `room_goal_memory_soak_result/v1` contract. |
| `src/xmuse_core/chat/room_execution_views.py` | Transaction-free candidate and run ledger read models. |
| `src/xmuse_core/chat/room_execution_read_store.py` | Read-only candidate/run projection source without command capabilities. |
| `src/xmuse_core/chat/room_execution_operator_store.py` | Fixed policy, candidate-decision, and cancel capability adapter for operator routes. |
| `src/xmuse_core/chat/room_execution_controller_store.py` | One-shot controller claim, gate, promotion, and finalization capability adapter. |
| `src/xmuse_core/chat/room_execution_runtime_store.py` | Long-lived consensus discovery and controller-recovery capability adapter. |
| `src/xmuse_core/chat/room_execution_events.py` | Caller-transaction projection invalidation helper for execution changes. |
| `src/xmuse_core/chat/room_execution_review_store.py` | Least-authority review material and receipt store used by Room delivery. |
| `src/xmuse_core/skills/` | Bundled Skill catalog, selection, and evidence. |
| `scripts/room_soak_chaos.py` | Independent live provider/MemoryOS fault and browser orchestration; no production telemetry surface. |
| `xmuse/room_runner_composition.py` | Room-only Host, transport, native runtime, stream, and session wiring. |
| `xmuse/room_runner_memory.py` | Optional MemoryOS environment, store, adapter, and pump composition. |
| `xmuse/workroom_contracts.py` | Workroom dependency injection and runtime-root path contracts. |
| `xmuse/workroom_cli.py` | Public `xmuse-workroom` argument parsing and command dispatch. |
| `xmuse/workroom.py` | Managed lifecycle, recovery, and manifest coordinator. |
| `frontend/src/` | Room-first browser and fixed write proxies. |

## Authority

| State | Authority | Not authority |
| --- | --- | --- |
| Room activity, observations, attempts, controls, outcomes | `chat.db` | UI cache or provider text |
| Participant/provider binding | `god_sessions.json` plus live reconciliation | rendered identity or PID alone |
| Runtime recovery | process evidence, Runner receipt, operator ledger | HTTP success text |
| Skill decision/context | durable attempt Skill rows | prompt text |
| Exact patch and execution | execution ledger and promotion journal in `chat.db` | Agent prose, browser action state, raw gate output |
| Long-term memory governance and delivery | memory outbox/candidate/receipt rows in `chat.db` | MemoryOS database, recalled text alone, browser cache |

The optional MemoryOS database is deleted and rebuilt rather than backed up. Only archival
items with source documents and activities re-proved from `chat.db` may enter Agent context;
shared user/project evidence additionally requires an approved and delivered candidate plus
the target Room's shared-archive attachment. The Workroom manager retries only a confirmed-
dead owned sidecar, preserves generation-local capability identity, and exposes crash-loop or
explicit cache/schema rebuilds through a guarded Inspector action. Rebuild stops the proven
child before fixed-cache deletion, resets only derived bindings/outbox in one transaction,
then waits for replay evidence; it never changes Room Runtime readiness or manufactures Room
activity.

Participant Codex session creation, ordinary reuse, and forced recovery share one
participant-scoped singleflight. A late recovery task cannot abort a newer incarnation.
Native actions record internal preparation, proof, dispatch, and completion stages:
pre-dispatch work can be safely reconciled and re-proved after a restart, but a crash after
dispatch is fenced as result-unknown and never automatically replays a provider mutation.
A provider acknowledgement is durable before the best-effort post-action snapshot refresh.

The `v0.1.0` release boundary is the fixed `live-goal-memory-soak` profile: four Rooms, two
Agents per Room, four waves, at least 60 minutes, and injected provider, Runner, MemoryOS,
and projection-cache faults. Its safe result combines settled Room facts, native-action and
memory evidence, browser verification, process cleanup, and workspace integrity without
persisting conversation or provider content.

`xmuse-data` has a narrow offline verifier for old `xmuse.chat_db/v1` databases. There
is no executable compatibility API, MCP, runner, UI projection, or ChatStore runtime.

Use Git history for retired implementations; do not create repository-local archive or
legacy source trees.

## Maintenance boundaries

The process entrypoints own lifecycle, not provider wiring or persistence policy.
`xmuse/room_runner.py` delegates object wiring to `room_runner_composition.py` and receives one
sidecar-neutral `RoomMemoryRuntime`; only `room_runner_memory.py` may compose the MemoryOS HTTP
adapter, concrete memory stores, environment configuration, and outbox pump policy. The
adapter depends on the behavioral store ports in `room_memory_ports.py`, not concrete SQLite
classes.

Room delivery follows the same least-authority rule. `room_host.py` only reads bounded
execution review material and `room_codex_transport.py` only binds the submitted-context
receipt through `room_execution_ports.py`; neither imports the privileged operator,
controller, promotion, or cancel facade. The Runner constructs
`RoomExecutionReviewStore`, not a broadly typed `RoomExecutionStore` hidden behind a narrow
annotation.

Execution HTTP reads likewise construct `RoomExecutionLedgerReader`; only fixed operator
routes acquire the command store. A projection request therefore cannot obtain authorization,
cancel, controller, or promotion methods through its injected store.

Operator HTTP routes receive a separate `RoomExecutionOperatorStore`. It preserves the
ledger's existing atomic authorization/cancel transactions while withholding controller
claim, gate evidence, promotion, acknowledgement, and finalization methods from the API
composition.

The one-shot Harness process receives a distinct `RoomExecutionControllerStore`. It can
recover its authorized run and record fixed gate/promotion evidence, but cannot change Room
policy, authorize candidates, reconcile consensus, request operator cancellation, or bind
Room delivery review receipts.

The long-lived Chat API reconciler uses `RoomExecutionRuntimeStore`: it may discover endorsed
candidates, reconcile consensus authorization, and recover controller bindings, but it does
not receive operator commands or the controller's gate/promotion/finalization surface.

The remaining internal execution authority binds existing candidate, action, run, promotion,
and event `*_conn` helpers as explicit class seams. This keeps transaction fault injection
possible without duplicating forwarding signatures inside the aggregate store; event helpers
never open or commit their own connection.

Core continues to have no dependency on the application namespace or `memoryos_lite`.
Boundary tests enforce both directions. Future reductions should preserve wire contracts and
move one cohesive responsibility at a time; line-count movement without a narrower import or
authority boundary is not considered an architectural improvement.

The Workroom command surface follows the same rule: `workroom_cli.py` owns parsing and invokes
the lifecycle API, while `workroom.py` has no CLI parser or public entrypoint. Dependency and
path seams live in `workroom_contracts.py`, so lifecycle tests can inject process evidence
without treating the coordinator module as an accidental namespace facade.

## References

- [Quickstart](../../QUICKSTART.md)
- [Frontend API](frontend/FRONTEND_API.md)
- [MCP permission boundary](mcp-permission-model.md)
