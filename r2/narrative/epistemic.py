"""Proposition identity and the fail-closed epistemic view resolver.

The resolver never selects a "latest" row to hide a corrupt overlap: zero active
KnowledgeStates means the proposition is absent from the view, exactly one is
selected, and more than one raises ``EpistemicIntegrityError``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import ConfigDict

from r2.contracts import (
    EpistemicProposition,
    EpistemicState,
    KnowledgeState,
    canonical_json_bytes,
    compute_epistemic_proposition_ref,
    ensure_json_value,
)
from r2.contracts.common import NonEmptyStr, R2ContractModel

from .canon_state import ResolvedCanonView
from .errors import EpistemicIntegrityError

_VIEW_HASH_SCHEMA = "r2-epistemic-view-v1"
_BUCKET_BY_STATE: dict[EpistemicState, str] = {
    EpistemicState.KNOWN: "known",
    EpistemicState.SUSPECTED: "suspected",
    EpistemicState.FALSE_BELIEF: "false_beliefs",
    EpistemicState.UNKNOWN: "explicit_unknown",
}


def compute_proposition_ref(proposition: EpistemicProposition) -> str:
    """Recompute a proposition's content-addressed reference from its semantic fields."""
    return compute_epistemic_proposition_ref(
        subject_ref=proposition.subject_ref,
        predicate=proposition.predicate,
        object_or_value=proposition.object_or_value,
    )


class EpistemicViewItem(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    knowledge_state_id: NonEmptyStr
    proposition: EpistemicProposition
    effective_from: datetime
    effective_until: datetime | None
    evidence_event_refs: tuple[NonEmptyStr, ...]


class EpistemicView(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    canon_version_id: NonEmptyStr | None
    subject_entity_id: NonEmptyStr
    story_time: datetime
    known: tuple[EpistemicViewItem, ...]
    suspected: tuple[EpistemicViewItem, ...]
    false_beliefs: tuple[EpistemicViewItem, ...]
    explicit_unknown: tuple[EpistemicViewItem, ...]
    evidence_event_refs: tuple[NonEmptyStr, ...]
    view_hash: NonEmptyStr


def _is_active(state: KnowledgeState, at: datetime) -> bool:
    return state.effective_from <= at and (state.effective_until is None or at < state.effective_until)


class EpistemicViewResolver:
    def resolve(self, *, canon: ResolvedCanonView, subject_entity_id: str, at: datetime) -> EpistemicView:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("story time must be timezone-aware")

        states_by_proposition: dict[str, list[KnowledgeState]] = {}
        for state in canon.content.knowledge_states_by_id.values():
            if state.subject_entity_id != subject_entity_id:
                continue
            states_by_proposition.setdefault(state.proposition_ref, []).append(state)

        buckets: dict[str, list[EpistemicViewItem]] = {name: [] for name in _BUCKET_BY_STATE.values()}
        evidence: set[str] = set()
        for proposition_ref in sorted(states_by_proposition):
            active = [state for state in states_by_proposition[proposition_ref] if _is_active(state, at)]
            if not active:
                continue
            if len(active) > 1:
                raise EpistemicIntegrityError(
                    f"{len(active)} active knowledge states for subject {subject_entity_id!r} "
                    f"and proposition {proposition_ref!r} at {at.isoformat()}"
                )
            state = active[0]
            proposition = canon.content.epistemic_propositions_by_ref.get(proposition_ref)
            if proposition is None:
                raise EpistemicIntegrityError(
                    f"knowledge state {state.knowledge_state_id!r} references unknown proposition {proposition_ref!r}"
                )
            buckets[_BUCKET_BY_STATE[state.epistemic_state]].append(
                EpistemicViewItem(
                    knowledge_state_id=state.knowledge_state_id,
                    proposition=proposition,
                    effective_from=state.effective_from,
                    effective_until=state.effective_until,
                    evidence_event_refs=tuple(state.evidence_event_refs),
                )
            )
            evidence.update(state.evidence_event_refs)

        evidence_event_refs = tuple(sorted(evidence))
        return EpistemicView(
            canon_version_id=canon.canon_version_id,
            subject_entity_id=subject_entity_id,
            story_time=at,
            known=tuple(buckets["known"]),
            suspected=tuple(buckets["suspected"]),
            false_beliefs=tuple(buckets["false_beliefs"]),
            explicit_unknown=tuple(buckets["explicit_unknown"]),
            evidence_event_refs=evidence_event_refs,
            view_hash=_view_hash(
                canon_version_id=canon.canon_version_id,
                subject_entity_id=subject_entity_id,
                at=at,
                buckets=buckets,
                evidence_event_refs=evidence_event_refs,
            ),
        )


def _view_hash(
    *,
    canon_version_id: str | None,
    subject_entity_id: str,
    at: datetime,
    buckets: dict[str, list[EpistemicViewItem]],
    evidence_event_refs: tuple[str, ...],
) -> str:
    payload = {
        "schema": _VIEW_HASH_SCHEMA,
        "canon_version_id": canon_version_id,
        "subject_entity_id": subject_entity_id,
        "story_time": at.isoformat(),
        "evidence_event_refs": list(evidence_event_refs),
        "items": {
            name: [
                {
                    "knowledge_state_id": item.knowledge_state_id,
                    "proposition_ref": item.proposition.proposition_ref,
                    "effective_from": item.effective_from.isoformat(),
                    "effective_until": None if item.effective_until is None else item.effective_until.isoformat(),
                    "evidence_event_refs": list(item.evidence_event_refs),
                }
                for item in items
            ]
            for name, items in buckets.items()
        },
    }
    return "ev:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()
