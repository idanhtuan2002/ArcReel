"""Alembic migration adding the factual script-lock table and the Final Cut audio decision (ADR-0092)."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from alembic import command

REVISION = "c9e1f4a2b701"
DOWN_REVISION = "b8d4f0e2a300"


def _tables(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    names = set(sa.inspect(engine).get_table_names())
    engine.dispose()
    return names


def _receipt_columns(db_path: Path) -> dict[str, bool]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    columns = {c["name"]: c["nullable"] for c in sa.inspect(engine).get_columns("gate_final_cut_receipts")}
    engine.dispose()
    return columns


def test_upgrade_adds_the_script_lock_table_and_a_nullable_audio_decision(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, REVISION)

    assert "gate_script_lock_decisions" in _tables(db_path)
    assert _receipt_columns(db_path)["audio_decision"] is True


def test_downgrade_removes_both_and_keeps_the_receipt_table(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, DOWN_REVISION)

    assert "gate_script_lock_decisions" not in _tables(db_path)
    assert "audio_decision" not in _receipt_columns(db_path)
    assert "selected_candidate_id" in _receipt_columns(db_path)
