"""The M10-C quality profile template: a complete V2 policy over the embedded host-v1 probe catalog.

Three one-slot requirements (container probe, decode probe, Human review) so independence groups never collide;
platform constraints come from the operator with every packaging check rule declared. Policy bodies that have no
accepted registry (deterministic-probe qualification, single-slot disagreement, no reference eligibility) are
schema-tagged canonical hashes, bound only as data the accepted services copy.
"""

from __future__ import annotations

import hashlib
from typing import Any

import r2.contracts.quality as q
from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.host_catalog import CONTAINER_CONFIG, DECODE_CONFIG
from r2.quality.probes import ProbeConfig, config_digest, policy_digest
from r2.quality.runs import HUMAN_SHOWRUNNER_POLICY_ID, human_showrunner_policy_digest

REVIEW_RULE_ID = "review"
TECHNICAL_FRESHNESS_RULE_ID = "fresh-technical"
REVIEW_FRESHNESS_RULE_ID = "fresh-review"
FRESHNESS_SECONDS = 7 * 24 * 3600
REQUIREMENTS = {"technical-container": "container", "technical-decode": "decode", "review": "human"}


def private_digest(schema: str, body: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of a schema-tagged body (no registered M10-A domain)."""
    return "sha256:" + hashlib.sha256(canonical_json_bytes({"schema": schema} | body)).hexdigest()


PROBE_QUALIFICATION_ID = "m10-c.qualification.host-deterministic-probe.v1"
PROBE_QUALIFICATION_DIGEST = private_digest(
    PROBE_QUALIFICATION_ID, {"proof": "A4 confined probe run of a host-v1 catalog config bound by config digest"}
)
DISAGREEMENT_ID = "m10-c.disagreement.single-slot.v1"
DISAGREEMENT_DIGEST = private_digest(DISAGREEMENT_ID, {"rule": "one slot per requirement; no disagreement possible"})
REFERENCE_ELIGIBILITY_ID = "m10-c.reference-eligibility.none.v1"
REFERENCE_ELIGIBILITY_DIGEST = private_digest(REFERENCE_ELIGIBILITY_ID, {"rule": "no reference-based recipe"})


def _probe_rule(config: ProbeConfig) -> dict[str, Any]:
    primary = config.primary_tool()
    return {
        "rule_id": config.rule_id,
        "probe_kind": config.recipe,
        "tool_identity": primary.name,
        "tool_version_constraint": "==" + primary.version,
        "config_schema_id": config.schema_id,
        "config_digest": config_digest(config),
        "applicability_policy_id": config.applicability_policy.policy_id,
        "applicability_policy_digest": policy_digest(config.applicability_policy),
        "threshold_policy_id": config.threshold_policy.policy_id,
        "threshold_policy_digest": policy_digest(config.threshold_policy),
        "max_runtime_ms": config.max_runtime_ms,
        "max_output_bytes": config.max_output_bytes,
    }


def _technical(requirement_id: str, slot_id: str, rule_id: str) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "mode": "ALL",
        "slots": [
            {
                "slot_id": slot_id,
                "kind": "TECHNICAL",
                "assessor_class": "DETERMINISTIC",
                "qualification_policy_id": PROBE_QUALIFICATION_ID,
                "qualification_policy_digest": PROBE_QUALIFICATION_DIGEST,
                "rule_ids": [rule_id],
                "allowed_applicability_states": ["PASS", "FAIL", "INDETERMINATE", "INAPPLICABLE"],
                "producer_conflict_forbidden": True,
                "required_independence_groups": 1,
            }
        ],
        "minimum_satisfied_slots": 1,
        "disagreement_policy_id": DISAGREEMENT_ID,
        "disagreement_policy_digest": DISAGREEMENT_DIGEST,
        "escalation_requirement_id": None,
    }


def _review() -> dict[str, Any]:
    return {
        "requirement_id": "review",
        "mode": "ALL",
        "slots": [
            {
                "slot_id": "human",
                "kind": "NARRATIVE",
                "assessor_class": "HUMAN",
                "qualification_policy_id": HUMAN_SHOWRUNNER_POLICY_ID,
                "qualification_policy_digest": human_showrunner_policy_digest(),
                "rule_ids": [REVIEW_RULE_ID],
                "allowed_applicability_states": ["PASS", "FAIL", "INDETERMINATE"],
                "producer_conflict_forbidden": True,
                "required_independence_groups": 1,
            }
        ],
        "minimum_satisfied_slots": 1,
        "disagreement_policy_id": DISAGREEMENT_ID,
        "disagreement_policy_digest": DISAGREEMENT_DIGEST,
        "escalation_requirement_id": None,
    }


def quality_policy(
    platform_constraints: dict[str, Any],
    *,
    supersession_effect: q.SupersessionEffect = q.SupersessionEffect.HISTORICAL_ONLY,
    packaging_waiverable_rule_ids: tuple[str, ...] = (),
) -> q.QualityPolicyV2:
    """The template V2 policy for these platform constraints; the contract validates every reference."""
    probes = (CONTAINER_CONFIG, DECODE_CONFIG)
    return q.QualityPolicyV2.model_validate(
        {
            "schema_id": "m10.quality-policy.v2",
            "rule_ids": [
                *(config.rule_id for config in probes),
                REVIEW_RULE_ID,
                TECHNICAL_FRESHNESS_RULE_ID,
                REVIEW_FRESHNESS_RULE_ID,
            ],
            "probe_rules": [_probe_rule(config) for config in probes],
            "assessment_requirements": [
                _technical("technical-container", "container", CONTAINER_CONFIG.rule_id),
                _technical("technical-decode", "decode", DECODE_CONFIG.rule_id),
                _review(),
            ],
            "freshness_rules": [
                {
                    "rule_id": TECHNICAL_FRESHNESS_RULE_ID,
                    "evidence_kind": "TECHNICAL",
                    "max_age_seconds": FRESHNESS_SECONDS,
                    "supersession_effect": supersession_effect,
                },
                {
                    "rule_id": REVIEW_FRESHNESS_RULE_ID,
                    "evidence_kind": "NARRATIVE",
                    "max_age_seconds": FRESHNESS_SECONDS,
                    "supersession_effect": supersession_effect,
                },
            ],
            "disposition_rule": {
                "max_disposition_ttl_seconds": 604800,
                "max_waiver_ttl_seconds": 86400,
                "waiverable_rule_ids": [REVIEW_RULE_ID],
                "non_waiverable_failure_codes": ["IDENTITY_INVALID"],
            },
            "accessibility_rules": [],
            "reference_eligibility_policy_id": REFERENCE_ELIGIBILITY_ID,
            "reference_eligibility_policy_digest": REFERENCE_ELIGIBILITY_DIGEST,
            "platform_constraints": platform_constraints,
            "packaging_waiverable_rule_ids": list(packaging_waiverable_rule_ids),
        }
    )


def default_platform_constraints(
    *,
    platform_profile_id: str,
    width: int,
    height: int,
    min_duration_ms: int,
    max_duration_ms: int,
    required_locales: tuple[str, ...],
) -> dict[str, Any]:
    """Editable platform constraints with every packaging check declared once (BLOCKING, banned phrases ADVISORY)."""
    rules = [
        {
            "rule_id": "asset-video",
            "check_id": "asset.required",
            "rule_class": "REQUIRED_ASSET",
            "severity": "BLOCKING",
        },
        {
            "rule_id": "asset-thumbnail",
            "check_id": "asset.integrity",
            "rule_class": "INTEGRITY",
            "severity": "BLOCKING",
        },
    ]
    declared = {rule["check_id"] for rule in rules}
    for check_id, rule_class in q.PACKAGING_CHECK_CLASSES.items():
        if check_id not in declared:
            severity = "ADVISORY" if check_id == "phrases.banned" else "BLOCKING"
            rules.append(
                {"rule_id": check_id, "check_id": check_id, "rule_class": rule_class.value, "severity": severity}
            )
    return {
        "schema_id": "m10.platform-constraints.v1",
        "platform_profile_id": platform_profile_id,
        "platform_profile_revision": 1,
        "min_duration_ms": min_duration_ms,
        "max_duration_ms": max_duration_ms,
        "width": width,
        "height": height,
        "title_max_chars": 100,
        "description_min_chars": 20,
        "description_max_chars": 5000,
        "plain_text_only": True,
        "title_required_terms": [],
        "description_required_terms": [],
        "banned_phrases": [],
        "tag_charset": "UNICODE_LETTERS_DIGITS_SPACE",
        "min_tags": 1,
        "max_tags": 15,
        "max_tag_chars": 30,
        "min_hashtags": 0,
        "max_hashtags": 3,
        "max_hashtag_chars": 30,
        "chapter_min_ms": 10000,
        "max_chapters": 20,
        "required_locales": list(required_locales),
        "max_variant_groups": 2,
        "max_variants_per_group": 3,
        "asset_roles": [
            {
                "role": "video",
                "constraint_rule_id": "asset-video",
                "required": True,
                "media_types": ["video/mp4"],
                "max_bytes": 2**31 - 1,
            },
            {
                "role": "thumbnail",
                "constraint_rule_id": "asset-thumbnail",
                "required": False,
                "media_types": ["image/png", "image/jpeg"],
                "max_bytes": 2097152,
            },
        ],
        "rules": rules,
    }


__all__ = [
    "DISAGREEMENT_DIGEST",
    "PROBE_QUALIFICATION_DIGEST",
    "REQUIREMENTS",
    "default_platform_constraints",
    "private_digest",
    "quality_policy",
]
