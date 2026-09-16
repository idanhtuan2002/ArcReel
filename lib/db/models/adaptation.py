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
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base, UserOwnedMixin

_ID = String(255)
_SHORT = String(64)
_ADAPTATION_OPERATIONS = (
    "('PRESERVE','EXTERNALIZE','CONDENSE','COMBINE','SPLIT','OMIT','REORDER','REFRAME_POV','MODIFY_FOR_MEDIUM')"
)
_APPROVAL_STATUSES = "('DRAFT','PROPOSED','REVIEW_REQUIRED','APPROVED','REJECTED')"
_AUTHORITY_FAMILIES = "('MAP_APPROVAL','PROFILE_WAIVER','SCREENPLAY_ADMISSION')"
_DECISION_KINDS = "('MAP_APPROVAL','PROFILE_WAIVER','SCREENPLAY_ADMISSION')"
_SIDECAR_KINDS = "('WESTERN_DRAMA_ANALYSIS','SHUANGWEN_ANALYSIS')"
_FINDING_DISPOSITIONS = "('INTEGRITY_BLOCK','PROFILE_BLOCK','ADVISORY','NOT_APPLICABLE')"


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


class AdaptationDecisionModel(UserOwnedMixin, Base):
    """Append-only decision log entry (plan Task 7). ``decision_id`` is a single global
    identity registry per ``(user_id, project_name)`` across every family, matching
    ``AdaptationAuthorityRepositoryPort.get_decision_by_id``'s family-agnostic lookup.
    Carries no FK to ``adaptation_heads``: the head row is always prepared before any
    decision referencing it is inserted (enforced by ``AdaptationAuthorityService``'s
    call order, mirroring M5C's own decision/head table pair), and a decision->head FK
    alongside the head->decision FK below would be circular.
    """

    __tablename__ = "adaptation_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "decision_id", name="pk_adaptation_decisions"),
        UniqueConstraint(
            "user_id", "project_name", "family", "head_key", "sequence", name="uq_adaptation_decisions_chain_position"
        ),
        CheckConstraint(f"family IN {_AUTHORITY_FAMILIES}", name="ck_adaptation_decisions_family"),
        CheckConstraint(f"decision_kind IN {_DECISION_KINDS}", name="ck_adaptation_decisions_kind"),
        CheckConstraint("sequence >= 1", name="ck_adaptation_decisions_sequence"),
        Index("ix_adaptation_decisions_project_name", "project_name"),
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

    family: Mapped[str] = mapped_column(String(32), nullable=False)
    head_key: Mapped[str] = mapped_column(_ID, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    command_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authorization_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision_digest: Mapped[str] = mapped_column(_ID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdaptationHeadModel(UserOwnedMixin, Base):
    """The one mutable, rebuildable lock/index projection per ``(user_id, project_name,
    family, head_key)`` (plan Task 7). ``generation = 0`` is an internal-only genesis
    sentinel — the repository translates it to the public ``None`` (no decisions yet);
    a real ``AdaptationHead`` never has ``generation < 1``. Created via ``INSERT ...
    ON CONFLICT DO NOTHING`` at genesis, then always read back through ``SELECT ...
    FOR UPDATE`` before its columns are trusted (plan global constraint: "genesis uses
    unique insert plus lock/reread, never absent-row FOR UPDATE").
    """

    __tablename__ = "adaptation_heads"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "family", "head_key", name="pk_adaptation_heads"),
        ForeignKeyConstraint(
            ["latest_decision_id", "user_id", "project_name"],
            ["adaptation_decisions.decision_id", "adaptation_decisions.user_id", "adaptation_decisions.project_name"],
            name="fk_adaptation_heads_latest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["effective_decision_id", "user_id", "project_name"],
            ["adaptation_decisions.decision_id", "adaptation_decisions.user_id", "adaptation_decisions.project_name"],
            name="fk_adaptation_heads_effective",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"family IN {_AUTHORITY_FAMILIES}", name="ck_adaptation_heads_family"),
        CheckConstraint("generation >= 0", name="ck_adaptation_heads_generation"),
        Index("ix_adaptation_heads_project_name", "project_name"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    family: Mapped[str] = mapped_column(String(32), primary_key=True)
    head_key: Mapped[str] = mapped_column(_ID, primary_key=True)

    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_decision_id: Mapped[str | None] = mapped_column(_ID)
    effective_decision_id: Mapped[str | None] = mapped_column(_ID)
    selected_artifact_id: Mapped[str | None] = mapped_column(_ID)
    selected_artifact_version: Mapped[int | None] = mapped_column(Integer)
    selected_artifact_hash: Mapped[str | None] = mapped_column(_ID)


class AdaptationProfileSidecarModel(UserOwnedMixin, Base):
    """One versioned profile-analysis sidecar (``WesternDramaAnalysis`` or
    ``ShuangwenAnalysis``, plan Task 11). ``sidecar_id`` is minted deterministically by
    ``ProfileEvaluationService`` from the evaluated artifact id and the profile id
    (``f"{artifact_id}:{profile_id}"``), so the same artifact evaluated under two
    different profiles never collides, and ``version`` mirrors the evaluated artifact's
    own version — re-evaluating unchanged content under the same profile is a pure,
    deterministic, byte-identical exact retry; a different tuple at the same
    ``(sidecar_id, version)`` is a real identity conflict (an evaluator regression),
    never silently overwritten. The full sidecar payload is stored as JSON (its shape is
    a closed Pydantic contract, not a queryable relation) with a ``kind`` discriminator
    to reconstruct the exact model.
    """

    __tablename__ = "adaptation_profile_sidecars"
    __table_args__ = (
        PrimaryKeyConstraint("sidecar_id", "version", name="pk_adaptation_profile_sidecars"),
        UniqueConstraint(
            "user_id", "project_name", "sidecar_id", "version", name="uq_adaptation_profile_sidecars_scope"
        ),
        CheckConstraint("version >= 1", name="ck_adaptation_profile_sidecars_version"),
        CheckConstraint(f"kind IN {_SIDECAR_KINDS}", name="ck_adaptation_profile_sidecars_kind"),
        Index("ix_adaptation_profile_sidecars_project_name", "project_name"),
    )

    sidecar_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AdaptationEvaluationReportModel(UserOwnedMixin, Base):
    """One immutable ``ProfileEvaluationReport`` (plan Task 11). Content-addressed by
    its own ``report_digest`` (``compute_profile_evaluation_report_digest``) — a report
    has no separate opaque id, so an exact retry with byte-identical content always
    lands on the same primary-key row, and there is no tuple-mismatch case to detect: a
    colliding digest can only carry identical content by construction of the hash. A
    ``ProfileWaiverCommand.report_ref``/``MapApprovalCommand.relied_report_refs`` entry
    names this row by ``decision_id=decision_digest=report_digest``, the same generic
    ``DecisionRef`` shape used for real authority decisions.
    """

    __tablename__ = "adaptation_evaluation_reports"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "project_name", "report_digest", name="pk_adaptation_evaluation_reports"),
        Index("ix_adaptation_evaluation_reports_project_name", "project_name"),
        Index(
            "ix_adaptation_evaluation_reports_artifact",
            "user_id",
            "project_name",
            "artifact_hash",
            "profile_id",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    report_digest: Mapped[str] = mapped_column(_ID, primary_key=True)

    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(_ID, nullable=False)

    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    policy_pack_digest: Mapped[str] = mapped_column(_ID, nullable=False)

    evaluator_version: Mapped[str] = mapped_column(_SHORT, nullable=False)

    sidecar_ref_id: Mapped[str] = mapped_column(_ID, nullable=False)
    sidecar_ref_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sidecar_ref_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    sidecar_digest: Mapped[str] = mapped_column(_ID, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdaptationEvaluationFindingModel(UserOwnedMixin, Base):
    """Ordered ``findings`` on one evaluation report. One row per finding (plan Task 11),
    mirroring ``AdaptationMapEntryModel``'s ordered-child-row pattern."""

    __tablename__ = "adaptation_evaluation_findings"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "project_name", "report_digest", "finding_id", name="pk_adaptation_evaluation_findings"
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "report_digest"],
            [
                "adaptation_evaluation_reports.user_id",
                "adaptation_evaluation_reports.project_name",
                "adaptation_evaluation_reports.report_digest",
            ],
            name="fk_adaptation_evaluation_findings_report",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "project_name",
            "report_digest",
            "position",
            name="uq_adaptation_evaluation_findings_position",
        ),
        CheckConstraint(
            f"disposition IN {_FINDING_DISPOSITIONS}", name="ck_adaptation_evaluation_findings_disposition"
        ),
        CheckConstraint("position >= 0", name="ck_adaptation_evaluation_findings_position"),
        Index("ix_adaptation_evaluation_findings_project_name", "project_name"),
    )

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        server_default=DEFAULT_USER_ID,
        primary_key=True,
    )
    project_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    report_digest: Mapped[str] = mapped_column(_ID, primary_key=True)
    finding_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    rule_id: Mapped[str] = mapped_column(_ID, nullable=False)
    rule_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    applicability: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    target_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_span: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_refs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    message_params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AdaptationScreenplayAdmissionModel(UserOwnedMixin, Base):
    """A dedicated read-optimized projection: which exact screenplay version is
    currently admitted (``APPROVED`` + ``locked_for_direction``) for direction, and by
    which decision (plan Task 12). One row per admitted screenplay version, inserted
    atomically alongside its ``adaptation_screenplays`` row and its
    ``SCREENPLAY_ADMISSION`` decision, in the same transaction as the authority
    write — never inserted for a ``REVOKE`` decision. This is what
    ``ApprovedScreenplayReader`` reads; it never joins the generic decision chain, and
    nothing outside ``AdaptationAuthorityService`` ever writes it.
    """

    __tablename__ = "adaptation_screenplay_admissions"
    __table_args__ = (
        PrimaryKeyConstraint("screenplay_id", "screenplay_version", name="pk_adaptation_screenplay_admissions"),
        UniqueConstraint(
            "user_id",
            "project_name",
            "screenplay_id",
            "screenplay_version",
            name="uq_adaptation_screenplay_admissions_scope",
        ),
        ForeignKeyConstraint(
            ["user_id", "project_name", "screenplay_id", "screenplay_version"],
            [
                "adaptation_screenplays.user_id",
                "adaptation_screenplays.project_name",
                "adaptation_screenplays.screenplay_id",
                "adaptation_screenplays.version",
            ],
            name="fk_adaptation_screenplay_admissions_screenplay",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["admission_decision_id", "user_id", "project_name"],
            ["adaptation_decisions.decision_id", "adaptation_decisions.user_id", "adaptation_decisions.project_name"],
            name="fk_adaptation_screenplay_admissions_decision",
            ondelete="RESTRICT",
        ),
        Index("ix_adaptation_screenplay_admissions_project_name", "project_name"),
    )

    screenplay_id: Mapped[str] = mapped_column(_ID, primary_key=True)
    screenplay_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    screenplay_content_hash: Mapped[str] = mapped_column(_ID, nullable=False)
    admission_decision_id: Mapped[str] = mapped_column(_ID, nullable=False)
    admission_decision_digest: Mapped[str] = mapped_column(_ID, nullable=False)

    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(_SHORT, nullable=False)
    policy_pack_digest: Mapped[str] = mapped_column(_ID, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
