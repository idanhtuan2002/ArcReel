"""Pure ``WESTERN_GENERIC`` evaluator (plan Task 9).

``evaluate_western`` is deterministic and provider-neutral: its only inputs are the
screenplay under evaluation and the exact resolved ``ProfilePack`` it evaluates
against, and it makes no I/O call. It evaluates only what is structurally observable
from the screenplay's own content — the five ``WESTERN_*`` rules the pack declares
with ``applicability=WESTERN_GENERIC``. The pack's nine ``ALWAYS``-scoped shared
rules (Canon/branch/map lineage, candidate/master currentness, and the rest of spec
section 5.1) need context this evaluator is never given — Canon, the branch, the
map, production candidates — so it emits no finding for them at all; they are
validated where that context actually lives (``AdaptationEvidenceService``,
``AdaptationAuthorityService``, Task 12's admission).

The nine spec section 5.2 rubric concepts (problem, goal/action, opposition, stakes,
cause/effect, escalation, revelation, reversal, resolution) are never scored: this
evaluator has no semantic understanding of dramatic structure, so it reports only
that scene-level evidence exists for each concept, in a fixed order, and asserts no
verdict about narrative completeness. A valid slow-burn, tragic, or unresolved
excerpt can never fail this evaluator on rubric grounds — there is no code path by
which a rubric concept becomes a blocking finding.
"""

from __future__ import annotations

from r2.adaptation.errors import AdaptationProfileMismatchError
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.profiles import ProfilePack
from r2.contracts.adaptation import (
    AdaptationProfileId,
    FindingDisposition,
    ProfileFinding,
    ScreenplayArtifactV2,
    WesternDramaAnalysis,
)

_VALID_SLUGLINE_PREFIXES = ("INT.", "EXT.", "INT/EXT.", "I/E.")
_INTERIORITY_MARKERS = ("thinks that", "feels that", "realizes that", "remembers that", "knows that")
_RUBRIC_CONCEPTS = (
    "problem",
    "goal_action",
    "opposition",
    "stakes",
    "cause_effect",
    "escalation",
    "revelation",
    "reversal",
    "resolution",
)

_DISPOSITION_SEVERITY = {
    FindingDisposition.INTEGRITY_BLOCK: "BLOCKING",
    FindingDisposition.PROFILE_BLOCK: "BLOCKING",
    FindingDisposition.ADVISORY: "ADVISORY",
    FindingDisposition.NOT_APPLICABLE: "NONE",
}


def _rule(profile_pack: ProfilePack, rule_id: str):
    for rule in profile_pack.rules:
        if rule.rule_id == rule_id:
            return rule
    raise AdaptationProfileMismatchError(
        f"profile pack for {profile_pack.ref.profile_id.value!r} does not declare required rule {rule_id!r}"
    )


def _finding(
    profile_pack: ProfilePack,
    *,
    rule_id: str,
    finding_id: str,
    target_path: str,
    source_span: str,
    **message_params: str,
) -> ProfileFinding:
    rule = _rule(profile_pack, rule_id)
    return ProfileFinding(
        finding_id=finding_id,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        disposition=rule.disposition,
        applicability=rule.applicability.value,
        severity=_DISPOSITION_SEVERITY[rule.disposition],
        target_path=target_path,
        source_span=source_span,
        evidence_refs=[target_path],
        message_params=dict(message_params),
    )


def _scene_heading_findings(screenplay: ScreenplayArtifactV2, profile_pack: ProfilePack) -> list[ProfileFinding]:
    findings: list[ProfileFinding] = []
    for index, scene in enumerate(screenplay.scenes):
        if scene.dramatic_text.strip().upper().startswith(_VALID_SLUGLINE_PREFIXES):
            continue
        findings.append(
            _finding(
                profile_pack,
                rule_id="WESTERN_SCENE_HEADING_STRUCTURE",
                finding_id=f"WESTERN_SCENE_HEADING_STRUCTURE:{scene.scene_id}",
                target_path=f"scenes[{index}].dramatic_text",
                source_span=scene.dramatic_text[:80],
                scene_id=scene.scene_id,
            )
        )
    return findings


def _action_dialogue_separability_findings(
    screenplay: ScreenplayArtifactV2, profile_pack: ProfilePack
) -> list[ProfileFinding]:
    findings: list[ProfileFinding] = []
    for index, scene in enumerate(screenplay.scenes):
        if len(scene.dramatic_text.splitlines()) >= 2:
            continue
        findings.append(
            _finding(
                profile_pack,
                rule_id="WESTERN_ACTION_DIALOGUE_SEPARABILITY",
                finding_id=f"WESTERN_ACTION_DIALOGUE_SEPARABILITY:{scene.scene_id}",
                target_path=f"scenes[{index}].dramatic_text",
                source_span=scene.dramatic_text[:80],
                scene_id=scene.scene_id,
            )
        )
    return findings


def _action_surface_visibility_findings(
    screenplay: ScreenplayArtifactV2, profile_pack: ProfilePack
) -> list[ProfileFinding]:
    findings: list[ProfileFinding] = []
    for index, scene in enumerate(screenplay.scenes):
        lowered = scene.dramatic_text.lower()
        marker = next((needle for needle in _INTERIORITY_MARKERS if needle in lowered), None)
        if marker is None:
            continue
        findings.append(
            _finding(
                profile_pack,
                rule_id="WESTERN_ACTION_SURFACE_VISIBILITY",
                finding_id=f"WESTERN_ACTION_SURFACE_VISIBILITY:{scene.scene_id}",
                target_path=f"scenes[{index}].dramatic_text",
                source_span=scene.dramatic_text[:80],
                scene_id=scene.scene_id,
                marker=marker,
            )
        )
    return findings


def _reference_integrity_findings(screenplay: ScreenplayArtifactV2, profile_pack: ProfilePack) -> list[ProfileFinding]:
    top_level = set(screenplay.source_mapping_refs)
    findings: list[ProfileFinding] = []
    for index, scene in enumerate(screenplay.scenes):
        orphans = [ref for ref in scene.source_mapping_refs if ref not in top_level]
        if not orphans:
            continue
        findings.append(
            _finding(
                profile_pack,
                rule_id="WESTERN_SCREENPLAY_REFERENCE_INTEGRITY",
                finding_id=f"WESTERN_SCREENPLAY_REFERENCE_INTEGRITY:{scene.scene_id}",
                target_path=f"scenes[{index}].source_mapping_refs",
                source_span=",".join(orphans),
                scene_id=scene.scene_id,
                orphan_refs=",".join(orphans),
            )
        )
    return findings


def _delivery_constraint_findings(screenplay: ScreenplayArtifactV2, profile_pack: ProfilePack) -> list[ProfileFinding]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for scene in screenplay.scenes:
        if scene.scene_id in seen and scene.scene_id not in duplicates:
            duplicates.append(scene.scene_id)
        seen.add(scene.scene_id)
    if not duplicates:
        return []
    return [
        _finding(
            profile_pack,
            rule_id="WESTERN_DELIVERY_CONSTRAINTS",
            finding_id=f"WESTERN_DELIVERY_CONSTRAINTS:{scene_id}",
            target_path="scenes[*].scene_id",
            source_span=scene_id,
            scene_id=scene_id,
        )
        for scene_id in duplicates
    ]


def _rubric_observations(screenplay: ScreenplayArtifactV2) -> tuple[list[str], list[str]]:
    evidence_locations = [f"scenes[{index}].scene_id={scene.scene_id}" for index, scene in enumerate(screenplay.scenes)]
    observations = [
        f"{concept}: {len(screenplay.scenes)} scene(s) available as evidence; no numeric score or fixed beat "
        "timestamp applied"
        for concept in _RUBRIC_CONCEPTS
    ]
    return observations, evidence_locations


def evaluate_western(screenplay: ScreenplayArtifactV2, *, profile_pack: ProfilePack) -> WesternDramaAnalysis:
    if profile_pack.ref.profile_id != AdaptationProfileId.WESTERN_GENERIC:
        raise AdaptationProfileMismatchError(
            f"evaluate_western requires a WESTERN_GENERIC profile pack, got {profile_pack.ref.profile_id.value!r}"
        )

    format_findings = [
        *_scene_heading_findings(screenplay, profile_pack),
        *_action_dialogue_separability_findings(screenplay, profile_pack),
        *_action_surface_visibility_findings(screenplay, profile_pack),
        *_reference_integrity_findings(screenplay, profile_pack),
        *_delivery_constraint_findings(screenplay, profile_pack),
    ]
    rubric_observations, evidence_locations = _rubric_observations(screenplay)

    draft = WesternDramaAnalysis(
        schema_version="r2-western-drama-analysis-v1",
        content_hash="pending",
        format_findings=format_findings,
        rubric_observations=rubric_observations,
        evidence_locations=evidence_locations,
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


__all__ = ["evaluate_western"]
