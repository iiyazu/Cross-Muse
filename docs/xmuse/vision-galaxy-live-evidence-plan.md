# Vision Galaxy Live Evidence Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the next xmuse vision closure wave: a live/operator-supplied evidence pack that connects natural multi-GOD deliberation, blueprint freeze, laneDAG execution, MemoryOS trace, provider runtime evidence, and GitHub truth without overstating proof.

**Architecture:** Keep durable authority in existing contracts and stores: deliberation envelopes, frozen blueprint revisions, graph sets, review evidence, MemoryOS REST traces, provider runtime manifests, and GitHub server truth captures. TUI/dashboard/cards remain projections that display proof levels and manual gaps; they must not become state authority.

**Tech Stack:** Python, Textual, FastAPI, xmuse_core contracts, MemoryOS Lite REST API, GitHub CLI/API evidence capture, Codex/OpenCode provider adapters, pytest, ruff, uv.

---

Updated: 2026-06-11

Source report:

```text
C:\tmp\deep-research-report_07.md
/mnt/c/tmp/deep-research-report_07.md
```

Short `/goal` prompt:

```text
docs/xmuse/vision-galaxy-live-evidence-goal-prompt.md
```

## Context

`deep-research-report_07` concludes that xmuse now has a strong contract shell,
GitHub merge/review governance, MemoryOS Lite compatibility, and a TUI front
door wave in progress. The remaining gap is not another static proof document.
The next product proof must show a connected path:

```text
natural multi-GOD deliberation
-> frozen blueprint
-> feature/lane/laneDAG execution
-> review and patch-forward evidence
-> MemoryOS context/trace continuity
-> provider runtime/session evidence
-> GitHub checks/review/merge truth
```

This wave is evidence-first. It should make existing surfaces more truthful and
more connected, but it must not claim live, real-provider, or server-side proof
unless the artifact is actually captured.

## Vision

The north-star is a "GOD galaxy": Codex, OpenCode, and future coding CLI
instances can eventually act as peer developers in one xmuse-governed system.
This wave does not grant full peer-GOD production status by assertion. It builds
the evidence rails required before that promotion is credible.

Current provider boundary:

- Codex remains the primary production groupchat GOD provider path.
- OpenCode remains bounded/secondary unless a task explicitly proves persistent
  session, writeback, review, and MemoryOS semantics.
- If OpenCode is invoked, use the confirmed command format:

```bash
opencode --model opencode-go/deepseek-v4-flash:max run ...
```

Do not use the obsolete `deepseek-v4-flash-max` or
`opencode-go/deepseek-v4-flash-max` spellings.

## Proof Vocabulary

Use these labels consistently in code, UI, docs, and artifacts:

| Label | Meaning |
| --- | --- |
| `contract_proof` | Deterministic local contract or fixture proves behavior. |
| `fake_runtime_proof` | Fake/local runtime path ran without live services. |
| `live_service_proof` | A live service returned evidence. |
| `server_side_enforcement_proof` | GitHub server settings/statuses prove enforcement. |
| `server_side_merge_proof` | GitHub merge event, merge commit, and merged timestamp prove merge fact. |
| `real_provider_proof` | Real Codex/OpenCode/Ray/MCP/provider runtime produced evidence. |
| `manual_gap` | Required operator/admin/live evidence is missing or unavailable. |

Readiness is not completion. `merge_ready`, `review_ready`, and
`ready_to_freeze` must never be rendered as `pr_merged`, `review_complete`, or
`frozen` unless the corresponding fact evidence exists.

## Non-Goals

- Do not rebuild a browser frontend.
- Do not clean unrelated history or large blobs.
- Do not commit runtime state, DBs, sqlite files, jsonl logs,
  `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, or `xmuse/logs/`.
- Do not make `feature_lanes.json`, TUI cards, dashboard rows, or Ray actors
  durable authority.
- Do not import runtime `xmuse/` or `memoryos_lite` from `xmuse_core`.
- Do not require secrets, live services, GitHub admin mutation, or real
  providers in default CI.
- Do not promote OpenCode to production peer-GOD status without persistent
  session, writeback, MemoryOS trace, review evidence, and GitHub truth
  artifacts.

## Authority Boundaries

- Deliberation authority: structured chat envelopes and durable message stores.
- Blueprint authority: frozen blueprint revisions and source refs.
- Execution authority: graph sets, lane graph stores, review evidence, and
  platform run manifests.
- Memory authority: MemoryOS REST evidence and xmuse namespace/session binding.
- GitHub authority: server-side API/CLI captures, status checks, review events,
  and merge events.
- UI authority: none. TUI/dashboard render projections and proof levels only.

## Likely File Map

Read before implementation:

- `docs/xmuse/README.md`
- `docs/xmuse/mainline-contracts.md`
- `docs/xmuse/vision-closure-wave-deliberation-tui-walkthrough.md`
- `docs/xmuse/vision-runtime-evidence-closure.md`
- `docs/xmuse/memoryos-lite-runtime-compatibility.md`
- `docs/xmuse/github-server-side-gate.md`
- `docs/xmuse/opencode-in-long-runtime-evidence-closure.md`
- `AGENTS.md`

Likely implementation surfaces:

- `src/xmuse_core/chat/` - deliberation envelopes and transcript export.
- `src/xmuse_core/structuring/` - blueprint, feature, lane, laneDAG contracts.
- `src/xmuse_core/platform/` - orchestrator, review, dashboard/read models,
  TUI vision read model, provider runtime evidence.
- `src/xmuse_core/providers/` - provider policy, registry, Codex/OpenCode
  runtime boundaries.
- `xmuse/tui/` - display proof levels and drill-down links.
- `.github/` - PR template, CODEOWNERS, workflow/status contract checks only
  when GitHub truth surfaces change.
- `docs/xmuse/` - evidence pack, walkthrough, manual gaps, and goal docs.

Likely focused tests:

- `tests/xmuse/test_deliberation_protocol_v2.py`
- `tests/xmuse/test_tui_vision_read_model.py`
- `tests/xmuse/test_tui_widgets.py`
- `tests/xmuse/test_tui_navigation.py`
- `tests/xmuse/test_blueprint_lane_dag_service.py`
- `tests/xmuse/test_memoryos_lite_interop.py`
- `tests/xmuse/test_github_server_truth_capture.py`
- `tests/xmuse/test_package_boundaries.py`
- `tests/xmuse/test_mainline_contract_docs.py`

## Work Packages

### S0 - Truth Map And Baseline

Goal: establish the current proof state without changing behavior.

- [ ] Read the source report, this plan, and the authoritative docs listed in
  the file map.
- [ ] Run `git status --short` and identify unrelated user work. Preserve it.
- [ ] Inspect current TUI vision read model, provider board, MemoryOS adapter,
  GitHub truth capture, and provider registry.
- [ ] Record the current state as `proven`, `contract_only`, or `manual_gap` in
  the eventual evidence artifact.
- [ ] Confirm whether PR #42 merge evidence and issue #37 server-side truth gap
  are still the current GitHub facts before referencing them.

Acceptance:

- A baseline note exists in the evidence artifact.
- No runtime state is committed.
- Existing dirty work is not reverted.

### S1 - Natural Deliberation Export

Goal: export one natural or operator-supplied multi-GOD deliberation transcript
as a replayable artifact.

- [ ] Add or extend tests proving exported messages preserve `god_id`,
  `provider_id`, speech act, target refs, source refs, blocker state,
  decision scope, and proof level.
- [ ] Export transcript data from existing durable message/envelope stores
  rather than scraping TUI render text.
- [ ] Include unresolved questions, blocking objections, votes, decisions,
  evidence refs, and retractions when present.
- [ ] If the transcript is fixture-only, label it `contract_proof`.
- [ ] If the transcript comes from a real run, include run id, provider ids,
  timestamps, source refs, and runtime command/session evidence.

Acceptance:

- The transcript artifact can be replayed or inspected without live services.
- The artifact distinguishes natural runtime evidence from deterministic
  contract fixtures.
- TUI panels can link to transcript refs without becoming transcript authority.

### S2 - Blueprint Freeze To LaneDAG Evidence

Goal: connect a frozen blueprint to feature/lane/laneDAG evidence and blockers.

- [ ] Add focused tests for source refs from deliberation decisions into
  blueprint freeze metadata.
- [ ] Verify lane graph generation preserves blueprint refs, feature refs,
  dependencies, gate predecessors, touched areas, and acceptance criteria.
- [ ] Record why each lane is ready, blocked, under review, reworked, or
  patch-forwarded.
- [ ] Surface review decisions and patch-forward lineage in the TUI projection
  as read-only facts.

Acceptance:

- A reader can trace a lane back to the frozen blueprint and source
  deliberation.
- Readiness, review, rework, and patch-forward are distinct states.
- LaneDAG display never treats `feature_lanes.json` as authority.

### S3 - Provider Runtime Evidence

Goal: capture provider/session evidence sufficient to reason about real or
bounded provider work.

- [ ] Extend provider runtime manifests to include provider id, boundary role,
  model, transport, command, session id, heartbeat, waiting reason, and proof
  level when available.
- [ ] Keep Codex as production primary unless a separate proof promotes another
  provider.
- [ ] When using OpenCode, invoke exactly:

```bash
opencode --model opencode-go/deepseek-v4-flash:max run ...
```

- [ ] Record OpenCode output as bounded worker evidence unless persistent
  peer-GOD semantics are proven.
- [ ] Do not store provider secrets, tokens, or full private prompts in
  committed artifacts.

Acceptance:

- Provider Board can explain who acted, under which boundary, and with what
  proof level.
- OpenCode evidence is useful without being mislabeled as production peer-GOD
  authority.
- Failed provider invocations are captured with failure class and next action.

### S4 - MemoryOS Trace Continuity

Goal: prove or explicitly gap the memory path from deliberation/execution into
MemoryOS Lite.

- [ ] Use MemoryOS Lite only through REST-facing compatibility surfaces.
- [ ] Capture or fixture namespace/session binding, ingest refs, context build,
  pinned core, retrieved pages, dropped pages, and trace refs.
- [ ] Add tests that parse trace artifacts without requiring a live MemoryOS
  service.
- [ ] For opt-in live runs, store redacted evidence and label it
  `live_service_proof`.
- [ ] For local deterministic tests, label evidence `contract_proof` or
  `fake_runtime_proof`.

Acceptance:

- The evidence pack shows whether memory context came from a real service,
  fixture, or manual gap.
- `xmuse_core` still does not import `memoryos_lite`.
- Memory refs keep `memory://conversation/<id>/...` or `memory://global/...`
  format, with feature-scoped refs carrying `feature_scope_id`.

### S5 - GitHub Truth Refresh

Goal: refresh GitHub evidence without turning local readiness into server fact.

- [ ] Capture PR checks, review truth, branch protection/required checks
  visibility, CODEOWNERS relevance, and merge event data only through GitHub
  server/API/CLI evidence.
- [ ] Keep issue #37 or its successor as the tracked gap until server-side
  enforcement is proven.
- [ ] Emit `server_side_merge_proof` only when the evidence includes merged
  flag, merge commit SHA, merged timestamp, and merge event id or equivalent
  server-side event.
- [ ] Emit `server_side_enforcement_proof` only when branch protection,
  required checks, and review/CODEOWNER enforcement are actually visible.
- [ ] Add regression tests for missing/partial GitHub fields.

Acceptance:

- TUI and docs separate `merge_ready` from `pr_merged`.
- Server-side enforcement gaps remain explicit.
- GitHub evidence can be audited from committed redacted artifacts.

### S6 - Evidence Pack And Walkthrough

Goal: produce a single cross-layer artifact for the wave.

- [ ] Create `docs/xmuse/vision-galaxy-live-evidence-pack.md`.
- [ ] Include baseline truth map, transcript refs, blueprint refs, lane refs,
  review refs, provider runtime refs, MemoryOS refs, GitHub refs, validation
  results, and manual gaps.
- [ ] Link the evidence pack from `docs/xmuse/README.md`.
- [ ] Run focused tests for every touched surface.
- [ ] Run `uv run ruff check .`.
- [ ] Run `git diff --check`.
- [ ] Request a fresh review before finalizing.

Acceptance:

- The final report lists what is proven, what is contract-only, and what remains
  manual gap.
- No evidence label is stronger than the underlying artifact.
- The next iteration can start from the evidence pack without reconstructing
  context from chat history.

## Behavior Rules

1. Use `uv run` for pytest, ruff, scripts, and Python entrypoints.
2. Preserve unrelated worktree changes. Do not use `git reset --hard` or
   destructive checkout commands.
3. Work as vertical slices: read model or exporter, TUI/display when relevant,
   tests, docs, then review.
4. Keep proof language strict. Never call a fixture live, never call readiness a
   fact, and never call local configuration server-side enforcement.
5. Keep default validation no-secrets and no-live-service. Live/provider/GitHub
   operator runs are opt-in and must be labeled.
6. Treat OpenCode as bounded unless this wave explicitly proves peer-GOD
   promotion criteria.
7. Keep MemoryOS REST-first and namespace-disciplined.
8. Keep UI read-only with respect to authority stores except through existing
   approved commands/contracts.
9. Commit in coherent slices if the execution goal asks for commits; otherwise
   leave a clean, auditable diff.
10. Before declaring completion, run focused validation, ruff, `git diff
    --check`, and a fresh review.

## Completion Criteria

This wave is complete only when all of these are true:

- A cross-layer evidence pack exists under `docs/xmuse/`.
- Natural/fixture deliberation evidence is exported and labeled correctly.
- Blueprint freeze, laneDAG, review, and patch-forward refs are traceable.
- Provider runtime evidence distinguishes Codex production boundary from
  bounded OpenCode work.
- MemoryOS evidence is either captured through REST-compatible artifacts or
  marked `manual_gap`.
- GitHub server facts are captured or explicitly marked `manual_gap`.
- Focused tests and ruff pass with `uv run`.
- Package boundary tests still pass.
- A fresh review has no blocking findings, or findings are documented with
  remediation status.
