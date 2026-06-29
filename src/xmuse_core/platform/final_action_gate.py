from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from xmuse_core.chat.acceptance_spine import AcceptanceSpine, AcceptanceSpineStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.github_gate_evidence import (
    GitHubGateEvidenceStore,
    GitHubGateTruthCollector,
    GitHubMainCiTruthCollector,
)


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
    github_gate_gap_ref: str | None = None


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
        github_gate_gap_ref: str | None = None,
        github_gate_evidence_store_path: Path | str | None = None,
    ) -> PendingFinalAction:
        data = self._read()
        for item in data.get("holds", []):
            if item.get("id") == hold_id:
                accepted_github_ref = self._accepted_github_gate_ref(
                    hold_id=hold_id,
                    github_gate_evidence_ref=github_gate_evidence_ref,
                    evidence_store_path=github_gate_evidence_store_path,
                )
                rejected_github_ref = (
                    github_gate_evidence_ref
                    if github_gate_evidence_ref and not accepted_github_ref
                    else None
                )
                normalized_status = status.strip().lower()
                status_requires_github_gate = item.get("action") == "merge" and (
                    normalized_status in {
                        "approved",
                        "accepted",
                        "resolved",
                    }
                )
                status_blocked_by_github_gate = (
                    status_requires_github_gate and not accepted_github_ref
                )
                item["status"] = "blocked" if status_blocked_by_github_gate else status
                item["resolved_by"] = resolved_by
                if accepted_github_ref:
                    item["github_gate_evidence_ref"] = accepted_github_ref
                    item.pop("github_gate_gap_ref", None)
                else:
                    item.pop("github_gate_evidence_ref", None)
                    if status_blocked_by_github_gate:
                        item["github_gate_gap_ref"] = (
                            github_gate_gap_ref
                            or rejected_github_ref
                            or "github_gate_unverified"
                        )
                self._write(data)
                action = PendingFinalAction(**item)
                spine = self._update_acceptance_spine_for_resolution(
                    hold_id=hold_id,
                    status=status,
                    github_gate_evidence_ref=accepted_github_ref,
                    github_gate_evidence_store_path=github_gate_evidence_store_path,
                )
                self._record_groupchat_writeback(
                    action,
                    requested_status=status,
                    spine=spine,
                )
                return action
        raise KeyError(f"unknown final action hold: {hold_id}")

    def resolve_with_github_gate_evidence(
        self,
        hold_id: str,
        *,
        status: str,
        resolved_by: str | None = None,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
        collector: GitHubGateTruthCollector,
        main_ci_collector: GitHubMainCiTruthCollector | None = None,
        evidence_store_path: Path | str | None = None,
    ) -> PendingFinalAction:
        resolved_evidence_store_path = (
            evidence_store_path or self._path.parent / "github_gate_evidence.json"
        )
        github_gate_evidence_ref: str | None = None
        github_gate_gap_ref: str | None = None
        if status.strip().lower() in {"approved", "accepted", "resolved"}:
            store = GitHubGateEvidenceStore(resolved_evidence_store_path)
            record = store.capture_for_final_action(
                final_action_id=hold_id,
                repo=repo,
                pull_request_number=pull_request_number,
                required_checks=required_checks,
                collector=collector,
                main_ci_collector=main_ci_collector,
            )
            record_ref = store.ref_for(record)
            if record.can_accept:
                github_gate_evidence_ref = record_ref
            else:
                github_gate_gap_ref = record_ref
        return self.resolve(
            hold_id,
            status=status,
            resolved_by=resolved_by,
            github_gate_evidence_ref=github_gate_evidence_ref,
            github_gate_gap_ref=github_gate_gap_ref,
            github_gate_evidence_store_path=resolved_evidence_store_path,
        )

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

    def _accepted_github_gate_ref(
        self,
        *,
        hold_id: str,
        github_gate_evidence_ref: str | None,
        evidence_store_path: Path | str | None,
    ) -> str | None:
        if not github_gate_evidence_ref:
            return None
        store = GitHubGateEvidenceStore(
            evidence_store_path or self._path.parent / "github_gate_evidence.json"
        )
        if store.is_accepted_ref(
            github_gate_evidence_ref,
            final_action_id=hold_id,
        ):
            return github_gate_evidence_ref
        return None

    def _update_acceptance_spine_for_resolution(
        self,
        *,
        hold_id: str,
        status: str,
        github_gate_evidence_ref: str | None,
        github_gate_evidence_store_path: Path | str | None,
    ) -> AcceptanceSpine | None:
        chat_db_path = self._path.parent / "chat.db"
        if not chat_db_path.exists():
            return None
        return AcceptanceSpineStore(chat_db_path).resolve_final_action(
            final_action_ref=f"{self._path.name}#hold={hold_id}",
            status=status,
            github_gate_evidence_ref=github_gate_evidence_ref,
            github_gate_evidence_store_path=github_gate_evidence_store_path,
        )

    def _record_groupchat_writeback(
        self,
        action: PendingFinalAction,
        *,
        requested_status: str,
        spine: AcceptanceSpine | None,
    ) -> None:
        if spine is None:
            return
        chat_db_path = self._path.parent / "chat.db"
        if not chat_db_path.exists():
            return
        final_action_ref = f"{self._path.name}#hold={action.id}"
        spine_ref = f"chat.db#acceptance_spine={spine.spine_id}"
        source_refs = _final_action_source_refs(
            final_action_ref=final_action_ref,
            spine_ref=spine_ref,
            review_verdict_ref=spine.review_verdict_ref,
            github_gate_ref=action.github_gate_evidence_ref or action.github_gate_gap_ref,
        )
        ChatStore(chat_db_path).create_message_inbox_and_log(
            conversation_id=spine.conversation_id,
            tool_name="final_action_gate_writeback",
            caller_identity="final-action-gate",
            client_request_id=(
                f"{action.id}:{action.status}:"
                f"{action.github_gate_evidence_ref or action.github_gate_gap_ref or 'none'}"
            ),
            author="final-action-gate",
            role="system",
            content=_final_action_writeback_content(action),
            envelope_type="final_action_result",
            envelope_json={
                "type": "final_action_result",
                "authority": "chat.db/messages/final_action_result",
                "final_action_id": action.id,
                "final_action_ref": final_action_ref,
                "lane_id": action.lane_id,
                "verdict_id": action.verdict_id,
                "action": action.action,
                "target_status": action.target_status,
                "requested_status": requested_status,
                "status": action.status,
                "resolved_by": action.resolved_by,
                "github_gate_evidence_ref": action.github_gate_evidence_ref,
                "github_gate_gap_ref": action.github_gate_gap_ref,
                "acceptance_spine_ref": spine_ref,
                "source_refs": source_refs,
                "proof_boundary": "final_action_writeback_not_github_or_merge_truth",
            },
            mentions=[],
            inbox_items=[],
        )


def _final_action_source_refs(
    *,
    final_action_ref: str,
    spine_ref: str,
    review_verdict_ref: str | None,
    github_gate_ref: str | None,
) -> list[str]:
    return _dedupe_refs(
        [
            final_action_ref,
            spine_ref,
            review_verdict_ref,
            github_gate_ref,
        ]
    )


def _final_action_writeback_content(action: PendingFinalAction) -> str:
    lines = [
        (
            f"Final action {action.action} for lane {action.lane_id} "
            f"is {action.status}."
        )
    ]
    if action.github_gate_evidence_ref:
        lines.append(f"GitHub gate evidence: {action.github_gate_evidence_ref}")
    if action.github_gate_gap_ref:
        lines.append(f"GitHub gate gap: {action.github_gate_gap_ref}")
    lines.append("This writeback is not GitHub merge or main CI truth.")
    return "\n".join(lines)


def _dedupe_refs(refs: list[str | None]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        clean = ref.strip() if isinstance(ref, str) else ""
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped
