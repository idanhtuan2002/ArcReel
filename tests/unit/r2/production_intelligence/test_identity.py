"""D05 — scoped + typed VisualIdentity resolution."""

from __future__ import annotations

import pytest

from r2.contracts import (
    IdentityConstraint,
    IdentityScopeType,
    IdentityStrength,
    ResolvedIdentityStatus,
    VisualIdentityProfile,
)
from r2.production_intelligence.identity import VisualIdentityResolver

FORBIDDEN_PROVIDER_FIELDS = {"provider", "model", "endpoint", "payload", "provider_job_id"}


def _profile(
    profile_id: str,
    scope_type: IdentityScopeType | None,
    scope_ref: str | None,
    *constraints: IdentityConstraint,
    **flat: object,
) -> VisualIdentityProfile:
    return VisualIdentityProfile(
        id=profile_id,
        schema_version="1",
        version=1,
        semantic_character_ref="character:maya",
        scope_type=scope_type,
        scope_ref=scope_ref,
        identity_constraints=list(constraints),
        **flat,
    )


def _c(key: str, strength: IdentityStrength, value: str) -> IdentityConstraint:
    return IdentityConstraint(semantic_key=key, strength=strength, semantic_value=value)


def _resolver() -> VisualIdentityResolver:
    return VisualIdentityResolver()


def _by_key(resolved):
    return {rc.semantic_key: rc for rc in resolved.resolved_constraints}


def test_specific_preferred_refines_broader_preferred() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[
            _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.PREFERRED, "bob")),
            _profile(
                "P-scene", IdentityScopeType.SCENE, "SC01", _c("hairstyle", IdentityStrength.PREFERRED, "ponytail")
            ),
        ],
    )
    assert resolved.status is ResolvedIdentityStatus.RESOLVED
    hairstyle = _by_key(resolved)["hairstyle"]
    assert hairstyle.effective_value == "ponytail"
    assert hairstyle.effective_strength is IdentityStrength.PREFERRED
    assert hairstyle.source_scope_ref == "SC01"


def test_weaker_narrower_constraint_cannot_weaken_inherited_locked() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[
            _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.LOCKED, "bob")),
            _profile("P-shot", IdentityScopeType.SHOT, "SH01", _c("hairstyle", IdentityStrength.PREFERRED, "ponytail")),
        ],
    )
    assert resolved.status is ResolvedIdentityStatus.RESOLVED
    hairstyle = _by_key(resolved)["hairstyle"]
    assert hairstyle.effective_strength is IdentityStrength.LOCKED
    assert hairstyle.effective_value == "bob"


def test_narrower_locked_may_strengthen_broader_preferred() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[
            _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.PREFERRED, "bob")),
            _profile("P-scene", IdentityScopeType.SCENE, "SC01", _c("hairstyle", IdentityStrength.LOCKED, "bob")),
        ],
    )
    assert resolved.status is ResolvedIdentityStatus.RESOLVED
    assert _by_key(resolved)["hairstyle"].effective_strength is IdentityStrength.LOCKED


def test_conflicting_locked_constraints_produce_conflict_not_a_silent_winner() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[
            _profile("P-scene", IdentityScopeType.SCENE, "SC01", _c("hairstyle", IdentityStrength.LOCKED, "bob")),
            _profile("P-shot", IdentityScopeType.SHOT, "SH01", _c("hairstyle", IdentityStrength.LOCKED, "long braid")),
        ],
    )
    assert resolved.status is ResolvedIdentityStatus.CONFLICTED
    assert any("hairstyle" in c for c in resolved.conflicts)


def test_resolution_is_deterministic_regardless_of_profile_order() -> None:
    profiles = [
        _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.PREFERRED, "bob")),
        _profile("P-seq", IdentityScopeType.SEQUENCE, "SEQ1", _c("wardrobe", IdentityStrength.LOCKED, "grey coat")),
        _profile("P-scene", IdentityScopeType.SCENE, "SC01", _c("hairstyle", IdentityStrength.LOCKED, "bob")),
    ]
    a = _resolver().resolve(target_ref="SH01", profiles=profiles)
    b = _resolver().resolve(target_ref="SH01", profiles=list(reversed(profiles)))
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_flat_hairstyle_lock_is_treated_as_a_locked_constraint() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[_profile("P-flat", None, None, hairstyle_lock="bob")],
    )
    hairstyle = _by_key(resolved)["hairstyle"]
    assert hairstyle.effective_strength is IdentityStrength.LOCKED
    assert hairstyle.effective_value == "bob"


def test_resolved_view_carries_no_provider_fields() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        profiles=[
            _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.LOCKED, "bob"))
        ],
    )
    assert set(resolved.model_dump(mode="json")).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)
    assert resolved.observed_profile_versions == ["P-proj@1"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
