# Production Closure Gap Ledger

Updated: 2026-06-19

This ledger records current production-closure gaps for the real xmuse GOD
chatgroup and fullchain goal. It is not proof by itself; use it as an index
back to runtime artifacts and findings.

## Current Proof Boundary

Current strongest proof level:

```text
local_runtime_proof for selected runs only; Loop 25r is degraded local runtime proof
Loop 25s is candidate-branch local_runtime_proof for proposal lane authority only
Loop 25t is candidate-branch local_runtime_proof for read_run_health process discovery only
Loop 25v is integrated local candidate proof to no-auto-merge final-action hold
Loop 25x is current-worktree negative fullchain proof: child MCP was exposed but status-guard writeback failed
Loop 25y is current-worktree local proof for runner-dispatched child MCP writeback only
Loop 25z4d is current-worktree local_runtime_proof for one natural GOD groupchat
to package-boundary lane execution, configured OpenCode review, and
no-auto-merge final-action hold
Loop 25z6 is post-PR59 main local_runtime_proof for natural groupchat through
approval, projected worktree creation, child stdout-fallback execution, and
gate; it fails at configured OpenCode platform review with
session_layer_unavailable
Loop 25z7c is candidate-branch local_runtime_proof for the same bounded
groupchat path through configured OpenCode platform review and no-auto-merge
final-action hold after wiring the peer-chat session layer into review handoff
Loop 25z8 is post-PR60 main local_runtime_proof that configured OpenCode
review handoff no longer fails with session_layer_unavailable, but the run
required operator nudge after an architect peer_response_timeout
Loop 25z9 is candidate-branch local_runtime_proof that timeout after durable
MCP writeback is now classified as mcp_writeback rather than failed, and the
same no-nudge bounded chain reached no-auto-merge final-action hold
Loop 25z10b is post-PR61 main local_runtime_proof for a no-nudge durable
GOD groupchat through proposal, approval, lane execution, configured OpenCode
review, and no-auto-merge final-action hold
Loop 25z11 is candidate-branch local_runtime_proof that dispatch bridge
chat-plane handoff can reuse peer_chat_worktree and record dispatched instead
of failing execute session reuse
Loop 25z12 is post-PR62 main local_runtime_proof that the dispatch bridge fix
survives merge and the bounded no-nudge chain still reaches no-auto-merge
final-action hold, while review evidence refs remain empty
PR #63 has contract/local validation for persistent review evidence propagation
only; runtime probes 25z13c/25z13d/25z13f stopped before a parseable persistent
review verdict reached the patched accept path
GitHub server fact for PR #54 head e84da7d / merge commit 3a84c7d only
GitHub server fact for PR #55 head 6931690 / merge commit a84c9b9 only
GitHub server fact for PR #56 head 600c2db / merge commit e64d696 only
GitHub server fact for PR #57 head dfebf9a / merge commit 09453e4 only
GitHub server fact for PR #58 head 4f6a29a / merge commit ff5d61d only
GitHub server fact for PR #59 head ef38360 / merge commit 6058002 only
GitHub server fact for PR #60 head 93d690e / merge commit db5b7df only
GitHub server fact for PR #61 head d85d88d / merge commit ec9a755 only;
Actions run 27781274986 completed successfully before merge, but no GitHub
review truth is claimed
GitHub server fact for PR #62 head 42db27c / merge commit 8c9966d only;
Actions run 27783134156 completed successfully before merge, but no GitHub
review truth is claimed
GitHub server fact for PR #63 head 6b68371 / merge commit 3fbbb5e only;
Actions run 27785122877 completed successfully before merge, but no GitHub
review truth is claimed
GitHub server fact for PR #64 head 741fb4f / merge commit e7879cd only;
Actions run 27785599908 completed successfully before merge, but no GitHub
review truth is claimed
Loop 25z14 local_runtime_negative evidence: configured OpenCode review returned
a codex-app-server result shape but still failed closed with
review_peer_no_verdict; PR #64 diagnostic metadata landed
GitHub server fact for PR #65 head ce2b9a9 / merge commit c4b668f only;
Actions run 27786146679 completed successfully before merge, but no GitHub
review truth is claimed
Loop 25z15 candidate and Loop 25z16 post-merge main local_runtime_negative
evidence: configured OpenCode review now fails closed with
codex_app_server_error and peer_result_status=peer_error instead of a false
successful empty app-server result
GitHub server fact for PR #66 head d42541b / merge commit 457cbf1 only;
Actions run 27787176120 completed successfully before merge, but no GitHub
review truth is claimed
Loop 25z17 candidate and Loop 25z18 post-merge main local_runtime_proof:
configured OpenCode review used the OpenCode process shim, returned
review_decision=merge, and reached no-auto-merge final-action hold; review MCP
tool exposure and evidence refs remain open
GitHub server fact for PR #67 head bd25527 / merge commit 5d1e1c7 only;
reviewDecision was empty and no GitHub review truth is claimed
Loop 25z20 post-PR67 local_runtime_proof: child Codex MCP writeback worked and
the bounded lane reached no-auto-merge final-action hold, but OpenCode review
formal collaboration response required operator nudge because the Chinese
collaboration-response request was not detected as formal
GitHub server fact for PR #68 head d134f87 / merge commit 24b8b25 only;
Actions run 27789931110 completed successfully before merge, but no GitHub
review truth is claimed
Loop 25z22 post-PR68 main local_runtime_proof: clean human @architect demand
reached durable Codex/OpenCode collaboration, CJK OpenCode formal
collaboration response without operator nudge, lane_graph proposal, manual
approval, dispatch, child MCP update_lane_status, configured OpenCode review,
and no-auto-merge final-action hold; gate_profiles_missing and review-plane
stdout fallback remain open
Loop 25z23b candidate-branch local_runtime_proof on
codex/gate-profile-runtime-authority at 31f3714: the same bounded chain reached
no-auto-merge final-action hold while the gate used tracked
xmuse/gate_profiles.json from the lane worktree, ran strict-product
package-boundary pytest, and no longer passed open with gate_profiles_missing;
review-plane stdout fallback remains open
GitHub server fact for PR #69 head 31f3714 / merge commit 007811a only;
Actions run 27791970708 completed successfully before merge, but no GitHub
review truth is claimed
Loop 25z24 post-PR69 main local_runtime_proof: clean human @architect demand
reached durable Codex/OpenCode collaboration, proposal, manual approval,
dispatch, lane execution, strict-product gate profile command execution, and
no-auto-merge final-action hold on main at 007811a; gate_profiles_missing did
not recur, while review_runtime=local and review-plane one-shot fallback remain
open; peer session health still showed sessions as status=starting after
successful writebacks
Loop 25z25 post-PR69 main local_runtime_negative evidence: explicit
review_runtime=opencode target reached collaboration
collab_6b6adc941aa74afb89320099f19a20e1, but natural CJK
"协作响应工具回填" phrasing produced ordinary OpenCode chat
msg_2e3625ec83a04d338da6e187ee8f1c26 instead of a formal
collaboration_responses row; collaboration remained partial and no proposal
dispatch happened
PR #70 open draft server fact only: head 4195420 on
codex/cjk-collab-response-tool-phrase, base main, URL
https://github.com/iiyazu/Cross-Muse/pull/70; Actions run 27793722331
completed successfully for contract-smoke-gates, real-runtime-integration-gate,
and quality-gates; no GitHub review truth or merge truth is claimed
Loop 25z26 candidate-branch local_runtime_proof on PR #70 head 4195420:
natural groupchat reached formal OpenCode collaboration response
collab_resp_407f6b61bc314781a936957ae90a0237, proposal
prop_47f0d6057ab7405eb5595e7394816955, dispatch, strict-product gate,
configured OpenCode platform review with review_runtime=opencode, non-empty
review_evidence_refs, and no-auto-merge final-action hold
final-135ac3dde026; review MCP tool exposure, duplicate proposal noise, and
session_health=starting remain open
Loop 25z27b post-PR69 main local_runtime_proof/negative review evidence:
clean human @architect demand reached durable Codex/OpenCode collaboration
collab_eeb0ffec254d455dbd781f2dafa61452, accepted proposal
prop_1b09bb35d22842dd98f33fac687c4300, strict-product gate, configured
OpenCode platform review, non-empty review_evidence_refs, and final hold
final-f9f998f0542a; however the review summary incorrectly said logs/gate
artifacts did not exist while they did exist in the runtime root
PR #71 open draft server fact only: head cd71375 on
codex/review-peer-artifact-grounding, base main, URL
https://github.com/iiyazu/Cross-Muse/pull/71; Actions run 27795048428
completed successfully for contract-smoke-gates, real-runtime-integration-gate,
and quality-gates; no GitHub review truth or merge truth is claimed
Loop 25z28 candidate-branch local_runtime_proof on PR #71 head cd71375:
natural groupchat reached durable collaboration
collab_c29de586d02c44049be6e7d21027c5e9, accepted proposal
prop_9a853383ff4e4433894040efc51b74c2, strict-product gate, configured
OpenCode platform review with review_runtime=opencode, non-empty
review_evidence_refs, and final hold final-def8a28d600e; the review summary
now grounds its verdict in gate, worker, lane context, git diff, and git status
artifacts, but review provider MCP exposure still falls back to stdout
manual_gap for production closure
manual_gap for GitHub review truth and future PR/server truth
manual_gap for repeated stability, configured OpenCode platform-review proof,
review MCP evidence, and broad coding-task completion
```

## Open Manual Gaps

### G1. Child MCP writeback reliability

Status: open.

Evidence:

- Loop 25d and 25e showed positive child MCP writeback.
- Loop 25f failed closed with `child_mcp_required_but_unavailable`.
- Loop 25g showed MCP-required missing-tool fallback now reports
  `exec_failed` before running tests, but Codex CLI still returned process exit
  code 0.
- Loop 25h showed direct Codex/SSE can call `query_knowledge` and
  `update_lane_status`; `update_lane_status` now accepts bounded
  `tests_run`/`changed_files` evidence metadata. The AgentSpawner child path
  still failed early as MCP unavailable in the same runtime root.
- Loop 25i showed one positive AgentSpawner child path: `query_knowledge`,
  package-boundary pytest, and `update_lane_status` all completed, and
  `feature_lanes.json` reached `status=executed`.
- Loop 25j showed the same child MCP sequence inside a groupchat-produced
  fullchain run: `query_knowledge`, package-boundary pytest, and
  `update_lane_status` all completed from the spawned Codex worker before the
  lane reached `awaiting_final_action`.
- Loop 25k repeated the groupchat-produced fullchain child MCP path and reached
  `awaiting_final_action` again. The child first tried broader metadata keys
  and retried successfully with accepted bounded metadata.
- Loop 25l produced a real code-change candidate, but failed closed because the
  live MCP server had not loaded the candidate handler change from the isolated
  execution worktree.
- Loop 25m reran after main Codex import and service restart. The child worker
  successfully wrote back `tests_run`, `changed_files`, `review_runtime`,
  `final_action`, and `proof_boundary` through live MCP.
- Loop 25p reran latest main after PR #55 and reached final-action hold, but
  the parent execution coordinator attempted a stale `gated -> executed`
  transition after the child worker had already advanced the lane through MCP
  writeback and gate/review.
- PR #56 split the advanced child-writeback idempotency fix into a small
  `origin/main`-based PR. Required GitHub checks passed for head
  `600c2dbd0b5fe411be80ec6fdea55cbbe8032697`, and GitHub accepted a normal
  squash merge as `e64d696d4b7240390617d559e2514941949a937c`.
- Loop 25r reran from that merge commit and reached final-action hold without
  the Loop 25p duplicate transition incident. This is degraded local runtime
  proof because the approval/projection path dropped the proposal lane shape.
- Loop 25s reran on a candidate branch and reached final-action hold after the
  accepted proposal lane was preserved through approval/projection. The child
  worker called MCP and wrote `tests_run`, `changed_files`, `final_action`, and
  `proof_boundary`; this is candidate-branch local runtime evidence only.
- Loop 25v combined the proposal-authority, run-health, and projected-worktree
  candidate fixes and reached no-auto-merge final-action hold, but the child
  worker did not have MCP tools exposed and used stdout fallback. It is not
  positive child MCP writeback evidence.
- Loop 25w showed that the current-worktree direct AgentSpawner child path can
  expose xmuse MCP tools: the child called `query_knowledge`, called
  `update_lane_status`, and moved the lane to `executed`.
- Loop 25x showed that the current-worktree fullchain child worker did have MCP
  tools and ran the focused package-boundary test, but `update_lane_status`
  writes were rejected by a status guard mismatch. The old runner
  classification incorrectly recorded this as MCP unavailable.
- Loop 25y rechecked the status-guard fix through a real runner-dispatched
  Codex child worker. It called `query_knowledge`, ran
  `uv run pytest tests/xmuse/test_package_boundaries.py -q`, and successfully
  wrote `status=executed` with `guard.current_status=dispatched`.
- Loop 25z4c showed a child worker could run the required
  `uv run pytest tests/xmuse/test_package_boundaries.py -q` command and pass
  16 tests, but failed the lane because it tried to perform OpenCode review
  routing itself.
- Loop 25z4d reran after the execution/review boundary prompt fix. The child
  worker ran the same command, passed 16 tests, reported execution completion,
  and allowed the parent runner to proceed to gate, configured OpenCode review,
  and final-action hold.
- Loop 25z6 reran from current `origin/main` after PR #57/#58/#59 merges. The
  child worker ran `uv run pytest tests/xmuse/test_package_boundaries.py -q`
  and passed 16 tests, but MCP tools were unavailable in that child session and
  the worker used stdout fallback. The lane reached `gated` and then failed at
  review handoff.
- Loop 25z20 reran after PR #67 and exposed Codex child MCP tools through the
  fullchain lane path: `query_knowledge`, focused package-boundary pytest, and
  `update_lane_status` completed before final-action hold.
- Loop 25z22 reran after PR #68 from main at merge commit `24b8b25`. The child
  worker again had MCP tools exposed, ran
  `uv run pytest tests/xmuse/test_package_boundaries.py -q`, passed
  `16 passed in 2.95s`, and updated the lane to `executed` through
  `update_lane_status`. This is local runtime proof only.

Required proof:

- Repeated real lane executions where Codex child workers call
  `query_knowledge` before execution and `update_lane_status` after execution.
- No stdout fallback counted as success.
- Repeat the Loop 25z4d path and add real code-change lanes; keep no-edit
  package-boundary proof scoped.
- Add real code-change lanes before counting broad coding-task completion; the
  current clean child MCP proof is still a bounded package-boundary lane.

### G2. Natural peer-GOD groupchat production readiness

Status: open.

Evidence:

- Codex and OpenCode can both write durable messages through MCP/callback paths.
- Loop 25f showed natural role mentions in prose can create direct-inbox noise.
- Loop 25f used message-shaped `collab_*` references without a structured
  `collaboration_runs` table in that runtime root.
- Loop 25j produced a structured durable collaboration run with Codex architect,
  Codex execute, and OpenCode review, then emitted a proposal referencing that
  collaboration run. The human prompt mentioned only `@architect`.
- Loop 25k repeated the same pattern with a different conversation and
  collaboration run, then advanced the approved proposal to final-action hold.
- Loop 25l and 25m repeated the collaboration/proposal path for a real
  code-change demand. Loop 25m advanced the approved proposal to final-action
  hold after main import.
- Loop 25p repeated the collaboration/proposal/approval path from latest main
  and advanced to final-action hold, but exposed the duplicate execution
  transition fixed by PR #56.
- Loop 25r completed a durable Codex/OpenCode collaboration and architect
  `chat_emit_proposal` flow, then reached final-action hold after human
  approval. It is not clean production groupchat proof because the first
  architect latency trace recorded `peer_response_timeout`, and approval
  projection did not preserve the proposal lane graph.
- Loop 25s again completed durable Codex execute and OpenCode review
  collaboration responses and a Codex architect `chat_emit_proposal` flow, but
  the first architect turn still recorded `peer_response_timeout` and a stale
  health blocker required human resolution through the public API before
  approval could proceed.
- Loop 25t isolated that specific stale health blocker to the
  `read_run_health` process discovery path and created local candidate commit
  `b05be1c fix: let run health discover live runtime processes`. A real MCP
  `read_run_health` call then reported `runner_count=1`, `mcp_count=1`, and no
  warnings for the current entrypoint forms.
- Loop 25v combined the run-health candidate with the proposal-authority and
  worktree-provisioning candidates. The stale no-live-runner/MCP blocker did
  not recur, and the chain reached final-action hold. The first architect
  latency trace still recorded `peer_response_timeout`, and durable peer MCP
  tool traces did not record `read_run_health`, so production-ready natural
  groupchat remains unproven.
- Loop 25x reran a current-worktree maximum-accessible chain from human
  `@architect` mention through durable collaboration, `lane_graph` proposal,
  approval, projection, and worker dispatch. It proved the child execution
  session had MCP tools, but failed at child writeback guard mismatch before
  review/final hold.
- Loop 25z4b showed a real natural groupchat failure where OpenCode wrote a
  normal confirmation message but did not record `collaboration_responses`,
  leaving the collaboration run `partial`.
- Loop 25z4c fixed that OpenCode collaboration-response formalization path:
  the collaboration reached `done`, architect emitted a proposal, and human
  approval dispatched a lane. The run then failed in execution because the
  child tried to perform acceptance review routing.
- Loop 25z4d completed a clean bounded natural groupchat path from a human
  `@architect` mention through durable Codex execute and OpenCode review
  collaboration responses, architect `chat_emit_proposal`, OpenCode proposal
  review trigger, human approval, lane worker execution, configured OpenCode
  platform review, and final-action hold.
- Loop 25z6 repeated the natural groupchat portion from current `origin/main`
  after PR #57/#58/#59. Human mentioned only `@architect`; architect created
  collaboration `collab_6430946533ba4311a8952fd060715b62`; execute and review
  both wrote durable responses; architect emitted a post-collaboration proposal
  `prop_52d5bc3241524697b05e29cd8d0c7045`; OpenCode proposal review wrote a
  durable response; human approval projected the lane. The run failed later at
  platform review handoff, not at natural groupchat proposal production.
- Loop 25z9 reran the bounded natural groupchat path on candidate branch
  `codex/peer-timeout-after-writeback` with no operator nudge. The architect
  turn timed out at the provider layer after already writing durable MCP
  output, and the candidate fix recorded it as
  `delivery_mode=mcp_writeback` /
  `degraded_reason=peer_response_timeout_after_writeback`. The chain reached
  `awaiting_final_action`. One early execute inbox still failed with a session
  reuse mismatch, so peer session lifecycle reliability remains open.
- Loop 25z20 reached the same bounded chain after PR #67, but OpenCode review
  initially wrote a normal chat message instead of a formal
  `collaboration_responses` row for the Chinese review request; an operator
  nudge was required. This was negative evidence for CJK collaboration-response
  detection.
- PR #68 addressed that bounded parser gap. Loop 25z22 then repeated a clean
  human `@architect` demand from main and produced the OpenCode review
  `collaboration_responses` row
  `collab_resp_09efb3c7288a4c03b247fce66364ded4` without operator nudge. The
  chain reached final-action hold, but it is still local runtime proof only.
- Loop 25z25 showed a remaining natural CJK phrase gap: `协作响应工具回填`
  was not detected as a formal collaboration-response request, so the OpenCode
  review peer wrote ordinary chat and the collaboration stayed partial. PR #70
  adds the bounded detector markers. Loop 25z26 on that candidate reached
  completed durable collaboration, proposal, dispatch, configured OpenCode
  review, and final-action hold, but duplicate proposal noise and
  `session_health=starting` remain open.

Required proof:

- Durable multi-turn Codex + OpenCode peer discussion with intended source
  inboxes, terminal delivery states, and no unclassified duplicate turns.
- Repeated stability evidence before claiming production-ready natural
  groupchat.
- Real code-change demands with the same no-nudge formal collaboration behavior,
  not just package-boundary retests.

### G3. Review truth boundary

Status: open.

Additional evidence:

- Loop 25z22 configured OpenCode as the platform review peer and reached a
  merge verdict plus final-action hold, but the review summary explicitly said
  `MCP tools unavailable` and used stdout fallback. That is local runtime
  review evidence only.
- PR #68 had successful GitHub Actions and was squash merged by GitHub, but
  `reviewDecision` was empty. This is CI/merge server fact, not GitHub review
  truth.
- Loop 25z23b on candidate branch `codex/gate-profile-runtime-authority`
  reached configured OpenCode review plus final-action hold with a real
  strict-product gate report from tracked `xmuse/gate_profiles.json`:
  `profile_ids=["strict-product"]`, command
  `uv run pytest -q tests/xmuse/test_package_boundaries.py`, and result
  `16 passed in 2.99s`. This closes only the candidate-path
  `gate_profiles_missing` fail-open blocker; review-plane MCP evidence still
  fell back to stdout.
- PR #69 published and merged that gate-profile authority slice. GitHub
  Actions run `27791970708` succeeded for head
  `31f3714052bc60e68f5bc75db8490cb6e0fd7f39`; GitHub merged it as
  `007811aaaebc7f82b05dd2dc781829ed026a2197` at
  `2026-06-18T22:01:21Z`. `reviewDecision` was empty, so no GitHub review
  truth is claimed.
- Loop 25z24 reran from post-PR69 main at `007811a` and reached
  final-action hold. The gate used tracked `xmuse/gate_profiles.json`, ran the
  strict-product package-boundary command, and did not record
  `gate_profiles_missing`. The lane proposal had `review_runtime=local`, and
  the review plane degraded to one-shot fallback with
  `missing_feature_identity`; peer session health still reported sessions as
  `status=starting` after successful writebacks. This does not close
  configured OpenCode platform-review proof.
- Loop 25z26 on PR #70 candidate head reached configured OpenCode platform
  review with `review_runtime=opencode`, `persistent_review_degraded=false`,
  `review_decision=merge`, and non-empty `review_evidence_refs`. It still does
  not close review truth because the OpenCode review summary said MCP tools
  were unavailable and reported via stdout. PR #70 CI success is exact-head
  server fact only, not GitHub review truth or merge truth.

Required proof:

- Expose or verify durable MCP/tool evidence for the platform OpenCode review
  plane, or keep stdout fallback classified as lower proof.
- Preserve separate labels for local review verdicts, GitHub checks, GitHub
  reviews, and merge facts.

Evidence:

- Loop 25e produced durable final review refs including child spawn artifacts.
- Loop 25f added a focused guard so successful OpenCode callback summaries are
  bounded by evidence refs.
- Loop 25f did not reach final review because execution failed closed first.
- Loop 25j reached configured OpenCode persistent review with bounded
  `review_summary`, non-degraded delivery, and review refs that cite lane and
  review artifacts. `review_plane.gate_report_ref` was still `null`.
- Loop 25k fixed the missing-gate-report path for absent `gate_profiles.json`.
  The review task recorded
  `logs/gates/loop25k-gate-report-ref-final-hold/report.json`, and the review
  verdict evidence refs included that gate report.
- Loop 25m reviewed a real code-change lane with configured OpenCode
  persistent review and evidence refs that included the gate report.
- PR #55 split the missing-profile gate report producer fix into a small
  `origin/main`-based PR. Required GitHub checks passed for head
  `6931690c46b86447d3c3bf071a6a992ec50596f5`, and GitHub accepted a normal
  squash merge as `a84c9b99d4fe4143dce12257079a423a21e6f1e5`.
- Loop 25p reached configured OpenCode persistent review without persistent
  degradation, but the review summary still reported stdout fallback and
  `review_evidence_refs=[]`.
- Loop 25r reached final-action hold with review evidence refs, but persistent
  review degraded to `one_shot_fallback`/stdout because of
  `missing_feature_identity` after approval projection changed the lane id.
- Loop 25s preserved the lane identity through projection and reached
  final-action hold, but the final review verdict still had
  `review_evidence_refs=[]` and `review_fallback_reason=verdict_merge`.
- Loop 25v reached final-action hold on the integrated candidate path, but the
  final review still had `review_evidence_refs=[]`,
  `review_fallback_reason=verdict_merge`, and the review summary reported MCP
  tools unavailable in the review session.
- Loop 25y execution and gate passed, but required OpenCode review peer
  delivery failed with `required_review_peer_unavailable` /
  `missing_conversation_id` because the direct runner lane lacked conversation
  context.
- Loop 25z3 showed the next current-worktree review blocker:
  `session_layer_unavailable` for configured OpenCode review.
- Loop 25z4d reran with peer-chat session layer wired into review handoff and
  completed configured OpenCode review:
  `peer_delivery_mode=configured_peer`,
  `persistent_review_identity=configured:<review participant>`,
  `review_decision=merge`, `review_verdict.status=finalized`, and evidence
  refs including `feature_lanes.json`, `review_plane.json`, lane prompt, and
  gate report.
- Loop 25z6 reran from post-PR59 `origin/main` and failed at this same review
  boundary:
  `failure_reason=required_review_peer_unavailable`,
  `peer_delivery_mode=required_peer_failed`,
  `peer_degraded_reason=session_layer_unavailable`,
  `review_plane.review_verdicts=[]`. This confirms the Loop 25z4d review
  session-layer wiring is still not in main.
- Loop 25z7c rebuilt the review session-layer wiring as a small candidate on
  `origin/main` and reran the bounded chain with explicit OpenCode review. It
  reached `status=awaiting_final_action`,
  `peer_delivery_mode=configured_peer`, `peer_degraded_reason=null`,
  `review_decision=merge`, and `final_action_hold_id=final-bc45596d37e1`.
  This closes only the `session_layer_unavailable` handoff blocker for that
  candidate branch.
- PR #60 published and merged the review session-layer wiring. GitHub Actions
  run `27779712756` succeeded for head
  `93d690efc64f92af639ac5df7451f903491aee0f`; GitHub merged it as
  `db5b7dfa10608d74b01f56447db75b63caaeaf60` at
  `2026-06-18T18:10:33Z`.
- Loop 25z8 reran from post-PR60 main and reached
  `status=awaiting_final_action`,
  `peer_delivery_mode=configured_peer`, `peer_degraded_reason=null`,
  `review_decision=merge`, and `final_action_hold_id=final-fb5833c722b3`.
  This verifies the handoff blocker is closed on main for one local run, but
  the run required operator nudge after the first architect turn timed out.
- Loop 25z9 reran on candidate branch `codex/peer-timeout-after-writeback`
  and reached `status=awaiting_final_action`,
  `peer_delivery_mode=configured_peer`, `peer_degraded_reason=null`,
  `review_decision=merge`, and `final_action_hold_id=final-e846e62cbe84`
  without operator nudge. The review session still reported MCP tools
  unavailable, used stdout fallback, and recorded `review_evidence_refs=[]`.
- Loop 25z10b reran after PR #61 merged to main and reached
  `status=awaiting_final_action`,
  `peer_delivery_mode=configured_peer`, `peer_degraded_reason=null`,
  `review_decision=merge`, and `final_action_hold_id=final-6978d6b6a743`
  without operator nudge. `review_plane.gate_report_ref` existed, but the
  final verdict still had `review_evidence_refs=[]`, and gate profiles were
  still missing.
- Loop 25z11 reran on candidate branch `codex/dispatch-bridge-peer-worktree`
  and reached `status=awaiting_final_action`. It closed the repeated
  chat-dispatch execute session reuse failure for that candidate run:
  `chat_dispatch_queue.status=dispatched`,
  `dispatch_evidence=mcp_writeback:inbox_03492d6f6c044219b50ef7dfb52cc0a6`,
  and `failure_reason=null`. Review evidence refs and gate profiles remained
  open.
- Loop 25z12 reran after PR #62 merged to main and reached
  `status=awaiting_final_action` without operator nudge. It preserved
  `chat_dispatch_queue.status=dispatched`,
  `dispatch_evidence=mcp_writeback:inbox_96cfbd027996488886bc41555ce0df31`,
  `peer_delivery_mode=configured_peer`, and `review_decision=merge`, but
  `review_evidence_refs=[]` and gate profiles remained open. The review peer
  self-ran the package-boundary test instead of citing durable execution
  artifacts.
- PR #63 adds contract/local coverage for carrying review evidence refs through
  persistent review accept paths. Runtime probes did not prove it yet:
  25z13c/25z13d stopped at architect `peer_no_inbox_side_effect`, and 25z13f
  reached execution/gate but failed configured OpenCode review with
  `review_peer_no_verdict` before a verdict reached the patched path.
- PR #64 adds server-merged diagnostic metadata for configured review peer
  failures. Loop 25z14 reached the same review boundary and recorded
  `peer_result_status=ok`, `peer_result_message_runtime=codex-app-server`, and
  artifact keys `latency_stages/stdout/transport`, but still failed closed with
  `review_peer_no_verdict`.
- PR #65 fixes the false-success shape for Codex app-server error
  notifications and failed turns. Loop 25z15 on the candidate branch and Loop
  25z16 on post-merge main both reached `status=gate_failed` with
  `peer_degraded_reason=codex_app_server_error`,
  `peer_result_status=peer_error`, and
  `peer_result_message_runtime=codex-app-server`.
- PR #66 fixes Ray GOD session transport selection so OpenCode review peers
  use process JSON transport instead of Codex app-server. Loop 25z17 reached
  `status=awaiting_final_action`, `peer_delivery_mode=configured_peer`,
  `review_decision=merge`, and `final_action_hold_id=final-648d470f52e2` on
  the candidate branch. Loop 25z18 repeated that path on post-merge main with
  `final_action_hold_id=final-06e33f50b16a`.

Required proof:

- Real fullchain run where `review_summary` is bounded, raw provider prose is
  stored separately, and `review_evidence_refs` cite real child artifacts.
- Repeated review runs with direct gate report linkage for configured and
  missing-profile gate paths.
- Repeat with configured OpenCode platform review and real code-change lanes
  before claiming production review readiness.
- Repeat with real code-change lanes before claiming production review
  readiness.
- Keep review evidence refs, review-session MCP writeback, and no-intervention
  natural groupchat reliability open.

### G4. GitHub/server truth

Status: partially closed for exact small-PR merge facts only; open for review truth.

Evidence:

- PR #54 (`codex/mcp-status-metadata-allowlist`) was created from
  `origin/main` for the bounded MCP metadata allowlist domain only.
- PR #54 head
  `e84da7d43276cae596fd70394e72d339539afff1` passed required GitHub checks in
  run `27762687502`:
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`.
- GitHub reported `mergeStateStatus=CLEAN` and `mergeable=MERGEABLE` for that
  exact head before merge.
- GitHub accepted a normal squash merge without admin bypass:
  `mergedAt=2026-06-18T13:26:54Z`,
  `merge_commit=3a84c7d674a007f07a03e33da97f88b969cb68b9`.
- PR #55 (`codex/gate-missing-profile-report`) was created from `origin/main`
  for the missing-profile gate report producer domain only.
- PR #55 head
  `6931690c46b86447d3c3bf071a6a992ec50596f5` passed required GitHub checks in
  run `27763032153`:
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`.
- GitHub reported `mergeStateStatus=CLEAN` and `mergeable=MERGEABLE` for that
  exact head before merge.
- GitHub accepted a normal squash merge without admin bypass:
  `mergedAt=2026-06-18T13:31:58Z`,
  `merge_commit=a84c9b99d4fe4143dce12257079a423a21e6f1e5`.
- PR #56 (`codex/execution-child-writeback-advanced-status`) was created from
  `origin/main` for the advanced child execution writeback idempotency domain
  only.
- PR #56 head
  `600c2dbd0b5fe411be80ec6fdea55cbbe8032697` passed required GitHub checks in
  run `27764570812`:
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`.
- GitHub reported `mergeStateStatus=CLEAN` and `mergeable=MERGEABLE` for that
  exact head before merge.
- GitHub accepted a normal squash merge without admin bypass:
  `mergedAt=2026-06-18T13:57:14Z`,
  `merge_commit=e64d696d4b7240390617d559e2514941949a937c`.
- PR #63, PR #64, and PR #65 were also created as bounded `origin/main`-based
  PRs. GitHub accepted squash merges for exact heads
  `6b6837129d5a65e5f2d24b4d2c5ad4f63568da7a`,
  `741fb4fe71c297330f504c64eee028bb724cab90`, and
  `ce2b9a9a50289be61ba7f7e30b794bbc5620aaa3` as merge commits `3fbbb5e`,
  `e7879cd`, and `c4b668f`.
- Required GitHub checks completed successfully before those merges in runs
  `27785122877`, `27785599908`, and `27786146679`.
- PR #66 was created as a bounded `origin/main`-based PR for OpenCode Ray
  transport selection only. GitHub accepted squash merge for exact head
  `d42541b18c27d1eb101e5463aff5e0c29c139662` as merge commit
  `457cbf14ebf74edf472b38c028551f42a9e08772`; required checks completed
  successfully before merge in run `27787176120`.
- `reviewDecision` was empty; no GitHub review truth is claimed.
- PR #43 must remain historical and unmutated.

Required proof:

- Current-head GitHub facts for each future small PR before any CI, review, or
  merge claim.
- Explicit review facts before any GitHub review-truth claim.

### G5. Production readiness

Status: open.

Evidence:

- Runtime loops are still exposing routing, child MCP, and review-evidence
  weaknesses.
- Loop 25j shows a clean local fullchain to final-action hold, but it was one
  bounded no-edit lane and does not prove repeated stability, real code-change
  completion, GitHub truth, or production readiness.
- Loop 25k repeated the bounded no-edit lane and closed one review evidence
  quality gap. It still does not prove real code-change completion, GitHub
  truth, merge truth, or production readiness.
- Loop 25m shows one local real code-change fullchain to final-action hold.
  It still does not prove GitHub truth, merge truth, production readiness, or
  small-PR publication.
- PR #54 moved that one bounded MCP metadata allowlist domain into a small
  main-based PR and GitHub accepted its squash merge after required checks
  passed. This does not prove broader production readiness, groupchat
  stability, GitHub review truth, or full closure.
- PR #55 moved the missing-profile gate report producer into a small
  main-based PR and GitHub accepted its squash merge after required checks
  passed. This does not prove broader production readiness, groupchat
  stability, GitHub review truth, or full closure.
- PR #56 moved the advanced child execution writeback idempotency fix into a
  small main-based PR and GitHub accepted its squash merge after required
  checks passed. This does not prove broader production readiness, groupchat
  stability, GitHub review truth, or full closure.
- Loop 25r reached final-action hold after PR #56, but only as degraded local
  runtime proof because proposal approval did not preserve the proposal lane
  graph and review degraded to stdout fallback.
- Loop 25s shows candidate-branch local runtime proof that approval/projection
  can preserve the proposal lane graph and reach final-action hold. It does
  not prove production readiness because it required stale blocker resolution,
  still had chat dispatch queue failure, and did not produce GitHub/server
  truth for the candidate branch.
- Loop 25t shows candidate-branch local runtime proof that the MCP
  `read_run_health` tool can see live runner/MCP processes after process
  discovery fixes. It does not prove future groupchat stability by itself.
- Loop 25v shows an integrated local candidate run from GOD groupchat through
  approval, lane execution, review, and no-auto-merge final-action hold. It
  does not prove production readiness because it is not main/GitHub truth, the
  child worker used stdout fallback, review evidence refs remained empty, and
  the first architect latency trace still timed out.
- Loop 25w2 shows current-worktree local runtime proof that MCP
  `read_run_health` can see live runner/MCP processes with
  `runner_count=1`, `mcp_count=1`, and no warnings.
- Loop 25x shows current-worktree groupchat/proposal/approval can dispatch a
  child worker with MCP exposed, but failed at status-guard writeback.
- Loop 25y shows current-worktree runner-dispatched child MCP writeback can
  succeed after the status-guard prompt fix, but review handoff then failed
  because a required OpenCode review peer lacked conversation context.
- Loop 25z4d shows current-worktree local runtime proof for one bounded
  no-edit package-boundary lane from natural groupchat to no-auto-merge
  final-action hold with configured OpenCode review. It does not prove
  production readiness because it is one local run, gate profiles were missing,
  and it is not GitHub/server truth or broad coding-task completion.
- Loop 25z6 shows post-PR59 main can now reach the projected-worktree and gate
  boundary from real groupchat, but still fails before final-action hold due
  `session_layer_unavailable` in configured OpenCode platform review. It also
  used child stdout fallback, so it is not clean child MCP proof.
- Loop 25z7c shows the review session-layer candidate can reach
  no-auto-merge final-action hold with configured OpenCode review. It is still
  not production readiness because `review_evidence_refs=[]`, the review
  session reported MCP tools unavailable, gate profiles were missing, and this
  is candidate-branch local proof rather than server/main proof.
- Loop 25z8 shows post-PR60 main can reach no-auto-merge final-action hold
  with configured OpenCode review. It is still not production readiness because
  the first architect turn timed out, operator nudge was required,
  `review_evidence_refs=[]`, review-session MCP tools were unavailable, and
  gate profiles were missing.
- Loop 25z9 shows candidate-branch local runtime proof that the architect
  timeout-after-writeback path can proceed without operator nudge and still
  reach no-auto-merge final-action hold. PR #61 GitHub Actions passed for the
  candidate head. It is still not production readiness because review evidence
  refs were empty, review-session MCP tools were unavailable, gate profiles
  were missing, GitHub review/merge truth is not claimed, and an execute
  session reuse failure was observed.
- Loop 25z10b shows post-PR61 main can repeat the no-nudge groupchat-to-final
  hold path with durable Codex/OpenCode peer writeback. It is still not
  production readiness because `chat_dispatch_queue` execute dispatch failed
  on session reuse, review evidence refs remained empty, gate profiles were
  missing, and this was one bounded no-edit lane rather than broad coding-task
  completion.
- Loop 25z11 shows a candidate fix for the dispatch-session reuse gap. It is
  not production readiness by itself because review evidence refs remained
  empty, gate profiles were missing, and the run was still one bounded no-edit
  lane.
- Loop 25z12 shows the dispatch-session reuse fix survived PR #62 merge and a
  post-merge main rerun. It is still not production readiness because the
  reviewer self-verified instead of citing durable execution artifacts,
  `review_evidence_refs=[]`, gate profiles were missing, and the run remained
  one bounded no-edit lane rather than broad coding-task completion.
- Loop 25z13c/25z13d/25z13f show the current frontier is peer writeback and
  review verdict delivery. They are not production readiness because natural
  groupchat failed before proposal in 25z13c/25z13d, and downstream review
  failed with `review_peer_no_verdict` in 25z13f.
- Loop 25z14 narrows the review failure to a real codex-app-server review
  result shape without a parseable verdict. It is not production readiness
  because review still ended `gate_failed` and no review verdict was finalized.
- Loop 25z15 and Loop 25z16 show PR #65 fixed the app-server false-success
  shape, but the chain still ends `gate_failed` because OpenCode review is
  being attempted through Codex app-server and fails with
  `codex_app_server_error`.
- Loop 25z17 and Loop 25z18 show PR #66 moves configured OpenCode platform
  review onto the OpenCode process shim and reaches no-auto-merge final-action
  hold on both candidate branch and post-merge main. This is still not
  production readiness because review MCP tools were not exposed, review
  evidence refs remain weak, gate profiles were missing, and these were bounded
  no-edit lanes.

Required proof:

- Repeated stable fullchain runs, recovery behavior, server truth where
  relevant, and explicit operator acceptance criteria.

### G6. Proposal approval/projection lane authority

Status: merged through PR #57; post-merge runtime rerun still required.

Evidence:

- Loop 25r proved the failure on latest main after PR #56: the proposal lane
  `loop25r-main-package-boundary-final-hold` was projected as
  `res_f9801f1a12e745f6a61f5b28bb110969-lane-1`, with the lane prompt reduced
  to the approval summary and capabilities reduced to `["code"]`.
- Loop 25s used candidate branch
  `codex/proposal-approval-preserves-lane-graph` at base
  `e64d696d4b7240390617d559e2514941949a937c`, with local commit
  `dfebf9a fix: preserve proposal lane authority on approval`.
- Loop 25s accepted proposal
  `prop_626c370252014279ba648eaa3bbb4864` into resolution
  `res_5b884de2fbf44b558d6e51a1c685ba95` and projected lane
  `loop25s-proposal-authority-final-hold`.
- The projected lane preserved prompt authority, capabilities
  `["python", "pytest", "xmuse_mcp"]`, `review_runtime=opencode`,
  `final_action=no-auto-merge`, and `proof_boundary=local_runtime_proof`.
- The lane reached `awaiting_final_action` with hold
  `final-d4e8e0467a55`.
- Loop 25v integrated this candidate with the run-health and projected-worktree
  candidates. Approval of proposal
  `prop_404ac2c4fbfd4550baf4e42a0a5ffe4d` projected lane
  `loop25v-integrated-fullchain-final-hold` with the requested prompt,
  capabilities, `review_runtime=opencode`, `final_action=no-auto-merge`, and
  `proof_boundary=local_integrated_runtime_proof`; the lane reached
  `awaiting_final_action` with hold `final-e1681af6b91d`.
- PR #57 published this slice against `main`:
  `codex/proposal-approval-preserves-lane-graph` at
  `dfebf9a95d252ce57b45431b4e49be0ebeb3ae5f`. GitHub Actions `xmuse CI`
  completed successfully in run `27776606264`. GitHub reported
  `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`; branch protection
  required `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`, with no required PR reviews. GitHub accepted
  a normal squash merge as `09453e42924c61dcaad8e624874a1e03e113e5ab` at
  `2026-06-18T17:25:20Z`.

Required proof:

- Rerun the groupchat proposal/approval path from main after any merge.
- Preserve manual gaps for stale health blocker, chat dispatch session reuse,
  and review evidence refs until their own loops close them.
- Loop 25z6 satisfied the post-merge proposal/approval rerun for a bounded
  lane: approval of `prop_52d5bc3241524697b05e29cd8d0c7045` preserved the
  lane prompt, `review_runtime=opencode`, `final_action=no-auto-merge`, and
  `proof_boundary=local_runtime_proof`.

### G7. run_health process discovery for GOD peer decisions

Status: merged through PR #58; post-merge runtime rerun still required.

Evidence:

- Loop 25s architect raised blocker
  `collab_blocker_b61ddec99d9e40cc93ce45d788ceed9f` because
  `read_run_health` reported no live runner/MCP, even though services were
  alive and durable execute/review responses later landed.
- Loop 25t found that `build_run_health_snapshot()` disabled process discovery
  by passing empty PID sets and lists into `build_run_health_model()`.
- Loop 25t also found that runtime process classification did not recognize
  `xmuse-platform-runner`, `xmuse-mcp-server`, or
  `python -m xmuse.mcp_server` entrypoint forms.
- Candidate branch `codex/run-health-mcp-discovers-processes`, local commit
  `b05be1c fix: let run health discover live runtime processes`, fixed both
  issues.
- Real MCP `/sse` `read_run_health` call after the patch returned
  `runner_count=1`, `mcp_count=1`, and `warnings=[]`.
- Loop 25v integrated this fix into a real groupchat run. The stale
  no-live-runner/MCP blocker did not recur, but `peer_turn_mcp_tool_traces`
  recorded only chat tools, so there is still no durable peer-turn
  `read_run_health` trace for that run.
- Loop 25w2 applied the run-health discovery fix in the current worktree and
  verified it through real MCP `/sse` `read_run_health` while runner and MCP
  processes were alive: `runner_count=1`, `mcp_count=1`, `warnings=[]`.
- PR #58 published this slice against `main`. After PR #57 merged, the branch
  was rebased to `4f6a29a42f0f98708b6030ac226a2091445d46e8`. GitHub Actions
  `xmuse CI` completed successfully in run `27777358377`. GitHub reported
  `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`; branch protection
  required `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`, with no required PR reviews. GitHub accepted
  a normal squash merge as `ff5d61d8d77dbc7f776a904fd5861342895709ea` at
  `2026-06-18T17:27:39Z`.

Required proof:

- Rerun a real GOD architect collaboration that calls `read_run_health` before
  raising or declining a blocker.
- Keep blocker lifecycle timing and inbox race behavior as open until a
  groupchat rerun proves the stale blocker no longer appears.
- Loop 25z6 did not reproduce the stale no-live-runner/MCP blocker, but the
  groupchat peers did not record a durable `read_run_health` tool trace, so
  this gap remains open.

### G8. Projected lane worktree provisioning

Status: merged through PR #59; post-merge runtime rerun still required.

Evidence:

- Loop 25u2 combined the proposal-authority and run-health candidates and
  reached approval/projection, but execution failed before worker spawn with
  `FileNotFoundError` for the projected worktree path
  `/tmp/xmuse-loop-25u2-integrated-health-authority-fullchain-225325-exec`.
- Root cause: the projected lane carried a `worktree` field whose directory did
  not exist yet, and `ensure_lane_worktree()` tried to verify the existing
  branch before materializing the checkout.
- Integrated candidate commit
  `b9c6e31 fix: create missing projected lane worktree` creates or reuses the
  requested worktree path before branch verification.
- Loop 25v reran after the fix and dispatched a real `codex exec` worker in
  `/tmp/xmuse-loop-25v-integrated-fullchain-after-worktree-fix-230627-exec`.
  The lane reached `awaiting_final_action` with no file edits in the execution
  worktree.
- PR #59 published this slice against `main`. After PR #58 merged, the branch
  was rebased to `ef3836041fb95ab0e0102b95d62b02f2efa8fbac`. GitHub Actions
  `xmuse CI` completed successfully in run `27777469922`. GitHub reported
  `mergeable=MERGEABLE` and `mergeStateStatus=CLEAN`; branch protection
  required `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`, with no required PR reviews. GitHub accepted
  a normal squash merge as `6058002cc039345a7780f7f04e28bc2b2e3122fc` at
  `2026-06-18T17:30:02Z`.

Required proof:

- Rerun the integrated groupchat-to-final-hold path from main after merge.
- Keep child MCP fallback, review evidence refs, and latency trace gaps open.
- Loop 25z6 satisfied the projected-worktree part of this proof on current
  main: the configured execution worktree path did not exist before dispatch
  and was materialized as a populated git worktree at head `6058002`.
  The integrated chain did not reach final-action hold because configured
  OpenCode platform review failed with `session_layer_unavailable`.

### G9. Persistent review artifact grounding and provider MCP exposure

Status: partially improved by PR #71 candidate; MCP exposure still open.

Evidence:

- Loop 25z27b on main reached configured OpenCode review and final-action hold
  with non-empty `review_evidence_refs`, but the review summary incorrectly
  stated that logs and gate artifacts did not exist.
- Candidate branch `codex/review-peer-artifact-grounding` at `cd71375` adds
  prompt/context grounding for gate report refs, gate summary, worker refs, and
  lane context refs.
- Loop 25z28 reran the same bounded chain on that branch and the OpenCode
  review summary cited the gate report, worker stdout/result logs, lane context
  bundle, git diff, and git status before emitting a verdict.
- PR #71 is an open draft small PR against `main`; GitHub Actions run
  `27795048428` completed successfully for the three configured jobs.

Remaining manual gaps:

- OpenCode review provider still reports MCP unavailable and uses stdout
  fallback. This is not review truth.
- Duplicate proposal emission remains open.
- Peer session health still reports `starting` despite durable responses.
- PR #71 is draft/open/unmerged; no GitHub review truth, merge truth,
  `ready_to_merge`, or `pr_merged` is claimed.

## Forbidden Claims Still Preserved

```text
github_review_truth
ready_to_merge
live_memoryos
worker_output_is_review_truth
local_tests_are_review_truth
broad_server_side_truth
broad_merge_truth
full_l8_l10_closure
full_l1_l11_closure
overnight_readiness
natural_peer_god_groupchat_production_ready
```
