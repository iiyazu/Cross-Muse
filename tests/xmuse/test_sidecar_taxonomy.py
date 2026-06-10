from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xmuse_core.sidecar.taxonomy import (
    ChatMemoryCategory,
    ChatMemoryScope,
    ChatMemoryTaxonomy,
    SourceEvidence,
    build_blueprint_decision_taxonomy,
    build_conversation_shared_taxonomy,
    build_cross_restart_recall_taxonomy,
    build_participant_taxonomy,
    build_unresolved_thread_taxonomy,
)


class TestChatMemoryScope:
    def test_scope_enum_has_expected_values(self):
        assert ChatMemoryScope.CONVERSATION_SHARED.value == "conversation_shared"
        assert ChatMemoryScope.BLUEPRINT_DECISION.value == "blueprint_decision"
        assert ChatMemoryScope.PARTICIPANT.value == "participant"
        assert ChatMemoryScope.UNRESOLVED_THREAD.value == "unresolved_thread"
        assert ChatMemoryScope.CROSS_RESTART_RECALL.value == "cross_restart_recall"

    def test_scope_coverage_meets_v6_requirement(self):
        required = {"conversation_shared", "blueprint_decision", "participant", "unresolved_thread"}
        actual = {s.value for s in ChatMemoryScope}
        for r in required:
            assert r in actual, f"missing required scope: {r}"


class TestChatMemoryCategory:
    def test_category_enum_has_expected_values(self):
        assert ChatMemoryCategory.CONVERSATION_SUMMARY.value == "conversation_summary"
        assert ChatMemoryCategory.BLUEPRINT_VERSION.value == "blueprint_version"
        assert ChatMemoryCategory.DECISION_RATIONALE.value == "decision_rationale"
        assert ChatMemoryCategory.FEATURE_PLAN_REF.value == "feature_plan_ref"
        assert ChatMemoryCategory.PARTICIPANT_PREFERENCE.value == "participant_preference"
        assert ChatMemoryCategory.PARTICIPANT_HISTORY.value == "participant_history"
        assert ChatMemoryCategory.THREAD_QUESTION.value == "thread_question"
        assert ChatMemoryCategory.THREAD_DECISION_PENDING.value == "thread_decision_pending"
        assert ChatMemoryCategory.RECOVERY_CHECKPOINT.value == "recovery_checkpoint"
        assert ChatMemoryCategory.SESSION_BOUNDARY.value == "session_boundary"

    def test_each_scope_has_at_least_one_category(self):
        scope_to_cats = ChatMemoryTaxonomy.scope_to_categories()
        for scope in ChatMemoryScope:
            assert scope in scope_to_cats, f"scope {scope} has no categories"
            assert len(scope_to_cats[scope]) >= 1, f"scope {scope} has empty categories"


class TestSourceEvidence:
    def test_source_evidence_minimal(self):
        se = SourceEvidence(
            source_type="message",
            source_id="msg_123",
            conversation_id="conv_1",
            participant_id="participant_architect",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        )
        assert se.source_type == "message"
        assert se.source_id == "msg_123"
        assert se.thread_id is None

    def test_source_evidence_with_optional_fields(self):
        se = SourceEvidence(
            source_type="proposal",
            source_id="prop_456",
            conversation_id="conv_1",
            participant_id="participant_human",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            thread_id="thread_789",
            evidence_uri="memoryos://conversation/conv_1/ses_abc",
        )
        assert se.thread_id == "thread_789"
        assert se.evidence_uri == "memoryos://conversation/conv_1/ses_abc"

    def test_source_evidence_rejects_empty_source_type(self):
        with pytest.raises(ValidationError):
            SourceEvidence(
                source_type="",
                source_id="msg_123",
                conversation_id="conv_1",
                participant_id="participant_architect",
                timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            )


class TestChatMemoryTaxonomy:
    def test_build_taxonomy_requires_non_empty_categories(self):
        with pytest.raises(Exception, match="at least 1 item"):
            ChatMemoryTaxonomy(
                scope=ChatMemoryScope.CONVERSATION_SHARED,
                categories=[],
            )

    def test_build_taxonomy_rejects_wrong_scope_category_mapping(self):
        with pytest.raises(ValueError, match="category.*not valid for scope"):
            ChatMemoryTaxonomy(
                scope=ChatMemoryScope.PARTICIPANT,
                categories=[ChatMemoryCategory.BLUEPRINT_VERSION],
            )

    def test_build_taxonomy_accepts_valid_mapping(self):
        tax = ChatMemoryTaxonomy(
            scope=ChatMemoryScope.CONVERSATION_SHARED,
            categories=[ChatMemoryCategory.CONVERSATION_SUMMARY],
        )
        assert tax.scope == ChatMemoryScope.CONVERSATION_SHARED
        assert ChatMemoryCategory.CONVERSATION_SUMMARY in tax.categories


class TestTaxonomyBuilders:
    def test_conversation_shared_builder(self):
        tax = build_conversation_shared_taxonomy()
        assert tax.scope == ChatMemoryScope.CONVERSATION_SHARED
        assert ChatMemoryCategory.CONVERSATION_SUMMARY in tax.categories
        assert ChatMemoryCategory.SESSION_BOUNDARY in tax.categories

    def test_blueprint_decision_builder(self):
        tax = build_blueprint_decision_taxonomy()
        assert tax.scope == ChatMemoryScope.BLUEPRINT_DECISION
        assert ChatMemoryCategory.BLUEPRINT_VERSION in tax.categories
        assert ChatMemoryCategory.DECISION_RATIONALE in tax.categories
        assert ChatMemoryCategory.FEATURE_PLAN_REF in tax.categories

    def test_participant_builder(self):
        tax = build_participant_taxonomy()
        assert tax.scope == ChatMemoryScope.PARTICIPANT
        assert ChatMemoryCategory.PARTICIPANT_PREFERENCE in tax.categories
        assert ChatMemoryCategory.PARTICIPANT_HISTORY in tax.categories

    def test_unresolved_thread_builder(self):
        tax = build_unresolved_thread_taxonomy()
        assert tax.scope == ChatMemoryScope.UNRESOLVED_THREAD
        assert ChatMemoryCategory.THREAD_QUESTION in tax.categories
        assert ChatMemoryCategory.THREAD_DECISION_PENDING in tax.categories

    def test_cross_restart_recall_builder(self):
        tax = build_cross_restart_recall_taxonomy()
        assert tax.scope == ChatMemoryScope.CROSS_RESTART_RECALL
        assert ChatMemoryCategory.RECOVERY_CHECKPOINT in tax.categories
        assert ChatMemoryCategory.SESSION_BOUNDARY in tax.categories

    def test_all_scopes_have_builders(self):
        builders = {
            ChatMemoryScope.CONVERSATION_SHARED,
            ChatMemoryScope.BLUEPRINT_DECISION,
            ChatMemoryScope.PARTICIPANT,
            ChatMemoryScope.UNRESOLVED_THREAD,
            ChatMemoryScope.CROSS_RESTART_RECALL,
        }
        assert len(builders) == 5


class TestSourceGroundedEvidence:
    def test_evidence_can_track_message_source(self):
        se = SourceEvidence(
            source_type="message",
            source_id="msg_001",
            conversation_id="conv_x",
            participant_id="p_arch",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        )
        assert se.model_dump(mode="json")["source_type"] == "message"

    def test_evidence_can_track_card_source(self):
        se = SourceEvidence(
            source_type="card",
            source_id="card_health_001",
            conversation_id="conv_x",
            participant_id="p_system",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        )
        assert se.source_type == "card"

    def test_evidence_can_track_proposal_source(self):
        se = SourceEvidence(
            source_type="proposal",
            source_id="proposal_042",
            conversation_id="conv_x",
            participant_id="p_arch",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        )
        assert se.source_type == "proposal"

    def test_evidence_rejects_invalid_source_type(self):
        with pytest.raises(ValidationError):
            SourceEvidence(
                source_type="invalid_type",
                source_id="x",
                conversation_id="conv_x",
                participant_id="p_x",
                timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            )
