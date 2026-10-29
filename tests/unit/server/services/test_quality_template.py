"""The M10-C profile template is a complete V2 policy bound to the embedded host catalog."""

from __future__ import annotations

import pytest

import r2.contracts.quality as q
from r2.quality.host_catalog import CONTAINER_CONFIG, DECODE_CONFIG
from r2.quality.probes import config_digest
from r2.quality.runs import HUMAN_SHOWRUNNER_POLICY_ID, human_showrunner_policy_digest
from server.services.quality_template import default_platform_constraints, quality_policy


def _policy(**changes) -> q.QualityPolicyV2:
    constraints = default_platform_constraints(
        platform_profile_id="youtube-long",
        width=1920,
        height=1080,
        min_duration_ms=60000,
        max_duration_ms=900000,
        required_locales=("en",),
    )
    return quality_policy(constraints, **changes)


def test_each_probe_rule_binds_its_catalog_config() -> None:
    policy = _policy()
    assert {(r.rule_id, r.config_digest) for r in policy.probe_rules} == {
        (CONTAINER_CONFIG.rule_id, config_digest(CONTAINER_CONFIG)),
        (DECODE_CONFIG.rule_id, config_digest(DECODE_CONFIG)),
    }


def test_every_requirement_has_exactly_one_slot_so_independence_groups_never_collide() -> None:
    policy = _policy()
    assert [(r.requirement_id, [s.slot_id for s in r.slots]) for r in policy.assessment_requirements] == [
        ("technical-container", ["container"]),
        ("technical-decode", ["decode"]),
        ("review", ["human"]),
    ]
    human = policy.assessment_requirements[2].slots[0]
    assert (human.qualification_policy_id, human.qualification_policy_digest) == (
        HUMAN_SHOWRUNNER_POLICY_ID,
        human_showrunner_policy_digest(),
    )


def test_every_packaging_check_is_declared_once() -> None:
    checks = [rule.check_id for rule in _policy().platform_constraints.rules]
    assert sorted(checks) == sorted(q.PACKAGING_CHECK_CLASSES)


@pytest.mark.parametrize("effect", list(q.SupersessionEffect))
def test_the_operator_chooses_the_supersession_effect(effect: q.SupersessionEffect) -> None:
    assert {rule.supersession_effect for rule in _policy(supersession_effect=effect).freshness_rules} == {effect}


def test_integrity_rules_cannot_be_waived() -> None:
    with pytest.raises(ValueError, match="never waivable"):
        _policy(packaging_waiverable_rule_ids=("asset-video",))
