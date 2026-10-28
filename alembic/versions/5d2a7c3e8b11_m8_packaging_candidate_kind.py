"""Admit the M10 PACKAGING candidate kind in the shared M8 revision kernel.

Revision ID: 5d2a7c3e8b11
Revises: 4c1f0e2a9b10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5d2a7c3e8b11"
down_revision: str | Sequence[str] | None = "4c1f0e2a9b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "m8_candidate_revisions"
_CHECK = "ck_m8_candidate_revisions_kind"


def _replace_check(kinds: str) -> None:
    with op.batch_alter_table(_TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(_CHECK, type_="check")
        batch_op.create_check_constraint(_CHECK, f"kind IN ({kinds})")


def upgrade() -> None:
    _replace_check("'CANVAS', 'SPATIAL', 'FORMAT', 'PACKAGING'")


def downgrade() -> None:
    """Refuse rather than discard packaging revisions."""
    if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {_TABLE} WHERE kind = 'PACKAGING'")).scalar_one():
        raise RuntimeError("M10_PACKAGING_HISTORY_PRESENT")
    _replace_check("'CANVAS', 'SPATIAL', 'FORMAT'")
