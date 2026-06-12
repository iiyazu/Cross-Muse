# Vision Production Evidence-Control Closure Walkthrough

Updated: 2026-06-12

This artifact records the first implementation slice for
`docs/xmuse/vision-production-evidence-control-closure-plan.md`.

It does not claim full production closure. It moves production control from
documents into testable contracts for GOD/CLI selection, TUI operator action
execution, action audit, and release readiness evaluation.

## Current Production Baseline

Observed during this run:

- Branch: `vision-closure-deliberation-tui`.
- `xmuse/__init__.py` remains absent.
- `gh auth status` succeeds for GitHub user `iiyazu` with ssh git protocol.
- `codex --version` returns `codex-cli 0.139.0`.
- `opencode --version` returns `1.17.3`.
- `uv run python` can import Ray: `ray_import=ok:2.55.1`.
- The `ray` shell command is not on PATH.
- `uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100`
  reports Chat API and MCP as unreachable, runner process missing, and cleanup
  status clean.
- The current shell has no configured MemoryOS Lite URL/flag, Ray backend env
  bundle, DeepSeek/OpenCode API key, or TUI operator capability env.

These facts mean live production gates are not satisfied in the current shell.
They are release blockers or operator setup gaps, not fake-runtime successes.

## Implemented Slice

### GOD/CLI Registry

New module:

```text
src/xmuse_core/providers/god_cli_registry.py
```

The registry makes GOD participant selection explicit:

- `codex.god` is exposed as the built-in peer-GOD-capable CLI boundary.
- `opencode.deepseek_flash_worker` remains bounded: code writing and
  deliberation only.
- OpenCode allowed speech acts remain `propose`, `ask`, and `challenge`.
- Manual peer-GOD registration requires persistent sessions, MCP writeback,
  state-write authority, and `real_provider_proof`.
- Selecting a CLI for peer-GOD work returns an explicit allowed/blocked
  selection result.

`build_god_cli_inventory()` is exported through
`src/xmuse_core/platform/provider_read_contracts.py` so read surfaces can show
registered GOD CLI choices.

### Operator Action Contract And Audit

New module:

```text
src/xmuse_core/platform/operator_actions.py
```

The first production operator action is:

```text
select_god_cli
```

It requires the `select_god_cli` capability. Without that capability, the result
is `denied`. If the operator selects a bounded CLI such as OpenCode for peer-GOD
authority, the result is `blocked`.

Every handled action writes an audit row to:

```text
xmuse/work/operator_actions/operator-actions.jsonl
```

This is ignored runtime state. It is useful for operator audit but is not a
durable authority replacement.

### TUI Control Surface

The TUI now has a production-control route:

```text
/god select <cli_id>
```

Adapter behavior:

- `XmuseAdapter.run_operator_control_action(...)` routes the request through
  `OperatorActionService`.
- TUI operator capabilities come from
  `XMUSE_TUI_OPERATOR_CAPABILITIES`.
- Without `XMUSE_TUI_OPERATOR_CAPABILITIES=select_god_cli`, `/god select` is
  denied instead of mutating state.
- TUI command events now accept `operator_action_contract` and
  `operator_evidence_action` as recorded surface authorities.

This is intentionally not a direct projection write. Selection goes through a
contract service and emits audit evidence. The current production-control path
also exposes the action through Chat API:

```text
POST /api/chat/operator/actions
GET /api/chat/operator/god-cli-selections/{conversation_id}
```

The API reads operator identity from `X-XMuse-Operator-Id` and operator
capabilities from `X-XMuse-Operator-Capabilities`. A successful `select_god_cli`
call persists the selected CLI in:

```text
xmuse/god_cli_selections.json
```

That file is runtime state. It records the selected CLI per conversation with
`source_authority=operator_action_contract`, `proof_level=contract_proof`, and
the audit id that authorized the write. The TUI adapter now attempts this Chat
API path first and falls back to the same local contract service only when the
API is unavailable.

### Release Readiness Contract

New module:

```text
src/xmuse_core/platform/release_readiness.py
```

It evaluates release gates with explicit proof-level requirements:

- local validation requires `contract_proof`;
- internal review requires `internal_review_proof`;
- MemoryOS live gate requires `live_service_proof`;
- GitHub server truth requires `server_side_enforcement_proof`;
- GitHub merge truth requires `server_side_merge_proof`;
- real provider gate requires `real_provider_proof`.

The evaluator blocks fake/local proof from satisfying production live gates and
blocks internal review from substituting for GitHub server enforcement.

## Proof-Level Summary

| Surface | Current proof | Boundary |
| --- | --- | --- |
| GOD/CLI registry | `contract_proof` | Defines selectable boundaries; does not prove live CLI runtime. |
| `/god select` route | `contract_proof` | TUI action path calls Chat API first; no live operator session proof. |
| Operator action audit | `contract_proof` | JSONL audit row written in test/runtime path; not durable authority. |
| GOD CLI selection store | `contract_proof` | Durable per-conversation selection record; does not prove live CLI runtime. |
| Release readiness evaluator | `contract_proof` | Blocks proof contamination; no live gate captured. |
| MemoryOS live gate | `manual_gap` | Env not configured in current shell. |
| Ray/Codex/OpenCode live gate | `manual_gap` | Binaries/Ray import exist, but production services/env are not running/configured. |
| GitHub server truth | `manual_gap` | GitHub auth exists, but no PR/server capture was completed in this slice. |

## Validation

Focused validation run during this slice:

```bash
uv run pytest tests/xmuse/test_god_cli_registry.py tests/xmuse/test_operator_actions.py tests/xmuse/test_release_readiness.py -q
uv run pytest tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_selects_god_cli_with_capability tests/xmuse/test_tui_adapter.py::test_adapter_operator_control_action_denies_without_capability tests/xmuse/test_tui_adapter.py::test_adapter_records_operator_action_tui_command_event tests/xmuse/test_tui_navigation.py::test_chat_screen_help_command_lists_slash_commands tests/xmuse/test_tui_navigation.py::test_chat_screen_god_select_runs_operator_control_action -q
```

Observed results:

```text
10 passed
8 passed, 1 warning
```

The warning is the existing Starlette/httpx deprecation warning from FastAPI
`TestClient`.

## Remaining Production Gaps

- No production Auth/RBAC middleware has been applied to Chat API or MCP routes
  yet.
- `/god select` now persists selected GOD CLI per conversation, but this is
  still a CLI selection authority only; it does not prove a live provider
  session is running.
- Live MemoryOS Lite was not configured in the current shell.
- Ray/Codex/MCP services were not running during health check.
- OpenCode binary exists, but `DEEPSEEK_API_KEY` is not configured in this
  shell.
- GitHub auth exists, but no PR/server-truth release capture was completed.
- No natural multi-GOD live transcript was captured.
- Release readiness cannot be `ready` until configured live gates produce real
  evidence or named blockers are resolved.

## Next Recommended Slice

1. Bind selected CLI records into the official conversation/bootstrap
   participant flow where role templates need selected runtime providers.
2. Implement production operator capabilities for the remaining Chat API/MCP
   write routes.
3. Add a release-readiness capture command that reads live gate artifacts and
   writes a redacted readiness report.
4. Start the configured Chat API/MCP/platform runner bundle and capture a real
   Ray/Codex/MCP health proof.
5. Create or target a draft PR and run GitHub server truth capture against it.
