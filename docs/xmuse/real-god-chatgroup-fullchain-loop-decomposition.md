# Real GOD Chatgroup And Fullchain Loop Decomposition

Updated: 2026-06-21

This document decomposes the long xmuse goal into runtime-driven loops. Each
loop completes one useful target before scope expands. It is not a specification
and not a waterfall plan; if one real run proves adjacent targets, record that
evidence and move forward.

Behavior rules live in:

```text
docs/xmuse/real-runtime-loop-behavior-policy.md
```

## How To Use This From `/goal`

The `/goal` prompt should reference this file instead of duplicating it. A goal
run should start with truth refresh, run the largest safe real chain, then select
the next task as the first failing authority / producer / consumer boundary with
durable evidence.

Do not treat the loop list as mandatory staircase work. Do not use it to justify
an umbrella PR. Each loop must end as one of: runtime proof, classified blocker,
small scoped patch with rerun evidence, or a small PR if the boundary is
complete and the PR budget allows it.

This file is a loop target map, not a product spec. The operator may skip,
merge, or reorder loops when one real runtime run proves adjacent targets or
exposes a higher-priority blocker. The invariant is that every loop ends with
recorded durable evidence and a clear next boundary.

## Tonight's Target

Build and prove the maximum reachable real chain:

```text
human demand
-> durable GOD chatgroup
-> Codex and one configured non-Codex peer discussion
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

This is a real-runtime-driven development goal, not a spec-writing goal. The
operator should not start by inventing a new architecture document. Start from
the current implementation, run the largest safe chain, inspect durable state,
and refactor only where runtime evidence shows the existing boundary cannot
hold.

## GitHub Main Audit Checkpoint

Before selecting the next implementation loop, refresh GitHub mainline truth.
A 2026-06-21 GPT-5.5 Pro audit of `origin/main` at
`88cb2d9 fix: guard final-action target imports` found that mainline groupchat
has moved beyond the older local Grok branch shape:

- dynamic participants are intended to be real session-bound peers, not roster
  text;
- peer progress, roster changes, collaboration, proposal review, and dispatch
  gates are part of the groupchat control plane;
- structured MCP/callback writeback is the successful truth path;
- proposal review pending gates and execute feasibility verdicts are governance
  gates, not prompt-only advice;
- peer reply drain callbacks and proposal semantic dedupe are part of runtime
  closure and retry hygiene;
- deliberation/freeze guardrails are the direction for turning speech into
  auditable decisions.

If the active branch is behind or diverged from `origin/main`, the first loop is
not another feature patch. The first loop is branch realignment:

```text
preserve local useful changes
-> rebase/merge or recreate on origin/main
-> rerun focused groupchat/Grok proof
-> then choose the next failing runtime boundary
```

Do not claim audited mainline capabilities on a diverged local branch. Do not
continue implementing broad groupchat behavior on the older branch unless the
loop target is explicitly "port this mainline capability back with focused
evidence".

## Acceptance Spine Checkpoint

The first local AcceptanceSpine/GoalRun cut is now implemented:

```text
human post_human_message intake
-> durable acceptance_spines row
-> source-linked proposal_id
-> approved resolution verdict ref
-> dispatch queue entry
-> dispatch evidence refs
-> read-only Chat API status
```

This is a product-control-plane improvement, not a fullchain success claim. It
does not yet close independent review verdicts, final-action targets, or
GitHub/server gate evidence.

For the next loop, prefer the smallest real path that extends the same spine:

```text
review_plane verdict
-> final_actions hold/target ref
-> GitHub/server gate evidence ref or manual gap
-> accepted / blocked / failed terminal status
```

Do not add provider scope or UI scope until this same demand record can show
where closure stopped.

## Current Implementation Baseline

The current implementation has useful production-shaped parts, but the real GOD
chatgroup must be treated as not production-ready until the loops below prove
the durable chain.

Known implemented parts:

- durable chat storage and REST/MCP surfaces;
- GOD participants, inbox routing, and peer scheduler pieces;
- provider adapters and policy/registry boundaries;
- blueprint / feature / lane projection and execution machinery;
- platform runner, isolated execution, review, and final-action hold pieces;
- minimal durable AcceptanceSpine/GoalRun rows for human intake, proposal,
  approval/verdict, dispatch queue, dispatch evidence, and read-only API status;
- dashboard/TUI read-model surfaces.

Current unproven or fragile boundaries:

- natural Codex + configured non-Codex peer multi-turn discussion;
- provider-native session continuity across resumes;
- MCP/callback writeback as the only successful reply truth;
- proposal production from real chat instead of manual construction;
- groupchat-produced proposal flowing through execution and review;
- independent review verdicts and final-action/GitHub gate evidence linked back
  into the same acceptance spine;
- repeated-run stability, stale-session recovery, and timeout handling.

Therefore the first runtime assumption is:

```text
xmuse has usable groupchat components, not yet a proven production-grade
natural multi-CLI GOD chatgroup fullchain.
```

## Dual Core

### Core 1: Real GOD Chatgroup Runtime

Codex and one configured non-Codex CLI provider should act as registered CLI
peers in the same durable GOD chatgroup. The current active non-Codex target is
Grok because OpenCode is not available in the current runtime environment.

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

Both cores are first-class tonight. Do not defer the fullchain indefinitely
after improving groupchat, and do not bypass groupchat just to make fullchain
execution look green.

## Phase Map

Use these phases as operating modes, not as rigid gates. A real run may cross
multiple phases; record that evidence and continue from the next failing
boundary.

Phase 0: Truth refresh and cleanup.
Purpose: know current branch, PR, provider, port, process, and runtime-state
facts before mutating code or GitHub.
Exit: current facts are recorded, stale services are cleared or explicitly
owned, and the first runnable chain is selected.

Phase A: Real GOD chatgroup breakthrough.
Purpose: Codex and the active non-Codex provider behave as durable peer CLI
providers in one chatgroup, with natural handoff and durable writeback.
Exit: a real Codex/non-Codex peer exchange is visible in `chat.db`, or the
failing boundary is classified with durable evidence.

Phase B: Groupchat-to-completion fullchain.
Purpose: a human demand enters the groupchat, produces a durable proposal or
decision, runs one real execution unit, reaches independent review, and stops at
safe final-action hold or another explicit target.
Exit: one useful demand reaches a durable completed state, or the first failing
fullchain boundary is classified.

Phase C: Stability and recovery.
Purpose: repeated runs, restart/resume, stale-session recovery, timeout
classification, and degraded-state behavior after the chain works once.
Exit: repeated-run evidence exists, or the next reliability blocker is recorded
and scoped.

Phase D: Small PR publication.
Purpose: split completed implementation domains into small reviewable PRs,
without expanding PR #43 or creating a new umbrella branch.
Exit: one scoped PR exists per completed domain, or publication is blocked by
validation/GitHub truth.

## Provider Scope

Minimum real peer set:

- Codex: architect / execution-leaning peer;
- one configured non-Codex peer: review / adversarial peer.

Current enabled non-Codex target:

- Grok: register as a durable GOD groupchat peer first, preferably as architect
  or review; do not require lane execution support in the first pass.

Current blocked / optional peer:

- OpenCode: remains a valid secondary peer target, but the current environment
  has no available OpenCode provider. Do not block the multi-provider groupchat
  breakthrough on OpenCode while Grok is the active configured target.

Grok CLI environment prerequisite:

```bash
which grok
grok login
grok models
```

Expected Grok model:

```text
grok-composer-2.5-fast
```

Correct smoke command:

```bash
grok -m grok-composer-2.5-fast \
  -p "Non-mutating smoke test. Reply exactly: GROK_SMOKE_OK" \
  --output-format json \
  --max-turns 1 \
  --no-wait-for-background \
  --disable-web-search
```

Do not use `composer-2.5` as the model id. On 2026-06-21, `grok models`
reported `grok-composer-2.5-fast` as the available Composer 2.5 model, while
`grok -m composer-2.5 ...` failed with `unknown model id`.

Grok CLI capabilities to preserve behind an adapter:

- `grok -p "..."` / `--single` for one-shot headless turns;
- `grok -r` / `--resume` for session resume;
- `--output-format json` for structured output;
- `grok mcp` for MCP configuration;
- `-w, --worktree` for isolated worktree execution context.

Minimal Grok GOD scope:

- extend `cli_kind` / runtime typing to accept `grok`;
- create participant records with `cli_kind="grok"`, provider id `grok`, and
  explicit model `grok-composer-2.5-fast`;
- persist GOD session records with `runtime="grok"`,
  `provider_session_kind="grok_cli_session"`, and resume-capable
  `provider_session_id` when Grok exposes one;
- implement a `grok_persistent` shim compatible with the existing stdin/stdout
  peer protocol;
- implement `GrokLauncher` and register it in the default launcher registry;
- configure Grok MCP access to `xmuse-mcp-server` so successful replies use
  `chat_post_message` with `reply_to_inbox_item_id`;
- prove inbox -> Grok -> durable writeback before using Grok for lane
  execution.

Grok minimum MCP writeback tool subset:

- `chat_read_inbox`;
- `chat_post_message`;
- `chat_mention`;
- `chat_emit_proposal`;
- `chat_create_collaboration_request`;
- `chat_record_collaboration_response`;
- `chat_inspect_conversation`.

Provider-plane Grok support is a second phase. Only add
`ProviderId.GROK`, `GrokProviderAdapter`, `grok.god` / `grok.worker` profiles,
or platform orchestrator `god_runtime="grok"` support after the groupchat peer
path has durable writeback proof.

OpenCode invocation must use:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

OpenCode must not be treated as a Codex subagent. It is a peer provider when
available.

## Design References

Use `/home/iiyatu/clowder-ai` as a design reference for:

- durable agent identity and provider-session separation;
- model-agnostic CLI peers;
- strict mention parsing and routing warnings;
- delivery lifecycle visibility;
- callback/MCP writeback reconciliation;
- shared memory/evidence discipline.

Do not absorb the whole clowder-ai routing architecture. In xmuse, the durable
chat inbox remains the peer wakeup authority, and centralized coordinator
execution remains the only execution-status writer. Runtime worklists,
recent-speaker fallback routing, chat-product UI scope, and peer-to-peer
execution autonomy are out of scope.

The clowder-ai-derived target shape for xmuse is:

```text
conversation message
-> strict mention / speech-act validation
-> durable inbox item
-> turn lifecycle record
-> peer context assembly
-> participant session
-> provider-native session binding
-> MCP/callback writeback
-> message/card/read-model projection
```

The minimum absorbable design units are:

- turn lifecycle: a traceable chain from source message and inbox item to
  running peer turn, writeback message, latency evidence, and terminal status;
- writeback reconciliation: MCP/callback writeback is the only happy path, and
  stdout/stream text can only be degraded evidence, never success truth;
- strict mention contract: unknown or ambiguous `@target` must fail closed or
  surface a routing warning; natural-language `@mention` is display-only until
  it creates a durable inbox item;
- identity separation: conversation, participant session, provider session
  binding, and active turn slot must remain distinct concepts;
- context assembly: peer prompts should be built from a bounded context
  assembler rather than scattering groupchat, MCP, handoff, and execution
  policy text through scheduler code.

Use k8s-style reconciliation for desired state versus observed state.

Use loop-engineer style feedback cycles: run, observe, classify, patch, rerun.

Do not copy unrelated UI, brand, desktop, memory, marketplace, or broad
orchestration scope.

Aggressive refactor is allowed inside the real groupchat runtime boundary when
repeated runtime evidence shows the existing design cannot preserve peer
identity, delivery lifecycle, or durable writeback. That authorization does not
extend to unrelated TUI, MemoryOS, GitHub truth, or release-pack expansion.

## Loop Shape

Each loop should produce one of:

- a proved runtime capability;
- a classified blocker with durable evidence;
- a small code change plus rerun evidence;
- a small PR when the boundary is complete.

Do not create artificial staircase tasks. Prefer the largest real chain that is
currently safe to run, then narrow only at the first proven failure boundary.

Every loop owns exactly one primary target. Related cleanup is allowed only when
it is required to rerun that target. Unrelated implementation domains must move
to backlog or a separate PR.

Every loop must have a concrete exit:

- runtime proof for the loop target;
- classified blocker with durable evidence;
- one targeted patch plus rerun evidence;
- refactor decision after the patch threshold is reached;
- small PR boundary when the implementation domain is complete.

## Loop Selection Rule

At the start of each loop, choose the largest reachable real chain, not the next
item in a checklist.

Selection order:

1. If the fullchain can run safely, run it and stop at the first proven failure.
2. If fullchain cannot run, run the deepest real subchain that includes a real
   producer and real consumer.
3. If only a single boundary can run, make that boundary the loop target and
   preserve the blocker evidence.

After each loop, either advance to the next runtime boundary or split the
implementation domain into a small PR. Do not keep patching inside one branch
just because another adjacent problem is visible.

The operator should intervene when branch scope expands across domains. The
right response is to split domains into separate PRs, not to argue about whether
one oversized PR can still be explained.

## Adaptive Task Discovery Rule

This document intentionally stays short. It does not predefine every task a
long `/goal` run will execute. Codex `/goal` may decompose work automatically,
but each discovered task must come from the real xmuse flow:

```text
human demand
-> GOD chatgroup
-> proposal / decision
-> lane projection
-> isolated execution
-> review
-> final-action / GitHub truth
```

Select the next task as the first failing authority/producer/consumer boundary
in the largest safe real chain. A valid task has:

- one durable authority object;
- one real producer;
- one real consumer;
- one expected artifact;
- one proof level;
- explicit forbidden claims.

Examples of valid discovered tasks:

- `mention validation`: a real groupchat message cannot create a correct inbox
  item;
- `writeback reconciliation`: a provider turn writes durable output but the
  scheduler classifies it as failed;
- `provider session identity`: a real peer turn cannot resume the expected
  provider session;
- `review verdict`: the execution chain produces a candidate but review cannot
  cite a durable verdict.

Examples of invalid active tasks:

- dashboard polish discovered while the active boundary is writeback;
- broad refactor without a failing producer/consumer pair;
- MemoryOS or GitHub expansion when the current runtime blocker is chatgroup
  delivery;
- test cleanup that does not protect a real observed failure.

When runtime exposes several issues, keep only the first failing boundary as the
active task and record the rest as backlog or manual gaps.

## Loop Entry Template

Each loop should leave a compact entry in the operation record or findings file
so a resumed `/goal` session can continue without expanding scope:

```text
loop_id:
active_boundary:
target_behavior:
authority:
producer:
consumer:
expected_artifact:
commands_run:
observed_artifacts:
failure_boundary:
root_cause_hypothesis:
patch_scope:
rerun_result:
proof_level:
forbidden_claims_preserved:
next_action:
```

`next_action` must be singular. If two next actions look equally valid, stop and
record the choice instead of continuing.

## Parallel Execution Option

Short validation on 2026-06-20 found that xmuse already has enough primitives to
serve as a bounded parallel execution plane for `/goal`:

- `xmuse/platform_runner.py` runs lane dispatch under a writer lease and
  semaphore-limited concurrency;
- `PlatformOrchestrator` can reconcile lane batches concurrently;
- `scripts/goal_stage_runner.py` provides a bounded stage runner for stable
  stages;
- `docs/xmuse/解耦开发协议.md` already requires single coordinator ownership,
  isolated work, and no direct subagent durable-state writes.

Use those primitives only after `/goal` has selected one active boundary. The
main `/goal` agent remains the control plane; xmuse lanes are worker slots that
produce evidence or candidate patches.

Allowed pattern:

```text
active boundary selected
-> parallel observe / diagnose lanes
-> main /goal chooses one root-cause hypothesis
-> single-writer patch or one candidate lane
-> parallel verify / review lanes
-> main /goal imports or rejects the candidate
-> real chain rerun
```

Do not parallelize:

- active boundary selection;
- durable authority writes;
- PR creation or merge;
- patch import into the control worktree;
- tasks with overlapping allowed files;
- tasks that would require changing the current active boundary.

Parallel lane candidates should fit this compact shape:

```text
lane_id:
objective:
kind: observe | diagnose | patch_candidate | review | verify
active_boundary:
allowed_files:
forbidden_files:
allowed_commands:
expected_artifact:
write_policy: read_only | candidate_patch_only
```

If a candidate cannot name its active boundary, scope, allowed commands, and
expected artifact, it is not ready for parallel execution. Keep it as backlog or
run it serially under the main `/goal` loop.

## Runtime Loop Families

The long goal has two primary loop families. They may interleave when one real
run crosses both boundaries.

Groupchat loops:

- registered CLI peer identity;
- durable provider sessions;
- MCP/callback writeback;
- strict mentions, routing warnings, and handoffs;
- turn lifecycle and writeback reconciliation;
- Codex + active non-Codex peer multi-turn discussion;
- groupchat-produced proposal or decision.

Fullchain loops:

- proposal approval;
- lane projection from authority to queue;
- isolated worktree execution;
- independent review;
- final-action hold or explicit merge target;
- main Codex audit/import;
- validation and small PR.

Stability loops start only after the reachable chain works once. They should
focus on restart/resume, repeated turns, stale-session recovery, provider
timeouts, and degraded-state classification.

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
- provider availability checks for `codex`, `grok`, and `opencode`;
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
- Grok command smoke and login/model availability check;
- current Grok participant route through chat inbox if configured;
- OpenCode command smoke only if the provider is configured.

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
Represent Codex and the active non-Codex peer as durable registered peer
providers through the same runtime contract.

Authority:

- provider registry or equivalent runtime config;
- participant records;
- GOD session registry.

Producer:

- peer runtime registration / session ensure path.

Consumer:

- peer scheduler / dispatch bridge.

Condition:

- Codex and the active non-Codex peer both have stable identity, role, command,
  session policy, and writeback contract;
- provider differences are adapter-local;
- no fake non-Codex peer is used.

Expected branch/PR domain:

- real GOD chatgroup runtime kernel.

## Loop 2A: Register Grok As GOD Peer

Status:
Enabled as the current non-Codex peer task.

Target:
Grok CLI can be registered as a durable GOD groupchat participant and selected
for a real peer turn without pretending it is a Codex subagent.

Authority:

- participant records in `chat.db`;
- GOD session registry;
- launcher registry;
- peer scheduler runtime mapping;
- MCP writeback traces.

Producer:

- participant bootstrap / apply path;
- `GrokLauncher`;
- `grok_persistent` shim;
- Grok CLI process.

Consumer:

- peer scheduler;
- inbox delivery;
- MCP `chat_post_message` writeback;
- dashboard/TUI read models.

Required code boundaries:

- `src/xmuse_core/chat/participant_store.py` accepts `cli_kind="grok"`;
- `src/xmuse_core/chat/bootstrap_contracts.py` accepts Grok cli/provider ids;
- peer scheduler/runtime mapping resolves Grok participants to Grok runtime;
- persistent peer ensure path can launch Grok;
- launcher registry exposes `GrokLauncher`;
- the shim speaks `hello`, `ping`, `abort`, `task`, `result`, and `error`.

Condition:

- current REST participant creation with `cli_kind="grok"` no longer fails at
  enum validation;
- bootstrap can create a Grok GOD participant and corresponding session record;
- Grok writeback is accepted only through durable MCP/callback writeback;
- stdout/JSON output from Grok is evidence, not reply truth;
- lane execution and platform orchestrator Grok support remain out of scope
  unless this loop is already proven.

Complete when:

- `which grok`, `grok login` state, and `grok models` evidence are recorded or
  the exact environment blocker is classified;
- a Grok GOD participant exists with durable `cli_kind="grok"`;
- a Grok GOD session exists with `runtime="grok"`;
- one inbox item can be delivered to Grok and reaches durable terminal state;
- successful reply proof contains a `chat_post_message` writeback linked to
  `reply_to_inbox_item_id`, or failure is durable and exact.

Suggested verification:

```bash
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
uv run pytest tests/xmuse/test_groupchat_bootstrap_lifecycle.py -q
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py -q -k grok
```

## Loop 3: Durable Peer Writeback

Target:
Codex and the active non-Codex peer can each produce one durable assistant
message through the chatgroup writeback path, with a visible turn lifecycle from
inbox claim to terminal writeback or classified failure.

Authority:

- `chat.db` messages;
- inbox terminal state;
- MCP/callback tool traces.
- turn lifecycle or latency trace records when available.

Condition:

- provider stdout or streaming text cannot satisfy reply truth;
- success requires durable message and matching tool/callback trace;
- failure is classified and durable.
- duplicate callback/stream output does not create duplicate assistant bubbles;
  secondary output can only augment metadata or degraded evidence.

Complete when:

- Codex writeback succeeds or fails closed with exact durable reason;
- active non-Codex peer writeback succeeds or fails closed with exact durable
  reason;
- no stdout fallback is counted as success;
- every completed turn can be followed by source message, inbox item,
  participant session, provider session binding, writeback message, and latency
  evidence where that evidence exists.

## Loop 4: Peer-To-Peer Handoff

Target:
Codex can hand off to the active non-Codex peer inside the GOD chatgroup, and
that peer can respond as a peer.

Condition:

```text
human -> Codex -> active non-Codex peer -> Codex or human
```

Complete when:

- the handoff path is visible in durable chat state;
- the active non-Codex peer is not invoked as a subagent;
- unknown or ambiguous handoff targets fail closed or produce a durable routing
  warning instead of silently falling back;
- all routing and delivery states are terminal or explicitly blocked.

## Loop 5: Multi-Turn Groupchat Reliability

Target:
The real Codex + active non-Codex peer groupchat survives repeated turns.

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
Runner or worker must not write the current control worktree. Runtime probes
must use `--no-auto-merge` unless local auto-merge is the explicit target.

Authority:

- lane graph or equivalent execution artifact;
- dispatch queue / runner state;
- isolated worktree candidate artifact.

Complete when:

- one execution unit runs in the isolated worktree;
- candidate evidence exists;
- current worktree is not modified by the worker or by runner auto-merge.

## Loop 8: Independent Review Passed

Target:
An independent review accepts the candidate.

Authority:

- review artifact / review verdict record;
- cited candidate artifact.
- review task terminal state in the review plane store.

Condition:

- review must cite the candidate;
- review terminal state must be passed, not merely terminal failed;
- if review does not produce a passed verdict, the review task must still end
  as `failed_classified` or `interrupted_retryable` with a terminal reason and
  evidence refs;
- worker self-report is not review truth.

Complete when:

- review passed with evidence;
- if `--no-auto-merge` is enabled, the lane stops at `awaiting_final_action`
  with a pending final-action hold;
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

- maximum three PRs for one long goal unless the active prompt lowers it;
- if the active prompt says PR budget is full, create no new PRs;
- continuing work must count already opened PRs against the budget.

Expected PR split:

1. Minimal closure spine foundation only.
2. Real GOD chatgroup runtime kernel with Codex + the active non-Codex peer.
3. Fullchain completion integration, or one blocking runner/dispatch safety fix.

Rules:

- do not mutate PR #43;
- do not expand any existing small PR beyond its stated scope;
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

## Expected PR Domains

Use these domains as the default split. A branch may skip a domain only when the
runtime evidence proves it is already complete.

P0: Evidence and policy maintenance.
Base: current active branch unless the active goal says main-only.
Gate: docs-only diff, `git diff --check`.
Waits for: nothing.

P1: Real GOD chatgroup runtime kernel.
Base: origin/main or the smallest prior required PR.
Gate: Codex and the active non-Codex peer durable registration plus at least
one real writeback path.
Waits for: provider command availability.

P2: Peer-to-peer handoff and proposal production.
Base: P1 if P1 changes the runtime contract.
Gate: human demand produces durable discussion and durable proposal without
manual proposal construction.
Waits for: P1.

P3: Fullchain execution and review.
Base: P2 if it consumes groupchat-produced proposal shape.
Gate: approved proposal reaches isolated execution and independent review; no
auto-merge unless explicitly targeted.
Waits for: P2.

P4: Reliability and recovery.
Base: the smallest merged runtime branch that contains the working chain.
Gate: repeated run, restart/resume, stale-session, and timeout evidence.
Waits for: at least one successful runtime chain.

P5: Downstream projections.
Base: proven upstream truth only.
Gate: dashboard/TUI/MemoryOS projections consume evidence; they do not create
truth.
Waits for: upstream authority path.

## Explicit Non-Goals

- PR #43 mutation;
- live MemoryOS;
- TUI / cockpit;
- Computer Use repair;
- GitHub truth framework expansion;
- broad suite cleanup;
- overnight readiness;
- full L1-L11 closure;
- natural peer-GOD groupchat completion without Codex + one configured
  non-Codex peer durable multi-turn evidence.

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
