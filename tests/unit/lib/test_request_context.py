"""lib.request_context: entry-request binding and caller-supplied ID acceptance."""

from __future__ import annotations

import pytest

from lib.request_context import (
    accept_or_mint_request_id,
    bound_request_id,
    bound_task,
    current_request_id,
    current_task_id,
    new_request_id,
    task_attribution,
)


def test_no_request_is_bound_by_default() -> None:
    assert current_request_id() is None


def test_bound_request_id_is_visible_inside_and_reset_after() -> None:
    with bound_request_id("req-outer-0001"):
        assert current_request_id() == "req-outer-0001"
        with bound_request_id("req-inner-0002"):
            assert current_request_id() == "req-inner-0002"
        assert current_request_id() == "req-outer-0001"
    assert current_request_id() is None


def test_minted_ids_are_unique_and_accepted_when_echoed() -> None:
    first, second = new_request_id(), new_request_id()
    assert first != second
    assert accept_or_mint_request_id(first) == first


@pytest.mark.parametrize(
    "candidate",
    [None, "", "short", "has space inside", "a/b/../etc/passwd", "x" * 129, "Bearer sk-live-secret"],
)
def test_malformed_caller_ids_are_replaced(candidate: str | None) -> None:
    minted = accept_or_mint_request_id(candidate)
    assert minted != candidate
    assert minted.startswith("req_")


def test_bound_task_binds_task_and_its_request_then_restores() -> None:
    assert task_attribution() == {}
    with bound_request_id("req-http-000001"):
        with bound_task("T-1", request_id="req-origin-0001"):
            assert current_task_id() == "T-1"
            assert current_request_id() == "req-origin-0001"
            assert task_attribution() == {"task_id": "T-1"}
        assert current_task_id() is None
        assert current_request_id() == "req-http-000001"
