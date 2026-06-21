# xmuse Current Baseline - 2026-06-21

This file freezes the current xmuse state as the working baseline after the
long-running goal loop. It is intentionally short; detailed loop evidence
remains in the operation record, findings ledger, runtime artifacts, and
ignored `.goal-runs/` records.

## Baseline Position

xmuse is now treated as a durable orchestration layer for long-running agentic
software development:

- mature coding harnesses execute code, tests, commits, and PR workflows;
- xmuse owns GOD groupchat decisions, durable artifacts, lane/control plane,
  review/final-action gates, and recoverable long-running state;
- `feature_lanes.json` is runner-visible projection, not authority;
- durable authority lives in graph sets, review plane, stores, chat messages,
  GOD sessions, and final-action records.

## Current Runtime Picture

The current verified chain is partial but real:

1. GOD groupchat can persist participants, messages, callbacks, proposals, and
   writebacks.
2. Grok CLI is available as the current non-Codex peer target with model
   `grok-composer-2.5-fast`.
3. OpenCode remains unavailable and is not the current blocker.
4. A Grok-reviewed proposal has been accepted and projected into a lane graph.
5. The platform runner can pick up the projected lane and reach execution and
   review boundaries when the MCP server topology is correct.
6. The latest code-level boundary is review continuation terminality: a gated
   lane that starts a review attempt now has a durable review task lifecycle
   for `in_progress`, `verdict_emitted`, `failed_classified`, and
   `interrupted_retryable`; runner deadline shutdown cancels in-flight dispatch
   instead of waiting forever.
7. A bounded local proof now covers the minimal positive authority chain from a
   real `chat.db` human demand message, to a source-linked lane-graph proposal,
   to approval/projection, to `xmuse.platform_runner.run` lane consumption, to a
   durable merge verdict and pending final-action hold. The proof uses
   deterministic test doubles only at the external CLI execution/review
   boundary, so it is a local runtime/control-plane proof, not a natural
   peer-GOD or live provider proof.
8. The first durable AcceptanceSpine/GoalRun slice is implemented in `chat.db`:
   human `post_human_message` intake creates a spine; source-linked proposals,
   approved resolutions, dispatch queue entries, dispatch evidence refs, and a
   read-only Chat API endpoint now attach to the same demand record.
9. The AcceptanceSpine now also receives review-plane verdict refs,
   final-action hold refs, and an explicit `github_gate_unverified` manual gap
   when a verdict is held for final action without server-side GitHub truth.
10. Final-action resolution now drives AcceptanceSpine terminal status:
    approved without GitHub/server evidence stays `blocked`; approved with an
    explicit evidence ref becomes `accepted`; rejected/failed/cancelled becomes
    `failed`.

## GitHub Main Audit Absorption

A GPT-5.5 Pro audit against GitHub `origin/main` on 2026-06-21 identified a
more advanced mainline groupchat shape than this local working branch currently
contains. The audited mainline head is:

```text
88cb2d9 fix: guard final-action target imports
```

The current local branch `codex/groupchat-proposal-review-payload` is not a
safe substitute for that mainline state. At the time this baseline was updated,
`git rev-list --left-right --count HEAD...origin/main` reported:

```text
5	112
```

That means further groupchat development on this branch must first account for
mainline drift. In particular, the audit found mainline work around:

- dynamic groupchat members bound to durable GOD sessions;
- roster and peer-progress timeline events;
- proposal-review pending gates before dispatch approval;
- structured MCP peer tools counted as durable writeback evidence;
- writeback grace handling for provider result delays;
- collaboration/peer-reply drain callbacks back to the originator;
- semantic lane-graph proposal deduplication;
- deliberation freeze/decision guardrails.

These are accepted as the correct design direction for xmuse: groupchat is a
durable collaboration governance plane, not a chat transcript wrapper. However,
they must not be claimed as present on this local branch unless the code is
rebased/merged onto `origin/main` or the specific mainline changes are
re-applied and verified here.

The audit also sharpened the current risk ledger:

- plain human messages can still enter the timeline without enqueuing peer
  work unless they go through mention/collaboration dispatch paths;
- timeline consumers must not assume `items` is the complete event stream when
  progress/roster/runtime events are exposed separately;
- review pending gates prove state was handled, not review quality;
- durable writeback detection remains fragile when it depends on tool-stage
  names rather than the writeback mutation itself;
- semantic proposal deduplication needs an explicit revision/update route to
  avoid suppressing intentional revised proposals.

The deeper audit finding has now been partially absorbed locally: xmuse has a
minimal durable acceptance spine for intake -> proposal -> approval/verdict ->
dispatch evidence -> review-plane verdict -> final-action hold/manual GitHub
gap -> final-action terminal outcome. It does not yet prove a real
GitHub/server gate evidence producer.

## Baseline Evidence

Latest important runtime evidence before this baseline:

- PR #150 is merged on GitHub.
- The first Loop 2H runner attempt failed because the child worker required the
  xmuse MCP server and port 8100 was not serving it.
- The second Loop 2H runner attempt with the MCP server running recovered the
  lane from `gate_failed` to `gated`.
- A later Loop 2H-R2 attempt started `review_god`, but interruption left the
  durable review task pending and did not prove a verdict. The current
  code-level contract now prevents that class of unclassified hanging task,
  including runner deadline shutdown paths that previously could wait
  indefinitely on in-flight dispatch.
- A fresh local runtime proof at
  `.goal-runs/2026-06-21/review-terminality-runtime-proof-2/` ran
  `xmuse-platform-runner` against a gated lane requiring an unavailable
  OpenCode review peer. The lane reached `gate_failed` and the review task
  reached `failed_classified(required_review_peer_unavailable)` with
  attempt/runner/provider/evidence refs in `review_plane.json`.
- A fresh bounded local positive proof at
  `.goal-runs/2026-06-21/minimal-groupchat-fullchain-proof-runner/` writes
  `minimal-fullchain-proof.json` and `summary.json`. It proves:
  `human_demand` message in `chat.db` -> proposal references that message ->
  approved resolution -> projected lane in `feature_lanes.json` and lane graph
  store -> `xmuse.platform_runner.run` consumption -> durable
  `review_plane.json` task `verdict_emitted` with merge verdict -> pending
  `final_actions.json` hold under final-action safety mode.
- Focused acceptance-spine verification now proves:
  `post_human_message` -> `acceptance_spines.intake_message_id` ->
  source-linked proposal -> approved `resolution:<id>` verdict ref ->
  dispatch queue ref -> dispatch evidence refs -> read-only Chat API status.
- Focused acceptance-spine review/final-action verification now proves:
  review-plane `verdict:<id>` -> `final_actions.json#hold=<id>` ->
  `manual_gaps=["github_gate_unverified"]` -> blocked spine status.
- Focused final-action terminal verification now proves:
  approved without GitHub evidence remains blocked, approved with an explicit
  GitHub evidence ref becomes accepted, and rejected final action becomes
  failed.

## Forbidden Claims

This baseline does not prove:

- full autonomous overnight readiness;
- complete final-action closure for the current lane;
- a durable accepted review verdict for the historical pending review task;
- a passed/accepted review verdict from a real external Review GOD / live
  provider runtime proof;
- that Grok is a full platform orchestrator runtime;
- that OpenCode is available;
- that stdout or summaries alone are sufficient proof.
- natural peer-GOD groupchat; the bounded local proof uses deterministic
  external-boundary doubles and explicitly forbids that claim.

## Next Entry Point

The next loop should continue from the AcceptanceSpine boundary, not from more
provider expansion. Keep the GitHub mainline drift risk visible, but the next
small product cut is:

```text
independent review verdict
-> final-action hold/target ref
-> GitHub/server gate evidence ref or explicit manual gap
-> accepted / blocked / failed terminal spine status
```

The review verdict, final-action hold, manual GitHub gap, and final-action
resolution outcomes are now wired. The next boundary is narrower: add or reuse
a real GitHub/server gate evidence producer so `github_gate_evidence_ref` is
not caller-supplied by hand.

When using the existing Loop 2H runtime:

1. Start `xmuse-mcp-server` for the same runtime root when using the existing
   Loop 2H runtime.
2. Run the platform runner long enough to force a real external Review GOD or
   configured peer to emit a durable passed verdict, then link that verdict to
   the acceptance spine; otherwise explicitly record the next classified
   review/provider/transport blocker.
3. Link final-action hold/target evidence and GitHub/server gate evidence or a
   manual gap to the same spine.
4. Inspect `acceptance_spines`, `review_plane.json`, `feature_lanes.json`,
   state history, and spawn logs before claiming runtime closure.
5. Patch only if the runtime proof contradicts the durable terminality or
   minimal fullchain authority contract.

## Baseline Verification

Focused verification for this snapshot passed:

- `uv run pytest tests/xmuse/test_acceptance_spine.py tests/xmuse/test_review_plane_controller.py tests/xmuse/test_run_terminal_aggregation.py -q`
- `uv run ruff check src/xmuse_core/chat/acceptance_spine.py src/xmuse_core/platform/final_action_gate.py tests/xmuse/test_acceptance_spine.py`
- `uv run pytest tests/xmuse/test_acceptance_spine.py tests/xmuse/test_review_plane_controller.py -q`
- `uv run ruff check src/xmuse_core/chat/acceptance_spine.py src/xmuse_core/platform/review_plane.py tests/xmuse/test_acceptance_spine.py`
- `uv run pytest tests/xmuse/test_acceptance_spine.py tests/xmuse/test_chat_default_intake.py tests/xmuse/test_peer_chat_store.py tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_emit_proposal_supersedes_prior_open_collaboration_proposal -q`
- `uv run ruff check src/xmuse_core/chat/acceptance_spine.py src/xmuse_core/chat/store.py src/xmuse_core/chat/dispatch_queue.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/__init__.py xmuse/chat_api.py tests/xmuse/test_acceptance_spine.py`
- `git diff --check`
- `uv run ruff check .`
- `uv run pytest tests/xmuse/test_groupchat_minimal_fullchain_proof.py -q`
- `uv run pytest tests/xmuse/test_grok_persistent.py tests/xmuse/test_peer_provider_parity.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_platform_runner.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_review_plane_orchestrator_integration.py -q`

Before the mainline quarantine, full-suite verification was not green:

- `uv run pytest -q`
- result: `3720 passed, 45 failed, 4 skipped, 12 warnings`

Failure clusters observed in the full suite:

- chat API conversation scoping, compact cards, fork contracts, and proposal
  approval compatibility;
- participant/template legacy `claude` CLI-kind compatibility expectations;
- launcher command contract expectations;
- MCP permission metadata documentation coverage;
- feature-plan proposal and V14 closure approval compatibility;
- real Ray/Codex app-server restart/resume scenarios;
- gate profile and master-loop legacy contract tests;
- split export entrypoint expectations around `xmuse-tui-terminal-demo`;
- Ray optional dependency contract expectations.

This baseline therefore means "current honest working state", not "full suite
green release state".

Historical/compatibility failures are now isolated by
`docs/xmuse/mainline-test-quarantine.md`. The default `uv run pytest -q` is the
mainline signal; latest result after quarantine:

- `uv run pytest -q`
- result: `3727 passed, 49 skipped, 12 warnings`

The isolated compatibility set remains explicit and enumerable:

- `uv run pytest --collect-only -q --include-legacy-compat -m legacy_compat`
- result: `45/3769 tests collected (3724 deselected)`

`uv run pytest -q --include-legacy-compat` remains available for broad
archaeology and compatibility repair.
