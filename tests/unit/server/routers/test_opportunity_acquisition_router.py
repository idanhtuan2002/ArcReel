"""Source query and V2 acquisition HTTP admission: authenticated scope only, explicit protocol, validation first."""

from contextlib import AbstractAsyncContextManager

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from lib.i18n.en.errors import MESSAGES as EN
from lib.i18n.vi.errors import MESSAGES as VI
from lib.i18n.zh.errors import MESSAGES as ZH
from r2.advanced_creative.exploration import uuid7
from r2.opportunity.acquisition_v2 import OpportunityAcquisitionServiceV2
from r2.opportunity.errors import OpportunityError, StopCode
from server import auth
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.dependencies import require_project_migration_ok
from server.error_handlers import register_error_handlers
from server.routers import opportunity_acquisition

COMMAND = "019a0000-0000-7000-8000-000000000091"
QUERY = "019a0000-0000-7000-8000-000000000001"
BASE = "/api/v1/projects/show-a/m9/opportunity"
USER = CurrentUserInfo(id="u1", sub="human-a", role="user")
DIGEST = "sha256:" + "a" * 64


class UntouchedStore:
    """A store port that fails the test if any request reaches persistence."""

    def __init__(self) -> None:
        self.entered = 0

    def transaction(self) -> AbstractAsyncContextManager[object]:
        self.entered += 1
        raise AssertionError("the request reached persistence")


def client_fixture(*, human: bool = True):
    store = UntouchedStore()
    built: list[tuple[str, str]] = []
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        opportunity_acquisition.router, prefix="/api/v1", dependencies=[Depends(require_project_migration_ok)]
    )
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[require_project_migration_ok] = lambda: None
    if human:
        app.dependency_overrides[get_current_interactive_user] = lambda: USER

    def factory(user, project_name):
        built.append((user.id, project_name))
        return OpportunityAcquisitionServiceV2(
            store=store,
            registry=None,
            descriptor=None,
            upload=None,
            capabilities=None,
            new_id=uuid7,
            user_id=user.id,
            project_name=project_name,
            actor_id=user.sub,
        )

    def query_factory(user, project_name):
        built.append((user.id, project_name))
        raise AssertionError("query declaration reached the application")

    app.dependency_overrides[opportunity_acquisition.acquisition_service_factory] = lambda: factory
    app.dependency_overrides[opportunity_acquisition.query_service_factory] = lambda: query_factory
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver"), store, built


def acquisition(**updates):
    return {
        "protocol_version": "m9.acquisition.v2",
        "command_id": COMMAND,
        "query_id": QUERY,
        "query_revision": 1,
        "query_digest": DIGEST,
        "expected_query_head_version": 1,
        **updates,
    }


def declaration(**updates):
    return {
        "command_id": COMMAND,
        "query_id": QUERY,
        "parent_revision": None,
        "expected_head_version": None,
        "draft": {},
        **updates,
    }


@pytest.mark.parametrize("protocol", [None, "m9.acquisition.v1", "m9.acquisition.v3", ""])
async def test_acquisition_names_the_v2_protocol_explicitly_before_any_application_call(protocol):
    client, store, built = client_fixture()
    body = acquisition(protocol_version=protocol)
    if protocol is None:
        del body["protocol_version"]
    response = await client.post(BASE + "/acquisitions", json=body)
    assert response.status_code == 422
    assert built == []
    assert store.entered == 0


@pytest.mark.parametrize("scope_field", ["user_id", "project_name", "actor_id", "context"])
async def test_body_scope_injection_is_rejected_before_the_application(scope_field):
    client, store, built = client_fixture()
    response = await client.post(BASE + "/acquisitions", json=acquisition(**{scope_field: "foreign"}))
    assert response.status_code == 422
    assert built == []
    assert store.entered == 0


@pytest.mark.parametrize("auth_enabled", [False, True])
@pytest.mark.parametrize(("path", "make"), [("/acquisitions", acquisition), ("/queries", declaration)])
async def test_api_keys_and_disabled_auth_cannot_mutate(monkeypatch, auth_enabled, path, make):
    client, store, built = client_fixture(human=False)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: auth_enabled)
    headers = {"Authorization": "Bearer " + auth.API_KEY_PREFIX + "fixture-only"}
    response = await client.post(BASE + path, json=make(), headers=headers)
    assert response.status_code == 401
    assert built == []
    assert store.entered == 0


@pytest.mark.parametrize(
    "query",
    [
        "/capabilities?limit=0",
        "/capabilities?limit=101",
        "/snapshots?limit=10",
        "/snapshots/x?revision=0",
        "/queries/x?revision=0",
    ],
)
async def test_read_bounds_and_required_parameters_are_enforced_before_the_application(query):
    client, store, built = client_fixture(human=False)
    response = await client.get(BASE + query)
    assert response.status_code == 422
    assert built == []
    assert store.entered == 0


@pytest.mark.parametrize("code", list(StopCode))
def test_every_stop_code_maps_to_a_localized_sanitized_error(code):
    error = opportunity_acquisition.api_error(OpportunityError(code))
    assert error.status_code in {403, 409, 410, 503}
    assert error.diagnostic == {"stop_code": code.value}
    for catalog in (EN, VI, ZH):
        assert error.key in catalog


def test_conflicts_retention_and_unavailable_sources_have_distinct_statuses():
    status = {
        code: opportunity_acquisition.api_error(OpportunityError(code)).status_code
        for code in (
            StopCode.M9_COMMAND_REPLAY_CONFLICT,
            StopCode.M9_STALE_HEAD,
            StopCode.M9_SOURCE_POLICY_FORBIDDEN,
            StopCode.M9_EVIDENCE_RETENTION_EXPIRED,
            StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE,
        )
    }
    assert list(status.values()) == [409, 409, 403, 410, 503]


async def test_the_real_app_serves_the_routes_behind_the_migration_guard(monkeypatch):
    from lib.api_errors import ServiceUnavailableError
    from server.app import app

    built: list[str] = []

    async def blocked_migration():
        raise ServiceUnavailableError("m9_acquisition_evidence_missing")

    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: USER)
    monkeypatch.setitem(app.dependency_overrides, get_current_interactive_user, lambda: USER)
    monkeypatch.setitem(
        app.dependency_overrides,
        opportunity_acquisition.acquisition_service_factory,
        lambda: lambda user, project: built.append(project),
    )
    monkeypatch.setitem(app.dependency_overrides, require_project_migration_ok, blocked_migration)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(BASE + "/acquisitions", json=acquisition())
    assert response.status_code == 503
    assert built == []
