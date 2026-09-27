"""add request/task correlation columns

Revision ID: a7c3e9d1f200
Revises: d80b64c4edcf
Create Date: 2026-09-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from lib.db.migration_helpers import preserve_sqlite_indexes

revision: str = "a7c3e9d1f200"
down_revision: str | Sequence[str] | None = "d80b64c4edcf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=255), nullable=True))
        batch_op.create_index("idx_tasks_request_id", ["request_id"], unique=False)
    with op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.String(length=255), nullable=True))
        batch_op.create_index("idx_api_calls_task_id", ["task_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_api_calls_task_id", table_name="api_calls")
    with preserve_sqlite_indexes("api_calls"), op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.drop_column("task_id")
    op.drop_index("idx_tasks_request_id", table_name="tasks")
    with preserve_sqlite_indexes("tasks"), op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("request_id")
