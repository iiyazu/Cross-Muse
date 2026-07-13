"""Verified target-facing boundary for the durable room kernel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_identity import verify_room_participant_identity
from xmuse_core.chat.room_kernel import RoomKernelStore, normalize_participant_outcome


class RoomApplicationService:
    def __init__(
        self,
        db_path: Path | str,
        registry_path: Path | str,
        *,
        max_causal_depth: int = 4,
    ) -> None:
        if (
            isinstance(max_causal_depth, bool)
            or not isinstance(max_causal_depth, int)
            or max_causal_depth <= 0
        ):
            raise ValueError("room_max_causal_depth_invalid")
        self._db_path = Path(db_path)
        self._registry_path = Path(registry_path)
        self._max_causal_depth = max_causal_depth

    def submit_participant_outcome(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        outcome_type: str,
        outcome_payload: dict[str, Any] | None = None,
        observation_batch_id: str | None = None,
        reply_to_activity_id: str | None = None,
        proposal_assessments: list[dict[str, Any]] | None = None,
        memory_candidates: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        participants = ParticipantStore(self._db_path)
        try:
            identity = verify_room_participant_identity(
                participants,
                registry_path=self._registry_path,
                conversation_id=conversation_id,
                participant_id=participant_id,
                god_session_id=god_session_id,
            )
            normalize_participant_outcome(outcome_type, outcome_payload, self._max_causal_depth)
            return RoomKernelStore(self._db_path).submit_participant_outcome(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                outcome_type=outcome_type,
                outcome_payload=outcome_payload,
                observation_batch_id=observation_batch_id,
                reply_to_activity_id=reply_to_activity_id,
                proposal_assessments=proposal_assessments,
                memory_candidates=memory_candidates,
                now=now,
                max_causal_depth=self._max_causal_depth,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc
