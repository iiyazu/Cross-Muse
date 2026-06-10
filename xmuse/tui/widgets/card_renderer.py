from rich.panel import Panel
from rich.text import Text

CARD_STYLES = {
    "blueprint_execution_started": "#88c0d0",
    "feature_plan_ready": "#a3be8c",
    "lane_graph_ready": "#a3be8c",
    "run_progress": "#ebcb8b",
    "lane_blocked": "#bf616a",
    "takeover_requested": "#bf616a",
    "run_takeover": "#bf616a",
    "run_terminal": "#b48ead",
    "blueprint_gap_review": "#81a1c1",
    "peer_route_status": "#81a1c1",
    "peer_pending": "#ebcb8b",
    "runtime_bootstrap": "#a3be8c",
    "runtime_discussion": "#88c0d0",
    "runtime_blocker": "#bf616a",
    "runtime_dispatch_gate": "#d08770",
    "runtime_dispatch_queue": "#ebcb8b",
    "runtime_provider_writeback": "#b48ead",
}


def render_card(card: dict) -> Panel:
    card_type = card.get("card_type", "card")
    style = CARD_STYLES.get(card_type, "white")
    title = _card_title(card, fallback=card_type.replace("_", " ").title())
    summary = _card_summary(card)
    href = _drilldown_href(card)
    body = Text(summary)
    if href:
        body.append("\n")
        body.append(f"\u2192 {href}", style="dim blue")
    return Panel(
        body,
        title=f"[bold]{title}[/bold]",
        border_style=style,
        padding=(0, 1),
    )


def _card_title(card: dict, *, fallback: str) -> str:
    title = card.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return fallback


def _card_summary(card: dict) -> str:
    summary = card.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    title = card.get("title")
    status = card.get("status")
    lines: list[str] = []
    if isinstance(title, str) and title:
        lines.append(title)
    if isinstance(status, str) and status:
        lines.append(f"Status: {status}")
    return "\n".join(lines)


def _drilldown_href(card: dict) -> str:
    drilldown_refs = card.get("drilldown_refs")
    if isinstance(drilldown_refs, list):
        for ref in drilldown_refs:
            if not isinstance(ref, dict):
                continue
            api_href = ref.get("api_href")
            if isinstance(api_href, str) and api_href:
                return api_href
    for field in ("drill_down_href", "href", "api_href"):
        value = card.get(field)
        if isinstance(value, str) and value:
            return value
    return ""
