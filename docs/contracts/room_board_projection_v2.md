# Room board read model — contract v2

Status: **draft for P0** (2026-10-04). Normative for every consumer: the Workroom browser UI,
host plugins (Claude Code mod, OpenCode TUI plugin), `xmuse-ctl`, and the M4 evaluation.
Backend, frontend, plugin tests and the evaluation share the golden fixtures in
`docs/contracts/fixtures/board_v2/`; the JSON Schemas in `docs/contracts/schemas/` are the
machine-readable form of this document. Change this document first, then the schemas and
fixtures, then code.

Authority: `chat.db` is the only authority. Everything below is a *projection*; no consumer
keeps board state of its own and no consumer infers completion from agent text.

## 1. Compatibility rules

1. Clients ignore unknown fields. Adding a field is compatible. Removing a field, changing a
   field's meaning, or widening an enum a client must exhaustively handle bumps the major
   version in `schema_version` (`room_board_projection/v3`, ...).
2. Clients feature-detect through `capabilities`, never through the presence of arrays.
   Capability keys not listed in §3 do not exist yet.
3. The server emits **codes and structured values, never prose for humans**. Every adapter
   localizes (the browser UI is Chinese). Reason codes live in the registry in §9.
4. Errors on every route in this document are `{"detail": {"code": string, "message": string}}`.
   `message` is short English for developers and logs; adapters must not show it to people.
5. Timestamps are UTC ISO-8601 with `Z`. Identifiers are opaque strings.
6. Ordering: `participants` by `participant_id`; `modules` by `module_id`; `contracts` by
   `contract_id`; `splits` by `created_at`; `events` ascending by `seq`; `attention` as in §3.8.

## 2. What never leaves the server in any payload

Host absolute paths; `patch_digest`; `patch_text`; `base_commit`; lease tokens; the text the
host writes *to agents* (`board_activity_content`, delivery context, `payload.content`); raw
`payload` objects of activities; `evidence` objects of verification results; the full list of
changed paths (only `changed_path_count`); review `rule_inputs_json` and `verdict_json` as
stored. Charter `paths` are repository-relative globs and may be shown. `head_commit` may be
shown.

Tests assert this by scanning every fixture and every route response for these keys and for
absolute-path-looking strings.

Exactly two values leave the server in a narrower form, each through one route only:

1. **Gate output tails** (from `evidence.output_tails`) leave as `AgentText` through the
   verification detail route (§5.2), never through the projection, summary, events or stream.
   The host scrubs them at the source before storing: the stage root is removed, the repository
   mount becomes repository-relative paths, toolchain mounts become placeholders (`<python>`,
   `<site-packages>`, `<tools>`, `<git>`), and **every other absolute path** (Unix, including
   sandbox system paths such as `/usr/lib/…` or `/etc/…`, and Windows drive paths) becomes
   `<host-path>`. URLs are left alone.
2. **The patch under operator review** leaves through the review material route (§8.2) and
   nowhere else: only for a review with `reviewer_kind == "operator"`, only with the operator
   token, only through the Web server proxy. It is the reviewed module's own stored patch text
   from that verification (bound by `Review.digest`, §3.10), not a re-read of the owner branch
   and not the patches of stacked modules. Plugins, the CLI and the Claude Code mod never call
   it, and no plugin grant covers it.

The path scan whitelists the material route's `patch.text` field and nothing else.

## 3. `room_board_projection/v2`

`GET /api/chat/conversations/{conversation_id}/board`

```jsonc
{
  "schema_version": "room_board_projection/v2",
  "metrics_version": "board_metrics/v1",
  "conversation_id": "…",
  "server_time": "2026-10-04T10:00:00Z",
  "board_seq": 41,              // §3.9
  "revision": "41:9f2c0a7d41be",// §3.9, doubles as the ETag value
  "capabilities": { "verification": 1, "reviews": 0, "integrations": 0, "lessons": 0 },
  "review_policy": "off",       // off | cross_family (§3.10)
  "participants": [ Participant ],
  "modules": [ Module ],
  "contracts": [ ContractSummary ],
  "splits": [ Split ],
  "stale_dependents": [ StaleDependent ],
  "attention": [ AttentionItem ],
  "events": [ Event ]           // newest 50, ascending
}
```

`capabilities`: `verification: 1` means the host verifies `done` reports (M1). `reviews: 1`
means the room's `review_policy` is `cross_family`: every passed verification opens a review
(§3.10). `integrations` and `lessons` are `0` until M2b/M3 define and ship their shapes; the
keys exist so clients can already feature-detect. No placeholder arrays exist for them.

### 3.1 `AgentText`

Every string authored by an agent is wrapped, so a consumer cannot render it by accident:

```jsonc
{ "text": "…", "untrusted": true, "truncated": false }
```

- The server strips C0/C1 control characters (except `\n` and `\t`), ANSI escape sequences,
  and Unicode bidirectional controls (U+061C, U+200E, U+200F, U+202A–U+202E, U+2066–U+2069)
  before wrapping, and truncates to the field's bound on a code-point boundary (`truncated`).
- `untrusted` is always `true`. Status lines, toasts, CLI one-liners, notification titles and
  anything written into a model's context must not contain `AgentText.text`.
- Bounds: `title` ≤ 120, `summary` ≤ 400, `question` ≤ 400, `rationale` ≤ 400, each claim ≤ 200
  (at most 8 claims in an event; `claims_total` carries the real count).

### 3.2 `Participant`

```jsonc
{ "participant_id": "…", "display_name": "…", "provider_kind": "opencode",
  "model_family": "opencode", "role_preset": "frontend-owner" /* or null */, "is_lead": false }
```

All participants of the room. `provider_kind` is the participant's `cli_kind`. `model_family`
is an opaque label the server derives for cross-family rules; today it equals the family the
exact-patch `cross_family_review` already uses (`cli_kind`), so the board and the execution
gate never disagree. M2 may refine it. Members are agent + role preset and can change at any
time; no consumer hard-codes a vendor or role.

### 3.3 `Module`

One row per module whose **latest charter is `active`**.

```jsonc
{
  "module_id": "frontend",
  "title": AgentText,
  "owner_participant_id": "…",
  "report_to": "…",             // participant id or null
  "charter_version": 1,
  "paths": ["src/ui/**"],       // charter globs, repository-relative
  "provides": ["ui.api"],       // contract ids
  "depends": ["backend.api"],
  "lifecycle": "working",       // §4.1, reported by the owner
  "verification": Verification, // §4.2, established by the host
  "counters": Counters,         // §6
  "state": "verifying",         // §4.3, derived single value for compact UI
  "review": Review,             // §3.10, always present
  "accepted": false,            // §4.4, always present
  "attention": { "kind": "none", "reason_code": null } // §3.8
}
```

`Verification`:

```jsonc
{
  "status": "none",             // none|waiting_for_provider|pending|running|passed|failed|error
  "verification_id": null,
  "reason_code": null,          // §9; present for failed/error/waiting_for_provider/pending-after-abandon
  "escalated": false,           // three consecutive failures reached the lead / report_to
  "gate_ids": [],               // gates of the latest failed result whose status is not "passed"
  "stacked": [ { "module_id": "backend", "verification_id": "…" } ],
  "head_commit": null,          // commit of the owner branch that was verified
  "changed_path_count": 0,
  "updated_at": null
}
```

### 3.4 `ContractSummary`

```jsonc
{ "contract_id": "backend.api", "latest_version": 2, "versions_count": 2, "digest": "sha256:…",
  "provider_module_id": "backend", "kind": "api_schema",
  "author_participant_id": "…", "updated_at": "…" }
```

Version history and content come from §5.

### 3.5 `Split`

```jsonc
{
  "split_id": "…", "status": "proposed",     // proposed|approved|rejected|superseded
  "proposed_by_participant_id": "…", "created_at": "…", "decided_at": null,
  "digest": "sha256:…",                      // canonical digest of the stored split; the approval guard
  "decided_via": null,                       // web | plugin:<host> | cli | null (§8)
  "actions": { "decide": {                   // same descriptor convention as the other operator actions
    "available": true,                       // true only while status == "proposed"
    "method": "POST",
    "href": "/api/chat/operator/board-splits/<split_id>/decision",
    "expected_digest": "sha256:…",           // equals `digest`
    "allowed_decisions": ["approve", "reject"] } },
  "modules": [ { "module_id": "…", "title": AgentText, "owner_participant_id": "…",
                 "paths": [], "provides": [], "depends": [] } ],
  "contracts": [ { "contract_id": "…", "provider_module_id": "…", "kind": "text", "digest": "sha256:…" } ]
}
```

Contract content and charter `acceptance` are not part of a split summary. `acceptance` is
descriptive text, is never executed and never shown as a result.

### 3.6 `StaleDependent`

```jsonc
{ "contract_id": "backend.api", "revised_version": 2, "revised_seq": 17,
  "module_id": "frontend", "owner_participant_id": "…" }
```

A contract with `versions_count ≥ 2` is *revised*. For its **latest** revision, every active
module whose charter `depends` on the contract (the provider module excluded) is stale until
that module's owner files a progress report whose activity `seq` is greater than
`revised_seq`. This is the measurable form of contract drift.

### 3.7 `Event`

```jsonc
{ "seq": 17, "kind": "contract_revised", "at": "…", "module_id": "backend" /* or null */,
  "actor": { "kind": "participant", "participant_id": "…" /* null unless kind=participant */ },
  "data": { … } }
```

`actor.kind` ∈ `participant | operator | infrastructure`. `data` is a per-kind whitelist
(never the raw activity payload):

| `kind` | `module_id` | `data` |
| --- | --- | --- |
| `split_proposed` | — | `{split_id, module_ids[]}` |
| `split_rejected` | — | `{split_id, decided_via}` |
| `charter_assigned` | assigned module | `{split_id, owner_participant_id, charter_version, decided_via}` |
| `claimed` | claimed module | `{}` |
| `contract_published`, `contract_revised` | provider module | `{contract_id, version, kind, digest, rationale: AgentText\|null}` |
| `progress` | reporting module | `{status, summary: AgentText, claims: [AgentText], claims_total}` |
| `question` | — | `{target_participant_id, question: AgentText}` |
| `verification` | verified module | `{verification_id, status: passed\|failed\|error, reason_code, gate_ids[], escalated, stacked[]}` |
| `review_requested` | reviewed module | `{review_id, verification_id, rule_id, author_family, reviewer_kind, reviewer_participant_id, reviewer_family, escalated_from: Escalation\|null}` |
| `review` | reviewed module | `{review_id, verdict: endorse\|object, findings_count, findings: [Finding], findings_total, summary: AgentText, decided_via: board_tool\|web}` |

`review_requested` is always `infrastructure`; a request re-issued to the operator after the
assigned reviewer did not answer carries `escalated_from` (§3.10). `review` is `participant`
(the assigned reviewer, through the Room MCP tool) or `operator` (through the Web). In events
`summary` ≤ 400 and each `Finding.text` ≤ 200, at most 8 findings, `findings_total` the real
count; the review detail route (§5.1) carries the full bounds.

An unknown `kind` must be tolerated by clients (rule 1).

### 3.8 `AttentionItem` and `Module.attention`

```jsonc
{ "kind": "operator", "reason_code": "board_attention_split_pending",
  "module_id": null, "split_id": "…" }
```

`kind` says who has to act: `operator` (the human), `lead` (the room lead or the charter's
`report_to`), `owner` (the module owner). Status lines and toasts look only at this field.
`Module.attention` is the same pair for one module (`kind: "none"` and `reason_code: null`
when nothing is needed); the top-level `attention` list is room-level items plus every
module's non-`none` attention, sorted `operator`, `lead`, `owner`, then by `module_id`, then
by `split_id`.

Per-module precedence (the first matching row wins):

| Condition | `kind` | `reason_code` |
| --- | --- | --- |
| `verification.status == error` | `operator` | `board_attention_verification_error` |
| `verification.status == failed` and `escalated` | `lead` | `board_attention_verification_escalated` |
| `verification.status == failed` and `lifecycle == done_claimed` | `owner` | `board_attention_verification_failed` |
| `review.status == pending` and `review.reviewer_kind == operator` | `operator` | `board_attention_review_operator_pending` |
| `review.status == objected` and `lifecycle == done_claimed` | `owner` | `board_attention_review_objected` |
| `lifecycle == blocked` | `lead` | `board_attention_module_blocked` |
| module is a stale dependent | `owner` | `board_attention_contract_stale` |
| otherwise | `none` | `null` |

Room-level: every split with `status == proposed` yields `operator` /
`board_attention_split_pending` with its `split_id`.

A `failed` verification stops being attention once the owner files any newer progress report
(`lifecycle` leaves `done_claimed`); the verification axis still shows the failure. The same
holds for an `objected` review. A participant review that is merely `pending` is not
attention: either the reviewer answers or the host escalates it to the operator (§3.10), and
the escalated review then matches the operator row above.

### 3.9 `board_seq` and `revision`

`board_seq` is the largest `room_activities.seq` of `board.*` activities in the conversation
(`0` when none). It is the cursor of the event feed. Not every visible change writes an
activity (a job moving to `running` or being deferred does not), so the projection also
carries `revision = "<board_seq>:<12 hex>"`, where the hex part is the SHA-256 prefix of the
canonical JSON of the projection **without** `server_time`, `events` and `revision`. Two
projections with equal `revision` are equal. `GET .../board` and `GET .../board/summary` send
`ETag: "<revision>"` and answer `If-None-Match` with `304`. `Cache-Control: no-store`.

### 3.10 `Review`, `review_policy` and escalation

`review_policy` is set when the room is created, is `off` unless the setup asks for
`cross_family`, and never changes afterwards. With `off`, no review is ever opened and
`Module.review.status` is always `none`. Clients decide behaviour from
`capabilities.reviews` only; `review_policy` is for display. With `cross_family`, the same transaction that records a `passed` verification opens a
review whose reviewer is assigned by rule `cross_family/v1`: an active agent of a different
`model_family` than the module's owner (the author), preferring the module's previous
reviewer, then the fewest pending reviews, then the lowest `participant_id`. With no such
agent the operator reviews; a same-family agent never does. The author never reviews or picks
its reviewer. The rule's inputs are stored with the review (§5.1 `rule_inputs`).

```jsonc
{
  "status": "none",               // none | pending | endorsed | objected
  "review_id": null,
  "verification_id": null,        // the passed verification under review
  "digest": null,                 // "sha256:<64 hex>", see below; the decision guard
  "rule_id": null,                // "cross_family/v1"
  "author_family": null,
  "reviewer_kind": null,          // participant | operator
  "reviewer_participant_id": null,// null when reviewer_kind == operator
  "reviewer_family": null,        // null when reviewer_kind == operator
  "escalated_from": null,         // Escalation, when the host moved the review to the operator
  "findings_count": { "blocker": 0, "major": 0, "minor": 0 },
  "decided_via": null,            // board_tool | web
  "updated_at": null,
  "actions": {}                   // { "decide", "material" } only while pending with reviewer_kind == operator
}
```

`Module.review` is the review of the module's **current** verification (`verification.
verification_id`): when that verification has no review (not passed, or reviews off), every
field is the `none` value above. Older reviews, including `superseded` ones, are reachable
only through events and §5.1.

**What a review covers.** A verification may stack upstream modules' verified patches
(`Verification.stacked`) so the whole-repository gates can run; each module's own patch is
stored separately. A review covers **only the reviewed module's own patch**: that is what the
reviewer reads (the participant through `chat_room_board_read`, the operator through §8.2) and
what an endorsement vouches for. A stacked module's code is vouched for by that module's own
review; it is never accepted through a dependent's review.

**`digest`** = `"sha256:" + hex(SHA-256(canonical JSON of {review_id, verification_id,
head_commit, patch_sha256}))`, where `patch_sha256` is the SHA-256 of the reviewed module's
own stored patch bytes. `patch_sha256` takes part in the digest only and never leaves the
server. Because the material route returns the same `digest`, an operator decision guarded by
`expected_digest` proves the human decided on exactly the bytes they were shown.

`Escalation` = `{ "participant_id": "…", "family": "…", "reason_code": "board_review_reviewer_*",
"at": "…" }`. A host background loop moves a pending participant review to the operator when
the reviewer is no longer active or its delivery of the request exhausted its attempts
(`board_review_reviewer_unavailable`), when the reviewer's turn ended without a verdict
(`board_review_reviewer_no_verdict`), or when no verdict arrived within the response window
(`board_review_reviewer_unresponsive`; default 3600 seconds from the request, set by the
server environment variable `XMUSE_BOARD_REVIEW_RESPONSE_SECONDS`). The `review_id` and
`digest` stay; the former reviewer can no longer decide. Escalation always writes a
`board.review_requested` activity (event `review_requested` with `escalated_from`, actor
`infrastructure`, audience the room lead or `report_to`, waking nobody), so `board_seq` and
`revision` change even though a timer triggered it.

`actions` (operator reviews only, Web only — §8.1, §8.2):

```jsonc
{ "decide": { "available": true, "method": "POST",
              "href": "/api/chat/operator/board-reviews/<review_id>/decision",
              "expected_digest": "sha256:…",   // equals `digest`
              "allowed_verdicts": ["endorse", "object"] },
  "material": { "available": true } }        // no href: the Web uses its own fixed proxy route
```

Both are present only while `status == "pending"` and `reviewer_kind == "operator"`. The
material route's path never appears in any payload; host plugins, the CLI and the mod act on
neither descriptor.

`Finding` = `{ "severity": "blocker|major|minor", "path": "src/x.py" /* repository-relative or
null */, "text": AgentText }`. An `object` verdict carries at least one `blocker` or `major`
finding. A reviewer's `object` wakes the owner; `endorse` wakes nobody.

**Verdict limits** (enforced identically for the Room MCP tool and the operator route, §8.1):
`summary` is required for both verdicts, 1–4000 characters after trimming; at most 32
findings; each finding `text` 1–1000 characters; `path` is `null` or a repository-relative
path of at most 512 characters with `/` separators — no leading `/`, no drive letter, no
backslash, no `.` or `..` segment, no control characters and no Unicode format characters
(category Cf, which includes the bidirectional controls: a path must not be able to display
as a different file name). A violation is rejected whole
(`room_board_review_summary_invalid` or `room_board_review_findings_invalid`); nothing is
truncated on input. On output `path` is guaranteed to satisfy the same rule.

## 4. State model

Two independent axes plus derived values. Never merge them.

### 4.1 `lifecycle` — what the owner says

Evaluated over the module's progress reports filed by the current owner at or after the
current charter's `created_at`, latest report wins.

| Value | Meaning |
| --- | --- |
| `assigned` | charter exists, not claimed, no report |
| `claimed` | claimed, no report yet |
| `working`, `blocked`, `ready_for_review` | status of the latest report |
| `done_claimed` | latest report is `done` — **a claim, not completion** |

### 4.2 `verification` — what the host proved

Taken from the latest non-`superseded` row of the module's verification jobs at or after the
current charter's `created_at`. `waiting_for_provider` is `pending` plus
`reason_code == board_verification_waiting_for_provider`. No row → `none`.
`escalated` is true when the latest status is `failed` and the trailing run of terminal
results (`passed`/`failed`, newest first) is at least `MAX_CONSECUTIVE_FAILURES` (3) failures.

### 4.3 `state` — one value for compact UIs

If `lifecycle == done_claimed`:

| `verification.status` | `state` |
| --- | --- |
| `passed` | `verified` |
| `failed` | `verification_failed` |
| `error` | `verification_error` |
| `pending`, `running` | `verifying` |
| `waiting_for_provider` | `waiting_for_provider` |
| `none` | `done_claimed` |

Otherwise `state == lifecycle`. All states: `assigned, claimed, working, blocked,
ready_for_review, done_claimed, verifying, waiting_for_provider, verified,
verification_failed, verification_error`.

**`done_claimed` and `verified` must be visually unmistakable in every consumer.** A verified
module is the only evidence of completion. `done_claimed` is only observable for the instant
before a verification row exists, and during that instant it still is not completion.

Acceptance text in a charter is never a source for any of these values; only server gate
results are.

`state` does not change with reviews; a review is its own axis (§3.10).

### 4.4 `accepted` — the one completion value

```
accepted = state == "verified" AND (capabilities.reviews == 0 OR review.status == "endorsed")
```

This definition is frozen for `room_board_projection/v2`. Later milestones never add
conditions to it (integration status is its own field); a combined "landed" value would be a
new field. Consumers show a completion mark only for `accepted`; `verified && !accepted`
shows "verified" plus the review status (pending / objected), distinguished by glyph and
text, never by colour alone.

## 5. Contract detail

`GET /api/chat/conversations/{conversation_id}/board/contracts/{contract_id}?version=N`
(404 `room_board_contract_unknown`; 422 `room_board_version_invalid`)

```jsonc
{
  "schema_version": "room_board_contract/v2",
  "conversation_id": "…", "contract_id": "backend.api",
  "provider_module_id": "backend", "kind": "api_schema",
  "versions": [ { "version": 1, "digest": "sha256:…", "author_participant_id": "…",
                  "created_at": "…", "rationale": AgentText /* or null */ } ],
  "version": 2,                       // the version `content` belongs to (default: latest)
  "content": { "text": "…", "untrusted": true, "truncated": false }
}
```

`content` is at most 64 KiB (the store's write limit) and sanitized like `AgentText`.
`digest` covers the stored original bytes. Consumers render `content` as **plain text**
(a code block); if a consumer renders it as Markdown it must disable raw HTML and
non-`http(s)` links first. `content` never appears in a status line, toast or notification.

### 5.1 Review detail

`GET /api/chat/conversations/{conversation_id}/board/reviews/{review_id}`
(404 `room_board_review_unknown`, also when the review exists but belongs to another
conversation: detail routes never reveal whether an id exists elsewhere)

```jsonc
{
  "schema_version": "room_board_review/v1",
  "conversation_id": "…", "module_id": "backend",
  "review": Review,               // §3.10 fields, without `actions`; status may also be "superseded"
  "head_commit": "…",             // the verified commit, full id
  "summary": AgentText /* ≤ 4000, or null while pending */,
  "findings": [ Finding ],        // ≤ 32, text ≤ 1000
  "rule_inputs": {
    "rule_id": "cross_family/v1",
    "author_participant_id": "…", "author_family": "opencode",
    "eligible": [ { "participant_id": "…", "family": "antigravity", "pending": 0 } ],
    "last_reviewer_participant_id": null,
    "picked_participant_id": "…"  // null → operator
  },
  "created_at": "…", "decided_at": null
}
```

`rule_inputs` answers "why this reviewer": a client can re-apply §3.10 to it and must get
`picked_participant_id`. `Cache-Control: no-store`.

### 5.2 Verification detail

`GET /api/chat/conversations/{conversation_id}/board/verifications/{verification_id}`
(404 `room_board_verification_unknown`, also for a verification of another conversation)

```jsonc
{
  "schema_version": "room_board_verification/v1",
  "conversation_id": "…", "module_id": "backend", "verification_id": "…",
  "status": "failed", "reason_code": "board_verification_gate_failed",
  "head_commit": "…", "changed_path_count": 3,
  "stacked": [ { "module_id": "…", "verification_id": "…" } ],
  "gates": [ { "gate_id": "python_uv_pytest", "status": "failed", "exit_code": 1,
               "reason_code": "execution_gate_failed",
               "output_tail": AgentText /* ≤ 2000, or null */ } ],
  "created_at": "…", "updated_at": "…"
}
```

`output_tail` is present (non-null) for at most 3 non-passed gates. It is scrubbed (§2) and
sanitized like `AgentText`, rendered as plain text, and never shown in a status line, toast,
summary or event. The Claude Code mod and other host plugins never fetch this route (their
output reaches model context). `Cache-Control: no-store`; not part of `revision`.

## 6. Metrics — `board_metrics/v1`

Per module, over all history of the module id:

| Counter | Definition |
| --- | --- |
| `done_reports` | progress reports with `status == done` |
| `passed`, `failed`, `superseded`, `errored` | verification jobs in that terminal status; deferred `pending` jobs are not counted |
| `rework_rounds` | `failed` jobs **before the first `passed`**; all `failed` jobs if it never passed |
| `reviews_endorsed`, `reviews_objected` | reviews of the module that ended in that verdict (superseded and pending ones are not counted) |

Adding a counter does not change the others, so `metrics_version` stays `board_metrics/v1`;
changing any definition bumps it. The M4 evaluation and every UI read the same
derivation function; there is exactly one (`xmuse_core.chat.room_board_projection`), used by
the HTTP projection, the Room MCP `chat_room_board_read` module states and the owner's
`.xmuse` view.

## 7. Change feeds

All are read-only, `Cache-Control: no-store`, and need no authentication beyond the loopback
boundary.

### 7.1 Summary — `GET …/board/summary`

```jsonc
{ "schema_version": "room_board_summary/v1", "conversation_id": "…", "server_time": "…",
  "board_seq": 41, "revision": "41:9f2c0a7d41be", "capabilities": { … },
  "modules_total": 3,
  "counts": { "assigned": 0, "claimed": 0, "working": 1, "blocked": 0, "ready_for_review": 0,
              "done_claimed": 0, "verifying": 1, "waiting_for_provider": 0, "verified": 1,
              "verification_failed": 0, "verification_error": 0 },
  "accepted_total": 1,
  "attention_total": 2, "attention": [ AttentionItem ] /* first 5 */ }
```

Structured fields only: no `AgentText`, no titles. Intended for status lines, toasts,
`xmuse-ctl status`. All eleven `counts` keys are always present; `counts` holds only `state`
values, so the number of `accepted` modules (§4.4) is the separate `accepted_total`.

### 7.2 Events, long-poll — `GET …/board/events?after_seq=N&limit=100&wait=25&revision=R`

```jsonc
{ "schema_version": "room_board_events/v1", "conversation_id": "…",
  "board_seq": 41, "revision": "41:9f2c0a7d41be",
  "events": [ Event ], "has_more": false, "reset": false }
```

Returns events with `seq > after_seq` (ascending, at most `limit`, default 100, max 200).
With `wait > 0` (max 30 seconds) and nothing new it holds the request until `board_seq`
changes **or** the server `revision` differs from the `revision` the client passed, then
returns; on timeout it returns an empty list. `reset: true` means `after_seq` is ahead of the
server (restored database): the client discards its cache and reloads §3. Clients use the
returned `revision` to decide whether to refetch §3 or §7.1.

### 7.3 Stream, SSE — `GET …/board/stream`

`Content-Type: text/event-stream`. Event `board` carries one `room_board_events/v1` object as
`data`, with `id: <board_seq>`; a revision-only change is a `board` event with an empty
`events` list. The first event after connecting holds the events after `Last-Event-ID`
(or none, when absent). `reset` when `Last-Event-ID` is ahead of the server. `: heartbeat`
comment every 15 seconds. Same template as `/agent-streams`.

## 8. Writes, authorization, provenance

- **Reads**: loopback, the existing CORS rule, and a `Host`-header guard on the whole chat API:
  a request whose `Host` is not `127.0.0.1`, `localhost` or `[::1]` (any port) is refused with
  `400 room_host_invalid` before routing, which closes DNS-rebinding reads. Plugins and the CLI
  must therefore address the API by a loopback name, never by a LAN address or a custom hostname.
- **Writes**: operator actions need the server-only operator token. The browser reaches them
  only through the Next.js server proxies that inject the token. Host plugins never hold the
  token in P2; in P3 they use a separately designed, scoped, short-lived, memory-only,
  revocable plugin grant that must pass a threat-model review (cross-room, replay, expiry,
  revocation, model-initiated paths) before any write route accepts it.
- Writes originate from a human action (button or command). Plugins must not register them as
  model-callable tools.
- Every operator decision records `decided_via` ∈ `web`, `plugin:<host>`, `cli` in the event
  `data` (`split_rejected`, and every `charter_assigned` of the approved split). Those events also
  carry `grant_id: string | null` (the grant id for plugin decisions, `null` for `web` and `cli`;
  see `plugin_grant_v1.md` §6).
  `POST /api/chat/operator/board-splits/{split_id}/decision` accepts
  `{conversation_id, decision, expected_digest?, decided_via?}`: `decided_via` defaults to
  `web` and must be `web` or `cli` (else `422 room_board_decided_via_invalid`); `plugin:<host>`
  is recorded only by the plugin grant route (`plugin_grant_v1.md` §4.2), which takes it from
  the grant; `expected_digest`, when present, must equal
  `Split.digest` of the stored split (else `409 room_board_split_digest_mismatch`, nothing
  decided). Clients take `href`, `expected_digest` and the allowed decisions from
  `Split.actions.decide` rather than building them. The Next.js proxy fixes
  `decided_via: "web"` itself; a browser can never claim another provenance.

### 8.1 Review verdicts

An assigned participant reviewer decides through the Room MCP tool `chat_room_board_review`
(lease-bound, idempotent, assignee only); its events carry `decided_via: "board_tool"`. Host
plugins never register that tool, or any review write, for a host's own model: review verdicts
belong to Room agents and to the human in the Web.

An operator review is decided **only in the Web**:
`POST /api/chat/operator/board-reviews/{review_id}/decision` with exactly
`{conversation_id, verdict: "endorse"|"object", expected_digest, summary, findings, decided_via?}`
and no other key (`422 room_board_review_request_invalid`). Checks, in order:

1. Body at most 64 KiB (`413 room_board_review_request_too_large`); shape and the verdict
   limits of §3.10 (`422 room_board_review_request_invalid`,
   `room_board_review_summary_invalid`, `room_board_review_findings_invalid`); `object` needs a
   `blocker` or `major` finding (`422 room_board_review_findings_invalid`).
2. `decided_via` may only be `web` (`422 room_board_decided_via_invalid`) — this route's set
   differs from the split route's on purpose.
3. The review exists **in `conversation_id`** (`404 room_board_review_unknown` otherwise,
   including a review of another conversation).
4. It is pending with `reviewer_kind == "operator"` (`409 room_board_review_not_pending`).
5. `expected_digest` is required and equals `Review.digest` (`409
   room_board_review_digest_mismatch`).
6. `endorse` is refused with `409 room_board_review_material_incomplete` when the material
   (§8.2) is truncated: a human does not endorse what they could not read; `object` stays
   allowed.

Nothing is decided when any check fails. The P3 plugin grant never covers this route.

### 8.2 Review material — the one patch route

`GET /api/chat/operator/board-reviews/{review_id}/material?conversation_id=…` (operator
token; 404 `room_board_review_unknown`, also for a review of another conversation; 409
`room_board_review_not_operator` unless `reviewer_kind == "operator"`)

```jsonc
{
  "schema_version": "room_board_review_material/v1",
  "review_id": "…", "verification_id": "…", "head_commit": "…",
  "digest": "sha256:…",           // equals Review.digest
  "patch": { "text": "…", "bytes_total": 18234, "truncated": false, "hidden_char_count": 0 }
}
```

- `patch.text` is the reviewed module's own stored patch from that verification (the bytes
  its digest covers, §3.10), not the owner branch as it is now and not stacked modules'
  patches. `bytes_total` is the size of those stored bytes **before** marking. Exported
  patches are at most 200 KiB, but markers can grow the text: `text` is cut so its UTF-8 size
  is at most 256 KiB, only at a line or marker boundary (never inside a marker or a code
  point), and `truncated` says so.
- Hidden characters are **made visible, not removed**: every C0/C1 control except `\n` and
  `\t`, every ANSI escape introducer and every bidirectional control is replaced by a marker
  `<U+XXXX>`, and `hidden_char_count` counts the replacements. This differs from `AgentText`
  sanitizing on purpose: a reviewer must see the code as it is (Trojan Source).
- The Web reaches it only through a Next.js server proxy that checks a loopback `Host` and
  `Sec-Fetch-Site: same-origin` and answers `Cache-Control: no-store`. It renders `patch.text`
  as plain text only. Plugins, the CLI and the mod never call it.

## 9. Reason-code registry

Verification (`Verification.reason_code`, event `reason_code`):
`board_verification_gate_failed`, `board_verification_outside_charter`,
`board_verification_waiting_for_provider`, `board_verification_dependency_overlap`,
`board_verification_base_mismatch`, `board_verification_provider_patch_missing`,
`board_verification_charter_unknown`, `board_verification_evidence_unavailable`,
`board_verification_attempts_exhausted`.

Patch export: `owner_patch_empty`, `owner_patch_binary`, `owner_patch_reserved_path`,
`owner_patch_too_large`, `owner_patch_too_many_files`, `owner_patch_fetch_failed`,
`owner_clone_missing`, `owner_clone_metadata_invalid`.

Staging and gates (from `room_execution`): `execution_*` (for example
`execution_patch_*_rejected`, `execution_repo_busy`, `execution_frontend_dependencies_unavailable`).

Split: `room_board_split_dependency_cycle` and the other `room_board_*` validation codes.

Review escalation (`Escalation.reason_code`, §3.10): `board_review_reviewer_unavailable`,
`board_review_reviewer_no_verdict`, `board_review_reviewer_unresponsive`.

Attention (§3.8): `board_attention_split_pending`, `board_attention_verification_error`,
`board_attention_verification_escalated`, `board_attention_verification_failed`,
`board_attention_review_operator_pending`, `board_attention_review_objected`,
`board_attention_module_blocked`, `board_attention_contract_stale`.

Route errors: `room_host_invalid`, `room_conversation_unknown`, `room_board_contract_unknown`,
`room_board_version_invalid`, `room_board_split_digest_mismatch`, `room_board_query_invalid`,
`room_board_decided_via_invalid`, `room_board_review_unknown`,
`room_board_verification_unknown`, `room_board_review_digest_mismatch`,
`room_board_review_not_pending`, `room_board_review_not_operator`,
`room_board_review_material_incomplete`, `room_board_review_findings_invalid`,
`room_board_review_summary_invalid`, `room_board_review_request_invalid`,
`room_board_review_request_too_large`.

Routes that take an id under a `conversation_id` answer 404 for an id of another
conversation, and each such route has a test for it.

A reason code unknown to a client is shown as a generic "unknown reason" plus the code string,
never hidden.

## 10. Fixtures

`docs/contracts/fixtures/board_v2/<scenario>.json` — each file is the exact output of the
production derivation for a deterministic scenario (`{"projection": …, "summary": …,
"events_page": …}`). The pytest suite regenerates every fixture and fails on any difference;
`UPDATE_BOARD_FIXTURES=1` rewrites them. The frontend vitest suite and plugin tests load the
same files and never hand-edit them.

Scenarios: `empty`, `split_pending`, `lifecycle_mix` (assigned, claimed, working, blocked,
ready_for_review), `verifying_and_waiting`, `verified`, `verification_failed_rework`,
`verification_escalated`, `verification_error`, `superseded_done`,
`contract_revised_stale_dependent`, `injection_text` (agent text with prompt-injection
strings, ANSI escapes, RTL controls, over-long values); with `review_policy: cross_family`:
`review_participant_pending`, `review_operator_pending` (single-family room),
`review_endorsed` (an `accepted` module), `review_objected` (owner attention, injection text
in findings), `review_superseded` (a newer `done` replaces a pending review),
`review_escalated` (reviewer turn ended without a verdict → operator). The pre-review
scenarios run with `review_policy: off` and differ from their earlier form only by the
always-present `review_policy`, `Module.review`, `Module.accepted` and `accepted_total`.
Routes §5.1, §5.2 and §8.2 have their own golden responses next to the scenarios
(`<scenario>.review.json`, `<scenario>.verification.json`, `<scenario>.material.json`).
Required coverage: `review_operator_pending` reviews a dependent module whose verification
stacked a provider (its material holds only the dependent's own patch) and whose patch
contains a bidirectional control and an ANSI escape (shown as markers, `hidden_char_count >
0`); `verification_failed_rework.verification.json` has a tail whose raw gate output held a
stage path, `/usr/lib/…`, `/home/…` and a Windows drive path (all scrubbed). `done_claimed` and every attention
row are additionally covered by a table-driven test over the pure derivation functions with
synthetic facts, because the store cannot produce `done_claimed` without a verification row.

## 11. P0 checklist (non-contract items to verify while implementing)

- `Host`-header validation on read routes: **verified absent** before this change (a request
  with `Host: evil.example` was served); now enforced for the whole chat API (§8).
- `GET /board` uses a read-only connection (done); no contention measurement was taken, the
  read-only connection is simply the safer default.
- `summary` on a database with 10,000 activities answers in under 50 ms (asserted in tests).
- The `/board` 422 string `detail` is replaced by the §1 error shape.

## 12. Changelog

- 2026-10-04 — reviews (M2a), compatible additions: `review_policy`, `capabilities.reviews`,
  `Module.review` with escalation and the Web-only operator decision, frozen `Module.accepted`,
  `accepted_total`, review counters, `review_requested`/`review` events, two attention rows,
  review and verification detail routes, and the two §2 exceptions (scrubbed gate output
  tails; the operator review material route).

- 2026-10-04 — `Split.actions.decide` descriptor and decision provenance (`decided_via`,
  `expected_digest`); the cross-domain operator inbox (`room_operator_inbox/v1`) is deferred to
  the phase that needs it (plugin approvals) and is not part of this contract version yet.
- 2026-10-04 — draft v2: removes v1 aliases (`id`, `author`, `audience`) and raw `payload`;
  moves verification to a per-module axis; adds participants, lifecycle/state/attention,
  stale dependents, typed events, `AgentText`, summary/events/stream, `revision`.
