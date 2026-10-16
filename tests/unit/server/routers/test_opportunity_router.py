"""Profile HTTP admission derives owner/principal from auth and preserves replay bytes."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from r2.opportunity.profiles import OpportunityProfileService
from server import auth
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.dependencies import require_project_migration_ok
from server.error_handlers import register_error_handlers
from server.routers import opportunity
from tests.unit.r2.contracts.test_opportunity import profile_payload
from tests.unit.r2.opportunity.test_profiles import ProfileCustodianFixture, ProfileMemoryStore

ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
COMMAND = "019a0000-0000-7000-8000-000000000010"
BASE = "/api/v1/projects/show-a/m9/opportunity/cohort-profiles"
USER = CurrentUserInfo(id="u1", sub="human-a", role="user")


def client_fixture(*, human=True, migration_ok=True):
    store = ProfileMemoryStore()
    custodian = ProfileCustodianFixture(store)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(opportunity.router, prefix="/api/v1", dependencies=[Depends(require_project_migration_ok)])
    app.dependency_overrides[get_current_user] = lambda: USER
    if human:
        app.dependency_overrides[get_current_interactive_user] = lambda: USER
    if migration_ok:
        app.dependency_overrides[require_project_migration_ok] = lambda: None

    def factory(user, project_name):
        return OpportunityProfileService(
            store=store, custodian=custodian, user_id=user.id, project_name=project_name, actor_id=user.sub
        )

    app.dependency_overrides[opportunity.profile_service_factory] = lambda: factory
    return (AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver"), store, custodian)


def body(**updates):
    return {
        "command_id": COMMAND,
        "profile_id": ID,
        "parent_revision": None,
        "expected_head_version": None,
        "payload": profile_payload(),
        **updates,
    }


async def test_publish_and_replay_use_authenticated_owner_and_principal_with_byte_equal_receipts(
    opportunity_client_factory,
):
    client, store, custodian = opportunity_client_factory()
    first = await client.post(BASE, json=body())
    assert first.status_code == 200
    profile = first.json()["profile"]
    assert (profile["user_id"], profile["created_by"], profile["project_name"]) == ("u1", "human-a", "show-a")
    assert (await client.post(BASE, json=body())).content == first.content
    assert custodian.calls == 1
    assert len(store.events) == 1
    assert (await client.get(BASE)).json()[0]["profile_id"] == ID
    assert (await client.get(BASE + "/" + ID)).json() == profile


@pytest.mark.parametrize("scope_field", ["user_id", "actor_id", "project_name"])
async def test_body_scope_injection_is_rejected_before_authorization(scope_field, opportunity_client_factory):
    client, store, custodian = opportunity_client_factory()
    response = await client.post(BASE, json=body(**{scope_field: "foreign"}))
    assert response.status_code == 422
    assert custodian.calls == 0
    assert not store.events


@pytest.mark.parametrize("query", ["?limit=0", "?limit=101"])
async def test_list_bounds_are_enforced_before_storage(query, opportunity_client_factory):
    client, store, _ = opportunity_client_factory()
    assert (await client.get(BASE + query)).status_code == 422
    assert not store.events


async def test_current_and_historical_reads_are_separate_and_unknown_scope_is_not_found(opportunity_client_factory):
    client, _, _ = opportunity_client_factory()
    first = (await client.post(BASE, json=body())).json()
    second = (await client.post(BASE, json=body(command_id=OTHER, parent_revision=1, expected_head_version=1))).json()
    assert (await client.get(BASE)).json() == [second["profile"]]
    assert (await client.get(BASE + "/" + ID + "?revision=1")).json() == first["profile"]
    assert (await client.get(BASE + "/" + ID + "?revision=0")).status_code == 422
    foreign = await client.get(BASE.replace("show-a", "foreign-project") + "/" + ID)
    unknown = await client.get(BASE + "/" + OTHER)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


@pytest.mark.parametrize("auth_enabled", [False, True])
async def test_auth_disabled_or_api_key_cannot_reach_human_publication(
    monkeypatch, auth_enabled, opportunity_client_factory
):
    client, store, custodian = opportunity_client_factory(human=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: auth_enabled)
    token = auth.API_KEY_PREFIX + "fixture-only"
    response = await client.post(BASE, json=body(), headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert custodian.calls == 0
    assert not store.events


async def test_domain_conflicts_and_forbidden_publication_have_stable_localized_stop_codes(opportunity_client_factory):
    client, _, custodian = opportunity_client_factory()
    custodian.override = {"authorized": False}
    denied = await client.post(BASE, json=body(), headers={"Accept-Language": "vi"})
    assert denied.status_code == 403
    assert denied.json()["diagnostic"]["stop_code"] == "M9_PROFILE_PUBLICATION_UNAUTHORIZED"
    assert denied.json()["detail"] == "Bạn không có quyền xuất bản hồ sơ cơ hội này."
    custodian.override = {}
    assert (await client.post(BASE, json=body())).status_code == 200
    conflict = await client.post(BASE, json=body(profile_id=OTHER))
    assert conflict.status_code == 409
    assert conflict.json()["diagnostic"]["stop_code"] == "M9_COMMAND_REPLAY_CONFLICT"


async def test_invalid_command_and_genesis_pairs_are_validation_errors(opportunity_client_factory):
    client, store, custodian = opportunity_client_factory()
    assert (await client.post(BASE, json=body(command_id="not-uuid7"))).status_code == 422
    assert (await client.post(BASE, json=body(parent_revision=1))).status_code == 422
    assert not store.events
    assert custodian.calls == 0


async def test_parent_migration_guard_is_enforced_on_the_real_app(monkeypatch):
    from lib.api_errors import ServiceUnavailableError
    from server.app import app

    store = ProfileMemoryStore()
    custodian = ProfileCustodianFixture(store)

    def factory(user, project_name):
        return OpportunityProfileService(
            store=store, custodian=custodian, user_id=user.id, project_name=project_name, actor_id=user.sub
        )

    async def blocked_migration():
        raise ServiceUnavailableError("m9_required_evidence_missing")

    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: USER)
    monkeypatch.setitem(app.dependency_overrides, get_current_interactive_user, lambda: USER)
    monkeypatch.setitem(app.dependency_overrides, opportunity.profile_service_factory, lambda: factory)
    monkeypatch.setitem(app.dependency_overrides, require_project_migration_ok, blocked_migration)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(BASE, json=body())
    assert response.status_code == 503
    assert custodian.calls == 0
    assert not store.events


async def test_reads_accept_authenticated_api_key_users_without_a_human_lease(monkeypatch, opportunity_client_factory):
    client, _, custodian = opportunity_client_factory(human=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    response = await client.get(BASE, headers={"Authorization": "Bearer " + auth.API_KEY_PREFIX + "fixture-only"})
    assert response.status_code == 200
    assert response.json() == []
    assert custodian.calls == 0


@pytest.mark.parametrize(
    ("fault", "expected_code", "status"),
    [
        ("cohort", "M9_COHORT_LEAKAGE", 409),
        ("stale", "M9_STALE_HEAD", 409),
        ("prerequisite", "M9_REQUIRED_EVIDENCE_MISSING", 503),
    ],
)
async def test_fixed_domain_error_statuses_remain_machine_readable(
    fault, expected_code, status, opportunity_client_factory
):
    from r2.opportunity.errors import StopCode

    client, store, custodian = opportunity_client_factory()
    command = body()
    if fault == "cohort":
        store.policy = ("WESTERN_GENERIC", "1", "sha256:" + "b" * 64)
    elif fault == "stale":
        assert (await client.post(BASE, json=body())).status_code == 200
        command = body(command_id=OTHER)
    else:
        custodian.failure_code = StopCode.M9_REQUIRED_EVIDENCE_MISSING
    response = await client.post(BASE, json=command)
    assert response.status_code == status
    assert response.json()["diagnostic"]["stop_code"] == expected_code


@pytest.fixture
async def opportunity_client_factory():
    clients = []

    def instantiate(**options):
        client, store, custodian = client_fixture(**options)
        clients.append(client)
        return (client, store, custodian)

    yield instantiate
    for client in clients:
        await client.aclose()
