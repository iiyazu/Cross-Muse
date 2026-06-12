# xmuse/tui/screens/chat_screen.py
from __future__ import annotations

import asyncio
import json
import os
import re

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key, MouseDown, MouseMove, MouseUp, Resize
from textual.screen import Screen
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea

from xmuse.tui.adapter.xmuse_adapter import StateDelta
from xmuse.tui.completion import CompletionCandidate, CompletionEngine
from xmuse.tui.slash_commands import SlashCommandContext, SlashCommandRouter
from xmuse.tui.state import StateUpdated
from xmuse.tui.widgets.blueprint_freeze_panel import BlueprintFreezePanel
from xmuse.tui.widgets.deliberation_cockpit import DeliberationCockpit
from xmuse.tui.widgets.execution_cockpit import ExecutionCockpit
from xmuse.tui.widgets.github_truth_panel import GitHubTruthPanel
from xmuse.tui.widgets.memory_trace_drawer import MemoryTraceDrawer
from xmuse.tui.widgets.message_log import MessageLog
from xmuse.tui.widgets.xmu_header import XmuHeader


class InputHistory:
    def __init__(self, max_per_type: int = 50) -> None:
        self._max = max_per_type
        self._messages: dict[str, list[str]] = {}
        self._slash: dict[str, list[str]] = {}
        self._msg_pos: dict[str, int] = {}
        self._slash_pos: dict[str, int] = {}

    def push_message(self, conv_id: str, text: str) -> None:
        self._push(self._messages, conv_id, text)

    def push_slash(self, conv_id: str, text: str) -> None:
        self._push(self._slash, conv_id, text)

    def _push(self, store: dict[str, list[str]], conv_id: str, text: str) -> None:
        entries = store.setdefault(conv_id, [])
        if entries and entries[-1] == text:
            return
        entries.append(text)
        if len(entries) > self._max:
            entries[: len(entries) - self._max] = []

    def navigate_up(self, conv_id: str) -> str:
        return self._navigate(self._messages, self._msg_pos, conv_id, 1)

    def navigate_down(self, conv_id: str) -> str:
        return self._navigate(self._messages, self._msg_pos, conv_id, -1)

    def navigate_up_slash(self, conv_id: str) -> str:
        return self._navigate(self._slash, self._slash_pos, conv_id, 1)

    def navigate_down_slash(self, conv_id: str) -> str:
        return self._navigate(self._slash, self._slash_pos, conv_id, -1)

    def _navigate(
        self,
        store: dict[str, list[str]],
        pos_store: dict[str, int],
        conv_id: str,
        direction: int,
    ) -> str:
        entries = store.get(conv_id, [])
        if not entries:
            return ""
        pos = pos_store.get(conv_id, -1)
        new_pos = pos + direction
        if new_pos < -1:
            return ""
        if new_pos >= len(entries):
            pos_store[conv_id] = -1
            return ""
        pos_store[conv_id] = new_pos
        if new_pos == -1:
            return ""
        idx = len(entries) - 1 - new_pos
        return entries[idx]

    def reset_position(self, conv_id: str) -> None:
        self._msg_pos[conv_id] = -1
        self._slash_pos[conv_id] = -1


class ConvListItem(ListItem):
    def __init__(self, conv_id: str, title: str) -> None:
        super().__init__(Label(f"{title}"))
        self.conv_id = conv_id


class WorkbenchTaskItem(ListItem):
    def __init__(self, lane: dict) -> None:
        lane_id = _lane_identifier(lane)
        status = str(lane.get("effective_status") or lane.get("status") or "?")
        title = str(lane.get("feature_label") or lane.get("title") or lane_id)
        super().__init__(Label(f"{status:<9} {lane_id} {title}"))
        self.lane = lane
        self.lane_id = lane_id


class WorkbenchInboxItem(ListItem):
    def __init__(self, item: dict) -> None:
        item_id = str(item.get("id") or item.get("message_id") or "?")
        title = str(item.get("title") or item.get("summary") or item.get("content") or item_id)
        status = str(item.get("status") or item.get("card_type") or "inbox")
        super().__init__(Label(f"{status:<12} {title[:80]}"))
        self.inbox_item = item
        self.inbox_item_id = item_id


class WorkbenchDetailPanel(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.renderable = ""

    def update(self, renderable="") -> None:
        self.renderable = renderable
        super().update(renderable)


class PaneDivider(Static):
    """Thin vertical divider. Click and drag to resize adjacent panes."""

    DEFAULT_CSS = """
    PaneDivider {
        width: 1;
        height: 100%;
        background: $primary-darken-2;
    }
    PaneDivider:hover {
        background: $primary;
    }
    """

    def __init__(self, divider_index: int) -> None:
        super().__init__(" ")
        self.divider_index = divider_index

    def on_mouse_down(self, event: MouseDown) -> None:
        event.stop()
        screen = self.screen
        if isinstance(screen, ChatScreen):
            screen._start_drag(self.divider_index, event.screen_x)


class ChatScreen(Screen):
    CSS = """
    #chat-horizontal {
        height: 1fr;
    }
    #pane-left {
        height: 100%;
        border: solid $primary;
    }
    #pane-center {
        height: 100%;
    }
    #pane-right {
        height: 100%;
        border: solid $primary;
    }
    #message-input {
        dock: bottom;
        margin: 1;
    }
    #completion-list {
        dock: bottom;
        height: auto;
        max-height: 10;
        display: none;
        border: solid $secondary;
        margin: 0 1;
    }
    #completion-list.visible {
        display: block;
    }
    #mode-status {
        dock: bottom;
        height: 1;
        margin: 0 1;
    }
    #search-input {
        dock: bottom;
        display: none;
        margin: 0 1;
    }
    #search-input.visible {
        display: block;
    }
    #task-list {
        height: 8;
        border: solid $secondary;
    }
    #inbox-list {
        height: 6;
        border: solid $secondary;
    }
    #deliberation-cockpit {
        height: 9;
    }
    #blueprint-freeze-panel {
        height: 8;
    }
    #execution-cockpit {
        height: 9;
    }
    #memory-trace-drawer {
        height: 7;
    }
    #github-truth-panel {
        height: 8;
    }
    #task-detail {
        height: 1fr;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    #execution-log {
        height: 8;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    PaneDivider.dragging {
        background: $warning;
    }
    """

    _dragging = False
    _drag_divider = 0
    _drag_start_x = 0
    _last_dx = 0
    _start_widths: tuple[int, int, int] = (20, 40, 20)

    def compose(self) -> ComposeResult:
        yield XmuHeader(id="header")
        with Horizontal(id="chat-horizontal"):
            yield ListView(id="pane-left")
            yield PaneDivider(divider_index=0)
            with Vertical(id="pane-center"):
                yield MessageLog(id="message-log")
                yield TextArea(
                    read_only=True,
                    soft_wrap=True,
                    show_line_numbers=False,
                    show_cursor=False,
                    id="copy-view",
                )
                yield ListView(id="completion-list", classes="completion-list")
                yield Input(id="search-input", placeholder="Search messages...")
                yield Static(id="mode-status", classes="mode-status")
                yield Input(id="message-input",
                            placeholder="Type a message... (Alt+Enter for newline)")
            yield PaneDivider(divider_index=1)
            with Vertical(id="pane-right"):
                yield Label("Inbox", classes="panel-header")
                yield ListView(id="inbox-list")
                yield Label("Deliberation", classes="panel-header")
                yield DeliberationCockpit(id="deliberation-cockpit")
                yield Label("Blueprint", classes="panel-header")
                yield BlueprintFreezePanel(id="blueprint-freeze-panel")
                yield Label("Execution", classes="panel-header")
                yield ExecutionCockpit(id="execution-cockpit")
                yield Label("Memory", classes="panel-header")
                yield MemoryTraceDrawer(id="memory-trace-drawer")
                yield Label("GitHub", classes="panel-header")
                yield GitHubTruthPanel(id="github-truth-panel")
                yield Label("Task list", classes="panel-header")
                yield ListView(id="task-list")
                yield Label("Task detail", classes="panel-header")
                yield WorkbenchDetailPanel(id="task-detail")
                yield Label("Execution log", classes="panel-header")
                yield WorkbenchDetailPanel(id="execution-log")

    def _distribute_widths(self, total_width: int) -> None:
        avail = total_width - 2  # 2 dividers
        left = max(10, int(avail * 0.25))
        right = max(10, int(avail * 0.25))
        center = max(10, avail - left - right)
        self._set_pane_widths(left, center, right)

    def _set_pane_widths(self, left: int, center: int, right: int) -> None:
        self._pane_left.styles.width = left
        self._pane_center.styles.width = center
        self._pane_right.styles.width = right

    def _start_drag(self, divider_index: int, screen_x: int) -> None:
        self._dragging = True
        self._drag_divider = divider_index
        self._drag_start_x = screen_x
        self._last_dx = 0
        def _w(pid: str) -> int:
            v = self.query_one(pid).styles.width.value
            return int(v) if isinstance(v, (int, float)) else 20
        self._start_widths = (_w("#pane-left"), _w("#pane-center"), _w("#pane-right"))
        for d in self.query(PaneDivider):
            d.add_class("dragging")
        self.capture_mouse()

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging:
            return
        dx = event.screen_x - self._drag_start_x
        if abs(dx - self._last_dx) < 3:
            return
        self._last_dx = dx
        MIN_W = 10
        left, center, right = self._start_widths

        if self._drag_divider == 0:
            left = max(MIN_W, left + dx)
            center = max(MIN_W, center - dx)
        else:
            center = max(MIN_W, center + dx)
            right = max(MIN_W, right - dx)

        self._set_pane_widths(left, center, right)

    def on_mouse_up(self, event: MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        for d in self.query(PaneDivider):
            d.remove_class("dragging")

    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+a" and not getattr(self, "_copy_mode", False):
            event.stop()
            self.action_toggle_archive()
            return
        if event.key == "ctrl+d" and not getattr(self, "_copy_mode", False):
            event.stop()
            self.app.switch_screen("board")
            return
        if event.key == "ctrl+c":
            event.stop()
            self.app.action_copy_selection()
            return
        if getattr(self, "_copy_mode", False) and event.key in {"ctrl+y", "escape"}:
            event.stop()
            self.action_toggle_copy_view()
        if event.key == "ctrl+f" and not getattr(self, "_copy_mode", False):
            event.stop()
            self._toggle_search()
            return
        if event.key == "escape" and self._search_mode:
            event.stop()
            self._exit_search()
            return
        if event.key == "escape" and self._completion_candidates:
            event.stop()
            self._dismiss_completions()
            return
        if event.key in ("tab", "enter") and self._completion_candidates:
            event.stop()
            self._apply_completion()
            return
        if event.key == "enter" and self._can_use_bootstrap_action_keys():
            event.stop()
            self._execute_selected_bootstrap_action()
            return
        if event.key in ("up", "down") and not getattr(self, "_copy_mode", False):
            inp = self.query_one("#message-input", Input)
            if inp.has_focus and self._completion_candidates:
                event.stop()
                self._completion_index += -1 if event.key == "up" else 1
                cl = self.query_one("#completion-list", ListView)
                n = len(self._completion_candidates)
                self._completion_index = max(0, min(self._completion_index, n - 1))
                cl.index = self._completion_index
                return
            if self._can_use_bootstrap_action_keys():
                event.stop()
                self._move_bootstrap_action_selection(-1 if event.key == "up" else 1)
                return
            if inp.has_focus and not self._completion_candidates:
                event.stop()
                conv_id = self.app.state.active_conversation_id
                if not conv_id:
                    return
                if event.key == "up":
                    val = self._input_history.navigate_up(conv_id)
                    if val:
                        inp.value = val
                    self._in_history_nav = True
                else:
                    val = self._input_history.navigate_down(conv_id)
                    inp.value = val
                    self._in_history_nav = bool(val)

    def on_mount(self) -> None:
        self._pane_left = self.query_one("#pane-left")
        self._pane_center = self.query_one("#pane-center")
        self._pane_right = self.query_one("#pane-right")
        self._copy_mode = False
        self.query_one("#copy-view", TextArea).display = False
        self._rendered_fingerprints: dict[str, str] = {}
        self._archive_mode = False
        self._slash_router = SlashCommandRouter()
        self._input_history = InputHistory()
        self._in_history_nav = False
        self._completion_engine = CompletionEngine()
        self._completion_candidates: list[CompletionCandidate] = []
        self._completion_index = -1
        self._drafts: dict[str, str] = {}
        self._send_status: dict[str, str] = {}  # conv_id -> "sending"|"sent"|"failed"|""
        self._input_mode = "normal"  # "normal"|"completion"|"copy"
        self._search_mode = False
        self._bootstrap_action_conv_id: str | None = None
        self._bootstrap_action_message_id: str | None = None
        self._bootstrap_actions: list[dict] = []
        self._bootstrap_action_index = 0
        self._selected_workbench_lane_id: str | None = None
        self._selected_workbench_inbox_id: str | None = None
        self.query_one("#search-input", Input).display = False
        self._load_conversations()
        self._distribute_widths(self.size.width)
        self.query_one("#message-input", Input).focus()
        self._maybe_start_terminal_demo()

    def _maybe_start_terminal_demo(self) -> None:
        conversation_id = os.environ.get("XMUSE_TUI_DEMO_CONVERSATION_ID", "").strip()
        terminal_run_id = os.environ.get("XMUSE_TUI_TERMINAL_RUN_ID", "").strip()
        if not conversation_id or not terminal_run_id:
            return
        asyncio.create_task(self._run_terminal_demo_commands(conversation_id))

    async def _run_terminal_demo_commands(self, conversation_id: str) -> None:
        await asyncio.sleep(1.0)
        context = SlashCommandContext(app=self.app, screen=self)
        for command in (
            f"/resume {conversation_id}",
            "/overview",
            "/discussion",
            "/blockers",
        ):
            result = self._slash_router.dispatch(command, context)
            if result.message:
                self._append_system_message(result.message)
            if result.refresh:
                self.app.action_refresh_now()
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)
        self.app.exit()

    def _load_conversations(self) -> None:
        convs = self._conversation_rows()
        lv = self.query_one("#pane-left", ListView)
        lv.clear()
        active_id = self.app.state.active_conversation_id
        selected_index = 0
        for conv in convs:
            cid = conv.get("conversation_id") or conv.get("id", "?")
            title = conv.get("title") or conv.get("name") or cid
            if active_id and cid == active_id:
                selected_index = len(lv.children)
            lv.append(ConvListItem(cid, title))
        if not self.app.state.active_conversation_id and convs:
            first = convs[0]
            cid = first.get("conversation_id") or first.get("id", "?")
            self._activate_conversation(str(cid))
        if convs:
            lv.index = selected_index

    def action_toggle_archive(self) -> None:
        self._archive_mode = not self._archive_mode
        self.app.state.active_conversation_id = None
        self._load_conversations()
        self.app.action_refresh_now()

    def _conversation_rows(self) -> list[dict]:
        rows = (
            self.app.adapter.list_archived_conversations()
            if getattr(self, "_archive_mode", False)
            else self.app.adapter.list_group_conversations()
        )
        return sorted(rows, key=lambda conv: str(conv.get("created_at", "")), reverse=True)

    @property
    def archive_mode(self) -> bool:
        return self._archive_mode

    @archive_mode.setter
    def archive_mode(self, value: bool) -> None:
        self._archive_mode = value

    def refresh_conversation_list(self) -> None:
        self._load_conversations()

    def activate_conversation(self, conv_id: str, *, refresh: bool = True) -> None:
        self._activate_conversation(conv_id, refresh=refresh)

    def conversation_title(self, conv_id: str) -> str:
        for conversation in self._conversation_rows():
            cid = conversation.get("conversation_id") or conversation.get("id")
            if str(cid) == conv_id:
                return str(conversation.get("title") or conversation.get("name") or conv_id)
        return conv_id

    def _toggle_search(self) -> None:
        self._search_mode = True
        self._input_mode = "search"
        inp = self.query_one("#message-input", Input)
        search_bar = self.query_one("#search-input", Input)
        inp.display = False
        search_bar.display = True
        search_bar.add_class("visible")
        search_bar.value = ""
        search_bar.focus()
        self._update_mode_status()

    def _exit_search(self) -> None:
        self._search_mode = False
        search_bar = self.query_one("#search-input", Input)
        search_bar.display = False
        search_bar.remove_class("visible")
        search_bar.value = ""
        inp = self.query_one("#message-input", Input)
        inp.display = True
        inp.focus()
        log = self.query_one("#message-log", MessageLog)
        log.clear_search()
        self._update_mode_status()

    def _dismiss_completions(self) -> None:
        self._completion_candidates = []
        self._completion_index = -1
        cl = self.query_one("#completion-list", ListView)
        cl.remove_class("visible")
        cl.clear()
        self._update_mode_status()

    def _apply_completion(self) -> None:
        if not self._completion_candidates:
            return
        idx = self._completion_index
        if idx < 0 or idx >= len(self._completion_candidates):
            if len(self._completion_candidates) == 1:
                idx = 0
            else:
                return
        candidate = self._completion_candidates[idx]
        inp = self.query_one("#message-input", Input)
        text = inp.value
        if candidate.type == "command":
            inp.value = candidate.value + " "
        elif candidate.type == "mention":
            at_pos = text.rfind(" @")
            if at_pos >= 0:
                inp.value = text[: at_pos + 2] + candidate.value[1:] + " "
            else:
                inp.value = candidate.value + " "
        inp.focus()
        self._dismiss_completions()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ConvListItem):
            self._activate_conversation(event.item.conv_id)
            return
        if isinstance(event.item, WorkbenchTaskItem):
            self._selected_workbench_lane_id = event.item.lane_id
            self._selected_workbench_inbox_id = None
            self._render_workbench_detail(
                conversation_id=self.app.state.active_conversation_id,
                lane=event.item.lane,
                inbox_item=None,
            )
            return
        if isinstance(event.item, WorkbenchInboxItem):
            self._selected_workbench_inbox_id = event.item.inbox_item_id
            self._render_workbench_detail(
                conversation_id=self.app.state.active_conversation_id,
                lane=None,
                inbox_item=event.item.inbox_item,
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._search_mode and event.input.id == "search-input":
            log = self.query_one("#message-log", MessageLog)
            log.search(event.value)
            return
        self._refresh_completions(event.value)

    def _refresh_completions(self, text: str) -> None:
        conv_id = self.app.state.active_conversation_id
        participants = self.app.state.participants_for(conv_id) if conv_id else []
        if not participants and conv_id:
            participants = self.app.adapter.get_participants(conv_id)
        cands = self._completion_engine.get_candidates(text, participants=participants)
        cl = self.query_one("#completion-list", ListView)
        if not cands:
            cl.remove_class("visible")
            cl.clear()
            self._completion_candidates = []
            self._completion_index = -1
            return
        cl.clear()
        for c in cands:
            if c.type == "command":
                cl.append(ListItem(Label(f"{c.display:<18} {c.description}")))
            else:
                cl.append(ListItem(Label(f"{c.display:<18} {c.description}")))
        self._completion_candidates = cands
        self._completion_index = -1
        cl.index = None
        cl.add_class("visible")
        self._update_mode_status()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._search_mode and event.input.id == "search-input":
            return
        content = event.value.strip()
        if not content:
            return
        conv_id = self.app.state.active_conversation_id or ""
        self._dismiss_completions()
        result = self._slash_router.dispatch(
            content,
            SlashCommandContext(app=self.app, screen=self),
        )
        if result.handled:
            if result.message:
                self._append_system_message(result.message)
            self.query_one("#message-input", Input).clear()
            if result.refresh:
                self.app.action_refresh_now()
            if conv_id:
                self._input_history.push_slash(conv_id, content)
            self._input_history.reset_position(conv_id)
            return
        self._send_status[conv_id] = "sending"
        msg_id = self.app.adapter.send_message(
            conv_id,
            author="user",
            role="user",
            content=content,
        )
        if msg_id:
            self._send_status[conv_id] = "sent"
            self._show_pending_peer_feedback(conv_id, content)
        else:
            self._send_status[conv_id] = "failed"
        self.query_one("#message-input", Input).clear()
        if conv_id:
            self._input_history.push_message(conv_id, content)
        self._input_history.reset_position(conv_id)
        self.app.action_refresh_now()

    def _show_pending_peer_feedback(self, conv_id: str, content: str) -> None:
        if not conv_id:
            return
        participants = self.app.state.participants_for(conv_id)
        if not participants:
            participants = self.app.adapter.get_participants(conv_id)
            self.app.state.participants[conv_id] = participants
        pending_messages = _pending_peer_messages(
            conv_id=conv_id,
            content=content,
            participants=participants,
        )
        if not pending_messages:
            return
        self.app.state.apply(StateDelta(messages=pending_messages))
        self.post_message(StateUpdated(self.app.state))

    def action_toggle_copy_view(self) -> None:
        self._copy_mode = not getattr(self, "_copy_mode", False)
        self._sync_copy_view()
        self.query_one("#message-log", MessageLog).display = not self._copy_mode
        copy_view = self.query_one("#copy-view", TextArea)
        copy_view.display = self._copy_mode
        if self._copy_mode:
            copy_view.focus()
        else:
            self.query_one("#message-input", Input).focus()

    def get_selected_text(self) -> str | None:
        if getattr(self, "_copy_mode", False):
            selected = self.query_one("#copy-view", TextArea).selected_text
            if selected:
                return selected
        return super().get_selected_text()

    def _sync_copy_view(self) -> None:
        conv_id = self.app.state.active_conversation_id
        if not conv_id:
            text = "No active conversation."
        else:
            text = _copyable_transcript(self.app.state, conv_id)
        self.query_one("#copy-view", TextArea).load_text(text)

    def get_copy_text_for_clipboard(self) -> str:
        if getattr(self, "_copy_mode", False):
            return self.query_one("#copy-view", TextArea).text
        conv_id = self.app.state.active_conversation_id
        if not conv_id:
            return ""
        return _copyable_transcript(self.app.state, conv_id)

    def _append_system_message(self, content: str) -> None:
        self.query_one("#message-log", MessageLog).append_message(
            author="xmuse",
            content=content,
            role="system",
        )

    def _show_current_thread(self) -> None:
        conv_id = self.app.state.active_conversation_id or "(none)"
        prefix = "Archive" if getattr(self, "_archive_mode", False) else "Current group"
        self.query_one("#message-log", MessageLog).append_message(
            author="xmuse",
            content=f"{prefix}: {conv_id}",
            role="system",
        )

    def _create_group_from_command(self, title: str) -> None:
        created = self.app.adapter.create_group_conversation(title)
        if not created:
            return
        conv_id = created.get("id") or created.get("conversation_id")
        if not conv_id:
            return
        self._archive_mode = False
        self._activate_conversation(str(conv_id), refresh=False)
        self._load_conversations()
        self.app.action_refresh_now()

    def _activate_conversation(self, conv_id: str, *, refresh: bool = True) -> None:
        previous = self.app.state.active_conversation_id
        inp = self.query_one("#message-input", Input)
        if previous and previous != conv_id:
            self._drafts[previous] = inp.value
        if self._search_mode:
            self._exit_search()
        self.app.state.active_conversation_id = conv_id
        self._input_history.reset_position(conv_id)
        self._dismiss_completions()
        self._clear_bootstrap_actions()
        draft = self._drafts.get(conv_id, "")
        inp.value = draft
        if previous != conv_id:
            self.query_one("#message-log", MessageLog).clear()
            self._copy_mode = False
            self.query_one("#message-log", MessageLog).display = True
            self.query_one("#copy-view", TextArea).display = False
            self._rendered_fingerprints.pop(conv_id, None)
        if refresh:
            self.app.action_refresh_now()

    def _update_mode_status(self) -> None:
        conv_id = self.app.state.active_conversation_id or ""
        parts: list[str] = []
        if self._search_mode:
            self._input_mode = "search"
        elif self._completion_candidates:
            self._input_mode = "completion"
        elif getattr(self, "_copy_mode", False):
            self._input_mode = "copy"
        else:
            self._input_mode = "normal"
        parts.append(f"[bold]{self._input_mode}[/bold]")
        status = self._send_status.get(conv_id, "")
        if status == "sending":
            parts.append("[yellow]sending...[/yellow]")
        elif status == "failed":
            parts.append("[red]send failed[/red]")
        elif status == "sent":
            parts.append("[green]sent[/green]")
        self.query_one("#mode-status", Static).update(" | ".join(parts))

    def on_state_updated(self, event: StateUpdated) -> None:
        self.query_one(XmuHeader).load(event.state)
        self._update_mode_status()
        state = event.state
        conv_id = state.active_conversation_id
        if not conv_id:
            return
        log = self.query_one("#message-log", MessageLog)
        msgs = state.messages_for(conv_id)
        cards = state.cards_for(conv_id)
        self._sync_bootstrap_actions(conv_id, msgs)
        fingerprint = _render_fingerprint(msgs, cards)
        if fingerprint != self._rendered_fingerprints.get(conv_id):
            log.clear()
            for msg in msgs:
                log.append_message(
                    author=msg.get("author", "?"),
                    display_author=_message_display_author(msg),
                    content=self._message_content_for_display(msg),
                    time_str=msg.get("created_at", ""),
                    role=msg.get("role", "system"),
                )
            for card in cards:
                log.append_card(card)
            self._rendered_fingerprints[conv_id] = fingerprint
        if getattr(self, "_copy_mode", False):
            self._sync_copy_view()
        self.query_one("#deliberation-cockpit", DeliberationCockpit).load(state.vision)
        self.query_one("#blueprint-freeze-panel", BlueprintFreezePanel).load(state.vision)
        self.query_one("#execution-cockpit", ExecutionCockpit).load(state.vision)
        self.query_one("#memory-trace-drawer", MemoryTraceDrawer).load(state.vision)
        self.query_one("#github-truth-panel", GitHubTruthPanel).load(state.vision)
        lanes = state.latest_lanes()
        self._refresh_workbench_lists(conv_id, lanes, cards)

    def _refresh_workbench_lists(
        self,
        conv_id: str,
        lanes: list[dict],
        cards: list[dict],
    ) -> None:
        task_list = self.query_one("#task-list", ListView)
        inbox_list = self.query_one("#inbox-list", ListView)
        selected_lane_id = self._selected_workbench_lane_id
        selected_inbox_id = self._selected_workbench_inbox_id

        task_list.clear()
        task_index = 0
        for lane in lanes:
            item = WorkbenchTaskItem(lane)
            if selected_lane_id and item.lane_id == selected_lane_id:
                task_index = len(task_list.children)
            task_list.append(item)
        if task_list.children:
            task_list.index = min(task_index, len(task_list.children) - 1)

        inbox_cards = _workbench_inbox_cards(cards)
        inbox_list.clear()
        inbox_index = 0
        for inbox_item in inbox_cards:
            item = WorkbenchInboxItem(inbox_item)
            if selected_inbox_id and item.inbox_item_id == selected_inbox_id:
                inbox_index = len(inbox_list.children)
            inbox_list.append(item)
        if inbox_list.children:
            inbox_list.index = min(inbox_index, len(inbox_list.children) - 1)

        lane = _selected_lane(lanes, selected_lane_id)
        inbox_item = _selected_inbox_item(inbox_cards, selected_inbox_id)
        if lane is None and lanes:
            lane = lanes[0]
            self._selected_workbench_lane_id = _lane_identifier(lane)
        if inbox_item is None and inbox_cards and lane is None:
            inbox_item = inbox_cards[0]
            self._selected_workbench_inbox_id = str(
                inbox_item.get("id") or inbox_item.get("message_id") or ""
            )
        self._render_workbench_detail(
            conversation_id=conv_id,
            lane=lane,
            inbox_item=inbox_item,
        )

    def _render_workbench_detail(
        self,
        *,
        conversation_id: str | None,
        lane: dict | None,
        inbox_item: dict | None,
    ) -> None:
        detail = self.query_one("#task-detail", WorkbenchDetailPanel)
        execution_log = self.query_one("#execution-log", WorkbenchDetailPanel)
        if lane is not None:
            lane_id = _lane_identifier(lane)
            lane_detail = self.app.adapter.get_workbench_lane_detail(
                conversation_id,
                lane_id,
            )
            lane_task = lane_detail.get("task") if isinstance(lane_detail, dict) else None
            detail.update(_format_lane_detail(lane_task or lane))
            execution_log.update(_format_execution_log(lane_detail))
            return
        if inbox_item is not None:
            detail.update(_format_inbox_detail(inbox_item))
            execution_log.update(_format_inbox_execution_context(inbox_item))
            return
        detail.update("[dim]No active task or inbox item[/dim]")
        execution_log.update("[dim]No execution evidence[/dim]")

    def _sync_bootstrap_actions(self, conv_id: str, messages: list[dict]) -> None:
        message = _latest_bootstrap_guidance_message(messages)
        if message is None:
            self._clear_bootstrap_actions()
            return
        actions = _bootstrap_actions(message)
        if not actions:
            self._clear_bootstrap_actions()
            return
        message_id = str(message.get("id") or "")
        if (
            self._bootstrap_action_conv_id != conv_id
            or self._bootstrap_action_message_id != message_id
        ):
            self._bootstrap_action_index = 0
        self._bootstrap_action_conv_id = conv_id
        self._bootstrap_action_message_id = message_id
        self._bootstrap_actions = actions
        self._bootstrap_action_index = max(
            0,
            min(self._bootstrap_action_index, len(self._bootstrap_actions) - 1),
        )

    def _clear_bootstrap_actions(self) -> None:
        self._bootstrap_action_conv_id = None
        self._bootstrap_action_message_id = None
        self._bootstrap_actions = []
        self._bootstrap_action_index = 0

    def _message_content_for_display(self, message: dict) -> str:
        content = str(message.get("content") or "")
        if not self._is_active_bootstrap_guidance_message(message):
            return content
        lines = [content, "", "Initialization actions:"]
        for index, action in enumerate(self._bootstrap_actions):
            marker = "\u25b6" if index == self._bootstrap_action_index else " "
            label = str(action.get("label") or action.get("id") or "Action").strip()
            lines.append(f"{marker} {label}")
        return "\n".join(lines)

    def _is_active_bootstrap_guidance_message(self, message: dict) -> bool:
        if str(message.get("envelope_type") or "") != "bootstrap_guidance":
            return False
        message_id = str(message.get("id") or "")
        return bool(
            self._bootstrap_actions
            and self._bootstrap_action_message_id
            and message_id == self._bootstrap_action_message_id
        )

    def _can_use_bootstrap_action_keys(self) -> bool:
        if not self._bootstrap_actions:
            return False
        if getattr(self, "_copy_mode", False) or self._search_mode:
            return False
        inp = self.query_one("#message-input", Input)
        return bool(inp.has_focus and not inp.value.strip())

    def _move_bootstrap_action_selection(self, delta: int) -> None:
        if not self._bootstrap_actions:
            return
        self._bootstrap_action_index = max(
            0,
            min(self._bootstrap_action_index + delta, len(self._bootstrap_actions) - 1),
        )
        conv_id = self.app.state.active_conversation_id
        if conv_id:
            self._rendered_fingerprints.pop(conv_id, None)
            self.post_message(StateUpdated(self.app.state))

    def _execute_selected_bootstrap_action(self) -> None:
        if not self._bootstrap_actions:
            return
        action = self._bootstrap_actions[self._bootstrap_action_index]
        command = str(action.get("command") or "").strip()
        if not command:
            return
        conv_id = self.app.state.active_conversation_id or ""
        result = self._slash_router.dispatch(
            command,
            SlashCommandContext(app=self.app, screen=self),
        )
        if result.message:
            self._append_system_message(result.message)
        if result.refresh:
            self.app.action_refresh_now()
        if conv_id:
            self._input_history.push_slash(conv_id, command)
            self._input_history.reset_position(conv_id)

    def on_resize(self, event: Resize) -> None:
        self.query_one("#pane-right").display = event.size.width >= 80
        self._distribute_widths(event.size.width)

    def _format_lane_lines(self, lanes: list[dict]) -> str:
        if not lanes:
            return ""
        lines = ["Lanes"]
        for lane in lanes:
            status = (
                lane.get("effective_status")
                or lane.get("status")
                or "?"
            )
            lane_id = (
                lane.get("lane_local_id")
                or lane.get("plan_feature_id")
                or lane.get("feature_id")
                or lane.get("lane_id")
                or "?"
            )
            title = (
                lane.get("feature_label")
                or lane.get("title")
                or lane.get("prompt_summary")
                or lane.get("lane_id")
                or lane_id
            )
            lines.append(f"{status:<9} {lane_id} {title}")
        return "\n".join(lines)


def _copyable_transcript(state, conv_id: str) -> str:
    lines: list[str] = []
    for msg in state.messages_for(conv_id):
        author = _message_display_author(msg)
        content = str(msg.get("content") or "")
        created_at = str(msg.get("created_at") or "")
        prefix = f"[{created_at}] " if created_at else ""
        lines.append(f"{prefix}{author}: {content}".strip())
    for card in state.cards_for(conv_id):
        card_type = str(card.get("card_type") or "card")
        title = str(card.get("title") or card_type)
        summary = str(card.get("summary") or "")
        status = str(card.get("status") or "")
        detail = f" - {summary}" if summary else ""
        suffix = f" ({status})" if status else ""
        lines.append(f"[{card_type}] {title}{suffix}{detail}")
    return "\n\n".join(lines) if lines else "No messages in this conversation."


def _lane_identifier(lane: dict) -> str:
    return str(
        lane.get("lane_id")
        or lane.get("feature_id")
        or lane.get("lane_local_id")
        or lane.get("plan_feature_id")
        or "?"
    )


def _selected_lane(lanes: list[dict], lane_id: str | None) -> dict | None:
    if lane_id is None:
        return None
    for lane in lanes:
        if _lane_identifier(lane) == lane_id or str(lane.get("lane_local_id") or "") == lane_id:
            return lane
    return None


def _workbench_inbox_cards(cards: list[dict]) -> list[dict]:
    inbox_types = {
        "peer_route_status",
        "peer_pending",
        "runtime_discussion",
        "runtime_blocker",
        "runtime_dispatch_gate",
        "runtime_dispatch_queue",
        "runtime_provider_writeback",
    }
    return [
        card
        for card in cards
        if isinstance(card, dict) and str(card.get("card_type") or "") in inbox_types
    ]


def _selected_inbox_item(items: list[dict], item_id: str | None) -> dict | None:
    if item_id is None:
        return None
    for item in items:
        if str(item.get("id") or item.get("message_id") or "") == item_id:
            return item
    return None


def _format_lane_detail(detail: dict | None) -> str:
    if not isinstance(detail, dict):
        return "[dim]No task detail[/dim]"
    lane_id = str(detail.get("lane_id") or detail.get("feature_id") or "?")
    lane_local_id = str(detail.get("lane_local_id") or lane_id)
    title = str(detail.get("feature_label") or detail.get("title") or lane_id)
    status = str(detail.get("effective_status") or detail.get("status") or "?")
    lines = [
        f"{title}",
        f"lane: {lane_id}",
        f"local: {lane_local_id}",
        f"status: {status}",
        f"feature: {detail.get('plan_feature_id') or '?'}",
        f"source: {detail.get('source_authority') or 'state'}",
    ]
    if detail.get("priority") is not None:
        lines.append(f"priority: {detail.get('priority')}")
    dependencies = _text_items(
        detail.get("scoped_dependency_ids")
        or detail.get("lane_depends_on_ids")
        or detail.get("depends_on")
    )
    gate_predecessors = _text_items(
        detail.get("gate_predecessors")
        or detail.get("gate_predecessor_ids")
        or detail.get("predecessor_gate_ids")
    )
    touched_areas = _text_items(detail.get("touched_areas") or detail.get("touched_paths"))
    source_refs = _text_items(detail.get("source_refs") or detail.get("blueprint_refs"))
    merge_blockers = _text_items(
        detail.get("merge_blockers")
        or detail.get("merge_blockage")
        or detail.get("merge_blockage_reasons")
    )
    if dependencies:
        lines.append(f"depends_on: {', '.join(dependencies)}")
    if gate_predecessors:
        lines.append(f"gate_predecessors: {', '.join(gate_predecessors)}")
    if touched_areas:
        lines.append(f"touched_areas: {', '.join(touched_areas)}")
    if source_refs:
        lines.append(f"source_refs: {', '.join(source_refs)}")
    if merge_blockers:
        lines.append(f"merge_blockers: {', '.join(merge_blockers)}")
    prompt_summary = str(detail.get("prompt_summary") or "").strip()
    if prompt_summary:
        lines.extend(["", "prompt:", prompt_summary])
    debug_refs = detail.get("debug_refs")
    if isinstance(debug_refs, dict):
        lane_ref = debug_refs.get("lane") if isinstance(debug_refs.get("lane"), dict) else None
        href = lane_ref.get("api_href") if isinstance(lane_ref, dict) else None
        if href:
            lines.extend(["", f"detail: {href}"])
    return "\n".join(lines)


def _format_execution_log(detail: dict | None) -> str:
    if not isinstance(detail, dict):
        return "[dim]No execution evidence[/dim]"
    lines = detail.get("execution_log")
    if isinstance(lines, list) and lines:
        return "\n".join(str(line) for line in lines)
    if isinstance(lines, dict) and isinstance(lines.get("events"), list):
        rendered = []
        for event in lines["events"]:
            if not isinstance(event, dict):
                continue
            summary = str(event.get("summary") or "").strip()
            title = str(event.get("title") or event.get("event_type") or "").strip()
            status = str(event.get("status") or "").strip()
            rendered.append(" ".join(part for part in (title, status, summary) if part))
        if rendered:
            return "\n".join(rendered)
    return "[dim]No execution evidence[/dim]"


def _format_inbox_detail(item: dict) -> str:
    title = str(item.get("title") or item.get("summary") or item.get("id") or "Inbox item")
    status = str(item.get("status") or item.get("card_type") or "?")
    source = str(item.get("source_id") or item.get("id") or "?")
    summary = str(item.get("summary") or item.get("content") or "").strip()
    lines = [title, f"status: {status}", f"source: {source}"]
    if summary:
        lines.extend(["", summary])
    href = str(item.get("api_href") or item.get("href") or "").strip()
    if href:
        lines.extend(["", f"detail: {href}"])
    return "\n".join(lines)


def _format_inbox_execution_context(item: dict) -> str:
    lines = [
        f"inbox/card: {item.get('id') or item.get('source_id') or '?'}",
        f"type: {item.get('card_type') or '?'}",
    ]
    for key in ("source_id", "intent_id", "api_href", "href"):
        value = str(item.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _text_items(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _message_display_author(message: dict) -> str:
    return str(message.get("display_author") or message.get("author") or "?")


def _latest_bootstrap_guidance_message(messages: list[dict]) -> dict | None:
    for message in reversed(messages):
        if str(message.get("envelope_type") or "") == "bootstrap_guidance":
            return message
    return None


def _bootstrap_actions(message: dict) -> list[dict]:
    envelope = message.get("envelope_json")
    if not isinstance(envelope, dict):
        return []
    actions = envelope.get("actions")
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict) and str(action.get("command") or "").strip()
    ]


def _pending_peer_messages(
    *,
    conv_id: str,
    content: str,
    participants: list[dict],
) -> list[dict]:
    mentioned_roles = _mentioned_roles(content)
    if not mentioned_roles:
        return []
    messages: list[dict] = []
    for participant in participants:
        role = str(participant.get("role") or "").strip()
        if not role or role.lower() not in mentioned_roles:
            continue
        participant_id = str(participant.get("participant_id") or participant.get("id") or role)
        display_name = str(participant.get("display_name") or role)
        messages.append(
            {
                "id": f"peer_pending_{conv_id}_{participant_id}",
                "conversation_id": conv_id,
                "author": participant_id,
                "display_author": display_name,
                "role": "assistant",
                "content": f"{display_name} ...",
                "envelope_type": "peer_pending",
                "envelope_json": {
                    "type": "peer_pending",
                    "target_role": role,
                    "target_participant_id": participant_id,
                },
                "mentions": [],
                "reply_to_message_id": None,
            }
        )
    return messages


def _mentioned_roles(content: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in re.finditer(r"@([A-Za-z][A-Za-z0-9_-]*)", content)
    }


def _participant_status_symbol(status: str) -> str:
    if status == "active":
        return "●"
    if status == "stopped":
        return "◆"
    return "○"


def _format_participant_panel(
    *,
    title: str,
    conv_id: str,
    participants: list[dict],
) -> str:
    lines = [f"{title}", conv_id]
    if not participants:
        lines.append("No GOD participants")
        return "\n".join(lines)
    for participant in participants:
        role = str(participant.get("role") or "?")
        name = str(participant.get("display_name") or participant.get("participant_id") or "?")
        model = str(participant.get("model") or "?")
        status = str(participant.get("status") or "?")
        symbol = _participant_status_symbol(status)
        lines.append(f"{symbol} {role}: {name} [{status}] {model}")
    return "\n".join(lines)


def _render_fingerprint(messages: list[dict], cards: list[dict]) -> str:
    return json.dumps(
        {"messages": messages, "cards": cards},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
