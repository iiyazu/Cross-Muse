# xmuse runtime operation findings

This file tracks product and harness findings from local runtime operation
attempts. It is intentionally conservative: a passing local run is not review
truth, merge truth, live MemoryOS proof, or full closure.

## Current Evidence Summary

- Current active line on 2026-06-21: Loop 7R-R prepared a clean
  `origin/main`-based local PR candidate for the final-action import guard
  domain. Historical
  bullets below may contain superseded `next_action` values; resume from the
  latest loop entry unless a newer summary artifact exists.
- Loop 7R-R on 2026-06-21 created an isolated worktree at
  `/home/iiyatu/.config/superpowers/worktrees/xmuse/loop7r-dirty-import-guard`
  on branch `codex/loop7r-dirty-import-guard`, based exactly on
  `origin/main` head `ae1dce9ef5aad73163d566370c94f6d0f1619beb`. Runtime
  proof summary:
  `.goal-runs/2026-06-21/loop-7rr-clean-worktree-pr-candidate-20260621/summary.json`.
  The candidate diff is limited to three files:
  `src/xmuse_core/platform/dashboard_details.py`,
  `xmuse/dashboard_api.py`, and `tests/xmuse/test_dashboard_api.py`.
  It adds explicit final-action target import, requires a durable
  `final_action_import_decisions.json` main-agent decision before target apply,
  copies safe changed files into the explicit target worktree, records
  `final_action_imports.json`, and rejects same-path dirty target conflicts
  before copy. The TDD RED run first failed on all three desired behaviors:
  target artifact was not copied, missing import decision returned 200 instead
  of 409, and dirty target conflict returned 200 instead of 409. After the
  scoped patch, the three focused tests passed, and the broader
  `tests/xmuse/test_dashboard_api.py tests/xmuse/test_platform_mcp_tools.py`
  gate passed with `177 passed, 8 warnings`. Ruff passed for the three changed
  files. This is a local clean-worktree PR candidate only: no branch was pushed,
  no PR was created, no GitHub server truth exists for the candidate, and no
  source-root merge occurred. The next action is `Loop 7S-R`: publish the clean
  scoped branch as a small draft PR only after a final diff review confirms the
  3-file scope; then capture GitHub server truth for that PR head.
- Loop 7Q-R on 2026-06-21 performed a read-only publication authority audit
  after Loop 7P-R. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-7qr-publication-authority-audit-20260621/summary.json`;
  GitHub capture:
  `.goal-runs/2026-06-21/loop-7qr-publication-authority-audit-20260621/pr46-server-truth.json`.
  The current branch `codex/groupchat-proposal-review-payload` is still at head
  `110dd47b435e44e7b608ac5b880ad4aebcf79ab0`, while `origin/main` is
  `ae1dce9ef5aad73163d566370c94f6d0f1619beb`; the branch is
  `{ahead: 1, behind: 111}` relative to `origin/main`, and the local worktree
  has `dirty_path_count=80`. GitHub PR #46 for this branch is already
  `MERGED`, with merge commit
  `109c4a4eae8b2a0a492fbe8e11d100a0bc76ee98` at
  `2026-06-17T18:50:42Z`, and required check names
  `quality-gates`, `contract-smoke-gates`, and
  `real-runtime-integration-gate`. The server-side truth capture found branch
  protection required checks and check run ids, but produced
  `proof_level=manual_gap`, `can_emit_pr_merged=false`, and
  `gap_reason="missing server-side truth: review_truth"`. This means PR #46
  is historical merge evidence for head `110dd47`, not publication authority
  for the current uncommitted 7P/7Q local changes. Loop 7Q-R rejects
  source-root import into the dirty control worktree, rejects reusing merged
  PR #46 for uncommitted local changes, rejects claiming `pr_merged` from the
  manual-gap server capture, and rejects local clean-target replay as source
  integration truth. The selected next path is a small GitHub/server-truth PR
  boundary prepared from a fresh clean worktree. The next action is
  `Loop 7R-R`: create or use a fresh clean worktree from current `origin/main`
  and prepare a smallest scoped PR candidate for the 7P dirty-conflict guard
  domain, with local validation only; stop before push/PR unless the scoped
  diff is clean and unique.
- Loop 7P-R on 2026-06-21 repaired the next boundary after Loop 7O-R's local
  target-worktree apply proof. Before this patch, dashboard final-action
  approval could accept a durable `final_action_import_decisions.json` decision
  and copy changed files into an explicit target even when that target git
  worktree already had a dirty file at the same path. The new guard intersects
  target `git status --porcelain --untracked-files=all` dirty paths with lane
  `changed_files` and rejects same-path conflicts before copy with
  `final_action_import_target_dirty_conflict`. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-7pr-source-root-import-dirty-guard-20260621/summary.json`.
  The replay used the current dirty xmuse source worktree
  `/home/iiyatu/projects/python/xmuse` as the explicit import target, selected
  dirty path `docs/xmuse/README.md`, and received HTTP 409
  `final_action_import_target_dirty_conflict: docs/xmuse/README.md`. The target
  sha256 stayed
  `25cfe8c66d145bc811af022940eb403804fcf610823f25e6f2081ebfcd0886ab`,
  `target_text_unchanged=true`, lane stayed `awaiting_final_action`, hold
  stayed `pending`, and no `final_action_imports.json` was written. This proves
  local source-root dirty-conflict protection only. It does not prove
  GitHub/server truth, source-root merge, production readiness, or full xmuse
  closure. The next action is `Loop 7Q-R`: audit publication/source-integration
  authority after the dirty source-root guard and decide whether the next valid
  integration path is a small GitHub/server-truth PR boundary or a local
  clean-target import replay, without importing into the current dirty source
  root.
- Loop 2G on 2026-06-21 proved the smallest safe control-plane approval path
  for the Grok-reviewed lane_graph proposal. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-2g-approved-proposal-lane-graph-authority-20260621/summary.json`.
  The run reused isolated runtime root `/tmp/xmuse-loop2e-root-vyv2cv3y`,
  worktree `/tmp/xmuse-loop2e-worktree-6kr40pe1`, and conversation
  `conv_afc1580e7e274835b1c847f33b73dc0a`. The REST approval endpoint returned
  200 with `approved_by=["human:goal-loop-2g"]` and
  `approval_mode=manual_control_plane`. Proposal
  `prop_116899dd4b494d48b1ebbab443546eec` moved from `open` to `accepted` and
  now has `accepted_resolution_id=res_3183f7781479438eb39be22bcbdfca85`. The
  durable resolution `res_3183f7781479438eb39be22bcbdfca85` has version `1`,
  status `approved`, `derived_from_proposal_ids` containing the proposal id,
  `content.type=lane_graph`, and lane `loop-2e-proposal-lane`. The lane graph
  authority file exists at
  `/tmp/xmuse-loop2e-root-vyv2cv3y/lane_graphs/res_3183f7781479438eb39be22bcbdfca85-graph-v1.json`;
  it has id `res_3183f7781479438eb39be22bcbdfca85-graph-v1`,
  `resolution_id=res_3183f7781479438eb39be22bcbdfca85`, status `planned`, lane
  `loop-2e-proposal-lane`, `feature_group=groupchat-runtime`, and
  `review_runtime=grok`. Its source refs include the resolution, conversation,
  runtime root, chat.db, proposal id, and Grok review message
  `msg_9eab7b3e12e24e55be747ad04a09d5b1`. `feature_lanes.json` was created
  with `projection_revision=1` and a single `pending` lane pointing to the
  approved resolution/graph; this is observed projection only, not authority.
  The dispatch queue rows for the conversation are empty, so this proof did not
  enter dispatch. Loop 2G proves only local approval to durable lane_graph
  authority. It does not prove lane dispatch, worker code execution, platform
  review routing, GitHub/server truth, merge truth, production reliability, or
  full xmuse closure. The next action is `Loop 2H`: run the smallest safe
  coordinator/runner observation of the approved lane graph projection under
  final-action hold, proving whether the pending lane can be claimed or
  classifying the first execution-scheduling boundary; stop before worker code
  execution, platform review routing, GitHub truth, or merge.
- Loop 2F on 2026-06-21 proved that the automatic proposal `review_trigger`
  produced by Loop 2E can be consumed by a real Grok review peer with durable
  MCP writeback. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-2f-grok-proposal-review-trigger-20260621/summary.json`.
  The run reused Loop 2E's isolated runtime root
  `/tmp/xmuse-loop2e-root-vyv2cv3y`, worktree
  `/tmp/xmuse-loop2e-worktree-6kr40pe1`, and conversation
  `conv_afc1580e7e274835b1c847f33b73dc0a`. Source proposal
  `prop_116899dd4b494d48b1ebbab443546eec` remained type `lane_graph`,
  status `open`, and continued to reference
  `message:msg_9eab7b3e12e24e55be747ad04a09d5b1`. The automatic trigger
  `inbox_e558b5cf0841410cbd627ec8993e213e`, sourced from proposal message
  `msg_b5960801fed746b79b05a165b2d83427`, was consumed by Grok review
  participant `part_573eb74cf1da472b8fc2725f8321472c`. It reached
  `status=read` and `responded_message_id=msg_0da9c5c2ea26490bb8393408415c8e96`.
  The response is an assistant message with
  `writeback_path=grok_callback_bridge` and request id
  `inbox_e558b5cf0841410cbd627ec8993e213e`. The request log sequence is now
  `chat_post_message -> chat_mention -> chat_post_message ->
  chat_emit_proposal -> chat_post_message`; the trigger's MCP tool trace is
  `chat_post_message`; its latency trace records `delivery_mode=mcp_writeback`
  and `degraded_reason=null`. After abort, both Codex and Grok sessions were
  durably `stopped`; Grok retained provider session
  `019ee828-5cff-7aa0-8cdd-cd86e88c0e33` with
  `provider_binding_status=active`. One harness-only failure happened before
  the successful collection: the first evidence runner used a non-login uv
  invocation, so `GrokLauncher(grok_binary="grok")` inherited a PATH that did
  not resolve the CLI and produced `grok_spawn_failed`; the runner also assumed
  stale store reader names. The replay artifact now uses the absolute Grok
  binary path and sqlite readers for durable request/latency traces. No product
  code patch was required. Loop 2F proves only local Grok review-trigger
  writeback. It does not prove formal proposal approval, lane graph authority
  creation, lane dispatch, lane execution, platform review routing,
  GitHub/server truth, natural Grok-to-Codex handback, production reliability,
  or full xmuse closure. The next action is `Loop 2G`: perform the smallest
  safe human/control-plane approval proof for the Grok-reviewed lane_graph
  proposal, verifying that approval creates durable resolution/lane graph
  authority while keeping dispatch, lane execution, platform review routing,
  GitHub truth, and merge actions off.
- Loop 2E on 2026-06-21 proved a bounded groupchat-produced proposal after a
  durable Grok review. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-2e-groupchat-produced-proposal-20260621/summary.json`.
  The run used isolated runtime root `/tmp/xmuse-loop2e-root-vyv2cv3y`,
  worktree `/tmp/xmuse-loop2e-worktree-6kr40pe1`, and conversation
  `conv_afc1580e7e274835b1c847f33b73dc0a`. The human message created only the
  Codex architect inbox `inbox_43a5e036318e4c5ba3bee7af8996a41f` for
  participant `part_4ac21708bad14802a5144c7c32d5592d`. Codex completed that
  turn with `happy_path=1`, wrote message
  `msg_4982f3e117d4415d8fc401d26d3220c5` containing
  `CODEX_LOOP2E_ARCHITECT_ACK`, and used `chat_mention` to create the Grok
  review inbox `inbox_fc53e249ddc54b79b678e71976b1bf11`. Grok review
  participant `part_573eb74cf1da472b8fc2725f8321472c` completed its turn with
  `happy_path=1`, wrote durable message
  `msg_9eab7b3e12e24e55be747ad04a09d5b1` containing
  `GROK_LOOP2E_REVIEW_OK`, and reached `delivery_mode=mcp_writeback` with
  `degraded_reason=null`. A harness-created Codex proposal inbox
  `inbox_3d7db32d635c4126b2af132da0e8dd15`, sourced from that durable Grok
  review message, then caused Codex to call `chat_emit_proposal`. The emitted
  proposal `prop_116899dd4b494d48b1ebbab443546eec` has type `lane_graph`,
  status `open`, proposal message `msg_b5960801fed746b79b05a165b2d83427`, and
  references `message:msg_9eab7b3e12e24e55be747ad04a09d5b1`. The request log
  sequence was `chat_post_message -> chat_mention -> chat_post_message ->
  chat_emit_proposal`. `chat_emit_proposal` also created the next unread review
  trigger inbox `inbox_e558b5cf0841410cbd627ec8993e213e` for `review`, sourced
  from proposal message `msg_b5960801fed746b79b05a165b2d83427`. After abort,
  Codex and Grok sessions were durably `stopped`; Grok retained provider
  session `019ee828-5cff-7aa0-8cdd-cd86e88c0e33` with
  `provider_binding_status=active`. Loop 2E proves only a bounded local
  proposal-after-Grok-review path. It does not prove natural Grok-to-Codex
  handback, proposal approval, lane execution, platform review routing,
  GitHub/server truth, production reliability, or full xmuse closure. The next
  action is `Loop 2F`: consume the automatically created proposal
  `review_trigger` with the Grok review peer and prove durable proposal-review
  writeback, then stop before approval, dispatch, lane execution, or platform
  review routing.
- Loop 2D on 2026-06-21 proved the scheduler-driven Codex-to-Grok natural
  handoff after the Loop 2C lifecycle patch. Runtime proof summary:
  `.goal-runs/2026-06-21/loop-2d-codex-grok-lifecycle-handoff-20260621/summary.json`.
  The clean rerun used isolated runtime root
  `/tmp/xmuse-loop2d-rerun-root-aejz310s` and worktree
  `/tmp/xmuse-loop2d-rerun-worktree-v46aai8f`. The human message
  `msg_add1538f9efd4a849a45d538ad60b382` created only the architect inbox
  `inbox_bfc470cfa71a4314bdacdde1eda6d359` for Codex participant
  `part_5e99851e2f2d4b5191e6ab4306a65f72`. The Codex scheduler turn completed
  with `happy_path=1`, wrote assistant message
  `msg_f4b0935da2a74a2e82ad1f3b55cb8cc8` containing
  `CODEX_LOOP2D_ARCHITECT_OK`, and used `chat_mention` to create the Grok
  review inbox `inbox_0df92a3c14a7476d9567f6472cc34bc3`. That review inbox was
  Codex-produced: source message `msg_97f086aaee6c488bb5af004e8e651aef`,
  sender participant `part_5e99851e2f2d4b5191e6ab4306a65f72`, payload
  `Reply exactly: GROK_LOOP2D_REVIEW_OK`. The Grok scheduler turn then
  completed with `happy_path=1` through participant
  `part_1c8141d14ac74f18bccaacea4a1303e0`, wrote assistant message
  `msg_c4c24bc221a6405a9670f73838479a10` containing
  `GROK_LOOP2D_REVIEW_OK`, and used `writeback_path=grok_callback_bridge`.
  Both inboxes reached `read`; the request log sequence was
  `chat_post_message -> chat_mention -> chat_post_message`; both latency traces
  recorded `delivery_mode=mcp_writeback` and `degraded_reason=null`.
  `god_sessions.json` recorded Codex architect session
  `god-464e57f79abb4243a373d692c4df6c15` as `running` after the Codex turn and
  Grok review session `god-3947cb9ac75746808936494032d489b0` as `running`
  after the Grok turn. After `abort_session`, both sessions were durably
  `stopped`; Grok retained provider session
  `019ee81f-aded-7d82-92a4-9928c0e7156c` with
  `provider_binding_status=active`. `PeerChatService.list_participants`
  exposed the stopped session status for both participants.
  One earlier Loop 2D harness attempt is partial evidence only: it completed
  the Codex architect reply and `chat_mention`, but the ad hoc observer used
  the wrong inbox-store API name before processing the Grok turn. Loop 2D
  proves local lifecycle-observable Codex-to-Grok handoff only. It does not
  prove Grok proposal production, groupchat-produced proposal, lane execution,
  platform review routing, production reliability, GitHub/server truth, or
  full xmuse closure. The next action is `Loop 2E`: run a bounded
  groupchat-produced proposal proof using the now lifecycle-observable
  Codex-to-Grok path, requiring Codex to create the Grok review inbox through
  `chat_mention`, Grok to reply through durable writeback, and Codex to emit
  one durable proposal that cites the Grok review message; stop before
  approval, lane execution, or platform review routing.
- Loop 2C on 2026-06-21 repaired the `god_sessions.status` lifecycle
  observability gap exposed by Loop 2B. The root cause was producer-side:
  `GodSessionLayer` created durable `GodSessionRegistry` records but did not
  persist lifecycle transitions after `LocalSession.spawn` or
  `abort_session`. `GodSessionRegistry.update_status(...)` now persists the
  lifecycle field, and `GodSessionLayer` writes `status="running"` after
  successful attach/respawn and `status="stopped"` on abort. Focused red-green
  tests covered the registry API and layer lifecycle contract; related
  GodSession/Grok parity tests passed (`53 passed`). Runtime proof summary:
  `.goal-runs/2026-06-21/loop-2c-god-session-lifecycle-status-20260621/summary.json`.
  The isolated runtime used root `/tmp/xmuse-loop2c-root-owkiwsj8`, worktree
  `/tmp/xmuse-loop2c-worktree-y8iiq0vs`, conversation
  `conv_ce9c973d162e4f8395e256271159dfe9`, Grok participant
  `part_2187f45114cb42b3806c949a7031c5af`, and inbox
  `inbox_c6ea45aa26c1477d842d1ca4b9fe7680`. A real Grok scheduler turn
  completed with `happy_path=1`, durable assistant message
  `msg_e2872d6b8f4e4ffcb550dbaf370125f3`, content
  `GROK_LOOP2C_LIFECYCLE_OK`, `writeback_path=grok_callback_bridge`, inbox
  `read`, and `delivery_mode=mcp_writeback`. The Grok God session
  `god-2d670583f4b14013ba1f373e6025568e` recorded
  `provider_session_id=019ee813-2fa9-7a11-94e4-07e40babd15f`,
  `provider_session_kind=grok_cli_session`, and
  `provider_binding_status=active`; `status_after_turn` was `running`, and
  after `abort_session` the durable status was `stopped`.
  `PeerChatService.list_participants` read the same durable session status
  through the participant/session consumer surface. This proves session
  lifecycle observability for one real Grok peer turn only. It does not prove a
  fresh Codex-to-Grok full handoff after the lifecycle patch, Grok proposal
  production, lane execution, platform review routing, production reliability,
  GitHub/server truth, or full xmuse closure. The next action is `Loop 2D`:
  rerun the scheduler-driven Codex-to-Grok natural handoff with the fixed
  lifecycle contract and prove both Codex and Grok peer sessions reach
  observable `running`/`stopped` statuses through durable registry and
  participant/session read surfaces, without expanding into proposal or lane
  execution.
- Loop 2B on 2026-06-21 proved a scheduler-driven natural Codex-to-Grok
  handoff under the current Grok peer path. Runtime probe summary:
  `.goal-runs/2026-06-21/loop-2b-scheduler-codex-grok-handoff-20260621-rerun2/summary.json`.
  The clean rerun used isolated runtime root
  `/tmp/xmuse-goal-loop2b-rerun2-root-y7vtkhfi` and worktree
  `/tmp/xmuse-goal-loop2b-rerun2-worktree-1b_9m4de`. The human message
  `msg_d882a9f3feab4ab4899213503a93f822` mentioned only `@architect`, creating
  architect inbox `inbox_31596d1580bc49fda092ce5e948efaae` for Codex
  participant `part_94c916c513e04035a2242b7c122a5e2b`. PeerChatScheduler
  processed that inbox through the real Codex CLI/MCP path; Codex persisted
  assistant message `msg_aa5380ea152047dd9c38eff3f1f11ddc` with
  `CODEX_LOOP2B_ARCHITECT_OK`, and then called `chat_mention` to create Grok
  review inbox `inbox_76afb21b08c9437fa91d02e515398529`. That review inbox was
  Codex-produced: its `source_message_id` is Codex mention message
  `msg_748d0a39bc214f7b95a14b8e3e770bdf`, and its
  `sender_participant_id` is the Codex architect participant. A second
  scheduler tick processed the Grok inbox through Grok participant
  `part_5c4c89bb97754b97a49a38225b1cab95`; Grok persisted assistant message
  `msg_e2c41d5f9f97415d9700fb46e19556cb` with
  `GROK_LOOP2B_REVIEW_OK` through the `grok_callback_bridge`. Both inboxes
  reached `read`; both peer latency traces recorded `delivery_mode=mcp_writeback`
  and `degraded_reason=null`. This proves local scheduler-driven
  human -> Codex architect -> Grok review natural handoff and durable writeback
  only. It does not prove Grok proposal production, lane execution, platform
  review routing, GitHub/server truth, full xmuse closure, or production-ready
  groupchat.
  Two earlier attempts were harness evidence only: the first omitted
  `provider_id="grok"` and failed before product execution; rerun1 proved the
  Codex turn but was contaminated because the human prompt also contained
  `@review`, creating a human-origin review inbox. Loop 2B also exposed a
  lifecycle observability gap: `god_sessions.json` still records
  `status="starting"` for init, Codex architect, and Grok review sessions after
  successful turns, while Grok separately records
  `provider_binding_status="active"` and provider session id
  `019ee807-c084-7671-9953-bb5c54c8636b`. The next action is `Loop 2C`: repair
  or explicitly demote the stale `god_sessions.status` lifecycle field by
  proving the GodSessionLayer/GodSessionRegistry producer and
  dashboard/scheduler consumer contract for active peer sessions; the loop
  target is session lifecycle observability only, not another groupchat
  proposal or lane execution step.
- Loop 2A on 2026-06-21 proved the current minimal Grok GOD peer registration
  and callback writeback boundary. Grok CLI is available at
  `/home/iiyatu/.local/bin/grok`, logged in, and reports default model
  `grok-composer-2.5-fast`; OpenCode is not available in this environment and
  is not a blocker for the active non-Codex peer path. Focused tests for the
  Grok shim, launcher, participant/runtime mapping, GodSessionLayer, and
  GodSessionRegistry passed (`56 passed`). A plain real Grok smoke with
  `Reply exactly: GROK_SMOKE_OK` returned `GROK_SMOKE_OK` with
  `stopReason=EndTurn`. A prompt containing "xmuse Loop 2A smoke test" caused
  Grok to start searching the codebase and exit with max-turns, so future smoke
  prompts should avoid task-procedure phrasing when the goal is exact one-shot
  provider availability.
  Runtime probe summary:
  `.goal-runs/2026-06-21/loop-2a-grok-peer-writeback-20260621/summary.json`.
  The isolated probe ran xmuse MCP on port 8100 against runtime root
  `/tmp/xmuse-goal-loop2a-grok-root-4jmxt3g_`, registered Grok review
  participant `part_9e882718f3db47a59d0c44db4ea6d49e` in conversation
  `conv_b15dfe3982334b34a818b0e4afbe28c1`, created inbox item
  `inbox_0f06f48cde2e44e98f704c39358ab44c`, spawned Grok through
  GodSessionLayer/GrokLauncher, captured provider session id
  `019ee7f9-7066-7662-b9e5-aee2592dd34d`, posted
  `GROK_LOOP2A_WRITEBACK_OK` through the `chat_post_message` callback bridge,
  persisted assistant message `msg_bc1119f7719f4ac0a5646496534bbc0a`, and
  marked the inbox `read`. `god_sessions.json` records
  `runtime="grok"`, `model="grok-composer-2.5-fast"`,
  `provider_session_kind="grok_cli_session"`, and
  `provider_binding_status="active"`. The session `status` field still reads
  `starting`, so lifecycle status should be verified in the next natural
  scheduler loop before claiming production-grade session lifecycle. This
  proves local real Grok peer callback writeback only. It does not prove
  natural multi-turn Codex+Grok groupchat, Grok proposal production, lane
  execution, platform review routing, GitHub/server truth, or full xmuse
  closure. The next action is `Loop 2B`: run a scheduler-driven natural handoff
  proof where a human message creates a Codex architect inbox, Codex writes a
  durable reply and creates the Grok `@review` inbox through `chat_mention`,
  and Grok consumes that inbox through the real PeerChatScheduler/Grok callback
  bridge; also classify whether `god_sessions.status` remaining `starting`
  after active provider binding is a lifecycle bug or a legacy
  non-authoritative field.
- Loop 7O-R on 2026-06-21 proved that the runner-produced hold path and the new
  main-import decision contract compose. A fresh platform-runner lane in
  `/tmp/xmuse-goal-loop7or-root-t30ei01s` used a real Codex execution child,
  explicit gate profile, real Codex review child, pending final-action hold,
  main `/goal` import decision, and dashboard final-action approval. The lane
  preserved `changed_files=["runtime_artifacts/loop7o_runner_decision_import.txt"]`,
  `tests_run=["python -c artifact content assertion"]`, and
  `evidence_refs=["runtime_artifacts/loop7o_runner_decision_import.txt"]`.
  Gate profile `loop7o-runtime-artifact` passed with return code 0, review
  emitted merge, and hold `final-59069c6408f1` was pending before approval. The
  main `/goal` agent then wrote `final_action_import_decisions.json` with
  decision `decision-final-59069c6408f1` by `main-goal-agent`, and dashboard
  approval applied the artifact into target worktree
  `/tmp/xmuse-goal-loop7or-target-_ie7cdqs`; `final_action_imports.json`
  embedded the decision snapshot and recorded matching sha256
  `55ee760689937fb2f3e573ec89120d561c5e63d80d2d117b051443030733f9fb`.
  Summary:
  `.goal-runs/2026-06-21/loop-7or-runner-hold-main-import-decision-20260621/summary.json`.
  This proves local platform-runner hold + main-import decision +
  target-worktree apply only. It does not prove GitHub/server truth,
  source-root merge unless explicitly targeted, Grok platform review routing,
  natural peer-GOD groupchat proof, or full xmuse closure. The next action is
  `Loop 7P-R`: define and prove the next boundary after local target-worktree
  import: either an audit-only source-root/main-worktree import decision with
  dirty-worktree conflict checks, or classify it as a GitHub/server-truth
  manual gap if source integration requires PR/server authority.
- Loop 7N-R on 2026-06-21 added the audit-safe main-import decision boundary
  that Loop 7M-R exposed as missing. Before this patch, any lane carrying
  `final_action_import_target` could be approved and applied by dashboard
  final-action approval; the target path was lane metadata, but the main
  `/goal` agent's decision to import into that target was not a separate
  durable authority object. The new contract requires
  `final_action_import_decisions.json` for target-worktree apply. A valid
  decision must name the lane, target worktree,
  `decision=apply_to_target_worktree`, `status=approved`, non-empty
  `decided_by`, and non-empty `reason`; if it names a hold id, that hold must
  match the pending final-action hold. The selected decision snapshot is copied
  into `final_action_imports.json`. Focused TDD first proved the old behavior
  wrongly returned 200 without a decision, then proved stale decisions for
  another hold could be misused before hold matching was tightened. Runtime
  probe summary:
  `.goal-runs/2026-06-21/loop-7nr-main-import-decision-boundary-20260621/summary.json`.
  The success root `/tmp/xmuse-goal-loop7nr-root-x6vsq5tv` used decision
  `decision-final-loop7n` by `main-goal-agent` and applied
  `runtime_artifacts/loop7n_import.txt` into target worktree
  `/tmp/xmuse-goal-loop7nr-target-w7jeb5ub` with sha256
  `650b882f606dd9c3ab0ce9ac833a5f62a264e45919fdfb7119f7fa604f5347f6`.
  The missing-decision root
  `/tmp/xmuse-goal-loop7nr-missing-root-ebkgxg5z` returned HTTP 409
  `final_action_import_decision_missing`, left the lane
  `awaiting_final_action`, left the hold `pending`, and did not copy the
  target artifact. This proves local dashboard main-import decision gating
  only. It does not prove a fresh runner-produced hold under the new decision
  contract, GitHub/server truth, source-root merge unless explicitly targeted,
  Grok platform review routing, natural peer-GOD groupchat proof, or full xmuse
  closure. The next action is `Loop 7O-R`: rerun the Loop 7M-R
  platform-runner final-action flow, but insert a durable
  `final_action_import_decisions.json` decision after the runner-produced hold
  and before dashboard approval, proving the full runner-produced hold plus
  main-import decision plus target-worktree apply path under the new decision
  contract.
- Loop 7M-R on 2026-06-21 proved the runner-produced final-action import/apply
  path and repaired the execution evidence metadata contract needed for it. A
  fresh platform-runner lane with explicit `final_action_import_target` used a
  real Codex execution child, explicit gate profile, real Codex review child,
  final-action hold, and dashboard approval. Two early attempts were harness
  setup errors (`gate_profiles.schema_version` missing, then a malformed gate
  command with a literal newline). The first product failure was a contract
  mismatch: the execution child attempted `update_lane_status` with
  `evidence_refs`, but MCP rejected that metadata field, so the retry encoded
  evidence in the audit reason and lost durable `changed_files` / `tests_run` /
  `evidence_refs`; dashboard approval then correctly returned HTTP 409 for
  missing `changed_files`. The patch allows bounded execution `evidence_refs`
  through `update_lane_status` and lane schema validation. The final rerun in
  `/tmp/xmuse-goal-loop7mr-root4-erxxf6gw` preserved
  `changed_files=["runtime_artifacts/loop7m_runner_import.txt"]`,
  `tests_run=["python -c artifact content assertion"]`, and
  `evidence_refs=["runtime_artifacts/loop7m_runner_import.txt"]`, passed gate
  profile `loop7m-runtime-artifact`, recorded review merge verdict
  `verdict-merge-rtask_8dc9c2d3445f4853b14ac2f68baae682`, reached hold
  `final-920c37eba2f6`, and dashboard approval imported the artifact into
  target worktree `/tmp/xmuse-goal-loop7mr-target4-jv3whgbg` with matching
  sha256 `e6fbfcafcb61907ac15f31db49fafcb64dd6e97b7242c1207e3151ffaa04754f`.
  Summary:
  `.goal-runs/2026-06-21/loop-7mr-runner-final-action-import-target-20260621/summary.json`.
  This proves local platform-runner execution/gate/review/final-action
  target-worktree import only. It does not prove GitHub/server truth,
  source-root merge unless explicitly targeted, Grok platform review routing,
  natural peer-GOD groupchat proof, or full xmuse closure. The next action is
  `Loop 7N-R`: convert the proven local target-worktree import into an
  audit-safe main-import decision boundary by defining how the main `/goal`
  agent chooses an explicit target worktree for approved runner artifacts,
  while preserving the rule that xmuse never claims GitHub/server merge truth
  without server evidence.
- Loop 7L-R on 2026-06-21 made final-action import/apply explicit at the
  dashboard approval boundary. Before the patch, `POST
  /api/lanes/{feature_id}/approve` could approve a merge hold and mark the lane
  `merged` without producing any durable import/apply artifact. The new
  contract writes `final_action_imports.json` for merge approvals. When a lane
  carries an explicit `final_action_import_target`, approval copies each safe
  relative `changed_file` from the lane worktree into that target worktree and
  records source/target sha256 hashes; without an explicit target it records an
  audit-only boundary rather than implying source integration. Focused TDD first
  reproduced the missing target-worktree artifact with
  `test_approve_awaiting_final_action_merge_applies_import_to_target_worktree`;
  after the patch the dashboard file suite passed (`134 passed`). Runtime probe
  summary:
  `.goal-runs/2026-06-21/loop-7lr-final-action-import-apply-20260621/summary.json`.
  The probe approved hold `final-loop7l-runtime` in isolated root
  `/tmp/xmuse-goal-loop7lr-import-root-f3d4v_e2`, copied
  `runtime_artifacts/loop7l_runtime_apply.txt` from source worktree
  `/tmp/xmuse-goal-loop7lr-import-source-nl2skpy6` into explicit target
  worktree `/tmp/xmuse-goal-loop7lr-import-target-xliyol8k`, and recorded
  matching source/target sha256
  `fcd719de2ba079b585116808f9e980b8396f19fb859bec6b90ec76516c94510e`.
  This proves local dashboard final-action import/apply only. It does not prove
  GitHub/server truth, source-root merge unless that root is the explicit
  target, natural peer-GOD groupchat proof, or full xmuse closure. The next
  action is `Loop 7M-R`: run a fresh non-probe platform-runner lane that
  carries an explicit `final_action_import_target` through execution/review to a
  pending final-action hold, then approve it through dashboard and verify the
  runner-produced hold imports into the target worktree without claiming
  GitHub/server merge truth.
- Loop 7K-R on 2026-06-21 closed the local diff/import evidence gap exposed by
  Loop 7J-R. `McpToolHandler.get_diff` now returns structured
  `status_short`, `status_returncode`, `untracked_files`, and `has_untracked`
  in addition to tracked `diff`. Dashboard final-action approval now verifies
  that claimed `changed_files` are visible in either `git diff --name-only
  HEAD` or `git ls-files --others --exclude-standard` when the lane has a
  worktree. Focused TDD first reproduced both failures:
  `get_diff` lacked `untracked_files`, and dashboard approval returned 200 for
  a claimed missing worktree file. Runtime probe against the Loop 7J-R source
  root `/tmp/xmuse-goal-loop7jr-positive-root2-g1_tk0be` now reports
  `untracked_files=["runtime_artifacts/loop7j_positive_final_action.txt"]`.
  A copied approval root
  `/tmp/xmuse-goal-loop7kr-final-approval-copy-5wy0ewd8` accepted that
  untracked artifact and resolved its copied hold to approved/merged, while
  the original Loop 7J-R hold stayed `pending`. Summary:
  `/tmp/xmuse-goal-loop7jr-positive-root2-g1_tk0be/loop7kr_diff_import_evidence_summary.json`.
  This proves local diff/import evidence and copied dashboard approval only.
  It does not prove source-root import, GitHub/server truth, Grok platform
  review routing, or full xmuse closure. The next action is `Loop 7L-R`: make
  final-action import explicit by adding a local import/apply step or audit
  contract that turns an approved hold with tracked or untracked evidence into
  a controlled target-worktree change without claiming GitHub/server merge
  truth.
- Loop 7J-R on 2026-06-21 proved the positive local
  gate-profile-to-final-action path with a non-probe lane. The corrected rerun
  used runtime root `/tmp/xmuse-goal-loop7jr-positive-root2-g1_tk0be`,
  worktree `/tmp/xmuse-goal-loop7jr-positive-worktree2-5czwhtm8`, MCP port
  `55227`, and branch `loop7jr-positive2-1782003765`. The execution child
  called `query_knowledge` and `update_lane_status` through MCP, created
  `runtime_artifacts/loop7j_positive_final_action.txt`, and wrote durable
  `changed_files` / `tests_run`. The explicit gate profile
  `loop7j-runtime-artifact` ran a real command with return code 0. The review
  child called `get_lane`, `get_gate_report`, `get_diff`, and
  `update_lane_status` through MCP; review plane recorded finalized merge
  verdict `verdict-merge-rtask_c6301ed13a8c40f08bb0a79b01d19628`; final action
  hold `final-ba9ee95291c3` remains `pending`; lane status is
  `awaiting_final_action`. Summary:
  `/tmp/xmuse-goal-loop7jr-positive-root2-g1_tk0be/loop7jr_positive_final_action_summary.json`.
  This proves local runtime execution/review/gate-profile/final-action-hold
  only. It does not prove dashboard final-action approval, merge/import,
  GitHub/server truth, Grok platform review routing, or full xmuse closure.
  New finding: review `get_diff` returned empty diff for an untracked worker
  artifact even though `git status` shows `?? runtime_artifacts/`; the next
  action is `Loop 7K-R`: close the diff/import evidence gap by making
  review/final-action evidence include untracked worker outputs or by requiring
  execution workers to stage/track importable artifacts before final approval
  can proceed.
- Loop 7I-R on 2026-06-21 converted the Loop 7H-R finding into an explicit
  dashboard approval contract. The consumer
  `POST /api/lanes/{feature_id}/approve` now rejects `action=merge`
  final-action holds unless the lane has non-empty `changed_files` and a real
  gate report with non-empty `profile_ids` and `command_results`. Focused TDD
  first reproduced the old false approval behavior
  (`test_approve_awaiting_final_action_merge_rejects_probe_without_gate_evidence`
  returned 200 before the patch), then passed after the patch alongside the
  valid evidenced merge path. A local TestClient probe in runtime root
  `/tmp/xmuse-goal-loop7ir-final-action-contract-seuumyks` returned HTTP 409
  for a no-op probe hold; `feature_lanes.json` remained
  `status=awaiting_final_action` and `final_actions.json` kept
  `hold_status=pending`. Summary:
  `/tmp/xmuse-goal-loop7ir-final-action-contract-seuumyks/loop7ir_final_action_approval_contract_summary.json`.
  This prevents probe/no-op holds from becoming false `merged` approvals. It
  does not prove GitHub/server truth, import/merge, non-probe lane execution,
  Grok platform review routing, or full xmuse closure. The next action is
  `Loop 7J-R`: run a minimal non-probe lane with explicit `gate_profiles.json`
  and a real changed file to prove the positive final-action approval path
  reaches `awaiting_final_action` with importable evidence while still stopping
  before GitHub/server merge truth.
- Loop 7H-R on 2026-06-21 audited the Loop 7G-R pending final-action hold
  `final-d71020c9276d` in runtime root
  `/tmp/xmuse-goal-loop7gr-final-review-mcp-rqmg9ktr`. The hold was a
  probe-only merge hold from the MCP writeback/review prompt quarantine proof:
  `feature_lanes.json` had `changed_files=[]`, tests were intentionally not
  run, the execution worktree
  `/tmp/xmuse-goal-loop7gr-final-exec-czfafzrl` had no tracked diff or
  untracked artifact, and the gate report warned that `gate_profiles.json` was
  missing so the gate passed open. Approving the hold would have created false
  `merged` semantics without GitHub/server truth or an importable artifact.
  The final-action auditor resolved the hold through `FinalActionGateStore` as
  `status=rejected`, `resolved_by=loop7hr-audit-probe-no-import`. Summary:
  `/tmp/xmuse-goal-loop7gr-final-review-mcp-rqmg9ktr/loop7hr_final_action_hold_audit_summary.json`.
  This closes the Loop 7G-R pending hold without import. It does not prove
  merge/import, GitHub/server truth, real gate profile enforcement, Grok
  platform review routing, or full xmuse closure. The next action is
  `Loop 7I-R`: make the final-action/gate-profile boundary explicit by proving
  a non-probe lane with real gate profile evidence or by adding a minimal
  final-action audit contract that prevents no-op probe holds from becoming
  merge approvals.
- Loop 7G-R on 2026-06-21 repaired the review prompt contamination boundary and
  revalidated the actual platform-runner execution/review path in isolated root
  `/tmp/xmuse-goal-loop7gr-final-review-mcp-rqmg9ktr`. The patch quarantines
  review lane task text as quoted subject matter, removes `gate_failed` as a
  semantic review verdict write after a passed gate, and tightens both
  execution/review prompts so Codex must attempt a direct xmuse-platform MCP
  call before claiming MCP is unavailable. Focused prompt tests passed
  (`uv run pytest tests/xmuse/test_platform_prompt_builders.py -q`: 35
  passed). The final rerun used MCP port `38181`; execution child stderr
  contains `xmuse-platform/query_knowledge` and `update_lane_status`
  started/completed, review child stderr contains `get_lane`,
  `get_gate_report`, `get_diff`, and `update_lane_status` started/completed,
  review stdout was `Findings: none` / `Verdict: merge`, and
  `feature_lanes.json` reached `status=awaiting_final_action` with pending
  final hold `final-d71020c9276d`. Summary:
  `/tmp/xmuse-goal-loop7gr-final-review-mcp-rqmg9ktr/loop7gr_review_prompt_quarantine_summary.json`.
  This proves local platform-runner execution/review MCP to final-action hold
  only. It does not prove GitHub/server truth, merge/import, real gate profile
  enforcement, Grok platform review routing, or full xmuse closure. The next
  action is `Loop 7H-R`: audit pending final-action hold
  `final-d71020c9276d` and decide whether to reject it as probe-only/no-import,
  approve the no-op hold, or convert the open `gate_profiles.json`/manual
  final-action boundary into the next targeted runtime proof.
- Loop 7F-R on 2026-06-21 reran a minimal real platform-runner lane against a
  live xmuse MCP server in runtime root
  `/tmp/xmuse-goal-loop7fr-runner-mcp-nckrn_t1`. The runner spawned a real
  Codex execution child with command MCP config
  `mcp_servers.xmuse-platform.url="http://localhost:34869/sse"`. The first
  execution spawn
  `logs/agent_spawns/loop7f-runner-child-mcp-writeback/20260620T233649Z.stderr.log`
  contains `mcp: xmuse-platform/query_knowledge started/completed` and
  `mcp: xmuse-platform/update_lane_status started/completed`; durable
  `feature_lanes.json` recorded
  `last_mutation_audit.tool=update_lane_status`, `tests_run=["not run:
  runner-spawned MCP writeback probe"]`, and `changed_files=[]`. This proves
  the repaired execution child prompt works through the actual
  `xmuse-platform-runner -> AgentSpawner -> codex exec -> xmuse MCP -> lane
  projection` path. The run then exposed the next boundary: review prompt
  contamination. The review worker received the execution lane task as
  imperative text, attempted the child-worker
  `update_lane_status(status="executed", guard={"current_status":"dispatched"})`
  instruction while the lane was already `gated`, observed a state-guard
  mismatch, attempted `gate_failed` after `gate_passed=true` and hit state
  invariants, then emitted a `rework` verdict through MCP. The runner retried
  once and exited at `status=gated` with a second pending review task when
  `--max-hours` elapsed. Summary:
  `/tmp/xmuse-goal-loop7fr-runner-mcp-nckrn_t1/loop7fr_runner_spawned_child_mcp_writeback_summary.json`.
  No final-action hold, GitHub/server truth, merge truth, Grok platform review
  routing proof, or review-prompt repair proof exists. The next action is
  `Loop 7G-R`: repair or quarantine review prompt task-context contamination,
  ensure review failure/status fallback does not attempt `gate_failed` when
  `gate_passed=true`, and rerun the same minimal platform-runner lane to reach
  `reviewed` or final-action hold without false rework.
- Loop 7E-R on 2026-06-21 isolated and repaired the child Codex MCP
  tool-exposure/writeback boundary in runtime root
  `/tmp/xmuse-goal-loop7er-mcp-probe-zgquo_id`. HTTP JSON-RPC proved the live
  xmuse MCP server exposed `query_knowledge` and `update_lane_status`; direct
  imperative `codex exec` prompts then called both tools and changed isolated
  lane `loop7e-mcp-probe` to `executed`. A full
  `build_execution_prompt()` child prompt reproduced the old failure:
  `status=exec_failed`,
  `failure_reason=child_mcp_required_but_unavailable`, and the lane remained
  `dispatched`. The root cause was the child prompt's model-facing tool-name
  contract: it emphasized `mcp__xmuse_platform.query_knowledge` plus fallback
  language, while current Codex exposes the tool in traces as
  `xmuse-platform/query_knowledge`. The prompt contract was patched in
  `xmuse/god_prompts/execution_god.md` and covered by
  `tests/xmuse/test_platform_prompt_builders.py`; focused prompt tests passed
  (`3 passed`). A repaired full child prompt then called
  `xmuse-platform/query_knowledge` and `xmuse-platform/update_lane_status`, and
  `feature_lanes.json` recorded
  `loop7e-mcp-required-prompt-rerun.status=executed` with
  `last_mutation_audit.tool=update_lane_status`. Summary:
  `/tmp/xmuse-goal-loop7er-mcp-probe-zgquo_id/loop7er_child_codex_mcp_prompt_contract_summary.json`.
  This is local child-prompt/writeback proof only: no full platform-runner lane,
  review worker, Grok platform review routing, GitHub/server truth, or merge
  truth was produced. The next action is `Loop 7F-R`: rerun a minimal
  platform-runner MCP-required execution lane using the repaired child prompt
  against a live xmuse-mcp-server.
- Loop 7D-R on 2026-06-21 audited pending final-action hold
  `final-fdf66ded3605` in runtime root
  `/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY`. The isolated execution
  worktree `/tmp/xmuse-goal-loop7cr-mcp-exec-ialBKYv` contained one untracked
  docs artifact, `docs/xmuse/loop7b-corrected-execute-ready-proof.md`, and no
  tracked diff. The artifact was accurate within its own proof boundary, but
  control evidence docs already contained the same Loop 7B/7C durable refs and
  stronger current context. Because Loop 7C-R execution/review used stdout
  fallback, the gate passed open with missing `gate_profiles.json`, and review
  provider selection was `codex.review` rather than Grok platform review
  routing, the final-action auditor rejected the hold without importing the
  worker artifact. `final_actions.json` now records `status=rejected` and
  `resolved_by=loop7dr-audit-no-import`. Audit summary:
  `/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY/loop7dr_final_action_audit_summary.json`.
  No final-action approval/import, GitHub/server truth, or merge truth exists.
  The next action is `Loop 7E-R`: isolate and repair or revalidate child Codex
  MCP tool exposure/writeback for execution/review workers.
- Loop 7C-R on 2026-06-21 copied the approved Loop 7B-R runtime root to
  `/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY`, overwrote the projected lane
  `worktree` to isolated execution worktree
  `/tmp/xmuse-goal-loop7cr-mcp-exec-ialBKYv`, and consumed the queued dispatch
  entry into durable `dispatch_handoff`
  `msg_f2217f76b34f48d8af15f2dc32acf517`. A first attempt without an MCP
  server failed at `child_mcp_required_but_unavailable`; the rerun started a
  temporary MCP server for the copied root on port `39861` before invoking
  platform runner with `--no-auto-merge`. The lane reached
  `awaiting_final_action` with state history
  `dispatched -> executed -> gated -> reviewed -> awaiting_final_action`,
  review task `rtask_2f9c87921af3457cbb6dde752bc85694`, merge verdict
  `verdict-merge-rtask_2f9c87921af3457cbb6dde752bc85694`, and pending final
  action hold `final-fdf66ded3605`. The execution worktree contains one
  untracked docs artifact,
  `docs/xmuse/loop7b-corrected-execute-ready-proof.md`. This proves a local
  dispatch-to-final-action-hold slice through the isolated worktree, but both
  execution and review reported MCP tools unavailable and proceeded through
  stdout fallback; review provider selection was `codex.review`, not Grok
  platform review routing. Loop 7D-R later rejected the pending final-action
  hold without importing the worker artifact.
- Loop 7B-R on 2026-06-21 corrected the approval-readiness proof in isolated
  root `/tmp/xmuse-goal-loop7br-execute-ready-r0cyfrw2`. It created a real
  `@execute` collaboration run
  `collab_55f757d8e3fa44db97ca8e06f2e932d3`, ran a Codex execute peer through
  `PeerChatScheduler`, and durably recorded
  `collab_resp_80210c543c884f6b8debde0b1498b5f8` with
  `target=@execute`, `type=execute_feasibility_verdict`,
  `verdict=dispatchable`, and `execution_performed=false`. The execute inbox
  `inbox_151cf56d3e014b45a8c97e014e6d9fcd` reached `read` with
  `delivery_mode=mcp_writeback`, `degraded_reason=null`, and
  `total_latency_ms=171719`. A fresh proposal
  `prop_d47c207c2e59467cb276a80b4d4740e4` was created after collaboration
  completion and approved into resolution
  `res_954c10cef8ae46beb53b766ebaec5216`; dispatch gate event
  `collab_gate_803915621d49443eaf067841f0ec1f03` recorded
  `decision=allowed` and `execute_confirmed=1`. The root now has a lane graph,
  `feature_lanes.json` projection with one pending lane, and one queued
  dispatch entry. Loop 7C-R later consumed that dispatch queue into isolated
  execution and final-action hold.
- Loop 7-R on 2026-06-21 audited approval readiness for the Loop 6I-R/6J-R
  proposal in copied root `/tmp/xmuse-goal-loop7r-approval-audit-v7cgk7bs`.
  Calling `POST /api/chat/proposals/prop_260a6958c5754f8bb00e2568f4a9229a/approve`
  returned `400 dispatch_gate_blocked: blocked_execute_not_confirmed` and
  persisted dispatch gate event
  `collab_gate_72ca53ee7e314297be2e36b54118146a` with
  `execute_confirmed=0`. The referenced collaboration run
  `collab_1cd8035f0dcb49c48a7f5fcad93e21a4` is `done`, and its content is a
  dispatchable `execute_feasibility_verdict`, but its durable target is
  `@architect`, not `execute`/`@execute`. The proposal remains `open`;
  `resolutions=[]`, no lane graph projection, no `feature_lanes.json`, no
  review plane, no final action, no dispatch, no GitHub, and no merge truth.
  Loop 7B-R later reran the proof with an actual `@execute` target and reached
  approval/projection/queued-dispatch evidence.
- Loop 6J-R on 2026-06-21 copied the Loop 6I-R runtime root to
  `/tmp/xmuse-goal-loop6jr-review-trigger-2ymsb8y0` and closed the downstream
  inbox boundary before approval. The stale collaboration callback
  `inbox_f7a34137836b43558af6d8fd31f25e71` was terminally classified as
  `failed` with reason
  `superseded_by_existing_proposal:prop_260a6958c5754f8bb00e2568f4a9229a`
  because the existing proposal already contains
  `collaboration:collab_1cd8035f0dcb49c48a7f5fcad93e21a4`. The automatic
  proposal review trigger `inbox_7bc04d1d03e24617bc8b90f3fb743343` was consumed
  by Grok through the real scheduler and callback bridge; it reached `read`
  with durable review message `msg_e353adbab38d4036a86e0966ef47917a`,
  `delivery_mode=mcp_writeback`, `degraded_reason=null`, and
  `total_latency_ms=20279`. The copied root has `non_terminal_inboxes=[]`; the
  proposal remains `open` and unapproved. Loop 7-R later proved approval is
  blocked until an actual `@execute` confirmation exists.
- Loop 6I-R on 2026-06-21 reran the current groupchat-produced proposal proof
  with the corrected architect-only routing pattern. Runtime root
  `/tmp/xmuse-goal-loop6ir-proposal-t1lu4s7l` contains conversation
  `conv_8ec9b7b7d6e546d58e4d7230130b0fc6` and open lane_graph proposal
  `prop_260a6958c5754f8bb00e2568f4a9229a`. Human messages mentioned only
  `@architect`; Codex wrote `CODEX_L6I_REVIEW_REQUEST_OK`, created the Grok
  review inbox through `chat_mention`, Grok replied through callback
  writeback, and Codex emitted proposal `Loop 6-I Corrected Durable Proposal
  Proof` with refs to the human demand, Codex handoff, Grok review, human
  proposal request, and collaboration evidence. All three provider turns were
  durable `mcp_writeback` with `degraded_reason=null`; `chat_request_log` has
  `chat_post_message x3`, `chat_mention x1`, and `chat_emit_proposal x1`.
  Loop 6J-R later consumed/classified the downstream callback/review-trigger
  state in a copied runtime root, so the remaining unclosed boundary is no
  longer proposal-production but proposal approval/final-action hold.
- Loop 6H-R on 2026-06-21 ran a corrected handoff-only probe after Loop 6G-R's
  partial proposal proof. Runtime root `/tmp/xmuse-goal-loop6hr-handoff-df2yyv7f`
  contains conversation `conv_8879e65e464b4a10b3c7cd134dc018ad`. The human
  message mentioned only `@architect`; Codex replied
  `CODEX_L6H_HANDOFF_ACK_OK` and created the Grok review inbox with
  `chat_mention`; Grok replied `GROK_L6H_HANDOFF_REPLY_OK` through the callback
  bridge. Both inboxes reached `read`; request log shows `chat_post_message x2`
  and `chat_mention x1`; both latency traces are `mcp_writeback` with
  `degraded_reason=null`. This proves the Loop 6G-R handoff weakness was a
  harness prompt issue, not a Grok registration or scheduler routing failure.
- Loop 6G-R on 2026-06-21 attempted the current groupchat-produced proposal
  proof after the repeated-clean Codex-Grok peer path. Runtime root
  `/tmp/xmuse-goal-loop6r-current-proposal-cw926lko` contains conversation
  `conv_30d055299d3049bdb41850b8e715ff58` and proposal
  `prop_78db403afc624b8a947ad7fce8adf39c`. The run proved that a current
  Codex architect and Grok review discussion can be cited by a durable
  `lane_graph` proposal (`Loop 6-R Current Durable Proposal Proof`) with
  source message refs and `chat_emit_proposal x1`. It is only a partial Loop
  6-R proof: the first Codex turn wrote `chat_post_message` but timed out at
  the scheduler boundary (`peer_response_timeout`, `total_latency_ms=300210`),
  `chat_mention x0`, and the human demand directly mentioned `@review`, so
  Grok's review inbox was not produced by Codex handoff. The proposal also
  created an unread automatic review-trigger inbox. The next action is
  `Loop 6H-R`: rerun a corrected Codex-to-Grok handoff-only probe where human
  mentions only `@architect` and Codex must create the `@review` inbox through
  `chat_mention` under the 300s scheduler budget before rerunning proposal
  proof or advancing to approval/lane execution.
- Loop 5F-R on 2026-06-21 reran the current Codex-Grok three-turn short soak
  after the Loop 5E-R timeout-budget patch. Runtime root
  `/tmp/xmuse-goal-loop5fr-codex-grok-soak-g7_cnr84` contains conversation
  `conv_8f9b98975dbb449f9d8c40aff77f9194`. All three
  `human -> Codex @architect -> Grok @review` turns completed through durable
  MCP writeback with rebuilt `GodSessionLayer` instances. All six inboxes
  reached `read`; all six latency traces have `delivery_mode=mcp_writeback`
  and `degraded_reason=null`; `chat_request_log` has `chat_post_message x6`
  and `chat_mention x3`; `failure_traces=[]`; and
  `final_non_read_inbox_items=[]`. Codex latencies were `151356ms`,
  `156991ms`, and `180171ms`, so the third turn would have been cut off by the
  old 180s budget. Grok reused provider session
  `019ee6dc-9712-7091-aad9-12862a4e1de6` on turns 2 and 3. This gives the
  current revalidation line a second clean three-turn short-soak sample after
  the timeout-budget patch, but provider events still show nested Codex shell
  reads (`/bin/bash=2`, `sed -n=1`, `cat /mnt=1`), so do not claim tool-free
  peer turns.
- Loop 5E-R on 2026-06-21 isolated the Loop 5D-R timeout boundary and applied a
  minimal peer-chat timeout budget patch. Runtime root
  `/tmp/xmuse-goal-loop5er-codex-only-probe-h3q2ghdm` showed Codex reply-only
  completed in `153625ms`, while Codex reply-then-mention completed in
  `206055ms`: it wrote `CODEX_L5ER_HANDOFF_ACK_OK`, called `chat_mention`, and
  created review inbox `inbox_8a8f202b45c04dcdb28b6a7cad600ff1`. Therefore the
  first failing Loop 5D-R boundary was narrowed to the old 180s peer-chat wait
  being too tight for current Codex multi-action turns. The patch sets
  peer-chat scheduler and dispatch bridge budgets to `response_wait_s=300.0`
  and `claim_ttl_s=360`, including platform runner wiring. A default-budget
  real rerun at `/tmp/xmuse-goal-loop5er-default-budget-rerun-pm5u9ab1`
  confirmed `scheduler_defaults.response_wait_s=300.0`,
  `scheduler_defaults.claim_ttl_s=360`, `happy_path=1`, `chat_post_message x1`,
  `chat_mention x1`, a read architect inbox, an unread review inbox, and
  `delivery_mode=mcp_writeback` with `degraded_reason=null`. Focused tests
  passed for `tests/xmuse/test_peer_chat_scheduler.py` and
  `tests/xmuse/test_platform_runner.py` (`79 passed, 1 Ray warning`), and ruff
  passed on touched files.
- Loop 5D-R on 2026-06-21 attempted the required second current Codex-Grok
  three-turn short soak and did not produce a second clean sample. Runtime root
  `/tmp/xmuse-goal-loop5dr-codex-grok-soak-78ly1o7z` contains conversation
  `conv_f3f13b1aae954092bdb1d38040a89040`. The first Codex architect turn
  wrote durable assistant message `CODEX_L5DR_TURN1_ACK_OK` through
  `chat_post_message`, and the architect inbox reached `read`, but the provider
  turn did not return before the 180s scheduler wait boundary and did not call
  `chat_mention`. The durable latency trace has `delivery_mode=failed`,
  `degraded_reason=peer_response_timeout`, and `total_latency_ms=180115`;
  `chat_request_log` has `chat_post_message x1` and `chat_mention x0`; no Grok
  inbox or Grok reply was created. Therefore Loop 5C-R remains one clean
  three-turn sample, not a repeated-clean promotion basis for Loop 6-R.
- Loop 5C-R on 2026-06-21 produced a current Codex-Grok three-turn short soak.
  Runtime root `/tmp/xmuse-goal-loop5cr-codex-grok-soak-iyx4377d` contains
  conversation `conv_fabdd5b2ceb147538e99e6f6156a04ed`. The run completed
  `CODEX_L5CR_TURN1_ACK_OK -> GROK_L5CR_TURN1_REPLY_OK.`,
  `CODEX_L5CR_TURN2_ACK_OK -> GROK_L5CR_TURN2_REPLY_OK.`, and
  `CODEX_L5CR_TURN3_ACK_OK -> GROK_L5CR_TURN3_REPLY_OK.` across rebuilt
  `GodSessionLayer` instances. All six inboxes reached `read`; all six latency
  traces have `delivery_mode=mcp_writeback` and `degraded_reason=null`;
  `chat_request_log` has six `chat_post_message` rows and three `chat_mention`
  rows; `failure_traces=[]`; and `final_non_read_inbox_items=[]`. Grok reused
  provider session `019ee6b7-59db-7c02-9b83-9a1a4e1e8563` on turns 2 and 3.
  Codex latency remained high but below the 180s scheduler wait boundary
  (`154580ms`, `139324ms`, `139109ms`). The prior Loop 5B-R shell-read
  discipline risk did not recur as `/bin/bash`, `sed -n`, `cat /mnt`, or
  `exec\n` traces in `provider_events.jsonl`, but the risk remains open until
  repeated samples confirm it.
- Loop 5B-R on 2026-06-21 produced a bounded current Codex-Grok
  restart/resume reliability sample. Runtime root
  `/tmp/xmuse-goal-loop5br-codex-grok-resume-obo_z1xr` contains conversation
  `conv_60283595c95e4c4fb9fe3c0fd34428f0`. Turn 1 completed
  `CODEX_L5BR_TURN1_ACK_OK -> GROK_L5BR_TURN1_REPLY_OK`; after rebuilding
  `GodSessionLayer`, turn 2 completed
  `CODEX_L5BR_TURN2_ACK_OK -> GROK_L5BR_TURN2_REPLY_OK`. All four inboxes
  reached `read`; all four peer latency traces have
  `delivery_mode=mcp_writeback` and `degraded_reason=null`; `chat_request_log`
  has four `chat_post_message` rows and two `chat_mention` rows. Grok reused
  provider session `019ee6ad-529e-71d3-a42a-7f9aab88754c` after the rebuild.
  This sample does not repeat Loop 4's timeout or prior
  `peer_no_inbox_side_effect`, but Codex's post-rebuild turn still took
  `178643ms`, close to the 180s wait boundary. Provider events also show the
  nested Codex peer harness executed local shell reads for its own skill policy,
  so this proves durable writeback/restart behavior, not tool-free peer turns.
- Loop 0-R on 2026-06-21 resolved the current `/goal` resume selector. The
  evidence ledger contains two valid same-day lines: the active prompt's current
  Grok peer revalidation line (`Loop 2A-R -> Loop 3-R -> Loop 4B -> Loop 5A`)
  and an older downstream fullchain line (`Loop 5B/5C/5D -> Loop 6 -> Loop 7 ->
  Loop 8 -> Loop 8B`). Because the active `/goal` objective reset the current
  work to Grok-as-GOD-peer revalidation, the current active line is the
  revalidation line and the single next action is `Loop 5B-R`: run a bounded
  current Codex-Grok restart/resume reliability sample. The older Loop 6-8B
  evidence remains valid historical downstream evidence, but it is not the
  next active boundary for this resumed revalidation sequence.
- Loop 5A on 2026-06-21 produced a bounded current Codex-Grok two-turn
  reliability sample without code changes. Runtime root
  `/tmp/xmuse-goal-loop5-codex-grok-reliability-4zbqelni` contains
  conversation `conv_6656d6bb0144432ab3afbf32bb2d8812`. Two sequential
  `human -> Codex @architect -> Grok @review` turns created four terminal
  inboxes, two Codex ACK messages, two Codex-created `@review` mention
  messages, and two Grok replies. All four latency rows have
  `delivery_mode=mcp_writeback` and `degraded_reason=null`. The Loop 4 180s
  Codex `peer_response_timeout` did not repeat in this sample, but the Codex
  turns were close to the 180s boundary (`179694ms` and `175681ms`), so timeout
  budget remains an open reliability risk rather than a closed issue. This
  proves one bounded two-turn local sample only; it does not prove
  restart/resume, overnight soak, proposal production, lane execution, or
  GitHub/server truth.
- Loop 4B on 2026-06-21 revalidated current Codex -> Grok durable peer handoff.
  Runtime root `/tmp/xmuse-goal-loop4b-codex-grok-handoff-sd6vf62g` contains
  conversation `conv_b75635ceefbc4c9d88240668c1a90a0b`. Human created only the
  `@architect` inbox `inbox_8589f39cae324d8298ed597b349e95e5`; Codex architect
  `part_554538a8173d4d4f89cc4d983be29d00` replied
  `CODEX_GOAL_LOOP4B_HANDOFF_ACK` and wrote durable mention message
  `msg_b11e6cf067604e668d4eb4975362b9f8` with `mentions=["@review"]`.
  That mention created Grok inbox `inbox_bc6c0e9ab9304e6a899cf33bc25b898c`
  with sender `part_554538a8173d4d4f89cc4d983be29d00` and source message
  `msg_b11e6cf067604e668d4eb4975362b9f8`. Grok review peer
  `part_53418e5d197841c49c0a0dc743a7a109` consumed that inbox and replied
  `GROK_GOAL_LOOP4B_HANDOFF_REPLY_OK.` through the callback bridge. Both
  Codex and Grok latency traces have `delivery_mode=mcp_writeback` and
  `degraded_reason=null`. A first Loop 4 attempt with `response_wait_s=180`
  produced the same durable side effects but recorded Codex
  `peer_response_timeout`; the clean Loop 4B rerun used `response_wait_s=300`.
  This proves current local peer handoff only; it does not prove multi-turn
  reliability, restart/resume, proposal production, lane execution, or
  GitHub/server truth.
- Loop 3-R on 2026-06-21 revalidated current same-conversation Codex + Grok
  durable writeback. Runtime root
  `/tmp/xmuse-goal-loop3-codex-grok-writeback-jkybnov6` contains conversation
  `conv_ca08da47ebe94b0686ae097f5a76e4bf` with Codex architect participant
  `part_50e93744c53d471b802c0f62fcdeb2ce` and Grok review participant
  `part_cef850b1df954cd2bee976755e2f1133`. Codex inbox
  `inbox_4c69f476a0d24813abbdb47c40340f5e` reached `read` with assistant
  message `msg_95a85c0ff8fb42fd8af6642b7aaceefd` containing
  `CODEX_GOAL_LOOP3_WRITEBACK_OK.` and latency
  `delivery_mode=mcp_writeback`, `degraded_reason=null`, with
  `chat_read_inbox` and `chat_post_message` stage timings. Grok inbox
  `inbox_20e4c099168e4caa97e331425354591f` reached `read` with assistant
  message `msg_8f461a07d1324a829b4e5d9f721aa70e` containing
  `GROK_GOAL_LOOP3_WRITEBACK_OK.`, `writeback_path=grok_callback_bridge`,
  GOD session `runtime=grok`, provider session kind `grok_cli_session`, and
  latency `delivery_mode=mcp_writeback`, `degraded_reason=null`, with
  `chat_post_message` stage timing. This proves current local two-peer
  writeback only; it does not prove peer-to-peer handoff, multi-turn
  reliability, proposal production, lane execution, or GitHub/server truth.
- Loop 2A-R on 2026-06-21 revalidated the current worktree's Grok GOD peer
  path for the active task boundary. Runtime root
  `/tmp/xmuse-goal-loop2a-grok-peer-4wza39t7` contains conversation
  `conv_9c0e858b43d14c20a3802826e2effeb7`, Grok participant
  `part_8c41dc039054492c8b9ae0690300778c` with `cli_kind=grok` and model
  `grok-composer-2.5-fast`, inbox
  `inbox_cfde090e381d45779e90ddb8a681bf65` in `read` state, assistant message
  `msg_378dc11350c54fd2b2f10df2435e3280` containing
  `GROK_GOAL_LOOP2A_WRITEBACK_OK`, GOD session
  `god-31ef66f2971448baaeb2d2649eb7ba06` with `runtime=grok`,
  `provider_session_kind=grok_cli_session`, provider session id
  `019ee684-446a-72c3-bd6c-90960f87b82c`, and a peer latency trace with
  `delivery_mode=mcp_writeback`, `degraded_reason=null`, and
  `chat_post_message` stage timing. This proves current local Loop 2A
  participant/session/inbox/writeback behavior only; it does not prove lane
  execution, platform `god_runtime=grok`, provider-plane Grok profiles, or
  multi-turn reliability.
- Loop 8B on 2026-06-21 reran approval-to-final-action hold using the new
  evidence-carrying approved-proposal contract. Runtime root
  `/tmp/xmuse-loop8b-finalhold-root-7af3fb07` approved proposal
  `prop_ba139bc0b76845aa98a36a56bd5e3835` into resolution
  `res_4461386b411442fca8a59fbbec599227` and dispatched
  `loop6_grok_reviewed_proposal` in git worktree
  `/tmp/xmuse-loop8b-exec-f1d0da0b`. The child prompt contained the Loop 8
  approved-proposal execution contract and durable Loop 6 refs, but the lane
  stopped at `exec_failed` with
  `failure_reason=child_mcp_required_but_unavailable` and
  `stdout_fallback_rejected=true`. `review_plane.json` and
  `final_actions.json` were not created. MCP SSE HTTP traffic reached the
  server, so the new first downstream boundary is model-facing Codex child MCP
  tool exposure/writeback, not approval projection.
- Loop 8 on 2026-06-21 repaired the first Loop 7 producer boundary. Approved
  `lane_graph` proposals now wrap each lane prompt with an "Approved proposal
  execution contract" before saving the lane graph and projecting
  `feature_lanes.json`. A copied Loop 6 runtime root
  `/tmp/xmuse-loop8-approval-contract-zxtje9yb` approved proposal
  `prop_ba139bc0b76845aa98a36a56bd5e3835` into resolution
  `res_251a13b51dbe45d7be71f15c6794daa9`; graph source refs and prompt artifact
  `/tmp/xmuse-loop8-approval-contract-zxtje9yb/logs/lane_prompts/loop6_grok_reviewed_proposal.md`
  now carry the resolution ref, proposal ref, Grok review message ref, runtime
  root, chat.db, and Loop 6 summary artifact. This proves the approval
  projection repair only; it does not prove execution success, final-action
  hold, or Grok platform-review routing.
- Loop 7 on 2026-06-21 approved the Loop 6 Grok-reviewed proposal into an
  isolated execution projection, but did not reach final-action hold. Approval
  root `/tmp/xmuse-loop7-approve-finalhold-d4aa52qi` created resolution
  `res_c9fff755337f4c2f8e2bbb1ec85ba8f9`. The corrected unique-branch rerun
  under `/tmp/xmuse-loop7c-exec-failure-contract-rdgogmxl` created resolution
  `res_5d67c5a2896e469ab6463855a6e12d44`, executed in
  `/tmp/xmuse-loop7c-exec-ce0351c7`, reached Codex review rework verdict
  `verdict-rework-loop6_grok_reviewed_proposal`, then ended as `exec_failed`
  after rework because child MCP writeback was unavailable. `final_actions.json`
  was never created. This proves approval/projection and execution/review
  rejection, not safe final-action hold. It also exposed that
  `review_runtime=grok` remains metadata for platform execution; review routed
  to Codex.
- Loop 6 on 2026-06-21 produced local real runtime proof for a bounded
  Codex-Grok groupchat-produced proposal. Runtime root
  `/tmp/xmuse-loop6-codex-grok-proposal-b55nt9e8` contains conversation
  `conv_0a0e39214e944f80bb5a5aaf25ffd4fd`. Codex architect
  `part_9ff3d62fff9b43f09d14787f0ae1e526` and Grok review
  `part_cec7ea3852d744a582890566261eb763` completed:
  human -> Codex intake ack, Codex -> Grok preproposal review, Grok review
  containing `GROK_L6_REVIEW_READY_FOR_PROPOSAL`, Codex
  `chat_emit_proposal`, automatic Grok `review_trigger`, and Grok trigger
  reply. Proposal `prop_ba139bc0b76845aa98a36a56bd5e3835` is an open
  `lane_graph` proposal with one docs-only lane
  `loop6_grok_reviewed_proposal`, `review_runtime=grok`, and reference
  `message:msg_6dc2805535d744cc8a4e84d4c85be8bf`. All four inboxes reached
  `read`; all four latency traces have `delivery_mode=mcp_writeback` and
  `degraded_reason=null`; `resolutions=[]`; and `feature_lanes.json` was not
  created. This proves proposal production and review-trigger consumption only;
  it does not prove approval, dispatch, lane execution, final action, GitHub
  truth, or merge truth.
- Loop 5D on 2026-06-21 produced a second clean local Codex + Grok three-turn
  short soak with explicit provider-turn artifact capture. Runtime root
  `/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7` contains conversation
  `conv_14ac6db06e7d4c67a9233cd1643d0e6b`. Codex architect
  `part_9cc94aa6014147e5a3ee4820abaf5b92` and Grok review
  `part_a9961ec7560d4000b144a9a17edaa2de` completed three human -> Codex ->
  Grok handoffs: `CODEX_L5D_TURN1_ACK_OK` -> `GROK_L5D_TURN1_REPLY_OK`,
  `CODEX_L5D_TURN2_ACK_OK` -> `GROK_L5D_TURN2_REPLY_OK`, and
  `CODEX_L5D_TURN3_ACK_OK` -> `GROK_L5D_TURN3_REPLY_OK`. All six inboxes
  reached `read`; all six latency traces have `delivery_mode=mcp_writeback`
  and `degraded_reason=null`; `failure_traces=[]`; and
  `final_non_read_inbox_items=[]`. Grok reused provider session
  `019ee626-98df-7c50-b301-8d697ea96bc2` on turns 2 and 3 after session-layer
  rebuilds. Together with Loop 5C, this gives two clean short-soak samples, not
  overnight reliability, proposal production, lane execution, GitHub truth, or
  merge truth.
- Loop 5C on 2026-06-21 produced a clean local Codex + Grok three-turn short
  soak with explicit provider-turn artifact capture. Runtime root
  `/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d` contains conversation
  `conv_7c9f17af64c1427eaf5bd9943606acea`. Codex architect
  `part_ca6614226f004488b7d4819431517cad` and Grok review
  `part_9491a8ad4ed24448af5b1a416c4e2800` completed three human -> Codex ->
  Grok handoffs: `CODEX_L5C_TURN1_ACK_OK` -> `GROK_L5C_TURN1_REPLY_OK`,
  `CODEX_L5C_TURN2_ACK_OK` -> `GROK_L5C_TURN2_REPLY_OK`, and
  `CODEX_L5C_TURN3_ACK_OK` -> `GROK_L5C_TURN3_REPLY_OK`. All six inboxes
  reached `read`; all six latency traces have `delivery_mode=mcp_writeback`
  and `degraded_reason=null`; `failure_traces=[]`; and
  `final_non_read_inbox_items=[]`. `provider_events.jsonl` captured six
  successful provider receive events. Grok reused provider session
  `019ee618-083f-7ef2-bbfd-6b421c4c832a` on turns 2 and 3 after session-layer
  rebuilds. This is one clean short-soak sample and does not prove overnight
  reliability, proposal production, lane execution, GitHub truth, or merge
  truth.
- Loop 5B on 2026-06-21 produced a second local Codex + Grok restart/resume
  sample, but it was not zero-retry reliable. Runtime root
  `/tmp/xmuse-loop5b-codex-grok-resume-k2msw2e9` contains conversation
  `conv_9492b501e94a4826a510402064d96971`. Turn 1 completed normally:
  Codex wrote `CODEX_L5B_TURN1_ACK_OK`, created a durable `@review` inbox, and
  Grok wrote `GROK_L5B_TURN1_REPLY_OK`. After rebuilding `GodSessionLayer`,
  the second Codex architect attempt returned a provider result but created no
  durable `chat_post_message` or `chat_mention` side effect; scheduler recorded
  `delivery_mode=failed`, `degraded_reason=peer_no_inbox_side_effect`, left
  inbox `inbox_6c5fc48dda0a4c22b502f80209f83f48` unread, and incremented
  `nudge_count=1`. A retry of the same inbox then succeeded with
  `CODEX_L5B_TURN2_ACK_OK`, created review inbox
  `inbox_c236f827f90e43f19fc2d773167a6a4e`, and Grok replied
  `GROK_L5B_TURN2_REPLY_OK`. The second Grok review reused provider session
  `019ee60c-0ee3-75e3-901c-a8cc48b29b6b`. This proves durable recovery after
  one transient Codex producer miss, not soak/overnight reliability.
- Loop 5 on 2026-06-21 produced one local restart/resume reliability sample for
  Codex + Grok handoff. Runtime root
  `/tmp/xmuse-loop5-restart-resume-fClwAR` contains conversation
  `conv_d0ee4175d61545bcae0437d65baec435` with Codex architect
  `part_caf68a4c665b48429ead2f4714907c8e` and Grok review
  `part_b60d5656ee2a4611828e7f9dbaa769fc`. Turn 1 wrote
  `CODEX_L5_TURN1_ACK_OK`, created a durable `@review` inbox, and Grok wrote
  `GROK_L5_TURN1_REPLY_OK`. After rebuilding `GodSessionLayer` from the same
  `god_sessions.json`, turn 2 wrote `CODEX_L5_TURN2_ACK_OK`, created a second
  durable `@review` inbox, and Grok wrote `GROK_L5_TURN2_REPLY_OK`. All four
  inboxes reached `read`; all four latency rows have
  `delivery_mode=mcp_writeback` and `degraded_reason=null`; request logs show
  Codex `chat_post_message` + `chat_mention` for both turns and Grok
  `chat_post_message` for both turns. The loop exposed and fixed a Grok
  provider-native resume gap: restarted Grok shims now receive the persisted
  `grok_cli_session` id. Focused tests passed (`7 passed in 0.21s`), and the
  post-patch Grok-only real rerun under `/tmp/xmuse-loop5-grok-resume-ki8zs13h`
  reused provider session `019ee604-3fdf-7e52-9621-ae7827e12107` across two
  restart-separated turns. This is still one restart/resume sample plus one
  provider-resume proof; it is not soak/overnight reliability, proposal
  production, lane execution, Grok provider-plane adapter/profile support,
  GitHub truth, or merge truth.
- Loop 4 on 2026-06-21 produced local real runtime proof for a Codex-to-Grok
  peer handoff. Runtime root `/tmp/xmuse-loop4-codex-grok-handoff-NTskt3`
  contains conversation `conv_224378ef76654f328de23e52f6463525`, Codex
  architect `part_d38db40b0e5a4168bebd048a9510c346`, and Grok review
  `part_ea7382d5d20541e9a0a56b72c36a4538`. Human inbox
  `inbox_c8b47fdbf72f40d2a6f93197a4345af3` reached `read` after Codex wrote
  `CODEX_HANDOFF_ACK_OK`; Codex then wrote mention message
  `msg_2c370b9ca1e54441879b53fc63224eb9` with `mentions=["@review"]`, creating
  Grok inbox `inbox_2005a4bdd6d249ed98cf67735b582371`; Grok replied
  `GROK_HANDOFF_REPLY_OK` in `msg_324bda71355848d4a66d30b743b837f5`. The
  request log contains both Codex `chat_post_message` and `chat_mention`, plus
  Grok `chat_post_message`; both latency rows have
  `delivery_mode=mcp_writeback` and `degraded_reason=null`. This proves one
  local human -> Codex -> Grok handoff only; it does not prove repeated-run
  reliability, restart/resume recovery, proposal production, lane execution,
  Grok provider-plane adapter/profile support, GitHub truth, or merge truth.
- Loop 3 on 2026-06-21 produced local real runtime proof for durable Codex +
  Grok peer writeback in one conversation. Runtime root
  `/tmp/xmuse-loop3-codex-grok-ZZI9SH` contains conversation
  `conv_6646254388a54501a668961769d3bfa7` with Codex architect
  `part_e5b8e1b21a8f47859a17ab5159b9ecaf` and Grok review
  `part_81314a9fdf3543e79481c42f6c48d590`. Codex inbox
  `inbox_654ed99c3b0a42a5b69b843722711b58` and Grok inbox
  `inbox_8bb4dafade1f417eb1a38fab8530154f` both reached `read`; assistant
  messages `msg_3c8425418d2548b09a0422af3fc9d002` and
  `msg_b80fb4bf12b547b7ab8d46f7d61a6634` contain
  `CODEX_LOOP3_WRITEBACK_OK` and `GROK_LOOP3_WRITEBACK_OK`; both latency rows
  have `delivery_mode=mcp_writeback` and `degraded_reason=null`; both turns
  have `chat_post_message` tool evidence. This proves durable writeback for
  one Codex turn and one Grok turn only; it does not prove peer-to-peer
  handoff, multi-turn reliability, lane execution, Grok provider-plane
  adapter/profile support, GitHub truth, or merge truth.
- Loop 2A on 2026-06-21 registered Grok as the current non-Codex GOD
  groupchat peer for local runtime proof. Focused tests passed
  (`48 passed in 7.74s`). A real scheduler smoke under
  `/tmp/xmuse-grok-peer-binding-DRpRNL` created durable participant
  `part_4e27d009c6dc4d459bbfb1017de172c1` with `cli_kind=grok`, created GOD
  session `god-f5485c412cca46bea7214d90f3085f22` with `runtime=grok`,
  persisted `provider_session_kind=grok_cli_session` and Grok session id
  `019ee5e5-ad6a-7443-be2f-1be51a9f283b`, delivered inbox
  `inbox_9fd2e8fc9d16417993307c7bc16b85c4`, wrote assistant message
  `msg_0b2fda8fc75046b69ec8c6e051d0daf8`, and recorded
  `chat_post_message` in MCP tool stages. This proves one local
  inbox -> Grok -> durable writeback path only; it does not prove lane
  execution, provider-plane Grok profiles/adapters, platform
  `god_runtime=grok`, multi-turn reliability, GitHub truth, or merge truth.
- PR #67 merged the bounded child MCP prompt-contract clarification as GitHub
  server fact only: head `bd25527530686d8727eb26b233210688141ef2bf`,
  merge commit `5d1e1c7c25f9ddfa05a26a3ef600e333ca2da6a6`, merged at
  `2026-06-18T20:59:03Z`. No GitHub review truth is claimed.
- PR #68 merged the bounded CJK/formal collaboration-response detection fix as
  GitHub server fact only: head `d134f875f4d28a14c8cbaea841f9fba1709fa17f`,
  merge commit `24b8b257ace5b1f64d0b2099e8803e438a251453`, merged at
  `2026-06-18T21:19:52Z`. GitHub Actions run `27789931110` completed
  successfully for `contract-smoke-gates`, `quality-gates`, and
  `real-runtime-integration-gate`. No GitHub review truth is claimed.
- PR #69 merged the bounded gate profile authority fix as GitHub server fact
  only: head `31f3714052bc60e68f5bc75db8490cb6e0fd7f39`, merge commit
  `007811aaaebc7f82b05dd2dc781829ed026a2197`, merged at
  `2026-06-18T22:01:21Z`. GitHub Actions run `27791970708` completed
  successfully for `contract-smoke-gates`, `real-runtime-integration-gate`,
  and `quality-gates`. No GitHub review truth is claimed.
- PR #70 is an open draft small PR for the CJK collaboration fill/writeback
  detector: head `41954201ffab05d410e77b0c96f19cbeac76336a`, base `main`,
  URL `https://github.com/iiyazu/Cross-Muse/pull/70`. GitHub Actions run
  `27793722331` completed successfully for `contract-smoke-gates`,
  `real-runtime-integration-gate`, and `quality-gates`. No GitHub review truth
  or merge truth is claimed here.
- PR #71 is an open draft small PR for persistent review artifact grounding:
  head `cd713753343228ac928b79cf9611885d016eee23`, base `main`, URL
  `https://github.com/iiyazu/Cross-Muse/pull/71`. GitHub Actions run
  `27795048428` completed successfully for `contract-smoke-gates`,
  `real-runtime-integration-gate`, and `quality-gates`. No GitHub review truth
  or merge truth is claimed here.
- Loop 25z22 reran the clean post-PR68 path from main at
  `24b8b257ace5b1f64d0b2099e8803e438a251453`. Human mentioned only
  `@architect`; Codex architect created collaboration
  `collab_9b1d2393013c452587cffe0c513d4065`; Codex execute and OpenCode
  review both wrote durable `collaboration_responses`; architect emitted
  proposal `prop_0ef95194b4b442368ccd7a9076acd5bb`; manual approval produced
  resolution `res_214663f82f08465f90b49fe2c2c48904`; lane
  `loop25z22_post_pr68_clean_formal_collab_fullchain` reached
  `awaiting_final_action`.
- Loop 25z22 remains the strongest post-merge main proof for the bounded
  package-boundary lane: child Codex MCP tools were exposed, the child called
  `update_lane_status`, `uv run pytest tests/xmuse/test_package_boundaries.py -q`
  passed with `16 passed in 2.95s`, configured OpenCode review returned a
  merge verdict, and `--no-auto-merge` held final action at
  `final-3359846396cb`.
- Loop 25z23b is the current strongest candidate-branch proof for gate profile
  authority. Branch `codex/gate-profile-runtime-authority` at
  `31f3714052bc60e68f5bc75db8490cb6e0fd7f39` reran the clean bounded chain and
  produced gate report
  `logs/gates/loop25z23b_gate_profile_authority_fullchain/report.json` with
  `profile_ids=["strict-product"]`, package-boundary pytest `16 passed in
  2.99s`, and no `gate_profiles_missing` fail-open. PR #69 later supplied the
  exact GitHub CI and merge server facts for this head, but the runtime chain
  evidence remains local runtime proof.
- Loop 25z24 reran from post-PR69 main at
  `007811aaaebc7f82b05dd2dc781829ed026a2197`. Human mentioned only
  `@architect`; Codex architect created collaboration
  `collab_c288f01ad8be46e8947425a965d3124d`; Codex execute and OpenCode
  review both wrote durable responses; architect emitted proposal
  `prop_9f17d777d4654ea589b44f8c8f5fe759`; manual approval produced
  resolution `res_a5fa5185b2164a7faeda0d8809b95b80`; lane
  `loop25z24_post_pr69_gate_profile_main_fullchain` reached
  `awaiting_final_action`.
- Loop 25z24 is the current strongest post-merge main proof for gate profile
  authority: gate report
  `logs/gates/loop25z24_post_pr69_gate_profile_main_fullchain/report.json`
  used `profile_ids=["strict-product"]`, ran
  `uv run pytest -q tests/xmuse/test_package_boundaries.py`, passed with
  `16 passed in 3.00s`, and did not record `gate_profiles_missing`.
- Loop 25z25 reran from post-PR69 main at `007811a` with an explicit
  `review_runtime=opencode` target. The durable groupchat reached
  collaboration `collab_6b6adc941aa74afb89320099f19a20e1`, but OpenCode wrote
  ordinary chat message `msg_2e3625ec83a04d338da6e187ee8f1c26` instead of a
  formal `collaboration_responses` row when the request used the natural CJK
  phrase `协作响应工具回填`. The collaboration remained partial and no proposal
  dispatch happened.
- Loop 25z26 reran on candidate branch
  `codex/cjk-collab-response-tool-phrase` at `4195420`. It reached durable
  collaboration `collab_d4c53784db5f4d88a0aba61e4ba93434`, OpenCode formal
  response `collab_resp_407f6b61bc314781a936957ae90a0237`, proposal
  `prop_47f0d6057ab7405eb5595e7394816955`, dispatch, strict-product gate,
  configured OpenCode platform review with `review_runtime=opencode`,
  non-empty review evidence refs, and final hold `final-135ac3dde026`.
- Loop 25z27b reran from post-PR69 main at `007811a` with a clean initial
  `@architect` mention. It reached durable collaboration
  `collab_eeb0ffec254d455dbd781f2dafa61452`, accepted proposal
  `prop_1b09bb35d22842dd98f33fac687c4300`, resolution
  `res_53e495fa801d4c70a67b7cd837e59ab9`, configured OpenCode platform
  review, non-empty `review_evidence_refs`, and final hold
  `final-f9f998f0542a`. It also proved a negative review-plane fact: OpenCode
  said MCP tools were unavailable and then incorrectly stated no logs/gate
  artifacts existed, despite gate and worker artifacts existing in the runtime
  root.
- Loop 25z28 reran on candidate branch
  `codex/review-peer-artifact-grounding` at `cd713753`. It reached durable
  collaboration `collab_c29de586d02c44049be6e7d21027c5e9`, accepted proposal
  `prop_9a853383ff4e4433894040efc51b74c2`, resolution
  `res_d1e839d0c0214a14a1b6da1acb16e2b3`, configured OpenCode platform
  review, non-empty `review_evidence_refs`, and final hold
  `final-def8a28d600e`. The review summary cited the gate report, worker
  stdout/result logs, lane context bundle, git diff, and git status before
  emitting its verdict.
- Loop 25z23b still preserves open gaps: the runtime root had no override
  `gate_profiles.json` and therefore used the tracked lane worktree config
  with a warning; the platform OpenCode review plane still reported
  `MCP tools unavailable` and used stdout fallback; final action stayed
  pending; the proof level remains `local_runtime_proof` only.
- Loop 25z24 still preserves open gaps: the proposal set
  `review_runtime=local`, platform review used one-shot fallback with
  `persistent_review_degraded_reason=missing_feature_identity`, review
  evidence refs were empty, and final action stayed pending under
  `--no-auto-merge`.
- Loop 25z26 still preserves open gaps: the configured OpenCode review summary
  text said MCP tools were unavailable and reported via stdout, peer
  `session_health` still showed sessions as `status=starting`, duplicate
  proposal noise appeared as `prop_c41f9769aeb24debb58374204b767b16`, and the
  proof remains candidate local runtime proof until PR #70 receives server-side
  check results.
- Loop 25z28 still preserves open gaps: the configured OpenCode review provider
  still used stdout fallback because MCP tools were not exposed in that provider
  CLI session, duplicate proposal noise appeared as
  `prop_a4c905c2b2a6460583b61c06bfd0df63`, peer `session_health` still showed
  sessions as `status=starting`, and PR #71 remains draft/open/unmerged.
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
- Loop 18 reran the restart/resume and multi-turn handoff soak from clean
  `origin/main` after PR #47 merged. Run 1 reproduced prompt contamination
  when the human text included literal `@review`; clean runs 2/3/4 used only
  `@architect`, and each produced architect durable writeback, an
  architect-created review handoff, and OpenCode durable writeback. The durable
  result was 17 messages, 9 read inbox items, and 9 `mcp_writeback` latency
  traces with no degraded reason.
- Loop 23f and Loop 23g reached the strongest local runtime chain so far:
  human `@architect` demand -> durable Codex/OpenCode collaboration -> formal
  execute and review responses -> architect-emitted lane_graph proposal ->
  approval -> platform lane execution -> review -> `awaiting_final_action`.
  This is still local runtime proof only.
- Loop 23g preserved exact command scope for the lane:
  `uv run pytest tests/xmuse/test_package_boundaries.py -q`, with the lane
  worktree under `/tmp/xmuse-loop-23g-clean-dispatch-worktree-100647-exec` and
  final hold `final-74e460a0d061`.
- Loop 23 also found that chat-plane dispatch prompts could still carry the
  repository root as `execution_worktree` even when the platform lane worker
  used the isolated lane worktree. A targeted fix now routes dispatch prompts
  from `feature_lanes.json` via `lanes_path`; this is focused-validated and has
  a Loop 23h2 runtime recheck showing the dispatch prompt used the
  isolated lane worktree.
- Loop 23h2 exposed another real execute gate parser variant:
  `response_type=execute_feasibility_verdict` plus `verdict=dispatchable`.
  The approval gate initially blocked with `blocked_execute_not_confirmed`.
  A targeted parser fix accepted that shape without dropping command,
  proof-boundary, or notes requirements.
- After that fix, the same durable groupchat proposal approved and the lane
  reached `awaiting_final_action` with final hold `final-d2d756e69af0`. The
  dispatch prompt used `/tmp/xmuse-loop-23h2-dispatch-worktree-rerun-103026-exec`
  and did not contain the repository root.
- Loop 23h2 also preserved a negative finding: the chat dispatch queue failed
  with execute session reuse mismatch and the execute peer wrote
  `DISPATCH_FAILED` because a peer-chat nudge turn is chat-only. The platform
  lane worker still reached final-action hold through the lane authority path.
- Loop 24j reran the Codex/OpenCode groupchat-to-proposal-to-approval path
  after changing chat dispatch into lane-worker handoff. The dispatch queue
  reached `status=dispatched` with `provider_run_ref=lane_worker:*` and a
  durable `dispatch_handoff` message, then lane execution failed because the
  projected execution worktree path did not exist.
- Loop 24k reran after the local worktree lifecycle fix. It created the
  projected execution worktree before provider spawn and preserved the
  dispatch handoff evidence, then failed for an operator-safety reason: the
  lane prompt referenced tests that existed only in the dirty control worktree,
  not in the isolated worktree at committed HEAD `110dd47`.
- `production-closure-gap-ledger.md` was absent at the time of this older
  summary. Current runs use the ledger as the gap index.

## Findings

### F155. Runner-spawned execution child MCP writeback works; review prompt can execute lane-task instructions

Severity: positive execution proof with a newly classified review boundary.

Loop 7F-R proved the repaired execution child prompt works through the real
platform runner path. Runtime root:
`/tmp/xmuse-goal-loop7fr-runner-mcp-nckrn_t1`. Execution worktree:
`/tmp/xmuse-goal-loop7fr-exec-placeholder-hb1147dj`.

Evidence:

- `xmuse-platform-runner` dispatched
  `loop7f-runner-child-mcp-writeback` and spawned a real Codex execution child.
- The recorded child command used
  `mcp_servers.xmuse-platform.url="http://localhost:34869/sse"`.
- Execution stderr
  `logs/agent_spawns/loop7f-runner-child-mcp-writeback/20260620T233649Z.stderr.log`
  contains:
  - `mcp: xmuse-platform/query_knowledge started`
  - `mcp: xmuse-platform/query_knowledge (completed)`
  - `mcp: xmuse-platform/update_lane_status started`
  - `mcp: xmuse-platform/update_lane_status (completed)`
- Durable `feature_lanes.json` recorded
  `last_mutation_audit.tool=update_lane_status`, `tests_run`, and
  `changed_files=[]`.
- `state_history.json` recorded `pending -> dispatched` and
  `executed -> gated`.

New boundary:

- The first review worker also used MCP tools, but the review prompt contained
  the execution lane task as imperative text.
- The reviewer attempted the child-worker
  `update_lane_status(status="executed", guard={"current_status":"dispatched"})`
  instruction while the lane was already `gated`.
- That produced `state guard mismatch for update_lane_status: expected status
  dispatched` and a `rework` verdict.
- The same review turn attempted `gate_failed` after `gate_passed=true`; state
  invariants rejected that transition, so the reviewer made a second status
  attempt and recorded `rejected`/rework.
- The runner retried once, reached `gated` again, and exited with a second
  pending review task when the bounded `--max-hours` window elapsed.

Impact:

- F133/F154's execution child MCP exposure/writeback concern is repaired for
  the actual runner-spawned execution path.
- The next blocker is not execution MCP transport; it is review prompt
  contamination by unquoted executable lane-task instructions.

Limits:

- No final-action hold was reached.
- No GitHub/server truth, merge truth, Grok platform review routing proof, or
  review-prompt repair proof exists.

Next:

- Loop 7G-R should quarantine lane task text in review prompts as subject
  matter, ensure review workers do not execute child-worker MCP writeback
  instructions, prevent review fallback from attempting `gate_failed` after a
  passed gate, and rerun the same minimal platform-runner lane.

### F154. Child Codex MCP-required worker prompt used the wrong primary tool name

Severity: repaired local runtime producer/consumer contract bug.

Loop 7E-R showed that the child Codex MCP writeback failure was not a server or
SSE transport failure. In isolated root
`/tmp/xmuse-goal-loop7er-mcp-probe-zgquo_id`, HTTP JSON-RPC confirmed the live
xmuse MCP server exposed `query_knowledge` and `update_lane_status`, and direct
imperative Codex prompts successfully called both tools.

Evidence:

- HTTP tools/list exposed both `query_knowledge` and `update_lane_status`.
- Direct imperative Codex stderr showed
  `mcp: xmuse-platform/query_knowledge started/completed`.
- Direct writeback Codex stderr showed
  `mcp: xmuse-platform/update_lane_status started/completed`.
- The direct writeback probe changed lane `loop7e-mcp-probe` to `executed`
  with `last_mutation_audit.tool=update_lane_status`.
- Before repair, the full `build_execution_prompt()` child prompt still printed
  `failure_reason=child_mcp_required_but_unavailable` and left
  `loop7e-mcp-required-prompt-rerun` as `dispatched`.
- After repair, the same full child-prompt shape called both MCP tools and
  changed `loop7e-mcp-required-prompt-rerun` to `executed`.

Root cause:

- Current Codex exposes the working tool in traces as
  `xmuse-platform/query_knowledge`.
- The old child-worker prompt emphasized
  `mcp__xmuse_platform.query_knowledge` and allowed visibility
  self-judgment before a tool call, so the worker could choose stdout fallback
  without attempting the actual available tool.

Repair:

- `xmuse/god_prompts/execution_god.md` now makes
  `xmuse-platform/query_knowledge` the primary Codex-visible tool trace name
  and forbids visibility self-judgment for MCP-required lanes.
- `tests/xmuse/test_platform_prompt_builders.py` covers this prompt contract.

Limits:

- This proves local child-prompt MCP writeback only.
- It does not prove a full platform-runner lane after the prompt repair, review
  worker MCP behavior, Grok platform review routing, GitHub/server truth, or
  merge truth.

Next:

- Loop 7F-R should rerun a minimal platform-runner MCP-required execution lane
  against a live xmuse-mcp-server and stop at runner-spawned child writeback,
  review fallback, or the next producer/consumer boundary.

### F152. Loop 7C-R reaches isolated dispatch-to-final-action hold, with stdout fallback limits

Severity: positive local runtime boundary proof with remaining MCP/Grok review
limits.

Loop 7C-R advanced the current corrected execute-target proposal from queued
dispatch into the platform execution/review/final-action path. Runtime root:
`/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY`. Isolated execution worktree:
`/tmp/xmuse-goal-loop7cr-mcp-exec-ialBKYv`.

Evidence:

- Dispatch queue entry
  `dispatch:conv_acbacd44220c4b29819a284fa40aaf01:res_954c10cef8ae46beb53b766ebaec5216:execute`
  reached `status=dispatched`.
- Dispatch handoff message
  `msg_f2217f76b34f48d8af15f2dc32acf517` recorded
  `execution_worktree=/tmp/xmuse-goal-loop7cr-mcp-exec-ialBKYv`.
- Lane state history reached
  `dispatched -> executed -> gated -> reviewed -> awaiting_final_action`.
- Codex execution worker created
  `docs/xmuse/loop7b-corrected-execute-ready-proof.md` in the isolated
  worktree and exited `0`.
- Gate passed open because `gate_profiles.json` was missing; the gate report
  explicitly warns that no gate commands were run.
- Codex review emitted merge verdict
  `verdict-merge-rtask_2f9c87921af3457cbb6dde752bc85694`.
- Final-action gate created pending hold `final-fdf66ded3605` with
  `action=merge` and `target_status=reviewed`.

Limits:

- The first Loop 7C-R attempt failed at
  `child_mcp_required_but_unavailable` because the runner port had no live MCP
  server.
- The successful rerun had a live MCP server, but child Codex still reported
  MCP tools unavailable and used stdout fallback for both execution and review.
- Provider selection records show execution on `codex.default` and review on
  `codex.review`; this is not Grok platform review routing proof.
- The final-action hold is pending. No final-action approval/import,
  GitHub/server truth, or merge truth exists.

Later resolution:

- Loop 7D-R audited pending hold `final-fdf66ded3605` and rejected it without
  importing the candidate artifact. See F153 for the final-action decision.

### F153. Loop 7D-R rejects the fallback/open-gate final-action hold without import

Severity: final-action audit decision; prevents weaker evidence from entering
the control branch.

Loop 7D-R inspected pending hold `final-fdf66ded3605` from the Loop 7C-R
runtime root `/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY`.

Evidence:

- Hold before audit: `status=pending`, `action=merge`,
  `target_status=reviewed`, `resolved_by=null`.
- Execution worktree:
  `/tmp/xmuse-goal-loop7cr-mcp-exec-ialBKYv`.
- Worktree status had one untracked candidate file:
  `docs/xmuse/loop7b-corrected-execute-ready-proof.md`.
- The candidate artifact was 64 lines and stayed within a docs-only Loop 7B
  approval-readiness proof boundary.
- Control operation/findings docs already contained the same durable refs for
  the human request, execute-target request, execute response, dispatch gate,
  proposal, approval resolution, dispatch handoff, review verdict, and final
  hold.
- Gate report had `profile_ids=[]` and warning
  `gate_profiles.json missing; no gate commands were run and lane passed open`.
- Provider records showed execution through `codex.default` and review through
  `codex.review`; both execution and review used stdout fallback rather than
  MCP-native status writeback.

Decision:

- The hold was rejected without importing the candidate artifact.
- `final_actions.json` now records `status=rejected` and
  `resolved_by=loop7dr-audit-no-import`.
- Audit summary:
  `/tmp/xmuse-goal-loop7cr-mcp-rerun-REWrbiY/loop7dr_final_action_audit_summary.json`.

Implications:

- Loop 7C-R remains valid local dispatch-to-final-action-hold evidence.
- No final-action approval/import, GitHub/server truth, merge truth, Grok
  platform review proof, or MCP-native execution/review writeback proof exists.
- The next boundary should target child Codex MCP tool exposure/writeback before
  another final-action import attempt.

### F145. Final-action audit rejected the Loop 7-R hold because the worker diff was stale relative to current evidence

Severity: final-action decision / no-import evidence.

Loop 8-R audited the pending Loop 7-R final-action hold:

```text
runtime_root=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/runtime
audit_summary=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/runtime/loop8r_final_action_audit_summary.json
execution_worktree=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/exec-worktree
hold_id=final-29e23839a1f5
lane_id=loop6r-durable-proposal-proof
verdict_id=verdict-merge-rtask_cdacfa7947f4488d916fe71ea264877f
```

The execution worktree diff was:

```text
docs/xmuse/fullchain-runtime-findings-2026-06-17.md | 33 insertions
docs/xmuse/fullchain-runtime-operation-record-2026-06-17.md | 71 insertions
total=2 files changed, 104 insertions(+)
```

Audit result:

```text
current control docs already contain Loop 6-R operation entry=true
current control docs already contain Loop 7-R operation entry=true
current control docs already contain F143=true
current control docs already contain F144=true
decision=reject_hold_without_import
hold_before.status=pending
hold_after.status=rejected
hold_after.resolved_by=loop8r-audit-no-import
```

Impact:

- The final-action gate is no longer left pending for the Loop 7-R worker diff.
- No worker diff was imported into the control worktree.
- The control evidence ledger keeps the stronger main-Codex Loop 6-R/7-R
  records, including the review-fallback limitation, instead of merging a
  narrower stale worker append.

Limits and risks:

- This is not a GitHub/server/merge proof.
- This does not prove final-action approval or import.
- This does not fix the Loop 7-R review transport limitation:
  `review_fallback=stdout` remains the next concrete boundary.

Next targeted action:

- Run `Loop 9-R`: isolate and repair or revalidate the Codex review MCP-native
  writeback boundary that caused Loop 7-R `review_fallback=stdout` before
  attempting another final-action import or merge decision.

### F144. Current groupchat-produced proposal reached a safe no-auto-merge final-action hold

Severity: positive approval/execution/final-action evidence with bounded confidence.

Loop 7-R copied the Loop 6-R runtime root, approved the current
groupchat-produced proposal, ran the projected lane in an isolated execution
worktree, and stopped under `--no-auto-merge`:

```text
loop7_runtime_root=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/runtime
summary=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/runtime/loop7r_finalhold_summary.json
execution_worktree=/tmp/xmuse-goal-loop7r-approval-probe-053x1dyz/exec-worktree
proposal_id=prop_727b362340a64d7c9b9af4dc1734259e
resolution_id=res_4a8364eca8704511ae22538d6756d1e4
lane_id=loop6r-durable-proposal-proof
final_action_hold_id=final-29e23839a1f5
```

Durable evidence:

```text
Chat API approval status_code=200
resolution_status=approved
feature_lanes.status=awaiting_final_action
state_history=dispatched -> executed -> gated -> reviewed -> awaiting_final_action
review_task_id=rtask_cdacfa7947f4488d916fe71ea264877f
review_verdict_id=verdict-merge-rtask_cdacfa7947f4488d916fe71ea264877f
review_verdict.status=finalized
review_decision=merge
final_actions.holds[0].status=pending
final_actions.holds[0].action=merge
execution_worktree diff=2 docs files, 104 insertions
```

Impact:

- The current Codex-Grok groupchat-produced proposal now has a downstream
  approval-to-safe-hold proof, not only proposal-plane proof.
- Approval projection preserved durable source refs and wrapped the lane with
  the approved-proposal execution contract.
- `--no-auto-merge` held the accepted lane at pending final action instead of
  merging into the control branch.
- The execution worktree isolated the worker changes from the active control
  worktree.

Limits and risks:

- This does not resolve the final-action hold, import the worker diff, prove
  GitHub/server truth, or prove merge truth.
- Review was durable in `review_plane.json`, but the review provider used
  stdout fallback (`review_fallback=stdout`, `review_fallback_reason=verdict_merge`)
  after reporting MCP unavailable. This loop proves final-action hold, not
  MCP-native review writeback.
- The first runner command used an empty-path harness invocation and generated
  `coordinator_incidents.jsonl` in the control worktree before reaching the
  real chain; that file was removed. The successful runner used absolute paths.

Next targeted action:

- Run `Loop 8-R`: audit the pending Loop 7-R final-action hold and execution
  worktree diff against the durable Loop 6-R/7-R evidence, then decide whether
  to import the minimal docs evidence or reject the hold, without resolving
  GitHub/server/merge truth.

### F143. Codex-Grok groupchat produced a durable open lane_graph proposal

Severity: positive proposal-plane evidence with bounded confidence.

Loop 6-R promoted the current repeated-clean Codex-Grok peer path from chat
writeback into durable proposal production:

```text
runtime_root=/tmp/xmuse-goal-loop6r-proposal-proof-mu7_4jw6
summary=/tmp/xmuse-goal-loop6r-proposal-proof-mu7_4jw6/loop6r_postmortem_summary.json
conversation_id=conv_283fadbedf60480d8dfa572df5a2c9d9
architect=part_5efab63c5e3847a6931c9d26aeba3d84 codex gpt-5.4
review=part_3863b8500b9a4d69979d9c9977334048 grok grok-composer-2.5-fast
proposal=prop_727b362340a64d7c9b9af4dc1734259e open lane_graph
```

The run completed the bounded groupchat proposal chain:

```text
Codex draft reply=CODEX_L6R_DRAFT_READY
Codex handoff=GROK_L6R_REVIEW_REQUEST
Grok draft review=GROK_L6R_REVIEW_ACCEPTABLE
Codex proposal card=[proposal] Loop 6-R Durable Proposal Proof (1 lanes)
Grok proposal review=GROK_L6R_REVIEW_OK
```

Durable evidence:

```text
all four inbox items: status=read
request_log: chat_post_message x3, chat_mention x1, chat_emit_proposal x1
latency traces: 4 x mcp_writeback, degraded_reason=null
proposal status=open
proposal type=lane_graph
proposal lane=loop6r-durable-proposal-proof
proposal references=["message:GROK_L6R_REVIEW_ACCEPTABLE"]
grok_provider_session_id=019ee6ed-67a5-7dc2-a78d-1f6efa7eeb3a
```

Impact:

- The current peer path now has durable proposal-plane evidence, not only chat
  message/writeback evidence.
- `chat_emit_proposal` closed the Codex architect inbox through MCP tool stages,
  created the proposal row, and created the visible proposal chat card.
- The automatic proposal review trigger created a downstream Grok review inbox,
  and Grok closed it through the callback bridge.
- This validates the next boundary as approval/dispatch/final-action behavior.

Limits and risks:

- This does not prove approval, dispatch, lane execution, final-action hold,
  GitHub/server truth, merge truth, overnight reliability, or statistical
  reliability.
- The first harness failed during observation because it called a non-existent
  `ChatStore.list_request_log` helper after the product chain had already run.
  A follow-up summary script also initially assumed `GodSessionRecord` had
  `model_dump`. Durable state was recovered from SQLite/request-log tables and
  `god_sessions.json`; these were harness bugs, not product proposal failures.
- Nested Codex peer tool/shell discipline remains outside this proof.

Next targeted action:

- Run `Loop 7-R`: approve the Loop 6-R groupchat-produced proposal into a safe
  no-auto-merge final-action hold, first confirming the approval-to-dispatch
  contract and stopping before any GitHub/server/merge truth claim.

### F142. Patched Codex-Grok short soak completed three turns and supports proposal-proof promotion

Severity: positive reliability evidence with bounded confidence.

Loop 5F-R reran the current-line Codex-Grok short soak after the 300s
peer-chat budget patch:

```text
runtime_root=/tmp/xmuse-goal-loop5fr-codex-grok-soak-g7_cnr84
summary=/tmp/xmuse-goal-loop5fr-codex-grok-soak-g7_cnr84/loop5fr_short_soak_summary.json
provider_events=/tmp/xmuse-goal-loop5fr-codex-grok-soak-g7_cnr84/provider_events.jsonl
conversation_id=conv_8f9b98975dbb449f9d8c40aff77f9194
architect=part_4e8bdb7c7eda48bc837b92beaa95568e codex gpt-5.4
review=part_a612910d8a104413bf27aebcec60e958 grok grok-composer-2.5-fast
```

The run rebuilt `GodSessionLayer` between turns and completed:

```text
turn_1=CODEX_L5FR_TURN1_ACK_OK -> GROK_L5FR_TURN1_REPLY_OK.
turn_2=CODEX_L5FR_TURN2_ACK_OK -> GROK_L5FR_TURN2_REPLY_OK.
turn_3=CODEX_L5FR_TURN3_ACK_OK -> GROK_L5FR_TURN3_REPLY_OK.
```

Durable evidence:

```text
all six inboxes: status=read
all six latency traces: delivery_mode=mcp_writeback, degraded_reason=null
request_log: chat_post_message x6, chat_mention x3
failure_traces=[]
final_non_read_inbox_items=[]
grok_provider_session_id=019ee6dc-9712-7091-aad9-12862a4e1de6
grok_provider_native_session_reused=true on turns 2 and 3
scheduler_defaults=response_wait_s=300.0, claim_ttl_s=360
```

Impact:

- Loop 5F-R is the current revalidation line's second clean three-turn
  short-soak sample, following Loop 5C-R and the Loop 5E-R timeout-budget
  patch.
- It specifically validates the Loop 5E-R diagnosis because turn 3 Codex
  latency was `180171ms`, just over the former 180s timeout boundary, while
  the patched 300s budget completed successfully.
- Grok provider-native session binding persisted across rebuilt session layers.
- This is enough to promote the current active boundary to a bounded
  groupchat-produced proposal proof.

Limits and risks:

- This is not overnight or statistical reliability proof.
- This does not prove proposal production, lane execution, GitHub truth, or
  merge truth.
- Provider events still show nested Codex peer shell reads for its own skill
  policy: `/bin/bash=2`, `sed -n=1`, `cat /mnt=1`, `exec\n=0`. This sample
  proves durable writeback and handoff, not tool-free Codex peer turns.

Next targeted action:

- Run `Loop 6-R`: a bounded current groupchat-produced proposal proof with
  Codex architect and Grok review using the repeated-clean patched peer path.
  Keep lane execution out of scope until the proposal artifact itself is
  durable.

### F146. Current proposal proof produced a durable proposal but did not prove clean Codex-to-Grok handoff

Loop 6G-R attempted the current groupchat-produced proposal proof:

```text
runtime_root=/tmp/xmuse-goal-loop6r-current-proposal-cw926lko
summary=/tmp/xmuse-goal-loop6r-current-proposal-cw926lko/loop6r_current_proposal_summary.json
conversation_id=conv_30d055299d3049bdb41850b8e715ff58
proposal_id=prop_78db403afc624b8a947ad7fce8adf39c
architect=part_21ac836d90dd496cb400603773a2f5a1 codex gpt-5.4
review=part_ffec50e417604b088adbbe01b433a225 grok grok-composer-2.5-fast
```

Positive evidence:

```text
has_grok_participant=true
has_grok_session=true
has_codex_session=true
has_grok_reply=true
has_lane_graph_proposal=true
proposal_refs_nonempty=true
request_log=post_human_message x2, chat_post_message x3, chat_emit_proposal x1
proposal_summary=Loop 6-R Current Durable Proposal Proof
proposal_lane=loop6r-current-durable-proposal-proof
```

Durable proposal refs:

```text
msg_ffc3efaf7d6643ecad1dfdffbb200c29 human demand
msg_c5e570a4c11d4a458a1edc1d0e2fbd71 Codex architect message
msg_93f2eded6ebf400c8ab075e36deecdde Grok review message
msg_debd6e0ca4794cb0ae359a7fd5aebe96 human proposal request
```

Failure boundary:

```text
first_architect_inbox:
  delivery_mode=failed
  degraded_reason=peer_response_timeout
  total_latency_ms=300210
  chat_post_message stage existed before timeout

handoff:
  chat_mention x0
  human demand mentioned both @architect and @review
  Grok review inbox was therefore human-routed, not Codex-routed

proposal_review_trigger:
  automatic review_trigger inbox remained unread
```

Impact:

- This run is valid evidence that the current Codex/Grok chat path can produce
  a durable `lane_graph` proposal with source refs.
- It is not valid proof of clean Codex-to-Grok handoff for this proposal loop.
- It should not be used to approve, dispatch, or execute the proposal.

Next targeted action:

- Run `Loop 6H-R`: a corrected Codex-to-Grok handoff-only probe where the human
  mentions only `@architect` and Codex must create the `@review` inbox through
  `chat_mention` under the 300s scheduler budget. If clean, rerun proposal
  proof; otherwise classify the Codex `chat_mention` or result-return boundary
  before any approval or lane execution step.

### F151. Corrected execute-target proof passes approval gate and queues dispatch

Loop 7B-R reran the approval-readiness proof with an actual `@execute`
collaboration target:

```text
runtime_root=/tmp/xmuse-goal-loop7br-execute-ready-r0cyfrw2
summary=/tmp/xmuse-goal-loop7br-execute-ready-r0cyfrw2/loop7br_corrected_execute_ready_summary.json
conversation_id=conv_acbacd44220c4b29819a284fa40aaf01
architect=part_d6f26c2d30ca463cb4f6649cbc0dc768 codex gpt-5.4
execute=part_4c13a5f38ed94204b5d31a3401c6ebc5 codex gpt-5.4
review=part_64127639a2314aec919c2160c6f5c88a grok grok-composer-2.5-fast
```

Execute-target collaboration evidence:

```text
collaboration_run=collab_55f757d8e3fa44db97ca8e06f2e932d3
targets=["@execute"]
status=done
response_id=collab_resp_80210c543c884f6b8debde0b1498b5f8
response.target=@execute
response.content.type=execute_feasibility_verdict
response.content.verdict=dispatchable
execution_performed=false
execute_inbox=inbox_151cf56d3e014b45a8c97e014e6d9fcd read
execute_latency=delivery_mode:mcp_writeback,degraded_reason:null,total_latency_ms:171719
```

Approval/projection evidence:

```text
proposal_id=prop_d47c207c2e59467cb276a80b4d4740e4
proposal.status=accepted
accepted_resolution_id=res_954c10cef8ae46beb53b766ebaec5216
approval_status_code=200
dispatch_gate_event=collab_gate_803915621d49443eaf067841f0ec1f03
dispatch_gate.decision=allowed
dispatch_gate.execute_confirmed=1
feature_lanes_exists=true
lane_graph=lane_graphs/res_954c10cef8ae46beb53b766ebaec5216-graph-v1.json
dispatch_queue.status=queued
dispatch_queue.auto_execute=1
```

Callback cleanup:

```text
collaboration_callback=inbox_21833a4e16fa4c318f39d96c6a2cccf2
status=failed
reason=superseded_by_accepted_proposal:prop_d47c207c2e59467cb276a80b4d4740e4; accepted_resolution:res_954c10cef8ae46beb53b766ebaec5216
non_terminal_inboxes=[]
```

Classification:

- Loop 7-R's root cause is confirmed: authority must come from `@execute`.
- With the same verdict shape produced by an actual `@execute` target before
  proposal creation, the approval gate records `allowed` and `execute_confirmed=1`.
- This proves approval/projection/dispatch-queue readiness only. It is not lane
  execution, review-plane, final-action, GitHub, or merge truth.
- The current projection points the lane `worktree` at the control repo path, so
  the next dispatch/final-action proof must explicitly use an isolated execution
  worktree.

Next targeted action:

- Run `Loop 7C-R`: run the approved Loop 7B-R dispatch queue through an explicit
  isolated execution worktree with no-auto-merge/final-action approval enabled,
  stopping at final-action hold or the first durable dispatch/execution/review
  boundary. Do not use the control repo path from the projection as the
  execution worktree.

### F150. Approval gate blocks current proposal because execute verdict is not from execute target

Loop 7-R attempted to approve the Loop 6I-R/6J-R proposal in a copied isolated
root:

```text
source_runtime_root=/tmp/xmuse-goal-loop6jr-review-trigger-2ymsb8y0
runtime_root=/tmp/xmuse-goal-loop7r-approval-audit-v7cgk7bs
summary=/tmp/xmuse-goal-loop7r-approval-audit-v7cgk7bs/loop7r_approval_audit_summary.json
proposal_id=prop_260a6958c5754f8bb00e2568f4a9229a
```

Approval result:

```text
POST /api/chat/proposals/prop_260a6958c5754f8bb00e2568f4a9229a/approve
-> 400 dispatch_gate_blocked: blocked_execute_not_confirmed

dispatch_gate_event=collab_gate_72ca53ee7e314297be2e36b54118146a
proposal_ref=proposal:prop_260a6958c5754f8bb00e2568f4a9229a
artifact_ref=artifact:lane_graph
execute_confirmed=0
policy_allows_real_provider=1
```

Root cause:

```text
referenced_collaboration=collab_1cd8035f0dcb49c48a7f5fcad93e21a4
collaboration.status=done
collaboration.targets=["@architect"]
response.target=@architect
response.content.type=execute_feasibility_verdict
response.content.verdict=dispatchable
```

The approval gate intentionally requires execute confirmation from target
`execute` or `@execute`. A dispatchable-looking JSON response from `@architect`
does not satisfy that authority boundary.

Post-attempt state:

```text
proposal.status=open
accepted_resolution_id=null
resolutions=[]
feature_lanes_exists=false
lane_graphs=[]
final_actions_exists=false
review_plane_exists=false
```

Classification:

- The approval gate behaved correctly under the current contract.
- The current proposal is not approval-ready because its collaboration evidence
  lacks an actual execute-target response.
- This is a producer-side proof gap in the proposal-generation/harness flow, not
  an approval API bug.
- Do not approve, dispatch, or execute
  `prop_260a6958c5754f8bb00e2568f4a9229a`.

Next targeted action:

- Run `Loop 7B-R`: rerun a corrected approval-ready proposal proof with an
  actual `@execute` participant/target producing the execute-feasibility verdict
  before proposal emission, then retry approval into a safe no-auto-merge
  final-action hold only if the durable dispatch gate records
  `execute_confirmed=1`.

### F149. Downstream proposal callback/review-trigger boundary closed before approval

Loop 6J-R copied the Loop 6I-R runtime root and handled the two downstream
inboxes that were intentionally left unread at proposal-production time:

```text
source_runtime_root=/tmp/xmuse-goal-loop6ir-proposal-t1lu4s7l
runtime_root=/tmp/xmuse-goal-loop6jr-review-trigger-2ymsb8y0
summary=/tmp/xmuse-goal-loop6jr-review-trigger-2ymsb8y0/loop6jr_review_trigger_summary.json
conversation_id=conv_8ec9b7b7d6e546d58e4d7230130b0fc6
proposal_id=prop_260a6958c5754f8bb00e2568f4a9229a
```

Callback classification:

```text
inbox_id=inbox_f7a34137836b43558af6d8fd31f25e71
item_type=collaboration_callback
status=failed
failure_reason=superseded_by_existing_proposal:prop_260a6958c5754f8bb00e2568f4a9229a; existing_proposal_message:msg_0265101fc68242ce915225d934fbece2; contains_collaboration:collab_1cd8035f0dcb49c48a7f5fcad93e21a4
```

Automatic Grok review-trigger consumption:

```text
inbox_id=inbox_7bc04d1d03e24617bc8b90f3fb743343
status=read
responded_message_id=msg_e353adbab38d4036a86e0966ef47917a
writeback_path=grok_callback_bridge
scheduler_outcome={"nudged":1,"happy_path":1,"failed":0,"fallback_replies":0}
latency=delivery_mode:mcp_writeback,degraded_reason:null,total_latency_ms:20279
review_verdict=Approve
non_terminal_inboxes=[]
proposal.status=open
```

Classification:

- The collaboration callback was stale/superseded by the existing open proposal
  because that proposal already references the collaboration run.
- The automatic review trigger is a real downstream consumer and was consumed
  by Grok through durable callback writeback.
- This closes the downstream inbox consumer boundary before approval, but it is
  not approval, dispatch, lane execution, final-action, GitHub, or merge truth.

Next targeted action:

- Run `Loop 7-R`: audit the Loop 6I-R/6J-R proposal and downstream review
  evidence, then decide whether to approve
  `prop_260a6958c5754f8bb00e2568f4a9229a` into a safe no-auto-merge
  final-action hold, stopping before any GitHub/server/merge truth claim.

### F148. Corrected proposal proof is durable; downstream callback/review-trigger remain unconsumed

Loop 6I-R reran proposal production after the clean Loop 6H-R handoff:

```text
runtime_root=/tmp/xmuse-goal-loop6ir-proposal-t1lu4s7l
summary=/tmp/xmuse-goal-loop6ir-proposal-t1lu4s7l/loop6ir_proposal_summary.json
conversation_id=conv_8ec9b7b7d6e546d58e4d7230130b0fc6
proposal_id=prop_260a6958c5754f8bb00e2568f4a9229a
architect=part_cdaa4f3674b5401ea85ab4480d8701cb codex gpt-5.4
review=part_b62eb04956f24dd38208a6b5465b3cf1 grok grok-composer-2.5-fast
```

Positive evidence:

```text
human messages mentioned only @architect
Codex review ack=CODEX_L6I_REVIEW_REQUEST_OK
Codex-created handoff message=msg_12c0b70f768b43afb7ee5c3d3671c350 mentions=["@review"]
Grok review message=msg_35d5d149b8494b6496c0879ac3fe7b9a
Codex proposal marker=CODEX_L6I_PROPOSAL_EMITTED_OK
request_log=post_human_message x2, chat_post_message x3, chat_mention x1, chat_emit_proposal x1
latency traces: all delivery_mode=mcp_writeback, degraded_reason=null
```

Durable proposal:

```text
proposal_type=lane_graph
status=open
summary=Loop 6-I Corrected Durable Proposal Proof
lane=loop6i-corrected-durable-proposal-proof
references:
  message:msg_7ad60e1d9f59480bb19a1ca299ea92fe
  message:msg_12c0b70f768b43afb7ee5c3d3671c350
  message:msg_35d5d149b8494b6496c0879ac3fe7b9a
  message:msg_77c92bde3c2d4e6c8db6caf34f7152a3
  collaboration:collab_1cd8035f0dcb49c48a7f5fcad93e21a4
```

Limits:

```text
unread collaboration_callback=inbox_f7a34137836b43558af6d8fd31f25e71 target=architect
unread review_trigger=inbox_7bc04d1d03e24617bc8b90f3fb743343 target=review
no approval, dispatch, lane execution, review-plane, final-action, GitHub, or merge truth
```

Classification:

- The corrected groupchat proposal-production boundary is proven locally.
- The first unclosed downstream boundary is consumer-side follow-up for
  callback/review-trigger inboxes generated by collaboration/proposal tooling.
- Do not approve or dispatch `prop_260a6958c5754f8bb00e2568f4a9229a` until that
  downstream inbox state is consumed or explicitly classified.

Next targeted action:

- Run `Loop 6J-R`: consume or explicitly classify the Loop 6I-R unconsumed
  collaboration_callback and automatic review_trigger in the isolated runtime
  root before approving or dispatching proposal
  `prop_260a6958c5754f8bb00e2568f4a9229a`.

### F147. Corrected architect-only handoff proves Codex-created Grok review inbox

Loop 6H-R reran the handoff-only boundary with corrected human routing:

```text
runtime_root=/tmp/xmuse-goal-loop6hr-handoff-df2yyv7f
summary=/tmp/xmuse-goal-loop6hr-handoff-df2yyv7f/loop6hr_handoff_summary.json
conversation_id=conv_8879e65e464b4a10b3c7cd134dc018ad
architect=part_e7010ee1e7454fba95e966ba6df51b86 codex gpt-5.4
review=part_3e75840a3c9146eea5f43d2f717737e0 grok grok-composer-2.5-fast
```

Evidence:

```text
human_message=msg_d5a5dbf9ca494442bb4849110f73e760 mentions=["@architect"]
codex_ack=msg_2893799409eb49099eac1083a38434ab CODEX_L6H_HANDOFF_ACK_OK
codex_handoff=msg_36270cf9f818480188dab7805a2441fb mentions=["@review"]
grok_reply=msg_ccde42cafc464d6caacfd6b3dc5587cd GROK_L6H_HANDOFF_REPLY_OK
request_log=post_human_message x1, chat_post_message x2, chat_mention x1
all inboxes read=true
all latency traces mcp_writeback/null=true
```

Impact:

- Loop 6G-R's handoff weakness was caused by the probe text directly mentioning
  `@review`.
- Under architect-only human routing, Codex can create the review inbox through
  `chat_mention`, and Grok can consume it as a durable peer.
- This unblocks a corrected proposal-production rerun, but by itself does not
  prove proposal production or approval.

### F141. Codex multi-action peer turns need a 300s bounded wait budget

Severity: reliability fix for current Grok peer revalidation path.

Loop 5E-R separated the Loop 5D-R failure into two Codex-only probes:

```text
probe_runtime_root=/tmp/xmuse-goal-loop5er-codex-only-probe-h3q2ghdm
summary=/tmp/xmuse-goal-loop5er-codex-only-probe-h3q2ghdm/loop5er_codex_only_probe_summary.json
conversation_id=conv_53c4747afabc428e9ea9ee126949229d
```

Durable timing evidence:

```text
reply_only_180s:
  elapsed_ms=153625
  outcome=happy_path
  request_log_delta=chat_post_message +1
  latency.delivery_mode=mcp_writeback
  latency.degraded_reason=null

reply_then_mention_300s:
  elapsed_ms=206055
  outcome=happy_path
  request_log_delta=chat_post_message +1, chat_mention +1
  assistant_message=CODEX_L5ER_HANDOFF_ACK_OK
  review_inbox=inbox_8a8f202b45c04dcdb28b6a7cad600ff1 status=unread
  latency.delivery_mode=mcp_writeback
  latency.degraded_reason=null
```

Patch:

```text
src/xmuse_core/chat/peer_scheduler.py:
  default response_wait_s=300.0
  default claim_ttl_s=360

src/xmuse_core/chat/dispatch_bridge.py:
  default response_wait_s=300.0
  default claim_ttl_s=360

xmuse/platform_runner.py:
  peer scheduler wiring response_wait_s=300.0 claim_ttl_s=360
  chat dispatch bridge wiring response_wait_s=300.0 claim_ttl_s=360
```

Rerun evidence:

```text
default_budget_rerun_root=/tmp/xmuse-goal-loop5er-default-budget-rerun-pm5u9ab1
summary=/tmp/xmuse-goal-loop5er-default-budget-rerun-pm5u9ab1/loop5er_default_budget_rerun_summary.json
scheduler_defaults.response_wait_s=300.0
scheduler_defaults.claim_ttl_s=360
outcome=happy_path
elapsed_ms=173133
request_log=chat_post_message x1, chat_mention x1
architect_inbox=read
review_inbox=unread
latency.delivery_mode=mcp_writeback
latency.degraded_reason=null
```

Verification:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_platform_runner.py -q
  79 passed, 1 warning

uv run ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/chat/dispatch_bridge.py xmuse/platform_runner.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_platform_runner.py
  All checks passed
```

Impact:

- Loop 5D-R should not be classified as a Grok failure; Grok was never
  enqueued.
- Codex can complete reply+mention under a 300s bounded wait.
- The previous 180s wait cut too close to real multi-action peer turns; one
  diagnostic case needed `206055ms`.
- This patch does not by itself create a second clean Codex-Grok short-soak
  sample. That must be rerun as the next boundary.

Next targeted action:

- Run `Loop 5F-R`: rerun the current Codex-Grok three-turn short soak with the
  patched 300s peer-chat budget and rebuilt `GodSessionLayer` between turns.
  If it is clean, record it as the second current clean short-soak sample
  before deciding whether promotion to Loop 6-R is justified.

### F140. Second current Codex-Grok short soak failed on Codex partial writeback timeout

Severity: reliability blocker for promotion to groupchat-produced proposal proof.

Loop 5D-R attempted the second current-line three-turn short soak:

```text
runtime_root=/tmp/xmuse-goal-loop5dr-codex-grok-soak-78ly1o7z
summary=/tmp/xmuse-goal-loop5dr-codex-grok-soak-78ly1o7z/loop5dr_short_soak_summary.json
provider_events=/tmp/xmuse-goal-loop5dr-codex-grok-soak-78ly1o7z/provider_events.jsonl
conversation_id=conv_f3f13b1aae954092bdb1d38040a89040
architect=part_414bd4d357f742bbb59e56bb7f39aa5f codex gpt-5.4
review=part_eb474f55219c468d8e9bb2528caea6c0 grok grok-composer-2.5-fast
```

Durable evidence:

```text
architect_inbox=inbox_e7e148654740461ba10c4d98c7a1df32 status=read
architect_message=msg_f3872c4452614bc9bf500e42bba03901 content=CODEX_L5DR_TURN1_ACK_OK
request_log: chat_post_message x1, chat_mention x0
latency: delivery_mode=failed, degraded_reason=peer_response_timeout, total_latency_ms=180115
stage_timings: chat_read_inbox and chat_post_message were observed; chat_mention was not
review_inbox=missing
grok_message=missing
```

Impact:

- Loop 5D-R invalidates promotion from Loop 5C-R directly to Loop 6-R.
- The current active blocker is Codex peer producer reliability for
  multi-action turns: durable reply writeback can happen, while provider result
  return and follow-on `chat_mention` do not complete within the scheduler
  boundary.
- The failure is not a Grok provider failure; Grok was never enqueued.
- The harness had a post-failure summary bug, but durable sqlite state and
  provider_events still classify the product boundary.

Limits and risks:

- This is one failure sample after one clean three-turn sample; it does not
  prove permanent unreliability.
- It does prove the current evidence is insufficient for proposal-production
  promotion.
- The next loop should isolate reply writeback timing, `chat_mention` enqueue
  timing, and provider result return timing before changing product code.

Next targeted action:

- Run `Loop 5E-R`: a bounded Codex-only multi-action reliability probe that
  separates reply writeback, `chat_mention` enqueue, and provider result return
  timing. Use durable `chat_request_log` and `peer_turn_latency_traces` to
  decide whether to patch scheduler prompt/tool contract, timeout handling, or
  retry semantics before attempting another Codex-Grok short soak.

### F139. Current Codex-Grok short soak completed three turns with rebuilt session layers

Severity: positive reliability evidence with bounded confidence.

Loop 5C-R ran a fresh current-line three-turn short soak:

```text
runtime_root=/tmp/xmuse-goal-loop5cr-codex-grok-soak-iyx4377d
summary=/tmp/xmuse-goal-loop5cr-codex-grok-soak-iyx4377d/loop5cr_short_soak_summary.json
provider_events=/tmp/xmuse-goal-loop5cr-codex-grok-soak-iyx4377d/provider_events.jsonl
conversation_id=conv_fabdd5b2ceb147538e99e6f6156a04ed
architect=part_9dc69c72b9ad45faaf998cc8db978e16 codex gpt-5.4
review=part_67c73051d2d84dd59dfce965b86ea020 grok grok-composer-2.5-fast
```

The run rebuilt `GodSessionLayer` between turns and completed:

```text
turn_1=CODEX_L5CR_TURN1_ACK_OK -> GROK_L5CR_TURN1_REPLY_OK.
turn_2=CODEX_L5CR_TURN2_ACK_OK -> GROK_L5CR_TURN2_REPLY_OK.
turn_3=CODEX_L5CR_TURN3_ACK_OK -> GROK_L5CR_TURN3_REPLY_OK.
```

Durable evidence:

```text
all six inboxes: status=read
all six latency traces: delivery_mode=mcp_writeback, degraded_reason=null
request_log: chat_post_message x6, chat_mention x3
failure_traces=[]
final_non_read_inbox_items=[]
grok_provider_session_id=019ee6b7-59db-7c02-9b83-9a1a4e1e8563
grok_provider_native_session_reused=true on turns 2 and 3
```

Impact:

- This is the current revalidation line's first clean three-turn short soak.
- It did not repeat Loop 4's `peer_response_timeout`.
- It did not repeat any `peer_no_inbox_side_effect`.
- It preserved Grok provider-native session binding across two session-layer
  rebuilds.
- It used durable inbox/message/request-log/latency evidence, not stdout, as
  the proof boundary.

Limits and risks:

- This is still one current short-soak sample, not overnight or statistical
  reliability proof.
- Codex turns remain slow: `154580ms`, `139324ms`, and `139109ms`.
- The Loop 5B-R provider shell/tool discipline risk did not recur as
  `/bin/bash`, `sed -n`, `cat /mnt`, or `exec\n` traces in this sample, but one
  clean sample is not enough to close that risk.
- This is not proposal production, lane execution, GitHub/server truth, or
  merge truth.

Next:

- Run `Loop 5D-R`: a second current three-turn Codex-Grok short soak with
  `provider_events` capture and session-layer rebuilds between turns. If it is
  also clean, promote the current active boundary to `Loop 6-R`
  groupchat-produced proposal proof.

### F138. Current Codex-Grok restart/resume sample preserves durable writeback and Grok session binding

Severity: positive reliability evidence with tail-latency and peer-discipline risks.

Loop 5B-R reran the current revalidation line's restart/resume boundary with a
fresh runtime root:

```text
runtime_root=/tmp/xmuse-goal-loop5br-codex-grok-resume-obo_z1xr
summary=/tmp/xmuse-goal-loop5br-codex-grok-resume-obo_z1xr/loop5br_restart_resume_summary.json
provider_events=/tmp/xmuse-goal-loop5br-codex-grok-resume-obo_z1xr/provider_events.jsonl
conversation_id=conv_60283595c95e4c4fb9fe3c0fd34428f0
architect=part_0809a7d77ea3473c8a6f6f3ae5202d5d codex gpt-5.4
review=part_dd23959cb7e14bd6bf65084c25c4b562 grok grok-composer-2.5-fast
```

The run completed one fresh handoff and one handoff after rebuilding
`GodSessionLayer`:

```text
turn_1=CODEX_L5BR_TURN1_ACK_OK -> GROK_L5BR_TURN1_REPLY_OK
turn_2_after_rebuild=CODEX_L5BR_TURN2_ACK_OK -> GROK_L5BR_TURN2_REPLY_OK
```

Durable evidence:

```text
all four inboxes: status=read
all four latency traces: delivery_mode=mcp_writeback, degraded_reason=null
request_log: chat_post_message x4, chat_mention x2
grok_provider_session_id=019ee6ad-529e-71d3-a42a-7f9aab88754c
grok_provider_session_kind=grok_cli_session
grok_provider_binding_status=active
grok provider_native_session_reused=true on turn 2
```

Impact:

- The current revalidation line now has a bounded restart/resume sample proving
  durable Codex -> Grok handoff across a rebuilt `GodSessionLayer`.
- Loop 4's `peer_response_timeout` did not recur in this sample.
- The prior `peer_no_inbox_side_effect` class did not recur in this sample.
- Grok provider-native session binding survived the rebuild and was reused.

Limits and risks:

- This is still one bounded current restart/resume sample, not overnight or
  statistical reliability proof.
- Codex tail latency remains close to the scheduler timeout:
  `turn1_architect=142409ms`, `turn2_architect=178643ms`.
- Provider events show nested Codex peer turns executed local shell reads for
  their own skill policy despite the inbox request saying not to run shell
  commands. This does not invalidate durable writeback proof, but it means this
  sample cannot claim tool-free peer turns or strict chat-only behavior.
- This is not proposal production, lane execution, GitHub/server truth, or
  merge truth.

Next:

- Run `Loop 5C-R`: a current three-turn Codex-Grok short soak with
  `provider_events` capture and session-layer rebuilds between turns, tracking
  Codex tail latency and whether `peer_no_inbox_side_effect` or provider
  shell/tool discipline risks recur.

### F137. Resumed `/goal` continues the current revalidation line before using older downstream evidence

Severity: control-plane selector risk, documentation-only resolution.

The resumed `/goal` truth refresh found that the runtime evidence files contain
two valid but different same-day progress lines:

```text
current revalidation line:
  Loop 2A-R -> Loop 3-R -> Loop 4B -> Loop 5A
  next_action=Loop 5B-R restart/resume reliability sample

older downstream fullchain line:
  Loop 5B/5C/5D -> Loop 6 -> Loop 7 -> Loop 8 -> Loop 8B
  next_action=Loop 9 child MCP tool exposure/writeback repair
```

The ambiguity matters because `real-runtime-loop-behavior-policy.md` requires
one active boundary and one unique `next_action`; it explicitly says to stop
and rebuild truth refresh when the latest loop entry or active boundary is
ambiguous.

Classification:

```text
authority: runtime policy, loop decomposition, operation record, findings summary
producer: resumed /goal truth_refresh
consumer: next loop selector
boundary: documentation/control-plane selection, not product runtime behavior
```

Resolution:

- Continue the current revalidation line created by the active `/goal` prompt's
  Loop 2A reset and Grok peer target.
- Treat older Loop 6-8B entries as valid historical downstream evidence, not
  the next active boundary for this resumed line.
- Do not run Loop 9 until the current revalidation line either reaches that
  downstream boundary again or explicitly imports the older line as authority.

Next:

- Run `Loop 5B-R`: a bounded current Codex-Grok restart/resume reliability
  sample that preserves durable conversation/provider-session evidence across a
  rebuilt `GodSessionLayer` and records whether the Loop 4 timeout or any
  `peer_no_inbox_side_effect` recurs.

### F136. Current Codex-to-Grok peer handoff works with a longer Codex wait window

Severity: positive active-boundary proof with a reliability note.

Loop 4B revalidated the current worktree's Codex -> Grok handoff path. Unlike
Loop 3-R, the Grok inbox was not human-created: Codex created it through a
durable `@review` mention message.

Evidence:

```text
runtime_root=/tmp/xmuse-goal-loop4b-codex-grok-handoff-sd6vf62g
summary=/tmp/xmuse-goal-loop4b-codex-grok-handoff-sd6vf62g/loop4b_codex_grok_handoff_summary.json
conversation=conv_b75635ceefbc4c9d88240668c1a90a0b

human_message=msg_cd1b43f1aeb449aaa3c04922dea5907b mentions=["@architect"]
codex_participant=part_554538a8173d4d4f89cc4d983be29d00 cli_kind=codex model=gpt-5.4
codex_inbox=inbox_8589f39cae324d8298ed597b349e95e5 status=read responded_message_id=msg_598eacc277604f3580d8455a6746be4c
codex_ack=msg_598eacc277604f3580d8455a6746be4c content=CODEX_GOAL_LOOP4B_HANDOFF_ACK
codex_handoff=msg_b11e6cf067604e668d4eb4975362b9f8 envelope_type=mention mentions=["@review"]
codex_handoff.content=Reply exactly GROK_GOAL_LOOP4B_HANDOFF_REPLY_OK.
codex_latency.delivery_mode=mcp_writeback
codex_latency.degraded_reason=null

grok_participant=part_53418e5d197841c49c0a0dc743a7a109 cli_kind=grok model=grok-composer-2.5-fast
grok_inbox=inbox_bc6c0e9ab9304e6a899cf33bc25b898c status=read sender_participant_id=part_554538a8173d4d4f89cc4d983be29d00
grok_inbox.source_message_id=msg_b11e6cf067604e668d4eb4975362b9f8
grok_reply=msg_9a317d353f904e33be7a681baac21fea content=GROK_GOAL_LOOP4B_HANDOFF_REPLY_OK.
grok_reply.envelope.writeback_path=grok_callback_bridge
grok_session=god-3025a698439349a6a6b9336fa2fd43ca runtime=grok provider_session_kind=grok_cli_session
grok_provider_session_id=019ee696-360a-7450-8ead-4b7ac61fa528
grok_latency.delivery_mode=mcp_writeback
grok_latency.degraded_reason=null
```

First attempt note:

```text
first_attempt_root=/tmp/xmuse-goal-loop4-codex-grok-handoff-9k2r_mtj
first_attempt.codex_outcome={"nudged": 0, "happy_path": 0, "failed": 1, "fallback_replies": 0}
first_attempt.codex_latency.delivery_mode=failed
first_attempt.codex_latency.degraded_reason=peer_response_timeout
first_attempt.side_effects=Codex ACK, durable @review mention, and Grok reply all existed
rerun_change=response_wait_s 180 -> 300
```

Classification:

- Current Codex can create a durable `@review` mention that routes to the Grok
  participant inbox.
- Grok consumes that peer-created inbox as a peer provider, not as a Codex
  subagent.
- Both turns reached `mcp_writeback` in the clean rerun.
- The 180s first-attempt timeout is a reliability concern for Codex peer turns
  with multiple MCP side effects, but the 300s rerun proves the handoff
  producer/consumer path itself is functional.

Limits:

- This does not prove multi-turn reliability or restart/resume.
- This does not prove proposal production, lane execution, Grok platform review
  routing, GitHub truth, or merge truth.
- Do not treat the 180s timeout as fixed by code; it is only classified and
  carried into the next reliability loop.

Next targeted action:

```text
Loop 5: run a bounded current Codex-Grok multi-turn reliability sample,
including whether the 180s Codex peer timeout observation repeats or is only a
single-run budget issue.
```

### F135. Current Codex and Grok peers can each produce durable writeback in one conversation

Severity: positive active-boundary proof for two-peer groupchat writeback.

Loop 3-R revalidated the current worktree's same-conversation Codex + Grok
writeback boundary. This is stronger than Loop 2A-R because both the Codex peer
and Grok peer consumed inbox items in one durable conversation and both reached
`mcp_writeback`.

Evidence:

```text
runtime_root=/tmp/xmuse-goal-loop3-codex-grok-writeback-jkybnov6
summary=/tmp/xmuse-goal-loop3-codex-grok-writeback-jkybnov6/loop3_codex_grok_writeback_summary.json
conversation=conv_ca08da47ebe94b0686ae097f5a76e4bf

codex_participant=part_50e93744c53d471b802c0f62fcdeb2ce cli_kind=codex model=gpt-5.4
codex_inbox=inbox_4c69f476a0d24813abbdb47c40340f5e status=read responded_message_id=msg_95a85c0ff8fb42fd8af6642b7aaceefd
codex_message=msg_95a85c0ff8fb42fd8af6642b7aaceefd content=CODEX_GOAL_LOOP3_WRITEBACK_OK.
codex_session=god-4e8c92372a2c43e78b58fb250107baf7 runtime=codex
codex_latency.delivery_mode=mcp_writeback
codex_latency.degraded_reason=null
codex_latency.stage_timings.chat_read_inbox.at=270549.814936579
codex_latency.stage_timings.chat_post_message.at=270569.860527356

grok_participant=part_cef850b1df954cd2bee976755e2f1133 cli_kind=grok model=grok-composer-2.5-fast
grok_inbox=inbox_20e4c099168e4caa97e331425354591f status=read responded_message_id=msg_8f461a07d1324a829b4e5d9f721aa70e
grok_message=msg_8f461a07d1324a829b4e5d9f721aa70e content=GROK_GOAL_LOOP3_WRITEBACK_OK.
grok_message.envelope.writeback_path=grok_callback_bridge
grok_session=god-ae8995db95154e65bf748399e276a6c0 runtime=grok provider_session_kind=grok_cli_session
grok_provider_session_id=019ee68c-30c1-7482-b9d6-9c35faab1ed1
grok_latency.delivery_mode=mcp_writeback
grok_latency.degraded_reason=null
grok_latency.stage_timings.chat_post_message.at=270627.976105777
```

Classification:

- Codex and Grok can coexist as durable GOD participants in one conversation.
- Codex can consume an inbox item and produce a durable assistant message
  through MCP chat tools; its latency trace includes `chat_read_inbox` and
  `chat_post_message`.
- Grok can consume an inbox item and produce durable assistant message through
  the callback bridge; its session records a provider-native
  `grok_cli_session`.
- Neither path used stdout fallback as success truth.
- Both peers added a trailing period to the requested marker; this is not a
  product failure for this loop because the active boundary is durable
  writeback, not exact-text obedience.

Limits:

- This does not prove Codex -> Grok handoff, because the two inboxes were
  human-created.
- This does not prove multi-turn reliability, restart/resume, proposal
  production, lane execution, Grok platform review routing, GitHub truth, or
  merge truth.

Next targeted action:

```text
Loop 4: prove current Codex-to-Grok peer handoff through a durable @review
mention and Grok peer reply in the same GOD conversation.
```

### F134. Current Grok GOD peer registration/writeback path still works locally

Severity: positive active-boundary proof for Grok groupchat peer registration.

Loop 2A-R revalidated the active Grok peer boundary against the current dirty
worktree rather than relying only on the earlier `/tmp/xmuse-grok-peer-binding`
artifact.

Evidence:

```text
runtime_root=/tmp/xmuse-goal-loop2a-grok-peer-4wza39t7
summary=/tmp/xmuse-goal-loop2a-grok-peer-4wza39t7/loop2a_current_grok_peer_revalidation_summary.json
conversation=conv_9c0e858b43d14c20a3802826e2effeb7
participant=part_8c41dc039054492c8b9ae0690300778c cli_kind=grok model=grok-composer-2.5-fast
inbox=inbox_cfde090e381d45779e90ddb8a681bf65 status=read responded_message_id=msg_378dc11350c54fd2b2f10df2435e3280
assistant_message=msg_378dc11350c54fd2b2f10df2435e3280 content=GROK_GOAL_LOOP2A_WRITEBACK_OK
assistant_envelope.writeback_path=grok_callback_bridge
god_session=god-31ef66f2971448baaeb2d2649eb7ba06 runtime=grok provider_session_kind=grok_cli_session
provider_session_id=019ee684-446a-72c3-bd6c-90960f87b82c
latency.delivery_mode=mcp_writeback
latency.degraded_reason=null
latency.stage_timings.chat_post_message.at=270109.463571883
```

Tests and provider checks:

```text
grok path=/home/iiyatu/.local/bin/grok
grok version=grok 0.2.59 (d73c632f8)
grok default model=grok-composer-2.5-fast
grok smoke=GROK_GOAL_SMOKE_OK
uv run pytest tests/xmuse/test_grok_persistent.py tests/xmuse/test_peer_chat_scheduler.py -q
  -> 18 passed in 6.07s
uv run pytest tests/xmuse/test_peer_provider_parity.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_god_session_layer.py -q -k 'grok or Grok'
  -> 7 passed, 37 deselected in 0.98s
```

Classification:

- `cli_kind="grok"` participant creation is currently accepted.
- `GrokLauncher` and `grok_persistent` can create a durable GOD session with
  provider-native `grok_cli_session` binding.
- `PeerChatScheduler` can deliver one inbox item to Grok and observe durable
  callback writeback as success truth.
- The external summary harness initially failed after product writeback because
  it called a stale inspection method; direct durable-store inspection and the
  regenerated summary artifact close that evidence gap.

Limits:

- This is one current local revalidation, not multi-turn reliability.
- It does not prove lane execution, provider-plane Grok adapters/profiles,
  platform `god_runtime=grok`, final-action hold, GitHub truth, or merge truth.

Next targeted action:

```text
Loop 3: prove current Codex and Grok can each produce one durable assistant
message through the GOD chatgroup writeback path in the same conversation.
```

### F133. Codex child execution cannot see required xmuse MCP writeback tools

Severity: downstream execution/writeback boundary blocking final-action proof.

Loop 8B reran approval-to-final-action hold after the Loop 8 approval
projection repair. The repaired prompt contract reached the child worker, but
execution still stopped before review.

Durable evidence:

```text
runtime_root=/tmp/xmuse-loop8b-finalhold-root-7af3fb07
summary=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/loop8b_finalhold_rerun_summary.json
preflight=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/loop8b_preflight_summary.json
execution_worktree=/tmp/xmuse-loop8b-exec-f1d0da0b
execution_branch=loop8b_loop6_grok_reviewed_proposal_5a18232e
proposal_id=prop_ba139bc0b76845aa98a36a56bd5e3835
resolution_id=res_4461386b411442fca8a59fbbec599227
agent_spawn_result=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/logs/agent_spawns/loop6_grok_reviewed_proposal/20260620T191543Z.result.json
agent_spawn_stdout=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/logs/agent_spawns/loop6_grok_reviewed_proposal/20260620T191543Z.stdout.log
agent_spawn_stderr=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/logs/agent_spawns/loop6_grok_reviewed_proposal/20260620T191543Z.stderr.log
state_history=/tmp/xmuse-loop8b-finalhold-root-7af3fb07/state_history.json
```

What worked:

- Loop 8B used a real git worktree
  `/tmp/xmuse-loop8b-exec-f1d0da0b` on branch
  `loop8b_loop6_grok_reviewed_proposal_5a18232e`.
- Platform runner dispatched the approved lane and created a lane context.
- The child stderr shows the full `Approved proposal execution contract`,
  including resolution, proposal, Grok review message, runtime root, chat.db,
  and Loop 6 summary artifact refs.
- The child command included MCP SSE configuration:
  `mcp_servers.xmuse-platform.url="http://localhost:8100/sse"`.
- The MCP server observed `/sse` HTTP requests during the child run.

What failed:

- The child reported that `query_knowledge` / `update_lane_status` were not
  callable in the model-facing tool surface.
- `feature_lanes.json` ended with `status=exec_failed`,
  `failure_reason=child_mcp_required_but_unavailable`,
  `failure_layer=worker`, `execute_failure_source=worker_test_gate`, and
  `stdout_fallback_rejected=true`.
- `state_history.json` contains only `dispatched -> exec_failed`.
- `review_plane.json` and `final_actions.json` do not exist.

Classification:

```text
authority: feature_lanes.json, state_history.json, agent_spawns result/stdout/stderr
producer: Codex child execution transport configured with xmuse MCP SSE
consumer: child model tool surface and LaneStateMachine writeback guard
boundary: MCP server reachability exists, but required xmuse MCP tools are not
  exposed as callable tools to Codex exec in this path
```

Next:

- Run `Loop 9`: repair Codex child execution MCP tool exposure/writeback path or
  change executor contract so child status writeback uses a supported provider
  result channel before rerunning final-action hold.

### F132. Approved proposal projection now carries durable execution evidence refs

Severity: repaired producer boundary for groupchat proposal-to-execution continuation.

Loop 8 repaired the first Loop 7 boundary: approval projection no longer passes
the original no-dispatch proposal prompt through as the only executable lane
task text.

Durable evidence:

```text
source_runtime_root=/tmp/xmuse-loop6-codex-grok-proposal-b55nt9e8
loop8_runtime_root=/tmp/xmuse-loop8-approval-contract-zxtje9yb
loop8_summary=/tmp/xmuse-loop8-approval-contract-zxtje9yb/loop8_approval_evidence_contract_summary.json
proposal_id=prop_ba139bc0b76845aa98a36a56bd5e3835
resolution_id=res_251a13b51dbe45d7be71f15c6794daa9
graph_path=/tmp/xmuse-loop8-approval-contract-zxtje9yb/lane_graphs/res_251a13b51dbe45d7be71f15c6794daa9-graph-v1.json
prompt_artifact=/tmp/xmuse-loop8-approval-contract-zxtje9yb/logs/lane_prompts/loop6_grok_reviewed_proposal.md
```

What changed:

- `xmuse/chat_api.py` enriches approved `lane_graph` resolutions before saving
  the graph and projecting ready lanes.
- The saved lane graph now has `source_refs` containing resolution,
  conversation, runtime root, chat.db, proposal, proposal references, and local
  `loop*_summary.json` artifacts.
- The projected prompt artifact begins with `Approved proposal execution
  contract`, then preserves the original proposal prompt as source context.
- `review_runtime=grok` remains preserved in projection metadata; this loop does
  not change platform review routing.

Verification:

```text
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_carries_execution_evidence_contract tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_preserves_review_runtime_in_projection tests/xmuse/test_chat_api.py::test_approving_proposal_projects_dependency_ready_lanes_into_execution_queue -q
result: 3 passed, 1 StarletteDeprecationWarning

uv run ruff check xmuse/chat_api.py tests/xmuse/test_groupchat_collaboration_runtime.py
result: All checks passed

git diff --check -- xmuse/chat_api.py tests/xmuse/test_groupchat_collaboration_runtime.py
result: no output
```

Limits:

- No platform runner rerun to `awaiting_final_action` has happened in this loop.
- No Grok platform-review routing proof exists; review routing remains known to
  select Codex in Loop 7.
- No execution success, final-action hold, GitHub truth, or merge truth is
  implied.

Next:

- Run `Loop 8B`: rerun approval-to-final-action hold from the Loop 6 proposal
  using the new approved-proposal execution contract, then classify the first
  downstream execution/review/final-action boundary.

### F131. Approval projection reached execution/review, but not final-action hold

Severity: product boundary for groupchat proposal-to-execution continuation.

Loop 7 attempted to approve Loop 6 proposal
`prop_ba139bc0b76845aa98a36a56bd5e3835` into isolated execution with
`--no-auto-merge`.

Durable evidence:

```text
approval_root=/tmp/xmuse-loop7-approve-finalhold-d4aa52qi
approval_resolution=res_c9fff755337f4c2f8e2bbb1ec85ba8f9
loop7c_root=/tmp/xmuse-loop7c-exec-failure-contract-rdgogmxl
loop7c_resolution=res_5d67c5a2896e469ab6463855a6e12d44
loop7c_execution_worktree=/tmp/xmuse-loop7c-exec-ce0351c7
review_task=rtask_e387d690df584cfbb40c00abb965e0ea
review_verdict=verdict-rework-loop6_grok_reviewed_proposal
final_actions_exists=false
```

What worked:

- Chat API approval created `read_models/resolutions.json`, one lane graph, and
  a runner-visible `feature_lanes.json` projection.
- Platform runner consumed the projected lane in an isolated worktree.
- The lane reached gate pass and review; the review plane persisted a finalized
  rework verdict.
- A focused guard now prevents zero-exit child output that explicitly says
  `status=exec_failed` from being advanced as `executed`.

What failed:

- The lane did not reach `awaiting_final_action`; `final_actions.json` was not
  created.
- The projected lane prompt still inherited the Loop 6 no-dispatch text:
  "Document a bounded no-dispatch proposal proof ... do not execute or approve
  in this loop."
- The isolated execution worktree was created from git HEAD and did not include
  the current dirty Loop 6/Loop 7 runtime ledger evidence from the control
  worktree.
- Review rejected the generated artifact as overclaiming Codex-Grok evidence
  because the worker/reviewer consumed stale checked-out docs instead of the
  durable Loop 6 runtime root and summary.
- `review_runtime=grok` was preserved on the lane projection, but platform
  review still selected Codex (`provider_profile_ref=codex.review`).

Classification:

```text
authority: Loop 6 proposal + Loop 7 resolution/lane graph + review_plane verdict
producer: approval projection and lane prompt/context builder
consumer: platform runner execution/review/final-action flow
boundary: proposal approval currently projects a no-dispatch documentation
  prompt into an execution lane without carrying the durable runtime evidence
  refs needed by isolated workers/reviewers
```

Next:

- Run `Loop 8`: repair approval projection into an execution-suitable lane
  contract that carries durable Loop 6 evidence refs into the isolated
  worktree/context, then rerun approval-to-final-action hold before attempting
  Grok platform review routing.

### F130. Codex-Grok groupchat produced a durable Grok-reviewed proposal

Severity: positive proposal-layer evidence with bounded scope.

Loop 6 advanced the Codex-Grok peer path from repeated writeback/handoff proof
to a durable proposal artifact:

```text
runtime_root=/tmp/xmuse-loop6-codex-grok-proposal-b55nt9e8
summary=/tmp/xmuse-loop6-codex-grok-proposal-b55nt9e8/loop6_groupchat_proposal_summary.json
conversation_id=conv_0a0e39214e944f80bb5a5aaf25ffd4fd
architect=part_9ff3d62fff9b43f09d14787f0ae1e526 codex gpt-5.4
review=part_cec7ea3852d744a582890566261eb763 grok grok-composer-2.5-fast
```

Durable chain:

```text
Human -> @architect mention
Codex chat_post_message -> CODEX_L6_INTAKE_ACK_OK
Codex chat_mention -> @review preproposal review
Grok chat_post_message -> GROK_L6_REVIEW_READY_FOR_PROPOSAL
Human -> @architect proposal-emission request referencing Grok message
Codex chat_emit_proposal -> prop_ba139bc0b76845aa98a36a56bd5e3835
PeerChatService automatic review_trigger -> @review
Grok chat_post_message -> review-trigger reply
```

Durable proposal evidence:

```text
proposal_id=prop_ba139bc0b76845aa98a36a56bd5e3835
proposal_type=lane_graph
proposal_status=open
proposal_message=msg_3567b01333104dc5b1bbe9a4542019d2
proposal_references=["message:msg_6dc2805535d744cc8a4e84d4c85be8bf"]
lane.feature_id=loop6_grok_reviewed_proposal
lane.capabilities=["docs"]
lane.feature_group=loop6
lane.review_runtime=grok
```

Runtime accounting:

```text
inboxes: 4/4 status=read
latency traces: 4/4 delivery_mode=mcp_writeback
degraded_reason: null for all four traces
request_log tools: chat_post_message, chat_mention, chat_post_message,
  chat_emit_proposal, chat_post_message
resolutions=[]
feature_lanes_exists=false
```

Impact:

- The current Grok peer path can participate in bounded groupchat review before
  a Codex architect emits a durable proposal.
- `chat_emit_proposal` successfully closes the architect inbox and creates the
  automatic `review_trigger`; Grok can consume that trigger with normal
  callback writeback.
- This is the first Codex-Grok local runtime proof for groupchat-produced
  proposal artifacts, not just peer message writeback.

Limits:

- The run intentionally did not approve or dispatch the proposal.
- There is no lane execution, final-action hold, GitHub truth, or merge truth.
- Grok still used the callback bridge for normal chat writeback; this does not
  prove Grok formal collaboration-response tool support.
- The proof is one local sample, not soak or overnight reliability.

Notes:

- Two excluded harness failures preceded the successful run. One reused a stale
  inbox object after Grok review and concatenated a `None` responded message id;
  one supplied `profile_id='god_peer'` for role `review` instead of the
  required `profile_id='review'`. Neither changed product code or indicates a
  product proposal boundary failure.

Next:

- Run `Loop 7` as a bounded approval-to-safe-final-action-hold proof using the
  Grok-reviewed proposal path, isolated execution, and no auto-merge.

### F129. Codex-Grok peer path has two clean short-soak samples

Severity: positive reliability evidence with bounded confidence.

Loop 5D reran the Loop 5C short-soak shape with a fresh runtime root and fresh
conversation:

```text
runtime_root=/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7
conversation_id=conv_14ac6db06e7d4c67a9233cd1643d0e6b
architect=part_9cc94aa6014147e5a3ee4820abaf5b92 codex gpt-5.4
review=part_a9961ec7560d4000b144a9a17edaa2de grok grok-composer-2.5-fast
```

The run executed three human -> Codex architect -> Grok review handoffs in the
same conversation while rebuilding `GodSessionLayer` between turns:

```text
turn_1=CODEX_L5D_TURN1_ACK_OK -> GROK_L5D_TURN1_REPLY_OK
turn_2=CODEX_L5D_TURN2_ACK_OK -> GROK_L5D_TURN2_REPLY_OK
turn_3=CODEX_L5D_TURN3_ACK_OK -> GROK_L5D_TURN3_REPLY_OK
```

Durable evidence:

```text
summary=/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7/loop5d_short_soak_summary.json
provider_events=/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7/provider_events.jsonl
chat_db=/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7/chat.db
god_sessions=/tmp/xmuse-loop5d-codex-grok-soak-k0znhff7/god_sessions.json

all six inboxes: status=read
all six latency traces: delivery_mode=mcp_writeback, degraded_reason=null
failure_traces=[]
final_non_read_inbox_items=[]
provider receive events: six successes
grok provider session: 019ee626-98df-7c50-b301-8d697ea96bc2
grok provider_native_session_reused: false on turn 1, true on turns 2 and 3
```

Impact:

- Loop 5C and Loop 5D together provide two clean local Codex + Grok short-soak
  samples after the Loop 5B recovered Codex producer miss.
- The repeated clean samples are enough to move the next active boundary from
  basic peer writeback/restart short-soak toward groupchat-produced proposal
  proof.
- The evidence still supports fail-closed durable accounting: success is
  based on inbox states, request logs, latency traces, callback writeback, and
  provider events, not provider stdout alone.

Limits:

- This is not overnight or statistical reliability proof.
- This is not yet groupchat-produced proposal proof.
- This is not lane execution proof.
- This is not Grok provider-plane adapter/profile proof.
- This is not GitHub/server truth or merge truth.

Notes:

- A first Loop 5D harness attempt failed before peer runtime because the
  scripted Grok initial participant omitted explicit `provider_id='grok'`.
  Current `PeerChatService` validation requires non-Codex participants to
  provide `provider_id`, `cli_kind`, and `model`. The corrected harness used
  that contract and completed the run.

Next:

- Run `Loop 6` as a bounded groupchat-produced proposal proof with Codex
  architect and Grok review.
- Keep lane execution out of scope until the proposal artifact itself is
  durable and inspectable.

### F128. Codex-Grok short soak passed once with explicit provider-turn artifacts

Severity: positive reliability evidence with bounded confidence.

Loop 5C produced one clean local Codex + Grok short soak after the Loop 5B
recovered `peer_no_inbox_side_effect` sample:

```text
runtime_root=/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d
conversation_id=conv_7c9f17af64c1427eaf5bd9943606acea
architect=part_ca6614226f004488b7d4819431517cad codex gpt-5.4
review=part_9491a8ad4ed24448af5b1a416c4e2800 grok grok-composer-2.5-fast
```

The run executed three human -> Codex architect -> Grok review handoffs in the
same conversation while rebuilding `GodSessionLayer` between turns:

```text
turn_1=CODEX_L5C_TURN1_ACK_OK -> GROK_L5C_TURN1_REPLY_OK
turn_2=CODEX_L5C_TURN2_ACK_OK -> GROK_L5C_TURN2_REPLY_OK
turn_3=CODEX_L5C_TURN3_ACK_OK -> GROK_L5C_TURN3_REPLY_OK
```

Durable evidence:

```text
summary=/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d/loop5c_short_soak_summary.json
provider_events=/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d/provider_events.jsonl
chat_db=/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d/chat.db
god_sessions=/tmp/xmuse-loop5c-codex-grok-soak-38ht7x0d/god_sessions.json

all six inboxes: status=read
all six latency traces: delivery_mode=mcp_writeback, degraded_reason=null
failure_traces=[]
final_non_read_inbox_items=[]
provider receive events: six successes
grok provider session: 019ee618-083f-7ef2-bbfd-6b421c4c832a
grok provider_native_session_reused: false on turn 1, true on turns 2 and 3
```

Impact:

- This is the strongest current Grok peer reliability evidence: one clean
  three-turn short soak with explicit provider artifacts, durable inbox
  terminal states, MCP writeback latency traces, and provider-native Grok
  session reuse after session-layer rebuilds.
- The Loop 5B `peer_no_inbox_side_effect` did not recur in this sample, so
  there is still no evidence-supported xmuse code patch for that boundary.
- Treat the Loop 5B miss as a recovered Codex producer reliability warning
  that needs repeated sampling, not as a confirmed deterministic xmuse bug.

Limits:

- This is not overnight or statistical reliability proof.
- This is not groupchat-produced proposal proof.
- This is not lane execution proof.
- This is not Grok provider-plane adapter/profile proof.
- This is not GitHub/server truth or merge truth.

Next:

- Run `Loop 5D` as a second Codex + Grok short soak with the same
  provider-turn artifact capture.
- If Loop 5D is also clean, promote the next active boundary to a
  groupchat-produced proposal path using Codex + Grok peers.
- If `peer_no_inbox_side_effect` recurs, keep the active boundary at the
  Codex producer side and add durable provider-turn diagnostics before any
  code patch.

### F127. Codex-Grok restart/resume can recover from one Codex no-side-effect turn

Severity: reliability gap with positive recovery evidence.

Loop 5B attempted a post-patch Codex + Grok restart/resume sample:

```text
runtime_root=/tmp/xmuse-loop5b-codex-grok-resume-k2msw2e9
conversation_id=conv_9492b501e94a4826a510402064d96971
turn_1=CODEX_L5B_TURN1_ACK_OK -> GROK_L5B_TURN1_REPLY_OK
```

After `GodSessionLayer` restart, the first attempt at turn 2 failed at the
Codex producer boundary:

```text
architect_inbox=inbox_6c5fc48dda0a4c22b502f80209f83f48
delivery_mode=failed
degraded_reason=peer_no_inbox_side_effect
status_after_failure=unread
nudge_count=1
request_log_rows_for_failed_attempt=0
```

The same durable inbox was then retried and recovered:

```text
retry_outcome={"nudged": 1, "happy_path": 1, "failed": 0, "fallback_replies": 0}
architect_reply=CODEX_L5B_TURN2_ACK_OK
created_review_inbox=inbox_c236f827f90e43f19fc2d773167a6a4e
review_reply=GROK_L5B_TURN2_REPLY_OK
grok_provider_session_reused=true
grok_provider_session_id=019ee60c-0ee3-75e3-901c-a8cc48b29b6b
```

Impact:

- The scheduler's fail-closed behavior is useful: it did not count stdout or
  provider success as chat success, and it left the inbox retryable.
- The current proof cannot claim zero-retry reliability because Codex produced
  one successful provider result without durable chat side effects.
- Grok provider-native resume remained intact during the recovered second
  review turn.

Required next behavior:

- Run `Loop 5C` as a short Codex + Grok soak with explicit provider-turn
  artifact capture for every peer turn.
- If `peer_no_inbox_side_effect` recurs, classify the first common producer
  boundary before patching.
- Do not treat the recovered sample as soak/overnight readiness.

### F126. Grok peer can resume provider-native session after GodSessionLayer restart

Severity: positive local runtime evidence with remaining reliability scope.

Loop 5 produced one successful Codex/Grok restart-resume handoff sample:

```text
runtime_root=/tmp/xmuse-loop5-restart-resume-fClwAR
conversation_id=conv_d0ee4175d61545bcae0437d65baec435
codex_god_session=god-b5a91f4d785f4bf1bf7e991f72f1ebb1
grok_god_session=god-722e5d8439e446038e69771253e88bcf
turn_1=CODEX_L5_TURN1_ACK_OK -> GROK_L5_TURN1_REPLY_OK
turn_2_after_restart=CODEX_L5_TURN2_ACK_OK -> GROK_L5_TURN2_REPLY_OK
all_inboxes=read
all_latency=delivery_mode:mcp_writeback,degraded_reason:null
```

The first sample exposed a provider-native resume gap: `GodSessionLayer`
reused the durable Grok GOD session record after restart, but the restarted
`grok_persistent` shim did not receive the stored `grok_cli_session`
`provider_session_id`.

The targeted fix passes active Grok provider bindings into `GrokLauncher`,
which now starts `grok_persistent --session-id <id>`, and the shim uses that id
as the initial `grok -r` resume target.

Post-patch proof:

```text
uv run pytest ... -> 7 passed in 0.21s
runtime_root=/tmp/xmuse-loop5-grok-resume-ki8zs13h
conversation_id=conv_689bee9a6be840c1bb68dbc86597716d
first_provider_session_id=019ee604-3fdf-7e52-9621-ae7827e12107
second_provider_session_id=019ee604-3fdf-7e52-9621-ae7827e12107
provider_session_reused=true
both inboxes=read
both latency=delivery_mode:mcp_writeback,degraded_reason:null
```

Impact:

- Grok now has a proven local provider-native resume path for the GOD peer
  scheduler boundary.
- The proof is not yet a multi-sample soak, not overnight readiness, and not
  provider-plane adapter/profile support.

Required next behavior:

- Run one additional Codex + Grok restart/resume or short soak sample after
  the provider resume patch.
- Keep stdout/fallback replies excluded from success.
- Do not claim lane execution, GitHub truth, merge truth, or production-ready
  groupchat from this evidence.

### F83. Persistent OpenCode review can ignore existing lane artifacts without prompt grounding

Severity: review evidence integrity issue.

Loop 25z27b reached a real bounded chain on main:

```text
conversation_id=conv_bf6ffeefe45b4e0b87c201a99966af91
collaboration_run=collab_eeb0ffec254d455dbd781f2dafa61452
proposal_id=prop_1b09bb35d22842dd98f33fac687c4300
resolution_id=res_53e495fa801d4c70a67b7cd837e59ab9
lane_status=awaiting_final_action
review_verdict_id=verdict-merge-rtask_de2af7adab2542cb9d21be47b8d6e707
final_action_hold=final-f9f998f0542a
```

The review verdict had non-empty evidence refs, including the gate report:

```text
logs/gates/loop25z27b_main_review_mcp_exposure_fullchain/report.json
```

But the OpenCode review summary said MCP tools were unavailable and then
claimed no logs or prior execution artifacts existed. That was false for the
runtime root and shows that refs alone are not enough; the review prompt must
ground the reviewer in the current gate, worker, lane context, and evidence
refs.

Impact:

- A review verdict can look structurally valid while its narrative evidence is
  stale or wrong.
- Non-empty `review_evidence_refs` are necessary but not sufficient.
- Stdout fallback review remains weaker than MCP-backed review truth.

Required next behavior:

- Prompt persistent reviewers to treat provided gate/worker/lane refs as
  current review authority.
- Preserve MCP tool exposure as a separate gap; do not mask it with better
  prompt text.

### F84. PR #71 improves review artifact grounding but does not fix provider MCP exposure

Severity: bounded improvement with explicit remaining manual gap.

Candidate branch `codex/review-peer-artifact-grounding` at
`cd713753343228ac928b79cf9611885d016eee23` adds a prompt/context grounding
section for persistent review.

Loop 25z28 reran the same bounded path and reached:

```text
conversation_id=conv_5b4dcc9355de484cac3b6521a3f1b7e9
collaboration_run=collab_c29de586d02c44049be6e7d21027c5e9
proposal_id=prop_9a853383ff4e4433894040efc51b74c2
resolution_id=res_d1e839d0c0214a14a1b6da1acb16e2b3
lane_status=awaiting_final_action
review_verdict_id=verdict-merge-rtask_255e97edcac1453cb7514162be09d42e
final_action_hold=final-def8a28d600e
```

The review summary cited:

```text
logs/gates/loop25z28_candidate_review_artifact_grounding_fullchain/report.json
logs/agent_spawns/loop25z28_candidate_review_artifact_grounding_fullchain/20260618T230823Z.stdout.log
logs/agent_spawns/loop25z28_candidate_review_artifact_grounding_fullchain/20260618T230823Z.result.json
logs/lane_context/loop25z28_candidate_review_artifact_grounding_fullchain/latest.json
git diff HEAD~1
git status
```

PR #71 was opened as draft against `main`; GitHub Actions run `27795048428`
completed successfully for `contract-smoke-gates`,
`real-runtime-integration-gate`, and `quality-gates`.

Remaining gaps:

- OpenCode review provider still reported MCP unavailable and used stdout
  fallback.
- Duplicate proposal emission still appeared.
- Peer session health still reported `starting`.
- PR #71 is open/draft/unmerged; no review truth or merge truth is claimed.

### F79. CJK formal collaboration response detection is fixed for one clean runtime path

Severity: resolved blocker for the observed CJK OpenCode collaboration-response
turn; production readiness remains open.

Before PR #68, an OpenCode review peer could receive a Chinese request that
explicitly mentioned `chat_record_collaboration_response` but still write only
a normal chat message, leaving the formal collaboration run partial unless the
operator nudged it.

PR #68 changed the OpenCode peer callback bridge to recognize explicit
`chat_record_collaboration_response` requests and CJK
collaboration/response/record wording as formal collaboration-response turns.

Runtime recheck:

```text
loop=25z22
conversation_id=conv_de93a1a3420c463687471ad27e965970
collaboration_run=collab_9b1d2393013c452587cffe0c513d4065
review_mention=msg_ea0a4a5141ab48c7b9d49349c76c3375
review_response=collab_resp_09efb3c7288a4c03b247fce66364ded4
review_ack_message=msg_94e90dd8c55441408a2f12bc1779ada0
operator_nudge_required=false
```

Impact:

- The specific CJK formal collaboration-response parser gap is closed for the
  observed OpenCode peer-chat callback path.
- The durable authority is the `collaboration_responses` row, not streamed
  provider stdout.
- The broader groupchat remains local proof only and must not be called
  production ready.

Remaining gaps:

- Gate profiles still fail open when `gate_profiles.json` is missing.
- Platform OpenCode review still lacks exposed MCP tools in Loop 25z22 and
  used stdout fallback for the review summary.
- No live MemoryOS trace id/artifact was produced.
- No GitHub review truth, merge truth, `ready_to_merge`, `pr_merged`, full
  L8-L10 closure, full L1-L11 closure, or overnight readiness is claimed.

### F80. Gate profile authority candidate removes the observed fail-open path

Severity: candidate fix for an execution gate contract gap; not server proof.

Loop 25z22 showed that a missing `gate_profiles.json` let the lane gate pass
open with `gate_profiles_missing` before configured OpenCode review. The
candidate branch `codex/gate-profile-runtime-authority` changes the authority
contract:

- `XMUSE_ROOT/gate_profiles.json` is still the runtime override.
- `xmuse/gate_profiles.json` in the lane worktree is the tracked repository
  fallback.
- missing runtime and worktree gate config fails closed instead of passing
  open.

Runtime recheck:

```text
loop=25z23b
branch=codex/gate-profile-runtime-authority
candidate_commit=31f3714052bc60e68f5bc75db8490cb6e0fd7f39
conversation_id=conv_6a878e9bd1e64ab6a55c271e9768c7d5
collaboration_run=collab_441bcec91d1546d78eec63386ec7ca37
proposal_id=prop_29b2575582744677a40867af10f877f3
resolution_id=res_6dcb6bdeb3a440c39cffd1ca5d54a91e
lane=loop25z23b_gate_profile_authority_fullchain
gate_report=logs/gates/loop25z23b_gate_profile_authority_fullchain/report.json
profile_ids=["strict-product"]
gate_command=uv run pytest -q tests/xmuse/test_package_boundaries.py
gate_result=16 passed in 2.99s
gate_profiles_missing=false
final_action_hold_id=final-dfa93a59cd91
```

Impact:

- The observed missing-profile gate ambiguity is no longer accepted on the
  candidate path.
- The gate report now proves a configured blocking profile was resolved and
  run for the bounded package-boundary lane.
- PR #69 supplies exact GitHub PR/CI/merge server facts for this head, but no
  GitHub review truth.

Remaining gaps:

- Platform OpenCode review still used stdout fallback instead of durable review
  MCP/tool evidence.
- This was a bounded package-boundary lane, not a broad real code-change
  completion proof.
- No live MemoryOS trace id/artifact was produced.
- No GitHub review truth, merge truth, `ready_to_merge`, `pr_merged`, full
  L8-L10 closure, full L1-L11 closure, or overnight readiness is claimed.

### F81. Gate profile authority survives post-merge main rerun

Severity: resolved for the bounded package-boundary lane gate path; review
plane remains degraded.

After PR #69 merged, Loop 25z24 reran the groupchat-to-final-hold path from
`origin/main` at merge commit `007811aaaebc7f82b05dd2dc781829ed026a2197`.

Runtime recheck:

```text
loop=25z24
conversation_id=conv_da39b523e89f4c229381559e1fbf2891
collaboration_run=collab_c288f01ad8be46e8947425a965d3124d
proposal_id=prop_9f17d777d4654ea589b44f8c8f5fe759
resolution_id=res_a5fa5185b2164a7faeda0d8809b95b80
lane=loop25z24_post_pr69_gate_profile_main_fullchain
base_head_sha=007811aaaebc7f82b05dd2dc781829ed026a2197
gate_report=logs/gates/loop25z24_post_pr69_gate_profile_main_fullchain/report.json
profile_ids=["strict-product"]
gate_command=uv run pytest -q tests/xmuse/test_package_boundaries.py
gate_result=16 passed in 3.00s
gate_profiles_missing=false
final_action_hold_id=final-e6266f212977
```

Impact:

- The tracked repository gate profile authority is now verified on main for
  one bounded real runtime chain.
- The observed fail-open `gate_profiles_missing` path did not recur.
- The lane still used the worktree fallback because runtime
  `XMUSE_ROOT/gate_profiles.json` was absent; that warning is expected for
  this run and is not the old fail-open condition.

Remaining gaps:

- The lane proposal requested `review_runtime=local`, so this is not a
  configured OpenCode platform-review rerun.
- The platform review plane degraded to one-shot fallback with
  `missing_feature_identity`, and `review_evidence_refs=[]`.
- Peer session health still showed sessions as `status=starting` after
  successful MCP writebacks, so session lifecycle observability remains open.
- This remains a bounded package-boundary lane, not broad coding-task
  completion.
- No live MemoryOS trace id/artifact was produced.
- No GitHub review truth, `ready_to_merge`, `pr_merged`, full L8-L10 closure,
  full L1-L11 closure, production-ready groupchat, or overnight readiness is
  claimed.

### F82. CJK collaboration fill requests need explicit formal callback detection

Severity: candidate fix for one real OpenCode peer collaboration blocker;
production readiness remains open.

Loop 25z25 showed that the earlier CJK collaboration-response fix still missed
a natural Chinese phrase shape. The OpenCode review request asked the peer to
use the collaboration response tool and "回填" its review conclusion, but did
not include the exact `chat_record_collaboration_response` tool name. The peer
therefore wrote an ordinary chat message, leaving the collaboration partial.

Candidate PR #70 adds fill/writeback record markers to the CJK detector:
`回填`, `回写`, and `登记`.

Runtime recheck:

```text
loop=25z26
branch=codex/cjk-collab-response-tool-phrase
candidate_commit=41954201ffab05d410e77b0c96f19cbeac76336a
conversation_id=conv_7305970133014d07a050a81aedfa479a
collaboration_run=collab_d4c53784db5f4d88a0aba61e4ba93434
review_response=collab_resp_407f6b61bc314781a936957ae90a0237
proposal_id=prop_47f0d6057ab7405eb5595e7394816955
resolution_id=res_eba239f0cd5149fda06a62d3d5f51017
lane=loop25z26_candidate_cjk_fill_opencode_review_fullchain
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_evidence_refs=non_empty
gate_result=16 passed in 2.95s
final_action_hold_id=final-135ac3dde026
```

Impact:

- The observed natural CJK fill/writeback phrase now maps to the formal
  collaboration-response callback prompt in focused coverage.
- The candidate runtime reached a completed durable collaboration and final
  action hold with configured OpenCode platform review.
- The PR remains narrow: one detector and its focused tests.

Remaining gaps:

- PR #70 is open draft at the time of this entry. GitHub Actions succeeded for
  the exact head, but this is CI server fact only.
- The review peer summary still said MCP tools were unavailable and reported
  via stdout, so review-plane MCP tool exposure is still open.
- Duplicate proposal/idempotency noise and stale `session_health=starting`
  remain open.
- This remains a bounded package-boundary lane, not broad coding-task
  completion.
- No live MemoryOS trace id/artifact was produced.
- No GitHub review truth, merge truth, `ready_to_merge`, `pr_merged`, full
  L8-L10 closure, full L1-L11 closure, production-ready groupchat, or
  overnight readiness is claimed.

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

Loop 23l gap before fix:

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

Historical manual gap:

- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this
  loop and should be treated as missing evidence for that loop, not fabricated
  truth. Current runs use the ledger as the gap index.

### F32. Codex/OpenCode handoff reliability passes a second clean restart/soak probe

Severity: positive local runtime evidence for Loop 5 reliability; not provider
memory proof or fullchain closure.

Loop 18 ran from a detached clean `origin/main` worktree after PR #47 merged:

```text
worktree=/tmp/xmuse-loop18-main-sjeLJ8
HEAD=10d5a0e92d3c63fa10bf1e5a5053c29e1ea2ae21
runtime_root=.goal-runs/2026-06-18/loop-18-restart-resume-codex-opencode-Sq9mR2
conversation_id=conv_8f8c444cf3ed4751a6848ce6bff5839c
```

Run 1 intentionally remains contaminated evidence because the human prompt
included literal `@review`, which created a direct review inbox:

```text
run1 human_mentions=["@architect", "@review"]
direct_review_inbox=inbox_f54bf477af174f149aff8cd638d57ab6
architect_handoff_inbox=inbox_2f9a2487f2b24c2d82433aafc0843264
```

After stopping and restarting the runner against the same runtime root and
conversation, clean runs 2/3/4 used only human `@architect` mentions:

```text
run2 architect=ARCHITECT_LOOP18_RUN2_READY
run2 review=OPENCODE_LOOP18_RUN2_READY

run3 architect=ARCHITECT_LOOP18_RUN3_READY
run3 review=OPENCODE_LOOP18_RUN3_READY

run4 architect=ARCHITECT_LOOP18_RUN4_READY
run4 review=OPENCODE_LOOP18_RUN4_READY
```

Observed durable state:

```text
message_count=17
assistant_count=13
inbox_by_status={"read": 9}
latency_count=9
latency_by_mode={"mcp_writeback": 9}
latency_degraded=[]
tool_counts={"chat_post_message": 9, "chat_read_inbox": 4}
```

Impact:

- This provides a second local restart/resume sample for real Codex/OpenCode
  groupchat handoff.
- Clean runs 2/3/4 prove the review inboxes were produced by architect
  handoff messages, not direct human review mentions.
- No stdout fallback was counted as successful reply truth.

Remaining boundary:

- `god_sessions.json` preserved durable xmuse session identity and
  `peer_chat_worktree`, but it does not record provider-native thread ids for
  this backend; provider memory continuity remains unproven.
- This loop does not execute a proposal, resolve final-action hold, prove
  GitHub review truth, prove live MemoryOS, or prove full closure.

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

### F33. Execute feasibility producer prompt did not match dispatch-gate authority

Severity: runtime blocker found by Loop 19; fixed in PR #48.

Loop 19 reached a real proposal approval attempt, but approval failed closed:

```text
code=dispatch_gate_blocked
message=blocked_execute_not_confirmed
```

The durable execute collaboration response used:

```text
type=execute_feasibility_verdict
verdict=feasible
```

The approval gate actually requires:

```text
type=execute_feasibility_verdict
status=executable
summary=<nonempty>
evidence_refs=<nonempty list>
```

Impact:

- The authority was correct to reject the proposal.
- The producer prompt/tool descriptions were too loose and let execute emit a
  plausible but non-authoritative shape.
- Follow-up chat prompting could not safely mutate a completed collaboration
  response.

Fix:

- PR #48 makes the exact schema visible in peer nudge prompts and MCP tool
  descriptions.
- The fix does not weaken the dispatch gate.
- Loop 19b proved the prompt contract change locally: execute emitted
  `status=executable`, and Chat API approval passed.

Remaining boundary:

- PR #48 passed current-head GitHub checks and was squash-merged at
  `2026-06-18T00:13:38Z` with merge commit
  `16f27a9ba25951d46809ca8b9faddf9002899ea1`.
- No GitHub review truth or ready-to-merge claim is made; `reviewDecision` was
  empty.

### F34. Real GOD groupchat can now drive one local lane to final-action hold

Severity: positive local runtime evidence; not GitHub truth or full closure.

Loop 19b exercised:

```text
human @architect
-> Codex architect collaboration/proposal
-> Codex execute feasibility verdict
-> OpenCode review scope PASS
-> human Chat API approval
-> feature_lanes.json projection
-> platform runner execution
-> OpenCode persistent review
-> awaiting_final_action
```

Observed terminal lane state:

```text
lane_id=slice-human-mention-extraction-code-span-escape-guard
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
final_action_hold_id=final-75d340b41a53
```

Candidate implementation:

- `src/xmuse_core/chat/mentions.py`
- `src/xmuse_core/chat/peer_service.py`
- `tests/xmuse/test_peer_chat_api.py`
- `tests/xmuse/test_peer_chat_mentions.py`

Main Codex audit reran focused tests, package boundary tests, full ruff, diff
whitespace checks, and namespace boundary check before opening PR #49.

Impact:

- This is the first recorded local sample where a natural Codex/OpenCode GOD
  groupchat produced a real lane that was executed and independently reviewed
  through the platform runner.
- The runner correctly stopped at final-action hold under `--no-auto-merge`.
- The result was split into a small main-based PR (#49), not added to PR #43.

Remaining boundary:

- PR #49 was rebased after PR #48 merged, passed current-head GitHub checks,
  and was squash-merged at `2026-06-18T00:16:14Z` with merge commit
  `0111f3bef270ad9e8a82eb919bcd8ed12220fc21`.
- OpenCode persistent review is local review evidence only.
- GitHub merge truth exists for PR #49 only as the inspected merged PR fact.
  No GitHub review truth, ready-to-merge, live MemoryOS, full L8-L10 closure,
  or full L1-L11 closure is claimed.

### F35. Dispatch bridge still asks a chat-only execute peer to do worktree execution

Severity: real runtime design gap.

During Loop 19b, approval queued a dispatch bridge message to the groupchat
execute peer. The peer replied:

```text
DISPATCH_FAILED: peer_chat_nudge mode is chat-only, so I did not execute the
approved worktree changes or run verification.
```

Impact:

- The groupchat execute role is currently a discussion/feasibility peer, not a
  worktree-mutating executor.
- The real worktree execution succeeded through the platform execution worker,
  so the lane was not blocked.
- Dispatch bridge semantics are confusing and can look like a failed execution
  even when the platform execution path is healthy.

Recommended next change:

- Split dispatch bridge notification from execution authority.
- Either make the bridge emit a status/coordination message only, or bind it to
  a real execution worker capability instead of the chat-only peer nudge mode.

### F36. Gate profile and proposal-text evidence need tightening

Severity: medium; evidence hygiene gap.

Loop 19b recorded:

```text
gate_profiles_missing
```

The lane still reached persistent review and final-action hold, but the gate
profile signal should be explicit for runtime-derived lanes.

Loop 19b also had stale proposal text saying collaboration responses were still
pending after execute/review had replied.

Impact:

- Neither issue invalidates the local fullchain evidence.
- Both make later audits noisier because read-model text can disagree with the
  durable collaboration/proposal/runner authority.

Recommended next change:

- Add a default gate profile for proposal-created peer-chat lanes.
- Refresh or avoid speculative proposal notes that describe pending evidence.
- Treat durable collaboration responses, proposal status, resolutions, and lane
  state as authority over proposal prose.

### F37. Dispatch bridge could turn chat-only text into false execution evidence

Severity: real runtime authority bug; patched in Loop 20b candidate.

Loop 20 reproduced the boundary on current `origin/main` after PR #48 and PR
#49 had merged. The repro used real Chat API approval and real peer scheduler
delivery for a dispatch-boundary lane.

Observed prompt from `ChatDispatchBridge`:

```text
Execute this approved xmuse dispatch queue entry through the real provider path.
Use available Codex tools to inspect/edit the requested worktree files.
The final chat_post_message content must include DISPATCH_COMPLETED, files changed, and verification run.
```

Observed durable response:

```text
DISPATCH_COMPLETED
Files changed: none.
Verification run: chat_read_inbox ...
```

Observed queue state:

```text
status=dispatched
provider_run_ref=provider:execute:part_8115217095814e82a6c090facd5e29e7
dispatch_evidence=mcp_writeback:inbox_9d5428672b044fb68001bd244b7cc4df
```

Impact:

- A chat-only peer nudge could be recorded as dispatched provider execution
  evidence by including the `DISPATCH_COMPLETED` text marker.
- This contradicted the peer-chat nudge contract, which says the turn is
  interactive chat and must not edit files, run tests, or start long work.
- The actual lane worker is the execution authority; dispatch bridge chat text
  must not claim execution.

Loop 20b patch:

- changes the bridge prompt to an acknowledgement-only chat-plane handoff;
- requires `DISPATCH_ACKNOWLEDGED` instead of `DISPATCH_COMPLETED`;
- tells the peer not to edit files, run tests, inspect unrelated state, or claim
  execution;
- writes `provider_run_ref=peer_ack:<role>:<participant_id>` to avoid presenting
  the chat acknowledgement as provider execution;
- keeps real execution proof with platform lane worker and review artifacts.

Loop 20b durable result:

```text
status=dispatched
provider_run_ref=peer_ack:execute:part_22071394643a41ee9fe672f1af9bc5e6
dispatch_evidence=mcp_writeback:inbox_0d251b1d591848a39aae8dac6c26a8ee
assistant_message=DISPATCH_ACKNOWLEDGED ... does not claim or perform lane execution
```

Remaining boundary:

- PR #50 passed current-head GitHub checks and was squash-merged at
  `2026-06-18T00:32:44Z` with merge commit
  `6c98c7aa09c92b0a3dce1009bb6f3e79fffd6c75`.
- The post-merge main-branch CI completed successfully in run `27728769841`.
- `reviewDecision` was empty, so no GitHub review truth is claimed.
- The dispatch queue status name `dispatched` now means the chat-plane handoff
  was delivered, not that worktree execution completed.

### F38. Observation lanes can still trigger long child-worker execution

Severity: runtime prompt hygiene gap; not fixed in Loop 20b.

Loop 20b used a lane prompt that said:

```text
Do not modify code. Observe dispatch bridge acknowledgement semantics only.
```

The platform lane worker still launched a Codex child worker and the child read
superpowers skill files before the runner was stopped.

Impact:

- This did not invalidate the dispatch bridge acknowledgement evidence because
  the bridge proof came from `chat.db` queue/message/tool-trace records before
  relying on lane-worker output.
- It shows that observation/no-op lanes need stronger execution-mode controls,
  or they should not be projected into `feature_lanes.json` when the loop target
  is only chat-plane dispatch evidence.

Recommended next change:

- Add a dry-run/no-worker projection mode for dispatch-boundary probes, or make
  observation lanes explicit no-op tasks at the runner level.
- Keep this separate from dispatch bridge acknowledgement semantics to avoid a
  broad PR.

### F39. OpenCode peer-chat callback can now write formal collaboration responses

Severity: resolved local runtime capability boundary.

Loop 21 used a real OpenCode review participant:

```text
participant=part_45482890c9f343aa9cacfecf476539bb
model=opencode-go/deepseek-v4-flash
runtime=opencode
```

Review wrote durable chat messages through the callback bridge:

```text
msg_116d26c7430a496e9097fe048a473c70
msg_033c1b4fc8da44cd8e816a76d45fdd90
writeback_path=opencode_callback_bridge
```

But the collaboration run remained partial:

```text
run_id=collab_db787fd9f18f46169c140f6ac0cf9343
status=partial
formal_review_response=missing
```

Original root cause:

- `opencode_persistent` peer-chat mode tells OpenCode to return concise natural
  language only and explicitly says not to call tools.
- The callback bridge always writes via `chat_post_message`.
- Prompting Review GOD to "use the collaboration response tool" only produced
  another normal chat message, because that mode does not expose such a write
  path.

Fix:

- `opencode_persistent` now detects formal collaboration-response requests that
  include a `collab_...` run id.
- It asks OpenCode for one strict callback JSON object and rejects ordinary chat
  text as authority.
- The callback bridge writes `chat_record_collaboration_response` first, then
  writes the durable groupchat reply through `chat_post_message` with
  `envelope.callback_action=chat_record_collaboration_response`.
- A prompt-contract cleanup removed the conflicting natural-language reply
  instruction from structured callback turns.

Runtime proof:

- Loop 22b proved the direct OpenCode callback bridge can write both the formal
  response and assistant message.
- Loop 22d proved the real scheduler/Ray/OpenCode/MCP path after the transport
  fix:

```text
conversation_id=conv_a37a685f28764b2da93ef204650ee956
collaboration_run=collab_d018a7ce96c7467ea5943b73a044f170
formal_response=collab_resp_6e22cf4398b64d428ab289e6c31eb203
chat_inbox_items.status=read
collaboration_runs.status=done
message.envelope.callback_action=chat_record_collaboration_response
```

Remaining boundary:

- This is local runtime proof only.
- It is not GitHub review truth, merge truth, live MemoryOS proof, full L8-L10
  closure, full L1-L11 closure, or overnight readiness.
- Trace parity remains incomplete; see F45.

### F40. Collaboration gate can allow dispatch while collaboration run is partial

Severity: authority clarity gap.

Loop 21 approved a lane_graph proposal with:

```text
proposal_id=prop_b3a9152563ae45239d1cd342912bf616
resolution_id=res_35af1e68a5c5464f95f1298ca7e4e748
collaboration_run=collab_db787fd9f18f46169c140f6ac0cf9343
collaboration_run_status=partial
execute_confirmed=1
gate_decision=allowed
```

The proposal and resolution explicitly carried:

```text
manual_gap=review_response_tool_unavailable_via_opencode_bridge
```

Impact:

- The gate did not claim a formal OpenCode collaboration response existed.
- The gate did allow dispatch with only execute's formal response and review
  durable chat messages as manual-gap evidence.
- This may be acceptable for a no-code verification lane, but the rule needs to
  be explicit so future code lanes do not inherit a weaker review authority
  accidentally.

Recommended next change:

- Make collaboration dispatch gate policy explicit by lane type and risk.
- For code-changing lanes, fail closed until every required role writes a
  formal collaboration response or a human override is recorded as a stronger
  authority artifact.
- For no-code verification lanes, keep the allowed path but surface the manual
  gap in lane context and review prompt.

### F41. Dispatch queue and lane worker authority can diverge

Severity: runtime authority mismatch.

Loop 21 produced an acknowledgement-only dispatch bridge message after PR #50:

```text
dispatch_request=msg_5b216023d43e4293a31a1a4e42669fb0
dispatch_ack=msg_22a17a334aca4b7399676cc49b970b0b
ack_text=DISPATCH_ACKNOWLEDGED ... real execution remains with the platform lane worker
```

But the dispatch queue authority recorded failure:

```text
status=failed
failure_reason=Cannot reuse role='execute': existing live session does not match requested agent/worktree
provider_run_ref=null
```

At the same time, the platform lane worker executed and reached:

```text
feature_lanes.status=awaiting_final_action
gate_passed=true
review_decision=merge
```

Impact:

- The patch from Loop 20b prevented false execution claims in the chat message.
- The queue can still report failed while chat contains a handoff
  acknowledgement and the platform lane worker succeeds.
- Auditors must treat `chat_dispatch_queue` as chat-plane handoff authority,
  not as the final lane execution authority.

Recommended next change:

- Split queue statuses into handoff delivery states and execution states.
- Fix execute peer session reuse for dispatch notices, or avoid trying to reuse
  the same persistent execute session/worktree for chat-plane acknowledgement.
- Cross-link queue failure with lane execution state so dashboards do not show
  contradictory truth without context.

### F42. No-code verification worker did not preserve exact requested scope

Severity: runtime prompt hygiene gap.

Loop 21 asked the lane to run the named no-code verification command. The worker
ran focused tests and passed:

```text
13 passed, 1 warning in 5.99s
changed_files=none
```

However, the actual command did not exactly match the human request:

- omitted `tests/xmuse/test_peer_chat_api.py`;
- added several dispatch-bridge tests;
- read superpowers skill files despite the no-code verification task and
  child-worker override.

Impact:

- The worker output is useful local runtime evidence, but it is not exact
  compliance with the requested verification command.
- This extends F38: no-code/observation lanes still run through a generic child
  worker prompt that assumes code fixing and can be diverted by skill policies.
- Review accepted the result as correct and did not catch the missing
  `test_peer_chat_api.py` scope.

Recommended next change:

- Add a runner-level verification-only task type that executes an exact command
  list without invoking a coding child worker.
- When a prompt specifies exact validation commands, record and compare the
  actual executed command list before review.
- Keep superpowers/skill policies disabled for xmuse child-worker invocations,
  or make the child-worker wrapper fail when it reads skill files contrary to
  the lane contract.

### F43. Review runtime and provider read models disagree

Severity: evidence/read-model mismatch.

Loop 21 requested OpenCode review and a real OpenCode review process was
present:

```text
review_runtime_requested=opencode
opencode_persistent --model opencode-go/deepseek-v4-flash --variant max
```

But provider selection records said:

```text
provider_id=codex
profile_id=review
task_type=review
selection_reason=Route review to the high-quality codex review profile.
```

The review verdict also had:

```text
decision=merge
evidence_refs=[]
summary=MCP unavailable; stdout fallback.
```

Impact:

- Process truth and read-model truth disagree on which provider reviewed the
  lane.
- The review verdict is local runtime review evidence only; it is not GitHub
  review truth, and it missed the exact-command mismatch from F42.
- Empty `evidence_refs` make later audit weaker even when the summary includes
  useful references.

Recommended next change:

- Make persistent peer review delivery write the actual peer provider/runtime
  into provider selection records and review verdict metadata.
- Require review verdicts to include concrete evidence refs for worker result,
  stdout, diff, and command list.
- Teach review to compare requested command scope with executed command scope
  before emitting `merge`.

### F44. Ray app-server transport was incorrectly applied to OpenCode peers

Severity: resolved local runtime blocker for scheduler-driven OpenCode callback.

Loop 22c reran the scheduler path after the OpenCode callback prompt cleanup
and failed with:

```text
conversation_id=conv_fd749fe7864e45b7a304bac3a60c16af
collaboration_run=collab_b035cf1e1f7a4af5b1c985e115be5c41
chat_inbox_items.status=failed
failure_reason=peer_no_inbox_side_effect
collaboration_responses=0
peer_turn_mcp_tool_traces=0
```

The same request succeeded when sent directly to `opencode_persistent`, proving
the callback bridge itself was not the failing component. The runner/Ray path
had routed the OpenCode participant through the global Ray app-server transport:

```text
provider_session_kind=codex_app_server_thread
```

Impact:

- OpenCode participants could be silently handled by the Codex app-server
  transport when `XMUSE_RAY_GOD_TRANSPORT` defaulted to `app-server`.
- That bypassed the OpenCode process shim and therefore bypassed the OpenCode
  callback bridge.
- The failure surfaced as a missing inbox side effect instead of a clear
  provider-routing error.

Fix:

- `RayGodSessionLayer` now forces OpenCode runtime sessions to use process
  transport while leaving Codex on the configured default transport.
- Focused coverage asserts that OpenCode actor kwargs carry
  `transport_mode=process` even when the layer default is `app-server`.

Runtime recheck:

```text
conversation_id=conv_a37a685f28764b2da93ef204650ee956
collaboration_run=collab_d018a7ce96c7467ea5943b73a044f170
formal_response=collab_resp_6e22cf4398b64d428ab289e6c31eb203
chat_inbox_items.status=read
collaboration_runs.status=done
peer_turn_mcp_tool_traces=chat_post_message
```

Remaining boundary:

- This is local runtime proof for one scheduler-driven OpenCode collaboration
  response.
- Runner shutdown still emitted Ray cleanup noise after success; that is a
  separate lifecycle hygiene issue, not callback authority evidence.

### F45. Collaboration-response callback lacks separate peer tool trace parity

Severity: observability gap; not a formal-response authority blocker.

After Loop 22d, the formal response authority was durable:

```text
collaboration_responses.target=@review
collaboration_responses.status=received
collaboration_runs.status=done
message.envelope.callback_action=chat_record_collaboration_response
```

However, peer-turn tool traces still showed only:

```text
peer_turn_mcp_tool_traces=chat_post_message
```

Impact:

- `collaboration_responses` is the authority for the formal response, so the
  response itself is not invalidated.
- Trace consumers cannot yet see `chat_record_collaboration_response` as a
  separate callback action in the peer-turn trace table.
- Stronger observability claims should remain forbidden until the trace model
  represents every structured callback write.

Recommended next change:

- Record `chat_record_collaboration_response` in peer-turn trace stages when
  the callback bridge writes the formal response.
- Keep this as a narrow observability PR; do not mix it with collaboration gate,
  proposal, lane execution, or review-plane changes.

### F46. Formal collaboration can now drive proposal creation

Severity: positive local runtime evidence with remaining observability gaps.

Loop 23g created one clean architect-led collaboration:

```text
conversation_id=conv_bdd2542c231e44f2a2c2e1fc4d926bd6
collaboration_run=collab_076164aed2a643febf6df27715f29569
collaboration_runs.status=done
collaboration_responses.@execute=received
collaboration_responses.@review=received
proposal_id=prop_5446f2c7a80445188bda18af8417c8bf
proposal.references=["collaboration:collab_076164aed2a643febf6df27715f29569"]
```

This was enabled by three targeted fixes:

- OpenCode callback parsing now tolerates markdown/fenced JSON while preserving
  expected collaboration run-id checks.
- The peer service writes a durable `collaboration_callback` inbox when a run
  becomes `done`.
- The callback payload explicitly asks the architect to emit the requested
  lane_graph proposal when the original request required one.

Impact:

- The chain no longer needs manual proposal construction for this bounded lane.
- The proposal still depends on local runtime chat authority, not GitHub or
  server truth.
- `chat_record_collaboration_response` trace parity remains incomplete as
  recorded in F45.

Recommended next change:

- Rerun the same chain after the dispatch worktree fix and record whether the
  architect callback still emits exactly one proposal without manual repair.

### F47. Execute gate parser was too narrow for provider-style verdicts

Severity: resolved local approval blocker.

Loop 23f/23g showed that a real execute peer may return a structured verdict
using provider-friendly fields:

```text
feasible=true
dispatchable=true
later_execution_command=uv run pytest tests/xmuse/test_package_boundaries.py -q
proof_boundary=local runtime contract proof only
```

The approval gate originally expected a narrower legacy shape and blocked the
proposal until the parser accepted `dispatchable` / `feasible` plus either
`command` or `later_execution_command`, while still requiring a non-empty proof
boundary and summary/notes.

Impact:

- The gate can now consume real provider-shaped execute feasibility responses.
- This does not weaken forbidden-claim handling; the proof boundary is still
  explicit and local-only.

Recommended next change:

- Keep the parser strict on proof boundary and exact command preservation.
- Add runtime evidence for a code-changing lane before using this as a general
  execution gate claim.

### F48. Chat dispatch worktree authority lagged lane projection authority

Severity: operator safety / authority mismatch.

Loop 23g lane projection contained the isolated lane worktree:

```text
feature_lanes.worktree=/tmp/xmuse-loop-23g-clean-dispatch-worktree-100647-exec
worker_worktree=/tmp/xmuse-loop-23g-clean-dispatch-worktree-100647-exec
```

But the chat dispatch bridge message still instructed the execute peer:

```text
Execution worktree: /home/iiyatu/projects/python/xmuse
```

Impact:

- Platform lane execution used the isolated worktree, but chat-plane dispatch
  instructions were stale and could lead a provider to run verification from
  the control repository root.
- This is an authority mismatch between lane projection and dispatch prompt,
  not a lane execution success blocker for Loop 23g.

Fix:

- `ChatDispatchBridge` now accepts `lanes_path`.
- It resolves `execution_worktree` by matching the dispatch entry
  `resolution_id` against `feature_lanes.json`.
- `platform_runner` passes its active `lanes_path` into the bridge.

Focused validation:

```text
tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_auto_dispatches_gated_entry_through_execute_provider
tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer
```

Remaining gap:

- The full real groupchat-to-final-action chain has not yet been rerun after
  this fix. Treat it as focused local contract proof, not full runtime proof.

### F49. Loop 23 reached final-action hold but review evidence remains weak

Severity: local runtime proof with review-plane evidence gap.

Loop 23g lane state:

```text
lane=minimal_lane_package_boundary_pytest
status=awaiting_final_action
gate_passed=true
review_task.status=verdict_emitted
review_decision=merge
final_action_hold_id=final-74e460a0d061
final_actions.status=pending
```

Weak evidence fields:

```text
review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
review_evidence_refs=[]
chat_dispatch_queue.status=dispatched
```

Impact:

- The local runner reached the intended safe boundary: final-action hold, not
  auto-merge.
- The review verdict is useful local runtime evidence but must not be reported
  as GitHub review truth or merge truth.
- Empty review evidence refs make the result harder to audit after the fact.
- The chat dispatch queue state does not express final lane completion.

Recommended next change:

- Preserve feature identity into persistent review delivery.
- Require review verdicts to cite worker result, command list, diff or no-diff
  evidence, and lane artifact refs.
- Split chat dispatch queue handoff state from lane execution/final-action
  state in read models.

### F50. Execute gate parser missed real `response_type` / `verdict` shape

Severity: resolved local approval blocker.

Loop 23h2 produced a durable execute collaboration response with this shape:

```text
response_type=execute_feasibility_verdict
verdict=dispatchable
command=uv run pytest tests/xmuse/test_package_boundaries.py -q
proof_boundary=local runtime contract proof only
```

The first approval attempt failed:

```text
proposal_id=prop_45e0c3adc3ea4731abd6baa8b6b2e338
dispatch_gate_blocked=blocked_execute_not_confirmed
```

Impact:

- The gate was stricter than the real provider response grammar.
- The failure was fail-closed and did not create a resolution or lane.
- The durable execute response itself preserved the correct command and proof
  boundary.

Fix:

- `_execute_feasibility_verdict_confirmed()` now accepts `response_type` as an
  alias for `type`.
- It accepts string verdicts `dispatchable`, `feasible`, and `executable` as
  confirmation.
- It still requires a non-empty command, proof boundary, and summary/notes.

Validation:

```text
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_accepts_response_type_dispatchable_verdict tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_accepts_dispatchable_execute_verdict tests/xmuse/test_groupchat_collaboration_runtime.py::test_blocked_collaboration_gate_leaves_no_approval_side_effects -q
3 passed, 1 warning
```

Boundary:

- This is the second targeted patch on the execute gate parser family. If the
  same boundary fails again, stop patching and refactor the verdict grammar into
  an explicit structured parser/model.

### F51. Dispatch worktree routing is runtime-positive, but queue semantics still fail

Severity: resolved for lane-worker handoff semantics; downstream evidence gaps remain.

Loop 23h2 approval rerun reached:

```text
resolution_id=res_aff45ebed00b451980161d468493883a
lane=local-runtime-contract-proof-package-boundaries
lane.status=awaiting_final_action
lane.worktree=/tmp/xmuse-loop-23h2-dispatch-worktree-rerun-103026-exec
final_action_hold=final-d2d756e69af0
```

The chat dispatch request now carried the lane worktree:

```text
dispatch_message=msg_cea38e09176244c9869215583d8fe0cd
envelope.execution_worktree=/tmp/xmuse-loop-23h2-dispatch-worktree-rerun-103026-exec
content_has_exec_worktree=true
content_has_repo_root=false
```

Remaining negative evidence:

```text
chat_dispatch_queue.status=failed
failure_reason=Cannot reuse conversation participant ... existing registered session does not match requested role/agent
execute_chat_reply=DISPATCH_FAILED: this peer_chat_nudge turn is chat-only
```

Impact:

- The worktree authority mismatch from F48 is locally fixed by runtime
  evidence, not only focused tests.
- The chat dispatch queue remains a handoff/read-model surface, not final
  execution truth.
- Execute peer chat and platform lane execution still have overlapping but
  different semantics; the queue can fail while the platform lane worker
  succeeds to final-action hold.

Recommended next change:

- Keep chat dispatch queue as handoff/read-model evidence, not final execution
  truth.
- Preserve the platform lane worker as the execution authority until a separate
  dispatch executor contract exists.

Loop 23l update:

```text
runtime_root=.goal-runs/2026-06-18/loop-23l-review-callback-rerun-111555
chat_dispatch_queue.status=dispatched
provider_run_ref=lane_worker:runtime-contract-proof-package-boundaries
dispatch_evidence=dispatch_handoff:msg_89ae4bdc5624456987d3129f5818caea:feature_lanes:runtime-contract-proof-package-boundaries:pending
handoff.execution_worktree=/tmp/xmuse-loop-23l-review-callback-rerun-111555-exec
lane.status=awaiting_final_action
final_action_hold_id=final-33247a789f24
```

The queue no longer tries to execute through peer-chat nudge. It records a
lane-worker handoff and leaves execution/review truth with `feature_lanes.json`,
review plane artifacts, and final-action hold state.

### F52. Execute verdict producer drifted to `allowed_command`

Severity: resolved local approval blocker.

Loop 23i failure:

```text
execute_response.type=execute_feasibility_verdict
execute_response.allowed_command=uv run pytest tests/xmuse/test_package_boundaries.py -q
execute_response.proof_boundary missing
approval=400 dispatch_gate_blocked: blocked_execute_not_confirmed
```

Impact:

- The approval gate correctly failed closed.
- The producer prompt/tool description was too weak; it allowed a real Codex
  execute peer to invent `allowed_command`.

Fix:

- Execute role prompt, peer-chat prompt, Codex App transport prompt, and MCP
  tool description now require `command`, `proof_boundary`, and
  `execution_performed=false` when peer chat did not run the command.
- The gate was not weakened to accept missing proof boundaries.

Runtime proof:

```text
Loop 23l execute_response.command=uv run pytest tests/xmuse/test_package_boundaries.py -q
Loop 23l execute_response.proof_boundary=local runtime contract proof only
Loop 23l execute_response.execution_performed=false
approval=200
```

### F53. OpenCode review callback detection was too phrase-sensitive

Severity: resolved local collaboration blocker.

Observed failures:

```text
Loop 23j: review peer wrote ordinary chat; collaboration_runs.status=partial
Loop 23k: "Please respond on collaboration `collab_*` ..." still missed structured callback
```

Impact:

- The OpenCode peer produced useful review text, but it was not durable
  collaboration response truth.
- Architect callback and proposal emission remained blocked until review wrote
  through `chat_record_collaboration_response`.

Fix:

- OpenCode peer-chat prompts now switch to a structured callback contract for
  concrete `collab_*` requests that ask for collaboration response, durable
  response, respond, or review.
- The prompt includes recent transcript so exact commands and proof boundaries
  are preserved.
- The callback bridge persists both `chat_record_collaboration_response` and a
  concise groupchat acknowledgement.

Runtime proof:

```text
Loop 23l collaboration_runs.status=done
Loop 23l review_response=collab_resp_e61001ccdb664ec095374fa232e47503
Loop 23l proposal_id=prop_497a235bce924cad95a4f3dc922473cb
```

Boundary:

- This was the second regex-level repair on the OpenCode callback detection
  surface. If it fails again on natural phrasing, stop patching patterns and
  refactor to an explicit collaboration callback marker in inbox payloads.

### F54. Stdout-fallback review verdicts originally had empty evidence refs

Severity: resolved local evidence-quality gap; remaining fallback gaps are
explicit.

Loop 23l reached:

```text
human @architect
-> Codex/OpenCode durable collaboration
-> lane_graph proposal
-> human approval
-> lane-worker dispatch handoff
-> package-boundary pytest execution
-> review verdict
-> final-action hold
```

Evidence:

```text
feature_lanes.status=awaiting_final_action
required command=uv run pytest tests/xmuse/test_package_boundaries.py -q
required command result=16 passed
review_decision=merge
final_actions.status=pending
```

Remaining gap:

```text
review_evidence_refs=[]
review_fallback=stdout/structured
gate_profiles_missing still appears before review
```

Fix:

- Stdout-fallback merge/rework verdict ingestion now accepts and persists
  evidence refs.
- The fallback path derives refs from lane metadata, review task id, lane
  prompt ref, and gate report ref when present.
- `feature_lanes.json` lane metadata and `review_plane.json` verdicts now share
  the same deduped ref set.

Runtime proof:

```text
Loop 23m runtime_root=.goal-runs/2026-06-18/loop-23m-review-evidence-rerun-113240
lane=runtime_contract_proof_package_boundaries_pytest
lane.status=awaiting_final_action
review_verdict=verdict-merge-rtask_0c5e92d8b1b646169384919b596de850
final_action_hold=final-35ab7cbc5a2d
feature_lanes.review_evidence_refs=[
  "feature_lanes.json#lane=runtime_contract_proof_package_boundaries_pytest",
  "review_plane.json#task=rtask_0c5e92d8b1b646169384919b596de850",
  "logs/lane_prompts/runtime_contract_proof_package_boundaries_pytest.md"
]
review_plane.review_verdicts[0].evidence_refs=same set
```

Validation:

```text
uv run pytest tests/xmuse/test_opencode_persistent.py \
  tests/xmuse/test_peer_chat_scheduler.py::test_peer_chat_nudge_prompt_has_short_turn_contract \
  tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_writeback_and_explicit_handoff_tools \
  tests/xmuse/test_groupchat_collaboration_runtime.py \
  tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_platform_orchestrator.py::test_review_god_stdout_fallback_approves_when_mcp_status_missing \
  -q
67 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Remaining gaps after Loop 23m:

```text
review_fallback=stdout/structured
gate_profiles_missing still appears before review
docs/xmuse/production-closure-gap-ledger.md was absent at the time of this loop
GitHub review truth, merge truth, ready_to_merge, pr_merged, live MemoryOS,
full L8-L10 closure, full L1-L11 closure, overnight readiness, and natural
peer-GOD completion remain unclaimed
```

Boundary:

- Do not report this as GitHub review truth, merge truth, live MemoryOS, full
  L8-L10 closure, full L1-L11 closure, or overnight readiness.
- Treat it as local runtime proof that the current maximum accessible chain can
  reach a safe final-action hold.

Publication:

```text
PR #51 merged: https://github.com/iiyazu/Cross-Muse/pull/51
mergeCommit=6181bf187962888fa6aed117e7bbce1883fa9412
scope=stdout-fallback review evidence refs only
```

This is merge truth only for PR #51. It is not GitHub review truth and does not
upgrade the broader fullchain, MemoryOS, or natural peer-GOD claims.

### F55. OpenCode peer chat wrote groupchat text but not collaboration response truth

Severity: resolved local OpenCode callback blocker; published in PR #52.

Loop 24b ran from clean `origin/main` after PR #51:

```text
runtime_root=.goal-runs/2026-06-18/loop-24b-main-fullchain-rerun-115432
code_head=6181bf187962888fa6aed117e7bbce1883fa9412
conversation_id=conv_cf23d2af8d5e43b5a52976db26e3164b
collaboration_run=collab_d2e3b35a2af44f0f9e319706d8c98105
review_runtime=opencode
```

Observed failure:

```text
OpenCode message=msg_ccdf3d2b138e41fdbba8ff59a13110ad
OpenCode message envelope.writeback_path=opencode_callback_bridge
collaboration_runs.status=partial
collaboration_responses only contained @execute
proposals=[]
```

Impact:

- OpenCode produced durable groupchat text, but that was not enough to complete
  the formal collaboration run.
- The architect had no completed collaboration and did not emit a proposal.
- This blocked the chain before proposal approval and lane execution.

Fix:

- OpenCode peer-chat prompts now identify explicit `collab_*` collaboration
  response requests.
- The callback bridge records those responses through
  `chat_record_collaboration_response`.
- Structured JSON callbacks are supported.
- Natural-language replies to a collaboration-response inbox are also persisted
  as the formal collaboration response for that run, then posted as durable
  groupchat acknowledgement.

Runtime proof:

```text
Loop 24c runtime_root=.goal-runs/2026-06-18/loop-24c-opencode-callback-rerun-120420
collaboration_run=collab_642087f2c2c248a094fe247c6b49058b
collaboration_runs.status=done
execute_response=collab_resp_554b69dc8704484292456439ad3379ba
review_response=collab_resp_e5c45cdb9ac1429780562593c628475f
OpenCode message=msg_f70c36e1c45e4686bdc2795228da37ad
OpenCode envelope.callback_action=chat_record_collaboration_response
```

Validation:

```text
uv run pytest tests/xmuse/test_opencode_persistent.py -q
11 passed

uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Publication:

```text
PR #52 merged: https://github.com/iiyazu/Cross-Muse/pull/52
mergeCommit=995b165b82b31db390bfd0e739a1e58254ce269d
scope=OpenCode collaboration callback writeback only
```

Boundary:

- This is local runtime proof and GitHub merge truth for PR #52 only.
- It is not GitHub review truth.
- It is not full groupchat or fullchain completion.

### F56. Collaboration completion did not continue to architect proposal

Severity: resolved local collaboration-delivery blocker; published in PR #53.

Loop 24c reached:

```text
collaboration_runs.status=done
collaboration_responses contains both @execute and @review
proposals=[]
```

Impact:

- The Codex/OpenCode collaboration completed durably.
- The chain did not advance to the requested lane_graph proposal.
- Fullchain remains blocked before proposal approval, dispatch, execution, and
  review.

Fix:

- `PeerChatService.record_collaboration_response()` now resolves the
  collaboration callback target before storing the response.
- When the updated collaboration run reaches `done`, it emits a durable
  `collaboration_callback` message and inbox item for the callback target.
- The callback payload includes the completed collaboration run id, status, and
  formal responses.

Runtime proof:

```text
Loop 24d runtime_root=.goal-runs/2026-06-18/loop-24d-collaboration-done-callback-rerun-121850
collaboration_run=collab_7fb91c13f2024195a4f0a8b3ac9bb6d9
collaboration_runs.status=done
callback_inbox=inbox_18d1f52ef3b94fe0996ecd8ca76995e4
callback_inbox.item_type=collaboration_callback
callback_inbox.status=read
callback_inbox.responded_message_id=msg_3baf65f419794b07a5abff8776e3607b
proposal_id=prop_a6d8536283b94310bf6f7ff2887a1a7a
proposal.references=["collaboration:collab_7fb91c13f2024195a4f0a8b3ac9bb6d9"]
resolution_id=res_ed1f78065fa74c8a835ca8a42a21e4fb
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_groupchat_collaboration_runtime.py -q
51 passed, 1 warning

uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Publication:

```text
PR #53 merged: https://github.com/iiyazu/Cross-Muse/pull/53
mergeCommit=8dcb28eacce86f8a2457e15a1522a46407497605
scope=collaboration completion callback inbox only
```

Boundary:

- This is local runtime proof and GitHub merge truth for PR #53 only.
- It is not GitHub review truth.
- It is not full groupchat or fullchain completion.

### F57. Approved projected lane depends on execution worktree lifecycle

Severity: local candidate fix proven; not published because the active goal's
three-PR budget is already used.

Loop 24d moved past the collaboration/proposal/approval boundary and projected a
lane, then failed before lane execution:

```text
feature_id=runtime-contract-proof-package-boundaries
feature_lanes.status=exec_failed
failure_reason=execution_infra_unavailable
worker_worktree=/tmp/xmuse-loop-24d-collaboration-done-callback-rerun-121850-exec
worktree_exists=false
```

Loop 24e reran from latest `origin/main` after PR #53 with the execution git
worktree created before approval:

```text
runtime_root=.goal-runs/2026-06-18/loop-24e-main-after-pr53-rerun-123739
code_head=8dcb28eacce86f8a2457e15a1522a46407497605
execution_worktree=/tmp/xmuse-loop-24e-main-after-pr53-rerun-123739-exec
feature_lanes.status=awaiting_final_action
branch=runtime-contract-proof-package-boundaries
base_head_sha=8dcb28eacce86f8a2457e15a1522a46407497605
gate_passed=true
review_task.status=verdict_emitted
review_verdict.status=finalized
review_decision=merge
final_action_hold=final-bcb7f1e646d5
```

Execution proof:

```text
command=uv run pytest tests/xmuse/test_package_boundaries.py -q
result=exit 0; 16 passed in 2.84s
worktree status=clean
branch delta=HEAD == origin/main (8dcb28e)
```

The chat dispatch acknowledgement path still failed closed:

```text
chat_dispatch_queue.status=failed
failure_reason=Cannot reuse role='execute': existing live session does not match requested agent/worktree
```

Candidate fix:

- `PlatformOrchestrator` now keeps a code repository root separate from
  `XMUSE_ROOT`.
- `xmuse-platform-runner` assigns the real code root to the orchestrator after
  construction.
- `ensure_lane_worktree()` does not early-return when existing `worktree`
  metadata points to a missing path.
- Missing projected worktree paths are created before provider spawn.

Loop 24f reran with the execution worktree deliberately absent before approval:

```text
runtime_root=.goal-runs/2026-06-18/loop-24f-missing-worktree-create-rerun-125611
code_patch=.goal-runs/2026-06-18/loop-24f-missing-worktree-create-rerun-125611/code-diff.patch
execution_worktree=/tmp/xmuse-loop-24f-missing-worktree-create-rerun-125611-exec
execution_worktree_exists_before=false
feature_id=runtime-contract-proof-package-boundaries-f57
feature_lanes.status=awaiting_final_action
execution_worktree_exists_after=true
execution_worktree_branch=runtime-contract-proof-package-boundaries-f57
execution_worktree_head=8dcb28eacce86f8a2457e15a1522a46407497605
execution_worktree_status=clean
gate_passed=true
review_task.status=verdict_emitted
review_verdict.status=finalized
review_decision=merge
final_action_hold=final-ed27dfb3b8ab
```

Impact:

- The real chain now reaches durable proposal, review, human approval,
  projection, package-boundary pytest execution, review verdict, and
  final-action hold from the Codex/OpenCode groupchat.
- This is local runtime final-action-hold proof only.
- The 24d missing-worktree failure was reproduced as a target condition and the
  candidate fix created the missing execution worktree before provider spawn.
- The candidate fix is not GitHub CI truth and is not merged code.
- The chat dispatch queue still cannot acknowledge through an already-live
  `execute` peer when the requested worktree differs from the peer-chat session.
- MCP review verdicts in 24f still produced `review_evidence_refs=[]`.

Next direction:

- Publish the F57 worktree lifecycle patch as the next small PR only after the
  active goal's current PR budget resets or the operator authorizes another PR.
- Decide whether chat dispatch acknowledgement should reuse the peer-chat
  execute session as a pure acknowledgement, create a separate session, or stay
  advisory without trying to launch a provider.
- Treat chat dispatch acknowledgement as advisory unless it produces durable
  lane-worker evidence; it must not be execution authority.
- Treat MCP review evidence refs as a separate F58 candidate boundary; do not
  hide it behind the worktree lifecycle fix.

Forbidden claims preserved:

```text
No natural peer-GOD completion.
No full groupchat-to-completion chain.
No GitHub review truth.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F58. MCP review verdicts lacked evidence refs

Severity: local candidate fix proven; not published because the active goal's
three-PR budget is already used.

Loop 24f reached final-action hold, but MCP review status updates still wrote
empty review refs:

```text
review_evidence_refs=[]
```

Impact:

- The lane could reach `awaiting_final_action`, but the accepted review verdict
  did not cite the lane/review-plane authority path.
- This weakened review auditability for the MCP `update_lane_status` producer.
- It did not invalidate the execution command result, but it left review
  evidence below the desired local runtime proof boundary.

Candidate fix:

- MCP `update_lane_status` now normalizes reviewed/rejected status metadata with
  access to the lane id and `XMUSE_ROOT`.
- Accepted or rejected MCP review status updates derive evidence refs from:
  `feature_lanes.json#lane=<lane_id>`, the current review task,
  `prompt_ref`, optional gate report refs, explicit metadata refs, and existing
  lane refs.
- Review history entries now include the evidence refs used by the MCP status
  update.

Loop 24g reran the real Codex/OpenCode groupchat-to-final-action chain with the
candidate patch:

```text
runtime_root=.goal-runs/2026-06-18/loop-24g-mcp-review-evidence-rerun-131637
code_patch=.goal-runs/2026-06-18/loop-24g-mcp-review-evidence-rerun-131637/code-diff.patch
conversation_id=conv_b958eefa252a4223bcf5b3a8ddb53dc2
collaboration_run=collab_bb84ec146e2c455491ef4ca50518fcb0
proposal_id=prop_2b4872dd96cc4b1e918343f5c559e1fc
resolution_id=res_b08aa0ccbdac47c0bf88730a459fca7d
feature_id=runtime-contract-proof-package-boundaries-mcprefs
feature_lanes.status=awaiting_final_action
review_task.status=verdict_emitted
review_verdict.status=finalized
review_decision=merge
final_action_hold=final-6bc6a8753af2
```

MCP review evidence result:

```text
review_history[0].fallback=mcp
review_history[0].fallback_reason=update_lane_status
feature_lanes.review_evidence_refs=[
  "feature_lanes.json#lane=runtime-contract-proof-package-boundaries-mcprefs",
  "review_plane.json#task=rtask_def01f8904b64769a566f623432ddcf6",
  "logs/lane_prompts/runtime-contract-proof-package-boundaries-mcprefs.md"
]
review_plane.review_verdicts[0].evidence_refs=same set
```

Validation:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_mcp_status_change_callback \
  tests/xmuse/test_platform_orchestrator.py::test_mcp_reviewed_status_derives_review_evidence_refs \
  tests/xmuse/test_platform_orchestrator.py::test_mcp_reviewed_status_triggers_auto_merge \
  tests/xmuse/test_platform_orchestrator.py::test_review_god_stdout_fallback_approves_when_mcp_status_missing \
  tests/xmuse/test_package_boundaries.py \
  -q
-> 20 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Publication:

```text
local branch=codex/review-mcp-evidence-refs
path=/tmp/xmuse-review-mcp-evidence-refs
local commit=089f431 fix: derive mcp review evidence refs
PR opened=false
reason=active goal PR budget already used by PR #51, PR #52, and PR #53
```

Remaining gaps:

- The candidate is local only: no push, no GitHub CI, no merge truth.
- Execution GOD still used stdout fallback for execution completion in Loop
  24g.
- `gate_profiles_missing` still appeared before review.
- `chat_dispatch_queue.status=failed` remains on the advisory acknowledgement
  path because the live `execute` peer session does not match the lane worktree.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this
  loop. Current runs use the ledger as the gap index.

Forbidden claims preserved:

```text
No natural peer-GOD completion.
No full groupchat-to-completion chain.
No GitHub review truth.
No merge truth for F58.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F59. Execution one-shot fallback lacked durable evidence classification

Severity: local candidate fix proven; not published because the active goal's
three-PR budget is already used.

Loop 24g reached final-action hold, but execution completion still came through
one-shot process/stdout fallback. Before F59, the durable lane status did not
clearly classify that `executed` was runner-owned fallback rather than MCP
writeback.

Impact:

- The lane could reach `executed`, gate, review, and final-action hold.
- Consumers could not distinguish MCP execution writeback from runner-owned
  process-exit fallback by reading lane metadata alone.
- This risked overstating execution proof strength, even though the actual
  command output was preserved in spawn logs.

Candidate fix:

- `ExecuteResponse` now carries spawn prompt/stdout/stderr/result log paths
  from the subprocess transport back to the executor.
- When a one-shot execution worker exits 0 while the lane is still
  `dispatched`, the executor records:
  `execute_delivery_mode=one_shot_fallback`,
  `execute_fallback_reason=spawn_exit_without_mcp_status`,
  `execute_evidence_refs`, and `execute_result_artifact_ref`.
- If the worker has already committed `executed` via MCP, the runner does not
  overwrite that metadata with fallback classification.

Loop 24h reran the real Codex/OpenCode groupchat-to-final-action chain with the
candidate patch:

```text
runtime_root=.goal-runs/2026-06-18/loop-24h-execution-fallback-evidence-rerun-133546
code_patch=.goal-runs/2026-06-18/loop-24h-execution-fallback-evidence-rerun-133546/code-diff.patch
conversation_id=conv_306d9571cff2455da7e93ee07364bf81
collaboration_run=collab_b623d6be319449a79a0ba95ce7708880
proposal_id=prop_d087086f5a0b4e1ea20b503e33488728
resolution_id=res_4a6bdda35d35444ebe955a116b427730
feature_id=runtime-contract-proof-package-boundaries-f59
feature_lanes.status=awaiting_final_action
review_task.status=verdict_emitted
review_verdict.status=finalized
review_decision=merge
final_action_hold=final-a5acf1cd10bc
```

Execution fallback evidence result:

```text
execute_delivery_mode=one_shot_fallback
execute_fallback_reason=spawn_exit_without_mcp_status
execute_result_artifact_ref=logs/agent_spawns/runtime-contract-proof-package-boundaries-f59/20260618T054349Z.result.json
execute_evidence_refs=[
  "logs/agent_spawns/runtime-contract-proof-package-boundaries-f59/20260618T054349Z.result.json",
  "logs/agent_spawns/runtime-contract-proof-package-boundaries-f59/20260618T054349Z.stdout.log",
  "logs/agent_spawns/runtime-contract-proof-package-boundaries-f59/20260618T054349Z.stderr.log",
  "logs/agent_spawns/runtime-contract-proof-package-boundaries-f59/20260618T054349Z.prompt.md"
]
```

Execution proof:

```text
execution command=uv run pytest tests/xmuse/test_package_boundaries.py -q
execution result=16 passed in 2.80s
execution worktree status=clean
```

Validation:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_exit_zero_records_one_shot_fallback_evidence \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_preserves_mcp_committed_executed_metadata \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_timeout_marks_exec_failed \
  tests/xmuse/test_platform_orchestrator.py::test_execution_transport_receives_provider_invocation \
  tests/xmuse/test_package_boundaries.py \
  -q
-> 20 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Publication:

```text
local branch=codex/execution-fallback-evidence-refs
path=/tmp/xmuse-execution-fallback-evidence
local commit=37f734d fix: record execution fallback evidence refs
PR opened=false
reason=active goal PR budget already used by PR #51, PR #52, and PR #53
```

Remaining gaps:

- The candidate is local only: no push, no GitHub CI, no merge truth.
- This fix classifies execution fallback; it does not remove fallback or prove
  MCP execution writeback.
- Review GOD in 24h treated `logs/...` refs as execution-worktree-relative,
  while the actual spawn logs are under `XMUSE_ROOT`; evidence ref root
  semantics remain ambiguous for downstream consumers.
- `review_evidence_refs=[]` remains in 24h because this branch intentionally
  does not include the separate F58 patch.
- `gate_profiles_missing` still appeared before review.
- `chat_dispatch_queue.status=failed` remains on the advisory acknowledgement
  path because the live `execute` peer session does not match the lane worktree.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this
  loop. Current runs use the ledger as the gap index.

Forbidden claims preserved:

```text
No natural peer-GOD completion.
No full groupchat-to-completion chain.
No GitHub review truth.
No merge truth for F59.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### Integrated candidate status after F57-F59

Severity: local integration proof only; not a publication branch.

Loop 24i stacked the three current local candidate commits on `origin/main`:

```text
branch=codex/runtime-chain-integrated-candidates
path=/tmp/xmuse-runtime-chain-integrated-candidates
base_head=8dcb28eacce86f8a2457e15a1522a46407497605
commits=[
  "797fdf4 fix: create missing projected lane worktrees",
  "b0936ea fix: derive mcp review evidence refs",
  "1edd8a5 fix: record execution fallback evidence refs"
]
```

Focused validation before runtime:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_initializes_missing_isolated_worktree \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_creates_missing_projected_worktree_before_spawn \
  tests/xmuse/test_platform_orchestrator.py::test_mcp_reviewed_status_derives_review_evidence_refs \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_exit_zero_records_one_shot_fallback_evidence \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_preserves_mcp_committed_executed_metadata \
  tests/xmuse/test_platform_orchestrator.py::test_review_god_stdout_fallback_approves_when_mcp_status_missing \
  tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer \
  tests/xmuse/test_package_boundaries.py \
  -q
-> 23 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Loop 24i runtime result:

```text
runtime_root=.goal-runs/2026-06-18/loop-24i-integrated-candidates-rerun-135131
conversation_id=conv_ab5f4a293a574522b4a1ede4724da2f0
collaboration_run=collab_64883dc97d594c9c9413033f368b103d
proposal_id=prop_0c9da9e97a1141ee805093d2ec2b4279
resolution_id=res_c0dbe7916f0644f4b9b971d6048a1139
feature_id=runtime-contract-proof-package-boundaries-24i
feature_lanes.status=awaiting_final_action
execution_worktree_exists_after=true
execution_worktree_branch=runtime-contract-proof-package-boundaries-24i
execution_worktree_status=clean
gate_passed=true
review_decision=merge
final_action_hold=final-c441cfeac410
```

Combined positive evidence:

- F57: the deliberately missing execution worktree path was created before lane
  execution.
- F58: MCP review status produced non-empty `review_evidence_refs` in both
  `feature_lanes.json` and `review_plane.json`.
- F59: one-shot execution fallback was classified with
  `execute_delivery_mode=one_shot_fallback`,
  `execute_fallback_reason=spawn_exit_without_mcp_status`, and spawn artifact
  refs.

Remaining gaps:

- Integration branch is local only and must not be opened as a PR.
- The three fixes were later split into small PRs #57, #58, and #59 after
  operator PR budget approval, then squash merged after exact-head required
  checks passed. They still must not be treated as GitHub review truth or broad
  merge truth beyond those exact PR merge facts.
- Execution fallback remains fallback; it is classified, not removed.
- `chat_dispatch_queue.status=failed` remains due live `execute` session /
  lane worktree mismatch.
- `gate_profiles_missing` still appears before review.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this
  loop. Current runs use the ledger as the gap index.

Forbidden claims preserved:

```text
No natural peer-GOD completion.
No full groupchat-to-completion chain.
No GitHub review truth.
No merge truth for the integrated branch.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F60. Chat dispatch queue now records lane-worker handoff instead of peer execution truth

Severity: local candidate fix proven for the dispatch acknowledgement boundary;
not published in this record.

Loop 24j reran the real Codex/OpenCode groupchat path:

```text
runtime_root=.goal-runs/2026-06-18/loop-24j-dispatch-handoff-rerun-141159
conversation_id=conv_16e3e6d438e24375a8eec4caf93ce97a
collaboration_run=collab_52f670cbbb444a6fb273380acbe8e65a
proposal_id=prop_a3e043708f9d43b4a36837fece9a9d28
resolution_id=res_a39480c16efc4225b0c0f47fc0dc5799
feature_id=loop24j-dispatch-handoff-proof
```

Positive evidence:

```text
collaboration_runs.status=done
proposal.status=accepted
resolution.status=approved
chat_dispatch_queue.status=dispatched
provider_run_ref=lane_worker:loop24j-dispatch-handoff-proof
dispatch_evidence=dispatch_handoff:msg_047304b5d3994aeea2f72b8fc3cc0401:feature_lanes:loop24j-dispatch-handoff-proof:pending
dispatch_handoff.envelope.lane_worker_authority=feature_lanes
dispatch_handoff.envelope.execution_worktree=/tmp/xmuse-loop-24j-dispatch-handoff-rerun-141159-exec
```

Impact:

- The chat-plane dispatch queue no longer needs to claim that peer-chat execute
  performed lane execution.
- The durable handoff message identifies `feature_lanes` as the lane-worker
  authority and carries the projected execution worktree.
- This closes the earlier semantic mismatch where a peer-chat nudge was treated
  like execution authority.

Remaining blocker from the same run:

```text
feature_lanes.status=exec_failed
failure_layer=coordinator
failure_reason=execution_infra_unavailable
runner_error=FileNotFoundError for /tmp/xmuse-loop-24j-dispatch-handoff-rerun-141159-exec
```

Next direction:

- Keep the lane-worker handoff model.
- Treat chat dispatch as acknowledgement/projection evidence, not execution
  authority.
- Address projected execution worktree lifecycle as a separate boundary.

Forbidden claims preserved:

```text
No full groupchat-to-completion chain.
No GitHub review truth.
No merge truth for F60.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F61. Runtime probes must not reference dirty-control-worktree-only tests

Severity: operator-safety and proof-boundary issue.

Loop 24k reran the chain after the local projected-worktree lifecycle fix:

```text
runtime_root=.goal-runs/2026-06-18/loop-24k-dispatch-worktree-rerun-142634
conversation_id=conv_5b385e226ac84d36a62d4be94c4e59ee
collaboration_run=collab_e3ceb0df973c47f18d93559c5c7fd87e
proposal_id=prop_4785cb40b0a84c95801e374750ad1df8
resolution_id=res_473438e9b37c4e9eac9c5d7c8b72652c
feature_id=loop24k-dispatch-worktree-proof
```

Positive evidence:

```text
chat_dispatch_queue.status=dispatched
provider_run_ref=lane_worker:loop24k-dispatch-worktree-proof
dispatch_evidence=dispatch_handoff:msg_d7e26ee9d31944f0a609a49ef6f0be2a:feature_lanes:loop24k-dispatch-worktree-proof:pending
execution_worktree_exists_after=true
execution_worktree_branch=loop24k-dispatch-worktree-proof
execution_worktree_head=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
execution_worktree_status=clean
gate_passed=true
```

Negative evidence:

```text
feature_lanes.status=failed
retry_count=2
review_decision=rework
pytest_exit_code=4
changed_files=none
```

The isolated execution worktree did not contain:

```text
tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_creates_missing_projected_worktree_before_spawn
tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_records_lane_worker_handoff_without_peer_nudge
```

Those tests existed only in the dirty control worktree, not in committed HEAD
`110dd47`, which was the base of the isolated lane worktree. The lane
instruction also forbade editing files, so the worker could not create the
missing tests and correctly reported no changed files.

Impact:

- Loop 24k proves the local worktree lifecycle candidate can create the missing
  projected execution worktree before provider spawn.
- Loop 24k does not prove the lane's verification command passes.
- Dirty control worktree tests cannot be used as isolated lane proof unless the
  candidate is first committed/imported into the lane base or the lane command
  references tests available at that base.

Additional operator-safety note:

```text
child-worker stderr read the local superpowers using-superpowers SKILL.md
despite the xmuse child-worker automation override. The worker still preserved
the lane no-edit boundary and reported changed_files=none.
```

Next direction:

- For the next real-chain probe, either use a verification command already
  present at the isolated worktree base, or commit/import the candidate patch
  into a dedicated branch before asking a lane to verify candidate-only tests.
- Keep `--no-auto-merge` as the default for runtime probes.
- Treat child-worker skill leakage as an operator-safety item under the
  anti-superpowers-abuse policy if it repeats or affects lane behavior.

Forbidden claims preserved:

```text
No full groupchat-to-completion chain from Loop 24k.
No GitHub review truth.
No merge truth for F61.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F62. Persistent OpenCode review GOD reaches local final-action hold

Severity: local runtime capability proven with explicit proof limits.

Loop 24l first reran the committed-base package-boundary command without
`--persistent-review-god`:

```text
runtime_root=.goal-runs/2026-06-18/loop-24l-package-boundary-final-hold-145243
conversation_id=conv_6bafd28c1b1740399496aa62594a13d8
feature_id=loop24l-package-boundary-final-hold
feature_lanes.status=gate_failed
failure_layer=review
failure_reason=required_review_peer_unavailable
peer_delivery_mode=required_peer_failed
peer_degraded_reason=session_layer_unavailable
worker result=16 passed in 2.79s
changed_files=none
```

Loop 24m reran the same boundary with persistent review enabled:

```text
runtime_root=.goal-runs/2026-06-18/loop-24m-persistent-review-final-hold-150335
conversation_id=conv_53162974ea6345c39c0c0f034d4eee1d
feature_id=loop24m-persistent-review-final-hold
feature_lanes.status=awaiting_final_action
gate_passed=true
review_delivery_mode=persistent
peer_delivery_mode=configured_peer
review_peer_id=part_a42dc7bdf742471789f4d7d6116ff238
review_runtime_requested=opencode
review_verdict.decision=merge
final_action_hold_id=final-2d5644ebe432
final_actions.status=pending
```

Impact:

- The real chain can now reach a safe local final-action hold through durable
  groupchat, human approval, lane-worker handoff, isolated execution, and a
  configured OpenCode review peer.
- The review-session boundary from 24l is addressed by running the platform
  with persistent review GOD enabled.
- The result remains local runtime proof only. `--no-auto-merge` preserved the
  final-action hold and no merge truth was produced.

Remaining gaps:

- Review summary still reports `MCP unavailable; stdout fallback`.
- `review_evidence_refs=[]` remains in the review verdict.
- `gate_profiles_missing` still appears before review.
- Provider selection read model still records a `codex.review` policy
  selection even though the lane records configured OpenCode peer delivery.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this loop.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

### F63. Proposal emission is not synchronized with collaboration completion

Severity: authority-time and product-correctness issue.

Loop 24m produced useful local runtime proof, but it also exposed a proposal
ordering problem:

```text
collaboration_run=collab_d9363769fcd24b1daf9dc11c0b497f70
first_proposal=prop_22ef639d2d1c484a8a0c02510aac0124
first_proposal.created_at=2026-06-18T07:07:35Z
execute_response.created_at=2026-06-18T07:08:35Z
review_response.created_at=2026-06-18T07:09:28Z
first_proposal.status=accepted
accepted_resolution=res_2a8e75b024694270b294f9e57212faef
second_proposal=prop_4ba2287b59ba409084e8b1fea17f5271
second_proposal.created_at=2026-06-18T07:11:20Z
second_proposal.status=open
```

The architect emitted the first lane-graph proposal before the execute and
review collaboration responses were done. After the collaboration callback, it
emitted a second proposal that remained open. The human-approved resolution was
derived from the first proposal and still carried manual-gap wording for
pending peer confirmations, even though the peers later responded.

Impact:

- A proposal can be reviewed and accepted from stale collaboration state.
- The groupchat can leave a second open proposal for essentially the same
  demand.
- Human approval can proceed after collaboration completion, but the accepted
  proposal content may not reflect the final collaboration evidence.

Next direction:

- Make lane-graph proposal emission wait for required collaboration targets to
  reach `done`, or mark pre-callback proposals as stale once the callback
  emits a newer proposal.
- Ensure approval uses the latest durable proposal whose collaboration
  references are complete.
- Preserve early proposals as history, but do not let them be the default
  dispatch authority when a newer completed-collaboration proposal exists.

Forbidden claims preserved:

```text
No natural peer-GOD completion.
No production-ready groupchat claim.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 or L1-L11 closure.
No overnight readiness.
```

24p update:

```text
runtime_root=.goal-runs/2026-06-18/loop-24p-uncontaminated-collab-rerun-154255
collaboration_run=collab_b332d2529a974517b2a0bb4eaa86fbf0
proposal_id=prop_f5a7803eedf84f01910ab110293e1ab2
proposal.created_at=2026-06-18T07:48:32.055077Z
collaboration_done_at=2026-06-18T07:47:18.533898Z
```

The clean 24p proposal was emitted after the collaboration run reached `done`.
The stale-proposal guard did not block it, and no duplicate open proposal was
left for the same collaboration reference in that run.

### F64. Collaboration run ids must be tool-created authority, not chat text

Severity: authority and product-correctness issue.

Loop 24n exposed that a real provider can invent a plausible collaboration run
id when prompted to "create or reference" a collaboration run:

```text
runtime_root=.goal-runs/2026-06-18/loop-24n-proposal-freshness-rerun-152915
invented_run_id=loop24n-proposal-freshness-final-hold-20260618T0732Z
collaboration_runs=[]
execute_writeback=unknown_collaboration_run
proposal=None
```

Impact:

- Chat text cannot be treated as collaboration authority.
- A valid collaboration reference must point to a durable row returned by
  `chat_create_collaboration_request`.
- Downstream proposal and approval gates should fail closed on unknown
  collaboration refs.

Targeted change:

- Peer scheduler, Codex persistent, Codex app transport, and MCP tool
  descriptions now require `chat_create_collaboration_request` first when no
  durable `collab_*` run id is present.
- Tool instructions now say to use only the returned run id and never invent or
  guess a run id.

Positive follow-up evidence:

```text
Loop 24o created collab_2dad0c5189324501bdbb3e9cad8d2728
Loop 24p created collab_b332d2529a974517b2a0bb4eaa86fbf0
```

Loop 24o was harness-contaminated by direct `@execute`/`@review` mentions, so
it is partial evidence only. Loop 24p was clean: the human mentioned only
`@architect`, and the architect created the durable collaboration run before
mentioning execute and review.

Remaining gap:

- The prompt fix reduces this failure, but the authority remains the durable
  store and approval gate, not provider compliance.

Forbidden claims preserved:

```text
No production-ready groupchat claim.
No GitHub review truth.
No merge truth.
No live MemoryOS.
No full closure claim.
```

### F65. Execute-verdict parser was too narrow for provider-expanded positives

Severity: local approval-gate correctness issue.

Loop 24p reached a real collaboration-backed proposal, but the first human
approval attempt failed:

```text
proposal_id=prop_f5a7803eedf84f01910ab110293e1ab2
approval=400 dispatch_gate_blocked: blocked_execute_not_confirmed
```

The durable execute response was structured but used a provider-expanded
positive verdict:

```json
{
  "type": "execute_feasibility_verdict",
  "verdict": "dispatchable_for_later_lane_execution_worktree_pending_human_approval",
  "command": "uv run pytest tests/xmuse/test_package_boundaries.py -q",
  "proof_boundary": "local runtime proof only",
  "execution_performed": false
}
```

Impact:

- Real providers may return semantically correct positive verdicts that are
  more specific than a fixed enum.
- The gate should remain strict about required structure while tolerating
  positive dispatchability tokens.
- Negative or blocked variants must still fail closed.

Targeted change:

- `_execute_feasibility_verdict_confirmed()` now recognizes positive
  dispatchability tokens inside expanded `verdict` text.
- It rejects negative tokens such as `not`, `blocked`, `deny`, `failed`,
  `reject`, and `unsafe`.
- Peer prompts and MCP descriptions now request exact
  `verdict="dispatchable"` for positive judgments.

Focused validation:

```text
test_proposal_approval_accepts_provider_expanded_dispatchable_verdict -> pass
test_proposal_approval_rejects_negative_expanded_execute_verdict -> pass
test_scheduler_claims_and_nudges_oldest_item -> pass
ruff focused files -> pass
```

Positive follow-up evidence from the same durable 24p proposal after restarting
the Chat API:

```text
resolution_id=res_90ae9022b1244d06bb6bfabf47e1c686
dispatch_gate_event=allowed
execute_confirmed=1
proposal.status=accepted
chat_dispatch_queue.status=dispatched
```

Remaining gap:

- The parser remains a local runtime gate. It is not GitHub review truth, merge
  truth, or proof of provider semantic reliability across broad tasks.

### F66. Clean groupchat-to-final-action-hold local slice is now reachable

Severity: positive capability finding with explicit proof boundary.

Loop 24p produced a clean local runtime chain:

```text
human @architect intake
-> architect-created durable collaboration run
-> execute/review peer collaboration responses
-> fresh lane_graph proposal
-> manual human approval through Chat API
-> dispatch queue handoff to lane worker
-> isolated lane command
-> persistent OpenCode review
-> awaiting_final_action
```

Key evidence:

```text
runtime_root=.goal-runs/2026-06-18/loop-24p-uncontaminated-collab-rerun-154255
conversation_id=conv_f8db8697ae324c799b85dbfae30173ff
collaboration_run=collab_b332d2529a974517b2a0bb4eaa86fbf0
proposal_id=prop_f5a7803eedf84f01910ab110293e1ab2
resolution_id=res_90ae9022b1244d06bb6bfabf47e1c686
feature_id=loop24p-uncontaminated-final-hold
worker_stdout="16 passed in 2.77s"
changed_files=none
review_runtime_requested=opencode
review_decision=merge
feature_lanes.status=awaiting_final_action
final_action_hold_id=final-becb84435f3e
```

This is the strongest current local runtime evidence for the intended GOD
groupchat shape. It does not prove production readiness.

Remaining gaps:

- Review verdict still has `review_evidence_refs=[]`.
- The execution worker reported MCP unavailable and used stdout fallback.
- No GitHub checks, GitHub review, merge, or live deployment truth was
  produced.
- The slice used a bounded package-boundary command, not a broad real feature
  implementation.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this loop.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F116. Timeout-after-durable-writeback is repaired in PR #61 candidate

Severity: scheduler observability and control-flow fix.

Loop 25z9 exercised the exact condition from F78 on candidate branch
`codex/peer-timeout-after-writeback`:

```text
conversation=conv_e38bb4ffc6d54435b3e414a49959bcad
architect inbox=inbox_4e2e0e9d2bf14df3b6d5468f2fe55910
responded_message_id=msg_e3e9cb71cbc84425a1432ff67aec75cd
delivery_mode=mcp_writeback
degraded_reason=peer_response_timeout_after_writeback
operator_nudge_used=false
result=awaiting_final_action
```

Impact:

- A provider turn that times out after a real durable MCP writeback is no
  longer misclassified as `failed / peer_response_timeout`.
- The scheduler aborts the still-running provider session, finishes the stream
  as `done`, and preserves durable message truth as the stronger authority.
- This is candidate-branch local runtime proof only.

Publication:

```text
PR #61=https://github.com/iiyazu/Cross-Muse/pull/61
head=d85d88d38c56e7be8b59cc6e5872ad5656f895dd
base=main
Actions run 27781274986=completed success
mergeStateStatus=CLEAN after Actions success
reviewDecision empty
mergedAt=2026-06-18T18:41:56Z
merge_commit=ec9a755132f117ee9b372513fbcb7420edb85b58
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_package_boundaries.py -q
-> 30 passed
uv run ruff check .
-> pass
git diff --check
test ! -e xmuse/__init__.py
-> pass
```

Required next behavior:

- Preserve the distinction between GitHub check success and GitHub review
  truth.
- Keep production-ready groupchat, GitHub review truth, merge truth, full
  closure, live MemoryOS, and overnight readiness forbidden.

### F117. Execute session reuse can still fail inside a successful groupchat run

Severity: peer session lifecycle reliability gap.

Loop 25z9 reached final-action hold, but one early execute collaboration inbox
recorded:

```text
target_role=execute
status=failed
failure_reason=Cannot reuse role='execute': existing live session does not match requested agent/worktree
```

The same run later produced a successful dispatch acknowledgement:

```text
dispatch_queue.status=dispatched
dispatch_evidence=mcp_writeback:inbox_9cfc981b443346c48b34a2d1d87caa57
lane.status=awaiting_final_action
```

Impact:

- The full chain can recover, but peer session reuse is still not reliable
  enough for production-ready natural groupchat.
- Do not treat Loop 25z9 as proof that all peer inbox delivery paths are
  stable.

Required next behavior:

- Isolate role/session reuse authority before broadening groupchat scope.
- Fix this in a separate small PR if it requires code changes; do not expand
  PR #61.

Loop 25z10b confirmed the same dispatch-session lifecycle gap after PR #61 was
merged:

```text
source_head=ec9a755132f117ee9b372513fbcb7420edb85b58
dispatch_queue.status=failed
failure_reason=Cannot reuse role='execute': existing live session does not match requested agent/worktree
lane.status=awaiting_final_action
```

The durable collaboration execute inbox itself succeeded, so the failure is in
the dispatch queue's provider-session reuse path, not in the initial
collaboration response path.

Loop 25z11 rebuilt this as a separate dispatch-session candidate:

```text
branch=codex/dispatch-bridge-peer-worktree
commit=42db27ccce013026746f3fbd56cb2a75981466db
dispatch_queue.status=dispatched
dispatch_evidence=mcp_writeback:inbox_03492d6f6c044219b50ef7dfb52cc0a6
failure_reason=null
lane.status=awaiting_final_action
PR #62=https://github.com/iiyazu/Cross-Muse/pull/62
```

PR #62 later received server success and was merged. The merge fact covers only
PR #62 head `42db27ccce013026746f3fbd56cb2a75981466db` and merge commit
`8c9966d658623714648058074618f80599efb0fc`; no GitHub review truth is claimed.

### F120. Dispatch bridge used the repo root instead of peer_chat_worktree

Severity: peer session lifecycle fix candidate.

Observed failure:

```text
Loop 25z10b dispatch_queue.status=failed
failure_reason=Cannot reuse role='execute': existing live session does not match requested agent/worktree
```

Root cause:

- The peer chat scheduler constructed Codex/OpenCode peer sessions in
  `peer_chat_worktree`.
- `ChatDispatchBridge` was constructed with repo `ROOT`.
- Dispatch is a chat-plane acknowledgement and should reuse the peer chat
  session identity, not switch the execute participant to a repo-root
  worktree.

Candidate result:

```text
Loop 25z11 dispatch_queue.status=dispatched
dispatch_evidence=mcp_writeback:inbox_03492d6f6c044219b50ef7dfb52cc0a6
provider_run_ref=peer_ack:execute:part_1fda8d2c2f20471e8a92e5fa050d32fb
result=awaiting_final_action
```

Publication:

```text
PR #62=https://github.com/iiyazu/Cross-Muse/pull/62
head=42db27ccce013026746f3fbd56cb2a75981466db
base=main
Actions run 27783134156=success before merge
jobs=quality-gates, contract-smoke-gates, real-runtime-integration-gate
reviewDecision=
state=MERGED
mergedAt=2026-06-18T19:11:33Z
merge_commit=8c9966d658623714648058074618f80599efb0fc
```

Remaining gaps:

- Review evidence refs remain empty.
- Gate profiles remain missing.
- This does not prove production-ready groupchat.

Post-merge confirmation:

```text
Loop 25z12 source_head=8c9966d658623714648058074618f80599efb0fc
chat_dispatch_queue.status=dispatched
dispatch_evidence=mcp_writeback:inbox_96cfbd027996488886bc41555ce0df31
failure_reason=null
lane.status=awaiting_final_action
operator_nudge_used=false
```

### F118. Post-PR61 main reaches final-action hold without operator nudge

Severity: positive runtime proof with preserved manual gaps.

Loop 25z10b reran from merge commit
`ec9a755132f117ee9b372513fbcb7420edb85b58`:

```text
conversation=conv_d6e5920e214b4668b78979ab13555632
collaboration=collab_cbceda4260fc4fafbe338a00b57959fa
proposal=prop_deed51e60eb344e1855860bce80c3310
resolution=res_53f80076260149b496acfc20493be325
feature_id=loop25z10b_post_pr61_main_fullchain
operator_nudge_used=false
result=awaiting_final_action
final_action_hold_id=final-6978d6b6a743
```

Positive evidence:

- Human message created only the architect inbox; execute and review were
  reached by durable collaboration handoff.
- Codex architect, Codex execute, and OpenCode review wrote durable MCP
  responses.
- Collaboration reached `done`, architect emitted a proposal, approval
  projected a lane, execution reached gate, configured OpenCode review emitted
  a finalized merge verdict, and the lane stopped at no-auto-merge final-action
  hold.
- Peer latency traces for the observed chat turns recorded
  `delivery_mode=mcp_writeback` with no degraded reason.

Manual gaps:

- `chat_dispatch_queue.status=failed` for execute dispatch session reuse.
- `review_evidence_refs=[]` even though `review_plane.gate_report_ref` exists.
- `gate_profiles_missing` still caused fail-open gate behavior.
- This is one bounded no-edit package-boundary lane, not broad coding-task
  completion or production readiness.

### F119. Review verdict evidence refs remain empty after configured peer review

Severity: review evidence integrity gap.

Loop 25z10b produced a configured OpenCode review verdict:

```text
peer_delivery_mode=configured_peer
persistent_review_identity=configured:part_57168c28b2bb46939ca0bf269dd12f59
review_decision=merge
review_verdict.status=finalized
review_plane.gate_report_ref=logs/gates/loop25z10b_post_pr61_main_fullchain/report.json
review_evidence_refs=[]
```

Impact:

- The review task knows a gate report ref, and the reviewer summary references
  worker output and clean worktree state, but the finalized verdict still lacks
  durable evidence refs.
- Do not treat this as production-grade independent review evidence.

Required next behavior:

- Use the real review path to determine whether evidence refs are missing in
  the prompt, provider output parser, verdict writer, or lane projection.
- Fix in a review-evidence scoped PR only; do not mix with dispatch session
  reuse.

### F121. Post-PR62 review still self-verifies instead of citing execution evidence

Severity: review evidence integrity gap.

Loop 25z12 reran from PR #62 merge commit
`8c9966d658623714648058074618f80599efb0fc` and confirmed the dispatch bridge
fix on main:

```text
chat_dispatch_queue.status=dispatched
dispatch_evidence=mcp_writeback:inbox_96cfbd027996488886bc41555ce0df31
lane.status=awaiting_final_action
peer_delivery_mode=configured_peer
persistent_review_identity=configured:part_2c2351d5b9134f5f999e9080eb105e68
review_decision=merge
review_plane.gate_report_ref=logs/gates/loop25z12_post_pr62_main_fullchain/report.json
review_evidence_refs=[]
```

Negative evidence:

- The review peer reported that the lane had no execution evidence yet.
- The review peer then ran the package-boundary test itself and emitted a merge
  verdict.
- The finalized verdict still recorded `review_evidence_refs=[]`.

Impact:

- The platform can reach no-auto-merge final-action hold after PR #62 without
  operator nudge, but review proof remains weak because review is not citing
  durable worker/gate artifacts.
- The next small implementation boundary is review evidence propagation, not
  broader groupchat scope.

### F122. Natural groupchat can regress to peer_no_inbox_side_effect

Severity: groupchat reliability blocker.

Loop 25z13c and 25z13d attempted the same natural entry shape as the successful
post-PR62 run: human message only addressed `@architect`, with execution and
review peers expected to be reached by durable collaboration tools.

Observed:

```text
Loop 25z13c conversation=conv_7198521581f741438870bbfbce0a5318
architect inbox status=failed
failure_reason=peer_no_inbox_side_effect
nudge_count=3
stream.status=done
proposal count=0
```

```text
Loop 25z13d architect inbox status=failed
failure_reason=peer_no_inbox_side_effect
nudge_count=3
proposal count=0
```

Impact:

- The architect peer produced stream text but no MCP writeback side effect, so
  the scheduler failed the inbox and no proposal existed to approve.
- This blocks the full natural groupchat chain before lane execution/review.
- Do not count these loops as review-evidence proof.

### F123. PR #63 fixes evidence propagation but runtime is blocked before the patched path

Severity: scoped fix with unresolved runtime blocker.

PR #63:

```text
branch=codex/persistent-review-evidence-refs
commit=6b6837129d5a65e5f2d24b4d2c5ad4f63568da7a
PR=https://github.com/iiyazu/Cross-Muse/pull/63
state=MERGED
Actions run 27785122877=success before merge
merge_commit=3fbbb5e083ac34995cbeda23a4edabaa8004fe5e
reviewDecision=
```

Local validation:

```text
persistent_review_delivery focused test=4 passed
orchestrator focused review tests=4 passed
focused publish pytest including package boundaries=22 passed
ruff=passed
git diff --check=passed
test ! -e xmuse/__init__.py=passed
```

Runtime boundary:

```text
Loop 25z13f lane.status=gate_failed
gate_passed=true
failure_reason=review_peer_delivery_failed
peer_delivery_mode=required_peer_failed
peer_degraded_reason=review_peer_no_verdict
review_verdicts=[]
```

Impact:

- The patch has contract/local proof that persistent review accept paths carry
  evidence refs into lane metadata and verdict ingestion.
- It does not yet have runtime success proof because configured OpenCode review
  did not emit a parseable verdict in Loop 25z13f.
- The next implementation boundary is review peer result/verdict delivery, not
  more evidence propagation code in PR #63.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth beyond exact merged PR server facts already recorded.
No ready_to_merge.
No pr_merged beyond exact merged PR server facts already recorded.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F70. Post-PR60 main reaches final-action hold, but natural groupchat still needs reliability work

Severity: mixed positive runtime proof plus remaining groupchat reliability gap.

GitHub server facts for PR #60:

```text
head=93d690efc64f92af639ac5df7451f903491aee0f
CI=xmuse CI completed success, run 27779712756
jobs=quality-gates, contract-smoke-gates, real-runtime-integration-gate
merge_commit=db5b7dfa10608d74b01f56447db75b63caaeaf60
merged_at=2026-06-18T18:10:33Z
```

Loop 25z8 reran from post-merge `origin/main`:

```text
source_head=db5b7dfa10608d74b01f56447db75b63caaeaf60
runtime_root=/tmp/xmuse-main-after-pr60-fullchain/.goal-runs/2026-06-19/loop-25z8-post-pr60-main-fullchain-021230
conversation_id=conv_ff267b09367e4ffeb3f7ec468cefa52a
collaboration_run=collab_d5fa442a7089410fb0bc240afdda5323
proposal_id=prop_ead66f338fd94867933bfadd402f5d25
resolution_id=res_235c0ebbcb3a46cd964019806dbc2650
feature_lanes.status=awaiting_final_action
peer_delivery_mode=configured_peer
peer_degraded_reason=null
review_decision=merge
final_action_hold_id=final-fb5833c722b3
```

Positive impact:

- The PR #60 fix is now server-merged into `main`.
- Post-merge main no longer reproduces the
  `peer_degraded_reason=session_layer_unavailable` failure at configured
  OpenCode platform review.
- The projected execution worktree used main head `db5b7df`, and the lane
  reached no-auto-merge final-action hold.

Remaining reliability gap:

```text
first architect turn timed out after writing a message:
delivery_mode=failed
degraded_reason=peer_response_timeout

operator nudge was required before the run reached proposal approval
review_evidence_refs=[]
review MCP tools unavailable; stdout fallback used
gate_profiles_missing remained
```

Impact:

- Review handoff wiring is no longer the current blocker on main.
- The next implementation domain is natural groupchat reliability: architect
  must reliably create the durable collaboration/proposal without timeout or
  operator nudge.
- Post-merge final-action hold is local runtime proof only, not production
  readiness and not GitHub review truth.

Forbidden claims preserved:

```text
No GitHub review truth.
No ready_to_merge.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F69. Peer-chat session layer must be wired into platform review handoff

Severity: current main fullchain blocker; candidate fix validated locally.

Loop 25z6 on post-PR59 `origin/main` reached gate, then failed before
configured OpenCode platform review:

```text
feature_lanes.status=gate_failed
failure_layer=review
failure_reason=required_review_peer_unavailable
peer_delivery_mode=required_peer_failed
peer_degraded_reason=session_layer_unavailable
review_plane.review_verdicts=[]
```

Root cause in implementation:

- `xmuse/platform_runner.py` constructed `PlatformOrchestrator` before the
  peer-chat `GodSessionLayer` was created.
- The orchestrator therefore received `review_god_session_layer=None` even
  though `--peer-chat` later created a live session layer for the same durable
  groupchat.
- Configured OpenCode review could not route to the review peer at the platform
  review stage.

Candidate fix:

```text
branch/worktree=/tmp/xmuse-review-session-layer-main-candidate
files=xmuse/platform_runner.py, tests/xmuse/test_platform_runner.py
change=construct PlatformOrchestrator after peer-chat layer setup and pass the
peer GOD layer as review_god_session_layer when no explicit review layer exists
```

Loop 25z7c reran the maximum-accessible chain with explicit OpenCode review:

```text
runtime_root=/tmp/xmuse-review-session-layer-main-candidate/.goal-runs/2026-06-19/loop-25z7c-review-session-layer-candidate-015853
conversation_id=conv_21380e00c72148f48ce8b3c217a0c49b
collaboration_run=collab_9610f35b62b749a3bd22dc1ff9e725d9
proposal_id=prop_3c71e409630b4008aa0ffba5307431b9
resolution_id=res_f3e4566797b94fcfbd68dd141adfd7f6
feature_lanes.status=awaiting_final_action
peer_delivery_mode=configured_peer
peer_degraded_reason=null
review_decision=merge
final_action_hold_id=final-bc45596d37e1
```

Positive impact:

- The specific `session_layer_unavailable` review handoff blocker is closed for
  the candidate branch.
- Real Codex architect, Codex execute, and OpenCode review peers all wrote
  durable groupchat turns before proposal approval.
- Platform review reached the configured OpenCode review peer and emitted a
  finalized review verdict instead of failing closed before review.

Remaining gaps:

```text
review_evidence_refs=[]
review session still reported MCP tools unavailable and used stdout fallback
gate_profiles_missing remained
child-worker MCP status writeback was not cleanly proven by this loop
```

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F113. Post-PR59 main fullchain reaches review handoff then fails on missing session layer

Severity: current main runtime blocker for fullchain final-action hold.

Loop 25z6 reran the maximum-accessible real chain from `origin/main` after
PR #57, PR #58, and PR #59 merged:

```text
source_head=6058002cc039345a7780f7f04e28bc2b2e3122fc
runtime_root=/tmp/xmuse-main-post-pr59-fullchain/.goal-runs/2026-06-19/loop-25z6-post-pr59-main-fullchain-013255
conversation_id=conv_a1bdbe89fe6d4141af5277158b061b18
collaboration_run=collab_6430946533ba4311a8952fd060715b62
post_collaboration_proposal=prop_52d5bc3241524697b05e29cd8d0c7045
resolution_id=res_a8488fa1f8ab4c409209460908364c7d
lane=post_merge_fullchain_proof_main_pr57_pr58_pr59
```

Positive evidence:

- Human mentioned only `@architect`.
- Architect, execute, and review peers wrote durable `mcp_writeback` chat
  responses with no degraded reason in the groupchat/collaboration phase.
- `collaboration_runs.status=done` with both execute and review responses.
- The post-collaboration proposal was approved and preserved lane fields:
  `review_runtime=opencode`, `final_action=no-auto-merge`, and
  `proof_boundary=local_runtime_proof`.
- The projected execution worktree was missing before dispatch and was created
  as a populated git worktree at main head `6058002`.
- The child worker ran
  `uv run pytest tests/xmuse/test_package_boundaries.py -q`, which passed with
  `16 passed in 3.16s`.
- Gate report was produced and passed open with `gate_profiles_missing`.

Failure:

```text
feature_lanes.status=gate_failed
failure_layer=review
failure_reason=required_review_peer_unavailable
peer_delivery_mode=required_peer_failed
peer_degraded_reason=session_layer_unavailable
review_plane.review_tasks[0].status=pending
review_plane.review_verdicts=[]
```

Secondary gap:

```text
child worker MCP unavailable -> stdout fallback
state_history still recorded dispatched -> executed -> gated -> gate_failed
```

Impact:

- PR #57 and PR #59 are post-merge runtime-confirmed for the bounded path.
- PR #58 did not regress this path, but Loop 25z6 did not prove a peer
  `read_run_health` decision call.
- Current `origin/main` still cannot complete the configured OpenCode platform
  review handoff. The next implementation domain is the review peer session
  layer wiring already proven locally in Loop 25z4d, but it requires a future
  small PR because the active PR budget is full.

Still not claimed:

```text
No GitHub review truth.
No ready_to_merge.
No clean child MCP writeback.
No live MemoryOS.
No production-ready groupchat.
No full L8-L10 closure.
No full L1-L11 closure.
```

### F124. Codex app-server errors were previously shaped as successful empty review results

Severity: partially fixed runtime blocker for the configured OpenCode review path.

Evidence:

```text
Loop 25z14:
run_root=/tmp/xmuse-review-peer-verdict-delivery/.goal-runs/2026-06-19/loop-25z14-review-peer-diagnostics-035829
source_head=741fb4fe71c297330f504c64eee028bb724cab90
conversation=conv_b0e6c315c8a84906b8e4055961b634a6
proposal=prop_7326f00795934a9c9a1a78900a01be31
resolution=res_bcd9bdfbb09f485ca3e78d073c46e527
lane=loop25z14_review_peer_diagnostics
```

Observed lane metadata:

```text
lane.status=gate_failed
gate_passed=true
failure_reason=review_peer_delivery_failed
peer_delivery_mode=required_peer_failed
peer_degraded_reason=review_peer_no_verdict
peer_result_status=ok
peer_result_message_type=result
peer_result_message_status=success
peer_result_message_runtime=codex-app-server
peer_result_artifact_keys=["latency_stages", "stdout", "transport"]
review_verdicts=[]
```

Follow-up evidence:

```text
PR #65:
head=ce2b9a9a50289be61ba7f7e30b794bbc5620aaa3
merge_commit=c4b668f740310a60e299e01e394ef283490130a4
Actions run 27786146679=success before merge
reviewDecision=

Loop 25z15 candidate:
run_root=/tmp/xmuse-review-appserver-result-text/.goal-runs/2026-06-19/loop-25z15-appserver-failure-candidate-040621
lane=loop25z15_appserver_failure_candidate
status=gate_failed
failure_reason=review_peer_delivery_failed
peer_degraded_reason=codex_app_server_error
peer_result_status=peer_error
peer_result_message_type=error
peer_result_message_runtime=codex-app-server

Loop 25z16 post-merge main:
run_root=/tmp/xmuse-main-after-pr65-fullchain/.goal-runs/2026-06-19/loop-25z16-main-post-pr65-appserver-error-041200
source_head=c4b668f740310a60e299e01e394ef283490130a4
lane=loop25z16_main_post_pr65_appserver_error
status=gate_failed
failure_reason=review_peer_delivery_failed
peer_degraded_reason=codex_app_server_error
peer_result_status=peer_error
peer_result_message_type=error
peer_result_message_runtime=codex-app-server
```

Impact:

- PR #64 made the failure diagnosable.
- PR #65 corrected the false-success shape for app-server error notifications
  and failed turns.
- The runner now fails closed with `peer_result_status=peer_error` for this
  provider/model error instead of treating an empty successful result as
  no-verdict.
- The next fix should route an OpenCode review peer through the real OpenCode
  provider path, not through Codex app-server with an OpenCode model name.

Forbidden claims preserved:

```text
No GitHub review truth.
No fullchain success from Loop 25z14, 25z15, or 25z16.
No production-ready natural groupchat.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
```

### F125. OpenCode Ray review sessions must not use Codex app-server transport

Severity: fixed for the bounded Ray session routing path; downstream review
MCP/evidence gaps remain open.

Evidence:

```text
PR #66:
head=d42541b18c27d1eb101e5463aff5e0c29c139662
merge_commit=457cbf14ebf74edf472b38c028551f42a9e08772
Actions run 27787176120=success before merge
reviewDecision=

Loop 25z17 candidate:
run_root=/tmp/xmuse-ray-opencode-process-transport/.goal-runs/2026-06-19/loop-25z17-opencode-process-review-candidate-042000
lane=loop25z17_opencode_process_review_candidate
source_head=d42541b18c27d1eb101e5463aff5e0c29c139662
status=awaiting_final_action
peer_delivery_mode=configured_peer
review_decision=merge
final_action_hold_id=final-648d470f52e2

Loop 25z18 post-merge main:
run_root=/tmp/xmuse-main-after-pr66-fullchain/.goal-runs/2026-06-19/loop-25z18-main-post-pr66-opencode-process-042700
lane=loop25z18_main_post_pr66_opencode_process
source_head=457cbf14ebf74edf472b38c028551f42a9e08772
status=awaiting_final_action
peer_delivery_mode=configured_peer
review_decision=merge
final_action_hold_id=final-06e33f50b16a
```

Runtime process evidence:

```text
xmuse_core.agents.opencode_persistent
opencode run --model opencode-go/deepseek-v4-flash --variant max --format json
```

Impact:

- The configured OpenCode platform review peer no longer goes through Codex
  app-server just because the Ray layer default transport is app-server.
- The prior `codex_app_server_error` boundary from Loops 25z15/25z16 is closed
  for this candidate runtime path.
- Review still used stdout fallback because MCP tools were not exposed in the
  OpenCode review session, so cited review evidence refs and review-session MCP
  writeback remain open.

Forbidden claims preserved:

```text
No GitHub review truth.
No production-ready natural groupchat.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
```

### F112. Three integrated runtime candidate fixes were split and merged as small PRs

Severity: publication bookkeeping; no closure claim.

After operator approval for new PR budget, the integrated local candidate work
was not pushed as an umbrella branch. Three bounded fixes were split into
`main`-based PRs:

```text
PR #57: codex/proposal-approval-preserves-lane-graph
head=dfebf9a95d252ce57b45431b4e49be0ebeb3ae5f
CI=xmuse CI completed success, run 27776606264
merge_commit=09453e42924c61dcaad8e624874a1e03e113e5ab

PR #58: codex/run-health-mcp-discovers-processes
rebased_head=4f6a29a42f0f98708b6030ac226a2091445d46e8
CI=xmuse CI completed success, run 27777358377
merge_commit=ff5d61d8d77dbc7f776a904fd5861342895709ea

PR #59: codex/create-missing-projected-lane-worktree
rebased_head=ef3836041fb95ab0e0102b95d62b02f2efa8fbac
CI=xmuse CI completed success, run 27777469922
merge_commit=6058002cc039345a7780f7f04e28bc2b2e3122fc
```

Impact:

- The earlier "needs separate PR publication" gap is now closed for these three
  slices, and `origin/main` includes the proposal-authority, run-health process
  discovery, and projected-worktree provisioning fixes.
- The current dirty integration branch remains non-authoritative and was not
  used as a replacement umbrella PR.
- PR #43 was not mutated.
- Post-merge runtime proof is still required from current `origin/main`.

Still not claimed:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No production-ready groupchat claim.
```

### F99. Real groupchat code-change lane needs main import before live MCP can prove the new handler

Severity: expected fullchain integration boundary.

Loop 25l was the first loop in this sequence where the real GOD groupchat drove
a small production code-change candidate instead of a no-edit validation lane.
The groupchat produced a durable proposal, approval dispatched a real lane, and
the child worker edited only:

```text
src/xmuse_core/platform/mcp_tools.py
tests/xmuse/test_platform_mcp_tools.py
```

The candidate test run passed in the execution worktree:

```text
uv run pytest tests/xmuse/test_platform_mcp_tools.py -q
-> 42 passed in 1.76s
```

The lane still ended as:

```text
status=exec_failed
reason=Focused lane fix applied and tests passed, but MCP update_lane_status still rejected review_runtime/final_action/proof_boundary in the live handler.
```

Impact:

- The code-change candidate was real and bounded, but live MCP server truth
  remained with the control worktree.
- This is the expected isolated-candidate/import boundary: a worker can change
  the execution worktree, but the running MCP server cannot prove newly changed
  handler behavior until the candidate is imported and the service restarts.
- The child correctly failed closed instead of using stdout or local tests as
  live MCP truth.

Required next behavior:

- Main Codex must audit/import the candidate into the control worktree.
- Then rerun a real chain with restarted services before claiming live MCP
  metadata acceptance.

### F100. Post-import code-change fullchain reached final-action hold with live metadata writeback

Severity: positive local-runtime capability finding.

After main Codex imported the Loop 25l candidate, Loop 25m reran the same small
production demand through the real groupchat.

Durable chain:

```text
human @architect
-> durable Codex/OpenCode collaboration
-> architect lane_graph proposal
-> human approval
-> lane worker edits code and test files
-> child Codex calls query_knowledge
-> child Codex runs uv run pytest tests/xmuse/test_platform_mcp_tools.py -q
-> child Codex calls update_lane_status with tests_run, changed_files,
   review_runtime, final_action, and proof_boundary
-> gate report
-> OpenCode persistent review
-> final-action hold
```

Key durable ids:

```text
runtime_root=.goal-runs/2026-06-18/loop-25m-code-change-post-import-fullchain-210843
conversation_id=conv_bdcdc0851f5d449d87262289edfc2a15
collaboration_run=collab_e8cd490b2e214f24b93fb4335f11c64b
proposal_id=prop_6a32beb79e304939b65d865ca63396ff
resolution_id=res_c3699f46ece44161b451c25ca1773511
lane_id=loop25m-mcp-status-metadata-allowlist-final-hold
review_task_id=rtask_07f8f34731324485bfc963f071fc4dfa
review_verdict_id=verdict-merge-rtask_07f8f34731324485bfc963f071fc4dfa
final_action_hold_id=final-6eb1f84dde22
```

The final lane state included:

```text
status=awaiting_final_action
tests_run=["uv run pytest tests/xmuse/test_platform_mcp_tools.py -q"]
changed_files=[
  "src/xmuse_core/platform/mcp_tools.py",
  "tests/xmuse/test_platform_mcp_tools.py"
]
review_runtime=opencode
final_action=no-auto-merge
proof_boundary=local_runtime_proof
review_decision=merge
```

Impact:

- The real groupchat can now drive a small production code-change candidate to
  local final-action hold.
- Live MCP accepted the broader bounded scalar metadata after import and
  service restart.
- This is still local runtime proof only. It is not GitHub review truth, merge
  truth, CI truth, or production readiness.

Remaining gaps at the time of Loop 25m:

- The branch was still broad and dirty; this needed to be split before PR
  publication.
- The final action hold was not resolved or merged.
- No GitHub server facts had been inspected for this code-change candidate.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F101. Bounded MCP metadata change was split into one small main-based PR and merged

Severity: positive publication finding with narrow server-truth boundary.

After Loop 25m, main Codex extracted only the bounded MCP metadata allowlist
change into a clean `origin/main`-based worktree:

```text
branch=codex/mcp-status-metadata-allowlist
base=origin/main
commit=e84da7d43276cae596fd70394e72d339539afff1
files_changed=2
insertions=99
deletions=0
```

The local clean-worktree validation passed:

```text
uv run pytest tests/xmuse/test_platform_mcp_tools.py -q
-> 43 passed in 2.87s

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed in 3.40s

uv run ruff check src/xmuse_core/platform/mcp_tools.py \
  tests/xmuse/test_platform_mcp_tools.py
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

GitHub server facts for the exact PR head:

```text
PR=https://github.com/iiyazu/Cross-Muse/pull/54
head_sha=e84da7d43276cae596fd70394e72d339539afff1
workflow_run=27762687502
quality-gates=SUCCESS
contract-smoke-gates=SUCCESS
real-runtime-integration-gate=SUCCESS
mergeStateStatus_before_merge=CLEAN
mergeable_before_merge=MERGEABLE
reviewDecision=""
```

GitHub accepted a normal squash merge without admin bypass:

```text
state=MERGED
mergedAt=2026-06-18T13:26:54Z
merge_commit=3a84c7d674a007f07a03e33da97f88b969cb68b9
remote_branch_preserved=true
```

Impact:

- One real fullchain-discovered implementation boundary has moved from broad
  runtime branch to a small reviewed-by-CI mainline change.
- This closes the publication gap only for the bounded MCP metadata allowlist
  domain.
- It does not close the broader GOD groupchat stability, GitHub review truth,
  production readiness, or full closure gaps.

Forbidden claims preserved:

```text
No GitHub review truth.
No broad merge truth beyond PR #54's exact server merge fact.
No ready_to_merge claim.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F102. Missing-profile gate report producer fix was split into one small main-based PR and merged

Severity: positive publication finding with narrow server-truth boundary.

After Loop 25k/25m, main Codex extracted only the missing-profile gate report
producer fix into a clean `origin/main`-based worktree:

```text
branch=codex/gate-missing-profile-report
base=origin/main
commit=6931690c46b86447d3c3bf071a6a992ec50596f5
files_changed=2
insertions=58
deletions=0
```

The local clean-worktree validation passed:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_run_gate_writes_report_when_gate_profiles_missing \
  tests/xmuse/test_platform_orchestrator.py::test_run_gate_uses_plural_gate_profiles \
  tests/xmuse/test_platform_orchestrator.py::test_run_review_god_captures_gate_report_ref_in_task \
  -q
-> 3 passed in 0.99s

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed in 3.57s

uv run ruff check src/xmuse_core/platform/execution/gate.py \
  tests/xmuse/test_platform_orchestrator.py
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

GitHub server facts for the exact PR head:

```text
PR=https://github.com/iiyazu/Cross-Muse/pull/55
head_sha=6931690c46b86447d3c3bf071a6a992ec50596f5
workflow_run=27763032153
quality-gates=SUCCESS
contract-smoke-gates=SUCCESS
real-runtime-integration-gate=SUCCESS
mergeStateStatus_before_merge=CLEAN
mergeable_before_merge=MERGEABLE
reviewDecision=""
```

GitHub accepted a normal squash merge without admin bypass:

```text
state=MERGED
mergedAt=2026-06-18T13:31:58Z
merge_commit=a84c9b99d4fe4143dce12257079a423a21e6f1e5
remote_branch_preserved=true
```

Impact:

- The missing-profile gate report producer now exists on `main`.
- Review tasks can cite a durable gate artifact even when `gate_profiles.json`
  is absent and the gate intentionally fails open.
- This closes only the missing-profile gate report producer domain. It does
  not prove broader review truth, production readiness, or natural groupchat
  stability.

Forbidden claims preserved:

```text
No GitHub review truth.
No broad merge truth beyond PR #55's exact server merge fact.
No ready_to_merge claim.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F103. Advanced child writeback idempotency fix was split into one small main-based PR and merged

Severity: positive publication finding with narrow server-truth boundary.

Loop 25p exposed a real runner-side duplicate transition:

```text
InvalidTransitionError: cannot transition
loop25p-main-package-boundary-final-hold from gated to executed
```

The child worker had already advanced the lane through MCP writeback and the
gate/review path before the parent execution provider result returned. Main
Codex extracted only that execution-coordinator idempotency fix into a clean
`origin/main`-based worktree:

```text
branch=codex/execution-child-writeback-advanced-status
base=origin/main
commit=600c2dbd0b5fe411be80ec6fdea55cbbe8032697
files_changed=2
insertions=85
deletions=11
```

The local clean-worktree validation passed:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_execution_god_tolerates_child_writeback_already_gated \
  tests/xmuse/test_platform_orchestrator.py::test_execution_transport_receives_provider_invocation \
  tests/xmuse/test_platform_orchestrator.py::test_run_gate_writes_report_when_gate_profiles_missing \
  tests/xmuse/test_platform_orchestrator.py::test_run_review_god_captures_gate_report_ref_in_task \
  -q
-> 4 passed

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check src/xmuse_core/platform/execution/executor.py \
  tests/xmuse/test_platform_orchestrator.py
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

GitHub server facts for the exact PR head:

```text
PR=https://github.com/iiyazu/Cross-Muse/pull/56
head_sha=600c2dbd0b5fe411be80ec6fdea55cbbe8032697
workflow_run=27764570812
quality-gates=SUCCESS
contract-smoke-gates=SUCCESS
real-runtime-integration-gate=SUCCESS
mergeStateStatus_before_merge=CLEAN
mergeable_before_merge=MERGEABLE
reviewDecision=""
```

GitHub accepted a normal squash merge without admin bypass:

```text
state=MERGED
mergedAt=2026-06-18T13:57:14Z
merge_commit=e64d696d4b7240390617d559e2514941949a937c
remote_branch_preserved=true
```

Impact:

- The execution coordinator now tolerates a provider result arriving after a
  child worker has already advanced the lane to `gated`, `reviewed`,
  `awaiting_final_action`, or another advanced status.
- This closes only the duplicate child-writeback transition domain.
- It does not close chat dispatch session reuse, review truth, production
  readiness, or full closure.

Forbidden claims preserved:

```text
No GitHub review truth.
No broad merge truth beyond PR #56's exact server merge fact.
No ready_to_merge claim.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F104. Loop 25r reached final-action hold after PR #56, but as degraded local runtime proof

Severity: mixed runtime finding.

Loop 25r reran the latest-main chain after PR #56 merged:

```text
base_head_sha=e64d696d4b7240390617d559e2514941949a937c
run_root=/tmp/xmuse-main-fullchain-after-pr56-215858/.goal-runs/2026-06-18/loop-25r-main-post-pr56-fullchain-215858
conversation_id=conv_eb893befc70146848b586fb96b59b798
collaboration_run=collab_f3903fe69de445b0a70b230eeed7c036
proposal_id=prop_b32f725604f643cd836277b13c5f1cc3
resolution_id=res_f9801f1a12e745f6a61f5b28bb110969
final_action_hold=final-dc80b6cd9786
```

Positive evidence:

- Codex architect, Codex execute, and OpenCode review completed a durable
  collaboration run.
- Architect emitted a durable `lane_graph` proposal through
  `chat_emit_proposal`.
- Human approval projected a lane and the platform lane reached
  `awaiting_final_action`.
- The state history reached
  `dispatched -> executed -> gated -> reviewed -> awaiting_final_action`.
- `coordinator_incidents.jsonl` contained only lifecycle entries, and the
  runner log showed no repeat of the Loop 25p `gated -> executed`
  `InvalidTransitionError`.

Negative evidence:

```text
first architect latency trace:
  delivery_mode=failed
  degraded_reason=peer_response_timeout

proposal lane feature_id=loop25r-main-package-boundary-final-hold
projected lane feature_id=res_f9801f1a12e745f6a61f5b28bb110969-lane-1
projected prompt_ref content=approval goal summary only
projected capabilities=["code"]

chat_dispatch_queue.status=failed
failure_reason=Cannot reuse role='execute':
  existing live session does not match requested agent/worktree

review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
review_fallback=stdout
```

Impact:

- PR #56's target failure did not recur in Loop 25r.
- The run cannot be used as clean proposal-to-lane proof because approval
  projection did not preserve the proposal lane graph as the lane authority.
- It cannot be used as persistent OpenCode review proof because review degraded
  to one-shot/stdout fallback.
- It still strengthens evidence that the current runtime can reach
  final-action hold under degraded conditions.

Required next behavior:

- Fix the approval/projection authority path so accepted `lane_graph`
  proposal lanes preserve their feature ids, prompts, capabilities,
  `review_runtime`, `final_action`, and proof boundary.
- Keep chat dispatch session/worktree reuse as an open boundary.
- Keep persistent review identity/evidence as an open boundary.

Forbidden claims preserved:

```text
No GitHub review truth.
No broad merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F105. Candidate approval/projection fix preserves proposal lane authority

Severity: positive candidate finding with degraded runtime evidence.

Loop 25s reran the Loop 25r authority failure boundary from a clean
`origin/main`-based candidate branch:

```text
source_worktree=/tmp/xmuse-proposal-approval-preserves-lane-graph
branch=codex/proposal-approval-preserves-lane-graph
base_head_sha=e64d696d4b7240390617d559e2514941949a937c
local_commit=dfebf9a fix: preserve proposal lane authority on approval
run_root=/tmp/xmuse-proposal-approval-preserves-lane-graph/.goal-runs/2026-06-18/loop-25s-proposal-authority-rerun-222452
conversation_id=conv_c37c6e46f5d9450d9e10fe682d2aad9d
collaboration_run=collab_eed99af4f63a4ab382570adcb15e29c8
proposal_id=prop_626c370252014279ba648eaa3bbb4864
resolution_id=res_5b884de2fbf44b558d6e51a1c685ba95
final_action_hold=final-d4e8e0467a55
summary_artifact=loop25s-final-durable-summary.json
```

Positive evidence:

- Codex architect emitted a durable `lane_graph` proposal through
  `chat_emit_proposal`.
- Codex execute and OpenCode review produced durable collaboration responses.
- Approval attempt 1 failed closed with
  `dispatch_gate_blocked: blocked_active_veto` while an active blocker existed.
- The stale health blocker was resolved through the public API with evidence
  that the durable execute/review responses had landed.
- Approval attempt 2 succeeded and preserved the proposal lane as the
  authority.
- The projected lane preserved:
  `feature_id=loop25s-proposal-authority-final-hold`,
  `capabilities=["python", "pytest", "xmuse_mcp"]`,
  `review_runtime=opencode`, `final_action=no-auto-merge`, and
  `proof_boundary=local_runtime_proof`.
- The platform lane authority path reached `awaiting_final_action`.

Impact:

- The candidate patch addresses the Loop 25r proposal-to-lane authority loss.
- Human approval content can add bounded supplemental metadata without
  replacing accepted proposal lanes.
- This is not yet main or GitHub-server proof because the candidate branch has
  not been pushed or published due the active PR budget.

Remaining negative evidence:

```text
first architect latency trace:
  delivery_mode=failed
  degraded_reason=peer_response_timeout

stale collaboration blocker:
  read_run_health incorrectly reported no live runner/MCP and unread inbox
  items before later durable peer responses arrived.

chat_dispatch_queue.status=failed
failure_reason=Cannot reuse role='execute':
  existing live session does not match requested agent/worktree

review_fallback_reason=verdict_merge
review_evidence_refs=[]
gate_profiles_missing warning remained
```

Required next behavior:

- Keep this patch scoped as a proposal/approval/projection authority domain.
- Do not spend another PR tonight unless the PR budget is explicitly reopened.
- Next runtime loop should target the stale run-health/blocker lifecycle or the
  chat dispatch session/worktree reuse boundary, not expand this candidate
  branch into a broader groupchat PR.

Forbidden claims preserved:

```text
No GitHub review truth.
No GitHub server truth for the candidate branch.
No broad merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F106. Candidate read_run_health fix sees live MCP and runner processes

Severity: positive candidate finding with narrow proof boundary.

Loop 25s showed a stale blocker:

```text
blocker_id=collab_blocker_b61ddec99d9e40cc93ce45d788ceed9f
reason=read_run_health reports no live xmuse platform runner process and no live xmuse MCP server process
contradiction=runner/MCP were live and durable execute/review responses landed later
```

Loop 25t isolated the root causes:

```text
source_worktree=/tmp/xmuse-run-health-mcp-discovers-processes
branch=codex/run-health-mcp-discovers-processes
base_head_sha=e64d696d4b7240390617d559e2514941949a937c
local_commit=b05be1c fix: let run health discover live runtime processes
run_root=/tmp/xmuse-run-health-mcp-discovers-processes/.goal-runs/2026-06-18/loop-25t-run-health-process-discovery-224352
```

Root causes:

- `build_run_health_snapshot()` passed `live_pids=set()`,
  `runner_pids=[]`, and `mcp_pids=[]`, so the read contract disabled process
  discovery even when live processes existed.
- `discover_xmuse_runtime_processes()` did not recognize the real current
  startup forms `xmuse-platform-runner` and `python -m xmuse.mcp_server`.

Real post-patch MCP evidence:

```text
POST /sse tools/call read_run_health
artifact=loop25t-read-run-health-live-mcp-after-classifier-fix.json
runner_count=1
runner_pids=[495151]
mcp_count=1
mcp_pids=[495111]
warnings=[]
```

Impact:

- `read_run_health` can now report live runner/MCP process truth for the
  current entrypoint forms used in these loops.
- This should prevent the specific false "no live runner/MCP" blocker seen in
  Loop 25s once the candidate fix is imported into the active runtime.

Remaining caveats:

- This is a local candidate branch, not main or GitHub server truth.
- It does not prove the full blocker lifecycle is fixed; stale blockers can
  still come from timing, inbox-state races, or peer prompt behavior.
- A full groupchat rerun is still required after this fix is available in the
  runtime used by the GOD peers.

Forbidden claims preserved:

```text
No GitHub review truth.
No GitHub server truth for the candidate branch.
No broad merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F107. Projected lane worktree fields must create real worktrees

Severity: execution-infrastructure blocker, locally fixed.

Loop 25u2 combined the proposal-authority and run-health candidate fixes and
used a clean human prompt that mentioned only `@architect`. The chain advanced
through durable collaboration, proposal, approval, and projection, then failed
before real lane execution:

```text
source_worktree=/tmp/xmuse-integrated-25u-fullchain
branch=codex/local-25u-integrated-fullchain
run_id=loop-25u2-integrated-health-authority-fullchain-225325
lane_id=loop25u2-integrated-health-authority-final-hold
failure=FileNotFoundError
missing_path=/tmp/xmuse-loop-25u2-integrated-health-authority-fullchain-225325-exec
lane.status=exec_failed
failure_reason=execution_infra_unavailable
worker_pid=null
```

Root cause:

- Projection wrote a `worktree` path into the lane.
- The path did not exist yet.
- `ensure_lane_worktree()` treated the field as an existing worktree and called
  branch verification before creating the checkout.

Candidate fix:

```text
local_commit=b9c6e31 fix: create missing projected lane worktree
file=src/xmuse_core/platform/orchestrator_lane_flow.py
```

Impact:

- A projected lane can now carry the intended worktree path while still letting
  the orchestrator materialize it before dispatch.
- This closes the immediate execution-infrastructure blocker exposed by
  Loop 25u2.

Focused validation:

```text
uv run pytest \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_creates_missing_projected_worktree_path \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_initializes_missing_isolated_worktree \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_records_branch_for_existing_non_git_worktree \
  -q
-> 3 passed

uv run ruff check src/xmuse_core/platform/orchestrator_lane_flow.py \
  tests/xmuse/test_platform_orchestrator.py
-> All checks passed
```

Forbidden claims preserved:

```text
No GitHub review truth.
No GitHub server truth for the candidate branch.
No merge truth.
No ready_to_merge or pr_merged.
No fullchain proof from Loop 25u2.
No production-ready groupchat claim.
```

### F108. Integrated candidate chain reaches no-auto-merge final-action hold

Severity: strongest current local integrated runtime finding with explicit
candidate proof boundary.

Loop 25v reran after combining three local candidate commits:

```text
source_worktree=/tmp/xmuse-integrated-25u-fullchain
branch=codex/local-25u-integrated-fullchain
base_head_sha=e64d696d4b7240390617d559e2514941949a937c
local_commits:
  ee4bc01 fix: preserve proposal lane authority on approval
  7e7dec0 fix: let run health discover live runtime processes
  b9c6e31 fix: create missing projected lane worktree
run_id=loop-25v-integrated-fullchain-after-worktree-fix-230627
conversation_id=conv_8643ce76d634458c932e9e4da977e17e
collaboration_run=collab_40e57ea4c6764f2a8cbb8d687e1a0e34
proposal_id=prop_404ac2c4fbfd4550baf4e42a0a5ffe4d
resolution_id=res_c1da2ab84ec545b68e57ede769773ed3
lane_id=loop25v-integrated-fullchain-final-hold
final_action_hold_id=final-e1681af6b91d
```

Positive evidence:

- Human message mentioned only `@architect`.
- Codex architect emitted the durable `lane_graph` proposal.
- Codex execute and OpenCode review durable collaboration responses landed.
- Human approval preserved the proposal lane authority and projected the
  requested lane shape.
- The lane worktree was created at the projected path and used by a real
  `codex exec` worker.
- The worker exited 0 after running exactly
  `uv run pytest tests/xmuse/test_package_boundaries.py -q`.
- The focused package-boundary run reported `16 passed in 3.63s`.
- The execution worktree git status was clean.
- The lane state reached `awaiting_final_action` with
  `final_action=no-auto-merge`.

Remaining caveats:

```text
architect latency trace still recorded peer_response_timeout for the first turn
peer_turn_mcp_tool_traces did not record read_run_health
child worker MCP tools were unavailable and stdout fallback was used
child worker read superpowers skill files despite the child-worker override
gate_profiles_missing warning remained
review_evidence_refs=[]
review_fallback_reason=verdict_merge
review session also reported MCP tools unavailable
```

Impact:

- This is the strongest current local integrated proof that the candidate path
  can run from groupchat proposal through approval, execution, review, and
  no-auto-merge hold.
- It does not convert the candidates into main or GitHub server truth.
- It does not close the child MCP writeback, review evidence, latency-trace,
  or production-readiness gaps.

Post-loop validation:

```text
uv run pytest \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_metadata_preserves_proposal_lane_authority \
  tests/xmuse/test_run_health.py::test_read_run_health_snapshot_uses_runtime_process_discovery \
  tests/xmuse/test_run_health.py::test_discover_xmuse_runtime_processes_recognizes_entrypoint_runtime_commands \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_creates_missing_projected_worktree_path \
  tests/xmuse/test_package_boundaries.py \
  -q
-> 20 passed, 1 warning in 4.46s

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
ports 8100/8201 after cleanup -> no listeners
runtime processes after cleanup -> none observed
```

Forbidden claims preserved:

```text
No GitHub review truth.
No GitHub server truth for the integrated candidate branch.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready natural groupchat claim.
```

### F109. Current AgentSpawner child path can expose xmuse MCP

Severity: positive current-worktree runtime finding with narrow boundary.

Loop 25w ran the current-worktree AgentSpawner path against an isolated runtime
root and execution worktree:

```text
run_root=.goal-runs/2026-06-18/loop-25w-child-mcp-agent-spawner-probe-232428
execution_worktree=/tmp/xmuse-loop-25w-child-mcp-agent-spawner-probe-232428-exec
lane_id=loop25w-child-mcp-agent-spawner-probe
```

Observed:

```text
worker command included --ignore-user-config
child called query_knowledge
child called update_lane_status
feature_lanes.status=executed
```

Impact:

- The current AgentSpawner child path can expose the xmuse MCP server to
  noninteractive Codex workers.
- Loop 25v's child-MCP fallback was not a universal MCP/server limitation; it
  was specific to that integrated candidate path.
- This does not by itself prove the full groupchat chain, review truth, or
  production readiness.

### F110. Execution workers need explicit current-status guard authority

Severity: execution contract integrity issue, locally fixed and rechecked.

Loop 25x proved that the child worker had MCP tools, ran the package-boundary
test, and attempted `update_lane_status`, but both writes were rejected:

```text
child called query_knowledge
child ran uv run pytest tests/xmuse/test_package_boundaries.py -q
test result=16 passed in 3.29s
child called update_lane_status twice
rejection=state guard mismatch
```

The lane id ended in `final-hold`, and the worker inferred the guard from the
lane id/final-action wording instead of the actual lane status. The runner then
misclassified the result as:

```text
failure_reason=child_mcp_required_but_unavailable
```

Corrected boundary:

- MCP was available.
- The writeback failed because `guard.current_status` did not match the actual
  lane state.
- The classifier must treat observed MCP tool-call markers as stronger evidence
  than fallback prose.

Fix:

```text
build_execution_prompt now includes:
  Current lane status: <status>
  use guard.current_status exactly <status>

executor child-MCP classification now separates:
  child_mcp_required_but_unavailable
  child_mcp_writeback_rejected
  child_mcp_required_but_missing_writeback
```

Loop 25y rechecked the fix through a real runner-dispatched Codex child worker:

```text
worker prompt Current lane status=dispatched
child called query_knowledge
child ran uv run pytest tests/xmuse/test_package_boundaries.py -q
test result=16 passed in 3.56s
child update_lane_status succeeded with guard.current_status=dispatched
tests_run=["uv run pytest tests/xmuse/test_package_boundaries.py -q"]
changed_files=[]
```

Impact:

- Direct child MCP execution writeback is now locally proven on the current
  runner-dispatched path.
- This is still local current-worktree proof only, not GitHub/server truth.
- Repeated fullchain runs are still required before treating the path as stable.

### F111. Required OpenCode review peer handoff needs conversation context

Severity: review-plane integration blocker.

Loop 25y deliberately skipped full groupchat setup and dispatched a direct
runner lane. Execution and gate passed, then review failed:

```text
status=gate_failed
gate_passed=true
failure_layer=review
failure_reason=required_review_peer_unavailable
peer_delivery_mode=required_peer_failed
peer_degraded_reason=missing_conversation_id
```

Impact:

- The runner can now reach the review handoff after direct child MCP writeback.
- Required persistent OpenCode review delivery cannot be assumed for a direct
  runner lane without a conversation/session context.
- A future fix should either supply the required conversation context from the
  approved groupchat/lane authority or fail closed earlier with a clearer
  operator-facing reason.

Remaining caveat:

```text
gate_profiles.json missing; no gate commands were run and lane passed open
```

That warning means Loop 25y is not a production gate proof.

### F97. Missing gate_profiles now produces a durable gate report ref in fullchain

Severity: positive local-runtime capability finding.

Loop 25j showed `review_plane.review_tasks[0].gate_report_ref=null` after an
otherwise successful local fullchain. Inspection found the producer gap:
`run_gate()` returned `True` when `gate_profiles.json` was missing, but did not
write a gate report artifact.

Loop 25k added a targeted fix and reran the real chain:

```text
human @architect
-> durable Codex/OpenCode collaboration
-> architect lane_graph proposal
-> human approval
-> lane worker child MCP execution
-> gate_profiles_missing fail-open gate report
-> OpenCode persistent review
-> final-action hold
```

Key durable ids:

```text
runtime_root=.goal-runs/2026-06-18/loop-25k-gate-report-ref-fullchain-204322
conversation_id=conv_5a97d187f2ec470bb2e2617387d049b0
collaboration_run=collab_afd725bac1fe4ae6a5635ca16ee4cb01
proposal_id=prop_a3cb3cd433f44f82a0572f081f74df44
resolution_id=res_a0019a76a84448fe9db3a1b67953dc74
lane_id=loop25k-gate-report-ref-final-hold
review_task_id=rtask_620a82c0a915475894e0ab2d6a997ab0
review_verdict_id=verdict-merge-rtask_620a82c0a915475894e0ab2d6a997ab0
final_action_hold_id=final-07f2f0dbc671
```

The new gate artifact exists:

```text
logs/gates/loop25k-gate-report-ref-final-hold/report.json
passed=true
blocking_passed=true
profile_ids=[]
command_results=[]
resolution_reasons.gate_profiles=["gate_profiles_missing"]
```

The review plane now cites it:

```text
review_plane.review_tasks[0].gate_report_ref=
  logs/gates/loop25k-gate-report-ref-final-hold/report.json
review_plane.review_verdicts[0].evidence_refs includes:
  logs/gates/loop25k-gate-report-ref-final-hold/report.json
```

Impact:

- The prior `gate_report_ref=null` evidence gap is fixed for the missing
  `gate_profiles.json` path.
- Review evidence now distinguishes "no gate commands were configured" from
  "gate evidence missing".
- This remains fail-open local runtime evidence, not a stronger production gate
  policy.

Proof boundary:

```text
local_runtime_proof for this path only
not GitHub review truth
not merge truth
not ready_to_merge
not pr_merged
not live MemoryOS
not full L8-L10 closure
not full L1-L11 closure
not overnight readiness
not production-ready groupchat
```

### F98. Child update_lane_status metadata allowlist still rejects broader context keys

Severity: evidence ergonomics gap, not a Loop 25k blocker.

Loop 25k's child worker first tried to write extra metadata keys through
`update_lane_status`:

```text
review_runtime
final_action
proof_boundary
```

MCP rejected those keys, then the child retried with accepted metadata and
included the broader context in the audit reason. The final status update
succeeded and the lane reached `awaiting_final_action`.

Impact:

- The allowlist is still stricter than the natural lane prompt wording.
- This did not compromise the 25k result because `review_runtime` and
  final-action policy were already present in lane projection, and the bounded
  execution evidence keys were accepted.
- A future cleanup can either keep these keys out of child metadata prompts or
  explicitly allow safe scalar context fields.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F95. Loop 25j reached groupchat-produced fullchain final-action hold with child MCP writeback

Severity: positive local-runtime capability finding.

Loop 25j produced the strongest current single-run local runtime chain:

```text
human @architect
-> durable GOD chatgroup
-> Codex architect opens collaboration with Codex execute and OpenCode review
-> execute records dispatchable response
-> review records review_ready response
-> architect emits lane_graph proposal
-> human approval
-> dispatch bridge handoff
-> isolated lane worker in a git worktree
-> child Codex calls query_knowledge over xmuse MCP
-> child Codex runs uv run pytest tests/xmuse/test_package_boundaries.py -q
-> child Codex calls update_lane_status over xmuse MCP
-> platform gate passes
-> configured OpenCode persistent review emits merge verdict
-> final-action hold remains pending because --no-auto-merge is active
```

Key durable ids:

```text
runtime_root=.goal-runs/2026-06-18/loop-25j-groupchat-child-mcp-fullchain-202309
conversation_id=conv_e248968369354772ac9a08a2544f480c
collaboration_run=collab_329af5f56f244b5098273b13b7ad7225
proposal_id=prop_8f401b153a4e434e97ef563dfd003906
resolution_id=res_a7a3afb8ee3e4a3a8019584eda7d75e2
lane_id=loop25j-groupchat-child-mcp-final-hold
review_task_id=rtask_5b90ffd347ab45bfbe9b376bd31e2715
review_verdict_id=verdict-merge-rtask_5b90ffd347ab45bfbe9b376bd31e2715
final_action_hold_id=final-8a92addc9580
```

The child worker spawn log contains direct MCP proof:

```text
mcp: xmuse-platform/query_knowledge started
mcp: xmuse-platform/query_knowledge (completed)
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 3.27s
mcp: xmuse-platform/update_lane_status started
mcp: xmuse-platform/update_lane_status (completed)
```

Impact:

- The child MCP writeback path is no longer only an isolated AgentSpawner
  success. It has been observed inside a groupchat-produced fullchain run.
- The natural groupchat path can produce a proposal from durable collaboration
  responses instead of a manually constructed lane graph.
- The OpenCode peer can participate both in groupchat review readiness and in
  configured persistent final review for the same local runtime chain.

Proof boundary:

```text
local_runtime_proof for this run only
not GitHub review truth
not merge truth
not ready_to_merge
not pr_merged
not live MemoryOS
not full L8-L10 closure
not full L1-L11 closure
not overnight readiness
not production-ready groupchat
```

### F96. Loop 25j still exposes automation and evidence-quality gaps

Severity: local-runtime gap.

Loop 25j did not remove the remaining production-closure gaps.

Observed gaps:

```text
local harness did not auto-approve because it looked for proposals in the wrong timeline field
review_plane.review_tasks[0].gate_report_ref=null
only one clean fullchain run has reached this exact child-MCP path
the lane performed no code edits, so it does not yet prove demand-to-code-change completion
no GitHub PR, CI, review, or merge truth was inspected or claimed
```

Impact:

- Operator automation can still miss a product proposal even when durable
  proposal state is present.
- Review evidence is stronger than earlier empty-ref runs, but the review task
  still lacks a direct gate report reference.
- Repeated-run reliability and real code-change completion remain open before
  any production-readiness claim.

Required next behavior:

- Pick the next loop from the remaining durable gaps instead of broadening this
  branch into an umbrella.
- Prefer a real small demand that changes code or documentation through the
  groupchat-to-lane path, then stops at final-action hold.
- If the same review evidence gap appears again, patch the review task/gate
  report linkage directly and rerun.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F92. Child MCP tools are reachable, but AgentSpawner child prompt can still fail early

Severity: reliability blocker.

Loop 25h started a real xmuse MCP server with `query_knowledge` and
`update_lane_status` exposed. A direct Codex probe using the same SSE config
successfully called `get_status`, `query_knowledge`, and `update_lane_status`.

However, the AgentSpawner-launched child for the same runtime root returned:

```text
status=exec_failed
failure_reason=child_mcp_required_but_unavailable
tests_run=
changed_files=
```

Impact:

- The server and SSE command shape are not sufficient root cause by themselves.
- The remaining reliability issue is in the child invocation/prompt behavior:
  the AgentSpawner child can decide no tools are exposed even when the direct
  Codex/SSE probe can call the tools.

Required next behavior:

- Reduce the AgentSpawner execution prompt so the child explicitly calls
  `mcp__xmuse_platform.query_knowledge` instead of first reasoning about tool
  availability in prose.
- Re-run the AgentSpawner child path against a live MCP server until the child
  performs the tool calls or a lower transport issue is proven.

### F93. update_lane_status rejected normal execution evidence metadata

Severity: producer/authority mismatch, targeted fix applied.

Loop 25h direct Codex/SSE probe successfully called:

```text
query_knowledge
uv run pytest tests/xmuse/test_package_boundaries.py -q
update_lane_status
```

The first `update_lane_status` call failed because the projection metadata
allowlist rejected:

```text
changed_files
tests_run
```

Impact:

- A real child worker could not preserve normal execution evidence through the
  lane authority path even after reaching the mutating MCP tool.

Applied fix:

- `update_lane_status` now accepts bounded string-list metadata for
  `tests_run` and `changed_files`.
- Unsafe provider/worker internals remain rejected.

Post-fix proof:

```text
feature_lanes.json status=executed
tests_run=["uv run pytest tests/xmuse/test_package_boundaries.py -q"]
changed_files=[]
last_mutation_audit.tool=update_lane_status
```

Proof boundary:

```text
local direct Codex/SSE MCP writeback only
not AgentSpawner reliability
not full groupchat proof
not review truth
not merge truth
not production readiness
```

### F94. AgentSpawner child MCP writeback reached a positive local runtime proof

Severity: positive boundary proof with stability still open.

Loop 25i reran the AgentSpawner child path after tightening the child prompt to
require an actual namespaced MCP tool-call attempt before fallback.

Observed child trace:

```text
mcp: xmuse-platform/query_knowledge started
mcp: xmuse-platform/query_knowledge (completed)
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 3.27s
mcp: xmuse-platform/update_lane_status started
mcp: xmuse-platform/update_lane_status (completed)
```

Authority state:

```text
feature_lanes.json status=executed
tests_run=["uv run pytest tests/xmuse/test_package_boundaries.py -q"]
changed_files=[]
last_mutation_audit.tool=update_lane_status
```

Impact:

- The prior child MCP writeback blocker is no longer absolute.
- One AgentSpawner-launched Codex child can call xmuse MCP, run the bounded
  validation command, and update lane authority with bounded evidence.

Remaining gap:

- This is one local runtime probe, not repeated stability.
- It does not yet include groupchat proposal approval, review, final-action
  hold, or full demand-to-completion.

Required next behavior:

- Run the larger groupchat-to-lane fullchain again and verify this same child
  MCP writeback occurs inside the groupchat-produced lane path.
- If it regresses, stop prompt patching and refactor the child invocation
  boundary so required MCP calls are mechanically verified before execution.

Forbidden claims preserved:

```text
No repeated child MCP reliability claim.
No full groupchat-to-completion claim.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F91. MCP-required child workers now fail closed before running tests when tools are unavailable

Severity: evidence integrity improvement with an open reliability gap.

Loop 25f showed a bad child-worker behavior shape:

```text
MCP required by lane contract
MCP tools unavailable
child still ran uv run pytest tests/xmuse/test_package_boundaries.py -q
child stdout fallback said status=executed
runner rejected the fallback and marked exec_failed
```

Loop 25g updated the child execution contract and then launched a real Codex
child through `AgentSpawner` with no MCP server available on the configured
port. The observed stdout was:

```text
status=exec_failed
failure_reason=child_mcp_required_but_unavailable
tests_run=none
changed_files=none
```

Impact:

- MCP-required missing-tool fallback is now classified earlier and no longer
  encourages the child to run tests before failing.
- Runner fail-closed classification now also treats real provider wording
  "not callable" as an MCP-unavailable fallback.

Remaining negative evidence:

```text
codex_cli_exit_code=0
```

Codex CLI still returned process exit code 0 for an `exec_failed` prose result.
Therefore process exit code is not a reliable authority for this failure mode;
runner metadata and durable lane state must continue to fail closed when
MCP-required writeback is missing.

Required next behavior:

- Run another real fullchain with an actual MCP server and require direct
  `query_knowledge` plus `update_lane_status` calls from the child worker.
- Do not claim child MCP writeback reliability until repeated successful
  writebacks are observed in the real lane path.

Forbidden claims preserved:

```text
No child MCP reliability claim.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F80. Loop 25a proves the strongest local groupchat-to-final-hold chain so far

Severity: positive fullchain runtime finding with local proof boundary.

Loop 25a combined the previously separate 24y and 24z proofs in one run:

```text
runtime_root=.goal-runs/2026-06-18/loop-25a-fullchain-child-mcp-opencode-review-181115
conversation_id=conv_a5b913114720429ca0334e363419328b
proposal_id=prop_6330d680af104942812e8b3744150f58
resolution_id=res_6edb2cd51e0f49108cd2317df9b3da8c
lane_id=loop25a-child-mcp-opencode-final-hold
final_action_hold_id=final-e79569f65a5e
```

The durable chain reached:

```text
human @architect demand
-> Codex architect durable messages
-> Codex execute formal collaboration response
-> OpenCode review formal collaboration response
-> architect-emitted lane_graph proposal
-> OpenCode proposal review writeback
-> human HTTP approval
-> isolated lane execution
-> child Codex MCP query_knowledge and update_lane_status
-> configured OpenCode final review callback update_lane_status
-> awaiting_final_action
```

Key child-worker evidence:

```text
worktree=/tmp/xmuse-loop-25a-fullchain-child-mcp-opencode-review-181115-exec
mcp: xmuse-platform/query_knowledge started/completed
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 2.69s
mcp: xmuse-platform/update_lane_status started/completed
```

Key final review evidence:

```text
last_mutation_audit.actor=opencode-review-callback
last_mutation_audit.tool=update_lane_status
review_peer_id=part_59b9600cee914dd6b51ef9380b023f77
review_runtime_requested=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict.status=finalized
final_actions.status=pending
```

Impact:

- F77 is now closed for this specific local groupchat-driven fullchain shape:
  the child worker did direct MCP writeback and final review used configured
  OpenCode callback in the same run.
- The real groupchat layer is no longer only a fake/demo path for this bounded
  demand. Codex and OpenCode acted as registered durable peer providers for the
  proposal path.
- This does not prove production readiness or repeated-run stability.

Proof boundary:

```text
local_runtime_proof only
not GitHub review truth
not merge truth
not ready_to_merge or pr_merged
not live MemoryOS
not full L8-L10 closure
not full L1-L11 closure
not production readiness
not overnight readiness
```

### F81. Loop 25a left an orphan running collaboration from an earlier architect attempt

Severity: collaboration lifecycle integrity gap.

During Loop 25a, the architect first created:

```text
collab_b43e047991064b7997c04303e8f7cab4
status=running
targets=["@execute", "@review"]
idempotency_key=inbox_003ea0d5fe794f5881be3a2f3dae5251-loop25a-collab
```

The architect later created the successful collaboration:

```text
collab_eba23ae2b83e4a47a9e3e5b9a209a807
status=done
targets=["@execute", "@review"]
idempotency_key=loop25a-child-mcp-opencode-final-hold-collab
```

Impact:

- The useful fullchain completed, but collaboration lifecycle accounting is not
  clean.
- Late provider turns or self-correction can leave stale active collaboration
  runs that are no longer the selected authority.
- Future reliability work should fail closed or supersede/cancel older active
  collaborations for the same source inbox and target set.

Required next behavior:

- Add lifecycle handling for orphaned/stale collaboration runs before claiming
  repeated-run stability.
- Preserve `collab_eba23...` as the authority for Loop 25a and keep
  `collab_b43...` as negative evidence.

### F82. Review evidence refs can cite a missing gate report

Severity: evidence integrity gap.

Loop 25a final review recorded:

```text
review_evidence_refs=[
  "feature_lanes.json#lane=loop25a-child-mcp-opencode-final-hold",
  "logs/gates/loop25a-child-mcp-opencode-final-hold/report.json"
]
review_plane.review_tasks[0].gate_report_ref=null
```

But the referenced gate report file did not exist after the run:

```text
logs/gates/loop25a-child-mcp-opencode-final-hold/report.json -> missing
```

Impact:

- The review verdict itself is durable, and the lane reached final-action hold,
  but part of its cited evidence chain is stale or speculative.
- Non-empty `review_evidence_refs` is not enough; refs must resolve to real
  artifacts or explicitly point to durable state anchors.

Required next behavior:

- Make review evidence refs resolvable before using them as proof support.
- If gate profiles are missing, do not cite a gate report path unless the file
  exists.
- Keep `gate_profiles_missing` as an open runtime gap.

Targeted fix after Loop 25a:

- `opencode_persistent` now filters review callback evidence refs against the
  configured local root before putting them into `update_lane_status` metadata.
- Non-local or URI-style refs are preserved, but local `logs/...` and
  `feature_lanes.json#...` refs must resolve under the configured root.
- Focused guard:
  `uv run pytest tests/xmuse/test_opencode_persistent.py -q` -> `19 passed`.

Runtime status:

- Loop 25b2 reran the full groupchat-to-final-hold shape and proved this
  specific stale-ref path is closed for the current review callback path:

```text
runtime_root=.goal-runs/2026-06-18/loop-25b2-evidence-ref-filter-fullchain-183725
lane_id=loop25b2-evidence-ref-filter-final-hold
review_verdict.evidence_refs=[
  "/tmp/xmuse-loop-25b2-evidence-ref-filter-fullchain-183725-exec/.pytest_cache/v/cache/nodeids"
]
logs/gates/loop25b2-evidence-ref-filter-final-hold/report.json -> missing as expected
missing gate report path cited by review_evidence_refs -> no
```

Proof boundary:

- This closes only the missing local `logs/gates/.../report.json` citation path.
- It does not prove strong review truth, GitHub review truth, merge truth,
  production readiness, full L8-L10 closure, or full L1-L11 closure.

### F83. Review evidence refs are resolvable but still weak

Severity: evidence quality gap.

Loop 25b2 no longer cited the absent gate report path, but the final review
evidence ref was:

```text
/tmp/xmuse-loop-25b2-evidence-ref-filter-fullchain-183725-exec/.pytest_cache/v/cache/nodeids
```

That file existed, and therefore the F82 missing-ref failure was not repeated.
However, the cited artifact is only pytest cache metadata. It is weaker than
the child-worker stdout/stderr/result logs, a real gate report, or a durable
lane/review state anchor.

The same run also preserved:

```text
review_plane.review_tasks[0].gate_report_ref=null
gate_profiles_missing
```

Impact:

- Current `review_evidence_refs` are now resolvable, but they are not yet the
  best proof artifact for review decisions.
- Do not use this as strong review truth or production readiness.

Required next behavior:

- Prefer spawn result/stdout/stderr refs or a real gate report over incidental
  pytest cache files.
- Keep `gate_profiles_missing` open until a real gate profile/report path is
  produced or the review prompt stops expecting one.

Runtime status after targeted fix:

- `opencode_persistent` now allowlists local review evidence refs to formal
  xmuse run-root anchors and falls back to context-derived refs when provider
  output contains only weak refs.
- Focused guard:
  `uv run pytest tests/xmuse/test_opencode_persistent.py -q` -> `20 passed`.
- Loop 25c proved the fix in the real fullchain shape:

```text
runtime_root=.goal-runs/2026-06-18/loop-25c-review-evidence-quality-185246
lane_id=loop25c-review-evidence-quality-final-hold
review_evidence_refs=[
  "feature_lanes.json#lane=loop25c-review-evidence-quality-final-hold",
  "logs/agent_spawns/loop25c-review-evidence-quality-final-hold/20260618T110049Z.stdout.log",
  "logs/agent_spawns/loop25c-review-evidence-quality-final-hold/20260618T110049Z.result.json",
  "logs/lane_context/loop25c-review-evidence-quality-final-hold/latest.json"
]
.pytest_cache refs in final review_evidence_refs -> none
missing logs/gates report refs in final review_evidence_refs -> none
```

Remaining scope:

- This closes the weak pytest-cache ref path for the current OpenCode review
  callback. It does not close `gate_profiles_missing` or prove GitHub/server
  review truth.

### F84. Review provider selection read model can disagree with configured OpenCode callback truth

Severity: observability integrity gap.

Loop 25b2 final lane state recorded the authoritative review mutation as:

```text
last_mutation_audit.actor=opencode-review-callback
review_runtime_requested=opencode
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_identity=configured:part_6948207a01bb4c6f94de3fbbce1904db
```

But `read_models/provider_selection_records.jsonl` also recorded:

```text
task_type=review
provider_id=codex
profile_id=review
selection_reason=Route review to the high-quality codex review profile.
```

Impact:

- The provider-selection read model is not sufficient authority for the actual
  review actor in configured-peer review paths.
- The lane/review-plane mutation still shows OpenCode callback authority, but
  downstream dashboards or audits could misread the review provider if they use
  only provider-selection records.

Required next behavior:

- Split provider-policy selection telemetry from configured peer callback
  delivery truth.
- Dashboards/audits should prefer final lane mutation and review-plane verdict
  actor metadata for configured-peer reviews.

Loop 25c repeated the same read-model inconsistency:

```text
provider_selection_records task_type=review provider_id=codex profile_id=review
feature_lanes.last_mutation_audit.actor=opencode-review-callback
review_runtime_requested=opencode
persistent_review_identity=configured:part_cb5eccaea6ea482f8230b54a798ea4ce
```

### F85. Child-worker MCP writeback is not yet repeatably reliable across fullchain runs

Severity: evidence integrity gap.

Loop 25a and Loop 25b2 both showed child-worker MCP access in the fullchain
shape:

```text
mcp: xmuse-platform/query_knowledge started/completed
mcp: xmuse-platform/update_lane_status started/completed
```

Loop 25c used the same broad child-worker command shape but reported:

```text
MCP unavailable in this session: the listed xmuse tool calls
(`query_knowledge`, `update_lane_status`) were not exposed
```

The lane still reached final-action hold:

```text
feature_lanes.status=awaiting_final_action
review_decision=merge
final_action_hold_id=final-dda127c88867
```

Impact:

- Current code can complete the local fullchain without clean child-worker MCP
  writeback, but that weakens evidence integrity.
- Do not claim repeatably reliable child-worker MCP writeback from Loop 25c.

Required next behavior:

- Preserve the distinction between runner-mediated execution truth and
  child-worker MCP callback truth.
- Keep the fail-closed guard: if a lane explicitly requires child MCP writeback
  and the durable lane remains `dispatched` after an exit-0 child worker result,
  do not transition it to `executed`.
- Continue repeatability work before claiming production-grade child-worker MCP
  exposure.

2026-06-18 update:

- A targeted executor guard now rejects the Loop 25c negative shape. The focused
  regression
  `test_execution_god_rejects_stdout_success_when_child_mcp_is_required`
  proves an explicit MCP-required lane with stdout `MCP unavailable` and
  exit-code 0 is marked `exec_failed` instead of `executed`.
- Loop 25d reran the real groupchat-to-final-hold chain after the guard:

```text
runtime_root=.goal-runs/2026-06-18/loop-25d-child-mcp-failclosed-191335
conversation_id=conv_105fd7e41795440b9caec14d46bac230
collaboration_run=collab_6139d8f7632241bc9af42612cc992a1c
proposal_id=prop_81934285e4c04b868cb854443294db6c
resolution_id=res_418433e212904f5cad65089a58251afd
lane_id=loop25d-child-mcp-failclosed-final-hold
final_action_hold_id=final-9b4f094ce5eb
```

- Loop 25d did not trigger fail-closed because the child worker had real MCP
  access:

```text
mcp: xmuse-platform/query_knowledge started/completed
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 2.81s
mcp: xmuse-platform/update_lane_status started/completed
mcp: xmuse-platform/update_lane_status started/completed
last_mutation_audit.tool=update_lane_status
```

Current classification:

- Loop 25d strengthens local runtime evidence for the successful child MCP path
  and proves the guard does not break it.
- The repeatability claim remains forbidden: 25a, 25b2, and 25d were positive;
  25c was negative. Treat this as improved evidence integrity, not production
  readiness.

Remaining gaps:

- `gate_profiles_missing` still appears before review.
- `review_plane.review_tasks[0].gate_report_ref=null`.
- The final review summary can mention pytest cache text even when evidence
  refs are formal xmuse refs; summary text is not artifact truth.

### F79. Child-worker MCP writeback works in an isolated lane-worker run

Severity: positive isolation finding with a narrow proof boundary.

Loop 24z ran the real platform lane-worker path without the chatgroup/proposal
layer:

```text
runtime_root=.goal-runs/2026-06-18/loop-24z-child-mcp-probe-180105
lane_id=loop24z-child-mcp-probe
worktree=/tmp/xmuse-loop-24z-child-mcp-probe-180105-exec
base_head_sha=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
```

The child Codex worker was spawned by the runner with explicit SSE MCP config:

```text
codex exec -m gpt-5.4 --ignore-user-config
-c mcp_servers.xmuse-platform.type="sse"
-c mcp_servers.xmuse-platform.url="http://localhost:8100/sse"
-C /tmp/xmuse-loop-24z-child-mcp-probe-180105-exec
```

The child worker ran the bounded verification command and used MCP tools:

```text
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 3.02s
mcp: xmuse-platform/query_knowledge started
mcp: xmuse-platform/query_knowledge (completed)
mcp: xmuse-platform/update_lane_status started
mcp: xmuse-platform/update_lane_status (completed)
mcp: xmuse-platform/update_lane_status started
mcp: xmuse-platform/update_lane_status (completed)
```

The runner consumed the committed state and advanced the lane through review to
safe final-action hold:

```text
state_history: pending -> dispatched -> gated -> awaiting_final_action
review_decision=merge
final_action_hold_id=final-35d2c1ff6ef8
execution_worktree_status=clean
```

Impact:

- The Codex child-worker MCP failure observed in Loop 24y is not a deterministic
  command/config failure by itself.
- Fullchain child-worker writeback is likely prompt/context/timing/session
  dependent, or dependent on the richer groupchat-to-lane path.
- Future fullchain probes should explicitly preserve the worker MCP requirement
  in the lane prompt and then verify the child writeback before review
  overwrites the final mutation audit.

Remaining gaps:

- This was not groupchat-driven and did not prove proposal-to-execution closure.
- Review used Codex, not OpenCode.
- `review_evidence_refs=[]` remains.
- Loop 24y still stands as negative fullchain evidence until one fullchain run
  proves child-worker MCP writeback and OpenCode review callback together.
- `docs/xmuse/production-closure-gap-ledger.md` was absent at the time of this loop.

Forbidden claims preserved:

```text
No natural peer-GOD groupchat completion.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F72. Child-worker MCP writeback now works in the real platform dispatch path

Severity: positive local-runtime capability finding.

Loops 24v2 and 24v3 prove that the temporary Codex lane worker can call xmuse
MCP from the actual platform dispatch path:

```text
mcp: xmuse-platform/query_knowledge started/completed
mcp: xmuse-platform/get_lane started/completed
mcp: xmuse-platform/update_lane_status started/completed
last_mutation_audit.tool=update_lane_status
```

Loop 24v2 exposed a real runner bug after the child worker moved the lane to
`executed` through MCP:

```text
InvalidTransitionError:
cannot transition ... from executed to executed
```

The executor now tolerates provider results when the lane is already
`executed` by MCP writeback. Loop 24v3 reran the direct platform path and
reached:

```text
status=awaiting_final_action
test_result=16 passed in 2.85s
final_action_hold_id=final-796b54c3c3bd
```

Impact:

- The previous "child worker MCP unavailable" gap is closed for direct platform
  dispatch.
- The runner no longer double-transitions `executed -> executed` after an MCP
  writeback.
- This finding by itself is not groupchat proof.

Remaining gap:

- Fullchain groupchat still had to be rerun after this fix.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready claim.
```

### F73. Loop 24w closes the child-worker MCP gap in the groupchat fullchain

Severity: positive fullchain local-runtime evidence with bounded proof.

Loop 24w drove the current strongest end-to-end local runtime chain:

```text
human @architect
-> Codex architect creates durable collaboration run
-> Codex execute peer records dispatchable feasibility verdict
-> OpenCode review peer records collaboration response
-> Codex architect emits one lane_graph proposal
-> OpenCode reviews the proposal
-> human approves proposal through Chat API
-> feature_lanes projection creates pending lane
-> platform runner dispatches lane
-> empty projected worktree is reclaimed/populated
-> Codex temporary child worker runs focused pytest
-> child worker writes executed through xmuse MCP update_lane_status
-> persistent OpenCode review emits merge verdict
-> no-auto-merge final-action hold is created
```

Key evidence:

```text
conversation_id=conv_8b45fbd686934ed1b8caa838add497df
collaboration_run=collab_3e8af1267b9c438e8baffab7b8bc080f
proposal_id=prop_710e6bfa21e54770ab2d3f042f2bf255
resolution_id=res_453de69afd6b4e4793a8b11825ecebb7
feature_id=loop24w-fullchain-mcp-writeback-final-hold
test_result=16 passed in 2.83s
last_mutation_audit.tool=update_lane_status
status=awaiting_final_action
final_action_hold_id=final-2e2b5cda36de
```

Impact:

- The strongest prior fullchain gap from Loop 24s is closed: execution no
  longer depends on stdout fallback for child-worker status truth.
- The lane worker used the projected execution worktree, not a sibling loop
  substitute.
- The chain still stops correctly at pending final action; no merge was
  performed.

Proof boundary:

```text
local_runtime_proof only
bounded package-boundary command
no GitHub/server-side truth
no production readiness
```

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F74. Persistent OpenCode final review remains weak evidence

Severity: evidence integrity issue.

Loop 24w reached final-action hold, but the final persistent OpenCode review
turn still reported MCP tools unavailable:

```text
MCP tools unavailable.
If update_lane_status were available via MCP, I would call ...
```

The review was ingested through persistent output and structured verdict
parsing:

```text
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_fallback=persistent
review_fallback_reason=verdict_merge
review_evidence_refs=[]
```

The review summary also over-claimed broad evidence that does not match the
narrow lane:

```text
All 61 tests pass
diff main..HEAD, 15 files, +2903/-21
ruff check on all changed source and test files
```

Impact:

- The review verdict is useful as persistent OpenCode output, but it is not
  strong review truth.
- `review_evidence_refs=[]` remains a blocker for stronger closure claims.
- The review prompt/context likely encourages broad branch-level inspection
  instead of lane-local evidence.

Required next behavior:

- Make persistent review turns use MCP tools when available, or fail closed
  when MCP is required.
- Populate `review_evidence_refs` from real lane artifacts: worker logs, gate
  result, diff refs, and exact tests.
- Tighten review prompts so they cannot over-claim unrelated branch-wide tests
  or broad diff scope.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F75. Persistent review now records non-empty evidence refs, but OpenCode MCP remains unavailable

Severity: partial positive finding; review truth still bounded.

Loop 24x reran the fullchain after wiring persistent review ingestion to the
same evidence-ref builder used by stdout review fallback. The chain reached:

```text
conversation_id=conv_4068032ab83c4f3f84af1a1f1f33789d
collaboration_run=collab_3e8d0fad4789461d9289de1fe5a25411
proposal_id=prop_f491283d696342c892737e4f9cf15c5a
resolution_id=res_5fcfd1116a764696ba11f3645f083dcf
feature_id=loop24x-persistent-review-evidence-refs-final-hold
status=awaiting_final_action
final_action_hold_id=final-d2b599c86940
```

The child worker still used real MCP writeback:

```text
test_result=16 passed in 2.73s
last_mutation_audit.tool=update_lane_status
```

The main F74 evidence-ref gap is closed for this path. Lane metadata and
review-plane verdict both recorded:

```text
review_evidence_refs=[
  "feature_lanes.json#lane=loop24x-persistent-review-evidence-refs-final-hold",
  "review_plane.json#task=rtask_6fb6d966f165416a8d580fee9e73511e",
  "logs/lane_prompts/loop24x-persistent-review-evidence-refs-final-hold.md"
]
```

Impact:

- Future final-action/GitHub gate logic no longer sees an empty
  `review_evidence_refs` list for persistent review fallback.
- The review-plane verdict now has the same evidence refs as the lane.
- This improves evidence lineage, but it does not turn persistent OpenCode
  fallback into GitHub review truth.

Remaining gaps:

- OpenCode final review still reports MCP tools are not exposed in the CLI
  session.
- The refs are structural lane/review/prompt refs; no gate report existed in
  this run.
- Persistent review remains local runtime provider output, not server-side
  review truth.

Required next behavior:

- Explore real OpenCode MCP/tool exposure through OpenCode config or a bounded
  xmuse callback bridge for review turns.
- Add gate-report or worker-log refs when those artifacts exist.
- Keep final-action hold as the default until GitHub/server facts can be
  observed.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F71. Codex child-style MCP writeback works in isolation after prompt tightening

Severity: positive isolation finding; fullchain follow-up required.

Loop 24t showed that plain `codex exec` without `--json` can call xmuse MCP:

```text
mcp: xmuse-platform/get_status started/completed
feature_id=probe-no-json
lane.status=unknown
```

Loop 24u then used a synthetic child-style prompt and a dispatched probe lane.
Codex called the MCP tools instead of falling back to stdout:

```text
mcp: xmuse-platform/query_knowledge started/completed
mcp: xmuse-platform/update_lane_status started/completed
feature_id=probe-child-mcp-writeback
status=executed
```

The durable lane mutation recorded:

```json
{
  "actor": "codex-probe",
  "reason": "synthetic_mcp_writeback_probe",
  "request_id": "probe-child-mcp-writeback",
  "tool": "update_lane_status"
}
```

Impact:

- The remaining child-worker MCP failure is not explained by Codex plain output
  mode or `--ignore-user-config`.
- Prompt behavior was too permissive: workers could declare MCP unavailable
  without first attempting a tool call.
- The execution prompt now requires at least one listed MCP tool attempt before
  stdout fallback.

Remaining gap:

- This is not yet fullchain proof. A future real lane execution must show the
  temporary child worker calling `query_knowledge` and `update_lane_status`
  inside the actual platform dispatch path.

Forbidden claims preserved:

```text
No clean fullchain child-worker MCP writeback claim yet.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F69. Empty projected worktree recovery now works in the real fullchain

Severity: positive local-runtime capability finding.

Loop 24s intentionally pre-created the projected lane execution directory as
an empty directory:

```text
/tmp/xmuse-loop-24s-reclaim-empty-worktree-rerun-162557-exec
```

The real approved lane dispatch recovered it into a populated git worktree:

```text
feature_id=loop24s-reclaim-empty-worktree-final-hold
branch=loop24s-reclaim-empty-worktree-final-hold
base_head_sha=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
git worktree=true
tests/xmuse/test_package_boundaries.py=present
worker_worktree=/tmp/xmuse-loop-24s-reclaim-empty-worktree-rerun-162557-exec
```

The lane worker then ran the bounded proof in that exact worktree:

```text
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 3.15s
changed_files=none
```

Impact:

- The Loop 24r empty-worktree contamination is fixed for empty or
  pytest-cache-only placeholders.
- The execution worker no longer selected a stale sibling loop checkout.
- The prompt now explicitly forbids substitute `/tmp` or sibling worktrees.

Proof boundary:

```text
local_runtime_proof only
not GitHub review truth
not merge truth
not production readiness
```

### F70. Fullchain peer shape improved, but MCP lane writeback and review evidence remain weak

Severity: evidence integrity issue.

Loop 24s is the strongest current fullchain shape:

```text
human @architect
-> Codex architect creates durable collaboration run
-> Codex execute peer records structured dispatchable verdict
-> OpenCode review peer records collaboration response
-> Codex architect emits lane_graph proposal
-> OpenCode peer reviews proposal
-> human approves proposal
-> dispatch bridge delegates to platform lane worker
-> projected worktree recovered
-> child worker runs package-boundary proof
-> persistent OpenCode review
-> awaiting_final_action
```

But two proof gaps remain:

```text
child_worker_stdout=MCP unavailable; stdout fallback follows.
persistent_review_stdout=MCP tools unavailable — using stdout fallback.
review_evidence_refs=[]
gate_profiles_missing=true
```

The persistent OpenCode review also failed to cite the actual agent spawn logs
and claimed no execution artifacts were found, despite the runner writing:

```text
logs/agent_spawns/loop24s-reclaim-empty-worktree-final-hold/20260618T083446Z.*
```

Impact:

- The chain can reach final-action hold, but lane writeback is still not a real
  MCP `update_lane_status` proof.
- Review must be treated as persistent provider review output plus runner
  ingestion, not as strong artifact-cited review truth.
- `review_evidence_refs=[]` remains a blocker for stronger closure claims.

Forbidden claims preserved:

```text
No clean child-worker MCP writeback claim.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F69. Loop 7S-R restored PR cadence and captured server-side merge proof

Severity: publication/control-plane boundary.

Latest GitHub PR before this loop was #149:

```text
#149 created_at=2026-06-20T11:07:09Z
#149 merged_at=2026-06-20T11:08:13Z
```

No newer PR existed because the following loops intentionally stayed local:

- Loop 7P-R proved dirty-target conflict protection in the source-root runtime.
- Loop 7Q-R audited GitHub publication authority and rejected reuse of already
  merged PR #46.
- Loop 7R-R built a clean candidate worktree from `origin/main`, but stopped
  before push/PR creation.

Loop 7S-R published that candidate as PR #150, then patched review-identified
target import safety gaps before merge:

```text
url=https://github.com/iiyazu/Cross-Muse/pull/150
branch=codex/loop7r-dirty-import-guard
head_sha=7c7115ab1bc9d12737aa0049b4212ffecadc00f3
state=MERGED
merged_at=2026-06-21T04:25:12Z
merge_commit=88cb2d9dc45131605d4d1b1665e470e5b0921391
```

Required checks passed:

```text
quality-gates=SUCCESS
contract-smoke-gates=SUCCESS
real-runtime-integration-gate=SUCCESS
```

Independent review truth was captured through a local review artifact because
branch protection does not require GitHub PR review:

```text
review_artifact=.goal-runs/2026-06-21/loop-7sr-publish-dirty-import-guard-pr150-20260621/codex-independent-review-7c7115a.md
reviewer=codex-independent-review
reviewed_head=7c7115ab1bc9d12737aa0049b4212ffecadc00f3
```

Final server-truth capture:

```text
proof_level=server_side_merge_proof
gap_reason=null
can_emit_pr_merged=true
```

Impact:

- PR cadence recovered without importing the dirty source-root worktree.
- The published unit is a small local final-action import guard, not a full
  groupchat/fullchain closure.
- Local review found and blocked real safety gaps before merge: non-git targets,
  git subdirectory targets, partial-copy risks, unbound decisions, and empty
  `changed_files`.
- `pr_merged` is now claimable for PR #150 only. Full xmuse closure, full
  groupchat/fullchain closure, and overnight readiness remain unclaimed.

### F70. Approved Grok-reviewed lane can enter runner, but review continuation is still pending

Severity: runtime topology / review continuation boundary.

Loop 2H resumed from the Loop 2G approved Grok-reviewed lane graph:

```text
runtime_root=/tmp/xmuse-loop2e-root-vyv2cv3y
lane=loop-2e-proposal-lane
resolution_id=res_3183f7781479438eb39be22bcbdfca85
graph_id=res_3183f7781479438eb39be22bcbdfca85-graph-v1
```

First runner attempt without an MCP server on port 8100 produced a real failure:

```text
state_history=pending -> dispatched -> executed -> gated -> gate_failed
worker_failure_reason=child_mcp_required_but_unavailable
review_failure_reason=review_no_verdict
```

This is not proof that worker execution succeeded. The worker explicitly reported
no edits and no tests because required MCP tools were unavailable.

After starting `xmuse-mcp-server` with
`XMUSE_ROOT=/tmp/xmuse-loop2e-root-vyv2cv3y`, the server health endpoint pointed
at the correct runtime root. A second runner attempt recovered the lane:

```text
state_history_delta=gate_failed -> gated
review_recovered_from=review_no_verdict
new_review_task_id=rtask_7db107867e65476faa141479eac08d42
new_review_task_status=pending
```

Impact:

- The approved Grok-reviewed proposal can reach runner dispatch and isolated
  worktree initialization.
- The runner's child-worker MCP dependency must be treated as part of the
  runtime topology; running the platform runner without the MCP server produces
  degraded execution evidence.
- The next boundary is review continuation for
  `rtask_7db107867e65476faa141479eac08d42`, not code patching.

Forbidden claims preserved:

```text
No accepted review verdict.
No final-action hold.
No GitHub/server truth for this runtime lane.
No fullchain closure.
No overnight readiness.
```

### F69. OpenCode collaboration confirmation needed broader formalization

Severity: real groupchat collaboration blocker, now locally fixed.

Loop 25z4b showed this failure:

```text
collaboration_run=collab_c7e03acea21e4109bbc1f9c83db89cd6
OpenCode message=@architect Confirmed ...
collaboration_runs.status=partial
collaboration_responses missing @review
proposal not emitted
```

Root cause:

- The OpenCode callback bridge recognized formal collaboration responses only
  when the request text included stronger `collaboration response` phrasing.
- The real architect prompt used `Please respond on collab_* confirming ...`,
  which was semantically clear but did not match the narrower detector.

Fix:

- OpenCode peer-chat writeback now treats `collab_*` plus
  respond/response/review/confirm wording as a collaboration response context.
- If the model returns plain text in that bounded context, the bridge records
  `chat_record_collaboration_response` before posting the chat reply.

Local proof:

```text
Loop 25z4c:
collaboration_runs.status=done
review_response=collab_resp_7420fa8b689343b2982c6e3132f5cbb5
OpenCode chat envelope callback_action=chat_record_collaboration_response
```

Boundary:

- This does not make arbitrary plain chat into proof. The recorded response is
  still constrained by a concrete `collab_*` run and participant authority.

### F70. Execution child must not perform acceptance review routing

Severity: authority-boundary bug, now locally fixed.

Loop 25z4c reached execution but failed after the child ran the real command:

```text
tests_run=uv run pytest tests/xmuse/test_package_boundaries.py -q
result=16 passed
lane.status=exec_failed
reason=chat_post_message returned unknown_god_session for required opencode
acceptance review routing
```

Root cause:

- The lane prompt contained review-routing language intended for the platform
  review phase.
- The temporary execution child interpreted that language as its own
  responsibility and attempted `chat_post_message` review handoff instead of
  reporting `executed`.

Fix:

- Execution prompts now include an explicit execution/review boundary:
  execution children must not perform acceptance review, proposal review,
  peer-chat routing, or final-action approval.
- `review_runtime`, `hold_final_action`, and review-routing phrases are
  parent-orchestrator metadata. After focused execution succeeds, the child
  should only report `executed`.

Local proof:

```text
Loop 25z4d:
execution_god_completed
lane transitioned to gated
review_god_started
lane_awaiting_final_action
```

### F71. Configured OpenCode review handoff can complete through peer-chat session layer

Severity: positive local runtime proof with remaining production gaps.

Loop 25z4d proved the configured review peer path in a bounded fullchain:

```text
review_runtime_requested=opencode
peer_routing_mode=required
peer_delivery_mode=configured_peer
persistent_review_identity=configured:part_adf60e5d1d464a818c835950797c6f2e
review_decision=merge
review_verdict.status=finalized
feature_lanes.status=awaiting_final_action
final_action_hold_id=final-d9749e2e1622
```

This supersedes the earlier `missing_conversation_id` and
`session_layer_unavailable` blockers for this bounded run.

Remaining limits:

- The gate still passed open with `gate_profiles_missing`.
- This is local runtime proof only.
- It is one no-edit package-boundary lane, not broad coding-task completion.
- No GitHub review truth, merge truth, live MemoryOS, full closure, or
  production-ready groupchat claim is made.

### F88. Review callback success summary is now bounded before durable writeback

Severity: positive contract guard with focused proof only.

Loop 25f patched the persistent OpenCode review callback bridge after Loop 25e
showed that provider prose could claim unsupported details such as an extra
test and scoped diff.

New writeback behavior for successful `reviewed` callbacks:

```text
review_summary=<bounded summary generated from durable evidence refs>
review_provider_summary=<raw provider prose>
review_summary_proof_level=provider_prose_bounded_by_evidence_refs
audit.reason=<bounded summary>
```

Focused guard:

```text
uv run pytest \
  tests/xmuse/test_opencode_persistent.py::test_review_callback_action_builds_update_lane_status_payload \
  tests/xmuse/test_opencode_persistent.py::test_review_writeback_bounds_success_summary_and_preserves_provider_prose \
  tests/xmuse/test_opencode_persistent.py::test_review_writeback_supplements_context_refs_with_current_spawn_artifacts \
  -q
-> 3 passed
```

Proof boundary:

```text
contract_proof / focused guard only
not fullchain proof
not review truth
not GitHub/server truth
```

Reason: the real Loop 25f fullchain did not reach final review. It failed
closed earlier at child execution because the Codex child worker did not get a
callable MCP tool channel.

Required next behavior:

- Rerun this through a real fullchain after child MCP writeback reliability is
  restored.
- Treat raw `review_provider_summary` as candidate prose, not proof.

### F89. Natural instructions with peer @mentions create direct-inbox noise

Severity: groupchat routing and delivery lifecycle gap.

Loop 25f intended the human to mention only `@architect`, but the prompt text
also contained `@execute` and `@review` in instructions. The mention parser
created direct human-to-execute and human-to-review inbox items:

```text
human_message=msg_e98db2b4ae2c43679aae0a6c4e4c8537
mentions_json=["@architect","@execute","@review"]
direct execute inbox=inbox_d8a30291aacb47babc494162063338d8
direct review inbox=inbox_62bf4583029445ae9943c5ae924535c3
```

Impact:

- Execute and review can respond to the human's instruction text before, or
  instead of, the architect's intended handoff.
- This can duplicate peer turns and blur source-message authority.
- Natural groupchat prompting is still fragile when role names are used as
  prose references.

Required next behavior:

- Add mention intent rules or quoting/escaping semantics so only intended
  addressees become inbox targets.
- Preserve natural language usability: users should be able to discuss roles
  without necessarily addressing those peers.

### F90. Child MCP writeback reliability remains a blocker after fail-closed guard

Severity: fullchain blocker.

Loop 25f approved a real groupchat-produced proposal and dispatched a real
isolated execution lane:

```text
conversation_id=conv_3da9f1be0de84a6c98221cde257ea7ab
proposal_id=prop_6e83532c3d3b43e18c64c77ea8c0710f
resolution_id=res_7f604be464fc443880863b903c25acc7
lane=loop25f-review-summary-bounds-final-hold
```

The child worker ran the requested command successfully:

```text
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 2.72s
```

But it reported:

```text
MCP unavailable in this session: `query_knowledge` and `update_lane_status`
were requested by the lane contract but no callable MCP tool channel for them
was exposed.
```

The runner correctly failed closed:

```text
status=exec_failed
failure_reason=child_mcp_required_but_unavailable
stdout_fallback_rejected=true
```

Impact:

- Loop 25f did not reach independent review or final-action hold.
- Review summary bounding has not yet been proven by real fullchain runtime.
- The next runtime target should be child MCP exposure/writeback reliability,
  not another review-summary tweak.

Required next behavior:

- Inspect why the child Codex invocation sometimes exposes xmuse MCP tools and
  sometimes only receives the textual tool list.
- Preserve fail-closed behavior; do not accept stdout fallback as success when
  the lane explicitly requires child MCP writeback.

### F86. Final review evidence refs can now be supplemented from runtime-root spawn artifacts

Severity: positive evidence-integrity finding with local-runtime proof boundary.

Loop 25e reran the real groupchat-to-final-hold chain after persistent OpenCode
review writeback was changed to merge callback refs with runtime-root fallback
refs.

Runtime:

```text
runtime_root=.goal-runs/2026-06-18/loop-25e-review-artifact-refs-193133
conversation_id=conv_f21cd83fc08c4f0d8196fb2ea88cb754
collaboration_run=collab_d67f0e218e8242af9d33a01dac709afe
proposal_id=prop_039016fcdd4f4660b31bdf63a5123d25
resolution_id=res_e996df624bb34b97baaf3549fb4ee885
lane=loop25e-review-artifact-refs
status=awaiting_final_action
final_action_hold_id=final-84d55cba307f
```

The lane context still had stale spawn refs:

```text
logs/lane_context/loop25e-review-artifact-refs/latest.json:
recent_agent_spawn_refs=[]
```

But durable final review evidence now includes the runtime-root child worker
artifacts:

```text
feature_lanes.json#lane=loop25e-review-artifact-refs
logs/lane_context/loop25e-review-artifact-refs/latest.json
logs/agent_spawns/loop25e-review-artifact-refs/20260618T114043Z.stderr.log
logs/agent_spawns/loop25e-review-artifact-refs/20260618T114043Z.stdout.log
logs/agent_spawns/loop25e-review-artifact-refs/20260618T114043Z.result.json
logs/agent_spawns/loop25e-review-artifact-refs/20260618T114043Z.prompt.md
logs/lane_prompts/loop25e-review-artifact-refs.md
```

Impact:

- F83/F85's specific stale-context evidence-ref weakness is closed for this
  path.
- The proof remains local runtime proof only.
- This does not imply GitHub review truth, merge truth, production readiness,
  full L8-L10 closure, or full L1-L11 closure.

Required next behavior:

- Keep `review_evidence_refs` grounded in formal xmuse artifacts, not provider
  prose.
- Add a stronger end-to-end check that asserts durable review evidence includes
  child spawn `stdout.log` and `result.json` after a real child execution.

### F87. OpenCode review summary can still overstate what it verified

Severity: review prose integrity gap.

Loop 25e final review durably cited the correct formal artifacts, but the review
summary said:

```text
test_package_boundaries.py 16 passed; new test_peer_chat_review_trigger.py 1 passed; diff scoped and correct
```

The approved lane requested only:

```text
uv run pytest tests/xmuse/test_package_boundaries.py -q
```

The lane was also a no-edit task, so "diff scoped and correct" is weak wording
unless it is tied to an observed empty diff artifact.

Impact:

- Durable artifact refs are currently stronger than review prose.
- Review summaries should not be treated as proof when they mention commands or
  diffs that are not supported by explicit artifacts.
- This is not a blocker for Loop 25e's final hold because the durable refs and
  child spawn artifacts are present, but it is a blocker for stronger review
  truth claims.

Required next behavior:

- Constrain review callback summaries to cited artifacts.
- Prefer structured fields for verified commands, verified diffs, and forbidden
  claims rather than free-form summary text.
- Fail closed or downgrade confidence when summary claims exceed evidence refs.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F76. OpenCode final review can now persist a verdict through callback/MCP

Severity: positive local-runtime capability finding.

Loop 24y reached final-action hold through a real runtime chain:

```text
human @architect
-> durable GOD groupchat
-> Codex architect coordination
-> Codex execute dispatchability response
-> OpenCode review peer callback response
-> architect lane_graph proposal
-> human approval
-> projected lane execution
-> configured OpenCode final review
-> opencode-review-callback /mcp update_lane_status
-> final-action hold
```

Key durable ids:

```text
runtime_root=.goal-runs/2026-06-18/loop-24y-review-callback-174307
conversation_id=conv_6c337d8dc6e44f3a988ba8e699d2517a
collaboration_run=collab_1b2cd614cd0945cfa5d0a9e80b8bbbbd
proposal_id=prop_f3bad19b869a45ca84e524b72d8353c9
resolution_id=res_f5dfc7956576453c94d8b40e1c174e72
lane_id=loop24y-review-callback-final-hold
review_peer_id=part_137bc7b6f15944a8af9227da7ae77fea
final_action_hold_id=final-6072caccaf63
```

The final lane state proves callback/MCP review writeback:

```text
status=awaiting_final_action
review_decision=merge
last_mutation_audit.actor=opencode-review-callback
last_mutation_audit.tool=update_lane_status
peer_delivery_mode=configured_peer
review_evidence_refs=[
  "logs/agent_spawns/loop24y-review-callback-final-hold/20260618T095252Z.stdout.log",
  "logs/agent_spawns/loop24y-review-callback-final-hold/20260618T095252Z.stderr.log"
]
```

Impact:

- Persistent OpenCode final review is no longer limited to stdout/runner
  ingestion for the merge verdict path.
- The runner now honors a review state already committed by MCP/callback and
  avoids a duplicate transition.
- The review plane received a finalized merge verdict with matching evidence
  refs.

Proof boundary:

```text
local_runtime_proof only
not GitHub review truth
not merge truth
not live MemoryOS
not full L8-L10 closure
not full L1-L11 closure
not production readiness
```

### F77. Child execution still lacks direct MCP writeback in the fullchain

Severity: evidence integrity gap.

Loop 24y execution worker ran the bounded command successfully:

```text
uv run pytest tests/xmuse/test_package_boundaries.py -q
16 passed in 2.96s
changed_files=none
```

But the worker still reported:

```text
MCP unavailable in this session: query_knowledge / update_lane_status were not exposed
```

Impact:

- Final review callback is now durable, but child execution writeback is still
  runner-mediated from exit status rather than a child-worker
  `update_lane_status` MCP call.
- Do not claim clean child-worker MCP writeback from Loop 24y.

Required next behavior:

- Continue debugging Codex child-worker MCP exposure in the actual lane worker
  path.
- Preserve the distinction between runner transition truth and child MCP
  writeback truth.

### F78. Peer-turn latency trace can contradict durable message truth

Severity: scheduler observability integrity issue.

Loop 24y recorded the initial architect turn as:

```text
delivery_mode=failed
degraded_reason=peer_response_timeout
```

The same turn also produced durable evidence:

```text
responded_message_id=msg_b75e3975c9d84194aeca2334aa54713c
tool_trace=chat_post_message
collaboration_run=collab_1b2cd614cd0945cfa5d0a9e80b8bbbbd
```

Impact:

- The scheduler latency trace is not always an authority for semantic peer
  success.
- Durable message, collaboration, proposal, and lane artifacts remain the
  stronger authority.

Required next behavior:

- Reconcile latency trace finalization with late-but-successful writeback.
- Do not use latency trace alone to prove or disprove groupchat success.

Forbidden claims preserved:

```text
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```

### F67. Noninteractive Codex can see xmuse MCP with explicit SSE config

Severity: positive isolation finding with narrow proof boundary.

Loop 24q directly launched Codex with `--ignore-user-config`, explicit SSE MCP
config, and `--json`. The process emitted an xmuse MCP tool call:

```text
server=xmuse-platform
tool=get_status
arguments={"feature_id":"probe"}
result={"feature_id":"probe","lane":{"feature_id":"probe","status":"unknown"},"active_session":null}
```

Impact:

- The MCP server and CLI config form are not the root cause by themselves.
- Child-worker MCP failure must be debugged in the full lane-worker path:
  prompt/tool discovery, cwd/worktree shape, or Codex execution mode.
- `--ignore-user-config` is useful for noninteractive workers because it avoids
  unrelated user-level skill/plugin behavior.

Proof boundary:

```text
local MCP exposure probe only
not groupchat proof
not lane writeback proof
not GitHub/server truth
```

### F68. Loop 24r reached final-action hold but child-worker evidence is contaminated

Severity: fullchain evidence integrity issue.

Loop 24r produced a real durable groupchat chain:

```text
conversation_id=conv_a9132f3c82c1464aa41f8ad10dd63b93
collaboration_run=collab_1823e6e885c342b68b60fa17ee233a3c
proposal_id=prop_a3276c587c3042a88400c98bfac52f0b
resolution_id=res_213bfc08866343c3ae334b3d96434b46
feature_lanes.status=awaiting_final_action
final_action_hold_id=final-396e3bf74291
```

It cannot be counted as clean child-worker MCP or clean worktree proof:

```text
first attempt: MCP unavailable stdout fallback, exec_failed
first attempt worktree: empty directory with only .pytest_cache
base_head_sha=unknown
second attempt: MCP unavailable stdout fallback, executed
second attempt worktree: /tmp/xmuse-loop-24l-package-boundary-final-hold-145243-exec
```

Impact:

- The chain can recover to final-action hold, but the evidence source is not
  the projected lane worktree.
- Review accepted a pragmatic retry that used stale sibling state. That must be
  treated as contaminated evidence, not a clean pass.
- Future fullchain loops must fail closed if the projected lane worktree is not
  a populated git checkout.

Required next behavior:

- Fix or guard lane worktree provisioning before further fullchain claims.
- Prevent workers from searching `/tmp` for substitute worktrees.
- Preserve the child-worker MCP gap until a real `update_lane_status` call is
  observed from the lane worker.

Forbidden claims preserved:

```text
No clean child-worker MCP writeback claim.
No GitHub review truth.
No merge truth.
No ready_to_merge or pr_merged.
No live MemoryOS.
No full L8-L10 closure.
No full L1-L11 closure.
No overnight readiness.
No production-ready groupchat claim.
```
