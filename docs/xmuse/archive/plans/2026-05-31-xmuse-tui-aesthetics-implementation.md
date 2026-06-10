# xmuse TUI Aesthetics & Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply Nord color theme, add rich header bar to main screens, and finalize splitter drag performance.

**Architecture:** `xmuHeader` widget added to ChatScreen and FeatureBoardScreen compose(). Detail screens keep their existing dock:top headers — no persistent App-level header (Textual limitation: push_screen replaces widget tree). All inline Rich markup updated to Nord hex values. `theme.tcss` updated with Nord variables.

**Tech Stack:** Python 3.12, Textual 1.x, Rich, Nord color palette

---

## File Structure

```
xmuse/tui/
├── app.py                        # [Modify] No compose() change — keep push_screen
├── style/theme.tcss              # [Modify] Nord CSS variables
├── widgets/
│   ├── card_renderer.py          # [Modify] Nord hex in CARD_STYLES
│   ├── dag_tree.py               # [Modify] Inline color markup
│   ├── feature_row.py            # [Modify] Inline color markup
│   ├── health_panel.py           # [Modify] Inline color markup
│   ├── message_log.py            # [Modify] Nord card colors, role-based author color
│   ├── provider_board.py         # NOT a widget — handled in screens/
│   ├── state_indicator.py        # [Modify] Inline color markup
│   └── xmu_header.py             # [Create] Custom header widget
└── screens/
    ├── chat_screen.py            # [Modify] Add header to compose, height: 1fr
    ├── feature_board.py          # [Modify] Add header to compose
    ├── feature_detail.py         # [Modify] Remove dock:top header (replaced by xmuHeader-like content)
    ├── lane_detail.py            # [Modify] Remove dock:top label header
    ├── planning_run.py           # [Modify] Remove dock:top label header
    └── provider_board.py         # [Modify] Remove dock:top label header + Nord hex colors
```

### Task 1: Nord CSS variables in theme.tcss

**Files:**
- Modify: `xmuse/tui/style/theme.tcss`

- [ ] **Step 1: Replace theme.tcss with Nord definitions**

```css
/* xmuse/tui/style/theme.tcss */
Screen {
    background: #2e3440;
}

RichLog {
    background: #2e3440;
    border: solid #4c566a;
}

Input {
    dock: bottom;
}

DataTable {
    height: 100%;
}

Scrollbar {
    scrollbar-color: #4c566a;
    scrollbar-color-active: #88c0d0;
    scrollbar-color-hover: #81a1c1;
}

/* Nord semantic colors as Textual CSS variables */
$surface: #2e3440;
$boost: #3b4252;
$primary: #88c0d0;
$secondary: #81a1c1;
$accent: #b48ead;
$success: #a3be8c;
$warning: #ebcb8b;
$error: #bf616a;
$text: #eceff4;
$text-muted: #616e88;
$border: #4c566a;
```

- [ ] **Step 2: Verify app loads**

Run: `cd /home/iiyatu/projects/python/memoryOS && timeout 3 uv run python -m xmuse.tui`
Expected exit code 124 (timeout). App renders with Nord background.

- [ ] **Step 3: Commit**

```bash
git add xmuse/tui/style/theme.tcss
git commit -m "style(tui): apply Nord color palette to theme CSS"
```

---

### Task 2: xmuHeader widget

**Files:**
- Create: `xmuse/tui/widgets/xmu_header.py`

- [ ] **Step 1: Create XmuHeader widget**

```python
# xmuse/tui/widgets/xmu_header.py
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class XmuHeader(Static):
    """Header bar showing app name, conversation, and run health."""

    DEFAULT_CSS = """
    XmuHeader {
        dock: top;
        height: 1;
        background: $boost;
        color: $text;
    }
    """

    def load(self, state: AppState) -> None:
        conv_id = state.active_conversation_id or ""
        conv_title = conv_id[:40] if conv_id else "(no conversation)"
        health = state.run_health or {}
        live = health.get("live", 0)
        failed = health.get("failed", 0)
        t = Text.assemble(
            (" xmuse ", "bold #88c0d0"),
            ("│", "#4c566a"),
            (f" {conv_title} ", "#eceff4"),
            ("│", "#4c566a"),
            (" ● ", "#a3be8c"),
            (f"{live} live", "#a3be8c"),
            (" │ ", "#4c566a"),
            (" ● ", "#bf616a"),
            (f"{failed} failed", "#bf616a"),
            (" │ ", "#4c566a"),
            (f" {conv_id[:20]} ", "#616e88"),
        )
        self.update(t)
```

- [ ] **Step 2: Verify import**

Run: `cd /home/iiyatu/projects/python/memoryOS && uv run python -c "from xmuse.tui.widgets.xmu_header import XmuHeader; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add xmuse/tui/widgets/xmu_header.py
git commit -m "feat(tui): add Nord-styled XmuHeader widget"
```

---

### Task 3: Add header to ChatScreen + FeatureBoardScreen

**Files:**
- Modify: `xmuse/tui/screens/chat_screen.py`
- Modify: `xmuse/tui/screens/feature_board.py`

- [ ] **Step 1: ChatScreen — add header to compose + height: 1fr**

Add import:
```python
from xmuse.tui.widgets.xmu_header import XmuHeader
```

In `compose()`, yield header before the horizontal layout:

```python
def compose(self) -> ComposeResult:
    yield XmuHeader(id="header")
    with Horizontal(id="chat-horizontal"):
        # ... existing panes and dividers ...
```

In CSS, change `#chat-horizontal` from `height: 100%` to `height: 1fr`.

Add `on_state_updated` call to update header:

```python
def on_state_updated(self, event: StateUpdated) -> None:
    self.query_one(XmuHeader).load(event.state)
    # ... existing message/card rendering ...
```

- [ ] **Step 2: FeatureBoardScreen — add header**

Add import:
```python
from xmuse.tui.widgets.xmu_header import XmuHeader
```

In `compose()`, yield header before the TabbedContent:

```python
def compose(self) -> ComposeResult:
    yield XmuHeader(id="header")
    with TabbedContent("Features", "System"):
        # ... existing content ...
```

In `on_state_updated`, add:
```python
self.query_one(XmuHeader).load(event.state)
```

- [ ] **Step 3: Verify both screens**

Run: `cd /home/iiyatu/projects/python/memoryOS && timeout 3 uv run python -m xmuse.tui`
Expected exit code 124. Header visible on chat screen.

Test Ctrl+D switches to board: press `ctrl+d` in the running TUI — header should persist.

- [ ] **Step 4: Run all tests**

```bash
cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py -q
```
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add xmuse/tui/screens/chat_screen.py xmuse/tui/screens/feature_board.py
git commit -m "feat(tui): add XmuHeader to ChatScreen and FeatureBoardScreen"
```

---

### Task 4: Remove dock:top headers from detail screens + Nord colors

**Files:**
- Modify: `xmuse/tui/screens/feature_detail.py`
- Modify: `xmuse/tui/screens/lane_detail.py`
- Modify: `xmuse/tui/screens/planning_run.py`
- Modify: `xmuse/tui/screens/provider_board.py`

- [ ] **Step 1: FeatureDetail — remove dock:top**

Replace the CSS block:
```css
#detail-header {
    dock: top;
    height: auto;
    padding: 1;
}
```
with:
```css
#detail-header {
    height: auto;
    padding: 1;
    background: $boost;
    color: $primary;
}
```

- [ ] **Step 2: LaneDetail — remove dock:top**

Replace:
```css
#lane-header {
    dock: top;
    height: auto;
    padding: 1;
}
```
with:
```css
#lane-header {
    height: auto;
    padding: 1;
    background: $boost;
    color: $primary;
}
```

- [ ] **Step 3: PlanningRun — remove dock:top**

Replace:
```css
#run-header {
    dock: top;
    height: auto;
    padding: 1;
}
```
with:
```css
#run-header {
    height: auto;
    padding: 1;
    background: $boost;
    color: $primary;
}
```

- [ ] **Step 4: ProviderBoard — remove dock:top + Nord colors**

Replace:
```css
#provider-header {
    dock: top;
    height: auto;
    padding: 1;
}
```
with:
```css
#provider-header {
    height: auto;
    padding: 1;
    background: $boost;
    color: $primary;
}
```

Also replace inline Rich colors in ProviderBoard's `on_mount`:
```python
# Replace:
t.add_column("Provider", style="cyan")
t.add_column("Profile", style="green")
t.add_column("Capability", style="yellow")
# With:
t.add_column("Provider", style="#88c0d0")
t.add_column("Profile", style="#a3be8c")
t.add_column("Capability", style="#ebcb8b")
```

- [ ] **Step 5: Verify all detail screens render**

Run: `cd /home/iiyatu/projects/python/memoryOS && timeout 3 uv run python -m xmuse.tui`
Expected exit code 124. App starts.

- [ ] **Step 6: Run tests**

```bash
cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py -q
```
Expected: 12 passed

- [ ] **Step 7: Commit**

```bash
git add xmuse/tui/screens/feature_detail.py xmuse/tui/screens/lane_detail.py xmuse/tui/screens/planning_run.py xmuse/tui/screens/provider_board.py
git commit -m "fix(tui): remove dock:top from detail screen headers, apply Nord colors"
```

---

### Task 5: Update inline Rich markup to Nord hex values

**Files:**
- Modify: `xmuse/tui/widgets/card_renderer.py`
- Modify: `xmuse/tui/widgets/message_log.py`
- Modify: `xmuse/tui/widgets/dag_tree.py`
- Modify: `xmuse/tui/widgets/feature_row.py`
- Modify: `xmuse/tui/widgets/health_panel.py`
- Modify: `xmuse/tui/widgets/state_indicator.py`

- [ ] **Step 1: card_renderer.py — Nord hex in CARD_STYLES**

```python
CARD_STYLES = {
    "blueprint_execution_started": "#88c0d0",
    "feature_plan_ready": "#a3be8c",
    "lane_graph_ready": "#a3be8c",
    "run_progress": "#ebcb8b",
    "run_takeover": "#bf616a",
    "run_terminal": "#b48ead",
    "blueprint_gap_review": "#81a1c1",
}
```

- [ ] **Step 2: message_log.py — Nord card border + role-based author color**

Replace `border_style="cyan"` with `border_style="#88c0d0"` in `append_card`.

In `append_message`, add role parameter and color mapping:

```python
def append_message(self, author: str, content: str, time_str: str = "",
                   role: str = "system") -> None:
    role_color = {
        "user": "#eceff4",
        "assistant": "#88c0d0",
        "god": "#88c0d0",
        "review-god": "#88c0d0",
        "execution-god": "#81a1c1",
    }.get(role, "#616e88")
    header = Text.assemble(
        (f"{author}  ", f"bold {role_color}"),
        (f"[{time_str}]" if time_str else "", "dim"),
    )
```

Also update `chat_screen.py` to pass `role` in the call to `log.append_message`:

```python
log.append_message(
    author=msg.get("author", "?"),
    content=msg.get("content", ""),
    time_str=msg.get("created_at", ""),
    role=msg.get("role", "system"),
)
```

- [ ] **Step 3: dag_tree.py — Nord hex inline colors**

Replace:
- `"[bold cyan]"` → `"[bold #88c0d0]"`
- `"[green]"` → `"[#a3be8c]"`
- `"[dim]"` → `"[dim #616e88]"`

- [ ] **Step 4: feature_row.py — Nord hex inline colors**

Replace:
- `"[green]"` in `_progress_bar` → `"[#a3be8c]"`
- `"[dim]"` in `_progress_bar` → `"[dim #616e88]"`

- [ ] **Step 5: health_panel.py — Nord hex**

Replace `style="yellow"` → `style="#ebcb8b"`

- [ ] **Step 6: state_indicator.py — Nord hex error color**

Replace `"[red]"` → `"[#bf616a]"`

- [ ] **Step 7: Verify and run tests**

```bash
cd /home/iiyatu/projects/python/memoryOS && uv run pytest tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py -q
```
Expected: 12 passed

```bash
cd /home/iiyatu/projects/python/memoryOS && timeout 3 uv run python -m xmuse.tui
```
Expected exit code 124. App renders with Nord colors throughout.

- [ ] **Step 8: Commit**

```bash
git add xmuse/tui/widgets/card_renderer.py xmuse/tui/widgets/message_log.py xmuse/tui/widgets/dag_tree.py xmuse/tui/widgets/feature_row.py xmuse/tui/widgets/health_panel.py xmuse/tui/widgets/state_indicator.py xmuse/tui/screens/chat_screen.py
git commit -m "style(tui): apply Nord hex colors to all inline Rich markup"
```

---

### Self-Review Checklist

- [ ] Spec coverage: §1 Nord CSS → Task 1, §1 Rich inline → Task 4 (provider_board) + Task 5, §2 Header → Tasks 2-3, §3 Cards → Task 5, §4 Performance → already in place
- [ ] No placeholders — all code blocks contain actual content
- [ ] No `compose()` on App — push_screen pattern preserved
- [ ] All `dock: top` explicitly removed in Task 4 (not just height changed)
- [ ] `provider_board.py` treated as screen file, not widget file
- [ ] `XmuHeader` follows PascalCase convention
- [ ] `verify` commands use `timeout N uv run ...` without `|| true` — exit 124 is correct for timeout
- [ ] message_log role parameter wired through chat_screen.py call site
