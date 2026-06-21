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
-> GitHub gate evidence producer captures server-side truth or a durable gap
-> final-action resolution updates accepted / blocked / failed terminal status
-> chat API can read spine status
```

Read endpoint:

```text
GET /api/chat/conversations/{conversation_id}/acceptance-spines
```

The endpoint is read-only and reports `source_authority = "chat_store"`.

Short-run CLI entrypoint:

```bash
uv run xmuse-platform-runner \
  --goal "<human demand>" \
  --acceptance-gate \
  --github-pr <number>
```

This entrypoint does not start the long platform loop. It writes a durable human
intake spine, proposal, dispatch evidence, review verdict, final-action hold,
and GitHub gate evidence record, then prints a compact terminal summary from
those stores. The printed JSON is not authority. The durable refs in `chat.db`,
`final_actions.json`, `review_plane.json`, and `github_gate_evidence.json` are
authority.

By default the command records a GitHub gate `manual_gap` and remains blocked.
Live GitHub capture is opt-in:

```bash
uv run xmuse-platform-runner \
  --goal "<human demand>" \
  --acceptance-gate \
  --github-pr <number> \
  --github-live-capture \
  --internal-review-artifact <path> \
  --internal-reviewer <id> \
  --internal-reviewed-head-sha <sha>
```

The live mode uses read-only `gh api` calls through
`GitHubCliServerSideTruthClient`. It can accept only when the producer writes a
durable `server_side_merge_proof` record for the same final action.

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
- `FinalActionGateStore.resolve` updates the spine terminal outcome. Approved
  final action without a producer-owned GitHub/server evidence ref remains
  blocked. Arbitrary or unverifiable GitHub refs are downgraded to gap refs,
  not accepted evidence. Rejected, failed, or cancelled final action becomes
  failed.
- `GitHubGateEvidenceStore` captures read-only GitHub/server truth evidence in
  `github_gate_evidence.json`. `FinalActionGateStore.resolve_with_github_gate_evidence`
  passes a `github_gate_evidence_ref` to the spine only when the captured record
  is a complete `server_side_merge_proof`; incomplete evidence is persisted as a
  gap ref on the final action and leaves the spine blocked.
- `AcceptanceSpineStore.resolve_final_action` also verifies the evidence ref at
  the authority layer: the ref must point at a durable
  `github_gate_evidence.json#evidence=<id>` record for the same final action,
  with `can_accept = true` and `proof_level = server_side_merge_proof`.

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

The current implementation records a GitHub/server gate manual gap and can now
produce a durable GitHub gate evidence ref from an injected read-only
server-truth collector. Manual gaps are persisted in `github_gate_evidence.json`
but are not accepted evidence refs.

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
- `accepted`: final action is approved with a producer-owned, authority-verified
  GitHub/server gate evidence ref;
- `failed`: a dispatch queue failure is linked back to the demand.

Terminal final-action rules:

- `approved` / `accepted` / `resolved` without `github_gate_evidence_ref`, or
  with only a GitHub gate gap ref, keeps `status = blocked` and
  `manual_gaps = ["github_gate_unverified"]`;
- `approved` / `accepted` / `resolved` with a valid
  `github_gate_evidence_ref` sets `status = accepted` and clears the GitHub
  manual gap only when the evidence ref resolves to a durable accepted producer
  record for the same final action;
- `rejected` / `failed` / `cancelled` / `canceled` sets `status = failed`.

Other lifecycle statuses are reserved for the broader closure path and must not
be claimed until their producer writes them.

## Current Boundary

The local producer/consumer contract is implemented:

```text
GitHub/server gate evidence
-> github_gate_evidence.json
-> github_gate_evidence_ref
-> accepted terminal status
```

The remaining runtime boundary is to invoke the producer from the real long-run
GitHub/final-action path with authenticated read-only server access. Until that
path captures a complete `server_side_merge_proof`, xmuse must keep the spine
blocked with `github_gate_unverified`.

The minimal `--goal --acceptance-gate` runner now invokes that producer for a
short real run. Its first smoke is recorded in
`docs/xmuse/acceptance-gated-runner-evidence-2026-06-21.md` and correctly ends
as `blocked/github_gate_unverified` because it has no `server_side_merge_proof`.
The first opt-in live GitHub capture smoke is recorded in
`docs/xmuse/acceptance-gated-live-capture-evidence-2026-06-21.md` and ends as
`accepted` because the producer captured a complete `server_side_merge_proof`.
This supports the current `production-closure short path accepted` claim. It
does not prove full release readiness, a multi-hour real-provider soak, or
long-running GOD groupchat stability across real provider/Ray/Codex sessions.
