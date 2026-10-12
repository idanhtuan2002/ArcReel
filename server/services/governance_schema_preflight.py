"""Read-only schema readiness prerequisite for a future Governance startup gate."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

_REQUIRED_TABLES = frozenset({"alembic_version", "r2_showrunner_grant_heads", "r2_showrunner_grant_events"})
_SCRIPT_LOCATION = str(Path(__file__).resolve().parents[2] / "alembic")


class GovernanceSchemaUnavailable(RuntimeError):
    """The database is not ready for a grant recovery scan without migration."""


async def verify_governance_schema_ready(engine: AsyncEngine) -> str:
    """Require the image's exact Alembic head without stamping or upgrading."""

    if engine.dialect.name != "postgresql":
        raise GovernanceSchemaUnavailable("governance schema is unavailable")
    try:
        config = Config()
        config.set_main_option("script_location", _SCRIPT_LOCATION)
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise GovernanceSchemaUnavailable("governance schema is unavailable")
        expected = heads[0]
        async with engine.connect() as connection, connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            tables = await connection.run_sync(lambda sync_connection: set(inspect(sync_connection).get_table_names()))
            if not _REQUIRED_TABLES.issubset(tables):
                raise GovernanceSchemaUnavailable("governance schema is unavailable")
            revisions = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            if revisions != [expected]:
                raise GovernanceSchemaUnavailable("governance schema is unavailable")
        return expected
    except Exception:
        raise GovernanceSchemaUnavailable("governance schema is unavailable") from None


__all__ = ["GovernanceSchemaUnavailable", "verify_governance_schema_ready"]
