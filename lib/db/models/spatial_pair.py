"""Scoped heads, immutable decisions and command receipts for reviewed spatial pairs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base


class SpatialPairHeadModel(Base):
    __tablename__ = "m8_spatial_pair_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "pair_id", name="pk_m8_spatial_pair_heads"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id", "current_version"],
            [
                "m8_spatial_pair_decisions.user_id",
                "m8_spatial_pair_decisions.project_name",
                "m8_spatial_pair_decisions.pair_id",
                "m8_spatial_pair_decisions.pair_version",
            ],
            name="fk_m8_spatial_pair_heads_current",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(current_version IS NULL AND current_decision_digest IS NULL) OR "
            "(current_version IS NOT NULL AND current_version >= 1 AND current_decision_digest IS NOT NULL)",
            name="ck_m8_spatial_pair_heads_current_pair",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_decision_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)


class SpatialPairDecisionModel(Base):
    __tablename__ = "m8_spatial_pair_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_decisions"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id"],
            ["m8_spatial_pair_heads.user_id", "m8_spatial_pair_heads.project_name", "m8_spatial_pair_heads.pair_id"],
            name="fk_m8_spatial_pair_decisions_head",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id", "binding_version"],
            [
                "production_binding_versions.user_id",
                "production_binding_versions.project_name",
                "production_binding_versions.binding_id",
                "production_binding_versions.binding_version",
            ],
            name="fk_m8_spatial_pair_decisions_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "target_type", "target_id", "target_registry_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_m8_spatial_pair_decisions_target",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "scene_type", "scene_id", "scene_registry_version"],
            [
                "production_target_versions.user_id",
                "production_target_versions.project_name",
                "production_target_versions.target_type",
                "production_target_versions.target_id",
                "production_target_versions.registry_version",
            ],
            name="fk_m8_spatial_pair_decisions_scene",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "master_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_master_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_pair_decisions_reverse_receipt",
            ondelete="RESTRICT",
        ),
        CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_decisions_version"),
        CheckConstraint("binding_version >= 1", name="ck_m8_spatial_pair_decisions_binding_version"),
        CheckConstraint("target_type = 'SHOT' AND scene_type = 'SCENE'", name="ck_m8_spatial_pair_decisions_types"),
        CheckConstraint("master_receipt_id <> reverse_receipt_id", name="ck_m8_spatial_pair_decisions_distinct_frames"),
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_m8_spatial_pair_decisions_action"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    pair_version: Mapped[int] = mapped_column(Integer)
    decision_body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(71))
    command_digest: Mapped[str] = mapped_column(String(71))
    authorization_digest: Mapped[str] = mapped_column(String(71))
    binding_id: Mapped[str] = mapped_column(String(255))
    binding_version: Mapped[int] = mapped_column(Integer)
    binding_envelope_digest: Mapped[str] = mapped_column(String(71))
    binding_core_digest: Mapped[str] = mapped_column(String(71))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(255))
    target_registry_version: Mapped[int] = mapped_column(Integer)
    target_version_digest: Mapped[str] = mapped_column(String(71))
    scene_type: Mapped[str] = mapped_column(String(32))
    scene_id: Mapped[str] = mapped_column(String(255))
    scene_registry_version: Mapped[int] = mapped_column(Integer)
    scene_version_digest: Mapped[str] = mapped_column(String(71))
    master_receipt_id: Mapped[str] = mapped_column(String(255))
    reverse_receipt_id: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpatialPairCommandModel(Base):
    __tablename__ = "m8_spatial_pair_commands"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "principal", "command_id", name="pk_m8_spatial_pair_commands"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    principal: Mapped[str] = mapped_column(String(255))
    command_id: Mapped[str] = mapped_column(String(255))
    command_digest: Mapped[str] = mapped_column(String(71))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpatialPairV2CustodyModel(Base):
    __tablename__ = "m8_spatial_pair_v2_custody"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "pair_id", "pair_version", name="pk_m8_spatial_pair_v2_custody"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "pair_id", "pair_version"],
            [
                "m8_spatial_pair_decisions.user_id",
                "m8_spatial_pair_decisions.project_name",
                "m8_spatial_pair_decisions.pair_id",
                "m8_spatial_pair_decisions.pair_version",
            ],
            name="fk_m8_spatial_pair_v2_custody_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "review_session_id"],
            [
                "m8_spatial_review_sessions.user_id",
                "m8_spatial_review_sessions.project_name",
                "m8_spatial_review_sessions.session_id",
            ],
            name="fk_m8_spatial_pair_v2_custody_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint("pair_version >= 1", name="ck_m8_spatial_pair_v2_custody_version"),
        UniqueConstraint("user_id", "project_name", "review_session_id", name="uq_m8_spatial_pair_v2_custody_session"),
    )

    user_id: Mapped[str] = mapped_column(String)
    project_name: Mapped[str] = mapped_column(String(255))
    pair_id: Mapped[str] = mapped_column(String(255))
    pair_version: Mapped[int] = mapped_column(Integer)
    review_session_id: Mapped[str] = mapped_column(String(32))
    review_evidence_digest: Mapped[str] = mapped_column(String(71))
    decision_digest: Mapped[str] = mapped_column(String(71))


__all__ = ["SpatialPairCommandModel", "SpatialPairDecisionModel", "SpatialPairHeadModel", "SpatialPairV2CustodyModel"]


class SpatialConstraintSetModel(Base):
    """One immutable typed spatial constraint set; its ID names its body digest."""

    __tablename__ = "m8_spatial_constraint_sets"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "set_id", name="pk_m8_spatial_constraint_sets"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_m8_spatial_constraint_sets_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "master_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_constraint_sets_master",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "reverse_receipt_id"],
            [
                "m8_spatial_frame_receipts.user_id",
                "m8_spatial_frame_receipts.project_name",
                "m8_spatial_frame_receipts.receipt_id",
            ],
            name="fk_m8_spatial_constraint_sets_reverse",
            ondelete="RESTRICT",
        ),
        CheckConstraint("master_receipt_id <> reverse_receipt_id", name="ck_m8_spatial_constraint_sets_two_views"),
        CheckConstraint("substr(set_id, 5) = substr(set_digest, 8)", name="ck_m8_spatial_constraint_sets_id_digest"),
    )

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="RESTRICT"), server_default=DEFAULT_USER_ID
    )
    project_name: Mapped[str] = mapped_column(String(255))
    set_id: Mapped[str] = mapped_column(String(255))
    set_digest: Mapped[str] = mapped_column(String(71))
    binding_id: Mapped[str] = mapped_column(String(255))
    master_receipt_id: Mapped[str] = mapped_column(String(255))
    reverse_receipt_id: Mapped[str] = mapped_column(String(255))
    body_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpatialPreviewBindingModel(Base):
    """Sidecar of one binding-target M8 preview; PostgreSQL triggers couple it to the base row."""

    __tablename__ = "m8_spatial_preview_bindings"
    __table_args__ = (
        PrimaryKeyConstraint("preview_id", name="pk_m8_spatial_preview_bindings"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            ["m8_promotion_previews.user_id", "m8_promotion_previews.project_name", "m8_promotion_previews.preview_id"],
            name="fk_m8_spatial_preview_bindings_preview",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_m8_spatial_preview_bindings_binding",
            ondelete="RESTRICT",
        ),
        CheckConstraint("expected_binding_version >= 1", name="ck_m8_spatial_preview_bindings_version"),
    )

    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    preview_id: Mapped[str] = mapped_column(String(255))
    binding_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_binding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    binding_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    preview_v2_digest: Mapped[str] = mapped_column(String(71), nullable=False)


class SpatialPromotionResultModel(Base):
    """Sidecar of one binding-target M8 receipt: the binding version and constraint set it produced."""

    __tablename__ = "m8_spatial_promotion_results"
    __table_args__ = (
        PrimaryKeyConstraint("receipt_id", name="pk_m8_spatial_promotion_results"),
        ForeignKeyConstraint(
            ["receipt_id"],
            ["m8_promotion_receipts.receipt_id"],
            name="fk_m8_spatial_promotion_results_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id", "binding_version"],
            [
                "production_binding_versions.user_id",
                "production_binding_versions.project_name",
                "production_binding_versions.binding_id",
                "production_binding_versions.binding_version",
            ],
            name="fk_m8_spatial_promotion_results_binding_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "set_id"],
            [
                "m8_spatial_constraint_sets.user_id",
                "m8_spatial_constraint_sets.project_name",
                "m8_spatial_constraint_sets.set_id",
            ],
            name="fk_m8_spatial_promotion_results_set",
            ondelete="RESTRICT",
        ),
        CheckConstraint("binding_version >= 2", name="ck_m8_spatial_promotion_results_version"),
    )

    user_id: Mapped[str] = mapped_column(String, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    receipt_id: Mapped[str] = mapped_column(String(255))
    binding_id: Mapped[str] = mapped_column(String(255), nullable=False)
    binding_version: Mapped[int] = mapped_column(Integer, nullable=False)
    set_id: Mapped[str] = mapped_column(String(255), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    receipt_v2_digest: Mapped[str] = mapped_column(String(71), nullable=False)


_COUPLING_FUNCTION = """
CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    key text;
    kind text;
    sidecars integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        key := OLD.{key};
    ELSE
        key := NEW.{key};
    END IF;
    SELECT target_kind INTO kind FROM {base} WHERE {key} = key;
    IF kind IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO sidecars FROM {sidecar} WHERE {key} = key;
    IF (kind = 'PRODUCTION_BINDING' AND sidecars <> 1) OR (kind <> 'PRODUCTION_BINDING' AND sidecars <> 0) THEN
        RAISE EXCEPTION '{name}: % % has % spatial sidecars', kind, key, sidecars USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$
"""
_COUPLING_TRIGGER = (
    "CREATE CONSTRAINT TRIGGER {name}_{suffix} AFTER {events} ON {table} "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {name}()"
)


def _install_coupling(sidecar: Table, *, name: str, base: str, key: str) -> None:
    """Schemas built from the models (tests) get the same PostgreSQL coupling triggers as migration 913c4a0e0001."""
    statements = (
        _COUPLING_FUNCTION.format(name=name, base=base, sidecar=sidecar.name, key=key),
        _COUPLING_TRIGGER.format(name=name, suffix="base", events="INSERT OR UPDATE", table=base),
        _COUPLING_TRIGGER.format(name=name, suffix="sidecar", events="INSERT OR UPDATE OR DELETE", table=sidecar.name),
    )
    for statement in statements:
        # DDL applies %-style substitution, so the RAISE placeholders are escaped.
        event.listen(sidecar, "after_create", DDL(statement.replace("%", "%%")).execute_if(dialect="postgresql"))


_install_coupling(
    SpatialPreviewBindingModel.__table__,  # type: ignore[arg-type]
    name="m8_spatial_preview_coupling",
    base="m8_promotion_previews",
    key="preview_id",
)
_install_coupling(
    SpatialPromotionResultModel.__table__,  # type: ignore[arg-type]
    name="m8_spatial_receipt_coupling",
    base="m8_promotion_receipts",
    key="receipt_id",
)
