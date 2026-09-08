"""D01–D03 — Director routing authority and the normalized DirectorResult boundary.

These contracts are provider-neutral. Provider/model identity never appears here;
it becomes authoritative only at ``ExecutionDecision`` / ``ProviderRequest``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from .common import NonEmptyStr, R2ContractModel
from .enums import DirectorFailureClass, DirectorKind
from .production import SceneSpec, ShotSpec
from .provenance import Provenance


class RoutingDecision(R2ContractModel):
    routing_decision_id: NonEmptyStr
    routing_policy_version: NonEmptyStr
    input_profile_ref: NonEmptyStr
    policy_selected_director: DirectorKind
    advisory_recommendations: list[DirectorKind] = Field(default_factory=list)
    advisory_reasons: list[NonEmptyStr] = Field(default_factory=list)
    human_override: DirectorKind | None = None
    override_actor: NonEmptyStr | None = None
    override_reason: NonEmptyStr | None = None
    selected_director: DirectorKind
    fallback_enabled: bool
    decided_at: AwareDatetime
    provenance: Provenance


class DirectorSuccess(R2ContractModel):
    result_kind: Literal["SUCCESS"] = "SUCCESS"
    routing_decision_ref: NonEmptyStr
    actual_director: DirectorKind
    scenes: list[SceneSpec] = Field(default_factory=list)
    shots: list[ShotSpec] = Field(default_factory=list)
    diagnostics: list[NonEmptyStr] = Field(default_factory=list)
    validation_summary: NonEmptyStr
    provenance: Provenance


class DirectorFailure(R2ContractModel):
    result_kind: Literal["FAILURE"] = "FAILURE"
    routing_decision_ref: NonEmptyStr
    attempted_director: DirectorKind
    failure_class: DirectorFailureClass
    retryable: bool
    # Normalized classification/evidence only; the authoritative fallback
    # decision stays with the versioned routing/fallback policy.
    fallback_eligible: bool
    error_code: NonEmptyStr
    message: NonEmptyStr
    diagnostic_refs: list[NonEmptyStr] = Field(default_factory=list)
    # A pointer into a diagnostic/quarantine store — never inline specs.
    partial_output_diagnostic_ref: NonEmptyStr | None = None


DirectorResult = Annotated[
    DirectorSuccess | DirectorFailure,
    Field(discriminator="result_kind"),
]
