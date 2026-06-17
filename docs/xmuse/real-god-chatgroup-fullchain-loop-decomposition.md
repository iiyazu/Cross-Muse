# Real GOD Chatgroup And Fullchain Loop Decomposition

Updated: 2026-06-18

This document decomposes the long xmuse goal into runtime-driven loops. Each
loop completes one useful target before scope expands. It is not a specification
and not a waterfall plan; if one real run proves adjacent targets, record that
evidence and move forward.

Behavior rules live in:

```text
docs/xmuse/real-runtime-loop-behavior-policy.md
```

## Tonight's Target

Build and prove the maximum reachable real chain:

```text
human demand
-> durable GOD chatgroup
-> Codex and OpenCode peer discussion
-> durable decision/proposal
-> real execution unit
-> isolated worktree candidate
-> independent review
-> main Codex audit/import
-> validation
-> small PR
-> conditional merge only when GitHub server truth permits
```

The core challenge is the real GOD chatgroup. It may be aggressively refactored
if the current implementation cannot preserve durable peer identity, session
continuity, and natural groupchat delivery.

## Dual Core

### Core 1: Real GOD Chatgroup Runtime

Codex and OpenCode should act as registered CLI peers in the same durable GOD
chatgroup.

Required properties:

- durable peer identity;
- durable provider session;
- provider-native CLI capability preserved;
- natural `@mention` and handoff;
- durable MCP/callback writeback;
- observable delivery lifecycle;
- multi-turn discussion;
- no stdout or streamed text counted as successful reply truth.

### Core 2: Fullchain Completion Loop

The real GOD chatgroup must drive a small production demand to completion. The
fullchain may not bypass the chatgroup by manually constructing downstream
artifacts.

## Provider Scope

Tonight's minimum real peer set:

- Codex: architect / execution-leaning peer;
- OpenCode: review peer.

Grok and other providers are backlog until Codex + OpenCode can complete a
durable multi-turn peer exchange.

OpenCode invocation must use:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

OpenCode must not be treated as a Codex subagent. It is a peer provider.

## Design References

Use `/home/iiyatu/clowder-ai` as a design reference for:

- persistent agent identity;
- model-agnostic CLI peers;
- A2A routing;
- group mentions;
- delivery lifecycle;
- shared memory/evidence discipline;
- callback/MCP bridges;
- unified dispatch queue.

Use k8s-style reconciliation for desired state versus observed state.

Use loop-engineer style feedback cycles: run, observe, classify, patch, rerun.

Do not copy unrelated UI, brand, desktop, memory, marketplace, or broad
orchestration scope.

## Loop Shape

Each loop should produce one of:

- a proved runtime capability;
- a classified blocker with durable evidence;
- a small code change plus rerun evidence;
- a small PR when the boundary is complete.

Do not create artificial staircase tasks. Prefer the largest real chain that is
currently safe to run, then narrow only at the first proven failure boundary.

## Loop 0: Truth Refresh

Target:
Establish current repo, PR, provider, and runtime truth.

Run:

- `git status -sb`;
- `git branch --show-current`;
- `git rev-parse HEAD`;
- relevant `gh pr view` commands;
- limited `gh run list`;
- `gh api rate_limit` if GitHub will be used;
- provider availability checks for `codex` and `opencode`;
- port and process cleanup checks.

Complete when:

- current branch/PR facts are known;
- GitHub rate budget is known;
- provider commands are present or blocked;
- no stale service/process assumption remains.

## Loop 1: Current Chatgroup Runtime Fact Audit

Target:
Determine exactly what current xmuse groupchat can do today.

Run the maximum safe current chain:

- external Chat API + MCP service smoke;
- real Codex app-server restart/resume if available;
- real Codex app-server soak if available;
- OpenCode command smoke;
- current OpenCode participant route through chat inbox if configured.

Inspect:

- conversation bootstrap;
- participant/session mapping;
- inbox routing;
- MCP `chat_read_inbox`;
- MCP `chat_post_message`;
- peer scheduler behavior;
- durable messages;
- latency/tool traces;
- provider/session records.

Complete when:

- current groupchat parts are classified as production-capable,
  runtime-capable, contract-only, fake-only, or blocked;
- at least one blocker is selected as the next loop target.

## Loop 2: Unified CLI Peer Runtime Kernel

Target:
Represent Codex and OpenCode as durable registered peer providers through the
same runtime contract.

Authority:

- provider registry or equivalent runtime config;
- participant records;
- GOD session registry.

Producer:

- peer runtime registration / session ensure path.

Consumer:

- peer scheduler / dispatch bridge.

Condition:

- Codex and OpenCode both have stable identity, role, command, session policy,
  and writeback contract;
- provider differences are adapter-local;
- no fake OpenCode peer is used.

Expected branch/PR domain:

- real GOD chatgroup runtime kernel.

## Loop 3: Durable Peer Writeback

Target:
Codex and OpenCode can each produce one durable assistant message through the
chatgroup writeback path.

Authority:

- `chat.db` messages;
- inbox terminal state;
- MCP/callback tool traces.

Condition:

- provider stdout or streaming text cannot satisfy reply truth;
- success requires durable message and matching tool/callback trace;
- failure is classified and durable.

Complete when:

- Codex writeback succeeds or fails closed with exact durable reason;
- OpenCode writeback succeeds or fails closed with exact durable reason;
- no stdout fallback is counted as success.

## Loop 4: Peer-To-Peer Handoff

Target:
Codex can hand off to OpenCode inside the GOD chatgroup, and OpenCode can
respond as a peer.

Condition:

```text
human -> Codex -> OpenCode -> Codex or human
```

Complete when:

- the handoff path is visible in durable chat state;
- OpenCode is not invoked as a subagent;
- all routing and delivery states are terminal or explicitly blocked.

## Loop 5: Multi-Turn Groupchat Reliability

Target:
The real Codex + OpenCode groupchat survives repeated turns.

Minimum threshold:

- at least two restart/resume runs;
- at least two multi-turn soak runs;
- every successful reply is durable writeback;
- zero stdout fallback counted as success;
- zero unclassified provider side effects.

Complete when:

- the reliability threshold passes; or
- failures are classified with durable evidence and the next loop target is
  selected.

## Loop 6: Demand Decision From Groupchat

Target:
Use the real groupchat to discuss a small production demand and produce a
durable decision/proposal.

Good demand candidates:

- provider writeback reliability;
- delivery lifecycle classification;
- isolated dispatch safety;
- participant/session mapping ergonomics if it blocks runtime use.

Condition:

- the proposal or decision cites the chat messages that produced it;
- the artifact is produced through chatgroup path, not manually fabricated.

Complete when:

- a concrete durable decision/proposal exists;
- its source refs point to the real discussion.

## Loop 7: Isolated Fullchain Execution

Target:
Approved demand enters real execution in an isolated worktree.

Hard rule:
Runner or worker must not write the current control worktree.

Authority:

- lane graph or equivalent execution artifact;
- dispatch queue / runner state;
- isolated worktree candidate artifact.

Complete when:

- one execution unit runs in the isolated worktree;
- candidate evidence exists;
- current worktree is not modified by the worker.

## Loop 8: Independent Review Passed

Target:
An independent review accepts the candidate.

Authority:

- review artifact / review verdict record;
- cited candidate artifact.

Condition:

- review must cite the candidate;
- review terminal state must be passed, not merely terminal failed;
- worker self-report is not review truth.

Complete when:

- review passed with evidence;
- remaining gaps are explicit.

## Loop 9: Main Codex Audit And Import

Target:
Main Codex audits worker output and imports the minimal correct patch into the
active development branch.

Condition:

- worker output remains candidate evidence;
- main Codex reads and understands the patch;
- only the minimal safe change is applied;
- focused validation passes.

Complete when:

- active branch contains audited change;
- runtime evidence and validation results are recorded.

## Loop 10: Small PRs And Conditional Merge

Target:
Publish and merge small PRs only when their own boundary is complete and GitHub
server truth permits.

PR budget:

- maximum three PRs tonight.

Expected PR split:

1. PR #44: minimal closure spine foundation only.
2. Real GOD chatgroup runtime kernel with Codex + OpenCode peer.
3. Fullchain completion integration, or one blocking runner/dispatch safety fix.

Rules:

- do not mutate PR #43;
- do not expand PR #44 beyond minimal closure spine;
- do not use one PR for unrelated domains;
- merge only after GitHub truth refresh confirms current-head checks,
  mergeability, and review/branch protection requirements;
- if server truth is missing or unclear, stop with `manual_gap`.

## Anti-Bloat Boundaries

Split implementation domains into separate PRs.

Do not mix:

- closure spine;
- provider peer runtime;
- dispatch safety;
- API ergonomics;
- GitHub truth framework;
- MemoryOS;
- TUI.

If a fourth PR appears necessary, stop and report.

## Explicit Non-Goals

- PR #43 mutation;
- live MemoryOS;
- TUI / cockpit;
- Computer Use repair;
- GitHub truth framework expansion;
- broad suite cleanup;
- overnight readiness;
- full L1-L11 closure;
- natural peer-GOD groupchat completion without Codex + OpenCode durable
  multi-turn evidence.

## Final Report Requirements

Report:

- loops completed;
- loops blocked;
- exact runtime commands;
- durable artifacts observed;
- PRs opened, updated, or merged;
- failures preserved;
- manual gaps;
- forbidden claims not made;
- next backlog item.
