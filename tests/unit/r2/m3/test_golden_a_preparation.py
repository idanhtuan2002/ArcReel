import pytest

from r2.contracts.enums import ProductionMethod, ReadinessState
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.preparation import GoldenAProductionPreparation


def directed_shots():
    script = load_golden_a_factual_bundle().script
    return GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script).shots


def by_id(items):
    return {item.shot.id: item for item in items}


def test_golden_a_assigns_reuse_and_deterministic_methods():
    prepared = by_id(
        GoldenAProductionPreparation().prepare(
            directed_shots(),
            reused_asset_ref="asset:golden-a/reused-terminal-frame",
        )
    )
    assert prepared["SH01"].method.method is ProductionMethod.REUSE
    assert prepared["SH02"].method.method is ProductionMethod.DETERMINISTIC
    assert prepared["SH03"].method.method is ProductionMethod.DETERMINISTIC
    assert prepared["SH04"].method.method is ProductionMethod.DETERMINISTIC
    assert all(item.readiness.state is ReadinessState.READY for item in prepared.values())


def test_reuse_shot_is_blocked_when_required_binding_is_missing():
    prepared = by_id(
        GoldenAProductionPreparation().prepare(
            directed_shots(),
            reused_asset_ref=None,
        )
    )
    sh01 = prepared["SH01"]
    assert sh01.readiness.state is ReadinessState.BLOCKED
    assert sh01.bindings == ()
    assert sh01.readiness.requirements[0].required is True
    assert sh01.readiness.requirements[0].resolved_binding is None


def test_assignment_must_be_allowed_by_shot_spec():
    shots = list(directed_shots())
    sh01 = shots[0].model_copy(update={"allowed_methods": [ProductionMethod.DETERMINISTIC]})
    with pytest.raises(ValueError, match="allowed"):
        GoldenAProductionPreparation().prepare(
            [sh01, *shots[1:]],
            reused_asset_ref="asset:golden-a/reused-terminal-frame",
        )
