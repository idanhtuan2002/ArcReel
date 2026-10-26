"""Closed M10-A digest projections over immutable evidence data.

Cache verification checks embedded bodies only. External evidence, qualification,
custodian authority, candidate projection and currentness require their owning runtime.
"""

from __future__ import annotations

from types import MappingProxyType

from pydantic import BaseModel, TypeAdapter

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts import quality as q
from r2.contracts.advanced_creative import CanonicalJsonObject
from r2.contracts.content_basis import ContentBasis

DIGEST_DOMAINS = (
    "m10.quality-policy.v1",
    "m10.quality-profile-draft.v1",
    "m10.quality-profile.v1",
    "m10.artifact-metadata.v1",
    "m10.master-binding.v1",
    "m10.content-basis.v1",
    "m10.assessed-subject.v1",
    "m10.technical-observation.v1",
    "m10.factual-observation.v1",
    "m10.narrative-observation.v1",
    "m10.continuity-observation.v1",
    "m10.perceptual-regression-observation.v1",
    "m10.perceptual-review-observation.v1",
    "m10.accessibility-observation.v1",
    "m10.observation-closure.v1",
    "m10.assessment-requirements.v1",
    "m10.quality-run.v1",
    "m10.waiver-binding.v1",
    "m10.quality-disposition.v1",
    "m10.profile-publication-subject.v1",
    "m10.disposition-subject.v1",
    "m10.profile-publication-request.v1",
    "m10.run-completion-request.v1",
    "m10.disposition-request.v1",
    "m10.command-key-guard.v1",
)

_MODELS = MappingProxyType(
    {
        "m10.quality-policy.v1": q.QualityPolicyV1,
        "m10.quality-profile-draft.v1": q.QualityProfileDraft,
        "m10.quality-profile.v1": q.QualityProfileRevision,
        "m10.artifact-metadata.v1": q.ArtifactMetadataSnapshot,
        "m10.master-binding.v1": q.MasterBindingV1,
        "m10.assessed-subject.v1": q.AssessedSubject,
        "m10.technical-observation.v1": q.TechnicalObservation,
        "m10.factual-observation.v1": q.FactualObservation,
        "m10.narrative-observation.v1": q.NarrativeObservation,
        "m10.continuity-observation.v1": q.ContinuityObservation,
        "m10.perceptual-regression-observation.v1": q.PerceptualRegressionObservation,
        "m10.perceptual-review-observation.v1": q.PerceptualReviewObservation,
        "m10.accessibility-observation.v1": q.AccessibilityObservation,
        "m10.quality-run.v1": q.QualityRun,
        "m10.waiver-binding.v1": q.WaiverBinding,
        "m10.quality-disposition.v1": q.QualityDisposition,
        "m10.profile-publication-subject.v1": q.ProfilePublicationSubject,
        "m10.disposition-subject.v1": q.DispositionSubject,
        "m10.profile-publication-request.v1": q.ProfilePublicationAuthorizationRequest,
        "m10.run-completion-request.v1": q.CompleteRunCommand,
        "m10.disposition-request.v1": q.DispositionAuthorizationRequest,
        "m10.command-key-guard.v1": q.CommandEnvelope,
    }
)
_OWN_CACHES = MappingProxyType(
    {"m10.quality-profile.v1": "profile_digest", "m10.artifact-metadata.v1": "metadata_digest"}
)
_REQUESTS = MappingProxyType(
    {
        "m10.profile-publication-request.v1": q.ProfilePublicationAuthorizationRequest,
        "m10.run-completion-request.v1": q.CompleteRunCommand,
        "m10.disposition-request.v1": q.DispositionAuthorizationRequest,
    }
)


def _body(domain: str, value: object) -> object:
    if domain not in DIGEST_DOMAINS:
        raise ValueError("unregistered M10-A digest domain")
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    if domain == "m10.observation-closure.v1":
        observations = TypeAdapter(tuple[q.ObservationBinding, ...]).validate_python(raw)
        return q.RunCompletionSubject.observation_order(observations)
    if domain == "m10.assessment-requirements.v1":
        requirements = TypeAdapter(tuple[q.AssessmentRequirement, ...]).validate_python(raw)
        return q.validate_requirements(requirements)
    if domain == "m10.content-basis.v1":
        immutable = CanonicalJsonObject.model_validate(raw)
        material = immutable.model_dump(mode="json")
        temporary = ContentBasis.model_validate(material)
        if canonical_json_bytes(material) != canonical_json_bytes(temporary.model_dump(mode="json")):
            raise ValueError("content basis must be fully normalized")
        return immutable
    model = _MODELS[domain].model_validate(raw)
    if domain in _REQUESTS:
        request = model.model_dump(mode="python")
        return {
            "command": {key: request["command"][key] for key in ("user_id", "project_name", "actor_id", "operation")},
            "subject": request["subject"],
        }
    if domain == "m10.command-key-guard.v1":
        command = model.model_dump(mode="python")
        return {key: command[key] for key in ("user_id", "project_name", "actor_id", "operation", "command_id")}
    own = _OWN_CACHES.get(domain)
    return model.model_dump(mode="python", exclude={own} if own else set())


def compute_digest(domain: str, value: object) -> str:
    """Validate/normalize a registered body and hash its exact domain/version envelope."""
    return digest_canonical({"domain": domain, "contract_version": "1", "body": _body(domain, value)})


def verify_digest(domain: str, value: object, expected: str) -> None:
    if compute_digest(domain, value) != expected:
        raise ValueError("quality digest mismatch")


def _embedded_caches(value: q.M10ContractModel) -> None:
    if isinstance(value, q.ArtifactMetadataSnapshot):
        verify_digest("m10.artifact-metadata.v1", value, value.metadata_digest)
    if isinstance(value, (q.QualityProfileDraft, q.QualityProfileRevision)):
        verify_digest("m10.quality-policy.v1", value.policy, value.policy_digest)
    if isinstance(value, q.QualityProfileRevision):
        verify_digest("m10.quality-profile.v1", value, value.profile_digest)
    if isinstance(value, q.AssessedSubject):
        verify_digest("m10.master-binding.v1", value.master_binding, value.master_binding_digest)
        root = next(
            s
            for s in value.master_binding.metadata_snapshots
            if s.artifact_key == value.master_binding.root.artifact_key
        )
        verify_digest(
            "m10.content-basis.v1", root.body.model_dump(mode="python")["content_basis"], value.content_basis_digest
        )
    if isinstance(value, q.ProfilePublicationSubject):
        verify_digest("m10.quality-profile-draft.v1", value.profile_draft, value.profile_draft_digest)
    if isinstance(value, (q.RunCompletionSubject, q.QualityRun)):
        verify_digest("m10.assessed-subject.v1", value.subject, value.subject_digest)
    if isinstance(value, q.RunCompletionSubject):
        verify_digest("m10.observation-closure.v1", value.observations, value.observation_closure_digest)
    for domain, model in _REQUESTS.items():
        if isinstance(value, model):
            verify_digest(domain, value, value.command.request_digest)


def _walk(value: object) -> None:
    if isinstance(value, q.M10ContractModel):
        _embedded_caches(value)
        for _, child in value:
            _walk(child)
    elif isinstance(value, tuple):
        for child in value:
            _walk(child)


def verify_caches(value: object) -> None:
    """Revalidate shape and every available embedded cache; never resolve foreign authority."""
    if not isinstance(value, q.M10ContractModel):
        raise ValueError("quality contract required")
    normalized = type(value).model_validate(value.model_dump(mode="python"))
    _walk(normalized)


__all__ = ["DIGEST_DOMAINS", "compute_digest", "verify_caches", "verify_digest"]
