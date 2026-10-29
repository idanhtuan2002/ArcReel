"""Server seals for M10-C prepared requests.

A prepare endpoint builds the complete typed service request and seals it; the submit endpoint accepts only that
exact request back, so a retry after a lost response replays the service's receipt instead of rebuilding fields that
would change (identities, times, the resolved subject). The seal proves the server built the request for this
principal, project and action; every authority check stays in the services.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel

from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.errors import RequiredEvidenceMissingError

type Action = Literal["publish_profile", "probe", "review", "seal_run", "dispose"]
ACTIONS: tuple[Action, ...] = ("publish_profile", "probe", "review", "seal_run", "dispose")
_SALT = b"arcreel.m10-c"
_INFO = b"m10-quality-prepare.v1"
_SCHEMA = "m10-c.prepared.v1"


def _key(secret: str) -> bytes:
    if not secret:
        raise RequiredEvidenceMissingError()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT, info=_INFO).derive(secret.encode("utf-8"))


def _envelope(action: Action, user_id: str, actor_id: str, project_name: str, request: BaseModel) -> bytes:
    if action not in ACTIONS:
        raise RequiredEvidenceMissingError()
    return canonical_json_bytes(
        {
            "schema": _SCHEMA,
            "action": action,
            "user_id": user_id,
            "actor_id": actor_id,
            "project_name": project_name,
            "request_type": type(request).__name__,
            "request": request.model_dump(mode="json"),
        }
    )


def seal(secret: str, action: Action, *, user_id: str, actor_id: str, project_name: str, request: BaseModel) -> str:
    digest = hmac.new(_key(secret), _envelope(action, user_id, actor_id, project_name, request), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")


def unseal[M: BaseModel](
    secret: str,
    action: Action,
    model: type[M],
    *,
    user_id: str,
    actor_id: str,
    project_name: str,
    request: Any,
    token: str,
) -> M:
    """The typed request iff `token` seals it for this principal, project and action; refusal otherwise."""
    try:
        typed = model.model_validate(request)
    except ValueError:
        raise RequiredEvidenceMissingError() from None
    if typed.model_dump(mode="json") != request:
        # Only the exact normalized body the server sealed is accepted back.
        raise RequiredEvidenceMissingError()
    expected = seal(secret, action, user_id=user_id, actor_id=actor_id, project_name=project_name, request=typed)
    if not hmac.compare_digest(expected.encode("ascii"), token.encode("ascii", "replace")):
        raise RequiredEvidenceMissingError()
    return typed


__all__ = ["ACTIONS", "Action", "seal", "unseal"]
