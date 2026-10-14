"""Allow a format slot's first promotion preview to bind no master at version 0 (M8-E amendment).

Every other ARTIFACT_SLOT preview still binds an exact master; PRODUCTION_BINDING previews still
bind none.

Revision ID: 917c4a0e0001
Revises: 916c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "917c4a0e0001"
down_revision: str | Sequence[str] | None = "916c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ck_m8_promotion_previews_master_coupling"
_BEFORE = (
    "(target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NOT NULL AND expected_master_digest IS NOT NULL)"
    " OR (target_kind = 'PRODUCTION_BINDING' AND expected_master_id IS NULL"
    " AND expected_master_digest IS NULL)"
)
_AFTER = (
    "(target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NOT NULL AND expected_master_digest IS NOT NULL)"
    " OR (target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NULL AND expected_master_digest IS NULL"
    " AND expected_target_version = 0 AND target_ref LIKE 'm8-format:%')"
    " OR (target_kind = 'PRODUCTION_BINDING' AND expected_master_id IS NULL"
    " AND expected_master_digest IS NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("m8_promotion_previews") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _AFTER)


def downgrade() -> None:
    genesis = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM m8_promotion_previews WHERE target_kind = 'ARTIFACT_SLOT' AND expected_master_id IS NULL"
            )
        )
        .scalar_one()
    )
    if genesis:
        raise RuntimeError("format slot genesis previews exist; they cannot be kept by the earlier schema")
    with op.batch_alter_table("m8_promotion_previews") as batch:
        batch.drop_constraint(_NAME, type_="check")
        batch.create_check_constraint(_NAME, _BEFORE)
