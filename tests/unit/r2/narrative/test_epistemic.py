from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    CanonContent,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Event,
    KnowledgeState,
    compute_epistemic_proposition_ref,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.epistemic import EpistemicView, EpistemicViewResolver, compute_proposition_ref
from r2.narrative.errors import EpistemicIntegrityError
from r2.narrative.hashing import compute_canon_content_hash

AT_09 = datetime(2026, 3, 1, 9, tzinfo=UTC)
AT_10 = datetime(2026, 3, 1, 10, tzinfo=UTC)
AT_12 = datetime(2026, 3, 1, 12, tzinfo=UTC)
AT_14 = datetime(2026, 3, 1, 14, tzinfo=UTC)


def prop(subject: str, predicate: str, value: object) -> EpistemicProposition:
    return EpistemicProposition(
        proposition_ref=compute_epistemic_proposition_ref(
            subject_ref=subject, predicate=predicate, object_or_value=value
        ),
        subject_ref=subject,
        predicate=predicate,
        object_or_value=value,
    )


def knowledge(
    ks_id: str,
    subject: str,
    proposition: EpistemicProposition,
    state: EpistemicState,
    frm: datetime,
    until: datetime | None = None,
    evidence: Iterable[str] = (),
) -> KnowledgeState:
    return KnowledgeState(
        knowledge_state_id=ks_id,
        subject_entity_id=subject,
        proposition_ref=proposition.proposition_ref,
        epistemic_state=state,
        effective_from=frm,
        effective_until=until,
        evidence_event_refs=list(evidence),
    )


def v2_content(
    *,
    propositions: Iterable[EpistemicProposition] = (),
    knowledge_states: Iterable[KnowledgeState] = (),
    events: Iterable[Event] = (),
) -> CanonContent:
    return CanonContent(
        entities_by_id={"char-a": Entity(entity_id="char-a", entity_type=EntityType.CHARACTER, canonical_name="A")},
        facts_by_id={},
        events_by_id={event.event_id: event for event in events},
        epistemic_propositions_by_ref={item.proposition_ref: item for item in propositions},
        knowledge_states_by_id={item.knowledge_state_id: item for item in knowledge_states},
    )


def resolved(content: CanonContent, *, version_id: str = "v-1") -> ResolvedCanonView:
    return ResolvedCanonView(
        canon_version_id=version_id,
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def test_compute_proposition_ref_is_content_addressed_and_matches_the_contract() -> None:
    proposition = prop("ring", "owner", "char-b")
    assert compute_proposition_ref(proposition) == proposition.proposition_ref
    assert compute_proposition_ref(proposition).startswith("ep:")
    assert compute_proposition_ref(prop("ring", "owner", "char-c")) != proposition.proposition_ref


def test_epistemic_proposition_rejects_a_ref_that_does_not_match_its_content() -> None:
    with pytest.raises(ValidationError):
        EpistemicProposition(
            proposition_ref=prop("ring", "owner", "char-b").proposition_ref,
            subject_ref="ring",
            predicate="owner",
            object_or_value="char-c",
        )


def test_resolver_omits_a_proposition_with_no_active_state() -> None:
    p = prop("ring", "owner", "char-b")
    view = EpistemicViewResolver().resolve(
        canon=resolved(
            v2_content(
                propositions=[p],
                knowledge_states=[knowledge("k-1", "char-a", p, EpistemicState.KNOWN, AT_10, AT_12)],
            )
        ),
        subject_entity_id="char-a",
        at=AT_14,
    )
    assert view.known == ()
    assert view.suspected == ()


def test_resolver_selects_the_single_active_state_and_keeps_its_source_id() -> None:
    p = prop("ring", "owner", "char-b")
    view = EpistemicViewResolver().resolve(
        canon=resolved(
            v2_content(
                propositions=[p],
                knowledge_states=[knowledge("k-1", "char-a", p, EpistemicState.SUSPECTED, AT_10, evidence=["ev-1"])],
            )
        ),
        subject_entity_id="char-a",
        at=AT_12,
    )
    assert [item.knowledge_state_id for item in view.suspected] == ["k-1"]
    assert view.suspected[0].proposition == p
    assert view.evidence_event_refs == ("ev-1",)


def test_resolver_raises_instead_of_picking_a_latest_corrupt_overlap() -> None:
    p = prop("ring", "owner", "char-b")
    corrupt = v2_content(
        propositions=[p],
        knowledge_states=[
            knowledge("k-1", "char-a", p, EpistemicState.KNOWN, AT_09),
            knowledge("k-2", "char-a", p, EpistemicState.FALSE_BELIEF, AT_10),
        ],
    )
    with pytest.raises(EpistemicIntegrityError):
        EpistemicViewResolver().resolve(canon=resolved(corrupt), subject_entity_id="char-a", at=AT_12)


def test_resolver_half_open_boundary_excludes_the_end_instant() -> None:
    p = prop("ring", "owner", "char-b")
    resolver = EpistemicViewResolver()
    canon = resolved(
        v2_content(
            propositions=[p],
            knowledge_states=[knowledge("k-1", "char-a", p, EpistemicState.KNOWN, AT_10, AT_12)],
        )
    )
    assert [
        item.knowledge_state_id for item in resolver.resolve(canon=canon, subject_entity_id="char-a", at=AT_10).known
    ] == ["k-1"]
    assert resolver.resolve(canon=canon, subject_entity_id="char-a", at=AT_12).known == ()


def test_resolver_sorts_items_by_proposition_ref_and_unions_evidence() -> None:
    p1 = prop("ring", "owner", "char-b")
    p2 = prop("crown", "location", "vault")
    canon = resolved(
        v2_content(
            propositions=[p1, p2],
            knowledge_states=[
                knowledge("k-1", "char-a", p1, EpistemicState.KNOWN, AT_10, evidence=["ev-2"]),
                knowledge("k-2", "char-a", p2, EpistemicState.KNOWN, AT_10, evidence=["ev-1"]),
            ],
        )
    )
    view = EpistemicViewResolver().resolve(canon=canon, subject_entity_id="char-a", at=AT_12)
    assert [item.proposition.proposition_ref for item in view.known] == sorted([p1.proposition_ref, p2.proposition_ref])
    assert view.evidence_event_refs == ("ev-1", "ev-2")


def test_resolver_view_hash_is_deterministic_for_equal_inputs() -> None:
    p = prop("ring", "owner", "char-b")
    resolver = EpistemicViewResolver()
    canon = resolved(
        v2_content(
            propositions=[p],
            knowledge_states=[knowledge("k-1", "char-a", p, EpistemicState.KNOWN, AT_10)],
        )
    )
    first = resolver.resolve(canon=canon, subject_entity_id="char-a", at=AT_12)
    second = resolver.resolve(canon=canon, subject_entity_id="char-a", at=AT_12)
    assert isinstance(first, EpistemicView)
    assert first.view_hash == second.view_hash
    third = resolver.resolve(canon=canon, subject_entity_id="char-a", at=AT_14)
    assert third.view_hash != first.view_hash


def test_resolver_raises_when_a_state_references_an_unknown_proposition() -> None:
    p = prop("ring", "owner", "char-b")
    orphan = v2_content(knowledge_states=[knowledge("k-1", "char-a", p, EpistemicState.KNOWN, AT_10)])
    with pytest.raises(EpistemicIntegrityError):
        EpistemicViewResolver().resolve(canon=resolved(orphan), subject_entity_id="char-a", at=AT_12)
