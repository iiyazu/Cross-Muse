"""Verified target-facing boundary for the durable room kernel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_board import RoomBoardStore
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

    def board_read(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_ref: str | None = None,
        review_id: str | None = None,
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
            return RoomBoardStore(self._db_path).read(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                contract_ref=contract_ref,
                review_id=review_id,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_propose_split(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        modules: list[dict[str, Any]],
        assignments: dict[str, str],
        contracts: list[dict[str, Any]],
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
            return RoomBoardStore(self._db_path).propose_split(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                modules=modules,
                assignments=assignments,
                contracts=contracts,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_decide_split(
        self,
        *,
        conversation_id: str,
        split_id: str,
        decision: str,
        operator_identity: str,
        decided_via: str = "web",
        expected_digest: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        try:
            return RoomBoardStore(self._db_path).decide_split(
                conversation_id=conversation_id,
                split_id=split_id,
                decision=decision,
                operator_identity=operator_identity,
                decided_via=decided_via,
                expected_digest=expected_digest,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_claim(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
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
            return RoomBoardStore(self._db_path).claim(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                module_id=module_id,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_publish_contract(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        contract_id: str,
        kind: str,
        content: str,
        base_version: int | None,
        rationale: str = "",
        provider_module_id: str | None = None,
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
            return RoomBoardStore(self._db_path).publish_contract(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                contract_id=contract_id,
                kind=kind,
                content=content,
                base_version=base_version,
                rationale=rationale,
                provider_module_id=provider_module_id,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_report_progress(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        module_id: str,
        status: str,
        summary: str,
        claims: list[str] | None = None,
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
            return RoomBoardStore(self._db_path).report_progress(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                module_id=module_id,
                status=status,
                summary=summary,
                claims=claims,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_ask(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        target_participant_id: str,
        question: str,
        references: list[str] | None = None,
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
            return RoomBoardStore(self._db_path).ask(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                target_participant_id=target_participant_id,
                question=question,
                references=references,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_review(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        observation_id: str,
        lease_token: str,
        client_request_id: str,
        review_id: str,
        verdict: str,
        summary: str,
        findings: list[dict[str, Any]] | None = None,
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
            return RoomBoardStore(self._db_path).review(
                conversation_id=conversation_id,
                participant_id=participant_id,
                caller_identity=identity.caller_identity,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=client_request_id,
                review_id=review_id,
                verdict=verdict,
                summary=summary,
                findings=findings,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_decide_review(
        self,
        *,
        conversation_id: str,
        review_id: str,
        verdict: str,
        summary: str,
        findings: list[dict[str, Any]] | None = None,
        expected_digest: str | None = None,
        operator_identity: str,
        decided_via: str = "web",
        grant_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        # The digest is the human's proof of what they were shown; the server never
        # fills it in on the caller's behalf (a missing one fails as a mismatch).
        try:
            return RoomBoardStore(self._db_path).decide_review(
                conversation_id=conversation_id,
                review_id=review_id,
                verdict=verdict,
                summary=summary,
                findings=findings,
                expected_digest=expected_digest or "",
                operator_identity=operator_identity,
                decided_via=decided_via,
                grant_id=grant_id,
                now=now,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_review_material(
        self,
        conversation_id: str,
        review_id: str,
    ) -> dict[str, Any]:
        try:
            return RoomBoardStore(self._db_path).review_material(
                conversation_id=conversation_id,
                review_id=review_id,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_review_detail(
        self,
        conversation_id: str,
        review_id: str,
    ) -> dict[str, Any]:
        try:
            return RoomBoardStore(self._db_path).review_detail(
                conversation_id=conversation_id,
                review_id=review_id,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc

    def board_verification_detail(
        self,
        conversation_id: str,
        verification_id: str,
    ) -> dict[str, Any]:
        try:
            return RoomBoardStore(self._db_path).verification_detail(
                conversation_id=conversation_id,
                verification_id=verification_id,
            )
        except RoomApplicationError:
            raise
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0]
            raise RoomApplicationError(code, str(exc)) from exc
