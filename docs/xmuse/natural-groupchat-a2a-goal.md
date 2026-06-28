# Natural Groupchat A2A Goal

Updated: 2026-06-28

This is the current `/goal` entrypoint for the next xmuse production push. It
supersedes older L8-L11, closure-ledger, walkthrough, and runtime-log driven
planning docs for this goal.

## Source Inputs

Read these first:

- `AGENTS.md`
- `docs/xmuse/README.md`
- `docs/xmuse/natural-groupchat-a2a-behavior.md`
- `docs/xmuse/natural-groupchat-a2a-task-plan.md`
- `docs/xmuse/mainline-contracts.md`
- `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md`
- `/home/iiyatu/clowder-ai` as implementation reference, not as authority

## Latest Calibration

As of this update:

- `origin/main` is calibrated at merge commit
  `8ae7600991371783658829900cda59ecdbed7a57`.
- The latest merged PR is #273 (`docs: record sentinel backend alignment
  merge`),
  merged 2026-06-28 with exact PR head
  `f67d34035d78eeb662b8f927e5a22dcd7328b080`.
- PR #266 (`Clarify copilot intake authority
  boundaries`), merged 2026-06-28 with exact PR head
  `778937c1a26c81b70bb798ea6616cd8fd6fc3911`.
- Current server-side main CI evidence:
  - PR #242 `c1d19ad2ae9bd8b22742376c98968073a508329c`: run
    `28292323481` success.
  - PR #244 `65910e683eb6f8c70ed5428ac77c0e971ff0aa99`: run
    `28307269298` success.
  - PR #245 `328e79a9b153843069146826192dc9ac2cc115d6`: run
    `28308325362` success.
  - PR #246 `176d26272cb118c62ab424053d77bd6a1a44a5a5`: run
    `28309007290` success.
  - PR #247 `a94ebb33c751a02b13e00de06d53a0fd56649405`: run
    `28309375745` success.
  - PR #248 `a752432b73a5d7a6cdd735d9776141f0d2ebc3a1`: run
    `28309677170` success.
  - PR #249 `159b851435b735ac828eca0637b601907c306cef`: run
    `28310645567` success.
  - PR #250 `38306251fa1a820b35ce3ca46e877e9e04f1679c`: run
    `28310900258` success.
  - PR #251 `10d9f89900646e5b364424e01dc931383983084c`: run
    `28311466358` success.
  - PR #252 `e2a2e2742ff452bc8e306fb6efdd525231d22bff`: run
    `28311860691` success.
  - PR #253 `db62fdaa34a3ec87c96553e5c0f45101ea2062d0`: run
    `28311993991` success.
  - PR #254 `b04fcd902296fe78086aa8502f98ee565a4cb545`: run
    `28312435751` success.
  - PR #255 `502f7a6b1e777991ff22c7ea73bdc52373e2a218`: run
    `28313035616` success.
  - PR #257 `9a30aeadd242e4978a84683801c0c65494a66c1c`: run
    `28313722964` success.
  - PR #258 `d78a2df79d7515e1b536052b958f2e1be7983e51`: run
    `28313973331` success.
  - PR #259 `53dbeb9ace749510e9cb0f82f73cbd4df11ec190`: run
    `28314524612` success.
  - PR #260 `7e8d06679715e8eb2f2d78743a5827fa5dbfaa3f`: run
    `28314661776` success.
  - PR #261 `ea0f23b85011cb68429089a8acdc30891d2836c2`: run
    `28315305767` success.
  - PR #262 `3772b07f9f47bca0205dac465af762463b5bdeaa`: run
    `28315629004` success.
  - PR #263 `3fe6d8a853ddeade5548733970445c9ef108f4e1`: run
    `28316064426` success.
  - PR #264 `de51f8faf981b04755ebf1a2bd8fdd6f62a0a993`: run
    `28316229878` success.
  - PR #265 `09b8164866992e9f7df8ac84072f4d9aeb26a602`: run
    `28316510543` success.
  - PR #266 `235f36ea4c5c38b73d23a786903407ee99088f23`: run
    `28316712653` success.
  - PR #267 `df83ea99803e64f97317d854f69c0befa468adf4`: run
    `28316881854` success.
  - PR #268 `76a57362c73f0f63dc2d9b61f871b24a7a5bb329`: run
    `28317369049` success.
  - PR #269 `0b383026b1b250be3fe11a91697d3c6b8102ae55`: run
    `28317521660` success.
  - PR #270 `fa1cc1e1996be3c18540f574c3513b0cafbea642`: run
    `28317667416` success.
  - PR #271 `7c5831d75b6efa59c0ce57aebbae21fdefc68240`: run
    `28317787154` success.
  - PR #272 `c60f12090868a35ca56917feabfd66cee6306809`: run
    `28318839517` success.
  - PR #273 `8ae7600991371783658829900cda59ecdbed7a57`: run
    `28318943411` success.
- Recent domain-scoped progress:
  - #244 advanced the natural peer-callback proposal handoff path.
  - #245 added opt-in MemoryOS sidecar recall/degraded-mode support.
  - #246 added frontend read-only peer-chat UX projection.
  - #247 added read-only goal copilot audit guardrails.
  - #248 refreshed the current goal documentation package.
  - #249 made GitHub server truth require exact PR head check-run evidence
    before merge proof can emit `pr_merged`.
  - #250 refreshed current goal docs against the newer main truth.
  - #251 projected sanitized MemoryOS sidecar support metadata through the
    read-only peer-chat UX projection.
  - #252 made A2A `dispatch_allowed` review verdict writeback name
    `chat.db/proposal_approval` as the next authority boundary, while dropping
    provider-supplied boundary claims.
  - #253 refreshed current goal docs after #252.
  - #254 exposed `chat.db/dispatch_queue` as next authority only when proposal
    approval creates a real durable queue entry.
  - #255 persisted dispatch gate refs for MemoryOS sidecar/context continuity,
    frontend projection, and read-only copilot audit consumers.
  - #257 propagated dispatch authority refs into execute-peer dispatch
    context/prompt/envelope, kept frontend `source_refs` authority-only, and
    made read-only copilot intake accept `chat_dispatch_queue:*` while keeping
    `mcp_writeback:*` execution evidence separate.
  - #258 refreshed current goal docs after #257.
  - #259 separated dispatch acknowledgement/evidence refs from actual lane
    execution evidence in the acceptance spine and inspector closure evidence
    read projection.
  - #260 refreshed current goal docs after #259.
  - #261 propagated approved dispatch authority refs into saved lane graphs,
    projected lanes, lane context bundles, normal execution prompts, and
    persistent execute context, while preserving the #259 proof split.
  - #262 refreshed current goal docs after #261.
  - #263 records approved dispatch handoff continuity into the optional
    MemoryOS sidecar, keeps dispatch refs as sidecar continuity rather than
    execution proof, and continues dispatch when sidecar ingest degrades.
  - #264 refreshed current goal docs after #263.
  - #265 exposes dispatch queue entry-level authority refs, authority boundary,
    and projection-only sidecar continuity through the frontend read-only UX
    projection.
  - #266 makes read-only copilot intake accept `review_trigger_verdict:*` as
    durable review verdict authority, keeps `mcp_writeback:*` and legacy
    `chat_dispatch_queue#entry=*` candidate-only, and adds an explicit advisory
    intake boundary.
  - #267 refreshed current goal docs after the B/C/D completion pass.
  - #268 fixes the acceptance-gated short-run read projection after
    final-action GitHub gate resolution: accepted gates project as `merged`,
    manual gaps project as `blocked_for_input` with `blocked_reason`, and
    durable refs point back to `chat.db`, dispatch queue, review verdict,
    final action, and GitHub gate evidence/gap authority.
  - #269 refreshed current goal docs after #268.
  - #270 marks synthetic acceptance-gated short-run lane projections as
    `integration_mode: noop`, preventing health from reporting ordinary
    dependent-release risk for a projection-only gate lane.
  - #271 refreshed current goal docs after #270.
  - #272 keeps the fullchain docs sentinel peer/review/execute GOD backends
    aligned with the selected `--peer-god-backend`, so native sentinel runs do
    not drift into Ray defaults.
  - #273 refreshed current goal docs after #272 and records its merge/main-CI
    facts.
- The next long goal should start from a clean `origin/main` worktree after
  truth refresh.
- Dirty historical worktrees may be read as references only. They are not main
  capability.
- PR #243 is an older broad docs package and is behind current main. Treat it
  as reference-only unless it is explicitly rebased and revalidated.

## Objective

Make xmuse use its own natural agents groupchat to carry a small real xmuse
change through:

```text
Chat API human demand
-> durable natural groupchat
-> real provider participant
-> proposal or fail-closed blocker
-> structured review verdict
-> approved or blocked state
-> dispatch / execution
-> PR
-> CI observation
-> operator merge or explicit blocker
```

The goal is not to declare production-ready natural groupchat. The goal is to
advance the maximum real chain and leave precise durable blockers where it
cannot advance.

## Architecture Direction

Default route:

```text
natural groupchat
-> official a2a-sdk provider / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / CI / operator merge
```

Do not use Ray as the default natural groupchat kernel. Ray may remain a
legacy compatibility adapter, but it should not consume the main repair budget.

A2A is an interop boundary, not xmuse authority. Every important A2A event must
be normalized into durable xmuse state before proposal, review, dispatch, or
merge gates consume it.

## Clowder-AI Extraction

Borrow only the small primitives that make natural groupchat real:

- layered `SystemPromptBuilder`;
- bounded `ContextAssembler`;
- line-start A2A mention parsing with code-block stripping;
- one invocation/worklist path with dedupe and loop guards;
- per-session mutex;
- delivery/writeback reconciliation before projection;
- remote-agent shape informed by A2A, implemented through official SDK where
  public wire behavior is needed.

Do not copy clowder-ai Redis authority, full UI, broad queue stack, or rich
message system unless xmuse actually needs it.

## Forbidden Claims

Do not claim:

- production-ready natural groupchat;
- live MemoryOS authority;
- fully autonomous merge;
- GitHub review truth;
- provider stdout review truth;
- full multi-provider parity;
- frontend complete;
- Ray-backed production proof.
