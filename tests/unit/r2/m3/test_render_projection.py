from pathlib import Path

import pytest

from r2.contracts.enums import ProductionMethod
from r2.m3.director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from r2.m3.factual_fixture import load_golden_a_factual_bundle
from r2.m3.render_projection import UnimplementedRenderMethodError, project_shot_to_cut


def _shots():
    script = load_golden_a_factual_bundle().script
    return GoldenAOpenMontageAdapter(FixtureOpenMontageBackend()).direct(script).shots


def test_reuse_without_bound_source_raises():
    shot = _shots()[0]
    with pytest.raises(ValueError, match="REUSE requires"):
        project_shot_to_cut(shot, method=ProductionMethod.REUSE, bound_source=None, display_text=None)


def test_reuse_produces_a_video_passthrough_cut_with_the_exact_bound_source():
    shot = _shots()[0]
    source = Path("r2/m3/fixtures/assets/reused_terminal_frame.svg")
    cut = project_shot_to_cut(shot, method=ProductionMethod.REUSE, bound_source=source, display_text=None)
    assert cut.kind == "video_passthrough"
    assert cut.source_path == source
    assert cut.text is None
    assert cut.cut_id == shot.id
    assert cut.in_seconds == 0.0
    assert cut.out_seconds == float(shot.target_duration)


def test_deterministic_without_display_text_raises():
    shot = _shots()[1]
    with pytest.raises(ValueError, match="requires real display text"):
        project_shot_to_cut(shot, method=ProductionMethod.DETERMINISTIC, bound_source=None, display_text=None)


def test_deterministic_produces_a_text_card_cut_with_the_exact_display_text():
    shot = _shots()[1]
    claim_text = "git commit records the current index contents as a new commit."
    cut = project_shot_to_cut(shot, method=ProductionMethod.DETERMINISTIC, bound_source=None, display_text=claim_text)
    assert cut.kind == "text_card"
    assert cut.text == claim_text
    assert cut.source_path is None


@pytest.mark.parametrize(
    "method",
    [
        ProductionMethod.STOCK,
        ProductionMethod.SCREEN_CAPTURE,
        ProductionMethod.GENERATED_IMAGE,
        ProductionMethod.GENERATED_VIDEO,
        ProductionMethod.COMPOSITE,
    ],
)
def test_out_of_scope_methods_raise_explicitly_never_fall_back_to_a_placeholder(method):
    shot = _shots()[0]
    with pytest.raises(UnimplementedRenderMethodError):
        project_shot_to_cut(shot, method=method, bound_source=None, display_text=None)
