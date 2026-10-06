# Main-window control — contract v1

Status: draft (contract first; no implementation yet). It extends `plugin_grant_v1.md`.
Everything that document says still holds unless a section below replaces it.

## 0. Why

xmuse coordinates several agents working on one task. The human drives that from **one main
agent window** (Claude Code first, then OpenCode); xmuse carries the messages, enforces
permissions and sandboxing, and keeps the audit trail. Today every human write goes through the
Web Workroom (plugins are read-only, and a plugin grant can only decide a split and can only be
issued from the Web). This contract lets the human do the writes a coordination run needs from
the main window, without the Web, while keeping the `integrations/` invariants: no plugin holds the
operator token, no write is model-callable, and no agent-authored text reaches model context.

## 1. What a human can do from the main window

| Scope | Action | Route (§4) |
| --- | --- | --- |
| `room.create` | create a Room: lead, module owners, optional reviewer | `POST /api/chat/plugin/rooms` |
| `room.message` | post a Human message to a Room, optionally addressed | `POST /api/chat/plugin/rooms/{conversation_id}/messages` |
| `board.split.decide` | approve or reject a proposed split (unchanged from v1) | `POST /api/chat/plugin/board-splits/{split_id}/decision` |
| `board.review.decide` | rule on a review the Human must decide (§4.4) | `POST /api/chat/plugin/board-reviews/{review_id}/decision` |

Not covered, still operator-only: execution candidates and runs, observation retry/cancel,
runtime recovery, memory candidates and rebuild, Codex actions, grant issue/list/revoke.

## 2. Grant changes

`Grant` gains two fields and becomes schema `plugin_grant/v2`:

```jsonc
{
  "grant_id": "grant_…",
  "host": "claude-code",
  "scopes": ["room.create", "room.message", "board.split.decide", "board.review.decide"],
  "conversation_ids": ["…"],          // the Rooms this grant may act on
  "status": "active",
  "created_at": "…", "activated_at": "…", "expires_at": "…", "revoked_at": null,
  "last_used_at": null, "use_count": 0
}
```

- `scopes` is a non-empty set over the four values of §1. v1's single `scope` is read as
  `scopes: [scope]`; a v1 grant never gains scopes.
- `conversation_ids` holds the Rooms named at issue (0–16) plus every Room created through this
  grant, appended in the same transaction as the creation. A grant acts only on Rooms in this
  set: any other `conversation_id`, or an object (split, review) of another Room, answers `404`
  with the object's own unknown code (v1 T2 unchanged). The set is capped at 16 (`409
  plugin_grant_room_limit`).
- `ttl_seconds` range becomes 60–14400 (4 h), default 3600.
- Up to 4 live grants per `host` (two main windows each pair on their own). Issuing a fifth revokes
  the oldest. Issuing any v2 grant for a host revokes that host's live v1 grants, so a v1 grant
  never runs in parallel with a wider one. `pair --revoke` revokes every grant of the host.
- Storage: v2 grants live in new tables (`plugin_grants_v2`, `plugin_grant_rooms`); the v1 table
  is no longer written. v1 grants are not migrated: they are short-lived, and a new Workroom
  generation invalidates them anyway.
- HTTP: the issue route still accepts the v1 body (`{conversation_id, host, scope, ttl_seconds}`,
  read as one Room and one scope), but every grant response is now v2-shaped
  (`plugin_grant_issue/v2`, `…_list/v2`, `…_exchange/v2`, `…_revoke/v2`). The Web Workroom,
  the only v1 issuer, has been removed; the host plugins move to v2 in the same change. The list
  route takes `conversation_id` or `host`.

## 3. Issue from the terminal

The Web panel is no longer required. `xmuse-workroom pair` issues a grant through the existing
operator route `POST /api/chat/operator/plugin-grants` (body now
`{host, scopes, conversation_ids, ttl_seconds}`) and prints the pairing code:

```
xmuse-workroom pair --host claude-code [--room PREFIX]... [--scope S]... [--ttl SECONDS]
```

- Default scopes: all four of §1. `--room` takes a unique id prefix, as `xmuse-ctl attach` does.
- **TTY only.** It refuses unless both stdin and stdout are terminals (`plugin_pair_tty_required`,
  exit 2). An agent's shell tool has no terminal, so the main-window model cannot obtain a code in
  the normal path (T16).
- The operator token comes from `<root>/runtime/operator-token`, which the Workroom writes at
  start (mode 0600, directory 0700) and deletes at stop. A new Workroom generation writes a new
  token, which invalidates every grant (v1 T5).
- Output: the pairing code, its 120 s expiry, the scopes and the short Room ids. Never logged,
  never written to a file. The human types the code into the plugin's own input field (v1 §7).
- **Exchange report.** `pair` then waits (up to the 120 s) until the code is exchanged or expires
  and prints `exchanged by <host> at <time>` or `expired unused`. A code exchanged before the
  human typed it into the pane is visible at once; the human runs `pair --revoke` (T16).
- `xmuse-workroom pair --revoke --host claude-code` revokes every grant of that host;
  `pair --list` prints the host's live grants with their Room ids (full ids, never prefixes).

## 4. Plugin routes

All `/api/chat/plugin/*` rules of v1 §4 apply: Bearer only, `Origin` refused, JSON only, error
messages never echo the request. Each route records `via: "plugin:<host>"` and `grant_id` in the
Room activity it appends (T12).

Check order on every route: bearer (401) → scope (`403 plugin_grant_scope_denied`; it reveals only
the caller's own grant) → body shape (422) → Room in `conversation_ids` and object in that Room
(404) → the action's own rules. Idempotency keys (`client_request_id`, 1–200 chars) are scoped to
`(grant_id, key)`: the same key under another grant never replays or reveals another grant's
object.

### 4.1 Create a Room — scope `room.create`

```jsonc
POST /api/chat/plugin/rooms
{
  "client_request_id": "…",
  "title": "…",                                   // 1–200
  "lead": {"cli_kind": "opencode"},
  "owners": [{"cli_kind": "opencode"}, {"cli_kind": "claude"}],   // 1–6
  "reviewer": null,                               // or {"cli_kind": "antigravity"}
  "review_policy": "off"                          // off | cross_family
}
```

- Builds the same `RoomConversationCreate` the eval driver builds: `collaboration.mode =
  addressed`, the lead is `lead_role`, owners are `workspace_access = workspace_write` with roles
  `owner-1`…`owner-N`. Models come from the server's provider defaults, never from the body.
  At most 8 participants (lead, owners and reviewer together).
- The workspace is the Workroom's configured execution workspace and profile. The body names no
  path (T17).
- Validation is server-side: `title` 1–200, owners 1–6 (`claude`, `opencode` or `antigravity`),
  total participants ≤ 8, no other keys (`422 plugin_room_request_invalid`). Provider admission is
  the same as `POST /api/chat/conversations`: a provider that is not enabled answers `422
  room_provider_unavailable`.
- Limits: at most one creation per 10 s per grant (`429 plugin_room_rate_limited`) and the 16-Room
  set cap (`409 plugin_grant_room_limit`). The cap check and the rate-limit stamp are one
  transaction, which serializes creations per grant; the Room is then created and appended to
  `conversation_ids`. A creation interrupted before the append is repaired by retrying the same
  `client_request_id`: the replay skips the limits and appends the existing Room.
- `201` returns `{conversation_id, participants: [{participant_id, role, cli_kind}],
  room_count}`: no grant object.

### 4.2 Post a Human message — scope `room.message`

```jsonc
POST /api/chat/plugin/rooms/{conversation_id}/messages
{ "client_request_id": "…", "message": "…", "mentions": ["participant_id", …] }
```

- `message` is 1–32768 characters; `mentions` names participants of this Room (else `422
  plugin_message_mention_invalid`). In an `addressed` Room an unaddressed message goes to the lead,
  as it does from the Web.
- Recorded through the same kernel call as the Web route; the activity carries `via` and `grant_id`.
- The runtime autostart rule is the Web route's.

### 4.3 Decide a split — scope `board.split.decide`

Unchanged from v1 §4.2, except that the split's Room must be in `conversation_ids`.

### 4.4 Decide a review — scope `board.review.decide`

```jsonc
POST /api/chat/plugin/board-reviews/{review_id}/decision
{ "conversation_id": "…", "verdict": "endorse" | "object", "expected_digest": "…",
  "summary": "…", "findings": [ … ] }
```

- Same body rules as the operator review route, except that a body naming `decided_via` is
  refused with `422 plugin_grant_request_invalid`: provenance comes from the grant.
- Only a review that is waiting for the Human may be decided: assigned to the Human (no other
  model family present) or escalated to the operator (`board_review_reviewer_unavailable`,
  `…_no_verdict`, `…_unresponsive`). Otherwise `409 plugin_review_not_human`. The status check,
  the `expected_digest` check and the write are one transaction, so a participant verdict that
  lands first wins and the plugin gets `409`.
- The board projection's `review.decided_via` (`board_tool|web`) gains `plugin:<host>`; consumers
  render an unknown value as a fixed word. `room_board_projection_v2.md` records the addition in
  its changelog.

### 4.5 Read review material — scope `board.review.decide`

`GET /api/chat/plugin/board-reviews/{review_id}/material?conversation_id=…` returns the operator
material route's body (diff, gate tails, path-scrubbed) for a review that §4.4 may decide, else
`409 plugin_review_not_human`. The Web was the only material viewer and is gone; the human must not
decide blind. The plugin draws it only in its pane, labels agent-authored parts untrusted, and
never puts it in command output, a tool result, a status line, a toast or `context` (T14).
Requests without a body still refuse `Origin`; the JSON content-type rule applies to bodies only.

## 5. Host rules (Claude Code mod; OpenCode later)

- The server trusts only the Bearer secret; it cannot see who pressed what. The rules below are
  the plugin's defense in depth, not a server guarantee.
- A write starts only from the human:
  - slash commands (`/xmuse new …`, `/xmuse say …`) run only when `command.run`'s
    `origin.kind` is exactly `composer`. Every other kind, a missing origin and `unclassified`
    are refused with fixed text and no request;
  - split and review decisions stay pane buttons with the v1 two-step confirmation (T11).
- No write is registered as a tool. Command results carry structured fields only (ids, counts,
  fixed words), never agent text, and the mod never sets `context`.
- The pairing code is still entered only in the pane's input field; the secret stays in memory.

## 6. Threats (additions to the v1 model)

| # | Threat | Mitigation | Test |
| --- | --- | --- | --- |
| T6′ | The main-window model triggers a write | commands gated on `origin.kind == "composer"`; decisions are buttons; no write tools | mod test: the same command with each non-composer origin sends nothing |
| T16 | The model obtains a pairing code by running `pair` | TTY-only; code printed only to the terminal; exchange report shows who used the code | `pair` with a non-terminal stdin or stdout exits 2 without calling the server; the report names the exchanging host |
| T17 | A plugin points a Room at another workspace or model | the body names no path and no model; server defaults only | create body with extra keys → 422 |
| T18 | A grant is used on a Room outside its set | `conversation_ids` checked on every route | other-Room message, split and review → 404 |
| T19 | Messages spoofed as the Human | only a grant with `room.message` can post; activity records `via` and `grant_id` | activity assertions |

Residual, accepted (single-user loopback app; cross-family review 2026-10-06 raised both):

- **A same-user process, including the main-window agent's shell, can act as operator.** It can
  read the token file, and before this contract it could already read the token from the Chat
  API's `/proc/<pid>/environ`. A token file only makes that easier to find. The boundary against
  the main-window model is therefore (a) its own sandbox, for example Claude Code's sandbox with
  the xmuse root denied for reading, which the setup guide recommends, (b) no model-callable write
  path, so a prompt-injected model has to go out of its way, and (c) provenance on every write.
- A pseudo-terminal defeats the TTY gate; the exchange report (§3) makes a stolen code visible.
- v1's accepted residuals (public `grant_id` lets a local process burn a grant with bad bearers;
  the global exchange limiter can be exhausted) still apply.
- Not adopted: binding the code to a plugin instance key (PAKE). It would not change the first
  residual.

## 7. Reason codes (additions)

`plugin_grant_scope_denied` (403), `plugin_grant_room_limit` (409),
`plugin_message_mention_invalid` (422), `plugin_review_not_human` (409),
`plugin_room_request_invalid` (422), `plugin_room_rate_limited` (429),
`plugin_pair_tty_required` (CLI exit 2), `workroom_not_running` (CLI exit 3),
`operator_token_file_unsafe` (CLI exit 2: the file is a symlink, not owned by the user, or
readable by others).

## 8. Test obligations

- One test per threat row (T6′, T16–T19) plus the v1 rows that change: T2 now checks the Room set.
- The end-to-end product path: Workroom start → `pair` → create a Room → message → split → owners
  → verification → integration. It runs through the product runner and Chat API, not the eval
  driver's in-process host.
- A v2 grant for a host revokes that host's live v1 grants.
- Idempotency: the same `client_request_id` under two grants creates two Rooms.
- Review decide race: a participant verdict committed first makes the plugin decision `409`.
- The mod: every non-composer origin kind sends nothing; review material never reaches `text`,
  `context`, a status line or a toast.

## 9. Changelog

- 2026-10-06 — v1 draft; cross-family review (OpenCode muse-spark) applied: several live grants
  per host, exchange report, check order, per-grant idempotency, create rate limit, review decide
  in one transaction plus a material route, explicit residuals.
