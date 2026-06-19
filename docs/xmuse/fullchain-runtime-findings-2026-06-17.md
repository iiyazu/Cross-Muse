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
- The 2026-06-19 proposal-readiness rerun kept proposal count at zero while the
  execute collaboration was still running, then emitted exactly one proposal
  after the collaboration reached `done`, approved it, dispatched it, and again
  stopped at `awaiting_final_action` under `--no-auto-merge`.
- Loop 25z40 moved to a real code-change demand and failed closed because the
  peer-chat provider worktree was an empty directory. Loop 25z40b reran after
  making the peer-chat worktree repo-backed, produced a real isolated candidate
  diff, passed gate, received OpenCode review decision `merge`, and stopped at
  `awaiting_final_action` under `--no-auto-merge`.
- PR #81 normalized groupchat-produced review aliases such as
  `human_final_hold`, `final_hold`, and `review-god` to the active OpenCode
  review runtime when exactly one OpenCode review peer is present. GitHub
  server state merged it as `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8` after
  successful branch and post-merge main CI.
- Loop 25z46 then exposed a narrower real boundary: explicit
  `review_runtime=OpenCode` casing still bypassed the lowercase runtime id and
  degraded persistent review to one-shot fallback.
- Loop 25z48 reran after the casing fix and reached a docs-only local
  fullchain final-action hold with `review_runtime=opencode`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`, gate
  pass, and OpenCode review decision `merge`.
- PR #82 merged the explicit `OpenCode` casing fix as
  `94218b269e4a005049e18378ebdc179c1dcada28` after successful PR and
  post-merge main `xmuse CI`.
- Loop 25z49 then drove a real post-PR82 code-change demand through durable
  groupchat, execute feasibility, proposal, OpenCode proposal review, human
  approval, isolated execution, xmuse-core gate, persistent OpenCode review,
  and final-action hold. The candidate exposed `participant_sessions` in
  conversation create/bootstrap responses.
- PR #83 merged the participant session mapping API change as
  `6c962708071895e94458ff947eaed8753c789ce0` after successful PR checks and
  successful post-merge main `xmuse CI`.
- Loop 25z50 exposed a peer-chat delivery-classification defect: a Codex
  architect had already performed durable MCP `chat_post_message`, but the
  scheduler recorded the turn as `delivery_mode=failed` because the provider
  returned `codex_exit_1` afterward. A local fix now makes durable writeback
  authority win while preserving provider failure as `*_after_writeback`.
- Loop 25z51 exposed peer-chat scheduler head-of-line blocking: platform
  runner `concurrency=4` did not help because `tick_once()` awaited one
  provider turn before claiming more inbox work. A local fix now adds
  `tick_many(max_concurrent=...)` and passes runner concurrency into the
  peer-chat scheduler.
- Loop 25z52 reran the three-conversation probe after the scheduler fix. The
  initial three architect inbox items were claimed concurrently, all nine
  inbox items reached durable `mcp_writeback`, and no proposals/resolutions
  were emitted. Remaining groupchat gaps include provider result timeout after
  writeback and missing final-summary gating after downstream peer replies.
- Loop 25z53 confirmed the final-summary gap: execute and review replies
  became durable in two conversations, but architect never posted the requested
  final summary after both replies.
- Loop 25z54 added a local peer-reply drain callback but exposed that
  `chat_mention` side effects did not close the current inbox, so scheduler
  progress still depended on provider final-result behavior.
- Loop 25z55 added `chat_mention(reply_to_inbox_item_id=...)` as a real
  handoff writeback and completed two conversations through execute/review
  replies, callback, and final summary. It still waited for
  `peer_response_timeout_after_writeback`.
- Loop 25z56 proved immediate early release after durable writeback improves
  throughput but can cut off consecutive handoffs in the same provider turn.
- Loop 25z57 added a short post-writeback grace window and completed the same
  two-conversation path with `early_writeback_traces` and zero
  `timeout_after_writeback_traces`, proposals, or resolutions.

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

### F80. Leading-route fix survives a real groupchat-to-final-action rerun

Severity: resolved local fullchain routing issue with remaining ergonomics gaps.

Loop 25z38 reran the full groupchat-to-lane path on the leading mention routing
fix. The human demand intentionally mentioned `@execute` and `@review` in the
body, while starting with `@architect`.

Initial durable routing:

```text
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
```

Observed chain:

```text
human @architect demand
-> architect durable MCP writeback
-> architect-created @execute handoff
-> execute durable MCP writeback and collaboration response
-> architect callback writeback
-> lane_graph proposal
-> human approval
-> execute dispatch
-> child Codex MCP query_knowledge/update_lane_status
-> strict-product package-boundary gate
-> configured OpenCode persistent review
-> awaiting_final_action under --no-auto-merge
```

Lane result:

```text
lane_id=loop25z38_routing_fix_fullchain
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
final_action_hold_id=final-c6021aa4fe11
```

Positive impact:

- The routing fix did not break the existing real groupchat-to-lane path.
- Body references to `@execute` and `@review` no longer created direct human
  inbox items.
- Execute, review, and dispatch turns still entered through durable system
  handoffs.

Remaining gaps:

- Loop 25z39 adds a readiness guard for proposals that reference a
  collaboration run and reruns the chain without the duplicate proposal. Keep
  watching for duplicate proposals that do not carry a collaboration reference.
- Gate profile resolution still warned that `gate_profiles.json` was missing in
  `XMUSE_ROOT` and used the lane worktree config.
- The proof remains local runtime proof. It is not GitHub review truth, merge
  truth, live MemoryOS, full closure, or production readiness.

### F81. Collaboration-backed proposals must wait for collaboration readiness

Severity: resolved local proposal-authority issue.

Loop 25z38 showed that an architect could emit a `lane_graph` proposal
referencing a collaboration run while the execute collaboration was still in
progress, then emit another proposal after the collaboration callback. That
left one open duplicate proposal and one accepted proposal for the same
operator demand.

Fix:

- `chat_emit_proposal` now inspects `collaboration:<run_id>` references before
  writing the proposal.
- A referenced collaboration run must belong to the same conversation.
- A referenced collaboration run must be `done`; otherwise proposal emission
  fails with `collaboration_run_not_ready`.
- The guard is enforced before review triggers are enqueued, so a not-ready
  collaboration reference cannot create review work.

Rerun evidence:

```text
Loop 25z39
collaboration_run=collab_a0265a7420db4d9b9d87596843e54e0f
running_window_proposals=0
saw_running_without_proposal=true
collaboration_status=done
proposal_after_done=prop_3997229437eb4e84b32996813dea49c8
proposal_count_after_done=1
lane_id=loop25z39_proposal_ready_guard
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
final_action_hold_id=final-aa3d2b8ca9a7
```

Positive impact:

- The proposal authority no longer accepts collaboration-backed proposals
  before the referenced producer has finished.
- The automatic review trigger is only created after the collaboration-backed
  proposal is admissible.
- The real groupchat-to-lane path still reaches final-action hold under
  `--no-auto-merge`.

Remaining gaps:

- The guard only covers proposals that explicitly reference
  `collaboration:<run_id>`.
- Gate profile resolution still falls back from `XMUSE_ROOT` to the lane
  worktree config.
- This is local runtime proof, not GitHub review truth, merge truth, live
  MemoryOS proof, full closure, production-ready groupchat, or overnight
  readiness.

### F82. Peer-chat peers need repo-backed worktrees for real code-change demands

Severity: resolved local groupchat execution-readiness blocker.

Loop 25z40 asked the real groupchat to produce a small code-change lane. The
human message routed only to architect, architect handed off to execute, and a
single collaboration-backed proposal was produced. Dispatch approval failed
closed:

```text
approval_error.code=dispatch_gate_blocked
approval_error.message=blocked_execute_not_confirmed
peer_chat_worktree_entries=[]
execute_response.status=failed
execute_response.content.type=execute_feasibility_blocker
```

Root cause:

- `platform_runner --peer-chat` gave peer providers
  `xmuse_root/peer_chat_worktree`.
- That path was created as an empty directory.
- For discussion-only chains, this was enough to avoid mutating the control
  worktree.
- For real code-change demands, execute peers could not inspect repository
  files and correctly refused feasibility.

Fix:

- The peer-chat runtime worktree is now created as a detached git worktree from
  the current repository HEAD when possible.
- Existing non-empty non-git directories are preserved and only warned about.
- If git worktree creation fails, the old empty-directory fallback remains
  explicit through runner logs.

Rerun evidence:

```text
Loop 25z40b
peer_chat_worktree git rev-parse --is-inside-work-tree -> true
src/xmuse_core/platform/execution/gate.py -> present
collaboration_run=collab_a9832c489d72425f8d5064c1bc852a57
proposal_id=prop_1f67619ee1a245969278e8f8ad2d8b2c
resolution_id=res_f1b257fda82a4712ac45e15b8c9af7b1
lane_id=loop25z40_gate_profile_source
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_decision=merge
final_action_hold_id=final-bab763cf5987
```

Positive impact:

- Peer chat can now discuss and inspect real repository files without using the
  mutable control worktree as the provider cwd.
- The dispatch gate continued to fail closed before the fix and allowed
  approval only after execute feasibility was recorded.
- The chain produced a real isolated candidate diff, not just a no-op pytest
  lane.

Remaining gaps:

- This proves one local runtime code-change lane only.
- The peer-chat worktree is detached from HEAD and does not include uncommitted
  local control-branch edits.
- This is not GitHub review truth, merge truth, live MemoryOS proof, full
  closure, production-ready groupchat, or overnight readiness.

### F83. Gate reports should identify gate profile source

Severity: resolved local evidence-quality gap.

Repeated runtime runs used `xmuse/gate_profiles.json` from the lane worktree
when `XMUSE_ROOT/gate_profiles.json` was absent. The warning was visible, but
runtime audits had to infer the selected authority path from text.

Fix:

- Gate reports now include `gate_profiles_source`.
- Values identify `source` as `xmuse_root`, `lane_worktree_fallback`, or
  `missing`.
- Reports also include the selected path plus both candidate paths.

Rerun/import evidence:

```text
Loop 25z40b worker candidate changed:
src/xmuse_core/platform/execution/gate.py
tests/xmuse/test_platform_orchestrator.py

Main Codex audited and imported the minimal candidate diff.
Focused validation: 23 passed.
```

Remaining gaps:

- This makes the fallback explicit; it does not remove the fallback.
- Server-side CI for this branch is not yet claimed until a PR branch is
  pushed and checks run.

### F84. Durable peer writebacks should promote session health

Severity: resolved local peer-chat observability blocker.

Loop 25z41 reached a real code-change lane with explicit OpenCode persistent
review and durable callback writeback, but the peer-chat health view could
still report a peer as `starting` after the peer had authenticated and written
back through MCP.

Evidence:

```text
Loop 25z41
conversation_id=conv_680fdda55ff341abbc34e0ad3c617ba0
execute_collaboration_run=collab_f8ca32b910f64d9a8673b8b4341b149f
execute_response=collab_resp_2cdddaa615284d0e91277a19de256a0b
review_collaboration_response=collab_resp_e53db7d80ff4415780ed665dca2b5982
lane_id=loop25z41_session_health_writeback_status
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
persistent_review_degraded=false
review_decision=merge
final_action_hold_id=final-c93b57b1ffb8
```

Root cause:

- Runtime activity was durable enough to prove a peer writeback happened.
- Session health did not consistently promote durable session status from
  `starting` to `running` when a registered peer wrote back.
- The inspector could also let stale active-session status hide a stronger
  durable status.

Fix:

- `GodSessionRegistry` now exposes a running-status promotion path.
- `PeerChatService` promotes session status after authenticated durable
  writebacks.
- The peer-chat inspector merges durable session status with active runtime
  fields so durable status can improve health without dropping live process
  details.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_dashboard.py -k 'session_health or writeback' -q
-> 6 passed, 32 deselected, 1 warning

uv run pytest tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_mcp_server.py::test_chat_emit_proposal_can_complete_current_peer_inbox_item \
  tests/xmuse/test_mcp_server.py::test_chat_emit_proposal_without_reply_id_closes_single_claimed_inbox_item \
  tests/xmuse/test_mcp_server.py::test_chat_post_message_reply_marks_inbox_read_with_responded_message_id \
  tests/xmuse/test_mcp_server.py::test_chat_record_collaboration_response_promotes_session_status_to_running \
  tests/xmuse/test_package_boundaries.py -q
-> 35 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

GitHub server facts:

```text
PR #78=https://github.com/iiyazu/Cross-Muse/pull/78
head=524c1c961881d4f17851361f920d068d5c652874
state=MERGED
merge_commit=c5818ba433142765c817bc63fed73ec40141ae06
checks_run=27803856684
checks=quality-gates success, contract-smoke-gates success, real-runtime-integration-gate success
main_post_merge_run=27803891559 success
```

Remaining gaps:

- Default review peer selection can still choose Codex unless OpenCode is
  explicitly requested.
- Mention parsing still overmatches forms such as `@architect Coordinate...`.
- This is one real local code-change loop and related server facts, not
  repeated stability proof, live MemoryOS proof, full closure, production-ready
  groupchat, or overnight readiness.

### F85. Leading role mentions must not consume the following sentence verb

Severity: resolved local groupchat routing blocker.

Loop 25z41 showed that a natural human message such as
`@architect Coordinate...` could fail to route. Loop 25z42 reproduced the same
class of failure on current main through the real Chat API.

Prepatch evidence:

```text
Loop 25z42 prepatch
runtime_root=/tmp/xmuse-mention-routing-after-pr79/.goal-runs/2026-06-19/loop-25z42-mention-routing-prepatch-115536
content="@architect Coordinate a tiny routing fix."
message_status=201
mentions=[]
inbox_targets=[]

control_content="@architect, Coordinate a tiny routing fix."
message_status=201
mentions=["@architect"]
inbox_targets=["architect"]
```

Root cause:

- The mention regex allowed `@role` followed by a capitalized word to be read
  as one raw mention.
- Human routing used that raw regex result before participant-aware alias
  resolution.
- Chat API preserves unknown human `@text` as a plain message, so the failure
  mode was fail-open: the message was stored but no durable inbox was created.

Fix:

- `MentionResolver` now resolves leading content with participant-aware alias
  matching.
- Human routing uses the resolver for leading route headers and full-content
  fallback instead of relying on raw regex mentions.
- Overlong raw mentions shrink to the longest resolvable alias, preserving
  multi-word display names and explicit ambiguity behavior.
- Leading `@all` remains a broadcast token.

Postpatch evidence:

```text
Loop 25z42 postpatch
runtime_root=/tmp/xmuse-mention-routing-after-pr79/.goal-runs/2026-06-19/loop-25z42-mention-routing-postpatch-120105
conversation_id=conv_8b0c4ba05f8145a791713448b48ab9c2
content="@architect Coordinate a tiny routing fix."
message_status=201
mentions=["@architect"]
inbox_targets=["architect"]
inbox_ids=["inbox_1e25d11673b5436192e9b7ad7963fb82"]
durable_row=mentions_json='["@architect"]', target_role=architect, status=unread
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_service.py \
  tests/xmuse/test_peer_chat_mentions.py \
  tests/xmuse/test_peer_chat_api.py \
  tests/xmuse/test_peer_chat_end_to_end.py::test_default_group_chat_flow_reaches_god_reply_proposal_and_keeps_roles_isolated \
  tests/xmuse/test_package_boundaries.py -q
-> 50 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Remaining gaps:

- This fixes one natural leading mention failure mode. It is not a multi-turn
  groupchat stability proof.
- Default review peer selection can still choose Codex unless OpenCode is
  explicitly requested.
- Live MemoryOS proof, GitHub review truth, full closure, production-ready
  groupchat, and overnight readiness remain unproven.

### F86. Lane review runtime must resolve the active review peer identity

Severity: resolved approval/projection routing blocker for the observed alias
forms.

Loop 25z43 showed a groupchat-produced lane could carry
`review_runtime="human_final_hold"`, mixing final-action policy with review
provider selection. Loop 25z44 then exposed a second real form:
`review_runtime="review-god"`, matching the active OpenCode review participant's
display name rather than the provider runtime id.

Observed evidence:

```text
Loop 25z44 runtime_root:
/tmp/xmuse-post-pr80-fullchain-121024/.goal-runs/2026-06-19/loop-25z44-review-runtime-authority-123333

conversation_id=conv_4af99a4e53ff49baa3daedc1a380d629
proposal_id=prop_ee0a49da461b438a845fa15ca0edbd42
resolution_id=res_b4848df06b7142ef9128f6acdd36f914
active review participant: display_name=review-god, cli_kind=opencode
feature_lanes.review_runtime=review-god
god_sessions.review.runtime=opencode
god_sessions.review.status=starting
```

Root cause:

- Lane proposal content is natural groupchat output and may name the review
  peer by participant display name or final-hold language.
- Approval projection previously trusted `review_runtime` literally.
- The review runtime field is consumed downstream as a provider/runtime selector,
  so display-name aliases can bypass the intended OpenCode review path.

Fix:

- During lane_graph approval projection, if the conversation has exactly one
  active OpenCode review participant, normalize observed non-runtime values to
  `opencode`.
- Accepted aliases are the final-hold placeholders
  `human_final_hold`/`final_hold`, the review participant role, and the review
  participant display name, with optional leading `@`.
- Explicit valid `opencode` remains preserved.
- Missing `review_runtime` is not rewritten in this slice.

Post-fix evidence:

```text
Loop 25z45 runtime_root:
/tmp/xmuse-post-pr80-fullchain-121024/.goal-runs/2026-06-19/loop-25z45-review-runtime-projection-smoke-124901

POST /api/chat/conversations -> review participant display_name=review-god,
cli_kind=opencode
POST /api/chat/conversations/{conversation_id}/proposals ->
lane review_runtime=review-god
POST /api/chat/proposals/{proposal_id}/approve -> 200
approval response review_runtime=opencode
feature_lanes.review_runtime=opencode
```

Validation:

```text
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_uses_opencode_review_peer_for_final_hold_runtime \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_uses_opencode_review_peer_display_name_runtime \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_preserves_review_runtime_in_projection \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_routes_to_existing_review_peer \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_without_feature_scope_uses_request_scope \
  tests/xmuse/test_package_boundaries.py -q
-> 21 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Remaining gaps:

- Loop 25z45 is a focused HTTP approval/projection smoke, not a fullchain
  worker/review/final-hold proof.
- Loop 25z44 timed out while the execution worker was still running; the
  cleanup-induced `exec_failed` is preserved as an operator-interrupted state,
  not as a natural business verdict.
- Independent OpenCode lane review after execution still needs a successful
  rerun with `review_runtime=opencode`.
- Production-ready groupchat, GitHub review truth, live MemoryOS, full closure,
  and overnight readiness remain unproven.

### F87. Review runtime canonicalization must include provider casing

Severity: resolved local review-routing blocker for the observed explicit
`OpenCode` provider form.

PR #81 resolved the observed final-hold and display-name alias forms, but Loop
25z46 showed that real groupchat output could also emit the intended provider
name with non-canonical casing:

```text
Loop 25z46 runtime_root:
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z46-post-pr81-fullchain-125758

feature_id=post-pr81-fullchain-ledger-sync-docs
status=awaiting_final_action
gate_passed=true
review_runtime=OpenCode
review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
review_decision=merge
final_action_hold_id=final-1199ff0e330d
```

Root cause:

- Approval projection lowercased the candidate runtime for comparison, but did
  not treat explicit `opencode` as a value that should be rewritten to the
  active review peer's authoritative runtime.
- Downstream review selection uses the canonical provider/runtime identity.
  Preserving `OpenCode` kept the lane from binding to the configured OpenCode
  review peer identity.

Fix:

- During lane_graph approval projection, when a conversation has exactly one
  active OpenCode review participant, normalize explicit `opencode` casing to
  the authoritative runtime value.
- This keeps the earlier alias guard intact and still avoids inventing
  `review_runtime` when it is missing.

Focused post-fix evidence:

```text
Loop 25z47 runtime_root:
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z47-opencode-case-projection-smoke-131455

proposal lane review_runtime=OpenCode
approval response review_runtime=opencode
feature_lanes.json review_runtime=opencode
```

Fullchain post-fix evidence:

```text
Loop 25z48 runtime_root:
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z48-opencode-case-fullchain-131556

conversation_id=conv_78f4da6f5c3b4e11a4c7e50e96275b96
proposal_id=prop_0a317551f8ef48d5aa4338310427f89b
resolution_id=res_6ae312c81f34476fa51ee9bbe7765743
collaboration_run=collab_ecaa21e66b584129924111e4c725bebf
feature_id=docs-production-closure-gap-ledger-post-pr81-rerun
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
peer_delivery_mode=configured_peer
review_peer_id=part_6ed04cc020e145a6a7101938569e37bd
review_decision=merge
review_task=rtask_935e4743a2cf477da02fd60f80398870
review_verdict=verdict-merge-rtask_935e4743a2cf477da02fd60f80398870
final_action_hold_id=final-d1959362ae2b
```

Validation:

```text
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_uses_opencode_review_peer_for_final_hold_runtime \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_uses_opencode_review_peer_display_name_runtime \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_canonicalizes_opencode_review_runtime_case \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_preserves_review_runtime_in_projection \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_routes_to_existing_review_peer \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_without_feature_scope_uses_request_scope \
  tests/xmuse/test_package_boundaries.py -q
-> 22 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Remaining gaps:

- This proves one docs-only local fullchain loop, not repeated soak.
- The successful lane stopped at final-action hold under `--no-auto-merge`; it
  does not prove live merge automation or GitHub review truth.
- Provider-native memory continuity, live MemoryOS, production-ready
  groupchat, full L8-L10 closure, full L1-L11 closure, and overnight readiness
  remain unproven.

### F88. Conversation creation should expose participant session mappings

Severity: resolved local API ergonomics gap with one real code-change
fullchain.

Earlier operation finding F3 noted that external clients had to parse
`god_sessions.json` to map conversation participants to durable GOD sessions.
Loop 25z49 used that as a real small code-change task after PR #82 landed.

Runtime evidence:

```text
Loop 25z49 runtime_root:
/tmp/xmuse-post-pr82-code-lane-5TCIGa/.goal-runs/2026-06-19/loop-25z49-post-pr82-code-lane-134000

conversation_id=conv_d4fc824bbaae4955aafab5fcec53e521
collaboration_run=collab_9be5084eab334e50ab0e327ea7d3b078
proposal_id=prop_8afc1aabe2ce40b3acdb06924f66e161
resolution_id=res_f6262fa36fcf4f078ba78af72957e628
feature_id=peer-chat-participant-sessions-response
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
peer_delivery_mode=configured_peer
review_decision=merge
review_task=rtask_7cea2ced463e4a579dc22af4b66adeef
review_verdict=verdict-merge-rtask_7cea2ced463e4a579dc22af4b66adeef
final_action_hold_id=final-d596ee1cb4ea
```

Real chain:

- Human mentioned only `@architect`.
- Architect asked execute for feasibility through a collaboration run.
- Execute recorded an executable collaboration response.
- Architect emitted exactly one lane_graph proposal.
- OpenCode review-god reviewed the proposal trigger and returned PASS.
- The operator approved the proposal through the public Chat API.
- The runner dispatched the lane into an isolated execution worktree.
- Gate passed the selected `xmuse-core` profile.
- Persistent OpenCode review returned `merge`.
- The lane stopped at human final-action hold under `--no-auto-merge`.

Implementation candidate:

```text
src/xmuse_core/chat/peer_service.py
xmuse/chat_api.py
tests/xmuse/test_peer_chat_api.py
```

The change is additive:

- `PeerChatService.create_conversation` returns top-level
  `participant_sessions` copied from bootstrap output.
- deterministic bootstrap includes `participant_sessions` for created peers.
- proposal-then-approve bootstrap starts with an empty participant session list
  and returns populated mappings after bootstrap apply.
- Chat API exposes the top-level field while preserving existing
  `bootstrap.participant_sessions`.

Gate evidence:

```text
logs/gates/peer-chat-participant-sessions-response/report.json
passed=true
blocking_passed=true
profile_ids=["xmuse-core"]
pytest returncode=0
stdout="253 passed, 2 warnings in 70.15s"
```

Post-import validation:

```text
uv run pytest tests/xmuse/test_peer_chat_api.py tests/xmuse/test_package_boundaries.py -q
-> 28 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Remaining gaps:

- This is one real code-change fullchain and local validation, not repeated
  soak.
- The lane stopped at final-action hold; no live lane merge automation is
  claimed.
- The imported branch has no server facts until pushed and checked.
- GitHub review truth, live MemoryOS, production-ready groupchat, full L8-L10
  closure, full L1-L11 closure, and overnight readiness remain unproven.

### F89. Durable peer writeback must outrank provider process exit in delivery classification

Severity: resolved local observability defect.

Loop 25z50 showed a Codex architect turn with a real durable MCP writeback:

```text
inbox_b8d0d0df31884926848bd62b7e64b8cb
responded_message_id=msg_392105789d3c44c1a924cc50feb3fd9c
peer_turn_mcp_tool_traces included chat_post_message
recorded delivery_mode=failed
recorded degraded_reason=codex_exit_1
```

The chat/inbox store was the stronger authority: the inbox was read, the
responded message existed, and the MCP tool trace showed a real writeback. The
provider process exit remained useful degradation evidence, but it should not
override durable delivery truth.

Local fix:

- `PeerChatScheduler` now rechecks durable inbox/writeback state before
  treating provider `error` results as failed delivery.
- If writeback is real, the trace records `delivery_mode=mcp_writeback` and
  preserves the provider failure as `codex_exit_1_after_writeback` or the
  corresponding `*_after_writeback` reason.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
-> 15 passed, then 16 passed after the scheduler-parallelism test was added
```

Remaining gap:

- Provider wrappers can still fail or time out after successful writeback. That
  is now visible as degraded delivery metadata, not hidden as failed delivery.

### F90. Peer-chat scheduler caused cross-conversation head-of-line blocking

Severity: resolved local throughput blocker for bounded peer-chat fan-out.

Loop 25z51 used three conversations and runner `concurrency=4`, but the
peer-chat control loop awaited one `tick_once()` provider turn before claiming
additional inbox work. Snapshot evidence:

```text
messages=9
chat_inbox_items=7
open_inbox_items=5
proposals=0
resolutions=0
```

This meant one slow peer turn could stall unrelated conversations and made the
groupchat layer feel serial rather than naturally concurrent.

Local fix:

- `PeerChatScheduler.tick_many(max_concurrent=...)` runs bounded concurrent
  `tick_once()` calls against the same durable inbox queue.
- sqlite inbox claims remain the authority for exactly-one item ownership.
- `CoordinatorControlService.tick_peer_chat_scheduler` calls `tick_many` when
  available and platform runner passes through existing `--max-concurrent`.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
-> 16 passed in 4.63s

uv run pytest tests/xmuse/test_platform_runner.py -q
-> 66 passed, 1 warning in 8.86s
```

Loop 25z52 runtime evidence:

```text
elapsed_s=16
initial inbox=3
claimed=3

final:
messages=19
chat_inbox_items=9
open=0
peer_turn_latency_traces=9
peer_turn_mcp_tool_traces=15
proposals=0
resolutions=0
```

Remaining gap:

- `tick_many` claims available inbox items in batches. It does not yet model a
  full conversation-level planner that waits for downstream peer replies before
  allowing summaries or next-stage handoffs.

### F91. Architect final-summary gating needed durable callback authority

Severity: locally mitigated product behavior gap.

Loop 25z52 completed all nine inbox items with durable `mcp_writeback`, but
the conversation semantics were not fully reliable:

- one architect posted a summary before execute/review replies landed;
- alpha/beta peer replies landed, but no later architect summary closed the
  shard after both peer replies were visible;
- all of this happened without proposal or lane leakage, so the issue is
  groupchat turn orchestration, not execution dispatch.

Impact:

- xmuse can now drive a real multi-peer durable groupchat under bounded
  parallelism, but it cannot yet claim production-ready natural peer-GOD
  groupchat behavior.
- Prompt instructions such as "summarize after both replies land" are not a
  sufficient authority boundary.

Next direction:

- Keep the new `peer_reply_drain_callback` narrow: it is a direct-peer-reply
  drain callback, not a general planner or proof authority.
- Add a stronger coordination primitive later for explicit dependency sets
  when a future workflow needs more than "all current direct peer mentions from
  this sender have drained."
- Keep this separate from lane execution and GitHub truth; projection layers
  must not create proof.

2026-06-19 update:

- Loop 25z53 reproduced the gap with two conversations.
- Loop 25z55 and Loop 25z57 completed two conversations through
  execute/review replies, a durable callback to architect, and final summary
  messages containing `FINAL_SUMMARY_AFTER_BOTH_REPLIES`.
- This is local runtime proof only and does not make natural peer-GOD groupchat
  production-ready.

### F92. Handoff side effects must close the current inbox explicitly

Severity: locally resolved scheduler progress blocker.

Loop 25z54 showed that a Codex architect could call `chat_mention` twice and
create downstream execute/review inbox items, while the original human
architect inbox remained open. The provider then returned no final result, and
the scheduler recorded failed delivery before downstream work could proceed.

Local fix:

- `chat_mention` accepts `reply_to_inbox_item_id`.
- When supplied, it marks the current inbox item read, records
  `chat_mention` as an MCP tool stage, and enqueues the target peer inbox in
  the same durable writeback.
- Peer scheduler and provider prompts now describe this as the handoff path.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_mcp_tools.py \
  tests/xmuse/test_peer_chat_scheduler.py \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_ray_adapters.py::test_app_server_mcp_instructions_prefer_direct_post -q
-> 57 passed, 1 warning
```

Runtime evidence:

- Loop 25z55 completed two conversations through final summary.
- Loop 25z57 repeated the path after the early-release grace fix.

### F93. Durable writeback early release needs a grace window

Severity: locally resolved throughput/correctness interaction.

Loop 25z55 still waited for provider timeout after durable handoff writeback.
Loop 25z56 removed that wait but returned immediately after the first
`chat_mention`, cutting off the second same-turn review handoff and creating a
premature callback after only execute replied.

Local fix:

- Scheduler detects durable writeback before provider final result.
- It waits a short post-writeback grace window before aborting the provider
  turn, allowing consecutive handoff tool calls to land.
- If the provider returns during the grace window, normal result handling is
  used; otherwise the turn is recorded as `mcp_writeback` with
  `peer_writeback_before_provider_result`.

Loop 25z57 evidence:

```text
alpha:
  execute_replies=1, review_replies=1
  callback_read=1, marker_messages=1, final_after_both=true
  early_writeback_traces=2
  timeout_after_writeback_traces=0

beta:
  execute_replies=1, review_replies=1
  callback_read=1, marker_messages=1, final_after_both=true
  early_writeback_traces=2
  timeout_after_writeback_traces=0
```

Remaining gap:

- This is bounded local runtime evidence. It does not prove production
  scheduling under load, overnight readiness, live MemoryOS, or full closure.

### F94. Peer-chat fan-out must serialize delivery per target participant

Severity: locally resolved transport/delivery-lifecycle blocker.

Loop 25z61 reran the six-conversation Codex/OpenCode peer-chat stability path
after PR #87 merged. Five conversations reached the expected shape, but alpha
created two architect inbox items for the same participant/session: a normal
mention and a `peer_reply_drain_callback`. `tick_many(max_concurrent=10)`
delivered both to the same persistent Codex session concurrently, producing a
failed trace:

```text
degraded_reason=readuntil() called while another coroutine is already waiting for incoming data
```

Local fix:

- `PeerChatScheduler` keeps cross-participant fan-out;
- delivery to the same `target_participant_id` is serialized with a scheduler
  participant lock;
- focused coverage verifies different participants can still run concurrently
  while two inbox items for the same participant do not overlap provider
  receives.

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
-> 18 passed
```

Loop 25z62 evidence:

- the previous concurrent `readuntil()` failure did not recur;
- the run still failed on a different prompt/tool-contract boundary, with
  `peer_no_inbox_writeback_message`.

Remaining gap:

- This lock is a local scheduler protection. It is not a general dependency-set
  planner and does not prove production load or overnight readiness.

### F95. Simple peer replies must not use back-mention as the reply path

Severity: locally mitigated prompt/tool-contract blocker.

Loop 25z62 showed that after same-participant delivery was serialized, peers
could still answer a simple "name the risk / critique" request by using
`chat_mention` back to the sender. That created extra architect inbox items and
left some items read with no durable response message, producing
`peer_no_inbox_writeback_message` traces and final-summary ordering gaps.

Local fix:

- peer prompt now states that answer/report/review/critique/risk replies must
  use `chat_post_message` with `reply_to_inbox_item_id`;
- `chat_mention` back to the sender is explicitly discouraged for simple
  answers;
- `chat_mention` remains the handoff tool when another GOD should take over,
  inspect, or continue work.

Loop 25z63 evidence:

```text
conversation_count=6
all_final_after_both=true
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
total_failed_traces=0
total_timeout_after_writeback_traces=0
callback_items_by_label={alpha:1,beta:1,gamma:1,delta:1,epsilon:1,zeta:1}
```

Remaining gap:

- This is prompt/tool-contract mitigation, not a hard protocol proof. A future
  coordination primitive should model named dependency sets instead of relying
  on prompt-following for complex multi-peer workflows.
