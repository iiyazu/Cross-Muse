#!/usr/bin/env python3
"""Xmuse-local error knowledge maintainer.

The maintainer reads existing Xmuse control-plane artifacts and writes only
local, quarantined knowledge objects. It does not modify MemoryOS runtime
behavior, active prompts, active skills, Master state, or approval artifacts.
"""

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from xmuse_core.knowledge import cluster_artifacts
from xmuse_core.knowledge.handoff_artifacts import (
    build_ack,
    build_review_verdict,
    build_slave_state,
    render_result_markdown,
)
from xmuse_core.knowledge.maintainer_contracts import (
    DEFAULT_ALLOWED_WRITES,
    EXTRACTOR_VERSION,
    FEATURE_ID,
    FINAL_WORK_ARTIFACTS,
    OPTIONAL_INPUTS,
    REQUIRED_INPUTS,
    SCAN_GLOBS,
    SCHEMA_VERSION,
    Finding,
    SimulatedWriteFailure,
    _atomic_write_json,
    _atomic_write_text,
    _path_matches,
    _read_json,
    _safe_relative,
    _write_bootstrap_blocked,
    artifact_type_for,
    canonical_json,
    feature_id_for,
    normalize_command,
    sha256_file,
    sha256_text,
    source_digest_for_refs,
    source_ref,
    stable_id,
    unique_source_refs,
    utc_now,
    validate_contract,
)


class KnowledgeMaintainer:
    def __init__(
        self,
        root: str | Path,
        *,
        run_id: str | None = None,
        now: str | None = None,
        fail_after_object_writes: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id or f"knowledge-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        self.now = now or utc_now()
        contract_status = validate_contract(self.root)
        self.contract = contract_status.get("contract") or {}
        self.allowed_writes = list(self.contract.get("allowed_writes") or DEFAULT_ALLOWED_WRITES)
        self.fail_after_object_writes = fail_after_object_writes
        self.object_write_count = 0
        self.diagnostics: list[str] = []
        self.scanned_artifacts: list[str] = []
        self.generated: dict[str, list[str]] = {
            "error_records": [],
            "clusters": [],
            "methods": [],
            "skill_proposals": [],
        }

    @property
    def feature_dir(self) -> Path:
        return self.root / f"xmuse/work/features/{FEATURE_ID}"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "xmuse/knowledge"

    def assert_allowed_write(self, path: str | Path) -> None:
        path = Path(path)
        try:
            rel = _safe_relative(self.root, path)
        except ValueError as exc:
            raise ValueError(f"write outside knowledge_maintainer boundary: {path}") from exc
        if not any(_path_matches(pattern, rel) for pattern in self.allowed_writes):
            raise ValueError(f"write outside knowledge_maintainer boundary: {rel}")

    def write_json(
        self,
        rel_path: str,
        payload: Any,
        *,
        object_write: bool = False,
    ) -> None:
        path = self.root / rel_path
        self.assert_allowed_write(path)
        if object_write:
            if (
                self.fail_after_object_writes is not None
                and self.object_write_count >= self.fail_after_object_writes
            ):
                raise SimulatedWriteFailure("simulated partial object write failure")
            self.object_write_count += 1
        _atomic_write_json(path, payload)

    def write_text(
        self,
        rel_path: str,
        content: str,
        *,
        object_write: bool = False,
    ) -> None:
        path = self.root / rel_path
        self.assert_allowed_write(path)
        if object_write:
            if (
                self.fail_after_object_writes is not None
                and self.object_write_count >= self.fail_after_object_writes
            ):
                raise SimulatedWriteFailure("simulated partial object write failure")
            self.object_write_count += 1
        _atomic_write_text(path, content)

    def run(self) -> dict[str, Any]:
        try:
            findings = self.scan_findings()
            records = self.write_error_records(findings)
            clusters = self.write_clusters(records)
            methods = self.write_methods(clusters)
            proposals = self.write_skill_proposals(methods, clusters)
            self.write_run_summary(records, clusters, methods, proposals)
            self.rebuild_indexes()
            self.write_handoff_artifacts(
                status="usable",
                records=records,
                clusters=clusters,
                methods=methods,
                proposals=proposals,
            )
            return {
                "status": "usable",
                "knowledge_run_id": self.run_id,
                "records": len(records),
                "clusters": len(clusters),
                "methods": len(methods),
                "skill_proposals": len(proposals),
            }
        except SimulatedWriteFailure as exc:
            self.write_handoff_artifacts(
                status="failed",
                records=[],
                clusters=[],
                methods=[],
                proposals=[],
                blockers=[str(exc)],
            )
            return {
                "status": "failed",
                "knowledge_run_id": self.run_id,
                "blockers": [str(exc)],
            }

    def scan_findings(self) -> list[Finding]:
        for optional in OPTIONAL_INPUTS:
            if not (self.root / optional).exists():
                self.diagnostics.append(f"missing optional input: {optional}")

        findings: list[Finding] = []
        findings.extend(self.find_missing_feature_artifacts())
        seen_paths: set[Path] = set()
        for pattern in SCAN_GLOBS:
            for path in sorted(self.root.glob(pattern)):
                if not path.is_file() or path in seen_paths:
                    continue
                seen_paths.add(path)
                feature_id = feature_id_for(self.root, path)
                if feature_id == FEATURE_ID:
                    continue
                artifact_type = artifact_type_for(path)
                self.scanned_artifacts.append(_safe_relative(self.root, path))
                if path.suffix == ".json":
                    findings.extend(self.extract_json_findings(path, feature_id, artifact_type))
                elif path.suffix == ".md":
                    findings.extend(self.extract_markdown_findings(path, feature_id, artifact_type))
        return findings

    def find_missing_feature_artifacts(self) -> list[Finding]:
        work_features = self.root / "xmuse/work/features"
        if not work_features.exists():
            return []
        findings: list[Finding] = []
        for feature_dir in sorted(path for path in work_features.iterdir() if path.is_dir()):
            feature_id = feature_dir.name
            if feature_id == FEATURE_ID:
                continue
            for artifact in FINAL_WORK_ARTIFACTS:
                if (feature_dir / artifact).exists():
                    continue
                artifact_type = artifact_type_for(feature_dir / artifact)
                missing_path = feature_dir / artifact
                findings.append(
                    Finding(
                        feature_id=feature_id,
                        artifact_path=missing_path,
                        artifact_type=artifact_type,
                        fingerprint=f"missing_required_artifact:{artifact_type}",
                        summary=f"Required artifact {artifact} is missing for {feature_id}",
                        evidence=f"{_safe_relative(self.root, missing_path)} missing",
                        root_cause_status="confirmed",
                        deterministic_invariant="missing_required_artifact",
                    )
                )
        return findings

    def extract_json_findings(
        self,
        path: Path,
        feature_id: str,
        artifact_type: str,
    ) -> list[Finding]:
        try:
            payload = _read_json(path)
        except JSONDecodeError as exc:
            return [
                Finding(
                    feature_id=feature_id,
                    artifact_path=path,
                    artifact_type=artifact_type,
                    fingerprint=f"invalid_json_artifact:{artifact_type}",
                    summary=f"{artifact_type} artifact contains invalid JSON",
                    evidence=exc.msg,
                    root_cause_status="confirmed",
                    deterministic_invariant="invalid_json_artifact",
                )
            ]
        if not isinstance(payload, dict):
            return []

        source_run_id = self.extract_source_run_id(payload)
        findings: list[Finding] = []
        if artifact_type == "ack":
            ack_level = str(payload.get("ack_level", "")).lower()
            if ack_level != "usable":
                findings.append(
                    Finding(
                        feature_id=feature_id,
                        artifact_path=path,
                        artifact_type=artifact_type,
                        fingerprint="ack_non_usable",
                        summary=f"ACK level is {ack_level or 'missing'}",
                        evidence=canonical_json(payload)[:500],
                        root_cause_status="confirmed",
                        deterministic_invariant="ack_non_usable",
                        source_run_id=source_run_id,
                    )
                )
        elif artifact_type == "review_verdict":
            verdict = str(payload.get("verdict", "")).upper()
            if verdict != "PASS":
                findings.append(
                    Finding(
                        feature_id=feature_id,
                        artifact_path=path,
                        artifact_type=artifact_type,
                        fingerprint="review_verdict_not_pass",
                        summary=f"Review verdict is {verdict or 'missing'}",
                        evidence=canonical_json(payload)[:500],
                        root_cause_status="confirmed",
                        deterministic_invariant="review_verdict_not_pass",
                        source_run_id=source_run_id,
                    )
                )
        elif artifact_type == "integrated_tests":
            status = str(payload.get("status", "")).lower()
            if status and status not in {"passed", "pass"}:
                findings.append(
                    Finding(
                        feature_id=feature_id,
                        artifact_path=path,
                        artifact_type=artifact_type,
                        fingerprint="integrated_tests_not_passed",
                        summary=f"Integrated tests status is {status}",
                        evidence=canonical_json(payload)[:500],
                        root_cause_status="confirmed",
                        deterministic_invariant="integrated_tests_not_passed",
                        source_run_id=source_run_id,
                    )
                )
            if payload.get("stale_against_current_target_head") is True or (
                status and "stale_target_head" in status
            ):
                findings.append(
                    Finding(
                        feature_id=feature_id,
                        artifact_path=path,
                        artifact_type=artifact_type,
                        fingerprint="stale_target_head",
                        summary="Integrated test evidence is stale against target HEAD",
                        evidence=canonical_json(payload)[:500],
                        root_cause_status="confirmed",
                        deterministic_invariant="stale_target_head",
                        source_run_id=source_run_id,
                    )
                )
        findings.extend(
            self.extract_json_text_findings(
                payload,
                path=path,
                feature_id=feature_id,
                artifact_type=artifact_type,
                source_run_id=source_run_id,
            )
        )
        return self.deduplicate_findings(findings)

    def extract_json_text_findings(
        self,
        payload: dict[str, Any],
        *,
        path: Path,
        feature_id: str,
        artifact_type: str,
        source_run_id: str | None,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for line in self.iter_json_evidence_lines(payload):
            lower = line.lower()
            finding = self.finding_from_markdown_line(
                line,
                lower,
                path=path,
                feature_id=feature_id,
                artifact_type=artifact_type,
                source_run_id=source_run_id,
            )
            if finding is not None:
                findings.append(finding)
        return findings

    def iter_json_evidence_lines(self, value: Any) -> list[str]:
        lines: list[str] = []

        def walk(item: Any) -> None:
            if isinstance(item, dict):
                command = item.get("command")
                status = str(item.get("status", "")).lower()
                if isinstance(command, str) and any(
                    marker in status
                    for marker in ("fail", "error", "interrupted", "blocked")
                ):
                    summary = item.get("summary")
                    suffix = f": {summary}" if isinstance(summary, str) and summary else ""
                    lines.append(f"{command} failed{suffix}")
                for nested in item.values():
                    walk(nested)
            elif isinstance(item, list):
                for nested in item:
                    walk(nested)
            elif isinstance(item, str):
                lines.append(item)

        walk(value)
        return lines

    def deduplicate_findings(self, findings: list[Finding]) -> list[Finding]:
        unique: dict[tuple[str, str], Finding] = {}
        for finding in findings:
            if finding.deterministic_invariant is not None:
                key = (finding.fingerprint, finding.deterministic_invariant)
            else:
                key = (finding.fingerprint, finding.evidence)
            unique[key] = finding
        return list(unique.values())

    def extract_markdown_findings(
        self,
        path: Path,
        feature_id: str,
        artifact_type: str,
    ) -> list[Finding]:
        text = path.read_text(encoding="utf-8", errors="replace")[:200_000]
        digest_seen: set[tuple[str, str]] = set()
        findings: list[Finding] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            finding = self.finding_from_markdown_line(
                line,
                lower,
                path=path,
                feature_id=feature_id,
                artifact_type=artifact_type,
            )
            if finding is None:
                continue
            dedup_key = (finding.fingerprint, finding.evidence)
            if dedup_key in digest_seen:
                continue
            digest_seen.add(dedup_key)
            findings.append(finding)
        return findings

    def finding_from_markdown_line(
        self,
        line: str,
        lower: str,
        *,
        path: Path,
        feature_id: str,
        artifact_type: str,
        source_run_id: str | None = None,
    ) -> Finding | None:
        verification = "verification evidence" in lower
        command_match = re.search(
            r"((?:uv|pytest|python|mypy|ruff|make|git)\s+[^`|;:]*?)\s+"
            r"(?:fails?|failed|reports?\s+\w*\s*failed)\b",
            line,
            flags=re.IGNORECASE,
        )
        if command_match:
            command = command_match.group(1).strip()
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint=f"failed_command:{normalize_command(command)}",
                summary=f"Command failed: {command}",
                evidence=line[:500],
                root_cause_status="confirmed" if verification else "suspected",
                verification_evidence=verification,
                source_run_id=source_run_id,
            )
        if "hard eval" in lower and (
            "baseline" in lower or "drift" in lower or "instead of stated" in lower
        ):
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="baseline_drift:hard-eval",
                summary="Hard eval drift or baseline mismatch reported",
                evidence=line[:500],
                root_cause_status="suspected",
                promotion_suppressed=True,
                source_run_id=source_run_id,
            )
        if "network timeout" in lower or ("transient" in lower and "timeout" in lower):
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="environment:network-timeout",
                summary="Transient network timeout reported",
                evidence=line[:500],
                root_cause_status="suspected",
                promotion_suppressed=True,
                source_run_id=source_run_id,
            )
        if "stale_target_head" in lower or (
            "stale" in lower and "target" in lower and "head" in lower
        ):
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="stale_target_head",
                summary="Gate evidence is stale against target HEAD",
                evidence=line[:500],
                root_cause_status="confirmed",
                deterministic_invariant="stale_target_head",
                source_run_id=source_run_id,
            )
        if (
            "external merge approval is absent" in lower
            or "merge requested without explicit approval" in lower
        ):
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="merge_requested_without_approval",
                summary="Merge is blocked by missing explicit approval",
                evidence=line[:500],
                root_cause_status="confirmed",
                deterministic_invariant="merge_requested_without_approval",
                source_run_id=source_run_id,
            )
        if "approval artifact digest mismatch" in lower:
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="approval_artifact_digest_mismatch",
                summary="Approval artifact digest mismatch reported",
                evidence=line[:500],
                root_cause_status="confirmed",
                deterministic_invariant="approval_artifact_digest_mismatch",
                source_run_id=source_run_id,
            )
        if "root cause:" in lower:
            return Finding(
                feature_id=feature_id,
                artifact_path=path,
                artifact_type=artifact_type,
                fingerprint="markdown_diagnosis:free-form-root-cause",
                summary="Markdown-only root cause diagnosis",
                evidence=line[:500],
                root_cause_status="suspected",
                source_run_id=source_run_id,
            )
        return None

    def extract_source_run_id(self, payload: dict[str, Any]) -> str | None:
        for key in ("source_run_id", "run_id", "knowledge_run_id", "head_commit"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def write_error_records(self, findings: list[Finding]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_records: set[str] = set()
        for finding in findings:
            if finding.artifact_path.exists():
                digest = sha256_file(finding.artifact_path)
            else:
                digest = sha256_text("missing:" + _safe_relative(self.root, finding.artifact_path))
            ref = source_ref(
                self.root,
                finding.artifact_path,
                artifact_type=finding.artifact_type,
                feature_id=finding.feature_id,
                digest=digest,
                source_run_id=finding.source_run_id,
            )
            record_id = stable_id(
                "error",
                finding.fingerprint,
                ref["path"],
                digest,
                finding.evidence,
            )
            if record_id in seen_records:
                continue
            seen_records.add(record_id)
            rel_path = f"xmuse/knowledge/error_records/{finding.feature_id}/{record_id}.json"
            existing_path = self.root / rel_path
            if existing_path.exists():
                record = _read_json(existing_path)
                record["last_seen_at"] = self.now
                record["last_knowledge_run_id"] = self.run_id
            else:
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "error_record",
                    "record_id": record_id,
                    "knowledge_run_id": self.run_id,
                    "extractor_version": EXTRACTOR_VERSION,
                    "created_at": self.now,
                    "last_seen_at": self.now,
                    "feature_id": finding.feature_id,
                    "fingerprint": finding.fingerprint,
                    "summary": finding.summary,
                    "evidence": finding.evidence,
                    "source_ref": ref,
                    "source_refs": [ref],
                    "source_digest": ref["digest"],
                    "root_cause_status": finding.root_cause_status,
                    "deterministic_invariant": finding.deterministic_invariant,
                    "verification_evidence": finding.verification_evidence,
                    "promotion_suppressed": finding.promotion_suppressed,
                }
            self.write_json(rel_path, record, object_write=True)
            self.generated["error_records"].append(record_id)
            records.append(record)
        return records

    def write_clusters(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_cluster: dict[str, dict[str, Any]] = {}
        for record in records:
            cluster_id = stable_id("cluster", record["fingerprint"])
            rel_path = f"xmuse/knowledge/clusters/{cluster_id}.json"
            if cluster_id in by_cluster:
                cluster = by_cluster[cluster_id]
            elif (self.root / rel_path).exists():
                cluster = _read_json(self.root / rel_path)
            else:
                cluster = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "cluster",
                    "cluster_id": cluster_id,
                    "knowledge_run_id": self.run_id,
                    "extractor_version": EXTRACTOR_VERSION,
                    "created_at": self.now,
                    "fingerprint": record["fingerprint"],
                    "summary": record["summary"],
                    "occurrences": [],
                    "source_refs": [],
                    "promotion_stage": "observed",
                    "promotion_blockers": [],
                }
            cluster_artifacts.add_record_to_cluster(cluster, record)
            by_cluster[cluster_id] = cluster

        clusters = []
        for cluster in by_cluster.values():
            self.prune_missing_cluster_records(cluster)
            cluster_artifacts.recompute_cluster(cluster, now=self.now, run_id=self.run_id)
            rel_path = f"xmuse/knowledge/clusters/{cluster['cluster_id']}.json"
            self.write_json(rel_path, cluster, object_write=True)
            self.generated["clusters"].append(cluster["cluster_id"])
            clusters.append(cluster)
        return clusters

    def prune_missing_cluster_records(self, cluster: dict[str, Any]) -> None:
        kept_occurrences = []
        kept_refs = []
        for occurrence in cluster.get("occurrences", []):
            record_path = (
                self.knowledge_dir
                / "error_records"
                / str(occurrence.get("feature_id", ""))
                / f"{occurrence.get('record_id')}.json"
            )
            if not record_path.exists():
                continue
            kept_occurrences.append(occurrence)
            record = _read_json(record_path)
            if isinstance(record.get("source_ref"), dict):
                kept_refs.append(record["source_ref"])
            elif isinstance(record.get("source_refs"), list):
                kept_refs.extend(record["source_refs"])
        cluster["occurrences"] = kept_occurrences
        cluster["source_refs"] = unique_source_refs(kept_refs)

    def write_methods(self, clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        methods = []
        for cluster in clusters:
            if cluster.get("promotion_stage") != "method_created":
                continue
            method_id = stable_id("method", cluster["cluster_id"])
            method_dir_rel = f"xmuse/knowledge/methods/{method_id}"
            manifest_rel = f"{method_dir_rel}/manifest.json"
            manifest_path = self.root / manifest_rel
            generated_body = cluster_artifacts.render_method(cluster, method_id)
            generated_digest = sha256_text(generated_body)
            if manifest_path.exists():
                manifest = _read_json(manifest_path)
                manifest["updated_at"] = self.now
            else:
                manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "method_manifest",
                    "method_id": method_id,
                    "knowledge_run_id": self.run_id,
                    "extractor_version": EXTRACTOR_VERSION,
                    "created_at": self.now,
                    "status": "draft",
                    "quarantined": True,
                    "activation_status": "not_active",
                    "cluster_id": cluster["cluster_id"],
                    "tombstones": [],
                }
            manifest["last_knowledge_run_id"] = self.run_id
            manifest["last_generated_digest"] = generated_digest
            manifest["source_refs"] = unique_source_refs(cluster["source_refs"])
            manifest["source_digest"] = source_digest_for_refs(manifest["source_refs"])
            manifest["occurrence_count"] = cluster["occurrence_count"]
            manifest["feature_count"] = cluster["feature_count"]
            self.write_current_or_revision(method_dir_rel, generated_body, generated_digest)
            self.write_json(manifest_rel, manifest, object_write=True)
            for subdir in ("revisions", "tombstones"):
                (self.root / method_dir_rel / subdir).mkdir(parents=True, exist_ok=True)
            self.generated["methods"].append(method_id)
            methods.append(manifest)
        return methods

    def write_current_or_revision(
        self,
        object_dir_rel: str,
        generated_body: str,
        generated_digest: str,
    ) -> None:
        current_rel = f"{object_dir_rel}/current.md"
        current_path = self.root / current_rel
        content = f"<!-- xmuse-generated-digest:{generated_digest} -->\n{generated_body}"
        if current_path.exists():
            current_text = current_path.read_text(encoding="utf-8")
            if current_text != content:
                revision_rel = (
                    f"{object_dir_rel}/revisions/"
                    f"{self.run_id}-{generated_digest.removeprefix('sha256:')[:12]}.md"
                )
                self.write_text(revision_rel, content, object_write=True)
                return
        self.write_text(current_rel, content, object_write=True)

    def write_skill_proposals(
        self,
        methods: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        proposals = []
        clusters_by_id = {cluster["cluster_id"]: cluster for cluster in clusters}
        for method in methods:
            cluster = clusters_by_id.get(method["cluster_id"], {})
            if len(methods) < 2 and cluster.get("feature_count", 0) < 2:
                continue
            proposal_id = stable_id("proposal", method["method_id"])
            proposal_dir_rel = f"xmuse/knowledge/skill_proposals/{proposal_id}"
            manifest_rel = f"{proposal_dir_rel}/manifest.json"
            manifest_path = self.root / manifest_rel
            body = cluster_artifacts.render_skill_proposal(method, proposal_id)
            digest = sha256_text(body)
            if manifest_path.exists():
                manifest = _read_json(manifest_path)
                if not isinstance(manifest, dict):
                    manifest = {}
            else:
                manifest = {
                    "knowledge_run_id": self.run_id,
                    "created_at": self.now,
                }
            source_refs = unique_source_refs(method.get("source_refs", []))
            tombstones = manifest.get("tombstones")
            manifest.update(
                {
                    "schema_version": SCHEMA_VERSION,
                    "object_type": "skill_proposal_manifest",
                    "proposal_id": proposal_id,
                    "extractor_version": EXTRACTOR_VERSION,
                    "updated_at": self.now,
                    "status": "draft",
                    "quarantined": True,
                    "activation_status": "not_installed",
                    "method_ids": [method["method_id"]],
                    "source_refs": source_refs,
                    "source_digest": source_digest_for_refs(source_refs),
                    "last_generated_digest": digest,
                    "last_knowledge_run_id": self.run_id,
                    "tombstones": tombstones if isinstance(tombstones, list) else [],
                }
            )
            manifest.setdefault("knowledge_run_id", self.run_id)
            manifest.setdefault("created_at", self.now)
            self.write_current_or_revision(proposal_dir_rel, body, digest)
            self.write_json(manifest_rel, manifest, object_write=True)
            for subdir in ("revisions", "tombstones"):
                (self.root / proposal_dir_rel / subdir).mkdir(parents=True, exist_ok=True)
            self.generated["skill_proposals"].append(proposal_id)
            proposals.append(manifest)
        return proposals

    def write_run_summary(
        self,
        records: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        methods: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
    ) -> None:
        source_refs = unique_source_refs(
            [ref for record in records for ref in record.get("source_refs", [])]
        )
        summary = {
            "schema_version": SCHEMA_VERSION,
            "object_type": "knowledge_run",
            "knowledge_run_id": self.run_id,
            "extractor_version": EXTRACTOR_VERSION,
            "recorded_at": self.now,
            "feature_id": FEATURE_ID,
            "source_refs": source_refs,
            "source_digest": source_digest_for_refs(source_refs),
            "scanned_artifacts": sorted(set(self.scanned_artifacts)),
            "diagnostics": self.diagnostics,
            "generated_or_updated": self.generated,
            "counts": {
                "error_records": len(records),
                "clusters": len(clusters),
                "methods": len(methods),
                "skill_proposals": len(proposals),
                "blocked_clusters": len(
                    [cluster for cluster in clusters if cluster.get("promotion_blockers")]
                ),
                "promoted_clusters": len(
                    [
                        cluster
                        for cluster in clusters
                        if cluster.get("promotion_stage") == "method_created"
                    ]
                ),
            },
        }
        self.write_json(f"xmuse/knowledge/runs/{self.run_id}.json", summary, object_write=True)

    def rebuild_indexes(self) -> None:
        indexes = {
            "error_index": self.collect_index(
                "xmuse/knowledge/error_records/*/*.json",
                "record_id",
            ),
            "cluster_index": self.collect_index("xmuse/knowledge/clusters/*.json", "cluster_id"),
            "method_index": self.collect_index(
                "xmuse/knowledge/methods/*/manifest.json",
                "method_id",
            ),
            "proposal_index": self.collect_index(
                "xmuse/knowledge/skill_proposals/*/manifest.json",
                "proposal_id",
            ),
        }
        for name, paths in indexes.items():
            source_refs = self.source_refs_for_index(paths)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "object_type": name,
                "knowledge_run_id": self.run_id,
                "extractor_version": EXTRACTOR_VERSION,
                "updated_at": self.now,
                "source_refs": source_refs,
                "source_digest": source_digest_for_refs(source_refs),
                "paths": paths,
            }
            self.write_json(f"xmuse/knowledge/indexes/{name}.json", payload)

    def collect_index(self, pattern: str, id_key: str) -> dict[str, str]:
        paths: dict[str, str] = {}
        for path in sorted(self.root.glob(pattern)):
            if not path.is_file():
                continue
            payload = _read_json(path)
            object_id = payload.get(id_key)
            if isinstance(object_id, str) and object_id:
                paths[object_id] = _safe_relative(self.root, path)
        return paths

    def source_refs_for_index(self, paths: dict[str, str]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for rel_path in paths.values():
            payload = _read_json(self.root / rel_path)
            if isinstance(payload.get("source_refs"), list):
                refs.extend(payload["source_refs"])
            elif isinstance(payload.get("source_ref"), dict):
                refs.append(payload["source_ref"])
        if refs:
            return unique_source_refs(refs)
        return self.all_source_refs()

    def all_source_refs(self) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for path in sorted((self.root / "xmuse/knowledge/error_records").glob("*/*.json")):
            payload = _read_json(path)
            if isinstance(payload.get("source_refs"), list):
                refs.extend(payload["source_refs"])
            elif isinstance(payload.get("source_ref"), dict):
                refs.append(payload["source_ref"])
        return unique_source_refs(refs)

    def write_handoff_artifacts(
        self,
        *,
        status: str,
        records: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        methods: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
        blockers: list[str] | None = None,
    ) -> None:
        blockers = blockers or []
        result_md = render_result_markdown(
            feature_id=FEATURE_ID,
            status=status,
            run_id=self.run_id,
            record_count=len(records),
            cluster_count=len(clusters),
            method_count=len(methods),
            proposal_count=len(proposals),
            blockers=blockers,
        )
        review = build_review_verdict(
            feature_id=FEATURE_ID,
            status=status,
            blockers=blockers,
        )
        ack = build_ack(
            feature_id=FEATURE_ID,
            status=status,
            root=self.root,
            head_ref=self.current_head_ref(),
            run_id=self.run_id,
            blockers=blockers,
        )
        slave_state = build_slave_state(
            feature_id=FEATURE_ID,
            status=status,
            root=self.root,
            now=self.now,
            run_id=self.run_id,
        )
        self.write_text(f"xmuse/work/features/{FEATURE_ID}/result.md", result_md)
        self.write_json(f"xmuse/work/features/{FEATURE_ID}/review_verdict.json", review)
        self.write_json(f"xmuse/work/features/{FEATURE_ID}/ack.json", ack)
        self.write_json(f"xmuse/work/features/{FEATURE_ID}/slave_state.json", slave_state)

    def current_head_ref(self) -> str:
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        except OSError:
            return "unknown"
        if branch and commit:
            return f"{branch}@{commit}"
        return commit or branch or "unknown"


def missing_required_inputs(root: Path) -> list[str]:
    blockers = []
    for rel in REQUIRED_INPUTS:
        if not (root / rel).exists():
            blockers.append(f"missing required input: {rel}")
    return blockers


def run_knowledge_maintenance(
    root: str | Path = ".",
    *,
    run_id: str | None = None,
    now: str | None = None,
    fail_after_object_writes: int | None = None,
) -> dict[str, Any]:
    root = Path(root)
    actual_run_id = run_id or f"knowledge-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    actual_now = now or utc_now()
    contract = validate_contract(root)
    if not contract["valid"]:
        return _write_bootstrap_blocked(
            root,
            contract["blockers"],
            run_id=actual_run_id,
            now=actual_now,
        )
    blockers = missing_required_inputs(root)
    if blockers:
        return _write_bootstrap_blocked(root, blockers, run_id=actual_run_id, now=actual_now)
    maintainer = KnowledgeMaintainer(
        root,
        run_id=actual_run_id,
        now=actual_now,
        fail_after_object_writes=fail_after_object_writes,
    )
    return maintainer.run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    result = run_knowledge_maintenance(args.root, run_id=args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "usable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
