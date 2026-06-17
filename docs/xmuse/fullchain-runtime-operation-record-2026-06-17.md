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
