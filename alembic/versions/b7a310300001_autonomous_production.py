"""Persist autonomous production runs and append-only orchestration evidence.

Revision ID: b7a310300001
Revises: 8a5d0f6b1e44
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7a310300001"
down_revision = "8a5d0f6b1e44"
branch_labels = None
depends_on = None

# Frozen DDL; migration execution does not import application models.
_SCHEMA_SQL: dict[str, tuple[str, ...]] = {
    "postgresql": (
        """CREATE TABLE auto_production_policies (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	policy_json TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, policy_digest), 
	CONSTRAINT ck_auto_policy_json_bytes_pg CHECK (octet_length(policy_json) <= 1048576), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""",
        """CREATE TABLE auto_production_runs (
	run_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	input_digest VARCHAR(71) NOT NULL, 
	start_command_id VARCHAR(255) NOT NULL, 
	start_command_digest VARCHAR(71) NOT NULL, 
	start_command_json TEXT NOT NULL, 
	snapshot_json TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	stage VARCHAR(32) NOT NULL, 
	version BIGINT NOT NULL, 
	generation BIGINT NOT NULL, 
	fencing_epoch BIGINT NOT NULL, 
	lease_owner VARCHAR(255), 
	lease_until TIMESTAMP WITH TIME ZONE, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (run_id), 
	CONSTRAINT uq_auto_run_scope UNIQUE (user_id, project_name, run_id), 
	CONSTRAINT uq_auto_start_command UNIQUE (user_id, project_name, start_command_id), 
	CONSTRAINT fk_auto_run_policy FOREIGN KEY(user_id, project_name, run_id, policy_digest) REFERENCES auto_production_policies (user_id, project_name, run_id, policy_digest) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_run_versions CHECK (version >= 1 AND generation >= 1 AND fencing_epoch >= 0), 
	CONSTRAINT ck_auto_run_lease_pair CHECK ((lease_owner IS NULL) = (lease_until IS NULL)), 
	CONSTRAINT ck_auto_snapshot_json_bytes_pg CHECK (octet_length(snapshot_json) <= 1048576), 
	CONSTRAINT ck_auto_start_command_json_bytes_pg CHECK (octet_length(start_command_json) <= 1048576)
)""",
        """CREATE INDEX idx_auto_run_due ON auto_production_runs (status, due_at)""",
        """CREATE UNIQUE INDEX uq_auto_active_project ON auto_production_runs (user_id, project_name) WHERE status NOT IN ('SUCCEEDED','FAILED','FAILED_QUALITY','CANCELLED')""",
        """CREATE TABLE auto_production_steps (
	command_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	stage VARCHAR(32) NOT NULL, 
	unit_key VARCHAR(255) NOT NULL, 
	generation BIGINT NOT NULL, 
	repair_index INTEGER NOT NULL, 
	input_digest VARCHAR(71) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	intent_digest VARCHAR(71) NOT NULL, 
	intent_json TEXT NOT NULL, 
	receipt_json TEXT, 
	PRIMARY KEY (command_id), 
	CONSTRAINT fk_auto_step_run FOREIGN KEY(user_id, project_name, run_id) REFERENCES auto_production_runs (user_id, project_name, run_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_step_scope UNIQUE (user_id, project_name, run_id, command_id), 
	CONSTRAINT uq_auto_step_identity UNIQUE (user_id, project_name, run_id, stage, unit_key, generation, repair_index, input_digest, policy_digest), 
	CONSTRAINT ck_auto_step_versions CHECK (generation >= 1 AND repair_index >= 0), 
	CONSTRAINT ck_auto_intent_json_bytes_pg CHECK (octet_length(intent_json) <= 1048576), 
	CONSTRAINT ck_auto_receipt_json_bytes_pg CHECK (octet_length(receipt_json) <= 1048576)
)""",
        """CREATE TABLE auto_production_allocations (
	reservation_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	command_id VARCHAR(255) NOT NULL, 
	reservation_json TEXT NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	held_cost BIGINT NOT NULL, 
	held_calls BIGINT NOT NULL, 
	held_tasks BIGINT NOT NULL, 
	held_runtime BIGINT NOT NULL, 
	settled_usage_digest VARCHAR(71), 
	PRIMARY KEY (reservation_id), 
	CONSTRAINT fk_auto_allocation_step FOREIGN KEY(user_id, project_name, run_id, command_id) REFERENCES auto_production_steps (user_id, project_name, run_id, command_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_allocation_scope UNIQUE (user_id, project_name, run_id, reservation_id), 
	CONSTRAINT uq_auto_allocation_command UNIQUE (command_id), 
	CONSTRAINT ck_auto_allocation_state CHECK (state IN ('RESERVED','UNKNOWN','SETTLED')), 
	CONSTRAINT ck_auto_allocation_totals CHECK (held_cost >= 0 AND held_calls >= 0 AND held_tasks >= 0 AND held_runtime >= 0), 
	CONSTRAINT ck_auto_reservation_json_bytes_pg CHECK (octet_length(reservation_json) <= 1048576)
)""",
        """CREATE TABLE auto_production_usage_refs (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	owner VARCHAR(255) NOT NULL, 
	receipt_ref VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	reservation_id VARCHAR(255) NOT NULL, 
	usage_digest VARCHAR(71) NOT NULL, 
	usage_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, owner, receipt_ref), 
	CONSTRAINT fk_auto_usage_allocation FOREIGN KEY(user_id, project_name, run_id, reservation_id) REFERENCES auto_production_allocations (user_id, project_name, run_id, reservation_id) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_usage_json_bytes_pg CHECK (octet_length(usage_json) <= 1048576)
)""",
    ),
    "sqlite": (
        """CREATE TABLE auto_production_policies (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	policy_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, policy_digest), 
	CONSTRAINT ck_auto_policy_json_bytes_sqlite CHECK (length(CAST(policy_json AS BLOB)) <= 1048576), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""",
        """CREATE TABLE auto_production_runs (
	run_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	input_digest VARCHAR(71) NOT NULL, 
	start_command_id VARCHAR(255) NOT NULL, 
	start_command_digest VARCHAR(71) NOT NULL, 
	start_command_json TEXT NOT NULL, 
	snapshot_json TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	stage VARCHAR(32) NOT NULL, 
	version BIGINT NOT NULL, 
	generation BIGINT NOT NULL, 
	fencing_epoch BIGINT NOT NULL, 
	lease_owner VARCHAR(255), 
	lease_until DATETIME, 
	due_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (run_id), 
	CONSTRAINT uq_auto_run_scope UNIQUE (user_id, project_name, run_id), 
	CONSTRAINT uq_auto_start_command UNIQUE (user_id, project_name, start_command_id), 
	CONSTRAINT fk_auto_run_policy FOREIGN KEY(user_id, project_name, run_id, policy_digest) REFERENCES auto_production_policies (user_id, project_name, run_id, policy_digest) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_run_versions CHECK (version >= 1 AND generation >= 1 AND fencing_epoch >= 0), 
	CONSTRAINT ck_auto_run_lease_pair CHECK ((lease_owner IS NULL) = (lease_until IS NULL)), 
	CONSTRAINT ck_auto_snapshot_json_bytes_sqlite CHECK (length(CAST(snapshot_json AS BLOB)) <= 1048576), 
	CONSTRAINT ck_auto_start_command_json_bytes_sqlite CHECK (length(CAST(start_command_json AS BLOB)) <= 1048576)
)""",
        """CREATE INDEX idx_auto_run_due ON auto_production_runs (status, due_at)""",
        """CREATE UNIQUE INDEX uq_auto_active_project ON auto_production_runs (user_id, project_name) WHERE status NOT IN ('SUCCEEDED','FAILED','FAILED_QUALITY','CANCELLED')""",
        """CREATE TABLE auto_production_steps (
	command_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	stage VARCHAR(32) NOT NULL, 
	unit_key VARCHAR(255) NOT NULL, 
	generation BIGINT NOT NULL, 
	repair_index INTEGER NOT NULL, 
	input_digest VARCHAR(71) NOT NULL, 
	policy_digest VARCHAR(71) NOT NULL, 
	intent_digest VARCHAR(71) NOT NULL, 
	intent_json TEXT NOT NULL, 
	receipt_json TEXT, 
	PRIMARY KEY (command_id), 
	CONSTRAINT fk_auto_step_run FOREIGN KEY(user_id, project_name, run_id) REFERENCES auto_production_runs (user_id, project_name, run_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_step_scope UNIQUE (user_id, project_name, run_id, command_id), 
	CONSTRAINT uq_auto_step_identity UNIQUE (user_id, project_name, run_id, stage, unit_key, generation, repair_index, input_digest, policy_digest), 
	CONSTRAINT ck_auto_step_versions CHECK (generation >= 1 AND repair_index >= 0), 
	CONSTRAINT ck_auto_intent_json_bytes_sqlite CHECK (length(CAST(intent_json AS BLOB)) <= 1048576), 
	CONSTRAINT ck_auto_receipt_json_bytes_sqlite CHECK (length(CAST(receipt_json AS BLOB)) <= 1048576)
)""",
        """CREATE TABLE auto_production_allocations (
	reservation_id VARCHAR(255) NOT NULL, 
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	command_id VARCHAR(255) NOT NULL, 
	reservation_json TEXT NOT NULL, 
	state VARCHAR(16) NOT NULL, 
	held_cost BIGINT NOT NULL, 
	held_calls BIGINT NOT NULL, 
	held_tasks BIGINT NOT NULL, 
	held_runtime BIGINT NOT NULL, 
	settled_usage_digest VARCHAR(71), 
	PRIMARY KEY (reservation_id), 
	CONSTRAINT fk_auto_allocation_step FOREIGN KEY(user_id, project_name, run_id, command_id) REFERENCES auto_production_steps (user_id, project_name, run_id, command_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_allocation_scope UNIQUE (user_id, project_name, run_id, reservation_id), 
	CONSTRAINT uq_auto_allocation_command UNIQUE (command_id), 
	CONSTRAINT ck_auto_allocation_state CHECK (state IN ('RESERVED','UNKNOWN','SETTLED')), 
	CONSTRAINT ck_auto_allocation_totals CHECK (held_cost >= 0 AND held_calls >= 0 AND held_tasks >= 0 AND held_runtime >= 0), 
	CONSTRAINT ck_auto_reservation_json_bytes_sqlite CHECK (length(CAST(reservation_json AS BLOB)) <= 1048576)
)""",
        """CREATE TABLE auto_production_usage_refs (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	owner VARCHAR(255) NOT NULL, 
	receipt_ref VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	reservation_id VARCHAR(255) NOT NULL, 
	usage_digest VARCHAR(71) NOT NULL, 
	usage_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, owner, receipt_ref), 
	CONSTRAINT fk_auto_usage_allocation FOREIGN KEY(user_id, project_name, run_id, reservation_id) REFERENCES auto_production_allocations (user_id, project_name, run_id, reservation_id) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_usage_json_bytes_sqlite CHECK (length(CAST(usage_json AS BLOB)) <= 1048576)
)""",
    ),
}

_IMMUTABLE = ("auto_production_policies", "auto_production_usage_refs")
_TABLES = (
    "auto_production_usage_refs",
    "auto_production_allocations",
    "auto_production_steps",
    "auto_production_runs",
    "auto_production_policies",
)


def install_immutability(connection: sa.engine.Connection) -> None:
    """Install append-only policy/usage and write-once intent/receipt guards."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_production_immutable_row() RETURNS trigger
            LANGUAGE plpgsql AS $auto$
            BEGIN
                RAISE EXCEPTION 'AUTO_PRODUCTION_IMMUTABLE' USING ERRCODE = '23514';
            END;
            $auto$
        """)
        for table in _IMMUTABLE:
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION auto_production_immutable_row()"
            )
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_production_step_guard() RETURNS trigger
            LANGUAGE plpgsql AS $auto$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'AUTO_PRODUCTION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                IF (to_jsonb(NEW) - 'receipt_json') IS DISTINCT FROM (to_jsonb(OLD) - 'receipt_json')
                   OR (OLD.receipt_json IS NOT NULL AND NEW.receipt_json IS DISTINCT FROM OLD.receipt_json) THEN
                    RAISE EXCEPTION 'AUTO_PRODUCTION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $auto$
        """)
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_production_steps_immutable BEFORE UPDATE OR DELETE ON "
            "auto_production_steps FOR EACH ROW EXECUTE FUNCTION auto_production_step_guard()"
        )
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_production_allocation_guard() RETURNS trigger
            LANGUAGE plpgsql AS $auto$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'AUTO_PRODUCTION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                IF (to_jsonb(NEW) - ARRAY['state','held_cost','held_calls','held_tasks','held_runtime','settled_usage_digest'])
                    IS DISTINCT FROM
                    (to_jsonb(OLD) - ARRAY['state','held_cost','held_calls','held_tasks','held_runtime','settled_usage_digest'])
                   OR (OLD.state = 'SETTLED' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD))
                   OR (OLD.state = 'UNKNOWN' AND NEW.state = 'RESERVED')
                   OR (NEW.state <> 'SETTLED' AND
                       ROW(NEW.held_cost,NEW.held_calls,NEW.held_tasks,NEW.held_runtime,NEW.settled_usage_digest)
                       IS DISTINCT FROM
                       ROW(OLD.held_cost,OLD.held_calls,OLD.held_tasks,OLD.held_runtime,OLD.settled_usage_digest))
                   OR (NEW.state = 'SETTLED' AND NEW.settled_usage_digest IS NULL) THEN
                    RAISE EXCEPTION 'AUTO_PRODUCTION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $auto$
        """)
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_production_allocations_immutable BEFORE UPDATE OR DELETE ON "
            "auto_production_allocations FOR EACH ROW EXECUTE FUNCTION auto_production_allocation_guard()"
        )
    elif connection.dialect.name == "sqlite":
        for table in _IMMUTABLE:
            for event in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_no_{event.lower()}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'AUTO_PRODUCTION_IMMUTABLE'); END"
                )
        for table in ("auto_production_steps", "auto_production_allocations"):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_no_delete" BEFORE DELETE ON "{table}" '
                "BEGIN SELECT RAISE(ABORT, 'AUTO_PRODUCTION_IMMUTABLE'); END"
            )
        protected = (
            "command_id",
            "user_id",
            "project_name",
            "run_id",
            "stage",
            "unit_key",
            "generation",
            "repair_index",
            "input_digest",
            "policy_digest",
            "intent_digest",
            "intent_json",
        )
        condition = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in protected)
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_production_steps_write_once BEFORE UPDATE ON auto_production_steps "
            f"WHEN {condition} OR (OLD.receipt_json IS NOT NULL AND NEW.receipt_json IS NOT OLD.receipt_json) "
            "BEGIN SELECT RAISE(ABORT, 'AUTO_PRODUCTION_IMMUTABLE'); END"
        )
        protected = ("reservation_id", "user_id", "project_name", "run_id", "command_id", "reservation_json")
        condition = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in protected)
        settled = " OR ".join(
            f"NEW.{c} IS NOT OLD.{c}"
            for c in ("state", "held_cost", "held_calls", "held_tasks", "held_runtime", "settled_usage_digest")
        )
        held = " OR ".join(
            f"NEW.{c} IS NOT OLD.{c}"
            for c in ("held_cost", "held_calls", "held_tasks", "held_runtime", "settled_usage_digest")
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_production_allocations_guard BEFORE UPDATE ON auto_production_allocations "
            f"WHEN {condition} OR (OLD.state = 'SETTLED' AND ({settled})) "
            f"OR (OLD.state = 'UNKNOWN' AND NEW.state = 'RESERVED') "
            f"OR (NEW.state <> 'SETTLED' AND ({held})) "
            "OR (NEW.state = 'SETTLED' AND NEW.settled_usage_digest IS NULL) "
            "BEGIN SELECT RAISE(ABORT, 'AUTO_PRODUCTION_IMMUTABLE'); END"
        )


def upgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name
    if dialect not in _SCHEMA_SQL:
        raise RuntimeError("Unsupported autonomous production storage dialect")
    for statement in _SCHEMA_SQL[dialect]:
        connection.exec_driver_sql(statement)
    install_immutability(connection)


def downgrade() -> None:
    connection = op.get_bind()
    for table in _TABLES:
        op.drop_table(table)
    if connection.dialect.name == "postgresql":
        for function in (
            "auto_production_immutable_row",
            "auto_production_step_guard",
            "auto_production_allocation_guard",
        ):
            connection.exec_driver_sql(f'DROP FUNCTION "{function}"()')
