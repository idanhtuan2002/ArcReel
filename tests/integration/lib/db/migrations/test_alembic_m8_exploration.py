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
        "ck_m8_candidate_heads_current_revision",
        "ck_m8_candidate_heads_head_version",
        "ix_m8_candidate_heads_scope",
    },
    "m8_candidate_revisions": {
        "pk_m8_candidate_revisions",
        "fk_m8_candidate_revisions_candidate",
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
        "uq_m8_promotion_previews_scope",
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

type _ForeignKey = tuple[tuple[str, ...], str, tuple[str, ...], str]


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

    assert script.get_heads() == ["911c4a0e0001"]
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


def _reflected_keys(inspector: sa.Inspector, table: str) -> tuple[list[str], set[_ForeignKey]]:
    foreign = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            str((fk.get("options") or {}).get("ondelete", "NO ACTION")).upper(),
        )
        for fk in inspector.get_foreign_keys(table)
    }
    return list(inspector.get_pk_constraint(table)["constrained_columns"]), foreign


def _declared_keys(table: sa.Table) -> tuple[list[str], set[_ForeignKey]]:
    foreign = {
        (
            tuple(column.name for column in constraint.columns),
            constraint.referred_table.name,
            tuple(element.column.name for element in constraint.elements),
            (constraint.ondelete or "NO ACTION").upper(),
        )
        for constraint in table.foreign_key_constraints
    }
    return [column.name for column in table.primary_key.columns], foreign


def test_keys_are_scoped_match_the_orm_and_never_cascade(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    inspector = sa.inspect(_engine(db_path))
    tables = M8CandidateHeadModel.metadata.tables

    for table in sorted(M8_TABLES):
        primary, foreign = _reflected_keys(inspector, table)
        assert (primary, foreign) == _declared_keys(tables[table]), table
        assert ((("user_id",), "users", ("id",), "RESTRICT")) in foreign, table
        assert all(rule != "CASCADE" for *_, rule in foreign), table
    assert _reflected_keys(inspector, "m8_candidate_heads")[0] == ["user_id", "project_name", "candidate_id"]
    assert _reflected_keys(inspector, "m8_candidate_revisions")[0] == [
        "user_id",
        "project_name",
        "candidate_id",
        "revision",
    ]
    revision_ref = (
        ("user_id", "project_name", "candidate_id", "candidate_revision"),
        "m8_candidate_revisions",
        ("user_id", "project_name", "candidate_id", "revision"),
        "NO ACTION",
    )
    assert revision_ref in _reflected_keys(inspector, "m8_promotion_previews")[1]
    assert revision_ref in _reflected_keys(inspector, "m8_promotion_receipts")[1]
    preview_ref = (
        ("user_id", "project_name", "preview_id"),
        "m8_promotion_previews",
        ("user_id", "project_name", "preview_id"),
        "NO ACTION",
    )
    assert preview_ref in _reflected_keys(inspector, "m8_promotion_authorizations")[1]
    assert preview_ref in _reflected_keys(inspector, "m8_promotion_receipts")[1]


def test_downgrade_removes_only_the_m8_tables(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    before = set(sa.inspect(_engine(db_path)).get_table_names())

    command.downgrade(cfg, "c9e1f4a2b701")
    after = set(sa.inspect(_engine(db_path)).get_table_names())
    command.upgrade(cfg, "head")

    assert before - after == M8_TABLES | {
        "m8_spatial_frame_receipts",
        "m8_spatial_execution_evidence",
        "production_target_heads",
        "production_target_versions",
        "production_target_commands",
        "production_binding_heads",
        "production_binding_versions",
        "production_binding_commands",
        "m8_spatial_pair_heads",
        "m8_spatial_pair_decisions",
        "m8_spatial_pair_commands",
        "r2_showrunner_grant_heads",
        "r2_showrunner_grant_events",
        "m8_spatial_review_sessions",
        "m8_spatial_review_deliveries",
        "m8_spatial_review_acknowledgments",
        "m8_spatial_pair_v2_custody",
    }
    assert set(sa.inspect(_engine(db_path)).get_table_names()) >= M8_TABLES
