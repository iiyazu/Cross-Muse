# Natural Groupchat A2A Task Plan

Updated: 2026-06-29

This plan is the detailed task reference for
`docs/xmuse/natural-groupchat-a2a-goal-prompt.md`.

## Minimum Success

This is a staged A/B/C closure goal, sized for a multi-hour or overnight
development run. It is not complete merely because one support surface improves.
Reach one of these terminal states:

- integrated closure: one real natural groupchat demand flows through Track A,
  Track B, and Track C on the same source refs, creates a small xmuse PR,
  observes exact-head CI, and reaches guarded merge plus main CI observation;
- operator blocker: the same staged chain reaches the deepest possible durable
  boundary, records the next authority boundary, preserves source refs, and
  names why operator input is required;
- implementation blocker: a repeated runtime boundary failure is captured as a
  durable blocker with producer, consumer, proof level, and a patch/refactor
  target for the next goal turn.

Track-specific closure means:

- Track A: natural groupchat carries the demand through durable discussion,
  provider invocation, proposal/review/dispatch/execution, PR, exact-head CI,
  guarded merge, and main CI, or stops at a durable blocker.
- Track B: MemoryOS sidecar contributes continuity to the same Track A demand
  without creating proposal, review, dispatch, execution, GitHub, or merge truth;
  degraded sidecar state does not block xmuse authority.
- Track C: frontend/API/UX read projection follows the same Track A/B demand and
  exposes operator next actions and proof traces without writing truth.

The #294 run satisfied the first docs-sentinel integrated A/B/C closure. The
next stage must not treat another docs sentinel as equivalent progress unless
it proves repeatability, better diagnosis, or a new failure boundary. The next
closure target is a progressively more capable development harness:

- repeat the integrated chain through a standard evidence summary;
- shorten durable diagnosis at the first stalled boundary;
- carry one low-risk real-code lane through PR/CI/guarded merge/main CI;
- then expand to multi-lane or multi-PR behavior.

## Execution Throughput Gate

Before each implementation loop, record:

```text
stage
primary_track
support_tracks
primary_authority_boundary
support_authority_boundaries
core_chain_progress_target
support_progress_target
closure_target
producer
consumer
condition
proof_level
failure_boundary
blocked_boundary
timebox
next_primary_action
continue_or_stop_condition
```

Track A is the default primary track. Track B or Track C can become primary
only as the named next stage in this staged closure plan, or when the loop names
the Track A blocker it removes.
Support work must not be reported as core-chain completion.

The goal loop should operate in staged cadence, not in isolated small-task
cadence:

1. Run the largest reachable real chain for the current stage before patching.
2. Patch or refactor only the first durable blocker on that stage.
3. Verify the patched boundary with a runtime replay or exact source-level
   contract test.
4. Advance to the next stage only when the previous stage's stop condition is
   satisfied or explicitly blocked.
5. Keep PRs domain-scoped, but let a single long goal produce multiple PRs as the
   staged chain advances.

For final reports, keep these categories separate:

- core-chain progress: real natural groupchat movement toward PR, exact-head
  CI, guarded merge, main CI, or an explicit operator blocker;
- support progress: MemoryOS sidecar, frontend read projection, copilot or
  subagent audit, docs, local tests, and CI harness improvements;
- forbidden progress claims: projection readiness, sidecar continuity,
  advisory audit output, green local tests, or green CI described as natural
  groupchat production readiness without the real chain evidence above.

Do not restart documentation-calibration churn during this long goal. Update this
task plan only when a milestone changes execution rules, staged closure status,
or a durable blocker. Do not rewrite the baseline table merely because main moved
after a PR.

## Recorded Main Baseline

Recorded server facts through the 2026-06-28 Track A/B/C/D pass:

| PR | Domain | Merge commit | Main CI run |
|---|---|---|---|
| #242 | native peer GOD default / A2A natural real chain foundation | `c1d19ad2ae9bd8b22742376c98968073a508329c` | `28292323481` success |
| #244 | natural peer-callback proposal handoff hardening | `65910e683eb6f8c70ed5428ac77c0e971ff0aa99` | `28307269298` success |
| #245 | MemoryOS sidecar/context continuity | `328e79a9b153843069146826192dc9ac2cc115d6` | `28308325362` success |
| #246 | frontend read-only UX projection | `176d26272cb118c62ab424053d77bd6a1a44a5a5` | `28309007290` success |
| #247 | read-only copilot audit guardrails | `a94ebb33c751a02b13e00de06d53a0fd56649405` | `28309375745` success |
| #248 | current goal documentation calibration | `a752432b73a5d7a6cdd735d9776141f0d2ebc3a1` | `28309677170` success |
| #249 | GitHub exact-head evidence hardening | `159b851435b735ac828eca0637b601907c306cef` | `28310645567` success |
| #250 | current main truth documentation calibration | `38306251fa1a820b35ce3ca46e877e9e04f1679c` | `28310900258` success |
| #251 | MemoryOS sidecar support UX projection | `10d9f89900646e5b364424e01dc931383983084c` | `28311466358` success |
| #252 | A2A review verdict approval boundary | `e2a2e2742ff452bc8e306fb6efdd525231d22bff` | `28311860691` success |
| #253 | docs refresh after A2A boundary merge | `db62fdaa34a3ec87c96553e5c0f45101ea2062d0` | `28311993991` success |
| #254 | proposal approval dispatch queue boundary | `b04fcd902296fe78086aa8502f98ee565a4cb545` | `28312435751` success |
| #255 | durable dispatch gate refs for read projections | `502f7a6b1e777991ff22c7ea73bdc52373e2a218` | `28313035616` success |
| #257 | dispatch authority refs to execute/frontend/copilot consumers | `9a30aeadd242e4978a84683801c0c65494a66c1c` | `28313722964` success |
| #258 | docs refresh after dispatch authority refs | `d78a2df79d7515e1b536052b958f2e1be7983e51` | `28313973331` success |
| #259 | dispatch ack separated from execution proof | `53dbeb9ace749510e9cb0f82f73cbd4df11ec190` | `28314524612` success |
| #260 | docs refresh after execution proof boundary | `7e8d06679715e8eb2f2d78743a5827fa5dbfaa3f` | `28314661776` success |
| #261 | dispatch authority refs into lane execution context | `ea0f23b85011cb68429089a8acdc30891d2836c2` | `28315305767` success |
| #262 | docs refresh after dispatch context refs | `3772b07f9f47bca0205dac465af762463b5bdeaa` | `28315629004` success |
| #263 | MemoryOS sidecar dispatch handoff continuity | `3fe6d8a853ddeade5548733970445c9ef108f4e1` | `28316064426` success |
| #264 | docs refresh after MemoryOS sidecar handoffs | `de51f8faf981b04755ebf1a2bd8fdd6f62a0a993` | `28316229878` success |
| #265 | frontend dispatch continuity read projection | `09b8164866992e9f7df8ac84072f4d9aeb26a602` | `28316510543` success |
| #266 | copilot intake authority boundary clarification | `235f36ea4c5c38b73d23a786903407ee99088f23` | `28316712653` success |
| #267 | docs refresh after B/C/D completion | `df83ea99803e64f97317d854f69c0befa468adf4` | `28316881854` success |
| #268 | acceptance gate lane projection terminalization | `76a57362c73f0f63dc2d9b61f871b24a7a5bb329` | `28317369049` success |
| #269 | docs refresh after Track A projection fix | `0b383026b1b250be3fe11a91697d3c6b8102ae55` | `28317521660` success |
| #270 | acceptance gate noop integration projection | `fa1cc1e1996be3c18540f574c3513b0cafbea642` | `28317667416` success |
| #271 | docs refresh after noop integration projection | `7c5831d75b6efa59c0ce57aebbae21fdefc68240` | `28317787154` success |
| #272 | docs sentinel GOD backend alignment | `c60f12090868a35ca56917feabfd66cee6306809` | `28318839517` success |
| #273 | docs refresh after sentinel backend alignment | `8ae7600991371783658829900cda59ecdbed7a57` | `28318943411` success |
| #274 | docs calibration after post-sentinel main facts | `f0a7041eba700ce4c1240dfac389f8ca54e6bd52` | `28319547618` success |
| #275 | frontend final-action hold read projection | `9811e12c236ac88e31e67771d9788d75489d767d` | `28319975311` success |
| #276 | copilot final-action hold authority boundary | `232e91672650d2bcda6cae0e8e2f8cd9976bfae1` | `28320338930` success |
| #277 | MemoryOS sidecar context continuity refs | `22e0e4ead7dd14a77ae737b88d288227bd86f79e` | `28321033182` success |
| #278 | docs refresh after MemoryOS sidecar continuity | `f15cd87f595eebe1131a7e4c8590c18f1557acdc` | `28321147772` success |
| #279 | docs-only gate profile and explicit-profile scope enforcement | `5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d` | `28323650818` success |

These rows are GitHub server facts for merged code and CI as recorded in this
docs snapshot. They are not live GitHub truth, latest remote-head truth, proof
of production-ready natural groupchat, live MemoryOS authority, frontend
completeness, GitHub review truth, or autonomous merge.

The recorded `last_observed_baseline` is
`5d03bbe82a3f17f2d854d46ee4dcbf7972fe533d`. Next execution loop should start
from a clean live `origin/main` after Phase 0 refresh, not from this static
baseline by assumption. Then push the largest reachable real chain beyond the
current handoff/review/dispatch boundary. If the next chain cannot advance,
record the durable blocker and next authority boundary rather than relying on
stdout, worker summaries, or local tests.

Latest local runtime evidence recorded during #272 preparation:

- local runtime chain observed across durable authority and projection:
  `chat.db` human mention -> architect collaboration request -> execute
  `execute_feasibility_verdict` -> collaboration callback -> architect
  `lane_graph` proposal -> review-trigger verdict -> approved proposal ->
  dispatch queue -> dispatch ack -> lane execution -> gate -> review verdict ->
  `awaiting_final_action`;
- producer/consumer proof boundaries:
  `chat_inbox_items`, `collaboration_responses`, `proposals`, `resolutions`,
  and `chat_dispatch_queue` are durable chat-plane authority surfaces;
  `feature_lanes.json` is projection evidence only; `review_plane.json`, gate
  reports, and the isolated execution worktree file are review/gate/execution
  proof surfaces;
- condition satisfied:
  `docs/xmuse/track-a-timebudget-sentinel-20260628.md` existed in the
  isolated execution worktree with the exact expected sentence, the lane
  reached `awaiting_final_action`, and the final action hold stayed pending;
- failure boundary learned:
  a 240-second proposal timeout is too short for the current real multi-hop
  natural chain because individual provider turns can consume 90-200 seconds;
  use multi-hop budgets such as `--proposal-timeout-s 900` and
  `--peer-chat-response-wait-s 420` for this sentinel until latency is
  reduced;
- proof limitation:
  this is local runtime evidence, not GitHub server truth, production
  readiness, autonomous merge, or live MemoryOS proof.

Latest post-#273 local runtime evidence:

- command path:
  `scripts/run_fullchain_docs_sentinel.py` was run from clean
  `origin/main@8ae7600991371783658829900cda59ecdbed7a57` without
  review/execute backend env overrides and without an explicit CLI
  `--peer-god-backend`; the sentinel script defaulted to native and launched
  `xmuse.platform_runner --peer-god-backend native`;
- condition satisfied:
  feature `track-a-post273-sentinel-20260628` reached
  `awaiting_final_action`, final action hold `final-219d4426fecd` stayed
  pending, and the isolated execution file
  `docs/xmuse/track-a-post273-sentinel-20260628.md` matched the exact expected
  sentence;
- authority/projection boundary:
  `chat.db`, `collaboration_responses`, `proposals`, `resolutions`,
  `chat_dispatch_queue`, `review_plane.json`, gate reports, and the isolated
  execution worktree were inspected; `feature_lanes.json` was used only as
  projection evidence;
- proof limitation:
  this default native sentinel is local durable runtime proof for the
  handoff/review/dispatch/lane/gate/final-action-hold path. It is not proof of
  GitHub PR creation by the natural chain, autonomous merge, live MemoryOS, or
  production readiness.

Latest #279 PR-head local runtime evidence:

- command path:
  `scripts/run_fullchain_docs_sentinel.py` was run from clean PR head
  `f3212bba613693cdbb38249fd746fb760064d3c8` after the `docs-only` gate
  profile fix, with `--peer-god-backend native` and `--review-provider auto`;
- condition satisfied:
  feature `track-a-docs-only-gate-final2-20260628` reached
  `awaiting_final_action`, final action hold `final-e7112dbbd2b9` stayed
  pending, `gate_passed` was true, and the isolated execution file
  `docs/xmuse/track-a-docs-only-gate-final2-20260628.md` matched the exact
  expected sentence;
- gate proof:
  `logs/gates/track-a-docs-only-gate-final2-20260628/report.json` selected
  `profile_ids=["docs-only"]` and ran
  `uv run pytest -q tests/xmuse/test_mainline_contract_docs.py
  tests/xmuse/test_contract_smoke_gates.py` with return code 0;
- authority/projection boundary:
  `chat.db`, proposal/review/resolution/dispatch queue, `review_plane.json`,
  gate report, review verdict, final-action hold, and the isolated worktree
  were the inspected proof surfaces; provider stdout and local test output
  remained diagnostics only;
- proof limitation:
  this is local durable runtime evidence for the natural docs sentinel on the
  #279 PR head, not proof of production readiness, autonomous merge, live
  MemoryOS authority, full frontend readiness, or GitHub review truth.

## Historical Pre-#294 Source-Derived Context

The following #284 source-derived inspection is retained only as historical
context for the source surfaces that existed before #294. It is not the next
goal starting state. The next stage starts from the Post-#294 Starting State
below, then refreshes live facts in Phase 0.

- historical GitHub/server fact observed before the older task-plan update:
  `origin/main` and the clean inspection worktree were both at
  `7f8a3df3e7153bf60fab2e0d84203f0df62c947b`; main CI run `28325344618` was
  `success`; recent merged PRs #281-#284 were inspected as GitHub server facts;
- Track A implementation shape: `chat.db` dispatch queue, dispatch bridge,
  acceptance spine, review plane, final-action holds, and GitHub gate evidence
  producer exist in source. They support durable control-plane closure, but they
  do not yet prove a production-style natural groupchat demand has created a PR,
  observed exact-head CI, and reached guarded merge/main CI;
- Track B implementation shape: optional MemoryOS sidecar recall and dispatch
  handoff continuity exist, including degraded non-blocking behavior and
  namespace-scoped continuity refs. This is context continuity, not xmuse truth;
- Track C implementation shape: peer-chat UX read projection exposes timeline,
  worklist, dispatch state, supporting context, review state, final-action
  holds, source refs, and authority boundaries. It is projection-only and has no
  write capabilities;
- historical blocker before #294: A/B/C had useful pieces, but the task plan
  still needed to drive them through one staged demand instead of letting
  support surfaces accumulate as separate progress claims.

This historical section is not a replacement for the static
`last_observed_baseline`, the post-#294 baseline below, or live GitHub truth.

## Post-#294 Starting State

Live server and durable run facts recorded on 2026-06-29:

- `post_abc_closure_baseline`:
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6`;
- PR #294:
  `https://github.com/iiyazu/Cross-Muse/pull/294`;
- run / conversation / final action:
  `track-abc-integrated-memoryos-degraded-20260629-01`,
  `conv_c7528fbf03b84755b8d4eb65166aa0a1`, `final-cce17cc5e0e7`;
- PR head:
  `9be3b17190380171756bd8375fcb946247217d7c`;
- exact-head CI:
  `28332878486` success for `quality-gates`, `contract-smoke-gates`,
  `real-runtime-integration-gate`, and `peer-chat-runtime-gate`;
- guarded merge:
  `gh pr merge --match-head-commit 9be3b17190380171756bd8375fcb946247217d7c`;
- main CI:
  `28332906024` success on
  `07630131dcb6e26c8dc09dcf41690381e5cd0ee6`;
- durable run root:
  `.goal-runs/2026-06-29/track-abc-integrated-memoryos-degraded-20260629-01`;
- durable authority/proof refs:
  `chat.db`, `review_plane.json`, `final_actions.json`,
  `final_action_prs.json`, `github_gate_evidence.json`,
  `logs/gates/track-abc-integrated-memoryos-degraded-20260629-01/report.json`,
  and the isolated execution worktree file
  `docs/xmuse/track-abc-integrated-memoryos-degraded-20260629-01.md`;
- GitHub gate evidence:
  `github_gate_evidence.json#evidence=ghgate_e3e90b98395d4c6e81136db6241ecf49`;
- MemoryOS state:
  sidecar `build_context` and `ingest` degraded against an unavailable endpoint,
  did not block Track A, and frontend projection exposed
  `continuity_attempt_ref`;
- frontend state:
  `/api/dashboard/peer-chat/conversations/conv_c7528fbf03b84755b8d4eb65166aa0a1/ux-projection`
  returned `projection_only=true`, empty `write_capabilities`,
  `review_state.total=1`, `final_action_state.status_summary={"approved":1}`,
  no pending final-action holds, and MemoryOS degraded summary.

Proof limitation: #294 is still a docs-only sentinel. It proves one integrated
A/B/C path through PR/CI/guarded merge/main CI, not long-run repeatability,
real-code implementation, multi-lane scheduling, live MemoryOS truth, complete
frontend UX, or production readiness.

## Next-Stage Task Ladder

Execute the next stage in this order. Do not skip to a later rung unless the
previous rung has a durable success record or a named blocker.

### Rung 1 - Repeatability And Evidence Summary

Objective: turn the #294 replay shape into a standard operator-grade run path.

Deliver:

- a single command or runbook for integrated A/B/C replay from durable demand to
  final-action state;
- a generated or scripted evidence summary that lists conversation, proposal,
  review verdict, dispatch queue entry, execution proof, final action, PR,
  exact-head CI, merge commit, main CI, MemoryOS state, and frontend projection
  endpoint;
- clear failure boundary output when the replay stops early.

Success proof:

- two consecutive replays either reach final action or record the same named
  durable boundary without manual durable-file spelunking;
- evidence summaries separate authority, execution proof, GitHub server truth,
  sidecar continuity, and read projection.

### Rung 2 - Durable Failure Taxonomy

Objective: reduce long-goal diagnosis time before increasing task complexity.

Deliver durable classifications for:

- provider turn no-writeback or timeout;
- collaboration callback/proposal failure;
- review-trigger timeout or rejected verdict;
- lane execution failure;
- docs/code gate failure;
- branch-behind or stale-base PR creation;
- exact-head CI failure;
- guarded merge rejection;
- main CI failure;
- MemoryOS unavailable or ingest failure;
- frontend projection gap.

Success proof:

- each class has producer, consumer, condition, proof level, failure boundary,
  and next recovery action;
- frontend/API projection can show the active blocker without writing truth.

### Rung 3 - Low-Risk Real-Code Lane

Objective: prove xmuse can carry a small source-code change, not only docs-only
sentinel output.

Constraints:

- select one low-blast-radius behavior with existing local tests nearby;
- require test-first or contract-first implementation after the runtime demand
  identifies the lane;
- keep the PR domain-scoped and small;
- do not expand to multi-lane until the single code lane reaches PR/CI/merge or
  a durable blocker.

Success proof:

- natural groupchat demand produces proposal/review/dispatch/execution/review
  verdict/final-action;
- the resulting PR contains a code/test diff, exact-head CI success, guarded
  merge, and main CI success; or
- a durable blocker names the exact authority boundary preventing code-lane
  closure.

### Rung 4 - Multi-Lane / Multi-PR Harness

Objective: test scheduling, dependency, failure isolation, and projection
behavior across 2-3 independent lanes.

Success proof:

- each lane has separate source refs, review verdict, final action, and PR/gate
  state when applicable;
- one lane failure does not fabricate success for another lane;
- frontend projection shows lane-specific status without treating
  `feature_lanes.json` as authority.

### Rung 5 - MemoryOS Live/Degraded Contract

Objective: prove both live and degraded sidecar modes without changing xmuse
truth.

Success proof:

- degraded mode records attempt refs and does not block Track A;
- live mode, when configured, records recall/ingest continuity refs;
- neither mode creates proposal, review, dispatch, execution, GitHub, merge, or
  production truth.

### Rung 6 - Frontend Operator Cockpit

Objective: make the authority chain inspectable without reading internals.

Success proof:

- read-only frontend/API surfaces show timeline, proposal, review, dispatch,
  execution/gate, final action, GitHub gate, MemoryOS sidecar, and blocker
  state for the same demand;
- `write_capabilities` remains empty for the peer-chat UX projection;
- frontend never becomes a truth producer.

## Phase 0 - Truth Refresh And Run Setup

Run and record live facts dynamically:

```text
git status -sb
git branch --show-current
git fetch origin main --prune
git rev-parse HEAD origin/main
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,isDraft,mergeStateStatus,url
gh pr list --state merged --limit 12 --json number,title,headRefOid,mergeCommit,mergedAt,url
gh run list --branch main --workflow "xmuse CI" --limit 5 --json databaseId,headSha,status,conclusion,createdAt,url
git worktree list --porcelain
```

Exit with:

- a clean `origin/main`-based worktree selected for source edits;
- dirty historical worktrees marked reference-only;
- live main SHA, latest main CI, open PR state, and recent merged PRs recorded
  from GitHub server facts;
- current provider availability and expected latency budget recorded;
- current stage selected from Phase 1-5 below;
- the first runtime chain selected before any patching.

## Phase 1 - Track A Real-Chain Harness

Objective: drive the largest reachable natural groupchat chain before patching.

The target chain is:

```text
durable human/operator demand
-> chat.db message/inbox
-> natural groupchat handoff
-> provider-native peer turn
-> durable proposal or blocker
-> review-trigger verdict
-> proposal approval or explicit blocker
-> dispatch queue
-> dispatch bridge / execute peer
-> lane execution proof
-> review verdict
-> final-action hold or GitHub gate path
```

Deliver:

- a runtime replay command or harness path that starts from a durable demand,
  not from manually constructed downstream artifacts;
- durable source refs for message, inbox, proposal, review trigger, dispatch
  queue entry, lane/execution proof, review verdict, and final-action state when
  those objects exist;
- first durable blocker recorded with producer, consumer, condition, proof level,
  and failure boundary;
- patch/refactor only the first blocker that prevents this chain from advancing.

Validation:

- provider stdout, worker summaries, and local test output remain diagnostics
  only;
- `feature_lanes.json` is used only as projection/live queue, not authority;
- Ray is not used as the default natural groupchat route;
- the chain reaches at least the previous `awaiting_final_action` local proof
  level, or records why current main regressed before that boundary.

Continue when:

- Track A reaches final-action hold or a later PR/CI boundary from the natural
  chain; or
- the first repeated blocker has a domain-scoped implementation target and a
  planned PR.

Stop when:

- the same boundary fails twice after a focused refactor;
- proof would require stdout or local tests as truth;
- the next change would become an umbrella PR.

## Phase 2 - Track A PR/CI/Guarded Merge Closure

Objective: extend Track A from local final-action closure to GitHub-visible PR
and guarded merge closure.

Deliver:

- one small PR created from the natural chain or an explicit durable blocker that
  states why the chain cannot create or prepare that PR yet;
- exact PR head SHA recorded;
- required GitHub check names and per-check-run head SHAs observed;
- final-action resolution only through producer-owned GitHub gate evidence or a
  persisted manual gap;
- guarded merge by operator or explicit operator blocker;
- main CI observed after merge when merge occurs.

Validation:

- PR/CI/merge state is tied to exact head SHA, check-run names, check-run head
  SHAs, run metadata, and GitHub server facts;
- no GitHub review truth, ready-to-merge, or autonomous merge claim is made;
- final-action approval without accepted GitHub gate evidence leaves the
  acceptance spine blocked, not accepted.

Continue when:

- one natural-chain PR reaches exact-head CI and either guarded merge/main CI or
  explicit operator blocker.

Stop when:

- GitHub facts cannot be collected for the exact head SHA;
- final-action acceptance would require bypassing the GitHub evidence producer.

## Phase 3 - Track B MemoryOS Sidecar Closure On The Same Demand

Objective: attach MemoryOS sidecar continuity to the same Track A demand without
creating or mutating xmuse truth.

Deliver:

- opt-in sidecar recall for natural peer turns when MemoryOS is configured;
- dispatch handoff continuity ingest using the same queue/proposal/review/
  resolution/artifact refs consumed by Track A;
- degraded sidecar behavior that preserves Track A progress and records an
  attempt ref without emitting assembled continuity refs;
- prompt/supporting-context/read-projection metadata that separates sidecar
  continuity refs from authority `source_refs`.

Validation:

- contract proof with fake/local adapter remains enough when live MemoryOS is not
  configured;
- live proof is claimed only when a live MemoryOS service is actually used;
- sidecar output is never proposal, review, dispatch, lane execution, GitHub,
  merge, or production truth;
- #259 remains the proof split: `peer_ack:*`, `mcp_writeback:*`, provider run
  refs, and queue refs do not become acceptance spine lane execution proof.

Continue when:

- the same demand can be replayed with MemoryOS configured or deliberately
  degraded, and Track A authority is unchanged.

Stop when:

- MemoryOS work starts displacing the Track A chain;
- sidecar continuity would need to be promoted into authority to make progress.

## Phase 4 - Track C Frontend/API Read Projection Closure On The Same Demand

Objective: make the same Track A/B demand inspectable through read-only API/UX
projection without bypassing authority stores.

Deliver read-only payloads for:

- conversation timeline and agent cards;
- inbox/worklist and next action;
- proposal, dispatch, review verdict, final-action, and GitHub gate/gap state;
- MemoryOS sidecar supporting context and continuity metadata when present;
- collapsible detail payloads with source refs and authority boundaries.

Validation:

- frontend/API consumers can inspect the chain without reading internal stores
  directly and without writing truth;
- `write_capabilities` stays empty for peer-chat UX projection;
- worklist `source_refs` remain authority-only and keep execution evidence
  separate;
- pending final-action holds are operator next-action projection, not GitHub gate
  or merge truth;
- recalled sidecar text is never exposed as frontend truth.

Continue when:

- the same demand can be inspected end-to-end from intake through the deepest
  reached Track A/B state, and missing fields are captured as explicit projection
  gaps.

Stop when:

- frontend work becomes a full UI build unrelated to the current authority chain;
- projection state is needed to create truth.

## Phase 5 - Integrated A/B/C Replay

Objective: run one integrated replay after staged Track A, B, and C changes so
the final report describes one coherent chain, not three unrelated improvements.

Replay proof must name:

```text
demand_id_or_message_ref
conversation_id
proposal_or_blocker_ref
review_verdict_ref
dispatch_queue_ref
execution_evidence_ref
final_action_ref
github_gate_evidence_or_gap_ref
memoryos_continuity_or_degraded_ref
frontend_projection_ref_or_endpoint
```

Validation:

- each ref has a producer and consumer;
- each proof claim states whether it is authority, execution proof, GitHub server
  truth, sidecar continuity, or read projection;
- local tests are only regression/contract evidence for the code changed during
  the goal;
- subagent or copilot audit, when used, is sampled at decision points and remains
  candidate input only.

Stop with success when:

- the integrated chain reaches guarded merge/main CI; or
- an explicit durable blocker names the next authority boundary and source refs.

Stop with failure when:

- the chain can only proceed by weakening forbidden claims or using diagnostic
  output as proof truth.

## Phase 6 - Documentation And Final Report

Update only the concise current docs unless a historical artifact needs a
pointer:

- `docs/xmuse/README.md`;
- `docs/xmuse/natural-groupchat-a2a-goal.md`;
- `docs/xmuse/natural-groupchat-a2a-behavior.md`;
- `docs/xmuse/natural-groupchat-a2a-goal-prompt.md`;
- this file;
- `docs/xmuse/release-checklist.md` only if release claims change.

Final report includes:

- maximum real chain reached;
- demand attempted or completed;
- PR/CI/merge state tied to exact GitHub facts;
- A/B/C progress by stage;
- MemoryOS state: skipped, degraded, contract proof, or live proof;
- frontend/API projection state: absent, partial, complete for the replayed
  demand, or blocked;
- whether Ray was used in the main path;
- durable blockers and next authority boundary;
- exact forbidden claims not made.

Current final-report notes for the #294 milestone:

- maximum verified chain: one docs-only integrated A/B/C natural groupchat run
  reached final action, PR #294, exact-head CI, guarded merge, and main CI as
  GitHub server facts;
- Track A state: #294 proves the docs-sentinel control-plane path through
  proposal/review/dispatch/execution/final-action/PR/CI/merge. The next Track A
  work is repeatable evidence summary, durable diagnosis, then one low-risk
  real-code lane;
- Track B state: MemoryOS sidecar build/ingest degraded against an unavailable
  endpoint and remained non-blocking; this was degraded attempt projection, not
  live MemoryOS truth;
- Track C state: read-only peer-chat UX projection exposed review state,
  approved final-action state, GitHub gate refs, and degraded MemoryOS attempt
  refs with no write capabilities;
- Ray use: not the default natural groupchat route; remains optional legacy;
- copilot/subagent audit: useful at PR-ready review, repeated boundary failure,
  or authority classification uncertainty, but output is candidate input only;
- next authority boundary: start from `post_abc_closure_baseline`, refresh live
  facts in Phase 0, then progress through repeatability/evidence summary,
  durable failure taxonomy, low-risk real-code lane, multi-lane/PR,
  MemoryOS live/degraded contract, and read-only frontend cockpit.
