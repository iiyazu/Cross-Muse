# xmuse MCP Permission Model

Date: 2026-06-04

Scope: Path A Phase 4 contract closure. This document defines declarative MCP
permission categories and current enforcement boundaries. It does not implement
API authentication middleware, broad authorization, dashboard admin UI, or rate
limiting.

## Vocabulary

- API authentication is not implemented: `/mcp` and `/mcp/chat` currently accept
  JSON-RPC requests without a token/header gate.
- identity verification is not API authentication: selected chat tools verify
  `god_session_id`, `conversation_id`, and `participant_id` against
  `god_sessions.json`; this proves session scope, not network caller identity.
- audit guard is not authorization: tools such as `enqueue_lane`, `abort_lane`,
  `update_lane_status`, and `apply_takeover_decision` require audit/guard
  payloads to prevent blind writes, but the payload does not authenticate the caller.
- permission category is declarative: V11 adds metadata and tests so every tool
  is classified before future auth/authorization work.

## Permission Categories

| Category | Meaning | Runtime enforcement in V11 |
| --- | --- | --- |
| read_only | Tool is non-mutating and returns bounded read models or diagnostics | Metadata + tests only |
| write | Tool mutates state and requires a write contract such as audit guard or idempotency | Existing write validation where present |
| identity_bound_god | Chat GOD tool scoped by `god_session_id`, `conversation_id`, and `participant_id` | Existing `_verify_god_identity()` checks |
| admin_operator | High-privilege operator action requiring future admin authorization | Existing audit/guard only; no auth middleware |

## Tool Matrix

| Tool | Category | Mutates | Identity verification | Audit guard | Scope |
| --- | --- | --- | --- | --- | --- |
| list_lanes | read_only | false | none | none | lane_projection |
| enqueue_lane | write | true | none | audit_guard_required | lane_projection |
| get_status | read_only | false | none | none | lane_projection |
| abort_lane | admin_operator | true | none | audit_guard_required | lane_projection_and_active_session |
| get_error_knowledge | read_only | false | none | none | error_knowledge |
| get_logs | read_only | false | none | none | execution_logs |
| get_tool_inventory | read_only | false | none | none | tool_inventory |
| get_lane | read_only | false | none | none | lane_projection |
| get_gate_report | read_only | false | none | none | gate_report |
| get_diff | read_only | false | none | none | lane_worktree |
| query_knowledge | read_only | false | none | none | error_knowledge |
| update_lane_status | write | true | none | audit_guard_required | lane_projection |
| apply_takeover_decision | admin_operator | true | none | audit_guard_required | lane_projection_and_takeover |
| read_lane_contract | read_only | false | none | none | lane_contract |
| read_blueprint_contract | read_only | false | none | none | blueprint_contract |
| read_feature_plan_contract | read_only | false | none | none | feature_plan_contract |
| read_review_contract | read_only | false | none | none | review_contract |
| read_graph_set_summary | read_only | false | none | none | graph_set |
| read_health_contract | read_only | false | none | none | run_health |
| read_graph_set_contract | read_only | false | none | none | graph_set |
| read_evidence_refs | read_only | false | none | none | evidence_refs |
| read_review_verdict | read_only | false | none | none | review_verdict |
| read_takeover_context | read_only | false | none | none | takeover_context |
| read_run_health | read_only | false | none | none | run_health |
| read_provider_inventory | read_only | false | none | none | provider_inventory |
| chat_list_conversations | read_only | false | none | none | all_conversations |
| chat_create_conversation | write | true | none | none | conversation_creation |
| chat_list_participants | read_only | false | none | none | conversation |
| chat_post_message | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_read_inbox | identity_bound_god | false | god_session | none | conversation_participant_session |
| chat_mark_inbox | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_mention | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_emit_proposal | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_approve_proposal | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_create_collaboration_request | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_record_collaboration_response | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_raise_collaboration_blocker | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_resolve_collaboration_blocker | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_evaluate_dispatch_gate | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_inspect_conversation | read_only | false | none | none | conversation |
| chat_emit_blueprint_proposal | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |

## Disabled MemoryOS MCP Policy Entries

These names have permission metadata for authorization policy checks, but they
are not registered in the MCP server tool schema:

| Tool | Category | Mutates | Identity verification | Audit guard | Scope |
| --- | --- | --- | --- | --- | --- |
| memory_search | read_only | false | none | none | memory_namespace |
| memory_build_context | read_only | false | none | none | memory_namespace |
| memory_ingest | write | true | none | audit_guard_required | memory_namespace |

`memory_search` and `memory_build_context` remain REST-sidecar read concepts.
`memory_ingest` is a disabled MCP write concept and is denied unless host
auth/RBAC is explicitly enabled. MemoryOS must not become xmuse truth authority
through MCP tool registration.

## V11 Runtime Rejection Contract

The identity-bound chat tools must reject:

- wrong `conversation_id` for the `god_session_id`,
- wrong `participant_id` for the `god_session_id`,
- unknown `god_session_id`.

Read-only tools are classified as non-mutating. They still require future API
authentication and caller authorization before exposing the MCP server beyond a
trusted local operator boundary.
