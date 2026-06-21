# Acceptance Spine

Updated: 2026-06-21

The acceptance spine is the smallest durable record that lets xmuse answer
where a human demand is in the product closure path.

It is chat/control-plane authority, not a dashboard or TUI projection.

## Current Implementation

The minimal slice is implemented in `src/xmuse_core/chat/acceptance_spine.py`.
`ChatStore._init_db` creates the `acceptance_spines` table in `chat.db`.

Implemented flow:

```text
human post_human_message intake
-> acceptance spine created with intake_message_id
-> source-linked proposal attaches proposal_id
-> proposal approval attaches resolution:<id> as verdict ref
-> dispatch queue enqueue attaches dispatch_item_id
-> dispatch mark_dispatched attaches provider/dispatch evidence refs
-> review_plane verdict attaches review_verdict_ref
-> final-action hold attaches final_action_ref
-> missing GitHub/server truth attaches github_gate_unverified manual gap
-> chat API can read spine status
```

Read endpoint:

```text
GET /api/chat/conversations/{conversation_id}/acceptance-spines
```

The endpoint is read-only and reports `source_authority = "chat_store"`.

## Authority

The authority is `chat.db` through chat/control-plane stores:

- `ChatStore` creates the intake spine for human `post_human_message`;
- `ChatStore.create_proposal` and `create_proposal_message_and_log` attach
  proposal refs when the proposal references `intake_message:<message_id>`;
- `ChatStore.approve_proposal` attaches the approved resolution ref;
- `PeerChatService` attaches review-trigger inbox refs when proposal review
  triggers are created;
- `ChatDispatchQueueStore` attaches dispatch and dispatch evidence refs.
- `ReviewPlaneController.ingest_verdict` attaches durable review verdict refs
  and final-action hold refs when the review plane emits a verdict;
- GitHub/server gate evidence is not faked. When final-action is held without
  server-side gate evidence, the spine records `github_gate_unverified` in
  `manual_gaps`.

Dashboard, TUI, timeline, provider stdout, fake/sentinel scripts, and copied
GitHub text are not acceptance authorities.

## Minimal Record

The current record tracks:

- `spine_id`;
- `conversation_id`;
- `intake_message_id`;
- `status`;
- `proposal_id`;
- `review_trigger_inbox_id`;
- `review_or_execute_verdict_ref`;
- `dispatch_item_id`;
- `execution_evidence_refs`;
- `review_verdict_ref`;
- `final_action_ref`;
- `github_gate_evidence_ref`;
- `manual_gaps`;
- `blocked_reason`.

The current implementation records a GitHub/server gate manual gap. It does not
claim server-side GitHub truth until a real producer writes
`github_gate_evidence_ref`.

## Status Semantics

Current implemented statuses:

- `intake`: a human demand has entered durable chat intake;
- `proposed`: a durable proposal is linked to the same demand;
- `review_pending`: a proposal review trigger inbox exists;
- `review_cleared`: the proposal has an approved resolution/verdict ref;
- `dispatched`: a dispatch queue item exists and may carry dispatch evidence;
- `reviewed`: an independent review-plane verdict ref is linked;
- `blocked`: a final-action hold or GitHub/server manual gap blocks terminal
  closure;
- `failed`: a dispatch queue failure is linked back to the demand.

Other lifecycle statuses are reserved for the broader closure path and must not
be claimed until their producer writes them.

## Remaining Boundary

The next implementation boundary is not another provider adapter. It is to
replace the manual GitHub/server gap with a real gate evidence producer, then
resolve the final-action hold into a terminal accepted/failed outcome:

```text
GitHub/server gate evidence
-> final-action resolution
-> accepted / blocked / failed terminal status
```

Use focused tests around the changed producer/consumer contract. Do not run the
full suite by default for this boundary.
