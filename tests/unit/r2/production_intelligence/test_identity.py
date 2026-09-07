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


# The SH01 target's scope ancestry: one ref per level it descends from.
_ANCESTRY = {
    IdentityScopeType.PROJECT: "PRJ",
    IdentityScopeType.SEQUENCE: "SEQ1",
    IdentityScopeType.SCENE: "SC01",
    IdentityScopeType.SHOT: "SH01",
}


def _by_key(resolved):
    return {rc.semantic_key: rc for rc in resolved.resolved_constraints}


def test_specific_preferred_refines_broader_preferred() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry=_ANCESTRY,
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
        scope_ancestry=_ANCESTRY,
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
        scope_ancestry=_ANCESTRY,
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
        scope_ancestry=_ANCESTRY,
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
    a = _resolver().resolve(target_ref="SH01", scope_ancestry=_ANCESTRY, profiles=profiles)
    b = _resolver().resolve(target_ref="SH01", scope_ancestry=_ANCESTRY, profiles=list(reversed(profiles)))
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_flat_hairstyle_lock_is_treated_as_a_locked_constraint() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry=_ANCESTRY,
        profiles=[_profile("P-flat", None, None, hairstyle_lock="bob")],
    )
    hairstyle = _by_key(resolved)["hairstyle"]
    assert hairstyle.effective_strength is IdentityStrength.LOCKED
    assert hairstyle.effective_value == "bob"


def test_every_frozen_flat_lock_reaches_the_resolved_view() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry={IdentityScopeType.SHOT: "SH01"},
        profiles=[
            _profile(
                "P-flat",
                None,
                None,
                face_master_ref="asset:face-1",
                full_body_master_ref="asset:body-1",
                side_profile_ref="asset:side-1",
                costume_locks=["asset:coat", "asset:boots"],
                accessory_locks=["asset:watch"],
                state_variants=["rain-soaked"],
            )
        ],
    )
    keys = _by_key(resolved)
    assert keys["full_body_master"].effective_strength is IdentityStrength.LOCKED
    assert keys["full_body_master"].effective_value == "asset:body-1"
    assert keys["side_profile"].effective_value == "asset:side-1"
    assert keys["costume_lock:asset:coat"].effective_strength is IdentityStrength.LOCKED
    assert keys["costume_lock:asset:boots"].effective_value == "asset:boots"
    assert keys["accessory_lock:asset:watch"].effective_strength is IdentityStrength.LOCKED
    # State variants are an allowed-variance envelope, not a pinned reference.
    assert keys["state_variant:rain-soaked"].effective_strength is IdentityStrength.PREFERRED


def test_resolved_view_carries_no_provider_fields() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry=_ANCESTRY,
        profiles=[
            _profile("P-proj", IdentityScopeType.PROJECT, "PRJ", _c("hairstyle", IdentityStrength.LOCKED, "bob"))
        ],
    )
    assert set(resolved.model_dump(mode="json")).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)
    assert resolved.observed_profile_versions == ["P-proj@1"]


def test_profile_scoped_to_a_different_shot_is_excluded_from_resolution() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry=_ANCESTRY,
        profiles=[
            _profile("P-scene", IdentityScopeType.SCENE, "SC01", _c("hairstyle", IdentityStrength.LOCKED, "bob")),
            _profile(
                "P-other-shot", IdentityScopeType.SHOT, "SH99", _c("hairstyle", IdentityStrength.LOCKED, "long braid")
            ),
        ],
    )
    # The SH99-scoped lock is not on SH01's ancestry, so it never contributes:
    # no phantom conflict, no phantom provenance.
    assert resolved.status is ResolvedIdentityStatus.RESOLVED
    assert _by_key(resolved)["hairstyle"].effective_value == "bob"
    assert "P-other-shot" not in resolved.contributing_profile_refs
    assert resolved.observed_profile_versions == ["P-scene@1"]


def test_episode_scope_outranks_format_scope_deterministically() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry={
            IdentityScopeType.FORMAT: "FMT-explainer",
            IdentityScopeType.EPISODE: "EP01",
            IdentityScopeType.SHOT: "SH01",
        },
        profiles=[
            _profile(
                "P-fmt", IdentityScopeType.FORMAT, "FMT-explainer", _c("palette", IdentityStrength.PREFERRED, "cool")
            ),
            _profile("P-ep", IdentityScopeType.EPISODE, "EP01", _c("palette", IdentityStrength.PREFERRED, "warm")),
        ],
    )
    palette = _by_key(resolved)["palette"]
    assert palette.effective_value == "warm"
    assert palette.source_scope_ref == "EP01"


def test_sibling_format_profile_off_the_ancestry_is_dropped() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry={IdentityScopeType.FORMAT: "FMT-a", IdentityScopeType.SHOT: "SH01"},
        profiles=[
            _profile("P-fmt-a", IdentityScopeType.FORMAT, "FMT-a", _c("palette", IdentityStrength.LOCKED, "warm")),
            _profile("P-fmt-b", IdentityScopeType.FORMAT, "FMT-b", _c("palette", IdentityStrength.LOCKED, "cool")),
        ],
    )
    assert resolved.status is ResolvedIdentityStatus.RESOLVED
    assert _by_key(resolved)["palette"].effective_value == "warm"
    assert resolved.contributing_profile_refs == ["P-fmt-a"]


def test_unscoped_profile_always_contributes_as_the_broad_base() -> None:
    resolved = _resolver().resolve(
        target_ref="SH01",
        scope_ancestry={IdentityScopeType.SHOT: "SH01"},
        profiles=[_profile("P-flat", None, None, hairstyle_lock="bob")],
    )
    assert _by_key(resolved)["hairstyle"].effective_value == "bob"
    assert resolved.contributing_profile_refs == ["P-flat"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
