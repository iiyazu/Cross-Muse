from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import PeerChatScheduler
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


class DemoFakeGodLayer:
    """In-process provider substitute used only by the onboarding demo."""

    def __init__(self, xmuse_root: Path) -> None:
        self._xmuse_root = xmuse_root
        self._registry_path = xmuse_root / "god_sessions.json"
        self._registry = GodSessionRegistry(self._registry_path)
        self._service = PeerChatService(xmuse_root / "chat.db")
        self._pending_context: dict[str, dict[str, object]] = {}

    async def ensure_conversation_session(self, **kwargs):
        conversation_id = str(kwargs["conversation_id"])
        participant_id = str(kwargs["participant_id"])
        try:
            return self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
            )
        except KeyError:
            session_address, session_inbox_id = build_conversation_session_identity(
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
            agent = kwargs["agent"]
            runtime = getattr(getattr(agent, "runtime", "codex"), "value", "codex")
            return self._registry.create(
                role=str(kwargs["role"]),
                agent_name=str(getattr(agent, "name", kwargs["role"])),
                runtime=str(runtime),
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=conversation_id,
                participant_id=participant_id,
                model=kwargs.get("model"),
                prompt_fingerprint=kwargs.get("prompt_fingerprint"),
                worktree=str(kwargs["worktree"]),
                feature_scope_id=kwargs.get("feature_scope_id"),
            )

    async def send_message(
        self,
        god_session_id: str,
        _message_type: str,
        *,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None:
        payload = json.loads(context)
        payload["request_id"] = request_id
        payload["prompt_seen"] = bool(prompt)
        self._pending_context[god_session_id] = payload

    async def receive_message(self, god_session_id: str):
        context = self._pending_context.pop(god_session_id)
        inbox = self._service.read_inbox(
            registry_path=self._registry_path,
            conversation_id=str(context["conversation_id"]),
            participant_id=str(context["participant_id"]),
            god_session_id=god_session_id,
        )
        inbox_items = inbox["inbox_items"]
        if not inbox_items:
            raise RuntimeError("fake demo GOD found no inbox item")
        item = inbox_items[0]
        content = str(item.get("payload", {}).get("content", ""))
        reply = f"Architect GOD demo reply: received {content!r}."
        self._service.post_god_message(
            registry_path=self._registry_path,
            conversation_id=str(context["conversation_id"]),
            participant_id=str(context["participant_id"]),
            god_session_id=god_session_id,
            client_request_id=f"{item['id']}:demo-fake-god",
            content=reply,
            reply_to_inbox_item_id=str(item["id"]),
        )
        return SimpleNamespace(
            type="result",
            status="success",
            request_id=context.get("request_id"),
            message="",
            artifacts={"transport": "demo-fake-god-layer"},
        )


async def _run_demo(*, xmuse_root: Path, message: str) -> dict[str, object]:
    xmuse_root.mkdir(parents=True, exist_ok=True)
    db_path = xmuse_root / "chat.db"
    service = PeerChatService(db_path)
    created = service.create_conversation(
        title="xmuse fake groupchat demo",
        init_mode="deterministic",
    )
    conversation_id = created["conversation"]["id"]
    human_result = service.post_human_message(
        conversation_id=conversation_id,
        author="human-demo",
        content=message,
        client_request_id="fake-demo-human-1",
    )
    if not human_result.inbox_items:
        raise RuntimeError("human message did not create a GOD inbox item")

    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=DemoFakeGodLayer(xmuse_root),
        worktree=xmuse_root,
        scheduler_id="fake-demo-scheduler",
        response_wait_s=5.0,
    )
    outcome = await scheduler.tick_once()
    if outcome.happy_path != 1:
        raise RuntimeError(f"scheduler did not observe happy path: {outcome}")

    architect = next(
        participant
        for participant in ParticipantStore(db_path).list_by_conversation(conversation_id)
        if participant.role == "architect"
    )
    replies = [
        item
        for item in ChatStore(db_path).list_messages(conversation_id)
        if item.author == architect.participant_id and item.role == "assistant"
    ]
    if not replies:
        raise RuntimeError("scheduler happy path did not persist a GOD reply")
    traces = PeerTurnLatencyTraceStore(db_path).list_recent(conversation_id)
    if not traces or traces[0]["delivery_mode"] != "mcp_writeback":
        raise RuntimeError("demo did not record mcp_writeback latency evidence")

    return {
        "conversation_id": conversation_id,
        "reply": replies[-1].content,
        "scheduler_happy_path": outcome.happy_path,
        "xmuse_root": str(xmuse_root),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the xmuse fake groupchat demo.")
    parser.add_argument(
        "--xmuse-root",
        type=Path,
        default=None,
        help="Runtime root for demo state. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--message",
        default="Need a small release candidate packaging plan.",
        help="Human message to post into the demo groupchat.",
    )
    parser.add_argument(
        "--keep-root",
        action="store_true",
        help="Keep the temporary root after the demo finishes.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    temp_root: Path | None = None
    if args.xmuse_root is None:
        temp_root = Path(tempfile.mkdtemp(prefix="xmuse-fake-demo-"))
        xmuse_root = temp_root
    else:
        xmuse_root = args.xmuse_root

    try:
        result = asyncio.run(_run_demo(xmuse_root=xmuse_root, message=args.message))
        print("fake-groupchat-demo-ok")
        print(f"xmuse_root={result['xmuse_root']}")
        print(f"conversation_id={result['conversation_id']}")
        print(f"scheduler_happy_path={result['scheduler_happy_path']}")
        print(f"GOD reply: {result['reply']}")
        return 0
    finally:
        if temp_root is not None and not args.keep_root:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
