"""Append-only M5C Narrative-lifecycle evidence ORM models (design Section 7.1).

Every row is immutable evidence: drafts, revisions, extraction attempts / results, and
proposal change sets are written once and never updated. All authority references use
``RESTRICT`` so evidence lineage can never be deleted, and cross-row scope FKs carry
``(user_id, project_name)`` so a bare opaque id cannot join two tenants or bind a
revision to an incompatible attempt.

The rule "a SUCCEEDED extraction result owns >=1 ordered change-set association row and a
non-success result owns none" is a cross-row invariant: it is enforced inside the
repository transaction (research Section 3.1), not by a DB CHECK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, UserOwnedMixin

_ID = String(255)
_SHORT = String(64)
_EXTRACTION_OUTCOMES = "('SUCCEEDED','ABSTAINED','CONFLICT','FAILED','OUTCOME_UNKNOWN')"


class NarrativeDraftCandidateModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_draft_candidates"
    __table_args__ = (
        UniqueConstraint("user_id", "project_name", "candidate_id", name="uq_narrative_draft_candidates_scope"),
        CheckConstraint("plan_version >= 1", name="ck_narrative_draft_candidates_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_narrative_draft_candidates_scene_version"),
        Index("ix_narrative_draft_candidates_project_name", "project_name"),
    )

    candidate_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    writer_kind: Mapped[str] = mapped_column(String(255), nullable=False)
    writer_version: Mapped[str] = mapped_column(String(255), nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)


class NarrativeRevisionModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_revisions"
    __table_args__ = (
        UniqueConstraint("user_id", "project_name", "revision_id", name="uq_narrative_revisions_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "base_candidate_id"],
            [
                "narrative_draft_candidates.user_id",
                "narrative_draft_candidates.project_name",
                "narrative_draft_candidates.candidate_id",
            ],
            name="fk_narrative_revisions_base_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "predecessor_revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_revisions_predecessor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("plan_version >= 1", name="ck_narrative_revisions_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_narrative_revisions_scene_version"),
        CheckConstraint(
            "predecessor_revision_id IS NULL OR predecessor_revision_id <> revision_id",
            name="ck_narrative_revisions_predecessor_not_self",
        ),
        Index("ix_narrative_revisions_project_name", "project_name"),
    )

    revision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    base_candidate_id: Mapped[str] = mapped_column(_ID, nullable=False)
    predecessor_revision_id: Mapped[str | None] = mapped_column(_ID)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    review_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)


class NarrativeExtractionAttemptModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_extraction_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_id", "generation", name="uq_narrative_extraction_attempts_generation"),
        UniqueConstraint("user_id", "project_name", "attempt_id", name="uq_narrative_extraction_attempts_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_extraction_attempts_revision",
            ondelete="RESTRICT",
        ),
        CheckConstraint("generation >= 0", name="ck_narrative_extraction_attempts_generation"),
        CheckConstraint(
            "observed_revision_effective_generation >= 0",
            name="ck_narrative_extraction_attempts_observed_generation",
        ),
        CheckConstraint("plan_version >= 1", name="ck_narrative_extraction_attempts_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_narrative_extraction_attempts_scene_version"),
        Index("ix_narrative_extraction_attempts_project_name", "project_name"),
    )

    attempt_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    revision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    observed_revision_effective_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    extractor_kind: Mapped[str] = mapped_column(String(255), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    policy_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)


class NarrativeExtractionResultModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_extraction_results"
    __table_args__ = (
        UniqueConstraint("attempt_id", "generation", name="uq_narrative_extraction_results_generation"),
        UniqueConstraint("user_id", "project_name", "result_id", name="uq_narrative_extraction_results_scope"),
        ForeignKeyConstraint(
            ["attempt_id", "generation"],
            [
                "narrative_extraction_attempts.attempt_id",
                "narrative_extraction_attempts.generation",
            ],
            name="fk_narrative_extraction_results_attempt_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "narrative_extraction_attempts.user_id",
                "narrative_extraction_attempts.project_name",
                "narrative_extraction_attempts.attempt_id",
            ],
            name="fk_narrative_extraction_results_attempt_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("generation >= 0", name="ck_narrative_extraction_results_generation"),
        CheckConstraint(f"outcome IN {_EXTRACTION_OUTCOMES}", name="ck_narrative_extraction_results_outcome"),
        Index("ix_narrative_extraction_results_project_name", "project_name"),
    )

    result_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_id: Mapped[str] = mapped_column(_ID, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    diagnostics_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    provider_receipt_json: Mapped[Any | None] = mapped_column(JSON)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    output_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)


class NarrativeChangeSetModel(UserOwnedMixin, Base):
    __tablename__ = "narrative_change_sets"
    __table_args__ = (
        UniqueConstraint("user_id", "project_name", "change_set_id", name="uq_narrative_change_sets_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "source_revision_id"],
            [
                "narrative_revisions.user_id",
                "narrative_revisions.project_name",
                "narrative_revisions.revision_id",
            ],
            name="fk_narrative_change_sets_source_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["extraction_attempt_id", "extraction_generation"],
            [
                "narrative_extraction_attempts.attempt_id",
                "narrative_extraction_attempts.generation",
            ],
            name="fk_narrative_change_sets_attempt_generation",
            ondelete="RESTRICT",
        ),
        CheckConstraint("extraction_generation >= 0", name="ck_narrative_change_sets_generation"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_narrative_change_sets_confidence"),
        Index("ix_narrative_change_sets_project_name", "project_name"),
        Index("ix_narrative_change_sets_lineage", "change_set_lineage_id"),
    )

    change_set_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    change_set_lineage_id: Mapped[str] = mapped_column(_ID, nullable=False)
    source_revision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    extraction_attempt_id: Mapped[str] = mapped_column(_ID, nullable=False)
    extraction_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    source_spans_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    semantic_effect_keys_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    changes_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    policy_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    output_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)


class NarrativeExtractionResultChangeSetModel(UserOwnedMixin, Base):
    """Ordered proof that a SUCCEEDED extraction result declares exactly this set of
    change sets, in this order. One row per (result, change set)."""

    __tablename__ = "narrative_extraction_result_change_sets"
    __table_args__ = (
        UniqueConstraint("result_id", "position", name="uq_narrative_extraction_result_change_sets_position"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "result_id"],
            [
                "narrative_extraction_results.user_id",
                "narrative_extraction_results.project_name",
                "narrative_extraction_results.result_id",
            ],
            name="fk_narrative_extraction_result_change_sets_result",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "change_set_id"],
            [
                "narrative_change_sets.user_id",
                "narrative_change_sets.project_name",
                "narrative_change_sets.change_set_id",
            ],
            name="fk_narrative_extraction_result_change_sets_change_set",
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="ck_narrative_extraction_result_change_sets_position"),
        Index("ix_narrative_extraction_result_change_sets_change_set", "change_set_id"),
    )

    result_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    change_set_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
