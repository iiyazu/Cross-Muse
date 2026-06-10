# xmuse Textual TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Textual TUI for xmuse that provides IM chat, feature board, and drill-down detail screens by directly importing xmuse_core modules.

**Architecture:** A standalone `xmuse/tui/` package with an `adapter/xmuse_adapter.py` as the sole interface to `xmuse_core`. App-level single-timer polling distributes `StateDelta` to visible screens. Three-layer navigation: ChatScreen → FeatureBoardScreen → DetailScreens.

**Tech Stack:** Python 3.12, Textual 1.x, Rich, xmuse_core (existing), uv run, pytest

**Implementation notes:**
- xmuse_core models are Pydantic BaseModel instances, not plain dicts. The adapter calls `.model_dump(mode="json")` to convert before returning.
- Timestamps are ISO 8601 strings. Polling uses string comparison (ISO strings sort lexicographically by value).
- `LaneProjectionSyncer.read()` acquires a file lock. The adapter wraps it in `asyncio.to_thread()` to avoid blocking the event loop.
- xmuse_core stores are file-based and may not exist yet when the TUI starts. All adapter methods use try/except and return empty defaults on failure.

---

## File Structure

```
xmuse/tui/
├── __init__.py
├── __main__.py
├── app.py
├── adapter/
│   ├── __init__.py
│   └── xmuse_adapter.py
├── screens/
│   ├── __init__.py
│   ├── chat_screen.py
│   ├── feature_board.py
│   ├── feature_detail.py
│   ├── lane_detail.py
│   ├── planning_run.py
│   ├── provider_board.py
│   └── system_screen.py
├── widgets/
│   ├── __init__.py
│   ├── message_log.py
│   ├── card_renderer.py
│   ├── feature_row.py
│   ├── dag_tree.py
│   ├── health_panel.py
│   └── state_indicator.py
└── style/
    └── theme.tcss
```

```
tests/
├── test_xmuse_tui_adapter.py
├── test_xmuse_tui_widgets.py
└── test_xmuse_tui_navigation.py
```

---

### Task 0: Install textual dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add textual to project dependencies**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv add textual`

Expected output: `Resolved ... packages` with textual and its dependencies.

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add textual dependency for TUI"
```

---

### Task 1: Project scaffold and adapter skeleton

**Files:**
- Create: `xmuse/tui/__init__.py`
- Create: `xmuse/tui/adapter/__init__.py`
- Create: `xmuse/tui/screens/__init__.py`
- Create: `xmuse/tui/widgets/__init__.py`
- Create: `xmuse/tui/adapter/xmuse_adapter.py`

- [ ] **Step 1: Create empty init files**

```python
# xmuse/tui/__init__.py
"""xmuse Textual TUI — standalone IM + dashboard client."""
```

```python
# xmuse/tui/adapter/__init__.py
```

```python
# xmuse/tui/screens/__init__.py
```

```python
# xmuse/tui/widgets/__init__.py
```

- [ ] **Step 2: Write xmuse_adapter.py skeleton**

```python
# xmuse/tui/adapter/xmuse_adapter.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StateDelta:
    messages: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    lanes: list[dict] = field(default_factory=list)
    run_health: dict | None = None
    lanes_changed: bool = False
    errors: dict[str, str] = field(default_factory=dict)


class XmuseAdapter:
    """Sole bridge between TUI and xmuse_core stores.
    All methods return plain dicts/lists. No xmuse_core types leak to TUI.
    All xmuse_core calls are wrapped in try/except for graceful degradation.
    """

    def __init__(self, xmuse_root: Path) -> None:
        self._root = xmuse_root

    def poll_messages(self, conv_id: str) -> tuple[list[dict], str | None]:
        return [], None

    def poll_projection(self) -> tuple[dict | None, str | None]:
        return None, None

    def poll_cards(self, conv_id: str) -> tuple[list[dict], str | None]:
        return [], None

    def poll_delta(self, conv_id: str | None = None) -> StateDelta:
        return StateDelta()

    def sync(self, conv_id: str | None = None) -> StateDelta:
        return self.poll_delta(conv_id)

    def send_message(self, conv_id: str, author: str, role: str, content: str) -> str | None:
        return None

    def list_conversations(self) -> list[dict]:
        return []

    def get_participants(self, conv_id: str) -> list[dict]:
        return []

    def get_lane(self, lane_id: str) -> dict | None:
        return None

    def get_feature_graph(self, graph_id: str) -> dict | None:
        return None

    def get_planning_run(self, run_id: str) -> dict | None:
        return None

    def get_provider_inventory(self) -> list[dict]:
        return []
```

Key differences from Task 0:
- `send_message` has 4 params (added `role`)—matches `ChatStore.add_message(conv_id, author, role, content)`
- No `get_messages`, `get_card_intents`, `list_proposals`—these are covered by `poll_delta` or removed (wrong API signatures)
- `get_planning_run` and `get_provider_inventory` remain as stubs—wired in a follow-up task when their store APIs stabilize

- [ ] **Step 3: Verify imports**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run python -c "from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter, StateDelta; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add xmuse/tui/ tests/xmuse/test_tui_adapter.py
git commit -m "feat(tui): scaffold adapter with skeleton"
```

---

### Task 2: App entry point and main loop

**Files:**
- Create: `xmuse/tui/__main__.py`
- Create: `xmuse/tui/app.py`

- [ ] **Step 1: Write __main__.py**

```python
# xmuse/tui/__main__.py
"""Entry point: uv run python -m xmuse.tui"""
from __future__ import annotations

from pathlib import Path

from xmuse.tui.app import XmuseTUI


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    app = XmuseTUI(xmuse_root=root)
    app.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write app.py with timer and state**

```python
# xmuse/tui/app.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.screen import Screen

from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter, StateDelta
from xmuse.tui.screens.chat_screen import ChatScreen
from xmuse.tui.screens.feature_board import FeatureBoardScreen


@dataclass
class AppState:
    active_conversation_id: str | None = None
    conversations: list[dict] = field(default_factory=list)
    messages: dict[str, list[dict]] = field(default_factory=dict)
    cards: dict[str, list[dict]] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    lanes: list[dict] = field(default_factory=list)
    run_health: dict | None = None
    lanes_changed: bool = False
    consecutive_error_ticks: int = 0
    has_errors: bool = False

    def apply(self, delta: StateDelta) -> None:
        self.consecutive_error_ticks = self.consecutive_error_ticks + 1 if delta.errors else 0
        self.has_errors = bool(delta.errors)
        if delta.lanes:
            self.lanes = delta.lanes
        if delta.features:
            self.features = delta.features
        if delta.run_health is not None:
            self.run_health = delta.run_health
        self.lanes_changed = delta.lanes_changed

    def features_for(self, conv_id: str) -> dict[str, Any]:
        return self.features

    def messages_for(self, conv_id: str) -> list[dict]:
        return self.messages.get(conv_id, [])

    def cards_for(self, conv_id: str) -> list[dict]:
        return self.cards.get(conv_id, [])

    def all_features(self) -> dict[str, Any]:
        return self.features

    def latest_lanes(self) -> list[dict]:
        return self.lanes


class StateUpdated(Message):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state


class XmuseTUI(App):
    CSS_PATH = "style/theme.tcss"

    BINDINGS = [
        Binding("ctrl+d", "switch_screen('board')", "Feature Board"),
        Binding("ctrl+1", "switch_screen('chat')", "Chat"),
        Binding("ctrl+r", "refresh_now", "Refresh"),
        Binding("escape", "pop_screen", "Back"),
    ]

    SCREENS = {
        "chat": ChatScreen(),
        "board": FeatureBoardScreen(),
    }

    def __init__(self, xmuse_root: Path) -> None:
        super().__init__()
        self.adapter = XmuseAdapter(xmuse_root)
        self.state = AppState()

    def on_mount(self) -> None:
        self.push_screen("chat")
        self.set_interval(5, self._tick)

    async def _tick(self) -> None:
        conv_id = self.state.active_conversation_id
        if self.state.consecutive_error_ticks >= 3:
            delta = await self.adapter.sync(conv_id)
        else:
            delta = await self.adapter.poll_delta(conv_id)
        self.state.apply(delta)
        if self.screen_stack:
            self.post_message(StateUpdated(self.state))

    def action_refresh_now(self) -> None:
        asyncio.create_task(self._tick())

    def action_pop_screen(self) -> None:
        if len(self.screen_stack) > 1:
            super().pop_screen()
```

- [ ] **Step 3: Create theme CSS**

```css
/* xmuse/tui/style/theme.tcss */
Screen {
    background: $surface;
}

RichLog {
    background: $surface;
    border: solid $primary;
}

Input {
    dock: bottom;
}

DataTable {
    height: 100%;
}
```

- [ ] **Step 4: Verify app starts**

Run: `cd /home/iiyatu/projects/python/memoryOS && timeout 3 uv run python -m xmuse.tui 2>&1 || true`
Expected: Textual initializes cleanly. No import errors.

- [ ] **Step 5: Commit**

```bash
git add xmuse/tui/__main__.py xmuse/tui/app.py xmuse/tui/style/
git commit -m "feat(tui): add app entry point and main loop"
```

---

### Task 3: Adapter real implementation

**Files:**
- Modify: `xmuse/tui/adapter/xmuse_adapter.py`

This task fleshes out the adapter with real xmuse_core calls.

**Critical xmuse_core facts:**
- `ChatStore.list_messages(conv_id)` returns `list[ChatMessage]` (Pydantic BaseModel)—call `.model_dump(mode="json")` on each
- `ChatMessage.created_at` is ISO 8601 string (e.g. `2026-05-31T12:00:00Z`)—string comparison works because ISO strings sort lexicographically
- `ChatExecutionCardEmitter(root)` expects root as the xmuse directory, not `chat.db`—it resolves `read_models/execution_card_intents.json` internally
- `LaneProjectionSyncer.read()` acquires `fcntl.LOCK_EX`—wrap in `asyncio.to_thread()` to avoid blocking the asyncio event loop

- [ ] **Step 1: Replace __init__ and polling cursors**

```python
# Add to imports at top of adapter/xmuse_adapter.py:
import asyncio

def __init__(self, xmuse_root: Path) -> None:
    self._root = xmuse_root
```

- [ ] **Step 2: Write poll_messages**

```python
def poll_messages(self, conv_id: str) -> tuple[list[dict], str | None]:
    try:
        from xmuse_core.chat.store import ChatStore
        store = ChatStore(self._root / "chat.db")
        raw = store.list_messages(conv_id)
        dicts = [m.model_dump(mode="json") for m in raw if hasattr(m, "model_dump")]
        since = self._last_message_ts.get(conv_id, "")
        new = [m for m in dicts if str(m.get("created_at", "")) > since]
        if new:
            self._last_message_ts[conv_id] = max(str(m.get("created_at", "")) for m in new)
        return new, None
    except Exception as exc:
        return [], str(exc)
```

- [ ] **Step 3: Write poll_projection**

```python
async def poll_projection(self) -> tuple[dict | None, str | None]:
    try:
        from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
        syncer = LaneProjectionSyncer(self._root / "feature_lanes.json")
        # read() acquires flock(LOCK_EX) — run in thread to avoid blocking event loop
        data = await asyncio.to_thread(syncer.read)
        rev = data.get("projection_revision")
        if rev is not None and rev == self._last_projection_revision:
            return None, None
        self._last_projection_revision = rev
        return data, None
    except Exception as exc:
        return None, str(exc)
```

Make the corresponding method async and update `poll_delta`/`sync` to be async too.

- [ ] **Step 4: Write poll_cards**

```python
def poll_cards(self, conv_id: str) -> tuple[list[dict], str | None]:
    try:
        from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
        # emitter root = xmuse root, NOT chat.db path
        emitter = ChatExecutionCardEmitter(self._root)
        raw = emitter.list_intents(conversation_id=conv_id)
        dicts = [c.model_dump(mode="json") for c in raw if hasattr(c, "model_dump")]
        since = self._last_card_ts.get(conv_id, "")
        new = [c for c in dicts if str(c.get("created_at", "")) > since]
        if new:
            self._last_card_ts[conv_id] = max(str(c.get("created_at", "")) for c in new)
        return new, None
    except Exception as exc:
        return [], str(exc)
```

- [ ] **Step 5: Write poll_delta assembly, _filter_by_conv, _build_features, _build_health**

```python
async def poll_delta(self, conv_id: str | None = None) -> StateDelta:
    msgs, msg_err = self.poll_messages(conv_id) if conv_id else ([], None)
    proj, proj_err = await self.poll_projection()
    cards, card_err = self.poll_cards(conv_id) if conv_id else ([], None)
    errors = {k: v for k, v in {"messages": msg_err, "projection": proj_err, "cards": card_err}.items() if v}
    features = {}
    lanes_list = []
    health = None
    if proj is not None:
        all_lanes = proj.get("lanes", [])
        if conv_id:
            all_lanes = [l for l in all_lanes if l.get("conversation_id") == conv_id]
        features = _build_features(all_lanes)
        lanes_list = _extract_lanes(all_lanes)
        health = _build_health(all_lanes)
    return StateDelta(
        messages=msgs, cards=cards, features=features, lanes=lanes_list,
        run_health=health, lanes_changed=proj is not None, errors=errors,
    )

async def sync(self, conv_id: str | None = None) -> StateDelta:
    self._last_message_ts.clear()
    self._last_card_ts.clear()
    self._last_projection_revision = None
    return await self.poll_delta(conv_id)


def _build_features(lanes: list[dict]) -> dict[str, Any]:
    features: dict[str, dict] = {}
    for lane in lanes:
        fid = lane.get("feature_plan_feature_id") or lane.get("feature_group") or "?"
        if fid not in features:
            features[fid] = {"feature_id": fid, "total": 0, "merged": 0, "lanes": []}
        features[fid]["total"] += 1
        if lane.get("status") == "merged":
            features[fid]["merged"] += 1
        features[fid]["lanes"].append(lane)
    return features


def _extract_lanes(lanes: list[dict]) -> list[dict]:
    return lanes


def _build_health(lanes: list[dict]) -> dict:
    live = sum(1 for l in lanes if l.get("status") in {"dispatched", "gated", "executed", "reworking"})
    merged = sum(1 for l in lanes if l.get("status") == "merged")
    failed = sum(1 for l in lanes if l.get("status") in {"failed", "exec_failed", "gate_failed"})
    return {"live": live, "merged": merged, "failed": failed, "total": len(lanes)}
```

- [ ] **Step 6: Write list_conversations**

```python
def list_conversations(self) -> list[dict]:
    try:
        from xmuse_core.chat.store import ChatStore
        store = ChatStore(self._root / "chat.db")
        raw = store.list_conversations()
        return [c.model_dump(mode="json") for c in raw if hasattr(c, "model_dump")]
    except Exception:
        return []
```

- [ ] **Step 7: Write get_lane, get_feature_graph, get_participants**

```python
def get_lane(self, lane_id: str) -> dict | None:
    try:
        from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
        syncer = LaneProjectionSyncer(self._root / "feature_lanes.json")
        data = syncer.read()
        for lane in data.get("lanes", []):
            if lane.get("feature_id") == lane_id:
                return lane
        return None
    except Exception:
        return None

def get_feature_graph(self, graph_id: str) -> dict | None:
    try:
        from xmuse_core.structuring.graph_store import LaneGraphStore
        store = LaneGraphStore(self._root / "lane_graphs")
        graph = store.get(graph_id)
        return graph.model_dump(mode="json")
    except Exception:
        return None

def get_participants(self, conv_id: str) -> list[dict]:
    try:
        from xmuse_core.chat.participant_store import ParticipantStore
        store = ParticipantStore(self._root / "chat.db")
        parts = store.list_by_conversation(conv_id)
        return [p.model_dump() for p in parts]
    except Exception:
        return []
```

- [ ] **Step 8: Write send_message**

```python
def send_message(self, conv_id: str, author: str, role: str, content: str) -> str | None:
    try:
        from xmuse_core.chat.store import ChatStore
        store = ChatStore(self._root / "chat.db")
        return store.add_message(conv_id, author, role, content)
    except Exception:
        return None
```

- [ ] **Step 9: Write adapter test with fixture data**

```python
# tests/xmuse/test_tui_adapter.py
"""Tests for XmuseAdapter using fixture data."""
from pathlib import Path
from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter, _build_features, _build_health

ROOT = Path(__file__).resolve().parent.parent / "xmuse"


def test_build_features_empty():
    assert _build_features([]) == {}


def test_build_features_single():
    lanes = [{"feature_plan_feature_id": "C1", "status": "merged"}]
    result = _build_features(lanes)
    assert result["C1"]["total"] == 1
    assert result["C1"]["merged"] == 1


def test_build_health_empty():
    h = _build_health([])
    assert h == {"live": 0, "merged": 0, "failed": 0, "total": 0}


def test_build_health_counts():
    lanes = [
        {"status": "merged"},
        {"status": "dispatched"},
        {"status": "failed"},
        {"status": "gated"},
    ]
    h = _build_health(lanes)
    assert h["live"] == 2
    assert h["merged"] == 1
    assert h["failed"] == 1
    assert h["total"] == 4


async def test_adapter_poll_returns_delta():
    adapter = XmuseAdapter(ROOT)
    delta = await adapter.poll_delta(conv_id=None)
    assert delta is not None
    assert isinstance(delta.lanes, list)

def test_adapter_missing_keys():
    lanes = [{"feature_group": "C1"}, {"status": "merged"}, {}]
    result = _build_features(lanes)
    assert "?" in result or "C1" in result

def test_adapter_null_status():
    lanes = [{"status": "merged"}, {"status": None}, {}, {"status": "dispatched"}]
    h = _build_health(lanes)
    assert h["merged"] == 1
    assert h["live"] == 1
    assert h["total"] == 4
```

- [ ] **Step 10: Run tests**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_adapter.py -q`
Expected: 5 passed

- [ ] **Step 11: Commit**

```bash
git add xmuse/tui/adapter/xmuse_adapter.py tests/xmuse/test_tui_adapter.py
git commit -m "feat(tui): implement adapter with real xmuse_core polling"
```

---

### Task 4: ChatScreen — IM conversation list

**Files:**
- Create: `xmuse/tui/screens/chat_screen.py`

- [ ] **Step 1: Write ChatScreen with three-column layout**

```python
# xmuse/tui/screens/chat_screen.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Input, ListView, ListItem, Label

from xmuse.tui.app import StateUpdated
from xmuse.tui.widgets.message_log import MessageLog


class ConvListItem(ListItem):
    def __init__(self, conv_id: str, title: str) -> None:
        super().__init__(Label(f"{title}"))
        self.conv_id = conv_id


class WorklistSummary(Label):
    pass


class ChatScreen(Screen):
    CSS = """
    #chat-horizontal {
        height: 100%;
    }
    #conv-list {
        width: 25%;
        height: 100%;
        border: solid $primary;
    }
    #chat-center {
        width: 50%;
        height: 100%;
    }
    #worklist-panel {
        width: 25%;
        height: 100%;
        border: solid $primary;
    }
    #message-input {
        dock: bottom;
        margin: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-horizontal"):
            yield ListView(id="conv-list")
            with Vertical(id="chat-center"):
                yield MessageLog(id="message-log")
                yield Input(id="message-input", placeholder="Type a message...")
            with Vertical(id="worklist-panel"):
                yield Label("Worklist", classes="panel-header")
                yield WorklistSummary(id="worklist-summary")

    def on_mount(self) -> None:
        self._load_conversations()

    def _load_conversations(self) -> None:
        convs = self.app.adapter.list_conversations()
        lv = self.query_one("#conv-list", ListView)
        lv.clear()
        for conv in convs:
            cid = conv.get("conversation_id") or conv.get("id", "?")
            title = conv.get("title") or conv.get("name") or cid
            lv.append(ConvListItem(cid, title))
        if not self.app.state.active_conversation_id and convs:
            first = convs[0]
            cid = first.get("conversation_id") or first.get("id", "?")
            self.app.state.active_conversation_id = cid

    def on_listview_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ConvListItem):
            self.app.state.active_conversation_id = event.item.conv_id

    def on_input_submitted(self, event: Input.Submitted) -> None:
        content = event.value.strip()
        if not content:
            return
        self.app.adapter.send_message(
            self.app.state.active_conversation_id or "",
            author="user",
            role="user",
            content=content,
        )
        self.query_one("#message-input", Input).clear()

    def on_state_updated(self, event: StateUpdated) -> None:
        state = event.state
        conv_id = state.active_conversation_id
        if not conv_id:
            return
        log = self.query_one("#message-log", MessageLog)
        for msg in state.messages_for(conv_id):
            log.append_message(
                author=msg.get("author", "?"),
                content=msg.get("content", ""),
                time_str=msg.get("created_at", ""),
            )
        for card in state.cards_for(conv_id):
            log.append_card(card)
        features = state.features_for(conv_id)
        worklist_text = "\n".join(
            f"{fid}: {ft.get('merged', 0)}/{ft.get('total', 0)}"
            for fid, ft in sorted(features.items())
        ) or "[dim]No features[/dim]"
        self.query_one("#worklist-summary").update(worklist_text)
```

Note: `send_message` now passes 4 args (conv_id, author, role, content) to match `ChatStore.add_message()`.

- [ ] **Step 2: Commit**

```bash
git add xmuse/tui/screens/chat_screen.py
git commit -m "feat(tui): add chat screen with three-column layout"
```

---

### Task 5: MessageLog widget and card renderer

**Files:**
- Create: `xmuse/tui/widgets/message_log.py`
- Create: `xmuse/tui/widgets/card_renderer.py`
- Create: `xmuse/tui/widgets/state_indicator.py`

- [ ] **Step 1: Write MessageLog**

```python
# xmuse/tui/widgets/message_log.py
from __future__ import annotations

from rich.panel import Panel
from rich.text import Text
from textual.widgets import RichLog


class MessageLog(RichLog):
    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, max_lines=2000, **kwargs)
        self._at_bottom = True
        self._pending_count = 0

    def on_mount(self) -> None:
        self._at_bottom = True

    def append_message(self, author: str, content: str, time_str: str = "") -> None:
        header = Text.assemble(
            (f"{author}  ", "bold"),
            (f"[{time_str}]" if time_str else "", "dim"),
        )
        body = Text(content)
        if self._at_bottom:
            self.write(header)
            self.write(body)
            self.write("")
            self.scroll_end(animate=False)
        else:
            self.write(header)
            self.write(body)
            self.write("")
            self._pending_count += 1

    def append_card(self, card: dict) -> None:
        card_type = card.get("card_type", "card").replace("_", " ").title()
        summary = card.get("summary") or ""
        href = card.get("drill_down_href") or ""
        panel = Panel(
            Text(summary) + "\n" + Text(f"→ {href}", style="dim blue"),
            title=f"[bold]{card_type}[/bold]",
            border_style="cyan",
            padding=(0, 1),
        )
        if self._at_bottom:
            self.write(panel)
            self.write("")
            self.scroll_end(animate=False)
        else:
            self.write(panel)
            self.write("")
            self._pending_count += 1

    def _on_scroll(self) -> None:
        self._at_bottom = self.max_lines is not None  # simplified

    def show_pending_indicator(self) -> None:
        if self._pending_count > 0:
            self.write(Text(f"▼ {self._pending_count} new", style="bold cyan"))
            self._pending_count = 0
```

- [ ] **Step 2: Write card_renderer**

```python
# xmuse/tui/widgets/card_renderer.py
from rich.panel import Panel
from rich.text import Text

CARD_STYLES = {
    "blueprint_execution_started": "cyan",
    "feature_plan_ready": "green",
    "lane_graph_ready": "green",
    "run_progress": "yellow",
    "run_takeover": "red",
    "run_terminal": "magenta",
    "blueprint_gap_review": "blue",
}


def render_card(card: dict) -> Panel:
    card_type = card.get("card_type", "card")
    style = CARD_STYLES.get(card_type, "white")
    title = card_type.replace("_", " ").title()
    summary = card.get("summary") or ""
    href = card.get("drill_down_href") or ""
    return Panel(
        Text(summary) + "\n" + Text(f"→ {href}", style="dim blue"),
        title=f"[bold]{title}[/bold]",
        border_style=style,
        padding=(0, 1),
    )
```

- [ ] **Step 3: Write state_indicator**

```python
# xmuse/tui/widgets/state_indicator.py
from __future__ import annotations

from textual.widgets import Static
from rich.text import Text


class LoadingIndicator(Static):
    def on_mount(self) -> None:
        self.update(Text("[dim]Loading...[/dim]"))


class EmptyIndicator(Static):
    def __init__(self, message: str = "No data") -> None:
        super().__init__()
        self._msg = message

    def on_mount(self) -> None:
        self.update(Text(f"[dim]{self._msg}[/dim]"))


class ErrorIndicator(Static):
    def __init__(self, error: str = "") -> None:
        super().__init__()
        self._error = error

    def on_mount(self) -> None:
        self.update(Text(f"[red]✗ {self._error}[/red]"))
```

- [ ] **Step 4: Write widget tests**

```python
# tests/xmuse/test_tui_widgets.py
from rich.panel import Panel
from rich.text import Text
from xmuse.tui.widgets.card_renderer import render_card
from xmuse.tui.widgets.message_log import MessageLog
from xmuse.tui.widgets.state_indicator import LoadingIndicator, EmptyIndicator, ErrorIndicator


def test_render_card_returns_panel():
    card = {"card_type": "run_progress", "summary": "3/5 merged"}
    result = render_card(card)
    assert isinstance(result, Panel)


def test_render_card_no_drill():
    card = {"card_type": "run_terminal", "summary": "done"}
    result = render_card(card)
    assert isinstance(result, Panel)


def test_render_card_default_style():
    card = {"card_type": "unknown_type", "summary": "test"}
    result = render_card(card)
    assert isinstance(result, Panel)
```

- [ ] **Step 5: Run widget tests**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_widgets.py -q`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add xmuse/tui/widgets/message_log.py xmuse/tui/widgets/card_renderer.py xmuse/tui/widgets/state_indicator.py tests/xmuse/test_tui_widgets.py
git commit -m "feat(tui): add message log, card renderer, and state indicators"
```

---

### Task 6: HealthPanel widget

**Files:**
- Create: `xmuse/tui/widgets/health_panel.py`

- [ ] **Step 1: Write HealthPanel**

```python
# xmuse/tui/widgets/health_panel.py
from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static


class HealthPanel(Static):
    def show_health(self, health: dict | None) -> None:
        if not health:
            super().update(Text("No run health data", style="dim"))
            return
        t = Table(box=None, expand=True)
        t.add_column("Status", style="bold")
        t.add_column("Count", style="yellow")
        t.add_row("Live", str(health.get("live", 0)))
        t.add_row("Merged", str(health.get("merged", 0)))
        t.add_row("Failed", str(health.get("failed", 0)))
        t.add_row("Total", str(health.get("total", 0)))
        super().update(t)
```

Note: uses `super().update()` instead of `self.update()` to avoid recursion (Static.update() is the method being overridden).

- [ ] **Step 2: Commit**

```bash
git add xmuse/tui/widgets/health_panel.py
git commit -m "feat(tui): add health panel widget"
```

---

### Task 7: FeatureBoardScreen — Layer 2

**Files:**
- Create: `xmuse/tui/screens/feature_board.py`
- Create: `xmuse/tui/widgets/feature_row.py`
- Create: `xmuse/tui/screens/system_screen.py`

- [ ] **Step 1: Write FeatureTable**

```python
# xmuse/tui/widgets/feature_row.py
from __future__ import annotations

from rich import box
from rich.table import Table
from rich.text import Text
from textual.widgets import Static


class FeatureTable(Static):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data: dict = {}

    def update_data(self, features: dict) -> None:
        if features == self._data:
            return
        self._data = features
        if not features:
            super().update(Text("No features yet", style="dim"))
            return
        t = Table(box=box.ROUNDED)
        t.add_column("Feature", style="cyan")
        t.add_column("Progress")
        t.add_column("Lanes", style="yellow")
        t.add_column("Status")
        for fid in sorted(features):
            ft = features[fid]
            ratio = f"{ft['merged']}/{ft['total']}" if ft['total'] else "—"
            status = "✅" if ft['total'] > 0 and ft['merged'] == ft['total'] else \
                     "🔄" if ft['total'] > 0 else "⏳"
            t.add_row(fid, _progress_bar(ft), ratio, status)
        super().update(t)


def _progress_bar(ft: dict) -> str:
    total = ft.get("total", 0)
    merged = ft.get("merged", 0)
    if total == 0:
        return "[dim]—[/dim]"
    filled = "█" * merged
    empty = "░" * (total - merged)
    return f"[green]{filled}[/green][dim]{empty}[/dim]"
```

- [ ] **Step 2: Write FeatureBoardScreen**

```python
# xmuse/tui/screens/feature_board.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane

from xmuse.tui.app import StateUpdated
from xmuse.tui.widgets.feature_row import FeatureTable
from xmuse.tui.widgets.health_panel import HealthPanel
from xmuse.tui.screens.system_screen import SystemPlaceholder


class FeatureBoardScreen(Screen):
    CSS = """
    FeatureTable {
        height: 1fr;
    }
    HealthPanel {
        height: auto;
        margin: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent("Features", "System"):
            with TabPane("Features"):
                yield FeatureTable(id="feature-table")
                yield HealthPanel(id="board-health")
            with TabPane("System"):
                yield SystemPlaceholder(id="system-pane")

    def on_state_updated(self, event: StateUpdated) -> None:
        if not event.state.lanes_changed and not event.state.has_errors:
            return
        features = event.state.all_features()
        self.query_one("#feature-table", FeatureTable).update_data(features)
        self.query_one("#board-health", HealthPanel).show_health(event.state.run_health or {})
```

- [ ] **Step 3: Write SystemPlaceholder**

```python
# xmuse/tui/screens/system_screen.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label
from textual.widget import Widget


class SystemPlaceholder(Widget):
    def compose(self) -> ComposeResult:
        yield Label(
            "\n\n"
            "  System Monitoring\n\n"
            "  ⏳ LangGraph runtime adapter  — planned for R1\n"
            "  ⏳ Ray actor backend          — planned for R2\n"
            "  ⏳ Rollout gates              — planned for R3\n",
            id="system-label",
        )
```

- [ ] **Step 4: Commit**

```bash
git add xmuse/tui/screens/feature_board.py xmuse/tui/widgets/feature_row.py xmuse/tui/screens/system_screen.py
git commit -m "feat(tui): add feature board and system placeholder screens"
```

---

### Task 8: Detail screens

**Files:**
- Create: `xmuse/tui/widgets/dag_tree.py`
- Create: `xmuse/tui/screens/feature_detail.py`
- Create: `xmuse/tui/screens/lane_detail.py`
- Create: `xmuse/tui/screens/planning_run.py`
- Create: `xmuse/tui/screens/provider_board.py`

- [ ] **Step 1: Write DAG tree widget**

```python
# xmuse/tui/widgets/dag_tree.py
from __future__ import annotations

from rich.text import Text
from rich.tree import Tree
from textual.widgets import Static


def topological_sort(lanes: list[dict]) -> list[list[dict]]:
    ids = {l.get("lane_local_id") or l.get("feature_id", ""): l for l in lanes}
    deps = {k: list(set(v.get("lane_depends_on_ids") or [])) for k, v in ids.items()}
    layers: list[list[dict]] = []
    remaining = set(ids.keys())
    while remaining:
        current = {n for n in remaining if not any(d in remaining for d in deps.get(n, []))}
        if not current:
            break
        layers.append([ids[n] for n in sorted(current)])
        remaining -= current
    return layers


class DagTree(Static):
    def load_graph(self, graph: dict) -> None:
        lanes = graph.get("lanes", [])
        if not lanes:
            super().update(Text("No lanes in this graph", style="dim"))
            return
        tree = Tree(f"[bold]{graph.get('id', '?')}[/bold] (v{graph.get('version', '?')})")
        layers = topological_sort(lanes)
        for i, layer in enumerate(layers):
            branch = tree.add(f"[bold cyan]Layer {i}[/bold cyan]")
            for lane in layer:
                status = lane.get("status", "?")
                label = f"[green]●[/green] {lane.get('lane_local_id', '?')} [dim]({status})[/dim]"
                leaf = branch.add(label)
                deps = lane.get("lane_depends_on_ids") or []
                if deps:
                    leaf.add(f"[dim]depends: {', '.join(deps)}[/dim]")
        super().update(tree)
```

- [ ] **Step 2: Write FeatureDetail screen**

```python
# xmuse/tui/screens/feature_detail.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from xmuse.tui.widgets.dag_tree import DagTree


class FeatureDetailScreen(Screen):
    CSS = """
    #detail-header {
        dock: top;
        height: auto;
        padding: 1;
    }
    DagTree {
        height: 1fr;
    }
    """

    def __init__(self, graph_id: str = "") -> None:
        super().__init__()
        self.graph_id = graph_id

    def compose(self) -> ComposeResult:
        yield Label(f"Feature Graph: {self.graph_id}", id="detail-header")
        yield DagTree(id="dag-view")

    def on_mount(self) -> None:
        graph = self.app.adapter.get_feature_graph(self.graph_id)
        if graph:
            self.query_one("#dag-view", DagTree).load_graph(graph)
        else:
            self.query_one("#dag-view", DagTree).update(
                "[dim]Graph not found[/dim]"
            )
```

- [ ] **Step 3: Write LaneDetail screen**

```python
# xmuse/tui/screens/lane_detail.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static

from rich.text import Text


class LaneDetailScreen(Screen):
    CSS = """
    #lane-header {
        dock: top;
        height: auto;
        padding: 1;
    }
    #lane-content {
        height: 1fr;
        margin: 1;
    }
    """

    def __init__(self, lane_id: str = "") -> None:
        super().__init__()
        self.lane_id = lane_id

    def compose(self) -> ComposeResult:
        yield Label(f"Lane: {self.lane_id}", id="lane-header")
        yield Static(id="lane-content")

    def on_mount(self) -> None:
        lane = self.app.adapter.get_lane(self.lane_id)
        if not lane:
            self.query_one("#lane-content", Static).update("[red]Lane not found[/red]")
            return
        lines = [
            f"Status: {lane.get('status', '?')}",
            f"Provider: {lane.get('delegation_mode', lane.get('god_runtime', '?'))}",
            f"Retry count: {lane.get('retry_count', 0)}",
            "",
            "--- Prompt ---",
            lane.get("prompt", "")[:500] + ("..." if len(lane.get("prompt", "")) > 500 else ""),
        ]
        if lane.get("review_history"):
            lines.extend(["", "--- Review History ---"])
            for r in lane["review_history"][-3:]:
                lines.append(f"  {r.get('decision', '?')}: {r.get('summary', '')[:200]}...")
        self.query_one("#lane-content", Static).update(Text("\n".join(lines)))
```

- [ ] **Step 4: Write PlanningRun screen**

```python
# xmuse/tui/screens/planning_run.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static

from rich.text import Text


class PlanningRunScreen(Screen):
    CSS = """
    #run-header {
        dock: top;
        height: auto;
        padding: 1;
    }
    #run-content {
        height: 1fr;
        margin: 1;
    }
    """

    def __init__(self, run_id: str = "") -> None:
        super().__init__()
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        yield Label(f"Planning Run: {self.run_id}", id="run-header")
        yield Static(id="run-content", disabled=True)
        yield Label("[dim]PlanningRun store not yet wired[/dim]", id="run-notice")
```

- [ ] **Step 5: Write ProviderBoard screen**

```python
# xmuse/tui/screens/provider_board.py
from __future__ import annotations

from rich import box
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static


class ProviderBoardScreen(Screen):
    CSS = """
    #provider-header {
        dock: top;
        height: auto;
        padding: 1;
    }
    #provider-table {
        height: 1fr;
        margin: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Provider Inventory", id="provider-header")
        yield Static(id="provider-table")

    def on_mount(self) -> None:
        inventory = self.app.adapter.get_provider_inventory()
        if not inventory:
            self.query_one("#provider-table", Static).update(
                Text("[dim]Provider store not available — waiting for C0a/C0b to land[/dim]")
            )
            return
        t = Table(box=box.ROUNDED)
        t.add_column("Provider", style="cyan")
        t.add_column("Profile", style="green")
        t.add_column("Capability", style="yellow")
        for item in inventory:
            t.add_row(
                item.get("provider_id", "?"),
                item.get("profile_id", "?"),
                ", ".join(item.get("capabilities", [])),
            )
        self.query_one("#provider-table", Static).update(t)
```

All `box.ROUNDED` usages have `from rich import box` imported.

- [ ] **Step 6: Register detail screens in app.py**

Replace the SCREENS dict in app.py:

```python
# Add these imports at the top of app.py:
from xmuse.tui.screens.feature_detail import FeatureDetailScreen
from xmuse.tui.screens.lane_detail import LaneDetailScreen
from xmuse.tui.screens.planning_run import PlanningRunScreen
from xmuse.tui.screens.provider_board import ProviderBoardScreen

# Replace the SCREENS dict:
SCREENS = {
    "chat": ChatScreen(),
    "board": FeatureBoardScreen(),
    "feature_detail": FeatureDetailScreen(),
    "lane_detail": LaneDetailScreen(),
    "planning_run": PlanningRunScreen(),
    "provider_board": ProviderBoardScreen(),
}
```

- [ ] **Step 7: Commit**

```bash
git add xmuse/tui/screens/feature_detail.py xmuse/tui/screens/lane_detail.py xmuse/tui/screens/planning_run.py xmuse/tui/screens/provider_board.py xmuse/tui/widgets/dag_tree.py
git commit -m "feat(tui): add detail screens and dag tree widget"
```

---

### Task 9: Responsive layout and click-to-drill-down

**Files:**
- Modify: `xmuse/tui/screens/chat_screen.py`
- Modify: `xmuse/tui/screens/feature_board.py`

- [ ] **Step 1: Add responsive width detection to ChatScreen**

Add to ChatScreen class:

```python
def on_resize(self, event: Resize) -> None:
    width = event.size.width
    if width < 80:
        self.query_one("#worklist-panel").display = False
    else:
        self.query_one("#worklist-panel").display = True
```

Add the import:
```python
from textual.events import Resize
```

- [ ] **Step 2: Add click-to-drill-down to FeatureBoardScreen**

Add to FeatureBoardScreen class:

```python
def on_feature_row_click(self, feature_id: str) -> None:
    """Navigate to feature detail when user clicks a row."""
    from xmuse.tui.screens.feature_detail import FeatureDetailScreen
    screen = FeatureDetailScreen(graph_id=feature_id)
    self.app.push_screen(screen)
```

Note: feature rows emit click events via the `FeatureTable` widget.

- [ ] **Step 3: Commit**

```bash
git add xmuse/tui/screens/chat_screen.py xmuse/tui/screens/feature_board.py
git commit -m "feat(tui): add responsive layout and drill-down navigation"
```

---

### Task 10: Navigation and integration tests

**Files:**
- Create: `tests/xmuse/test_tui_navigation.py`

- [ ] **Step 1: Write Pilot-based navigation test**

```python
# tests/xmuse/test_tui_navigation.py
import pytest
from pathlib import Path

from xmuse.tui.app import XmuseTUI


pytestmark = pytest.mark.asyncio


@pytest.fixture
def app() -> XmuseTUI:
    root = Path(__file__).resolve().parent.parent / "xmuse"
    return XmuseTUI(xmuse_root=root)


async def test_app_starts_on_chat_screen(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        assert app.screen is not None
        assert len(app.screen_stack) >= 1


async def test_switch_to_board_and_back(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        current = type(app.screen).__name__
        # Should be on FeatureBoardScreen after Ctrl+D
        assert "Board" in current or "Feature" in current


async def test_switch_to_chat(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        await pilot.press("ctrl+1")
        assert "Chat" in type(app.screen).__name__
```

Note: `pytestmark = pytest.mark.asyncio` enables async test collection. Without this, the tests are silently skipped.

- [ ] **Step 2: Run navigation tests**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_navigation.py -q`
Expected: 3 passed

- [ ] **Step 3: Run ALL TUI tests**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py -q`
Expected: all tests passed

- [ ] **Step 4: Commit**

```bash
git add tests/xmuse/test_tui_navigation.py
git commit -m "test(tui): add pilot-based navigation and integration tests"
```

---

### Self-Review Checklist

- [ ] Every spec section maps to at least one task:
  - Section 2 (Architecture) → Task 1, 2
  - Section 3 (Navigation) → Task 4, 7, 9
  - Section 4 (Data flow) → Task 5, 6, 9
  - Section 5 (Polling) → Task 3 (async poll_projection, asyncio.to_thread)
  - Section 6 (DAG) → Task 8
  - Section 7 (Adapter API) → Task 1, 3
  - Section 8 (LangGraph/Ray) → Task 7 SystemPlaceholder
  - Section 9 (Error handling) → Task 3 (per-domain isolation, full recovery)
  - Section 10 (Testing) → Task 3, 5, 10
  - Terminal width -> Task 9
  - Click-to-drill-down -> Task 9
- [ ] No placeholders remain
- [ ] No `box` reference without `from rich import box`
- [ ] No `self.update()` recursion in HealthPanel or FeatureTable — all use `super().update()`
- [ ] `send_message` has 4 parameters matching `ChatStore.add_message(conv_id, author, role, content)`
- [ ] Pydantic models handled via `.model_dump(mode="json")` not raw access
- [ ] Polling uses string timestamp comparison, not float
- [ ] `ChatExecutionCardEmitter(root)` receives xmuse root, not chat.db path
- [ ] Navigation tests have `pytestmark = pytest.mark.asyncio`
- [ ] `Any` imported from `typing` in app.py
- [ ] Every file in File Structure is created by a task
