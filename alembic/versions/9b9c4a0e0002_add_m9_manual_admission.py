"""Add scoped manual admission, independent intents and bounded read/upload leases."""

import sqlalchemy as sa

from alembic import op

revision = "9b9c4a0e0002"
down_revision = "9b9c4a0e0001"
branch_labels = None
depends_on = None

_TABLES = (
    "m9_manual_admissions",
    "m9_manual_publication_intents",
    "m9_manual_upload_leases",
    "m9_manual_read_leases",
    "m9_manual_closure_intents",
)
_V1_STATES = "'PLANNED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN','NEEDS_OPERATOR'"
_V2_STATE_CHECK = (
    f"(protocol_version = 'm9.acquisition.v1' AND state IN ({_V1_STATES})) OR "
    f"(protocol_version = 'm9.acquisition.v2' AND state IN ({_V1_STATES},'EXPIRED_UNRECOVERABLE'))"
)


def _alter_attempt(*, upgrading: bool) -> None:
    connection = op.get_bind()
    source = sa.Table("m9_acquisition_attempts", sa.MetaData(), autoload_with=connection)
    state_checks = [c for c in source.constraints if isinstance(c, sa.CheckConstraint) and "PLANNED" in str(c.sqltext)]
    if len(state_checks) != 1:
        raise RuntimeError("M9_REQUIRED_EVIDENCE_MISSING: attempt state constraint differs")
    state_check = state_checks[0]
    if state_check.name is None:
        state_check.name = "ck_m9_attempt_state_v1"
    with op.batch_alter_table("m9_acquisition_attempts", copy_from=source) as batch:
        batch.drop_constraint(str(state_check.name), type_="check")
        if upgrading:
            batch.add_column(
                sa.Column("protocol_version", sa.String(32), nullable=False, server_default="m9.acquisition.v1")
            )
            batch.create_check_constraint(
                "ck_m9_attempt_protocol", "protocol_version IN ('m9.acquisition.v1','m9.acquisition.v2')"
            )
            batch.create_check_constraint("ck_m9_attempt_state_protocol", _V2_STATE_CHECK)
        else:
            batch.drop_constraint("ck_m9_attempt_protocol", type_="check")
            batch.drop_column("protocol_version")
            batch.create_check_constraint("ck_m9_attempt_state_v1", f"state IN ({_V1_STATES})")


def _create(name, primary, columns, constraints):
    op.create_table(
        name,
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("attempt_id", sa.String(255), nullable=False),
        *columns,
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column("metadata_digest", sa.String(71), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "project_name", *primary),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_id", "project_name", "attempt_id"],
            [
                "m9_acquisition_attempts.user_id",
                "m9_acquisition_attempts.project_name",
                "m9_acquisition_attempts.attempt_id",
            ],
            ondelete="RESTRICT",
        ),
        *constraints,
    )


def upgrade() -> None:
    _alter_attempt(upgrading=True)
    _create(
        "m9_manual_admissions",
        ("attempt_id",),
        [
            sa.Column("phase", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("erasure_fenced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("erasure_version", sa.Integer(), nullable=True),
        ],
        [
            sa.CheckConstraint("version >= 1"),
            sa.CheckConstraint("phase IN ('RESERVED','READY','CLEANUP_PENDING','ERASED')"),
            sa.CheckConstraint("phase <> 'READY' OR admitted_at IS NOT NULL"),
            sa.CheckConstraint(
                "(erasure_fenced_at IS NULL AND erasure_version IS NULL) OR (erasure_fenced_at IS NOT NULL AND erasure_version IS NOT NULL AND erasure_version >= 1)"
            ),
        ],
    )
    _create(
        "m9_manual_publication_intents",
        ("publication_key",),
        [
            sa.Column("publication_key", sa.String(255), nullable=False),
            sa.Column("phase", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
        ],
        [
            sa.UniqueConstraint("user_id", "project_name", "attempt_id"),
            sa.CheckConstraint("version >= 1"),
            sa.CheckConstraint("phase IN ('RESERVED','READY','CLEANUP_PENDING','ERASED')"),
        ],
    )
    _create(
        "m9_manual_upload_leases",
        ("claim_ref", "upload_version", "attempt_id"),
        [
            sa.Column("claim_ref", sa.String(255), nullable=False),
            sa.Column("upload_version", sa.Integer(), nullable=False),
            sa.Column("source_kind", sa.String(64), nullable=False),
            sa.Column("source_contract_version", sa.String(255), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("closure_id", sa.String(255), nullable=True),
        ],
        [
            sa.CheckConstraint("version >= 1 AND upload_version >= 1"),
            sa.CheckConstraint("state IN ('ACTIVE','CLOSING','SPENT')"),
        ],
    )
    _create(
        "m9_manual_read_leases",
        ("lease_id",),
        [
            sa.Column("lease_id", sa.String(255), nullable=False),
            sa.Column("attempt_version", sa.Integer(), nullable=False),
            sa.Column("envelope_version", sa.Integer(), nullable=False),
            sa.Column("operational", sa.Boolean(), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        ],
        [
            sa.CheckConstraint("attempt_version >= 1 AND envelope_version >= 1"),
            sa.CheckConstraint("expires_at > issued_at"),
            sa.CheckConstraint("released_at IS NULL OR released_at >= issued_at"),
        ],
    )
    _create(
        "m9_manual_closure_intents",
        ("closure_id",),
        [
            sa.Column("closure_id", sa.String(255), nullable=False),
            sa.Column("attempt_version", sa.Integer(), nullable=False),
            sa.Column("envelope_version", sa.Integer(), nullable=False),
            sa.Column("phase", sa.String(32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("fenced_at", sa.DateTime(timezone=True), nullable=False),
        ],
        [
            sa.CheckConstraint("version >= 1 AND attempt_version >= 1 AND envelope_version >= 1"),
            sa.CheckConstraint("phase IN ('CLEANUP_PENDING','ERASED')"),
        ],
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT 1 FROM m9_acquisition_attempts WHERE protocol_version = 'm9.acquisition.v2' LIMIT 1")
    ) is not None or any(
        connection.scalar(sa.text("SELECT 1 FROM " + name + " LIMIT 1")) is not None for name in _TABLES
    ):
        raise RuntimeError("M9_REQUIRED_EVIDENCE_MISSING: successor custody prevents downgrade")
    for name in reversed(_TABLES):
        op.drop_table(name)
    _alter_attempt(upgrading=False)
