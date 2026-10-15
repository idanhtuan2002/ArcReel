"""Real M6 screenplay admissions for M8 profile-isolated tests (ADR-0105).

``admit_profile`` drives the M6 services through Golden B's
``build_screenplay_admission_command`` and admits the result, so a project carries one effective
``SCREENPLAY_ADMISSION`` head under the exact M6 profile identity. ``revoke_profile`` revokes that
admission with its own command.
The authority double grants every request; production uses the Gate B route and its session
authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.contracts.adaptation import (
    AdaptationDecisionAction,
    AdaptationDecisionAuthorization,
    AdaptationProfileId,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    ScreenplayAdmissionCommand,
)
from tests.fixtures.r2.m6_dual_profile_corpus import build_golden_b_canon, build_screenplay_admission_command

PRINCIPAL = "human:anhtuan"
_PACK_FILES = {
    AdaptationProfileId.WESTERN_GENERIC: "western_generic_v1.json",
    AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: "cn_short_drama_shuangwen_v1.json",
}


class GrantingAuthority:
    async def authorize(self, *, authenticated_principal, action, command_identity_hash):
        return AdaptationDecisionAuthorization(
            authenticated_principal=authenticated_principal,
            authority_role="HUMAN_SHOWRUNNER",
            action=action,
            command_identity_hash=command_identity_hash,
            approval_receipt=f"receipt:{command_identity_hash}",
            authorized_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class AdmittedProfile:
    ref: AdmittedScreenplayRef
    command: ScreenplayAdmissionCommand


def profile_ref(profile_id: AdaptationProfileId) -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / _PACK_FILES[profile_id]).read_bytes())
    return AdaptationProfileRef(
        profile_id=profile_id, profile_version="v1", policy_pack_digest=_compute_policy_pack_digest(raw)
    )


async def admit_profile(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    project_name: str,
    profile_id: AdaptationProfileId,
) -> AdmittedProfile:
    uow_factory = adaptation_uow_factory(session_factory)
    setup = await build_screenplay_admission_command(
        profile_ref(profile_id),
        canon=build_golden_b_canon(),
        uow_factory=uow_factory,
        user_id=user_id,
        project_name=project_name,
        branch_id=f"{project_name}-{profile_id.value.lower()}",
    )
    receipt = await AdaptationAuthorityService(uow_factory, GrantingAuthority()).admit_screenplay_for_direction(
        setup.admit, authenticated_principal=PRINCIPAL
    )
    admitted = setup.admit.admitted_screenplay
    ref = AdmittedScreenplayRef(
        screenplay_ref=ArtifactVersionRef(
            artifact_id=admitted.screenplay_id, version=admitted.version, content_hash=admitted.content_hash
        ),
        admission_ref=receipt.decision_ref,
        profile_ref=setup.admit.profile_ref,
    )
    return AdmittedProfile(ref=ref, command=setup.admit)


async def revoke_profile(session_factory: async_sessionmaker[AsyncSession], admitted: AdmittedProfile) -> None:
    revoke = admitted.command.model_copy(
        update={
            "decision_id": f"{admitted.command.decision_id}-revoke",
            "expected_predecessor_id": admitted.command.decision_id,
            "action": AdaptationDecisionAction.REVOKE,
        }
    )
    await AdaptationAuthorityService(
        adaptation_uow_factory(session_factory), GrantingAuthority()
    ).admit_screenplay_for_direction(revoke, authenticated_principal=PRINCIPAL)
