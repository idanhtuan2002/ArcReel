"""Bind format review packets to the reviewer's showrunner grant and to neutral review clips (M8-E).

A packet records the grant event that authorized its reviewer and the two per-packet review copies
it serves as labels A and B. Rows written before this revision keep NULL and serve no clips.

Revision ID: 918c4a0e0001
Revises: 917c4a0e0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "918c4a0e0001"
down_revision: str | Sequence[str] | None = "917c4a0e0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("grant_event_digest", 71),
    ("clip_a_ref", 255),
    ("clip_a_digest", 71),
    ("clip_b_ref", 255),
    ("clip_b_digest", 71),
)


def upgrade() -> None:
    with op.batch_alter_table("m8_format_review_packets") as batch:
        for name, length in _COLUMNS:
            batch.add_column(sa.Column(name, sa.String(length), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("m8_format_review_packets") as batch:
        for name, _length in reversed(_COLUMNS):
            batch.drop_column(name)
