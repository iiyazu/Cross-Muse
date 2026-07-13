"""Single human write path for the default Room product."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status

from xmuse.chat_api_runtime import (
    WorkroomRuntimeStarter,
    should_autostart_workroom_runtime,
    start_workroom_runtime_for_message,
)
from xmuse_core.chat.mentions import MentionResolver
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_api_models import ThreadMessageCreate
from xmuse_core.chat.room_kernel import RoomKernelStore


def _request_id(value: str | None) -> str:
    return value or f"rest_{uuid.uuid4().hex}"


def _post_human_message(
    *,
    root: Path,
    conversation_id: str,
    payload: ThreadMessageCreate,
    client_request_id: str,
) -> dict[str, object]:
    participants = ParticipantStore(root / "chat.db")
    mentions = MentionResolver(participants).resolve_content(
        conversation_id,
        payload.message,
        strict=False,
    )
    try:
        return RoomKernelStore(root / "chat.db").post_human_activity(
            conversation_id=conversation_id,
            human_id="Human operator",
            content=payload.message,
            client_request_id=client_request_id,
            mentions=[item.participant.participant_id for item in mentions],
            display_mentions=[item.normalized for item in mentions],
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ValueError as exc:
        if str(exc) == "room_request_idempotency_conflict":
            raise HTTPException(status_code=409, detail="invocation_idempotency_conflict") from exc
        raise


def _receipt(
    *,
    conversation_id: str,
    result: dict[str, object],
    client_request_id: str,
    runtime: dict[str, object] | None,
) -> dict[str, object]:
    message = result.get("message")
    activity = result.get("activity")
    if not isinstance(message, dict) or not isinstance(activity, dict):
        raise RuntimeError("room_human_message_result_invalid")
    response: dict[str, object] = {
        "thread_id": conversation_id,
        "client_request_id": client_request_id,
        "activity_id": activity["activity_id"],
        "room_activity_seq": activity["seq"],
        "message": {
            "id": message["id"],
            "conversation_id": message["conversation_id"],
            "role": "user",
            "author": message["author"],
            "kind": "checkpoint",
            "content": message["content"],
            "created_at": message["created_at"],
            "mentions": message["mentions"],
            "envelope_type": message["envelope_type"],
            "envelope_json": message["envelope_json"],
        },
    }
    if runtime is not None:
        response["runtime"] = runtime
    return response


def register_room_message_routes(
    app: FastAPI,
    *,
    root: Path,
    execution_root: Path,
    runtime_starter: WorkroomRuntimeStarter,
    explicit_runtime_starter: bool,
) -> None:
    @app.post("/api/chat/threads/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
    def add_room_message(
        conversation_id: str,
        payload: ThreadMessageCreate,
        request: Request,
    ) -> dict[str, object]:
        client_request_id = _request_id(payload.client_request_id)
        result = _post_human_message(
            root=root,
            conversation_id=conversation_id,
            payload=payload,
            client_request_id=client_request_id,
        )
        observations = result.get("observations")
        has_pending = isinstance(observations, list) and any(
            isinstance(item, dict) and item.get("status") == "pending" for item in observations
        )
        runtime = None
        if has_pending and should_autostart_workroom_runtime(
            request,
            explicit_runtime_starter=explicit_runtime_starter,
        ):
            runtime = start_workroom_runtime_for_message(
                runtime_starter,
                root,
                execution_root,
            )
        return _receipt(
            conversation_id=conversation_id,
            result=result,
            client_request_id=client_request_id,
            runtime=runtime,
        )
