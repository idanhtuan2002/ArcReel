"""Unit coverage for the pure M6 Western-generic evaluator (plan Task 9).

Screenplay surface failures, evidence locations, deterministic finding order,
slow-burn/tragic/unresolved counterexamples, and absence of numeric craft gating.
"""

from __future__ import annotations

import json

from r2.adaptation.profiles import _PACKS_DIR, ProfilePackRegistry, _compute_policy_pack_digest
from r2.adaptation.western_profile import evaluate_western
from r2.contracts.adaptation import AdaptationProfileId, AdaptationProfileRef, FindingDisposition
from tests.fixtures.r2.m6_western_profile import (
    golden_western_screenplay,
    screenplay_with_bad_scene_heading,
    screenplay_with_duplicate_scene_id,
    screenplay_with_interiority_leak,
    screenplay_with_orphan_reference,
    screenplay_with_unseparated_action,
    slow_burn_screenplay,
)


def _western_pack():
    raw = json.loads((_PACKS_DIR / "western_generic_v1.json").read_bytes())
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )
    return ProfilePackRegistry().resolve(ref)


def test_a_well_formed_screenplay_has_no_format_findings() -> None:
    analysis = evaluate_western(golden_western_screenplay(), profile_pack=_western_pack())
    assert analysis.format_findings == []
    assert analysis.schema_version == "r2-western-drama-analysis-v1"


def test_a_bad_scene_heading_is_a_profile_block_finding() -> None:
    analysis = evaluate_western(screenplay_with_bad_scene_heading(), profile_pack=_western_pack())
    assert len(analysis.format_findings) == 1
    finding = analysis.format_findings[0]
    assert finding.rule_id == "WESTERN_SCENE_HEADING_STRUCTURE"
    assert finding.disposition == FindingDisposition.PROFILE_BLOCK
    assert finding.target_path == "scenes[0].dramatic_text"


def test_unseparated_action_and_dialogue_is_a_profile_block_finding() -> None:
    analysis = evaluate_western(screenplay_with_unseparated_action(), profile_pack=_western_pack())
    assert any(f.rule_id == "WESTERN_ACTION_DIALOGUE_SEPARABILITY" for f in analysis.format_findings)


def test_an_interiority_leak_is_a_profile_block_finding_with_evidence() -> None:
    analysis = evaluate_western(screenplay_with_interiority_leak(), profile_pack=_western_pack())
    findings = [f for f in analysis.format_findings if f.rule_id == "WESTERN_ACTION_SURFACE_VISIBILITY"]
    assert len(findings) == 1
    assert findings[0].evidence_refs == [findings[0].target_path]
    assert findings[0].message_params["marker"] == "thinks that"


def test_an_orphan_source_mapping_ref_is_a_profile_block_finding() -> None:
    analysis = evaluate_western(screenplay_with_orphan_reference(), profile_pack=_western_pack())
    findings = [f for f in analysis.format_findings if f.rule_id == "WESTERN_SCREENPLAY_REFERENCE_INTEGRITY"]
    assert len(findings) == 1
    assert "entry-orphan" in findings[0].source_span


def test_a_duplicate_scene_id_is_a_profile_block_finding() -> None:
    analysis = evaluate_western(screenplay_with_duplicate_scene_id(), profile_pack=_western_pack())
    findings = [f for f in analysis.format_findings if f.rule_id == "WESTERN_DELIVERY_CONSTRAINTS"]
    assert len(findings) == 1
    assert findings[0].source_span == "scene-1"


def test_every_finding_carries_a_stable_evidence_location() -> None:
    analysis = evaluate_western(screenplay_with_bad_scene_heading(), profile_pack=_western_pack())
    for finding in analysis.format_findings:
        assert finding.evidence_refs
        assert finding.target_path in finding.evidence_refs


def test_evaluation_is_deterministic_across_repeated_calls() -> None:
    screenplay = screenplay_with_bad_scene_heading()
    pack = _western_pack()
    first = evaluate_western(screenplay, profile_pack=pack)
    second = evaluate_western(screenplay, profile_pack=pack)
    assert first == second
    assert first.content_hash == second.content_hash


def test_finding_order_is_stable_and_grouped_by_rule() -> None:
    analysis = evaluate_western(screenplay_with_duplicate_scene_id(), profile_pack=_western_pack())
    rule_ids = [f.rule_id for f in analysis.format_findings]
    assert rule_ids == sorted(rule_ids, key=rule_ids.index)  # each rule's findings stay contiguous, in emit order


# --- rubric: advisory only, no numeric craft gating ------------------------------------


def test_a_slow_burn_unresolved_excerpt_produces_no_block_and_only_advisory_rubric_observations() -> None:
    analysis = evaluate_western(slow_burn_screenplay(), profile_pack=_western_pack())
    assert analysis.format_findings == []
    assert len(analysis.rubric_observations) == 9
    assert all("no numeric score" in observation for observation in analysis.rubric_observations)


def test_rubric_observations_carry_evidence_locations_and_no_disposition_field() -> None:
    analysis = evaluate_western(golden_western_screenplay(), profile_pack=_western_pack())
    assert analysis.evidence_locations == ["scenes[0].scene_id=scene-1", "scenes[1].scene_id=scene-2"]
    for observation in analysis.rubric_observations:
        assert isinstance(observation, str)


def test_rubric_observations_never_block_regardless_of_screenplay_content() -> None:
    """No fixture, however dramatically thin, can ever produce a rubric-caused
    finding: rubric observations are plain strings, never ProfileFinding objects,
    so there is no disposition field for a rubric concept to set to a blocking value."""
    for builder in (golden_western_screenplay, slow_burn_screenplay, screenplay_with_bad_scene_heading):
        analysis = evaluate_western(builder(), profile_pack=_western_pack())
        assert all(isinstance(observation, str) for observation in analysis.rubric_observations)
        assert all(finding.rule_id != "WESTERN_RUBRIC_DRAMATIC_STRUCTURE" for finding in analysis.format_findings)
