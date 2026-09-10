from __future__ import annotations

from sqlalchemy import Table

from lib.db.base import Base
from lib.db.models.narrative_lifecycle import (
    NarrativeChangeSetModel,
    NarrativeDraftCandidateModel,
    NarrativeExtractionAttemptModel,
    NarrativeExtractionResultChangeSetModel,
    NarrativeExtractionResultModel,
    NarrativeRevisionModel,
)

_TABLES = {
    "narrative_draft_candidates",
    "narrative_revisions",
    "narrative_extraction_attempts",
    "narrative_extraction_results",
    "narrative_change_sets",
    "narrative_extraction_result_change_sets",
}


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _is_unique(constraint: object) -> bool:
    return type(constraint).__name__ == "UniqueConstraint"


def _unique_map(table: Table) -> dict[str, set[str]]:
    return {str(c.name): set(c.columns.keys()) for c in table.constraints if _is_unique(c) and c.name}


def _fk_by_cols(table: Table) -> dict[tuple[str, ...], object]:
    return {tuple(sorted(fk.column_keys)): fk for fk in table.foreign_key_constraints}


def test_all_evidence_models_are_registered() -> None:
    for model in (
        NarrativeDraftCandidateModel,
        NarrativeRevisionModel,
        NarrativeExtractionAttemptModel,
        NarrativeExtractionResultModel,
        NarrativeChangeSetModel,
        NarrativeExtractionResultChangeSetModel,
    ):
        assert model.__tablename__ in Base.metadata.tables
    assert set(Base.metadata.tables) >= _TABLES


def test_attempt_has_unique_generation_key_for_the_result_foreign_key() -> None:
    table = _table("narrative_extraction_attempts")
    assert {"attempt_id", "generation"} in _unique_map(table).values()


def test_one_result_per_attempt_generation() -> None:
    table = _table("narrative_extraction_results")
    uniques = _unique_map(table).values()
    assert {"attempt_id", "generation"} in uniques
    fk = _fk_by_cols(table)[("attempt_id", "generation")]
    targets = {element.target_fullname for element in fk.elements}
    assert targets == {
        "narrative_extraction_attempts.attempt_id",
        "narrative_extraction_attempts.generation",
    }
    assert fk.ondelete == "RESTRICT"


def test_revision_links_use_composite_scope_foreign_keys_with_restrict() -> None:
    table = _table("narrative_revisions")
    fks = _fk_by_cols(table)
    base_fk = fks[("base_candidate_id", "project_name", "user_id")]
    assert {e.target_fullname for e in base_fk.elements} == {
        "narrative_draft_candidates.user_id",
        "narrative_draft_candidates.project_name",
        "narrative_draft_candidates.candidate_id",
    }
    assert base_fk.ondelete == "RESTRICT"
    predecessor_fk = fks[("predecessor_revision_id", "project_name", "user_id")]
    assert predecessor_fk.ondelete == "RESTRICT"
    assert table.columns["predecessor_revision_id"].nullable is True


def test_no_evidence_foreign_key_cascades() -> None:
    for name in _TABLES:
        for fk in _table(name).foreign_key_constraints:
            targets = {element.target_fullname for element in fk.elements}
            if targets == {"users.id"}:
                continue  # user ownership follows the repo-wide CASCADE convention
            assert (fk.ondelete or "").upper() == "RESTRICT", (name, fk.name)


def test_association_table_is_ordered_and_scoped() -> None:
    table = _table("narrative_extraction_result_change_sets")
    assert {c.name for c in table.primary_key} == {"result_id", "change_set_id"}
    assert {"result_id", "position"} in _unique_map(table).values()
    checks = {c.name for c in table.constraints if type(c).__name__ == "CheckConstraint"}
    assert "ck_narrative_extraction_result_change_sets_position" in checks


def test_generation_and_version_columns_are_range_checked() -> None:
    attempts = {
        c.name for c in _table("narrative_extraction_attempts").constraints if type(c).__name__ == "CheckConstraint"
    }
    assert "ck_narrative_extraction_attempts_generation" in attempts
    candidates = {
        c.name for c in _table("narrative_draft_candidates").constraints if type(c).__name__ == "CheckConstraint"
    }
    assert "ck_narrative_draft_candidates_plan_version" in candidates
