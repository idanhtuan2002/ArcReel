from __future__ import annotations

from sqlalchemy import Table

from lib.db.base import Base
from lib.db.models.adaptation import (
    AdaptationBranchModel,
    AdaptationMapEntryModel,
    AdaptationMapModel,
    AdaptationMapProfileAnalysisRefModel,
    AdaptationScreenplayModel,
    AdaptationScreenplayProfileAnalysisRefModel,
    AdaptationScreenplaySceneModel,
)

_TABLES = {
    "adaptation_branches",
    "adaptation_maps",
    "adaptation_map_entries",
    "adaptation_map_profile_analysis_refs",
    "adaptation_screenplays",
    "adaptation_screenplay_scenes",
    "adaptation_screenplay_profile_analysis_refs",
}


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _is_unique(constraint: object) -> bool:
    return type(constraint).__name__ == "UniqueConstraint"


def _unique_map(table: Table) -> dict[str, set[str]]:
    return {str(c.name): set(c.columns.keys()) for c in table.constraints if _is_unique(c) and c.name}


def _fk_by_cols(table: Table) -> dict[tuple[str, ...], object]:
    return {tuple(sorted(fk.column_keys)): fk for fk in table.foreign_key_constraints}


def test_all_adaptation_models_are_registered() -> None:
    for model in (
        AdaptationBranchModel,
        AdaptationMapModel,
        AdaptationMapEntryModel,
        AdaptationMapProfileAnalysisRefModel,
        AdaptationScreenplayModel,
        AdaptationScreenplaySceneModel,
        AdaptationScreenplayProfileAnalysisRefModel,
    ):
        assert model.__tablename__ in Base.metadata.tables
    assert set(Base.metadata.tables) >= _TABLES


def test_branch_primary_key_is_id_and_version_composite() -> None:
    table = _table("adaptation_branches")
    assert {c.name for c in table.primary_key.columns} == {"branch_id", "version"}


def test_branch_carries_a_scoped_uniqueness_constraint() -> None:
    table = _table("adaptation_branches")
    assert _unique_map(table)["uq_adaptation_branches_scope"] == {"user_id", "project_name", "branch_id", "version"}


def test_map_primary_key_is_id_and_version_composite() -> None:
    table = _table("adaptation_maps")
    assert {c.name for c in table.primary_key.columns} == {"adaptation_map_id", "version"}


def test_map_references_an_exact_branch_version_with_restrict() -> None:
    fk = _fk_by_cols(_table("adaptation_maps"))[
        ("adaptation_branch_ref_id", "adaptation_branch_ref_version", "project_name", "user_id")
    ]
    assert {e.target_fullname for e in fk.elements} == {
        "adaptation_branches.branch_id",
        "adaptation_branches.version",
        "adaptation_branches.project_name",
        "adaptation_branches.user_id",
    }
    assert fk.ondelete == "RESTRICT"


def test_map_entry_primary_key_includes_map_id_version_and_entry_id() -> None:
    table = _table("adaptation_map_entries")
    assert {c.name for c in table.primary_key.columns} == {
        "adaptation_map_id",
        "adaptation_map_version",
        "entry_id",
    }


def test_map_entry_position_is_unique_within_one_map_version() -> None:
    table = _table("adaptation_map_entries")
    assert _unique_map(table)["uq_adaptation_map_entries_position"] == {
        "adaptation_map_id",
        "adaptation_map_version",
        "position",
    }


def test_map_entry_references_the_exact_map_version_with_restrict() -> None:
    fk = _fk_by_cols(_table("adaptation_map_entries"))[
        ("adaptation_map_id", "adaptation_map_version", "project_name", "user_id")
    ]
    assert {e.target_fullname for e in fk.elements} == {
        "adaptation_maps.adaptation_map_id",
        "adaptation_maps.version",
        "adaptation_maps.project_name",
        "adaptation_maps.user_id",
    }
    assert fk.ondelete == "RESTRICT"


def test_screenplay_primary_key_is_id_and_version_composite() -> None:
    table = _table("adaptation_screenplays")
    assert {c.name for c in table.primary_key.columns} == {"screenplay_id", "version"}


def test_screenplay_references_both_an_exact_branch_and_an_exact_map_version() -> None:
    fks = _fk_by_cols(_table("adaptation_screenplays"))
    branch_fk = fks[("adaptation_branch_ref_id", "adaptation_branch_ref_version", "project_name", "user_id")]
    assert {e.target_fullname for e in branch_fk.elements} == {
        "adaptation_branches.branch_id",
        "adaptation_branches.version",
        "adaptation_branches.project_name",
        "adaptation_branches.user_id",
    }
    map_fk = fks[("adaptation_map_ref_id", "adaptation_map_ref_version", "project_name", "user_id")]
    assert {e.target_fullname for e in map_fk.elements} == {
        "adaptation_maps.adaptation_map_id",
        "adaptation_maps.version",
        "adaptation_maps.project_name",
        "adaptation_maps.user_id",
    }
    assert branch_fk.ondelete == "RESTRICT"
    assert map_fk.ondelete == "RESTRICT"


def test_screenplay_scene_primary_key_includes_screenplay_id_version_and_scene_id() -> None:
    table = _table("adaptation_screenplay_scenes")
    assert {c.name for c in table.primary_key.columns} == {
        "screenplay_id",
        "screenplay_version",
        "scene_id",
    }


def test_screenplay_scene_position_is_unique_within_one_screenplay_version() -> None:
    table = _table("adaptation_screenplay_scenes")
    assert _unique_map(table)["uq_adaptation_screenplay_scenes_position"] == {
        "screenplay_id",
        "screenplay_version",
        "position",
    }
