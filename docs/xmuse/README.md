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
| `src/xmuse_core/chat/room_memory_runtime.py` | Sidecar-neutral Host evidence protocol. |
| `src/xmuse_core/chat/room_memory_projection.py` | `room_memory_projection/v1` safe read model. |
| `src/xmuse_core/chat/memoryos_supervisor.py` | Optional sidecar command, environment, receipt, and safe status. |
| `src/xmuse_core/chat/room_soak_chaos.py` | Fixed soak profiles, strict aggregate evidence, and `room_soak_chaos_result/v1` gates. |
| `src/xmuse_core/chat/room_soak_ci.py` | Deterministic 12-Room production Kernel/Host CI simulation. |
| `src/xmuse_core/agents/room_codex_launcher.py` | Isolated persistent Codex launcher. |
| `src/xmuse_core/skills/` | Bundled Skill catalog, selection, and evidence. |
| `scripts/room_soak_chaos.py` | Independent live provider/MemoryOS fault and browser orchestration; no production telemetry surface. |
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

`xmuse-data` has a narrow offline verifier for old `xmuse.chat_db/v1` databases. There
is no executable compatibility API, MCP, runner, UI projection, or ChatStore runtime.

Use Git history for retired implementations; do not create repository-local archive or
legacy source trees.

## References

- [Quickstart](../../QUICKSTART.md)
- [Frontend API](frontend/FRONTEND_API.md)
- [MCP permission boundary](mcp-permission-model.md)
