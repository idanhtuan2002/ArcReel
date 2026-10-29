"""M10-C prepared-request seals bind the exact request to its principal, project and action."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from r2.quality.errors import RequiredEvidenceMissingError
from server.services.quality_prepare import seal, unseal

SECRET = "m10-test-secret-that-is-at-least-32-bytes"


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str
    value: int


SCOPE = {"user_id": "default", "actor_id": "actor", "project_name": "project"}
BODY = {"command_id": "c-1", "value": 7}


def _token(**changes) -> str:
    scope = SCOPE | changes
    return seal(SECRET, "probe", request=Req.model_validate(BODY), **scope)


def test_the_exact_sealed_request_is_accepted_back() -> None:
    assert unseal(SECRET, "probe", Req, request=BODY, token=_token(), **SCOPE) == Req.model_validate(BODY)


@pytest.mark.parametrize(
    "change",
    [
        {"request": BODY | {"value": 8}},
        {"user_id": "other"},
        {"actor_id": "other"},
        {"project_name": "other"},
        {"action": "dispose"},
        {"secret": SECRET + "x"},
        {"request": BODY | {"extra": 1}},
    ],
)
def test_any_other_request_principal_project_action_or_key_is_refused(change) -> None:
    kwargs = {"secret": SECRET, "action": "probe", "request": BODY} | SCOPE
    kwargs |= change
    secret, action = kwargs.pop("secret"), kwargs.pop("action")
    with pytest.raises(RequiredEvidenceMissingError):
        unseal(secret, action, Req, token=_token(), **kwargs)


def test_an_unknown_action_or_empty_secret_cannot_seal() -> None:
    with pytest.raises(RequiredEvidenceMissingError):
        seal(SECRET, "anything", request=Req.model_validate(BODY), **SCOPE)
    with pytest.raises(RequiredEvidenceMissingError):
        seal("", "probe", request=Req.model_validate(BODY), **SCOPE)
