# Vision Runtime Evidence Closure Plan

Updated: 2026-06-10

This document is the detailed task and behavior specification for the next xmuse
self-iteration goal after commit `2fdb299`.

The short goal prompt should reference this file instead of embedding all task
details.

## Context

Commit `2fdb299` completed a valuable contract-level replay sample:

```text
human request
-> deterministic GOD speech-act fixture
-> frozen blueprint
-> feature/lane/laneDAG
-> subagent runtime contract
-> evidence bundle
-> review pass/fail and patch-forward
-> fake GitHub merge readiness
-> fake REST-first MemoryOS writeback
-> replay documentation
```

That is a self-iteration contract replay closure. It is not a full xmuse vision
runtime closure. It does not prove:

- real multi-GOD natural deliberation;
- server-side GitHub branch protection or required checks;
- real GitHub merge state;
- live MemoryOS Lite evidence;
- real Ray/Codex/MCP runtime execution.

The next goal is to tighten the evidence chain so future runtime claims cannot
confuse fake/local contract proof with live/server-side proof.

## Objective

Turn the `2fdb299` contract replay into a stricter evidence pipeline that:

1. Is covered by default CI.
2. Does not write synthetic merge facts when only fake/local readiness was
   evaluated.
3. Captures GitHub server-side gate truth, or records exact remaining
   admin/permission gaps.
4. Separates deterministic replay contract proof from real multi-GOD
   deliberation evidence.
5. Adds an explicit opt-in live MemoryOS Lite evidence path.
6. Prepares a real Ray/Codex/MCP runtime soak tied to the same blueprint,
   feature, lane, and memory refs.
7. Keeps proof levels precise.

## Proof Levels

Use these labels consistently in code, tests, docs, issue comments, and memory
writebacks:

| Proof level | Meaning |
| --- | --- |
| `contract_proof` | Local deterministic contract behavior is validated. |
| `fake_runtime_proof` | Fake/local runtime path is exercised without live services. |
| `live_service_proof` | A live service such as MemoryOS Lite was called and returned evidence. |
| `server_side_enforcement_proof` | GitHub server-side settings/statuses prove enforcement. |
| `real_provider_proof` | Real provider/Ray/Codex/MCP execution produced evidence. |
| `manual_gap` | The requirement needs admin/operator evidence not available in default CI. |

No artifact may describe a weaker proof level as a stronger one.

## Required Issues

Create this batch unless equivalent issues already exist:

| Issue | Title | Purpose |
| --- | --- | --- |
| `#35` | Add self-iteration proof to default CI | Make the `2fdb299` closure proof part of the server-side default gate. |
| `#36` | Split merge readiness from real merge facts | Prevent fake/local readiness from writing `pr_merged` memory facts. |
| `#37` | GitHub server-side gate evidence closure | Verify or explicitly document branch protection, required checks, and CODEOWNER enforcement. |
| `#38` | Real multi-GOD deliberation replay export | Add a separate path for live/exported groupchat transcript evidence. |
| `#39` | Live MemoryOS Lite evidence artifact | Add opt-in live MemoryOS Lite ingest/context/trace proof. |
| `#40` | Real Ray/Codex/MCP runtime soak runbook | Define operator-run real runtime evidence capture. |
| `#41` | Proof-level docs and debt cleanup | Update docs/debt so proof claims remain precise. |

Each issue must include acceptance criteria, implementation evidence, validation
commands, and a completion comment before closing.

## Work Packages

### 1. Default CI Coverage For Self-Iteration Proof

Tasks:

- Update `.github/workflows/xmuse-ci.yml` so default CI runs the
  self-iteration proof.
- Include at minimum:
  - `src/xmuse_core/self_iteration/runtime_closure.py`
  - `src/xmuse_core/platform/execution/subagent_runtime.py`
  - `tests/xmuse/test_self_iteration_runtime_closure.py`
- Prefer adding these to `contract-smoke-gates` or an adjacent default gate.
- Avoid changing required check names unless server-side branch protection is
  updated and documented.
- Keep default CI no-secrets and no-live-service.

Acceptance:

- The workflow file contains the self-iteration source/test targets.
- Tests or docs prove the self-iteration proof is included in default CI.
- `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate` names remain aligned with docs.

### 2. Merge Readiness Versus Real Merge Facts

Tasks:

- Audit `MemoryOSWritebackKind`, `write_self_iteration_memory_evidence()`, and
  replay docs.
- Do not write `pr_merged` for fake/local merge readiness.
- Add or use a distinct event kind for fake/local outcomes, for example:
  - `merge_readiness_evaluated`
  - `gate_outcome_recorded`
  - `pr_draft_updated`
- Reserve `pr_merged` for real GitHub server-side merge evidence only.
- Update tests so fake/default self-iteration writeback cannot create a merged
  fact.

Acceptance:

- Fake/default tests prove no synthetic `pr_merged` event is written.
- Docs explain when `pr_merged` is allowed.
- MemoryOS writeback remains REST-first and preserves source refs.

### 3. GitHub Server-Side Gate Evidence

Tasks:

- Use the GitHub connector first for current repository evidence.
- Verify or document:
  - latest workflow run/status visibility for the target commit;
  - branch protection or ruleset enforcement for `main`;
  - whether required checks include `quality-gates`,
    `contract-smoke-gates`, and `real-runtime-integration-gate`;
  - whether Code Owners review is required server-side.
- If the connector cannot inspect a setting, record the exact missing permission
  or evidence gap.
- Do not claim branch protection, required checks, or CODEOWNER enforcement
  unless server-side evidence proves it.

Acceptance:

- A GitHub evidence artifact records observed evidence, source, timestamp, and
  limitations.
- Server-side gaps are recorded as `manual_gap`, not as proof.
- Required check names stay aligned with workflow job names.

### 4. Real Multi-GOD Deliberation Replay Export

Tasks:

- Keep the deterministic fixture as contract proof.
- Add a separate path for real/exported groupchat transcript evidence.
- The exported transcript must preserve:
  - speech acts;
  - causal refs;
  - source refs;
  - blockers;
  - objections/challenges;
  - freeze decision.
- Target speech acts:
  - `propose`
  - `ask`
  - `challenge`
  - `object`
  - `evidence`
  - `vote`
  - `decide`
  - `handoff`
- If real provider execution is not available in default CI, provide a
  no-secrets export contract and a separate live operator command.

Acceptance:

- Deterministic fixture is not described as natural deliberation proof.
- Real/exported transcript evidence has a distinct proof level.
- Freeze still fails when live/exported blockers remain unresolved.

### 5. Live MemoryOS Lite Evidence Artifact

Tasks:

- Keep default tests fake/no-live.
- Add explicit opt-in live evidence using MemoryOS Lite env vars.
- Capture at least:
  - session creation;
  - ingest of deliberation/execution events;
  - build-context after freeze;
  - session trace retrieval;
  - source refs;
  - token budget/context package metadata;
  - restart or recreate evidence if supported.
- Store safe docs/artifacts only.
- Do not commit databases, sqlite files, jsonl logs, runtime state, or secrets.

Acceptance:

- Live tests skip cleanly unless explicit env vars are set.
- Live evidence artifact marks itself as `live_service_proof`.
- Fake MemoryOS tests remain default CI proof and no live service is required.

### 6. Real Ray/Codex/MCP Runtime Soak Runbook

Tasks:

- Create or update an operator runbook for real runtime evidence capture.
- Include exact commands and expected evidence for:
  - app server / Codex or OpenCode provider;
  - chat API;
  - MCP server;
  - platform runner;
  - MemoryOS writeback;
  - restart/resume;
  - failure degradation.
- Bind the runbook to the same blueprint, feature, lane, and memory ref model.
- Do not fake real provider evidence.

Acceptance:

- Runbook clearly distinguishes contract smoke from real provider proof.
- Operator evidence requirements are executable and auditable.
- Remaining unavailable evidence is tracked as debt.

### 7. Documentation And Debt Cleanup

Tasks:

- Update:
  - `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md`
  - `docs/xmuse/broad-suite-baseline-debt.md`
  - `docs/xmuse/README.md`
- Add a new artifact if useful:
  - `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md`
- Record every remaining gap with:
  - owner file;
  - repro/evidence command;
  - current state;
  - proof level;
  - closure rule.

Acceptance:

- No fake demo is described as production autonomy.
- No local synthetic check is described as server-side GitHub proof.
- No deterministic fixture is described as natural multi-GOD deliberation proof.

## Behavior Rules For The Executing Agent

### Evidence Discipline

- Treat current worktree, GitHub state, command output, and live service output
  as authoritative.
- Do not rely on memory of earlier work when current evidence can be inspected.
- Do not claim GitHub branch protection, CI success, live MemoryOS proof, or
  real provider proof without direct evidence.
- If evidence cannot be retrieved, document the gap precisely.

### Scope Discipline

- Keep changes focused on evidence closure.
- Do not perform broad refactors unless required to satisfy acceptance.
- Do not turn fake/local paths into live-proof claims.
- Do not create a new authoritative state path that bypasses blueprint,
  laneDAG, review, GitHub, or MemoryOS contracts.

### Runtime State Discipline

Never commit:

- `*.db`
- `*.sqlite3`
- `*.jsonl`
- `feature_lanes.json`
- `xmuse/work/`
- `xmuse/history/`
- `xmuse/logs/`

`feature_lanes.json` remains a projection/queue, never authority.

### Boundary Discipline

- Do not create `xmuse/__init__.py`.
- `xmuse_core` must not import runtime `xmuse/`.
- `xmuse_core` must not import `memoryos_lite` directly.
- MemoryOS remains REST-first.
- MCP memory writes remain denied unless auth/RBAC is explicitly proven.

### Validation Discipline

Run the strongest relevant validation before committing:

```bash
uv run ruff check .
uv run mypy <changed typed core modules>
uv run pytest -q <focused changed contract tests>
uv run pytest -q tests/xmuse/test_package_boundaries.py
```

Also run the existing #13-#34 contract regression set, or a documented focused
equivalent if the full set is not practical in the current turn.

### GitHub Discipline

- Commit and push only relevant source/test/doc changes.
- Create or update issues #35-#41.
- Comment each issue with commit and command evidence.
- Close issues only when their acceptance criteria are actually satisfied.
- Leave issues open or explicitly blocked if server-side/admin evidence is
  unavailable.

## Completion Criteria

The goal is complete only when:

- self-iteration proof is included in default CI;
- fake/local writeback no longer records synthetic `pr_merged` facts;
- GitHub server-side evidence is proven or precisely recorded as a gap;
- deterministic replay and real/natural deliberation evidence are separated;
- live MemoryOS Lite opt-in evidence path exists and skips cleanly by default;
- real runtime soak evidence expectations are documented;
- docs/debt are updated;
- validation passes;
- changes are committed and pushed;
- issues #35-#41 are created/updated with evidence and closed only when complete.
