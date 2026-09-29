"""The M8 exploration migration matches the ORM and the fixed persistence map (plan Task A2.1)."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.advanced_creative import M8CandidateHeadModel

M8_TABLES = {
    "m8_candidate_heads",
    "m8_candidate_revisions",
    "m8_command_receipts",
    "m8_promotion_previews",
    "m8_promotion_authorizations",
    "m8_promotion_receipts",
}
EXPECTED_NAMES = {
    "m8_candidate_heads": {
        "pk_m8_candidate_heads",
        "uq_m8_candidate_heads_scope",
        "ck_m8_candidate_heads_current_revision",
        "ck_m8_candidate_heads_head_version",
        "ix_m8_candidate_heads_scope",
    },
    "m8_candidate_revisions": {
        "pk_m8_candidate_revisions",
        "fk_m8_candidate_revisions_candidate",
        "uq_m8_candidate_revisions_scope",
        "ck_m8_candidate_revisions_kind",
        "ck_m8_candidate_revisions_revision",
        "ck_m8_candidate_revisions_parent",
    },
    "m8_command_receipts": {"pk_m8_command_receipts", "ck_m8_command_receipts_operation"},
    "m8_promotion_previews": {
        "pk_m8_promotion_previews",
        "uq_m8_promotion_previews_command",
        "fk_m8_promotion_previews_revision",
        "ck_m8_promotion_previews_target_version",
        "ck_m8_promotion_previews_ttl",
        "ck_m8_promotion_previews_master_coupling",
        "ix_m8_promotion_previews_expiry",
    },
    "m8_promotion_authorizations": {
        "pk_m8_promotion_authorizations",
        "uq_m8_promotion_authorizations_digest",
        "fk_m8_promotion_authorizations_preview",
        "ck_m8_promotion_authorizations_decision",
    },
    "m8_promotion_receipts": {
        "pk_m8_promotion_receipts",
        "uq_m8_promotion_receipts_command",
        "fk_m8_promotion_receipts_preview",
        "fk_m8_promotion_receipts_revision",
        "fk_m8_promotion_receipts_authorization",
        "ck_m8_promotion_receipts_master_coupling",
    },
}


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _names(inspector: sa.Inspector, table: str) -> set[str]:
    found: list[str | None] = [inspector.get_pk_constraint(table).get("name")]
    found += [fk.get("name") for fk in inspector.get_foreign_keys(table)]
    found += [uq.get("name") for uq in inspector.get_unique_constraints(table)]
    found += [ck.get("name") for ck in inspector.get_check_constraints(table)]
    found += [ix.get("name") for ix in inspector.get_indexes(table)]
    return {name for name in found if name}


def _column_shape(column: dict[str, object]) -> tuple[str, bool]:
    return (str(column["type"]).upper(), bool(column["nullable"]))


def test_one_head_and_the_exact_parent(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)

    assert script.get_heads() == ["8a8c4a0e0001"]
    assert script.get_revision("8a8c4a0e0001").down_revision == "c9e1f4a2b701"


def test_the_six_tables_have_the_named_constraints_and_match_the_orm(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    inspector = sa.inspect(_engine(db_path))

    assert set(inspector.get_table_names()) >= M8_TABLES
    for table in sorted(M8_TABLES):
        assert EXPECTED_NAMES[table] <= _names(inspector, table), table
        reflected = {column["name"]: _column_shape(dict(column)) for column in inspector.get_columns(table)}
        declared = {
            column.name: (str(column.type.compile(dialect=_engine(db_path).dialect)).upper(), column.nullable)
            for column in M8CandidateHeadModel.metadata.tables[table].columns
        }
        assert reflected == declared, table


def test_downgrade_removes_only_the_m8_tables(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    before = set(sa.inspect(_engine(db_path)).get_table_names())

    command.downgrade(cfg, "c9e1f4a2b701")
    after = set(sa.inspect(_engine(db_path)).get_table_names())
    command.upgrade(cfg, "head")

    assert before - after == M8_TABLES
    assert set(sa.inspect(_engine(db_path)).get_table_names()) >= M8_TABLES
