"""Append-only M5C Narrative-lifecycle evidence ORM models.

Every row is immutable evidence: drafts, revisions, extraction attempts / results, and
proposal change sets are written once and never updated. Evidence-to-evidence references
use ``RESTRICT`` so lineage can never be deleted; ``user_id`` ownership follows the
repo-wide ``UserOwnedMixin`` ``CASCADE``. Cross-row FKs carry ``(user_id, project_name)``
so a bare opaque id cannot join two tenants, and attempt / change-set FKs also carry the
exact bases so an evidence row cannot bind to an incompatible revision.

The rule "a SUCCEEDED extraction result owns >=1 ordered change-set association row and a
non-success result owns none" is a cross-row invariant enforced inside the repository
transaction, not by a DB CHECK.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base, UserOwnedMixin

_ID = String(255)
_SHORT = String(64)
_EXTRACTION_OUTCOMES = "('SUCCEEDED','ABSTAINED','CONFLICT','FAILED','OUTCOME_UNKNOWN')"
_DECISION_FAMILIES = "('REVISION_ACCEPTANCE','CHANGE_SET_REVIEW','CONFLICT_RESOLUTION')"
_REVISION_ACTIONS = "('ACCEPT','REJECT','SUPERSEDE')"
_CHANGE_SET_ACTIONS = "('ACCEPT','REJECT','SUPERSEDE')"
_CONFLICT_ACTIONS = "('RESOLVE','REJECT','SUPERSEDE')"


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
        # FK targets: an attempt / change set binds to a revision only when its declared
        # exact bases match this revision's, so an opaque revision_id cannot bind an
        # evidence row to an incompatible revision.
        UniqueConstraint(
            "revision_id",
            "base_canon_version_id",
            "plan_version",
            "scene_contract_version",
            "context_pack_id",
            name="uq_narrative_revisions_full_basis",
        ),
        UniqueConstraint("revision_id", "base_canon_version_id", name="uq_narrative_revisions_canon_basis"),
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
        ForeignKeyConstraint(
            ["revision_id", "base_canon_version_id", "plan_version", "scene_contract_version", "context_pack_id"],
            [
                "narrative_revisions.revision_id",
                "narrative_revisions.base_canon_version_id",
                "narrative_revisions.plan_version",
                "narrative_revisions.scene_contract_version",
                "narrative_revisions.context_pack_id",
            ],
            name="fk_narrative_extraction_attempts_revision_basis",
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
            ["source_revision_id", "base_canon_version_id"],
            ["narrative_revisions.revision_id", "narrative_revisions.base_canon_version_id"],
            name="fk_narrative_change_sets_revision_basis",
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


# --- Narrative decision authority: identity registry, typed decisions, lineage, heads --
#
# Every typed decision row durably owns its exact original Human authorization
# (``authorization_*`` columns) — never the fresh per-request retry authentication, which
# the kernel never persists. Head rows are the only mutable rows in this section; every
# decision/identity/lineage row is append-only. A composite self-FK ties
# ``expected_latest_decision_id`` / ``expected_effective_decision_id`` to a prior decision
# of the *same* typed logical subject, and a composite FK ties each head pointer back to a
# decision of that same subject — a decision from a different subject cannot be linked in
# either direction.


class NarrativeDecisionIdentityModel(UserOwnedMixin, Base):
    """The shared registry enforcing ``decision_id`` uniqueness across all three typed
    decision tables. Every typed decision row's ``(decision_id, decision_family)``
    is a composite FK into this table, so an ID cannot be reused in another family."""

    __tablename__ = "narrative_decision_identities"
    __table_args__ = (
        UniqueConstraint("decision_id", "decision_family", name="uq_narrative_decision_identities_family"),
        CheckConstraint(f"decision_family IN {_DECISION_FAMILIES}", name="ck_narrative_decision_identities_family"),
        Index("ix_narrative_decision_identities_project_name", "project_name"),
    )

    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_family: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_identity_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RevisionAcceptanceDecisionModel(UserOwnedMixin, Base):
    """One typed ``decide_revision`` decision. Its logical subject key is exactly
    ``NarrativeWorkScope``; ``expected_latest_decision_id`` /
    ``expected_effective_decision_id`` are composite self-FKs to a prior decision of that
    same subject, never a bare opaque-ID reference."""

    __tablename__ = "revision_acceptance_decisions"
    __table_args__ = (
        UniqueConstraint("decision_id", "decision_family", name="uq_revision_acceptance_decisions_family"),
        # ``(user_id, project_name, decision_id)`` alone — a *different* column set from
        # the 6-column subject unique below — is a required FK target for
        # ``ChangeSetReviewDecisionModel``/``ConflictResolutionLineageModel``'s scope FKs.
        UniqueConstraint("user_id", "project_name", "decision_id", name="uq_revision_acceptance_decisions_scope"),
        ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_revision_acceptance_decisions_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "decision_id",
            "user_id",
            "project_name",
            "plan_id",
            "scene_contract_id",
            "canon_branch_id",
            name="uq_revision_acceptance_decisions_subject",
        ),
        ForeignKeyConstraint(
            [
                "expected_latest_decision_id",
                "user_id",
                "project_name",
                "plan_id",
                "scene_contract_id",
                "canon_branch_id",
            ],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "expected_effective_decision_id",
                "user_id",
                "project_name",
                "plan_id",
                "scene_contract_id",
                "canon_branch_id",
            ],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision_family = 'REVISION_ACCEPTANCE'", name="ck_revision_acceptance_decisions_family"),
        CheckConstraint(f"action IN {_REVISION_ACTIONS}", name="ck_revision_acceptance_decisions_action"),
        CheckConstraint("plan_version >= 1", name="ck_revision_acceptance_decisions_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_revision_acceptance_decisions_scene_version"),
        CheckConstraint("decision_generation >= 1", name="ck_revision_acceptance_decisions_generation"),
        Index("ix_revision_acceptance_decisions_project_name", "project_name"),
    )

    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_family: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    selected_revision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    expected_latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    expected_effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    authorization_authority_role: Mapped[str] = mapped_column(String(32), nullable=False)
    authorization_stable_subject_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_decision_command_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_authenticated_via: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChangeSetReviewDecisionModel(UserOwnedMixin, Base):
    """One typed ``review_change_set`` decision. Its logical subject key is
    ``(revision_acceptance_decision_id, change_set_lineage_id)``."""

    __tablename__ = "change_set_review_decisions"
    __table_args__ = (
        UniqueConstraint("decision_id", "decision_family", name="uq_change_set_review_decisions_family"),
        UniqueConstraint("user_id", "project_name", "decision_id", name="uq_change_set_review_decisions_scope"),
        ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_change_set_review_decisions_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_change_set_review_decisions_revision_acceptance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "decision_id",
            "revision_acceptance_decision_id",
            "change_set_lineage_id",
            name="uq_change_set_review_decisions_subject",
        ),
        ForeignKeyConstraint(
            ["expected_latest_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expected_effective_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision_family = 'CHANGE_SET_REVIEW'", name="ck_change_set_review_decisions_family"),
        CheckConstraint(f"action IN {_CHANGE_SET_ACTIONS}", name="ck_change_set_review_decisions_action"),
        CheckConstraint("plan_version >= 1", name="ck_change_set_review_decisions_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_change_set_review_decisions_scene_version"),
        CheckConstraint("decision_generation >= 1", name="ck_change_set_review_decisions_generation"),
        Index("ix_change_set_review_decisions_project_name", "project_name"),
        Index("ix_change_set_review_decisions_lineage", "revision_acceptance_decision_id", "change_set_lineage_id"),
    )

    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_family: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # The command's ``work_scope`` — the current plan/scene/canon-branch context this
    # decision was made under. Not the head key (see the class docstring), but part of
    # the exact canonical command and required to reconstruct it byte-for-byte.
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    change_set_lineage_id: Mapped[str] = mapped_column(_ID, nullable=False)
    selected_change_set_id: Mapped[str] = mapped_column(_ID, nullable=False)
    expected_latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    expected_effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    authorization_authority_role: Mapped[str] = mapped_column(String(32), nullable=False)
    authorization_stable_subject_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_decision_command_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_authenticated_via: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConflictResolutionLineageModel(UserOwnedMixin, Base):
    """The opaque conflict-resolution lineage allocated by the genesis form of
    ``resolve_change_set_conflict()``. ``UNIQUE(revision_acceptance_decision_id,
    conflict_subject_fingerprint)`` makes the same accepted revision + the same canonical
    conflict subject denote one lineage; reuse of ``conflict_resolution_lineage_id`` for a
    different subject is a separate identity conflict, not enforced by this constraint."""

    __tablename__ = "conflict_resolution_lineages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_conflict_resolution_lineages_revision_acceptance",
            ondelete="RESTRICT",
        ),
        PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "conflict_resolution_lineage_id", name="pk_conflict_resolution_lineages"
        ),
        UniqueConstraint(
            "revision_acceptance_decision_id",
            "conflict_subject_fingerprint",
            name="uq_conflict_resolution_lineages_subject",
        ),
        Index("ix_conflict_resolution_lineages_project_name", "project_name"),
    )

    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID)
    conflict_resolution_lineage_id: Mapped[str] = mapped_column(_ID)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    conflict_subject_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    conflict_subject_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class ConflictResolutionDecisionModel(UserOwnedMixin, Base):
    """One typed ``resolve_change_set_conflict`` decision. Its logical subject key is
    ``(revision_acceptance_decision_id, conflict_resolution_lineage_id)``; its genesis
    form is created atomically with the lineage and head it belongs to (enforced by the
    service, not this row alone)."""

    __tablename__ = "conflict_resolution_decisions"
    __table_args__ = (
        UniqueConstraint("decision_id", "decision_family", name="uq_conflict_resolution_decisions_family"),
        UniqueConstraint("user_id", "project_name", "decision_id", name="uq_conflict_resolution_decisions_scope"),
        ForeignKeyConstraint(
            ["decision_id", "decision_family"],
            ["narrative_decision_identities.decision_id", "narrative_decision_identities.decision_family"],
            name="fk_conflict_resolution_decisions_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_lineages.revision_acceptance_decision_id",
                "conflict_resolution_lineages.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_lineage",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "decision_id",
            "revision_acceptance_decision_id",
            "conflict_resolution_lineage_id",
            name="uq_conflict_resolution_decisions_subject",
        ),
        ForeignKeyConstraint(
            ["expected_latest_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_expected_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expected_effective_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_decisions_expected_effective",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision_family = 'CONFLICT_RESOLUTION'", name="ck_conflict_resolution_decisions_family"),
        CheckConstraint(f"action IN {_CONFLICT_ACTIONS}", name="ck_conflict_resolution_decisions_action"),
        CheckConstraint("plan_version >= 1", name="ck_conflict_resolution_decisions_plan_version"),
        CheckConstraint("scene_contract_version >= 1", name="ck_conflict_resolution_decisions_scene_version"),
        CheckConstraint("decision_generation >= 1", name="ck_conflict_resolution_decisions_generation"),
        Index("ix_conflict_resolution_decisions_project_name", "project_name"),
    )

    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_family: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # See ``ChangeSetReviewDecisionModel`` — the command's ``work_scope``, not this
    # decision's head key.
    plan_id: Mapped[str] = mapped_column(_ID, nullable=False)
    scene_contract_id: Mapped[str] = mapped_column(_ID, nullable=False)
    canon_branch_id: Mapped[str] = mapped_column(_ID, nullable=False)
    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    conflict_resolution_lineage_id: Mapped[str] = mapped_column(_ID, nullable=False)
    chosen_resolution: Mapped[str] = mapped_column(Text, nullable=False)
    expected_latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    expected_effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    base_canon_version_id: Mapped[str] = mapped_column(_ID, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_pack_id: Mapped[str] = mapped_column(_ID, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    authorization_authority_role: Mapped[str] = mapped_column(String(32), nullable=False)
    authorization_stable_subject_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_decision_command_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    authorization_authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_authenticated_via: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConflictResolutionDecisionCompetitorModel(UserOwnedMixin, Base):
    """Ordered proof that one conflict-resolution decision names exactly this paired set
    of competing change sets and their review decisions, in this order."""

    __tablename__ = "conflict_resolution_decision_competitors"
    __table_args__ = (
        PrimaryKeyConstraint("decision_id", "position", name="pk_conflict_resolution_decision_competitors"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "decision_id"],
            [
                "conflict_resolution_decisions.user_id",
                "conflict_resolution_decisions.project_name",
                "conflict_resolution_decisions.decision_id",
            ],
            name="fk_conflict_resolution_decision_competitors_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "change_set_id"],
            [
                "narrative_change_sets.user_id",
                "narrative_change_sets.project_name",
                "narrative_change_sets.change_set_id",
            ],
            name="fk_conflict_resolution_decision_competitors_change_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_decision_id"],
            ["change_set_review_decisions.decision_id"],
            name="fk_conflict_resolution_decision_competitors_review",
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="ck_conflict_resolution_decision_competitors_position"),
        Index("ix_conflict_resolution_decision_competitors_change_set", "change_set_id"),
        Index("ix_conflict_resolution_decision_competitors_review", "review_decision_id"),
    )

    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    change_set_id: Mapped[str] = mapped_column(_ID, nullable=False)
    review_decision_id: Mapped[str] = mapped_column(_ID, nullable=False)


def _head_generation_checks(prefix: str) -> tuple[CheckConstraint, ...]:
    """The null-pointer/zero-generation genesis invariant, shared by every head."""
    return (
        CheckConstraint(
            "(latest_decision_id IS NULL AND decision_generation = 0) "
            "OR (latest_decision_id IS NOT NULL AND decision_generation > 0)",
            name=f"ck_{prefix}_latest_zero_generation",
        ),
        CheckConstraint(
            "(effective_decision_id IS NULL AND effective_generation = 0) "
            "OR (effective_decision_id IS NOT NULL AND effective_generation > 0)",
            name=f"ck_{prefix}_effective_zero_generation",
        ),
        CheckConstraint("effective_generation <= decision_generation", name=f"ck_{prefix}_effective_not_ahead"),
    )


class RevisionAcceptanceHeadModel(UserOwnedMixin, Base):
    """The rebuildable lock/index projection keyed by exactly ``NarrativeWorkScope``.
    The only mutable row family in the Narrative decision-authority schema."""

    __tablename__ = "revision_acceptance_heads"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "plan_id",
            "scene_contract_id",
            "canon_branch_id",
            name="pk_revision_acceptance_heads",
        ),
        ForeignKeyConstraint(
            ["latest_decision_id", "user_id", "project_name", "plan_id", "scene_contract_id", "canon_branch_id"],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_heads_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_decision_id", "user_id", "project_name", "plan_id", "scene_contract_id", "canon_branch_id"],
            [
                "revision_acceptance_decisions.decision_id",
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.plan_id",
                "revision_acceptance_decisions.scene_contract_id",
                "revision_acceptance_decisions.canon_branch_id",
            ],
            name="fk_revision_acceptance_heads_effective",
            ondelete="RESTRICT",
        ),
        *_head_generation_checks("revision_acceptance_heads"),
        Index("ix_revision_acceptance_heads_project_name", "project_name"),
    )

    # ``NarrativeWorkScope`` is exactly this head's stable key, so ``user_id`` (unlike
    # every other table here) is part of the physical primary key, not just the
    # ownership FK — override the ``UserOwnedMixin`` column to add ``primary_key=True``.
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    plan_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    scene_contract_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    canon_branch_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    effective_generation: Mapped[int] = mapped_column(Integer, nullable=False)


class ChangeSetReviewHeadModel(UserOwnedMixin, Base):
    """The rebuildable lock/index projection keyed by
    ``(revision_acceptance_decision_id, change_set_lineage_id)``."""

    __tablename__ = "change_set_review_heads"
    __table_args__ = (
        PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "change_set_lineage_id", name="pk_change_set_review_heads"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "revision_acceptance_decision_id"],
            [
                "revision_acceptance_decisions.user_id",
                "revision_acceptance_decisions.project_name",
                "revision_acceptance_decisions.decision_id",
            ],
            name="fk_change_set_review_heads_revision_acceptance",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["latest_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_heads_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_decision_id", "revision_acceptance_decision_id", "change_set_lineage_id"],
            [
                "change_set_review_decisions.decision_id",
                "change_set_review_decisions.revision_acceptance_decision_id",
                "change_set_review_decisions.change_set_lineage_id",
            ],
            name="fk_change_set_review_heads_effective",
            ondelete="RESTRICT",
        ),
        *_head_generation_checks("change_set_review_heads"),
        Index("ix_change_set_review_heads_project_name", "project_name"),
    )

    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    change_set_lineage_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    effective_generation: Mapped[int] = mapped_column(Integer, nullable=False)


class ConflictResolutionHeadModel(UserOwnedMixin, Base):
    """The rebuildable lock/index projection keyed by
    ``(revision_acceptance_decision_id, conflict_resolution_lineage_id)``."""

    __tablename__ = "conflict_resolution_heads"
    __table_args__ = (
        PrimaryKeyConstraint(
            "revision_acceptance_decision_id", "conflict_resolution_lineage_id", name="pk_conflict_resolution_heads"
        ),
        ForeignKeyConstraint(
            ["revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_lineages.revision_acceptance_decision_id",
                "conflict_resolution_lineages.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_lineage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["latest_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_decision_id", "revision_acceptance_decision_id", "conflict_resolution_lineage_id"],
            [
                "conflict_resolution_decisions.decision_id",
                "conflict_resolution_decisions.revision_acceptance_decision_id",
                "conflict_resolution_decisions.conflict_resolution_lineage_id",
            ],
            name="fk_conflict_resolution_heads_effective",
            ondelete="RESTRICT",
        ),
        *_head_generation_checks("conflict_resolution_heads"),
        Index("ix_conflict_resolution_heads_project_name", "project_name"),
    )

    revision_acceptance_decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    conflict_resolution_lineage_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    decision_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    effective_generation: Mapped[int] = mapped_column(Integer, nullable=False)
