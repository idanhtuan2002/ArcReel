"""Append-only Canon authority ORM models (ADR-0075).

Accepted deltas and immutable versions are authority; ``canon_resolved_projections``
is a disposable cache. Branch head/parent version pointers are logical IDs without
physical foreign keys to avoid a dialect-specific create-time cycle; every other
Canon-to-Canon relationship uses ``RESTRICT`` so history can never be deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, UserOwnedMixin

_ID = String(255)
_SELECTOR = String(64)


class CanonBranchModel(UserOwnedMixin, Base):
    __tablename__ = "canon_branches"
    __table_args__ = (
        CheckConstraint("branch_type IN ('MAIN', 'NARRATIVE_BRANCH')", name="ck_canon_branches_branch_type"),
        CheckConstraint(
            "(branch_type = 'MAIN' AND parent_branch_id IS NULL AND parent_version_id IS NULL) "
            "OR (branch_type = 'NARRATIVE_BRANCH' "
            "AND parent_branch_id IS NOT NULL AND parent_version_id IS NOT NULL)",
            name="ck_canon_branches_parent_pairing",
        ),
        Index("ix_canon_branches_project_name", "project_name"),
        Index("ix_canon_branches_parent_version_id", "parent_version_id"),
        Index("ix_canon_branches_head_version_id", "head_version_id"),
        Index(
            "uq_canon_branches_one_main_per_scope",
            "user_id",
            "project_name",
            unique=True,
            sqlite_where=text("branch_type = 'MAIN'"),
            postgresql_where=text("branch_type = 'MAIN'"),
        ),
    )

    branch_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_branch_id: Mapped[str | None] = mapped_column(ForeignKey("canon_branches.branch_id", ondelete="RESTRICT"))
    parent_version_id: Mapped[str | None] = mapped_column(_ID)
    head_version_id: Mapped[str | None] = mapped_column(_ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class CanonDeltaModel(UserOwnedMixin, Base):
    __tablename__ = "canon_deltas"
    __table_args__ = (
        UniqueConstraint("approval_ref", name="uq_canon_deltas_approval_ref"),
        CheckConstraint("approval_status IN ('APPROVED')", name="ck_canon_deltas_approval_status"),
        Index("ix_canon_deltas_project_name", "project_name"),
        Index("ix_canon_deltas_target_branch_id", "target_branch_id"),
        Index("ix_canon_deltas_base_canon_version_id", "base_canon_version_id"),
        Index("ix_canon_deltas_committed_version_id", "committed_version_id"),
    )

    canon_delta_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch_id: Mapped[str] = mapped_column(
        ForeignKey("canon_branches.branch_id", ondelete="RESTRICT"), nullable=False
    )
    base_canon_version_id: Mapped[str | None] = mapped_column(_ID)
    operations_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    source_change_set_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    author_decision_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    validation_report_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    payload_hash_algorithm: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    payload_hash_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_schema_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_ref: Mapped[str] = mapped_column(_ID, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    committed_version_id: Mapped[str] = mapped_column(_ID, nullable=False)


class CanonVersionModel(Base):
    __tablename__ = "canon_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="ck_canon_versions_version_number_positive"),
        UniqueConstraint("branch_id", "version_number", name="uq_canon_versions_branch_version_number"),
        UniqueConstraint("committed_delta_id", name="uq_canon_versions_committed_delta_id"),
        Index("ix_canon_versions_branch_id", "branch_id"),
        Index("ix_canon_versions_parent_version_id", "parent_version_id"),
    )

    canon_version_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("canon_branches.branch_id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("canon_versions.canon_version_id", ondelete="RESTRICT")
    )
    committed_delta_id: Mapped[str] = mapped_column(
        ForeignKey("canon_deltas.canon_delta_id", ondelete="RESTRICT"), nullable=False
    )
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    content_hash_algorithm: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_hash_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_schema_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)


class CanonResolvedProjectionModel(Base):
    __tablename__ = "canon_resolved_projections"

    canon_version_id: Mapped[str] = mapped_column(
        ForeignKey("canon_versions.canon_version_id", ondelete="RESTRICT"), primary_key=True
    )
    resolved_view_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    content_hash_algorithm: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_hash_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    content_schema_version: Mapped[str] = mapped_column(_SELECTOR, nullable=False)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
