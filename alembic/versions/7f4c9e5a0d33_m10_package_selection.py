"""Persist M10-B package previews, Human selections, their leases and the PACKAGING_SLOT heads.

Revision ID: 7f4c9e5a0d33
Revises: 6e3b8d4f9c22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f4c9e5a0d33"
down_revision: str | Sequence[str] | None = "6e3b8d4f9c22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY = ("m10_package_previews", "m10_package_selection_authorizations", "m10_package_selections")
_HEADS = "m10_packaging_heads"
_TABLES = (*_APPEND_ONLY, _HEADS)


def _ceiling(table: str, column: str) -> sa.CheckConstraint:
    measure = (
        "octet_length(CAST({} AS text))" if op.get_bind().dialect.name == "postgresql" else "length(CAST({} AS BLOB))"
    )
    return sa.CheckConstraint(f"{measure.format(column)} <= 1048576", name=f"ck_{table}_{column}_bytes")


def install_immutability(connection: sa.engine.Connection) -> None:
    """Append-only previews, leases and selections; heads may advance but never disappear."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION m10_packaging_selection_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $m10$
            BEGIN
                RAISE EXCEPTION 'M10_IMMUTABLE_PACKAGING_ROW' USING ERRCODE = '23514';
            END;
            $m10$
        """)
        for table in _APPEND_ONLY:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION m10_packaging_selection_immutable_row()"
            )
        connection.exec_driver_sql(
            f'CREATE TRIGGER "{_HEADS}_no_delete" BEFORE DELETE ON "{_HEADS}" '
            "FOR EACH ROW EXECUTE FUNCTION m10_packaging_selection_immutable_row()"
        )
    elif connection.dialect.name == "sqlite":
        for table in _APPEND_ONLY:
            for event, suffix in (("UPDATE", "no_update"), ("DELETE", "no_delete")):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_{suffix}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PACKAGING_ROW'); END"
                )
        connection.exec_driver_sql(
            f'CREATE TRIGGER "{_HEADS}_no_delete" BEFORE DELETE ON "{_HEADS}" '
            "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PACKAGING_ROW'); END"
        )
    else:
        raise RuntimeError("M10_SCHEMA_CHANGE_REQUIRED")


def upgrade() -> None:
    op.create_table(
        "m10_package_previews",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("preview_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("source_artifact_key", sa.String(255), nullable=False),
        sa.Column("cohort_id", sa.String(255), nullable=False),
        sa.Column("product_surface", sa.String(255), nullable=False),
        sa.Column("packaging_observation_id", sa.String(36), nullable=False),
        sa.Column("preview_digest", sa.String(71), nullable=False),
        sa.Column("preview_json", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_package_previews_command"
        ),
        sa.PrimaryKeyConstraint("user_id", "project_name", "preview_id", name="pk_m10_package_previews"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "packaging_observation_id"],
            [
                "m10_packaging_observations.user_id",
                "m10_packaging_observations.project_name",
                "m10_packaging_observations.observation_id",
            ],
            name="fk_m10_package_previews_observation",
            ondelete="RESTRICT",
        ),
        _ceiling("m10_package_previews", "preview_json"),
    )
    op.create_table(
        "m10_package_selection_authorizations",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("lease_json", sa.JSON, nullable=False),
        sa.Column("grant_sequence", sa.Integer, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "project_name", "authorization_id", name="pk_m10_package_selection_authorizations"
        ),
        _ceiling("m10_package_selection_authorizations", "lease_json"),
    )
    op.create_table(
        "m10_package_selections",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("selection_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("command_id", sa.String(255), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("preview_id", sa.String(36), nullable=False),
        sa.Column("authorization_id", sa.String(255), nullable=False),
        sa.Column("source_artifact_key", sa.String(255), nullable=False),
        sa.Column("cohort_id", sa.String(255), nullable=False),
        sa.Column("product_surface", sa.String(255), nullable=False),
        sa.Column("head_version", sa.Integer, nullable=False),
        sa.Column("selection_digest", sa.String(71), nullable=False),
        sa.Column("selection_json", sa.JSON, nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", "selection_id", name="pk_m10_package_selections"),
        sa.UniqueConstraint(
            "user_id", "project_name", "actor_id", "command_id", name="uq_m10_package_selections_command"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            ["m10_package_previews.user_id", "m10_package_previews.project_name", "m10_package_previews.preview_id"],
            name="fk_m10_package_selections_preview",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("head_version >= 1", name="ck_m10_package_selections_version"),
        sa.UniqueConstraint("user_id", "project_name", "authorization_id", name="uq_m10_package_selections_lease"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "authorization_id"],
            [
                "m10_package_selection_authorizations.user_id",
                "m10_package_selection_authorizations.project_name",
                "m10_package_selection_authorizations.authorization_id",
            ],
            name="fk_m10_package_selections_lease",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "project_name",
            "source_artifact_key",
            "cohort_id",
            "product_surface",
            "head_version",
            name="uq_m10_package_selections_slot",
        ),
        _ceiling("m10_package_selections", "selection_json"),
    )
    op.create_table(
        "m10_packaging_heads",
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("source_artifact_key", sa.String(255), nullable=False),
        sa.Column("cohort_id", sa.String(255), nullable=False),
        sa.Column("product_surface", sa.String(255), nullable=False),
        sa.Column("current_selection_id", sa.String(36), nullable=False),
        sa.Column("head_version", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id",
            "project_name",
            "source_artifact_key",
            "cohort_id",
            "product_surface",
            name="pk_m10_packaging_heads",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "current_selection_id"],
            [
                "m10_package_selections.user_id",
                "m10_package_selections.project_name",
                "m10_package_selections.selection_id",
            ],
            name="fk_m10_packaging_heads_selection",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("head_version >= 1", name="ck_m10_packaging_heads_version"),
    )
    install_immutability(op.get_bind())


def downgrade() -> None:
    """Refuse rather than discard selection history."""
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():
            raise RuntimeError("M10_PACKAGING_HISTORY_PRESENT")
    for table in reversed(_TABLES):
        op.drop_table(table)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION m10_packaging_selection_immutable_row()"))
