from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from r2.host_hardening.provider_capabilities import (
    ProviderCapabilityIntegrityError,
    ProviderCapabilityNotFoundError,
    ProviderCapabilityUnqualifiedError,
    ReleaseMode,
    compute_entry_digest,
    load_capability_profile,
    require_enabled_capability,
)

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "provider_capabilities" / "unqualified.json"
REF = "acme-video-v3@1.0.0"
NOW = datetime.now(UTC)


def _document() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _entry() -> dict:
    return deepcopy(_document()["profiles"][0])


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(document))
    return path


def _with_entry(tmp_path: Path, entry: dict) -> Path:
    return _write(tmp_path, {"schema_version": 1, "profiles": [entry]})


# --- the fixture itself loads cleanly ---------------------------------------------------


def test_the_unqualified_fixture_loads_and_resolves() -> None:
    profile = load_capability_profile(REF, registry_path=FIXTURE_PATH)
    assert profile.ref == REF
    assert profile.supports_webhook is False


def test_unknown_ref_raises_not_found() -> None:
    with pytest.raises(ProviderCapabilityNotFoundError):
        load_capability_profile("no-such-ref", registry_path=FIXTURE_PATH)


# --- entry_digest self-consistency (tamper detection) ------------------------------------


def test_compute_entry_digest_matches_the_fixtures_own_recorded_digest() -> None:
    entry = _entry()
    recorded = entry.pop("entry_digest")
    assert compute_entry_digest({**entry, "entry_digest": recorded}) == recorded


def test_a_hand_edited_field_without_a_recomputed_digest_is_rejected(tmp_path: Path) -> None:
    entry = _entry()
    entry["api_version"] = "2099-01-01"  # edited without recomputing entry_digest
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError, match="entry_digest"):
        load_capability_profile(REF, registry_path=path)


# --- ref / provider / adapter match -------------------------------------------------------


def test_ref_must_contain_its_own_provider_id(tmp_path: Path) -> None:
    entry = _entry()
    entry["ref"] = "other-provider-v3@1.0.0"
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError):
        load_capability_profile("other-provider-v3@1.0.0", registry_path=path)


def test_ref_must_contain_its_own_adapter_version(tmp_path: Path) -> None:
    entry = _entry()
    entry["ref"] = "acme-video-v3@9.9.9"
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError):
        load_capability_profile("acme-video-v3@9.9.9", registry_path=path)


# --- unknown fields (schema + Pydantic extra=forbid) --------------------------------------


def test_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    entry = _entry()
    entry["unexpected_field"] = "x"
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError):
        load_capability_profile(REF, registry_path=path)


# --- token scope/value consistency ---------------------------------------------------------


def test_native_token_without_a_token_scope_is_rejected(tmp_path: Path) -> None:
    entry = _entry()
    entry["token_scope"] = None
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError, match="NATIVE_TOKEN"):
        load_capability_profile(REF, registry_path=path)


def test_lookup_by_metadata_with_a_token_scope_is_rejected(tmp_path: Path) -> None:
    entry = _entry()
    entry["idempotency_mode"] = "LOOKUP_BY_METADATA"
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError, match="must not declare"):
        load_capability_profile(REF, registry_path=path)


def test_idempotency_mode_none_with_no_token_scope_is_valid(tmp_path: Path) -> None:
    entry = _entry()
    entry["idempotency_mode"] = "NONE"
    entry["token_scope"] = None
    entry["token_scope_value"] = None
    entry["token_ttl_seconds"] = None
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    profile = load_capability_profile(REF, registry_path=path)
    assert profile.idempotency_mode.value == "NONE"


# --- NOT_FOUND settling-window semantics ---------------------------------------------------


def test_authoritative_after_settling_window_requires_a_window(tmp_path: Path) -> None:
    entry = _entry()
    entry["lookup_settling_window_seconds"] = None
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError, match="settling_window"):
        load_capability_profile(REF, registry_path=path)


def test_non_authoritative_not_found_does_not_require_a_window(tmp_path: Path) -> None:
    entry = _entry()
    entry["not_found_semantics"] = "NON_AUTHORITATIVE"
    entry["lookup_settling_window_seconds"] = None
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    profile = load_capability_profile(REF, registry_path=path)
    assert profile.not_found_semantics.value == "NON_AUTHORITATIVE"


# --- mandatory supports_webhook=false -------------------------------------------------------


def test_supports_webhook_true_is_rejected(tmp_path: Path) -> None:
    entry = _entry()
    entry["supports_webhook"] = True
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityIntegrityError):
        load_capability_profile(REF, registry_path=path)


# --- expired / missing evidence and release-mode qualification gating ----------------------


def test_dev_mode_permits_an_unqualified_but_unexpired_capability() -> None:
    profile = require_enabled_capability(REF, ReleaseMode.DEV, now=NOW, registry_path=FIXTURE_PATH)
    assert profile.ref == REF


def test_production_candidate_mode_rejects_an_unqualified_capability() -> None:
    with pytest.raises(ProviderCapabilityUnqualifiedError, match="UNQUALIFIED"):
        require_enabled_capability(REF, ReleaseMode.PRODUCTION_CANDIDATE, now=NOW, registry_path=FIXTURE_PATH)


def test_production_candidate_mode_permits_a_qualified_unexpired_capability(tmp_path: Path) -> None:
    entry = _entry()
    entry["qualification_status"] = "QUALIFIED"
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    profile = require_enabled_capability(REF, ReleaseMode.PRODUCTION_CANDIDATE, now=NOW, registry_path=path)
    assert profile.ref == REF


def test_expired_evidence_is_rejected_even_in_dev_mode(tmp_path: Path) -> None:
    entry = _entry()
    entry["qualification_status"] = "QUALIFIED"
    entry["evidence_expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    with pytest.raises(ProviderCapabilityUnqualifiedError, match="expired"):
        require_enabled_capability(REF, ReleaseMode.DEV, now=NOW, registry_path=path)


def test_unexpired_evidence_passes_the_freshness_check(tmp_path: Path) -> None:
    entry = _entry()
    entry["qualification_status"] = "QUALIFIED"
    entry["evidence_expires_at"] = (NOW + timedelta(days=1)).isoformat()
    entry["entry_digest"] = compute_entry_digest(entry)
    path = _with_entry(tmp_path, entry)
    profile = require_enabled_capability(REF, ReleaseMode.PRODUCTION_CANDIDATE, now=NOW, registry_path=path)
    assert profile.ref == REF


# --- real registry contains only fail-closed, unqualified route profiles -------------------


def test_the_real_registry_seeds_only_unqualified_route_profiles() -> None:
    real_registry = Path(__file__).resolve().parents[4] / "r2" / "provider_capabilities" / "registry.json"
    document = json.loads(real_registry.read_text())
    assert document["schema_version"] == 1
    assert len(document["profiles"]) == 9
    assert {entry["qualification_status"] for entry in document["profiles"]} == {"UNQUALIFIED"}
    assert {entry["idempotency_mode"] for entry in document["profiles"]} == {"NONE"}
    for entry in document["profiles"]:
        assert load_capability_profile(entry["ref"], registry_path=real_registry).ref == entry["ref"]
