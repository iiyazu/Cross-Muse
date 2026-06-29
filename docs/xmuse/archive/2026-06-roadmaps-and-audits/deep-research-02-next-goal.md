# Deep Research 02 Next Goal

## Goal

Make the Cross-Muse mainline explicit and enforceable:

`GOD groupchat deliberation -> frozen blueprint -> feature/lane/laneDAG -> centralized execution/review -> GitHub merge gate -> REST-first MemoryOS`

The previous roadmap closed the first contract and hardening pass. This goal turns the second research report into a product-mainline consolidation pass: define the missing contracts, connect them to tests and gates, and remove ambiguity between legacy/demo paths and the intended laneDAG execution model.

## Authoritative Inputs

- Research report: `C:\tmp\deep-research-report_02.md`
- Existing roadmap: `docs/xmuse/archive/2026-06-roadmaps-and-audits/deep-research-conversion-roadmap.md`
- Existing task list: `docs/xmuse/archive/2026-06-roadmaps-and-audits/deep-research-execution-tasks.md`
- Current repo: `/home/iiyatu/projects/python/xmuse`
- GitHub repo: `https://github.com/iiyazu/Cross-Muse`
- Current closed baseline: issues `#1-#12`, latest pushed `main`

## Core Judgment From Report 02

Cross-Muse already has strong pieces: groupchat intake, GOD session machinery, feature/lane/review modules, review-plane lineage, quality gates, and initial MemoryOS integration. The missing step is not another concept layer. The missing step is making five contracts first-class and enforceable:

1. GOD groupchat speech-act contract.
2. Blueprint arbitration and freeze contract.
3. Feature/lane/laneDAG execution contract.
4. GitHub review and merge contract.
5. MemoryOS namespace, retention, and privacy contract.

## Hard Constraints

- Keep `xmuse/` as runtime namespace only. Do not add `xmuse/__init__.py`.
- Runtime code imports from `xmuse_core.*`; `xmuse_core` must not depend on runtime `xmuse.*`.
- Use `uv run` for tests and tools.
- Do not commit runtime state: databases, sqlite files, jsonl traces, `feature_lanes.json`, `xmuse/work/`, `xmuse/history/`, `xmuse/logs/`.
- MemoryOS remains REST-first. Do not expose memory write tools through MCP unless auth/RBAC is proven by tests.
- OpenCode remains bounded worker unless a separate explicit contract upgrades it.
- Treat GitHub as an execution/review control plane, not just an archive target.
- Keep changes issue-scoped, tested, linted, committed, pushed, and reflected in GitHub issues.

## Phase 1: Contract Inventory And Mainline Docs

Create a concise mainline contract document under `docs/xmuse/`, and update the current docs entry point so the intended product path is unambiguous.

Deliverables:

- `docs/xmuse/mainline-contracts.md`
- README/docs update pointing to this as the current end-to-end path.
- A mapping table from current modules to intended contracts:
  - `src/xmuse_core/chat/*`
  - `src/xmuse_core/structuring/*`
  - `src/xmuse_core/platform/*review*`
  - `src/xmuse_core/platform/*lane*`
  - `src/xmuse_core/integrations/memoryos_*`

Acceptance:

- Docs distinguish demo/legacy paths from the intended mainline.
- Docs state that blueprint freeze is the boundary between decentralized deliberation and centralized execution.
- Docs state which artifact is authority and which artifact is projection.

## Phase 2: GOD Speech-Act And Active Challenge Contract

Extend the existing deliberation protocol so GOD messages can express structured behavior rather than plain text only.

Minimum contract fields:

- `message_id`
- `conversation_id`
- `thread_id`
- `sender_god`
- `targets`
- `speech_act`
- `references`
- `causal_parent_id`
- `lane_scope`
- `confidence`
- `memory_refs`
- `requires_reply_by`

Required speech acts:

- `propose`
- `ask`
- `challenge`
- `object`
- `vote`
- `decide`
- `handoff`
- `evidence`
- `retract`

Acceptance:

- A proposal with unverified assumptions triggers a review challenge task.
- An executable-gap finding can be represented as `object` or `ask`.
- Unanswered required replies become blockers.
- Tests cover stable serialization, causal ordering, duplicate handling, blocker creation, and reply resolution.

## Phase 3: Blueprint Arbitration And Freeze Gate

Upgrade blueprint freeze from simple readiness to a documented arbitration rule.

Rules:

- Extract claims from groupchat into requirements, constraints, assumptions, risks, external dependencies, and open questions.
- Require one objection/confirmation round for critical assumptions.
- Convert unresolved objections into blueprint blockers.
- Freeze only when quorum passes and no veto blocker remains.
- Normal technical changes use `2/3` approval with no review/safety veto.
- Production, privacy, or policy-sensitive changes require review GOD plus human/operator approval.

Acceptance:

- A veto blocker prevents freeze.
- Removing or resolving the blocker permits freeze.
- Non-blocking objections are preserved as open questions or decision-log entries.
- Frozen blueprint remains immutable and source-traceable.

## Phase 4: Blueprint To LaneDAG Mainline

Make the post-freeze execution path explicit through a `BlueprintExecutionService` or equivalent existing-pattern integration.

Scope:

- Convert frozen blueprint to feature set.
- Convert features to lanes.
- Generate typed dependency edges:
  - `hard_dep`
  - `soft_dep`
  - `review_dep`
  - `artifact_dep`
- Preserve blueprint refs, feature refs, acceptance criteria, touched areas, gate profiles, and memory refs.

Acceptance:

- Invalid blueprint refs reject planning.
- Lanes without acceptance criteria reject planning.
- Cycles reject deterministically.
- If lane A fails, dependent lanes B/C cannot dispatch.
- If lane A is approved, ready dependents can dispatch.
- Patch-forward verdict creates an auditable patch lane and links it to the failed lane.

## Phase 5: GitHub Review And Merge Contract

Turn GitHub into a first-class review/merge control plane.

Deliverables:

- Pull request template containing:
  - `blueprint_id`
  - `feature_ids`
  - `lane_ids`
  - `depends_on_lanes`
  - `memory_impact`
  - `new_artifacts`
  - `provider_changes`
  - `gate_profile`
  - `review_evidence_bundle`
  - `rollback_plan`
  - `privacy_impact`
- `CODEOWNERS` proposal for chat, platform, memory, providers, and GitHub workflow areas.
- Required-check policy document for lane/feature PRs.

Acceptance:

- Fake GitHub ops can render the full PR body from lane metadata.
- Merge-ready status is blocked unless required checks and review evidence are present.
- CODEOWNERS and PR template are documented even if repository branch protection must be configured manually.

## Phase 6: MemoryOS Namespace, Retention, And Privacy Contract

Move MemoryOS from “adapter exists” to “safe shared memory backend contract exists”.

Scope:

- Namespace dimensions:
  - `repo`
  - `workspace`
  - `god_id`
  - `conversation_id`
  - `thread_id`
  - `blueprint_id`
  - `feature_id`
  - `lane_id`
- Memory layers:
  - `pinned_core`
  - `task_state`
  - `archival`
- Governance:
  - source refs
  - audit trace refs
  - redaction hook before LLM paging
  - delete cascade or tombstone contract
  - confidence decay and versioned recompression notes

Acceptance:

- Memory context includes namespace and source refs.
- REST write paths require actor identity and namespace.
- MCP memory writes deny unless host auth/RBAC is enabled.
- LLM paging path has a redaction hook test.
- Deleted/tombstoned source messages are not returned as active memory.

## Phase 7: CI And Gate Enforcement

Make the contracts hard to bypass.

Gate layers:

- `lint+format+typecheck`
- contract tests for protocol, blueprint, laneDAG, memory API
- integration smoke for fake groupchat, fake memory, patch-forward
- performance smoke consuming `PRODUCTION_SLO_TARGETS`

Acceptance:

- `uv run ruff check .` passes.
- Targeted pytest suites pass.
- Existing known broad-suite failures are documented separately and not hidden.
- Any new GitHub workflow is scoped and does not require unavailable secrets for basic PR validation.

## Suggested First Batch Issues

- `#13 M7: Mainline contract documentation and docs entrypoint`
- `#14 P0: GOD speech-act and active challenge contract`
- `#15 P0: Blueprint arbitration quorum/veto gate`
- `#16 P0: Blueprint-to-laneDAG execution service shell`
- `#17 P0: GitHub PR template, CODEOWNERS, and merge-ready contract`
- `#18 P0: MemoryOS namespace/privacy/retention contract`
- `#19 P0: Contract gate CI smoke`

## Initial Execution Order

1. Open issues `#13-#19` from the suggested batch.
2. Implement `#13` first: documentation and current-module mapping.
3. Implement `#14` and `#15` next: speech-act and freeze arbitration.
4. Implement `#16` only after the freeze contract is stable.
5. Implement `#17` and `#18` in parallel after lane metadata and memory namespace fields are stable.
6. Finish with `#19` to make the contracts hard gates.

## Goal Prompt

You are the Cross-Muse / xmuse main execution agent. Work in `/home/iiyatu/projects/python/xmuse`.

Use `C:\tmp\deep-research-report_02.md` as the authoritative next-stage research input. Convert it into the next implementation milestone: make the intended xmuse mainline explicit and enforceable:

`GOD groupchat deliberation -> frozen blueprint -> feature/lane/laneDAG -> centralized execution/review -> GitHub merge gate -> REST-first MemoryOS`.

Start by creating GitHub issues for the suggested `#13-#19` batch unless they already exist. Then execute in order:

1. Document the mainline contracts and map existing modules to them.
2. Add GOD speech-act and active challenge contracts.
3. Add blueprint arbitration quorum/veto freeze gate.
4. Add blueprint-to-laneDAG execution service shell.
5. Add GitHub PR template/CODEOWNERS/merge-ready contract.
6. Add MemoryOS namespace/privacy/retention contract.
7. Add CI/contract smoke gates.

Maintain existing constraints: no `xmuse/__init__.py`, runtime imports only from `xmuse_core.*`, no runtime state commits, MemoryOS REST-first, MCP memory writes denied unless auth/RBAC is proven, all commands via `uv run`.

For each issue: write focused tests first where practical, implement narrowly, run targeted pytest and `uv run ruff check .`, commit with the issue number, push to `origin/main`, update/close the GitHub issue with validation evidence, and document any known baseline failures separately.
