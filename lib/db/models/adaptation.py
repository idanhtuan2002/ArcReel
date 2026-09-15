"""Append-only M6 adaptation proposal-evidence ORM models (plan Task 5).

Branches, maps and screenplays share one shape: each is a versioned lineage keyed by
its own opaque id, and every ``(id, version)`` pair is an immutable row written once —
exactly the tuple ``ArtifactVersionRef`` (id, version, content_hash) addresses. This
mirrors the M5C append-only pattern but is a genuinely new design decision for M6:
the plan's own contracts give maps and screenplays a ``version`` field without fixing
whether that means "one row per id" or "one row per (id, version)" — composite keying
was chosen for uniformity with branches (whose own multi-version ratchet, spec Task 2,
requires it) and because every reference elsewhere in the design binds the full
``ArtifactVersionRef`` triple, never a bare id.

``(id, version)`` is the primary key directly (not merely a unique constraint), so a
collision is caught globally across tenants without an extra query — "no same-ID
genesis tuple substitution" and "global opaque-ID collision" (plan Task 5) fall out of
the PK itself. ``user_id``/``project_name`` still scope every row (plan Global
Constraint: "every public repository predicate contains (user_id, project_name)") and
carry a redundant scoped-uniqueness constraint for query safety, matching the M5C
convention. Nothing here writes an authority head or decision — that starts at Task 7.
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
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, UserOwnedMixin

_ID = String(255)
_SHORT = String(64)
_ADAPTATION_OPERATIONS = (
    "('PRESERVE','EXTERNALIZE','CONDENSE','COMBINE','SPLIT','OMIT','REORDER','REFRAME_POV','MODIFY_FOR_MEDIUM')"
)
_APPROVAL_STATUSES = "('DRAFT','PROPOSED','REVIEW_REQUIRED','APPROVED','REJECTED')"


class AdaptationBranchModel(UserOwnedMixin, Base):
    __tablename__ = "adaptation_branches"
    __table_args__ = (
        PrimaryKeyConstraint("branch_id", "version", name="pk_adaptation_branches"),
        UniqueConstraint("user_id", "project_name", "branch_id", "version", name="uq_adaptation_branches_scope"),
        CheckConstraint("version >= 1", name="ck_adaptation_branches_version"),
        CheckConstraint("overlay_version >= 1", name="ck_adaptation_branches_overlay_version"),
        CheckConstraint("parent_canon_version >= 1", name="ck_adaptation_branches_parent_canon_version"),
        Index("ix_adaptation_branches_project_name", "project_name"),
    )

    branch_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    parent_branch_id: Mapped[str | None] = mapped_column(_ID)
    parent_canon_artifact_id: Mapped[str] = mapped_column(_ID, nullable=False)
    parent_canon_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_canon_content_hash: Mapped[str] = mapped_column(_ID, nullable=False)

    medium: Mapped[str] = mapped_column(String(255), nullable=False)
    adaptation_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    overlay_version: Mapped[int] = mapped_column(Integer, nullable=False)

    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    policy_pack_digest: Mapped[str] = mapped_column(_ID, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class AdaptationMapModel(UserOwnedMixin, Base):
    __tablename__ = "adaptation_maps"
    __table_args__ = (
        PrimaryKeyConstraint("adaptation_map_id", "version", name="pk_adaptation_maps"),
        UniqueConstraint("user_id", "project_name", "adaptation_map_id", "version", name="uq_adaptation_maps_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "adaptation_branch_ref_id", "adaptation_branch_ref_version"],
            [
                "adaptation_branches.user_id",
                "adaptation_branches.project_name",
                "adaptation_branches.branch_id",
                "adaptation_branches.version",
            ],
            name="fk_adaptation_maps_branch_ref",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_adaptation_maps_version"),
        Index("ix_adaptation_maps_project_name", "project_name"),
    )

    adaptation_map_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    adaptation_branch_ref_id: Mapped[str] = mapped_column(_ID, nullable=False)
    adaptation_branch_ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adaptation_branch_ref_hash: Mapped[str] = mapped_column(_ID, nullable=False)

    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)


class AdaptationMapProfileAnalysisRefModel(UserOwnedMixin, Base):
    """Ordered ``profile_analysis_refs`` on one map version. One row per ref."""

    __tablename__ = "adaptation_map_profile_analysis_refs"
    __table_args__ = (
        PrimaryKeyConstraint("adaptation_map_id", "adaptation_map_version", "position", name="pk_adaptation_map_par"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "adaptation_map_id", "adaptation_map_version"],
            [
                "adaptation_maps.user_id",
                "adaptation_maps.project_name",
                "adaptation_maps.adaptation_map_id",
                "adaptation_maps.version",
            ],
            name="fk_adaptation_map_par_map",
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="ck_adaptation_map_par_position"),
        Index("ix_adaptation_map_par_project_name", "project_name"),
    )

    adaptation_map_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    adaptation_map_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    ref_artifact_id: Mapped[str] = mapped_column(_ID, nullable=False)
    ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_content_hash: Mapped[str] = mapped_column(_ID, nullable=False)


class AdaptationMapEntryModel(UserOwnedMixin, Base):
    __tablename__ = "adaptation_map_entries"
    __table_args__ = (
        PrimaryKeyConstraint(
            "adaptation_map_id", "adaptation_map_version", "entry_id", name="pk_adaptation_map_entries"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "adaptation_map_id", "adaptation_map_version"],
            [
                "adaptation_maps.user_id",
                "adaptation_maps.project_name",
                "adaptation_maps.adaptation_map_id",
                "adaptation_maps.version",
            ],
            name="fk_adaptation_map_entries_map",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "adaptation_map_id",
            "adaptation_map_version",
            "position",
            name="uq_adaptation_map_entries_position",
        ),
        CheckConstraint(f"operation IN {_ADAPTATION_OPERATIONS}", name="ck_adaptation_map_entries_operation"),
        CheckConstraint(f"approval_status IN {_APPROVAL_STATUSES}", name="ck_adaptation_map_entries_approval"),
        CheckConstraint("position >= 0", name="ck_adaptation_map_entries_position"),
        Index("ix_adaptation_map_entries_project_name", "project_name"),
    )

    adaptation_map_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    adaptation_map_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    source_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    target_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    fidelity_risk: Mapped[str] = mapped_column(String(255), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)


class AdaptationScreenplayModel(UserOwnedMixin, Base):
    __tablename__ = "adaptation_screenplays"
    __table_args__ = (
        PrimaryKeyConstraint("screenplay_id", "version", name="pk_adaptation_screenplays"),
        UniqueConstraint("user_id", "project_name", "screenplay_id", "version", name="uq_adaptation_screenplays_scope"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "adaptation_branch_ref_id", "adaptation_branch_ref_version"],
            [
                "adaptation_branches.user_id",
                "adaptation_branches.project_name",
                "adaptation_branches.branch_id",
                "adaptation_branches.version",
            ],
            name="fk_adaptation_screenplays_branch_ref",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "adaptation_map_ref_id", "adaptation_map_ref_version"],
            [
                "adaptation_maps.user_id",
                "adaptation_maps.project_name",
                "adaptation_maps.adaptation_map_id",
                "adaptation_maps.version",
            ],
            name="fk_adaptation_screenplays_map_ref",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_adaptation_screenplays_version"),
        CheckConstraint(f"approval_status IN {_APPROVAL_STATUSES}", name="ck_adaptation_screenplays_approval"),
        Index("ix_adaptation_screenplays_project_name", "project_name"),
    )

    screenplay_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    adaptation_branch_ref_id: Mapped[str] = mapped_column(_ID, nullable=False)
    adaptation_branch_ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adaptation_branch_ref_hash: Mapped[str] = mapped_column(_ID, nullable=False)

    content_basis_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    characters_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    source_mapping_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    locked_for_direction: Mapped[bool] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)

    adaptation_map_ref_id: Mapped[str] = mapped_column(_ID, nullable=False)
    adaptation_map_ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adaptation_map_ref_hash: Mapped[str] = mapped_column(_ID, nullable=False)


class AdaptationScreenplayProfileAnalysisRefModel(UserOwnedMixin, Base):
    """Ordered ``profile_analysis_refs`` on one screenplay version. One row per ref."""

    __tablename__ = "adaptation_screenplay_profile_analysis_refs"
    __table_args__ = (
        PrimaryKeyConstraint("screenplay_id", "screenplay_version", "position", name="pk_adaptation_screenplay_par"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "screenplay_id", "screenplay_version"],
            [
                "adaptation_screenplays.user_id",
                "adaptation_screenplays.project_name",
                "adaptation_screenplays.screenplay_id",
                "adaptation_screenplays.version",
            ],
            name="fk_adaptation_screenplay_par_screenplay",
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="ck_adaptation_screenplay_par_position"),
        Index("ix_adaptation_screenplay_par_project_name", "project_name"),
    )

    screenplay_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    screenplay_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    ref_artifact_id: Mapped[str] = mapped_column(_ID, nullable=False)
    ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_content_hash: Mapped[str] = mapped_column(_ID, nullable=False)


class AdaptationScreenplaySceneModel(UserOwnedMixin, Base):
    __tablename__ = "adaptation_screenplay_scenes"
    __table_args__ = (
        PrimaryKeyConstraint("screenplay_id", "screenplay_version", "scene_id", name="pk_adaptation_screenplay_scenes"),
        ForeignKeyConstraint(
            ["user_id", "project_name", "screenplay_id", "screenplay_version"],
            [
                "adaptation_screenplays.user_id",
                "adaptation_screenplays.project_name",
                "adaptation_screenplays.screenplay_id",
                "adaptation_screenplays.version",
            ],
            name="fk_adaptation_screenplay_scenes_screenplay",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "screenplay_id", "screenplay_version", "position", name="uq_adaptation_screenplay_scenes_position"
        ),
        CheckConstraint("duration_target > 0", name="ck_adaptation_screenplay_scenes_duration"),
        CheckConstraint("position >= 0", name="ck_adaptation_screenplay_scenes_position"),
        Index("ix_adaptation_screenplay_scenes_project_name", "project_name"),
    )

    screenplay_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    screenplay_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    scene_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    purpose: Mapped[str] = mapped_column(String(2000), nullable=False)
    duration_target: Mapped[float] = mapped_column(Float, nullable=False)
    location_ref: Mapped[str | None] = mapped_column(_ID)
    character_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    source_mapping_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    dramatic_text: Mapped[str] = mapped_column(String(8000), nullable=False)
