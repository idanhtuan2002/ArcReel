from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    NarrativeChangeItem,
    NarrativeChangeSet,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.narrative_lifecycle.coverage import (
    ConflictSubject,
    coverage_contains,
    effect_keys_collide,
    minimal_conflict_subject,
    normalize_effect_keys,
    normalize_source_spans,
    spans_overlap,
)
from r2.narrative_lifecycle.errors import NarrativeConflictCoverageError

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _mut(subject: str, descriptor: str = "d", count: int = 1) -> CanonMutationEffectKey:
    return CanonMutationEffectKey(
        canon_subject_kind="FACT", subject_ref=subject, effect_descriptor=descriptor, canon_operation_count=count
    )


def _payoff(thread: str, payoff: str = "p") -> ThreadPayoffEffectKey:
    return ThreadPayoffEffectKey(thread_ref=thread, payoff_ref=payoff)


def _change_set(cs_id: str, spans: list[SourceSpan], keys: list[object]) -> NarrativeChangeSet:
    return NarrativeChangeSet(
        change_set_id=cs_id,
        change_set_lineage_id=f"lin-{cs_id}",
        source_revision_id="rev-1",
        extraction_attempt_id="att-1",
        extraction_generation=0,
        base_canon_version_id="cv-1",
        source_spans=tuple(spans),
        semantic_effect_keys=tuple(keys),
        changes=(NarrativeChangeItem(change_id="ch-1", evidence_span=spans[0], effect_keys=(keys[0],), summary="s"),),
        confidence=0.5,
        extractor_version="x",
        policy_ref="pol",
        policy_version="1",
        created_at=NOW,
        output_fingerprint="of",
    )


def test_normalize_source_spans_is_permutation_stable_and_merges_adjacent() -> None:
    a = SourceSpan(start=10, end=20)
    b = SourceSpan(start=0, end=10)  # adjacent to a
    c = SourceSpan(start=5, end=8)  # inside b
    assert normalize_source_spans([a, b, c]) == normalize_source_spans([c, a, b])
    assert normalize_source_spans([a, b, c]) == (SourceSpan(start=0, end=20),)


def test_normalize_effect_keys_orders_families_and_dedups_under_permutation() -> None:
    keys = [_payoff("t2"), _mut("z"), _mut("a"), _payoff("t1"), _mut("a")]
    out = normalize_effect_keys(keys)
    assert out == normalize_effect_keys(list(reversed(keys)))
    assert [k.kind for k in out] == ["CANON_MUTATION", "CANON_MUTATION", "THREAD_PAYOFF", "THREAD_PAYOFF"]
    assert out[0].subject_ref == "a"


def test_spans_overlap_uses_half_open_semantics() -> None:
    assert spans_overlap(SourceSpan(start=0, end=10), SourceSpan(start=5, end=15))
    assert not spans_overlap(SourceSpan(start=0, end=10), SourceSpan(start=10, end=20))  # touching, not overlapping


@pytest.mark.parametrize("policy", ["EXACT", "SAME_SUBJECT"])
def test_effect_keys_never_collide_across_families(policy: str) -> None:
    assert not effect_keys_collide(_mut("hero"), _payoff("hero"), policy=policy)


def test_effect_keys_collide_on_shared_subject_only_under_the_subject_policy() -> None:
    a = _mut("hero", "trust")
    b = _mut("hero", "fear")
    assert effect_keys_collide(a, b, policy="SAME_SUBJECT")
    assert not effect_keys_collide(a, b, policy="EXACT")
    assert effect_keys_collide(a, a, policy="EXACT")


def test_coverage_contains_requires_full_containment_in_one_declared_span() -> None:
    declared = (SourceSpan(start=0, end=10), SourceSpan(start=20, end=30))
    assert coverage_contains(SourceSpan(start=2, end=8), declared)
    assert not coverage_contains(SourceSpan(start=8, end=12), declared)  # straddles a gap


def test_minimal_conflict_subject_is_the_intersection_not_the_union() -> None:
    key = _mut("hero", "trust")
    left = _change_set("cs-1", [SourceSpan(start=0, end=20)], [key])
    right = _change_set("cs-2", [SourceSpan(start=10, end=40)], [key])
    subject = minimal_conflict_subject([left, right])
    assert subject == minimal_conflict_subject([right, left])  # order-independent
    assert subject.coverage == (SourceSpan(start=10, end=20),)  # narrowed, not 0..40
    assert isinstance(subject, ConflictSubject)


def test_minimal_conflict_subject_rejects_a_non_overlapping_pair() -> None:
    left = _change_set("cs-1", [SourceSpan(start=0, end=5)], [_mut("hero")])
    right = _change_set("cs-2", [SourceSpan(start=90, end=99)], [_mut("villain")])
    with pytest.raises(NarrativeConflictCoverageError):
        minimal_conflict_subject([left, right])
