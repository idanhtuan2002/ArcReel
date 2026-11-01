"""Ports between the production controller and the domain owners it drives.

Owners keep authority over their own writes: a receipt or outcome returned through a port is evidence the
controller inspects, never a proof that substitutes for the owner's locked final check.
"""

from __future__ import annotations

from typing import Protocol

from r2.contracts.automation import (
    AutomationContract,
    AutomationMode,
    BudgetReservation,
    DispatchIntent,
    ExactIdentity,
    NonnegativeInt,
    OwnerReceipt,
    PreflightReport,
    RunPolicy,
    RunSnapshot,
    StageOutcome,
    UsageReceipt,
)


class StepPlan(AutomationContract):
    """One owner command for the run's current stage; estimates are reserved before dispatch."""

    unit_key: ExactIdentity
    input_refs: tuple[OwnerReceipt, ...] = ()
    estimated_cost_minor_units: NonnegativeInt
    estimated_model_calls: NonnegativeInt
    estimated_tasks: NonnegativeInt
    estimated_runtime_seconds: NonnegativeInt


class OwnerAdapter(Protocol):
    """Drives one RunStage through its owner; every method is idempotent on the intent's task ID."""

    owner: str

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        """Deterministic for one run stage, generation, input and policy."""
        ...

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        """Submit, or return the receipt of the command already submitted under ``intent.identity.task_id``."""
        ...

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        """Read owner state for the intent's identity; ``WAIT`` while the owner has not finished."""
        ...

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        """The owner's verified usage for a finished command, or ``None`` when it cannot be established."""
        ...


class InputWitness(Protocol):
    """Digest of the project inputs a run consumes but does not own; run-owned revisions never move it."""

    async def digest(self, *, user_id: str, project_name: str) -> str: ...


class PolicyResolver(Protocol):
    """The frozen policy a new run in ``mode`` would use; resolving it grants nothing."""

    async def resolve(self, *, user_id: str, project_name: str, mode: AutomationMode) -> RunPolicy: ...


class PreflightCheck(Protocol):
    """Read-only prerequisites for a policy; see ``server.production_run.preflight.ProductionPreflight``."""

    async def check(self, *, user_id: str, project_name: str, policy: RunPolicy) -> PreflightReport: ...


__all__ = ["InputWitness", "OwnerAdapter", "PolicyResolver", "PreflightCheck", "StepPlan"]
