from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONTRACT_DIGEST = "sha256:03ed21bdc04bed3db221f755e2920700a74730d1615d853bc91c2b52a89eb0dc"
DIAGNOSTICS_DIGEST = "sha256:662ce085d09e8c6889926d698abb2ac35bcb97b06e2fac62b7491d7b4282acd0"
TOP_LEVEL_KEYS = {
    "schema",
    "items",
    "omitted_count",
    "estimated_tokens",
    "truncated",
    "diagnostics_digest",
}
ITEM_KEYS = {
    "item_id",
    "archive_id",
    "document_id",
    "source_refs",
    "text",
    "estimated_tokens",
    "content_sha256",
    "score",
    "rank",
    "truncated",
}
ADVISORY_V2_DIGEST = "sha256:5358e9965e419bc01cb1408c14a297ec72260a94ffa122ce517b0f1f4b14ae81"
ADVISORY_V2_ITEM_KEYS = {
    "advisory_id",
    "fingerprint",
    "proposal_type",
    "kind",
    "topic_key",
    "content",
    "source_refs",
    "supersedes_advisory_id",
}
ADVISORY_V2_REF_KEYS = {"source_type", "source_id", "session_id", "quote"}
FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"
GOLDEN = FIXTURES / "memoryos_source_evidence_v1.json"
DIGEST = FIXTURES / "memoryos_source_evidence_v1.sha256"
GOLDEN_V2 = FIXTURES / "memoryos_external_advisories_v2.json"
DIGEST_V2 = FIXTURES / "memoryos_external_advisories_v2.sha256"


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_source_evidence_golden_is_canonical_utf8_and_digest_frozen() -> None:
    raw = GOLDEN.read_bytes()
    payload = json.loads(raw)

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.endswith(b"\n")
    assert raw == _canonical(payload)
    assert _sha256(raw) == CONTRACT_DIGEST
    assert DIGEST.read_bytes() == CONTRACT_DIGEST.encode("ascii")


def test_source_evidence_golden_freezes_exact_wire_and_proofs() -> None:
    payload = json.loads(GOLDEN.read_bytes())

    assert set(payload) == TOP_LEVEL_KEYS
    assert payload["schema"] == "memoryos_source_evidence/v1"
    assert payload["estimated_tokens"] == 20
    assert payload["omitted_count"] == 1
    assert payload["truncated"] is True
    items = payload["items"]
    assert len(items) == 2
    assert [item["rank"] for item in items] == [1, 2]
    assert all(set(item) == ITEM_KEYS for item in items)
    assert items[0]["source_refs"] == [{"source_id": "activity-001", "source_type": "document"}]
    assert items[1]["source_refs"] == [
        {"source_id": "activity-002", "source_type": "document"},
        {"source_id": "activity-003", "source_type": "document"},
    ]
    assert items[1]["text"] == "项目偏好：默认使用只读沙箱 🧠"
    for item in items:
        assert item["content_sha256"] == _sha256(item["text"].encode("utf-8"))
        assert item["truncated"] is False
    diagnostic_payload = {
        key: value for key, value in payload.items() if key != "diagnostics_digest"
    }
    assert payload["diagnostics_digest"] == DIAGNOSTICS_DIGEST
    assert payload["diagnostics_digest"] == _sha256(_canonical(diagnostic_payload))


def test_advisory_v2_golden_is_canonical_utf8_and_digest_frozen() -> None:
    raw = GOLDEN_V2.read_bytes()
    payload = json.loads(raw)

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.endswith(b"\n")
    assert raw == _canonical(payload)
    assert _sha256(raw) == ADVISORY_V2_DIGEST
    assert DIGEST_V2.read_bytes() == ADVISORY_V2_DIGEST.encode("ascii")


def test_advisory_v2_golden_freezes_exact_wire_and_quote_proof_fields() -> None:
    payload = json.loads(GOLDEN_V2.read_bytes())

    assert set(payload) == {"schema", "items"}
    assert payload["schema"] == "memoryos_external_advisories/v2"
    items = payload["items"]
    assert len(items) == 1
    item = items[0]
    assert set(item) == ADVISORY_V2_ITEM_KEYS
    assert item["proposal_type"] == "curated_memory"
    assert item["kind"] in {"room_fact", "room_decision", "project_rule", "user_preference"}
    assert len(item["fingerprint"]) == 64
    assert int(item["fingerprint"], 16) >= 0
    assert item["supersedes_advisory_id"] is None
    assert 0 < len(item["content"].encode("utf-8")) <= 4096
    refs = item["source_refs"]
    assert 1 <= len(refs) <= 8
    for ref in refs:
        assert set(ref) == ADVISORY_V2_REF_KEYS
        assert ref["source_type"] == "message"
        assert len(ref["quote"]) >= 8
        assert ref["quote"].strip()
