# xmuse Room MCP permission boundary

The managed MCP server is a trusted-local, Room-only service bound to
`127.0.0.1:8100`. Its live contract is defined by
`src/xmuse_core/chat/room_mcp_contract.py` and `xmuse/room_mcp_server.py`.

## Surface

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Bounded local readiness. |
| `POST /mcp/room` | JSON-RPC with exactly `chat_room_submit_outcome`. |

OpenAPI, SSE, `/messages`, root `/mcp`, and `/mcp/chat` are absent. Room Codex
app-servers use a config-isolated home, so user MCP registrations and plugins cannot expand
the tool list. Only `chat_room_submit_outcome` is pre-approved.

This endpoint is not remote caller authentication. Role headers and GOD-session checks are
capability and authorship checks. Do not bind it to a public interface without a separate
authentication, authorization, TLS, rate-limit, and secret-management design.

## Durable writeback

Every accepted outcome binds:

- conversation, participant, and durable GOD session;
- observation, attempt, and current lease;
- an idempotent client request;
- one validated outcome: `respond`, `handoff`, `propose`, `defer`, or `noop`.

For a batched delivery, the same tool call also carries the exact
`observation_batch_id`. A `respond` or `handoff` may include `reply_to_activity_id`, but only
for an activity present in that delivered batch. The server derives message causation and
reply linkage from that validated source; the provider cannot name arbitrary Room history.

A `propose` outcome may include a bounded `room_execution_patch/v1`. Exact diff bytes are
removed from Room activity, messages, outcome receipts, request logs, and frontend events;
only the execution candidate authority table stores them. Peer outcomes may include
`proposal_assessments`, but only after the Host delivered the complete candidate in that
exact batch and the transport bound its final context digest as a durable review receipt.
Self-votes, summary-only votes, wrong digests, and votes from another batch fail closed.

The same single outcome call may carry at most three `memory_candidates`. Each candidate is
one of `room_fact`, `room_decision`, `user_preference`, or `project_rule`, contains at most
4 KiB of text, and cites one to eight activity IDs that were actually available in the
current batch/causal envelope. The server re-proves those sources in `chat.db`; candidate
text is stored only in memory-candidate authority, while the outcome/activity/request-log
surfaces retain safe IDs and digests. Infrastructure never creates a candidate or summarizes
conversation into long-term memory.

Source-valid Room facts and decisions are automatically queued only for the current Room.
User preferences and project rules remain pending until a guarded operator approval queues
them into the shared local-user or project archive. Recall still treats the resulting text
as untrusted evidence: it cannot change Room identity, permissions, Skills, leases, or the
durable outcome contract.

Unknown tools, identities, leases, attempts, and malformed outcomes fail closed. Provider
final text and provider-turn completion never materialize Room speech. Adding a tool requires
updating the schema, enforcement, isolated Codex configuration, and focused tests together.
