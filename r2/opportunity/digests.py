"""Versioned M9 semantic domains over the accepted M8 canonical JSON implementation."""

from __future__ import annotations

import struct
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts import opportunity as c


def _digest(domain: str, body: object) -> str:
    return digest_canonical({"domain": domain, "schema_version": "1", "body": body})


def _body(value: BaseModel | Mapping[str, object], *, exclude: tuple[str, ...] = ()) -> dict[str, object]:
    result = value.model_dump(mode="python") if isinstance(value, BaseModel) else dict(value)
    return {key: item for key, item in result.items() if key not in exclude}


def _sorted(values: Sequence[object]) -> tuple[object, ...]:
    encoded = [(canonical_json_bytes(value), value) for value in values]
    if len({key for key, _ in encoded}) != len(encoded):
        raise ValueError("closure members must be unique")
    return tuple(value for _, value in sorted(encoded, key=lambda pair: pair[0]))


def digest_profile_publication_subject(subject: c.ProfilePublicationSubject) -> str:
    return _digest("m9.profile-publication-subject.v1", subject)


def digest_creative_content(*, title: str, premise: str, angle: str, audience: object, creator_intent: object) -> str:
    return _digest(
        "m9.creative-content.v1",
        {"title": title, "premise": premise, "angle": angle, "audience": audience, "creator_intent": creator_intent},
    )


def _command_key(operation: str, context: c.CommandContext) -> dict[str, object]:
    return {
        "user_id": context.user_id,
        "actor_id": context.actor_id,
        "operation": operation,
        "command_id": context.command_id,
    }


def digest_command_request(operation: str, context: c.CommandContext, body: object) -> str:
    return _digest(
        "m9.command-request.v1",
        {"key": _command_key(operation, context), "project_name": context.project_name, "command": body},
    )


def command_guard_key(operation: str, context: c.CommandContext) -> tuple[int, int]:
    digest = _digest("m9.command-key-guard.v1", _command_key(operation, context))
    first, second = struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])
    return int(first), int(second)


def digest_command_result(operation: str, request_digest: str, receipt: BaseModel | Mapping[str, object]) -> str:
    return _digest(
        "m9.command-result.v1",
        {
            "operation": operation,
            "request_digest": request_digest,
            "receipt": _body(receipt, exclude=("result_digest",)),
        },
    )


def digest_evidence_closure(
    *,
    user_id: str,
    project_name: str,
    creative_policy: tuple[str, str, str],
    source_rule_digests: Sequence[str],
    snapshots: Sequence[object],
    signals: Sequence[object],
    m8_entries: Sequence[c.M8LearningEvidenceEntry],
) -> str:
    for entry in m8_entries:
        if (
            entry.creative_profile_id,
            entry.creative_profile_version,
            entry.creative_policy_pack_digest,
        ) != creative_policy:
            raise ValueError("M9_COHORT_LEAKAGE")
    return _digest(
        "m9.candidate-evidence-closure.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "creative_policy": creative_policy,
            "source_rule_digests": _sorted(source_rule_digests),
            "snapshots": _sorted(snapshots),
            "signals": _sorted(signals),
            "m8_entries": _sorted(m8_entries),
        },
    )


def _fields(model: BaseModel, names: str) -> dict[str, object]:
    return {name: getattr(model, name) for name in names.split()}


def digest_capability_grant(grant: c.SourceCapabilityGrant) -> str:
    return _digest("m9.capability-grant.v1", _body(grant, exclude=("grant_digest",)))


def digest_capability_evaluation(evaluation: c.EffectiveCapabilityEvaluation, *, actor_id: str) -> str:
    return _digest(
        "m9.capability-evaluation.v1", {**_body(evaluation, exclude=("evaluation_digest",)), "actor_id": actor_id}
    )


def digest_cohort_profile_payload(payload: c.OpportunityCohortProfilePayload) -> str:
    return _digest("m9.cohort-profile-payload.v1", payload)


def digest_cohort_profile(profile: c.OpportunityCohortProfile) -> str:
    return _digest("m9.cohort-profile.v1", _body(profile, exclude=("profile_digest", "payload")))


def digest_source_query(query: c.SourceQuery) -> str:
    return _digest(
        "m9.source-query.v1",
        _body(query, exclude=("query_id", "revision", "parent_revision", "query_digest", "created_by", "created_at")),
    )


def digest_source_snapshot(snapshot: c.SourceSnapshot) -> str:
    return _digest("m9.source-snapshot.v1", _body(snapshot, exclude=("snapshot_digest",)))


def digest_source_observation(observation: c.NormalizedSourceObservation) -> str:
    return _digest(
        "m9.source-observation.v1",
        _body(
            observation, exclude=("observation_id", "revision", "parent_revision", "observation_digest", "observed_at")
        ),
    )


def digest_opportunity_signal(signal: c.DerivedOpportunitySignal) -> str:
    return _digest(
        "m9.opportunity-signal.v1",
        _body(
            signal,
            exclude=("signal_id", "revision", "parent_revision", "signal_digest", "evaluated_by", "evaluated_at"),
        ),
    )


def digest_opportunity_payload(payload: c.OpportunityPayload) -> str:
    return _digest("m9.opportunity-payload.v1", payload)


def digest_greenlight_subject(subject: c.GreenlightSubject) -> str:
    return _digest("m9.greenlight-subject.v1", subject)


def digest_greenlight_binding(decision: c.GreenlightDecision) -> str:
    return _digest(
        "m9.greenlight-binding.v1", _body(decision, exclude=("decision_id", "decision_version", "binding_digest"))
    )


def digest_invalidation_job(job: c.InvalidationJob) -> str:
    return _digest("m9.invalidation-job.v1", _body(job, exclude=("job_digest",)))


def digest_invalidation_subject(subject: c.InvalidationSubject) -> str:
    return _digest("m9.invalidation-subject.v1", subject)


def digest_signal_input_closure(observations_and_correction_heads: Sequence[object]) -> str:
    return _digest("m9.signal-input-closure.v1", _sorted(observations_and_correction_heads))


def digest_policy_basis(grant_evaluation_tuples: Sequence[tuple[str, int, str, str, str]]) -> str:
    return _digest("m9.signal-policy-basis.v1", _sorted(grant_evaluation_tuples))


def digest_assessment_signal_closure(signal_tuples: Sequence[tuple[str, int, str]]) -> str:
    return _digest("m9.assessment-signal-closure.v1", _sorted(signal_tuples))


def digest_condition_evidence(
    *, grant_id: str, grant_version: int, grant_digest: str, condition_evidence: Sequence[c.CanonicalJsonObject]
) -> str:
    return _digest(
        "m9.capability-condition-evidence.v1",
        {
            "grant_id": grant_id,
            "grant_version": grant_version,
            "grant_digest": grant_digest,
            "condition_evidence": tuple(condition_evidence),
        },
    )


def digest_page_cursor(
    *,
    user_id: str,
    project_name: str,
    query_id: str,
    query_revision: int,
    query_digest: str,
    adapter_version: str,
    cursor: object | None,
) -> str | None:
    if cursor is None:
        return None
    return _digest(
        "m9.page-cursor.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "query_id": query_id,
            "query_revision": query_revision,
            "query_digest": query_digest,
            "adapter_version": adapter_version,
            "cursor": cursor,
        },
    )


def digest_system_command_request(
    *, user_id: str, project_name: str, operation: str, command_id: str, command: object
) -> str:
    return _digest(
        "m9.system-command-request.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "operation": operation,
            "command_id": command_id,
            "command": command,
        },
    )


def digest_system_command_result(
    *, user_id: str, project_name: str, operation: str, command_id: str, result: BaseModel | Mapping[str, object]
) -> str:
    return _digest(
        "m9.system-command-result.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "operation": operation,
            "command_id": command_id,
            "result": _body(result, exclude=("result_digest",)),
        },
    )


def digest_cohort_source_evidence(
    *,
    user_id: str,
    project_name: str,
    profile_id: str,
    profile_revision: int,
    profile_digest: str,
    rule: c.CohortSourceRule,
    evidence: c.CohortSourceEvidence,
) -> str:
    return _digest(
        "m9.cohort-source-evidence.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "profile_id": profile_id,
            "profile_revision": profile_revision,
            "profile_digest": profile_digest,
            "rule": rule,
            **_body(evidence, exclude=("result_digest",)),
        },
    )


def digest_opportunity_lineage(candidate: c.OpportunityCandidateRevision) -> str:
    return _digest(
        "m9.opportunity-lineage.v1",
        {
            **_fields(
                candidate,
                "candidate_id revision parent_revision supersedes_candidate_id payload_digest user_id project_name",
            ),
            **_fields(
                candidate.payload,
                "cohort_profile_id cohort_profile_revision cohort_profile_digest evidence_closure_digest",
            ),
        },
    )


def digest_evidence_validity(
    *, user_id: str, project_name: str, identity: str, revision: int, projection: c.EvidenceValidityProjection
) -> str:
    return _digest(
        "m9.evidence-validity-projection.v1",
        {
            "user_id": user_id,
            "project_name": project_name,
            "identity": identity,
            "revision": revision,
            **_body(projection, exclude=("projection_digest",)),
        },
    )


def digest_selected_content(selection: c.ResolvedFactualEvidenceSelection) -> str:
    return _digest("m9.factual-selected-content.v1", _body(selection, exclude=("selected_content_digest",)))


def digest_selection_closure(*, factual_scope: str, selections: Sequence[c.FactualEvidenceSelection]) -> str:
    rows = [
        {name: getattr(selection, name) for name in c.FactualEvidenceSelection.model_fields} for selection in selections
    ]
    return _digest("m9.factual-selection-closure.v1", {"factual_scope": factual_scope, "selections": _sorted(rows)})


def digest_bridge_frozen_request(kind: str, request: c.CanonicalJsonObject) -> str:
    return _digest("m9.bridge-frozen-request.v1", {"kind": kind, "request": request})


def digest_dependency_closure(*, user_id: str, project_name: str, job_id: str, dependencies: Sequence[object]) -> str:
    return _digest(
        "m9.invalidation-dependency-closure.v1",
        {"user_id": user_id, "project_name": project_name, "job_id": job_id, "dependencies": _sorted(dependencies)},
    )


def digest_bridge_closure(*, user_id: str, project_name: str, kind: str, dependencies: c.CanonicalJsonObject) -> str:
    return _digest(
        "m9.bridge-closure.v1",
        {"user_id": user_id, "project_name": project_name, "kind": kind, "dependencies": dependencies},
    )


def digest_m8_learning_closure(*, user_id: str, project_name: str, entries: Sequence[c.M8LearningEvidenceEntry]) -> str:
    return _digest(
        "m9.m8-learning-evidence-closure.v1",
        {"user_id": user_id, "project_name": project_name, "entries": _sorted(entries)},
    )


def digest_freshness_policy(*, profile: c.OpportunityCohortProfile, earliest_expiry: datetime | None) -> str:
    return _digest(
        "m9.greenlight-freshness-policy.v1",
        {
            **_fields(profile, "profile_id revision profile_digest"),
            "freshness_policy": profile.payload.freshness_policy,
            "earliest_expiry": earliest_expiry,
        },
    )
