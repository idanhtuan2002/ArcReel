"""Governance schema readiness is checked without Alembic writes."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantHeadModel
from server.services.governance_schema_preflight import GovernanceSchemaUnavailable, verify_governance_schema_ready


def _head() -> str:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[4] / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert isinstance(head, str)
    return head


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["ready", "missing_version", "stale_version", "missing_grant_table"])
async def test_pg_schema_preflight_requires_exact_head_without_mutation(
    session_factory: async_sessionmaker[AsyncSession], state: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL read-only transaction")
    head = _head()
    if state != "missing_version":
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": head if state != "stale_version" else "8f8c4a0e0001"},
            )
            if state == "missing_grant_table":
                await conn.execute(text("DROP TABLE r2_showrunner_grant_heads CASCADE"))
    async with session_factory() as session:
        users_before = await session.scalar(text("SELECT count(*) FROM users"))
    if state == "ready":
        assert await verify_governance_schema_ready(engine) == head
    else:
        with pytest.raises(GovernanceSchemaUnavailable):
            await verify_governance_schema_ready(engine)
    async with session_factory() as session:
        assert await session.scalar(text("SELECT count(*) FROM users")) == users_before
        if state != "missing_version":
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
                head if state != "stale_version" else "8f8c4a0e0001"
            )
        if state != "missing_grant_table":
            assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 0


@pytest.mark.asyncio
async def test_sqlite_schema_preflight_denies(db_engine: AsyncEngine) -> None:
    with pytest.raises(GovernanceSchemaUnavailable):
        await verify_governance_schema_ready(db_engine)
