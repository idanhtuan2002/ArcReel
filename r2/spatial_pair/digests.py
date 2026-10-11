"""Preparation-canonical digests for proposed spatial pair decisions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.spatial_pair import (
    PairAuthorizationV1,
    PairDecisionCommandV1,
    PairDecisionCommandV2,
    PairDecisionResultV1,
    PairDecisionResultV2,
    PairDecisionV1,
    PairDecisionV2,
)

_BINDING_ID = re.compile(r"m8b:[0-9a-f]{64}\Z")
_DOMAINS = {
    "identity": "r2.m8.spatial.pair.identity.v1",
    "command": "r2.m8.spatial.pair.command.v1",
    "command_v2": "r2.m8.spatial.pair.command.v2",
    "authorization": "r2.m8.spatial.pair.authorization.v1",
    "decision": "r2.m8.spatial.pair.decision.v2",
    "decision_v2": "r2.m8.spatial.pair.decision.v3",
    "result": "r2.m8.spatial.pair.result.v1",
    "result_v2": "r2.m8.spatial.pair.result.v2",
}


def _digest(kind: str, body: Mapping[str, Any]) -> str:
    envelope = ensure_json_value({"domain": _DOMAINS[kind], "canonical_version": "1", "body": dict(body)})
    return "sha256:" + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def scoped_pair_id(*, user_id: str, project_name: str, binding_id: str) -> str:
    if (
        not user_id
        or user_id != user_id.strip()
        or not project_name
        or project_name != project_name.strip()
        or _BINDING_ID.fullmatch(binding_id) is None
    ):
        raise ValueError("pair identity requires exact scope and binding ID")
    digest = _digest("identity", {"user_id": user_id, "project_name": project_name, "binding_id": binding_id})
    return "m8p:" + digest.removeprefix("sha256:")


def pair_command_digest(body: Mapping[str, Any]) -> str:
    command = PairDecisionCommandV1.model_validate(body)
    return _digest("command", command.model_dump(mode="json"))


def pair_command_digest_v2(body: Mapping[str, Any]) -> str:
    command = PairDecisionCommandV2.model_validate(body)
    return _digest("command_v2", command.model_dump(mode="json"))


def pair_authorization_digest(body: Mapping[str, Any]) -> str:
    authorization = PairAuthorizationV1.model_validate(body)
    return _digest("authorization", authorization.model_dump(mode="json"))


def pair_decision_digest(body: Mapping[str, Any]) -> str:
    decision = PairDecisionV1.model_validate(body)
    command = decision.command
    if decision.command_digest != pair_command_digest(command.model_dump(mode="json")):
        raise ValueError("pair decision command digest differs from exact command")
    if decision.authorization_digest != pair_authorization_digest(decision.authorization.model_dump(mode="json")):
        raise ValueError("pair decision authorization digest differs from exact authorization")
    if decision.pair_id != scoped_pair_id(
        user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id
    ):
        raise ValueError("pair decision ID differs from scoped binding identity")
    return _digest("decision", decision.model_dump(mode="json"))


def pair_result_digest(body: Mapping[str, Any]) -> str:
    result = PairDecisionResultV1.model_validate(body)
    return _digest("result", result.model_dump(mode="json"))


def pair_decision_digest_v2(body: Mapping[str, Any]) -> str:
    decision = PairDecisionV2.model_validate(body)
    return _digest("decision_v2", decision.model_dump(mode="json"))


def pair_result_digest_v2(body: Mapping[str, Any]) -> str:
    result = PairDecisionResultV2.model_validate(body)
    return _digest("result_v2", result.model_dump(mode="json"))


__all__ = [
    "pair_authorization_digest",
    "pair_command_digest",
    "pair_command_digest_v2",
    "pair_decision_digest",
    "pair_decision_digest_v2",
    "pair_result_digest",
    "pair_result_digest_v2",
    "scoped_pair_id",
]
