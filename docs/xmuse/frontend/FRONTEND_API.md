# xmuse Room-first browser API

Verified against `v0.1.0` and `frontend/src/` on 2026-07-14. This is a navigation contract,
not runtime authority; TypeScript source, backend implementation, and fresh tests take
precedence.

## Local boundary and configuration

| Use | Environment value | Default |
| --- | --- | --- |
| Browser Chat REST | `NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL` | `http://localhost:8201/api/chat` |
| Next server Chat REST | `XMUSE_CHAT_API_BASE_URL` | `http://127.0.0.1:8201/api/chat` |
| Next server operator credential | `XMUSE_OPERATOR_TOKEN` | none |

Only Chat REST coordinates are public. `XMUSE_OPERATOR_TOKEN` stays in the Next server
process and must never use a `NEXT_PUBLIC_*` name. The current deployment model is still a
loopback, single-user Workroom; the proxy described below is CSRF/secret hygiene, not remote
user authentication.

The default Room UI does not hold an operator-token WebSocket. It uses durable event polling
plus bounded Room projection refreshes. A separate SSE connection carries only disposable,
non-authoritative Agent response previews for the currently selected Room.

## Default browser calls

| Use | Request |
| --- | --- |
| List room summaries | `GET /api/chat/rooms` |
| List safe Room setup choices | `GET /api/chat/room-setup-options` |
| Create a room | `POST /api/rooms` on the Next origin → fixed backend `POST /api/chat/conversations` |
| Read bounded Room state | `GET /api/chat/conversations/{id}/room-projection` |
| Preview active Room Agents | `GET /api/chat/conversations/{id}/agent-streams` (SSE) |
| Catch up invalidations | `GET /api/chat/conversations/{id}/events?after_seq=&limit=` |
| Send human speech | `POST /api/rooms/{id}/messages` on the Next origin → fixed backend `POST /api/chat/threads/{id}/messages` |
| Cancel one Agent attempt | `POST /api/room-observations/{observation_id}/cancel` on the Next origin |
| Retry one observation | `POST /api/room-observations/{observation_id}/retry` on the Next origin |
| Inspect runtime incidents | `GET /api/chat/runtime/operations` |
| Recover degraded runtime | `POST /api/room-runtime/recover` on the Next origin |
| Rebuild a blocked MemoryOS index | `POST /api/room-memory/rebuild` on the Next origin |
| List Room executions | `GET /api/chat/conversations/{id}/executions` |
| Read one exact candidate | `GET /api/chat/execution-candidates/{candidate_id}` |
| Change execution policy | `PUT /api/room-execution-policy/{id}` on the Next origin |
| Decide a candidate | `POST /api/room-execution-candidates/{id}/decision` on the Next origin |
| Cancel an execution run | `POST /api/room-execution-runs/{id}/cancel` on the Next origin |
| Inspect source-backed memory | `GET /api/chat/conversations/{id}/memory` |
| Resolve a memory candidate | `POST /api/room-memory-candidates/{id}/resolve` on the Next origin |
| Invoke a guarded Codex capability | `POST /api/room-participants/{id}/codex-actions` on the Next origin |

Room creation accepts `title`, a `client_request_id`, and either `roster_template_id` or a
bounded `initial_participants` list. The backend atomically writes the Room, roster, and
`room_setup_requests` receipt. Identical retries return the same `room_setup/v2` response;
reusing the request ID with a different payload returns `409`. Bootstrap mode, provider
override, fork, and template-management fields are not part of the Room product. Fresh Room
creation does not emit a system message or create an init participant/provider session.
Custom participant identity fields are bounded at the API boundary (role 64 characters,
display name 120, model and role-template reference 200); a Room title is capped at 200.
These are identity metadata, not free-form persona prompts. Bundled templates alone freeze a
server-authored `persona_snapshot/v1` of at most 2 KiB into each participant identity.
New participants are Codex-only. Historical `a2a` or `opencode` rows remain readable for
offline compatibility, but cannot be activated, claimed, or used to start a transport.

`GET /api/chat/room-setup-options` returns `room_setup_options/v1`. It places the default
template first, then sorts at most nineteen other valid templates by display name. Each
template contains at most eight safe Codex role summaries: role ID, role, display name,
description, and collaboration focus. Invalid custom templates are omitted without hiding the
builtin fallback. Provider profiles, model bindings, persona prompts, paths, tokens, and
internal identities do not cross this boundary.

## Room list projection

`GET /api/chat/rooms` returns `room_list_projection/v1`. Each summary contains the durable
conversation id/title, up to four members, latest visible Room item and sequence, and active
and attention turn counts. The backend builds the list with batch queries; it does not build
one legacy worklist/evidence projection per room.

## Bounded Room projection

```http
GET /api/chat/conversations/{conversation_id}/room-projection?limit=60
GET /api/chat/conversations/{conversation_id}/room-projection?before_room_seq=81&limit=60
GET /api/chat/conversations/{conversation_id}/room-projection?after_room_seq=140&limit=60
```

`before_room_seq` and `after_room_seq` are mutually exclusive; `limit` is capped at 100.
The response is `room_chat_projection/v3` and includes:

- a bounded durable timeline with Room sequence, stable public participant identity,
  causation/correlation, message/proposal ids and proof boundary; provider/GOD session and
  attempt identifiers never cross this boundary;
- participant global frontiers and last outcomes;
- the latest eight human-root turns plus total active/attention counts;
- canonical observation-batch evidence, real provider-attempt and Skill-decision counts,
  context-only tail coverage, and resolved reply/handoff targets without exposing leases or
  provider identity;
- `page.has_older`, `page.has_newer`, and next Room cursors;
- a separate `event_cursor` for frontend invalidations.

Room sequence and frontend event sequence are different domains and must never be merged.
The store drains event pages first, then performs one incremental Room projection refresh; a
15-second safety refresh covers lease expiry, which does not create an event.

## Disposable Agent preview SSE

`GET /api/chat/conversations/{id}/agent-streams` returns
`room_agent_stream_projection/v1` events. The first event is a complete snapshot; reconnects
use the opaque epoch and stream cursor only to choose `projection` or `reset`. The browser
keeps one EventSource for the selected Room and may skip intermediate snapshots.

Preview content is sanitized bounded plain text with the proof boundary
`provider_preview_not_room_or_codex_authority`. It lives in the private Runner-owned
`runtime/room-agent-streams.sqlite3`, not `chat.db`, and never changes Room sequence, unread
state, memory, Harness evidence, peer observations, or summaries. `streaming` becomes
`committing` when the durable outcome tool starts. The API batch-reproves the exact current
attempt before publishing; a completed Room outcome resolves the preview by produced activity
ID, while cancellation, expiry, recovery, or a newer attempt invalidates it. Cache failure
only disables previews and does not affect durable Room polling.

The browser incrementally renders closed Markdown blocks with the same safe renderer used by
durable messages. The unfinished block remains a lightweight streaming tail until it reaches a
stable boundary; this avoids reparsing the complete growing answer or committing incomplete
fences/tables to the DOM. High-frequency stream snapshots subscribe only the timeline subtree,
not the sidebar, composer, Inspector, or other Workspace controls.

For `respond`, `handoff`, and `propose`, the Room delivery asks Codex to emit the answer itself
once before invoking the durable outcome tool; preambles and post-tool repetition are forbidden.
`noop` and `defer` invoke the tool without a draft. This preserves native delta timing without
client-side typewriter animation or promotion of preview bytes into Room authority.

## Human messages

```http
POST /api/chat/threads/{conversation_id}/messages
Content-Type: application/json
```

```json
{
  "message": "请一起审视这个边界，@reviewer 优先关注安全性。",
  "client_request_id": "ui_<uuid>"
}
```

The durable receipt returns `client_request_id`, `activity_id`, `room_activity_seq`, and the
complete message id/content/time. A recognized Mention raises one Agent's attention
priority; all active non-init Agents still observe the room activity.

Each active Agent has one root action opportunity for a Human turn. After all root
observations terminate, its peer observations for that correlation may be claimed as one
immutable batch of at most 16 items, producing at most one visible follow-up. Activities from
that follow-up remain durable context but do not create a third provider wave. The timeline
can render and navigate durable `reply_to` and handoff targets.

## Fixed managed-write proxies

The browser never calls a managed backend write directly and never receives the operator
token. Eleven fixed same-origin Next routes cover Room creation, human messages, observation
cancel/retry, Runtime recovery, MemoryOS index rebuild, execution policy, candidate decision,
run cancellation, memory-candidate resolution, and guarded Codex capability actions.
They enforce loopback-only configured upstreams, matching Origin/Host, JSON type, exact fixed
paths, `no-store`, no redirects, bounded responses, and distinct client abort versus server
deadline handling.

Create/control/recovery bodies are capped at 8KB; human messages are capped at 40KB. Create,
message, control, and recovery deadlines are respectively 10, 20, 15, and 30 seconds. Upstream
responses are streamed with a 1MiB limit. `XMUSE_CHAT_API_BASE_URL` is server-only and does
not fall back to a `NEXT_PUBLIC_*` value.

## Observation cancel/retry

Room frontiers carry guarded action descriptors. The browser sends only the descriptor's
expected state, attempt count, and control sequence to one of two fixed same-origin Next
routes:

```json
{
  "client_action_id": "ui_control_<uuid>",
  "expected_state": "active",
  "expected_attempt_count": 1,
  "expected_control_seq": 0
}
```

The control routes validate the exact fields, use a fixed upstream path, and add the
server-only operator token. They never proxy an href supplied by the browser.

The backend endpoints are:

- `POST /api/chat/operator/room-observations/{id}/cancel`;
- `POST /api/chat/operator/room-observations/{id}/retry`.

Cancel fences the current lease before transport cleanup. Retry is unavailable while cancel
cleanup is pending and reopens only the same durable observation after `cancelled` or
`exhausted`. Guard races return `409`; the UI immediately refreshes the Room projection.

## Exact-patch execution

An execution proposal stores one immutable `room_execution_patch/v1` candidate. The list
projection never contains raw diff bytes; the Room Workbench loads them only from the bounded
candidate-detail endpoint. The browser may reject or manually execute an open candidate,
switch the Room between `manual` and `consensus`, inspect frozen votes and gate progress, or
cancel a pre-promotion run. It cannot submit a patch, command, path, gate, PID, or proxy URL.

`manual` is the default. `consensus` is effective only when the Chat API started with
`XMUSE_ENABLE_AGENT_CONSENSUS_EXECUTION=1`; all frozen peers must have received the complete
candidate bytes and endorsed the same digest, and the server must prove the low-risk policy
and current workspace guard. A stale action descriptor returns `409` and causes a refresh.

The list and candidate projections expose only the safe
`room_execution_gate_profile/v1` reference: fixed profile ID/revision, ordered gate IDs, and
`ready|blocked` with a stable reason code. They never expose the workspace path, repository
or toolchain digest, dependency path, command output, or process identity. Missing or blocked
profile evidence disables both manual and consensus execution in the Room Workbench; the
backend re-proves the complete configured profile before authorization and again before
promotion.
The currently supported profiles are `docs/v1`, `python-uv/v1`, and
`xmuse-monorepo/v2`. Only the explicit docs profile may select diff-check alone.

## Source-backed memory

`GET /api/chat/conversations/{id}/memory` returns the bounded
`room_memory_projection/v1`: safe sidecar state, outbox counts, at most eight recent recall
receipts with activity references, and at most twenty pending Agent memory candidates. It
never returns MemoryOS session/archive/document IDs, process identity, endpoint, API key,
trace, path, prompt, or provider output.

`room_fact` and `room_decision` candidates are source-validated and automatically approved
for their current Room, so they do not appear as operator work. `user_preference` and
`project_rule` remain pending until the user approves or rejects the exact candidate digest
and revision through the fixed Next route. The action body contains only
`client_action_id`, `approve|reject`, `expected_digest`, and `expected_revision`; it is JSON,
8 KiB maximum, `no-store`, same-origin guarded, non-redirecting, and has a 30-second server
deadline. A `404` or `409` refreshes evidence instead of displaying success.

The Room tab polls memory and execution evidence about every five seconds while selected and
visible. The Runtime tab polls Operations at the same cadence. Unselected tabs, a closed
Workbench, and a hidden page use an approximately fifteen-second safety cadence. All loops
remain single-flight, abort on Room switch, use jittered backoff, and refresh only the current
visible tab on focus. A MemoryOS read failure preserves both the Room projection and the last
memory evidence; it is never reported as a Room Runtime failure.

`GET /api/chat/runtime/operations` returns `room_operations_projection/v2`, including a
strictly safe MemoryOS component, at most one guarded rebuild descriptor, and durable action
phase/status. For crash-loop or explicit derived-cache/schema blockers, the Runtime tab may
confirm `POST /api/room-memory/rebuild` with only `client_action_id` and
`expected_incident_id`. The fixed proxy uses the same Origin/Host, JSON, 8 KiB, no-redirect,
`no-store`, and server-token boundary and reconstructs both success and error payloads from
an allowlist. Pending phases survive browser reloads; `409` refreshes Operations and Room
memory instead of claiming success. Process identity, generation, API key, endpoint, cache
path, Room content, session bindings, and MemoryOS trace never enter this projection.

## Layered Workbench and per-participant Codex Console

The 400-pixel desktop Workbench has three fixed tabs: `Agent`, `Room`, and `Runtime`. Below
1180 CSS pixels it overlays the conversation; at 640 pixels it becomes a full-width sheet.
The Agent tab is participant-specific, the Room tab contains shared turn, execution, memory,
and advanced causal evidence, and Runtime contains only global health, impact, and actions the
backend proves usable. An incident marker opens Runtime directly. These views do not merge
Codex Goal state with a Room turn or process health.

`GET /api/chat/conversations/{id}/codex-agents` returns
`room_codex_projection/v1`. It keeps Codex native snapshot/events separate from the durable
Room Bridge hold, observation-frontier summary, and action ledger. The projection is bounded
and non-authoritative;
native identifiers, raw reasoning, prompts, tool arguments/results, credentials, absolute
paths, and provider output are excluded.

Controls are rendered only from `room_codex_native_capabilities/v1` and the participant's
guarded action descriptors. The browser posts an allowlisted capability, its closed safe
request, opaque expected guards, confirmation bit, and idempotent action ID through the fixed
`/api/room-participants/{id}/codex-actions` route. It cannot submit native method names or raw
RPC parameters. `/goal`, `/model`, `/effort`, `/plan`, `/default`, `/steer`, `/interrupt`,
`/compact`, `/review`, and `/status` are local UI aliases for the same descriptors; the Room
composer does not parse them. Parameterless Plan/Default choices are versioned local UX
preferences and do not change `chat.db` or Codex thread settings.

Native actions use durable internal stages: pre-dispatch work may reconcile a dead session
and re-prove its guards, while `dispatching` is fenced as result-unknown and is never
automatically replayed after a crash. A successful provider acknowledgement is persisted
before best-effort post-action snapshot refresh. These stages are recovery evidence, not
Agent speech or additional browser commands.

The Console refreshes single-flight with room/generation guards and aborts stale Room
requests. While the Agent tab is visible it uses about two seconds for an active native turn
and five seconds while idle; otherwise it falls back to about fifteen seconds. Focus refreshes
only the visible tab. Read or action errors preserve Room projections. Conflict or runtime
unavailability triggers a fresh projection instead of optimistic success.

## Browser state and authority

The URL is `/rooms/{conversation_id}`. The in-memory cache keeps a bounded set of recent Room
projections; the current Room, pinned Rooms, and Rooms with pending sends are protected from
eviction. Drafts use `sessionStorage`. `xmuse.room-ui/v2` stores sidebar and Workbench state,
the selected tab, pinned Room IDs, per-Room selected participant, versioned read cursors,
stable message anchors, and theme in `localStorage` for up to 50 Rooms. A v1 open Inspector
migrates to an open Workbench on the Room tab. Async responses are scoped by Room and request
generation.

`Ctrl/Cmd+K` opens a navigation-only command palette for Room creation/switching, participant
selection, Workbench tabs, and theme. It cannot invoke provider or operator actions. The Room
composer keeps its durable Mention, IME, optimistic-send, retry, and scroll semantics and
never interprets Codex slash commands.

Browser state, optimistic bubbles, events, telemetry, screenshots, provider final text, and
HTTP success text are not room authority. Only accepted `chat.db` transitions establish
messages, Agent outcomes, attempts, controls, and convergence state.
