"""Widget tests."""
from rich.panel import Panel

from xmuse.tui.widgets.card_renderer import CARD_STYLES, render_card
from xmuse.tui.widgets.deliberation_cockpit import render_deliberation_cockpit
from xmuse.tui.widgets.message_log import MessageLog


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


def test_render_card_prefers_card_title_for_peer_status():
    card = {
        "card_type": "peer_pending",
        "title": "Architect GOD is thinking",
        "summary": "Architect GOD 正在处理这条消息。",
    }

    result = render_card(card)

    assert "Architect GOD is thinking" in str(result.title)


def test_runtime_closure_card_types_have_explicit_styles():
    for card_type in [
        "runtime_bootstrap",
        "runtime_discussion",
        "runtime_blocker",
        "runtime_dispatch_gate",
        "runtime_dispatch_queue",
        "runtime_provider_writeback",
    ]:
        assert card_type in CARD_STYLES


def test_message_log_writes_message_body_with_content_width(monkeypatch):
    log = MessageLog()
    writes = []

    class _Size:
        width = 42

    monkeypatch.setattr(type(log), "size", property(lambda self: _Size()))
    monkeypatch.setattr(log, "scroll_end", lambda animate=False: None)

    def _write(content, width=None, expand=False, shrink=True, scroll_end=None, animate=False):
        writes.append({"content": content, "width": width})
        return log

    monkeypatch.setattr(log, "write", _write)

    log.append_message(
        author="architect-god",
        role="assistant",
        content="this is a very long message that should wrap inside the center pane",
    )

    assert writes[1]["width"] == 40


def test_message_log_enables_wrapped_selectable_text():
    log = MessageLog()

    assert log.wrap is True
    assert log.allow_select is True


def test_deliberation_cockpit_renders_speech_acts_and_blockers() -> None:
    panel = render_deliberation_cockpit(
        {
            "deliberation": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "speech_act_counts": {"challenge": 1, "propose": 1},
                "blockers": [
                    {
                        "message_id": "msg-challenge",
                        "speech_act": "challenge",
                        "reason": "acceptance criteria are missing",
                        "target_refs": ["blueprint:conv-1:1"],
                        "source_refs": ["message:msg-propose"],
                    }
                ],
                "target_refs": ["blueprint:conv-1:1"],
                "source_refs": ["message:msg-propose", "message:msg-challenge"],
                "manual_gap_reason": None,
            }
        }
    )

    rendered = panel.renderable.plain
    assert "contract_proof" in rendered
    assert "blocked" in rendered
    assert "challenge: 1" in rendered
    assert "acceptance criteria are missing" in rendered
    assert "blueprint:conv-1:1" in rendered


def test_deliberation_cockpit_renders_manual_gap() -> None:
    panel = render_deliberation_cockpit(None)

    rendered = panel.renderable.plain
    assert "manual_gap" in rendered
    assert "No deliberation evidence" in rendered


class TestRunHealthCounts:
    def test_extracts_counts_subdict(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        result = _run_health_counts({"counts": {"live": 1, "stale": 0}})
        assert result == {"live": 1, "stale": 0}

    def test_falls_back_to_plain_dict(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        result = _run_health_counts({"live": 1})
        assert result == {"live": 1}

    def test_empty_on_none(self):
        from xmuse.tui.widgets.xmu_header import _run_health_counts
        assert _run_health_counts(None) == {}


class TestParticipantStatusSymbol:
    def test_active_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("active") == "●"

    def test_stopped_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("stopped") == "◆"

    def test_unknown_symbol(self):
        from xmuse.tui.screens.chat_screen import _participant_status_symbol
        assert _participant_status_symbol("") == "○"
        assert _participant_status_symbol("thinking") == "○"
        assert _participant_status_symbol("failed") == "○"


class TestXmuHeader:
    def test_header_style_connected_by_live(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 2, "stale": 0, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "connected"

    def test_header_style_degraded_by_errors(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 0}}
        state.has_errors = True
        assert _connection_style_for(state) == "degraded"

    def test_header_style_degraded_by_fallback(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 1}}
        assert _connection_style_for(state) == "degraded"

    def test_header_style_degraded_by_stale(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 1, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "degraded"

    def test_header_style_idle(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"counts": {"live": 0, "stale": 0, "degraded_fallback": 0}}
        assert _connection_style_for(state) == "idle"

    def test_header_style_fallback_plain_run_health(self):
        from xmuse.tui.state import AppState
        from xmuse.tui.widgets.xmu_header import _connection_style_for
        state = AppState()
        state.run_health = {"live": 1}
        assert _connection_style_for(state) == "connected"


class TestMessageLogSearch:
    def test_search_finds_matching_messages(self):
        log = MessageLog()
        log.append_message(author="user", content="hello world", role="user")
        log.append_message(author="architect", content="plan for error handling", role="assistant")
        log.append_message(author="user", content="another message", role="user")
        results = log.search("error")
        assert "error" in results
        assert "hello" not in results

    def test_search_no_match_returns_none(self):
        log = MessageLog()
        log.append_message(author="user", content="hello world", role="user")
        results = log.search("zzzzz")
        assert results is None

    def test_clear_search_restores_all(self):
        log = MessageLog()
        log.append_message(author="user", content="hello", role="user")
        log.append_message(author="architect", content="world", role="assistant")
        log.search("hello")
        log.clear_search()
        assert log._search_query == ""

    def test_search_case_insensitive(self):
        log = MessageLog()
        log.append_message(author="user", content="Hello World", role="user")
        results = log.search("hello")
        assert "Hello" in results

    def test_search_matches_author(self):
        log = MessageLog()
        log.append_message(author="architect-god", content="plan", role="assistant")
        log.append_message(author="user", content="question", role="user")
        results = log.search("architect")
        assert "plan" in results
        assert "question" not in results
