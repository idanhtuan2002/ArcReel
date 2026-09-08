from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from itertools import pairwise

from r2.contracts import (
    CanonContent,
    CanonDelta,
    CanonValidationFinding,
    CanonValidationReport,
    EpistemicProposition,
    EpistemicState,
    Fact,
    KnowledgeState,
    NarrativeValidationFinding,
    NarrativeValidationReport,
    NarrativeValidationSeverity,
    RetireFactOperation,
    UpdateKnowledgeOperation,
    canonical_json_bytes,
    ensure_json_value,
)

from .canon_state import ResolvedCanonView
from .temporal import TemporalGraph, TemporalOrder, validate_relations

RULES = (
    "M5A_REFERENCE_MISSING",
    "M5A_EVENT_CAUSAL_SELF_REFERENCE",
    "M5A_FACT_INTERVAL_INVALID",
    "M5A_FACT_RETIREMENT_INVALID",
    "M5A_FACT_ACTIVE_COLLISION",
)
_RULE_ORDER = {rule_id: index for index, rule_id in enumerate(RULES)}


def intervals_overlap(
    left_from: datetime | None,
    left_until: datetime | None,
    right_from: datetime | None,
    right_until: datetime | None,
) -> bool:
    """Half-open ``[from, until)`` overlap with null infinities; equal adjacent endpoints do not overlap."""
    return _starts_before(left_from, right_until) and _starts_before(right_from, left_until)


def _starts_before(start: datetime | None, end: datetime | None) -> bool:
    if start is None or end is None:
        return True
    return start < end


def _finding(rule_id: str, affected_refs: tuple[str, ...], message: str) -> CanonValidationFinding:
    return CanonValidationFinding(rule_id=rule_id, affected_refs=affected_refs, message=message)


def _reference_missing(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    entity_ids = set(candidate.entities_by_id)
    event_ids = set(candidate.events_by_id)
    for fact in sorted(candidate.facts_by_id.values(), key=lambda item: item.fact_id):
        if fact.subject_ref not in entity_ids:
            yield _finding(
                "M5A_REFERENCE_MISSING",
                (fact.fact_id, fact.subject_ref),
                f"fact {fact.fact_id} references unknown subject entity {fact.subject_ref}",
            )
        for event_ref in fact.source_event_refs:
            if event_ref not in event_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (fact.fact_id, event_ref),
                    f"fact {fact.fact_id} references unknown source event {event_ref}",
                )
    for event in sorted(candidate.events_by_id.values(), key=lambda item: item.event_id):
        for participant in event.participant_refs:
            if participant not in entity_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (event.event_id, participant),
                    f"event {event.event_id} references unknown participant entity {participant}",
                )
        if event.location_ref is not None and event.location_ref not in entity_ids:
            yield _finding(
                "M5A_REFERENCE_MISSING",
                (event.event_id, event.location_ref),
                f"event {event.event_id} references unknown location entity {event.location_ref}",
            )
        for causal_ref in event.causal_refs:
            if causal_ref not in event_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (event.event_id, causal_ref),
                    f"event {event.event_id} references unknown causal event {causal_ref}",
                )


def _event_causal_self_reference(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    for event in sorted(candidate.events_by_id.values(), key=lambda item: item.event_id):
        if event.event_id in event.causal_refs:
            yield _finding(
                "M5A_EVENT_CAUSAL_SELF_REFERENCE",
                (event.event_id,),
                f"event {event.event_id} causally references itself",
            )


def _fact_interval_invalid(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    # Every final fact interval must have an ordered start/end when both exist,
    # regardless of which operation produced it (ADD_FACT, RETIRE_FACT, ...).
    for fact in sorted(candidate.facts_by_id.values(), key=lambda item: item.fact_id):
        if _interval_is_inverted(fact):
            yield _finding(
                "M5A_FACT_INTERVAL_INVALID",
                (fact.fact_id,),
                f"fact {fact.fact_id} effective_until is not after effective_from",
            )


def _fact_retirement_invalid(base: CanonContent, delta: CanonDelta) -> Iterator[CanonValidationFinding]:
    for op in delta.operations:
        if not isinstance(op, RetireFactOperation):
            continue
        base_fact = base.facts_by_id.get(op.target_id)
        if base_fact is None:
            yield _finding(
                "M5A_FACT_RETIREMENT_INVALID",
                (op.target_id,),
                f"fact {op.target_id} is not present in the resolved base and cannot be retired",
            )
            continue
        if base_fact.effective_until is not None:
            yield _finding(
                "M5A_FACT_RETIREMENT_INVALID",
                (op.target_id,),
                f"fact {op.target_id} is already retired in the resolved base",
            )
            continue
        if base_fact.effective_from is not None and op.effective_until <= base_fact.effective_from:
            yield _finding(
                "M5A_FACT_RETIREMENT_INVALID",
                (op.target_id,),
                f"retirement time for fact {op.target_id} is not after its effective_from",
            )


def _fact_active_collision(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    facts = list(candidate.facts_by_id.values())
    for index, left in enumerate(facts):
        for right in facts[index + 1 :]:
            if (left.subject_ref, left.predicate) != (right.subject_ref, right.predicate):
                continue
            if left.value == right.value:
                continue
            if intervals_overlap(
                left.effective_from, left.effective_until, right.effective_from, right.effective_until
            ):
                yield _finding(
                    "M5A_FACT_ACTIVE_COLLISION",
                    (left.fact_id, right.fact_id),
                    (
                        f"facts {left.fact_id} and {right.fact_id} assign different values to "
                        f"({left.subject_ref}, {left.predicate}) over overlapping intervals"
                    ),
                )


def _interval_is_inverted(fact: Fact) -> bool:
    return (
        fact.effective_from is not None
        and fact.effective_until is not None
        and fact.effective_until <= fact.effective_from
    )


def validate_canon_candidate(
    *, base: CanonContent, delta: CanonDelta, candidate: CanonContent
) -> CanonValidationReport:
    """M5A compatibility entry point: only the ``M5A_*`` structural rules, M5A ordering."""
    findings: list[CanonValidationFinding] = [
        *_reference_missing(candidate),
        *_event_causal_self_reference(candidate),
        *_fact_interval_invalid(candidate),
        *_fact_retirement_invalid(base, delta),
        *_fact_active_collision(candidate),
    ]
    findings.sort(key=lambda item: (_RULE_ORDER[item.rule_id], item.affected_refs))
    return CanonValidationReport(findings=tuple(findings))


# --- M5B: deterministic temporal/epistemic invariant validation --------------------

_ERROR = NarrativeValidationSeverity.ERROR


def _mb_finding(
    rule_id: str,
    affected_refs: tuple[str, ...],
    message: str,
    *,
    story_time: datetime | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> NarrativeValidationFinding:
    return NarrativeValidationFinding(
        rule_id=rule_id,
        severity=_ERROR,
        affected_refs=affected_refs,
        story_time=story_time,
        message=message,
        evidence_refs=evidence_refs,
    )


def _canonical_value(value: object) -> bytes:
    return canonical_json_bytes(ensure_json_value(value))


def _point_in(fact_from: datetime | None, fact_until: datetime | None, at: datetime) -> bool:
    return (fact_from is None or fact_from <= at) and (fact_until is None or at < fact_until)


def _covers_interval(
    state_from: datetime,
    state_until: datetime | None,
    covering: list[tuple[datetime | None, datetime | None]],
) -> bool:
    boundaries: set[datetime] = {state_from}
    if state_until is not None:
        boundaries.add(state_until)
    for cover_from, cover_until in covering:
        if cover_from is not None:
            boundaries.add(cover_from)
        if cover_until is not None:
            boundaries.add(cover_until)
    points = sorted(boundaries)
    for start, end in pairwise(points):
        if end <= state_from:
            continue
        if state_until is not None and start >= state_until:
            continue
        midpoint = start + (end - start) / 2
        if not any(_point_in(cover_from, cover_until, midpoint) for cover_from, cover_until in covering):
            return False
    if state_until is None:
        tail = points[-1]
        if not any(
            (cover_from is None or cover_from <= tail) and cover_until is None for cover_from, cover_until in covering
        ):
            return False
    return True


def _truth_coverage_finding(state: KnowledgeState, relevant_facts: list[Fact]) -> NarrativeValidationFinding | None:
    if state.epistemic_state not in (EpistemicState.KNOWN, EpistemicState.FALSE_BELIEF):
        return None
    if state.epistemic_state is EpistemicState.FALSE_BELIEF and not relevant_facts:
        return _mb_finding(
            "EPI_TRUTH_CONTRADICTION_UNPROVEN",
            (state.knowledge_state_id, state.proposition_ref),
            f"FALSE_BELIEF {state.knowledge_state_id} has no contradicting Canon fact",
            story_time=state.effective_from,
        )
    covering = [(fact.effective_from, fact.effective_until) for fact in relevant_facts]
    if not _covers_interval(state.effective_from, state.effective_until, covering):
        return _mb_finding(
            "EPI_TRUTH_INCOMPLETE_COVERAGE",
            (state.knowledge_state_id, state.proposition_ref),
            f"{state.epistemic_state.value} {state.knowledge_state_id} is not covered over its whole interval",
            story_time=state.effective_from,
        )
    return None


def validate_knowledge_interval(*, state: KnowledgeState, supporting_facts: list[Fact]) -> NarrativeValidationReport:
    """Classify one KnowledgeState's truth over its complete half-open interval.

    ``supporting_facts`` are the caller-selected relevant facts: those asserting the
    proposition for ``KNOWN``, or same subject/predicate with a different value for
    ``FALSE_BELIEF``.
    """
    finding = _truth_coverage_finding(state, supporting_facts)
    return NarrativeValidationReport(findings=(finding,) if finding is not None else ())


def _relevant_facts(proposition: EpistemicProposition, facts: Iterable[Fact], *, contradicting: bool) -> list[Fact]:
    target_value = _canonical_value(proposition.object_or_value)
    selected: list[Fact] = []
    for fact in facts:
        if (fact.subject_ref, fact.predicate) != (proposition.subject_ref, proposition.predicate):
            continue
        same_value = _canonical_value(fact.value) == target_value
        if same_value != contradicting:
            selected.append(fact)
    return selected


def _provably_later(graph: TemporalGraph, anchors: dict[str, datetime], event_ref: str, at: datetime) -> bool:
    direct = anchors.get(event_ref)
    if direct is not None and direct > at:
        return True
    for other_ref, other_anchor in anchors.items():
        if other_ref == event_ref:
            continue
        if other_anchor > at and graph.compare(event_ref, other_ref) is TemporalOrder.SIMULTANEOUS:
            return True
        if other_anchor >= at and graph.compare(other_ref, event_ref) is TemporalOrder.BEFORE:
            return True
    return False


class NarrativeInvariantValidator:
    """Deep pure validator over immutable ``base`` / ``delta`` / ``candidate`` values."""

    def validate_canon(
        self, *, base: ResolvedCanonView, delta: CanonDelta, candidate: ResolvedCanonView
    ) -> NarrativeValidationReport:
        findings: list[NarrativeValidationFinding] = [
            _mb_finding(m5a_finding.rule_id, m5a_finding.affected_refs, m5a_finding.message)
            for m5a_finding in (
                *_reference_missing(candidate.content),
                *_event_causal_self_reference(candidate.content),
                *_fact_interval_invalid(candidate.content),
                *_fact_retirement_invalid(base.content, delta),
                *_fact_active_collision(candidate.content),
            )
        ]
        findings.extend(
            _mb_finding(
                temporal_finding.rule_id,
                temporal_finding.affected_refs,
                temporal_finding.message,
                evidence_refs=temporal_finding.evidence_path,
            )
            for temporal_finding in validate_relations(
                candidate.content.temporal_relations_by_id.values(),
                events=candidate.content.events_by_id,
            ).findings
        )
        findings.extend(self._epistemic_findings(base=base, delta=delta, candidate=candidate))

        findings.sort(
            key=lambda finding: (
                finding.severity.value,
                finding.rule_id,
                finding.affected_refs,
                "" if finding.story_time is None else finding.story_time.isoformat(),
            )
        )
        return NarrativeValidationReport(findings=tuple(findings))

    def _epistemic_findings(
        self, *, base: ResolvedCanonView, delta: CanonDelta, candidate: ResolvedCanonView
    ) -> list[NarrativeValidationFinding]:
        content = candidate.content
        findings: list[NarrativeValidationFinding] = []
        facts = list(content.facts_by_id.values())
        graph = TemporalGraph.from_canon(content)
        anchors = {
            event.event_id: event.temporal_anchor
            for event in content.events_by_id.values()
            if event.temporal_anchor is not None
        }

        for state in sorted(content.knowledge_states_by_id.values(), key=lambda item: item.knowledge_state_id):
            proposition = content.epistemic_propositions_by_ref.get(state.proposition_ref)
            if proposition is None:
                findings.append(
                    _mb_finding(
                        "EPI_IDENTITY_PROPOSITION_MISSING",
                        (state.knowledge_state_id, state.proposition_ref),
                        f"knowledge state {state.knowledge_state_id} references an unknown proposition",
                        story_time=state.effective_from,
                    )
                )
                continue
            contradicting = state.epistemic_state is EpistemicState.FALSE_BELIEF
            relevant = _relevant_facts(proposition, facts, contradicting=contradicting)
            coverage = _truth_coverage_finding(state, relevant)
            if coverage is not None:
                findings.append(coverage)

        for event in content.events_by_id.values():
            for state_ref in event.state_effect_refs:
                state = content.knowledge_states_by_id.get(state_ref)
                if state is None:
                    continue
                if event.event_id not in state.evidence_event_refs:
                    findings.append(
                        _mb_finding(
                            "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK",
                            (event.event_id, state_ref),
                            f"event {event.event_id} names knowledge state {state_ref} which does not name it back",
                        )
                    )

        for operation in delta.operations:
            if not isinstance(operation, UpdateKnowledgeOperation):
                continue
            findings.extend(self._evidence_findings(operation, delta=delta, graph=graph, anchors=anchors))
        return findings

    def _evidence_findings(
        self,
        operation: UpdateKnowledgeOperation,
        *,
        delta: CanonDelta,
        graph: TemporalGraph,
        anchors: dict[str, datetime],
    ) -> list[NarrativeValidationFinding]:
        findings: list[NarrativeValidationFinding] = []
        refs = (operation.operation_id, operation.target_id)
        has_evidence = bool(operation.evidence_event_refs)
        has_bootstrap = operation.bootstrap_author_decision_ref is not None

        if operation.epistemic_state in (EpistemicState.KNOWN, EpistemicState.FALSE_BELIEF):
            if has_evidence and has_bootstrap:
                findings.append(
                    _mb_finding(
                        "EPI_EVIDENCE_BOOTSTRAP_AND_EVENT",
                        refs,
                        f"{operation.epistemic_state.value} transition {operation.target_id} carries both "
                        "event evidence and a bootstrap decision",
                        story_time=operation.effective_from,
                    )
                )
            elif not has_evidence and not has_bootstrap:
                findings.append(
                    _mb_finding(
                        "EPI_EVIDENCE_MISSING",
                        refs,
                        f"{operation.epistemic_state.value} transition {operation.target_id} has no evidence "
                        "event and no bootstrap decision",
                        story_time=operation.effective_from,
                    )
                )
        elif operation.epistemic_state is EpistemicState.SUSPECTED:
            if has_bootstrap:
                findings.append(
                    _mb_finding(
                        "EPI_EVIDENCE_BOOTSTRAP_FORBIDDEN",
                        refs,
                        f"SUSPECTED transition {operation.target_id} may not carry a bootstrap decision",
                        story_time=operation.effective_from,
                    )
                )
            if not has_evidence:
                findings.append(
                    _mb_finding(
                        "EPI_EVIDENCE_SUSPECTED_NEEDS_EVENT",
                        refs,
                        f"SUSPECTED transition {operation.target_id} requires at least one evidence event",
                        story_time=operation.effective_from,
                    )
                )
        elif operation.epistemic_state is EpistemicState.UNKNOWN and has_bootstrap:
            findings.append(
                _mb_finding(
                    "EPI_EVIDENCE_BOOTSTRAP_FORBIDDEN",
                    refs,
                    f"UNKNOWN transition {operation.target_id} may not carry a bootstrap decision",
                    story_time=operation.effective_from,
                )
            )

        bootstrap_ref = operation.bootstrap_author_decision_ref
        if bootstrap_ref is not None and bootstrap_ref not in delta.author_decision_refs:
            findings.append(
                _mb_finding(
                    "EPI_EVIDENCE_BOOTSTRAP_UNBOUND",
                    refs,
                    f"bootstrap decision {bootstrap_ref!r} is not listed in the delta author_decision_refs",
                    story_time=operation.effective_from,
                    evidence_refs=(bootstrap_ref,),
                )
            )

        findings.extend(
            _mb_finding(
                "EPI_EVIDENCE_FUTURE",
                refs,
                f"evidence event {event_ref} is provably later than the transition instant",
                story_time=operation.effective_from,
                evidence_refs=(event_ref,),
            )
            for event_ref in operation.evidence_event_refs
            if _provably_later(graph, anchors, event_ref, operation.effective_from)
        )
        return findings
