"""Human review endpoints accept only interactive session JWTs."""

from __future__ import annotations

from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from server import auth

SECRET = "test-secret-key-that-is-at-least-32-bytes"


@pytest.mark.asyncio
async def test_interactive_user_accepts_session_jwt() -> None:
    with patch.dict("os.environ", {"AUTH_ENABLED": "true", "AUTH_TOKEN_SECRET": SECRET}):
        result = await auth.get_current_interactive_user(auth.create_token("reviewer-a"))
    assert result.id == "default"
    assert result.sub == "reviewer-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "arc-test-api-key", "invalid-token"])
async def test_interactive_user_denies_missing_api_key_and_invalid_token(token: str | None) -> None:
    with (
        patch.dict("os.environ", {"AUTH_ENABLED": "true", "AUTH_TOKEN_SECRET": SECRET}),
        pytest.raises(HTTPException) as exc,
    ):
        await auth.get_current_interactive_user(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "INTERACTIVE_SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_interactive_user_denies_download_token_and_disabled_auth() -> None:
    with patch.dict("os.environ", {"AUTH_ENABLED": "true", "AUTH_TOKEN_SECRET": SECRET}):
        download = auth.create_download_token("reviewer-a", "show-a")
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_interactive_user(download)
        assert exc.value.status_code == 401
        empty_sub = jwt.encode({"sub": ""}, SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_interactive_user(empty_sub)
        assert exc.value.status_code == 401
        unbounded = jwt.encode({"sub": "reviewer-a"}, SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_interactive_user(unbounded)
        assert exc.value.status_code == 401
        session = auth.create_token("reviewer-a")
    with (
        patch.dict("os.environ", {"AUTH_ENABLED": "false", "AUTH_TOKEN_SECRET": SECRET}),
        pytest.raises(HTTPException) as exc,
    ):
        await auth.get_current_interactive_user(session)
    assert exc.value.status_code == 401
