from __future__ import annotations

import pytest
import sqlalchemy as sa

from lib.db.models.host_hardening import MasterHeadVersionModel, PromotionReceiptModel
from r2.automation.authorization import automation_principal
from r2.contracts.automation import AutomationOperation
from server.services.r2_shot_approval import R2ShotApprovalRefused, R2ShotCut
from tests.integration.server.production_run.test_master_authority import master_owner_run as master_owner_run
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_automation_grants import subject_for

TASK_ID = "shot-task-1"


@pytest.fixture
def sealed_shot(master_owner_run, monkeypatch):
    from server.production_run import master_authority

    issuer, sessions, grant, run, _subject, project_dir, cut = master_owner_run
    prepared = R2ShotCut(
        target_ref=cut.target_ref,
        content_fingerprint=cut.content_fingerprint,
        content_basis=cut.content_basis,
        direct_dependencies=cut.direct_dependencies,
        contract_version=cut.contract_version,
        contract_schema_version=cut.contract_schema_version,
        produced=cut.produced,
    )
    calls: list[dict[str, object]] = []

    async def prepare(**kwargs):
        calls.append(kwargs)
        return prepared

    monkeypatch.setattr(master_authority, "prepare_r2_shot_cut", prepare)
    subject = subject_for(run, grant).model_copy(
        update={"subject_digest": master_authority.master_subject_digest(target_id=cut.target_ref, task_id=TASK_ID)}
    )
    return issuer, sessions, grant, run, subject, project_dir, cut, calls


async def _bind(issuer, sessions, subject, project_dir, target_id, task_id=TASK_ID):
    from server.production_run.master_authority import AutomaticMasterApproval

    return await AutomaticMasterApproval.bind(
        sessions=sessions,
        authority=issuer.authority(),
        subject=subject,
        project_dir=project_dir,
        target_id=target_id,
        task_id=task_id,
    )


async def _counts(sessions) -> tuple[int, int]:
    async with sessions() as session:
        heads = await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel))
        receipts = await session.scalar(sa.select(sa.func.count()).select_from(PromotionReceiptModel))
    return int(heads or 0), int(receipts or 0)


async def test_bound_shot_promotes_as_the_run_principal_and_replays(sealed_shot):
    issuer, sessions, grant, run, subject, project_dir, cut, calls = sealed_shot

    approval = await _bind(issuer, sessions, subject, project_dir, cut.target_ref)
    receipt = await approval.promote()
    replay = await approval.promote()

    assert calls == [
        {
            "session_factory": sessions,
            "project_dir": project_dir,
            "user_id": run.user_id,
            "project_name": run.project_name,
            "target_id": cut.target_ref,
            "task_id": TASK_ID,
        }
    ]
    assert receipt == replay
    assert receipt.owner == "gate-c"
    assert receipt.task_id == TASK_ID
    assert approval.selected_by == automation_principal(run.run_id) == grant.principal
    assert await _counts(sessions) == (1, 1)


@pytest.mark.parametrize(
    ("change", "target", "task"),
    [
        ({"operation": AutomationOperation.MEDIA}, None, TASK_ID),
        ({"subject_digest": "sha256:" + "e" * 64}, None, TASK_ID),
        ({}, None, "another-task"),
        ({}, "SH02", TASK_ID),
    ],
)
async def test_bind_refuses_a_subject_not_for_this_exact_shot(sealed_shot, change, target, task):
    issuer, sessions, _grant, _run, subject, project_dir, cut, calls = sealed_shot

    with pytest.raises((PermissionError, ValueError)):
        await _bind(
            issuer, sessions, subject.model_copy(update=change), project_dir, target or cut.target_ref, task_id=task
        )
    assert calls == []
    assert await _counts(sessions) == (0, 0)


async def test_bind_requires_the_activated_run_authority(sealed_shot):
    from server.production_run.master_authority import AutomaticMasterApproval

    _issuer, sessions, _grant, _run, subject, project_dir, cut, calls = sealed_shot

    class Lookalike:
        async def require_locked(self, session, *, subject):
            raise AssertionError("must not be consulted")

    with pytest.raises(PermissionError):
        await AutomaticMasterApproval.bind(
            sessions=sessions,
            authority=Lookalike(),
            subject=subject,
            project_dir=project_dir,
            target_id=cut.target_ref,
            task_id=TASK_ID,
        )
    assert calls == []


async def test_a_refused_shot_is_reported_without_any_master(sealed_shot, monkeypatch):
    from server.production_run import master_authority
    from server.production_run.master_authority import MasterApprovalRefused

    issuer, sessions, _grant, _run, subject, project_dir, cut, _calls = sealed_shot

    async def refuse(**_kwargs):
        raise R2ShotApprovalRefused("r2_shot_output_changed")

    monkeypatch.setattr(master_authority, "prepare_r2_shot_cut", refuse)
    with pytest.raises(MasterApprovalRefused) as refused:
        await _bind(issuer, sessions, subject, project_dir, cut.target_ref)
    assert refused.value.code == "r2_shot_output_changed"
    assert await _counts(sessions) == (0, 0)


async def test_revocation_after_bind_blocks_promotion(sealed_shot):
    from server.auth import create_token

    issuer, sessions, grant, run, subject, project_dir, cut, _calls = sealed_shot
    approval = await _bind(issuer, sessions, subject, project_dir, cut.target_ref)

    await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)

    with pytest.raises(PermissionError):
        await approval.promote()
    assert await _counts(sessions) == (0, 0)


async def test_a_revoked_grant_cannot_bind(sealed_shot):
    from server.auth import create_token

    issuer, sessions, grant, run, subject, project_dir, cut, calls = sealed_shot
    await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)

    with pytest.raises(PermissionError):
        await _bind(issuer, sessions, subject, project_dir, cut.target_ref)
    assert calls == []
