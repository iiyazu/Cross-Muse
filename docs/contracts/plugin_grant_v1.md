# Plugin grant — contract v1

Status: draft for review (contract-first: no implementation exists). Companion to
`room_board_projection_v2.md` §8, which says host plugins never hold the operator token and that
a separately designed, scoped, short-lived, memory-only, revocable grant must pass a threat-model
review before any write route accepts it. The threat model is `p3-plugin-grant-threat-model.md`
(T1–T15); every rule below names the threat it answers.

## 1. What this adds, and what it does not

A **plugin grant** lets a host plugin (Claude Code mod, OpenCode plugin, later the CLI) perform
exactly one write on behalf of the human who issued it in the Web UI: **approve or reject a
proposed split** (`scope: "board.split.decide"`). Nothing else.

It never covers: review verdicts, the review material route, any other `/api/chat/operator/*`
route, memory, execution, runtime recovery. A route that requires the operator token refuses a
grant (T1).

Compatibility follows `room_board_projection_v2.md` §1: additive; codes and structured values
only; errors are `{"detail": {"code", "message"}}`; timestamps UTC `…Z`; ids opaque.

## 2. Objects

```jsonc
// Grant — never contains the secret or the pairing code
{
  "grant_id": "grant_…",
  "conversation_id": "…",
  "host": "claude-code",              // ^[a-z0-9][a-z0-9_-]{0,31}$, same set as `plugin:<host>`
  "scope": "board.split.decide",      // the only v1 value
  "status": "pending",                // pending | active | expired | revoked
  "created_at": "…",
  "activated_at": null,               // set by the exchange
  "expires_at": "…",                  // see §3.1
  "revoked_at": null,
  "last_used_at": null,
  "use_count": 0
}
```

`status` is derived at read time: `pending` until exchanged and before its pairing expiry;
`active` while `now < expires_at` and not revoked; otherwise `expired` or `revoked`.

Secret: `xpg_<grant_id>_<43 base64url chars>` (256 bits). The server stores only its SHA-256 digest
and compares in constant time. The pairing code is `XXXX-XXXX` over the alphabet
`ABCDEFGHJKMNPQRSTVWXYZ23456789` (40 bits); the server stores only its digest.

## 3. Operator routes (operator token; reached only through fixed Next.js server proxies)

### 3.1 Issue — `POST /api/chat/operator/plugin-grants`

Body (exactly these keys): `{conversation_id, host, scope, ttl_seconds}`; `ttl_seconds` 60–3600
(default 600 if omitted). `201`:

```jsonc
{ "schema_version": "plugin_grant_issue/v1",
  "grant": Grant,                     // status "pending"
  "pairing_code": "ABCD-EFGH",        // shown once, in the browser only
  "pairing_expires_at": "…" }         // issue time + 120 s
```

The code is single-use and expires 120 s after issue. `expires_at` of the grant is set to
`activated_at + ttl_seconds` at exchange time and is `pairing_expires_at` while pending. Issuing
a grant for the same `(conversation_id, host)` revokes every earlier `pending` or `active` grant
for that pair (one live grant per room and host).

Errors: `404 room_conversation_unknown`, `422 plugin_grant_request_invalid`,
`422 plugin_grant_scope_invalid`, `422 plugin_grant_host_invalid`.

### 3.2 List — `GET /api/chat/operator/plugin-grants?conversation_id=…`

`{ "schema_version": "plugin_grant_list/v1", "conversation_id": "…", "grants": [Grant] }`,
newest first, at most 50 (older ones are dropped, not paged). The Web panel shows
`last_used_at` and `use_count` (T12).

### 3.3 Revoke — `POST /api/chat/operator/plugin-grants/{grant_id}/revoke`

Body `{conversation_id}`. Returns the Grant (`status: "revoked"`). Idempotent. `404
plugin_grant_unknown` for an unknown id **or an id of another conversation** (T2).

## 4. Plugin routes (no operator token)

All plugin routes sit behind the existing loopback `Host` guard (T9).

### 4.1 Exchange — `POST /api/chat/plugin/grants/exchange`

Body `{pairing_code, host}`. On success `200`:

```jsonc
{ "schema_version": "plugin_grant_exchange/v1",
  "grant": Grant,                     // status "active"
  "secret": "xpg_…" }                 // returned exactly once; the server keeps only its digest
```

The code is consumed by a successful exchange. `host` must equal the grant's `host`.
Failure is always `401 plugin_pairing_invalid` — wrong, expired, already used and wrong-host are
indistinguishable (T8, T15). Limits (T15): at most 5 failed attempts per pairing code (the 5th
invalidates it); at most 10 failed exchanges per rolling minute across the server, after which
`429 plugin_pairing_locked` (with `Retry-After`) for 60 s.

### 4.2 Decide a split — `POST /api/chat/plugin/board-splits/{split_id}/decision`

`Authorization: Bearer <secret>`. Body exactly `{conversation_id, decision: "approve"|"reject",
expected_digest}`; `expected_digest` is required and must equal `Split.digest` (`409
room_board_split_digest_mismatch`), a body that names `decided_via` or any other key is refused
(`422 plugin_grant_request_invalid`): provenance comes from the grant (T3, T12).

Checks, in order:
1. Bearer present and well-formed, the grant exists, is `active`, and `conversation_id` equals
   the grant's: else `401 plugin_grant_invalid` — one code for unknown, expired, revoked and
   malformed, so the response never reveals which (T8). Each failed bearer for a known
   `grant_id` increments `failed_attempts`; the 5th revokes the grant (T8).
2. Body shape (`422 plugin_grant_request_invalid`).
3. The split exists **in the grant's conversation** (`404 room_board_split_unknown`, also for a
   split of another conversation — T2).
4. Same decision rules as the operator route (`proposed` status, digest). An already decided
   split answers `409` (T3).

On success the decision is recorded exactly as the operator route records it, with
`decided_via: "plugin:<host>"` taken from the grant and `grant_id` added to the decision events
(§6); `last_used_at` and `use_count` are updated. The response is the operator decision response.

### 4.3 Self-revoke — `POST /api/chat/plugin/grants/revoke`

`Authorization: Bearer <secret>`, empty body `{}`. Revokes that grant; `200` Grant. A bad bearer is
`401 plugin_grant_invalid`. A second call also answers `401`, because a revoked grant no longer
authenticates.

## 5. Never in logs or payloads (T7)

The secret, the pairing code, `Authorization` header values and `secret_digest` never appear in
any log line, event, projection, summary, list, error message or crash report. Request logging
redacts `Authorization` and `pairing_code`. Tests grep captured logs and every response of §3–§4
for them.

## 6. Provenance in events (T12)

`split_rejected` and each `charter_assigned` of an approved split carry `decided_via:
"plugin:<host>"` (already allowed by `room_board_projection_v2.md` §8) and now also
`grant_id: string | null` (null for `web` and `cli`). Adding a nullable key is a compatible change
to `room_board_events.v1`; it is a change to code under `room_board*.py`, so it waits for the
review work (#431) to merge and is made by the backend session.

## 7. Client rules

- The browser issues, lists and revokes only through fixed Next.js proxy routes that inject the
  token (same checks as the other fixed writes). The pairing code is shown only there, with a
  countdown, never in a URL, never persisted.
- A plugin receives the pairing code through a text field drawn by the host UI (Claude mod
  `Input`, OpenCode `dialog.prompt`) — never through a slash-command argument, a prompt, a tool
  argument or command output, all of which a model can read (T14). It keeps the secret in memory
  only, never in `$.store`/durable storage, never in a status line, toast or command result.
- The approve and reject actions are bound to buttons the human presses; they are not registered
  as tools or commands (T6). Confirmation shows structured fields only; agent-authored text is
  labelled untrusted and kept away from the confirm control (T11).
- A plugin never calls §3, the review routes or any other operator route.

## 8. Reason-code registry (additions)

`plugin_grant_request_invalid`, `plugin_grant_scope_invalid`, `plugin_grant_host_invalid`,
`plugin_grant_unknown`, `plugin_grant_invalid`, `plugin_pairing_invalid`,
`plugin_pairing_locked`; reused: `room_conversation_unknown`, `room_board_split_unknown`,
`room_board_split_digest_mismatch`, `room_host_invalid`.

## 9. Test obligations

One test per threat row T1–T15 in the threat model (names in the test ids), plus: secret and
pairing code absent from logs; a grant never authenticates an operator route; exchange of a used,
expired, wrong-host and brute-forced code; five bad bearers revoke; issuing a second grant revokes
the first; a plugin-recorded decision shows `decided_via: "plugin:claude-code"` and the
`grant_id`.

## 10. Changelog

- 2026-10-05 — v1 draft.
