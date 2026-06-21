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

## Forbidden Claims

This baseline does not prove:

- full autonomous overnight readiness;
- complete final-action closure for the current lane;
- a durable accepted review verdict for the historical pending review task;
- a passed/accepted review verdict from the fresh runtime proof;
- that Grok is a full platform orchestrator runtime;
- that OpenCode is available;
- that stdout or summaries alone are sufficient proof.

## Next Entry Point

Resume from the review-continuation boundary as a positive verdict proof pass:

1. Start `xmuse-mcp-server` for the same runtime root when using the existing
   Loop 2H runtime.
2. Run the platform runner long enough to force a review attempt to emit a
   durable passed verdict, or explicitly record the next classified
   review/provider/transport blocker.
3. Inspect `review_plane.json`, `feature_lanes.json`, state history, and spawn
   logs before claiming runtime closure.
4. Patch only if the runtime proof contradicts the durable terminality
   contract.

## Baseline Verification

Focused verification for this snapshot passed:

- `git diff --check`
- `uv run ruff check .`
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
- result: `3726 passed, 49 skipped, 12 warnings`

The isolated compatibility set remains explicit and enumerable:

- `uv run pytest --collect-only -q --include-legacy-compat -m legacy_compat`
- result: `45/3769 tests collected (3724 deselected)`

`uv run pytest -q --include-legacy-compat` remains available for broad
archaeology and compatibility repair.
