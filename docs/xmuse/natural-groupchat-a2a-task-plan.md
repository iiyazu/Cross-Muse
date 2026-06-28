# Natural Groupchat A2A Task Plan

Updated: 2026-06-28

This plan is the detailed task reference for
`docs/xmuse/natural-groupchat-a2a-goal-prompt.md`.

## Minimum Success

Reach one of these terminal states:

- a real natural groupchat chain creates a small xmuse PR, observes CI, and
  reaches operator merge or explicit operator blocker;
- or the chain stops at a durable blocker that names the next authority
  boundary and preserves source refs.

## Current Main Status

Current server facts after the 2026-06-28 Track A/B/C/D pass:

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

These rows are GitHub server facts for merged code and CI. They are not proof
of production-ready natural groupchat, live MemoryOS authority, frontend
completeness, GitHub review truth, or autonomous merge.

Next execution loop should start from clean `origin/main` at or after
`8ae7600991371783658829900cda59ecdbed7a57`, run Phase 0 again, and then push
the largest reachable real chain beyond the current handoff/review/dispatch
boundary. If the next chain cannot advance, record the durable blocker and
next authority boundary rather than relying on stdout, worker summaries, or
local tests.

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

## Phase 0 - Truth Refresh

Run and record:

```text
git status -sb
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
for pr in 242 244 245 246 247 248 249 250 251 252 253 254 255 257 258 259 260 261 262 263 264 265 266 267 268 269 270 271 272 273; do
  gh pr view "$pr" --json number,state,headRefName,headRefOid,baseRefName,mergedAt,mergeCommit,url
done
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,isDraft,mergeStateStatus,url
gh run list --branch main --limit 8 --json databaseId,headSha,status,conclusion,displayTitle,event,workflowName,createdAt,url
```

Exit with:

- clean worktree selected;
- `origin/main` verified against the current calibration or a newer fetched
  main SHA;
- #242, #244, #245, #246, #247, #248, #249, #250, #251, #252, #253, #254,
  #255, #257, #258, #259, #260, #261, #262, #263, #264, #265, #266, #267,
  #268, #269, #270, #271, #272, and #273 verified
  merged unless superseded by newer current docs;
- latest relevant main push CI observed through GitHub server facts;
- dirty historical worktrees marked reference-only;
- current provider availability recorded;
- first real runtime chain selected.

## Phase 1 - Security And Authority Preflight

Deliver:

- A2A bridge/server disabled by default;
- write paths local-only or token-gated;
- read-only Agent Card separated from task/send write path;
- A2A SDK task status cannot approve, dispatch, review, or merge directly.

Validation:

- missing token rejected for write path;
- valid token accepted for write path;
- read-only card behavior matches configured policy;
- no stdout or SDK status can bypass xmuse durable authority.

## Phase 2 - Agent Interop Kernel

Deliver:

- agent profile/card read model;
- official SDK model boundary available from main;
- layered prompt builder:
  `xmuse L0 + role identity + roster + task + bounded transcript + state refs`;
- context assembler with restart-stable refs;
- provider-native session binding and same-session serialization;
- canonical handoff task envelope.

Validation:

- Chat API can create a durable groupchat where each participant has identity,
  capability, provider/session state, and prompt/context payload.

## Phase 3 - Natural Handoff And Provider Invocation

Deliver:

- line-start mention or explicit target becomes durable handoff item;
- code-block mention stripping, target validation, self-filtering, dedupe, and
  ping-pong guard;
- outbound A2A/provider adapter for invocation;
- provider task/artifact normalization;
- writeback reconciliation into `chat.db` and inbox linkage.

Validation:

- real Codex participant reads inbox and produces durable proposal or blocker;
- main path does not use Ray as default route.

## Phase 4 - Review, Dispatch, Execution Closure

Deliver:

- structured review verdict remains review authority;
- P1/P2 findings block with evidence refs;
- P3 may allow dispatch only when explicitly non-blocking;
- approval/blocked state has source refs;
- dispatch/execution consumes xmuse authority, not stdout;
- dispatch acknowledgement remains a handoff proof, not lane execution proof;
- approved dispatch source refs are visible to saved lane graphs, projected
  lanes, lane context bundles, normal execution prompts, and persistent execute
  context without becoming execution proof;
- one small PR is created from the chain;
- CI is observed through GitHub server facts;
- operator merge or explicit blocker is recorded.

Validation:

- PR/CI/merge state is tied to exact head SHA, check-run names, check-run head
  SHAs, and run metadata;
- no GitHub review truth, ready-to-merge, or autonomous merge claim is made.

## Phase 5 - MemoryOS Sidecar

Only proceed after the natural groupchat chain has advanced.

Deliver:

- opt-in ingest of summaries, decisions, blockers, and artifact refs;
- recall into context assembler;
- degraded mode when unavailable.

Validation:

- contract proof with fake/local adapter is present on main through #245;
- durable dispatch gate refs are available to context/read projection consumers
  through #255;
- execute-peer dispatch context/prompt/envelope now carries the same ordered,
  deduped dispatch authority refs through #257;
- #259 keeps `peer_ack:*`, `mcp_writeback:*`, provider run refs, and
  `chat_dispatch_queue#entry=*` out of acceptance spine lane execution proof;
- #261 carries approved dispatch authority refs into lane graph/projection and
  worker-visible execution context, explicitly marked as not lane execution
  proof;
- #263 records approved dispatch handoff continuity into the optional
  MemoryOS sidecar with queue/proposal/review/resolution/artifact refs, and
  sidecar ingest degradation does not block `chat.db` dispatch authority;
- live proof only when live MemoryOS is actually available.

## Phase 6 - Frontend API / UX Contract

Do not attempt full frontend implementation.

Deliver read-only API payloads for:

- conversation timeline;
- agent cards;
- inbox/worklist;
- review/dispatch state;
- blocker/next action;
- artifact/source refs;
- card summary plus collapsible detail payload.

Validation:

- frontend can consume payloads without reading internal stores directly;
- read-only peer-chat UX projection exists on main through #246;
- dispatch queue source refs include queue/proposal/gate/resolution refs through
  #255, with old-schema fallback.
- #257 keeps worklist `source_refs` authority-only and exposes
  `dispatch_evidence` separately; frontend must not treat `mcp_writeback:*` as
  authority.
- #259 makes inspector closure evidence read dispatch ack from
  `chat_dispatch_queue` and lane execution from `acceptance_spines`, with
  explicit source authority refs for both stores.
- #261 makes dispatch authority refs available through lane projection and
  execution context so frontend/API consumers can trace the queue authority
  consumed by a lane without treating the refs as proof of execution.
- #265 exposes the same dispatch queue authority refs directly on
  `dispatch_queue.entries[]` with explicit frontend authority boundary and
  projection-only sidecar continuity metadata; this is still read-only and not
  a full frontend claim.

## Phase 7 - Documentation And Final Report

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
- PR/CI/merge state;
- A2A progress by phase;
- MemoryOS state: skipped, degraded, contract proof, or live proof;
- frontend API changes, if any;
- whether Ray was used in the main path;
- durable blockers and next authority boundary;
- exact forbidden claims not made.

Current final-report notes for the 2026-06-28 pass:

- maximum verified GitHub chain: domain-scoped PRs #244-#273 reached
  exact-head PR CI, guarded merge, and successful main push CI;
- MemoryOS state: opt-in sidecar contract/degraded-mode support only; no live
  MemoryOS authority claim; #255 gives sidecar/context continuity durable
  dispatch gate refs to consume, #257 carries those refs into the execute-peer
  dispatch context/prompt/envelope, and #261 carries the same authority refs
  into saved lane graphs, projected lanes, lane context bundles, normal
  execution prompts, and persistent execute context; #263 records approved
  dispatch handoff continuity into the optional sidecar while treating degraded
  sidecar ingest as non-blocking; #259 still prevents dispatch ack evidence
  from becoming lane execution proof;
- frontend state: read-only API/UX projection only; #251 exposes sanitized
  MemoryOS sidecar support metadata, #255 exposes durable dispatch gate refs,
  and #257 keeps dispatch execution evidence separate from authority
  `source_refs`; #259 separates inspector dispatch ack from lane execution
  closure evidence; #261 makes lane-level dispatch authority refs readable
  without promoting them to execution proof; #265 exposes dispatch queue
  entry-level authority refs, authority boundary, and projection-only sidecar
  continuity on the frontend UX projection; no full frontend claim;
- Ray use: not the default natural groupchat route; remains optional legacy;
  #272 keeps the fullchain docs sentinel peer/review/execute GOD backends
  aligned with the selected `--peer-god-backend`, so native sentinel runs do
  not drift into Ray defaults; the post-#273 default native sentinel confirmed
  the script default path launched `--peer-god-backend native` and reached
  `awaiting_final_action` without using Ray as the main route;
- copilot audit: helper exists for read-only append-only board and advisory
  intake; #257 lets accepted recommendations use `chat_dispatch_queue:*` as
  durable authority while keeping `mcp_writeback:*` candidate-only; #266 lets
  accepted recommendations also use `review_trigger_verdict:*` as durable
  review verdict authority, keeps legacy `chat_dispatch_queue#entry=*`
  candidate-only, and marks intake as advisory; subagent/copilot output is not
  proof truth;
- GitHub server truth: #249 requires complete required check names and
  per-check-run PR head SHA evidence before `server_side_merge_proof` can emit
  `pr_merged`; #268 makes the acceptance-gated short-run lane projection
  consume final-action GitHub gate resolution without becoming authority:
  accepted gates project as `merged`, manual gaps project as
  `blocked_for_input` with `blocked_reason`, and health must not report them as
  live or execution failures; #270 marks the same synthetic short-run lane as
  `integration_mode: noop`, so health does not treat it as an ordinary merged
  feature lane with dependent-release requirements;
- A2A review boundary: #252 records `chat.db/proposal_approval` as the next
  authority after A2A `dispatch_allowed` review verdict writeback; A2A output
  still cannot create dispatch truth directly;
- dispatch boundary: #254 only exposes `chat.db/dispatch_queue` next authority
  when a real queue entry exists; #255 persists A2A/collaboration gate refs on
  the queue for B/C/D read consumers; #257 propagates those refs to
  execute/frontend/copilot consumers without promoting execution evidence;
  #259 keeps dispatch ack/evidence in `chat_dispatch_queue` and actual lane
  execution proof in `acceptance_spines.execution_evidence_refs`; #261 makes
  the dispatch authority refs worker-visible through lane graph/projection and
  execution context while preserving that proof split; #263 copies the same
  dispatch handoff refs into optional MemoryOS sidecar continuity, not into
  lane execution proof; #265 exposes the dispatch refs to frontend consumers as
  projection-only metadata; #266 keeps copilot intake advisory and prevents
  execution evidence refs from becoming accepted authority; #268 records
  acceptance-gate projection refs back to `chat.db`, dispatch queue, review
  verdict, final action, and GitHub gate evidence/gap authority; #270 keeps
  the noop integration marker projection-only and separate from execution or
  merge proof;
- next authority boundary: run the next real natural chain from current main
  and tie any PR/CI/merge state to exact head SHA and GitHub run metadata.
