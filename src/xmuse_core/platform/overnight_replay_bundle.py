from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from xmuse_core.platform.release_readiness import ProofLevel

REPLAY_BUNDLE_SCHEMA_VERSION = "xmuse.overnight_replay_bundle.v1"
REPLAY_BUNDLE_AUTHORITY = "replay_index_only"

ReplaySectionStatus = Literal["ok", "blocked", "manual_gap", "not_evaluated"]

REQUIRED_REPLAY_SECTIONS = (
    "stage_evidence",
    "deliberation_transcript",
    "frozen_blueprint",
    "feature_lineage",
    "memoryos_trace",
    "memory_governance",
    "github_truth",
    "supervisor",
    "release_readiness",
)


@dataclass(frozen=True)
class ReplayBundleSection:
    section_id: str
    status: ReplaySectionStatus
    proof_level: ProofLevel
    source_authority: str
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    summary: str | None = None
    blocked_reason: str | None = None
    owner: str = "operator"
    next_action: str | None = None
    details: Mapping[str, object] | None = None

    def model_dump(
        self,
        *,
        tombstoned_source_refs: set[str],
    ) -> dict[str, object]:
        active_source_refs = [
            ref for ref in self.source_refs if ref not in tombstoned_source_refs
        ]
        payload: dict[str, object] = {
            "section_id": self.section_id,
            "status": self.status,
            "proof_level": self.proof_level,
            "source_authority": self.source_authority,
            "source_refs": list(self.source_refs),
            "active_source_refs": active_source_refs,
            "artifacts": list(self.artifacts),
            "summary": self.summary,
            "blocked_reason": self.blocked_reason,
            "owner": self.owner,
            "next_action": self.next_action,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


def build_overnight_replay_bundle(
    *,
    run_id: str,
    sections: list[ReplayBundleSection],
    tombstoned_source_refs: tuple[str, ...] = (),
) -> dict[str, object]:
    tombstoned_refs = {ref for ref in tombstoned_source_refs if ref}
    ordered_sections = _ordered_sections(sections)
    section_payloads = [
        section.model_dump(tombstoned_source_refs=tombstoned_refs)
        for section in ordered_sections
    ]
    blockers = _blockers(
        sections=ordered_sections,
        section_payloads=section_payloads,
        tombstoned_source_refs=tombstoned_refs,
    )
    return {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_id": run_id,
        "authority": REPLAY_BUNDLE_AUTHORITY,
        "decision": "blocked" if blockers else "ready_for_replay",
        "required_sections": list(REQUIRED_REPLAY_SECTIONS),
        "proof_level_summary": _proof_level_summary(ordered_sections),
        "sections": section_payloads,
        "blockers": blockers,
    }


def write_overnight_replay_bundle(
    *,
    bundle: dict[str, object],
    output_path: str | Path,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ordered_sections(sections: list[ReplayBundleSection]) -> list[ReplayBundleSection]:
    order = {section_id: index for index, section_id in enumerate(REQUIRED_REPLAY_SECTIONS)}
    return sorted(
        sections,
        key=lambda section: (order.get(section.section_id, len(order)), section.section_id),
    )


def _blockers(
    *,
    sections: list[ReplayBundleSection],
    section_payloads: list[dict[str, object]],
    tombstoned_source_refs: set[str],
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    by_section = {section.section_id: section for section in sections}
    for section_id in REQUIRED_REPLAY_SECTIONS:
        if section_id not in by_section:
            blockers.append(
                {
                    "section_id": section_id,
                    "reason": "required replay section is missing",
                    "owner": "operator",
                    "next_action": f"Capture or attach {section_id} replay evidence.",
                }
            )

    payload_by_section = {
        str(payload["section_id"]): payload for payload in section_payloads
    }
    for section in sections:
        if section.status != "ok":
            blockers.append(
                {
                    "section_id": section.section_id,
                    "reason": section.blocked_reason
                    or f"{section.section_id} status is {section.status}: {section.summary}",
                    "owner": section.owner,
                    "next_action": section.next_action,
                }
            )
        tombstoned = [
            ref for ref in section.source_refs if ref in tombstoned_source_refs
        ]
        if tombstoned:
            payload = payload_by_section[section.section_id]
            payload["blocked_reason"] = (
                f"section contains tombstoned source refs: {', '.join(tombstoned)}"
            )
            blockers.append(
                {
                    "section_id": section.section_id,
                    "reason": payload["blocked_reason"],
                    "owner": section.owner,
                    "next_action": (
                        "Remove tombstoned refs or regenerate the MemoryOS trace."
                    ),
                }
            )
    return blockers


def _proof_level_summary(
    sections: list[ReplayBundleSection],
) -> dict[str, int]:
    summary: dict[str, int] = {}
    for section in sections:
        summary[section.proof_level] = summary.get(section.proof_level, 0) + 1
    return summary


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
