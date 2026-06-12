# xmuse MCP Permission Model

Date: 2026-06-04

Scope: Path A Phase 4 contract closure. This document defines declarative MCP
permission categories and current enforcement boundaries. Chat API now has a
configurable token and role/capability gate for mutating routes; MCP HTTP
authentication is also available for mutating JSON-RPC tool calls. Dashboard
admin UI and rate limiting remain outside this document.

## Vocabulary

- MCP write authentication is opt-in: when `xmuse.mcp_server` is started with
  `XMUSE_MCP_AUTH_TOKEN`, `XMUSE_MCP_API_KEY`, or `create_app(auth_token=...)`,
  mutating `tools/call` requests require `X-XMUSE-API-Key`,
  `X-XMuse-Operator-Role`, and `X-XMuse-Operator-Capabilities`.
- Chat API authentication is opt-in: when started with an auth token, mutating
  `/api/chat/*` requests require `X-XMUSE-API-Key` plus an allowed
  `X-XMuse-Operator-Role` and `X-XMuse-Operator-Capabilities` value.
- production deployment profile is fail-closed: when
  `XMUSE_DEPLOYMENT_PROFILE=production`, Chat API startup requires
  `XMUSE_CHAT_API_AUTH_TOKEN`, `XMUSE_CHAT_API_KEY`, or an explicit
  `auth_token`; MCP startup requires `XMUSE_MCP_AUTH_TOKEN`,
  `XMUSE_MCP_API_KEY`, or an explicit `auth_token`.
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
| read_only | Tool is non-mutating and returns bounded read models or diagnostics | Metadata + tests; read tools remain token-free under local trust policy |
| write | Tool mutates state and requires a write contract such as audit guard or idempotency | Existing write validation plus opt-in HTTP token/role/capability gate |
| identity_bound_god | Chat GOD tool scoped by `god_session_id`, `conversation_id`, and `participant_id` | Existing `_verify_god_identity()` checks plus opt-in HTTP token/role/capability gate for mutating tools |
| admin_operator | High-privilege operator action requiring admin authorization | Existing audit/guard plus opt-in HTTP token/admin-role gate |

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
| chat_create_collaboration_request | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_record_collaboration_response | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_raise_collaboration_blocker | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_resolve_collaboration_blocker | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_evaluate_dispatch_gate | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| chat_inspect_conversation | read_only | false | none | none | conversation |
| chat_emit_blueprint_proposal | identity_bound_god | true | god_session | chat_identity_idempotency | conversation_participant_session |
| memory_search | read_only | false | none | none | memory_namespace |
| memory_build_context | read_only | false | none | none | memory_namespace |
| memory_ingest | write | true | none | audit_guard_required | memory_namespace |

## MCP HTTP Runtime Gate

When MCP auth is enabled:

- missing or wrong `X-XMUSE-API-Key` returns `401`;
- read-only tools stay readable without a token;
- `viewer` cannot mutate;
- `admin` may mutate without an explicit tool capability;
- `operator` may mutate non-admin write tools only when
  `X-XMuse-Operator-Capabilities` contains the exact MCP tool name, such as
  `enqueue_lane`;
- `god` may mutate identity-bound GOD tools only when the exact tool capability
  is present and the existing `god_session_id` identity check passes;
- `operator` and `god` cannot use `admin_operator` tools;
- audit/guard payloads remain required for tools that already require them.

The API key authenticates the HTTP caller. It does not replace GOD identity,
idempotency, audit guards, or durable authority checks. The MCP `/health`
response reports whether write auth is enabled and whether read tools require a
token.

## Runtime Rejection Contract

The identity-bound chat tools must reject:

- wrong `conversation_id` for the `god_session_id`,
- wrong `participant_id` for the `god_session_id`,
- unknown `god_session_id`.

Read-only tools are classified as non-mutating. They remain under the trusted
local read policy until a broader deployment policy requires read authentication.

## Chat API Runtime Gate

When Chat API auth is enabled:

- missing or wrong `X-XMUSE-API-Key` returns `401`;
- `viewer` cannot mutate any Chat API write surface;
- `admin` may mutate without an explicit capability;
- `operator` and `god` must include the route capability in
  `X-XMuse-Operator-Capabilities`;
- `/api/chat/operator/actions` still enforces the action-specific capability,
  such as `select_god_cli`, inside the operator action contract.

This is `contract_proof` for HTTP write-surface RBAC. It is not live service
proof until the configured Chat API process is started with the token and
exercised by a real operator/TUI session.
