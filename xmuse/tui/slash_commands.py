from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SlashCommandResult:
    handled: bool
    refresh: bool = False
    message: str | None = None


@dataclass
class SlashCommandContext:
    app: Any
    screen: Any


@dataclass
class SlashCommandRouter:
    _last_sessions: list[dict] = field(default_factory=list)

    def dispatch(self, content: str, context: SlashCommandContext) -> SlashCommandResult:
        text = content.strip()
        if not text.startswith("/"):
            return SlashCommandResult(handled=False)
        command, _, rest = text[1:].partition(" ")
        command = command.strip().lower()
        rest = rest.strip()

        if command == "help":
            return SlashCommandResult(True, message=_help_text())
        if command == "sessions":
            return self._sessions(rest, context)
        if command == "resume":
            return self._resume(rest, context)
        if command == "new":
            return self._new(rest, context)
        if command == "init":
            return self._init(rest, context)
        if command == "approve":
            return self._approve(rest, context)
        if command == "where":
            return self._where(context)
        if command == "participants":
            return self._participants(context)
        if command == "discussion":
            return self._discussion(context)
        if command == "blockers":
            return self._blockers(context)
        if command == "overview":
            return self._overview(context)
        if command == "dashboard":
            return self._overview(context)
        if command == "evidence":
            return self._evidence(rest, context)
        if command == "release":
            return self._release(rest, context)
        if command == "lane":
            return self._lane(rest, context)
        if command == "freeze":
            return self._freeze(rest, context)
        if command == "god":
            return self._god(rest, context)
        if command == "archive":
            context.screen.action_toggle_archive()
            return SlashCommandResult(True)
        if command == "copy":
            context.screen.action_toggle_copy_view()
            return SlashCommandResult(True)
        return SlashCommandResult(
            True,
            message=f"Unknown command: /{command}. Try /help.",
        )

    def _sessions(self, target: str, context: SlashCommandContext) -> SlashCommandResult:
        if target:
            return self._switch_session(target, context, command_name="/sessions")
        sessions = _session_rows(context.app)
        self._last_sessions = sessions
        if not sessions:
            return SlashCommandResult(True, message="No group sessions.")
        lines = ["Sessions:"]
        for index, session in enumerate(sessions, start=1):
            marker = (
                "*"
                if _conversation_id(session) == context.app.state.active_conversation_id
                else " "
            )
            lines.append(
                f"{index}. {_conversation_title(session)} ({_conversation_id(session)}) {marker}"
            )
        return SlashCommandResult(True, message="\n".join(lines))

    def _resume(self, target: str, context: SlashCommandContext) -> SlashCommandResult:
        if not target:
            sessions = _session_rows(context.app)
            if not sessions:
                return SlashCommandResult(True, message="No group sessions to resume.")
            most_recent = sessions[0]
            conv_id = _conversation_id(most_recent)
            context.screen.activate_conversation(conv_id, refresh=False)
            context.screen.refresh_conversation_list()
            title = _conversation_title(most_recent)
            _record_resume_command_event_if_available(context, conv_id)
            return SlashCommandResult(
                True,
                refresh=True,
                message=f"Resumed most recent session: {title} ({conv_id})",
            )
        return self._switch_session(target, context, command_name="/resume")

    def _switch_session(
        self,
        target: str,
        context: SlashCommandContext,
        *,
        command_name: str,
    ) -> SlashCommandResult:
        sessions = self._last_sessions or _session_rows(context.app)
        match = _resolve_session(target, sessions)
        if match is None and command_name == "/resume":
            match = _resolve_session(target, context.app.adapter.list_conversations())
        if isinstance(match, list):
            lines = ["Ambiguous session title. Candidates:"]
            for session in match:
                lines.append(f"- {_conversation_title(session)} ({_conversation_id(session)})")
            return SlashCommandResult(True, message="\n".join(lines))
        if match is None:
            return SlashCommandResult(True, message=f"No session matches: {target}")
        conv_id = _conversation_id(match)
        context.screen.activate_conversation(conv_id, refresh=False)
        context.screen.refresh_conversation_list()
        if command_name == "/resume":
            _record_resume_command_event_if_available(context, conv_id)
        return SlashCommandResult(
            True,
            refresh=True,
            message=f"Switched to {_conversation_title(match)} ({conv_id}) via {command_name}",
        )

    def _new(self, title: str, context: SlashCommandContext) -> SlashCommandResult:
        if not title:
            return SlashCommandResult(True, message="Usage: /new <title>")
        created = context.app.adapter.create_group_conversation(
            title,
            preset_id="architect-review-execute",
            init_mode="proposal_then_approve",
        )
        if not created:
            return SlashCommandResult(True, message=f"Could not create group: {title}")
        conv_id = str(created.get("id") or created.get("conversation_id") or "")
        if not conv_id:
            return SlashCommandResult(True, message="Created group did not include an id.")
        context.screen.archive_mode = False
        context.screen.activate_conversation(conv_id, refresh=False)
        context.screen.refresh_conversation_list()
        _refresh_participants(context, conv_id)
        self._last_sessions = _session_rows(context.app)
        bootstrap = created.get("bootstrap") if isinstance(created, dict) else {}
        status = bootstrap.get("status") if isinstance(bootstrap, dict) else "unknown"
        proposal_id = bootstrap.get("proposal_id") if isinstance(bootstrap, dict) else None
        participant_plan = (
            bootstrap.get("participant_plan")
            if isinstance(bootstrap, dict)
            else None
        )
        if status == "proposal_ready" and proposal_id:
            roles = (
                " / ".join(str(role) for role in participant_plan)
                if isinstance(participant_plan, list)
                else "configured peer roles"
            )
            message = (
                f"Created group {_conversation_title(created)} ({conv_id}); "
                f"init-god prepared {roles}. "
                f"Confirm with /init apply {proposal_id}, or use /init retry."
            )
        else:
            message = (
                f"Created group {_conversation_title(created)} ({conv_id}); "
                f"bootstrap={status}"
            )
        inspector = context.app.adapter.get_conversation_inspector(conv_id)
        if _has_new_read_surface(inspector, conv_id):
            _record_official_tui_command_event(
                context,
                command="/new",
                conversation_id=conv_id,
                read_surface_authority="chat_inspector",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=message,
        )

    def _init(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        parts = rest.split()
        action = parts[0] if parts else "status"
        if action == "status":
            status = context.app.adapter.get_bootstrap_status(conv_id)
            return SlashCommandResult(True, message=f"Bootstrap status: {status or 'unknown'}")
        if action == "retry":
            proposal = context.app.adapter.create_bootstrap_proposal(conv_id)
            if not proposal:
                return SlashCommandResult(True, message="Could not create bootstrap proposal.")
            proposal_id = str((proposal.get("proposal") or {}).get("proposal_id") or "")
            return SlashCommandResult(True, message=f"Bootstrap proposal ready: {proposal_id}")
        if action == "apply":
            if len(parts) < 2:
                return SlashCommandResult(True, message="Usage: /init apply <proposal_id>")
            applied = context.app.adapter.apply_bootstrap_proposal(conv_id, parts[1])
            if not applied:
                return SlashCommandResult(
                    True,
                    message=f"Could not apply bootstrap proposal: {parts[1]}",
                )
            bootstrap = applied.get("bootstrap") if isinstance(applied, dict) else {}
            status = bootstrap.get("status") if isinstance(bootstrap, dict) else "unknown"
            _refresh_participants(context, conv_id)
            return SlashCommandResult(True, refresh=True, message=f"Bootstrap apply: {status}")
        parts_str = " | ".join(["/init status", "/init retry", "/init apply <proposal_id>"])
        return SlashCommandResult(True, message=f"Usage: {parts_str}")

    def _approve(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        target = rest.strip() or "latest"
        proposal_id = target
        if target == "latest":
            inspector = context.app.adapter.get_conversation_inspector(conv_id)
            proposal_id = _latest_open_proposal_id(inspector) or ""
            if not proposal_id:
                return SlashCommandResult(True, message="No open proposal found for this group.")
        result = context.app.adapter.approve_proposal(
            proposal_id,
            approved_by="human",
            approval_mode="manual",
            goal_summary=f"Approve proposal {proposal_id} from TUI",
        )
        if not result:
            return SlashCommandResult(True, message=f"Could not approve proposal: {proposal_id}")
        error = result.get("error") if isinstance(result, dict) else None
        if error:
            return SlashCommandResult(
                True,
                message=f"Approval blocked for {proposal_id}: {_format_approval_error(error)}",
            )
        resolution_id = str(result.get("id") or result.get("resolution_id") or "")
        suffix = f" -> resolution {resolution_id}" if resolution_id else ""
        _record_official_tui_command_event(
            context,
            command="/approve",
            conversation_id=conv_id,
            read_surface_authority="chat_api",
        )
        return SlashCommandResult(
            True,
            refresh=True,
            message=f"Approved proposal {proposal_id}{suffix}.",
        )

    def _where(self, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        title = context.screen.conversation_title(conv_id)
        participants = _participants_for_context(context, conv_id)
        return SlashCommandResult(
            True,
            message=(
                f"Current group: {title} ({conv_id})\n"
                f"Participants: {_participant_inline(participants)}"
            ),
        )

    def _participants(self, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        participants = _participants_for_context(context, conv_id)
        return SlashCommandResult(True, message=_participant_block(participants))

    def _discussion(self, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        inspector = context.app.adapter.get_conversation_inspector(conv_id)
        if _has_read_surface_section(inspector, "collaboration"):
            _record_official_tui_command_event(
                context,
                command="/discussion",
                conversation_id=conv_id,
                read_surface_authority="chat_inspector",
            )
        return SlashCommandResult(True, message=_discussion_block(inspector))

    def _blockers(self, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        inspector = context.app.adapter.get_conversation_inspector(conv_id)
        if _has_read_surface_section(inspector, "blockers"):
            _record_official_tui_command_event(
                context,
                command="/blockers",
                conversation_id=conv_id,
                read_surface_authority="chat_inspector",
            )
        return SlashCommandResult(True, message=_blockers_block(inspector))

    def _overview(self, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        inspector = context.app.adapter.get_conversation_inspector(conv_id)
        bootstrap = context.app.adapter.get_bootstrap_status(conv_id)
        title = context.screen.conversation_title(conv_id)
        if _has_overview_read_surface(inspector):
            _record_official_tui_command_event(
                context,
                command="/overview",
                conversation_id=conv_id,
                read_surface_authority="chat_inspector",
            )
        return SlashCommandResult(
            True,
            message=_overview_block(
                inspector,
                bootstrap=bootstrap,
                conversation_id=conv_id,
                title=title,
            ),
        )

    def _evidence(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        action = rest.strip() or "transcript"
        if action not in {"transcript", "github", "memory", "blockers"}:
            return SlashCommandResult(
                True,
                message="Usage: /evidence <transcript|github|memory|blockers>",
            )
        runner = getattr(context.app.adapter, "run_operator_evidence_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Evidence actions unavailable for this adapter.",
            )
        result = runner(action, conv_id)
        if isinstance(result, dict):
            _record_official_tui_command_event(
                context,
                command=f"/evidence {action}",
                conversation_id=conv_id,
                read_surface_authority="operator_evidence_action",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_evidence_action_block(result if isinstance(result, dict) else {}),
        )

    def _release(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        try:
            parts = shlex.split(rest)
        except ValueError as exc:
            return SlashCommandResult(True, message=f"Invalid /release command: {exc}")
        if parts in (["pack"], ["evidence-pack"], ["evidence"]):
            action = "capture_release_evidence_pack"
            command = "/release pack"
        elif parts in (["refresh"], ["status"], ["live-gate-status"]):
            action = "refresh_live_gate_status"
            command = "/release refresh"
        else:
            return SlashCommandResult(True, message="Usage: /release <refresh|pack>")
        runner = getattr(context.app.adapter, "run_operator_control_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Operator control actions unavailable for this adapter.",
            )
        result = runner(action, conv_id, {})
        if isinstance(result, dict):
            _record_official_tui_command_event(
                context,
                command=command,
                conversation_id=conv_id,
                read_surface_authority="operator_action_contract",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_operator_action_block(result if isinstance(result, dict) else {}),
        )

    def _lane(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        try:
            parts = shlex.split(rest)
        except ValueError as exc:
            return SlashCommandResult(True, message=f"Invalid /lane command: {exc}")
        if len(parts) < 3 or parts[0] not in {"retry", "abort"}:
            return SlashCommandResult(
                True,
                message=(
                    "Usage: /lane retry <lane_id> <current_status> [reason] | "
                    "/lane abort <lane_id> <current_status> [reason]"
                ),
            )
        runner = getattr(context.app.adapter, "run_operator_control_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Operator control actions unavailable for this adapter.",
            )
        verb = parts[0]
        lane_id = parts[1]
        current_status = parts[2]
        reason = " ".join(parts[3:]).strip()
        action = "retry_lane" if verb == "retry" else "abort_lane"
        payload = {
            "lane_id": lane_id,
            "current_status": current_status,
        }
        if reason:
            payload["reason"] = reason
        result = runner(action, conv_id, payload)
        if isinstance(result, dict):
            _record_official_tui_command_event(
                context,
                command=f"/lane {verb} {lane_id}",
                conversation_id=conv_id,
                read_surface_authority="operator_action_contract",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_operator_action_block(result if isinstance(result, dict) else {}),
        )

    def _freeze(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        runner = getattr(context.app.adapter, "run_operator_control_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Operator control actions unavailable for this adapter.",
            )
        try:
            parts = shlex.split(rest)
            payload = _freeze_payload(parts)
        except ValueError as exc:
            return SlashCommandResult(True, message=str(exc))
        result = runner("freeze_blueprint", conv_id, payload)
        if isinstance(result, dict):
            _record_official_tui_command_event(
                context,
                command="/freeze",
                conversation_id=conv_id,
                read_surface_authority="operator_action_contract",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_operator_action_block(result if isinstance(result, dict) else {}),
        )

    def _god(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        try:
            parts = shlex.split(rest)
        except ValueError as exc:
            return SlashCommandResult(True, message=f"Invalid /god command: {exc}")
        if not parts or parts[0] not in {"add", "rm", "register", "select"}:
            return SlashCommandResult(
                True,
                message=(
                    "Usage: /god add <role> [display name] | "
                    "/god rm <role|participant_id> | /god register <key=value...> | "
                    "/god select <cli_id>"
                ),
            )
        if parts[0] == "register":
            if len(parts) < 2:
                return SlashCommandResult(
                    True,
                    message="Usage: /god register <key=value...>",
                )
            return self._god_register(parts[1:], context)
        if parts[0] == "select":
            if len(parts) < 2:
                return SlashCommandResult(True, message="Usage: /god select <cli_id>")
            return self._god_select(parts[1:], context)
        if len(parts) < 2:
            return SlashCommandResult(
                True,
                message=(
                    "Usage: /god add <role> [display name] | "
                    "/god rm <role|participant_id> | /god register <key=value...> | "
                    "/god select <cli_id>"
                ),
            )
        if parts[0] == "add":
            return self._god_add(parts[1:], context)
        return self._god_rm(parts[1:], context)

    def _god_add(self, args: list[str], context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        role = args[0]
        display_name = " ".join(args[1:]) or None
        role_template_id = None
        if role not in {"architect", "review", "execute"}:
            template = _find_role_template(context.app.adapter.list_role_templates(), role)
            if template is None:
                return SlashCommandResult(
                    True,
                    message=f"No role template found for custom GOD role: {role}",
                )
            role_template_id = str(template.get("id") or "")
        participant = context.app.adapter.add_participant(
            conv_id,
            role,
            display_name=display_name,
            role_template_id=role_template_id,
        )
        if not participant:
            return SlashCommandResult(True, message=f"Could not add GOD {role}.")
        _refresh_participants(context, conv_id)
        return SlashCommandResult(True, refresh=True, message=f"Added GOD {role}.")

    def _god_rm(self, args: list[str], context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        target = args[0]
        if not context.app.adapter.remove_participant(conv_id, target):
            return SlashCommandResult(True, message=f"Could not remove GOD {target}.")
        _refresh_participants(context, conv_id)
        return SlashCommandResult(True, refresh=True, message=f"Removed GOD {target}.")

    def _god_register(
        self,
        args: list[str],
        context: SlashCommandContext,
    ) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        runner = getattr(context.app.adapter, "run_operator_control_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Operator control actions unavailable for this adapter.",
            )
        try:
            payload = _god_registration_payload(args)
        except ValueError as exc:
            return SlashCommandResult(True, message=str(exc))
        result = runner("register_god_cli", conv_id, payload)
        if isinstance(result, dict):
            cli_id = str(payload.get("cli_id") or "")
            _record_official_tui_command_event(
                context,
                command=f"/god register {cli_id}",
                conversation_id=conv_id,
                read_surface_authority="operator_action_contract",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_operator_action_block(result if isinstance(result, dict) else {}),
        )

    def _god_select(self, args: list[str], context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        runner = getattr(context.app.adapter, "run_operator_control_action", None)
        if not callable(runner):
            return SlashCommandResult(
                True,
                message="Operator control actions unavailable for this adapter.",
            )
        cli_id = args[0]
        result = runner("select_god_cli", conv_id, {"cli_id": cli_id})
        if isinstance(result, dict):
            _record_official_tui_command_event(
                context,
                command=f"/god select {cli_id}",
                conversation_id=conv_id,
                read_surface_authority="operator_action_contract",
            )
        return SlashCommandResult(
            True,
            refresh=True,
            message=_operator_action_block(result if isinstance(result, dict) else {}),
        )


def _session_rows(app: Any) -> list[dict]:
    rows = app.adapter.list_group_conversations()
    return sorted(rows, key=lambda conv: str(conv.get("created_at", "")), reverse=True)


def _resolve_session(target: str, sessions: list[dict]) -> dict | list[dict] | None:
    clean = target.strip()
    if clean.isdigit():
        index = int(clean)
        if 1 <= index <= len(sessions):
            return sessions[index - 1]
    for session in sessions:
        if _conversation_id(session) == clean:
            return session
    lowered = clean.lower()
    matches = [
        session
        for session in sessions
        if lowered in _conversation_title(session).lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return matches
    return None


def _active_conversation_id(context: SlashCommandContext) -> str | None:
    conv_id = context.app.state.active_conversation_id
    return str(conv_id) if conv_id else None


def _latest_open_proposal_id(inspector: dict | None) -> str | None:
    artifacts = inspector.get("artifacts") if isinstance(inspector, dict) else None
    items = artifacts.get("items") if isinstance(artifacts, dict) else None
    if not isinstance(items, list):
        return None
    for item in reversed(items):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "proposal":
            continue
        if item.get("status") not in {None, "open"}:
            continue
        proposal_id = str(item.get("id") or "").strip()
        if proposal_id:
            return proposal_id
    return None


def _format_approval_error(error: object) -> str:
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        if code and message:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return code
    return str(error)


def _conversation_id(conversation: dict) -> str:
    return str(conversation.get("conversation_id") or conversation.get("id") or "")


def _conversation_title(conversation: dict) -> str:
    return str(
        conversation.get("title")
        or conversation.get("name")
        or _conversation_id(conversation)
    )


def _refresh_participants(context: SlashCommandContext, conv_id: str) -> list[dict]:
    participants = context.app.adapter.get_participants(conv_id)
    context.app.state.participants[conv_id] = participants
    return participants


def _record_official_tui_command_event(
    context: SlashCommandContext,
    *,
    command: str,
    conversation_id: str,
    read_surface_authority: str,
) -> None:
    surface_ref = f"{read_surface_authority}:{conversation_id}"
    event = {
        "command": command,
        "conversation_id": conversation_id,
        "read_surface_authority": read_surface_authority,
        "surface_ref": surface_ref,
    }
    terminal_run_id = os.environ.get("XMUSE_TUI_TERMINAL_RUN_ID", "").strip()
    if terminal_run_id:
        event["terminal_run_id"] = terminal_run_id
    recorder = getattr(context.app.state, "record_tui_command_event", None)
    if callable(recorder):
        recorder(event)
    adapter_recorder = getattr(context.app.adapter, "record_tui_command_event", None)
    if callable(adapter_recorder):
        adapter_recorder(event)


def _record_resume_command_event_if_available(
    context: SlashCommandContext,
    conversation_id: str,
) -> None:
    inspector = context.app.adapter.get_conversation_inspector(conversation_id)
    if _has_new_read_surface(inspector, conversation_id) or _has_overview_read_surface(inspector):
        _record_official_tui_command_event(
            context,
            command="/resume",
            conversation_id=conversation_id,
            read_surface_authority="chat_inspector",
        )


def _god_registration_payload(args: list[str]) -> dict[str, Any]:
    raw = _key_value_args(args)
    if not raw:
        raise ValueError("Usage: /god register <key=value...>")
    aliases = {
        "id": "cli_id",
        "display": "display_name",
        "command": "command_family",
        "family": "command_family",
        "profile": "provider_profile_ref",
        "proof": "proof_level",
        "persistent": "supports_persistent_sessions",
        "mcp": "supports_mcp_writeback",
        "mcp_writeback": "supports_mcp_writeback",
        "state_write": "state_write_allowed",
        "speech": "allowed_speech_acts",
        "proof_ref": "proof_refs",
    }
    payload: dict[str, Any] = {}
    list_keys = {"capabilities", "allowed_speech_acts", "proof_refs"}
    bool_keys = {
        "supports_persistent_sessions",
        "supports_mcp_writeback",
        "state_write_allowed",
    }
    for key, value in raw.items():
        normalized_key = aliases.get(key, key)
        if normalized_key in list_keys:
            payload[normalized_key] = _comma_values(value)
        elif normalized_key in bool_keys:
            payload[normalized_key] = _bool_arg(value)
        else:
            payload[normalized_key] = value
    return payload


def _freeze_payload(args: list[str]) -> dict[str, Any]:
    raw = _key_value_args(args)
    if not raw:
        raise ValueError(
            "Usage: /freeze target_ref=<ref> blueprint_id=<id> "
            "goal=<goal> scope=<items> acceptance=<items>"
        )
    aliases = {
        "target": "target_ref",
        "id": "blueprint_id",
        "acceptance": "acceptance_contracts",
        "acceptance_contract": "acceptance_contracts",
        "repo_area": "repo_areas",
        "source_ref": "source_refs",
        "required": "required_commits",
        "commits": "required_commits",
        "window": "objection_window_lamports",
    }
    list_keys = {
        "scope",
        "constraints",
        "non_goals",
        "acceptance_contracts",
        "repo_areas",
        "open_questions",
        "source_refs",
    }
    int_keys = {"revision", "required_commits", "objection_window_lamports"}
    top_level_keys = {"target_ref", "required_commits", "objection_window_lamports"}
    payload: dict[str, Any] = {}
    blueprint: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = aliases.get(key, key)
        if normalized_key in int_keys:
            parsed: Any = int(value)
        elif normalized_key in list_keys:
            parsed = _comma_values(value)
        else:
            parsed = value
        if normalized_key in top_level_keys:
            payload[normalized_key] = parsed
        else:
            blueprint[normalized_key] = parsed
    if "target_ref" not in payload or not blueprint:
        raise ValueError(
            "Usage: /freeze target_ref=<ref> blueprint_id=<id> "
            "goal=<goal> scope=<items> acceptance=<items>"
        )
    payload["blueprint"] = blueprint
    return payload


def _key_value_args(args: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for arg in args:
        key, sep, value = arg.partition("=")
        clean_key = key.strip().lower().replace("-", "_")
        if not sep or not clean_key:
            raise ValueError("Usage: /god register <key=value...>")
        parsed[clean_key] = value.strip()
    return parsed


def _comma_values(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _bool_arg(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _has_read_surface_section(payload: dict | None, section: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return isinstance(payload.get(section), dict)


def _has_overview_read_surface(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        isinstance(payload.get(section), dict)
        for section in (
            "participants",
            "collaboration",
            "blockers",
            "dispatch_queue",
            "peer_latency",
        )
    )


def _has_new_read_surface(payload: dict | None, conv_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    conversation = payload.get("conversation")
    if not isinstance(conversation, dict):
        return False
    return str(conversation.get("id") or "") == conv_id


def _participants_for_context(context: SlashCommandContext, conv_id: str) -> list[dict]:
    participants = context.app.state.participants_for(conv_id)
    if participants:
        return participants
    return _refresh_participants(context, conv_id)


def _participant_inline(participants: list[dict]) -> str:
    if not participants:
        return "none"
    return ", ".join(
        (
            f"{participant.get('role', '?')}="
            f"{participant.get('display_name') or participant.get('participant_id') or '?'}"
        )
        for participant in participants
    )


def _participant_block(participants: list[dict]) -> str:
    if not participants:
        return "Participants: none"
    lines = ["Participants:"]
    for participant in participants:
        role = str(participant.get("role") or "?")
        name = str(participant.get("display_name") or participant.get("participant_id") or "?")
        model = str(participant.get("model") or "?")
        status = str(participant.get("status") or "?")
        participant_id = str(participant.get("participant_id") or participant.get("id") or "?")
        lines.append(f"- {role}: {name} [{status}] model={model} id={participant_id}")
    return "\n".join(lines)


def _evidence_action_block(result: dict) -> str:
    action = str(result.get("action") or "unknown")
    status = str(result.get("status") or "?")
    proof = str(result.get("proof_level") or "?")
    fact = str(result.get("fact_state") or "?")
    lines = [
        f"Evidence action: {action}",
        f"status={status} proof={proof} fact={fact}",
    ]
    artifact_path = str(result.get("artifact_path") or "").strip()
    if artifact_path:
        lines.append(f"artifact={artifact_path}")
    manual_gap_reason = str(result.get("manual_gap_reason") or "").strip()
    if manual_gap_reason:
        lines.append(f"manual_gap={manual_gap_reason}")
    source_refs = _inline_refs(result.get("source_refs"))
    target_refs = _inline_refs(result.get("target_refs"))
    if source_refs:
        lines.append(f"sources={source_refs}")
    if target_refs:
        lines.append(f"targets={target_refs}")
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.append(summary)
    return "\n".join(lines)


def _operator_action_block(result: dict) -> str:
    action = str(result.get("action") or "unknown")
    status = str(result.get("status") or "?")
    proof = str(result.get("proof_level") or "?")
    fact = str(result.get("fact_state") or "?")
    lines = [
        f"Operator action: {action}",
        f"status={status} proof={proof} fact={fact}",
    ]
    audit_id = str(result.get("audit_id") or "").strip()
    if audit_id:
        lines.append(f"audit={audit_id}")
    payload = result.get("payload")
    if isinstance(payload, dict):
        gates = _gate_status_summary(payload.get("gate_statuses"))
        if gates:
            lines.append(f"gates={gates}")
        blockers = _gate_blocker_summary(payload.get("blockers"))
        if blockers:
            lines.append(f"blockers={blockers}")
    summary = str(result.get("summary") or "").strip()
    if summary:
        lines.append(summary)
    return "\n".join(lines)


def _gate_status_summary(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        gate_id = str(item.get("gate_id") or "").strip()
        status = str(item.get("status") or "").strip()
        proof = str(item.get("proof_level") or "").strip()
        if gate_id and status and proof:
            parts.append(f"{gate_id}:{status}/{proof}")
    return ", ".join(parts)


def _gate_blocker_summary(value: object) -> str:
    if not isinstance(value, list):
        return ""
    gate_ids = [
        str(item.get("gate_id") or "").strip()
        for item in value[:8]
        if isinstance(item, dict) and str(item.get("gate_id") or "").strip()
    ]
    return ", ".join(gate_ids)


def _inline_refs(value: object) -> str:
    if not isinstance(value, list):
        return ""
    refs = [str(item).strip() for item in value if str(item).strip()]
    return ", ".join(refs[:5])


def _discussion_block(inspector: dict | None) -> str:
    if not isinstance(inspector, dict):
        return "Discussion runs: unavailable"
    collaboration = inspector.get("collaboration")
    if not isinstance(collaboration, dict):
        return "Discussion runs: none"
    runs = collaboration.get("runs")
    run_rows = [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
    lines = [f"Discussion runs: active={int(collaboration.get('active_runs') or 0)}"]
    if not run_rows:
        lines.append("- none")
    else:
        for run in run_rows:
            run_id = str(run.get("run_id") or "?")
            status = str(run.get("status") or "?")
            mode = str(run.get("orchestration_mode") or "?")
            initiator = str(run.get("initiator") or "?")
            targets = run.get("targets")
            target_text = (
                ", ".join(str(target) for target in targets)
                if isinstance(targets, list)
                else "none"
            )
            response_count = int(run.get("response_count") or 0)
            blocker_count = int(run.get("blocker_count") or 0)
            lines.append(
                f"- {run_id} {status} {mode} initiator={initiator} "
                f"targets={target_text} responses={response_count} blockers={blocker_count}"
            )
    gates = collaboration.get("dispatch_gates")
    gate_rows = (
        [gate for gate in gates if isinstance(gate, dict)]
        if isinstance(gates, list)
        else []
    )
    if gate_rows:
        lines.append("Dispatch gates:")
        for gate in gate_rows[:5]:
            event_id = str(gate.get("event_id") or "?")
            run_id = str(gate.get("run_id") or "?")
            decision = str(gate.get("decision") or "?")
            proposal_ref = str(gate.get("proposal_ref") or "")
            artifact_ref = str(gate.get("artifact_ref") or "")
            suffix = " ".join(ref for ref in (proposal_ref, artifact_ref) if ref)
            if suffix:
                lines.append(f"- {event_id} {run_id} {decision} {suffix}")
            else:
                lines.append(f"- {event_id} {run_id} {decision}")
    queue = inspector.get("dispatch_queue")
    if isinstance(queue, dict):
        entries = queue.get("entries")
        entry_rows = (
            [entry for entry in entries if isinstance(entry, dict)]
            if isinstance(entries, list)
            else []
        )
        if entry_rows:
            lines.append(
                "Dispatch queue: "
                f"queued={int(queue.get('queued') or 0)} "
                f"processing={int(queue.get('processing') or 0)}"
            )
            for entry in entry_rows[:5]:
                entry_id = str(entry.get("entry_id") or "?")
                status = str(entry.get("status") or "?")
                source = str(entry.get("source") or "?")
                target = str(entry.get("target") or "?")
                auto = " auto" if bool(entry.get("auto_execute")) else ""
                proposal_id = str(entry.get("proposal_id") or "")
                resolution_id = str(entry.get("resolution_id") or "")
                claimed_by = str(entry.get("claimed_by") or "")
                provider_run_ref = str(entry.get("provider_run_ref") or "")
                failure_reason = str(entry.get("failure_reason") or "")
                refs = " ".join(
                    ref
                    for ref in (
                        proposal_id,
                        resolution_id,
                        claimed_by,
                        provider_run_ref,
                        failure_reason,
                    )
                    if ref
                )
                suffix = f" {refs}" if refs else ""
                lines.append(
                    f"- {entry_id} {status} {source} target={target}{auto}{suffix}"
                )
    return "\n".join(lines)


def _blockers_block(inspector: dict | None) -> str:
    if not isinstance(inspector, dict):
        return "Blockers: unavailable"
    blockers = inspector.get("blockers")
    if not isinstance(blockers, dict):
        return "Blockers: none"
    items = blockers.get("items")
    blocker_rows = [
        item for item in items
        if isinstance(item, dict) and bool(item.get("active"))
    ] if isinstance(items, list) else []
    lines = [f"Blockers: active={int(blockers.get('active') or 0)}"]
    if not blocker_rows:
        lines.append("- none")
        return "\n".join(lines)
    for blocker in blocker_rows:
        blocker_id = str(blocker.get("blocker_id") or "?")
        severity = str(blocker.get("severity") or "?")
        issuer = str(blocker.get("issuer") or "?")
        dispatch_flag = (
            "dispatch-blocking"
            if bool(blocker.get("blocks_dispatch"))
            else "non-dispatch"
        )
        reason = str(blocker.get("reason") or "")
        affected = str(blocker.get("affected_ref") or "")
        fix = str(blocker.get("suggested_fix") or "")
        lines.append(f"- {blocker_id} {severity} {issuer} {dispatch_flag}")
        if affected:
            lines.append(f"  affects: {affected}")
        if reason:
            lines.append(f"  reason: {reason}")
        if fix:
            lines.append(f"  fix: {fix}")
    return "\n".join(lines)


def _overview_block(
    inspector: dict | None,
    *,
    bootstrap: dict | None,
    conversation_id: str,
    title: str,
) -> str:
    lines = [f"Overview: {title} ({conversation_id})"]
    lines.append(_overview_bootstrap_line(bootstrap))
    lines.append(_overview_team_line(inspector))
    lines.append(_overview_discussion_line(inspector))
    lines.append(_overview_blocker_line(inspector))
    lines.append(_overview_dispatch_gate_line(inspector))
    lines.append(_overview_dispatch_queue_line(inspector))
    latest_dispatch = _overview_latest_dispatch_line(inspector)
    if latest_dispatch:
        lines.append(latest_dispatch)
    provider_line = _overview_provider_writeback_line(inspector)
    if provider_line:
        lines.append(provider_line)
    return "\n".join(lines)


def _overview_bootstrap_line(bootstrap: dict | None) -> str:
    if not isinstance(bootstrap, dict):
        return "Bootstrap: unknown"
    status = str(bootstrap.get("status") or "unknown")
    preset = str(bootstrap.get("preset_id") or "unknown")
    return f"Bootstrap: {status} preset={preset}"


def _overview_team_line(inspector: dict | None) -> str:
    participants = inspector.get("participants") if isinstance(inspector, dict) else None
    summary = participants.get("summary") if isinstance(participants, dict) else None
    if not isinstance(summary, dict) or not summary:
        total = int(participants.get("total") or 0) if isinstance(participants, dict) else 0
        return f"Team: total={total}"
    ordered = []
    for role in ("init", "architect", "review", "execute"):
        if role in summary:
            ordered.append(f"{role}={int(summary.get(role) or 0)}")
    default_roles = {"init", "architect", "review", "execute"}
    for role in sorted(key for key in summary if key not in default_roles):
        ordered.append(f"{role}={int(summary.get(role) or 0)}")
    return f"Team: {' '.join(ordered)}"


def _overview_discussion_line(inspector: dict | None) -> str:
    collaboration = inspector.get("collaboration") if isinstance(inspector, dict) else None
    if not isinstance(collaboration, dict):
        return "Discussion: active=0"
    runs = collaboration.get("runs")
    run_rows = [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
    active = int(collaboration.get("active_runs") or 0)
    if not run_rows:
        return f"Discussion: active={active}"
    latest = run_rows[-1]
    run_id = str(latest.get("run_id") or "?")
    status = str(latest.get("status") or "?")
    mode = str(latest.get("orchestration_mode") or "?")
    return f"Discussion: active={active} latest={run_id} {status} {mode}"


def _overview_blocker_line(inspector: dict | None) -> str:
    blockers = inspector.get("blockers") if isinstance(inspector, dict) else None
    if not isinstance(blockers, dict):
        return "Blockers: active=0 dispatch-blocking=0"
    items = blockers.get("items")
    blocker_rows = (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )
    blocking = sum(
        1
        for item in blocker_rows
        if bool(item.get("active")) and bool(item.get("blocks_dispatch"))
    )
    return f"Blockers: active={int(blockers.get('active') or 0)} dispatch-blocking={blocking}"


def _overview_dispatch_gate_line(inspector: dict | None) -> str:
    collaboration = inspector.get("collaboration") if isinstance(inspector, dict) else None
    gates = collaboration.get("dispatch_gates") if isinstance(collaboration, dict) else None
    gate_rows = (
        [gate for gate in gates if isinstance(gate, dict)]
        if isinstance(gates, list)
        else []
    )
    if not gate_rows:
        return "Dispatch gates: none"
    latest = gate_rows[-1]
    event_id = str(latest.get("event_id") or "?")
    decision = str(latest.get("decision") or "?")
    return f"Dispatch gates: latest={event_id} {decision}"


def _overview_dispatch_queue_line(inspector: dict | None) -> str:
    queue = inspector.get("dispatch_queue") if isinstance(inspector, dict) else None
    if not isinstance(queue, dict):
        return "Dispatch queue: queued=0 processing=0 dispatched=0 failed=0"
    return (
        "Dispatch queue: "
        f"queued={int(queue.get('queued') or 0)} "
        f"processing={int(queue.get('processing') or 0)} "
        f"dispatched={int(queue.get('dispatched') or 0)} "
        f"failed={int(queue.get('failed') or 0)}"
    )


def _overview_latest_dispatch_line(inspector: dict | None) -> str | None:
    queue = inspector.get("dispatch_queue") if isinstance(inspector, dict) else None
    entries = queue.get("entries") if isinstance(queue, dict) else None
    entry_rows = (
        [entry for entry in entries if isinstance(entry, dict)]
        if isinstance(entries, list)
        else []
    )
    if not entry_rows:
        return None
    latest = entry_rows[0]
    entry_id = str(latest.get("entry_id") or "?")
    status = str(latest.get("status") or "?")
    provider_ref = str(latest.get("provider_run_ref") or latest.get("failure_reason") or "")
    suffix = f" {provider_ref}" if provider_ref else ""
    return f"Latest dispatch: {entry_id} {status}{suffix}"


def _overview_provider_writeback_line(inspector: dict | None) -> str | None:
    latest_dispatch = _overview_latest_dispatch_entry(inspector)
    latency = inspector.get("peer_latency") if isinstance(inspector, dict) else None
    turns = latency.get("recent_turns") if isinstance(latency, dict) else None
    turn_rows = (
        [turn for turn in turns if isinstance(turn, dict)]
        if isinstance(turns, list)
        else []
    )
    evidence_inbox_id = _mcp_writeback_inbox_id(latest_dispatch)
    if evidence_inbox_id:
        for turn in turn_rows:
            if str(turn.get("inbox_item_id") or "") == evidence_inbox_id:
                return _provider_writeback_line_for_turn(turn)
        return f"Provider writeback: mcp_writeback evidence={evidence_inbox_id}"
    if not turn_rows:
        return None
    return _provider_writeback_line_for_turn(turn_rows[0])


def _provider_writeback_line_for_turn(turn: dict) -> str:
    mode = str(turn.get("delivery_mode") or "unknown")
    role = str(turn.get("target_role") or "?")
    reason = str(turn.get("degraded_reason") or "")
    suffix = f" degraded={reason}" if reason else ""
    return f"Provider writeback: {mode} {role}{suffix}"


def _overview_latest_dispatch_entry(inspector: dict | None) -> dict | None:
    queue = inspector.get("dispatch_queue") if isinstance(inspector, dict) else None
    entries = queue.get("entries") if isinstance(queue, dict) else None
    entry_rows = (
        [entry for entry in entries if isinstance(entry, dict)]
        if isinstance(entries, list)
        else []
    )
    return entry_rows[0] if entry_rows else None


def _mcp_writeback_inbox_id(entry: dict | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    evidence = str(entry.get("dispatch_evidence") or "")
    prefix = "mcp_writeback:"
    if not evidence.startswith(prefix):
        return None
    inbox_id = evidence.removeprefix(prefix).strip()
    return inbox_id or None


def _find_role_template(templates: list[dict], role: str) -> dict | None:
    for template in templates:
        if str(template.get("slug") or "") == role or str(template.get("id") or "") == role:
            return template
    return None


def _help_text() -> str:
    return "\n".join(
        [
            "Commands:",
            "/help",
            "/sessions",
            "/sessions <number|conversation_id|title>",
            "/new <title>",
            "/init status",
            "/init retry",
            "/init apply <proposal_id>",
            "/approve [latest|proposal_id]",
            "/where",
            "/participants",
            "/overview",
            "/dashboard (alias for /overview)",
            "/evidence <transcript|github|memory|blockers>",
            "/release refresh",
            "/release pack",
            "/lane retry <lane_id> <current_status> [reason]",
            "/lane abort <lane_id> <current_status> [reason]",
            "/freeze target_ref=<ref> blueprint_id=<id> goal=<goal> "
            "scope=<items> acceptance=<items>",
            "/discussion",
            "/blockers",
            "/god add <role> [display name]",
            "/god rm <role|participant_id>",
            "/god register <key=value...>",
            "/god select <cli_id>",
            "/archive",
            "/copy",
            "/resume [number|conversation_id|title] (resume session, default: most recent)",
        ]
    )
