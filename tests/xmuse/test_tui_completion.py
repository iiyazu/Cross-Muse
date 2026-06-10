"""Tests for TUI completion engine (Task 2: TUI-COMPLETION-ENGINE)."""

import pytest

from xmuse.tui.completion import CompletionEngine


@pytest.fixture
def engine():
    return CompletionEngine()


COMMANDS = [
    {"name": "help", "description": "Show help"},
    {"name": "sessions", "description": "List or switch sessions"},
    {"name": "resume", "description": "Resume a session"},
    {"name": "new", "description": "Create new conversation"},
    {"name": "where", "description": "Show current location"},
    {"name": "participants", "description": "List participants"},
    {"name": "god", "description": "Manage GOD participants"},
    {"name": "archive", "description": "Toggle archive view"},
    {"name": "copy", "description": "Toggle copy view"},
]


class TestCompletionEngine:
    def test_no_trigger_on_plain_text(self, engine):
        assert engine.get_candidates("hello") == []

    def test_slash_trigger_returns_all_commands(self, engine):
        cands = engine.get_candidates("/")
        values = [c.value for c in cands]
        assert "/help" in values
        assert "/sessions" in values
        assert "/new" in values

    def test_slash_partial_filter(self, engine):
        cands = engine.get_candidates("/se")
        values = [c.value for c in cands]
        assert "/sessions" in values
        assert "/help" not in values

    def test_slash_no_match_returns_empty(self, engine):
        cands = engine.get_candidates("/zzz")
        assert cands == []

    def test_mention_trigger_returns_participants(self, engine):
        participants = [
            {"role": "architect", "display_name": "Architect GOD"},
            {"role": "review", "display_name": "Review GOD"},
        ]
        cands = engine.get_candidates("@", participants=participants)
        values = [c.value for c in cands]
        assert "@architect" in values
        assert "@review" in values

    def test_mention_filter(self, engine):
        participants = [
            {"role": "architect", "display_name": "Architect GOD"},
            {"role": "review", "display_name": "Review GOD"},
        ]
        cands = engine.get_candidates("@arc", participants=participants)
        values = [c.value for c in cands]
        assert "@architect" in values
        assert "@review" not in values

    def test_mention_no_match_returns_empty(self, engine):
        cands = engine.get_candidates("@zzz", participants=[])
        assert cands == []

    def test_mention_filter_by_display_name(self, engine):
        participants = [
            {"role": "architect", "display_name": "Architect GOD"},
            {"role": "execute", "display_name": "Executor"},
        ]
        cands = engine.get_candidates("@exec", participants=participants)
        values = [c.value for c in cands]
        assert "@execute" in values
        assert "@architect" not in values

    def test_candidate_has_display_and_description(self, engine):
        cands = engine.get_candidates("/")
        assert all(c.display for c in cands)
        assert all(c.description for c in cands)

    def test_mention_candidate_display_includes_role_and_name(self, engine):
        participants = [
            {"role": "architect", "display_name": "Architect GOD"},
        ]
        cands = engine.get_candidates("@", participants=participants)
        assert "architect" in cands[0].value

    def test_no_candidates_when_no_participants(self, engine):
        cands = engine.get_candidates("@", participants=[])
        assert cands == []

    def test_text_with_slash_in_middle_not_triggered(self, engine):
        cands = engine.get_candidates("say /help", participants=[])
        assert cands == []

    def test_command_candidate_has_param_hint(self, engine):
        cands = engine.get_candidates("/new")
        new_cand = [c for c in cands if c.value == "/new"][0]
        assert "<title>" in new_cand.display

    def test_command_candidate_no_param_has_clean_display(self, engine):
        cands = engine.get_candidates("/help")
        help_cand = [c for c in cands if c.value == "/help"][0]
        assert "/help" in help_cand.display

    def test_command_palette_display_readable(self, engine):
        cands = engine.get_candidates("/")
        for c in cands:
            assert len(c.display) > 0
            assert len(c.description) > 0

    def test_candidate_dedup(self, engine):
        participants = [
            {"role": "architect", "display_name": "Architect GOD"},
            {"role": "architect", "display_name": "Architect GOD 2"},
        ]
        cands = engine.get_candidates("@", participants=participants)
        values = [c.value for c in cands]
        assert values == ["@architect"]
        assert len(cands) == 1
