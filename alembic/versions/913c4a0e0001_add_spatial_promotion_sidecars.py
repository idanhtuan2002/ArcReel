"""Add typed spatial promotion sidecars and their coupling to binding-target previews and receipts.

Revision ID: 913c4a0e0001
Revises: 912c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "913c4a0e0001"
down_revision: str | Sequence[str] | None = "912c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = """
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
_TRIGGER = (
    "CREATE CONSTRAINT TRIGGER {name}_{suffix} AFTER {events} ON {table} "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {name}()"
)
_PAIRS = (
    ("m8_spatial_preview_coupling", "m8_promotion_previews", "m8_spatial_preview_bindings", "preview_id"),
    ("m8_spatial_receipt_coupling", "m8_promotion_receipts", "m8_spatial_promotion_results", "receipt_id"),
)


def upgrade() -> None:
    op.create_table(
        "m8_spatial_preview_bindings",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("preview_id", sa.String(255), nullable=False),
        sa.Column("binding_id", sa.String(255), nullable=False),
        sa.Column("expected_binding_version", sa.Integer(), nullable=False),
        sa.Column("binding_json", sa.JSON(), nullable=False),
        sa.Column("preview_v2_digest", sa.String(71), nullable=False),
        sa.PrimaryKeyConstraint("preview_id", name="pk_m8_spatial_preview_bindings"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "preview_id"],
            ["m8_promotion_previews.user_id", "m8_promotion_previews.project_name", "m8_promotion_previews.preview_id"],
            name="fk_m8_spatial_preview_bindings_preview",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "binding_id"],
            [
                "production_binding_heads.user_id",
                "production_binding_heads.project_name",
                "production_binding_heads.binding_id",
            ],
            name="fk_m8_spatial_preview_bindings_binding",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("expected_binding_version >= 1", name="ck_m8_spatial_preview_bindings_version"),
    )
    op.create_table(
        "m8_spatial_promotion_results",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("receipt_id", sa.String(255), nullable=False),
        sa.Column("binding_id", sa.String(255), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.String(255), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("receipt_v2_digest", sa.String(71), nullable=False),
        sa.PrimaryKeyConstraint("receipt_id", name="pk_m8_spatial_promotion_results"),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["m8_promotion_receipts.receipt_id"],
            name="fk_m8_spatial_promotion_results_receipt",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "set_id"],
            [
                "m8_spatial_constraint_sets.user_id",
                "m8_spatial_constraint_sets.project_name",
                "m8_spatial_constraint_sets.set_id",
            ],
            name="fk_m8_spatial_promotion_results_set",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("binding_version >= 2", name="ck_m8_spatial_promotion_results_version"),
    )
    if op.get_bind().dialect.name == "postgresql":
        for name, base, sidecar, key in _PAIRS:
            op.execute(_FUNCTION.format(name=name, base=base, sidecar=sidecar, key=key))
            op.execute(_TRIGGER.format(name=name, suffix="base", events="INSERT OR UPDATE", table=base))
            op.execute(_TRIGGER.format(name=name, suffix="sidecar", events="INSERT OR UPDATE OR DELETE", table=sidecar))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for name, base, sidecar, _key in _PAIRS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}_sidecar ON {sidecar}")
            op.execute(f"DROP TRIGGER IF EXISTS {name}_base ON {base}")
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    op.drop_table("m8_spatial_promotion_results")
    op.drop_table("m8_spatial_preview_bindings")
