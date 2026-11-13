from __future__ import annotations

import httpx
import pytest

from lib.text_backends.route_failure import is_route_failure


class _Status(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(str(status))
        self.status_code = status


@pytest.mark.parametrize("status", [401, 402, 403, 404, 408, 429, 500, 503])
def test_quota_auth_missing_model_and_server_errors_name_the_route(status):
    assert is_route_failure(_Status(status))


@pytest.mark.parametrize("status", [400, 409, 422])
def test_a_bad_request_is_about_the_question_not_the_route(status):
    assert not is_route_failure(_Status(status))
    assert not is_route_failure(ValueError("schema mismatch"))


def test_transport_errors_and_wrapped_causes_name_the_route():
    request = httpx.Request("POST", "https://api.example.test")
    assert is_route_failure(httpx.ConnectError("down", request=request))
    assert is_route_failure(TimeoutError())
    wrapped = RuntimeError("generation failed")
    wrapped.__cause__ = _Status(429)
    assert is_route_failure(wrapped)
    response = httpx.Response(503, request=request)
    assert is_route_failure(httpx.HTTPStatusError("x", request=request, response=response))
