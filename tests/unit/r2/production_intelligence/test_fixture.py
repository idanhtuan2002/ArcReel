"""D09 — canonical 12-shot fixture coverage."""

from __future__ import annotations

import pytest

from r2.contracts import DirectorKind, ProductionMethod
from r2.production_intelligence.fixture_loader import load_m4_golden_12


def test_fixture_has_twelve_unique_shots() -> None:
    fixture = load_m4_golden_12()
    assert len(fixture.cases) == 12
    assert len({c.shot.id for c in fixture.cases}) == 12


def test_fixture_exercises_all_three_directors() -> None:
    fixture = load_m4_golden_12()
    assert {c.director for c in fixture.cases} == set(DirectorKind)


def test_fixture_exercises_all_seven_production_methods() -> None:
    fixture = load_m4_golden_12()
    assert {c.method for c in fixture.cases} == set(ProductionMethod)


def test_fixture_baseline_shot_method_table_is_exact() -> None:
    fixture = load_m4_golden_12()
    table = {c.shot.id: (c.director, c.method) for c in fixture.cases}
    assert table == {
        "SH01": (DirectorKind.OPENMONTAGE, ProductionMethod.REUSE),
        "SH02": (DirectorKind.OPENMONTAGE, ProductionMethod.SCREEN_CAPTURE),
        "SH03": (DirectorKind.OPENMONTAGE, ProductionMethod.DETERMINISTIC),
        "SH04": (DirectorKind.OPENMONTAGE, ProductionMethod.COMPOSITE),
        "SH05": (DirectorKind.TAKE, ProductionMethod.GENERATED_IMAGE),
        "SH06": (DirectorKind.TAKE, ProductionMethod.GENERATED_VIDEO),
        "SH07": (DirectorKind.TAKE, ProductionMethod.GENERATED_VIDEO),
        "SH08": (DirectorKind.TAKE, ProductionMethod.COMPOSITE),
        "SH09": (DirectorKind.ARCREEL_NATIVE, ProductionMethod.STOCK),
        "SH10": (DirectorKind.ARCREEL_NATIVE, ProductionMethod.DETERMINISTIC),
        "SH11": (DirectorKind.ARCREEL_NATIVE, ProductionMethod.GENERATED_IMAGE),
        "SH12": (DirectorKind.ARCREEL_NATIVE, ProductionMethod.GENERATED_VIDEO),
    }


def test_fixture_loader_is_deterministic() -> None:
    a = load_m4_golden_12()
    b = load_m4_golden_12()
    assert [c.shot.model_dump(mode="json") for c in a.cases] == [c.shot.model_dump(mode="json") for c in b.cases]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
