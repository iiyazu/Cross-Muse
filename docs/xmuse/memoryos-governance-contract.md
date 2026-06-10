# MemoryOS Governance Contract

MemoryOS is a REST-first shared memory backend for xmuse GODs. It must not be
exposed as MCP write tools unless the host has enabled auth/RBAC and audit
guards.

## Namespace Dimensions

The full task namespace can include:

- `repo`
- `workspace`
- `god_id`
- `conversation_id`
- `thread_id`
- `blueprint_id`
- `feature_id`
- `lane_id`

The canonical helper is `task_namespace(...)`, which renders all dimensions into
a deterministic `memory://...` URI. Older repo, workspace, conversation,
participant, and shared namespaces remain supported for compatibility.

## Memory Layers

Memory writes declare one of:

- `pinned_core`
- `task_state`
- `archival`

The default is `task_state`. Prompt context builders must preserve namespace URI
and source refs so retrieved memory can be audited back to the event that wrote
it.

## Write Requirements

Every REST ingest request must include:

- namespace
- namespace URI
- actor identity
- memory layer
- content
- source refs

Missing actor identity is invalid. Shared promotion requires an explicit shared
namespace.

## Privacy And Retention

LLM paging must run a redaction hook before exporting transcript text. The
default hook redacts common token, secret, password, and API key patterns.

Deleted source messages must be represented by tombstoned source refs. Tombstoned
refs are not returned as active memory by the fake contract client.

## MCP Boundary

`memory_search` and `memory_build_context` are read tools. `memory_ingest` is a
write tool and is denied by default. It can only be authorized when host
auth/RBAC is explicitly enabled.
