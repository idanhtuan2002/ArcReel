from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_default_auto_has_no_checkpoints_and_semi_requires_two(policy_data: dict):
    from r2.contracts.automation import AutomationMode, Checkpoint, RunPolicy

    automatic = RunPolicy.model_validate(policy_data)
    semi = RunPolicy.model_validate({**policy_data, "mode": "semi"})
    assert automatic.mode is AutomationMode.AUTO
    assert automatic.checkpoints == frozenset()
    assert semi.checkpoints == {Checkpoint.SCRIPT_PACKAGE, Checkpoint.FINAL_FILM}


@pytest.mark.parametrize(
    ("field", "value"), [("max_model_calls", True), ("max_tasks", 0), ("max_cost_minor_units", -1)]
)
def test_invalid_budget_cannot_be_accepted(policy_data: dict, field: str, value):
    from r2.contracts.automation import RunPolicy

    with pytest.raises(ValidationError):
        RunPolicy.model_validate({**policy_data, field: value})


@pytest.mark.parametrize("field", ["max_cost_minor_units", "max_model_calls", "max_tasks", "max_runtime_seconds"])
def test_policy_requires_explicit_total_caps(policy_data: dict, field: str):
    from r2.contracts.automation import RunPolicy

    policy_data.pop(field)
    with pytest.raises(ValidationError):
        RunPolicy.model_validate(policy_data)


@pytest.mark.parametrize(
    "override",
    [
        {"mode": "auto", "checkpoints": ["FINAL_FILM"]},
        {"unit_repair_limit": 3},
        {"final_evaluation_limit": 4},
        {"unknown": "ignored"},
        {"profile_id": " fiction_narration_vi_v1"},
    ],
)
def test_policy_refuses_ambiguous_or_expanded_scope(policy_data: dict, override: dict):
    from r2.contracts.automation import RunPolicy

    with pytest.raises(ValidationError):
        RunPolicy.model_validate({**policy_data, **override})


def test_policy_snapshot_cannot_be_mutated(policy_data: dict):
    from r2.contracts.automation import RunPolicy

    policy = RunPolicy.model_validate(policy_data)
    with pytest.raises(ValidationError):
        policy.mode = "semi"


def test_policy_digest_ignores_checkpoint_input_order(policy_data: dict):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import RunPolicy

    first = RunPolicy.model_validate({**policy_data, "mode": "semi", "checkpoints": ["SCRIPT_PACKAGE", "FINAL_FILM"]})
    second = RunPolicy.model_validate({**policy_data, "mode": "semi", "checkpoints": ["FINAL_FILM", "SCRIPT_PACKAGE"]})
    assert policy_digest(first) == policy_digest(second)
    changed = RunPolicy.model_validate({**policy_data, "mode": "semi", "max_model_calls": 199})
    assert policy_digest(first) != policy_digest(changed)


def test_duplicate_targets_are_not_a_valid_run(run_data: dict):
    from r2.contracts.automation import RunSnapshot

    with pytest.raises(ValidationError):
        RunSnapshot.model_validate({**run_data, "targets": ["episode:1", "episode:1"]})


def test_succeeded_run_requires_every_verified_target(run_data: dict):
    from r2.contracts.automation import RunSnapshot

    with pytest.raises(ValidationError):
        RunSnapshot.model_validate({**run_data, "status": "SUCCEEDED"})
