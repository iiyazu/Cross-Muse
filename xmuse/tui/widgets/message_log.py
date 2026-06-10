from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog

from xmuse.tui.widgets.card_renderer import render_card


class MessageLog(RichLog):
    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, max_lines=2000, wrap=True, **kwargs)
        self._at_bottom = True
        self._pending_count = 0
        self._stored_messages: list[dict] = []
        self._stored_cards: list[dict] = []
        self._search_query = ""

    def on_mount(self) -> None:
        self._at_bottom = True

    def _on_scroll(self) -> None:
        max_scroll = self.max_scroll_position
        cur_scroll = self.scroll_y
        was_at_bottom = self._at_bottom
        self._at_bottom = cur_scroll >= max_scroll - 1
        if self._at_bottom and not was_at_bottom and self._pending_count:
            self.scroll_end(animate=False)
            self._pending_count = 0

    def append_message(
        self,
        author: str,
        content: str,
        time_str: str = "",
        role: str = "system",
        display_author: str | None = None,
    ) -> None:
        visible_author = display_author or author
        self._stored_messages.append({
            "author": author, "display_author": visible_author, "content": content,
            "time_str": time_str, "role": role,
        })
        if self._search_query:
            return
        self._render_message(visible_author, content, time_str, role)

    def _render_message(self, author: str, content: str, time_str: str = "",
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
        body_width = self._content_width()
        body = Text(content, overflow="fold", no_wrap=False)
        if self._at_bottom:
            self.write(header)
            self.write(body, width=body_width)
            self.write("")
            self.scroll_end(animate=False)
        else:
            self.write(header)
            self.write(body, width=body_width)
            self.write("")
            self._pending_count += 1

    def append_card(self, card: dict) -> None:
        self._stored_cards.append(card)
        if self._search_query:
            return
        self._render_card(card)

    def _render_card(self, card: dict) -> None:
        panel = render_card(card)
        body_width = self._content_width()
        if self._at_bottom:
            self.write(panel, width=body_width)
            self.write("")
            self.scroll_end(animate=False)
        else:
            self.write(panel, width=body_width)
            self.write("")
            self._pending_count += 1

    def search(self, query: str) -> str | None:
        self._search_query = query.lower()
        if not query:
            self.clear_search()
            return None
        self.clear()
        body_width = self._content_width()
        matched: list[str] = []
        for msg in self._stored_messages:
            content = msg["content"]
            author = msg.get("display_author") or msg["author"]
            haystack = f"{author} {content}".lower()
            if self._search_query in haystack:
                self._render_message(author, content, msg["time_str"], msg["role"])
                matched.append(content)
        if not matched:
            self.write(Text("No results found.", style="dim italic"), width=body_width)
            self.write("")
            return None
        return " ".join(matched)

    def clear_search(self) -> None:
        self._search_query = ""
        self.clear()
        for msg in self._stored_messages:
            self._render_message(
                msg.get("display_author") or msg["author"],
                msg["content"],
                msg["time_str"],
                msg["role"],
            )
        for card in self._stored_cards:
            self._render_card(card)

    def _content_width(self) -> int:
        width = getattr(getattr(self, "size", None), "width", 0)
        if not isinstance(width, int) or width <= 0:
            return 80
        return max(20, width - 2)
