# xmuse Production Closure Gap Ledger

Updated: 2026-06-20.

This ledger records the current implementation proof boundary for the real
GOD chatgroup and demand-to-completion chain. It is not a readiness claim.

## Current Proof Boundary

- Latest main inspected: `019f580674eb731787c3f21a23122c53968b8953`
  (`origin/main`, PR #147 merge; PR #43 remains closed/draft/unmerged with
  head branch preserved). Latest focused dynamic-member OpenCode provider-resume proof
  remains Loop 28e from pre-PR144 main head
  `363229d3296d35e5da0d3533008a29b19685c720`: Chat API, MCP, and
  `xmuse.platform_runner --peer-chat` ran with a dynamically added OpenCode
  reviewer, two human mentions, and a runner restart between turns. Both turns
  produced durable writebacks with `degraded_reason=null`, the same
  `god_session_id` restored after restart, and the second turn reused
  `provider_session_id=ses_11bbe39bdffeIgPpauTAgyu7Im` with
  `provider_binding_status=active`. This closes the focused dynamic-member
  provider-resume boundary as local runtime proof only. It does not prove
  fullchain demand completion, production readiness, live MemoryOS, GitHub
  review truth, live lane merge truth, repeated soak, or full closure.
- Latest candidate Ray/MCP app-server non-docs code-change fullchain proof is
  Loop 28n on branch `codex/ray-mcp-codechange-head-evidence`, based on
  `origin/main` `019f580674eb731787c3f21a23122c53968b8953`. The real
  groupchat produced collaboration run
  `collab_28ac5266c7004201b0d14edf78c72571`, execute response
  `collab_resp_eee868fc716442d897294022b02df428`, exactly one accepted
  lane-graph proposal `prop_5f219cdd2b9e4200b6351e4d3db3ba09`, proposal
  review PASS, approval, dispatch acknowledgement, isolated execution,
  gate pass, persistent OpenCode review, finalized verdict
  `verdict-merge-rtask_16b31833348d446bb7d9c72469455a4f`, and pending
  final-action hold `final-4b6e9294a75c`. The candidate changed only
  `scripts/run_fullchain_docs_sentinel.py` and
  `tests/xmuse/test_fullchain_docs_sentinel.py` to record `repo_head_sha` in
  sentinel command artifacts. Driver exit was `2` because the one-off driver
  parsed `git status --porcelain` with a bad slice and reported a false
  `cripts/...` path; manual audit artifact
  `loop_driver_artifacts/manual_candidate_audit.json` confirmed the real
  changed-file set was exactly the two expected files and cleanup found no Chat
  API or MCP listener. This is candidate-branch local runtime proof only; it
  is not merged-main proof, server CI proof, production readiness, live
  MemoryOS, GitHub review truth, live lane merge truth, repeated soak,
  fullchain product completion, or full closure.
- Latest post-merge main Ray/MCP app-server fullchain proof is Loop 28m from
  main head `4cdc9c756924b806d10cf960e66144033d8bfd15` after PR #146 merged.
  The sentinel ran with `--peer-god-backend ray --ray-god-mcp` and
  `peer_chat_post_writeback_grace_s=30.0`; `commands.json` recorded
  `peer_god_backend=ray`, `ray_god_mcp=true`, Chat API port `45247`, and MCP
  port `50087`. The platform log shows
  `Peer chat scheduler enabled (god_backend=RayGodSessionLayer)`. The durable
  chain produced one collaboration run
  `collab_528370bd49ec4f959b6b1db2b23dd63d`, one
  `chat_record_collaboration_response`, one accepted lane-graph proposal
  `prop_5a683380ddf34a8daf46fe7339363b1c`, OpenCode proposal review
  writeback, approval, dispatch handoff acknowledgment, isolated docs
  execution, gate pass, persistent OpenCode review, finalized verdict
  `verdict-merge-rtask_4cec538df5234b5ca21c86ab4d38edef`, and pending
  final-action hold `final-56ae19d3dacd`. The isolated execution artifact
  matched
  `/tmp/loop-28m-post-pr146-ray-mcp-sentinel-20260620T1025Z-exec/docs/xmuse/loop_28m_post_pr146_ray_mcp_sentinel_20260620T1025Z.md`.
  All reusable sentinel success checks were true, and cleanup confirmed the
  Chat API and MCP ports were no longer listening. This is post-merge main
  local runtime proof for the docs-only sentinel shape; it is not server CI
  proof for the runtime artifact, production readiness, live MemoryOS, GitHub
  review truth, live lane merge truth, repeated soak, fullchain product
  completion, or full closure.
- Latest candidate Ray/MCP app-server proof before merge was Loop 28l on branch
  `codex/fullchain-sentinel-peer-backend-config`; PR #146 merged that repair to
  main after GitHub Actions run `27868290309` succeeded for head
  `eaa9e1a76ab99812eae2890db176950293abace3`.
- Previous post-merge main reusable fullchain sentinel proof was Loop 28f from
  main head `e235b9be7b7ebb6c643b9713a2fb1333f009634c` after PR #144. The
  reusable sentinel ran with `peer_chat_post_writeback_grace_s=8.0`, completed
  human demand to Codex architect, Codex execute collaboration, one durable
  lane-graph proposal, OpenCode proposal review, approval, dispatch, isolated
  docs execution, gate, persistent OpenCode review verdict, and final-action
  hold. All driver success checks were true, including one related proposal,
  configured execute handoff, gate pass, finalized review verdict, isolated
  note match, and pending final-action hold. Residual boundary: two Codex
  architect tool-writeback turns still recorded
  `peer_writeback_before_provider_result`. This is bounded post-merge main
  runtime proof for the docs-only sentinel shape; it does not prove production
  readiness, live MemoryOS, GitHub review truth beyond inspected PR/main check
  facts, live lane merge truth, repeated soak, fullchain product completion, or
  full closure.
- Latest provider-native OpenCode session evidence: PR #142 merged native
  provider-session binding to main as
  `2fde89eda05b6a34da9364bb0b9a426c1c0749b0`, with successful PR CI
  `27865756181` and successful post-merge main CI `27865780027`. Loop 28b then
  ran a focused two-turn real OpenCode probe from that main head. The first
  turn persisted
  `provider_session_id=ses_11bd29d58ffe2SlCF666g6EGe2` in
  `god_sessions.json` with `provider_session_kind=opencode_session` and
  `provider_binding_status=active`. After aborting the local shim and creating
  a fresh native `GodSessionLayer`, the same
  `god_session_id=god-439c97c471694fd2a70db80c515ff7aa` was restored, the
  second turn reused the provider session, and provider stdout contained a
  `sessionID`. This is post-merge main focused provider-session proof, not
  fullchain groupchat-to-lane proof or production readiness.
- Latest natural groupchat proposal evidence: Loop 27h recorded collaboration
  run `collab_ecd70e7a9edb4719ae8ea881b4f88177` with targets `@execute` and
  `@review`, `status=done`, and two peer responses. Architect proposal
  `prop_08dd65de7b444c82b2e93a8024424ccf` referenced the collaboration run,
  was approved, and projected feature
  `loop_27h_natural_groupchat_proposal_20260620t045459z`. The lane reached
  `awaiting_final_action` with `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_peer_cli_kind=opencode`, and
  `review_peer_model=opencode-go/deepseek-v4-flash`. The isolated execution
  note matched the required content, and cleanup found no Chat API or MCP
  listener.
- Latest local dynamic-member context evidence: Loop 27d on branch
  `codex/groupchat-context-capsule-proof` confirmed that a dynamically added
  OpenCode review participant mentioned by `@participant:<id>` receives a
  scheduler provider context containing `xmuse-local-context-capsule-v1`,
  recent messages including the prior human demand and roster event, the full
  active roster including itself, and an auditable
  `xmuse-peer-chat-prompt-v2` layer order. No code patch was needed for this
  boundary. This is local prompt/context delivery evidence only; it does not
  prove live provider resume, durable writeback for that dynamic member,
  natural peer-GOD completion, production readiness, live MemoryOS, GitHub
  review truth, or full closure.
- Latest post-PR124 fullchain sentinel evidence: Loop 26x ran from current
  main `050385b32ce62c6868773555271f25b8debe26f8` after PR #121, PR #123,
  and PR #124 landed. The docs-only runtime sentinel reached
  `awaiting_final_action` with `gate_passed=true`, `review_decision=merge`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`,
  `review_peer_cli_kind=opencode`,
  `review_peer_model=opencode-go/deepseek-v4-flash`, and all sentinel success
  checks true. The durable chain includes human request, Codex architect,
  Codex execute peer, OpenCode review peer, collaboration run
  `collab_6cac3eac965d4821bc019470084d11df`, lane proposal
  `prop_0c8c276523bf4b739a6a936a40d34c04`, approved resolution
  `res_22c0304fb52841a58733749759a447d2`, isolated execution artifact, gate
  report, review task `rtask_9d7ea699c64c429d9e28ec29bef8a118`, finalized
  review verdict, and pending final-action hold `final-510ce5ed0227`.
  Cleanup reported no Chat API or MCP listener. This is bounded docs-only
  fullchain runtime proof for the sentinel shape, not production readiness,
  natural peer-GOD groupchat completion, live MemoryOS, GitHub review truth,
  live lane merge truth, or full closure.
- Latest configured-review-peer degradation evidence: PR #121 merged the
  configured review peer fail-closed repair to main as
  `1adc2d19089aeacad5953bc577ca093f3441a761` after successful PR CI and
  successful post-merge main CI. Focused RED evidence showed preferred
  configured peer failures could previously continue through
  `auto_persistent_fallback` or `one_shot_fallback` and reach a merge verdict.
  The merged behavior transitions the lane to `gate_failed` with
  `failure_layer=review`, `peer_delivery_mode=configured_peer_failed`,
  `failure_reason=review_peer_delivery_failed` for delivery/no-verdict
  failures, or existing `required_review_peer_unavailable` for unavailable
  peers. Loop 26t attempted the docs-only fullchain sentinel from base main
  `24fc168672a90de8dd56d512269fee4e021dfeff` and produced a durable
  conversation, proposal, and approved resolution, but execution stopped
  before review because the child Codex execution worker hit external
  `usage_limit`; the lane ended `exec_failed` with
  `failure_reason=execution_infra_unavailable`. Loop 26x later reran the
  docs-only sentinel from post-PR124 main and reached final-action hold with
  persistent OpenCode review. This is bounded main evidence for the configured
  review peer authority boundary plus post-merge sentinel non-regression, not
  production readiness, GitHub review truth, or full closure.
- Latest fullchain sentinel harness evidence: PR #123 merged the
  `exec_failed` terminal-state repair for
  `scripts/run_fullchain_docs_sentinel.py` to main as
  `162da10f4ef1d515a95ea9fc90889494c8e75146` after successful PR CI and
  successful post-merge main CI. Loop 26t showed the previous harness kept
  waiting after a lane had already reached `exec_failed` from
  `execution_infra_unavailable`, forcing manual interruption and cleanup. This
  is a loop-efficiency/harness repair only; it does not change product runtime
  authority or provide fullchain success evidence.
- Latest peer-reply dependency-set evidence: PR #117 merged the direct
  `peer_reply_drain_callback` coordination repair to main as
  `f3f7b6dafa94ceae179af26c448f1aae183fd24b` after successful PR CI and
  successful post-merge main CI. The repair scopes pending replies to the
  durable source handoff message, records
  `dependency_set_id=peer-reply-set:<source_message_id>`,
  `source_message_id`, and `dependency_targets`, and avoids sender-global
  draining across independent handoffs. Loop 26p preserves the local pre/post
  durable-store probe: before the fix, one independent unread review handoff
  blocked the callback for a completed execute handoff; after the fix, the
  execute callback emitted while the unrelated review inbox stayed unread.
  Loop 26q then ran from post-PR117 main and reached `awaiting_final_action`
  with `gate_passed=true`, `review_decision=merge`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`,
  `review_peer_cli_kind=opencode`, and all sentinel success checks true. This
  is bounded main evidence for a direct handoff-message dependency set, not a
  general workflow dependency planner, production readiness, natural peer-GOD
  groupchat completion, or full closure.
- Latest default-review authority evidence: PR #119 merged the legacy
  empty-conversation Codex default-review auto-create removal to main as
  `353f61e442ffcae3a97377f54b44b9094e1ebb10` after successful PR CI and
  successful post-merge main CI. Focused RED evidence in Loop 26r showed the
  old path ensured a Codex review session when a conversation had no active
  OpenCode reviewer. The merged behavior fails closed as
  `required_review_peer_unavailable` with
  `peer_degraded_reason=review_peer_runtime_unavailable`, creates no Codex
  review participant, and does not invoke one-shot review. Loop 26s then ran
  from post-PR119 main with a registered OpenCode reviewer and reached
  `awaiting_final_action` with `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_peer_cli_kind=opencode`, and all
  success checks true. This is bounded main evidence for the default reviewer
  authority boundary, not production readiness, GitHub review truth, or full
  closure.
- Latest collaboration delivery lifecycle evidence: PR #115 merged the
  collaboration request/response/callback inbox lifecycle repair to main as
  `87c6f131d7a9851f1a4c5b023b192323ad8e73e4` after successful PR CI and
  successful post-merge main CI. Loop 26o then ran from that post-merge main
  and reached `awaiting_final_action` on a docs-only fullchain sentinel. The
  durable collaboration run `collab_fd442c340eed442fa393fdfd6df0d768` was
  `done`, target `@execute` recorded a formal response, the collaboration
  request inbox ended `read` with a `chat_record_collaboration_response`
  trace, the collaboration callback inbox ended `read` with a
  `chat_emit_proposal` trace, the dispatch inbox ended `read` with a
  `chat_post_message` trace, and the lane recorded `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_peer_cli_kind=opencode`, and
  `status=awaiting_final_action`. Loop 26m is the preserved pre-fix failure
  evidence: the same fullchain shape reached final-action hold while leaving
  stale unread collaboration request/callback inbox items. This is bounded
  local runtime proof plus inspected GitHub server facts for the small PR; it
  is not production readiness, live MemoryOS, GitHub review truth, natural
  peer-GOD groupchat completion, or full closure.
- Latest post-PR102 main fullchain evidence: PR #102 merged the
  `chat_mention` current-turn auto-bind fix to main as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` after successful PR CI and
  successful post-merge main CI. Loop 25z78 then ran from that post-merge main
  and drove the same docs-only real chain through durable groupchat, execute
  feasibility, proposal, approval, dispatch, isolated execution, gate,
  persistent OpenCode review, and final-action hold. The original architect
  inbox recorded `status=read`, `tool_trace=chat_mention`,
  `delivery_mode=mcp_writeback`, and a non-null `responded_message_id`; all
  inbox items ended `read`; the lane recorded `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_peer_defaulted=true`,
  `review_peer_cli_kind=opencode`,
  `review_peer_model=opencode-go/deepseek-v4-flash`,
  `peer_delivery_mode=configured_peer`, and `status=awaiting_final_action`.
  This is bounded local runtime proof plus inspected GitHub server facts for
  the small PR, not production readiness or full closure proof.
- Strongest code-change lane runtime evidence: Loop 25z69 ran after PR #93's
  default-review fix from current main, drove one real local code-change lane
  from durable groupchat through execute feasibility, proposal, runtime-driver
  approval, isolated execution, xmuse-core gate, persistent OpenCode review,
  and final-action hold under `--no-auto-merge`. The proposal intentionally
  omitted `review_runtime`; the lane recorded `proposal_has_review_runtime=false`,
  `review_peer_defaulted=true`,
  `review_peer_participant.cli_kind=opencode`,
  `review_peer_participant.model=opencode-go/deepseek-v4-flash`,
  `peer_delivery_mode=configured_peer`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `gate_passed=true`,
  `review_decision=merge`, and `status=awaiting_final_action`. PR #94 landed
  the review-peer runtime metadata candidate from that loop.
- Earlier post-merge fullchain evidence: Loop 25z74 ran after PR #98's merged
  main plus PR #99's local branch fix, intentionally pre-created an empty
  execution worktree, and reached `awaiting_final_action` on one docs-only
  fullchain lane with `proposal_has_review_runtime=false`, `gate_passed=true`,
  `review_decision=merge`, and `review_summary=review accepted`. The run used
  `review_delivery_mode=one_shot_fallback` with
  `persistent_review_degraded=true` and
  `persistent_review_degraded_reason=missing_feature_identity`, so it is not
  persistent OpenCode review proof or defaulted review peer metadata proof.
- Latest direct lane graph feature-scope evidence: Loop 25z75 locally proved
  the direct lane graph `feature_scope_id` fix, then PR #101 merged the small
  fix to main as `cae16e00429a4f97e30a07ecb69e5cd977ea16e8` after successful
  PR CI and successful post-merge main CI. Loop 25z76/25z77 both ran from that
  post-merge main, so `missing_feature_identity` is no longer the current
  blocker for this docs-only fullchain shape.
- Latest peer-chat stability evidence: Loop 25z70b ran concurrently with
  Loop 25z70a from the same current main using a separate `XMUSE_ROOT`,
  execution worktree, Chat API port, MCP port, and runner. Across three
  Codex/OpenCode groupchat conversations, each conversation reached human
  demand to Codex architect handoff, Codex execute reply, OpenCode review
  reply, durable peer-reply drain callback, and architect final summary after
  both replies. The aggregate result was `all_final_after_both=true`,
  `all_callbacks_created=true`, `all_callbacks_consumed=true`,
  `no_proposals_or_resolutions=true`, `no_open_or_failed_inbox=true`,
  `no_failed_or_timeout_traces=true`, `total_failed_traces=0`, and
  `total_timeout_after_writeback_traces=0`.
- Latest scoped process-health evidence: PR #96 merged the small fix that
  scopes runtime process discovery by `XMUSE_ROOT`/`--xmuse-root` for
  `run_health`, dashboard/TUI read models, and the platform runner's
  `--health-once` path. Loop 25z71 reran two isolated local shards and each
  shard's health snapshot reported `runner_count=1`, `mcp_count=1`,
  `counts_by_service.chat_api=1`, and `warnings=[]`. This makes higher
  operator-level parallelism less noisy; it is still bounded health
  observability proof, not production readiness or soak.
- Latest higher-parallelism evidence: Loop 25z72 ran three isolated local
  shards concurrently. Two stability shards completed six total Codex/OpenCode
  groupchat conversations with final summaries after execute and review
  replies, all callbacks consumed, no proposals/resolutions, no open/failed
  inbox items, and no failed/timeout traces. The fullchain shard exposed an
  empty execution worktree gate failure that PR #98 later fixed.
- Latest lane worktree recovery evidence: PR #98 merged the small fix that
  treats an existing empty lane worktree directory as uninitialized and
  recreates it as a git worktree. Loop 25z73 intentionally pre-created an
  empty execution worktree and verified `exec_is_git_worktree=true`,
  `exec_gate_profiles_exists=true`,
  `base_head_sha=591aa68e470aa5272df5bc46bbfab06a917bd4f4`, and
  `gate_passed=true`.
- Latest review diff authority evidence: PR #99 merged the small fix that
  includes untracked new files in MCP `get_diff(lane_id)` by appending
  `git diff --no-index -- /dev/null <path>` patches. Loop 25z74 then moved the
  same docs-only fullchain shape from Loop 25z73's review rework to
  `review_decision=merge` and `status=awaiting_final_action`.
- Latest default review authority evidence: PR #93 merged the small fix that
  reuses a unique active OpenCode review participant when the proposal omits
  `review_runtime`. GitHub server state reports PR #93 merged as
  `7468a5ab8797cf0a34528de419ceaf730034e75e` after successful PR checks on
  head `bc2be0e6e42a208d0e45a1a1d023723b4bfce194`, and post-merge main CI
  passed on `7468a5ab8797cf0a34528de419ceaf730034e75e`. Loop 25z69 then
  reran a real code-change lane from that main and confirmed defaulted
  persistent OpenCode review locally. This is still bounded local runtime proof
  plus inspected GitHub server facts for the small PR, not GitHub review truth
  or production readiness.
- Latest review peer observability evidence: PR #94 merged the small fix that
  persists `review_peer_cli_kind` and `review_peer_model` on configured/default
  review peer lanes and exposes those fields in run health summaries. GitHub
  server state reports PR #94 merged as
  `2996643e4f13a8ea97af6b6f9675fd697a847716` after successful PR checks on
  head `d29c6f434fb22974ba477a1267cf3e3c9b35a8f5`, and post-merge main CI
  passed on `2996643e4f13a8ea97af6b6f9675fd697a847716`. Loop 25z70a then
  verified the metadata in a real post-merge fullchain lane's run health
  summary.
- Review-state repeat evidence: Loop 25z65 reran a docs-only lane from
  current `origin/main` at `a8cceabb51022ddf802da276df1e4c37419b65b5` and
  reached `awaiting_final_action` with `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, `review_decision=merge`, and no
  runtime-artifact match for the Loop 25z64 invalid transition noise. This is a
  bounded local repeat, not code-change soak or production readiness.
- Strongest server facts: PR #102 was merged by GitHub server state as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` after successful `xmuse CI` on PR
  head `d4728c36cb252899a5631d3e0686fee4fb4c47cb` in run `27831639110`;
  post-merge main `xmuse CI` also passed on
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3` in run `27831706622`.
- Latest merged evidence sync: PR #100 `codex/post-pr99-runtime-evidence-sync`
  merged to main as `f03a058a0f0468e3902e2aafeb7b063601df2866`; PR #101
  subsequently merged the direct lane graph feature-scope implementation, and
  PR #102 subsequently merged the peer handoff writeback lifecycle fix.
- Proof type: local runtime proof plus inspected GitHub server facts for small
  PRs. This is not GitHub review truth or production readiness.

## Recent Small PR Slices

- PR #76 `codex/human-leading-mention-routing`: routed leading human mentions
  without treating body references as direct human inbox targets. Merged to
  main as `0d980be69f953b77a82c035abadc40f31797942d`.
- PR #77 `codex/real-code-lane-after-pr76`: made peer-chat runtime worktree
  repo-backed and exposed gate profile source in gate reports. Merged to main
  as `5a8b40654f934b422cb559b4a64d89a981d72a30`.
- PR #78 `codex/session-health-writeback-status`: promoted durable peer
  session health after authenticated writeback and preserved active runtime
  details in inspector output. Merged to main as
  `c5818ba433142765c817bc63fed73ec40141ae06`.
- PR #79 `codex/post-pr78-evidence-sync`: recorded the post-PR78 fullchain
  evidence boundary. Merged to main as
  `3a4ec2853ea2099f648513bbb0856415de81b906`.
- PR #80 `codex/strict-leading-mention-routing`: fixed leading role mentions
  such as `@architect Coordinate...`. Merged to main as
  `c02e9dce50b808bbd4aed1ab6d1960e32ca6472b`.
- PR #81 `codex/review-runtime-from-chat-peer`: normalized observed
  groupchat-produced review aliases such as `human_final_hold`, `final_hold`,
  and `review-god` to the active OpenCode review runtime. Merged to main as
  `ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8`.
- PR #82 `codex/post-pr81-fullchain-rerun`: canonicalized explicit
  `OpenCode` provider casing to the active `opencode` review runtime and
  recorded Loop 25z46/25z47/25z48 evidence. Merged to main as
  `94218b269e4a005049e18378ebdc179c1dcada28`.
- PR #83 `codex/post-pr82-code-lane-rerun`: exposed participant session
  mappings in conversation create/bootstrap responses and recorded Loop 25z49
  code-change evidence. Merged to main as
  `6c962708071895e94458ff947eaed8753c789ce0`.
- PR #84 `codex/post-pr83-scheduler-parallelism`: made durable MCP writeback
  authority outrank provider process exit for peer-chat delivery
  classification, added bounded peer-chat scheduler fan-out, and recorded Loop
  25z50/25z51/25z52 evidence. Merged to main as
  `744aee7d3215ff9b772b677a77304fb36570f878`.
- PR #85 `codex/post-pr84-final-summary-gating`: added
  `chat_mention(reply_to_inbox_item_id=...)`, direct peer-reply drain
  callbacks, and early durable-writeback release with a short grace window.
  Merged to main as `e6eeeddf5911a171bf32dc38b839fa2e7c51d62d`.
- PR #86 `codex/post-pr85-evidence-sync`: synced the post-PR85 closure
  evidence boundary. Merged to main as
  `a6575c01613e7568248e64c06a4799deb83a3b71`.
- PR #87 `codex/peer-chat-writeback-grace-tuning`: made peer-chat
  post-writeback grace configurable and defaulted it to a longer bounded wait.
  Merged to main as `17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f`.
- PR #88 `codex/post-pr87-runtime-audit`: serialized peer-chat delivery per
  target participant/session, tightened simple reply guidance, and recorded
  post-PR87 runtime evidence. Merged to main as
  `71ba128edfadbaea7ca45ea288e1ee5faf92e6b9`.
- PR #89 `codex/inspector-provider-summary`: added
  `participants.provider_summary` to the conversation inspector and recorded
  Loop 25z64 fullchain evidence. Merged to main as
  `8e9ae4d887f243723561a4ebe01e5ea1817c4963`.
- PR #90 `codex/review-state-idempotence`: ignored late rejected/rework review
  conflicts after accepted review/final-hold state and recorded Loop 25z65
  repeat evidence. Merged to main as
  `a8cceabb51022ddf802da276df1e4c37419b65b5`.
- PR #91 `codex/post-pr90-evidence-sync`: synced post-PR90 runtime evidence
  and gap ledger updates. Merged to main as
  `ff6a5fd9f61b86d5c1989fd6f613bcf5e6906009`.
- PR #92 `codex/post-pr91-parallel-stability-evidence`: recorded the
  post-PR91 two-shard parallel stability evidence. Merged to main as
  `9f19d84aeeb52043517a40e0c29f72edda2366a6`.
- PR #93 `codex/default-review-opencode-peer-routing`: defaulted review
  routing to a unique active OpenCode review peer when the proposal omitted
  `review_runtime`. Merged to main as
  `7468a5ab8797cf0a34528de419ceaf730034e75e`.
- PR #94 `codex/review-peer-runtime-metadata`: persisted configured/default
  review peer runtime metadata on lanes and exposed it in run health summaries.
  Merged to main as `2996643e4f13a8ea97af6b6f9675fd697a847716`.
- PR #95 `codex/post-pr94-parallel-runtime-evidence`: recorded the post-PR94
  parallel runtime evidence from Loop 25z70. Merged to main as
  `0f35f9ad33c6e701b1457b0e5aaa22bc2093e0c4`.
- PR #96 `codex/scoped-runtime-process-health`: scoped runtime process health
  discovery by `XMUSE_ROOT`/`--xmuse-root` for parallel shards and recorded
  Loop 25z71 evidence. Merged to main as
  `dcf4badf5da82cb472ea0f23d1c825f94d26218b`.
- PR #97 `codex/post-pr96-scoped-health-evidence`: recorded Loop 25z71 scoped
  process-health evidence. Merged to main as
  `591aa68e470aa5272df5bc46bbfab06a917bd4f4`.
- PR #98 `codex/recreate-empty-lane-worktree`: recreated empty projected lane
  worktree directories as git worktrees and recorded Loop 25z73 evidence.
  Merged to main as `cae76c1da7d1c38df9884579ba822b8019f3b197`.
- PR #99 `codex/include-untracked-lane-diff`: included untracked new files in
  MCP `get_diff(lane_id)` and recorded Loop 25z74 evidence. Merged to main as
  `2325427c0b96f5bc2f804a6f72ef8d5e77782fca`.
- PR #100 `codex/post-pr99-runtime-evidence-sync`: synced post-PR99 runtime
  evidence into the docs and gap ledger. Merged to main as
  `f03a058a0f0468e3902e2aafeb7b063601df2866`.
- PR #101 `codex/direct-lane-graph-feature-scope`: projected
  `feature_scope_id` for direct lane graphs without using lane primary
  `feature_id` as feature scope. Merged to main as
  `cae16e00429a4f97e30a07ecb69e5cd977ea16e8`.
- PR #102 `codex/peer-mention-writeback-autobind`: auto-bound
  `chat_mention` over MCP `/sse` to the participant's single claimed inbox
  item when `reply_to_inbox_item_id` is omitted, preserving explicit
  writeback for real peer handoffs. Merged to main as
  `c44a5caf247c2c049ae5af37d74a94f5b9f95ce3`.

## Manual Gaps

- Default review peer selection for the case where the conversation already
  has exactly one active OpenCode review participant is now present on main
  through PR #93. Ambiguous, missing, or inactive review participants remain
  bounded behavior and must not be reported as general review authority proof.
- Review peer runtime identity is now observable in lane metadata and run
  health summaries through PR #94, but those fields are metadata only.
  `peer_delivery_mode`, `review_delivery_mode`, and durable callback evidence
  remain the delivery authority.
- Groupchat-produced `review_runtime` aliases such as `human_final_hold`,
  `final_hold`, and `review-god` are addressed by PR #81. Explicit provider
  casing such as `OpenCode` is addressed by PR #82.
- Loop 25z57 locally verified bounded final-summary gating across two
  conversations; the code/docs carrying that evidence are now in PR #85's
  merged server state.
- The successful Loop 25z49 chain covered one small API ergonomics lane; it is
  not repeated code-change soak or production-load proof.
- Loop 25z57 proved one bounded local final-summary path with a direct
  peer-reply drain callback. It is not repeated soak and not production
  readiness.
- Loop 25z63 proved one bounded local six-conversation peer-chat stability path
  after local same-participant delivery serialization and prompt reply-contract
  mitigation. It is not repeated soak and not production readiness.
- Loop 25z70 proved one bounded local two-shard parallel runtime path after
  PR #94: one fullchain docs-only lane plus one three-conversation stability
  shard. It is not repeated soak, not overnight readiness, and not production
  readiness.
- Loop 25z71 repaired the process-health false positives exposed by Loop
  25z70. Scoped process discovery now reports the shard-local runner, MCP
  server, and Chat API without duplicate-runner or missing-MCP warnings for
  the two-shard harness. This is observability proof only; it is not a broader
  scheduling, capacity, or production-load claim.
- Loop 25z72 proved six groupchat-only conversations across two concurrent
  stability shards, while the concurrent fullchain shard failed at gate because
  an empty pre-created execution worktree was treated as initialized. This was
  a real runtime gap, not a proof of fullchain failure after PR #98/#99.
- Loop 25z73 verified empty execution worktree recovery through gate pass, then
  exposed that review could not see untracked new files through
  `get_diff(lane_id)`. PR #99 addresses that specific diff authority gap.
- Loop 25z74 reached final-action hold after the untracked diff fix, but it
  used `review_delivery_mode=one_shot_fallback` with
  `persistent_review_degraded_reason=missing_feature_identity`. Persistent
  OpenCode review and defaulted review peer metadata remain unproven for this
  shape.
- Loop 25z75 locally repaired the direct lane graph feature-scope gap and
  reached final-action hold with persistent OpenCode review/defaulted peer
  metadata. PR #101 then merged that small fix and post-merge main CI passed.
- Loop 25z76 exposed a peer-chat writeback lifecycle gap after PR #101:
  `chat_mention` over `/sse` could omit `reply_to_inbox_item_id`, enqueue the
  execute peer, and leave the architect's source inbox to fail with
  `peer_response_timeout`.
- Loop 25z77 locally repaired that `chat_mention` current-turn auto-bind gap
  and reran the fullchain to final-action hold with no failed inbox items.
  PR #102 then merged the fix, and Loop 25z78 reran the same fullchain shape
  from post-merge main with no failed inbox items.
- Loop 26c2 reran the docs-only fullchain sentinel from post-PR105 main
  `8df4415c0586b04adffb4bc30806f9e205b04a12` after the layered peer-chat
  prompt contract landed. It reached `awaiting_final_action` with
  `gate_passed=true`, `review_decision=merge`,
  `review_delivery_mode=persistent`, `persistent_review_degraded=false`,
  `peer_delivery_mode=configured_peer`, and OpenCode review peer metadata.
  Architect and execute sessions carried `xmuse-peer-chat-prompt-v2` layered
  prompt fingerprints. This is bounded local runtime proof only; it is not
  production readiness, restart/resume proof, MemoryOS proof, or full closure.
- Loop 26c2 also exposed a remaining observability gap: the OpenCode review
  participant was used as the configured persistent review peer, but the
  `god_sessions.json` review record did not carry a layered prompt contract
  fingerprint. Do not claim uniform prompt-contract persistence across all
  peer roles until that boundary is proven or intentionally split.
- Loop 26d locally repaired that configured OpenCode persistent review
  observability gap for the bounded docs-only fullchain shape. The review
  session now records `xmuse-persistent-review-session-prompt-v1` with
  `persistent_review_session_identity` in `god_sessions.json`, while the lane
  reached `awaiting_final_action` with persistent review and
  `persistent_review_degraded=false`. This is bounded local runtime proof only;
  it does not claim natural peer-chat review turns, production readiness,
  restart/resume proof, MemoryOS proof, or full closure.
- Loop 26e reran the same shape from post-PR107 main
  `91ee4f76e9f4ec3bc0627aa690a2dababcde91ad` after main CI passed. The chain
  again reached `awaiting_final_action` and the review session carried
  `xmuse-persistent-review-session-prompt-v1`. This confirms the PR #107 repair
  on current main for the bounded configured OpenCode review path only.
- Loop 26f on branch `codex/default-review-ambiguous-fail-closed` focused the
  ambiguous default review authority boundary. With two active OpenCode review
  participants in `chat.db` and no proposal `review_runtime`, the selector now
  returns `review_peer_runtime_ambiguous`, does not create a Codex review
  participant, and the review-plane consumer fails the lane closed as
  `required_review_peer_unavailable`. This is focused local
  review-authority proof only, not a fullchain run or production readiness.
- Loop 26g on branch
  `codex/default-review-missing-opencode-roster-fail-closed` focuses the
  missing OpenCode review authority boundary for a production-like peer roster.
  When active Codex architect/executor participants exist but no active
  OpenCode review participant exists, the selector now returns
  `review_peer_runtime_unavailable`, does not create a Codex review
  participant, and the review-plane consumer fails the lane closed as
  `required_review_peer_unavailable`. Empty legacy conversations without an
  active peer roster still retain the feature-scoped Codex default-review
  fallback.
- Loop 26h ran after PR #110 merged to main as
  `1614cc9dca8e28771ea15a8737d88ffb38f73ba0` and confirmed the positive
  default review route still selects a unique active OpenCode review
  participant. The focused route reached `awaiting_final_action` with
  `review_peer_cli_kind=opencode`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, and
  `peer_delivery_mode=configured_peer`. This is focused review-route evidence,
  not a fullchain run or live OpenCode CLI proof.
- Loop 26m exposed a structured collaboration lifecycle gap after
  `chat_create_collaboration_request` became a durable message/inbox producer:
  a fullchain docs sentinel reached final-action hold, but the execute
  `collaboration_request` inbox and architect `collaboration_callback` inbox
  remained `unread`. Loop 26n locally repaired that candidate path by marking
  the formal response as consumption of the request inbox and marking a
  proposal with `collaboration:<run_id>` as consumption of the callback inbox.
  PR #115 merged the repair, and Loop 26o reran the same bounded fullchain
  shape from post-merge main with all inbox items terminal. This is not
  repeated stability proof.
- Provider result acknowledgement timeout after durable writeback is mitigated
  by early writeback detection plus configurable bounded grace in PR #87.
  Broader production-load behavior is still unproven.
- Same participant/session delivery is protected in main by the PR #88 scheduler
  participant lock. This is not a general dependency-set planner.
- Loop 25z64 proved one bounded local groupchat-produced code lane to
  final-action hold. It also logged non-blocking review-state transition noise:
  `cannot transition loop25z64_inspector_provider_summary from reviewed to
  rejected`.
- PR #90 guards late persistent rework/rejected verdicts after accepted
  review/final-hold state by recording ignored-conflict metadata instead of
  attempting an invalid transition. Loop 25z65 then gave one bounded local
  repeat without the Loop 25z64 invalid transition noise.
- Loop 25z65 was docs-only. It is not repeated code-change soak and does not
  replace Loop 25z64 as the strongest groupchat-produced code lane evidence.
- Loop 25z64 did not expose `review_delivery_mode=persistent` or
  `persistent_review_degraded=false`; do not report it as complete persistent
  OpenCode delivery proof.
- Architect final-summary gating is locally mediated by a direct peer-reply
  drain callback. PR #117 narrows this callback to a durable source handoff
  message dependency set instead of a sender-global drain, but this is still
  not a general dependency-set planner for arbitrary workflow stages.
- Loop 27f proves one bounded local dynamic OpenCode review participant
  writeback turn from current main: dynamic member add, targeted
  `@participant:<id>` inbox delivery, durable assistant message, MCP
  `chat_post_message` trace, latency trace with `delivery_mode=mcp_writeback`,
  and Chat API progress projection. This narrows the dynamic-member writeback
  gap only. It does not prove provider-native session resume across restart,
  multi-turn natural Codex/OpenCode discussion, groupchat proposal production,
  production readiness, live MemoryOS, GitHub review truth, or full closure.
- Loop 27g extends Loop 27f to a bounded two-turn dynamic OpenCode continuity
  probe with a full Chat API/MCP/platform-runner restart between turns. The
  restarted participants read model restored the same dynamic participant
  `god_session_id`, and both turns produced durable assistant messages, MCP
  traces, and latency traces. This proves xmuse GOD session continuity for this
  shape only. It does not prove provider-native OpenCode resume because
  `provider_session_id` remained null.
- Loop 27h extends the strongest Phase 2/3 boundary from dynamic member
  continuity into a natural groupchat-produced proposal and execution chain:
  human demand to Codex architect, structured peer consensus with Codex execute
  and OpenCode review, durable proposal, approval, isolated execution, gate,
  persistent OpenCode review, and final-action hold. It also preserves
  observability caveats: the architect collaboration-request turn recorded a
  `peer_response_timeout` latency trace despite durable side effects, and the
  execute collaboration response recorded
  `peer_no_inbox_writeback_message` because `chat_record_collaboration_response`
  did not also create a chat message.
- Loop 27j is candidate-branch local runtime proof on
  `codex/collab-response-latency-success` that structured MCP tool writebacks
  no longer become false failed latency traces for the bounded sentinel shape.
  The same docs-only groupchat-to-final-hold chain reached
  `awaiting_final_action`; the architect `chat_create_collaboration_request`,
  execute `chat_record_collaboration_response`, architect `chat_emit_proposal`,
  and execute dispatch `chat_post_message` turns all recorded
  `delivery_mode=mcp_writeback`. This is observability/lifecycle proof only,
  not a new production-readiness or broad soak claim.
- Loop 27k attempted the first small non-docs groupchat-produced code-change
  lane for sentinel command artifacts. Groupchat collaboration, proposal,
  approval, and isolated execution produced a scoped two-file candidate, but
  the lane stopped at `gate_failed` because the selected `xmuse-core` gate hit
  a baseline MCP collaboration test setup gap. PR #134 repaired that test
  setup and merged with PR CI and main CI success.
- Loop 27l reran the same non-docs code-change lane from post-PR134 main and
  reached `awaiting_final_action` with `gate_passed=true`,
  `review_decision=merge`, `review_delivery_mode=persistent`,
  `persistent_review_degraded=false`, and OpenCode review peer metadata. This
  is bounded local runtime proof for one small code-change lane only. The
  architect callback needed a scheduler retry after one timeout, so stability
  remains unproven.
- Loop 27m repairs the evidence-retention side of that retry caveat:
  `peer_turn_latency_traces` now preserves every scheduler attempt for a
  retried inbox item instead of overwriting the earlier failed attempt with a
  later success. This makes future retry dependence durable and auditable; it
  does not prove the callback path no longer needs retry.
- Loop 27n reran the same sentinel shape from post-PR136 main and reached
  final-action hold without any peer inbox retry (`nudge_count=0` for the
  architect mention, execute collaboration response, architect callback,
  review trigger, and dispatch acknowledgement). This strengthens stability
  evidence for the callback path only. It also exposed a new caveat:
  pre-dispatch proposal review identified the lane as effectively no-op and
  recommended against dispatch, but no active veto blocked the driver approval.
  The execution candidate only changed a focused test because the production
  script already had the requested behavior.
- Loop 27o is a candidate repair for that caveat: collaboration-backed
  `lane_graph` approval now fails closed with `proposal_review_pending` while
  the related automatic review trigger is unread/claimed, and review-trigger
  content now instructs reviewers to use `chat_raise_collaboration_blocker`
  with `severity="veto"` and `blocks_dispatch=true` for no-dispatch findings.
  Focused regression suites passed locally, but this is not post-merge runtime
  proof. The next runtime loop should wait for proposal review completion and
  structured blocker/veto outcomes instead of immediately approving.
- PR #138 merged that candidate and main CI passed. Loop 27p reran the old
  immediate-approval runtime shape on post-PR138 main and confirmed it now
  fails closed before approval side effects with
  `proposal_review_pending` against unread review trigger
  `inbox_1f50a6d5d8c74cd2ba0c868de6007a0d`. No resolution, dispatch, lane
  projection, execution, or final-action hold was produced in that loop. This
  is desired boundary proof, not completion proof. The next bucket is to update
  the runtime harness/driver to wait for proposal review completion and
  structured veto/blocker outcomes.
- Loop 27q is the candidate-branch update for that harness/driver bucket. The
  reusable sentinel now waits for the related automatic `review_trigger` to
  reach terminal `read` state before approving. The run approved proposal
  `prop_3f0d6f5a3eff4f0f89dd7aa293b18bfe` only after
  `inbox_ffe0e282eafd4bb9a3ab08c05646cd34` was `read`, created resolution
  `res_f1223814dc59499098333f664cde140e`, reached
  `awaiting_final_action`, recorded finalized OpenCode review verdict
  `verdict-merge-rtask_5f80f70b11d1432c9e2997d9e31a4b03`, and left final hold
  `final-f332e8015da2` pending. This is local candidate-branch proof for the
  reusable sentinel harness, not merged main proof and not production
  readiness.
- PR #140 merged the reusable sentinel harness update to main as
  `419f00d4cd4c8227a33302658608f9d9532f07b6` after successful PR CI
  `27865014142` and successful post-merge main CI `27865045744`. Loop 27r then
  reran the merged harness from that main head and confirmed the
  wait-before-approval path on main: automatic review trigger
  `inbox_9487fcb303564ded8f5fd395f53ba6a8` reached `read`, proposal
  `prop_e0e1eab878b4465c8eb5945c60894f5d` was approved into resolution
  `res_bd24e8deb99444589850c5f611b94315`, the lane reached
  `awaiting_final_action`, OpenCode review verdict
  `verdict-merge-rtask_6d7f18ac90b8473c9a827b4fa15eee2e` finalized, and final
  hold `final-45abee1aa897` remained pending. This is post-merge main proof
  for the docs-only sentinel harness only, not production readiness or full
  closure.
- Loop 28a repairs the focused provider-native OpenCode resume gap on the
  candidate branch `codex/native-opencode-provider-session-binding`. The
  native OpenCode shim returned a real provider `sessionID`, `GodSessionLayer`
  persisted it into `god_sessions.json`, a fresh layer restored the same GOD
  session after local shim abort, and the next real OpenCode turn reused the
  provider session. This closes the direct producer/consumer binding gap
  exposed by Loop 27g for one focused probe, but it is not yet post-merge main
  fullchain evidence.
- PR #142 merged that repair to main as
  `2fde89eda05b6a34da9364bb0b9a426c1c0749b0` after successful PR CI
  `27865756181` and successful post-merge main CI `27865780027`. Loop 28b then
  reran the focused provider-session probe from that main head and confirmed
  persisted `provider_session_id`, `provider_binding_status=active`, same GOD
  session restore, and second-turn provider session reuse. This upgrades Loop
  28a to post-merge main focused proof only; fullchain groupchat-to-lane
  provider-resume evidence remains absent.
- The successful chains are not yet repeated overnight or production-load soak.
- Provider-native OpenCode session continuity has focused post-merge main
  proof only; fullchain groupchat-to-lane evidence is still absent. Memory
  persistence is not proven as durable product behavior.
- Live MemoryOS proof is absent.
- GitHub review truth is absent.
- Groupchat production readiness is absent.
- Full L8-L10 and full L1-L11 closure are absent.

## Forbidden Claims Still Preserved

- `github_review_truth`
- `ready_to_merge`
- `pr_merged` for a live lane beyond inspected GitHub server state
- `live_memoryos`
- `worker_output_is_review_truth`
- `local_tests_are_review_truth`
- `full_l8_l10_closure`
- `full_l1_l11_closure`
- `overnight_readiness`
- `production_ready_groupchat`
- `natural_peer_god_groupchat`

## Next Small Buckets

- P0 peer handoff/writeback lifecycle: complete on main for the bounded
  `chat_mention` current-turn auto-bind gap and the bounded structured
  collaboration request/callback inbox lifecycle shape. PR #115 plus Loop 26o
  provide post-merge proof for the latter. Keep broader `/sse` tool-surface
  behavior, repeated soak, and production readiness out of this claim.
- P1 explicit dependency coordination: PR #117 plus Loop 26q now scope the
  direct peer-reply callback to the durable source handoff message on main and
  record `dependency_set_id`, `source_message_id`, and `dependency_targets` in
  the callback payload. Remaining work is a broader planner only if future
  runtime evidence needs dependencies beyond a single handoff message's target
  set.
- P2 review peer prompt/session metadata: bounded local configured OpenCode
  persistent review now records a separate review-session prompt authority in
  `god_sessions.json`, and Loop 26e confirmed the behavior on post-PR107 main.
  Loop 26f adds focused candidate proof for the multiple-OpenCode-reviewer
  ambiguity case. Loop 26g adds focused candidate proof for the missing
  OpenCode reviewer case when a production-like active peer roster already
  exists. Loop 26h confirms the normal unique-OpenCode route still works after
  those fail-closed changes. Remaining work is broader review authority
  behavior. PR #119 plus Loop 26s remove the empty-conversation legacy Codex
  fallback on main and preserve the registered OpenCode fullchain route. The
  PR #121 closes the configured-peer degradation fallback on main by failing
  closed before auto persistent or one-shot fallback. Loop 26x then confirms
  the post-PR124 docs-only sentinel still reaches final-action hold with
  persistent OpenCode review.
- P3 higher-parallelism stability loop: repeat real groupchat-to-final-hold
  with independent `XMUSE_ROOT` directories, execution worktrees, Chat API
  ports, MCP ports, and runners when increasing concurrency beyond the current
  two-shard evidence. Do not share durable stores or one PR branch across
  parallel probes.
- P4 ambiguous review authority: multiple active OpenCode review participants
  now have focused fail-closed behavior without relying on proposal text.
  Missing OpenCode review participants also fail closed when an active peer
  roster exists. PR #119 plus Loop 26s remove the empty-conversation
  feature-scoped Codex default-review fallback on main. PR #121 changes
  configured-peer degradation fallback into fail-closed review authority on
  main; Loop 26x confirms the post-PR124 docs-only sentinel reaches
  final-action hold with persistent OpenCode review after that repair.
- P5 code-change soak: Loop 27l provides one bounded post-PR134 non-docs
  code-change lane to final-action hold. Remaining work is repeated small
  code-change lanes, broader code-change shapes, and production-load/stability
  evidence without callback retry dependence.
- P5a natural dynamic groupchat continuity: Loop 27g proves bounded xmuse GOD
  session restore plus second-turn dynamic OpenCode writeback. Loop 27h proves
  one natural multi-agent Codex/OpenCode discussion that produces a durable
  proposal and reaches final-action hold for a docs-only lane. Loop 27j
  locally repairs the structured-tool latency false-failed classification for
  that sentinel shape. Loop 27l adds one bounded non-docs code-change lane.
  Loop 28a adds focused candidate-branch proof for provider-native OpenCode
  resume after GOD layer restart, and Loop 28b upgrades that to focused
  post-merge main proof. Remaining work is fullchain provider-resume evidence,
  repeated stability, broader code-change lanes, and any production-load claim.
- P6 MemoryOS adapter proof: keep `live_memoryos` forbidden until a real trace
  id or artifact exists.
