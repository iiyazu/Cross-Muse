# OpenCode-In Long Runtime Evidence Closure Plan

This document is the detailed task and behavior contract for the next
OpenCode-in long goal. The short goal prompt should reference this file instead
of embedding all task detail directly.

Source blueprint:

```text
/mnt/c/tmp/deep-research-long-blueprint.md
```

## Objective

Run one evidence-closure iteration that moves xmuse from strong contract/fake
proof toward trustworthy long-runtime proof.

This iteration must not broaden the product surface. It must close proof
semantics first, make runtime evidence visible, then cautiously expand
OpenCode-in participation under bounded rules.

The target chain remains:

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS evidence
```

## Execution Model

OpenCode-in is a bounded implementation executor inside an outer Codex-controlled
goal. Codex remains responsible for orchestration, review, and final judgment.

Use OpenCode-in for:

- scoped implementation inside a stage;
- focused test creation and repair;
- bounded docs updates tied to changed behavior;
- local evidence gathering that does not mutate external systems.

Do not use OpenCode-in for:

- final merge/release judgment;
- unbounded architecture expansion;
- branch protection or GitHub settings mutation;
- direct durable xmuse state writes;
- live-service proof claims without explicit opt-in evidence.

## Autonomy Granted

The goal has bounded autonomy for this round.

It may:

- split a stage into smaller local work units when that improves verification;
- create stage manifests under `.goal-runs/` or another ignored run directory;
- choose focused tests for changed modules;
- add tests before implementation;
- update docs when code behavior or proof semantics change;
- create local fake collectors/adapters when live credentials are absent;
- mark a stage blocked with a precise owner and next action when external proof is
  unavailable;
- defer a P1/P2 task if completing it would require unsafe external mutation or a
  broad provider rewrite.

It must not:

- skip `scripts/goal_stage_runner.py`;
- treat `--dry-run` as pass evidence;
- claim live/server-side proof from local files;
- emit or preserve `pr_merged` from fake/local/contract paths;
- convert OpenCode from secondary/bounded to first-class GOD authority without
  tests and explicit documentation;
- create `xmuse/__init__.py`;
- commit runtime state or generated local run artifacts.

## Mandatory Stage Harness

Every phase must execute through:

```bash
uv run python scripts/goal_stage_runner.py \
  --stage-manifest /abs/path/to/stage-manifest.json \
  --engine opencode \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output .goal-runs/<stage_id>/result.json
```

Gate rules:

- only `result.json.status == "ok"` allows the next stage;
- `retry` reruns the same stage with the same manifest within `max_retries`;
- `blocked` stops the long goal and reports blocker, owner, and next action;
- `--dry-run` may preview prompt/command only and is never pass evidence;
- required artifacts are `result.json`, `result.json.prompt.txt`,
  `result.json.manifest.jsonl`, and
  `result.json.evidence/engine_output.txt`.

Minimal stage manifest:

```json
{
  "stage_id": "S1",
  "objective": "Fix merge readiness versus merge fact semantics.",
  "scope": ["src/xmuse_core/...", "tests/xmuse/...", "docs/xmuse/..."],
  "acceptance_contracts": [
    "contract/fake/local paths never emit pr_merged",
    "server-side merge proof remains separate from local readiness"
  ],
  "owner": "opencode-in",
  "max_retries": 1,
  "risk": "high",
  "engine": "opencode"
}
```

## Priority Order

Do the phases in order unless a stage is blocked by an external dependency. If a
stage is blocked, record the blocker and continue only to stages that are
independent of that blocker.

P0 must land before any P1 provider expansion.

## S0 - Baseline Evidence Map

Goal:
produce a short current-state map before changing behavior.

Inspect:

- `docs/xmuse/README.md`
- `docs/xmuse/mainline-contracts.md`
- `docs/xmuse/archive/2026-06-proof-closure-legacy/self-iteration-runtime-closure.md`
- `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md`
- `docs/xmuse/provider-matrix.md`
- `docs/xmuse/broad-suite-baseline-debt.md`
- relevant `src/xmuse_core/` and `tests/xmuse/` files located with `rg`

Required output:

- files that currently define proof levels;
- files that emit or test merge readiness / merge facts;
- MemoryOS Lite trace symbols or documented mismatch;
- OpenCode provider capability boundary;
- GitHub server-side truth gaps.

Acceptance:

- no behavior changes in S0;
- evidence map is written into the stage result or a documented local artifact;
- follow-on stage manifests are updated if the codebase reality differs from the
  blueprint.

## S1 - P0 Merge Proof Semantics

Goal:
separate local merge readiness from real GitHub merge facts.

Required behavior:

- fake/local/contract paths must not emit `pr_merged`;
- local readiness must use `merge_readiness_evaluated` or an equivalent explicit
  readiness event;
- fake/local/contract readiness must include `real_merge_event: false`;
- `pr_merged` must require server-side evidence such as merge commit SHA,
  `merged_at`, PR event, or authenticated GitHub API evidence.

Required tests:

- fake/default self-iteration writeback cannot create `pr_merged`;
- contract proof cannot claim server-side merge;
- readiness and merge facts are distinct event kinds;
- docs and runtime artifact examples agree.

Allowed implementation:

- update event names;
- add typed constants or schema fields;
- add validation preventing proof-level escalation;
- update affected replay artifacts/docs.

Do not:

- remove GitHub truth evidence entirely;
- fake a server-side merge record;
- change unrelated review/merge behavior.

## S2 - P1 MemoryOS Lite Trace Evidence

Goal:
make MemoryOS Lite trace evidence discoverable and consumable by xmuse.

Required behavior:

- verify whether `fetch_trace`, `MemoryOSLiteTraceEvidence`, or an equivalent
  path already exists;
- if missing, implement a minimal discoverable trace-evidence boundary;
- convert MemoryOS Lite `/sessions/{id}/trace` shape into lane/runtime evidence;
- keep default CI fake/local and no-live-service;
- live MemoryOS Lite remains opt-in through env vars.

Required tests:

- schema/model test for trace evidence;
- fake adapter test for session trace conversion;
- default test proving live service is not required;
- opt-in test or documented manual gate for live trace capture.

Required docs:

- document exact proof level:
  `fake_runtime_proof` for fake trace;
  `live_service_proof` only for explicit live MemoryOS Lite trace.

Do not:

- import `memoryos_lite` directly into `xmuse_core`;
- bypass REST-first boundary;
- make live MemoryOS Lite a default CI requirement.

## S3 - P1 Natural Deliberation Proof Boundary

Goal:
make deterministic replay and natural multi-GOD deliberation evidence visibly
separate.

Required behavior:

- deterministic fixture exports remain `contract_proof`;
- natural deliberation exports must carry `natural_deliberation: true` or an
  equivalent explicit marker;
- natural transcript without live evidence must remain `manual_gap` or equivalent;
- unresolved blockers still prevent blueprint freeze.

Required tests:

- deterministic/non-natural replay cannot claim live proof;
- natural proof metadata is explicit;
- source refs and speech-act refs are present;
- unresolved blockers block freeze.

Do not:

- claim real multi-GOD runtime from deterministic fixture data;
- weaken blueprint freeze rules.

## S4 - P1 OpenCode-In Deliberation Pilot

Goal:
allow OpenCode to participate in deliberation as a bounded secondary actor
without making it a first-class authority.

Minimum supported speech acts:

- `propose`
- `ask`
- `challenge`

Required behavior:

- OpenCode returns structured speech-act/evidence artifacts;
- OpenCode cannot mutate durable xmuse state directly;
- OpenCode cannot perform review/takeover/final merge judgment;
- unavailable OpenCode falls back or blocks cleanly with evidence;
- provider matrix continues to label OpenCode as secondary/experimental unless
  persistent session and MCP/writeback parity are proven.

Required tests:

- provider policy allows only bounded deliberation pilot capability;
- OpenCode output is normalized into speech-act artifacts;
- invalid speech acts or direct state writes are rejected;
- missing `DEEPSEEK_API_KEY` does not fail default CI.

Current contract boundary:

- `opencode.deepseek_flash_worker` may advertise `bounded_deliberation` only as a
  secondary provider capability;
- `ProviderPolicyService.select_bounded_deliberation(...)` must return
  `allowed_speech_acts == ("propose", "ask", "challenge")`;
- bounded deliberation decisions must carry `state_write_allowed == false`;
- `normalize_bounded_deliberation_output(...)` converts bounded provider output
  into `god_speech_act_message.v1` artifacts without writing chat storage or
  durable xmuse state;
- normalized OpenCode output must reject `object`, `vote`, `decide`, `evidence`,
  `handoff`, and any direct state-write/writeback request;
- unavailable OpenCode must record a health/fallback cause and fall back to a
  bounded Codex deliberation decision or block at the stage harness;
- OpenCode stage harness commands must use
  `opencode run --model opencode-go/deepseek-v4-flash --variant max`;
- this does not prove live OpenCode deliberation, natural transcript quality, MCP
  parity, durable state writeback, review authority, takeover authority, or merge
  authority.

Do not:

- implement full provider unification in this round;
- promote OpenCode to primary GOD;
- route OpenCode through Codex-only session binding.

## S5 - P1 GitHub Server-Side Truth Collector Scaffold

Goal:
separate local workflow contract from server-side GitHub truth.

Required model fields:

- workflow run ID;
- check suite or check run ID;
- expected source app;
- branch protection or ruleset snapshot;
- review event identity;
- Code Owner coverage when available;
- merge commit SHA, `merged_at`, and PR event for real merge truth.

Allowed implementation:

- schema/model plus fake collector;
- read-only live collector if credentials exist;
- docs/runbook for operator evidence capture.

Required tests:

- local workflow files do not count as server-side proof;
- fake collector produces contract/fake proof only;
- `pr_merged` requires merge truth fields.

Do not:

- mutate branch protection;
- require GitHub credentials in default CI;
- treat PR template/CODEOWNERS files as server-side enforcement proof.

## S6 - P2 Long-Run Heartbeat And Replay Artifact

Goal:
make long execution auditable across lane execution, review, patch-forward, and
memory closure.

Required behavior:

- lane evidence heartbeat every logical stage;
- review verdict evidence;
- patch-forward lineage evidence;
- final replay summary with proof levels;
- failed lanes remain immutable; patch-forward appends lineage.

Real-run SLO:

- heartbeat at least every 15 minutes;
- review snapshot at least every 45 minutes;
- no silent stage transition without evidence.

Test strategy:

- simulate time/sequence without sleeping;
- verify heartbeat sequence and replay summary;
- verify failed lane facts are not overwritten.

## S7 - Documentation, Debt, And Handoff

Update docs only where behavior changed or evidence boundaries need to be clearer.

Required docs candidates:

- `docs/xmuse/provider-matrix.md`
- `docs/xmuse/archive/2026-06-proof-closure-legacy/vision-runtime-evidence-closure.md`
- `docs/xmuse/broad-suite-baseline-debt.md`
- `docs/xmuse/memoryos-lite-runtime-compatibility.md`
- `docs/xmuse/archive/2026-06-pre-m7/codex-strengthening-handoff.md`

Required handoff content:

- completed stages;
- proof level now achieved;
- fake/local/live/server-side boundaries;
- blockers and owners;
- validation commands;
- remaining debt.

Do not update broad historical docs unless they are the current entry point for
the changed behavior.

## S8 - Final Review And Verification

Run final verification appropriate to changed files.

Required:

- `uv run ruff check .`
- focused pytest for every changed contract/runtime path
- package boundary tests if imports changed
- provider policy tests if OpenCode behavior changed
- MemoryOS Lite fake/default tests if trace evidence changed
- GitHub truth tests if merge/readiness models changed

Use a fresh adversarial review for changed behavior. The review must check:

- proof-level contamination;
- direct durable state writes;
- OpenCode authority escalation;
- live/server-side claims without evidence;
- missing tests for behavior changes;
- docs/code mismatch.

## Proof-Level Rules

Use these definitions consistently.

`contract_proof`:
schema, docs, focused tests, deterministic fixtures, local workflow contract.
Must not claim live provider, natural live deliberation, real MemoryOS service, or
server-side GitHub enforcement.

`fake_runtime_proof`:
local fake runtime behavior, fake providers, fake MemoryOS adapter. Must not
claim real external connectivity.

`live_service_proof`:
explicit opt-in service evidence, such as live MemoryOS Lite trace. Requires
operator-provided URL/credentials and must be clearly marked.

`server_side_merge_proof`:
authenticated GitHub evidence proving checks/review/merge facts. Required before
emitting `pr_merged`.

## Blocker Handling

When blocked, do not continue by weakening proof language.

A blocked report must include:

- blocked stage ID;
- exact missing input or external dependency;
- proof level that remains achievable;
- files already changed;
- tests already run;
- owner for unblock;
- next safe stage, if any.

## Final Deliverable

The final answer from the long goal must contain:

- completed stages and status;
- files changed;
- proof-level changes;
- validation commands and results;
- live/server-side evidence captured or explicitly missing;
- blockers and owners;
- next recommended iteration.
