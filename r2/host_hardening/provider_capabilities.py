"""Versioned, fail-closed provider capability registry (spec section 10; plan
Task 4).

Two layers, matching the established declarative-definition convention
(``lib.custom_provider.endpoint_definition.validator``): ``schema.json``
governs structure (field set, types, enums), this module governs semantics --
token scope/value consistency, the ``NOT_FOUND`` settling-window requirement,
``ref``/provider/adapter match, ``entry_digest`` tamper detection, and
qualification/release-mode gating. Both must pass.

``registry.json`` seeds zero profiles: this task defines the loader and its
fail-closed rules, not real provider evidence. No route is enabled by this
file alone. ``ProviderCapabilityProfile.supports_webhook`` being
``Literal[False]`` already makes ``supports_webhook: true`` a Pydantic
construction failure -- this module does not re-check it, only surfaces that
failure as ``ProviderCapabilityIntegrityError``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from lib.content_digest import canonical_json_digest
from r2.contracts.host_hardening import (
    ProviderCapabilityProfile,
    ProviderIdempotencyMode,
    ProviderNotFoundSemantics,
    ProviderQualificationStatus,
)

SCHEMA_PATH = Path(__file__).parent.parent / "provider_capabilities" / "schema.json"
DEFAULT_REGISTRY_PATH = Path(__file__).parent.parent / "provider_capabilities" / "registry.json"

_ENTRY_DIGEST_FIELD = "entry_digest"
_PROFILE_FIELDS = frozenset(
    {
        "ref",
        "provider_id",
        "api_version",
        "adapter_version",
        "idempotency_mode",
        "token_scope",
        "token_scope_value",
        "token_ttl_seconds",
        "not_found_semantics",
        "lookup_settling_window_seconds",
        "supports_poll",
        "supports_cancel",
        "supports_webhook",
        "supports_lookup",
        "provider_sequence_is_monotonic",
        "evidence_digest",
    }
)


class ReleaseMode(StrEnum):
    """Task-local gating vocabulary, deliberately not part of the shared
    ``r2.contracts`` surface (mirrors ``r2.adaptation.profiles.RuleApplicability``'s
    own rationale: extending a fixed public contract enum for an internal
    concern is out of scope)."""

    DEV = "DEV"
    PRODUCTION_CANDIDATE = "PRODUCTION_CANDIDATE"


class ProviderCapabilityError(Exception):
    """Base class for the provider-capability registry error taxonomy."""


class ProviderCapabilityNotFoundError(ProviderCapabilityError):
    """No registry entry has this exact ``ref``."""


class ProviderCapabilityIntegrityError(ProviderCapabilityError):
    """The registry is structurally invalid: schema violation, ``entry_digest``
    mismatch, a ``ref``/provider/adapter mismatch, an inconsistent token
    scope/value for the declared ``idempotency_mode``, a missing settling
    window under ``AUTHORITATIVE_AFTER_SETTLING_WINDOW``, or a field
    ``ProviderCapabilityProfile`` itself rejects (e.g. ``supports_webhook: true``)."""


class ProviderCapabilityUnqualifiedError(ProviderCapabilityError):
    """The capability's qualification status does not permit enabling it in the
    requested release mode, or its evidence has expired."""


@dataclass(frozen=True)
class ProviderCapabilityRegistryEntry:
    profile: ProviderCapabilityProfile
    qualification_status: ProviderQualificationStatus
    evidence_recorded_at: datetime
    evidence_expires_at: datetime | None


def compute_entry_digest(raw_entry: dict[str, Any]) -> str:
    """``sha256:`` over the canonical JSON of every entry field except
    ``entry_digest`` itself -- the same self-covering-hash shape used
    throughout M7 (e.g. ``r2.contracts.host_hardening.command_receipt_result_envelope``)."""
    payload = {k: v for k, v in raw_entry.items() if k != _ENTRY_DIGEST_FIELD}
    return "sha256:" + canonical_json_digest(payload, allow_nan=False)


@cache
def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_schema(document: dict[str, Any]) -> None:
    errors = sorted(_schema_validator().iter_errors(document), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise ProviderCapabilityIntegrityError(f"registry failed schema validation: {details}")


def _validate_entry_semantics(raw: dict[str, Any]) -> None:
    ref = raw["ref"]

    actual_digest = compute_entry_digest(raw)
    if actual_digest != raw[_ENTRY_DIGEST_FIELD]:
        raise ProviderCapabilityIntegrityError(
            f"{ref!r}: entry_digest is {raw[_ENTRY_DIGEST_FIELD]!r}, expected {actual_digest!r} -- "
            "the registry entry was edited without recomputing its digest"
        )

    if raw["adapter_version"] not in ref:
        raise ProviderCapabilityIntegrityError(
            f"{ref!r}: ref does not contain its own declared adapter_version {raw['adapter_version']!r}"
        )
    if raw["provider_id"] not in ref:
        raise ProviderCapabilityIntegrityError(
            f"{ref!r}: ref does not contain its own declared provider_id {raw['provider_id']!r}"
        )

    idempotency_mode = raw["idempotency_mode"]
    has_token_scope = raw["token_scope"] is not None
    has_token_scope_value = raw["token_scope_value"] is not None
    has_token_ttl = raw["token_ttl_seconds"] is not None
    if idempotency_mode == ProviderIdempotencyMode.NATIVE_TOKEN.value:
        if not (has_token_scope and has_token_scope_value and has_token_ttl):
            raise ProviderCapabilityIntegrityError(
                f"{ref!r}: idempotency_mode NATIVE_TOKEN requires token_scope, token_scope_value and "
                "token_ttl_seconds to all be set"
            )
    elif has_token_scope or has_token_scope_value or has_token_ttl:
        raise ProviderCapabilityIntegrityError(
            f"{ref!r}: idempotency_mode {idempotency_mode} must not declare a token scope/value/ttl"
        )

    if (
        raw["not_found_semantics"] == ProviderNotFoundSemantics.AUTHORITATIVE_AFTER_SETTLING_WINDOW.value
        and raw["lookup_settling_window_seconds"] is None
    ):
        raise ProviderCapabilityIntegrityError(
            f"{ref!r}: not_found_semantics AUTHORITATIVE_AFTER_SETTLING_WINDOW requires lookup_settling_window_seconds"
        )


def _load_entries(registry_path: Path) -> dict[str, ProviderCapabilityRegistryEntry]:
    document = json.loads(registry_path.read_text())
    _validate_schema(document)

    entries: dict[str, ProviderCapabilityRegistryEntry] = {}
    for raw in document["profiles"]:
        _validate_entry_semantics(raw)
        ref = raw["ref"]
        try:
            profile = ProviderCapabilityProfile(**{k: raw[k] for k in _PROFILE_FIELDS})
        except ValidationError as exc:
            raise ProviderCapabilityIntegrityError(f"{ref!r}: {exc}") from exc
        if profile.ref != ref:
            raise ProviderCapabilityIntegrityError(
                f"registry key {ref!r} does not match its own profile.ref {profile.ref!r}"
            )
        entries[ref] = ProviderCapabilityRegistryEntry(
            profile=profile,
            qualification_status=ProviderQualificationStatus(raw["qualification_status"]),
            evidence_recorded_at=datetime.fromisoformat(raw["evidence_recorded_at"]),
            evidence_expires_at=(
                None if raw["evidence_expires_at"] is None else datetime.fromisoformat(raw["evidence_expires_at"])
            ),
        )
    return entries


def load_capability_profile(ref: str, *, registry_path: Path = DEFAULT_REGISTRY_PATH) -> ProviderCapabilityProfile:
    """Structural + semantic fail-closed load of one exact capability profile,
    with no qualification or release-mode gating (see ``require_enabled_capability``
    for that)."""
    entries = _load_entries(registry_path)
    entry = entries.get(ref)
    if entry is None:
        raise ProviderCapabilityNotFoundError(f"no provider capability registered for ref {ref!r}")
    return entry.profile


def require_enabled_capability(
    ref: str,
    release_mode: ReleaseMode,
    *,
    now: datetime,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> ProviderCapabilityProfile:
    """Fail-closed: only a ``QUALIFIED``, unexpired capability may be enabled in
    ``PRODUCTION_CANDIDATE`` release mode (spec section 10, "Only QUALIFIED
    routes may be enabled in a production-candidate configuration"). ``DEV``
    mode still requires unexpired evidence -- it relaxes the qualification bar,
    not the freshness one."""
    entries = _load_entries(registry_path)
    entry = entries.get(ref)
    if entry is None:
        raise ProviderCapabilityNotFoundError(f"no provider capability registered for ref {ref!r}")

    if entry.evidence_expires_at is not None and entry.evidence_expires_at <= now:
        raise ProviderCapabilityUnqualifiedError(
            f"{ref!r}: evidence expired at {entry.evidence_expires_at.isoformat()} (now {now.isoformat()})"
        )

    if (
        release_mode is ReleaseMode.PRODUCTION_CANDIDATE
        and entry.qualification_status != ProviderQualificationStatus.QUALIFIED
    ):
        raise ProviderCapabilityUnqualifiedError(
            f"{ref!r}: qualification_status is {entry.qualification_status}, PRODUCTION_CANDIDATE requires QUALIFIED"
        )

    return entry.profile


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "SCHEMA_PATH",
    "ProviderCapabilityError",
    "ProviderCapabilityIntegrityError",
    "ProviderCapabilityNotFoundError",
    "ProviderCapabilityRegistryEntry",
    "ProviderCapabilityUnqualifiedError",
    "ReleaseMode",
    "compute_entry_digest",
    "load_capability_profile",
    "require_enabled_capability",
]
