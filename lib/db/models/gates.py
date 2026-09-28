"""ADR-0089's four mandatory Human Gates (A-D) -- P1 backlog item 6
(docs/superpowers/specs/2026-09-22-r2-p1-gate-receipt-surface-design.md).

Three new, additive, append-only tables. Gate B (``adaptation_decisions``)
and Gate C's selection pointer (the host's own artifact manifest, via
``ApprovedMasterMetadata``) are unchanged and not duplicated here.
Column/constraint style mirrors ``lib/db/models/host_hardening.py``'s
``MasterHeadVersionModel``/``PromotionReceiptModel`` (the most recent
same-branch precedent for an append-only, per-scope-sequenced table), not
the older ``AdaptationDecisionModel`` shape.
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
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base, UserOwnedMixin

_ID = String(255)


class GreenlightDecisionModel(UserOwnedMixin, Base):
    """Gate A. Append-only -- no head/pointer row: an operator's full
    greenlight/revoke history for a project *is* the state; there is no
    separate "current effective decision" concept to CAS against."""

    __tablename__ = "gate_greenlight_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_greenlight_decisions"),
        UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_greenlight_decisions_sequence"),
        CheckConstraint("sequence >= 1", name="ck_gate_greenlight_decisions_sequence"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)

    source_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScriptLockDecisionModel(UserOwnedMixin, Base):
    """Gate B for a factual product (ADR-0092). Same shape/rationale as ``GreenlightDecisionModel``."""

    __tablename__ = "gate_script_lock_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_script_lock_decisions"),
        UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_script_lock_decisions_sequence"),
        CheckConstraint("sequence >= 1", name="ck_gate_script_lock_decisions_sequence"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)

    source_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    script_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublishApprovalDecisionModel(UserOwnedMixin, Base):
    """Gate D. Same shape/rationale as ``GreenlightDecisionModel``."""

    __tablename__ = "gate_publish_approval_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_gate_publish_approval_decisions"),
        UniqueConstraint("user_id", "project_name", "sequence", name="uq_gate_publish_approval_decisions_sequence"),
        CheckConstraint("sequence >= 1", name="ck_gate_publish_approval_decisions_sequence"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    decision_id: Mapped[str] = mapped_column(_ID, primary_key=True)

    deliverable_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinalCutReceiptModel(Base):
    """Gate C's additive audit companion. Written only by the Gate C route
    handler (design section 4.2), never by ``ProductionApprovalService``
    itself, which remains completely unmodified. UUID primary key mirrors
    ``MasterHeadVersionModel``'s own choice for the same reason: a receipt
    has no caller-supplied idempotency key the way a promotion command does,
    only a per-artifact sequence."""

    __tablename__ = "gate_final_cut_receipts"
    __table_args__ = (
        PrimaryKeyConstraint("final_cut_receipt_id", name="pk_gate_final_cut_receipts"),
        UniqueConstraint(
            "user_id", "project_name", "artifact_key", "sequence", name="uq_gate_final_cut_receipts_scope_sequence"
        ),
        Index("ix_gate_final_cut_receipts_scope", "user_id", "project_name", "artifact_key"),
        CheckConstraint("sequence >= 1", name="ck_gate_final_cut_receipts_sequence"),
    )

    final_cut_receipt_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_key: Mapped[str] = mapped_column(_ID, nullable=False)

    selected_candidate_id: Mapped[str] = mapped_column(_ID, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(_ID, nullable=False)
    approval_record: Mapped[str] = mapped_column(_ID, nullable=False)
    selected_by: Mapped[str] = mapped_column(_ID, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)


__all__ = [
    "FinalCutReceiptModel",
    "GreenlightDecisionModel",
    "PublishApprovalDecisionModel",
    "ScriptLockDecisionModel",
]
