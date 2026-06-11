# xmuse TUI Slash Command Handoff

Last updated: 2026-06-02

## Scope

Implement a production-quality slash command layer for the current Textual TUI
so group chat behaves closer to Codex/Claude Code/OpenCode:

- `/resume` is the reliable keyboard-first way to switch group chats.
- `/new` creates a new isolated group chat and selects it.
- `/participants` and `/where` make the current group state visible.
- `/god add` and `/god rm` manage conversation-scoped GOD participants.
- Left rail selection still works as a visual shortcut.
- Right side shows the current group's GOD participants, not only worklist data.
- GOD-to-GOD `@mention` works even when the model replies as plain final text
  instead of calling the MCP `chat_mention` tool.

Do not implement a browser frontend. The current front door is `xmuse/tui`.

## Repo And Runtime Facts

- Repo: `/home/iiyatu/projects/python/memoryOS`
- Current active work is dirty; do not revert unrelated changes.
- Use WSL/Linux side only.
- Historical runtime material belongs under `xmuse/history/`; do not inspect
  Windows/Open Design frontend directories.
- Current services have been run in tmux:
  - `xmuse_chat_api`
  - `xmuse_dashboard_api`
  - `xmuse_mcp`
  - `xmuse_runner`
  - `xmuse_tui`
- Recent runner command:

```bash
XMUSE_RAY_GOD_TRANSPORT=app-server \
XMUSE_RAY_GOD_EFFORT=low \
XMUSE_RAY_GOD_MCP=0 \
uv run python xmuse/platform_runner.py --max-hours 8 --max-concurrent 4 --peer-chat
```

- Recent TUI command:

```bash
XMUSE_CHAT_API_URL=http://127.0.0.1:8201 uv run python -m xmuse.tui
```

## Current Problems To Fix

### 1. Left rail conversation switching is unreliable

Current code has `ChatScreen.on_listview_selected`. Textual event handler naming
is likely wrong for `ListView.Selected`; verify and change to the correct
handler, likely `on_list_view_selected`.

File:

- `xmuse/tui/screens/chat_screen.py`

Expected:

- Selecting a left rail item changes `app.state.active_conversation_id`.
- Message log clears and renders the selected conversation.
- `/resume` provides a reliable fallback even if mouse/focus behavior changes.

### 2. Slash commands are currently hardcoded in `ChatScreen`

Current `on_input_submitted` has inline checks for `/new`, `/archive`,
`/where`, `/copy`. This should become a reusable command router.

Recommended new module:

- `xmuse/tui/slash_commands.py`

Suggested structures:

```python
@dataclass(frozen=True)
class SlashCommandResult:
    handled: bool
    refresh: bool = False
    message: str | None = None


@dataclass
class SlashCommandContext:
    app: Any
    screen: Any


class SlashCommandRouter:
    def dispatch(self, content: str, context: SlashCommandContext) -> SlashCommandResult:
        ...
```

Keep this lightweight. Do not import provider internals into the TUI command
router. TUI commands should call `XmuseAdapter` methods and update `AppState`.

### 3. New group chats do not expose/manage GOD participants in TUI

Existing API support:

- `POST /api/chat/conversations`
- `GET /api/chat/conversations/{conversation_id}/participants`
- `POST /api/chat/conversations/{conversation_id}/participants`
- `DELETE /api/chat/conversations/{conversation_id}/participants/{participant_id}`
- `GET/POST/PUT/DELETE /api/chat/role-templates`

Current adapter already has:

- `XmuseAdapter.create_group_conversation(title)`
- `XmuseAdapter.get_participants(conv_id)` but it reads local store directly.

Add adapter methods as needed:

- `add_participant(conv_id, role, display_name=None, model=None, role_template_id=None)`
- `remove_participant(conv_id, role_or_participant_id)`
- optionally `list_role_templates()`

Prefer chat API for mutations. Direct store reads are acceptable only as a
fallback/read path already used by the adapter.

### 4. Right pane lacks participant visibility

Current right pane only has `WorklistSummary`.

Add a small participant section above or below worklist:

- current group title/id summary
- role/display name/model/status for active participants
- compact command hints are okay, but do not turn it into a help wall

No nested cards. Keep the TUI dense and readable.

### 5. GOD-to-GOD plain-text mentions are not routed

Observed:

```text
user: @architect 让你@他打招呼
architect: @execute 你好呀
user: @execute 你收到architect的消息了吗
execute: 收到了，还没有看到 architect 的消息
```

Reason: when the GOD uses MCP `chat_mention`, `PeerChatService.mention_from_god`
creates an inbox item. But the current Ray/app-server fallback path persists a
plain final assistant message through `PeerChatScheduler._post_stdout_reply_if_available`.
That path does not route `@execute` mentions.

Files:

- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/chat/mentions.py`
- `src/xmuse_core/chat/inbox_store.py`
- `src/xmuse_core/chat/store.py`
- `src/xmuse_core/chat/peer_service.py`

Recommended fix:

- In scheduler final-reply fallback, resolve mentions from the final content
  against active participants in the same conversation.
- Ignore unknown mentions such as `@human`; do not fail the visible reply.
- When valid participant mentions exist, create inbox items for them.
- Mark the original inbox item read with the final reply.
- Avoid self-mention loops where target participant is the same as sender.

Implementation options:

1. Best: use `ChatStore.create_message_inbox_and_log` so message + inbox items
   are atomic and metadata matches existing human/GOD APIs.
2. Acceptable narrow fix: call `ChatStore.add_message`, then create inbox items
   through `ChatInboxStore.create_item` for resolved mentions, then mark the
   original item read. If doing this, add focused tests around mention routing.

## Required Slash Commands

Minimum production set:

```text
/help
/sessions
/resume <number|conversation_id|title fragment>
/new <title>
/where
/participants
/god add <role> [display name]
/god rm <role|participant_id>
/archive
/copy
```

Semantics:

- `/sessions` lists non-archived user group conversations sorted by latest/created
  timestamp. Include stable 1-based numbers for immediate `/resume 2`.
- `/resume` matches in this order:
  1. exact 1-based session number from current `/sessions` view
  2. exact conversation id
  3. unique title substring
  4. if ambiguous, print candidates and do not switch
- `/new` creates the group through chat API, activates it, refreshes left rail,
  and shows default participants.
- `/where` prints current conversation id/title and participant summary.
- `/participants` prints current participants.
- `/god add` posts to participants API. If role maps to predefined template
  (`architect`, `review`, `execute`), `role_template_id` can be omitted.
  For custom roles, use a role template if one is available; otherwise return
  a clear error.
- `/god rm` resolves by exact participant id first, then exact role if unique.
- Unknown slash commands should print a concise error and suggest `/help`.

Do not directly forward xmuse platform commands to the underlying Codex/OpenCode
slash parser. If passthrough is added later, use an explicit namespace such as:

```text
/codex architect /compact
/opencode worker /model deepseek-v4-flash /variant max
```

That passthrough is optional and not required for this task.

## Key Files

TUI:

- `xmuse/tui/app.py`
- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `xmuse/tui/state.py`
- `xmuse/tui/widgets/message_log.py`

Chat API and stores:

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/api_models.py`
- `src/xmuse_core/chat/store.py`
- `src/xmuse_core/chat/participant_store.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/inbox_store.py`
- `src/xmuse_core/chat/mentions.py`
- `src/xmuse_core/chat/peer_scheduler.py`

Tests:

- `tests/xmuse/test_tui_navigation.py`
- `tests/xmuse/test_tui_adapter.py`
- `tests/xmuse/test_tui_state.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/test_fe_vision_layer1_api.py`
- `tests/xmuse/test_chat_api.py`

Docs to read first:

- `xmuse/HANDOFF.md`
- `xmuse/FRONTEND_IMPLEMENTATION_GUIDE.md`
- `xmuse/FRONTEND_API.md`
- `xmuse/FRONTEND_VISION.md`
- `docs/xmuse/解耦开发协议.md`

## Testing Requirements

Focused tests must cover:

- `/sessions` output contains numbered conversations.
- `/resume 1`, `/resume <id>`, and `/resume <unique title fragment>` activate
  the expected conversation.
- ambiguous `/resume` does not switch and prints candidates.
- left rail selection activates a non-latest conversation.
- `/new` creates and selects a group.
- `/participants` renders current participants.
- `/god add` calls adapter/API and refreshes participants.
- `/god rm` resolves unique role or participant id.
- GOD final text containing `@execute` creates an inbox item for execute.
- Unknown mentions in GOD final text are ignored, not fatal.
- Self mentions are ignored to prevent loops.

Suggested commands:

```bash
uv run pytest \
  tests/xmuse/test_tui_navigation.py \
  tests/xmuse/test_tui_adapter.py \
  tests/xmuse/test_tui_state.py \
  tests/xmuse/test_peer_chat_scheduler.py

uv run ruff check \
  xmuse/tui \
  src/xmuse_core/chat/peer_scheduler.py \
  tests/xmuse/test_tui_navigation.py \
  tests/xmuse/test_tui_adapter.py \
  tests/xmuse/test_peer_chat_scheduler.py
```

If chat API models are changed, also run:

```bash
uv run pytest tests/test_fe_vision_layer1_api.py tests/xmuse/test_chat_api.py
```

## Acceptance Criteria

- TUI can switch away from the latest conversation via both left rail and
  `/resume`.
- User can create a group, inspect its GOD participants, add a GOD, remove a
  GOD, and keep chatting in the selected group.
- GOD plain-text `@role` replies route to the target GOD inbox.
- TUI command handling is not a pile of inline `if content.startswith(...)`
  branches in `ChatScreen`.
- Implementation reuses existing chat API/stores where possible.
- No unrelated refactors or history cleanup.
- Focused tests and ruff pass.

## Non-Goals

- Do not implement full OpenCode/Hermes/Codex slash command passthrough.
- Do not build a browser frontend.
- Do not rewrite Ray GOD runtime.
- Do not change feature/lane workflow unless required by tests.
- Do not clean or rewrite `feature_lanes.json` as part of this task.
