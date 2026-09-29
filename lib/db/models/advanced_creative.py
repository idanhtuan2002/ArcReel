"""M8 exploration evidence: candidate heads and immutable revisions, command receipts, promotion
previews, authorizations and receipts (plan 2026-09-13 M8-A fixed persistence map).

Evidence rows are append-only and are never cascade-deleted, not even with their owner: the
``users.id`` foreign key is ``RESTRICT``, not the ``UserOwnedMixin`` ``CASCADE``. Only the candidate
head row is mutable, through an explicit ``head_version`` compare-and-set. A candidate's identity is
``(user_id, project_name, candidate_id)``; every reference to a candidate, revision or preview carries
that scope, so the same ID in two scopes names two independent candidates. Canonical bytes and digests,
not database JSON ordering, are the hash authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base

_ID = String(255)
_DIGEST = String(71)
_ENUM = String(32)


class _EvidenceOwner:
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        index=True,
    )


class M8CandidateHeadModel(_EvidenceOwner, Base):
    __tablename__ = "m8_candidate_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "candidate_id", name="pk_m8_candidate_heads"),
        CheckConstraint("current_revision >= 1", name="ck_m8_candidate_heads_current_revision"),
        CheckConstraint("head_version >= 1", name="ck_m8_candidate_heads_head_version"),
        Index("ix_m8_candidate_heads_scope", "user_id", "project_name"),
    )

    candidate_id: Mapped[str] = mapped_column(_ID)
    project_name: Mapped[str] = mapped_column(_ID, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    head_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class M8CandidateRevisionModel(_EvidenceOwner, Base):
    __tablename__ = "m8_candidate_revisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "candidate_id", "revision", name="pk_m8_candidate_revisions"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id"],
            ["m8_candidate_heads.user_id", "m8_candidate_heads.project_name", "m8_candidate_heads.candidate_id"],
            name="fk_m8_candidate_revisions_candidate",
        ),
        CheckConstraint("kind IN ('CANVAS', 'SPATIAL', 'FORMAT')", name="ck_m8_candidate_revisions_kind"),
        CheckConstraint("revision >= 1", name="ck_m8_candidate_revisions_revision"),
        CheckConstraint(
            "parent_revision IS NULL OR parent_revision = revision - 1", name="ck_m8_candidate_revisions_parent"
        ),
    )

    candidate_id: Mapped[str] = mapped_column(_ID)
    revision: Mapped[int] = mapped_column(Integer)
    project_name: Mapped[str] = mapped_column(_ID, nullable=False)
    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(_ENUM, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    lineage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class M8CommandReceiptModel(_EvidenceOwner, Base):
    __tablename__ = "m8_command_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "actor_scope", "operation", "command_id", name="pk_m8_command_receipts"
        ),
        CheckConstraint(
            "operation IN ('APPEND_REVISION', 'PREVIEW', 'PROMOTE')", name="ck_m8_command_receipts_operation"
        ),
    )

    project_name: Mapped[str] = mapped_column(_ID)
    actor_scope: Mapped[str] = mapped_column(_ID)
    operation: Mapped[str] = mapped_column(_ENUM)
    command_id: Mapped[str] = mapped_column(_ID)
    command_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    result_kind: Mapped[str] = mapped_column(_ENUM, nullable=False)
    result_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    result_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class M8PromotionPreviewModel(_EvidenceOwner, Base):
    __tablename__ = "m8_promotion_previews"
    __table_args__ = (
        PrimaryKeyConstraint("preview_id", name="pk_m8_promotion_previews"),
        UniqueConstraint("user_id", "project_name", "preview_command_id", name="uq_m8_promotion_previews_command"),
        UniqueConstraint("user_id", "project_name", "preview_id", name="uq_m8_promotion_previews_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id", "candidate_revision"],
            [
                "m8_candidate_revisions.user_id",
                "m8_candidate_revisions.project_name",
                "m8_candidate_revisions.candidate_id",
                "m8_candidate_revisions.revision",
            ],
            name="fk_m8_promotion_previews_revision",
        ),
        CheckConstraint("expected_target_version >= 0", name="ck_m8_promotion_previews_target_version"),
        CheckConstraint("ttl_seconds > 0 AND ttl_seconds <= 3600", name="ck_m8_promotion_previews_ttl"),
        CheckConstraint(
            "(target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NOT NULL AND expected_master_digest IS NOT NULL)"
            " OR (target_kind = 'PRODUCTION_BINDING' AND expected_master_id IS NULL"
            " AND expected_master_digest IS NULL)",
            name="ck_m8_promotion_previews_master_coupling",
        ),
        Index("ix_m8_promotion_previews_expiry", "expires_at"),
    )

    preview_id: Mapped[str] = mapped_column(_ID)
    project_name: Mapped[str] = mapped_column(_ID, nullable=False)
    preview_command_id: Mapped[str] = mapped_column(_ID, nullable=False)
    candidate_id: Mapped[str] = mapped_column(_ID, nullable=False)
    candidate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_payload_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    target_kind: Mapped[str] = mapped_column(_ENUM, nullable=False)
    target_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    expected_target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_master_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    expected_master_digest: Mapped[str | None] = mapped_column(_DIGEST, nullable=True)
    impact_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    impact_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    preview_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    authorization_scope: Mapped[str] = mapped_column(_ID, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class M8PromotionAuthorizationModel(_EvidenceOwner, Base):
    __tablename__ = "m8_promotion_authorizations"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "command_id", name="pk_m8_promotion_authorizations"),
        UniqueConstraint(
            "user_id", "project_name", "authorization_digest", name="uq_m8_promotion_authorizations_digest"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            [
                "m8_promotion_previews.user_id",
                "m8_promotion_previews.project_name",
                "m8_promotion_previews.preview_id",
            ],
            name="fk_m8_promotion_authorizations_preview",
        ),
        CheckConstraint("decision = 'APPROVE'", name="ck_m8_promotion_authorizations_decision"),
    )

    project_name: Mapped[str] = mapped_column(_ID)
    command_id: Mapped[str] = mapped_column(_ID)
    preview_id: Mapped[str] = mapped_column(_ID, nullable=False)
    preview_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    actor_id: Mapped[str] = mapped_column(_ID, nullable=False)
    actor_scope: Mapped[str] = mapped_column(_ID, nullable=False)
    decision: Mapped[str] = mapped_column(_ENUM, nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)


class M8PromotionReceiptModel(_EvidenceOwner, Base):
    __tablename__ = "m8_promotion_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("receipt_id", name="pk_m8_promotion_receipts"),
        UniqueConstraint("user_id", "project_name", "command_id", name="uq_m8_promotion_receipts_command"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            [
                "m8_promotion_previews.user_id",
                "m8_promotion_previews.project_name",
                "m8_promotion_previews.preview_id",
            ],
            name="fk_m8_promotion_receipts_preview",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "candidate_id", "candidate_revision"],
            [
                "m8_candidate_revisions.user_id",
                "m8_candidate_revisions.project_name",
                "m8_candidate_revisions.candidate_id",
                "m8_candidate_revisions.revision",
            ],
            name="fk_m8_promotion_receipts_revision",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "command_id"],
            [
                "m8_promotion_authorizations.user_id",
                "m8_promotion_authorizations.project_name",
                "m8_promotion_authorizations.command_id",
            ],
            name="fk_m8_promotion_receipts_authorization",
        ),
        CheckConstraint(
            "(target_kind = 'ARTIFACT_SLOT' AND result_master_id IS NOT NULL)"
            " OR (target_kind = 'PRODUCTION_BINDING' AND result_master_id IS NULL)",
            name="ck_m8_promotion_receipts_master_coupling",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(_ID)
    project_name: Mapped[str] = mapped_column(_ID, nullable=False)
    command_id: Mapped[str] = mapped_column(_ID, nullable=False)
    preview_id: Mapped[str] = mapped_column(_ID, nullable=False)
    preview_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    authorization_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    candidate_id: Mapped[str] = mapped_column(_ID, nullable=False)
    candidate_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_kind: Mapped[str] = mapped_column(_ENUM, nullable=False)
    target_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    expected_target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_artifact_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    result_master_id: Mapped[str | None] = mapped_column(_ID, nullable=True)
    result_digest: Mapped[str] = mapped_column(_DIGEST, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "M8CandidateHeadModel",
    "M8CandidateRevisionModel",
    "M8CommandReceiptModel",
    "M8PromotionAuthorizationModel",
    "M8PromotionPreviewModel",
    "M8PromotionReceiptModel",
]
