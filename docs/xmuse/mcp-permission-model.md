# xmuse Room MCP permission boundary

The managed MCP server is a trusted-local, Room-only service bound to
`127.0.0.1:8100`. Its live contract is defined by
`src/xmuse_core/chat/room_mcp_contract.py` and `xmuse/room_mcp_server.py`.

## Surface

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Bounded local readiness. |
| `POST /mcp/room` | JSON-RPC with exactly `chat_room_submit_outcome` and the `chat_room_board_*` tools. |

OpenAPI, SSE, `/messages`, root `/mcp`, and `/mcp/chat` are absent. Room Codex
app-servers use a config-isolated home, so user MCP registrations and plugins cannot expand
the tool list. Only the Room tools are pre-approved, each by its exact name. Read-only ACP
participants get the same exact-title allowlist. Workspace-write owners are different by
design: they keep their own MCP servers and Skills, and their OS sandbox (not the tool
list) confines writes; a network-reached or delegating MCP server is outside that sandbox.

The OS sandboxes (bubblewrap, for OpenCode, agy and every owner) bind the whole filesystem
read-only and mask what must stay unreadable. On WSL that includes the
Windows drives: every drvfs mount (`/mnt/c`, `/mnt/d`, ...) is replaced by an empty tmpfs so
Windows-side credentials (`.ssh`, `.aws`, `.claude`, browser profiles) stay unreadable, and
only a workspace or owner clone living on a drive is re-bound over that mask. On other hosts
there are no drvfs mounts and the confinement is unchanged.

## Board tools

| Tool | Caller | Effect |
| --- | --- | --- |
| `chat_room_board_read` | any participant | Charters, contract index, the caller's board inbox (advances its cursor), optionally one contract's full text. |
| `chat_room_board_propose_split` | Room lead | Proposes module charters, initial contracts and module→participant assignments; inert until an operator approves. |
| `chat_room_board_claim` | assigned owner | Marks the module as taken. |
| `chat_room_board_publish_contract` | provider module owner or lead | Publishes or revises a contract with optimistic `base_version`; wakes every dependent owner. |
| `chat_room_board_report_progress` | module owner | Status, summary and checkable claims; `blocked`/`ready_for_review` wake the report target. |
| `chat_room_board_ask` | any participant | Question to one peer; wakes that peer, who answers with a normal outcome reply. |

Every board call carries the same conversation, participant, GOD session, observation,
lease token and client request identifiers as the outcome tool and fails closed on a lost
lease. Board writes append one `board.*` activity in the same transaction as the board
tables; contract text lives only in the contract table.

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
surfaces retain safe IDs and digests. Infrastructure never creates a candidate on an Agent's
behalf. The only non-Agent proposer is the opt-in MemoryOS Curator: its proposals are labeled
as such, cite Room activities with verbatim quotes re-proved in `chat.db`, and follow the same
approval rules.

Source-valid Room facts and decisions are automatically queued only for the current Room.
User preferences and project rules remain pending until a guarded operator approval queues
them into the shared local-user or project archive. Recall still treats the resulting text
as untrusted evidence: it cannot change Room identity, permissions, Skills, leases, or the
durable outcome contract.

Unknown tools, identities, leases, attempts, and malformed outcomes fail closed. Provider
final text and provider-turn completion never materialize Room speech. Adding a tool requires
updating the schema, enforcement, isolated Codex configuration, the ACP exact-title
allowlist, and focused tests together.
