# xmuse runtime operation findings

This file tracks product and harness findings from local runtime operation
attempts. It is intentionally conservative: a passing local run is not review
truth, merge truth, live MemoryOS proof, or full closure.

## Current Evidence Summary

- Fake groupchat demos passed in the 2026-06-17 run, but only prove the fake
  GOD layer and writeback trace contract.
- REST + MCP proposal approval reached an isolated `feature_lanes.json`
  projection in the 2026-06-17 run.
- Native `platform_runner --peer-chat` failed before assistant writeback in the
  2026-06-17 run because durable bootstrap GOD sessions could not be reused by
  the live native scheduler. The 2026-06-18 runtime-kernel run produced local
  evidence that compatible bootstrap session metadata can now be migrated for
  OpenCode peer runtime use.
- Real Ray/Codex app-server restart-resume passed twice in the 2026-06-18 run.
- Real Ray/Codex app-server soak was mixed in the 2026-06-18 run: one attempt
  failed because the provider streamed text but did not call MCP
  `chat_post_message`; a second attempt completed eight MCP writeback turns
  across restart/resume.
- Native Codex-to-OpenCode peer handoff succeeded twice in the 2026-06-18
  runtime-kernel run: human only mentioned Codex architect, Codex created a
  durable review mention, and OpenCode replied through durable callback
  writeback.
- Codex architect produced a durable `lane_graph` proposal through
  `chat_emit_proposal` in the 2026-06-18 proposal run. The first run exposed
  that automatic review triggers lacked readable proposal content for OpenCode;
  a follow-up fix made the trigger payload reviewable and OpenCode returned a
  proposal-specific `PASS`.
- Proposal approval while a runner is active can dispatch real provider work
  against the repository worktree unless a safer execution worktree or dry-run
  mode is used.
- The 2026-06-18 Loop 7 repro confirmed that approval with an explicit
  isolated execution worktree projected lanes with `worktree` but no `branch`,
  causing `merge_context_missing` after execution and review. A targeted fix
  now attaches existing detached git worktrees to a lane branch during dispatch.
- Loop 11 showed that a `lane_graph` proposal/resolution containing
  `review_runtime=opencode` lost that field before runner consumption because
  the lane graph model/projection omitted it. Loop 12 reran the real Chat API
  proposal approval path and preserved `review_runtime=opencode` in both the
  lane graph artifact and `feature_lanes.json`.
- Loop 13 then consumed a Chat API approved lane through the platform runner in
  an isolated git worktree and routed `review_runtime=opencode` to a persistent
  OpenCode review peer. The lane stopped at `awaiting_final_action` under
  `--no-auto-merge`.
- After that fix, the same chain moved past `merge_context_missing`, but
  exposed a new review/rework blocker: the second review invocation exited 0
  with empty stdout, leaving the lane at `review_no_verdict`. A follow-up
  review-plane closure fix now records committed MCP rework decisions and
  synthetic `review_failed` verdicts for empty review stdout in focused
  coverage. A real local recheck then completed a small isolated lane through
  `merged` with a `verdict_emitted` review task.
- The positive Loop 7 review-plane recheck also exposed an integration-target
  safety issue: `execution_worktree` isolated the worker edits, but auto-merge
  still advanced the control branch. The local probe commits were removed from
  the control branch after recording evidence.
- A follow-up `--no-auto-merge` runner probe held the accepted lane at
  `awaiting_final_action` with a pending final-action hold and left the control
  branch HEAD unchanged.
- The 2026-06-18 groupchat-to-final-action probe bootstrapped a real
  Codex/OpenCode groupchat, produced a durable architect `lane_graph` proposal,
  received an OpenCode review callback, approved the proposal, executed the
  lane, and stopped at final-action hold. The bounded production gap found and
  imported from that lane was direct `initial_participants` OpenCode support.
- The same probe showed that peer-chat discussion sessions still used the
  control repository worktree, while approved lane execution could use an
  isolated execution worktree. A small follow-up fix now routes peer-chat
  scheduler turns through `xmuse_root/peer_chat_worktree`, with a short real
  durable writeback recheck.
- The 2026-06-18 Loop 5 reliability probe produced one clean local runtime
  Codex-to-OpenCode handoff from human `@architect` mention to architect
  writeback to architect-created `@review` mention to OpenCode callback
  writeback. A first sample from the same run was excluded from clean proof
  because the human prompt itself contained a bare `@review` token and created
  a direct review inbox.
- A follow-up Loop 5 restart/resume and soak probe created a direct
  `initial_participants` groupchat with Codex architect, OpenCode review, and
  Codex execute peers. It completed four clean Codex-to-OpenCode handoffs in
  one durable conversation, including one runner restart between the first and
  second handoff. The durable result was 16 messages, 8 inbox items, and 8
  `mcp_writeback` latency traces with no degraded reason.
- The 2026-06-19 direct OpenCode probe showed that OpenCode can see the xmuse
  project MCP server when the runtime injects `xmuse-platform` into the
  worktree `opencode.json` used by `--dir`, and restores the original config
  afterward. The shim now uses `opencode run --pure --model
  opencode-go/deepseek-v4-flash --variant max ...`.
- The 2026-06-19 fullchain repro found that gate subprocesses inherited the
  platform control-plane `XMUSE_ROOT`, making `test_platform_runner` parser
  cases fail inside the real gate profile. The gate runner now strips inherited
  `XMUSE_ROOT` before applying command env.
- The 2026-06-19 gate-fixed fullchain reached `awaiting_final_action` with
  OpenCode review, then exposed a same-status callback failure when native MCP
  set the lane to `reviewed` before structured review callback processing. The
  persistent review delivery path now updates metadata when the lane is already
  in the target status.
- The 2026-06-19 idempotency rerun drove a real human demand through durable
  Codex/OpenCode groupchat, collaboration, proposal, approval, dispatch,
  execution, gate, OpenCode persistent review, and final-action hold. The lane
  stopped at `awaiting_final_action` under `--no-auto-merge`; this is local
  runtime proof only.

## Findings

### F1. Computer Use plugin unavailable

Severity: environment blocker.

The requested Windows Computer Use path failed during plugin bootstrap with a
package export error in the bundled `@oai/sky` runtime. No Windows UI automation
could be performed.

Impact:

- Visible Windows desktop QA was unavailable.
- Runtime evidence had to come from WSL processes, HTTP, MCP, logs, tests, and
  durable artifacts.

Next direction:

- Repair or update the bundled Computer Use runtime before relying on it for
  visible desktop QA.
- Keep this separate from xmuse product readiness; the failure happened before
  any xmuse process was touched.

### F2. `/mcp/chat` excludes conversation creation by design, but tooling can trip on it

Severity: contract clarity issue.

`chat_create_conversation` is available on `/mcp`, not `/mcp/chat`. Calling it
through `/mcp/chat` returns `tool is not exposed on this MCP endpoint`.

Next direction:

- Document endpoint split in `FRONTEND_API.md` / MCP docs.
- Consider a `tools/list` smoke in the operation runbook that records which
  endpoint owns each chat tool.

### F3. Conversation creation response lacks direct participant-session mapping

Severity: API ergonomics / integration risk.

`chat_create_conversation` returns `bootstrap.durable_god_sessions` as ids and
participants separately, but not a direct `{participant_id, god_session_id}`
mapping for each participant in `structuredContent`.

Impact:

- External test clients had to read `god_sessions.json` to find the architect
  session id.
- That bypasses the public contract and couples test tooling to durable store
  internals.

Next direction:

- Add a public `sessions` or `participant_sessions` field to creation and
  inspect responses.
- Cover it with a contract test so MCP/REST clients do not need to parse
  `god_sessions.json`.

### F4. Response shapes are inconsistent across chat APIs

Severity: API ergonomics / client correctness.

REST message/timeline responses, `chat_post_message`, and
`chat_emit_proposal` do not share one success envelope shape.

Next direction:

- Define a small black-box client contract for create/post/read/write/propose.
- Normalize success envelopes where practical, or publish typed per-endpoint
  response models and examples.

### F5. Native peer scheduler bootstrap session migration

Severity: partially resolved product blocker for local native peer-chat runtime.

The live `platform_runner --peer-chat` claimed the human inbox item but failed
immediately:

```text
Cannot reuse conversation participant '<conversation_id>:<participant_id>':
existing registered session does not match requested role/agent
```

The durable session records created during chat bootstrap have missing runtime
fields. The runner later tries to attach a live native session with runtime
metadata and rejects the existing record shape.

2026-06-18 update:

- A focused regression command passed:
  `uv run pytest tests/xmuse/test_opencode_persistent.py tests/xmuse/test_god_session_layer.py::test_ensure_conversation_session_migrates_bootstrap_record_with_model_only tests/xmuse/test_peer_chat_scheduler.py::test_peer_session_prompt_fingerprint_is_stable_across_inbox_content tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_claims_and_nudges_oldest_item -q`
  with `9 passed in 0.64s`.
- A real external service run created an OpenCode review participant through the
  public Chat API and `platform_runner --peer-chat` migrated the durable GOD
  session to include stable peer runtime metadata.
- The OpenCode review inbox reached `status=read`, produced an assistant
  message, and persisted `delivery_mode=mcp_writeback`.

Remaining gap:

- This is local runtime proof, not server-side or GitHub truth.
- The OpenCode provider-native `sessionID` is still not persisted in
  `god_sessions.json`, so provider memory continuity across shim process
  restarts is not proven.

Next direction:

- Preserve the migration guard and stable peer prompt fingerprint.
- Decide whether provider-native session ids should be persisted for OpenCode
  before claiming long-lived provider memory continuity.

### F6. Health process discovery misses live uv/python service wrappers

Severity: observability bug.

During the 2026-06-17 service run, HTTP health endpoints were serving, while
process discovery still reported missing runner/MCP processes.

Next direction:

- Extend process discovery to recognize both uv wrapper processes and child
  Python commands for `python -m xmuse.mcp_server`, `python -m xmuse.chat_api`,
  and the console-script resolved path.
- Prefer endpoint readiness over process discovery for HTTP services when both
  are available, or mark process evidence as advisory.

### F7. Proposal approval immediately dispatches live work if runner is active

Severity: operator safety / test harness risk.

Approving the proposal while the runner was active projected a lane and
dispatched `actual-fullchain-evidence-docs`. A Codex worker ran, then the lane
ended as:

```text
status=gate_failed
failure_reason=review_non_zero_exit
failure_layer=review
```

Next direction:

- Add an explicit dry-run / no-dispatch mode for proposal approval tests.
- For runtime QA, use a dedicated worktree or `XMUSE_ROOT` plus execution
  worktree override before approving lanes with an active runner.
- Add an operator-visible warning when approval will enqueue dispatchable work
  and a runner writer lease is active.

### F8. Missing gate profile causes post-execution gate ambiguity

Severity: execution contract gap.

The generated test lane had no gate profile. Runner log emitted
`gate_profiles_missing`, but the lane still progressed into review and then
failed with `review_non_zero_exit`.

Next direction:

- Enforce a default gate profile for approved proposal lanes, or fail proposal
  approval before projection.
- Surface missing gate profiles in chat cards and run health as a first-class
  blocker.

### F9. Real Codex app-server tool writeback is not deterministic under soak

Severity: product reliability blocker for treating provider writeback as
closure proof.

In the 2026-06-18 repeated run, the real Ray/Codex app-server restart-resume
test passed twice. The soak test then produced mixed evidence:

- attempt 1 failed on turn 1 with `peer_no_inbox_side_effect`;
- the failed turn had visible stream text: `real ray mcp soak fresh 1 ok`;
- `peer_turn_mcp_tool_traces` was empty;
- no durable assistant message was written;
- attempt 2 completed eight `mcp_writeback` turns across restart/resume.

Impact:

- The path is accessible and can work, but provider compliance with
  `chat_post_message` is not deterministic enough for closure proof.
- Streaming text is not an acceptable substitute for durable MCP writeback
  unless an explicit fallback mode is enabled and classified as degraded.
- Passing soak once must not erase the earlier failed-closed attempt.

Next direction:

- Preserve failed-closed behavior when the provider does not call the MCP
  writeback tool.
- Add a bounded reliability gate for real provider soak that records attempts,
  failure mode, and durable side effects instead of reporting only the last run.
- Investigate whether prompt/tool-choice constraints can force
  `chat_post_message`, or whether the runtime needs a stricter tool-required
  turn mode.

### F10. External clients need participant-session mapping before MCP inbox reads

Severity: API ergonomics / integration risk.

During the 2026-06-18 external service smoke, REST conversation creation and
message posting succeeded, but a direct `chat_read_inbox` call with only
`conversation_id` and `@architect` failed closed:

```text
chat_read_inbox missing required arguments: god_session_id, participant_id
```

The public participants endpoint did provide the required mapping, and MCP
`chat_read_inbox` succeeded after the caller supplied both values.

Impact:

- External clients must perform an additional participant/session discovery
  step before using MCP inbox tools.
- This is workable, but it is easy for ad hoc operators or automated smoke
  scripts to call the wrong shape.

Next direction:

- Document the required discovery step in the service operation runbook.
- Consider a first-class `target_address` helper only if it preserves session
  authority and does not weaken GOD session identity checks.

### F11. OpenCode peer durable callback writeback is locally accessible

Severity: capability unlocked, with proof boundary limits.

The 2026-06-18 runtime-kernel run created a real Chat API conversation with
OpenCode as the review GOD peer and posted a human `@review` message. Native
`platform_runner --peer-chat` invoked OpenCode through the configured peer
launcher and the shim wrote back through MCP `/mcp/chat` using
`chat_post_message`.

Observed durable state:

```text
conversation_id=conv_7a54d4ec0f184edebcbc4e64dd6f981b
inbox_item_id=inbox_56450f7f20a045fe9e9e6c40d5cf433b
assistant_message_id=msg_d3ddc9f7b4e94ad280f3ac80e47249ab
assistant_author=part_79cad55f43ca4398a8e1df1c36e03f69
assistant_content=OPENCODE_REVIEW_READY fresh DEVNULL durable writeback
writeback_path=opencode_callback_bridge
delivery_mode=mcp_writeback
degraded_reason=null
tool_trace=chat_post_message
```

Impact:

- OpenCode is no longer only a bounded worker/profile concept in this branch;
  it can act as a registered native peer for a review inbox in local runtime.
- Provider stdout is still not counted as groupchat truth. The proof is the
  durable assistant message, inbox terminal state, and tool trace.

Next direction:

- Keep OpenCode adapter behavior local to the adapter/shim.
- Persist or explicitly classify provider-native `sessionID` handling before
  claiming durable provider memory continuity.

### F12. Codex-to-OpenCode peer handoff works locally across runner restart

Severity: capability unlocked, reliability still bounded.

The 2026-06-18 handoff run used a fresh isolated runtime root and a human
message that only mentioned `@architect`. Codex architect produced a durable
review mention, the scheduler created a review inbox, and OpenCode review
replied through durable callback writeback.

The sequence succeeded twice in the same conversation, with a runner restart
between runs:

```text
run 1:
human -> @architect
architect inbox -> read
Codex message -> @review Please reply exactly OPENCODE_HANDOFF_READY.
review inbox -> read
OpenCode message -> OPENCODE_HANDOFF_READY

run 2:
human -> @architect
architect inbox -> read
Codex message -> @review Please reply exactly OPENCODE_HANDOFF_READY_TWO.
review inbox -> read
OpenCode message -> OPENCODE_HANDOFF_READY_TWO
```

All four provider turns had `delivery_mode=mcp_writeback` and
`degraded_reason=null`.

Impact:

- This is the first local runtime evidence in this ledger that a durable
  Codex-to-OpenCode peer handoff can complete through the native chat scheduler.
- It is still not proof of full natural groupchat completion, fullchain
  execution, independent review truth, GitHub merge truth, or live MemoryOS.

Next direction:

- Run a bounded multi-turn reliability gate before building downstream demand
  execution on top of this path.
- Then use the real groupchat to create a small durable decision/proposal rather
  than manually constructing downstream artifacts.

### F13. Automatic review trigger payload needed proposal content

Severity: product blocker for proposal review usefulness, locally fixed.

The first 2026-06-18 Loop 6 proposal run proved that Codex architect could
create a durable `lane_graph` proposal through `chat_emit_proposal`, but the
automatic review trigger sent to OpenCode review lacked readable proposal
content.

Observed before fix:

```text
proposal_id=prop_f9229b1926b546349803ca5fd93cac5a
review_inbox=inbox_0af29f72fe114b428d15f8a83ad55223
review payload keys=reviewable_type, source_message_id, trigger_mode
OpenCode reply=no inbox item content was delivered
```

Root cause:

- `_ensure_review_trigger()` created a structurally valid inbox item, but did
  not include `payload.content`.
- The OpenCode peer adapter uses `payload.content` as the natural-language
  request for review turns.

Fix direction applied:

- Build automatic review-trigger payloads from the proposal message envelope and
  source content.
- Preserve structured fields: `reviewable_type`, `source_message_id`, and
  `trigger_mode`.

Observed after fix:

```text
proposal_id=prop_ab84aa38b9614bdaa628b854559359ed
review_inbox=inbox_6ae7f911bf2c4b39b325373d178dbe8a
payload.content includes summary, lane feature_id, lane prompt, references,
  and source proposal message content
OpenCode reply starts with **PASS.**
review delivery_mode=mcp_writeback
review degraded_reason=null
```

Impact:

- The groupchat can now produce a durable proposal and route a readable
  automatic proposal review trigger to OpenCode in local runtime.
- This still stops before approval and dispatch.

Next direction:

- Before approving any proposal with a live runner, add or verify an isolated
  execution worktree / no-dispatch guard so Loop 7 cannot write the control
  worktree.

### F14. Existing execution worktree lacked branch metadata

Severity: Loop 7 product blocker, locally fixed.

When Chat API was configured with an explicit `execution_worktree`, approval
projected a lane with `worktree` only. The runner treated the existing worktree
as initialized and skipped branch/base metadata setup. After execution and a
merge-accepting review, merger failed closed:

```text
merge_failure_reason=merge_context_missing
merge_failure_detail=missing required integration metadata: branch
```

Observed before fix:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-repro-030440/root
execution_worktree=/tmp/xmuse-loop7-exec-2Pe8dh
feature_id=proposal-review-payload-loop7-no-collab
branch missing
status=failed
failure_reason=merge_context_missing
```

Fix direction applied:

- `ensure_lane_worktree()` no longer returns early when a lane has `worktree`
  but lacks `branch` or `base_head_sha`.
- Existing detached git worktrees are attached to a feature-scoped branch with
  `git checkout -B <lane-id>`.
- Existing non-git worktree paths still avoid forced git initialization and
  record `base_head_sha=unknown`.

Observed after fix:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-fixed-032235/root
execution_worktree=/tmp/xmuse-loop7-fixed-exec-6KzR0I
branch=proposal-review-payload-loop7-fixed
base_head_sha=109c4a4eae8b2a0a492fbe8e11d100a0bc76ee98
original merge_context_missing not repeated
```

Remaining gap:

- This is local runtime proof only.
- The fullchain did not complete; it moved to a later review/rework blocker.

### F15. Review/rework loop can end with `review_no_verdict`

Severity: product blocker for fullchain completion, partially mitigated locally.

After the branch metadata fix, the same real chain reached execution and review
without `merge_context_missing`. The first review requested rework. The second
execution exited successfully but left no final candidate diff. The second
review invocation exited 0 with empty stdout, so the runner could not parse the
required verdict:

```text
status=gate_failed
failure_reason=review_no_verdict
failure_layer=review
```

Impact:

- Loop 7 can now pass the branch metadata boundary, but it still cannot claim
  fullchain completion from the earlier failing run.
- A pending ReviewTask with no verdict is no longer acceptable durable state.
- Review stdout/fallback handling and rework-loop candidate preservation still
  need repeated runtime loops before treating this path as reliable.

Fix direction applied locally:

- MCP-committed `rejected` review states now ingest a rework verdict into the
  current review task before the lane is requeued.
- A provider result with exit code 0 and empty stdout now fails closed as
  `review_no_verdict` and records a synthetic review-plane verdict with
  `status=review_failed` instead of leaving the ReviewTask pending.
- Focused validation:
  `uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q`
  passed with `45 passed`.
  `uv run pytest tests/xmuse/test_platform_verdicts_writer.py tests/xmuse/test_platform_orchestrator.py -q`
  passed with `243 passed`.

Runtime recheck:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo
execution_worktree=/tmp/xmuse-loop7-reviewfix-exec-x74XQV
feature_id=proposal-review-payload-loop7-reviewfix
status=merged
review_task.status=verdict_emitted
review_verdict.decision=merge
review_verdict.status=finalized
```

Boundary:

- The positive runtime recheck did not reproduce the empty-stdout
  `review_no_verdict` branch. It proves this small lane can complete with a
  persisted review-plane verdict; it does not prove the empty-stdout failure
  branch is fixed by runtime evidence.

Next direction:

- Run a focused review/rework reliability loop with a task that leaves a
  concrete candidate diff.
- Keep failing closed if review exits 0 without a parseable `Verdict:` line,
  and preserve the boundary as review noncompliance rather than merge failure.
- Investigate why worker fallback reports "MCP unavailable" in child-worker
  turns even though runner MCP is configured.

### F16. Isolated execution worktree does not isolate auto-merge target

Severity: operator safety / PR-scope risk, locally mitigated with no-auto-merge.

The Loop 7 review-plane recheck started Chat API with an explicit
`execution_worktree`:

```text
execution_worktree=/tmp/xmuse-loop7-reviewfix-exec-x74XQV
```

The execution worker correctly made its candidate change on the isolated lane
branch:

```text
branch=proposal-review-payload-loop7-reviewfix
candidate_commit=2f17ee5
```

However, when Review GOD accepted the lane, runner auto-merge also advanced the
control branch with local runtime commits:

```text
f17144a feat(xmuse): merge lane proposal-review-payload-loop7-reviewfix
2f17ee5 feat(xmuse): apply lane proposal-review-payload-loop7-reviewfix
```

The control branch was reset back to:

```text
110dd47b435e44e7b608ac5b880ad4aebcf79ab0
```

Mitigation applied locally:

- Added runner flag `--no-auto-merge`.
- The flag maps to the existing final-action approval path, so merge-accepted
  lanes stop at `awaiting_final_action` instead of auto-merging.
- Focused validation:
  `uv run pytest tests/xmuse/test_platform_runner.py::test_runner_no_auto_merge_enables_final_action_hold tests/xmuse/test_platform_runner.py::test_runner_can_require_final_action_approval tests/xmuse/test_platform_orchestrator.py::test_reviewed_lane_enters_final_action_hold_when_enabled -q`
  passed with `3 passed`.

Runtime recheck:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv
execution_worktree=/tmp/xmuse-loop7-no-auto-merge-exec-GKbThV
feature_id=proposal-review-payload-loop7-no-auto-merge
runner flag=--no-auto-merge
status=awaiting_final_action
review_verdict.status=finalized
final_action_hold.status=pending
control_HEAD=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
```

Impact:

- `execution_worktree` prevents direct worker edits in the control worktree,
  but it does not by itself prevent integration/merge mutations.
- Runtime probes can still inflate the active branch unless auto-merge is
  disabled, redirected to a dedicated integration target, or protected by a
  dry-run/no-merge mode.
- `--no-auto-merge` now provides the minimum explicit guard for runtime probes,
  but final-action resolution still needs a separate operator-reviewed path.

Next direction:

- Use `--no-auto-merge` for runtime probes unless the operator explicitly wants
  local auto-merge.
- Require an explicit integration target worktree/branch before normal
  auto-merge is enabled in broader fullchain runs.
- Surface a visible operator warning when a live runner can merge accepted
  lanes into the current control branch.

### F17. Direct `initial_participants` rejected explicit OpenCode peers

Severity: groupchat production capability gap, locally fixed.

The bootstrap preset path could materialize an OpenCode peer through
`provider_overrides`, but the direct `initial_participants` path still rejected
non-Codex participants before provider identity validation could accept them.
That left two inconsistent ways to create a GOD groupchat:

```text
bootstrap provider_overrides -> review cli_kind=opencode works
direct initial_participants -> cli_kind=opencode rejected
```

Runtime loop:

```text
runtime_root=.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9
conversation_id=conv_d353c349af2e49ea8a19bae9681ccf79
proposal_id=prop_c7663c8297e3469f80ee446d3031d6f1
resolution_id=res_9ca3d1595e0649f4a68cc144aa9ad24b
lane_id=groupchat-opencode-initial-participants
status=awaiting_final_action
```

Durable groupchat evidence:

```text
architect delivery=mcp_writeback with chat_emit_proposal
OpenCode review delivery=mcp_writeback
OpenCode review result=PASS
final_action_hold.status=pending
```

Fix applied:

- `PeerChatService._normalize_participant_spec()` now allows `opencode` when
  `provider_id`, `profile_id`, `cli_kind`, and `model` are all explicit and
  consistent with the role template profile.
- Participant specs now preserve explicit provider/profile metadata when
  building the logical bootstrap team.
- Focused coverage proves a direct OpenCode review participant is created and
  receives a durable GOD session with `runtime=opencode`.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_service.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_peer_provider_parity.py tests/xmuse/test_package_boundaries.py -q
40 passed, 1 warning
```

Boundary:

- This is local runtime and focused test evidence only.
- It does not prove GitHub review truth, merge truth, live MemoryOS, or full
  closure.

### F18. Peer-chat discussion sessions used the control worktree

Severity: runtime isolation boundary, locally fixed for scheduler turns.

The same groupchat-to-final-action probe used a dedicated lane execution
worktree:

```text
lane execution worktree=/tmp/xmuse-groupchat-exec-jUcfwj
branch=codex/groupchat-runtime-loop-20260618-uHnZr9
```

However, peer-chat discussion sessions for Codex architect and OpenCode review
were registered with:

```text
worktree=/home/iiyatu/projects/python/xmuse
```

Impact:

- The observed architect/review groupchat turns did not edit files, so no
  control-worktree mutation occurred in this loop.
- The boundary still matters because a future peer-chat role or prompt bug
  could inspect or mutate the control worktree during deliberation.
- Lane execution isolation and peer-chat deliberation isolation are separate
  concerns.

Fix applied:

- `xmuse-platform-runner` now creates `xmuse_root/peer_chat_worktree` and passes
  it to `PeerChatScheduler`.
- A focused runner test asserts the scheduler worktree is runtime-local and
  exists before the scheduler starts.

Runtime recheck:

```text
runtime_root=.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm
conversation_id=conv_d13f495e58f6461cae004cbd4862d249
request=@architect Reply exactly SCRATCH_PEER_READY
delivery_mode=mcp_writeback
assistant content=SCRATCH_PEER_READY
architect session worktree=.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm/peer_chat_worktree
peer_chat_worktree contained no files after the turn
```

Remaining boundary:

- This fixes the normal peer-chat scheduler path, not every provider invocation
  path.
- `ChatDispatchBridge` still needs separate isolation semantics because it can
  represent approved dispatch work rather than pure discussion.

### F19. Bare role mentions in human prompt text can contaminate handoff proof

Severity: runtime evidence hygiene / prompt-contract risk.

The Loop 5 multi-turn handoff probe intentionally asked Codex architect to hand
off to OpenCode review. In the first sample, the human prompt included a literal
`@review` token while describing the desired target. The Chat API mention
extractor therefore created two paths:

```text
architect_inbox=inbox_320e9e8fbe334919b846f9461127ee5a
direct_human_review_inbox=inbox_f0b16b16851e425b82ee758116d3694f
architect_created_review_inbox=inbox_e45f2e7951a2432ea7d90e9219999813
```

Impact:

- The run still showed durable Codex and OpenCode MCP/callback writebacks, but
  it cannot be counted as a clean Codex-to-OpenCode handoff proof because the
  human message also directly addressed review.
- The evidence boundary is easy to blur during manual runtime testing because
  natural language instructions often quote the same role address they are
  trying to delegate to another peer.

Clean recheck:

```text
conversation_id=conv_0ce81045529f4c47b7afa8b778c633ad
human mentions=["@architect"]
architect_response=ARCHITECT_HANDOFF_TWO_READY
architect_created_review_inbox=inbox_0f2eda2692164360afd5134e690d71f1
review_response=OPENCODE_HANDOFF_TWO_READY
architect_delivery=mcp_writeback
review_delivery=mcp_writeback
```

Next direction:

- For proof runs, avoid bare downstream role tokens in human prompt text unless
  the desired proof is direct multi-mention fanout.
- Prefer structured target fields or quoted non-mention role names when asking
  one peer to delegate to another.
- Consider a future explicit escaping or quoted-role convention so prompts can
  discuss a role without creating a direct inbox item.

### F20. Codex/OpenCode handoff survives one runner restart and short soak

Severity: positive local runtime reliability evidence, not a blocker.

The follow-up Loop 5 reliability probe used a direct `initial_participants`
conversation:

```text
conversation_id=conv_b85095df51a9474b9a8426eb85b6fcc1
architect=codex gpt-5.4
review=opencode opencode-go/deepseek-v4-flash
execute=codex gpt-5.4-mini
```

The runner was stopped after the first handoff and restarted against the same
runtime root before the second handoff. Two additional same-runner handoffs
then exercised a short soak.

Observed:

```text
message_count=16
inbox_count=8
latency_trace_count=8
architect_traces=4 mcp_writeback degraded_reason=None
review_traces=4 mcp_writeback degraded_reason=None
```

Impact:

- The earlier session reuse and scratch-worktree fixes now have stronger local
  runtime evidence.
- The prompt-contamination risk from F19 did not repeat when human messages
  only mentioned `@architect`; all downstream `@review` inboxes were created by
  Codex through `chat_mention`.
- OpenCode was observed through the registered peer runtime command:
  `opencode_persistent --model opencode-go/deepseek-v4-flash --variant max`.

Remaining boundary:

- This is one local restart/resume run plus a short soak, not server-side truth.
- It does not prove demand-to-completion fullchain, GitHub review truth, merge
  truth, live MemoryOS, or full closure.
- The public conversation creation ergonomics still require exact role/profile
  ids: `architect=god`, `review=review`, `execute=worker`.

Next direction:

- Move the next real loop back to fullchain completion: groupchat demand,
  proposal, isolated execution, independent review, final-action hold, main
  Codex audit/import, validation, and small PR.
- Preserve `--no-auto-merge` until the merge target is explicit and GitHub
  server truth is checked.

### F21. Collaboration response target matching was too literal

Severity: blocking for dispatch-gated proposals; fixed locally and retested by
focused tests.

Loop 6 produced collaboration runs with target `@execute`. MCP response
recording used the participant role `execute`, so the service rejected the
response with:

```text
collaboration_target_mismatch: execute
```

Impact:

- The first profile-ergonomics proposal could not satisfy dispatch gating even
  though the execute peer was the intended target.
- This was a contract-shape mismatch between address targets and participant
  roles, not a proof failure by the execute peer.

Fix:

- Collaboration response recording now accepts either the role or the role
  address for a target.
- Dispatch-gate execute confirmation accepts `execute` and `@execute`, but only
  when the response is still a typed `execute_feasibility_verdict` with
  non-empty `evidence_refs`.

Remaining boundary:

- Untyped execute responses and responses without evidence refs remain blocked.
  This is intentional; stdout text or informal approval is not proof.

### F22. Proposal approval can dispatch an isolated worker, but review-plane truth is still not established

Severity: major fullchain blocker.

Loop 6 replacement proposal approval succeeded and dispatched the lane
`groupchat-initial-participants-profile-inference` into an isolated worktree.
The execution worker exited `0` and reported focused tests through stdout
fallback, but the lane ended:

```text
status=gate_failed
failure_layer=review
failure_reason=review_non_zero_exit
```

Observed review-plane issues:

- The review worker result recorded `runtime=codex` even though the lane
  proposal requested OpenCode review runtime.
- The review worker attempted to load a missing superpowers skill path and
  exited non-zero.
- No parseable review verdict was recorded in `review_plane.json`.

Impact:

- The run proves dispatch and execution-worker invocation, not review truth.
- Worker stdout fallback is still only candidate evidence.
- The final-action path must remain held until review worker selection,
  instruction hygiene, and verdict recording are made reliable.

Next direction:

- Fix review worker runtime/profile selection or explicitly document the
  authority that chooses Codex review.
- Ensure review worker prompts cannot be derailed by unavailable superpowers
  skill paths.
- Require a durable review verdict before any final-action or PR claim.

### F23. Direct OpenCode profile inference worked at participant level but initially misreported session profile

Severity: user-facing read-model mismatch; fixed locally and retested in Loop 8.

Loop 7 created a real conversation through REST with an OpenCode `review`
participant and omitted `profile_id`. The participant payload correctly
inferred:

```text
provider_id=opencode
profile_id=review
runtime=opencode
```

However, the public session summary showed `profile_id=default` for the same
OpenCode session. The peer still replied through durable MCP writeback, so this
was a metadata/read-model mismatch rather than a delivery failure.

Fix:

- Session summaries now prefer participant authority for provider/profile
  metadata when the session is bound to a participant.

Loop 8 retest:

```text
participant_profile_id=review
session_profile_id=review
session_runtime=opencode
reply=OPENCODE_PROFILE_SESSION_RETEST_READY
delivery_mode=mcp_writeback
degraded_reason=None
```

### F24. Direct OpenCode participant ergonomics now have local runtime proof

Severity: positive local runtime evidence, not fullchain completion.

Loop 8 verified the practical entrypoint needed for natural GOD groupchat:

- REST `initial_participants` can omit `profile_id` for an OpenCode `review`
  peer.
- The service infers the profile from role.
- The public participant and session payloads both show
  `provider_id=opencode`, `profile_id=review`, `runtime=opencode`.
- A human `@review` mention produced an OpenCode assistant reply through
  durable MCP writeback.

Observed durable evidence:

```text
conversation_id=conv_e07a3ef95b8f45478b49516f90ebcdd7
inbox=inbox_42a360b11f594f0a9942966417bf42b0
assistant_message=msg_014d38ea077848f48a74bd9440dec346
delivery_mode=mcp_writeback
degraded_reason=None
total_latency_ms=5325
```

Remaining boundary:

- This proves one direct OpenCode peer turn after profile inference.
- It does not prove demand-to-completion, review truth, merge truth, live
  MemoryOS, GitHub truth, full L8-L10 closure, or full L1-L11 closure.

### F25. `review_runtime=opencode` needed required peer routing and artifact-text parsing

Severity: major review-plane blocker; fixed locally and retested.

Loop 9 prepared a gated lane with `review_runtime=opencode` and an active
OpenCode `review` participant in the same conversation.

Observed:

```text
review_peer_id=part_42f137b236a24368a37ad0107f6bc207
review_runtime_requested=opencode
god_session_runtime=opencode
peer_delivery_mode=required_peer_failed
peer_degraded_reason=review_peer_no_verdict
```

This proved the route could target OpenCode and avoid one-shot Codex, but the
result was not accepted because persistent review delivery only checked
`review_verdict` artifacts and `message.message`. The OpenCode persistent path
can carry usable review text in artifacts such as `stdout`.

Fix:

- `PersistentCliPeerService` now supports OpenCode participants.
- A lane with `review_runtime=opencode` routes to the unique active OpenCode
  `review` participant in the same conversation when persistent review is
  available.
- Missing or ambiguous OpenCode review peers fail closed as required peer
  failures instead of silently falling back to one-shot Codex.
- Persistent review delivery can infer review text from artifact fields
  (`reply_text`, `message`, `result`, `stdout`) when no structured
  `review_verdict` artifact is present.

### F26. OpenCode persistent review can now produce a durable local verdict

Severity: positive local runtime evidence, not GitHub review truth.

Loop 10 reran the same shape with native persistent review backend:

```text
conversation_id=conv_bf447c5ade4043f2925f7d4900202d39
review_peer_id=part_06825251e025479a8075ce0d38074ec6
review_runtime_requested=opencode
```

Observed terminal state:

```text
status=awaiting_final_action
peer_delivery_mode=configured_peer
peer_routing_mode=required
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_fallback_reason=verdict_merge
```

Impact:

- An explicit OpenCode review runtime can now be honored by the review plane
  when an OpenCode review peer exists.
- The result advances only to final-action hold under `--no-auto-merge`.
- This reduces the earlier F22 blocker from "review runtime ignored / no
  durable verdict" to remaining fullchain integration work.

Remaining boundary:

- The loop was a review-runtime probe lane, not a real implementation diff.
- It is local runtime review evidence, not GitHub review truth or merge truth.
- It does not prove demand-to-completion, live MemoryOS, full L8-L10 closure,
  or full L1-L11 closure.

### F27. `review_runtime` proposal intent was dropped before projection

Severity: resolved local projection contract blocker; not fullchain proof.

Loop 11 created and approved a real Chat API `lane_graph` proposal whose
content and resolution included:

```text
review_runtime=opencode
```

Observed failure:

```text
runtime_root=.goal-runs/2026-06-18/loop-11-review-runtime-projection-1xixbI
conversation_id=conv_73bc6d581b6b477b9e6e54fe7530e3af
proposal_id=prop_4c59b2e75ec540f0812ea48d77e053c7
resolution_id=res_235207bb14184a6a92e2b67a8819ac22
lane_graph_review_runtime=missing
projected_review_runtime=missing
```

Root cause:

- `LaneNode` did not model `review_runtime`.
- Projection therefore could not carry the field to the runner queue.

Fix:

- `LaneNode` now has optional `review_runtime`.
- `_lane_payload()` preserves it when present.
- Focused coverage asserts proposal approval preserves
  `review_runtime=opencode` in the projection.

Loop 12 rerun:

```text
runtime_root=.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM
conversation_id=conv_50d2e89e91de4b13ae0ca9348b68bc16
proposal_id=prop_49a2988fab5c49c68874c80239ecf373
resolution_id=res_71b01fb4e5fc44e39affc463b70810a0
lane_id=loop12-review-runtime-opencode
lane_graph_review_runtime=opencode
projected_review_runtime=opencode
```

Impact:

- Groupchat-approved lane intent can now reach the runner projection with the
  OpenCode review-runtime selector intact.
- This connects the proposal path to the Loop 9-10 review-runtime routing work.

Remaining boundary:

- Loop 12 intentionally did not start the runner, so it proves projection only.
- It is not review execution proof, GitHub review truth, merge truth, live
  MemoryOS proof, full L8-L10 closure, or full L1-L11 closure.

### F28. Proposal-created lane can reach persistent OpenCode review and final hold

Severity: positive local runtime evidence; still not GitHub review or merge
truth.

Loop 13 used the same `review_runtime=opencode` path from a Chat API approved
`lane_graph` proposal, but let the platform runner consume the lane.

Runtime setup:

```text
runtime_root=.goal-runs/2026-06-18/loop-13-proposal-runner-opencode-review-WO3US9
execution_worktree=/tmp/xmuse-loop13-exec-TFCuyC
conversation_id=conv_721071eda8f84766b8685e08e631e94e
proposal_id=prop_ad663efb57f248e88f9b717c2df7f9bd
resolution_id=res_95fa16cb619542aa93c6c7b5ddc69f93
lane_id=loop13-review-runtime-preservation-worker
```

Observed runner terminal state:

```text
status=awaiting_final_action
review_runtime_requested=opencode
review_peer_id=part_ec729eefb8bd42139a1831ee17c570bc
peer_delivery_mode=configured_peer
peer_routing_mode=required
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_fallback_reason=verdict_merge
final_action_hold_id=final-f3f9df2ac3c8
```

Impact:

- A proposal-created lane can carry OpenCode review intent into runner review.
- The runner used an isolated git worktree for the execution candidate.
- `--no-auto-merge` correctly stopped the accepted lane at pending final-action
  hold instead of mutating the control branch.
- The OpenCode persistent review path produced a finalized local verdict.

Main Codex audit/import:

- Worker output and OpenCode review were treated as candidate evidence.
- The control worktree imported only the audited minimal additions:
  `review_runtime` field classification, lane graph artifact assertion, and
  classification coverage.

Remaining boundary:

- This was still an operator-created proposal, not a fully natural multi-turn
  Codex/OpenCode discussion generating the proposal unaided.
- The final action hold was not resolved or merged.
- No GitHub PR, GitHub review, GitHub mergeability, live MemoryOS, full L8-L10
  closure, or full L1-L11 closure was proven.

### F29. Ray/default peer-chat can stream text without durable proposal truth

Severity: open runtime blocker for the Ray/default groupchat path; bypassed by
native backend for the current loop.

Loop 14 ran a natural `@architect` demand against the Ray/default peer-chat
path with `XMUSE_RAY_GOD_MCP=0`.

Observed:

```text
runtime_root=.goal-runs/2026-06-18/loop-14-natural-groupchat-schema-proposal-85SfoR
conversation_id=conv_04719fb339f84ee5a746cf380c8326ff
inbox_status=failed
failure_reason=peer_no_inbox_side_effect
proposals_count=0
peer_turn_mcp_tool_traces=[]
```

Impact:

- Streamed or logged provider text was not counted as groupchat truth.
- No durable proposal existed.
- The current maximum-accessible path for the fullchain is the native peer
  backend, not Ray/default.

Remaining boundary:

- Ray/app-server MCP tool exposure remains a separate backlog item.
- This does not block the native Codex/OpenCode fullchain loop.

### F30. Configured OpenCode review peer reused the unscoped peer-chat session

Severity: resolved local runtime blocker for native configured OpenCode review.

Loop 15 proved the natural native groupchat path could produce a durable
proposal and durable OpenCode groupchat review, then failed when the runner
tried to use the same OpenCode review participant for lane review.

Observed Loop 15 failure:

```text
runtime_root=.goal-runs/2026-06-18/loop-15-native-natural-groupchat-schema-proposal-pI4XH1
conversation_id=conv_990194f51ed54237ad65e350ed699899
proposal_id=prop_550cd2f16f284a619724c097b5f7f3d2
resolution_id=res_c1b213dd734544b39a41c84b1300d9c3
lane_id=loop15-chat-emit-proposal-review-runtime-schema
status=gate_failed
failure_reason=required_review_peer_unavailable
peer_degraded_reason=ensure_failed
review_peer_id=part_a86ccb1e8cb34e88be3db1fc433d8699
```

Loop 16 refined the cause: even after exact feature-scope lookup support was
added, proposal-created lanes lacked `feature_scope_id` /
`feature_plan_feature_id`, so configured review still had no distinct session
scope and failed closed.

Fix:

- `GodSessionRegistry.find_by_conversation_participant()` can select an exact
  `feature_scope_id`.
- `GodSessionLayer` creates distinct session identities for scoped sessions.
- configured review peers use the lane feature scope when present, otherwise a
  stable `configured-review:<lane_id>` request scope.

Impact:

- A groupchat OpenCode peer can remain in its unscoped `peer_chat_worktree`
  session.
- A lane review for the same participant can use a separate request-scoped
  OpenCode persistent session.
- Required OpenCode review still fails closed when no OpenCode review
  participant exists.

### F31. Natural Codex/OpenCode groupchat can drive a small lane to local final hold

Severity: positive local runtime evidence; still not GitHub truth or full
closure.

Loop 17 reran the real path with an explicit OpenCode review participant:

```text
runtime_root=.goal-runs/2026-06-18/loop-17-native-opencode-review-request-scope-Rr4mN8
conversation_id=conv_5cb1dcf802ea4f59adec3e7271946c19
proposal_id=prop_27d04454dc264b14bc19fb5281901ce2
resolution_id=res_db428c1219b64168abe15d82ab8f1e6a
lane_id=loop17-opencode-chat-emit-proposal-review-runtime-schema
```

Observed durable groupchat evidence:

```text
Codex architect tools: chat_read_inbox, chat_post_message, chat_emit_proposal
OpenCode review tools: chat_post_message
delivery_mode=mcp_writeback
chat_streams=[]
```

Observed runner/review state:

```text
status=awaiting_final_action
review_runtime_requested=opencode
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
final_action_hold_id=final-3c6fadddda94
```

Impact:

- A real human demand in GOD groupchat produced a durable proposal through
  Codex MCP tools.
- OpenCode participated as a registered review peer in the groupchat.
- Human approval projected the lane to the runner.
- The runner executed the candidate in an isolated worktree.
- Configured OpenCode persistent review passed.
- `--no-auto-merge` held the lane at pending final action instead of mutating
  the control branch.
- Main Codex imported only the audited minimal candidate change:
  explicit `review_runtime` in MCP schema and a focused schema assertion.

Remaining boundary:

- Loop 17 is local runtime proof only.
- The OpenCode persistent review text reported MCP unavailable inside that CLI
  session and used stdout output; this is accepted only as local persistent
  review evidence, not groupchat truth or GitHub review truth.
- The final action hold remains unresolved.
- No GitHub PR, GitHub review, GitHub mergeability, live MemoryOS, full L8-L10
  closure, full L1-L11 closure, or overnight readiness was proven.

Additional manual gap:

- `docs/xmuse/production-closure-gap-ledger.md` is still absent in the current
  worktree and should be treated as missing evidence, not fabricated truth.

### F32. OpenCode reads project MCP config from the worktree passed to `--dir`

Severity: resolved local provider-command blocker for OpenCode MCP exposure.

The 2026-06-19 direct probe showed that OpenCode did not reliably expose the
xmuse MCP server unless the MCP config existed in the worktree used by `--dir`.
Global or caller-cwd config was not a safe authority for a persistent provider
shim.

Fix:

- run OpenCode with `--pure`;
- temporarily write a runtime `opencode.json` into the requested worktree;
- preserve project schema/model/provider config where present;
- inject `mcp.xmuse-platform` with the local `/sse` URL;
- force permission to `allow` for the bounded runtime invocation;
- restore or delete the temporary config after the run.

Impact:

- OpenCode can call xmuse MCP tools as a registered provider path in local
  runtime.
- The repository's original `opencode.json` is not left mutated by the shim.

Remaining boundary:

- This proves local provider-command MCP exposure only. It is not GitHub truth
  or review truth.
- Fullchain artifacts record durable MCP traces, but raw OpenCode provider
  event streams are still not persisted as first-class review artifacts.

### F33. Gate subprocesses must not inherit platform `XMUSE_ROOT`

Severity: resolved local gate blocker.

Loop 25z31 reached real dispatch and execution, then failed inside the real
gate profile because command subprocesses inherited the platform control-plane
`XMUSE_ROOT`. That made tests which intentionally pass their own
`--xmuse-root` read the wrong runtime root.

Fix:

- copy the process environment for gate commands;
- remove inherited `XMUSE_ROOT`;
- apply only the command-specific environment afterward.

Impact:

- Loop 25z33 gate passed both blocking profiles:
  `strict-product` and `xmuse-core`.
- Gate commands still receive explicit command env such as MemoryOS safety
  variables.

Remaining boundary:

- Local gate pass is not GitHub CI truth.
- The gate profile still warns when `gate_profiles.json` is missing in
  `XMUSE_ROOT` and falls back to the lane worktree profile.

### F34. Persistent review callback must be idempotent after native MCP writes

Severity: resolved local review-delivery blocker.

Loop 25z32 reached final-action hold with OpenCode review, but runner logs
recorded:

```text
InvalidTransitionError: cannot transition <lane> from reviewed to reviewed
```

Root cause:

- OpenCode used native MCP `update_lane_status` first, moving the lane to
  `reviewed`.
- Callback delivery later parsed the structured review verdict and attempted
  the same transition again.

Fix:

- if the lane is already in the target review status, update review metadata
  instead of asking the state machine for another same-status transition.

Impact:

- Loop 25z33 recorded review history from MCP, persistent callback, and
  structured verdict without the same-status exception.
- The lane stopped at `awaiting_final_action` with a pending hold under
  `--no-auto-merge`.

Remaining boundary:

- The fix is local runtime proof. It does not prove GitHub review, merge,
  branch protection, or production readiness.
- Ctrl-C shutdown after final-action hold still produced Ray atexit noise; this
  is a cleanup concern, not evidence of lane failure.

## Recommended Next Implementation Order

1. Move back to fullchain completion with the current Codex/OpenCode groupchat
   path: durable demand decision, isolated execution, independent review,
   final-action hold, main Codex audit/import, validation, then small PR.
2. Add explicit escaping or structured target handling for proof prompts that
   discuss downstream role names.
3. Add a review/rework reliability loop for Loop 7 after branch metadata setup.
4. Add dry-run/no-dispatch/no-merge controls for proposal approval and runtime
   probes while a runner is live.
5. Add an explicit integration target guard before auto-merge can mutate the
   control branch.
6. Fix health process discovery so readiness aligns with actual service PIDs
   and endpoint status.
7. Add a public participant-session mapping to conversation creation/inspection.
8. Normalize or document black-box response envelopes for chat write/proposal
   APIs.
9. Add default gate profile handling for proposal-created lanes.
10. Add a reliability gate for real app-server soak so mixed pass/fail evidence
   is preserved instead of collapsed into the latest result.
11. Keep Ray/app-server and soak tests separate from closure claims until a real
   candidate/review/handoff producer-consumer path feeds `closure_spine`.

## 2026-06-18 Repeated Run Notes

Repeated max-accessible testing produced the following local evidence:

- `tests/xmuse/test_minimal_closure_spine.py` and
  `tests/xmuse/test_package_boundaries.py`: `25 passed in 3.44s`.
- local full-chain and fake app-server restart/resume tests:
  `3 passed in 6.90s`.
- fake groupchat demo: three runs passed with `scheduler_happy_path=1`.
- real Ray/Codex app-server restart-resume: two runs passed, both with
  `provider_session_reused=true`, `delivery_mode=mcp_writeback`, and no stdout
  fallback.
- real Ray/Codex app-server soak: first run failed with
  `peer_no_inbox_side_effect`; second run passed eight `mcp_writeback` turns.
- external Chat API + MCP service smoke: health, REST conversation creation,
  REST human mention, public participant/session discovery, and MCP
  `chat_read_inbox` succeeded in an isolated runtime root.

This evidence does not resolve the 2026-06-17 native peer scheduler failure,
does not connect runtime delivery to `closure_spine`, and does not prove
Computer Use, live MemoryOS, natural peer-GOD groupchat, GitHub review truth,
merge truth, release readiness, full L8-L10 closure, or full L1-L11 closure.

Additional 2026-06-18 runtime-kernel evidence:

- OpenCode peer durable callback writeback succeeded once through the native
  peer scheduler.
- Codex-to-OpenCode handoff succeeded twice across runner restart/resume in a
  fresh isolated runtime root.
- Codex architect emitted a durable no-dispatch `lane_graph` proposal through
  `chat_emit_proposal`; after a payload fix, automatic OpenCode review received
  readable proposal content and returned a proposal-specific `PASS`.
- The proof level is local runtime proof only.
- The current evidence still does not prove isolated fullchain execution,
  independent review passed, GitHub truth, live MemoryOS, or full closure.

### F79. Human leading route mentions should not widen the queue from body references

Severity: resolved routing ergonomics issue.

Loop 25z37 reproduced the problem with the real Chat API and durable
`chat.db` state. The human message started with `@architect`, but later
referred to `@execute` and `@review` in the requirement text. The stored
message and inbox queue showed:

```text
message_mentions=["@architect","@execute","@review"]
inbox_targets=["architect","execute","review"]
```

Impact:

- A human could intend an architect-led turn while accidentally scheduling
  execute and review peers immediately.
- This made natural groupchat prompts noisy when they discussed role names.

Fix:

- Human messages now treat one or more leading mentions as an explicit routing
  header.
- Later mentions in the same human message body do not create additional inbox
  items when a leading routing header exists.
- Messages that do not start with a mention keep the previous body-mention
  routing behavior.

Rerun evidence:

```text
Loop 25z37b
message_mentions=["@architect"]
inbox_targets=["architect"]
```

Proof boundary:

- This is local runtime routing evidence only.
- It does not prove provider peer reply truth, full groupchat completion,
  GitHub review truth, merge truth, live MemoryOS, full L8-L10 closure, full
  L1-L11 closure, or production-ready groupchat.
