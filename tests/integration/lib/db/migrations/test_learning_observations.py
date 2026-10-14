"""Learning observations keep a scoped restrict-keyed correction chain and one original per identity."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

TABLE = "m8_learning_observations"


def test_observation_migration_has_scoped_chain_keys_and_downgrades_alone(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["914c4a0e0001"]
    assert script.get_revision("914c4a0e0001").down_revision == "913c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    assert inspector.get_pk_constraint(TABLE)["constrained_columns"] == ["user_id", "project_name", "observation_id"]
    foreign = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys(TABLE)
    }
    assert (
        ("user_id", "project_name", "correction_of"),
        TABLE,
        ("user_id", "project_name", "observation_id"),
        "RESTRICT",
    ) in foreign
    assert {
        "uq_m8_learning_observations_command",
        "uq_m8_learning_observations_successor",
        "ck_m8_learning_not_self",
        "ck_m8_learning_window",
        "ck_m8_learning_value_or_reason",
    } <= {item["name"] for item in inspector.get_unique_constraints(TABLE) + inspector.get_check_constraints(TABLE)}
    original = next(
        index for index in inspector.get_indexes(TABLE) if index["name"] == "uq_m8_learning_observations_original"
    )
    assert original["unique"]

    before = set(inspector.get_table_names())
    command.downgrade(cfg, "913c4a0e0001")
    after = set(sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names())
    assert TABLE in before - after
    assert "m8_promotion_receipts" in after
