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

### Post-PR72 proof-boundary and final-action callback reruns

#### Loop 25z34: post-PR72 main fullchain proof-boundary check

Runtime root:

```text
/tmp/xmuse-post-pr72-main/.goal-runs/2026-06-19/loop-25z34-post-pr72-main-fullchain-084618
```

Observed durable path:

```text
conversation_id=conv_e2f7d79a008143baaa01f71b9c9f7bdc
collaboration_run=collab_e63f97be43df48b390c8a79dab7013f6
execute_response=collab_resp_c1ec7b6f383c46d798ebb964d5fad0df
review_response=collab_resp_fad30bc1d4074668b772a835132c7183
proposal_id=prop_3361636d174045af9602a159e83352d2
resolution_id=res_2a1be59f6b9842deac99f81f9f5c8add
lane_id=loop25z34_post_pr72_main_fullchain
```

Lane state:

```text
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
final_action_hold_id=final-57b1f8883a1f
```

Finding: the OpenCode review summary persisted into lane metadata,
`review_plane.json`, and `final_actions.json` said the lane was "reviewed and
merged" even though the authoritative state was only `awaiting_final_action`.
This was a proof-boundary wording defect, not merge truth.

Resulting PR:

```text
PR #73: https://github.com/iiyazu/Cross-Muse/pull/73
branch=codex/review-proof-boundary-summary-safety
head=3d29f1cdb75f6bfc694f6d734c057884a9c59f26
merge_commit=f00399ee5fef6a5560564b073ce78c5d223d75d8
merged_at=2026-06-19T01:06:36Z
main_push_ci=27799088742 success
```

PR #73 sanitizes durable review summaries before they enter lane metadata,
review-plane verdicts, or final-action holds.

#### Loop 25z35: post-PR73 main fullchain final-action callback repro

Runtime root:

```text
/tmp/xmuse-post-pr73-main/.goal-runs/2026-06-19/loop-25z35-post-pr73-main-fullchain-090915
```

Observed durable path:

```text
conversation_id=conv_78734df274fc4d60af7c684e0a61a946
collaboration_run=collab_955dc85c3c1049acbc9a131f70b3e422
proposal_id=prop_9cac7611b67c4b42ac1059442e2e39e0
resolution_id=res_87d1c49421bc4ae595b3b5f9c59e2953
lane_id=loop25z35_post_pr73_main_fullchain
```

The lane reached execution, gate, OpenCode persistent review, and final-action
hold creation. PR #73's sanitizer worked: the persisted review summary was
`review accepted`, with no "reviewed and merged", `ready_to_merge`, or
`pr_merged` wording in authority-facing stores.

New failure:

```text
InvalidTransitionError: cannot transition loop25z35_post_pr73_main_fullchain
from awaiting_final_action to reviewed
```

Root cause: persistent review callback delivery arrived after the review plane
had already converted the merge verdict into a pending final-action hold. The
callback retried `reviewed` instead of treating `awaiting_final_action` as an
already-committed review state.

Resulting PR:

```text
PR #74: https://github.com/iiyazu/Cross-Muse/pull/74
branch=codex/persistent-review-final-action-idempotency
head=e568f7bb61bd8993eea58db18573ac35556de491
merge_commit=4adc60a634a11703887d5d4aae42c878ce492e6e
merged_at=2026-06-19T01:25:30Z
main_push_ci=27799697662 success
```

PR #74 makes persistent review callbacks idempotent when a merge review has
already produced an `awaiting_final_action` hold.

#### Loop 25z36: post-PR74 main fullchain rerun

Runtime root:

```text
/tmp/xmuse-post-pr74-main/.goal-runs/2026-06-19/loop-25z36-post-pr74-main-fullchain-092635
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

Conversation and peer group:

```text
conversation_id=conv_c177e451d4424777bf4c7554ba40a48f
architect_participant=part_b70740cbc7b04297aeb1e00d2b2414e8 codex gpt-5.4
execute_participant=part_0bbed2e0ba6e4777a28e37bfd0c3cb70 codex gpt-5.4-mini
review_participant=part_b05d71ea233d4ebb898777237d3b69bd opencode opencode-go/deepseek-v4-flash
```

The human demand mentioned only `@architect`; execute and review were brought
in by architect handoff rather than by direct human mentions.

Durable groupchat:

```text
human_message=msg_6c9effdcd4d1482ea743934700c3fa3e
collaboration_run=collab_3702effdfe2d4bc4b47ce3c9141ce73c
execute_response=collab_resp_4ac517ee2f34494682d8800404b26346
review_response=collab_resp_e25767d3afe14a6298eb27cb497723a6
proposal_id=prop_5c3419819fce4bbe9220f32101a1c4f7
resolution_id=res_3500bc36a8804f60a5cdbf61303a4295
```

Lane and review result:

```text
lane_id=loop25z36_post_pr74_main_fullchain
status=awaiting_final_action
gate_passed=true
review_runtime=opencode
review_runtime_requested=opencode
review_peer_id=part_b05d71ea233d4ebb898777237d3b69bd
peer_delivery_mode=configured_peer
review_delivery_mode=persistent
persistent_review_degraded=false
review_decision=merge
review_verdict_id=verdict-merge-rtask_8517335ce9734b4ab471c2fd4eea10b2
final_action_hold_id=final-d94401567174
```

Gate report:

```text
logs/gates/loop25z36_post_pr74_main_fullchain/report.json
passed=true
blocking_passed=true
strict-product: uv run pytest -q tests/xmuse/test_package_boundaries.py -> 0
```

Durable peer trace summary:

```text
architect delivery_mode=mcp_writeback
execute delivery_mode=mcp_writeback
review delivery_mode=mcp_writeback
degraded_reason=null for all peer_turn_latency_traces rows
architect callback tool trace includes chat_emit_proposal
OpenCode review process used --variant max
```

Negative search:

```text
rg "InvalidTransitionError|cannot transition|awaiting_final_action to reviewed|reviewed and merged|ready_to_merge=true|pr_merged=true" "$ROOT" -> no matches
```

Cleanup:

```text
8100/8201/8265 listeners: none
xmuse service processes: none
Ray service processes from the run: none
```

Claims not made: GitHub review truth, merge truth, `ready_to_merge`,
`pr_merged`, live MemoryOS, full L8-L10 closure, full L1-L11 closure,
production-ready groupchat, or overnight readiness. The final-action hold
remains pending under `--no-auto-merge`; this is not a claim that a local merge
or PR merge occurred.
