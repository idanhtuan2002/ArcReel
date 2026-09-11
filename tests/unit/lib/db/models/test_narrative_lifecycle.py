from __future__ import annotations

from sqlalchemy import Table

from lib.db.base import Base
from lib.db.models.narrative_lifecycle import (
    ChangeSetReviewDecisionModel,
    ChangeSetReviewHeadModel,
    ConflictResolutionDecisionCompetitorModel,
    ConflictResolutionDecisionModel,
    ConflictResolutionHeadModel,
    ConflictResolutionLineageModel,
    NarrativeChangeSetModel,
    NarrativeDecisionIdentityModel,
    NarrativeDraftCandidateModel,
    NarrativeExtractionAttemptModel,
    NarrativeExtractionResultChangeSetModel,
    NarrativeExtractionResultModel,
    NarrativeRevisionModel,
    RevisionAcceptanceDecisionModel,
    RevisionAcceptanceHeadModel,
)

_TABLES = {
    "narrative_draft_candidates",
    "narrative_revisions",
    "narrative_extraction_attempts",
    "narrative_extraction_results",
    "narrative_change_sets",
    "narrative_extraction_result_change_sets",
}

_AUTHORITY_TABLES = {
    "narrative_decision_identities",
    "revision_acceptance_decisions",
    "change_set_review_decisions",
    "conflict_resolution_lineages",
    "conflict_resolution_decisions",
    "conflict_resolution_decision_competitors",
    "revision_acceptance_heads",
    "change_set_review_heads",
    "conflict_resolution_heads",
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


def test_attempt_and_change_set_carry_a_composite_basis_fk_to_the_revision() -> None:
    revision_uniques = _unique_map(_table("narrative_revisions")).values()
    assert {"revision_id", "base_canon_version_id", "plan_version", "scene_contract_version", "context_pack_id"} in (
        revision_uniques
    )
    assert {"revision_id", "base_canon_version_id"} in revision_uniques

    attempt_fk = _fk_by_cols(_table("narrative_extraction_attempts"))[
        ("base_canon_version_id", "context_pack_id", "plan_version", "revision_id", "scene_contract_version")
    ]
    assert {e.target_fullname for e in attempt_fk.elements} == {
        "narrative_revisions.revision_id",
        "narrative_revisions.base_canon_version_id",
        "narrative_revisions.plan_version",
        "narrative_revisions.scene_contract_version",
        "narrative_revisions.context_pack_id",
    }
    assert attempt_fk.ondelete == "RESTRICT"

    cs_fk = _fk_by_cols(_table("narrative_change_sets"))[("base_canon_version_id", "source_revision_id")]
    assert {e.target_fullname for e in cs_fk.elements} == {
        "narrative_revisions.revision_id",
        "narrative_revisions.base_canon_version_id",
    }
    assert cs_fk.ondelete == "RESTRICT"


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


# --- M5C-2 decision authority (identity registry, typed decisions, lineage, heads) ---


def test_all_decision_authority_models_are_registered() -> None:
    for model in (
        NarrativeDecisionIdentityModel,
        RevisionAcceptanceDecisionModel,
        ChangeSetReviewDecisionModel,
        ConflictResolutionLineageModel,
        ConflictResolutionDecisionModel,
        ConflictResolutionDecisionCompetitorModel,
        RevisionAcceptanceHeadModel,
        ChangeSetReviewHeadModel,
        ConflictResolutionHeadModel,
    ):
        assert model.__tablename__ in Base.metadata.tables
    assert set(Base.metadata.tables) >= _AUTHORITY_TABLES


def test_identity_registry_enforces_global_decision_id_and_family_pairing() -> None:
    table = _table("narrative_decision_identities")
    assert {"decision_id", "decision_family"} in _unique_map(table).values()
    checks = {c.name for c in table.constraints if type(c).__name__ == "CheckConstraint"}
    assert "ck_narrative_decision_identities_family" in checks


def test_each_typed_decision_table_has_a_composite_fk_into_the_identity_registry() -> None:
    for name in ("revision_acceptance_decisions", "change_set_review_decisions", "conflict_resolution_decisions"):
        table = _table(name)
        fk = _fk_by_cols(table)[("decision_family", "decision_id")]
        assert {e.target_fullname for e in fk.elements} == {
            "narrative_decision_identities.decision_id",
            "narrative_decision_identities.decision_family",
        }
        assert fk.ondelete == "RESTRICT"
        # the scope-unique target required by other tables' composite FKs into this one
        assert {"user_id", "project_name", "decision_id"} in _unique_map(table).values()


def test_decision_tables_self_reference_expected_predecessors_within_the_same_subject() -> None:
    revision_fks = _fk_by_cols(_table("revision_acceptance_decisions"))
    latest = revision_fks[
        ("canon_branch_id", "expected_latest_decision_id", "plan_id", "project_name", "scene_contract_id", "user_id")
    ]
    assert {e.target_fullname for e in latest.elements} == {
        "revision_acceptance_decisions.decision_id",
        "revision_acceptance_decisions.user_id",
        "revision_acceptance_decisions.project_name",
        "revision_acceptance_decisions.plan_id",
        "revision_acceptance_decisions.scene_contract_id",
        "revision_acceptance_decisions.canon_branch_id",
    }
    assert latest.ondelete == "RESTRICT"

    review_fks = _fk_by_cols(_table("change_set_review_decisions"))
    effective = review_fks[
        ("change_set_lineage_id", "expected_effective_decision_id", "revision_acceptance_decision_id")
    ]
    assert {e.target_fullname for e in effective.elements} == {
        "change_set_review_decisions.decision_id",
        "change_set_review_decisions.revision_acceptance_decision_id",
        "change_set_review_decisions.change_set_lineage_id",
    }
    assert effective.ondelete == "RESTRICT"


def test_conflict_resolution_lineage_subject_is_unique_per_accepted_revision() -> None:
    table = _table("conflict_resolution_lineages")
    assert {c.name for c in table.primary_key} == {"revision_acceptance_decision_id", "conflict_resolution_lineage_id"}
    assert {"revision_acceptance_decision_id", "conflict_subject_fingerprint"} in _unique_map(table).values()


def test_conflict_resolution_decisions_bind_to_their_own_lineage() -> None:
    table = _table("conflict_resolution_decisions")
    fk = _fk_by_cols(table)[("conflict_resolution_lineage_id", "revision_acceptance_decision_id")]
    assert {e.target_fullname for e in fk.elements} == {
        "conflict_resolution_lineages.revision_acceptance_decision_id",
        "conflict_resolution_lineages.conflict_resolution_lineage_id",
    }
    assert fk.ondelete == "RESTRICT"


def test_conflict_resolution_competitors_are_ordered_and_scoped() -> None:
    table = _table("conflict_resolution_decision_competitors")
    assert {c.name for c in table.primary_key} == {"decision_id", "position"}
    checks = {c.name for c in table.constraints if type(c).__name__ == "CheckConstraint"}
    assert "ck_conflict_resolution_decision_competitors_position" in checks
    fks = _fk_by_cols(table)
    assert fks[("change_set_id", "project_name", "user_id")].ondelete == "RESTRICT"
    assert fks[("review_decision_id",)].ondelete == "RESTRICT"


def test_heads_have_null_pointer_zero_generation_checks() -> None:
    for name in ("revision_acceptance_heads", "change_set_review_heads", "conflict_resolution_heads"):
        checks = {c.name for c in _table(name).constraints if type(c).__name__ == "CheckConstraint"}
        assert f"ck_{name}_latest_zero_generation" in checks
        assert f"ck_{name}_effective_zero_generation" in checks
        assert f"ck_{name}_effective_not_ahead" in checks


def test_revision_acceptance_head_key_is_the_full_work_scope() -> None:
    table = _table("revision_acceptance_heads")
    assert {c.name for c in table.primary_key} == {
        "user_id",
        "project_name",
        "plan_id",
        "scene_contract_id",
        "canon_branch_id",
    }


def test_lineage_scoped_heads_are_keyed_by_revision_and_lineage() -> None:
    assert {c.name for c in _table("change_set_review_heads").primary_key} == {
        "revision_acceptance_decision_id",
        "change_set_lineage_id",
    }
    assert {c.name for c in _table("conflict_resolution_heads").primary_key} == {
        "revision_acceptance_decision_id",
        "conflict_resolution_lineage_id",
    }


def test_head_pointers_carry_a_composite_fk_back_to_a_decision_of_the_same_subject() -> None:
    table = _table("revision_acceptance_heads")
    fk = _fk_by_cols(table)[
        ("canon_branch_id", "effective_decision_id", "plan_id", "project_name", "scene_contract_id", "user_id")
    ]
    assert {e.target_fullname for e in fk.elements} == {
        "revision_acceptance_decisions.decision_id",
        "revision_acceptance_decisions.user_id",
        "revision_acceptance_decisions.project_name",
        "revision_acceptance_decisions.plan_id",
        "revision_acceptance_decisions.scene_contract_id",
        "revision_acceptance_decisions.canon_branch_id",
    }
    assert fk.ondelete == "RESTRICT"


def test_no_authority_foreign_key_cascades() -> None:
    for name in _AUTHORITY_TABLES:
        for fk in _table(name).foreign_key_constraints:
            targets = {element.target_fullname for element in fk.elements}
            if targets == {"users.id"}:
                continue
            assert (fk.ondelete or "").upper() == "RESTRICT", (name, fk.name)
