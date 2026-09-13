from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from r2.contracts.narrative import (
    CANON_SCHEMA_V1,
    AddFactOperation,
    CanonDeltaPayload,
    EpistemicProposition,
    EpistemicState,
    Fact,
    UpdateKnowledgeOperation,
    compute_epistemic_proposition_ref,
)
from r2.contracts.narrative_lifecycle import (
    CompilationSelectedChangeSet,
    ConflictResolutionCommand,
    NarrativeChangeSet,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative_lifecycle.compiler import (
    COMPILER_POLICY_VERSION,
    COMPILER_VERSION,
    RESOLUTION_INSTRUCTION_VERSION,
    CanonDeltaCompiler,
    CanonMutationRule,
    CompilationAbstained,
    CompilationConflict,
    CompilationFailed,
    CompilationNoCanonMutation,
    CompilationOutputIdentity,
    CompilationSucceeded,
    CompilerPolicy,
    ExactCanonBase,
    ReplacementEffectRule,
    ReviewedChangeSet,
)
from tests.factories import (
    make_canon_mutation_effect_key,
    make_compilation_attempt,
    make_conflict_resolution_command,
    make_narrative_change_set,
    make_narrative_revision,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[4]

REVISION = make_narrative_revision()
BASE = ExactCanonBase(canon_branch_id="branch-1", base_canon_version_id="cv-1", content_schema_version=CANON_SCHEMA_V1)


def _fact_operation(fact_id: str, subject: str, predicate: str, value: str) -> AddFactOperation:
    return AddFactOperation(
        operation_id="template",
        target_id=fact_id,
        fact=Fact(fact_id=fact_id, subject_ref=subject, predicate=predicate, value=value),
    )


def _knowledge_operation() -> UpdateKnowledgeOperation:
    proposition = EpistemicProposition(
        proposition_ref=compute_epistemic_proposition_ref(
            subject_ref="hero", predicate="knows", object_or_value="secret"
        ),
        subject_ref="hero",
        predicate="knows",
        object_or_value="secret",
    )
    return UpdateKnowledgeOperation(
        operation_id="template",
        target_id="ks-1",
        subject_entity_id="hero",
        proposition=proposition,
        epistemic_state=EpistemicState.KNOWN,
        effective_from=NOW,
    )


POLICY = CompilerPolicy(
    policy_ref="policy-1",
    policy_version=COMPILER_POLICY_VERSION,
    collision_policy="SAME_SUBJECT",
    mutation_rules=(
        CanonMutationRule(
            canon_subject_kind="FACT",
            subject_ref="hero",
            effect_descriptor="trust",
            operations=(_fact_operation("fact-trust", "hero", "trust", "high"),),
        ),
        CanonMutationRule(
            canon_subject_kind="FACT",
            subject_ref="hero",
            effect_descriptor="mood",
            operations=(_fact_operation("fact-mood", "hero", "mood", "calm"),),
        ),
        CanonMutationRule(
            canon_subject_kind="FACT",
            subject_ref="villain",
            effect_descriptor="fear",
            operations=(_fact_operation("fact-fear", "villain", "fear", "rising"),),
        ),
        CanonMutationRule(
            canon_subject_kind="FACT",
            subject_ref="mentor",
            effect_descriptor="warning",
            operations=(_fact_operation("fact-warning", "mentor", "warning", "spoken"),),
        ),
        CanonMutationRule(
            canon_subject_kind="FACT",
            subject_ref="hero",
            effect_descriptor="two-op-promise",
            operations=(_fact_operation("fact-promise", "hero", "promise", "sworn"),),
        ),
        CanonMutationRule(
            canon_subject_kind="KNOWLEDGE",
            subject_ref="hero",
            effect_descriptor="learns-secret",
            operations=(_knowledge_operation(),),
        ),
    ),
    replacement_rules=(
        ReplacementEffectRule(
            replacement_ref="merged-mood",
            effect_keys=(
                make_canon_mutation_effect_key(canon_subject_kind="FACT", subject_ref="hero", effect_descriptor="mood"),
            ),
        ),
    ),
)

COMPILER = CanonDeltaCompiler()


def _mutation_change_set(
    change_set_id: str,
    *,
    subject_ref: str = "hero",
    effect_descriptor: str = "trust",
    canon_subject_kind: str = "FACT",
    canon_operation_count: int = 1,
    span: tuple[int, int] = (0, 4),
) -> NarrativeChangeSet:
    key = make_canon_mutation_effect_key(
        canon_subject_kind=canon_subject_kind,
        subject_ref=subject_ref,
        effect_descriptor=effect_descriptor,
        canon_operation_count=canon_operation_count,
    )
    return make_narrative_change_set(change_set_id=change_set_id, key=key, span=SourceSpan(start=span[0], end=span[1]))


def _payoff_change_set(change_set_id: str, *, thread_ref: str = "thread-1", span: tuple[int, int] = (0, 4)):
    key = ThreadPayoffEffectKey(thread_ref=thread_ref, payoff_ref="payoff-1")
    return make_narrative_change_set(change_set_id=change_set_id, key=key, span=SourceSpan(start=span[0], end=span[1]))


def _reviewed(change_set: NarrativeChangeSet, review_decision_id: str) -> ReviewedChangeSet:
    return ReviewedChangeSet(change_set=change_set, review_decision_id=review_decision_id)


def _identity(
    reviewed: list[ReviewedChangeSet],
    resolutions: list[ConflictResolutionCommand] | None = None,
    **attempt_overrides: object,
) -> CompilationOutputIdentity:
    arguments: dict[str, object] = {
        "selected_change_sets": tuple(
            CompilationSelectedChangeSet(
                change_set_id=item.change_set.change_set_id, review_decision_id=item.review_decision_id
            )
            for item in reviewed
        ),
        "conflict_resolution_decision_ids": tuple(sorted(item.decision_id for item in (resolutions or []))),
        "compiler_version": COMPILER_VERSION,
        "creative_policy_ref": POLICY.policy_ref,
        "creative_policy_version": POLICY.policy_version,
    }
    arguments.update(attempt_overrides)
    return CompilationOutputIdentity.from_attempt(make_compilation_attempt(**arguments))


def _instruction(kind: str, argument: str) -> str:
    return f"{RESOLUTION_INSTRUCTION_VERSION}:{kind}:{argument}"


def golden_payload_hash() -> str:
    """The payload hash of one fixed SUCCEEDED compilation.

    Called both in-process and from a subprocess under a swept ``PYTHONHASHSEED`` / locale,
    so the determinism sensor and the ordinary tests never drift apart.
    """
    reviewed = [
        _reviewed(_mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4)), "d-2"),
        _reviewed(_mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(10, 14)), "d-3"),
        _reviewed(
            _mutation_change_set("cs-3", subject_ref="mentor", effect_descriptor="warning", span=(20, 24)), "d-4"
        ),
    ]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationSucceeded), result
    return result.canon_delta.payload_hash


def _succeed_two_change_sets() -> tuple[CompilationSucceeded, list[ReviewedChangeSet]]:
    reviewed = [
        _reviewed(_mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4)), "d-2"),
        _reviewed(_mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(10, 14)), "d-3"),
    ]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationSucceeded), result
    return result, reviewed


# --- §9.5 determinism ---------------------------------------------------------


def test_input_permutation_produces_identical_output_and_payload_hash() -> None:
    cs1 = _reviewed(_mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4)), "d-2")
    cs2 = _reviewed(_mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(10, 14)), "d-3")
    identity = _identity([cs1, cs2])
    forward = COMPILER.compile(identity, REVISION, [cs1, cs2], [], BASE, POLICY)
    reversed_ = COMPILER.compile(identity, REVISION, [cs2, cs1], [], BASE, POLICY)
    assert isinstance(forward, CompilationSucceeded)
    assert forward == reversed_


def test_process_hash_seed_and_locale_cannot_influence_the_compiled_payload_hash() -> None:
    script = (
        "import importlib.util,sys;"
        f"spec=importlib.util.spec_from_file_location('m5c_compiler_probe', {str(Path(__file__).resolve())!r});"
        "mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;"
        "spec.loader.exec_module(mod);print(mod.golden_payload_hash())"
    )
    observed = []
    for seed, locale in (("0", "C"), ("524287", "en_US.UTF-8")):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed, "LC_ALL": locale},
            capture_output=True,
            text=True,
            check=True,
        )
        observed.append(completed.stdout.strip())
    assert observed == [golden_payload_hash(), golden_payload_hash()]


def test_operations_are_emitted_in_canonical_effect_key_order() -> None:
    succeeded, _ = _succeed_two_change_sets()
    targets = [operation.target_id for operation in succeeded.canon_delta.operations]
    assert targets == ["fact-trust", "fact-fear"]


def test_non_overlapping_accepted_lineages_coexist_in_one_delta() -> None:
    succeeded, reviewed = _succeed_two_change_sets()
    assert succeeded.canon_delta.source_change_set_refs == ["cs-1", "cs-2"]
    assert {item.change_set.change_set_lineage_id for item in reviewed} == {"lin-cs-1", "lin-cs-2"}


# --- §9.4 CanonDelta construction --------------------------------------------


def test_delta_payload_hash_equals_the_existing_m5a_hash_function_output() -> None:
    succeeded, _ = _succeed_two_change_sets()
    delta = succeeded.canon_delta
    assert delta.payload_hash == compute_canon_delta_hash(delta)


def test_delta_binds_the_branch_base_identity_and_author_decisions_from_the_attempt() -> None:
    succeeded, _ = _succeed_two_change_sets()
    delta = succeeded.canon_delta
    assert delta.target_branch_id == "branch-1"
    assert delta.base_canon_version_id == "cv-1"
    assert delta.canon_delta_id == "delta-1"
    assert delta.created_by == "showrunner-1"
    assert delta.author_decision_refs == ["d-1", "d-2", "d-3"]


def test_source_change_set_refs_and_author_decision_refs_sit_inside_the_hashed_domain() -> None:
    succeeded, _ = _succeed_two_change_sets()
    fields = succeeded.canon_delta.model_dump(mode="json")
    fields.pop("payload_hash")
    without_sources = CanonDeltaPayload.model_validate({**fields, "source_change_set_refs": []})
    without_authors = CanonDeltaPayload.model_validate({**fields, "author_decision_refs": []})
    assert compute_canon_delta_hash(without_sources) != succeeded.canon_delta.payload_hash
    assert compute_canon_delta_hash(without_authors) != succeeded.canon_delta.payload_hash


def test_a_caller_supplied_payload_hash_mismatch_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    identity = _identity(reviewed)
    mismatched = CompilationOutputIdentity(
        attempt=identity.attempt,
        canon_delta_id=identity.canon_delta_id,
        created_at=identity.created_at,
        created_by=identity.created_by,
        expected_payload_hash="sha256:not-the-recomputed-hash",
    )
    result = COMPILER.compile(mismatched, REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["PAYLOAD_HASH_MISMATCH"]


# --- §9.4 / 5.5 outcome-only and unsupported effects --------------------------


def test_outcome_only_selection_returns_no_canon_mutation_not_empty_delta() -> None:
    reviewed = [_reviewed(_payoff_change_set("cs-1"), "d-2")]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationNoCanonMutation)
    assert result.canon_delta is None
    assert [finding.code for finding in result.findings] == ["OUTCOME_ONLY_SELECTION"]


def test_an_unsupported_canon_mutation_effect_abstains_instead_of_converting_by_best_effort() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1", effect_descriptor="not-in-the-policy"), "d-2")]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationAbstained)
    assert [finding.code for finding in result.findings] == ["UNSUPPORTED_CANON_MUTATION_EFFECT"]


def test_a_mutation_key_mixed_with_an_outcome_key_never_degrades_to_no_canon_mutation() -> None:
    reviewed = [
        _reviewed(_mutation_change_set("cs-1", effect_descriptor="unmapped"), "d-2"),
        _reviewed(_payoff_change_set("cs-2", span=(10, 14)), "d-3"),
    ]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert not isinstance(result, CompilationNoCanonMutation)
    assert isinstance(result, CompilationAbstained)


def test_a_rule_that_emits_fewer_operations_than_the_key_promises_abstains() -> None:
    reviewed = [
        _reviewed(_mutation_change_set("cs-1", effect_descriptor="two-op-promise", canon_operation_count=2), "d-2")
    ]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationAbstained)
    assert [finding.code for finding in result.findings] == ["UNDERSPECIFIED_CANON_MUTATION_EFFECT"]


def test_an_operation_kind_illegal_for_the_exact_canon_schema_abstains() -> None:
    reviewed = [
        _reviewed(
            _mutation_change_set("cs-1", canon_subject_kind="KNOWLEDGE", effect_descriptor="learns-secret"), "d-2"
        )
    ]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationAbstained)
    assert [finding.code for finding in result.findings] == ["OPERATION_KIND_ILLEGAL_FOR_CANON_SCHEMA"]


# --- §9.2 version and identity validation -------------------------------------


def test_an_unsupported_policy_version_fails_and_is_never_mislabeled_no_canon_mutation() -> None:
    reviewed = [_reviewed(_payoff_change_set("cs-1"), "d-2")]
    stale_policy = CompilerPolicy(
        policy_ref="policy-1",
        policy_version="r2-m5c-canon-delta-compiler-policy-v0",
        mutation_rules=POLICY.mutation_rules,
    )
    identity = _identity(reviewed, creative_policy_version=stale_policy.policy_version)
    result = COMPILER.compile(identity, REVISION, reviewed, [], BASE, stale_policy)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["UNSUPPORTED_POLICY_VERSION"]


def test_an_unsupported_compiler_version_on_the_attempt_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    result = COMPILER.compile(
        _identity(reviewed, compiler_version="compiler-from-the-future"), REVISION, reviewed, [], BASE, POLICY
    )
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["UNSUPPORTED_COMPILER_VERSION"]


def test_an_unsupported_canon_schema_selector_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    unknown_base = ExactCanonBase(
        canon_branch_id="branch-1", base_canon_version_id="cv-1", content_schema_version="r2-canon-schema-v9"
    )
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], unknown_base, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["UNSUPPORTED_CANON_SCHEMA_VERSION"]


def test_a_revision_outside_the_admitted_attempt_identity_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    foreign = make_narrative_revision(revision_id="rev-other")
    result = COMPILER.compile(_identity(reviewed), foreign, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["REVISION_IDENTITY_MISMATCH"]


def test_a_canon_base_that_disagrees_with_the_attempt_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    drifted = ExactCanonBase(
        canon_branch_id="branch-1", base_canon_version_id="cv-2", content_schema_version=CANON_SCHEMA_V1
    )
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], drifted, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["CANON_BASE_MISMATCH"]


def test_a_canon_branch_that_disagrees_with_the_work_scope_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    other_branch = ExactCanonBase(
        canon_branch_id="branch-9", base_canon_version_id="cv-1", content_schema_version=CANON_SCHEMA_V1
    )
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], other_branch, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["CANON_BRANCH_MISMATCH"]


def test_a_change_set_review_pair_outside_the_admitted_attempt_fails() -> None:
    reviewed = [_reviewed(_mutation_change_set("cs-1"), "d-2")]
    identity = _identity(reviewed)
    smuggled = [*reviewed, _reviewed(_mutation_change_set("cs-9", subject_ref="villain", span=(30, 34)), "d-9")]
    result = COMPILER.compile(identity, REVISION, smuggled, [], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["SELECTION_MISMATCH"]


def test_two_change_sets_from_the_same_lineage_fail_the_lineage_uniqueness_rule() -> None:
    first = _mutation_change_set("cs-1", effect_descriptor="trust")
    second = make_narrative_change_set(
        change_set_id="cs-2",
        change_set_lineage_id="lin-cs-1",
        key=make_canon_mutation_effect_key(subject_ref="villain", effect_descriptor="fear"),
        span=SourceSpan(start=10, end=14),
    )
    reviewed = [_reviewed(first, "d-2"), _reviewed(second, "d-3")]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["DUPLICATE_CHANGE_SET_LINEAGE"]


# --- §9.3 conflict detection and resolution -----------------------------------


def test_overlap_without_resolution_is_conflict() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 10))
    right = _mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(5, 12))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationConflict)
    assert result.canon_delta is None
    assert [finding.code for finding in result.findings] == ["UNRESOLVED_CONFLICT"]


def test_same_subject_effect_key_collision_without_overlapping_spans_is_still_a_conflict() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    result = COMPILER.compile(_identity(reviewed), REVISION, reviewed, [], BASE, POLICY)
    assert isinstance(result, CompilationConflict)
    assert result.findings[0].refs == ("cs-1", "cs-2")


def test_a_keep_resolution_compiles_only_the_kept_change_sets_effects() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationSucceeded)
    assert [operation.target_id for operation in result.canon_delta.operations] == ["fact-trust"]
    assert result.canon_delta.author_decision_refs == ["d-1", "d-2", "d-3"]


def test_a_combine_resolution_keeps_both_typed_effects_when_they_do_not_collide() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 10))
    right = _mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(5, 12))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("COMBINE", "cs-1,cs-2"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationSucceeded)
    assert [operation.target_id for operation in result.canon_delta.operations] == ["fact-trust", "fact-fear"]


def test_a_combine_resolution_over_colliding_typed_effects_stays_a_conflict() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("COMBINE", "cs-1,cs-2"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationConflict)
    assert [finding.code for finding in result.findings] == ["COMBINED_EFFECTS_STILL_COLLIDE"]


def test_a_replace_resolution_substitutes_the_typed_effect_the_policy_supports() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="two-op-promise", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("REPLACE", "merged-mood"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationSucceeded)
    assert [operation.target_id for operation in result.canon_delta.operations] == ["fact-mood"]


def test_a_replacement_reference_the_policy_does_not_support_abstains() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("REPLACE", "invented-by-the-caller"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationAbstained)
    assert [finding.code for finding in result.findings] == ["UNSUPPORTED_REPLACEMENT_EFFECT"]


def test_partial_conflict_resolution_coverage_fails_closed() -> None:
    a = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    b = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    c = _mutation_change_set("cs-3", subject_ref="villain", effect_descriptor="fear", span=(2, 6))
    reviewed = [_reviewed(a, "d-2"), _reviewed(b, "d-3"), _reviewed(c, "d-4")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationConflict)
    assert [finding.refs for finding in result.findings] == [("cs-1", "cs-3")]


def test_two_applicable_resolutions_for_one_conflict_fail_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    first = make_conflict_resolution_command(
        decision_id="d-10",
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    second = make_conflict_resolution_command(
        decision_id="d-11",
        conflict_resolution_lineage_id="lin-conflict-2",
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-2"),
    )
    resolutions = [first, second]
    result = COMPILER.compile(_identity(reviewed, resolutions), REVISION, reviewed, resolutions, BASE, POLICY)
    assert isinstance(result, CompilationConflict)
    assert [finding.code for finding in result.findings] == ["AMBIGUOUS_CONFLICT_RESOLUTION"]


def test_a_resolution_naming_a_change_set_outside_the_selection_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-foreign"),
        competing_review_decision_ids=("d-2", "d-99"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["RESOLUTION_OUTSIDE_SELECTION"]


def test_a_resolution_naming_a_stale_review_decision_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3-superseded"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["RESOLUTION_REVIEW_DECISION_MISMATCH"]


def test_an_unknown_resolution_kind_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("MERGE_SOMEHOW", "cs-1,cs-2"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["UNKNOWN_RESOLUTION_KIND"]


def test_a_free_text_resolution_from_before_the_instruction_grammar_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution="keep cs-1",
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["MALFORMED_RESOLUTION_INSTRUCTION"]


def test_a_resolution_that_matches_no_detected_conflict_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", subject_ref="villain", effect_descriptor="fear", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["INAPPLICABLE_RESOLUTION"]


def test_a_resolution_decision_that_is_not_a_resolve_action_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        action="REJECT",
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    result = COMPILER.compile(_identity(reviewed, [resolution]), REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["NON_RESOLVING_RESOLUTION_ACTION"]


def test_a_resolution_decision_outside_the_admitted_attempt_fails_closed() -> None:
    left = _mutation_change_set("cs-1", effect_descriptor="trust", span=(0, 4))
    right = _mutation_change_set("cs-2", effect_descriptor="mood", span=(50, 54))
    reviewed = [_reviewed(left, "d-2"), _reviewed(right, "d-3")]
    resolution = make_conflict_resolution_command(
        competing_change_set_ids=("cs-1", "cs-2"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=_instruction("KEEP", "cs-1"),
    )
    identity = _identity(reviewed)
    result = COMPILER.compile(identity, REVISION, reviewed, [resolution], BASE, POLICY)
    assert isinstance(result, CompilationFailed)
    assert [finding.code for finding in result.findings] == ["RESOLUTION_SELECTION_MISMATCH"]
