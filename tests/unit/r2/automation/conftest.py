from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture
def policy_data() -> dict:
    return {
        "profile_id": "fiction_narration_vi_v1",
        "profile_digest": "sha256:" + "a" * 64,
        "currency": "USD",
        "max_cost_minor_units": 500,
        "max_model_calls": 200,
        "max_tasks": 100,
        "max_runtime_seconds": 21600,
        "route_digests": ["sha256:" + "b" * 64],
    }


@pytest.fixture
def run_data(policy_data: dict) -> dict:
    return {
        "user_id": "u1",
        "project_name": "film",
        "run_id": "run-1",
        "policy": policy_data,
        "input_digest": "sha256:" + "c" * 64,
        "status": "RUNNING",
        "targets": ["episode:1"],
        "created_at": datetime(2026, 10, 30, tzinfo=UTC),
    }
