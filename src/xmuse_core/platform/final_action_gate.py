from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore


class PendingFinalAction(BaseModel):
    id: str
    lane_id: str
    verdict_id: str
    action: str
    target_status: str
    status: str = "pending"
    summary: str
    resolved_by: str | None = None
    github_gate_evidence_ref: str | None = None


class FinalActionGateStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def list_actions(self) -> list[PendingFinalAction]:
        data = self._read()
        return [PendingFinalAction(**item) for item in data.get("holds", [])]

    def create_hold(
        self,
        *,
        lane_id: str,
        verdict_id: str,
        action: str,
        target_status: str,
        summary: str,
    ) -> PendingFinalAction:
        data = self._read()
        holds = data.setdefault("holds", [])
        for item in holds:
            if item.get("lane_id") == lane_id and item.get("verdict_id") == verdict_id:
                return PendingFinalAction(**item)
        hold = PendingFinalAction(
            id=f"final-{uuid.uuid4().hex[:12]}",
            lane_id=lane_id,
            verdict_id=verdict_id,
            action=action,
            target_status=target_status,
            summary=summary,
        )
        holds.append(hold.model_dump(mode="json"))
        self._write(data)
        return hold

    def resolve(
        self,
        hold_id: str,
        *,
        status: str,
        resolved_by: str | None = None,
        github_gate_evidence_ref: str | None = None,
    ) -> PendingFinalAction:
        data = self._read()
        for item in data.get("holds", []):
            if item.get("id") == hold_id:
                item["status"] = status
                item["resolved_by"] = resolved_by
                if github_gate_evidence_ref:
                    item["github_gate_evidence_ref"] = github_gate_evidence_ref
                self._write(data)
                action = PendingFinalAction(**item)
                self._update_acceptance_spine_for_resolution(
                    hold_id=hold_id,
                    status=status,
                    github_gate_evidence_ref=github_gate_evidence_ref,
                )
                return action
        raise KeyError(f"unknown final action hold: {hold_id}")

    def get(self, hold_id: str) -> PendingFinalAction:
        for item in self._read().get("holds", []):
            if item.get("id") == hold_id:
                return PendingFinalAction(**item)
        raise KeyError(f"unknown final action hold: {hold_id}")

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"holds": []}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _update_acceptance_spine_for_resolution(
        self,
        *,
        hold_id: str,
        status: str,
        github_gate_evidence_ref: str | None,
    ) -> None:
        chat_db_path = self._path.parent / "chat.db"
        if not chat_db_path.exists():
            return
        AcceptanceSpineStore(chat_db_path).resolve_final_action(
            final_action_ref=f"{self._path.name}#hold={hold_id}",
            status=status,
            github_gate_evidence_ref=github_gate_evidence_ref,
        )
