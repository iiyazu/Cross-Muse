"""Navigation tests using Textual Pilot."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from textual.widgets import Input, ListView, Static

from xmuse.chat_api import create_app
from xmuse.tui.adapter.xmuse_adapter import StateDelta, XmuseAdapter
from xmuse.tui.app import XmuseTUI
from xmuse.tui.screens.lane_detail import LaneDetailScreen
from xmuse.tui.state import StateUpdated
from xmuse_core.chat.peer_service import PeerChatService

pytestmark = pytest.mark.asyncio


async def _empty_delta(conv_id=None):
    return StateDelta()


class _NoCloseClient:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get(self, *args, **kwargs):
        return self._client.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._client.post(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._client.delete(*args, **kwargs)


@pytest.fixture
def app(tmp_path: Path) -> XmuseTUI:
    tui = XmuseTUI(xmuse_root=tmp_path / "xmuse")

    tui.adapter.poll_delta = _empty_delta
    tui.adapter.sync = _empty_delta
    tui.adapter.get_participants = lambda conv_id: []
    tui.action_refresh_now = lambda: None
    return tui


async def test_app_starts_on_chat_screen(app: XmuseTUI) -> None:
    async with app.run_test():
        assert app.screen is not None
        assert len(app.screen_stack) >= 1


async def test_chat_screen_focuses_message_input_on_mount(app: XmuseTUI) -> None:
    async with app.run_test():
        input_widget = app.screen.query_one("#message-input", Input)
        assert input_widget.has_focus


async def test_app_uses_non_aggressive_poll_interval(app: XmuseTUI) -> None:
    intervals = []
    app.set_interval = lambda interval, callback: intervals.append((interval, callback))

    app.on_mount()

    assert intervals
    assert intervals[0][0] >= 2.0


async def test_chat_screen_defaults_to_latest_conversation(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-old",
            "title": "Old conversation",
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "id": "conv-new",
            "title": "New conversation",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async with app.run_test():
        assert app.state.active_conversation_id == "conv-new"


async def test_chat_screen_left_rail_uses_user_group_conversations(app: XmuseTUI) -> None:
    app.adapter.list_conversations = lambda: [
        {
            "id": "conv-archive",
            "title": "xmuse self-evolution: reliability",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]

    async with app.run_test():
        assert app.state.active_conversation_id == "conv-user"
        labels = [item.children[0].content for item in app.screen.query_one("#pane-left").children]
        assert labels == ["User group"]


async def test_chat_screen_implements_textual_list_view_selected_handler(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-01T00:00:00Z"},
        {"id": "conv-b", "title": "B", "created_at": "2026-06-02T00:00:00Z"},
    ]

    async with app.run_test() as pilot:
        assert ListView.Selected.handler_name == "on_list_view_selected"
        assert hasattr(app.screen, "on_list_view_selected")

        list_view = app.screen.query_one("#pane-left", ListView)
        item = next(
            child
            for child in list_view.children
            if getattr(child, "conv_id", "") == "conv-a"
        )
        list_view.post_message(ListView.Selected(list_view, item, 1))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-a"


async def test_chat_screen_can_toggle_archive_conversation_list(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.list_archived_conversations = lambda: [
        {
            "id": "conv-archive",
            "title": "xmuse self-evolution: reliability",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        await pilot.press("ctrl+a")
        labels = [item.children[0].content for item in app.screen.query_one("#pane-left").children]
        assert labels == ["xmuse self-evolution: reliability"]
        assert app.state.active_conversation_id == "conv-archive"

        await pilot.press("ctrl+a")
        labels = [item.children[0].content for item in app.screen.query_one("#pane-left").children]
        assert labels == ["User group"]
        assert app.state.active_conversation_id == "conv-user"


async def test_chat_screen_new_command_creates_and_selects_group(app: XmuseTUI) -> None:
    groups = []

    def _list_group_conversations():
        return list(groups)

    def _create_group(title: str, **kwargs):
        group = {
            "id": "conv-created",
            "title": title,
            "created_at": "2026-06-02T00:00:00Z",
            "participants": [],
            "bootstrap": {
                "status": "proposal_ready",
                "proposal_id": "bootstrap-proposal:conv-created:architect-review-execute",
                "participant_plan": ["architect", "review", "execute"],
            },
        }
        groups.append(group)
        return group

    app.adapter.list_group_conversations = _list_group_conversations
    app.adapter.create_group_conversation = _create_group

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/new Product planning"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-created"
        labels = [item.children[0].content for item in app.screen.query_one("#pane-left").children]
        assert labels == ["Product planning"]
        assert (
            "/init apply bootstrap-proposal:conv-created:architect-review-execute"
            in appended[-1]["content"]
        )
        assert "architect / review / execute" in appended[-1]["content"]


async def test_chat_screen_bootstrap_guidance_actions_are_keyboard_selectable(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    created = []
    app.adapter.create_bootstrap_proposal = lambda conv_id: created.append(conv_id) or {
        "proposal": {"proposal_id": "bootstrap-proposal:conv-user:retry"}
    }

    async with app.run_test() as pilot:
        app.state.apply(
            StateDelta(
                messages=[
                    {
                        "id": "msg-bootstrap-guidance",
                        "conversation_id": "conv-user",
                        "author": "init-god",
                        "display_author": "init-god",
                        "role": "assistant",
                        "content": "初始化草案已准备好。",
                        "created_at": "2026-06-02T00:00:00Z",
                        "envelope_type": "bootstrap_guidance",
                        "envelope_json": {
                            "type": "bootstrap_guidance",
                            "proposal_id": "bootstrap-proposal:conv-user:architect-review-execute",
                            "actions": [
                                {
                                    "id": "apply",
                                    "label": "Apply recommended team",
                                    "command": (
                                        "/init apply "
                                        "bootstrap-proposal:conv-user:architect-review-execute"
                                    ),
                                },
                                {
                                    "id": "retry",
                                    "label": "Regenerate proposal",
                                    "command": "/init retry",
                                },
                            ],
                        },
                    }
                ]
            )
        )
        app.screen.post_message(StateUpdated(app.state))
        await pilot.pause()
        app.screen.query_one("#message-input").focus()

        log = app.screen.query_one("#message-log")
        assert "▶ Apply recommended team" in log._stored_messages[-1]["content"]
        assert "  Regenerate proposal" in log._stored_messages[-1]["content"]

        await pilot.press("down")
        await pilot.pause()
        assert "▶ Regenerate proposal" in log._stored_messages[-1]["content"]

        await pilot.press("enter")
        await pilot.pause()

        assert created == ["conv-user"]


async def test_chat_screen_sessions_command_lists_and_switches_group(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-old",
            "title": "Legacy migration",
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "id": "conv-new",
            "title": "Latest mission",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/sessions"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert "1. Latest mission" in appended[-1]["content"]
        assert "2. Legacy migration" in appended[-1]["content"]

        input_widget.value = "/sessions 2"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-old"


async def test_chat_screen_help_command_lists_slash_commands(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-user", "title": "User group", "created_at": "2026-06-01T00:00:00Z"},
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/help"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert "/sessions" in appended[-1]["content"]
        assert "/sessions <number|conversation_id|title>" in appended[-1]["content"]
        assert "/god add <role> [display name]" in appended[-1]["content"]


async def test_chat_screen_sessions_matches_id_and_unique_title_fragment(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-old",
            "title": "Legacy migration",
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "id": "conv-new",
            "title": "Latest mission",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/sessions conv-old"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-old"

        input_widget.value = "/sessions Latest"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-new"


async def test_chat_screen_sessions_ambiguous_title_does_not_switch(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-one",
            "title": "Auth refactor",
            "created_at": "2026-06-01T00:00:00Z",
        },
        {
            "id": "conv-two",
            "title": "Auth audit",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/sessions Auth"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert app.state.active_conversation_id == "conv-two"
        assert "Ambiguous" in appended[-1]["content"]
        assert "Auth refactor" in appended[-1]["content"]
        assert "Auth audit" in appended[-1]["content"]


async def test_chat_screen_participants_and_god_commands(app: XmuseTUI) -> None:
    participants = [
        {
            "participant_id": "part-architect",
            "role": "architect",
            "display_name": "architect-god",
            "model": "gpt-5.4",
            "status": "active",
        }
    ]
    added = []
    removed = []

    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-user", "title": "User group", "created_at": "2026-06-01T00:00:00Z"},
    ]
    app.adapter.get_participants = lambda conv_id: list(participants)

    def _add_participant(conv_id, role, display_name=None, model=None, role_template_id=None):
        item = {
            "participant_id": "part-execute",
            "role": role,
            "display_name": display_name or f"{role}-god",
            "model": model or "gpt-5.4",
            "status": "active",
        }
        participants.append(item)
        added.append((conv_id, role, display_name, model, role_template_id))
        return item

    def _remove_participant(conv_id, role_or_participant_id):
        removed.append((conv_id, role_or_participant_id))
        participants[:] = [
            item
            for item in participants
            if item["participant_id"] != "part-execute" and item["role"] != "execute"
        ]
        return True

    app.adapter.add_participant = _add_participant
    app.adapter.remove_participant = _remove_participant

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/participants"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "architect-god" in appended[-1]["content"]

        input_widget.value = "/god add execute Execution GOD"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert added == [("conv-user", "execute", "Execution GOD", None, None)]
        assert "Added GOD execute" in appended[-1]["content"]

        input_widget.value = "/god rm execute"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert removed == [("conv-user", "execute")]
        assert "Removed GOD execute" in appended[-1]["content"]


async def test_chat_screen_refreshes_immediately_after_user_message(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    sent = []
    refreshed = []
    app.adapter.send_message = lambda conv_id, author, role, content: sent.append(
        (conv_id, author, role, content)
    ) or "msg-1"
    app.action_refresh_now = lambda: refreshed.append(True)

    async with app.run_test() as pilot:
        refreshed.clear()
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "please improve TUI"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert sent == [("conv-user", "user", "user", "please improve TUI")]
        assert refreshed == [True]


async def test_chat_screen_shows_pending_peer_row_after_mention_submit(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_participants = lambda conv_id: [
        {
            "participant_id": "part-architect",
            "role": "architect",
            "display_name": "architect-god",
            "status": "active",
        }
    ]
    app.adapter.send_message = lambda conv_id, author, role, content: "msg-human-1"

    async with app.run_test() as pilot:
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "@architect please improve TUI"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        messages = app.state.messages_for("conv-user")
        assert messages == [
            {
                "id": "peer_pending_conv-user_part-architect",
                "conversation_id": "conv-user",
                "author": "part-architect",
                "display_author": "architect-god",
                "role": "assistant",
                "content": "architect-god ...",
                "envelope_type": "peer_pending",
                "envelope_json": {
                    "type": "peer_pending",
                    "target_role": "architect",
                    "target_participant_id": "part-architect",
                },
                "mentions": [],
                "reply_to_message_id": None,
            }
        ]


async def test_chat_screen_where_command_reports_active_thread(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/where"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert appended == [
            {
                "author": "xmuse",
                "content": "Current group: User group (conv-user)\nParticipants: none",
                "role": "system",
            }
        ]


async def test_chat_screen_discussion_command_shows_collaboration_runs(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "collaboration": {
            "active_runs": 1,
            "runs": [
                {
                    "run_id": "collab-1",
                    "status": "running",
                    "orchestration_mode": "peer_consensus",
                    "initiator": "architect",
                    "targets": ["review", "execute"],
                    "response_count": 1,
                    "blocker_count": 0,
                }
            ],
            "dispatch_gates": [
                {
                    "event_id": "gate-1",
                    "run_id": "collab-1",
                    "decision": "blocked_execute_not_confirmed",
                    "proposal_ref": "proposal:lane-graph",
                    "artifact_ref": "artifact:lane-graph",
                }
            ],
        },
        "dispatch_queue": {
            "queued": 0,
            "processing": 1,
            "entries": [
                {
                    "entry_id": "dispatch-1",
                    "source": "agent",
                    "target": "execute",
                    "status": "processing",
                    "auto_execute": True,
                    "proposal_id": "proposal-1",
                    "resolution_id": "resolution-1",
                    "collaboration_run_id": "collab-1",
                    "artifact_ref": "artifact:lane_graph",
                    "claimed_by": "dispatch-bridge",
                    "provider_run_ref": "provider:codex:session-1",
                }
            ],
        },
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/discussion"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert "Discussion runs: active=1" in appended[-1]["content"]
        assert "collab-1 running peer_consensus" in appended[-1]["content"]
        assert "targets=review, execute" in appended[-1]["content"]
        assert "Dispatch gates:" in appended[-1]["content"]
        assert "gate-1 collab-1 blocked_execute_not_confirmed" in appended[-1]["content"]
        assert "Dispatch queue: queued=0 processing=1" in appended[-1]["content"]
        assert "dispatch-1 processing agent target=execute auto" in appended[-1]["content"]
        assert "provider:codex:session-1" in appended[-1]["content"]


async def test_chat_screen_overview_command_shows_runtime_closure_surface(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_bootstrap_status = lambda conv_id: {
        "status": "bootstrapped",
        "preset_id": "architect-review-execute",
        "participant_plan": ["architect", "review", "execute"],
        "proposal_id": "bootstrap-proposal-1",
    }
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "participants": {
            "total": 4,
            "summary": {"init": 1, "architect": 1, "review": 1, "execute": 1},
        },
        "collaboration": {
            "active_runs": 1,
            "runs": [
                {
                    "run_id": "collab-1",
                    "status": "partial",
                    "orchestration_mode": "peer_consensus",
                    "initiator": "architect",
                    "targets": ["review", "execute"],
                    "response_count": 1,
                    "blocker_count": 1,
                }
            ],
            "dispatch_gates": [
                {
                    "event_id": "gate-1",
                    "run_id": "collab-1",
                    "decision": "blocked_active_veto",
                    "proposal_ref": "proposal:lane-graph",
                    "artifact_ref": "artifact:lane-graph",
                }
            ],
        },
        "blockers": {
            "active": 1,
            "items": [
                {
                    "blocker_id": "blocker-1",
                    "active": True,
                    "severity": "veto",
                    "issuer": "review",
                    "blocks_dispatch": True,
                    "affected_ref": "tui:overview",
                    "reason": "Overview must show dispatch state.",
                }
            ],
        },
        "dispatch_queue": {
            "queued": 1,
            "processing": 1,
            "dispatched": 1,
            "failed": 0,
            "entries": [
                {
                    "entry_id": "dispatch-1",
                    "source": "agent",
                    "target": "execute",
                    "status": "dispatched",
                    "auto_execute": True,
                    "provider_run_ref": "provider:execute:part-execute",
                    "dispatch_evidence": "mcp_writeback:inbox-1",
                }
            ],
        },
        "peer_latency": {
            "recent_turns": [
                {
                    "delivery_mode": "mcp_writeback",
                    "inbox_item_id": "inbox-1",
                    "degraded_reason": None,
                    "target_role": "execute",
                }
            ]
        },
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/overview"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        content = appended[-1]["content"]
        assert "Overview: User group (conv-user)" in content
        assert "Bootstrap: bootstrapped preset=architect-review-execute" in content
        assert "Team: init=1 architect=1 review=1 execute=1" in content
        assert "Discussion: active=1 latest=collab-1 partial peer_consensus" in content
        assert "Blockers: active=1 dispatch-blocking=1" in content
        assert "Dispatch gates: latest=gate-1 blocked_active_veto" in content
        assert "Dispatch queue: queued=1 processing=1 dispatched=1 failed=0" in content
        assert "Latest dispatch: dispatch-1 dispatched provider:execute:part-execute" in content
        assert "Provider writeback: mcp_writeback execute" in content


async def test_chat_screen_dashboard_command_aliases_overview(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_bootstrap_status = lambda conv_id: {"status": "bootstrapped"}
    app.adapter.get_conversation_inspector = lambda conv_id: {"dispatch_queue": {}}

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/dashboard"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert appended
        assert appended[-1]["content"].startswith("Overview: User group (conv-user)")


async def test_chat_screen_overview_correlates_writeback_to_latest_dispatch(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_bootstrap_status = lambda conv_id: {
        "status": "bootstrapped",
        "preset_id": "architect-review-execute",
    }
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "dispatch_queue": {
            "queued": 0,
            "processing": 0,
            "dispatched": 1,
            "failed": 0,
            "entries": [
                {
                    "entry_id": "dispatch-1",
                    "status": "dispatched",
                    "target": "execute",
                    "provider_run_ref": "provider:execute:part-execute",
                    "dispatch_evidence": "mcp_writeback:dispatch-inbox",
                }
            ],
        },
        "peer_latency": {
            "recent_turns": [
                {
                    "inbox_item_id": "ordinary-inbox",
                    "delivery_mode": "mcp_writeback",
                    "target_role": "architect",
                    "degraded_reason": None,
                },
                {
                    "inbox_item_id": "dispatch-inbox",
                    "delivery_mode": "mcp_writeback",
                    "target_role": "execute",
                    "degraded_reason": None,
                },
            ]
        },
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/overview"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        content = appended[-1]["content"]
        assert "Provider writeback: mcp_writeback execute" in content
        assert "Provider writeback: mcp_writeback architect" not in content


async def test_chat_screen_discussion_command_shows_dispatch_gates_without_runs(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "collaboration": {
            "active_runs": 0,
            "runs": [],
            "dispatch_gates": [
                {
                    "event_id": "gate-unknown",
                    "run_id": "collab-missing",
                    "decision": "blocked_unknown_run",
                    "proposal_ref": "proposal:lane-graph",
                    "artifact_ref": "artifact:lane-graph",
                }
            ],
        }
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/discussion"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert "Discussion runs: active=0" in appended[-1]["content"]
        assert "- none" in appended[-1]["content"]
        assert "Dispatch gates:" in appended[-1]["content"]
        assert "gate-unknown collab-missing blocked_unknown_run" in appended[-1]["content"]


async def test_chat_screen_blockers_command_shows_active_vetoes(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "blockers": {
            "active": 1,
            "items": [
                {
                    "blocker_id": "blocker-1",
                    "active": True,
                    "blocks_dispatch": True,
                    "severity": "veto",
                    "issuer": "review",
                    "reason": "TUI does not expose blocker state yet.",
                    "affected_ref": "tui:blockers",
                    "suggested_fix": "Add blocker surface.",
                }
            ],
        }
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/blockers"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert "Blockers: active=1" in appended[-1]["content"]
        assert "blocker-1 veto review dispatch-blocking" in appended[-1]["content"]
        assert "TUI does not expose blocker state yet." in appended[-1]["content"]


async def test_chat_screen_records_official_tui_command_proof_for_runtime_commands(
    app: XmuseTUI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XMUSE_TUI_TERMINAL_RUN_ID", "terminal-run-proof")
    groups = []

    def _list_group_conversations():
        return list(groups)

    def _create_group(title: str, **kwargs):
        group = {
            "id": "conv-proof",
            "title": title,
            "created_at": "2026-06-05T00:00:00Z",
            "participants": [],
            "bootstrap": {
                "status": "proposal_ready",
                "proposal_id": "bootstrap-proposal:conv-proof:architect-review-execute",
                "participant_plan": ["architect", "review", "execute"],
            },
        }
        groups.append(group)
        return group

    app.adapter.list_group_conversations = _list_group_conversations
    app.adapter.create_group_conversation = _create_group
    app.adapter.get_bootstrap_status = lambda conv_id: {
        "conversation_id": conv_id,
        "status": "bootstrapped",
        "preset_id": "architect-review-execute",
    }
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "conversation": {"id": conv_id},
        "participants": {"total": 4, "summary": {"init": 1}},
        "collaboration": {"active_runs": 0, "runs": [], "dispatch_gates": []},
        "blockers": {"active": 0, "items": []},
        "dispatch_queue": {
            "queued": 0,
            "processing": 0,
            "dispatched": 0,
            "failed": 0,
            "entries": [],
        },
    }

    async with app.run_test() as pilot:
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: None
        input_widget = app.screen.query_one("#message-input")
        for command in (
            "/new Closure proof",
            "/resume conv-proof",
            "/overview",
            "/discussion",
            "/blockers",
        ):
            input_widget.value = command
            input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
            await pilot.pause()

    events = app.adapter.list_tui_command_events("conv-proof")
    assert [event["command"] for event in events] == [
        "/new",
        "/resume",
        "/overview",
        "/discussion",
        "/blockers",
    ]
    by_command = {event["command"]: event for event in events}
    assert by_command["/overview"]["read_surface_authority"] == "chat_inspector"
    assert by_command["/overview"]["surface_ref"] == "chat_inspector:conv-proof"
    assert {event["conversation_id"] for event in events} == {"conv-proof"}
    assert {event["terminal_run_id"] for event in events} == {"terminal-run-proof"}
    assert all(str(event.get("event_id") or "").startswith("tui_cmd_") for event in events)
    assert {
        event["read_surface_authority"] for event in events
    } <= {"chat_inspector", "dashboard_runtime_timeline"}
    assert all(
        event["surface_ref"]
        in {
            "chat_inspector:conv-proof",
            "dashboard_runtime_timeline:conv-proof",
        }
        for event in events
    )


async def test_chat_screen_terminal_demo_mode_records_runtime_commands(
    app: XmuseTUI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XMUSE_TUI_TERMINAL_RUN_ID", "terminal-run-demo")
    monkeypatch.setenv("XMUSE_TUI_DEMO_CONVERSATION_ID", "conv-demo")
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-demo",
            "title": "Demo",
            "created_at": "2026-06-05T00:00:00Z",
        }
    ]
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "conversation": {"id": conv_id},
        "participants": {"total": 4, "summary": {"init": 1}},
        "collaboration": {"active_runs": 0, "runs": [], "dispatch_gates": []},
        "blockers": {"active": 0, "items": []},
        "dispatch_queue": {
            "queued": 0,
            "processing": 0,
            "dispatched": 1,
            "failed": 0,
            "entries": [
                {
                    "entry_id": "dispatch-demo",
                    "status": "dispatched",
                    "dispatch_evidence": "mcp_writeback:inbox-demo",
                }
            ],
        },
        "peer_latency": {
            "recent_turns": [
                {
                    "inbox_item_id": "inbox-demo",
                    "delivery_mode": "mcp_writeback",
                }
            ]
        },
    }

    async with app.run_test() as pilot:
        await pilot.pause(1.6)

    events = app.adapter.list_tui_command_events("conv-demo")
    assert [event["command"] for event in events] == [
        "/resume",
        "/overview",
        "/discussion",
        "/blockers",
    ]
    assert {event["terminal_run_id"] for event in events} == {"terminal-run-demo"}


async def test_chat_screen_records_tui_command_proof_through_official_chat_api(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))
    tui = XmuseTUI(xmuse_root=tmp_path)
    tui.adapter = XmuseAdapter(
        tmp_path,
        chat_api_base_url="http://testserver",
        chat_api_client_factory=lambda timeout: _NoCloseClient(client),
    )
    tui.adapter.poll_delta = _empty_delta
    tui.adapter.sync = _empty_delta
    tui.action_refresh_now = lambda: None

    async with tui.run_test() as pilot:
        log = tui.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: None
        input_widget = tui.screen.query_one("#message-input")
        input_widget.value = "/new Official API proof"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        conversation_id = str(tui.state.active_conversation_id or "")
        for command in (
            f"/resume {conversation_id}",
            "/overview",
            "/discussion",
            "/blockers",
        ):
            input_widget.value = command
            input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
            await pilot.pause()

    conversations = PeerChatService(tmp_path / "chat.db").list_conversations()[
        "conversations"
    ]
    assert len(conversations) == 1
    conversation_id = conversations[0]["id"]
    bootstrap = PeerChatService(tmp_path / "chat.db").get_bootstrap_status(
        conversation_id
    )
    assert bootstrap["status"] == "proposal_ready"
    events = tui.adapter.list_tui_command_events(conversation_id)
    assert [event["command"] for event in events] == [
        "/new",
        "/resume",
        "/overview",
        "/discussion",
        "/blockers",
    ]
    assert {event["conversation_id"] for event in events} == {conversation_id}
    assert all(event["read_surface_authority"] == "chat_inspector" for event in events)
    assert {event["surface_ref"] for event in events} == {
        f"chat_inspector:{conversation_id}"
    }


async def test_chat_screen_does_not_record_tui_command_proof_for_unavailable_read_surface(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-proof",
            "title": "Closure proof",
            "created_at": "2026-06-05T00:00:00Z",
        }
    ]
    app.adapter.get_conversation_inspector = lambda conv_id: None

    async with app.run_test() as pilot:
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: None
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/discussion"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

    assert app.adapter.list_tui_command_events("conv-proof") == []


async def test_chat_screen_new_command_does_not_record_proof_when_inspector_unavailable(
    app: XmuseTUI,
) -> None:
    groups = []

    def _create_group(title: str, **kwargs):
        group = {
            "id": "conv-proof",
            "title": title,
            "created_at": "2026-06-05T00:00:00Z",
            "participants": [],
            "bootstrap": {"status": "proposal_ready"},
        }
        groups.append(group)
        return group

    app.adapter.list_group_conversations = lambda: list(groups)
    app.adapter.create_group_conversation = _create_group
    app.adapter.get_conversation_inspector = lambda conv_id: None

    async with app.run_test() as pilot:
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: None
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/new Closure proof"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

    assert app.state.active_conversation_id == "conv-proof"
    assert app.adapter.list_tui_command_events("conv-proof") == []


async def test_app_copy_selection_copies_selected_text(app: XmuseTUI) -> None:
    copied = []

    async with app.run_test() as pilot:
        app.screen.get_selected_text = lambda: "selected chat text"
        app._copy_text_to_clipboard = lambda text: copied.append(text)

        await pilot.press("ctrl+c")

        assert copied == ["selected chat text"]


async def test_app_copy_selection_falls_back_to_screen_copy_text(app: XmuseTUI) -> None:
    copied = []

    async with app.run_test() as pilot:
        app.screen.get_selected_text = lambda: ""
        app.screen.get_copy_text_for_clipboard = lambda: "whole visible transcript"
        app._copy_text_to_clipboard = lambda text: copied.append(text)

        await pilot.press("ctrl+c")

        assert copied == ["whole visible transcript"]


async def test_chat_screen_copy_command_opens_plain_text_copy_view(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]

    async with app.run_test() as pilot:
        app.state.messages = {
            "conv-user": [
                {
                    "author": "user",
                    "role": "human",
                    "content": "please improve TUI",
                    "created_at": "2026-06-02T00:00:00Z",
                },
                {
                    "author": "architect-god",
                    "role": "assistant",
                    "content": "I will turn that into a blueprint.",
                    "created_at": "2026-06-02T00:00:01Z",
                },
            ]
        }
        app.state.cards = {
            "conv-user": [
                {
                    "card_type": "peer_pending",
                    "title": "Architect GOD is thinking",
                    "summary": "Architect GOD 正在处理这条消息。",
                    "status": "pending",
                }
            ]
        }

        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/copy"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        copy_view = app.screen.query_one("#copy-view")
        assert copy_view.display is True
        assert copy_view.read_only is True
        assert "user: please improve TUI" in copy_view.text
        assert "architect-god: I will turn that into a blueprint." in copy_view.text


async def test_chat_screen_exposes_active_transcript_for_clipboard(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.state.messages = {
        "conv-user": [
            {
                "author": "user",
                "role": "human",
                "content": "copy this without selecting",
                "created_at": "2026-06-02T00:00:00Z",
            }
        ]
    }

    async with app.run_test():
        text = app.screen.get_copy_text_for_clipboard()

        assert "user: copy this without selecting" in text


async def test_chat_screen_clipboard_prefers_display_author(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.state.messages = {
        "conv-user": [
            {
                "author": "part_bec4c9a0ab3f430e896ed953addc0be3",
                "display_author": "architect-god",
                "role": "assistant",
                "content": "在。",
                "created_at": "2026-06-02T00:00:00Z",
            }
        ]
    }

    async with app.run_test():
        text = app.screen.get_copy_text_for_clipboard()

        assert "architect-god: 在。" in text
        assert "part_bec4c9a0ab3f430e896ed953addc0be3" not in text


async def test_chat_screen_copy_view_prefers_selected_text(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.state.messages = {
        "conv-user": [
            {
                "author": "user",
                "role": "human",
                "content": "first line\nsecond line",
                "created_at": "2026-06-02T00:00:00Z",
            }
        ]
    }

    async with app.run_test() as pilot:
        await pilot.press("ctrl+y")
        copy_view = app.screen.query_one("#copy-view")
        copy_view.select_all()

        assert app.screen.get_selected_text() == copy_view.text


async def test_ctrl_y_toggles_copy_view(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-user",
            "title": "User group",
            "created_at": "2026-06-01T00:00:00Z",
        },
    ]
    app.state.messages = {
        "conv-user": [
            {
                "author": "user",
                "role": "human",
                "content": "copy this",
                "created_at": "2026-06-02T00:00:00Z",
            }
        ]
    }

    async with app.run_test() as pilot:
        await pilot.press("ctrl+y")
        copy_view = app.screen.query_one("#copy-view")
        assert copy_view.display is True
        assert "copy this" in copy_view.text

        await pilot.press("ctrl+y")
        assert copy_view.display is False


async def test_chat_screen_clears_message_log_when_switching_conversation(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-01T00:00:00Z"},
        {"id": "conv-b", "title": "B", "created_at": "2026-06-02T00:00:00Z"},
    ]

    async with app.run_test():
        cleared = []
        log = app.screen.query_one("#message-log")
        log.clear = lambda: cleared.append(True)

        app.screen._activate_conversation("conv-a")

        assert app.state.active_conversation_id == "conv-a"
        assert cleared == [True]


async def test_chat_screen_tick_renders_worklist_summary(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-new",
            "title": "New conversation",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]

    async def _poll_delta(conv_id: str | None = None) -> StateDelta:
        return StateDelta(
            features={"TUI": {"merged": 1, "total": 1}},
            lanes=[
                {
                    "lane_id": "lane-tui",
                    "lane_local_id": "TUI-01",
                    "feature_label": "Visible worklist",
                    "effective_status": "merged",
                }
            ],
            lanes_changed=True,
        )

    app.adapter.poll_delta = _poll_delta

    async with app.run_test() as pilot:
        await app._tick()
        await pilot.pause()

        task_list = app.screen.query_one("#task-list", ListView)
        detail = app.screen.query_one("#task-detail", Static).renderable
        assert len(task_list.children) == 1
        assert "TUI-01" in str(detail)
        assert "Visible worklist" in str(detail)


async def test_chat_screen_right_panel_shows_workbench_lists_and_detail_surfaces(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-new",
            "title": "New conversation",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]
    app.adapter.get_workbench_lane_detail = lambda conv_id, lane_id: {
        "task": {
            "lane_id": lane_id,
            "lane_local_id": "TUI-01",
            "plan_feature_id": "TUI",
            "feature_label": "Closure workbench",
            "effective_status": "ready",
            "priority": 2,
            "scoped_dependency_ids": ["TUI-00"],
        },
        "execution_log": {
            "events": [
                {
                    "event_id": "evt-1",
                    "event_type": "dispatch",
                    "title": "Dispatch",
                    "summary": "Queued for execute",
                    "status": "ready",
                    "created_at": "2026-06-05T00:00:00Z",
                }
            ]
        },
    }

    async with app.run_test() as pilot:
        app.state.active_conversation_id = "conv-new"
        app.state.features = {"TUI": {"merged": 1, "total": 2}}
        app.state.lanes = [
            {
                "lane_id": "lane-workbench",
                "lane_local_id": "TUI-01",
                "plan_feature_id": "TUI",
                "feature_label": "Closure workbench",
                "effective_status": "ready",
            }
        ]
        app.state.cards["conv-new"] = [
            {
                "id": "card_inbox_pending_inbox-1",
                "conversation_id": "conv-new",
                "card_type": "peer_pending",
                "source_id": "inbox-1",
                "title": "Architect GOD is thinking",
                "summary": "Architect GOD 正在处理这条消息。",
                "status": "pending",
                "created_at": "2026-06-05T00:00:01Z",
                "metadata": {"target_role": "architect"},
            }
        ]
        app.screen.on_state_updated(StateUpdated(app.state))
        await pilot.pause()

        inbox_list = app.screen.query_one("#inbox-list", ListView)
        task_list = app.screen.query_one("#task-list", ListView)
        task_detail = app.screen.query_one("#task-detail", Static).renderable
        execution_log = app.screen.query_one("#execution-log", Static).renderable
        assert len(inbox_list.children) == 1
        assert len(task_list.children) == 1
        assert "Closure workbench" in str(task_detail)
        assert "Queued for execute" in str(execution_log)


async def test_chat_screen_rerenders_replaced_peer_status_card(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {
            "id": "conv-new",
            "title": "New conversation",
            "created_at": "2026-06-02T00:00:00Z",
        },
    ]
    deltas = [
        StateDelta(
            cards=[
                {
                    "id": "card_inbox_route_inbox-1",
                    "conversation_id": "conv-new",
                    "card_type": "peer_route_status",
                    "source_id": "inbox-1",
                    "title": "Routed to Architect GOD",
                    "summary": "已路由给 Architect GOD，等待处理。",
                    "status": "routed",
                }
            ]
        ),
        StateDelta(
            cards=[
                {
                    "id": "card_inbox_pending_inbox-1",
                    "conversation_id": "conv-new",
                    "card_type": "peer_pending",
                    "source_id": "inbox-1",
                    "title": "Architect GOD is thinking",
                    "summary": "Architect GOD 正在处理这条消息。",
                    "status": "pending",
                }
            ]
        ),
    ]

    async def _poll_delta(conv_id: str | None = None) -> StateDelta:
        return deltas.pop(0)

    app.adapter.poll_delta = _poll_delta

    async with app.run_test() as pilot:
        await app._tick()
        await app._tick()
        await pilot.pause()

        text = app.screen.get_copy_text_for_clipboard()
        assert "Architect GOD is thinking" in text
        assert "Routed to Architect GOD" not in text


async def test_switch_to_board_and_back(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        assert "Board" in type(app.screen).__name__
        await pilot.press("ctrl+1")
        assert "Chat" in type(app.screen).__name__


async def test_chat_screen_new_command_uses_bootstrap_contract(app: XmuseTUI) -> None:
    calls = []

    def _create_group(title: str, **kwargs):
        calls.append((title, kwargs))
        return {
            "id": "conv-created",
            "title": title,
            "created_at": "2026-06-04T00:00:00Z",
            "participants": [],
            "bootstrap": {"status": "proposal_ready"},
        }

    app.adapter.create_group_conversation = _create_group
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-created", "title": "Product planning", "created_at": "2026-06-04T00:00:00Z"}
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/new Product planning"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert calls == [
            (
                "Product planning",
                {"preset_id": "architect-review-execute", "init_mode": "proposal_then_approve"},
            )
        ]
        assert app.state.active_conversation_id == "conv-created"
        assert "proposal_ready" in appended[-1]["content"]


async def test_chat_screen_init_status_retry_apply_commands(app: XmuseTUI) -> None:
    app.state.active_conversation_id = "conv-1"
    app.adapter.get_bootstrap_status = lambda conv_id: {
        "status": "proposal_ready", "conversation_id": conv_id
    }
    app.adapter.create_bootstrap_proposal = lambda conv_id: {
        "proposal": {"proposal_id": "proposal-1"},
        "status": "proposal_ready",
    }
    app.adapter.apply_bootstrap_proposal = lambda conv_id, proposal_id: {
        "bootstrap": {"status": "bootstrapped", "proposal_id": proposal_id},
        "participants": [{"role": "architect"}],
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")

        input_widget.value = "/init status"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "proposal_ready" in appended[-1]["content"]

        input_widget.value = "/init retry"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "proposal-1" in appended[-1]["content"]

        input_widget.value = "/init apply proposal-1"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "bootstrapped" in appended[-1]["content"]


async def test_chat_screen_approve_latest_open_proposal(app: XmuseTUI) -> None:
    app.state.active_conversation_id = "conv-1"
    app.adapter.get_conversation_inspector = lambda conv_id: {
        "artifacts": {
            "items": [
                {"type": "proposal", "id": "proposal-old", "status": "accepted"},
                {"type": "proposal", "id": "proposal-open", "status": "open"},
            ]
        }
    }
    approved = []

    def _approve(proposal_id: str, **kwargs):
        approved.append((proposal_id, kwargs))
        return {"id": "resolution-1", "status": "approved"}

    app.adapter.approve_proposal = _approve

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")

        input_widget.value = "/approve"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert approved == [
            (
                "proposal-open",
                {
                    "approved_by": "human",
                    "approval_mode": "manual",
                    "goal_summary": "Approve proposal proposal-open from TUI",
                },
            )
        ]
        assert "Approved proposal proposal-open -> resolution resolution-1" in appended[-1][
            "content"
        ]


async def test_chat_screen_approve_shows_dispatch_gate_error(app: XmuseTUI) -> None:
    app.state.active_conversation_id = "conv-1"
    app.adapter.approve_proposal = lambda proposal_id, **kwargs: {
        "error": {
            "code": "dispatch_gate_blocked",
            "message": "blocked_execute_not_confirmed",
        },
        "proposal_id": proposal_id,
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")

        input_widget.value = "/approve proposal-1"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert (
            "Approval blocked for proposal-1: "
            "dispatch_gate_blocked: blocked_execute_not_confirmed"
        ) in appended[-1]["content"]


async def test_chat_screen_worklist_summary_shows_feature_progress_and_lane_scan(
    app: XmuseTUI,
) -> None:
    app.adapter.get_workbench_lane_detail = lambda conv_id, lane_id: {
        "task": {
            "lane_id": lane_id,
            "lane_local_id": "T1-01",
            "plan_feature_id": "T1",
            "feature_label": "Schema contract",
            "effective_status": "merged",
            "priority": 1,
            "scoped_dependency_ids": [],
        },
        "execution_log": {
            "events": [
                {
                    "event_id": "evt-1",
                    "event_type": "dispatch",
                    "title": "Dispatch",
                    "summary": "merged -> execute",
                    "status": "merged",
                    "created_at": "2026-06-05T00:00:00Z",
                }
            ]
        },
    }

    async with app.run_test():
        app.state.active_conversation_id = "conv-1"
        app.state.features = {
            "T1": {"merged": 1, "total": 2},
            "T2": {"merged": 0, "total": 1},
        }
        app.state.lanes = [
            {
                "lane_id": "lane-conv-1-schema",
                "lane_local_id": "T1-01",
                "plan_feature_id": "T1",
                "feature_label": "Schema contract",
                "effective_status": "merged",
            },
            {
                "lane_id": "lane-conv-1-ui",
                "lane_local_id": "T1-02",
                "plan_feature_id": "T1",
                "feature_label": "Chat worklist clarity",
                "effective_status": "ready",
            },
        ]

        app.screen.on_state_updated(StateUpdated(app.state))

        task_list = app.screen.query_one("#task-list", ListView)
        task_detail = app.screen.query_one("#task-detail", Static).renderable
        assert len(task_list.children) == 2
        assert "Schema contract" in str(task_detail)
        assert "merged" in str(task_detail)


async def test_chat_screen_task_selection_updates_detail_and_execution_log(
    app: XmuseTUI,
) -> None:
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-1", "title": "Conversation", "created_at": "2026-06-05T00:00:00Z"}
    ]

    def _detail(conv_id: str, lane_id: str):
        return {
            "task": {
                "lane_id": lane_id,
                "lane_local_id": "T1-02" if lane_id == "lane-2" else "T1-01",
                "plan_feature_id": "T1",
                "feature_label": "Execution log surface" if lane_id == "lane-2" else "Schema",
                "effective_status": "ready" if lane_id == "lane-2" else "merged",
                "priority": 2,
                "scoped_dependency_ids": ["T1-01"] if lane_id == "lane-2" else [],
            },
            "execution_log": {
                "events": [
                    {
                        "event_id": f"evt-{lane_id}",
                        "event_type": "dispatch",
                        "title": "Dispatch",
                        "summary": f"{lane_id} -> execute",
                        "status": "ready",
                        "created_at": "2026-06-05T00:00:00Z",
                    }
                ]
            },
        }

    app.adapter.get_workbench_lane_detail = _detail

    async with app.run_test() as pilot:
        app.state.active_conversation_id = "conv-1"
        app.state.lanes = [
            {
                "lane_id": "lane-1",
                "lane_local_id": "T1-01",
                "plan_feature_id": "T1",
                "feature_label": "Schema",
                "effective_status": "merged",
            },
            {
                "lane_id": "lane-2",
                "lane_local_id": "T1-02",
                "plan_feature_id": "T1",
                "feature_label": "Execution log surface",
                "effective_status": "ready",
            },
        ]
        app.screen.on_state_updated(StateUpdated(app.state))
        task_list = app.screen.query_one("#task-list", ListView)
        second_item = task_list.children[1]
        task_list.post_message(ListView.Selected(task_list, second_item, 1))
        await pilot.pause()

        task_detail = app.screen.query_one("#task-detail", Static).renderable
        execution_log = app.screen.query_one("#execution-log", Static).renderable
        assert "Execution log surface" in str(task_detail)
        assert "lane-2 -> execute" in str(execution_log)


async def test_lane_detail_screen_uses_workbench_detail_contract(app: XmuseTUI) -> None:
    app.adapter.get_lane = lambda lane_id: (_ for _ in ()).throw(AssertionError("legacy get_lane"))
    app.adapter.get_workbench_lane_detail = lambda conv_id, lane_id: {
        "task": {
            "lane_id": lane_id,
            "lane_local_id": "T1-03",
            "plan_feature_id": "T1",
            "feature_label": "Authoritative detail",
            "effective_status": "dispatched",
            "priority": 4,
            "scoped_dependency_ids": ["T1-02"],
        },
        "execution_log": {
            "events": [
                {
                    "event_id": "evt-detail",
                    "event_type": "dispatch",
                    "title": "Dispatch",
                    "summary": "lane-detail -> execute",
                    "status": "dispatched",
                    "created_at": "2026-06-05T00:00:00Z",
                }
            ]
        },
    }
    app.state.active_conversation_id = "conv-1"

    async with app.run_test() as pilot:
        app.push_screen(LaneDetailScreen("lane-3"))
        await pilot.pause()

        content = app.screen.query_one("#lane-content", Static).renderable
        assert "Authoritative detail" in str(content)
        assert "lane-detail -> execute" in str(content)
