# xmuse runtime operation evidence ledger

This file records local runtime operation attempts. It is an evidence ledger,
not a release-readiness report.

Do not read any entry here as proof of:

- full xmuse closure;
- GitHub review truth or merge truth;
- `ready_to_merge` or `pr_merged`;
- live MemoryOS proof;
- natural peer-GOD groupchat proof;
- full L8-L10 or L1-L11 closure.

## 2026-06-20 Reusable Fullchain Driver Sentinels

Reusable driver under test:

```text
scripts/run_fullchain_docs_sentinel.py
```

Command shape:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root "$RUN_ROOT" \
  --execution-worktree "$EXEC_ROOT" \
  --feature-id "$FEATURE_ID" \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Loop 26i artifact root:

```text
.goal-runs/2026-06-20/loop-26i-post-main-fullchain-driver-023933/
```

Observed local runtime chain:

- human demand to `@architect`;
- durable Codex architect, Codex execute, and OpenCode review participants;
- execute collaboration response recorded;
- one `lane_graph` proposal accepted;
- isolated docs lane executed in
  `/tmp/loop-26i-post-main-fullchain-driver-023933-exec`;
- gate passed;
- OpenCode review peer metadata recorded;
- lane stopped at `awaiting_final_action`;
- `final_actions.json` held a pending merge action;
- services cleaned up and ports were no longer listening.

Post-run stricter driver recomputation showed 26i does not prove healthy
executor peer handoff because the lane recorded
`peer_delivery_mode=auto_persistent_fallback` and
`peer_result_status=delivery_failed`.

Loop 26j artifact root:

```text
.goal-runs/2026-06-20/loop-26j-strict-fullchain-driver-024845/
```

Observed local runtime chain:

- human demand to `@architect`;
- durable Codex architect, Codex execute, and OpenCode review participants;
- execute collaboration response recorded;
- accepted proposal dispatched into isolated docs execution;
- isolated docs lane executed in
  `/tmp/loop-26j-strict-fullchain-driver-024845-exec`;
- gate passed;
- OpenCode review peer metadata recorded;
- lane stopped at `awaiting_final_action`;
- `final_actions.json` held a pending merge action;
- services cleaned up and ports were no longer listening.

Post-run stricter driver recomputation showed 26j does not prove the proposal
contract because two related `lane_graph` proposals were emitted for the same
feature id:

```text
prop_d9dded0ae4504326b972c8b3f7003d53 accepted
prop_bc94c62ae51249e98d123164b4f0e4b3 open
```

Classification: local runtime contract evidence only. These runs do not prove
production readiness, GitHub review truth, merge truth, live MemoryOS, or full
closure.

Loop 26k artifact root:

```text
.goal-runs/2026-06-20/loop-26k-proposal-idempotency-fullchain-030741/
```

Observed after adding collaboration lane-graph semantic deduplication:

- human demand to `@architect`;
- execute collaboration response recorded;
- one related `lane_graph` proposal existed for the feature id;
- proposal was accepted and dispatched;
- isolated docs lane executed in
  `/tmp/loop-26k-proposal-idempotency-fullchain-030741-exec`;
- gate passed;
- executor peer handoff recorded `peer_delivery_mode=configured_peer`;
- OpenCode review peer metadata recorded;
- lane stopped at `awaiting_final_action`;
- `final_actions.json` held a pending merge action;
- services cleaned up and ports were no longer listening.

Driver success checks were all true:

```text
single_related_lane_graph_proposal=true
approved_proposal_accepted=true
execution_peer_handoff_not_degraded=true
lane_awaiting_final_action=true
gate_passed=true
isolated_note_matches=true
opencode_review_peer_recorded=true
review_verdict_finalized=true
review_task_verdict_emitted=true
final_action_hold_pending=true
proposal_has_no_review_runtime=true
```

Classification: stronger local runtime contract evidence for the docs-only
sentinel only. It still does not prove production readiness, GitHub review
truth, merge truth, live MemoryOS, or full closure.

Loop 26l artifact root:

```text
.goal-runs/2026-06-20/loop-26l-product-driver-success-artifact-032330/
```

Observed product/tooling demand:

- human demand asked `@architect` to route a real code change through
  groupchat;
- architect and execute produced a completed collaboration run with an
  executable verdict;
- one related `lane_graph` proposal was accepted;
- isolated execution changed only `scripts/run_fullchain_docs_sentinel.py`;
- gate passed;
- OpenCode persistent review returned merge;
- lane stopped at `awaiting_final_action`;
- `final_actions.json` held a pending merge action;
- services cleaned up and ports were no longer listening.

Candidate diff:

```text
scripts/run_fullchain_docs_sentinel.py | 17 ++++++++++++++++-
```

Driver success checks were all true for the product-code run, including
configured executor handoff, one related proposal, gate pass, finalized review
verdict, and pending final-action hold.

Residual observation: the conversation also contained an earlier collaboration
run that remained `running` while the second collaboration run completed and
fed the accepted proposal. This does not invalidate the accepted lane proof,
but it is a remaining groupchat lifecycle/idempotency boundary.

Classification: local runtime evidence for a small xmuse code-change demand.
It still does not prove production readiness, GitHub review truth, merge
truth, live MemoryOS, or full closure.

## 2026-06-17 Windows/WSL Run

Runtime root:

```text
/home/iiyatu/projects/python/xmuse/.goal-runs/fullchain-20260617/
```

The run used an isolated `XMUSE_ROOT` under `.goal-runs/`. Repository runtime
state such as `xmuse/chat.db` and `xmuse/feature_lanes.json` was not the target
runtime root. The isolated service root did contain its own
`service-run/root/feature_lanes.json`.

### Computer Use

Requested path: drive visible Windows operation through the installed
`computer-use` capability.

Result: blocked before any Windows app automation could run. Bootstrap failed
twice with:

```text
Package subpath './dist/project/cua/sky_js/src/targets/windows/internal/computer_use_client_base.js' is not defined by "exports" in C:\Users\iiyatu\AppData\Local\OpenAI\Codex\runtimes\cua_node\a89897d3d9baa117\bin\node_modules\@oai\sky\package.json
```

Classification: environment blocker. No Windows UI automation evidence was
produced.

### Fake Groupchat Demos

Command shape:

```bash
uv run python scripts/demo_fake_groupchat.py \
  --xmuse-root .goal-runs/fullchain-20260617/demo-1 \
  --message "实际链路测试 1：请生成一个最小可执行交付计划。"
```

Observed:

```text
demo-1: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_77688c7066d24600a6c54de6a6bc9c3a

demo-2: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_08e218b7a4624ef3832fff9be3f3788d

demo-3: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_708400b9a3f84f888fb5cc3870799231
```

Classification: local fake-layer writeback contract evidence only. This is not
real Ray/Codex app-server proof.

### Service Chain Startup

Started:

```bash
XMUSE_ROOT="$ROOT" uv run python -m xmuse.chat_api
XMUSE_ROOT="$ROOT" uv run python -m xmuse.mcp_server
XMUSE_ROOT="$ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$ROOT" --peer-chat \
  --mcp-port 8100 --max-hours 0.20
```

Health endpoints returned:

```text
GET http://127.0.0.1:8201/health -> 200, service=xmuse-chat-api
GET http://127.0.0.1:8100/health -> 200, service=xmuse-mcp
```

The services were stopped after the test. Later checks showed no listeners on
ports `8100` or `8201`.

### REST + MCP Proposal Path

Goal: create a conversation, post a human mention, read/write via MCP, emit a
proposal, approve it, and verify lane projection.

Observed endpoint boundary:

- `chat_create_conversation` is exposed on `/mcp`, not `/mcp/chat`.
- `/mcp/chat` returned `tool is not exposed on this MCP endpoint` for
  `chat_create_conversation`.

Successful partial path:

```text
conversation_id=conv_2e47dc6c612745bda55d3fdfcbd58f8a
architect_session=god-90707580c68744668e39962efb12990e
human_message_id=msg_4a5cec9b1ae1431085d91fb7b63d7dff
reply_message_id=msg_900a3ed410be45bf8b41207966a519e5
proposal_id=prop_d3a2945821dc4e4c8c844c3c43ed8af5
approval_id=res_88698bd01e2f41fe91ce4779d221974e
```

Approval wrote an isolated lane projection:

```text
feature_lanes.json exists: true
top-level keys: lanes, projection_revision
lane count: 1
timeline card_counts: health_summary=1, lane_graph=1, proposal=1,
worklist_summary=1, total=4
```

Classification: REST + MCP + proposal/projection path evidence. It is not
assistant peer writeback proof and not closure proof.

### Native Platform Runner Peer-Chat Path

Goal: post a human message and let live `platform_runner --peer-chat` claim the
inbox item and perform native Codex writeback through MCP.

Observed failure:

```text
conversation_id=conv_5832221585f4461aacaa2018af46faa1
architect_participant=part_6dc865d89fa74a6caa1d0f510cdb060e
human_message_id=msg_54b0030b24094b06890286ebcb355c19
delivery_mode=failed
total_latency_ms=2
degraded_reason=Cannot reuse conversation participant
'conv_5832221585f4461aacaa2018af46faa1:part_6dc865d89fa74a6caa1d0f510cdb060e':
existing registered session does not match requested role/agent
```

No assistant reply appeared after polling. The inbox item became failed.

Classification: negative product evidence. The runner claimed the inbox item,
but durable GOD session reuse validation blocked delivery before a Codex turn.

### Execution Lane Side Effect

Approving the test proposal while the runner was active created and dispatched
a real lane in the isolated runtime root:

```text
feature_id=actual-fullchain-evidence-docs
status=gate_failed
failure_reason=review_non_zero_exit
failure_layer=review
provider_profile_ref=codex.default
projection_revision=12
```

Important risk: although `XMUSE_ROOT` was isolated, the generated lane's
`worktree` pointed at `/home/iiyatu/projects/python/xmuse`, so proposal approval
with an active runner can still trigger real provider work against the repo
worktree.

Classification: operator-safety finding, not successful chain evidence.

## 2026-06-18 Repeated Max-Accessible Runs

This section is maintained by the current run. It should record only commands
that were actually run and the proof boundary they support.

Runtime root for command-line demos and service smoke:

```text
/home/iiyatu/projects/python/xmuse/.goal-runs/fullchain-20260618/
```

Pytest-based runtime tests used pytest `tmp_path` roots under `/tmp`.

### Contract and Boundary Verification

Command:

```bash
uv run pytest tests/xmuse/test_minimal_closure_spine.py \
  tests/xmuse/test_package_boundaries.py -q
```

Observed:

```text
25 passed in 3.44s
```

Classification: `closure_spine` contract and package-boundary proof only.
This does not prove the runtime chain feeds `closure_spine`.

### Local Full-Chain and Fake App-Server Runtime

Command:

```bash
uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_full_chain_real_run_fresh \
  tests/xmuse/test_full_chain_real_run.py::test_full_chain_real_run_with_restart_resume \
  tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server \
  -q
```

Observed:

```text
3 passed, 3 warnings in 6.90s
```

Classification: local runtime contract and fake app-server restart/resume
evidence. This is not real provider proof.

### Fake Groupchat Demos

Commands:

```bash
uv run python scripts/demo_fake_groupchat.py \
  --xmuse-root .goal-runs/fullchain-20260618/demo-1 \
  --message "..."

uv run python scripts/demo_fake_groupchat.py \
  --xmuse-root .goal-runs/fullchain-20260618/demo-2 \
  --message "..."

uv run python scripts/demo_fake_groupchat.py \
  --xmuse-root .goal-runs/fullchain-20260618/demo-3 \
  --message "..."
```

Observed:

```text
demo-1: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_a20123018e674af7a26fc8a292438962

demo-2: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_5d4ca43f37de4b9b8fc747e8c063df10

demo-3: fake-groupchat-demo-ok, scheduler_happy_path=1,
conversation_id=conv_31fcc12a611546dd845505150d2e07e9
```

Classification: fake-layer writeback contract evidence only.

### Real Ray / Codex App-Server Restart-Resume

Command, run twice:

```bash
uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume \
  -q -s
```

Observed first run:

```text
1 passed, 4 warnings in 34.40s
provider_session_reused=true
turn 1: delivery_mode=mcp_writeback, writeback_ms=13491,
has_chat_post_message_stage=true, has_stdout_fallback=false
turn 2: delivery_mode=mcp_writeback, writeback_ms=10983,
has_chat_post_message_stage=true, has_stdout_fallback=false
```

Observed second run:

```text
1 passed, 4 warnings in 32.83s
provider_session_reused=true
turn 1: delivery_mode=mcp_writeback, writeback_ms=13803,
has_chat_post_message_stage=true, has_stdout_fallback=false
turn 2: delivery_mode=mcp_writeback, writeback_ms=11401,
has_chat_post_message_stage=true, has_stdout_fallback=false
```

Classification: local runtime proof that the Ray/Codex app-server path can
create a provider thread, write back through MCP, and reuse the provider
session after runner restart. It is not GitHub/server/review truth.

### Real Ray / Codex App-Server Soak

Command, run twice:

```bash
uv run pytest \
  tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume \
  -q -s
```

First observed result:

```text
FAILED in 66.39s
conversation_id=conv_555eba4c10ef40dab6582d7c706887f0
inbox_item_id=inbox_d2c4a53fe518493d84eba1e03e8375f7
inbox status=failed
failure_reason=peer_no_inbox_side_effect
delivery_mode=failed
degraded_reason=peer_no_inbox_side_effect
peer_turn_mcp_tool_traces count=0
chat_stream content="real ray mcp soak fresh 1 ok"
durable assistant message count=0
```

Failure classification: the provider produced visible stream text, but did not
call MCP `chat_post_message`, so the scheduler failed closed because there was
no durable inbox side effect.

Second observed result:

```text
1 passed, 4 warnings in 119.67s
turns=8
all delivery_mode=mcp_writeback
all degraded_reason=null
total_latency_ms: max=32816, median=8552, p95=32816
slowest_stage=mcp_tools_ready->chat_post_message, 24665ms
```

Classification: the soak path is accessible and can complete eight real
app-server turns across restart/resume, but it is not deterministic enough to
serve as closure proof without preserving the first failure as a product
finding.

### External Chat API + MCP Service Smoke

Runtime root:

```text
.goal-runs/fullchain-20260618/service-smoke/root
```

Started:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/fullchain-20260618/service-smoke/root \
  uv run python -m xmuse.chat_api

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/fullchain-20260618/service-smoke/root \
  uv run python -m xmuse.mcp_server
```

Observed:

```text
GET http://127.0.0.1:8201/health -> 200, service=xmuse-chat-api
GET http://127.0.0.1:8100/health -> 200, service=xmuse-mcp
POST /api/chat/conversations -> 201,
conversation_id=conv_809183d62c3b4bf8ada581d8833efb09
POST /api/chat/conversations/{id}/messages -> 201,
message_id=msg_617340f719ba47448ec41eb572673357,
inbox_items=1
```

Initial MCP read attempt with only `conversation_id` and `@architect` failed
closed:

```text
chat_read_inbox missing required arguments: god_session_id, participant_id
```

The public participants endpoint returned the required mapping:

```text
architect_participant_id=part_0598f5fc3cb64c70895d2c4099ecc481
architect_god_session_id=god-ef000a6275aa41f78d3e960cfe46e2b3
```

MCP read then succeeded:

```text
tool=chat_read_inbox
isError=false
inbox_item_id=inbox_d2ed1be169af4143beb84cc82f2c3ff3
status=unread
target_role=architect
```

The runner was not started and no proposal was approved during this service
smoke. The services were stopped after the test. Later checks showed no
listeners on ports `8100` or `8201`.

Classification: external process REST + MCP durable-store smoke. It does not
prove peer provider writeback or lane execution.

### OpenCode Peer Runtime Kernel And Durable Writeback

Runtime root:

```text
.goal-runs/2026-06-18/loop-2-opencode-runtime-kernel/fresh-root-devnull-Bl9QGL
```

Started:

```bash
XMUSE_ROOT="$ROOT" uv run python -m xmuse.chat_api
XMUSE_ROOT="$ROOT" uv run python -m xmuse.mcp_server
```

Created a deterministic GOD groupchat with review overridden to OpenCode:

```text
conversation_id=conv_7a54d4ec0f184edebcbc4e64dd6f981b
review_participant=part_79cad55f43ca4398a8e1df1c36e03f69
review_god_session=god-7e44245d679a4ec49433c5ec8a3a7aef
review_cli_kind=opencode
review_model=deepseek-v4-flash
```

Human message:

```text
message_id=msg_4eb5878f15214145b471ae754e8108b0
inbox_item_id=inbox_56450f7f20a045fe9e9e6c40d5cf433b
target=@review
```

Runner:

```bash
timeout 120 env XMUSE_ROOT="$ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 \
  uv run xmuse-platform-runner --xmuse-root "$ROOT" --peer-chat \
  --mcp-port 8100 --max-hours 0.015
```

Observed durable state:

```text
inbox status=read
responded_message_id=msg_d3ddc9f7b4e94ad280f3ac80e47249ab
assistant author=part_79cad55f43ca4398a8e1df1c36e03f69
assistant content=OPENCODE_REVIEW_READY fresh DEVNULL durable writeback
assistant envelope writeback_path=opencode_callback_bridge
delivery_mode=mcp_writeback
degraded_reason=null
total_latency_ms=6570
peer_turn_mcp_tool_traces=chat_post_message
```

The OpenCode GOD session record was safely migrated from bootstrap metadata to
include `prompt_fingerprint` and `worktree`.

Classification: local runtime proof for one OpenCode peer durable callback
writeback through the native peer scheduler. It is not natural peer-GOD
groupchat proof by itself.

Discarded handoff attempt: a later human prompt in this root directly included
`@review`, so REST mention resolution created both architect and review inbox
items immediately. That attempt is not used as peer-to-peer handoff proof.

### Codex To OpenCode Peer Handoff

Runtime root:

```text
.goal-runs/2026-06-18/loop-2-opencode-runtime-kernel/handoff-root-WiktHo
```

Created a deterministic GOD groupchat with Codex architect and OpenCode review:

```text
conversation_id=conv_fb918c1a25b245a78056b34f775446a6
architect_participant=part_8ab507d39c3c42b89c0c57b1af1d2ddd
review_participant=part_f8e592acf1fb4b3187f3470555111185
review_god_session=god-5182ff67ee114a0ab625a675743efcba
```

First handoff runner:

```bash
timeout 240 env XMUSE_ROOT="$ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 \
  uv run xmuse-platform-runner --xmuse-root "$ROOT" --peer-chat \
  --mcp-port 8100 --max-hours 0.04
```

Observed first handoff:

```text
human -> @architect only
architect inbox=inbox_f93819702ad547a39a4ca6c0f7785d01, status=read
codex message=msg_10155da078a74257bef0bc0ff7cb6eed,
  content=@review Please reply exactly OPENCODE_HANDOFF_READY.
codex mention message=msg_056e7ce94ea346afa1d17280bc319597
review inbox=inbox_35e9ec0df72b4fae94e83cd8b7ec6715, status=read
opencode message=msg_3048e0bdc2cc46e5bbc3032da62a971c,
  content=OPENCODE_HANDOFF_READY,
  writeback_path=opencode_callback_bridge
both turns delivery_mode=mcp_writeback
both turns degraded_reason=null
```

Second handoff after runner restart used the same conversation:

```bash
timeout 240 env XMUSE_ROOT="$ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 \
  uv run xmuse-platform-runner --xmuse-root "$ROOT" --peer-chat \
  --mcp-port 8100 --max-hours 0.04
```

Observed second handoff:

```text
human -> @architect only
architect inbox=inbox_649bc01b1a27405d96163a6e111bbda6, status=read
codex message=msg_d4c9be2d52134255bde2f7bf440ab6eb,
  content=@review Please reply exactly OPENCODE_HANDOFF_READY_TWO.
codex mention message=msg_a661ac652c074cb5b83ecb4aa710fea3
review inbox=inbox_cd783e3eab0347c988c77756b42e89b4, status=read
opencode message=msg_78a6bed3cf5e48f58be02068b594fabe,
  content=OPENCODE_HANDOFF_READY_TWO,
  writeback_path=opencode_callback_bridge
both turns delivery_mode=mcp_writeback
both turns degraded_reason=null
```

Classification: local runtime proof for repeated Codex-to-OpenCode durable
peer handoff across runner restart/resume. It is not fullchain execution,
review truth, merge truth, live MemoryOS, full L8-L10 closure, or full L1-L11
closure.

Remaining gap: `god_sessions.json` does not yet persist the OpenCode
provider-native `sessionID`, so provider-native memory continuity beyond the
shim process remains unproven.

### Groupchat Proposal And Review Trigger Payload

Initial runtime root:

```text
.goal-runs/2026-06-18/loop-6-proposal-root-hKdIfX
```

Goal: have Codex architect create a durable `lane_graph` proposal using
`chat_emit_proposal`, without approval or dispatch.

Observed initial proposal:

```text
conversation_id=conv_913110310a3d4244b1995895ae3e1ae3
proposal_id=prop_f9229b1926b546349803ca5fd93cac5a
proposal_type=lane_graph
status=open
feature_id=proposal-smoke-no-dispatch
architect tool trace=chat_emit_proposal
architect delivery_mode=mcp_writeback
```

No-dispatch check:

```text
feature_lanes.json exists=false
lane_graphs.json exists=false
graph_sets.json exists=false
```

The automatic review trigger reached OpenCode review, but the review inbox
payload did not include readable proposal content:

```text
review_inbox=inbox_0af29f72fe114b428d15f8a83ad55223
review payload keys=reviewable_type, source_message_id, trigger_mode
opencode review reply=no inbox item content was delivered
```

Classification: proposal creation local runtime proof, plus negative evidence
for the automatic review-trigger payload contract.

After fixing the review-trigger payload, the same path was rerun.

Runtime root:

```text
.goal-runs/2026-06-18/loop-6-review-payload-root-UfuahZ
```

Observed fixed proposal path:

```text
conversation_id=conv_1f3e17988cf748a48e4aed0bf0135601
proposal_id=prop_ab84aa38b9614bdaa628b854559359ed
proposal_type=lane_graph
status=open
feature_id=proposal-review-payload
references=chat:msg_d4b3b55f96b24e5c9d070b9fe3c1d560,
  inbox:inbox_22efbcc395254f2888bf0b5efee6f590
architect tool trace=chat_emit_proposal
architect delivery_mode=mcp_writeback
```

Observed fixed review trigger:

```text
review_inbox=inbox_6ae7f911bf2c4b39b325373d178dbe8a
status=read
payload.content includes summary, lane feature_id, lane prompt, references,
  and source proposal message content
opencode message=msg_64c55840555a4cab8ec4dc3ba49f84b5
opencode reply starts with **PASS.**
opencode writeback_path=opencode_callback_bridge
review delivery_mode=mcp_writeback
review degraded_reason=null
review tool trace=chat_post_message
```

No-dispatch check after the fixed run:

```text
feature_lanes.json exists=false
lane_graphs.json exists=false
graph_sets.json exists=false
```

Classification: local runtime proof that the real groupchat can produce a
durable proposal and automatically route a readable proposal review trigger to
OpenCode review. This is not approval, isolated execution, independent review
truth, merge truth, live MemoryOS, full L8-L10 closure, or full L1-L11 closure.

### Loop 7 Isolated Execution And Branch Metadata

Initial raw note:

```text
.goal-runs/2026-06-18/loop-7-isolated-execution/notes.md
```

The first isolated execution probe approved the fixed Loop 6 proposal with
Chat API configured to use a detached git execution worktree:

```text
execution_worktree=/tmp/xmuse-loop7-worktree-5XGtji
proposal_id=prop_ab84aa38b9614bdaa628b854559359ed
resolution_id=res_b3cc32974f614895b24cf79e4c5a62f9
```

Runner evidence:

```text
execution_god_started
execution_god_completed
gate_profiles_missing
review_god_started
merge_context_missing
```

Final lane state:

```text
status=failed
worker_worktree=/tmp/xmuse-loop7-worktree-5XGtji
gate_passed=true
review_decision=merge
review_summary=review accepted
merge_failure_reason=merge_context_missing
merge_failure_detail=missing required integration metadata: branch
failure_reason=merge_context_missing
```

Classification: local runtime proof that proposal approval can project to an
isolated worktree and that runner execution/review can operate there, but the
chain was blocked before integration because the projected lane had `worktree`
without `branch`.

Current-origin/main repro before fix:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-repro-030440/root
code_worktree=/tmp/xmuse-loop7-code-yC0yJ1
execution_worktree=/tmp/xmuse-loop7-exec-2Pe8dh
conversation_id=conv_46dd6c58c2d34e8d823664de4e68981a
proposal_id=prop_347c75fdc6274c85a1ec87aefed3996e
resolution_id=res_b943c89c3ee54c409040d1298fa174ea
```

The first repro proposal included a `collaboration:*` reference and approval
failed closed with:

```text
dispatch_gate_blocked: blocked_unknown_run
```

A second no-collaboration proposal reached approval. Projection wrote:

```text
feature_id=proposal-review-payload-loop7-no-collab
status=pending
worktree=/tmp/xmuse-loop7-exec-2Pe8dh
branch missing
```

Runner then reproduced the original blocker:

```text
execution_god_completed
gate_profiles_missing
review_god_started
merge_context_missing
merge_failure_detail=missing required integration metadata: branch
```

After the targeted fix, the same chain was rerun:

```text
runtime_root=.goal-runs/2026-06-18/loop-7-fixed-032235/root
execution_worktree=/tmp/xmuse-loop7-fixed-exec-6KzR0I
conversation_id=conv_79b70da978e743aba81dd741fb64b2c4
proposal_id=prop_8c78b9b3acc242dfb9d22a202d793b4c
resolution_id=res_79ee7f74d22e419c85ef18cd8fa2ea81
```

Fixed dispatch evidence:

```text
lane_worktree_initialized
branch=proposal-review-payload-loop7-fixed
base_head_sha=109c4a4eae8b2a0a492fbe8e11d100a0bc76ee98
worktree=/tmp/xmuse-loop7-fixed-exec-6KzR0I
```

The execution worktree was no longer detached:

```text
git -C /tmp/xmuse-loop7-fixed-exec-6KzR0I branch --show-current
proposal-review-payload-loop7-fixed
```

The run moved past `merge_context_missing`, then exposed a new review/rework
boundary:

```text
first review_decision=rework
second execution exit_code=0
second review exit_code=0
second review stdout empty
final status=gate_failed
failure_reason=review_no_verdict
failure_layer=review
```

Classification: local runtime proof that the branch metadata blocker is fixed
for an existing detached execution worktree. This is not fullchain completion:
the next blocker is review verdict / rework-loop reliability, and the isolated
candidate branch ended with no durable candidate diff.

### Loop 7 Review Plane Closure Recheck

Runtime root:

```text
.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo
```

Execution worktree:

```text
/tmp/xmuse-loop7-reviewfix-exec-x74XQV
```

Preparation:

```bash
git worktree add --detach /tmp/xmuse-loop7-reviewfix-exec-x74XQV HEAD
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo \
XMUSE_EXECUTION_WORKTREE=/tmp/xmuse-loop7-reviewfix-exec-x74XQV \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-reviewfix-o34mKo \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.18
```

Health endpoints returned `200`:

```text
GET http://127.0.0.1:8201/health -> service=xmuse-chat-api
GET http://127.0.0.1:8100/health -> service=xmuse-mcp
```

The probe created and approved one proposal through real HTTP:

```text
conversation_id=conv_9097d729ea87412697297e236122de25
proposal_id=prop_f4782ea5cb6d46acb80f1ff388bd6e7e
resolution_id=res_409d1a1dad7849d7a9bdfa1ca0513c50
feature_id=proposal-review-payload-loop7-reviewfix
```

Runner evidence:

```text
lane_worktree_initialized
execution_god_started
execution_god_completed
gate_profiles_missing
review_god_started
lane_merged
```

Final lane state:

```text
status=merged
branch=proposal-review-payload-loop7-reviewfix
base_head_sha=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
worktree=/tmp/xmuse-loop7-reviewfix-exec-x74XQV
review_decision=merge
review_summary=review accepted
review_task_id=rtask_c909cc6b4fc642fb81da8f5cf83e9f87
```

Review plane evidence:

```text
review_task.status=verdict_emitted
review_task.verdict_id=verdict-proposal-review-payload-loop7-reviewfix
review_verdict.decision=merge
review_verdict.status=finalized
review_verdict.task_id=rtask_c909cc6b4fc642fb81da8f5cf83e9f87
```

Execution worktree evidence:

```text
git -C /tmp/xmuse-loop7-reviewfix-exec-x74XQV branch --show-current
proposal-review-payload-loop7-reviewfix

git -C /tmp/xmuse-loop7-reviewfix-exec-x74XQV log --oneline -3
2f17ee5 feat(xmuse): apply lane proposal-review-payload-loop7-reviewfix
110dd47 fix: include proposal content in review triggers
8447379 feat: add opencode god peer runtime kernel
```

Operator cleanup:

```text
The runner auto-merge also advanced the control branch with local runtime
commits:

f17144a feat(xmuse): merge lane proposal-review-payload-loop7-reviewfix
2f17ee5 feat(xmuse): apply lane proposal-review-payload-loop7-reviewfix

The control branch was reset back to:
110dd47b435e44e7b608ac5b880ad4aebcf79ab0

The runtime probe assertion change was removed from the control worktree.
```

The services were stopped after the test. Later checks showed no listeners on
ports `8100` or `8201`.

Classification: local runtime evidence that the approved proposal path can
dispatch into an isolated execution worktree, attach a lane branch, execute,
gate, persist a review-plane verdict, and mark the lane merged for this small
probe. It also proves that `execution_worktree` alone does not isolate the
integration target: auto-merge can still mutate the control branch unless merge
is disabled or redirected. This does not prove GitHub review truth, server-side
truth, live MemoryOS, natural peer-GOD fullchain completion, or full
L8-L10/L1-L11 closure. The previous empty-stdout `review_no_verdict` branch was
not reproduced in this positive recheck; focused tests cover that fail-closed
recording path.

### Loop 7 No-Auto-Merge Runtime Probe

Runtime root:

```text
.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv
```

Execution worktree:

```text
/tmp/xmuse-loop7-no-auto-merge-exec-GKbThV
```

Preparation:

```bash
git worktree add --detach /tmp/xmuse-loop7-no-auto-merge-exec-GKbThV HEAD
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv \
XMUSE_EXECUTION_WORKTREE=/tmp/xmuse-loop7-no-auto-merge-exec-GKbThV \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-7-no-auto-merge-9dEsNv \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.18 \
  --no-auto-merge
```

Health endpoints returned `200`:

```text
GET http://127.0.0.1:8201/health -> service=xmuse-chat-api
GET http://127.0.0.1:8100/health -> service=xmuse-mcp
```

The probe created and approved one proposal through real HTTP:

```text
conversation_id=conv_5b77caf76967476ca5ff38fccd206096
proposal_id=prop_8f9aeaaa3b15476bbe7374102e3c74fa
resolution_id=res_9d71b9c5b035476ba306d9a1457166aa
feature_id=proposal-review-payload-loop7-no-auto-merge
```

Final lane state:

```text
status=awaiting_final_action
branch=proposal-review-payload-loop7-no-auto-merge
base_head_sha=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
worktree=/tmp/xmuse-loop7-no-auto-merge-exec-GKbThV
review_decision=merge
review_summary=review accepted
final_action_hold_id=final-560bfc9f2fc6
```

Review plane evidence:

```text
review_task.status=verdict_emitted
review_task.verdict_id=verdict-proposal-review-payload-loop7-no-auto-merge
review_verdict.decision=merge
review_verdict.status=finalized
```

Final-action evidence:

```text
hold.id=final-560bfc9f2fc6
hold.action=merge
hold.target_status=reviewed
hold.status=pending
```

Control branch evidence:

```text
git rev-parse HEAD
110dd47b435e44e7b608ac5b880ad4aebcf79ab0
```

The isolated execution worktree retained the candidate edit on the lane branch:

```text
git -C /tmp/xmuse-loop7-no-auto-merge-exec-GKbThV status -sb
## proposal-review-payload-loop7-no-auto-merge
 M tests/xmuse/test_chat_review_trigger.py
```

The services were stopped after the test. Later checks showed no listeners on
ports `8100` or `8201`.

Classification: local runtime evidence that `--no-auto-merge` allows
execution, gate, and independent review to complete while preventing direct
auto-merge into the control branch. The lane is intentionally not complete; it
waits at final-action approval. This is operator-safety evidence, not GitHub
review truth, merge truth, or fullchain completion.

### Loop 6-8 Groupchat To Final-Action Hold

Runtime root:

```text
.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9
```

Execution worktree:

```text
/tmp/xmuse-groupchat-exec-jUcfwj
```

Preparation:

```bash
git worktree add -b codex/groupchat-runtime-loop-20260618-uHnZr9 \
  /tmp/xmuse-groupchat-exec-jUcfwj HEAD
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9 \
XMUSE_EXECUTION_WORKTREE=/tmp/xmuse-groupchat-exec-jUcfwj \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9 \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9 \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-8-groupchat-no-auto-merge-uHnZr9 \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.35 \
  --no-auto-merge
```

Health endpoints returned `200`:

```text
GET http://127.0.0.1:8201/health -> service=xmuse-chat-api
GET http://127.0.0.1:8100/health -> service=xmuse-mcp
```

Groupchat bootstrap:

```text
conversation_id=conv_d353c349af2e49ea8a19bae9681ccf79
bootstrap_proposal_id=bootstrap-proposal:conv_d353c349af2e49ea8a19bae9681ccf79:architect-review-execute
architect=codex gpt-5.4
review=opencode opencode-go/deepseek-v4-flash
execute=codex gpt-5.4-mini
```

Human request:

```text
target=@architect
scope=make direct initial_participants accept explicit OpenCode peer identity
feature_id=groupchat-opencode-initial-participants
```

Durable groupchat evidence:

```text
architect_inbox=inbox_f348ca47d16d4e8b830fe95204cab031
architect_delivery=mcp_writeback
architect_tool_stages=chat_read_inbox, chat_post_message, chat_emit_proposal
proposal_id=prop_c7663c8297e3469f80ee446d3031d6f1
proposal_message_id=msg_db7d6bf1996e4557924c0a80608f714f
```

OpenCode review evidence:

```text
review_inbox=inbox_db72c51986d8448f8f3b399b95d5bd48
review_delivery=mcp_writeback
review_message_id=msg_a7ff87aebcfd48ce8345c2a9a4f424fe
review_content_prefix="**Review: lane `groupchat-opencode-initial-participants`**"
review_result=PASS
opencode_command=opencode run --model opencode-go/deepseek-v4-flash --variant max --format json
```

Approval and lane:

```text
resolution_id=res_9ca3d1595e0649f4a68cc144aa9ad24b
lane_id=groupchat-opencode-initial-participants
branch=codex/groupchat-runtime-loop-20260618-uHnZr9
base_head_sha=110dd47b435e44e7b608ac5b880ad4aebcf79ab0
worktree=/tmp/xmuse-groupchat-exec-jUcfwj
```

Final lane state:

```text
status=awaiting_final_action
review_decision=merge
review_summary=review accepted
review_task.status=verdict_emitted
review_verdict.status=finalized
final_action_hold_id=final-1f738cc3ae18
final_action.status=pending
```

Candidate diff was reviewed in the isolated worktree, then imported into the
control worktree after focused validation. Current imported files:

```text
src/xmuse_core/chat/peer_service.py
tests/xmuse/test_peer_chat_service.py
```

Validation after import:

```bash
uv run pytest tests/xmuse/test_peer_chat_service.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_peer_provider_parity.py tests/xmuse/test_package_boundaries.py -q
```

Result:

```text
40 passed, 1 warning
```

Observed boundary:

```text
peer-chat Codex/OpenCode discussion sessions used worktree=/home/iiyatu/projects/python/xmuse
lane execution used worktree=/tmp/xmuse-groupchat-exec-jUcfwj
```

Classification: local runtime evidence that a real GOD groupchat can bootstrap
Codex and OpenCode peers, route a human demand through durable architect
proposal and OpenCode review writeback, approve the proposal, execute the lane
in an isolated worktree, review it, and stop at final-action hold without
auto-merge. This is not GitHub review truth, server-side truth, merge truth,
live MemoryOS proof, full L8-L10 closure, full L1-L11 closure, or natural
provider-peer completion beyond the observed Codex/OpenCode local path.

### Peer-Chat Scratch Worktree Recheck

Runtime root:

```text
.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.10 \
  --no-auto-merge
```

Conversation:

```text
conversation_id=conv_d13f495e58f6461cae004cbd4862d249
request=@architect Reply exactly SCRATCH_PEER_READY
inbox_id=inbox_c1da00e7f3d642d294c8d19846f6852e
```

Result:

```text
responded_message_id=msg_7ade313d8911414fbb9dd508eaea439e
assistant content=SCRATCH_PEER_READY
delivery_mode=mcp_writeback
degraded_reason=None
tool stages=chat_read_inbox, chat_post_message
```

Peer session worktree evidence:

```text
architect session worktree=.goal-runs/2026-06-18/loop-peer-chat-scratch-worktree-Lt2CJm/peer_chat_worktree
control worktree not used for this peer-chat turn
peer_chat_worktree contained no files after the turn
```

Validation for the code change:

```bash
uv run pytest tests/xmuse/test_platform_runner.py::test_runner_enables_peer_chat_with_default_codex_launcher tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer -q
```

Result:

```text
2 passed
```

Classification: local runtime evidence that the peer-chat scheduler can run a
durable Codex chat turn from an xmuse-root scratch worktree instead of the
control repository worktree. This does not prove the dispatch bridge isolation
policy or full groupchat/task completion.

### Loop 5 Multi-Turn Codex/OpenCode Handoff Reliability Probe

Runtime root:

```text
.goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.30 \
  --no-auto-merge
```

Conversation:

```text
conversation_id=conv_0ce81045529f4c47b7afa8b778c633ad
architect=codex gpt-5.4
review=opencode opencode-go/deepseek-v4-flash
execute=codex gpt-5.4-mini
review session runtime=opencode
```

Peer session worktree evidence:

```text
codex_persistent --worktree .goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL/peer_chat_worktree --role architect
opencode_persistent --worktree .goal-runs/2026-06-18/loop-5-multiturn-codex-opencode-xWhUVL/peer_chat_worktree --role review
```

Run 1 was excluded from clean handoff proof because the human prompt included a
literal `@review` token. The Chat API therefore created both the intended
architect inbox and a direct review inbox from the human message:

```text
architect_inbox=inbox_320e9e8fbe334919b846f9461127ee5a
direct_human_review_inbox=inbox_f0b16b16851e425b82ee758116d3694f
```

Even with that contamination, the architect did perform a durable handoff:

```text
architect_response=ARCHITECT_HANDOFF_ONE_READY
architect_handoff_message=msg_4aeb977f06404319a9bdf8a13b08da92
handoff_review_inbox=inbox_e45f2e7951a2432ea7d90e9219999813
opencode_response=OPENCODE_HANDOFF_ONE_READY
opencode_delivery=mcp_writeback
```

Run 2 removed the direct `@review` token from the human message. The human only
mentioned `@architect`; Codex then created the review mention through the MCP
handoff tool:

```text
human_message_id=msg_f73274ed67044f3794abaa2500fae8ca
architect_inbox=inbox_d2908650c239426eaab84e04c7163847
architect_response_message=msg_2bbcb502390745cbbe78eac5094ac275
architect_response=ARCHITECT_HANDOFF_TWO_READY
architect_delivery=mcp_writeback
```

Clean handoff evidence:

```text
handoff_message_id=msg_e25b0c6cf7bb4177b4dcd7fcacd82ee4
handoff_envelope_type=mention
handoff_mentions=["@review"]
review_inbox=inbox_0f2eda2692164360afd5134e690d71f1
review_response_message=msg_f85d46503b2d45448abad607c5f86918
review_response=OPENCODE_HANDOFF_TWO_READY
review_delivery=mcp_writeback
review_degraded_reason=None
```

Latency traces:

```text
run2 architect total_latency_ms=70323, delivery=mcp_writeback
run2 review total_latency_ms=4499, delivery=mcp_writeback
```

The services were stopped after the test. Later checks showed no listeners on
ports `8100` or `8201`.

Classification: local runtime evidence that a real Codex architect can receive
a human mention, write back durably, create a durable `@review` handoff through
the chat tool, and a real OpenCode review peer can reply through durable
callback writeback from the scheduler scratch worktree. Run 1 is recorded as
contaminated evidence because the human message directly mentioned review. Run
2 is the clean handoff sample. This does not prove GitHub truth, merge truth,
live MemoryOS, full L8-L10 closure, full L1-L11 closure, or full task
completion from chat demand.

### Loop 5 Restart/Resume And Soak Handoff Reliability Probe

Runtime root:

```text
.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL
```

Raw summary:

```text
.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL/summary.md
```

Started real local services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-5-restart-resume-codex-opencode-KkzUCL \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.40 \
  --no-auto-merge
```

The runner was stopped after handoff run 1 and restarted with the same command
before handoff run 2. Chat API and MCP server stayed up against the same
runtime root and the same durable conversation.

Conversation:

```text
conversation_id=conv_b85095df51a9474b9a8426eb85b6fcc1
architect=part_d6558145bc3a4199ac5215ef40dcbe11 codex gpt-5.4
review=part_25cdafd6789c472f8f7149a89189a644 opencode opencode-go/deepseek-v4-flash
execute=part_694b28b134444ce59b923be4e578ca9f codex gpt-5.4-mini
```

Creation parameter corrections:

```text
profile_id=default rejected for architect
profile_id=god rejected for review
profile_id=god rejected for execute
accepted profile ids: architect=god, review=review, execute=worker
```

Observed peer runtime commands:

```text
codex_persistent --model gpt-5.4 --mcp-port 8100 --worktree .../peer_chat_worktree --role architect
opencode_persistent --model opencode-go/deepseek-v4-flash --variant max --mcp-port 8100 --worktree .../peer_chat_worktree --role review --opencode-binary opencode
```

Durable handoff results:

```text
run1 human_mentions=["@architect"]
run1 architect=ARCHITECT_RESTART_ONE_READY
run1 architect_handoff_mentions=["@review"]
run1 review=OPENCODE_RESTART_ONE_READY

run2 human_mentions=["@architect"]
run2 architect=ARCHITECT_RESTART_TWO_READY
run2 architect_handoff_mentions=["@review"]
run2 review=OPENCODE_RESTART_TWO_READY

run3 human_mentions=["@architect"]
run3 architect=ARCHITECT_SOAK_THREE_READY
run3 architect_handoff_mentions=["@review"]
run3 review=OPENCODE_SOAK_THREE_READY

run4 human_mentions=["@architect"]
run4 architect=ARCHITECT_SOAK_FOUR_READY
run4 architect_handoff_mentions=["@review"]
run4 review=OPENCODE_SOAK_FOUR_READY
```

Durable state summary:

```text
message_count=16
inbox_count=8
latency_trace_count=8
architect_traces=4 delivery=mcp_writeback degraded_reason=None
review_traces=4 delivery=mcp_writeback degraded_reason=None
```

Representative inbox and trace ids:

```text
run1 architect_inbox=inbox_8be411d24c0343f78221fffa442b050a
run1 review_inbox=inbox_e895f318c00045bbbcf646f4a3e0f7c9
run2 architect_inbox=inbox_c868608c341740929c1ca57517f1ac9a
run2 review_inbox=inbox_e4c6c9e8dbc74a87b0056a418c0ae402
run3 architect_inbox=inbox_450ce21e297b4814a155a35cde144b54
run3 review_inbox=inbox_9498de8b1ac94d0aaa234e5163313320
run4 architect_inbox=inbox_c43ac8807db545008da152727bd42e65
run4 review_inbox=inbox_13248182bf784ba2be392c8bf285a382
```

The services were stopped after the test. Later checks showed no listeners on
ports `8100` or `8201`, and no remaining runner, Chat API, MCP,
`codex_persistent`, or `opencode_persistent` processes.

Classification: local runtime evidence that a real Codex/OpenCode GOD
chatgroup can preserve durable peer routing through one runner restart and
multiple same-runner handoffs. All successful replies were durable
MCP/callback writebacks; no stdout fallback was counted. This is still not full
task completion, GitHub truth, merge truth, live MemoryOS proof, full L8-L10
closure, or full L1-L11 closure.

## 2026-06-18 Loop 6-8: profile ergonomics proposal and retests

Summary file:

```text
.goal-runs/2026-06-18/loop-6-to-8-profile-ergonomics-summary.md
```

### Loop 6: groupchat proposal to isolated execution dispatch

Runtime root:

```text
.goal-runs/2026-06-18/loop-6-to-9-profile-ergonomics-zhCXiz
```

Services:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-9-profile-ergonomics-zhCXiz \
XMUSE_EXECUTION_WORKTREE=/tmp/xmuse-profile-ergonomics-exec-dR1uet \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201)'

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-9-profile-ergonomics-zhCXiz \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-9-profile-ergonomics-zhCXiz \
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-6-to-9-profile-ergonomics-zhCXiz \
  --peer-chat \
  --mcp-port 8100 \
  --max-hours 0.75 \
  --no-auto-merge
```

Conversation and proposal:

```text
conversation_id=conv_8f07b3de1f504cbda2c5b9224b8bea15
architect=codex gpt-5.4
review=opencode opencode-go/deepseek-v4-flash
execute=codex gpt-5.4-mini

blocked_original_proposal=prop_c29a9fe0d5f14a8bb9d5ed6dc9de1dbc
replacement_proposal=prop_059edc69f61a4f338af5d332e6cdc189
execute_collaboration=collab_67ef7945f9814e5fb9c2452b6030c122
resolution_id=res_a088ab7b72f24c1188b8a9cc356784f6
lane_id=groupchat-initial-participants-profile-inference
```

Runtime observations:

```text
original failure=collaboration_target_mismatch when target was @execute
dispatch gate required typed execute_feasibility_verdict with evidence_refs
replacement approval status=200
lane status=gate_failed
failure_layer=review
failure_reason=review_non_zero_exit
execution worker result exit_code=0
review worker result exit_code=1
```

The execution worker changed a candidate worktree and reported `21 passed`
through stdout fallback. The review worker did not produce a verdict; it ran as
`runtime=codex` and attempted to read a missing superpowers skill path. This
lane is therefore evidence of real dispatch and a review-plane failure, not an
accepted implementation or review truth.

Main-control implementation after auditing the evidence:

```text
src/xmuse_core/chat/peer_service.py
src/xmuse_core/chat/peer_types.py
xmuse/chat_api.py
tests/xmuse/test_peer_chat_mcp_tools.py
tests/xmuse/test_groupchat_collaboration_runtime.py
tests/xmuse/test_peer_chat_service.py
tests/xmuse/test_chat_bootstrap_api.py
```

### Loop 7: direct participant profile retest

Runtime root:

```text
.goal-runs/2026-06-18/loop-7-profile-inference-retest-TD26DS
```

The REST create-conversation request omitted `profile_id` for an OpenCode
`review` peer. The participant payload inferred `profile_id=review`, but the
session summary still showed `profile_id=default`. OpenCode still responded
through durable MCP writeback:

```text
conversation_id=conv_e17790bb15114bf88e7b586a109e1536
review_participant=part_34f8db7fa65e4aa8b5789920fb987242
assistant_message=msg_d4fc8918337643ad967c751bfa55952b
content=OPENCODE_PROFILE_INFERENCE_RETEST_READY
delivery_mode=mcp_writeback
degraded_reason=None
total_latency_ms=5919
```

### Loop 8: session profile retest after fix

Runtime root:

```text
.goal-runs/2026-06-18/loop-8-profile-session-retest-digf71
```

The same REST request shape succeeded after the session-summary fix:

```text
conversation_id=conv_e07a3ef95b8f45478b49516f90ebcdd7
review_participant=part_cea56d7efaf746a08b9c69d039556034
participant_profile_id=review
session_profile_id=review
session_runtime=opencode
assistant_message=msg_014d38ea077848f48a74bd9440dec346
content=OPENCODE_PROFILE_SESSION_RETEST_READY
inbox=inbox_42a360b11f594f0a9942966417bf42b0
delivery_mode=mcp_writeback
degraded_reason=None
total_latency_ms=5325
```

Services were stopped after loop 8. A process check found no remaining
`uvicorn`, MCP, platform-runner, `codex exec`, or `opencode run` processes.

Classification: local runtime proof for direct participant profile inference
and real OpenCode peer writeback. This is still not full demand-to-completion,
GitHub review truth, merge truth, live MemoryOS proof, full L8-L10 closure, or
full L1-L11 closure.

## 2026-06-18 Loop 9-10: OpenCode persistent review runtime

Summary file:

```text
.goal-runs/2026-06-18/loop-9-to-10-opencode-review-runtime-summary.md
```

### Loop 9: required OpenCode review peer routed but no verdict

Runtime root:

```text
.goal-runs/2026-06-18/loop-9-opencode-review-runtime-75aJLr
```

Setup:

```text
conversation_id=conv_3f5d2092709144888456daed5f932e0a
review_participant_id=part_42f137b236a24368a37ad0107f6bc207
lane_id=loop9-opencode-review-runtime-probe
review_runtime=opencode
```

Runner:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-9-opencode-review-runtime-75aJLr \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-9-opencode-review-runtime-75aJLr \
XMUSE_RAY_GOD_MCP=0 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-9-opencode-review-runtime-75aJLr \
  --mcp-port 8100 \
  --persistent-review-god \
  --persistent-review-timeout-s 90 \
  --max-hours 0.15 \
  --no-auto-merge
```

Observed:

```text
status=gate_failed
peer_delivery_mode=required_peer_failed
peer_degraded_reason=review_peer_no_verdict
failure_reason=review_peer_delivery_failed
review_peer_id=part_42f137b236a24368a37ad0107f6bc207
review_runtime_requested=opencode
```

`god_sessions.json` recorded a real OpenCode review session:

```text
runtime=opencode
model=opencode-go/deepseek-v4-flash
feature_scope_id=feature-loop9-opencode-review-runtime
provider_session_id=019ed792-7066-7121-9aae-fff4caeb154d
```

This proved the route no longer fell back to one-shot Codex, but the review
result was not accepted because the verdict text was not read from the message
artifact payload.

### Loop 10: OpenCode persistent review verdict accepted

Runtime root:

```text
.goal-runs/2026-06-18/loop-10-opencode-review-verdict-cqsYft
```

Setup:

```text
conversation_id=conv_bf447c5ade4043f2925f7d4900202d39
review_participant_id=part_06825251e025479a8075ce0d38074ec6
lane_id=loop10-opencode-review-verdict-probe
review_runtime=opencode
```

Runner:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-10-opencode-review-verdict-cqsYft \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-10-opencode-review-verdict-cqsYft \
XMUSE_REVIEW_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-10-opencode-review-verdict-cqsYft \
  --mcp-port 8100 \
  --persistent-review-god \
  --persistent-review-timeout-s 90 \
  --max-hours 0.15 \
  --no-auto-merge
```

Observed:

```text
status=awaiting_final_action
peer_delivery_mode=configured_peer
peer_routing_mode=required
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_fallback_reason=verdict_merge
review_peer_id=part_06825251e025479a8075ce0d38074ec6
review_runtime_requested=opencode
final_action_hold_id=final-e5921fcdd52f
```

The OpenCode review text included:

```text
Findings: none
Verdict: merge
```

Services were stopped after loop 10.

Classification: local runtime proof that `review_runtime=opencode` can route
to a real OpenCode configured review peer, parse a durable verdict from the
persistent result, and advance to final-action hold. This is still not GitHub
review truth, merge truth, live MemoryOS proof, full L8-L10 closure, or full
L1-L11 closure.

## 2026-06-18 Loop 11-12: proposal projection preserves review runtime

Target:
Verify that a durable `lane_graph` proposal can carry
`review_runtime=opencode` through approval into the lane graph artifact and
`feature_lanes.json` projection consumed by the runner.

Authority:
The proposal/resolution and lane graph artifact are the source records. The
flat `feature_lanes.json` file is only the execution queue projection.

### Loop 11: proposal approval dropped `review_runtime`

Runtime root:

```text
.goal-runs/2026-06-18/loop-11-review-runtime-projection-1xixbI
```

REST path:

```text
conversation_id=conv_73bc6d581b6b477b9e6e54fe7530e3af
proposal_id=prop_4c59b2e75ec540f0812ea48d77e053c7
resolution_id=res_235207bb14184a6a92e2b67a8819ac22
```

The proposal and approved resolution contained:

```text
review_runtime=opencode
```

Observed lane graph artifact and projection:

```text
lane_graphs/res_235207bb14184a6a92e2b67a8819ac22-graph-v1.json:
  lane omitted review_runtime

feature_lanes.json:
  lane omitted review_runtime
```

Classification: projection/model contract failure. The API accepted a
structured lane runtime choice, but the `LaneNode` model and projection payload
did not preserve it for the runner.

### Loop 12: projection rerun after fix

Runtime root:

```text
.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM
```

Commands:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM \
uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201, log_level="info")'

uv run python - <<'PY'
# HTTP client: GET /health, POST /api/chat/conversations,
# POST /api/chat/conversations/{conversation_id}/proposals,
# POST /api/chat/proposals/{proposal_id}/approve, then inspect
# XMUSE_ROOT/feature_lanes.json and chat.db summaries.
PY
```

An initial harness attempt used bare `python` and failed with
`python: command not found`; the probe was rerun with `uv run python` per repo
policy. This was a harness error, not product evidence.

Observed:

```text
conversation_id=conv_50d2e89e91de4b13ae0ca9348b68bc16
proposal_id=prop_49a2988fab5c49c68874c80239ecf373
resolution_id=res_71b01fb4e5fc44e39affc463b70810a0
lane_id=loop12-review-runtime-opencode
lane_count=1
lane_graph_review_runtime=opencode
projected_review_runtime=opencode
runner_started=false
```

The conversation included an OpenCode review participant:

```text
role=review
provider_id=opencode
profile_id=review
runtime=opencode
model=opencode-go/deepseek-v4-flash
```

Durable files:

```text
.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM/result.json
.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM/state/lane-summary.json
.goal-runs/2026-06-18/loop-12-review-runtime-projection-rerun-CGczHM/lane_graphs/res_71b01fb4e5fc44e39affc463b70810a0-graph-v1.json
```

Services were stopped after loop 12. A process and port check found no
remaining listeners on `8100` or `8201`, and no remaining `uvicorn`, MCP,
platform-runner, `codex exec`, or `opencode run` processes.

Classification: local runtime proof for the proposal-approval-to-projection
contract only. This does not prove review execution, GitHub review truth, merge
truth, live MemoryOS proof, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-18 Loop 13: approved proposal consumed by runner with OpenCode review

Target:
Verify the next safe chain after loop 12:

```text
Chat API proposal approval
-> feature_lanes projection with review_runtime=opencode
-> platform runner consumes lane
-> isolated execution worktree candidate
-> persistent OpenCode review
-> no-auto-merge final-action hold
```

Runtime root:

```text
.goal-runs/2026-06-18/loop-13-proposal-runner-opencode-review-WO3US9
```

Execution worktree:

```text
/tmp/xmuse-loop13-exec-TFCuyC
```

The worktree was created as a detached git worktree from local HEAD. The Chat
API was started with `execution_worktree=/tmp/xmuse-loop13-exec-TFCuyC` so the
projected lane did not target the control worktree.

Projection path:

```text
conversation_id=conv_721071eda8f84766b8685e08e631e94e
proposal_id=prop_ad663efb57f248e88f9b717c2df7f9bd
resolution_id=res_95fa16cb619542aa93c6c7b5ddc69f93
lane_id=loop13-review-runtime-preservation-worker
projected_worktree=/tmp/xmuse-loop13-exec-TFCuyC
projected_review_runtime=opencode
```

Runner commands:

```bash
XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-13-proposal-runner-opencode-review-WO3US9 \
uv run python -m xmuse.mcp_server

XMUSE_ROOT=/home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-13-proposal-runner-opencode-review-WO3US9 \
XMUSE_REVIEW_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
uv run xmuse-platform-runner \
  --xmuse-root /home/iiyatu/projects/python/xmuse/.goal-runs/2026-06-18/loop-13-proposal-runner-opencode-review-WO3US9 \
  --mcp-port 8100 \
  --persistent-review-god \
  --persistent-review-timeout-s 120 \
  --max-hours 0.12 \
  --no-auto-merge
```

Observed:

```text
status=awaiting_final_action
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_ec729eefb8bd42139a1831ee17c570bc
peer_delivery_mode=configured_peer
peer_routing_mode=required
peer_degraded_reason=None
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_fallback_reason=verdict_merge
final_action_hold_id=final-f3f9df2ac3c8
```

Review plane:

```text
review_task_id=rtask_f5483de0e8f6435bbb5ca7c0960d081f
verdict_id=verdict-merge-rtask_f5483de0e8f6435bbb5ca7c0960d081f
decision=merge
status=finalized
```

Final action hold:

```text
id=final-f3f9df2ac3c8
action=merge
target_status=reviewed
status=pending
```

The execution candidate changed three files in the isolated worktree:

```text
src/xmuse_core/structuring/models.py
src/xmuse_core/structuring/projection.py
tests/xmuse/test_groupchat_collaboration_runtime.py
```

Main Codex audit/import:

- Treated worker output and OpenCode review as candidate evidence only.
- Kept the already imported `LaneNode.review_runtime` and projection payload
  fix in the control worktree.
- Imported the candidate's missing `review_runtime` field classification as a
  projection field.
- Strengthened the existing regression to inspect both the lane graph artifact
  and `feature_lanes.json`.
- Added classification coverage in `test_feature_graph_projection`.

Focused validation after import:

```bash
uv run pytest \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_lane_graph_approval_preserves_review_runtime_in_projection \
  tests/xmuse/test_feature_graph_projection.py::test_feature_lane_field_classifications_are_explicit_for_retained_projection_fields \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_routes_to_existing_review_peer \
  tests/xmuse/test_review_plane_orchestrator_integration.py::test_review_runtime_opencode_without_peer_fails_closed \
  -q
```

Observed:

```text
4 passed, 1 warning
```

Services were stopped after loop 13. Process and port checks found no remaining
listeners on `8100` or `8201`, and no remaining `uvicorn`, MCP,
platform-runner, `codex exec`, `opencode_persistent`, or `opencode run`
processes.

Classification: local runtime proof for proposal approval -> runner
consumption -> isolated execution -> persistent OpenCode review ->
final-action hold. It is still not GitHub review truth, merge truth,
ready-to-merge proof, live MemoryOS proof, full L8-L10 closure, or full L1-L11
closure.

## 2026-06-18 Loop 14: Ray/default natural groupchat proposal probe

Runtime root:

```text
.goal-runs/2026-06-18/loop-14-natural-groupchat-schema-proposal-85SfoR
```

Target:
Run the natural groupchat producer path without operator-created proposal:

```text
human @architect
-> Codex architect peer
-> durable MCP writeback
-> chat_emit_proposal
```

Observed durable state:

```text
conversation_id=conv_04719fb339f84ee5a746cf380c8326ff
human_message_id=msg_5ef8d002bc8b46a187b1ed3f03235be8
architect_inbox_id=inbox_6537a2af510a4b068a0166b7c4b85b05
inbox_status=failed
failure_reason=peer_no_inbox_side_effect
nudge_count=3
proposals_count=0
peer_turn_mcp_tool_traces=[]
```

The Ray/default path streamed natural-language output, but no durable proposal
or durable assistant writeback was created. `XMUSE_RAY_GOD_MCP=0` was part of
the run, so this is a real negative runtime fact for that backend shape, not a
claim about native backend capability.

Classification: prompt/tool contract and MCP/callback writeback failure for the
Ray/default peer-chat path. No closure claim was made.

## 2026-06-18 Loop 15: native natural groupchat to runner, review ensure failure

Runtime root:

```text
.goal-runs/2026-06-18/loop-15-native-natural-groupchat-schema-proposal-pI4XH1
```

Execution worktree:

```text
/tmp/xmuse-loop15-exec-ig2CI1
```

Service shape:

```bash
XMUSE_PEER_GOD_BACKEND=native \
XMUSE_REVIEW_GOD_BACKEND=native \
XMUSE_RAY_GOD_MCP=0 \
uv run xmuse-platform-runner \
  --xmuse-root .goal-runs/2026-06-18/loop-15-native-natural-groupchat-schema-proposal-pI4XH1 \
  --mcp-port 8100 \
  --peer-chat \
  --persistent-review-god \
  --persistent-review-timeout-s 120 \
  --max-hours 0.30 \
  --no-auto-merge
```

Observed groupchat state:

```text
conversation_id=conv_990194f51ed54237ad65e350ed699899
architect_participant=part_6bfe8d78620b4a0e963e06b041d209e1
review_participant=part_a86ccb1e8cb34e88be3db1fc433d8699
proposal_id=prop_550cd2f16f284a619724c097b5f7f3d2
proposal_message_id=msg_11a51b9476514942af37eae9263186e1
peer_review_message_id=msg_5b6669c253fb4df6b0d8871cb4435585
resolution_id=res_c1b213dd734544b39a41c84b1300d9c3
lane_id=loop15-chat-emit-proposal-review-runtime-schema
```

Groupchat MCP traces:

```text
architect: chat_read_inbox, chat_post_message, chat_emit_proposal
review: chat_post_message
delivery_mode=mcp_writeback
degraded_reason=None
```

Runner reached isolated execution and produced a candidate diff in the worker
worktree:

```text
xmuse/mcp_server.py
tests/xmuse/test_mcp_server.py
```

Observed terminal lane state:

```text
status=gate_failed
failure_reason=required_review_peer_unavailable
failure_layer=review
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_a86ccb1e8cb34e88be3db1fc433d8699
peer_delivery_mode=required_peer_failed
peer_degraded_reason=ensure_failed
```

Root-cause classification:
the same OpenCode review participant already had an unscoped peer-chat session
bound to `peer_chat_worktree`. The configured lane review path tried to reuse
that participant for a different review request/worktree without a distinct
session scope, so native session compatibility failed closed.

## 2026-06-18 Loop 16: first scoped-session fix, missing lane scope still fails

Runtime root:

```text
.goal-runs/2026-06-18/loop-16-native-fullchain-review-session-scope-Tu7rK2
```

Execution worktree:

```text
/tmp/xmuse-loop16-exec-Tu7rK2
```

Code change tested before Loop 16:

- `GodSessionRegistry.find_by_conversation_participant()` can select an exact
  `feature_scope_id`.
- `GodSessionLayer` can create distinct session addresses/inboxes for
  feature-scoped sessions using a stable scope suffix.

Loop 16 first created a default bootstrap conversation and recorded a separate
fact: the default `architect-review-execute` preset currently uses Codex review,
not OpenCode review. The OpenCode target therefore requires explicit
`provider_overrides.review=opencode` unless the default preset changes.

Loop 16 then created an explicit OpenCode review conversation:

```text
conversation_id=conv_7215306d2e734cc2ba3a6f5094cfa5fc
proposal_id=prop_811e1756b4cb43e9b49548af0198f5e3
resolution_id=res_a7a8eaf3ae6a45e8ba21704c43b2083b
lane_id=loop16-opencode-chat-emit-proposal-review-runtime-schema
```

Groupchat succeeded:

```text
Codex architect: chat_read_inbox, chat_post_message, chat_emit_proposal
OpenCode review: chat_post_message
delivery_mode=mcp_writeback
chat_streams=[]
```

Runner reached the same review failure:

```text
status=gate_failed
failure_reason=required_review_peer_unavailable
peer_degraded_reason=ensure_failed
review_peer_id=part_2f19335faa5e48bdbfe181e5e3f34d8b
review_runtime_requested=opencode
```

New root-cause refinement:
proposal-created lanes did not carry `feature_scope_id` or
`feature_plan_feature_id`, so `feature_scope_id_from_lane()` returned `None`.
The feature-scoped session fix could not activate for configured review peers
when the lane lacked feature identity.

## 2026-06-18 Loop 17: request-scoped configured OpenCode review succeeds

Runtime root:

```text
.goal-runs/2026-06-18/loop-17-native-opencode-review-request-scope-Rr4mN8
```

Execution worktree:

```text
/tmp/xmuse-loop17-exec-Rr4mN8
```

Additional code change tested before Loop 17:

- configured review peer sessions use `feature_scope_id_from_lane(lane)` when
  present;
- otherwise they use a stable request scope:
  `configured-review:<lane_id>`.

Conversation and proposal:

```text
conversation_id=conv_5cb1dcf802ea4f59adec3e7271946c19
proposal_id=prop_27d04454dc264b14bc19fb5281901ce2
resolution_id=res_db428c1219b64168abe15d82ab8f1e6a
lane_id=loop17-opencode-chat-emit-proposal-review-runtime-schema
```

Groupchat evidence:

```text
participants:
- architect: codex gpt-5.4
- review: opencode opencode-go/deepseek-v4-flash
- execute: codex gpt-5.4-mini

architect MCP tools:
- chat_read_inbox
- chat_post_message
- chat_emit_proposal

review MCP tools:
- chat_post_message

chat_streams=[]
```

Runner/review terminal state:

```text
status=awaiting_final_action
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_23e94f2c5c7347f1a299682678c1d37f
peer_routing_mode=required
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict_id=verdict-merge-rtask_c379e4f47dfa4a01b16793939e9a1e07
final_action_hold_id=final-3c6fadddda94
```

The `god_sessions.json` authority recorded a distinct configured review session
for the same OpenCode participant:

```text
god_session_id=god-af3440d590d142b7a12995f5610c3d62
runtime=opencode
participant_id=part_23e94f2c5c7347f1a299682678c1d37f
worktree=.goal-runs/2026-06-18/loop-17-native-opencode-review-request-scope-Rr4mN8
feature_scope_id=configured-review:loop17-opencode-chat-emit-proposal-review-runtime-schema
```

Final action hold:

```text
id=final-3c6fadddda94
action=merge
target_status=reviewed
status=pending
```

Worker candidate diff in the isolated worktree:

```text
xmuse/mcp_server.py
tests/xmuse/test_mcp_server.py
```

Main Codex audit/import:

- Worker output and OpenCode review were treated as candidate evidence only.
- Imported only the audited minimal schema and focused-test change:
  explicit `review_runtime` property in `CHAT_TOOL_SCHEMAS`, plus schema
  assertion in `tests/xmuse/test_mcp_server.py`.
- Did not resolve the final action hold.
- Did not claim GitHub review truth, merge truth, live MemoryOS, full L8-L10
  closure, or full L1-L11 closure.

## 2026-06-19 OpenCode project MCP and review idempotency loops

Candidate worktree:

```text
/tmp/xmuse-opencode-persistent-mcp-25z30
```

Candidate branch:

```text
codex/opencode-persistent-project-mcp
```

Proof level for this section: `local_runtime_proof` only.

### Direct OpenCode project MCP probe

Runtime root:

```text
/tmp/xmuse-opencode-persistent-mcp-25z30/.goal-runs/2026-06-19/loop-25z30-opencode-persistent-mcp-shim-072722
```

Command shape:

```bash
XMUSE_ROOT="$ROOT" uv run xmuse-mcp-server
printf '%s\n' "$TASK_JSON" |
  XMUSE_ROOT="$ROOT" uv run python -m xmuse_core.agents.opencode_persistent \
    --model opencode-go/deepseek-v4-flash --variant max --mcp-port 8100 \
    --worktree /tmp/xmuse-opencode-persistent-mcp-25z30 \
    --role review --timeout-s 180
```

Observed:

```text
status=success
opencode command included --pure
OpenCode emitted tool_use for xmuse-platform_get_status
temporary worktree opencode.json was restored after the run
```

Classification: direct provider-command evidence that OpenCode can see the
project MCP server when runtime MCP config is injected into the `--dir`
worktree. This is not GitHub truth or product review truth.

### Fullchain repro: gate environment leak

Runtime root:

```text
/tmp/xmuse-opencode-persistent-mcp-25z30/.goal-runs/2026-06-19/loop-25z31-opencode-review-native-mcp-fullchain-073214
```

Observed path:

```text
conversation_id=conv_1f4c1a26f1c948bfbe50e92573810bfb
proposal_id=prop_605a5862b557420fb918df4dcc7f5c33
resolution_id=res_d288c6772de444bf800c1a6d69c2ce9b
lane_id=loop25z31_opencode_review_native_mcp_fullchain
```

The chain reached real dispatch and execution. The package-boundary command
passed, but the gate profile failed because the gate subprocess inherited the
platform control-plane `XMUSE_ROOT`:

```text
profile_ids=["xmuse-core"]
2 failed, 241 passed
failed tests:
- test_runner_parser_resolves_lanes_from_xmuse_root
- test_runner_parser_explicit_lanes_override_xmuse_root
```

Classification: gate execution environment boundary. The targeted fix was to
strip `XMUSE_ROOT` from gate command subprocess environments before applying
command-specific env.

### Fullchain repro: persistent review same-status callback

Runtime root:

```text
/tmp/xmuse-opencode-persistent-mcp-25z30/.goal-runs/2026-06-19/loop-25z32-opencode-review-native-mcp-fullchain-gatefix-075600
```

Observed path:

```text
conversation_id=conv_5d175654d23d43868eb094d88dcf85bc
collaboration_run=collab_f37cb0bbd60c48489b6cc056c5557bc0
proposal_id=prop_2d581d444e14477baa645b8931d41c5f
resolution_id=res_1a9b58c7128245a898c826ef60490339
lane_id=loop25z32_opencode_review_native_mcp_fullchain_gatefix
review_peer_id=part_f8e6e96092694a038ff8bfec13a12642
```

Runner state reached:

```text
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
peer_delivery_mode=configured_peer
review_decision=merge
final_action_hold_id=final-27a0e0892978
```

Gate report:

```text
strict-product: 16 passed
xmuse-core: 243 passed, 2 warnings
```

Observed failure after review verdict delivery:

```text
InvalidTransitionError: cannot transition loop25z32_opencode_review_native_mcp_fullchain_gatefix from reviewed to reviewed
```

Root cause: the OpenCode persistent review peer first wrote lane status through
native MCP `update_lane_status`; callback processing then delivered the
structured review verdict and attempted the same `reviewed` transition again.

Classification: persistent review callback idempotency boundary. The targeted
fix lets review delivery update metadata when the lane is already in the target
status.

### Fullchain rerun after fixes

Runtime root:

```text
/tmp/xmuse-opencode-persistent-mcp-25z30/.goal-runs/2026-06-19/loop-25z33-opencode-review-native-mcp-idempotent-081617
```

Service commands:

```bash
XMUSE_ROOT="$ROOT" uv run xmuse-chat-api
XMUSE_ROOT="$ROOT" uv run xmuse-mcp-server
XMUSE_ROOT="$ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Conversation and groupchat:

```text
conversation_id=conv_4d32ecd005fe4a7a9de2c7f59db90aba
architect_participant=part_7ec8ff2b601e4144903d26b63681a4b9
execute_participant=part_44d0ef0aa8ec4bce974810e478041218
review_participant=part_34fc2292b14940a6903067e9699961f2
review_runtime=opencode
review_model=opencode-go/deepseek-v4-flash
```

Durable collaboration and proposal:

```text
human_message=msg_9c662bf677c6425b83af4dcd7d3a7caf
collaboration_run=collab_8e3ab8e6b4ca4ab28840cdb7d93fd699
execute_response=collab_resp_9127be7170c34b42af3d29b620bfcdc0
review_response=collab_resp_e854846db4d8499e8aa67a61906406f3
proposal_id=prop_074abe10c09c4d2bb4d0d47deacf2910
proposal_references=["collaboration:collab_8e3ab8e6b4ca4ab28840cdb7d93fd699"]
resolution_id=res_2ddf36a9428e49fe9a438334a91e92a3
```

Lane and review state:

```text
lane_id=loop25z33_opencode_review_native_mcp_idempotent
status=awaiting_final_action
proof_boundary=local_runtime_proof
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_34fc2292b14940a6903067e9699961f2
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict_id=verdict-merge-rtask_1cb17611dc7c414f91f0ef541a48d5f3
final_action_hold_id=final-f136441d0d74
```

Gate report:

```text
logs/gates/loop25z33_opencode_review_native_mcp_idempotent/report.json
passed=true
blocking_passed=true
strict-product: uv run pytest -q tests/xmuse/test_package_boundaries.py -> 0
xmuse-core: peer chat / GOD session / platform / feature graph focused suite -> 0
```

Review artifacts:

```text
review_plane.json:
  task_id=rtask_1cb17611dc7c414f91f0ef541a48d5f3
  status=verdict_emitted
  verdict.status=finalized
  verdict.decision=merge

final_actions.json:
  id=final-f136441d0d74
  action=merge
  target_status=reviewed
  status=pending
```

Durable peer traces:

```text
delivery_mode=mcp_writeback for architect, execute, and review turns
degraded_reason=null for all peer_turn_latency_traces rows
OpenCode review peer tool traces include chat_read_inbox and chat_post_message
Architect proposal turn includes chat_emit_proposal
```

Search result for the old idempotency failure:

```text
rg "InvalidTransitionError|cannot transition|reviewed to reviewed" "$ROOT" -> no matches
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
Ray service processes from the run: none
```

The runner was interrupted after the final-action hold had been recorded. Ray
printed shutdown/atexit noise during Ctrl-C handling; it did not change the
recorded lane result.

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness.

### Loop 25z37: human leading mention routing repro and rerun

Goal: verify whether human demand text that starts with `@architect` but later
mentions `@execute` and `@review` widens the initial peer queue.

Authority:

```text
chat.db messages and chat_inbox_items
```

Producer and consumer boundary:

```text
producer=Chat API / PeerChatService.post_human_message
consumer=peer scheduler inbox queue
proof_level=local_runtime_routing_evidence
```

Pre-fix runtime root:

```text
.goal-runs/2026-06-19/loop-25z37-role-mention-routing-094947
```

Service command:

```bash
XMUSE_ROOT="$RUN_ROOT" uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201, log_level="info")'
```

The first three HTTP attempts were harness/schema corrections for provider
profile ids. They are not product evidence. The corrected request created a
conversation with:

```text
architect: codex/god gpt-5.4
execute: codex/worker gpt-5.4-mini
review: opencode/review opencode-go/deepseek-v4-flash
```

Human message:

```text
@architect please coordinate the implementation. The written requirement needs
to discuss the @execute and @review roles as examples, but the initial work
should stay architect-led.
```

Observed pre-fix durable result:

```text
conversation_id=conv_ef85f8375d30416bb78b209e2f531127
message_mentions=["@architect","@execute","@review"]
inbox_targets=["architect","execute","review"]
artifact=.goal-runs/2026-06-19/loop-25z37-role-mention-routing-094947/role_mention_repro.json
```

Classification: routing. A leading architect address plus later role references
created three initial inbox items.

Targeted fix:

- Human messages now treat a leading `@mention` block as the routing header.
- If a human message starts with one or more mentions, only that leading block
  routes inbox items.
- If a human message does not start with a mention, existing body-mention
  routing remains unchanged.

Rerun runtime root:

```text
.goal-runs/2026-06-19/loop-25z37b-leading-routing-rerun-095415
```

Rerun service command:

```bash
XMUSE_ROOT="$RUN_ROOT" uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8201, log_level="info")'
```

Observed rerun durable result:

```text
conversation_id=conv_8a3f4ae510584709b5dbebac8ec4ea8e
message_mentions=["@architect"]
inbox_targets=["architect"]
artifact=.goal-runs/2026-06-19/loop-25z37b-leading-routing-rerun-095415/role_mention_rerun.json
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_service.py \
  tests/xmuse/test_package_boundaries.py -q
-> 31 passed

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
ports 8100/8201/8265 -> no listeners
```

Claims not made: provider peer reply truth, full groupchat completion, GitHub
review truth, merge truth, `ready_to_merge`, `pr_merged`, live MemoryOS, full
L8-L10 closure, full L1-L11 closure, production-ready groupchat, or overnight
readiness.

### Loop 25z38: routing fix fullchain rerun to final-action hold

Goal: rerun the real groupchat-to-lane chain on the human leading mention
routing fix. The human demand intentionally mentioned `@execute` and `@review`
in the body, but only the leading `@architect` mention should route the initial
turn.

Runtime root:

```text
.goal-runs/2026-06-19/loop-25z38-routing-fix-fullchain-095859
```

Execution worktree:

```text
/tmp/loop-25z38-routing-fix-fullchain-095859-exec
```

Service commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Conversation and participants:

```text
conversation_id=conv_f2884fbc14a849f98a71a924e15f879e
architect=codex/god gpt-5.4
execute=codex/worker gpt-5.4-mini
review=opencode/review opencode-go/deepseek-v4-flash
human_message_id=msg_1cbc99d035f2405488c8227e19343cb7
```

Initial routing evidence:

```text
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
artifact=.goal-runs/2026-06-19/loop-25z38-routing-fix-fullchain-095859/initial_routing_snapshot.json
```

Durable groupchat path:

```text
architect first writeback=msg_91d31b84bcf04bb789dd268f108710b7
architect execute handoff=msg_eb27add1bb084f1d9dfb5867694096a6
collaboration_run=collab_6c22ccf31e1b4611a87804d4fce04921
execute_response=received for @execute
proposal_early=prop_29676296a529419e991bec7c07bed578 status=open
architect callback writeback=msg_d7aacab013894cbd84a0ac03f730aaf8
proposal_accepted=prop_e2adada1bba54f098e19658697844298 status=accepted
resolution_id=res_b6f435d726c24bff8a7b7085585da4e8
```

The first proposal remained open after architect emitted a later proposal from
the execute callback. This is duplicate proposal noise and remains an open
groupchat ergonomics gap.

Lane result:

```text
lane_id=loop25z38_routing_fix_fullchain
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict_id=verdict-merge-rtask_0aa1395bab3a4e828ca2eade6673b1b4
final_action_hold_id=final-c6021aa4fe11
worktree=/tmp/loop-25z38-routing-fix-fullchain-095859-exec
```

Child worker evidence:

```text
command=codex exec -m gpt-5.4 ... -C /tmp/loop-25z38-routing-fix-fullchain-095859-exec
mcp_tools=query_knowledge, update_lane_status
test=uv run pytest tests/xmuse/test_package_boundaries.py -q
result=16 passed in 3.18s
changed_files=none
lane_status_update=executed
```

Gate report:

```text
logs/gates/loop25z38_routing_fix_fullchain/report.json
passed=true
blocking_passed=true
strict-product: uv run pytest -q tests/xmuse/test_package_boundaries.py -> 0
warning=gate_profiles.json missing in XMUSE_ROOT; using lane worktree xmuse/gate_profiles.json
```

Review and final-action artifacts:

```text
review_plane.json:
  task_id=rtask_0aa1395bab3a4e828ca2eade6673b1b4
  status=verdict_emitted
  verdict.status=finalized
  verdict.decision=merge

final_actions.json:
  id=final-c6021aa4fe11
  action=merge
  target_status=reviewed
  status=pending
```

Durable peer traces:

```text
delivery_mode=mcp_writeback for architect, execute, review, architect callback,
review trigger, and execute dispatch turns
degraded_reason=null for all recorded peer_turn_latency_traces rows
```

Negative search:

```text
rg "InvalidTransitionError|cannot transition|reviewed and merged|ready_to_merge=true|pr_merged=true|existing registered session does not match|peer_response_timeout|DISPATCH_FAILED" "$RUN_ROOT" -> no matches
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
Ray service processes from the run: none
execution worktree git status: clean
```

Runner shutdown printed asyncio subprocess transport cleanup noise after the
final-action hold was already recorded. This is not lane failure evidence.

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness. The final action remains
pending under `--no-auto-merge`.

### Loop 25z40: real code-change lane blocked by empty peer-chat worktree

Goal: move beyond a no-op package-boundary lane and ask the real groupchat to
produce a small code-change lane for gate profile source evidence.

Runtime root:

```text
.goal-runs/2026-06-19/loop-25z40-real-code-lane-103636
```

Execution worktree target:

```text
/tmp/loop-25z40-real-code-lane-103636-exec
```

Service commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Durable path:

```text
conversation_id=conv_7c035fc1a82b493d92b4734659187368
human_message_id=msg_e0bd86b0c8404ecf928cf6f298bbf73c
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
collaboration_run=collab_cfffe1fca30d4e7f92a6b56b611ff937
proposal_id=prop_9fb7912da63d4132b2a58f6d4a1a77c0
```

Failure boundary:

```text
boundary=peer_chat_worktree
peer_chat_worktree_entries=[]
execute_response.status=failed
execute_response.content.type=execute_feasibility_blocker
approval_error.code=dispatch_gate_blocked
approval_error.message=blocked_execute_not_confirmed
artifact=.goal-runs/2026-06-19/loop-25z40-real-code-lane-103636/negative_runtime_snapshot.json
```

The execute peer did not falsely approve dispatch. It reported that
`peer_chat_worktree` was empty and did not contain the requested repo files.
The approval path then failed closed through the dispatch gate.

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness.

### Loop 25z40b: repo-backed peer-chat worktree rerun to code-change final hold

Goal: rerun Loop 25z40 after making peer-chat runtime worktree repo-backed so
Codex/OpenCode peers can inspect real repo files without touching the control
worktree.

Runtime root:

```text
.goal-runs/2026-06-19/loop-25z40b-peer-worktree-rerun-104924
```

Execution worktree:

```text
/tmp/loop-25z40b-peer-worktree-rerun-104924-exec
```

Pre-run peer worktree evidence:

```text
peer_chat_worktree=.goal-runs/2026-06-19/loop-25z40b-peer-worktree-rerun-104924/peer_chat_worktree
git rev-parse --is-inside-work-tree -> true
branch --show-current -> empty detached worktree
src/xmuse_core/platform/execution/gate.py -> present
```

Durable groupchat and approval:

```text
conversation_id=conv_b8e73ff486c145adb0860bdd36da0ed0
human_message_id=msg_3da8a2f6fd95472699e23047c3a46694
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
collaboration_run=collab_a9832c489d72425f8d5064c1bc852a57
proposal_id=prop_1f67619ee1a245969278e8f8ad2d8b2c
resolution_id=res_f1b257fda82a4712ac45e15b8c9af7b1
approval_mode=runtime_loop_manual_approval_no_auto_merge
```

Lane result:

```text
lane_id=loop25z40_gate_profile_source
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_decision=merge
final_action_hold_id=final-bab763cf5987
worktree=/tmp/loop-25z40b-peer-worktree-rerun-104924-exec
artifact=.goal-runs/2026-06-19/loop-25z40b-peer-worktree-rerun-104924/final_runtime_snapshot.json
```

Worker candidate diff in isolated execution worktree:

```text
src/xmuse_core/platform/execution/gate.py | 58 +++++++++++++++++++++++++++++++
tests/xmuse/test_platform_orchestrator.py |  6 ++++
2 files changed, 64 insertions(+)
```

Main Codex audit/import:

```text
imported=peer-chat repo-backed worktree fix in xmuse/platform_runner.py
imported=worker candidate gate_profiles_source report metadata
worker_output_role=candidate evidence only
```

Focused validation after import:

```text
uv run pytest tests/xmuse/test_platform_runner.py::test_peer_chat_runtime_worktree_creates_repo_backed_detached_worktree \
  tests/xmuse/test_platform_runner.py::test_runner_enables_peer_chat_with_default_codex_launcher \
  tests/xmuse/test_platform_runner.py::test_runner_uses_ray_peer_god_layer_by_default \
  tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer \
  tests/xmuse/test_platform_runner.py::test_runner_prewarm_ray_peer_god_layer_by_default \
  tests/xmuse/test_platform_runner.py::test_runner_can_force_native_peer_god_layer \
  tests/xmuse/test_platform_orchestrator.py::test_run_gate_uses_worktree_gate_profiles_when_runtime_root_missing \
  tests/xmuse/test_package_boundaries.py -q
-> 23 passed

uv run ruff check xmuse/platform_runner.py src/xmuse_core/platform/execution/gate.py \
  tests/xmuse/test_platform_runner.py tests/xmuse/test_platform_orchestrator.py
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
```

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness. The final action remains
pending under `--no-auto-merge`.

### Loop 25z41: durable peer writeback promotes session health

Goal: rerun the real code-change chain after PR #77 from current
`origin/main`, require OpenCode as the persistent review peer, and verify that
durable peer writebacks are reflected in peer-chat session health instead of
leaving successful peers stuck in `starting`.

Runtime root:

```text
/tmp/xmuse-post-pr77-main-H8rIDc/.goal-runs/2026-06-19/loop-25z41-post-pr77-main-real-code-111357
```

Execution worktree:

```text
/tmp/xmuse-post-pr77-main-H8rIDc/.goal-runs/2026-06-19/loop-25z41-post-pr77-main-real-code-111357/peer_chat_worktree
```

Service commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Negative precondition evidence:

```text
default_review_conversation=abandoned
reason=default bootstrap still selected Codex review peer unless provider override was explicit

message="@architect Coordinate..."
observed_mentions=[]
reason=mention parser overmatched the capitalized following word as display-name text
```

Explicit OpenCode peer conversation:

```text
conversation_id=conv_680fdda55ff341abbc34e0ad3c617ba0
architect_participant=part_447bf5116ec643e6a658054d900ce85b
execute_participant=part_881b8600cbfa4c72b1853fa46b2e9da8
review_participant=part_81b8b06962554f8db8f99bc157aff543
review_runtime=opencode
review_model=opencode-go/deepseek-v4-flash
```

Durable groupchat and approval:

```text
human_message_id=msg_d98b9d5899ce496e9afb722049139755
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
execute_collaboration_run=collab_f8ca32b910f64d9a8673b8b4341b149f
execute_response=collab_resp_2cdddaa615284d0e91277a19de256a0b
execute_response_type=execute_feasibility_verdict
execute_response_status=executable
review_collaboration_response=collab_resp_e53db7d80ff4415780ed665dca2b5982
proposal_id=prop_3e85d38acb3d479fb6e073f9bd31f96c
resolution_id=res_b60b447eaa7f45a88060d630d40a53f5
approval_mode=runtime_loop_manual_approval_no_auto_merge
```

Lane result:

```text
lane_id=loop25z41_session_health_writeback_status
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
final_action_hold_id=final-c93b57b1ffb8
artifact=/tmp/xmuse-post-pr77-main-H8rIDc/.goal-runs/2026-06-19/loop-25z41-post-pr77-main-real-code-111357/final_runtime_snapshot.json
```

Worker candidate diff in isolated execution worktree:

```text
src/xmuse_core/agents/god_session_registry.py
src/xmuse_core/chat/peer_service.py
src/xmuse_core/chat/inspector_builder.py
tests/xmuse/test_god_session_registry.py
tests/xmuse/test_mcp_server.py
tests/xmuse/test_peer_chat_dashboard.py
```

Main Codex audit/import:

```text
imported=durable session status promotion after authenticated peer writeback
imported=peer-chat inspector merge that preserves non-null active runtime fields
worker_output_role=candidate evidence only
```

Focused validation after import:

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

uv run ruff check .
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

GitHub server facts inspected after the small PR:

```text
PR #78 URL=https://github.com/iiyazu/Cross-Muse/pull/78
PR #78 head=524c1c961881d4f17851361f920d068d5c652874
PR #78 state=MERGED
PR #78 merged_at=2026-06-19T03:40:20Z
PR #78 merge_commit=c5818ba433142765c817bc63fed73ec40141ae06
PR #78 checks_run=27803856684
PR #78 checks=quality-gates success, contract-smoke-gates success, real-runtime-integration-gate success
main_post_merge_run=27803891559
main_post_merge_head=c5818ba433142765c817bc63fed73ec40141ae06
main_post_merge_checks=success
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
```

Remaining manual gaps:

- The default peer-chat bootstrap still selected Codex for the first review
  conversation unless OpenCode was explicitly requested.
- The mention parser overmatched `@architect Coordinate...` and failed to
  route until the mention was written as `@architect,`.
- This is one successful local runtime code-change loop plus GitHub server
  facts for the imported PR. It is not repeated stability or production-ready
  groupchat proof.

Claims not made: GitHub review truth, inferred merge truth beyond the inspected
PR #78 server state, `ready_to_merge`, `pr_merged` for a live lane, live
MemoryOS, full L8-L10 closure, full L1-L11 closure, production-ready groupchat,
or overnight readiness.

### Loop 25z39: proposal waits for collaboration readiness

Goal: remove the duplicate proposal observed in Loop 25z38 by requiring
`lane_graph` proposals that reference `collaboration:<run_id>` to wait until
the referenced collaboration run is `done`.

Runtime root:

```text
.goal-runs/2026-06-19/loop-25z39-proposal-ready-guard-101608
```

Execution worktree:

```text
/tmp/loop-25z39-proposal-ready-guard-101608-exec
```

Service commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Conversation and routing:

```text
conversation_id=conv_2c464666fb8048bd89644832e430e7fa
human_message_id=msg_3ac351c9f0784e5ea39a955cd1ed5512
human_mentions=["@architect"]
initial_inbox_targets=["architect"]
artifact=.goal-runs/2026-06-19/loop-25z39-proposal-ready-guard-101608/initial_routing_snapshot.json
```

Collaboration and proposal timing:

```text
collaboration_run=collab_a0265a7420db4d9b9d87596843e54e0f
running_window_proposals=0
saw_running_without_proposal=true
execute_response=received
collaboration_status=done
proposal_after_done=prop_3997229437eb4e84b32996813dea49c8
proposal_count_after_done=1
artifact=.goal-runs/2026-06-19/loop-25z39-proposal-ready-guard-101608/proposal_timing_snapshot.json
```

Approval:

```text
proposal_id=prop_3997229437eb4e84b32996813dea49c8
resolution_id=res_d337544add8e4c578c93072adf6a1518
approval_mode=runtime_loop_manual_approval_no_auto_merge
derived_from_proposal_ids=["prop_3997229437eb4e84b32996813dea49c8"]
```

Lane result:

```text
lane_id=loop25z39_proposal_ready_guard
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict_id=verdict-merge-rtask_acd834dd61c94829a78642c227ac0a68
final_action_hold_id=final-aa3d2b8ca9a7
worktree=/tmp/loop-25z39-proposal-ready-guard-101608-exec
artifact=.goal-runs/2026-06-19/loop-25z39-proposal-ready-guard-101608/final_runtime_snapshot.json
```

Child worker evidence:

```text
command=codex exec -m gpt-5.4 ... -C /tmp/loop-25z39-proposal-ready-guard-101608-exec
mcp_tools=query_knowledge, update_lane_status
test=uv run pytest tests/xmuse/test_package_boundaries.py -q
result=16 passed in 3.11s
changed_files=none
lane_status_update=executed
```

Gate report:

```text
logs/gates/loop25z39_proposal_ready_guard/report.json
passed=true
blocking_passed=true
strict-product: uv run pytest -q tests/xmuse/test_package_boundaries.py -> 0
warning=gate_profiles.json missing in XMUSE_ROOT; using lane worktree xmuse/gate_profiles.json
```

Durable peer traces:

```text
delivery_mode=mcp_writeback for architect, execute, architect callback, review,
and execute dispatch turns
degraded_reason=null for all recorded peer_turn_latency_traces rows
```

Negative search:

```text
rg "InvalidTransitionError|cannot transition|reviewed and merged|ready_to_merge=true|pr_merged=true|existing registered session does not match|peer_response_timeout|DISPATCH_FAILED|collaboration_run_not_ready" "$RUN_ROOT" --glob '!**/logs/agent_spawns/**' -> no matches
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
```

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness. The final action remains
pending under `--no-auto-merge`.

### Loop 25z42: leading role mention before capitalized sentence

Goal: verify and fix the Loop 25z41 routing gap where a natural human message
starting with `@architect Coordinate...` was stored as a plain message without
durable inbox routing.

Branch:

```text
codex/strict-leading-mention-routing
base=origin/main@3a4ec2853ea2099f648513bbb0856415de81b906
```

Prepatch runtime root:

```text
/tmp/xmuse-mention-routing-after-pr79/.goal-runs/2026-06-19/loop-25z42-mention-routing-prepatch-115536
```

Prepatch Chat API command:

```bash
XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8211, log_level="warning")'
```

Prepatch HTTP observation:

```text
POST /api/chat/conversations -> 201
conversation_id=conv_2437704332cd445499e09b50602445cc

content="@architect Coordinate a tiny routing fix."
message_status=201
mentions=[]
inbox_targets=[]

content="@architect, Coordinate a tiny routing fix."
message_status=201
mentions=["@architect"]
inbox_targets=["architect"]
```

Implementation summary:

```text
src/xmuse_core/chat/mentions.py
- added participant-aware leading-content resolution
- preserved longest matching display-name alias behavior
- allows overlong regex raw mentions to shrink to the longest resolvable alias

src/xmuse_core/chat/peer_service.py
- human routing now uses MentionResolver for leading and full-content routing
- @all remains a leading broadcast token
- MentionResolutionError is converted back to PeerChatError at service boundary
```

Postpatch runtime root:

```text
/tmp/xmuse-mention-routing-after-pr79/.goal-runs/2026-06-19/loop-25z42-mention-routing-postpatch-120105
```

Postpatch Chat API command:

```bash
XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8212, log_level="warning")'
```

Postpatch HTTP and durable-state observation:

```text
POST /api/chat/conversations -> 201
conversation_id=conv_8b0c4ba05f8145a791713448b48ab9c2

content="@architect Coordinate a tiny routing fix."
message_status=201
mentions=["@architect"]
inbox_targets=["architect"]
inbox_ids=["inbox_1e25d11673b5436192e9b7ad7963fb82"]

durable chat.db row:
mentions_json='["@architect"]'
target_role=architect
status=unread
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_service.py \
  tests/xmuse/test_peer_chat_mentions.py \
  tests/xmuse/test_peer_chat_api.py \
  tests/xmuse/test_peer_chat_end_to_end.py::test_default_group_chat_flow_reaches_god_reply_proposal_and_keeps_roles_isolated \
  tests/xmuse/test_package_boundaries.py -q
-> 50 passed, 1 warning

uv run ruff check .
-> All checks passed

git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Cleanup:

```text
8211/8212/8201/8100/8265 listeners: none
```

Claims not made: GitHub review truth, `ready_to_merge`, `pr_merged`, live
MemoryOS, full L8-L10 closure, full L1-L11 closure, production-ready groupchat,
or overnight readiness.

### Loop 25z44: review peer display-name runtime exposed by real groupchat

Branch:

```text
codex/review-runtime-from-chat-peer
base=origin/main@c02e9dce50b808bbd4aed1ab6d1960e32ca6472b
```

Runtime root:

```text
/tmp/xmuse-post-pr80-fullchain-121024/.goal-runs/2026-06-19/loop-25z44-review-runtime-authority-123333
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 180 \
  --max-hours 0.75 --no-auto-merge
```

Driver action:

```text
Created a real Chat API conversation with review provider override:
provider_id=opencode, profile_id=review, cli_kind=opencode,
model=opencode-go/deepseek-v4-flash, display_name=review-god.

Posted natural human message:
@architect Coordinate a real post-fix fullchain review-runtime slice...
```

Durable observations:

```text
conversation_id=conv_4af99a4e53ff49baa3daedc1a380d629
proposal_id=prop_ee0a49da461b438a845fa15ca0edbd42
resolution_id=res_b4848df06b7142ef9128f6acdd36f914
collaboration_run=collab_9fc570479ba9432aa11df3f32b6ba886

human -> architect mention: read, mcp_writeback
architect -> execute handoff: read, mcp_writeback
execute -> architect collaboration callback: read, mcp_writeback
architect proposal turn: chat_emit_proposal recorded
dispatch bridge -> execute acknowledgement: read, mcp_writeback
```

Important runtime finding:

```text
The groupchat-produced lane_graph used review_runtime="review-god".
The active review participant was display_name=review-god, cli_kind=opencode.
Projection preserved review_runtime="review-god" into feature_lanes.json.
```

Pre-fix lane projection:

```text
feature_id=docs_review_runtime_loop_evidence
status=dispatched before operator timeout cleanup
review_runtime=review-god
god_sessions.review.runtime=opencode
god_sessions.review.status=starting
```

The driver timed out before lane execution completed. The subsequent
`exec_failed` status was caused by operator cleanup after timeout and is not
counted as a natural business failure.

Artifact paths:

```text
loop_driver_artifacts/create_conversation_response.json
loop_driver_artifacts/human_message_response.json
loop_driver_artifacts/approval_snapshot.json
loop_driver_artifacts/timeout_runtime_snapshot.json
feature_lanes.json
god_sessions.json
chat.db
```

### Loop 25z45: focused HTTP projection smoke for review-god alias

Purpose:

```text
Verify the approval/projection fix for the Loop 25z44 failure boundary without
claiming a full worker/review/final-hold chain.
```

Runtime root:

```text
/tmp/xmuse-post-pr80-fullchain-121024/.goal-runs/2026-06-19/loop-25z45-review-runtime-projection-smoke-124901
```

Command:

```bash
XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8213, log_level="info")'
```

HTTP chain:

```text
POST /api/chat/conversations -> 201
review provider override: opencode/review, display_name=review-god

POST /api/chat/conversations/{conversation_id}/proposals -> 201
proposal lane review_runtime=review-god

POST /api/chat/proposals/{proposal_id}/approve -> 200
approval response lane review_runtime=opencode
feature_lanes.json lane review_runtime=opencode
```

Artifact paths:

```text
loop_driver_artifacts/create_conversation_response.json
loop_driver_artifacts/proposal_response.json
loop_driver_artifacts/approval_response.json
loop_driver_artifacts/feature_lanes.json
loop_driver_artifacts/res_49249c77412a49e89ed50baeb3b40e10-graph-v1.json
loop_driver_artifacts/god_sessions.json
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

Cleanup:

```text
8201/8100/8213/8265 listeners: none
```

Claims not made: full chain success, independent OpenCode review pass,
GitHub review truth, merge truth, `ready_to_merge`, `pr_merged`, live MemoryOS,
full L8-L10 closure, full L1-L11 closure, production-ready groupchat, or
overnight readiness.

### Loop 25z46: post-PR81 fullchain rerun exposed OpenCode casing fallback

Branch:

```text
codex/post-pr81-fullchain-rerun
base=origin/main@ff57a06ce3834e35d8afcbcb6d15c2f14ce95ae8
```

Runtime root:

```text
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z46-post-pr81-fullchain-125758
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 240 \
  --max-hours 1.0 --no-auto-merge
```

Durable observations:

```text
conversation_id=conv_6656eed08af94e068c0eb37297b9e0ee
proposal_id=prop_4dcb154dd4144efba995b54dcbccc0cb
resolution_id=res_a13d67ee96c04ba1bf8c90cb71e216d1
collaboration_run=collab_3f059a7f87954944bc9a729faaf7879d

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

Classification: real local fullchain negative routing evidence. The groupchat
and lane reached final-action hold, but explicit `OpenCode` casing bypassed the
lowercase `opencode` provider identity and degraded persistent review to a
fallback path.

### Loop 25z47: focused HTTP projection smoke for OpenCode casing

Purpose:

```text
Verify that approval/projection canonicalizes explicit review_runtime=OpenCode
to the active OpenCode review participant runtime, without claiming a fullchain
execution/review loop.
```

Runtime root:

```text
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z47-opencode-case-projection-smoke-131455
```

Command:

```bash
XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"])), host="127.0.0.1", port=8214, log_level="info")'
```

HTTP chain:

```text
POST /api/chat/conversations -> 201
review provider override: opencode/review, display_name=review-god

POST /api/chat/conversations/{conversation_id}/proposals -> 201
proposal lane review_runtime=OpenCode

POST /api/chat/proposals/{proposal_id}/approve -> 200
approval response review_runtime=opencode
feature_lanes.json review_runtime=opencode

conversation_id=conv_848927cc81394c778f889af2f92d738e
proposal_id=prop_09c6d82413764fe3963a6ebe2aae6487
resolution_id=res_048df0afefef417ca54a1f893a08cc06
```

Classification: real Chat API approval/projection evidence only. It validates
the authority handoff for casing, not worker execution or independent review.

### Loop 25z48: post-casing-fix fullchain rerun to persistent OpenCode review

Runtime root:

```text
/tmp/xmuse-post-pr81-fullchain-main/.goal-runs/2026-06-19/loop-25z48-opencode-case-fullchain-131556
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 240 \
  --max-hours 1.0 --no-auto-merge
```

Durable observations:

```text
conversation_id=conv_78f4da6f5c3b4e11a4c7e50e96275b96
proposal_id=prop_0a317551f8ef48d5aa4338310427f89b
resolution_id=res_6ae312c81f34476fa51ee9bbe7765743
collaboration_run=collab_ecaa21e66b584129924111e4c725bebf

messages=9
chat_inbox_items=5
proposals=1
resolutions=1
collaboration_runs=1
peer_turn_latency_traces:
  mcp_writeback=3 with no degraded reason
  mcp_writeback=1 with peer_response_timeout_after_writeback
```

Lane result:

```text
feature_id=docs-production-closure-gap-ledger-post-pr81-rerun
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
peer_delivery_mode=configured_peer
review_peer_id=part_6ed04cc020e145a6a7101938569e37bd
review_runtime_requested=opencode
persistent_review_identity=configured:part_6ed04cc020e145a6a7101938569e37bd
review_decision=merge
final_action_hold_id=final-d1959362ae2b
review_task=rtask_935e4743a2cf477da02fd60f80398870
review_verdict=verdict-merge-rtask_935e4743a2cf477da02fd60f80398870
```

Gate evidence:

```text
logs/gates/docs-production-closure-gap-ledger-post-pr81-rerun/report.json
passed=true
blocking_passed=true
command="uv run pytest -q tests/xmuse/test_package_boundaries.py"
returncode=0
```

Review evidence refs:

```text
feature_lanes.json#lane=docs-production-closure-gap-ledger-post-pr81-rerun
review_plane.json#task=rtask_935e4743a2cf477da02fd60f80398870
logs/lane_prompts/docs-production-closure-gap-ledger-post-pr81-rerun.md
logs/gates/docs-production-closure-gap-ledger-post-pr81-rerun/report.json
```

Classification: real local fullchain evidence for one docs-only lane from
durable groupchat through proposal, approval, isolated execution, gate,
persistent OpenCode review, and final-action hold under `--no-auto-merge`.
This is not production readiness, GitHub review truth, live MemoryOS proof, or
full L8-L10/L1-L11 closure.

Cleanup:

```text
8201/8100/8214/8265 listeners: none
```

### Loop 25z49: post-PR82 real code-change lane to final hold

Branch:

```text
codex/post-pr82-code-lane-rerun
base=origin/main@94218b269e4a005049e18378ebdc179c1dcada28
```

Runtime root:

```text
/tmp/xmuse-post-pr82-code-lane-5TCIGa/.goal-runs/2026-06-19/loop-25z49-post-pr82-code-lane-134000
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --persistent-review-god --persistent-review-timeout-s 240 \
  --max-hours 1.0 --no-auto-merge
```

Human demand:

```text
Ask architect to coordinate one real code-change fullchain. The requested
bounded product change was to expose participant_sessions in the conversation
bootstrap/create response so external clients can map role and participant_id
to durable god_session_id without parsing god_sessions.json.
```

Durable groupchat observations:

```text
conversation_id=conv_d4fc824bbaae4955aafab5fcec53e521
collaboration_run=collab_9be5084eab334e50ab0e327ea7d3b078
proposal_id=prop_8afc1aabe2ce40b3acdb06924f66e161
resolution_id=res_f6262fa36fcf4f078ba78af72957e628

messages=10
chat_inbox_items=5
collaboration_runs=1
collaboration_responses=1
proposals=1
resolutions=1
peer_turn_latency_traces:
  mcp_writeback=4 with no degraded reason
  mcp_writeback=1 with peer_response_timeout_after_writeback
```

Groupchat chain:

```text
human -> architect mention: read, mcp_writeback
architect -> execute feasibility request: read, mcp_writeback
execute -> collaboration response: received, executable
collaboration callback -> architect: read, proposal emitted
proposal review trigger -> review-god/OpenCode: read, PASS
operator approval -> lane projection
```

Lane result:

```text
feature_id=peer-chat-participant-sessions-response
status=awaiting_final_action
changed_files:
  src/xmuse_core/chat/peer_service.py
  xmuse/chat_api.py
  tests/xmuse/test_peer_chat_api.py
gate_passed=true
review_runtime=opencode
review_delivery_mode=persistent
persistent_review_degraded=false
peer_delivery_mode=configured_peer
review_peer_id=part_f92861d9b05c4f6b92e39880313734f2
review_runtime_requested=opencode
persistent_review_identity=configured:part_f92861d9b05c4f6b92e39880313734f2
review_decision=merge
final_action_hold_id=final-d596ee1cb4ea
review_task=rtask_7cea2ced463e4a579dc22af4b66adeef
review_verdict=verdict-merge-rtask_7cea2ced463e4a579dc22af4b66adeef
```

Gate evidence:

```text
logs/gates/peer-chat-participant-sessions-response/report.json
passed=true
blocking_passed=true
profile_ids=["xmuse-core"]
command="uv run pytest -q tests/xmuse/test_peer_chat_service.py ... tests/xmuse/test_feature_summary.py"
returncode=0
stdout="253 passed, 2 warnings in 70.15s"
```

Post-import local validation:

```text
uv run pytest tests/xmuse/test_peer_chat_api.py tests/xmuse/test_package_boundaries.py -q
-> 28 passed, 1 warning

uv run ruff check . -> All checks passed
git diff --check -> pass
test ! -e xmuse/__init__.py -> pass
```

Cleanup:

```text
8201/8100/8265 listeners: none
```

The runner emitted Ray shutdown warnings and a `std::bad_alloc` stack after
operator Ctrl-C during cleanup. This happened after the lane reached
`awaiting_final_action` and is not counted as a business-chain failure.

Classification: real local fullchain evidence for one small code-change lane
from durable GOD groupchat through execute feasibility, proposal, OpenCode
proposal review, human approval, isolated execution, gate, persistent OpenCode
review, and final-action hold under `--no-auto-merge`. This is not GitHub
review truth, live MemoryOS proof, production readiness, or full L8-L10/L1-L11
closure.

## 2026-06-19 Post-PR83 Parallel Peer-Chat Reliability

Baseline:

```text
origin/main and local HEAD before this slice:
6c962708071895e94458ff947eaed8753c789ce0

PR #83:
https://github.com/iiyazu/Cross-Muse/pull/83
state=MERGED
head=c7deb891fb599a5ff5ef288af0d1a05c1ef3e53c
merge_commit=6c962708071895e94458ff947eaed8753c789ce0
post-merge main run=27808670855
post-merge main conclusion=success

PR #43:
state=CLOSED
mergedAt=null
headRefName=vision-closure-deliberation-tui
headRefOid=2c03b2492e9e0a618f21e19120192b0a46765dbf
```

The following runs used isolated `XMUSE_ROOT` directories under
`.goal-runs/2026-06-19/`. Ports `8201`, `8100`, and `8265` were clear after
cleanup. None of these local runs is GitHub review truth, merge truth,
production readiness, live MemoryOS proof, or full closure proof.

### Loop 25z50: two-conversation parallel groupchat probe

Runtime root:

```text
/tmp/xmuse-post-pr83-main-U3Tz5c/.goal-runs/2026-06-19/loop-25z50-post-pr83-parallel-groupchat-140846
```

Service shape:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c '... uvicorn.run(create_app(...), port=8201)'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" \
  --mcp-port 8100 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 240 --max-hours 0.75 --no-auto-merge
```

Probe:

- created two deterministic conversations with Codex architect, Codex execute,
  and OpenCode review participants;
- verified creation responses included three `participant_sessions`;
- posted one human `@architect` message per conversation;
- requested durable groupchat replies only and prohibited proposal/lane output.

Final durable state:

```text
messages=15
chat_inbox_items=7
unread_or_claimed=0
peer_turn_latency_traces=7
peer_turn_mcp_tool_traces=12
proposals=0
resolutions=0
```

Evidence artifacts:

```text
loop_driver_artifacts/failure_parallel_snapshot_manual.json
loop_driver_artifacts/final_snapshot_after_completion.json
```

Key finding:

```text
inbox_b8d0d0df31884926848bd62b7e64b8cb
target_role=architect
responded_message_id=msg_392105789d3c44c1a924cc50feb3fd9c
tool traces included chat_post_message
recorded delivery_mode=failed
recorded degraded_reason=codex_exit_1
```

Classification: durable chat authority had a real assistant writeback, but the
latency trace followed the provider process exit and marked delivery as failed.
This was a delivery-classification defect, not absence of durable writeback.

### Local delivery-classification fix

Local change:

- `PeerChatScheduler` now rechecks durable inbox/writeback authority when a
  provider returns `error`;
- if the target inbox is `read` and the responded message is a real MCP
  writeback from the target participant, delivery is recorded as
  `mcp_writeback`;
- provider failure is preserved as `*_after_writeback` degraded reason.

Focused validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
-> 15 passed in 6.44s
```

Classification: local focused contract validation only. It is not server truth.

### Loop 25z51: triple-conversation probe before scheduler parallelism

Runtime root:

```text
/tmp/xmuse-post-pr83-main-U3Tz5c/.goal-runs/2026-06-19/loop-25z51-patched-triple-groupchat-142552
```

Probe:

- same service shape as Loop 25z50;
- created three deterministic conversations;
- posted three human `@architect` messages;
- ran after the delivery-classification fix but before scheduler parallelism.

Interrupted evidence:

```text
loop_driver_artifacts/head_of_line_blocking_snapshot.json
loop_driver_artifacts/interrupted_head_of_line_final_snapshot.json

messages=9
chat_inbox_items=7
peer_turn_latency_traces=2
peer_turn_mcp_tool_traces=4
proposals=0
resolutions=0
open_inbox_items=5
```

Classification: negative local runtime evidence for scheduler throughput.
The platform runner reported `concurrency=4`, but peer-chat processing still
awaited one `tick_once()` provider turn before claiming more inbox work,
causing head-of-line blocking across conversations.

### Local scheduler-parallelism fix

Local change:

- `PeerChatScheduler.tick_many(max_concurrent=...)` concurrently runs bounded
  `tick_once()` calls over the same durable inbox queue;
- sqlite claim transactions remain the inbox authority;
- `only_inbox_item_id` continues to force single-item operation;
- platform runner passes its existing `--max-concurrent` value to peer-chat
  scheduler ticks through `CoordinatorControlService`.

Focused validation:

```text
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
-> 16 passed in 4.63s

uv run pytest tests/xmuse/test_platform_runner.py -q
-> 66 passed, 1 warning in 8.86s
```

Classification: local focused validation only.

### Loop 25z52: triple-conversation probe after scheduler parallelism

Runtime root:

```text
/tmp/xmuse-post-pr83-main-U3Tz5c/.goal-runs/2026-06-19/loop-25z52-patched-parallel-scheduler-143353
```

Probe:

- same service shape as Loop 25z50;
- runner used `--max-concurrent 4`;
- created three deterministic conversations with Codex architect, Codex
  execute, and OpenCode review participants;
- posted three human `@architect` messages;
- prohibited proposal/lane output.

Observed concurrency:

```text
elapsed_s=16
initial inbox=3
claimed=3
```

This differs from Loop 25z51, where only one peer turn was effectively in
flight while other conversation inboxes queued behind it.

Final durable state:

```text
messages=19
chat_inbox_items=9
open=0
peer_turn_latency_traces=9
peer_turn_mcp_tool_traces=15
proposals=0
resolutions=0
```

Latency trace summary:

```text
architect traces:
  3 x delivery_mode=mcp_writeback
  3 x degraded_reason=peer_response_timeout_after_writeback

execute traces:
  3 x delivery_mode=mcp_writeback
  degraded_reason=null

review traces:
  3 x delivery_mode=mcp_writeback
  degraded_reason=null
```

Evidence artifact:

```text
loop_driver_artifacts/final_snapshot.json
```

Remaining behavior gap:

- at least one architect summary was posted before the execute/review replies
  landed;
- alpha/beta did not produce a later final summary after both peer replies
  were visible;
- therefore this is real durable multi-peer groupchat evidence, but not proof
  that natural groupchat orchestration semantics are production-ready.

Classification: local runtime evidence that bounded parallel peer-chat inbox
consumption works and all nine inbox items reached durable `mcp_writeback`
without proposal/lane leakage. It also preserves the remaining gap that
provider result acknowledgement and architect final-summary gating are not yet
strong enough for production-ready natural groupchat claims.

### Loop 25z53: final-summary gating baseline

Runtime root:

```text
/tmp/xmuse-post-pr84-main-VLltPM/.goal-runs/2026-06-19/loop-25z53-final-summary-gating-baseline-145013
```

Probe:

- started Chat API on `:8201`, MCP on `:8100`, and
  `xmuse-platform-runner --peer-chat --persistent-review-god --max-concurrent 4
  --no-auto-merge`;
- created two deterministic conversations with Codex architect, Codex execute,
  and OpenCode review peers;
- asked architect to hand off to execute and review, then post a final summary
  beginning with `FINAL_SUMMARY_AFTER_BOTH_REPLIES` only after both replies
  were durable.

Observed:

```text
alpha: execute_replies=1, review_replies=1, final_summary_messages=0
beta:  execute_replies=1, review_replies=1, final_summary_messages=0
proposals=0
resolutions=0
```

Artifacts:

```text
loop_driver_artifacts/final_snapshot.json
loop_driver_artifacts/final_summary_gating_eval.json
```

Classification: negative local runtime evidence. Peer replies became durable,
but no authority-level follow-up nudged architect to close the final summary.

### Loop 25z54: explicit peer-reply drain callback first run

Runtime root:

```text
/tmp/xmuse-post-pr84-main-VLltPM/.goal-runs/2026-06-19/loop-25z54-final-summary-callback-rerun-150311
```

Local change under test:

- when a GOD replies to a direct peer `mention`, `ChatStore` can enqueue a
  `peer_reply_drain_callback` to the original sender after no unread/claimed
  direct mentions from that sender remain.

Observed failure:

```text
architect messages=2 per conversation
initial architect inbox stayed open
execute/review inbox items stayed queued
delivery_mode=failed
degraded_reason=peer_no_result_message
```

Classification: negative local runtime evidence. Architect produced
`chat_mention` side effects but did not close the current human inbox, so
scheduler progress still depended on provider final-result behavior.

### Loop 25z55: handoff writeback and callback success

Runtime root:

```text
/tmp/xmuse-post-pr84-main-VLltPM/.goal-runs/2026-06-19/loop-25z55-handoff-reply-callback-rerun-152044
```

Local changes under test:

- `chat_mention` accepts `reply_to_inbox_item_id`;
- scheduler recognizes `chat_mention` as a real MCP writeback stage;
- peer prompts describe handoff as one durable `chat_mention` writeback.

Final durable state:

```text
alpha:
  messages=6, inbox=4, open_inbox=0, read_inbox=4
  execute_replies=1, review_replies=1
  callback_items=1, callback_read=1
  marker_messages=1, final_after_both=true
  proposals=0, resolutions=0

beta:
  messages=6, inbox=4, open_inbox=0, read_inbox=4
  execute_replies=1, review_replies=1
  callback_items=1, callback_read=1
  marker_messages=1, final_after_both=true
  proposals=0, resolutions=0
```

Remaining behavior gap in this run:

```text
architect traces included peer_response_timeout_after_writeback
```

Classification: positive local runtime evidence for the two-conversation
groupchat sequence through final summary. It still showed an efficiency gap:
the provider result timeout delayed scheduler slot release after durable
writeback.

### Loop 25z56: early-release regression

Runtime root:

```text
/tmp/xmuse-post-pr84-main-VLltPM/.goal-runs/2026-06-19/loop-25z56-early-writeback-runtime-153053
```

Local change under test:

- scheduler returned early after detecting durable MCP writeback before the
  provider result.

Observed regression:

```text
initial_handoff_closed=true
early_writeback_traces=2
execute_replies=1
review_replies=0
callback_created=true before review handoff completed
```

Classification: negative local runtime evidence. Immediate early release freed
the scheduler slot, but cut off multi-step same-turn handoffs before the
architect could enqueue review work.

### Loop 25z57: early-release grace and final-summary success

Runtime root:

```text
/tmp/xmuse-post-pr84-main-VLltPM/.goal-runs/2026-06-19/loop-25z57-grace-early-writeback-runtime-153705
```

Local change under test:

- durable writeback still wins over provider final-result delay;
- scheduler now waits a short post-writeback grace window before aborting the
  provider turn, allowing consecutive handoff tool calls in the same turn.

Final durable state:

```text
alpha:
  messages=6, inbox=4, open_inbox=0, read_inbox=4
  execute_replies=1, review_replies=1
  callback_items=1, callback_read=1
  marker_messages=1, final_after_both=true
  mcp_writeback_traces=4, early_writeback_traces=2
  timeout_after_writeback_traces=0
  proposals=0, resolutions=0

beta:
  messages=6, inbox=4, open_inbox=0, read_inbox=4
  execute_replies=1, review_replies=1
  callback_items=1, callback_read=1
  marker_messages=1, final_after_both=true
  mcp_writeback_traces=3, early_writeback_traces=2
  timeout_after_writeback_traces=0
  proposals=0, resolutions=0
```

Artifacts:

```text
loop_driver_artifacts/final_snapshot.json
loop_driver_artifacts/final_summary_gating_eval.json
```

Classification: strongest current local peer-chat evidence. It proves this
bounded two-conversation runtime path only: human demand to Codex architect
handoff, Codex execute reply, OpenCode review reply, durable peer-reply drain
callback, and architect final summary after both replies. It is not server
truth, review truth, production-ready groupchat, live MemoryOS, overnight
readiness, or full closure.

## 2026-06-19 Post-PR87 High-Concurrency Peer-Chat Reruns

These runs used latest `origin/main` after PR #87 merged as
`17a75cbe2cb07b06e05cd40e432e867ea2fd5e8f`, then local candidate changes for
Loops 25z62 and 25z63. They used isolated `XMUSE_ROOT` directories under
`.goal-runs/2026-06-19/`.

Service shape:

```bash
XMUSE_ROOT="$RUN_ROOT" uv run python -m xmuse.chat_api
XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server
XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_RAY_GOD_MCP=0 \
  XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" \
  --mcp-port 8100 --peer-chat --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --max-hours 1.1 --max-concurrent 10 --no-auto-merge
```

The driver created six public Chat API conversations per run. Each conversation
used Codex architect, Codex execute, and OpenCode review participants. The
driver posted a human `@architect` groupchat demand and inspected durable
`chat.db` state only.

### Loop 25z61: post-PR87 main high-concurrency negative run

Runtime root:

```text
/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z61-post-pr87-main-grace20-highconcurrency-163937
```

Final durable state:

```text
conversation_count=6
all_initial_handoff_closed=true
all_final_after_both=false
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
total_failed_traces=1
total_timeout_after_writeback_traces=0
callback_items_by_label={alpha:2,beta:1,gamma:1,delta:1,epsilon:1,zeta:1}
```

The alpha conversation exposed same-participant concurrent delivery: a normal
architect mention and a `peer_reply_drain_callback` were delivered to the same
Codex architect session concurrently. The failed trace reason was:

```text
readuntil() called while another coroutine is already waiting for incoming data
```

Classification: negative local runtime evidence for same participant/session
fan-out. This is a peer-chat scheduler delivery-lifecycle boundary.

### Loop 25z62: participant-lock candidate rerun

Runtime root:

```text
/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z62-participant-lock-rerun-165536
```

Local change under test:

- `PeerChatScheduler` serializes delivery per target participant while keeping
  cross-participant `tick_many(max_concurrent=...)` fan-out.

Final durable state:

```text
conversation_count=6
all_final_after_both=false
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
total_failed_traces=2
total_timeout_after_writeback_traces=0
callback_items_by_label={alpha:2,beta:1,gamma:2,delta:1,epsilon:1,zeta:1}
```

The previous `readuntil()` concurrent-read failure did not recur. The run
instead exposed a prompt/tool-contract gap: peers could answer a simple request
with `chat_mention` back to the sender, creating extra architect inbox items
and failed `peer_no_inbox_writeback_message` traces.

Classification: participant serialization locally mitigated the transport
failure, but the run remained negative for reply semantics.

### Loop 25z63: prompt-contract rerun success

Runtime root:

```text
/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z63-prompt-contract-rerun-170840
```

Local changes under test:

- same participant delivery lock from Loop 25z62;
- peer prompt now directs answer/report/review/critique/risk replies to use
  `chat_post_message` with `reply_to_inbox_item_id`, not `chat_mention` back
  to the sender.

Final durable state:

```text
conversation_count=6
all_initial_handoff_closed=true
all_final_after_both=true
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
total_failed_traces=0
total_timeout_after_writeback_traces=0
callback_items_by_label={alpha:1,beta:1,gamma:1,delta:1,epsilon:1,zeta:1}
```

Per-conversation shape:

```text
messages=6
inbox=4
open_inbox=0
execute_replies=1
review_replies=1
callback_items=1
marker_messages=1
proposals=0
resolutions=0
```

Classification: positive local runtime evidence for a six-conversation
Codex/OpenCode peer-chat stability path under `--max-concurrent 10`. It is not
production readiness, live MemoryOS proof, GitHub review truth, full L8-L10
closure, full L1-L11 closure, or overnight readiness.

## 2026-06-19 Loop 25z64: post-PR88 groupchat-produced code lane

Runtime root:

```text
/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z64-post-pr88-fullchain-code-lane-172812
```

Execution worktree:

```text
/tmp/loop-25z64-post-pr88-fullchain-code-lane-172812-exec
```

Control branch and head under test:

```text
codex/post-pr87-runtime-audit
HEAD=a8144975612b9a57eca5edacb5230a246668e47f
```

Service shape:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --max-hours 1.1 --max-concurrent 8 --no-auto-merge
```

Human demand:

```text
Ask architect to coordinate one real code-change fullchain for adding
participants.provider_summary to the conversation inspector payload, derived
from durable participant rows and scoped to chat inspector/read-model code.
```

Durable groupchat and approval:

```text
conversation_id=conv_ef1a169072d14cceb6de94451982e2e3
collaboration_run=collab_11773649ef01478cbd570e55bcdcbb8c
proposal_id=prop_b06c970448f44e22a5397dbe5da61e11
resolution_id=res_861bd80750644822975605a8d3518b20
lane_id=loop25z64_inspector_provider_summary
final_action_hold_id=final-7f324c713574
```

Groupchat chain:

```text
human -> architect mention: read, mcp_writeback
architect -> execute feasibility request: read, mcp_writeback
execute -> collaboration response: received, executable
collaboration callback -> architect: read, chat_emit_proposal
peer reply drain callback -> architect: read, final proposal note
operator runtime-driver approval -> lane projection
dispatch bridge -> execute acknowledgement: read, mcp_writeback
```

Lane result:

```text
status=awaiting_final_action
base_head_sha=a8144975612b9a57eca5edacb5230a246668e47f
worktree=/tmp/loop-25z64-post-pr88-fullchain-code-lane-172812-exec
changed_files:
  src/xmuse_core/chat/inspector_builder.py
  tests/xmuse/test_peer_chat_dashboard.py
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_8f729098cd8a45e5a09094f495d1b604
review_decision=merge
review_verdict_id=verdict-loop25z64_inspector_provider_summary
```

Gate evidence:

```text
logs/gates/loop25z64_inspector_provider_summary/report.json
passed=true
blocking_passed=true
profile_ids=["xmuse-core"]
stdout="266 passed, 2 warnings in 59.95s"
```

Candidate diff:

```text
src/xmuse_core/chat/inspector_builder.py | 14 +++++++++++
tests/xmuse/test_peer_chat_dashboard.py  | 41 ++++++++++++++++++++++++++++++++
```

Recorded artifacts:

```text
loop_driver_artifacts/conversation_create.json
loop_driver_artifacts/human_message.json
loop_driver_artifacts/approval_response.json
loop_driver_artifacts/final_snapshot.json
loop_driver_artifacts/final_lane.json
review_plane.json
final_actions.json
logs/platform-runner.log
logs/driver.log
```

Observed review-state noise:

```text
InvalidTransitionError: cannot transition loop25z64_inspector_provider_summary from reviewed to rejected
```

The lane still reached `awaiting_final_action` with `review_decision=merge`.
Because the final lane record did not include `review_delivery_mode=persistent`
or `persistent_review_degraded=false`, this run is not claimed as complete
persistent OpenCode delivery proof. It is local runtime evidence for a registered
OpenCode review peer being selected in the lane review path and for the full
groupchat-produced code lane reaching final-action hold under `--no-auto-merge`.

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse-platform-runner, xmuse-mcp-server, chat_api, codex exec, opencode run: no
matching live process after shutdown checks
```

Classification: local runtime proof for one small code-change lane from
durable GOD groupchat through execute feasibility, proposal, approval, isolated
execution, gate, review verdict, and final-action hold. This is not production
readiness, GitHub review truth, live MemoryOS proof, full L8-L10 closure, full
L1-L11 closure, or overnight readiness.

## 2026-06-19 Loop 25z65: post-PR90 review-state repeat

Runtime root:

```text
/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z65-post-pr90-review-state-repeat-180741
```

Execution worktree:

```text
/tmp/loop-25z65-post-pr90-review-state-repeat-180741-exec
```

Control head under test:

```text
origin/main
HEAD=a8cceabb51022ddf802da276df1e4c37419b65b5
```

Service shape:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8201, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" uv run xmuse-mcp-server

XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8201 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8100 \
  --peer-chat --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --max-hours 1.1 --max-concurrent 8 --no-auto-merge
```

Human demand:

```text
Create only docs/xmuse/post-pr90-review-state-repeat-note.md in the isolated
lane worktree, as a no-PR runtime proof lane for post-PR90 review-state
idempotence. Do not edit product code or broad docs.
```

Durable ids:

```text
conversation_id=conv_5e579702d7314c7a9307311c93c70bc6
proposal_id=prop_6bf73b4d50834e8c94f04306137dbfbe
resolution_id=res_e0d8e2d6c5934d6cbf67d35b874bec8c
lane_id=loop25z65_post_pr90_review_state_repeat
review_task_id=rtask_f8bb921c75bd4ba9b61ba3d006aea38b
review_verdict_id=verdict-merge-rtask_f8bb921c75bd4ba9b61ba3d006aea38b
final_action_hold_id=final-9e1f94e1ee47
```

Lane result:

```text
status=awaiting_final_action
base_head_sha=a8cceabb51022ddf802da276df1e4c37419b65b5
worktree=/tmp/loop-25z65-post-pr90-review-state-repeat-180741-exec
changed_files:
  docs/xmuse/post-pr90-review-state-repeat-note.md
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_3ec0415065b349fb9d2fcd116d352eac
review_delivery_mode=persistent
persistent_review_degraded=false
persistent_review_identity=configured:part_3ec0415065b349fb9d2fcd116d352eac
peer_delivery_mode=configured_peer
review_decision=merge
```

Gate evidence:

```text
logs/gates/loop25z65_post_pr90_review_state_repeat/report.json
passed=true
blocking_passed=true
profile_ids=["strict-product"]
command=uv run pytest -q tests/xmuse/test_package_boundaries.py
returncode=0
```

Lane-scoped worker checks recorded by the final lane:

```text
uv run python - <<'PY' ... content-check for docs/xmuse/post-pr90-review-state-repeat-note.md ... PY
git diff --check -- docs/xmuse/post-pr90-review-state-repeat-note.md
git status --short
```

Runtime transition-noise search:

```text
rg "InvalidTransitionError|cannot transition|xmuse_core_operation_failed|review_conflict_ignored|ignored_review" \
  "$RUN_ROOT"/logs "$RUN_ROOT"/feature_lanes.json "$RUN_ROOT"/review_plane.json \
  "$RUN_ROOT"/final_actions.json "$RUN_ROOT"/loop_driver_artifacts \
  --glob '!**/peer_chat_worktree/**'
-> no matches
```

Recorded artifacts:

```text
loop_driver_artifacts/final_lane.json
review_plane.json
final_actions.json
logs/gates/loop25z65_post_pr90_review_state_repeat/report.json
logs/platform-runner.log
logs/driver.log
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse-platform-runner, xmuse-mcp-server, chat_api, codex exec, opencode run:
no matching live process after shutdown checks
```

Classification: positive bounded local runtime repeat for the PR #90
review-state idempotence fix on a docs-only lane. It reached persistent
OpenCode review metadata and final-action hold under `--no-auto-merge` without
the Loop 25z64 invalid transition noise recurring in the runtime artifacts
searched above. This is not production readiness, GitHub review truth, live
MemoryOS proof, full L8-L10 closure, full L1-L11 closure, or overnight
readiness.

## 2026-06-19 Loop 25z66: post-PR91 parallel groupchat stability

Loop target: repeat real Codex/OpenCode GOD groupchat stability from current
main while increasing safe parallelism. This loop did not create or approve
lane proposals.

Control head under test:

```text
origin/main
HEAD=ff6a5fd9f61b86d5c1989fd6f613bcf5e6906009
```

Parallel shard A:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z66a-post-pr91-parallel-stability-183602
EXEC_WORKTREE=/tmp/loop-25z66a-post-pr91-parallel-stability-183602-exec
CHAT_PORT=8202
MCP_PORT=8102
labels=alpha,beta,gamma
```

Parallel shard B:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z66b-post-pr91-parallel-stability-183602
EXEC_WORKTREE=/tmp/loop-25z66b-post-pr91-parallel-stability-183602-exec
CHAT_PORT=8203
MCP_PORT=8103
labels=delta,epsilon,zeta
```

Service shape per shard:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=<chat-port>, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; import uvicorn; from xmuse.mcp_server import create_app; uvicorn.run(create_app(os.environ["XMUSE_ROOT"]), host="127.0.0.1", port=<mcp-port>, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:<chat-port> \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" \
  --mcp-port <mcp-port> --peer-chat \
  --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --max-hours 0.8 --max-concurrent 4 --no-auto-merge
```

Driver:

```bash
uv run python .goal-runs/2026-06-19/loop-25z66-driver.py \
  --chat-url http://127.0.0.1:<chat-port> \
  --xmuse-root "$RUN_ROOT" \
  --labels <labels> \
  --timeout-s 900 --poll-s 5
```

The driver used public Chat API calls to create conversations and post human
`@architect` messages. It inspected durable `chat.db` tables for messages,
inbox items, proposals, resolutions, and peer latency traces.

Durable conversation ids:

```text
alpha=conv_4a132f9eefda4380a3e7e8217ea3aba0
beta=conv_558a261682f24f178733a89fdb73de0e
gamma=conv_bf0793cdc2aa4a3196ac554dd46cc242
delta=conv_1294a445dd514c678c339b2daace932b
epsilon=conv_9d39e49bfeee45a5a4b311b8b8a27c9b
zeta=conv_f5f5e76c51674944838c6f0c800cc577
```

Final summary across both shards:

```text
conversation_count=6
all_initial_handoff_closed=true
all_final_after_both=true
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
no_open_or_failed_inbox=true
no_failed_or_timeout_traces=true
total_failed_traces=0
total_timeout_after_writeback_traces=0
```

Per-conversation durable shape:

```text
messages=6
inbox=4
open_inbox=0
failed_inbox=0
execute_replies=1
review_replies=1
architect_messages=3
callback_items=1
callback_read=1
proposals=0
resolutions=0
failed_traces=0
timeout_after_writeback_traces=0
```

The driver reported `marker_messages=2` because the human prompt also includes
the exact final marker string. The pass condition used `final_after_both`,
which requires a later durable architect message containing the marker after
both execute and review replies.

Recorded artifacts:

```text
loop-25z66a.../commands.txt
loop-25z66a.../loop_driver_artifacts/conversation_posts.json
loop-25z66a.../loop_driver_artifacts/final_snapshot.json
loop-25z66a.../loop_driver_artifacts/stability_eval.json
loop-25z66a.../logs/{chat-api,mcp-server,driver}.log

loop-25z66b.../commands.txt
loop-25z66b.../loop_driver_artifacts/conversation_posts.json
loop-25z66b.../loop_driver_artifacts/final_snapshot.json
loop-25z66b.../loop_driver_artifacts/stability_eval.json
loop-25z66b.../logs/{chat-api,mcp-server,driver}.log
```

Cleanup:

```text
8102/8103/8202/8203 listeners: none
loop-25z66 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks, excluding the check command
itself
execution worktrees: clean detached HEAD
```

Classification: positive bounded local runtime proof for two independent
parallel groupchat stability shards on current main. It proves that, in this
run, six real Codex/OpenCode GOD conversations reached the final-summary path
with durable MCP/callback writeback and no proposal/lane side effects. It is
not production readiness, overnight soak, live MemoryOS proof, GitHub review
truth, full L8-L10 closure, full L1-L11 closure, or natural peer-GOD
completion as a finished product claim.

## 2026-06-19 Loop 25z67: default review authority gap

Loop target: test current main's default review authority when a durable
conversation registers an OpenCode review participant, but the groupchat
proposal does not include `review_runtime`.

Control head under test:

```text
HEAD=9f19d84aeeb52043517a40e0c29f72edda2366a6
```

Run shape:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z67-default-review-authority-185315
EXEC_WORKTREE=/tmp/loop-25z67-default-review-authority-185315-exec
CHAT_PORT=8204
MCP_PORT=8104
```

The driver created a conversation with:

```text
architect=codex/gpt-5.4
execute=codex/gpt-5.4-mini
review=opencode/opencode-go/deepseek-v4-flash
```

The human prompt requested exactly one docs-only lane and explicitly requested
no `review_runtime` field in the proposal. Durable output:

```text
conversation_id=conv_a1d50b420a644142bbefca696ed0c97b
proposal_id=prop_570cd4267a214564814ecf4a5dcbd087
proposal_has_review_runtime=false
status=awaiting_final_action
classification=not_defaulted
review_peer_defaulted absent
review_peer_id absent
review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
```

The registered review participant existed:

```text
participant_id=part_dec30b6b6d674a2b9e0d907cbef7ce5a
role=review
cli_kind=opencode
model=opencode-go/deepseek-v4-flash
status=active
```

Classification: negative bounded local runtime proof. Main could carry the
groupchat through proposal, approval, execution, gate, review, and final-action
hold, but default review authority did not route to the already registered
OpenCode review peer. The lane fell back to Codex one-shot review because no
feature-scoped default review identity existed. This is not production
readiness, GitHub review truth, live MemoryOS proof, full L8-L10 closure, or
full L1-L11 closure.

Cleanup:

```text
8104/8204 listeners: none
loop-25z67 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks
execution worktree: dirty only with the expected probe docs note
```

## 2026-06-19 Loop 25z68: post-fix default OpenCode review authority

Loop target: repeat the Loop 25z67 scenario after a narrow local change that
lets default review routing reuse a unique active OpenCode review participant
already registered in the durable conversation. The proposal still did not
include `review_runtime`.

Control head under test:

```text
HEAD=9f19d84aeeb52043517a40e0c29f72edda2366a6
local branch=codex/default-review-opencode-peer-routing
local code under test includes unmerged changes in review_god.py
```

Run shape:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z68-default-review-authority-postfix-190708
EXEC_WORKTREE=/tmp/loop-25z68-default-review-authority-postfix-190708-exec
CHAT_PORT=8205
MCP_PORT=8105
```

Final durable summary:

```text
classification=defaulted_opencode_review_peer
conversation_id=conv_82c511508d0645c08c11f718837d2a07
proposal_has_review_runtime=false
status=awaiting_final_action
review_peer_defaulted=true
review_peer_id=part_7ccc1f017c054234a48ed023a801b8df
review_peer_participant.cli_kind=opencode
review_peer_participant.model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
persistent_review_identity=configured:part_7ccc1f017c054234a48ed023a801b8df
```

The review session record also preserved the OpenCode runtime binding:

```text
role=review
runtime=opencode
participant_id=part_7ccc1f017c054234a48ed023a801b8df
feature_scope_id=configured-review:loop25z68_default_review_authority
model=opencode-go/deepseek-v4-flash
```

The lane wrote only the expected docs note in the isolated execution worktree:

```text
docs/xmuse/default-review-authority-runtime-note.md
```

Cleanup:

```text
8105/8205 listeners: none
loop-25z68 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks
execution worktree: dirty only with the expected probe docs note
```

Classification: positive bounded local runtime proof for the targeted default
review authority fix. It proves that, in this local run, a conversation with a
registered OpenCode review peer can reach persistent configured-peer review
without the proposal naming `review_runtime`. This is not GitHub CI/server
truth, GitHub review truth, production readiness, live MemoryOS proof,
overnight readiness, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-19 Loop 25z69: code-change lane after default OpenCode review merge

Loop target: rerun a real code-change lane from current main after PR #93
merged the default OpenCode review routing fix. The groupchat proposal again
omitted `review_runtime`; review should still use the registered OpenCode peer.

Control head under test:

```text
HEAD=7468a5ab8797cf0a34528de419ceaf730034e75e
```

Run shape:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z69-code-change-after-pr93-192536
EXEC_WORKTREE=/tmp/loop-25z69-code-change-after-pr93-192536-exec
CHAT_PORT=8206
MCP_PORT=8106
```

Service commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=8206, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" \
  uv run python -c 'import os; import uvicorn; from xmuse.mcp_server import create_app; uvicorn.run(create_app(os.environ["XMUSE_ROOT"]), host="127.0.0.1", port=8106, log_level="info")'

XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_WORKTREE" \
  XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  XMUSE_RAY_GOD_MCP=0 XMUSE_CHAT_API_URL=http://127.0.0.1:8206 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" --mcp-port 8106 \
  --peer-chat --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --default-review-peer-routing --max-hours 1.2 --max-concurrent 4 \
  --no-auto-merge

uv run python .goal-runs/2026-06-19/loop-25z69-code-change-driver.py \
  --chat-url http://127.0.0.1:8206 --xmuse-root "$RUN_ROOT" \
  --feature-id loop25z69_review_peer_metadata --timeout-s 1800 --poll-s 5
```

Durable result:

```text
classification=code_change_defaulted_opencode_review_peer
conversation_id=conv_5d320e51228847408f9883da9844950c
proposal_id=prop_b75c0d557eb84932bddca7977279ecb3
resolution_id=res_b317a3806e464d189948c063ebf4161b
collaboration_run_id=collab_6e15b09450364190b7c3eb5b828302f7
lane_id=loop25z69_review_peer_metadata
proposal_has_review_runtime=false
status=awaiting_final_action
gate_passed=true
review_decision=merge
final_action_hold_id=final-74909d63bc0b
review_peer_defaulted=true
review_peer_id=part_19d36e5e2f644175865795a6823ec22c
review_peer_participant.cli_kind=opencode
review_peer_participant.model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
persistent_review_identity=configured:part_19d36e5e2f644175865795a6823ec22c
```

OpenCode review session:

```text
role=review
runtime=opencode
participant_id=part_19d36e5e2f644175865795a6823ec22c
feature_scope_id=configured-review:loop25z69_review_peer_metadata
model=opencode-go/deepseek-v4-flash
```

The isolated execution worktree produced a small candidate diff:

```text
src/xmuse_core/platform/execution/review_god.py
src/xmuse_core/platform/run_health.py
tests/xmuse/test_platform_runner.py
tests/xmuse/test_review_plane_orchestrator_integration.py
tests/xmuse/test_run_health.py
```

Candidate validation in the execution worktree:

```text
uv run pytest -q tests/xmuse/test_review_plane_orchestrator_integration.py::test_default_review_peer_routing_reuses_registered_opencode_review_peer tests/xmuse/test_review_plane_orchestrator_integration.py::test_configured_review_peer_preferred_success_records_peer_metadata tests/xmuse/test_run_health.py::test_summarize_run_health_exposes_peer_delivery_degraded_visibility tests/xmuse/test_platform_runner.py::test_health_once_exposes_peer_delivery_visibility_read_only
-> 4 passed

uv run pytest -q tests/xmuse/test_review_plane_orchestrator_integration.py -k 'review_peer'
-> 20 passed, 29 deselected

uv run ruff check src/xmuse_core/platform/execution/review_god.py src/xmuse_core/platform/run_health.py tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_run_health.py tests/xmuse/test_platform_runner.py
-> All checks passed

git diff --check
-> no output
```

Cleanup:

```text
8106/8206 listeners: none
loop-25z69 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks
```

Classification: positive bounded local runtime proof for a real code-change
lane after PR #93. It also produced a small candidate improvement for review
peer runtime metadata. The candidate is not GitHub CI/server truth until a
small PR is opened and GitHub Actions runs on that pushed branch. This is not
GitHub review truth, production readiness, live MemoryOS proof, overnight
readiness, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-19 Loop 25z70: post-PR94 parallel runtime verification

Loop target: after PR #94 merged, increase operator-level parallelism with two
isolated runtime shards from the same current main. Shard A verified the
review-peer metadata read model in a fullchain lane. Shard B repeated a
three-conversation groupchat stability probe in parallel.

Control head under test:

```text
HEAD=2996643e4f13a8ea97af6b6f9675fd697a847716
```

Shard A:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z70a-post-pr94-health-metadata-195513
EXEC_WORKTREE=/tmp/loop-25z70a-post-pr94-health-metadata-195513-exec
CHAT_PORT=8207
MCP_PORT=8107
driver=.goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py
```

Shard B:

```text
RUN_ROOT=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z70b-post-pr94-parallel-stability-195513
EXEC_WORKTREE=/tmp/loop-25z70b-post-pr94-parallel-stability-195513-exec
CHAT_PORT=8208
MCP_PORT=8108
driver=.goal-runs/2026-06-19/loop-25z66-driver.py --labels kappa,lambda,mu
```

Both runners used:

```bash
uv run xmuse-platform-runner --peer-chat \
  --peer-chat-post-writeback-grace-s 20 \
  --persistent-review-god --persistent-review-timeout-s 300 \
  --default-review-peer-routing --max-concurrent 4 --no-auto-merge
```

Shard A durable result:

```text
classification=post_pr94_health_metadata_visible
conversation_id=conv_87a3fb3721de408d8242b57ebc838bef
proposal_has_review_runtime=false
lane_id=loop25z70_review_peer_health_metadata
status=awaiting_final_action
gate_passed=true
review_decision=merge
final_action_hold_id=final-2783eecf0227
review_peer_defaulted=true
review_peer_id=part_b3743a676eb146edbba63353b46df258
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
persistent_review_identity=configured:part_b3743a676eb146edbba63353b46df258
run_health_metadata_visible=true
```

The `run_health.peer_delivery.configured_peer_lanes` and
`run_health.peer_delivery.default_review_peer_routing` summaries both exposed:

```text
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
```

Shard A left only the expected isolated execution artifact:

```text
/tmp/loop-25z70a-post-pr94-health-metadata-195513-exec
?? docs/xmuse/post-pr94-review-peer-health-note.md
```

Shard B durable result:

```text
conversation_count=3
labels=kappa,lambda,mu
all_initial_handoff_closed=true
all_final_after_both=true
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
no_open_or_failed_inbox=true
no_failed_or_timeout_traces=true
total_failed_traces=0
total_timeout_after_writeback_traces=0
```

Per-conversation shape:

```text
messages=6
inbox=4
execute_replies=1
review_replies=1
architect_messages=3
callback_items=1
failed_inbox=0
failed_traces=0
timeout_after_writeback_traces=0
```

Cleanup:

```text
8107/8108/8207/8208 listeners: none
loop-25z70 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks, excluding the check command
itself
```

Classification: positive bounded local post-merge runtime proof. It proves
that, in this run, two isolated runtime shards can run concurrently; one
fullchain docs-only lane reached final-action hold with persistent defaulted
OpenCode review and health-visible review peer metadata, while one groupchat
stability shard completed three conversations without proposals or lane side
effects. This is not production readiness, overnight soak, GitHub review truth,
live MemoryOS proof, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-19 Loop 25z71: scoped process health for parallel shards

Loop target: repair the process-health false positives exposed by Loop 25z70.
Loop 25z70's Shard A lane succeeded, but its run-health snapshot saw both
parallel runners and missed the MCP server:

```text
runner_count=2
mcp_count=0
warnings=duplicate_runner_processes,missing_mcp_process
```

The authority was the shard-local `XMUSE_ROOT`; the producer was runtime
process discovery; the consumers were `run_health`, dashboard/TUI read models,
and `xmuse-platform-runner --health-once`.

Control head before PR:

```text
branch=codex/scoped-runtime-process-health
head=220edc61f11d5171a451225fdc16742f1491d15b
base=0f35f9ad33c6e701b1457b0e5aaa22bc2093e0c4
```

Runtime probe:

```text
RUN_A=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z71a-scoped-health-processes-202044
RUN_B=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z71b-scoped-health-processes-202044
EXEC_A=/tmp/loop-25z71a-scoped-health-processes-202044-exec
EXEC_B=/tmp/loop-25z71b-scoped-health-processes-202044-exec
ports A=8209/8109
ports B=8210/8110
```

Each shard started Chat API, MCP server, and platform runner. Health was read
with:

```bash
XMUSE_ROOT="$RUN_A" XMUSE_CHAT_API_URL=http://127.0.0.1:8209 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_A" --mcp-port 8109 \
  --health-once --health-check-http > "$RUN_A/health-once-postfix.json"

XMUSE_ROOT="$RUN_B" XMUSE_CHAT_API_URL=http://127.0.0.1:8210 \
  uv run xmuse-platform-runner --xmuse-root "$RUN_B" --mcp-port 8110 \
  --health-once --health-check-http > "$RUN_B/health-once-postfix.json"
```

Post-fix result for both shards:

```text
runner_count=1
mcp_count=1
counts_by_service.runner=1
counts_by_service.mcp=1
counts_by_service.chat_api=1
warnings=[]
```

Validation:

```text
uv run pytest tests/xmuse/test_run_processes.py tests/xmuse/test_run_health.py tests/xmuse/test_platform_runner.py tests/xmuse/test_dashboard_health.py tests/xmuse/test_dashboard_api.py -q
-> 241 passed, 9 warnings

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check .
-> All checks passed

git diff --check
-> no output

test ! -e xmuse/__init__.py
-> passed
```

GitHub server facts:

```text
PR #96=https://github.com/iiyazu/Cross-Muse/pull/96
head=220edc61f11d5171a451225fdc16742f1491d15b
merge_commit=dcf4badf5da82cb472ea0f23d1c825f94d26218b
PR CI run=27825635972 success
post-merge main CI run=27825747726 success
```

Cleanup:

```text
8109/8110/8209/8210 listeners: none
loop-25z71 xmuse-platform-runner, MCP, Chat API, codex/opencode processes:
no matching live process after shutdown checks
```

Classification: positive bounded local runtime health proof plus inspected
GitHub server facts for PR #96. It proves scoped process health for this
parallel-shard shape. It is not production readiness, overnight soak, GitHub
review truth, live MemoryOS proof, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-19 Loops 25z72-25z74: higher parallelism, empty worktree, and untracked diff

Loop 25z72 increased local operator parallelism to three isolated shards from
post-PR97 main:

```text
control_head=591aa68e470aa5272df5bc46bbfab06a917bd4f4
shard_a=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z72a-post-pr97-fullchain-204122
shard_b=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z72b-post-pr97-stability-204122
shard_c=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z72c-post-pr97-stability-204122
ports A=8211/8111
ports B=8212/8112
ports C=8213/8113
```

Shard B and Shard C each ran three Codex/OpenCode groupchat conversations.
Both stability shards closed all conversations:

```text
conversation_count_per_stability_shard=3
total_stability_conversations=6
all_initial_handoff_closed=true
all_final_after_both=true
all_callbacks_created=true
all_callbacks_consumed=true
no_proposals_or_resolutions=true
no_open_or_failed_inbox=true
no_failed_or_timeout_traces=true
```

Shard A drove a docs-only fullchain lane but failed at gate:

```text
lane_status=gate_failed
failure_reason=gate_failed
gate_profiles_source=missing
warning=gate_profiles.json missing in XMUSE_ROOT and lane worktree; gate failed closed
```

Root cause: the harness pre-created an empty `XMUSE_EXECUTION_WORKTREE`. The
orchestrator treated that empty directory as the lane worktree instead of
replacing it with a git worktree. The child worker wrote the requested note in
the empty directory, but the gate correctly failed closed because
`xmuse/gate_profiles.json` was absent.

PR #98 fixed that boundary by recreating empty lane worktree directories as
normal git worktrees while preserving existing non-empty non-git compatibility.
Loop 25z73 intentionally pre-created an empty execution worktree again:

```text
branch=codex/recreate-empty-lane-worktree
head=17f1d3ef23968c1060b1e09b58668924a87b24a4
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z73-empty-worktree-fullchain-205536
exec=/tmp/loop-25z73-empty-worktree-fullchain-205536-exec
```

The worktree recovery succeeded and the gate passed:

```text
exec_is_git_worktree=true
exec_gate_profiles_exists=true
base_head_sha=591aa68e470aa5272df5bc46bbfab06a917bd4f4
gate_passed=true
```

The same run then reached review and was rejected:

```text
lane_status=rejected
review_decision=rework
review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
review_summary=The requested docs-only note content is correct and scoped correctly, but it exists only as an untracked file...
```

Root cause: the MCP `get_diff(lane_id)` tool returned only `git diff HEAD`, so
review could not see untracked new files even though later merge staging uses
`git add -A`.

PR #99 fixed that boundary by appending `git diff --no-index -- /dev/null
<path>` patches for untracked files to the `get_diff` result. Loop 25z74 reran
the same shape:

```text
branch=codex/include-untracked-lane-diff
head=4a491dfea5cb9d0026d4afa7360cf1b466af6831
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z74-untracked-diff-fullchain-211119
exec=/tmp/loop-25z74-untracked-diff-fullchain-211119-exec
```

Loop 25z74 reached final-action hold:

```text
proposal_has_review_runtime=false
exec_is_git_worktree=true
exec_gate_profiles_exists=true
base_head_sha=cae76c1da7d1c38df9884579ba822b8019f3b197
gate_passed=true
review_decision=merge
review_summary=review accepted
lane_status=awaiting_final_action
health.runner_count=1
health.mcp_count=1
health.warnings=null
```

Remaining bounded caveat:

```text
review_delivery_mode=one_shot_fallback
persistent_review_degraded=true
persistent_review_degraded_reason=missing_feature_identity
review_peer_defaulted=null
review_peer_cli_kind=null
review_peer_model=null
```

Validation and server facts:

```text
PR #98=https://github.com/iiyazu/Cross-Muse/pull/98
PR #98 head=17f1d3ef23968c1060b1e09b58668924a87b24a4
PR #98 merge_commit=cae76c1da7d1c38df9884579ba822b8019f3b197
PR #98 CI run=27827540774 success
post-PR98 main CI run=27827589417 success

PR #99=https://github.com/iiyazu/Cross-Muse/pull/99
PR #99 head=4a491dfea5cb9d0026d4afa7360cf1b466af6831
PR #99 merge_commit=2325427c0b96f5bc2f804a6f72ef8d5e77782fca
PR #99 CI run=27828255039 success
post-PR99 main CI run=27828296247 success
```

Local validation for PR #98:

```text
uv run pytest tests/xmuse/test_platform_orchestrator.py -k 'worktree and dispatch_lane' -q
-> 5 passed, 236 deselected

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_platform_orchestrator.py
-> All checks passed

git diff --check
-> no output

test ! -e xmuse/__init__.py
-> passed
```

Local validation for PR #99:

```text
uv run pytest tests/xmuse/test_platform_mcp_tools.py -k 'get_diff or get_gate_report' -q
-> 2 passed, 42 deselected

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check src/xmuse_core/platform/mcp_tools.py tests/xmuse/test_platform_mcp_tools.py
-> All checks passed

git diff --check
-> no output

test ! -e xmuse/__init__.py
-> passed
```

Cleanup:

```text
8111/8112/8113/8114/8115/8211/8212/8213/8214/8215 listeners: none
loop-25z72/25z73/25z74 xmuse-platform-runner, MCP, Chat API, codex/opencode
processes: no matching live process after shutdown checks
```

Classification: positive bounded local runtime evidence plus inspected GitHub
server facts. It proves higher parallelism for six groupchat conversations in
two concurrent stability shards, empty execution worktree recovery, and
untracked-file review visibility for this docs-only lane shape. Loop 25z74
reached final-action hold, but it used one-shot review fallback with
`persistent_review_degraded_reason=missing_feature_identity`. This is not
persistent OpenCode review proof, defaulted review peer metadata proof,
production readiness, overnight soak, GitHub review truth, live MemoryOS proof,
full L8-L10 closure, or full L1-L11 closure.

### Loop 25z75: Direct Lane Graph Feature Scope Candidate

Local branch:

```text
branch=codex/direct-lane-graph-feature-scope
base_head=f03a058a0f0468e3902e2aafeb7b063601df2866
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z75-direct-scope-fullchain-213729
exec=/tmp/loop-25z75-direct-scope-fullchain-213729-exec
```

Runtime services:

```bash
uv run python -c '... uvicorn.run(create_app(run_root, execution_worktree=exec_root), port=8216) ...'
XMUSE_ROOT="$RUN" uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8116
XMUSE_ROOT="$RUN" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN" --lanes "$RUN/feature_lanes.json" \
  --mcp-port 8116 --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing --no-auto-merge
```

Driver:

```bash
uv run python .goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8216 \
  --xmuse-root "$RUN" \
  --feature-id loop25z75_direct_scope_fullchain \
  --timeout-s 1800 --poll-s 5
```

The run intentionally pre-created the execution worktree directory before
approval. Projection recreated it as a git worktree during dispatch.

Durable chain:

```text
conversation_id=conv_63ee7e0b200c42b586031e2d9ad07a80
collaboration_run=collab_0c0769c0311042d0bf9fd2a7cf48ef1b
proposal_id=prop_ce5ac39666274dacb5a0a2bf4d6550a3
resolution_id=res_e6b04d8737b84f6f99c1f710564e907d
feature_id=loop25z75_direct_scope_fullchain
feature_group=post-pr94-probe
feature_scope_id=post-pr94-probe
```

Final `feature_lanes.json` authority:

```text
status=awaiting_final_action
base_head_sha=f03a058a0f0468e3902e2aafeb7b063601df2866
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_fallback=persistent
```

The driver exited with `classification=not_defaulted` because its
`final_snapshot.json` was captured before the final persistent-review metadata
write landed. The later `feature_lanes.json` projection revision recorded the
configured/default peer metadata above. The race is a harness observation, not
a lane execution failure.

Post-run health check:

```text
chat_dispatch_bridge.status=observed
scheduler_progress.status=observed
peer_delivery.counts_by_delivery_mode.configured_peer=1
peer_delivery.degraded_or_fallback_lanes=[]
operations.cleanup.status=clean
mcp HTTP health on 8116=ready
```

Caveat: process discovery reported `mcp_count=0` because this run started MCP
through `uvicorn xmuse.mcp_server:app --port 8116` rather than the entrypoint
shape recognized by process discovery. The HTTP health check for the same MCP
server returned ready.

Execution worktree evidence:

```text
git -C /tmp/loop-25z75-direct-scope-fullchain-213729-exec status --short
-> ?? docs/xmuse/post-pr94-review-peer-health-note.md
```

Cleanup:

```text
8116/8216 listeners: none
loop-25z75 service and worker process matches: none after shutdown
```

Classification: positive bounded local candidate evidence. It shows that a
direct groupchat-produced `lane_graph` with feature scope metadata can reach
final-action hold through persistent OpenCode review without the Loop 25z74
`missing_feature_identity` fallback. This is not CI/server-verified, not
production readiness, not overnight soak, not GitHub review truth, not live
MemoryOS proof, not full L8-L10 closure, and not full L1-L11 closure.

### Loop 25z76: Post-PR101 Main Fullchain Regression Exposed Orphan Handoff

Branch and base:

```text
branch=main
head=cae16e00429a4f97e30a07ecb69e5cd977ea16e8
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z76-post-pr101-fullchain-215700
exec=/tmp/loop-25z76-post-pr101-fullchain-215700-exec
ports: chat=8217, mcp=8117
```

Runtime services:

```bash
uv run python -c '... uvicorn.run(create_app(run_root, execution_worktree=exec_root), port=8217) ...'
XMUSE_ROOT="$RUN" uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8117
XMUSE_ROOT="$RUN" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN" --lanes "$RUN/feature_lanes.json" \
  --mcp-port 8117 --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing --no-auto-merge \
  --peer-chat-post-writeback-grace-s 4
uv run python .goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8217 \
  --xmuse-root "$RUN" \
  --feature-id loop25z76_post_pr101_fullchain \
  --timeout-s 1800 --poll-s 5
```

Durable state:

```text
conversation_id=conv_b37a70d053e34116975b621741d496f6
architect_inbox=inbox_827781d38702404f84837a2926447b80
stale_collaboration_run=collab_b9e7ee25c0c14defa9c8bb0ffdc4ce58
active_collaboration_run=collab_f628dabcf6e74bf3b8d29dc51789b883
proposal_id=prop_3e765c5a9acd4585b32662a159cf5116
resolution_id=res_68f5f87988b14b7b894792d1cc5d0bbc
```

Observed failure boundary:

- The Codex architect peer used MCP `/sse`.
- It called `chat_post_message` and `chat_mention` without
  `reply_to_inbox_item_id`.
- `chat_mention` created the execute inbox, but the original architect inbox
  remained open and eventually became:

```text
status=failed
failure_reason=peer_response_timeout
responded_message_id=null
```

The chain later produced a collaboration response, proposal, approval, and a
dispatched lane, but the run was already polluted by the failed original
architect turn and a stale extra collaboration run. The services were stopped
after classification, so this loop is failure evidence, not success evidence.

Cleanup:

```text
8117/8217 listeners: none
loop-25z76 service and worker process matches: none after shutdown
```

Classification: real runtime failure at the peer-chat MCP writeback/delivery
lifecycle boundary. It is not a fullchain success, not CI/server proof, not
production readiness, not GitHub review truth, not live MemoryOS proof, not
full L8-L10 closure, and not full L1-L11 closure.

### Loop 25z77: Mention Writeback Auto-Bind Candidate Rerun

Local branch:

```text
branch=codex/peer-mention-writeback-autobind
base=cae16e00429a4f97e30a07ecb69e5cd977ea16e8
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z77-mention-autobind-fullchain-222000
exec=/tmp/loop-25z77-mention-autobind-fullchain-222000-exec
ports: chat=8218, mcp=8118
```

Candidate change:

```text
src/xmuse_core/chat/peer_service.py
```

`chat_mention` now mirrors the existing `chat_emit_proposal` behavior: when a
peer omits `reply_to_inbox_item_id` and exactly one inbox item for that
participant is currently claimed, the handoff is bound to that inbox item and
closes the current turn. `chat_post_message` was not auto-bound because Loop
25z76 showed the peer can emit progress/status messages before a real handoff;
auto-closing those would risk ending the turn too early.

Focused contract validation:

```bash
uv run pytest \
  tests/xmuse/test_mcp_server.py::test_sse_chat_mention_without_reply_id_closes_single_claimed_inbox_item \
  tests/xmuse/test_mcp_server.py::test_chat_emit_proposal_without_reply_id_closes_single_claimed_inbox_item \
  tests/xmuse/test_peer_chat_mcp_tools.py::test_chat_mention_can_reply_to_current_inbox_item \
  -q
```

Result:

```text
3 passed, 1 warning
```

Runtime commands matched Loop 25z76 with the new root/ports:

```bash
uv run python -c '... uvicorn.run(create_app(run_root, execution_worktree=exec_root), port=8218) ...'
XMUSE_ROOT="$RUN" uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8118
XMUSE_ROOT="$RUN" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN" --lanes "$RUN/feature_lanes.json" \
  --mcp-port 8118 --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing --no-auto-merge \
  --peer-chat-post-writeback-grace-s 4
uv run python .goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8218 \
  --xmuse-root "$RUN" \
  --feature-id loop25z77_mention_autobind_fullchain \
  --timeout-s 1800 --poll-s 5
```

Durable chain:

```text
conversation_id=conv_9906b4e095fe4e00bb447b0916551215
collaboration_run=collab_1727b67079964abaac851687236e1ab4
proposal_id=prop_2761fda359474a539aa8108e04c95bd4
resolution_id=res_1b353282a1fe488dbf27f93c9751a853
feature_id=loop25z77_mention_autobind_fullchain
feature_group=post-pr94-fullchain-verification
feature_scope_id=post-pr94-fullchain-verification
```

The previously failing handoff now closed durably:

```text
architect_inbox=inbox_7a30a7b71b734cee967e8c11e9b9624f
status=read
responded_message_id=msg_f1f8682f027540bf9eee072384978e80
tool_trace=chat_mention
delivery_mode=mcp_writeback
```

Final lane authority:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_fallback=persistent
run_health_metadata_visible=true
```

Post-run checks:

```text
inbox status counts: architect/read=3, execute/read=2, review/read=1
failed inbox count=0
collaboration_run.status=done
scheduler_progress.status=observed
scheduler_progress.trace_count=5
chat_dispatch_bridge.status=observed
operations.cleanup.status=clean
mcp HTTP health on 8118=ready
8118/8218 listeners: none after shutdown
loop-25z77 service and worker process matches: none after shutdown
```

Caveat: process discovery again reported `mcp_count=0` for the ad hoc
`uvicorn xmuse.mcp_server:app --port 8118` process shape, while HTTP health
for that same MCP server returned ready.

Execution worktree evidence:

```text
git -C /tmp/loop-25z77-mention-autobind-fullchain-222000-exec status --short
-> ?? docs/xmuse/post-pr94-review-peer-health-note.md
```

Classification: positive bounded local candidate evidence for the
`chat_mention` current-turn auto-bind fix and the same docs-only fullchain
shape. This is not CI/server-verified, not production readiness, not overnight
soak, not GitHub review truth, not live MemoryOS proof, not full L8-L10
closure, and not full L1-L11 closure.

### Loop 25z78: Post-PR102 Main Fullchain Confirmation

Server and local base:

```text
PR #102=https://github.com/iiyazu/Cross-Muse/pull/102
PR #102 head=d4728c36cb252899a5631d3e0686fee4fb4c47cb
PR #102 state=MERGED
merge_commit=c44a5caf247c2c049ae5af37d74a94f5b9f95ce3
main CI run=27831706622 success
branch=main
head=c44a5caf247c2c049ae5af37d74a94f5b9f95ce3
run=/tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z78-post-pr102-fullchain-223300
exec=/tmp/loop-25z78-post-pr102-fullchain-223300-exec
ports: chat=8219, mcp=8119
```

Runtime commands matched Loop 25z77 with the post-merge root/ports:

```bash
uv run python -c '... uvicorn.run(create_app(run_root, execution_worktree=exec_root), port=8219) ...'
XMUSE_ROOT="$RUN" uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8119
XMUSE_ROOT="$RUN" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN" --lanes "$RUN/feature_lanes.json" \
  --mcp-port 8119 --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing --no-auto-merge \
  --peer-chat-post-writeback-grace-s 4
uv run python .goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8219 \
  --xmuse-root "$RUN" \
  --feature-id loop25z78_post_pr102_fullchain \
  --timeout-s 1800 --poll-s 5
```

Durable chain:

```text
conversation_id=conv_5da0b99358704607b93faa47d0f8a7b2
collaboration_run=collab_592e7a3347de473ca314597e22d84c06
proposal_id=prop_469f3d8a022945ca8940d9757003dca2
resolution_id=res_efcce0c80fbd4532867c5fc833c5a573
feature_id=loop25z78_post_pr102_fullchain
feature_scope_id=lane_graph:res_efcce0c80fbd4532867c5fc833c5a573-graph-v1
```

The post-merge handoff closed durably:

```text
architect_inbox=inbox_0cee81f41e2f472c833b0bc6c1b49a72
status=read
responded_message_id=msg_98c5bd34e7de49908a4ca22422f260ba
tool_trace=chat_mention
delivery_mode=mcp_writeback
```

Final lane authority:

```text
base_head_sha=c44a5caf247c2c049ae5af37d74a94f5b9f95ce3
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
review_fallback=persistent
run_health_metadata_visible=true
```

Post-run checks:

```text
inbox status counts: architect/read=3, execute/read=2, review/read=1
failed inbox count=0
collaboration_run.status=done
scheduler_progress.status=observed
scheduler_progress.trace_count=5
chat_dispatch_bridge.status=observed
operations.cleanup.status=clean
mcp HTTP health on 8119=ready
8119/8219 listeners: none after shutdown
loop-25z78 service and worker process matches: none after shutdown
```

Caveat: process discovery again reported `mcp_count=0` for the ad hoc
`uvicorn xmuse.mcp_server:app --port 8119` process shape, while HTTP health
for that same MCP server returned ready.

Execution worktree evidence:

```text
git -C /tmp/loop-25z78-post-pr102-fullchain-223300-exec status --short
-> ?? docs/xmuse/post-pr94-review-peer-health-note.md
```

Classification: positive bounded post-merge main runtime evidence for the
`chat_mention` current-turn auto-bind fix and the same docs-only fullchain
shape. This is not production readiness, not overnight soak, not GitHub review
truth, not live MemoryOS proof, not full L8-L10 closure, and not full L1-L11
closure.

## 2026-06-20 Loop 26c2: Post-PR105 Layered Prompt Fullchain Sentinel

Purpose: rerun the largest safe post-PR105 real chain from current
`origin/main` after the layered peer-chat prompt contract landed. This loop
used the docs-only lane shape and stopped at final-action hold.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=8df4415c0586b04adffb4bc30806f9e205b04a12
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26c2-post-pr105-fullchain-010549
execution_worktree=/tmp/loop-26c2-post-pr105-fullchain-exec-010549
chat_port=8221
mcp_port=8121
feature_id=loop26c2_post_pr105_fullchain
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_ROOT" CHAT_PORT=8221 \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=int(os.environ["CHAT_PORT"]), log_level="info")'

XMUSE_ROOT="$RUN_ROOT" \
  uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8121

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" \
  --lanes "$RUN_ROOT/feature_lanes.json" --mcp-port 8121 \
  --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing \
  --no-auto-merge --peer-chat-post-writeback-grace-s 4

uv run python /tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8221 \
  --xmuse-root "$RUN_ROOT" \
  --feature-id loop26c2_post_pr105_fullchain \
  --timeout-s 1800 --poll-s 5
```

Durable chain:

```text
conversation_id=conv_bf25cd08ed9c4c79b49a8f441393514f
collaboration_run=collab_2ce7d8c34b6f4f6dbebdc41f7f26d937
proposal_id=prop_234a14f90d2c4bbb8cb15c362120c3d8
resolution_id=res_c981024731374ed68ca733079703bdca
graph_id=res_c981024731374ed68ca733079703bdca-graph-v1
feature_id=loop26c2_post_pr105_fullchain
final_action_hold_id=final-b25d00349f94
```

Chat and MCP writeback:

```text
architect initial inbox=inbox_e98b26d1fa1942b9921eabea22a9460b
architect initial status=read
architect initial responded_message_id=msg_94134560a3e14e07b244bcb41601785e
architect initial tool_trace=chat_mention

execute feasibility inbox=inbox_4733f0faf0914fa9abe525ed3d144b36
execute feasibility status=read
execute feasibility responded_message_id=msg_a4d36e93f1654a619cefa31516d6d5ae
execute feasibility tool_trace=chat_post_message

collaboration callback inbox=inbox_a1a57d4b883b423f87b57d89f7107f1a
collaboration callback status=read
collaboration callback responded_message_id=msg_85fbcf0e0bea48f98f595478252eced5
collaboration callback tool_trace=chat_emit_proposal

dispatch inbox=inbox_8fc2445191b442d5888afca3a0869cc7
dispatch status=read
dispatch responded_message_id=msg_957515b377bd4abab52927396868671b
dispatch tool_trace=chat_post_message
```

Final lane authority:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
review_peer_id=part_484bb35f90504906b7d67627c525f0bf
peer_delivery_mode=configured_peer
review_evidence_refs=feature_lanes.json#lane=loop26c2_post_pr105_fullchain, review_plane.json#task=rtask_4389b2b67d5942338e26120e8cf60d97, logs/lane_prompts/loop26c2_post_pr105_fullchain.md, logs/gates/loop26c2_post_pr105_fullchain/report.json
```

Layered prompt contract evidence:

```text
architect.prompt_contract_version=xmuse-peer-chat-prompt-v2
execute.prompt_contract_version=xmuse-peer-chat-prompt-v2
layer_order=xmuse_governance_l0, member_identity, roster_and_capabilities, local_context_capsule, tool_and_writeback_contract
architect.prompt_artifact_fingerprint=sha256:024874a8e5a40f5292e304bbc6b0c5baac359efb63a54e9646ad57b1e8888fd9
execute.prompt_artifact_fingerprint=sha256:13b65153fab2f47612f12fb48727153848890779c6b37395c3b833cb935b8115
review.prompt_contract_version=null
```

Execution and gate artifacts:

```text
worker_changed_files=docs/xmuse/post-pr94-review-peer-health-note.md
worker_file_content=Review peer runtime metadata is observable through lane health.
gate_report=logs/gates/loop26c2_post_pr105_fullchain/report.json
gate_command=uv run pytest -q tests/xmuse/test_package_boundaries.py
gate_result=passed
```

Post-run cleanup:

```text
8121 listener after shutdown: none
8221 listener after shutdown: none
loop-26c2 service and worker process matches after shutdown: none
```

Classification: positive bounded post-PR105 local runtime proof for:

- layered prompt metadata on Codex architect and execute peers;
- human -> architect -> execute collaboration -> proposal;
- accepted lane graph projection;
- isolated docs-only execution;
- package-boundary gate;
- configured OpenCode persistent review;
- final-action hold.

Caveats:

- This is one bounded docs-only sentinel, not production readiness.
- The OpenCode review peer produced a persistent review verdict, but the
  `god_sessions.json` review record still has no layered prompt contract
  fingerprint.
- The lane stopped at final-action hold and was not merged.
- The probe does not prove dynamic member mutation, restart/resume continuity,
  MemoryOS, overnight stability, GitHub review truth, or full closure.

## 2026-06-20 Loop 26d: Persistent Review Prompt Contract Metadata

Purpose: rerun the largest safe post-PR106 real chain after adding a distinct
persistent-review session prompt contract. This loop used the same docs-only
lane shape and stopped at final-action hold.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=30c48916d99943fdf5d9e670615950bdcbc8f874
branch=codex/review-peer-prompt-contract-metadata
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26d-review-prompt-contract-012856
execution_worktree=/tmp/loop-26d-review-prompt-contract-exec-012856
chat_port=8222
mcp_port=8122
feature_id=loop26d_review_prompt_contract
```

Commands:

```bash
XMUSE_ROOT="$RUN_ROOT" XMUSE_EXECUTION_WORKTREE="$EXEC_ROOT" CHAT_PORT=8222 \
  uv run python -c 'import os; from pathlib import Path; import uvicorn; from xmuse.chat_api import create_app; uvicorn.run(create_app(base_dir=Path(os.environ["XMUSE_ROOT"]), execution_worktree=Path(os.environ["XMUSE_EXECUTION_WORKTREE"])), host="127.0.0.1", port=int(os.environ["CHAT_PORT"]), log_level="info")'

XMUSE_ROOT="$RUN_ROOT" \
  uv run uvicorn xmuse.mcp_server:app --host 127.0.0.1 --port 8122

XMUSE_ROOT="$RUN_ROOT" XMUSE_PEER_GOD_BACKEND=native XMUSE_REVIEW_GOD_BACKEND=native \
  uv run xmuse-platform-runner --xmuse-root "$RUN_ROOT" \
  --lanes "$RUN_ROOT/feature_lanes.json" --mcp-port 8122 \
  --max-concurrent 1 --peer-chat --persistent-review-god \
  --persistent-review-timeout-s 900 --default-review-peer-routing \
  --no-auto-merge --peer-chat-post-writeback-grace-s 4

uv run python /tmp/xmuse-main-after-pr86-155349/.goal-runs/2026-06-19/loop-25z70-post-pr94-health-driver.py \
  --chat-url http://127.0.0.1:8222 \
  --xmuse-root "$RUN_ROOT" \
  --feature-id loop26d_review_prompt_contract \
  --timeout-s 1800 --poll-s 5
```

Durable chain:

```text
conversation_id=conv_373ea1b934a84dffb9da25fac162e73a
collaboration_run=collab_e5a13c307de44da983d1e81cdd5a26eb
proposal_id=prop_4f777d6291864abfa4e019d7f4a4aaaf
resolution_id=res_e099d0b0e01849ad9b9691e148d17bc1
graph_id=res_e099d0b0e01849ad9b9691e148d17bc1-graph-v1
feature_id=loop26d_review_prompt_contract
final_action_hold_id=final-e55c4317b605
```

Final lane authority:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
review_peer_id=part_ac0cb757679447ce822a50649355d1cb
peer_delivery_mode=configured_peer
review_task_id=rtask_80589352f75c43a3b482b377357a617a
review_verdict_id=verdict-merge-rtask_80589352f75c43a3b482b377357a617a
```

Prompt contract evidence from `god_sessions.json`:

```text
architect.prompt_contract_version=xmuse-peer-chat-prompt-v2
execute.prompt_contract_version=xmuse-peer-chat-prompt-v2
review.prompt_contract_version=xmuse-persistent-review-session-prompt-v1
review.prompt_layer_order=persistent_review_session_identity
review.prompt_artifact_fingerprint=sha256:0c930d0c723d2f0f309cacfe1a9867289a8dcd8b780b49d6f1ab9459352b84c2
```

Execution and gate artifacts:

```text
worker_changed_files=docs/xmuse/post-pr94-review-peer-health-note.md
worker_file_content=Review peer runtime metadata is observable through lane health; no separate `review_runtime` field is required.
gate_report=logs/gates/loop26d_review_prompt_contract/report.json
gate_command=uv run pytest -q tests/xmuse/test_package_boundaries.py
gate_result=passed
```

Post-run cleanup:

```text
8122 listener after shutdown: none
8222 listener after shutdown: none
loop-26d service and worker process matches after shutdown: none
```

Classification: positive bounded local runtime proof that configured OpenCode
persistent review now records an explicit review-session prompt contract in
`god_sessions.json` while the fullchain reaches final-action hold.

Caveats:

- This is one bounded docs-only sentinel, not production readiness.
- The persistent review prompt contract is intentionally separate from
  `xmuse-peer-chat-prompt-v2`; it does not claim that review delivery is a
  natural peer-chat turn.
- The lane stopped at final-action hold and was not merged.
- The probe does not prove dynamic member mutation, restart/resume continuity,
  MemoryOS, overnight stability, GitHub review truth, or full closure.

## 2026-06-20 Loop 26e: Post-PR107 Main Runtime Confirmation

Purpose: rerun the same largest safe fullchain from post-merge `origin/main`
after PR #107 landed. This loop confirmed the review-session prompt contract on
main and stopped at final-action hold.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=91ee4f76e9f4ec3bc0627aa690a2dababcde91ad
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26e-post-pr107-main-014701
execution_worktree=/tmp/loop-26e-post-pr107-main-exec-014701
chat_port=8223
mcp_port=8123
feature_id=loop26e_post_pr107_main
```

Durable chain:

```text
conversation_id=conv_d406ce2e042d472bbfbd08ff79c3bec8
collaboration_run=collab_7a498f51eee547fc8be9a75f6ac610a0
proposal_id=prop_bef3017793394b73b50e6a341d7df982
resolution_id=res_72270aa2d1894ac9b82ad8612ef37de6
graph_id=res_72270aa2d1894ac9b82ad8612ef37de6-graph-v1
feature_id=loop26e_post_pr107_main
final_action_hold_id=final-e3644c2efcca
```

Final lane authority:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
review_peer_id=part_f69a2a8024e0458d9e970c596722aaec
peer_delivery_mode=configured_peer
review_task_id=rtask_f151b25e04ab4544bdd002d3bd2de8f0
review_verdict_id=verdict-merge-rtask_f151b25e04ab4544bdd002d3bd2de8f0
```

Prompt contract evidence from `post_run_prompt_contracts.json`:

```text
architect.prompt_contract_version=xmuse-peer-chat-prompt-v2
execute.prompt_contract_version=xmuse-peer-chat-prompt-v2
review.prompt_contract_version=xmuse-persistent-review-session-prompt-v1
review.prompt_layer_order=persistent_review_session_identity
review.prompt_artifact_fingerprint=sha256:962ecb3f1b5a927c1ed908f44d28709ee3b845a1e9933c5bdd6bb1e4d9a25705
```

Execution and gate artifacts:

```text
worker_changed_files=docs/xmuse/post-pr94-review-peer-health-note.md
worker_file_content=Review peer runtime metadata is observable through lane health.
gate_report=logs/gates/loop26e_post_pr107_main/report.json
gate_command=uv run pytest -q tests/xmuse/test_package_boundaries.py
gate_result=passed
```

Post-run cleanup:

```text
8123 listener after shutdown: none
8223 listener after shutdown: none
loop-26e service and worker process matches after shutdown: none
```

Classification: positive bounded post-merge main runtime proof for the
configured OpenCode persistent review prompt-contract metadata path introduced
by PR #107.

Caveats:

- This is one bounded docs-only sentinel, not production readiness.
- The probe does not prove natural peer-GOD groupchat completion, dynamic
  member mutation, restart/resume continuity, MemoryOS, overnight stability,
  GitHub review truth, or full closure.

## 2026-06-20 Loop 26f: Default Review Ambiguity Focused Repro

Purpose: close one review-authority boundary without using proposal text. The
target was default review routing when the conversation already has multiple
active OpenCode `review` participants.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/default-review-ambiguous-fail-closed
base_head_sha=b762fd8770d3a911e60e495237da5f5145f3d660
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26f-default-review-ambiguous-fail-closed-021357
authority=chat.db participants table
summary_artifact=selector_summary.json
```

Focused repro shape:

```text
conversation_id=conv_5d408925f3dc4bdf8391fdd9513ed35d
existing_opencode_review_participants=2
selector_selected_participant_id=null
selector_failure=review_peer_runtime_ambiguous
created_codex_review_participant=false
```

Focused integration validation:

```text
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q -k 'default_review_peer'
-> 11 passed, 39 deselected

uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_persistent_review_session_contracts.py tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_package_boundaries.py -q
-> 90 passed

uv run ruff check .
-> All checks passed.

git diff --check
-> passed

test ! -e xmuse/__init__.py
-> passed
```

Classification: bounded focused runtime/contract proof for ambiguous default
OpenCode review authority. It proves the selector and review-plane consumer no
longer create or use a Codex default review participant when multiple active
OpenCode review participants exist in the same conversation.

Caveats:

- This is not a fullchain run and not production readiness.
- It does not close the missing-OpenCode-reviewer policy question; the legacy
  feature-scoped Codex default peer path remains for the no-OpenCode case.
- It does not prove GitHub review truth, live MemoryOS, dynamic roster mutation,
  overnight stability, or full closure.

## 2026-06-20 Loop 26g: Missing OpenCode Default Review Focused Repro

Purpose: test the remaining missing-reviewer boundary after Loop 26f. The
target was default review routing when a conversation has no active OpenCode
`review` participant.

Pre-fix evidence:

```text
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26g-missing-opencode-default-review-repro-022052
selector_summary=selector/selector_summary.json
consumer_summary=consumer/consumer_summary.json
selector.active_opencode_review_count=0
selector.created_codex_review_participant=true
selector.selector_failure=null
consumer.lane.status=awaiting_final_action
consumer.lane.review_peer_cli_kind=codex
consumer.lane.review_peer_defaulted=true
consumer.lane.review_delivery_mode=persistent
consumer.spawn_await_count=0
```

Closer production-roster repro:

```text
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26g2-missing-opencode-roster-repro-022125
summary_artifact=selector_summary.json
condition=active Codex architect/executor participants, no active OpenCode review participant
selector_selected_participant_id=part_bdc0070c37874d7d89fa7e0557d91228
selector_failure=null
created_codex_review_participant=true
```

Post-fix focused selector evidence:

```text
branch=codex/default-review-missing-opencode-roster-fail-closed
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26g3-missing-opencode-roster-postfix-022227
summary_artifact=selector_summary.json
condition=active Codex architect/executor participants, no active OpenCode review participant
selector_selected_participant_id=null
selector_failure=review_peer_runtime_unavailable
created_codex_review_participant=false
```

Focused integration validation:

```text
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q -k 'default_review_peer'
-> 12 passed, 39 deselected

uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_persistent_review_session_contracts.py tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_package_boundaries.py -q
-> 91 passed
```

Classification: bounded focused runtime/contract proof for the production-like
roster case. When a real peer roster exists but the OpenCode review participant
is missing, default review routing no longer creates a Codex replacement
reviewer.

Caveats:

- This is not a fullchain run and not production readiness.
- Empty or legacy conversations without any active peer roster still retain the
  old feature-scoped Codex default-review fallback.
- It does not prove GitHub review truth, live MemoryOS, dynamic roster mutation,
  overnight stability, or full closure.

## 2026-06-20 Loop 26h: Post-PR110 Positive OpenCode Route Check

Purpose: after PR #109 and PR #110 merged, verify the normal default review
route still selects a unique active OpenCode review participant.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
main_head_sha=1614cc9dca8e28771ea15a8737d88ffb38f73ba0
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26h-post-pr110-opencode-positive-route-022923
selector_summary=selector/selector_summary.json
consumer_summary=consumer/consumer_summary.json
authority=chat.db participants table plus review_god lane state
```

Selector result:

```text
selected_opencode_reviewer=true
selector_selected_participant_id=part_39f834a1e76f4383b788775ab7cef4d5
selector_failure=null
```

Consumer result:

```text
lane_id=lane-positive-opencode-default-review
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
spawn_await_count=0
```

Classification: positive focused post-merge main check for the default
OpenCode review route. It confirms the fail-closed changes did not break the
normal unique-OpenCode-reviewer path.

Caveats:

- This is not a fullchain run and not production readiness.
- The check used a focused orchestrator/review route, not live provider CLI
  execution.
- It does not prove GitHub review truth, live MemoryOS, dynamic roster mutation,
  overnight stability, or full closure.

## 2026-06-20 Loop 26m/26n: Collaboration Delivery Lifecycle Fullchain

Purpose: verify the collaboration request/response/callback delivery lifecycle
after `chat_create_collaboration_request` became a durable message and target
inbox producer.

Pre-fix evidence from Loop 26m:

```text
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26m-collaboration-delivery-fullchain-035148
base_head_sha=a7072f1f43559099592e595c49fbdf8744b49cd5
conversation_id=conv_30f3d962b2fb43b294dddbb1c8086729
collaboration_run=collab_852a8ce9cc6d49d5afde82ca9b9d1821
run_status=done
response_target=@execute
lane_status=awaiting_final_action
review_delivery_mode=persistent
persistent_review_degraded=false
```

Loop 26m also showed two stale delivery records in `chat.db`:

```text
collaboration_request inbox=inbox_161f83ecfe144da6aed10721c3f836a8 status=unread
collaboration_callback inbox=inbox_c35de00000154f3787a360afbae616b8 status=unread
missing_trace=chat_record_collaboration_response on request inbox
missing_trace=chat_emit_proposal on callback inbox
```

Post-fix validation:

```text
uv run pytest tests/xmuse/test_mcp_server.py -q -k 'collaboration_request_enqueues_normalized_target_inbox or collaboration_lane_graph_feature'
-> 2 passed

uv run pytest tests/xmuse/test_mcp_server.py tests/xmuse/test_groupchat_collaboration_runtime.py -q
-> 56 passed

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check .
-> All checks passed.

git diff --check
test ! -e xmuse/__init__.py
-> passed
```

Post-fix real runtime evidence from Loop 26n:

```text
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26n-collaboration-lifecycle-fullchain-040427
base_head_sha=a7072f1f43559099592e595c49fbdf8744b49cd5
conversation_id=conv_bde457d33ee24de88378361eb0b8a155
collaboration_run=collab_0b3189ec5131426ba8960cc5f98fccb3
proposal_id=prop_88d39e33ed9546408bc34d5290e438ae
resolution_id=res_809e579b848c4e1ab19d01f184c35c9c
lane_id=loop_26n_collaboration_lifecycle_fullchain_040427
final_action_hold_id=final-27faea15de67
```

Loop 26n final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Loop 26n collaboration lifecycle state:

```text
collaboration_run.status=done
collaboration_run.targets=["@execute"]
collaboration_response.target=@execute
collaboration_request inbox=inbox_94fe14559853429faa7cc82504cf756d status=read
collaboration_callback inbox=inbox_912b8fd9424543f7ad80dc925b74ec7f status=read responded_message_id=msg_94006e286b36442093fa7b182247b2f2
dispatch inbox=inbox_fafd0209bea5449a8d6215abb6efb260 status=read responded_message_id=msg_974d2bc93bfa4aa48fdb512170033093
trace=inbox_94fe14559853429faa7cc82504cf756d chat_record_collaboration_response
trace=inbox_912b8fd9424543f7ad80dc925b74ec7f chat_emit_proposal
trace=inbox_fafd0209bea5449a8d6215abb6efb260 chat_post_message
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26n service process matches after shutdown: none
```

Classification: bounded local runtime proof that the structured collaboration
request, formal response, callback, proposal, dispatch, isolated execution,
gate, persistent OpenCode review, and final-action hold path can complete
without stale collaboration request/callback inbox items for this docs-only
sentinel shape.

Caveats:

- This is not production readiness, repeated soak, MemoryOS proof, GitHub
  review truth, natural peer-GOD groupchat completion, or full closure.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 27p: Post-PR138 Pending Review Runtime Boundary

Target:

```text
Verify post-merge main fail-closed behavior for collaboration-backed proposal
approval while automatic proposal review is still pending.
```

Runtime command:

```bash
uv run python .goal-runs/2026-06-20/loop-27n-code-change-sentinel-post136-20260620T065337Z/code_change_driver.py \
  --run-root .goal-runs/2026-06-20/loop-27p-post-pr138-pending-review-boundary-20260620T072800Z/runtime \
  --execution-worktree /tmp/loop-27p-post-pr138-pending-review-boundary-20260620T072800Z-exec \
  --feature-id loop_27p_post_pr138_pending_review_boundary_20260620t072800z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Git / server context:

```text
main_merge_commit=0a90caf623ea85311b617d8034b0787eb1611372
pr_138=https://github.com/iiyazu/Cross-Muse/pull/138
pr_138_head=413616e5baa5b5f0496175075a070ae6fedc4bff
pr_138_ci=27864200633 success
main_ci=27864227027 success
```

Durable chain before fail-closed approval:

```text
conversation_id=conv_e12986f5836941b5a38e6301b62f3df1
collaboration_run=collab_7509e6e5a7e24c41ad7db9d725c764fc
collaboration_status=done
proposal_id=prop_2bc98f02d7f445a08a6c5fadf96d3152
proposal_status=open
review_trigger_inbox=inbox_1f50a6d5d8c74cd2ba0c868de6007a0d
review_trigger_status=unread
resolution_count=0
```

Observed approval boundary:

```text
POST /api/chat/proposals/prop_2bc98f02d7f445a08a6c5fadf96d3152/approve
status=400
detail.code=proposal_review_pending
detail.message=inbox_1f50a6d5d8c74cd2ba0c868de6007a0d:unread
```

Runtime artifact paths:

```text
.goal-runs/2026-06-20/loop-27p-post-pr138-pending-review-boundary-20260620T072800Z/runtime/loop_driver_artifacts/failure.json
.goal-runs/2026-06-20/loop-27p-post-pr138-pending-review-boundary-20260620T072800Z/runtime/loop_driver_artifacts/proposal.json
.goal-runs/2026-06-20/loop-27p-post-pr138-pending-review-boundary-20260620T072800Z/runtime/chat.db
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
matched xmuse/ray service processes after shutdown: none observed
```

Classification:

- Post-merge local runtime proof that PR #138 changes the old immediate
  approval driver shape from unsafe dispatch to fail-closed
  `proposal_review_pending`.
- This run intentionally stops before lane projection, isolated execution,
  gate, final review, or final-action hold.
- The next implementation boundary is harness/driver behavior: it must wait for
  proposal review completion and structured blocker/veto outcomes before
  approving dispatchable collaboration-backed proposals.

Forbidden claims preserved:

- no production readiness;
- no GitHub review truth;
- no live MemoryOS;
- no full groupchat-to-completion proof for this loop;
- no full L8-L10 or L1-L11 closure.

## 2026-06-20 Loop 27q: Sentinel Waits For Proposal Review

Target:

```text
Update the reusable fullchain sentinel harness so it waits for automatic
proposal review completion before approving a collaboration-backed lane_graph
proposal.
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root .goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime \
  --execution-worktree /tmp/loop-27q-sentinel-waits-proposal-review-20260620T074200Z-exec \
  --feature-id loop_27q_sentinel_waits_proposal_review_20260620t074200z \
  --proposal-timeout-s 900 \
  --proposal-review-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Git context:

```text
base_head=fdf050ff42042a1e41ffe224941a41dea9774ea0
branch=codex/wait-for-proposal-review-in-sentinel
```

Durable chain:

```text
conversation_id=conv_1e0b6025d3bb483ba738667b86794b40
collaboration_run=collab_d2ff4b25ad8d48feb2d4b0060fb20e99
proposal_id=prop_3f0d6f5a3eff4f0f89dd7aa293b18bfe
review_trigger_inbox=inbox_ffe0e282eafd4bb9a3ab08c05646cd34
review_trigger_status=read
review_trigger_responded_message_id=msg_0cc980effd7d4e1a8663740c6ad46740
resolution_id=res_f1223814dc59499098333f664cde140e
feature_id=loop_27q_sentinel_waits_proposal_review_20260620t074200z
lane_status=awaiting_final_action
gate_passed=true
review_task=rtask_5f80f70b11d1432c9e2997d9e31a4b03
review_verdict=verdict-merge-rtask_5f80f70b11d1432c9e2997d9e31a4b03
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
final_action_hold=final-f332e8015da2 pending
```

Execution artifact:

```text
/tmp/loop-27q-sentinel-waits-proposal-review-20260620T074200Z-exec/docs/xmuse/loop_27q_sentinel_waits_proposal_review_20260620t074200z.md
```

Driver success checks:

```text
single_related_lane_graph_proposal=true
approved_proposal_accepted=true
execution_peer_handoff_not_degraded=true
lane_awaiting_final_action=true
gate_passed=true
isolated_note_matches=true
opencode_review_peer_recorded=true
review_verdict_finalized=true
review_task_verdict_emitted=true
final_action_hold_pending=true
proposal_has_no_review_runtime=true
```

Runtime artifact paths:

```text
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/loop_driver_artifacts/proposal_review_trigger.json
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/loop_driver_artifacts/approval_response.json
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/loop_driver_artifacts/success_checks.json
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/review_plane.json
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/final_actions.json
.goal-runs/2026-06-20/loop-27q-sentinel-waits-proposal-review-20260620T074200Z/runtime/chat.db
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
```

Branch validation:

```bash
uv run pytest tests/xmuse/test_fullchain_docs_sentinel.py -q
uv run pytest tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_peer_chat_review_trigger.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_package_boundaries.py -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```

Results:

```text
3 passed
59 passed, 1 warning
ruff: All checks passed
git diff --check: passed
xmuse/__init__.py absent
```

Classification:

- Candidate-branch local runtime proof that the reusable sentinel harness can
  wait for automatic proposal review completion before approving a dispatchable
  collaboration-backed proposal.
- The loop moved beyond Loop 27p's expected fail-closed
  `proposal_review_pending` boundary, approved only after the trigger was read,
  and reached isolated execution, gate, persistent OpenCode review, and
  final-action hold.
- This is harness/runtime-loop evidence, not production readiness, GitHub
  review truth, live MemoryOS proof, repeated soak, or full closure.

## 2026-06-20 Loop 27r: Post-PR140 Main Sentinel Rerun

Target:

```text
Verify the merged reusable fullchain sentinel harness on post-PR140 main.
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root .goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime \
  --execution-worktree /tmp/loop-27r-post-pr140-main-sentinel-20260620T080409Z-exec \
  --feature-id loop_27r_post_pr140_main_sentinel_20260620T080409Z \
  --proposal-timeout-s 900 \
  --proposal-review-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Git / server context:

```text
pr_140=https://github.com/iiyazu/Cross-Muse/pull/140
pr_140_head=1e33f0273d08f83aa5a007b1af61883a4818e189
pr_140_merge_commit=419f00d4cd4c8227a33302658608f9d9532f07b6
pr_140_ci=27865014142 success
main_ci=27865045744 success
```

Durable chain:

```text
conversation_id=conv_758e55557d55489792da6b314c0ed12d
collaboration_run=collab_32e88f4991b4424a99618853b6e928fa
proposal_id=prop_e0e1eab878b4465c8eb5945c60894f5d
review_trigger_inbox=inbox_9487fcb303564ded8f5fd395f53ba6a8
review_trigger_status=read
review_trigger_responded_message_id=msg_b5412cab19c2455dbd1655df7ae408bc
resolution_id=res_bd24e8deb99444589850c5f611b94315
feature_id=loop_27r_post_pr140_main_sentinel_20260620T080409Z
lane_status=awaiting_final_action
gate_passed=true
review_task=rtask_6d7f18ac90b8473c9a827b4fa15eee2e
review_verdict=verdict-merge-rtask_6d7f18ac90b8473c9a827b4fa15eee2e
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
final_action_hold=final-45abee1aa897 pending
```

Execution artifact:

```text
/tmp/loop-27r-post-pr140-main-sentinel-20260620T080409Z-exec/docs/xmuse/loop_27r_post_pr140_main_sentinel_20260620T080409Z.md
```

Driver success checks:

```text
single_related_lane_graph_proposal=true
approved_proposal_accepted=true
execution_peer_handoff_not_degraded=true
lane_awaiting_final_action=true
gate_passed=true
isolated_note_matches=true
opencode_review_peer_recorded=true
review_verdict_finalized=true
review_task_verdict_emitted=true
final_action_hold_pending=true
proposal_has_no_review_runtime=true
```

Runtime artifact paths:

```text
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/loop_driver_artifacts/proposal_review_trigger.json
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/loop_driver_artifacts/approval_response.json
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/loop_driver_artifacts/success_checks.json
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/review_plane.json
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/final_actions.json
.goal-runs/2026-06-20/loop-27r-post-pr140-main-sentinel-20260620T080409Z/runtime/chat.db
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
service process pid files no longer resolve to live processes
```

Classification:

- Post-merge main local runtime proof that the PR #140 sentinel harness waits
  for automatic proposal review, approves only after the trigger is read, and
  then reaches isolated execution, gate, persistent OpenCode review, and
  final-action hold for this docs-only sentinel shape.
- This is not production readiness, repeated soak, GitHub review truth, live
  MemoryOS proof, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-20 Loop 28a: Native OpenCode Provider Session Binding

Purpose: close the Phase 2 provider-native session continuity gap exposed by
Loop 27g, where xmuse restored the same GOD session across restart but
`provider_session_id` remained null.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-goal-main-20260620
branch=codex/native-opencode-provider-session-binding
base_head_sha=4919e9807d074069190d71127c6fbf10408f7d19
run_root=.goal-runs/2026-06-20/loop-28a-native-opencode-session-binding-20260620T082733Z
registry=.goal-runs/2026-06-20/loop-28a-native-opencode-session-binding-20260620T082733Z/runtime/god_sessions.json
proof_artifact=.goal-runs/2026-06-20/loop-28a-native-opencode-session-binding-20260620T082733Z/runtime-proof.json
```

Runtime command shape:

```bash
uv run python - <<'PY'
# focused runtime probe:
# 1. spawn native GodSessionLayer with OpenCodeLauncher;
# 2. send one real OpenCode turn;
# 3. persist returned opencode_session_id into god_sessions.json;
# 4. abort the local shim;
# 5. create a fresh GodSessionLayer from the same registry;
# 6. send a second real OpenCode turn through --session-id.
PY
```

Durable/provider evidence:

```text
god_session_id=god-4a912088e72e4e79addda3e00d8b2367
provider_session_id=ses_11bda827fffekK9seMPaDldLtf
same_god_session_after_restart=true
provider_binding_active=true
provider_binding_resumed_in_registry=true
second_turn_reused_provider_session=true
second_stdout_contains_session_id=true
```

Classification: candidate-branch focused runtime proof that the native
OpenCode persistent peer can persist a real provider `sessionID` into
`god_sessions.json` and pass it back to the OpenCode shim on restart.

Caveats:

- This is not post-merge main proof until the branch lands and is rerun from
  main.
- This is not fullchain groupchat-to-lane proof; it exercises the provider
  session continuity boundary directly.
- This does not prove live MemoryOS, production readiness, repeated soak,
  GitHub review truth, full L8-L10 closure, or full L1-L11 closure.

## 2026-06-20 Loop 27o: Pending Proposal Review Approval Guard Candidate

Target:

```text
Phase 3 pre-dispatch proposal review/veto semantics.
```

Authority / producer / consumer:

```text
authority=chat.db proposal message + review_trigger inbox item + collaboration dispatch gate
producer=PeerChatService lane_graph proposal emission with collaboration reference
consumer=Chat API proposal approval path
condition=collaboration-backed dispatchable lane_graph approval must fail closed while its automatic proposal review trigger is unread/claimed
proof_level=contract_proof + focused regression after Loop 27n runtime caveat
```

Root-cause hypothesis:

```text
Loop 27n approval raced ahead of the automatic OpenCode proposal review because
the approval path treated a pending review_trigger as clearable bookkeeping
instead of a pre-dispatch review obligation for collaboration-backed lane_graph
work. The review prompt also did not state that a "do not dispatch" review must
use chat_raise_collaboration_blocker to create dispatch-blocking authority.
```

Candidate changes:

```text
xmuse/chat_api.py:
  - reject collaboration-backed lane_graph approval with proposal_review_pending
    when the related review_trigger is unread or claimed.
  - keep ordinary non-collaboration manual approval behavior unchanged.

src/xmuse_core/chat/peer_service.py:
  - add review-trigger instructions that blocking/no-dispatch recommendations
    must call chat_raise_collaboration_blocker with severity="veto" and
    blocks_dispatch=true.
  - explicitly state that a plain chat_post_message recommendation cannot block
    dispatch.
```

Focused validation:

```bash
uv run pytest tests/xmuse/test_chat_review_trigger.py::test_collaboration_proposal_approval_blocks_pending_review_trigger -q
uv run pytest tests/xmuse/test_peer_chat_review_trigger.py::test_lane_graph_review_trigger_includes_readable_proposal_content -q
uv run pytest tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_peer_chat_review_trigger.py -q
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_references_collaboration_gate_and_blocks_active_veto \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_blocked_collaboration_gate_leaves_no_approval_side_effects \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_requires_execute_collaboration_confirmation \
  tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_freeform_execute_confirmation -q
uv run pytest tests/xmuse/test_groupchat_collaboration_runtime.py -q
uv run pytest tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_peer_chat_api.py tests/xmuse/test_tui_adapter.py -q
uv run ruff check xmuse/chat_api.py src/xmuse_core/chat/peer_service.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_peer_chat_review_trigger.py
```

Results:

```text
1 passed, 1 warning
1 passed
8 passed, 1 warning
4 passed, 1 warning
35 passed, 1 warning
66 passed, 1 warning
ruff: All checks passed
```

Classification:

- Candidate contract repair for the Loop 27n pre-dispatch review race.
- This is not post-merge runtime proof and not a fullchain rerun.
- Expected next runtime behavior: the old immediate-approval driver shape
  should fail closed with `proposal_review_pending` until the proposal review
  trigger is handled. The next loop should update the driver/harness to wait for
  proposal review and structured veto/blocker outcomes instead of bypassing
  them.

Forbidden claims preserved:

- no production readiness;
- no GitHub review truth;
- no live MemoryOS;
- no natural peer-GOD groupchat completion;
- no full L8-L10 or L1-L11 closure.

## 2026-06-20 Loop 27k/27l: First Non-Docs Code-Change Sentinel

Purpose: move beyond docs-only sentinel proof by having natural groupchat drive
a small xmuse code change through proposal, isolated execution, gate, OpenCode
review, and final-action hold.

### Loop 27k: baseline gate blocker

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-goal-main-20260620
base_head_sha=ca17c4a91ad7594b069a2b265c9d0d63acbf8a2a
run_root=/tmp/xmuse-goal-main-20260620/.goal-runs/2026-06-20/loop-27k-code-change-sentinel-commands-20260620T054915Z/runtime
execution_worktree=/tmp/loop-27k-code-change-sentinel-commands-20260620T054915Z-exec
conversation_id=conv_f98eb31ee9d448f9a9f47ff9f5c4d526
```

Runtime command:

```bash
uv run python .goal-runs/2026-06-20/loop-27k-code-change-sentinel-commands-20260620T054915Z/code_change_driver.py \
  --run-root .goal-runs/2026-06-20/loop-27k-code-change-sentinel-commands-20260620T054915Z/runtime \
  --execution-worktree /tmp/loop-27k-code-change-sentinel-commands-20260620T054915Z-exec \
  --feature-id loop_27k_code_change_sentinel_commands_20260620t054915z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Durable chain:

```text
collaboration_run=collab_d6bac849094a42f987e4b2563fecedee
proposal_id=prop_5ef31b378e354f8caaf7e5399cf68c85
resolution_id=res_7c01b40ba0554a7e88ce6b9aef6b835f
lane_id=loop_27k_code_change_sentinel_commands_20260620t054915z
```

Outcome:

```text
status=gate_failed
gate_passed=false
changed_files=scripts/run_fullchain_docs_sentinel.py, tests/xmuse/test_fullchain_docs_sentinel.py
candidate_diff_scoped=true
```

Gate authority:

```text
gate_report=.goal-runs/2026-06-20/loop-27k-code-change-sentinel-commands-20260620T054915Z/runtime/logs/gates/loop_27k_code_change_sentinel_commands_20260620t054915z/report.json
failing_node=tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate
root_cause=test registered review target but omitted execute target while asking collaboration_request for ["review", "execute"]
```

Repair:

```text
pr=134
title=test: align collaboration target setup
head_sha=e4a36b70f5668c9e6bd872e4e1fbc1750d045424
merge_commit=893e911cce242a6ff8a08b060855ed9d63c3a8f1
pr_ci_run=27862441719 success
main_ci_run=27862466582 success
remote_branch_deleted=true
```

### Loop 27l: post-PR134 successful code-change chain

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-loop27l-main-893e911-runtime
base_head_sha=893e911cce242a6ff8a08b060855ed9d63c3a8f1
run_root=/tmp/xmuse-loop27l-main-893e911-runtime/.goal-runs/2026-06-20/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z/runtime
execution_worktree=/tmp/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z-exec
conversation_id=conv_6440e9fc2a7b4ca0aa46d06b0bdd4c8b
```

Runtime command:

```bash
uv run python .goal-runs/2026-06-20/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z/code_change_driver.py \
  --run-root .goal-runs/2026-06-20/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z/runtime \
  --execution-worktree /tmp/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z-exec \
  --feature-id loop_27l_code_change_sentinel_commands_post134_20260620t061200z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Durable chain:

```text
collaboration_run=collab_2d33039bacfc499c848f72fd4c3fc0d1
proposal_id=prop_e0c5c21371ba4ea5a699212c1ba23dc2
resolution_id=res_8c8a08462ccd492686184b64ceba63b5
lane_id=loop_27l_code_change_sentinel_commands_post134_20260620t061200z
review_task_id=rtask_dacd3cd9e6cf411f8f0c374435e620b3
review_verdict_id=verdict-merge-rtask_dacd3cd9e6cf411f8f0c374435e620b3
final_action_hold_id=final-e8aea6a8d2ff
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
```

Execution candidate:

```text
changed_files=scripts/run_fullchain_docs_sentinel.py, tests/xmuse/test_fullchain_docs_sentinel.py
command_artifacts_add_expected_note_content=true
driver_success_checks_all_true=true
```

Success checks:

```text
approved_proposal_accepted=true
changed_files_scoped=true
execution_peer_handoff_not_degraded=true
final_action_hold_pending=true
gate_passed=true
lane_awaiting_final_action=true
opencode_review_peer_recorded=true
proposal_has_no_review_runtime=true
review_task_verdict_emitted=true
review_verdict_finalized=true
script_records_expected_note_content=true
test_records_expected_note_content=true
worktree_exists=true
```

Classification: bounded local runtime proof for one small non-docs xmuse
code-change lane. It proves this lane shape only. It is not production
readiness, repeated soak, provider-native session resume, live MemoryOS,
GitHub review truth, natural peer-GOD groupchat completion, or full closure.

## 2026-06-20 Loop 27m: Preserve Peer Latency Retry Attempts

Purpose: close the observability gap exposed by Loop 27l where the architect
collaboration callback first timed out and later succeeded on scheduler retry,
but the final `peer_turn_latency_traces` table retained only the successful
retry for that inbox item.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-goal-main-20260620
branch=codex/preserve-peer-latency-retry-attempts
base_head_sha=eed99b0258dcc862719c38d571055b6fd85b3b33
observed_runtime_db=/tmp/xmuse-loop27l-main-893e911-runtime/.goal-runs/2026-06-20/loop-27l-code-change-sentinel-commands-post134-20260620T061200Z/runtime/chat.db
```

Boundary:

```text
target=peer latency retry-attempt observability
authority=peer_turn_latency_traces rows in chat.db
producer=PeerChatScheduler._record_latency_trace
consumer=peer progress/read surfaces and operator runtime audit
failure_boundary=delivery lifecycle observability
```

Observed Loop 27l durable state:

```text
callback_inbox=inbox_3998e10ac68740cb91c063f619d7f6b4
final_status=read
nudge_count=1
responded_message_id=msg_568c1d81b1d946dba66b9abd1fa3bbcf
final_latency_row_id=peer_latency_inbox_3998e10ac68740cb91c063f619d7f6b4
final_delivery_mode=mcp_writeback
final_degraded_reason=peer_writeback_before_provider_result
```

Root cause:

```text
PeerTurnLatencyTraceStore.record used id=peer_latency_<inbox_item_id> and
upserted on that primary key. A retry for the same inbox item overwrote the
earlier failed attempt instead of preserving both attempts.
```

Focused reproduction:

```bash
uv run pytest tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_preserves_latency_trace_for_retry_attempt -q
```

Result before repair:

```text
failed: list_recent returned only ['mcp_writeback'] instead of preserving
['mcp_writeback', 'failed'] for the same inbox retry sequence.
```

Repair:

```text
PeerTurnLatencyTraceStore.record is append-only per scheduler attempt.
The first trace keeps id peer_latency_<inbox_item_id> for compatibility.
Retries use peer_latency_<inbox_item_id>_attempt_N.
```

Focused validation:

```bash
uv run pytest tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_preserves_latency_trace_for_retry_attempt -q
uv run pytest tests/xmuse/test_peer_chat_scheduler.py -q
uv run pytest tests/xmuse/test_peer_chat_api.py tests/xmuse/test_tui_adapter.py -q
uv run ruff check src/xmuse_core/chat/stream_store.py tests/xmuse/test_peer_chat_scheduler.py
```

Result:

```text
new focused test: 1 passed
peer scheduler tests: 21 passed
peer progress/TUI focused tests: 45 passed, 1 warning
ruff touched files: All checks passed
```

Classification: targeted observability repair for retry-attempt evidence. This
does not prove the callback will no longer need retry; it makes future retry
dependence durable and auditable instead of overwritten by a later success.

## 2026-06-20 Loop 27n: Post-PR136 Code-Change Chain Rerun

Purpose: rerun the largest reachable code-change sentinel shape from latest
main after PR #136 to observe whether the Loop 27l collaboration callback retry
reproduces and whether the execution/review/final-action path still reaches
the safe hold boundary.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-goal-main-20260620
base_head_sha=cad8b7b40c916f756432591f86dee38da416fafa
run_root=/tmp/xmuse-goal-main-20260620/.goal-runs/2026-06-20/loop-27n-code-change-sentinel-post136-20260620T065337Z/runtime
execution_worktree=/tmp/loop-27n-code-change-sentinel-post136-20260620T065337Z-exec
conversation_id=conv_7ef31239eb4d4e2693a64c96c2c426b4
```

Runtime command:

```bash
uv run python .goal-runs/2026-06-20/loop-27n-code-change-sentinel-post136-20260620T065337Z/code_change_driver.py \
  --run-root .goal-runs/2026-06-20/loop-27n-code-change-sentinel-post136-20260620T065337Z/runtime \
  --execution-worktree /tmp/loop-27n-code-change-sentinel-post136-20260620T065337Z-exec \
  --feature-id loop_27n_code_change_sentinel_post136_20260620t065337z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.75
```

Durable chain:

```text
collaboration_run=collab_d68e4c215e80431487ae33d8407db163
proposal_id=prop_c45500ea19164801aff4fa31fb202f86
resolution_id=res_4387ec6d53284833aa68a5744cc9eb2c
lane_id=loop_27n_code_change_sentinel_post136_20260620t065337z
review_task_id=rtask_a24953dc176b46cbad36ae4fe3eebcbf
review_verdict_id=verdict-loop_27n_code_change_sentinel_post136_20260620t065337z
final_action_hold_id=final-55b46d51c6b5
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
review_peer_defaulted=true
```

Callback and latency observations:

```text
architect_mention_inbox=inbox_3677d7b37c47469dbaac1b0221d4c722 nudge_count=0 delivery_mode=mcp_writeback
execute_collaboration_inbox=inbox_0422d682380f46da89a2911c2f0c9e53 nudge_count=0 delivery_mode=mcp_writeback
architect_callback_inbox=inbox_fd69b2a178784db0ad69841af03b48dd nudge_count=0 delivery_mode=mcp_writeback stages=chat_read_inbox,chat_emit_proposal
review_trigger_inbox=inbox_ca1b845c3f074254924c11611ad7a364 nudge_count=0 delivery_mode=mcp_writeback
dispatch_inbox=inbox_59d28d8f31cb468f8181d42860b01079 nudge_count=0 delivery_mode=mcp_writeback
```

Success checks:

```text
approved_proposal_accepted=true
changed_files_scoped=true
execution_peer_handoff_not_degraded=true
final_action_hold_pending=true
gate_passed=true
lane_awaiting_final_action=true
opencode_review_peer_recorded=true
proposal_has_no_review_runtime=true
review_task_verdict_emitted=true
review_verdict_finalized=true
script_records_expected_note_content=true
test_records_expected_note_content=true
worktree_exists=true
```

Execution candidate:

```text
changed_files=tests/xmuse/test_fullchain_docs_sentinel.py
script_already_had_expected_note_content=true
test_records_expected_note_content=true
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
```

Classification: bounded post-PR136 local runtime proof that the same
groupchat-to-final-hold shape still reaches final-action hold and that the
Loop 27l callback retry did not reproduce in this run. This is not a new
production feature delivery because the main script already contained the
requested behavior and the candidate only broadened focused test coverage.

Caveat:

- The proposal review path observed the lane as effectively no-op and
  recommended against dispatch, but it did not create an active veto before the
  driver approval. The final review still accepted the candidate and recorded
  an ignored review conflict after acceptance. Treat pre-dispatch no-op review
  and veto semantics as the next evidence boundary.

## 2026-06-20 Loop 27a: Peer Progress Read Projection Candidate

Target:

```text
Phase 2 durable progress events visible through Chat API / read model.
```

Authority / producer / consumer:

```text
authority=chat_inbox_items + peer_turn_latency_traces
producer=PeerChatScheduler durable inbox/latency writers
consumer=PeerChatService conversation timeline / Chat API messages endpoint
proof_level=local_runtime_artifact_projection + focused contract guard
```

Pre-fix artifact inspection:

```bash
uv run python - <<'PY'
from pathlib import Path
from xmuse_core.chat.peer_service import PeerChatService
root = Path('.goal-runs/2026-06-20/loop-26x-post-pr124-fullchain-rerun-1117cst')
conv = 'conv_a086f7a07892470696e76787581f1508'
payload = PeerChatService(root / 'chat.db').list_conversation_timeline(conv)
print('has_peer_progress_events', 'peer_progress_events' in payload)
print('has_latency_traces', 'peer_turn_latency_traces' in payload or 'latency_traces' in payload)
PY
```

Observed:

```text
has_peer_progress_events=False
has_latency_traces=False
```

Durable trace inspection of the same Loop 26x `chat.db` showed:

```text
chat_streams=0
peer_turn_latency_traces=2
trace_modes:
- failed / peer_no_inbox_writeback_message: 1
- mcp_writeback / None: 1
```

Focused RED:

```bash
uv run pytest tests/xmuse/test_peer_chat_api.py::test_chat_timeline_projects_peer_progress_from_durable_inbox_and_trace -q
```

Observed before implementation:

```text
FAILED KeyError: 'peer_progress_events'
```

Candidate branch:

```text
branch=codex/groupchat-progress-event-contract
base=origin/main@c2f9bf57e3b0de235949439ada0f3395b87a4f76
```

Candidate behavior:

- `PeerChatService.list_conversation_timeline()` now exposes
  `peer_progress_events`, `peer_progress_counts`, and
  `recent_peer_progress_events`.
- The projection consumes existing durable inbox rows and
  `peer_turn_latency_traces` through read-only SQLite queries.
- The projection does not make stdout, worker output, or UI state into truth.

Post-fix artifact projection check:

```bash
uv run python - <<'PY'
from pathlib import Path
from xmuse_core.chat.peer_service import PeerChatService
root = Path('.goal-runs/2026-06-20/loop-26x-post-pr124-fullchain-rerun-1117cst')
conv = 'conv_a086f7a07892470696e76787581f1508'
payload = PeerChatService(root / 'chat.db').list_conversation_timeline(conv)
print('peer_progress_counts', payload.get('peer_progress_counts'))
print('trace_authority_events', sum(1 for e in payload.get('peer_progress_events', []) if e.get('source_authority') == 'peer_turn_latency_traces'))
print('statuses', [e.get('status') for e in payload.get('peer_progress_events', [])])
PY
```

Observed:

```text
peer_progress_counts {'failed': 1, 'done': 4, 'total': 5}
trace_authority_events 2
statuses ['failed', 'done', 'done', 'done', 'done']
```

Validation:

```text
uv run pytest tests/xmuse/test_peer_chat_api.py -q
-> 13 passed

uv run pytest tests/xmuse/test_peer_chat_end_to_end.py -q
-> 3 passed

uv run pytest tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_peer_chat_runtime_timeline_projects_inspector_state tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_links_dashboard_runtime_timeline -q
-> 2 passed

uv run pytest tests/xmuse/test_package_boundaries.py -q
-> 16 passed

uv run ruff check .
-> All checks passed.

git diff --check
-> passed

test ! -e xmuse/__init__.py
-> passed
```

Caveats:

- This is a local candidate branch until PR and CI/server facts exist.
- This is a read contract for peer progress visibility, not production
  readiness, natural peer-GOD groupchat completion, live MemoryOS, GitHub
  review truth, live lane merge truth, or full closure.

## 2026-06-20 Loop 27b: Dynamic Member Roster Event Candidate

Purpose: close the Phase 2 read/write gap where dynamically adding a groupchat
member updated `participants` but left no durable roster event for Chat API
consumers.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/groupchat-dynamic-member-events
base_head_sha=aa7cd90e1e9b8d8b7ce208bf2bf1f4d5968dee0b
authority=participants + messages(envelope_type=roster_event)
producer=POST /api/chat/conversations/{conversation_id}/participants
consumer=PeerChatService.list_conversation_timeline / GET /messages
proof_level=local_runtime_proof candidate
```

Pre-fix probe:

```bash
uv run python - <<'PY'
# FastAPI TestClient creates a conversation in a temporary XMUSE_ROOT,
# POSTs a new OpenCode review participant, then inspects chat.db and the
# /messages timeline.
PY
```

Observed before repair:

```text
add_status=201
participants included the new opencode review peer
messages=[]
timeline_message_count=0
timeline_item_kinds=[]
roster_event_fields={}
```

Candidate repair:

```text
src/xmuse_core/chat/roster_events.py
xmuse/chat_api.py
src/xmuse_core/chat/peer_service.py
tests/xmuse/test_peer_chat_api.py
```

Post-fix probe:

```text
add_status=201
timeline_message_count=0
messages[0].envelope_type=roster_event
messages[0].author=xmuse-system
roster_event_counts={'total': 1, 'participant_added': 1}
recent_roster_events[0].source_authority=participants
recent_roster_events[0].action=participant_added
recent_roster_events[0].cli_kind=opencode
recent_roster_events[0].model=opencode-go/deepseek-v4-flash
```

Focused validation so far:

```bash
uv run pytest tests/xmuse/test_peer_chat_api.py -q
uv run ruff check src/xmuse_core/chat/roster_events.py src/xmuse_core/chat/peer_service.py xmuse/chat_api.py tests/xmuse/test_peer_chat_api.py
```

Classification: local candidate proof that the dynamic member add path now
produces a durable roster event and the Chat API timeline exposes it. This is
not production readiness, natural peer-GOD groupchat completion, MemoryOS
proof, GitHub review truth, or full closure.

## 2026-06-20 Loop 27c: Dynamic Member Session Binding Candidate

Purpose: close the Phase 2 gap where dynamically adding a groupchat member
created a participant and roster event but no durable GOD session binding.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/dynamic-member-session-binding
base_head_sha=88602453fed774e1ceb2f3492b28879016c241db
authority=participants + god_sessions.json
producer=POST /api/chat/conversations/{conversation_id}/participants
consumer=GET /api/chat/conversations/{conversation_id}/participants after app restart
proof_level=local_runtime_proof candidate
```

Pre-fix probe from post-PR127 main:

```text
add_status=201
add_session=None
registry_session_count_for_dynamic=0
listed_dynamic[0].session=None
```

Candidate repair:

```text
src/xmuse_core/chat/peer_service.py
xmuse/chat_api.py
tests/xmuse/test_peer_chat_api.py
```

Post-fix probe:

```text
add_status=201
add_session.god_session_id=god-...
add_session.runtime=opencode
add_session.provider_id=opencode
add_session.profile_id=review
registry_session_count_for_dynamic=1
restarted GET /participants returns same god_session_id
```

Focused validation so far:

```bash
uv run pytest tests/xmuse/test_peer_chat_api.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_package_boundaries.py -q
uv run ruff check src/xmuse_core/chat/peer_service.py xmuse/chat_api.py tests/xmuse/test_peer_chat_api.py
git diff --check
test ! -e xmuse/__init__.py
```

Classification: local candidate proof that dynamic member add now creates a
durable session binding and the restarted participant read model restores it.
This is not provider-native resume proof, natural peer-GOD completion,
production readiness, live MemoryOS, GitHub review truth, or full closure.

## 2026-06-20 Loop 27d: Dynamic Member Context Capsule Probe

Purpose: verify whether a newly added dynamic member consumes the local context
capsule and layered prompt when the scheduler delivers a turn.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/groupchat-context-capsule-proof
base_head_sha=28cd878aa94c16e2b49d09cf806896e97322c88a
authority=chat.db messages/inbox + participants + scheduler provider context
producer=Chat API conversation/messages/participants + PeerChatScheduler
consumer=god_layer.send_message prompt/context payload
proof_level=local_runtime_probe
```

Probe shape:

```text
1. create conversation through Chat API
2. post human context message
3. dynamically add OpenCode review participant
4. mention that participant by @participant:<id>
5. run PeerChatScheduler for that inbox item with a capture GOD layer
6. inspect the prompt/context passed to send_message
```

Observed:

```text
outcome=PeerChatSchedulerOutcome(nudged=0, happy_path=0, failed=1, fallback_replies=0)
ensured_runtime=opencode
ensured_model=opencode-go/deepseek-v4-flash
context_participant_id=<dynamic participant id>
context_capsule_version=xmuse-local-context-capsule-v1
recent_message_count=3
recent_contents included:
- Initial demand: keep dynamic member informed.
- dynamic-context-review-god joined the groupchat as review via opencode.
- @participant:<id> review the latest demand with context.
roster_roles included init/architect/review/execute/dynamic review
prompt_has_dynamic_member=True
prompt_has_initial_demand=True
prompt_layer_order=[
  xmuse_governance_l0,
  member_identity,
  roster_and_capabilities,
  local_context_capsule,
  tool_and_writeback_contract
]
prompt_contract_version=xmuse-peer-chat-prompt-v2
```

Classification: no code patch needed for this boundary. The scheduler already
passes the dynamic member a bounded local context capsule and inspectable
layered prompt. The failed outcome is expected because the capture GOD layer did
not perform MCP/callback writeback; this probe targets prompt/context delivery,
not reply truth.

Caveats:

- This is local runtime probe evidence only.
- It does not prove provider-native live resume, MCP writeback success for this
  specific dynamic member, repeated multi-turn reliability, production
  readiness, live MemoryOS, GitHub review truth, or full closure.

## 2026-06-20 Loop 27f: Dynamic OpenCode Member Live Writeback

Purpose: prove the next Phase 2 boundary after dynamic roster/session/context
work: a dynamically added OpenCode review member can receive a real peer-chat
turn and write back through the production MCP callback path.

Superseded probe:

```text
loop=loop-27e-dynamic-opencode-writeback-20260620T042910Z
classification=probe_driver_exception
reason=probe SQL selected missing participants.active column
product_chain_started=false
```

Runtime command shape:

```bash
uv run python - <<'PY'
# bounded probe driver starting Chat API, MCP, platform_runner --peer-chat,
# creating a conversation with Codex architect/executor, dynamically adding
# an OpenCode review participant, posting @participant:<id>, then polling
# chat.db for inbox/message/MCP/latency artifacts.
PY
```

Authority and artifacts:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head=7d576bedaca182fd7784cd2914356074731a2bfb
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-27f-dynamic-opencode-latency-trace-20260620T043247Z
summary=.goal-runs/2026-06-20/loop-27f-dynamic-opencode-latency-trace-20260620T043247Z/loop_driver_artifacts/summary.json
final_snapshot=.goal-runs/2026-06-20/loop-27f-dynamic-opencode-latency-trace-20260620T043247Z/loop_driver_artifacts/final_snapshot.json
timeline=.goal-runs/2026-06-20/loop-27f-dynamic-opencode-latency-trace-20260620T043247Z/loop_driver_artifacts/timeline.json
```

Durable ids:

```text
conversation_id=conv_c73d15c965dd48f9b6f70bc584684169
dynamic_participant_id=part_1a69ceae3198458eb7ae0fe71ef36d73
god_session_id=god-bfb4d4bb311145b284f6ad24c0776baa
inbox_item_id=inbox_a45aa387b3654e929cc5cb8034633b75
assistant_message_id=msg_d7eaaa7961fb4ac0bd345e020838e746
```

Observed durable state:

```text
participant.cli_kind=opencode
participant.model=opencode-go/deepseek-v4-flash
god_session.prompt_contract_version=xmuse-peer-chat-prompt-v2
god_session.prompt_layer_order=[
  xmuse_governance_l0,
  member_identity,
  roster_and_capabilities,
  local_context_capsule,
  tool_and_writeback_contract
]
inbox.status=read
inbox.claim_owner=platform-runner
inbox.responded_message_id=msg_d7eaaa7961fb4ac0bd345e020838e746
assistant_message.author=part_1a69ceae3198458eb7ae0fe71ef36d73
mcp_tool_trace=chat_post_message
latency.delivery_mode=mcp_writeback
latency.degraded_reason=peer_writeback_before_provider_result
timeline.peer_progress_events[0].source_authority=peer_turn_latency_traces
timeline.peer_progress_events[0].status=degraded
roster_event_counts.participant_added=1
```

Cleanup:

```text
chat_port_listening_after_cleanup=false
mcp_port_listening_after_cleanup=false
```

Classification: bounded local runtime proof that a dynamically added OpenCode
review participant can receive a real peer-chat turn through the platform
runner and produce a durable assistant reply through `chat_post_message`.

Caveats:

- This proves one dynamic OpenCode member writeback turn, not provider-native
  session resume across process restart.
- The progress read model classified the turn as degraded because writeback was
  observed before the provider result was consumed; the durable message and MCP
  writeback are still present.
- This is not multi-turn natural groupchat, groupchat proposal production,
  production readiness, live MemoryOS, GitHub review truth, or full closure.

## 2026-06-20 Loop 27g: Dynamic OpenCode Restart Continuity

Purpose: extend Loop 27f from one dynamic OpenCode writeback turn to two turns
with a full Chat API, MCP, and platform runner restart between turns.

Runtime command shape:

```bash
uv run python - <<'PY'
# bounded probe driver:
# 1. start Chat API, MCP, platform_runner --peer-chat
# 2. create Codex architect/executor conversation
# 3. dynamically add OpenCode review participant
# 4. run turn 1 to latency trace
# 5. stop all services
# 6. restart Chat API, MCP, platform_runner with the same XMUSE_ROOT
# 7. verify participant read model restores the same god_session_id
# 8. run turn 2 to latency trace
PY
```

Authority and artifacts:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head=27ceac95e70240e7d6252c546581729970320e30
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-27g-dynamic-opencode-restart-continuity-20260620T044530Z
summary=.goal-runs/2026-06-20/loop-27g-dynamic-opencode-restart-continuity-20260620T044530Z/loop_driver_artifacts/summary.json
final_snapshot=.goal-runs/2026-06-20/loop-27g-dynamic-opencode-restart-continuity-20260620T044530Z/loop_driver_artifacts/final_snapshot.json
participants_after_restart=.goal-runs/2026-06-20/loop-27g-dynamic-opencode-restart-continuity-20260620T044530Z/loop_driver_artifacts/participants_after_restart.json
```

Durable ids:

```text
conversation_id=conv_5665b62e7fc7434987a346544310f6da
dynamic_participant_id=part_c4f601e5ed1a496391d0143fec3a4ff0
first_god_session_id=god-b63bd610c13c4240bceaa4f0f46597b7
restored_god_session_id=god-b63bd610c13c4240bceaa4f0f46597b7
turn1_inbox_item_id=inbox_537d9822bbf94501b3dfd1703016af6d
turn2_inbox_item_id=inbox_ec9562b505564e7e8ff4d04c83004e12
```

Observed durable state:

```text
same_god_session_after_restart=true
turn1_terminal_reason=turn1_latency_trace_after_inbox_read
turn2_terminal_reason=turn2_latency_trace_after_inbox_read
dynamic_assistant_messages=2
dynamic_inbox_items=2
dynamic_mcp_traces=3
dynamic_latency_traces=2
turn1.delivery_mode=mcp_writeback
turn2.delivery_mode=mcp_writeback
provider_session_ids=[null]
```

Cleanup:

```text
chat_port_listening_after_cleanup=false
mcp_port_listening_after_cleanup=false
```

Classification: bounded local runtime proof that xmuse restores the dynamic
OpenCode participant's GOD session after service restart and can deliver a
second durable MCP writeback turn to that participant.

Caveats:

- This proves xmuse GOD session continuity, not OpenCode provider-native
  session resume; `provider_session_id` remained null.
- This is still targeted two-turn continuity, not broad natural Codex/OpenCode
  group discussion, proposal production, production readiness, live MemoryOS,
  GitHub review truth, or full closure.

## 2026-06-20 Loop 27h: Natural Groupchat Proposal Fullchain Probe

Purpose: extend Phase 2 dynamic-member continuity into a Phase 3 natural
groupchat-produced proposal consumed by the execution harness.

Runtime command shape:

```bash
uv run python - <<'PY'
# bounded probe driver:
# 1. start Chat API, MCP, and xmuse.platform_runner --peer-chat
# 2. create human, Codex architect, Codex execute, and OpenCode review members
# 3. post one human @architect demand requiring peer_consensus collaboration
# 4. let architect create a structured collaboration request to @execute/@review
# 5. wait for durable peer responses and collaboration callback
# 6. let architect emit one lane_graph proposal with collaboration reference
# 7. approve the proposal and wait for isolated execution, gate, persistent
#    OpenCode review, and final-action hold
# 8. snapshot durable state and clean up services
PY
```

Authority and artifacts:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/natural-groupchat-proposal-probe
base_head=9b76b8cece4ea20d75bb0ed875fb602bdd363265
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z
summary=.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z/loop_driver_artifacts/summary.json
final_snapshot=.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z/loop_driver_artifacts/final_snapshot.json
lane=.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z/loop_driver_artifacts/lane.json
proposal=.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z/loop_driver_artifacts/proposal.json
timeline=.goal-runs/2026-06-20/loop-27h-natural-groupchat-proposal-20260620T045459Z/loop_driver_artifacts/timeline.json
execution_worktree=/tmp/loop-27h-natural-groupchat-proposal-20260620T045459Z-exec
```

Runtime ports:

```text
chat_port=38749
mcp_port=36325
```

Durable ids:

```text
conversation_id=conv_2919a995464c41a9846ff81e2dd7bfda
collaboration_run=collab_ecd70e7a9edb4719ae8ea881b4f88177
proposal_id=prop_08dd65de7b444c82b2e93a8024424ccf
feature_id=loop_27h_natural_groupchat_proposal_20260620t045459z
execution_note=docs/xmuse/loop_27h_natural_groupchat_proposal_20260620t045459z.md
```

Observed durable state:

```text
collaboration_run.status=done
collaboration_run.orchestration_mode=peer_consensus
collaboration_run.targets=["@execute", "@review"]
collaboration_run.callback_target=@architect
collaboration_response_counts=[2]
proposal_count=1
proposal_type=lane_graph
proposal.references=["collaboration:collab_ecd70e7a9edb4719ae8ea881b4f88177"]
lane.status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
execution_note_matches=true
```

Execution artifact:

```text
path=/tmp/loop-27h-natural-groupchat-proposal-20260620T045459Z-exec/docs/xmuse/loop_27h_natural_groupchat_proposal_20260620t045459z.md
content=Natural groupchat proposal loop_27h_natural_groupchat_proposal_20260620t045459z reached isolated execution.
```

Observed caveats:

```text
architect collaboration-request latency.delivery_mode=failed
architect collaboration-request latency.degraded_reason=peer_response_timeout
execute collaboration response latency.degraded_reason=peer_no_inbox_writeback_message
```

Cleanup:

```text
chat_port_listening_after_cleanup=false
mcp_port_listening_after_cleanup=false
```

Classification: bounded local runtime proof that a natural Codex/OpenCode
peer-consensus groupchat can produce a durable proposal that the execution
harness consumes through isolated execution, gate, persistent OpenCode review,
and final-action hold.

Caveats:

- This remains docs-only local runtime proof, not production readiness.
- This does not prove provider-native OpenCode resume, live MemoryOS, GitHub
  review truth, repeated stability, broad code-change completion, or full
  closure.

## 2026-06-20 Loop 27j: Structured Tool Latency Repair Candidate

Purpose: rerun the reusable docs-only sentinel after repairing scheduler
latency classification for structured MCP tool writebacks.

Preceding evidence:

```text
Loop 27h exposed:
- chat_create_collaboration_request produced durable side effects but the
  architect turn recorded delivery_mode=failed / peer_response_timeout.
- chat_record_collaboration_response consumed the execute collaboration request
  but recorded peer_no_inbox_writeback_message because it has no assistant
  message id.

Loop 27i candidate rerun after the first patch:
- execute chat_record_collaboration_response recorded delivery_mode=mcp_writeback.
- architect chat_create_collaboration_request still recorded a failed timeout
  trace, so the same boundary needed one broader structured-tool predicate.
```

Focused RED/GREEN guard:

```bash
uv run pytest \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_accepts_collaboration_request_tool_writeback \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_accepts_structured_collaboration_response_writeback \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_without_real_writeback_message \
  tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_pointing_to_unrelated_message \
  -q
```

Result:

```text
4 passed in 1.12s
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-goal-main-20260620/.goal-runs/2026-06-20/loop-27j-structured-tool-latency-success-20260620T052938Z \
  --execution-worktree /tmp/loop-27j-structured-tool-latency-success-20260620T052938Z-exec \
  --feature-id loop_27j_structured_tool_latency_success_20260620t052938z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Authority and artifacts:

```text
repo_worktree=/tmp/xmuse-goal-main-20260620
branch=codex/collab-response-latency-success
base_head=c23c1fdbd68d12490327101994be89e15a1cc37c
run_root=/tmp/xmuse-goal-main-20260620/.goal-runs/2026-06-20/loop-27j-structured-tool-latency-success-20260620T052938Z
final_snapshot=.goal-runs/2026-06-20/loop-27j-structured-tool-latency-success-20260620T052938Z/loop_driver_artifacts/final_snapshot.json
cleanup=.goal-runs/2026-06-20/loop-27j-structured-tool-latency-success-20260620T052938Z/loop_driver_artifacts/cleanup.json
execution_worktree=/tmp/loop-27j-structured-tool-latency-success-20260620T052938Z-exec
```

Durable ids:

```text
conversation_id=conv_a74f15bf7227455f905f36b9a3afe9a8
collaboration_run=collab_594466ffed7347cc869d3089f23eccb1
proposal_id=prop_14abe5a75c3842158cc458075be143b4
resolution_id=res_6750f01f9930455b98fad2ccf0e266fd
lane_id=loop_27j_structured_tool_latency_success_20260620t052938z
review_task_id=rtask_1dbc8856a9e34b05b271cf33205cca5c
review_verdict_id=verdict-merge-rtask_1dbc8856a9e34b05b271cf33205cca5c
final_action_hold_id=final-35c87adbaca5
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
single_related_lane_graph_proposal=true
execution_note_matches=true
```

Peer latency evidence:

```text
architect chat_create_collaboration_request -> delivery_mode=mcp_writeback
execute chat_record_collaboration_response -> delivery_mode=mcp_writeback
architect chat_emit_proposal callback -> delivery_mode=mcp_writeback
execute chat_post_message dispatch ack -> delivery_mode=mcp_writeback
failed latency traces for this run: 0
```

Cleanup:

```text
chat_port=56005 closed
mcp_port=57505 closed
cleanup.chat_port_listening=false
cleanup.mcp_port_listening=false
```

Classification: candidate-branch local runtime proof that structured MCP tool
writebacks are no longer misclassified as failed peer turns in the bounded
docs-only fullchain sentinel.

Caveats:

- This is not server-side proof until the branch receives PR/CI/merge facts.
- The structured tool turns still record
  `degraded_reason=peer_writeback_before_provider_result`, which is a
  provider-result timing caveat, not failed durable writeback.
- This is not production readiness, provider-native OpenCode resume, live
  MemoryOS, GitHub review truth, repeated stability, broad code-change
  completion, or full closure.

## 2026-06-20 Loop 26o: Post-PR115 Collaboration Lifecycle Main Check

Purpose: verify the PR #115 collaboration lifecycle repair after it landed on
`origin/main`.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=87c6f131d7a9851f1a4c5b023b192323ad8e73e4
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26o-post-pr115-collaboration-lifecycle-041707
execution_worktree=/tmp/loop-26o-post-pr115-collaboration-lifecycle-041707-exec
conversation_id=conv_81e48f1b8b0d43e8b902254fc788ba5e
```

Durable chain:

```text
collaboration_run=collab_fd442c340eed442fa393fdfd6df0d768
proposal_id=prop_48599913802f4b48ad9da895dfb90e88
resolution_id=res_c61bd2acf98b42a8a57e17e9f69457b3
lane_id=loop_26o_post_pr115_collaboration_lifecycle_041707
final_action_hold_id=final-5a1dd9895d92
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
peer_delivery_mode=configured_peer
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Collaboration lifecycle state:

```text
collaboration_run.status=done
collaboration_run.targets=["@execute"]
collaboration_response.target=@execute
collaboration_request inbox=inbox_e540a9a9fb29497bbb8b0ffe4dd208e4 status=read
collaboration_callback inbox=inbox_3d71989df8214f478fd3855ede128719 status=read responded_message_id=msg_8810f6a9e9c14132add0475210b5ce87
dispatch inbox=inbox_9823e84400fc45dea6d4ff6415187296 status=read responded_message_id=msg_90516359292f4ef0a31ba050354780b9
trace=inbox_e540a9a9fb29497bbb8b0ffe4dd208e4 chat_record_collaboration_response
trace=inbox_3d71989df8214f478fd3855ede128719 chat_emit_proposal
trace=inbox_9823e84400fc45dea6d4ff6415187296 chat_post_message
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26o service process matches after shutdown: none
```

Note: `platform_runner.log` ended with a Python asyncio subprocess transport
cleanup warning after shutdown. The driver exited successfully, all success
checks passed, and ports/processes were clean. Treat the warning as cleanup
noise to watch, not as runtime proof or production readiness.

Classification: bounded post-merge main runtime proof for PR #115's
collaboration request/response/callback inbox lifecycle repair on the docs-only
fullchain sentinel shape.

Caveats:

- This is not production readiness, repeated soak, MemoryOS proof, GitHub
  review truth, natural peer-GOD groupchat completion, or full closure.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 26p: Handoff-Scoped Peer Reply Dependency Candidate

Purpose: repair the P1 coordination gap where direct peer-reply drain callbacks
used sender-global pending mentions instead of a durable handoff message as the
dependency set.

Pre-fix durable-store probe:

```text
producer=ChatStore.create_message_inbox_and_log
consumer=ChatStore reply_to_inbox_item_id callback creation
shape=two independent architect handoff messages
first_handoff_target=execute
second_handoff_target=review
observed_before_fix=execute reply produced 0 peer_reply_drain_callback items
blocking_state=review handoff inbox remained unread
classification=sender-global drain blocked a completed independent handoff
```

Candidate change:

```text
branch=codex/peer-reply-dependency-set-callback
files=src/xmuse_core/chat/store.py, tests/xmuse/test_peer_chat_mcp_tools.py
dependency_set_authority=chat_inbox_items.source_message_id
callback_payload_fields=dependency_set_id, source_message_id, dependency_targets
```

Post-fix durable-store probe:

```text
execute_reply_callbacks=1
dependency_set_id=peer-reply-set:<first source message id>
dependency_targets=["execute"]
unrelated_review_inbox_status=unread
```

Focused validation:

```text
uv run pytest tests/xmuse/test_peer_chat_mcp_tools.py -q \
  -k 'peer_replies_enqueue_drain_callback_for_original_sender or peer_reply_drain_callback_is_scoped_to_source_handoff'
-> 2 passed, 22 deselected, 1 warning
```

Broad local note:

```text
uv run pytest tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_peer_chat_scheduler.py -q
-> 41 passed, 1 failed, 1 warning
```

The failure was pre-existing/unrelated to this candidate boundary:
`test_mcp_collaboration_tools_support_veto_and_dispatch_gate` creates no
execute participant but asks for `targets=["review", "execute"]`, so
`chat_create_collaboration_request` returns an error payload instead of
`run`. This was not folded into the dependency-set candidate.

Fullchain candidate rerun:

```bash
RUN_ID=loop-26p-dependency-set-callback-fullchain-044040
RUN_ROOT=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/$RUN_ID
EXEC_ROOT=/tmp/$RUN_ID-exec
FEATURE_ID=loop_26p_dependency_set_callback_fullchain_044040
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root "$RUN_ROOT" \
  --execution-worktree "$EXEC_ROOT" \
  --feature-id "$FEATURE_ID" \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain:

```text
base_head_sha=819e95046f82a8be970319b50cd581e44e60b66a
conversation_id=conv_36963d69e9bd4f6b8b3c9ec3fce8fff0
collaboration_run=collab_dc46c5918fb040a493300db796651033
proposal_id=prop_c3f500b569b74b4a95a936fa52f19ce2
resolution_id=res_7527b86a90b34e68bdce6ecdc6890eba
lane_id=loop_26p_dependency_set_callback_fullchain_044040
final_action_hold_id=final-157669a4cbdf
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Inbox and collaboration state:

```text
collaboration_run.status=done
collaboration_run.targets=["@execute"]
collaboration_request inbox=read
collaboration_callback inbox=read
review_trigger inbox=read
dispatch inbox=read
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
```

Classification: local candidate proof for handoff-scoped direct peer-reply
coordination plus fullchain non-regression on the docs-only sentinel shape.

Caveats:

- This is not PR CI, server truth, production readiness, repeated soak,
  MemoryOS proof, GitHub review truth, natural peer-GOD groupchat completion,
  or full closure.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 26q: Post-PR117 Peer Reply Dependency Main Check

Purpose: verify the PR #117 handoff-scoped peer reply callback repair after it
landed on `origin/main`.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=f3f7b6dafa94ceae179af26c448f1aae183fd24b
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26q-postmerge-dependency-set-fullchain-2058z
execution_worktree=/tmp/loop-26q-postmerge-dependency-set-fullchain-2058z-exec
conversation_id=conv_b36cbc5162e7462986079aecdbb7171a
```

GitHub server facts:

```text
pr=117
head_sha=6e66fb82407e29e401f859ed624ef54d5ca52cc5
merge_commit=f3f7b6dafa94ceae179af26c448f1aae183fd24b
pr_ci_run=27848017088 success
main_ci_run=27848097074 success
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26q-postmerge-dependency-set-fullchain-2058z \
  --execution-worktree /tmp/loop-26q-postmerge-dependency-set-fullchain-2058z-exec \
  --feature-id loop_26q_postmerge_dependency_set_fullchain_2058z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain:

```text
collaboration_run=collab_8bcefbde5d1147fb96827c6ffbe7bff7
proposal_id=prop_e32ea6c2fb4f4a4cbdbb4560d0c6b1c0
resolution_id=res_c137c05b6def40d3bc3c27f2eafda9e4
lane_id=loop_26q_postmerge_dependency_set_fullchain_2058z
review_task_id=rtask_bb92ef3081b94c85b042ac9640bf1cc1
review_verdict_id=verdict-merge-rtask_bb92ef3081b94c85b042ac9640bf1cc1
final_action_hold_id=final-616957b7f178
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Execution artifact:

```text
path=/tmp/loop-26q-postmerge-dependency-set-fullchain-2058z-exec/docs/xmuse/loop_26q_postmerge_dependency_set_fullchain_2058z.md
matches_expected=true
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26q service process matches after shutdown: none
```

Classification: bounded post-merge main runtime proof that PR #117's
handoff-scoped direct peer reply callback repair does not regress the
docs-only groupchat, proposal, approval, dispatch, isolated execution, gate,
persistent OpenCode review, and final-action hold path.

Caveats:

- This is not production readiness, repeated soak, MemoryOS proof, GitHub
  review truth, natural peer-GOD groupchat completion, or full closure.
- The dependency set remains scoped to a single handoff message target set; a
  general workflow dependency planner is not claimed.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 26r: Remove Empty Codex Default Review Fallback Candidate

Purpose: quarantine the remaining empty-conversation legacy path where default
review routing could create a Codex review participant when no active OpenCode
reviewer existed.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/default-review-no-codex-fallback
base_head_sha=3d82fda4342f57c224f9f5c60b4d5193cdcb2a01
authority=chat.db participants table plus review_god lane state
```

Focused RED:

```text
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py::test_default_review_peer_routing_empty_conversation_without_opencode_fails_closed -q
-> failed before fix because persistent.ensured contained one Codex review session
```

Candidate behavior:

```text
missing_opencode_review_peer -> review_peer_runtime_unavailable
lane.status=gate_failed
failure_reason=required_review_peer_unavailable
peer_delivery_mode=required_peer_failed
created_codex_review_participant=false
one_shot_review_invoked=false
```

Focused validation:

```text
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q -k 'default_review_peer'
-> 12 passed, 39 deselected

uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_persistent_review_session_contracts.py tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_package_boundaries.py -q
-> 91 passed

uv run ruff check .
-> All checks passed.

git diff --check
test ! -e xmuse/__init__.py
-> passed
```

Fullchain non-regression command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26r-no-codex-default-review-fallback-fullchain-2112z \
  --execution-worktree /tmp/loop-26r-no-codex-default-review-fallback-fullchain-2112z-exec \
  --feature-id loop_26r_no_codex_default_review_fallback_2112z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain:

```text
conversation_id=conv_064004c3996c41ac97c11eeb213493b7
collaboration_run=collab_9f987fe6a9b84a80b15425edb9cbd04d
proposal_id=prop_024a3c6de13344fca5ff19dcd3018ad5
resolution_id=res_71195ad2043c44559911926924af0408
lane_id=loop_26r_no_codex_default_review_fallback_2112z
review_task_id=rtask_2bc8208bfde54f5c88d885319781cd2c
review_verdict_id=verdict-merge-rtask_2bc8208bfde54f5c88d885319781cd2c
final_action_hold_id=final-8a9e25d0ab8c
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26r service process matches after shutdown: none
```

Classification: local candidate proof that default review routing no longer
creates a Codex reviewer when no active OpenCode reviewer exists, plus bounded
fullchain non-regression for the registered OpenCode review route.

Caveats:

- This is not PR CI, server truth, production readiness, MemoryOS proof,
  GitHub review truth, natural peer-GOD groupchat completion, or full closure.
- Configured-peer degradation fallback remains a separate review-authority
  question.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 26s: Post-PR119 No-Codex Default Review Main Check

Purpose: verify the PR #119 default-review authority repair after it landed on
`origin/main`.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
base_head_sha=353f61e442ffcae3a97377f54b44b9094e1ebb10
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26s-post-pr119-no-codex-default-review-fallback-2125z
execution_worktree=/tmp/loop-26s-post-pr119-no-codex-default-review-fallback-2125z-exec
conversation_id=conv_6414e806c7f14de1881a391603f00ddb
```

GitHub server facts:

```text
pr=119
head_sha=2e71882465250f6894fcd1e7b881a53f54f96e17
merge_commit=353f61e442ffcae3a97377f54b44b9094e1ebb10
pr_ci_run=27849001334 success
main_ci_run=27849053122 success
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26s-post-pr119-no-codex-default-review-fallback-2125z \
  --execution-worktree /tmp/loop-26s-post-pr119-no-codex-default-review-fallback-2125z-exec \
  --feature-id loop_26s_post_pr119_no_codex_default_review_fallback_2125z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain:

```text
collaboration_run=collab_f86f828584dd461ca4b891e5c641c5ee
proposal_id=prop_6563c68745894161aa994612432a218a
resolution_id=res_6bb6611b01094500bdbffb0e1591d9cb
lane_id=loop_26s_post_pr119_no_codex_default_review_fallback_2125z
review_task_id=rtask_0a720efb53b14258882e7275a1b02a76
review_verdict_id=verdict-merge-rtask_0a720efb53b14258882e7275a1b02a76
final_action_hold_id=final-111af2b61178
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Execution artifact:

```text
path=/tmp/loop-26s-post-pr119-no-codex-default-review-fallback-2125z-exec/docs/xmuse/loop_26s_post_pr119_no_codex_default_review_fallback_2125z.md
matches_expected=true
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26s service process matches after shutdown: none
```

Classification: bounded post-merge main runtime proof that the PR #119
default-review authority repair preserves the registered OpenCode review route
for the docs-only groupchat, proposal, approval, dispatch, isolated execution,
gate, persistent review, and final-action hold path.

Caveats:

- This is not production readiness, repeated soak, MemoryOS proof, GitHub
  review truth, natural peer-GOD groupchat completion, or full closure.
- Configured-peer degradation fallback remains a separate review-authority
  question.
- The final action was intentionally held; no live lane merge is claimed.

## 2026-06-20 Loop 26t: Configured Review Peer Fail-Closed Candidate

Purpose: close the remaining configured-review-peer degradation fallback
boundary so a failed configured review peer cannot be replaced by auto
persistent or one-shot review authority.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/review-configured-peer-degradation
base_head_sha=24fc168672a90de8dd56d512269fee4e021dfeff
review_authority=lane review metadata / review verdict path
```

Focused repro before implementation:

```bash
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q -k 'configured_review_peer_preferred_failure_fails_closed_before_auto_persistent or configured_review_peer_preferred_failure_fails_closed_before_one_shot or preferred_configured_review_peer_no_verdict_fails_closed'
```

Result:

```text
3 failed
```

Observed old behavior:

```text
preferred configured peer wrong request id -> second persistent review sent
preferred configured peer wrong request id -> one-shot spawner invoked
preferred configured peer no verdict -> one-shot spawner invoked
```

Candidate behavior after implementation:

```text
status=gate_failed
failure_layer=review
peer_delivery_mode=configured_peer_failed
failure_reason=review_peer_delivery_failed
peer_degraded_reason=request_id_mismatch | review_peer_no_verdict
one_shot_spawn_count=0
auto_persistent_second_send=false
```

Validation:

```bash
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py -q
uv run pytest tests/xmuse/test_review_plane_orchestrator_integration.py tests/xmuse/test_persistent_review_session_contracts.py tests/xmuse/test_persistent_cli_peer.py tests/xmuse/test_package_boundaries.py -q
uv run ruff check .
git diff --check
test ! -e xmuse/__init__.py
```

Result:

```text
review integration: 51 passed
review/session/peer/package focused set: 91 passed
ruff: All checks passed
git diff --check: passed
xmuse/__init__.py: absent
```

Fullchain command attempted:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26t-configured-review-failclosed-fullchain-2150z \
  --execution-worktree /tmp/loop-26t-configured-review-failclosed-fullchain-2150z-exec \
  --feature-id loop_26t_configured_review_failclosed_fullchain_2150z \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain reached before blocker:

```text
conversation_id=conv_cb28b7f8e4234761be49e75139035967
collaboration_run=collab_c8713869e9474510b4ce0f9aa503dd7e
proposal_id=prop_7c58e0bb92094d60808ff640f4fcdd69
resolution_id=res_d3cfaaa19fb34705b34d9ed8bb62ebcf
lane_id=loop_26t_configured_review_failclosed_fullchain_2150z
```

Final observed lane state:

```text
status=exec_failed
base_head_sha=24fc168672a90de8dd56d512269fee4e021dfeff
worker_provider_profile_ref=codex.default
failure_reason=execution_infra_unavailable
failure_layer=coordinator
```

Execution blocker:

```text
OpenAI Codex child worker returned usage_limit on three spawn attempts.
The lane did not reach gate or review.
```

Cleanup:

```text
manual termination was required because the sentinel script did not treat exec_failed as terminal
chat_port_listening=false
mcp_port_listening=false
```

Classification: focused local candidate proof for configured review peer
fail-closed behavior; fullchain non-regression blocked before review by
external Codex execution-worker usage limit.

Caveats:

- This is not post-merge proof.
- This is not production readiness, GitHub review truth, live MemoryOS,
  natural peer-GOD groupchat completion, or full closure.
- The sentinel harness terminal-state gap is separate from the configured
  review peer authority repair.

## 2026-06-20 Loop 26u: Post-PR121 Server Confirmation

Purpose: record the GitHub server facts after the configured review peer
degradation repair landed.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/post-pr121-review-degradation-evidence
main_head_sha=1adc2d19089aeacad5953bc577ca093f3441a761
```

GitHub server facts:

```text
pr=121
head_sha=79b09d2c411440ab1fe152c2f67b470bd774816f
merge_commit=1adc2d19089aeacad5953bc577ca093f3441a761
pr_ci_run=27850304479 success
main_ci_run=27850336946 success
remote_branch_deleted=true
```

Validation for this docs-only evidence sync:

```bash
git diff --check
test ! -e xmuse/__init__.py
uv run ruff check .
```

Classification: bounded post-merge GitHub server confirmation for PR #121.
The runtime path remained at the Loop 26t blocker until Loop 26x later reran
the docs-only sentinel successfully from post-PR124 main.

Caveats:

- This entry does not add post-merge runtime proof.
- It does not claim production readiness, GitHub review truth, live MemoryOS,
  natural peer-GOD groupchat completion, full closure, or live lane merge
  truth.

## 2026-06-20 Loop 26v: Fullchain Sentinel Exec-Failed Terminal Harness

Purpose: prevent the docs-only fullchain sentinel from waiting for lane timeout
after a lane has already reached terminal `exec_failed`.

Observed source:

```text
loop=26t
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26t-configured-review-failclosed-fullchain-2150z
lane_id=loop_26t_configured_review_failclosed_fullchain_2150z
status=exec_failed
failure_reason=execution_infra_unavailable
failure_layer=coordinator
```

Focused RED:

```bash
uv run pytest tests/xmuse/test_fullchain_docs_sentinel.py -q
```

Result before implementation:

```text
1 failed
AssertionError: exec_failed should be treated as terminal
```

Candidate behavior:

```text
scripts/run_fullchain_docs_sentinel.py::_wait_for_lane
terminal status set includes exec_failed
```

Validation:

```bash
uv run pytest tests/xmuse/test_fullchain_docs_sentinel.py -q
uv run ruff check scripts/run_fullchain_docs_sentinel.py tests/xmuse/test_fullchain_docs_sentinel.py
```

Result:

```text
1 passed
ruff: All checks passed
```

Classification: local harness candidate only. It shortens future failure
classification loops; it does not provide product runtime proof.

## 2026-06-20 Loop 26w: Post-PR123 Server Confirmation

Purpose: record GitHub server facts after the fullchain sentinel `exec_failed`
terminal-state repair landed.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/post-pr123-sentinel-evidence
main_head_sha=162da10f4ef1d515a95ea9fc90889494c8e75146
```

GitHub server facts:

```text
pr=123
head_sha=6f145725e8488081c5572ec72060f9d8062ba906
merge_commit=162da10f4ef1d515a95ea9fc90889494c8e75146
pr_ci_run=27850584077 success
main_ci_run=27850614290 success
remote_branch_deleted=true
```

Validation for this docs-only evidence sync:

```bash
git diff --check
test ! -e xmuse/__init__.py
uv run ruff check .
```

Classification: bounded post-merge GitHub server confirmation for PR #123.
This does not add product runtime proof.

## 2026-06-20 Loop 26x: Post-PR124 Fullchain Sentinel Rerun

Purpose: rerun the docs-only fullchain sentinel from latest main after PR #121,
PR #123, and PR #124 landed, verifying that the earlier Codex execution-worker
usage-limit blocker has cleared.

Workspace and authority:

```text
repo_worktree=/tmp/xmuse-postmerge-layered-prompt-main
branch=codex/post-pr124-fullchain-rerun
base_head_sha=050385b32ce62c6868773555271f25b8debe26f8
run_root=/tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26x-post-pr124-fullchain-rerun-1117cst
execution_worktree=/tmp/loop-26x-post-pr124-fullchain-rerun-1117cst-exec
conversation_id=conv_a086f7a07892470696e76787581f1508
```

Runtime command:

```bash
uv run python scripts/run_fullchain_docs_sentinel.py \
  --run-root /tmp/xmuse-postmerge-layered-prompt-main/.goal-runs/2026-06-20/loop-26x-post-pr124-fullchain-rerun-1117cst \
  --execution-worktree /tmp/loop-26x-post-pr124-fullchain-rerun-1117cst-exec \
  --feature-id loop_26x_post_pr124_fullchain_rerun_1117cst \
  --proposal-timeout-s 900 \
  --lane-timeout-s 1200 \
  --max-hours 0.8
```

Durable chain:

```text
collaboration_run=collab_6cac3eac965d4821bc019470084d11df
proposal_id=prop_0c8c276523bf4b739a6a936a40d34c04
resolution_id=res_22c0304fb52841a58733749759a447d2
lane_id=loop_26x_post_pr124_fullchain_rerun_1117cst
review_task_id=rtask_9d7ea699c64c429d9e28ec29bef8a118
review_verdict_id=verdict-merge-rtask_9d7ea699c64c429d9e28ec29bef8a118
final_action_hold_id=final-510ce5ed0227
```

Final lane state:

```text
status=awaiting_final_action
gate_passed=true
review_decision=merge
review_delivery_mode=persistent
persistent_review_degraded=false
review_peer_defaulted=true
review_peer_cli_kind=opencode
review_peer_model=opencode-go/deepseek-v4-flash
proposal_has_review_runtime=false
single_related_lane_graph_proposal=true
```

Execution artifact:

```text
path=/tmp/loop-26x-post-pr124-fullchain-rerun-1117cst-exec/docs/xmuse/loop_26x_post_pr124_fullchain_rerun_1117cst.md
matches_expected=true
```

Success checks:

```text
approved_proposal_accepted=true
execution_peer_handoff_not_degraded=true
final_action_hold_pending=true
gate_passed=true
isolated_note_matches=true
lane_awaiting_final_action=true
opencode_review_peer_recorded=true
proposal_has_no_review_runtime=true
review_task_verdict_emitted=true
review_verdict_finalized=true
single_related_lane_graph_proposal=true
```

Cleanup:

```text
chat_port_listening=false
mcp_port_listening=false
loop-26x service process matches after shutdown: none
```

Classification: bounded post-merge main runtime proof that the docs-only
groupchat, proposal, approval, dispatch, isolated execution, gate, persistent
OpenCode review, and final-action hold path works after PR #121 and PR #123.

Caveats:

- This is not production readiness, repeated soak, MemoryOS proof, GitHub
  review truth, natural peer-GOD groupchat completion, or full closure.
- The final action was intentionally held; no live lane merge is claimed.
