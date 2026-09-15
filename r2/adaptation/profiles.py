"""Immutable M6 profile-pack registry (plan Task 8).

Domain policy packs — named source identities and stable rule metadata for the two
M6 v1 profiles — live under ``r2/adaptation/policy_packs/``, deliberately separate
from ``agent_runtime_profile/`` at the repository root (which configures the embedded
creative Agent runtime, an unrelated concern with no rule-pack shape of its own).

``ProfilePackRegistry.resolve`` is the only public method: an exact
``AdaptationProfileRef`` (``profile_id`` + ``profile_version`` +
``policy_pack_digest``) in, the same immutable ``ProfilePack`` out every time, or a
typed error. There is no runtime "latest" lookup, no hot reload, and no executable
rule DSL — a rule is stable metadata (id, version, disposition, applicability,
description), never a prompt or a Human-approval record.

``PolicyRule.applicability`` is either ``ALWAYS`` (one of the nine spec section 5.1
shared rules, present verbatim in both packs) or the exact profile the containing
pack belongs to — a rule naming the *other* profile is a structural error
(``AdaptationPolicyPackIntegrityError``), not merely advisory: the two profile packs
never secretly borrow each other's requirements.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, ValidationError

from r2.adaptation.errors import (
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationPolicyPackIntegrityError,
)
from r2.adaptation.hashing import canonical_adaptation_bytes
from r2.contracts.adaptation import AdaptationProfileId, AdaptationProfileRef, FindingDisposition
from r2.contracts.common import NonEmptyStr, R2ContractModel

POLICY_PACK_HASH_VERSION = "r2-m6-policy-pack-hash-v1"

_PACKS_DIR = Path(__file__).parent / "policy_packs"
_PACK_FILENAMES: dict[AdaptationProfileId, str] = {
    AdaptationProfileId.WESTERN_GENERIC: "western_generic_v1.json",
    AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: "cn_short_drama_shuangwen_v1.json",
}


class RuleApplicability(StrEnum):
    """``ALWAYS`` for a spec section 5.1 shared rule; otherwise the exact profile the
    rule's own containing pack belongs to. Not ``AdaptationProfileId`` itself — that
    enum has no ``ALWAYS`` member and extending a fixed public contract enum for an
    internal, task-local concern is out of scope."""

    ALWAYS = "ALWAYS"
    WESTERN_GENERIC = "WESTERN_GENERIC"
    CN_SHORT_DRAMA_SHUANGWEN = "CN_SHORT_DRAMA_SHUANGWEN"


class PolicyRule(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: NonEmptyStr
    rule_version: NonEmptyStr
    disposition: FindingDisposition
    applicability: RuleApplicability
    description: NonEmptyStr


@dataclass(frozen=True)
class ProfilePack:
    ref: AdaptationProfileRef
    evaluator_version: str
    rules: tuple[PolicyRule, ...]
    canonical_bytes: bytes


def _compute_policy_pack_digest(raw: dict[str, Any]) -> str:
    payload = {"schema": POLICY_PACK_HASH_VERSION, **raw}
    return "sha256:" + hashlib.sha256(canonical_adaptation_bytes(payload)).hexdigest()


def _parse_and_validate(raw: dict[str, Any]) -> tuple[AdaptationProfileId, str, str, tuple[PolicyRule, ...]]:
    """Structural validation only — never checks a digest. Raises
    ``AdaptationPolicyPackIntegrityError`` for anything a caller-supplied digest
    cannot itself catch: an unrecognized profile, a malformed rule, a duplicate rule
    ID, or a rule whose applicability names a different profile than this pack."""
    try:
        profile_id = AdaptationProfileId(raw["profile_id"])
        profile_version = raw["profile_version"]
        evaluator_version = raw["evaluator_version"]
        raw_rules = raw["rules"]
    except (KeyError, ValueError) as err:
        raise AdaptationPolicyPackIntegrityError(f"policy pack manifest is missing or misnames a field: {err}") from err
    if (
        not isinstance(profile_version, str)
        or not isinstance(evaluator_version, str)
        or not isinstance(raw_rules, list)
    ):
        raise AdaptationPolicyPackIntegrityError("policy pack manifest has the wrong shape for a required field")

    seen_ids: set[str] = set()
    rules: list[PolicyRule] = []
    for entry in raw_rules:
        try:
            rule = PolicyRule.model_validate(entry)
        except ValidationError as err:
            raise AdaptationPolicyPackIntegrityError(f"policy pack manifest carries an invalid rule: {err}") from err
        if rule.rule_id in seen_ids:
            raise AdaptationPolicyPackIntegrityError(f"policy pack manifest reuses rule id {rule.rule_id!r}")
        seen_ids.add(rule.rule_id)
        if rule.applicability not in (RuleApplicability.ALWAYS, RuleApplicability(profile_id.value)):
            raise AdaptationPolicyPackIntegrityError(
                f"rule {rule.rule_id!r} declares applicability {rule.applicability.value!r}, which belongs to "
                f"neither ALWAYS nor this pack's own profile {profile_id.value!r}"
            )
        rules.append(rule)

    return profile_id, profile_version, evaluator_version, tuple(rules)


def verify_manifest_bytes(value: bytes, expected_digest: str) -> ProfilePack:
    """Parse, structurally validate, and digest-verify one policy-pack manifest from
    raw bytes — the primitive both ``ProfilePackRegistry.resolve`` and a direct
    tamper/corpus test use. Structural validation always runs first: a digest match
    never waves through a manifest that fails it, and a digest mismatch is reported
    distinctly from every structural failure."""
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as err:
        raise AdaptationPolicyPackIntegrityError(f"policy pack manifest is not valid JSON: {err}") from err
    if not isinstance(raw, dict):
        raise AdaptationPolicyPackIntegrityError("policy pack manifest must be a JSON object")

    profile_id, profile_version, evaluator_version, rules = _parse_and_validate(raw)

    digest = _compute_policy_pack_digest(raw)
    if digest != expected_digest:
        raise AdaptationPolicyDigestMismatchError(
            f"policy pack manifest digest {digest!r} does not match expected {expected_digest!r}"
        )

    ref = AdaptationProfileRef(profile_id=profile_id, profile_version=profile_version, policy_pack_digest=digest)
    return ProfilePack(
        ref=ref, evaluator_version=evaluator_version, rules=rules, canonical_bytes=canonical_adaptation_bytes(raw)
    )


class ProfilePackRegistry:
    """``resolve`` is the only public method — no ``latest``, no reload, no rule DSL."""

    def resolve(self, ref: AdaptationProfileRef) -> ProfilePack:
        filename = _PACK_FILENAMES.get(ref.profile_id)
        if filename is None:
            raise AdaptationNotFoundError(f"no policy pack is registered for profile {ref.profile_id.value!r}")

        value = (_PACKS_DIR / filename).read_bytes()
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as err:
            raise AdaptationPolicyPackIntegrityError(f"policy pack manifest is not valid JSON: {err}") from err
        if not isinstance(raw, dict):
            raise AdaptationPolicyPackIntegrityError("policy pack manifest must be a JSON object")

        profile_id, profile_version, _evaluator_version, _rules = _parse_and_validate(raw)
        if profile_id != ref.profile_id or profile_version != ref.profile_version:
            raise AdaptationNotFoundError(
                f"no policy pack resolves for {ref.profile_id.value!r} at version {ref.profile_version!r}"
            )

        return verify_manifest_bytes(value, ref.policy_pack_digest)


__all__ = [
    "POLICY_PACK_HASH_VERSION",
    "PolicyRule",
    "ProfilePack",
    "ProfilePackRegistry",
    "RuleApplicability",
    "verify_manifest_bytes",
]
