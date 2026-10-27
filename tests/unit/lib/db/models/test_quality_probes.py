"""Probe custody tables are scoped, restrictive and bound to the M7 attempt they record."""

from __future__ import annotations

from lib.db.models import QualityProbeInvocationModel, QualityProbeObservationModel, QualityProbeResultModel


def keys(model) -> dict[str, tuple[tuple[str, ...], str, str | None, bool | None]]:
    return {
        constraint.name: (
            tuple(column.name for column in constraint.columns),
            constraint.referred_table.name,
            constraint.ondelete,
            constraint.deferrable,
        )
        for constraint in model.__table__.foreign_key_constraints
        if constraint.name
    }


def test_invocation_is_keyed_by_full_command_and_bound_to_a_deferred_m7_attempt() -> None:
    table = QualityProbeInvocationModel.__table__
    assert [column.name for column in table.primary_key] == ["user_id", "project_name", "actor_id", "execution_ref"]
    assert keys(QualityProbeInvocationModel)["fk_m10_probe_invocations_attempt"] == (
        ("user_id", "project_name", "execution_id"),
        "execution_attempts",
        "RESTRICT",
        True,
    )
    unique = {
        constraint.name for constraint in table.constraints if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert {"uq_m10_probe_invocations_execution", "uq_m10_probe_invocations_observation"} <= unique


def test_result_and_observation_cannot_exist_without_their_scoped_invocation() -> None:
    assert keys(QualityProbeResultModel)["fk_m10_probe_results_invocation"][:3] == (
        ("user_id", "project_name", "execution_id"),
        "m10_quality_probe_invocations",
        "RESTRICT",
    )
    observation = keys(QualityProbeObservationModel)
    assert observation["fk_m10_probe_observations_invocation"][1] == "m10_quality_probe_invocations"
    assert observation["fk_m10_probe_observations_reserved_id"][0] == ("user_id", "project_name", "observation_id")
    assert observation["fk_m10_probe_observations_result"][1] == "m10_quality_probe_results"
    for model in (QualityProbeInvocationModel, QualityProbeResultModel, QualityProbeObservationModel):
        user = next(key for key in model.__table__.foreign_key_constraints if key.referred_table.name == "users")
        assert user.ondelete == "RESTRICT"
