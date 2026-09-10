"""Pure source-span and semantic-effect-key coverage rules.

One normalized coordinate system, one canonical sort order, deterministic adjacent-span
merge. No import of ``lib.db``, ``server``, providers, clocks, or randomness. These
helpers describe overlap and containment; they never resolve a conflict or write a head.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import ConfigDict

from r2.contracts.common import R2ContractModel
from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    NarrativeChangeSet,
    NarrativeSemanticEffectKey,
    SourceSpan,
)
from r2.narrative_lifecycle.errors import NarrativeConflictCoverageError

EffectKeyCollisionPolicy = Literal["EXACT", "SAME_SUBJECT"]


class ConflictSubject(R2ContractModel):
    """The minimal canonical intersection of competing reviewed change sets: the spans
    every competitor covers and the Canon / thread subjects every competitor touches."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    coverage: tuple[SourceSpan, ...]
    effect_key_subjects: tuple[str, ...]


def _effect_key_sort_key(key: NarrativeSemanticEffectKey) -> tuple[object, ...]:
    if isinstance(key, CanonMutationEffectKey):
        return (0, key.canon_subject_kind, key.subject_ref, key.effect_descriptor, key.canon_operation_count)
    return (1, key.thread_ref, key.payoff_ref)


def _effect_key_subject(key: NarrativeSemanticEffectKey) -> str:
    """The normalized subject a key touches — the Canon atom or the thread — without the
    finer effect descriptor. Two mutations on the same Canon subject share this subject
    even when they propose different descriptors or values."""
    if isinstance(key, CanonMutationEffectKey):
        return f"canon:{key.canon_subject_kind}:{key.subject_ref}"
    return f"thread:{key.thread_ref}"


def _effect_key_family(key: NarrativeSemanticEffectKey) -> str:
    return key.kind


def normalize_source_spans(spans: Iterable[SourceSpan]) -> tuple[SourceSpan, ...]:
    """Canonical, disjoint, ascending spans. Overlapping or adjacent spans merge."""
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: list[SourceSpan] = []
    for span in ordered:
        if merged and span.start <= merged[-1].end:
            last = merged[-1]
            if span.end > last.end:
                merged[-1] = SourceSpan(start=last.start, end=span.end)
        else:
            merged.append(span)
    return tuple(merged)


def normalize_effect_keys(keys: Iterable[NarrativeSemanticEffectKey]) -> tuple[NarrativeSemanticEffectKey, ...]:
    """Canonical ordering across both key families, with exact duplicates removed:
    every ``CanonMutationEffectKey`` before every ``ThreadPayoffEffectKey``."""
    ordered = sorted(keys, key=_effect_key_sort_key)
    deduped: list[NarrativeSemanticEffectKey] = []
    for key in ordered:
        if not deduped or deduped[-1] != key:
            deduped.append(key)
    return tuple(deduped)


def spans_overlap(a: SourceSpan, b: SourceSpan) -> bool:
    """True when the half-open intervals share at least one position."""
    return a.start < b.end and b.start < a.end


def effect_keys_collide(
    a: NarrativeSemanticEffectKey, b: NarrativeSemanticEffectKey, *, policy: EffectKeyCollisionPolicy
) -> bool:
    """A ``CanonMutationEffectKey`` and a ``ThreadPayoffEffectKey`` never collide across
    families. Within a family, ``EXACT`` compares the whole key; ``SAME_SUBJECT`` compares
    only the normalized Canon / thread subject."""
    if _effect_key_family(a) != _effect_key_family(b):
        return False
    if policy == "EXACT":
        return a == b
    return _effect_key_subject(a) == _effect_key_subject(b)


def coverage_contains(change_evidence_span: SourceSpan, declared_coverage: Iterable[SourceSpan]) -> bool:
    """True only when the change's evidence span is fully contained by a single declared
    coverage span (after normalization). A span that straddles a coverage gap fails."""
    return any(
        cov.start <= change_evidence_span.start and change_evidence_span.end <= cov.end
        for cov in normalize_source_spans(declared_coverage)
    )


def _intersect_span_lists(xs: tuple[SourceSpan, ...], ys: tuple[SourceSpan, ...]) -> tuple[SourceSpan, ...]:
    out: list[SourceSpan] = []
    for x in xs:
        for y in ys:
            lo = max(x.start, y.start)
            hi = min(x.end, y.end)
            if hi > lo:
                out.append(SourceSpan(start=lo, end=hi))
    return normalize_source_spans(out)


def minimal_conflict_subject(change_sets: Iterable[NarrativeChangeSet]) -> ConflictSubject:
    """The minimal canonical intersection of the competing reviewed change sets: the span
    coverage and effect-key subjects that *every* competitor shares. It is order-
    independent and never widens beyond the true intersection. A pair with no shared
    coverage and no shared subject raises ``NarrativeConflictCoverageError``."""
    materialized = list(change_sets)
    if len(materialized) < 2:
        raise NarrativeConflictCoverageError("a conflict subject needs at least two competing change sets")

    coverage = normalize_source_spans(materialized[0].source_spans)
    subjects: set[str] = {_effect_key_subject(k) for k in materialized[0].semantic_effect_keys}
    for change_set in materialized[1:]:
        coverage = _intersect_span_lists(coverage, normalize_source_spans(change_set.source_spans))
        subjects &= {_effect_key_subject(k) for k in change_set.semantic_effect_keys}

    if not coverage and not subjects:
        raise NarrativeConflictCoverageError("competing change sets share no coverage span or effect-key subject")
    return ConflictSubject(coverage=coverage, effect_key_subjects=tuple(sorted(subjects)))
