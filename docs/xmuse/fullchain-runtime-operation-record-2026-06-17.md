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
