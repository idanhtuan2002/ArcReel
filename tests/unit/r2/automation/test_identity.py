from __future__ import annotations

import pytest


@pytest.fixture
def identity_args() -> dict:
    return {
        "run_id": "run-1",
        "stage": "STORY",
        "unit_key": "manuscript",
        "generation": 1,
        "input_digest": "sha256:" + "a" * 64,
        "policy_digest": "sha256:" + "b" * 64,
        "repair_index": 0,
    }


def test_same_command_identity_replays_exactly(identity_args: dict):
    from r2.automation.identity import derive_step_identity

    first = derive_step_identity(**identity_args)
    assert first == derive_step_identity(**identity_args)
    assert len(first.command_id) > 16


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "run-2"},
        {"unit_key": "chapter:2"},
        {"stage": "SCRIPT"},
        {"generation": 2},
        {"input_digest": "sha256:" + "c" * 64},
        {"policy_digest": "sha256:" + "c" * 64},
        {"repair_index": 1},
    ],
)
def test_every_dispatch_authority_input_changes_identity(identity_args: dict, change: dict):
    from r2.automation.identity import derive_step_identity

    first = derive_step_identity(**identity_args)
    second = derive_step_identity(**{**identity_args, **change})
    assert first.command_id != second.command_id
    assert first.task_id != second.task_id


def test_invalid_scope_cannot_be_hashed_into_identity(identity_args: dict):
    from r2.automation.identity import derive_step_identity

    with pytest.raises(ValueError, match="generation"):
        derive_step_identity(**{**identity_args, "generation": 0})
