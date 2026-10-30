"""Persist scoped automatic delegation history and owner authorization receipts."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7a310300002"
down_revision = "b7a310300001"
branch_labels = None
depends_on = None

_SCHEMA_SQL: dict[str, tuple[str, ...]] = {
    "postgresql": (
        """CREATE TABLE auto_grant_events (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	version BIGINT NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	grant_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, version), 
	CONSTRAINT fk_auto_grant_run FOREIGN KEY(user_id, project_name, run_id) REFERENCES auto_production_runs (user_id, project_name, run_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_grant_event_scope UNIQUE (user_id, project_name, run_id, grant_id, version), 
	CONSTRAINT ck_auto_grant_version CHECK (version >= 1), 
	CONSTRAINT ck_auto_grant_grant_json_pg CHECK (octet_length(grant_json) <= 1048576)
)""",
        """CREATE TABLE auto_grant_heads (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	version BIGINT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id), 
	CONSTRAINT fk_auto_grant_head_event FOREIGN KEY(user_id, project_name, run_id, grant_id, version) REFERENCES auto_grant_events (user_id, project_name, run_id, grant_id, version) ON DELETE RESTRICT
)""",
        """CREATE TABLE auto_authorization_decisions (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	command_id VARCHAR(255) NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	grant_version BIGINT NOT NULL, 
	authorization_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, command_id), 
	CONSTRAINT fk_auto_decision_grant FOREIGN KEY(user_id, project_name, run_id, grant_id, grant_version) REFERENCES auto_grant_events (user_id, project_name, run_id, grant_id, version) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_grant_authorization_json_pg CHECK (octet_length(authorization_json) <= 1048576)
)""",
    ),
    "sqlite": (
        """CREATE TABLE auto_grant_events (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	version BIGINT NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	grant_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, version), 
	CONSTRAINT fk_auto_grant_run FOREIGN KEY(user_id, project_name, run_id) REFERENCES auto_production_runs (user_id, project_name, run_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_auto_grant_event_scope UNIQUE (user_id, project_name, run_id, grant_id, version), 
	CONSTRAINT ck_auto_grant_version CHECK (version >= 1), 
	CONSTRAINT ck_auto_grant_grant_json_sqlite CHECK (length(CAST(grant_json AS BLOB)) <= 1048576)
)""",
        """CREATE TABLE auto_grant_heads (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	version BIGINT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id), 
	CONSTRAINT fk_auto_grant_head_event FOREIGN KEY(user_id, project_name, run_id, grant_id, version) REFERENCES auto_grant_events (user_id, project_name, run_id, grant_id, version) ON DELETE RESTRICT
)""",
        """CREATE TABLE auto_authorization_decisions (
	user_id VARCHAR NOT NULL, 
	project_name VARCHAR(255) NOT NULL, 
	run_id VARCHAR(255) NOT NULL, 
	command_id VARCHAR(255) NOT NULL, 
	grant_id VARCHAR(255) NOT NULL, 
	grant_version BIGINT NOT NULL, 
	authorization_json TEXT NOT NULL, 
	PRIMARY KEY (user_id, project_name, run_id, command_id), 
	CONSTRAINT fk_auto_decision_grant FOREIGN KEY(user_id, project_name, run_id, grant_id, grant_version) REFERENCES auto_grant_events (user_id, project_name, run_id, grant_id, version) ON DELETE RESTRICT, 
	CONSTRAINT ck_auto_grant_authorization_json_sqlite CHECK (length(CAST(authorization_json AS BLOB)) <= 1048576)
)""",
    ),
}


def install_immutability(connection: sa.Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_delegation_immutable() RETURNS trigger LANGUAGE plpgsql AS $auto$
            BEGIN
                RAISE EXCEPTION 'AUTOMATION_DELEGATION_IMMUTABLE' USING ERRCODE = '23514';
            END;
            $auto$
        """)
        for table in ("auto_grant_events", "auto_authorization_decisions"):
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION auto_delegation_immutable()"
            )
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION auto_delegation_head_guard() RETURNS trigger LANGUAGE plpgsql AS $auto$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'AUTOMATION_DELEGATION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                IF (to_jsonb(NEW) - 'version') IS DISTINCT FROM (to_jsonb(OLD) - 'version')
                    OR NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'AUTOMATION_DELEGATION_IMMUTABLE' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $auto$
        """)
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_grant_heads_guard BEFORE UPDATE OR DELETE ON auto_grant_heads "
            "FOR EACH ROW EXECUTE FUNCTION auto_delegation_head_guard()"
        )
    elif connection.dialect.name == "sqlite":
        for table in ("auto_grant_events", "auto_authorization_decisions"):
            for event in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER "{table}_no_{event.lower()}" BEFORE {event} ON "{table}" '
                    "BEGIN SELECT RAISE(ABORT, 'AUTOMATION_DELEGATION_IMMUTABLE'); END"
                )
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_grant_heads_no_delete BEFORE DELETE ON auto_grant_heads "
            "BEGIN SELECT RAISE(ABORT, 'AUTOMATION_DELEGATION_IMMUTABLE'); END"
        )
        changed = " OR ".join(
            f"NEW.{column} IS NOT OLD.{column}" for column in ("user_id", "project_name", "run_id", "grant_id")
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER auto_grant_heads_guard BEFORE UPDATE ON auto_grant_heads "
            f"WHEN {changed} OR NEW.version <> OLD.version + 1 "
            "BEGIN SELECT RAISE(ABORT, 'AUTOMATION_DELEGATION_IMMUTABLE'); END"
        )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name not in _SCHEMA_SQL:
        raise RuntimeError("Unsupported automation delegation storage dialect")
    for statement in _SCHEMA_SQL[connection.dialect.name]:
        connection.exec_driver_sql(statement)
    install_immutability(connection)


def downgrade() -> None:
    for table in ("auto_authorization_decisions", "auto_grant_heads", "auto_grant_events"):
        op.drop_table(table)
    if op.get_bind().dialect.name == "postgresql":
        for function in ("auto_delegation_immutable", "auto_delegation_head_guard"):
            op.get_bind().exec_driver_sql(f'DROP FUNCTION "{function}"()')
