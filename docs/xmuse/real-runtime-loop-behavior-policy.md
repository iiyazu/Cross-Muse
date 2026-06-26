# Real Runtime Loop Behavior Policy

Updated: 2026-06-18

Note: for the next natural groupchat A2A `/goal`, prefer
`docs/xmuse/natural-groupchat-a2a-behavior.md`. This file remains a historical
runtime-loop policy and a compatibility reference for older goals.

This policy governs long xmuse `/goal` work that uses real runtime-chain
testing to build or repair production behavior. It is not a TDD-first workflow.
It is authority-first, producer-first, consumer-first, evidence-first, and
runtime-first.

Detailed task decomposition lives in:

```text
docs/xmuse/real-god-chatgroup-fullchain-loop-decomposition.md
```

## `/goal` Prompt Boundary

Keep the `/goal` prompt short. It should name the objective, point to this
policy and the loop decomposition, state any hard current-session constraints,
and define the immediate stop conditions.

Do not paste this whole policy into the `/goal` prompt. Do not create a
separate goal-prompt document. The prompt is an execution handle; this file is
the behavioral contract.

## Purpose

Each loop reconciles desired runtime behavior against observed durable state.
A loop is complete only when a real producer creates the expected durable
artifact, a real consumer uses it, and the result is verified through the
smallest relevant real chain.

Passing tests alone is never enough.

This file is the operating policy for the long runtime goal. It is not a
feature specification, not a test plan, and not a checklist to satisfy by
paperwork. When runtime evidence conflicts with this document, record the
evidence, update the policy if needed, and keep the proof boundary explicit.

## Core Rules

- Run real chains before patching whenever the runtime boundary is executable.
- Do not start a loop by writing a red test.
- Do not use fake producers to prove production behavior.
- Do not count stdout, terminal logs, worker summaries, or skill output as
  durable product truth.
- Preserve inherited `manual_gaps` and `forbidden_claims` unless stronger proof
  exists.
- Keep each loop to one concrete runtime target.
- Keep each PR to one implementation domain.

## Evidence Maintenance

Runtime loops must maintain the evidence trail while they run. Before adding new
runtime notes, delete or mark invalid stale content instead of layering fresh
claims over known-bad observations.

Primary evidence files for this long goal:

- `docs/xmuse/archive/2026-06-pre-m7/fullchain-runtime-operation-record-2026-06-17.md`;
- `docs/xmuse/archive/2026-06-pre-m7/fullchain-runtime-findings-2026-06-17.md`;
- `.goal-runs/<date>/<loop-id>/` for raw artifacts and snapshots.

The operation record should capture commands, process boundaries, durable ids,
and artifact paths. The findings document should capture product-impacting
failures, current classification, and the next targeted action. Neither file is
proof by itself; both point back to durable runtime artifacts.

## GitHub Usage Budget

Use GitHub only when it is the authority or when the current loop explicitly
needs PR/issue state.

Rules:

- run `gh api rate_limit` before GitHub-heavy work;
- prefer one truth refresh at the start of a loop and one verification at the
  end;
- avoid repeated polling of PRs, checks, or runs unless waiting on a live
  server-side transition is the loop target;
- do not trigger CI for broad exploratory branches;
- do not create placeholder PRs for incomplete runtime boundaries;
- do not mutate PR #43;
- do not expand an existing PR to absorb unrelated implementation domains;
- allow PR count to grow only when each PR is small, domain-scoped, and
  validated through the normal CI/CD path.

GitHub facts are server truth only for the exact resource, head SHA, and time
inspected. Local tests, worker output, and PR bodies are not GitHub truth.

## PR Anti-Bloat Rules

PR size is controlled by implementation domain, not by emotional attachment to a
branch.

Split separate domains into separate PRs:

- provider and GOD chatgroup runtime;
- lane/closure spine execution;
- review delivery;
- GitHub truth observation;
- MemoryOS adapter;
- TUI or cockpit projection;
- documentation-only evidence maintenance.

When a loop touches multiple domains, land only the domain required to close the
current runtime boundary and move the rest to backlog. If a branch starts
turning into an umbrella PR, stop and split before pushing.

## Loop Contract

Before changing code, identify:

- target behavior;
- authority object or durable store;
- real producer;
- real consumer;
- expected durable artifact;
- proof level;
- forbidden claims;
- failure boundary.

Then run the smallest real chain that exercises that target and inspect durable
state before making a patch.

Preferred evidence sources:

- `chat.db`;
- `god_sessions.json`;
- inbox/message records;
- provider session records;
- MCP/callback tool traces;
- lane graph / graph-set artifacts;
- `feature_lanes.json` only as projection or queue, not authority;
- review artifacts;
- process logs;
- GitHub facts only when GitHub is the authority.

## Reconcile Order

Every loop follows this order:

1. Name the loop target.
2. State authority, producer, consumer, condition, and proof level.
3. Run the smallest real runtime chain.
4. Record observed durable state.
5. Classify the failure boundary.
6. Form one minimal root-cause hypothesis.
7. Apply the smallest targeted fix.
8. Re-run the real runtime chain.
9. Preserve both failure and success evidence.
10. Stop only when the loop target is complete or explicitly blocked.

Adjacent steps may be combined when one real run naturally produces enough
evidence. Do not split work into artificial micro-loops just to look orderly.

## Failure Boundaries

Use these boundary names when classifying failures:

- provider registration;
- provider command availability;
- session identity;
- prompt/tool contract;
- routing;
- delivery lifecycle;
- MCP/callback writeback;
- dispatch;
- isolated worktree execution;
- review verdict;
- GitHub server truth;
- operator safety.

If a failure does not fit one of these, name the new boundary explicitly before
patching.

## Patch Threshold

Simple boundary:

- at most two targeted patches;
- a third same-boundary failure requires refactor or boundary redesign.

Complex or shared boundary:

- at most one targeted patch;
- the next same-boundary failure requires refactor or boundary redesign.

Do not stack compatibility branches to hide architectural failure.

## Anti-TDD-Abuse Rules

Tests protect confirmed behavior. They do not manufacture closure.

Tests may be added only after the authority, producer, consumer, and real
failure boundary are known. If a new test and implementation are created in the
same loop, record what wrong implementation the test would catch.

Forbidden test patterns:

- tests construct artifacts that production runtime should produce;
- mocks bypass provider tool use;
- mocks bypass MCP/callback writeback;
- mocks bypass GOD session identity;
- mocks bypass runner dispatch;
- mocks bypass independent review verdict;
- tests assert desired closure without observed durable state;
- tests omit inherited `manual_gaps` or `forbidden_claims`;
- local tests are reported as review truth, merge truth, or server truth.

Allowed test roles:

- pin a runtime contract after real failure is observed;
- protect a bugfix from regression;
- validate parser/adapter behavior that cannot safely call the provider every
  run;
- enforce package boundaries and safety guards.

## Anti-Superpowers-Abuse Rules

Skills, subagents, OpenCode workers, and other orchestration helpers are process
aids only. They do not produce proof truth.

Rules:

- skill output is not proof;
- worker output is candidate evidence only;
- subagent self-report is not review truth;
- OpenCode output is not server-side truth;
- use a skill only when its trigger actually applies or the user explicitly
  requests it;
- do not layer skills to avoid direct runtime evidence;
- if a skill conflicts with xmuse authority-first rules, xmuse rules win.

Use direct repo/runtime inspection as the default. Use brainstorming or other
skills only when they materially improve the current decision, not as a ritual
before every patch.

## Real Groupchat Truth

A GOD chatgroup reply is true only when represented in durable chat state.

Provider stdout, streamed text, terminal logs, and worker summaries are evidence
only. They are not groupchat truth unless a configured fallback explicitly
classifies them as degraded and writes a durable message with that
classification.

For successful peer reply truth, require:

- durable assistant message in `chat.db`;
- correct author participant;
- reply linked to the relevant inbox item when applicable;
- MCP/callback tool trace such as `chat_post_message`, or an equivalent durable
  callback writeback;
- inbox item terminal state consistent with the reply.

Natural peer-GOD groupchat requires durable multi-turn evidence involving at
least Codex and OpenCode as peer providers. A fake provider, one-shot smoke, or
single-provider run is not enough.

## Fullchain Truth

The fullchain target is not complete until the groupchat drives a real demand to
a completed outcome:

```text
groupchat discussion
-> durable decision/proposal
-> execution unit
-> isolated worktree candidate
-> independent review
-> main Codex audit/import
-> validation
-> small PR
-> conditional merge only when GitHub truth permits
```

No downstream artifact may be manually fabricated to bypass the groupchat path.

## Runtime Probe Merge Safety

Runtime probes that execute and review real lanes must not auto-merge into the
control branch unless that merge is the explicit loop target.

Default probe command:

```bash
uv run xmuse-platform-runner ... --no-auto-merge
```

`--no-auto-merge` uses the final-action hold path. A merge-accepted lane should
stop at `awaiting_final_action` with a pending final-action hold. This is the
expected safe proof boundary for execution/review probes.

If a loop intentionally tests local auto-merge, record the integration target
before starting the runner and inspect control-branch HEAD afterward. Do not
leave probe commits on the active control branch unless the operator has
explicitly authorized that merge.

## Runtime Proof Levels

Allowed proof levels:

- `manual_gap`;
- `contract_proof`;
- `local_runtime_proof`;
- `opt_in_live_proof`;
- `server_side_truth`.

Proof may only move upward when a stronger producer or authority exists.

Do not claim:

- GitHub review truth from local review;
- merge truth from PR state;
- server truth from local runtime;
- live MemoryOS from local artifacts;
- natural peer-GOD groupchat from fake or single-provider runs;
- full L8-L10 or L1-L11 closure from partial runtime evidence.

## Evidence Recording

Maintain the runtime evidence docs:

- `docs/xmuse/archive/2026-06-pre-m7/fullchain-runtime-operation-record-2026-06-17.md`;
- `docs/xmuse/archive/2026-06-pre-m7/fullchain-runtime-findings-2026-06-17.md`.

For each loop, save raw evidence under:

```text
.goal-runs/<date>/<loop-id>/
```

Recommended files:

- `commands.txt`;
- `result.json`;
- `logs/`;
- `state/chat-summary.json`;
- `state/god-sessions-summary.json`;
- `state/lane-summary.json`;
- `notes.md`.

Do not commit runtime databases, logs, or generated state unless explicitly
intended as a small redacted artifact.

## GitHub Use Budget

GitHub is an authority only for GitHub facts.

Use GitHub for:

- initial truth refresh;
- PR creation/update when a small branch is ready;
- final PR/check/mergeability verification;
- merge only after current-head server facts support it.

Do not use GitHub for:

- the inner debug loop;
- repeated CI polling;
- proving local review;
- proving runtime behavior;
- widening PR scope.

Rate-limit guard:

- if core API remaining is below 1000, stop nonessential GitHub queries;
- if search remaining is below 5, stop search queries.

PR budget:

- do not use a fixed PR-count ceiling as a substitute for domain control;
- split by implementation domain and dependency boundary;
- allow the number of PRs to grow dynamically when runtime evidence shows that
  separate domains must land separately;
- stop before creating an umbrella PR or a PR that crosses unrelated domains;
- if repeated tiny PRs keep exposing the same complex boundary, stop patching
  and redesign that boundary instead of opening another patch PR;
- no mutation of PR #43;
- do not expand PR #44 beyond minimal closure spine;
- split unrelated domains into separate PRs.

Anti-bloat intervention:

- if one PR starts crossing implementation domains, stop and split the work;
- if a patch drags unrelated history, rebuild the needed slice manually;
- if the branch starts becoming an umbrella branch, stop before pushing;
- do not spend GitHub API or CI budget on inner-loop debugging.

## Completion Definition

A loop is complete when:

- the target condition is satisfied by durable state;
- the real consumer has consumed the real producer output;
- focused verification has passed;
- failures and fixes are recorded;
- forbidden claims remain preserved;
- remaining manual gaps are explicit.

A loop is blocked when the same blocking condition remains after the allowed
patch threshold or when required external authority is unavailable.
