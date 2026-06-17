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
- Proposal approval while a runner is active can dispatch real provider work
  against the repository worktree unless a safer execution worktree or dry-run
  mode is used.

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

## Recommended Next Implementation Order

1. Add a bounded multi-turn reliability gate for the native Codex + OpenCode
   handoff path.
2. Use the real groupchat to produce a small durable decision/proposal and keep
   source refs to the chat messages.
3. Add dry-run/no-dispatch controls for proposal approval while a runner is
   live.
4. Fix health process discovery so readiness aligns with actual service PIDs
   and endpoint status.
5. Add a public participant-session mapping to conversation creation/inspection.
6. Normalize or document black-box response envelopes for chat write/proposal
   APIs.
7. Add default gate profile handling for proposal-created lanes.
8. Add a reliability gate for real app-server soak so mixed pass/fail evidence
   is preserved instead of collapsed into the latest result.
9. Keep Ray/app-server and soak tests separate from closure claims until a real
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
- The proof level is local runtime proof only.
- The current evidence still does not prove isolated fullchain execution,
  independent review passed, GitHub truth, live MemoryOS, or full closure.
