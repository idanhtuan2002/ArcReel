"""A profile publication authorization names the grant chain it was issued under (ADR-0123 workspace fallback).

The authorization row referenced the grant event of its own project; a project that rests on the workspace grant has
no event of its own, so recording its authorization broke the foreign key. The row now carries the chain
(``grant_project_name``: the project, or ``@workspace``), and the key follows it. Existing rows rest on their project.
The table is append-only: its immutability trigger is held only for the backfill, inside the migration transaction.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7a310300005"
down_revision = "b7a310300004"
branch_labels = None
depends_on = None

TABLE = "m10_profile_publication_authorizations"
FK = "fk_m10_publication_authorizations_grant"
PG_TRIGGER = f"{TABLE}_immutable"
SQLITE_TRIGGERS = (("UPDATE", "no_update"), ("DELETE", "no_delete"))


def _foreign_key(batch: object, project_column: str) -> None:
    batch.create_foreign_key(  # type: ignore[attr-defined]
        FK,
        "r2_showrunner_grant_events",
        ["user_id", project_column, "actor_id", "grant_sequence"],
        ["user_id", "project_name", "principal", "sequence"],
        ondelete="RESTRICT",
    )


def _sqlite_triggers(bind: sa.Connection) -> None:
    for event, suffix in SQLITE_TRIGGERS:
        bind.exec_driver_sql(
            f'CREATE TRIGGER IF NOT EXISTS "{TABLE}_{suffix}" BEFORE {event} ON "{TABLE}" '
            "BEGIN SELECT RAISE(ABORT, 'M10_IMMUTABLE_PUBLICATION_ROW'); END"
        )


def _backfill(bind: sa.Connection) -> None:
    update = f'UPDATE "{TABLE}" SET grant_project_name = project_name'
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f'ALTER TABLE "{TABLE}" DISABLE TRIGGER "{PG_TRIGGER}"')
        bind.exec_driver_sql(update)
        bind.exec_driver_sql(f'ALTER TABLE "{TABLE}" ENABLE TRIGGER "{PG_TRIGGER}"')
    else:
        bind.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{TABLE}_no_update"')
        bind.exec_driver_sql(update)


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(TABLE, sa.Column("grant_project_name", sa.String(255), nullable=True))
    _backfill(bind)
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("grant_project_name", existing_type=sa.String(255), nullable=False)
        batch.drop_constraint(FK, type_="foreignkey")
        _foreign_key(batch, "grant_project_name")
    if bind.dialect.name == "sqlite":
        _sqlite_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(FK, type_="foreignkey")
        _foreign_key(batch, "project_name")
        batch.drop_column("grant_project_name")
    if bind.dialect.name == "sqlite":
        _sqlite_triggers(bind)
