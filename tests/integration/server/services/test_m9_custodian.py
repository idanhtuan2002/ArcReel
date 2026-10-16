"""Host leases bind an authenticated scope to actual signed Human grant evidence."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, update

from lib.db.models.host_custodian import HostCustodianLeaseModel
from r2.contracts.opportunity import ProfilePublicationSubject
from r2.governance.grant_transition import GrantScopeV1
from r2.opportunity.errors import OpportunityError, StopCode
from server.services.governance_grants import CurrentShowrunnerGrantReader, GovernanceGrantImporter
from server.services.m9_custodian import M9ProfileCustodian
from tests.integration.r2.governance.test_grant_importer import _event, _signed

ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
COMMAND = "019a0000-0000-7000-8000-000000000010"
H = "sha256:" + "a" * 64


class LeaseClock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now


def subject(**updates):
    body = {
        "user_id": "u1",
        "project_name": "show-a",
        "actor_id": "reviewer-a",
        "profile_id": ID,
        "parent_revision": None,
        "payload_digest": H,
    }
    return ProfilePublicationSubject(**{**body, **updates})


async def bootstrap_grant(factory, *, expires_in=timedelta(days=365), user_id="u1", principal="reviewer-a"):
    async with factory() as session:
        assert session.get_bind().dialect.name == "postgresql", "M9_REQUIRED_EVIDENCE_MISSING"
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    importer = GovernanceGrantImporter(factory, key_id="test-governance-key", public_key=public)
    now = datetime.now(UTC)
    body = _event("ISSUE", 1, None, (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    body.update(user_id=user_id, principal=principal)
    body["expires_at"] = (now + expires_in).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = await importer.import_event(_signed(body, private), scope=GrantScopeV1(user_id, "show-a", principal))
    return reader, importer, event, private


def custodian(factory, reader, clock):
    return M9ProfileCustodian(
        factory, grants=reader, user_id="u1", project_name="show-a", actor_id="reviewer-a", clock=clock
    )


async def lease_count(factory):
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(HostCustodianLeaseModel))).scalar_one())


async def test_lease_replays_exact_identity_time_policy_and_signed_grant_digest(session_factory):
    reader, _, event, _ = await bootstrap_grant(session_factory)
    clock = LeaseClock()
    adapter = custodian(session_factory, reader, clock)
    lease = await adapter.authorize_publication(COMMAND, subject())
    assert lease.authorized
    assert lease.command_id == COMMAND
    assert lease.custodian_evidence_digest == event.event_digest
    assert (lease.custodian_policy_id, lease.custodian_policy_version) == (
        "arcreel.showrunner-grant",
        "governance.showrunner_grant_event.v1",
    )
    assert lease.admit_not_after - lease.issued_at == timedelta(seconds=30)
    clock.now += timedelta(seconds=1)
    assert await adapter.authorize_publication(COMMAND, subject()) == lease
    with pytest.raises(OpportunityError) as changed:
        await adapter.authorize_publication(COMMAND, subject(payload_digest="sha256:" + "b" * 64))
    assert changed.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert await lease_count(session_factory) == 1


async def test_expired_unadmitted_command_never_refreshes_its_lease(session_factory):
    reader, _, _, _ = await bootstrap_grant(session_factory)
    clock = LeaseClock()
    adapter = custodian(session_factory, reader, clock)
    lease = await adapter.authorize_publication(COMMAND, subject())
    clock.now += timedelta(seconds=31)
    with pytest.raises(OpportunityError) as expired:
        await adapter.authorize_publication(COMMAND, subject())
    assert expired.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    async with session_factory() as session:
        row = await session.get(HostCustodianLeaseModel, lease.authorization_id)
        assert row.issued_at == lease.issued_at
        assert row.admit_not_after == lease.admit_not_after
    assert await lease_count(session_factory) == 1


async def test_later_revocation_refuses_new_leases_without_reinterpreting_an_issued_lease(session_factory):
    reader, importer, event, private = await bootstrap_grant(session_factory)
    clock = LeaseClock()
    adapter = custodian(session_factory, reader, clock)
    lease = await adapter.authorize_publication(COMMAND, subject())
    raw = _signed(_event("REVOKE", 2, event.event_digest, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")), private)
    await importer.import_event(raw, scope=GrantScopeV1("u1", "show-a", "reviewer-a"))
    clock.now += timedelta(seconds=1)
    assert await adapter.authorize_publication(COMMAND, subject()) == lease
    with pytest.raises(OpportunityError) as denied:
        await adapter.authorize_publication(OTHER, subject())
    assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert await lease_count(session_factory) == 1


async def test_lease_deadline_cannot_extend_the_grants_expiry(session_factory):
    reader, _, event, _ = await bootstrap_grant(session_factory, expires_in=timedelta(seconds=12))
    adapter = custodian(session_factory, reader, LeaseClock())
    lease = await adapter.authorize_publication(COMMAND, subject())
    assert lease.admit_not_after == datetime.fromisoformat(event.body.expires_at)
    assert lease.admit_not_after - lease.issued_at < timedelta(seconds=30)


@pytest.mark.parametrize("updates", [{"actor_id": "model"}, {"project_name": "foreign"}, {"user_id": "default"}])
async def test_caller_cannot_override_the_adapters_authenticated_scope(session_factory, updates):
    reader, _, _, _ = await bootstrap_grant(session_factory)
    adapter = custodian(session_factory, reader, LeaseClock())
    with pytest.raises(OpportunityError) as foreign:
        await adapter.authorize_publication(COMMAND, subject(**updates))
    assert foreign.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert await lease_count(session_factory) == 0


async def test_a_principal_without_a_human_grant_cannot_issue_a_lease(session_factory):
    reader, _, _, _ = await bootstrap_grant(session_factory)
    adapter = M9ProfileCustodian(
        session_factory, grants=reader, user_id="u1", project_name="show-a", actor_id="model", clock=LeaseClock()
    )
    with pytest.raises(OpportunityError) as model:
        await adapter.authorize_publication(COMMAND, subject(actor_id="model"))
    assert model.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert await lease_count(session_factory) == 0


async def test_simultaneous_first_calls_return_one_durable_lease(session_factory):
    reader, _, _, _ = await bootstrap_grant(session_factory)
    adapter = custodian(session_factory, reader, LeaseClock())
    first, second = await asyncio.gather(
        adapter.authorize_publication(COMMAND, subject()), adapter.authorize_publication(COMMAND, subject())
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert await lease_count(session_factory) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("policy_id", "model-authority"),
        ("grant_event_digest", H),
        ("subject_digest", H),
        ("authorization_id", "model-checkpoint"),
    ],
)
async def test_replayed_lease_rejects_corrupt_authorization_policy_or_signed_evidence(session_factory, field, value):
    reader, _, _, _ = await bootstrap_grant(session_factory)
    adapter = custodian(session_factory, reader, LeaseClock())
    await adapter.authorize_publication(COMMAND, subject())
    async with session_factory() as session, session.begin():
        await session.execute(update(HostCustodianLeaseModel).values({field: value}))
    with pytest.raises(OpportunityError) as corrupt:
        await adapter.authorize_publication(COMMAND, subject())
    assert corrupt.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED


async def test_missing_activated_grant_reader_is_a_prerequisite_failure(session_factory):
    adapter = custodian(session_factory, None, LeaseClock())
    with pytest.raises(OpportunityError) as missing:
        await adapter.authorize_publication(COMMAND, subject())
    assert missing.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING
    assert await lease_count(session_factory) == 0


async def test_host_composition_publishes_and_replays_the_exact_signed_custody(session_factory):
    from r2.advanced_creative.lineage import host_policy_digest
    from r2.contracts.opportunity import OpportunityCohortProfilePayload
    from server.auth import CurrentUserInfo
    from server.services.opportunity import build_profile_service
    from tests.integration.lib.db.repositories.test_opportunity_profiles import row_counts
    from tests.unit.r2.contracts.test_opportunity import profile_payload
    from tests.unit.r2.opportunity.test_profiles import publication

    reader, _, event, _ = await bootstrap_grant(session_factory)
    user = CurrentUserInfo(id="u1", sub="reviewer-a", role="user")
    service = build_profile_service(session_factory, grants=reader, current_user=user, project_name="show-a")
    payload = OpportunityCohortProfilePayload.model_validate(
        {
            **profile_payload(),
            "creative_profile_id": "arcreel.host",
            "creative_profile_version": "1",
            "creative_policy_pack_digest": host_policy_digest(),
        }
    )
    command = publication(actor_id="reviewer-a", payload=payload)
    first, second = await asyncio.gather(
        service.publish_cohort_profile(command), service.publish_cohort_profile(command)
    )
    assert first.model_dump_json() == second.model_dump_json()
    assert first.profile.custodian_evidence_digest == event.event_digest
    assert (first.profile.user_id, first.profile.created_by) == ("u1", "reviewer-a")
    assert await row_counts(session_factory) == (1, 1, 1, 1)
    assert await lease_count(session_factory) == 1


@pytest.mark.parametrize("principal", ["reviewer-a", "reviewer-e\u0301"])
async def test_http_real_jwt_signed_grant_and_sql_preserve_owner_and_exact_principal(
    session_factory, monkeypatch, principal
):
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from r2.advanced_creative.lineage import host_policy_digest
    from server.auth import create_token
    from server.dependencies import require_project_migration_ok
    from server.error_handlers import register_error_handlers
    from server.routers import opportunity
    from server.services.opportunity import build_profile_service
    from tests.integration.lib.db.repositories.test_opportunity_profiles import row_counts
    from tests.unit.server.routers.test_opportunity_router import BASE, body

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "m9-test-only-secret-at-least-32-bytes")
    reader, _, event, _ = await bootstrap_grant(session_factory, user_id="default", principal=principal)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(opportunity.router, prefix="/api/v1", dependencies=[Depends(require_project_migration_ok)])
    app.dependency_overrides[require_project_migration_ok] = lambda: None

    def factory(user, project):
        return build_profile_service(session_factory, grants=reader, current_user=user, project_name=project)

    app.dependency_overrides[opportunity.profile_service_factory] = lambda: factory
    request = body()
    request["payload"].update(
        creative_profile_id="arcreel.host",
        creative_profile_version="1",
        creative_policy_pack_digest=host_policy_digest(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer " + create_token(principal)}
        first = await client.post(BASE, json=request, headers=headers)
        assert first.status_code == 200, first.text
        profile = first.json()["profile"]
        assert (profile["user_id"], profile["created_by"]) == ("default", principal)
        assert profile["custodian_evidence_digest"] == event.event_digest
        assert (await client.post(BASE, json=request, headers=headers)).content == first.content
        assert (await client.get(BASE + "/" + ID, headers=headers)).json() == profile
    assert await row_counts(session_factory) == (1, 1, 1, 1)
    assert await lease_count(session_factory) == 1


async def test_lease_replay_rejects_tampered_retained_signed_bytes_without_disclosing_them(session_factory):
    import traceback

    from lib.db.models.governance_grant import ShowrunnerGrantEventModel

    reader, _, _, _ = await bootstrap_grant(session_factory)
    adapter = custodian(session_factory, reader, LeaseClock())
    await adapter.authorize_publication(COMMAND, subject())
    canary = "m9-retained-private-canary"
    async with session_factory() as session, session.begin():
        await session.execute(update(ShowrunnerGrantEventModel).values(raw_event=canary.encode()))
    with pytest.raises(OpportunityError) as denied:
        await adapter.authorize_publication(COMMAND, subject())
    assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert canary not in "".join(traceback.format_exception(denied.value))
