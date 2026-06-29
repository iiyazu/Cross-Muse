# Self-Iteration Runtime Closure Plan

Updated: 2026-06-10

This document is the detailed task and behavior specification for the next
xmuse self-iteration goal. The short prompt should reference this file instead
of embedding all task details.

## Objective

Make xmuse prove one minimal self-iteration loop:

```text
human request
-> GOD speech-act replay
-> frozen blueprint
-> feature/lane/laneDAG
-> runnable lane dispatch
-> subagent runtime contract
-> evidence bundle
-> review decision / patch-forward
-> GitHub gate evidence
-> MemoryOS writeback
-> replay documentation
```

The goal is not full production autonomy. The goal is a replayable, auditable
sample that shows the current mainline contracts can drive xmuse improving
itself without confusing fake evidence with live runtime proof.

## Required Issues

Create and execute this batch, unless equivalent open issues already exist:

| Issue | Title | Purpose |
| --- | --- | --- |
| `#28` | GitHub truth alignment evidence | Reconcile GitHub-visible CI/ruleset evidence with repository contracts. |
| `#29` | Self-iteration groupchat replay fixture | Produce deterministic human request -> GOD speech acts -> frozen blueprint. |
| `#30` | Blueprint to laneDAG self-iteration sample | Convert the frozen blueprint into feature/lane/laneDAG authority data. |
| `#31` | Subagent runtime contract and evidence bundle | Define/lock serializable lane execution contract and evidence output. |
| `#32` | Review plane patch-forward self-iteration gate | Prove review pass/fail and patch-forward lane behavior. |
| `#33` | MemoryOS self-iteration writeback evidence | Write blueprint, lane evidence, review, and gate outcome through REST-first memory. |
| `#34` | Self-iteration runtime closure documentation | Publish the replay artifact and proof-level boundaries. |

Each issue must have acceptance criteria, implementation evidence, validation
commands, and a completion comment before being closed.

## Work Packages

### 1. GitHub Truth Alignment

Tasks:

- Check whether the current `main` tip has a visible GitHub Actions run.
- Check that documented required checks match workflow job names:
  - `quality-gates`
  - `contract-smoke-gates`
  - `real-runtime-integration-gate`
- Check CODEOWNERS and PR template alignment with the merge gate contract.
- If GitHub Actions visibility cannot be proven through connector or web
  evidence, document the evidence gap and optionally create a no-behavior
  evidence commit to trigger CI.
- Do not claim branch protection is enforced unless GitHub server-side settings
  are actually verified.

Acceptance:

- A document section or evidence artifact records what GitHub proves, what local
  tests prove, and what remains an admin/settings gap.
- Required check names are still unique and aligned with workflow jobs.
- Default CI remains no-secrets.

### 2. Deterministic GOD Groupchat Replay

Tasks:

- Add a deterministic fixture for one self-iteration request.
- The fixture must include these speech acts:
  - `propose`
  - `ask`
  - `challenge`
  - `object`
  - `vote`
  - `decide`
  - `evidence`
  - `handoff`
- Track unresolved challenges, objections, assumptions, open questions, and
  source refs before freeze.
- Produce a frozen `MissionBlueprintV1` or the current equivalent blueprint
  object.

Acceptance:

- Focused tests can replay the conversation and derive a frozen blueprint.
- Freeze is blocked if required objections/challenges are unresolved.
- The fixture becomes an input for the laneDAG sample, not a standalone story.

### 3. Blueprint To Feature/Lane/LaneDAG

Tasks:

- Use the frozen blueprint to generate a small self-iteration feature set.
- Generate lane specs with acceptance criteria.
- Generate typed edges:
  - `hard_dep`
  - `soft_dep`
  - `review_dep`
  - `artifact_dep`
- Prove graph validation rejects cycles, missing acceptance, and invalid refs.
- Prove ready lane dispatch comes from the central scheduler/graph contract.

Acceptance:

- Feature/lane/laneDAG data is deterministic from the blueprint fixture.
- `feature_lanes.json` is not treated as authority.
- Dashboard/TUI/MCP do not bypass contracts to write internal state.

### 4. Subagent Runtime Contract

Tasks:

- Define or strengthen a serializable lane execution contract with at least:
  - `blueprint_id`
  - `feature_id`
  - `lane_id`
  - `depends_on`
  - `worktree_path` or path scope
  - `allowed_files`
  - `allowed_tools`
  - `acceptance_criteria`
  - `required_checks`
  - `source_refs`
  - `memory_context_ref`
  - `rollback_plan`
  - `review_profile`
- Use fake/local subagent execution in default CI.
- Mark fake/local execution as contract proof, not live provider proof.

Acceptance:

- Tests prove the runtime contract serializes/deserializes.
- A lane execution result produces a structured evidence bundle.
- No default test requires provider secrets, Ray, Codex app-server, or live
  MemoryOS Lite.

### 5. Review Plane And Patch-Forward

Tasks:

- Route completed lane output into the review plane.
- On review pass, produce merge-ready evidence.
- On review fail, produce a patch-forward lane instead of overwriting the
  original lane state.
- Evidence bundle must include:
  - changed files
  - commands run
  - test results
  - source refs
  - memory refs
  - risk notes
  - rollback notes

Acceptance:

- Tests cover review pass and review fail.
- Patch-forward lane is linked to the failed lane.
- Fake GitHub PR body or record can render blueprint/lane/gate/privacy/rollback
  metadata.

### 6. MemoryOS Writeback

Tasks:

- Use REST-first MemoryOS integration.
- Write back at least:
  - frozen blueprint summary
  - lane execution evidence
  - review decision
  - final gate outcome
- Default tests use fake HTTP or fake MemoryOS client.
- Live MemoryOS Lite remains explicit opt-in only.

Acceptance:

- No `memoryos_lite` import in `xmuse_core`.
- Writeback payloads preserve actor identity, namespace, memory layer, and source
  refs.
- Documentation marks fake writeback as contract proof and live writeback as
  runtime proof.

### 7. Replay Artifact

Tasks:

- Add `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md`.
- Include:
  - human request
  - GOD speech-act transcript refs
  - frozen blueprint
  - feature/lane/laneDAG
  - subagent runtime contract
  - review evidence
  - GitHub/CI evidence
  - MemoryOS writeback evidence
  - proof-level table

Acceptance:

- A reader can replay the minimum self-iteration path from documented refs.
- The artifact clearly separates:
  - contract proof
  - fake runtime proof
  - live runtime proof
  - manual / future proof

### 8. Debt And Evidence Registry

Tasks:

- Update `docs/xmuse/broad-suite-baseline-debt.md`.
- Track these gaps if still true:
  - GitHub Actions visibility / branch protection evidence
  - real Ray/Codex/MCP runtime gate
  - Chat API / MCP auth layer
  - multi-CLI GOD natural groupchat
  - live MemoryOS Lite release evidence

Acceptance:

- No fake demo is described as full production autonomy.
- Every remaining gap has owner file, repro/evidence command, current state, and
  closure rule.

## Behavior Rules For The Executing Agent

### Evidence Discipline

- Treat current worktree, GitHub state, and command output as authoritative.
- Do not rely on memory of prior work when current files can be inspected.
- Do not claim GitHub branch protection, CI success, or live runtime proof unless
  the corresponding current evidence is inspected.
- If connector/web evidence is unavailable, document it as an evidence gap.

### Proof-Level Vocabulary

Use these terms consistently:

- `contract proof`: schema, static docs, fake client, fake GitHub, focused tests.
- `fake runtime proof`: runnable local flow using fake provider/service.
- `live runtime proof`: real service/provider/GitHub server behavior.
- `manual gap`: behavior that still needs operator/admin confirmation.

Never use a lower proof level to claim a higher proof level.

### Implementation Rules

- Prefer existing xmuse patterns and modules over new abstractions.
- Keep changes scoped to the self-iteration path.
- Add tests before or alongside implementation.
- Use structured models/parsers where available.
- Do not move historical docs unless required for the task.
- Do not change broad unrelated formatting.

### Package And Runtime Boundaries

- Do not create `xmuse/__init__.py`.
- `xmuse/` runtime imports from `xmuse_core.*`.
- `xmuse_core` must not import runtime `xmuse/` or `memoryos_lite`.
- Runtime state must not be committed:
  - `*.db`
  - `*.sqlite3`
  - `*.jsonl`
  - `feature_lanes.json`
  - `xmuse/work/`
  - `xmuse/history/`
  - `xmuse/logs/`
- `feature_lanes.json` remains projection/queue, not authority.
- MemoryOS remains REST-first.
- MCP memory writes remain denied unless auth/RBAC is proven by tests.

### Command Rules

- Always use `uv run`.
- Required local validation at minimum:
  - `uv run ruff check .`
  - focused pytest for changed contracts
  - `uv run mypy ...` for changed typed core modules
  - package boundary tests when touching imports or integrations

### GitHub Rules

- Prefer issue -> commit -> validation evidence -> close loop.
- Do not close an issue until acceptance criteria and validation evidence are
  posted.
- Do not claim server-side branch protection is enforced without GitHub settings
  evidence.
- Default CI must remain no-secrets and no-live-service.

## Completion Criteria

The long goal is complete only when current evidence proves:

- the self-iteration replay fixture exists and freezes a blueprint;
- the blueprint deterministically drives feature/lane/laneDAG data;
- a runnable lane dispatch contract exists and is tested;
- subagent execution produces an evidence bundle;
- review pass/fail and patch-forward are tested;
- MemoryOS writeback is tested through REST-first fake contract;
- replay documentation exists and names proof levels;
- broad-suite/runtime debt is updated;
- all required validation commands pass;
- no package/runtime boundary is violated;
- related GitHub issues are closed with evidence.
