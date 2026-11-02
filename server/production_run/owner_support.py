"""Shared pieces of owner adapters: current authorization subjects, run inputs, outcomes and usage receipts.

An adapter authorizes each owner write against the run's current grant and version at that moment, never against
the snapshot it planned from; the owner then re-requires the same subject inside its own locked transaction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository
from lib.script_review import content_fingerprint_of_data
from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationOperation,
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunCommand,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)

type Sessions = async_sessionmaker[AsyncSession]


class OwnerBlocked(Exception):
    """The owner refused the command for a stable reason the run reports as its block reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def current_run(sessions: Sessions, intent: DispatchIntent) -> RunSnapshot:
    async with sessions() as session:
        run = await ProductionRunRepository(session).get(
            user_id=intent.scope.user_id, project_name=intent.scope.project_name, run_id=intent.scope.run_id
        )
    if run is None:
        raise ProductionRunConflict("RUN_NOT_FOUND")
    return run


async def current_subject(sessions: Sessions, intent: DispatchIntent, *, subject_digest: str) -> AuthorizationSubject:
    """The subject an owner write is authorized under now: the grant head and the run version as they stand."""
    run = await current_run(sessions, intent)
    async with sessions() as session:
        grant = await AutomationGrantRepository(session).head(intent.scope)
    if grant is None:
        raise PermissionError("AUTOMATION_GRANT_UNAVAILABLE")
    identity = intent.identity
    return AuthorizationSubject(
        user_id=intent.scope.user_id,
        project_name=intent.scope.project_name,
        run_id=intent.scope.run_id,
        grant_id=grant.grant_id,
        grant_version=grant.version,
        expected_run_version=run.version,
        generation=identity.generation,
        input_digest=identity.input_digest,
        policy_digest=identity.policy_digest,
        operation=AutomationOperation(identity.stage.value),
        command_id=identity.command_id,
        subject_digest=subject_digest,
    )


async def step_intent(sessions: Sessions, reservation: BudgetReservation) -> DispatchIntent:
    """The intent a budget reservation was made for."""
    async with sessions() as session:
        intent = await ProductionRunRepository(session).intent(
            scope=reservation.scope, command_id=reservation.command_id
        )
    if intent is None:
        raise OwnerBlocked("OUTCOME_UNKNOWN")
    return intent


async def start_command(sessions: Sessions, intent: DispatchIntent) -> RunCommand:
    async with sessions() as session:
        return await ProductionRunRepository(session).start_command(intent.scope)


async def stage_receipt(sessions: Sessions, run: RunSnapshot, stage: RunStage) -> OwnerReceipt | None:
    async with sessions() as session:
        return await ProductionRunRepository(session).stage_receipt(run=run, stage=stage)


async def required_outcome(sessions: Sessions, run: RunSnapshot, stage: RunStage) -> StageOutcome:
    """The passing outcome of an upstream stage in the run's current lineage."""
    async with sessions() as session:
        passed = await ProductionRunRepository(session).stage_outcome(run=run, stage=stage)
    if passed is None or not passed.receipts:
        raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
    return passed


async def required_receipt(sessions: Sessions, run: RunSnapshot, stage: RunStage) -> OwnerReceipt:
    receipt = await stage_receipt(sessions, run, stage)
    if receipt is None:
        raise OwnerBlocked("UPSTREAM_RECEIPT_MISSING")
    return receipt


def outcome(
    intent: DispatchIntent,
    kind: str,
    *,
    receipts: tuple[OwnerReceipt, ...] = (),
    owner_state: str | None = None,
    reason: str | None = None,
) -> StageOutcome:
    identity = intent.identity
    return StageOutcome.model_validate(
        {
            "stage": identity.stage,
            "generation": identity.generation,
            "input_digest": identity.input_digest,
            "policy_digest": identity.policy_digest,
            "kind": kind,
            "receipts": receipts,
            "owner_state": owner_state,
            "reason": reason,
            "unit_key": identity.unit_key,
        }
    )


def usage_receipt(
    receipt: OwnerReceipt,
    reservation: BudgetReservation,
    *,
    cost_minor_units: int = 0,
    model_calls: int = 0,
    tasks: int = 0,
    runtime_seconds: int = 0,
    known: bool = True,
) -> UsageReceipt:
    """The owner's measured usage for one finished command, in the reservation's currency."""
    return UsageReceipt(
        **{**receipt.model_dump(mode="python"), "receipt_ref": f"usage:{reservation.reservation_id}"},
        reservation_id=reservation.reservation_id,
        currency=reservation.currency,
        cost_minor_units=cost_minor_units,
        model_calls=model_calls,
        tasks=tasks,
        runtime_seconds=runtime_seconds,
        outcome="KNOWN" if known else "UNKNOWN",
    )


def route_for(run: RunSnapshot, role: str) -> tuple[str, str] | None:
    route = next((r for r in run.policy.routes if r.role == role), None)
    return None if route is None else (route.provider_id, route.model_id)


def same_policy(run: RunSnapshot, intent: DispatchIntent) -> bool:
    return policy_digest(run.policy) == intent.identity.policy_digest


_SCRIPT_ITEM_LISTS = ("segments", "scenes", "shots", "units")
#: Item fields media generation writes back: the produced artifacts and the duration tier the video was made at.
_MEDIA_ITEM_FIELDS = frozenset({"generated_assets", "duration_seconds"})


def script_revision(path: Path) -> str | None:
    """The episode script's content revision: its canonical JSON without the media state media generation writes
    back (each item's ``generated_assets`` and ``duration_seconds``, and ``metadata.updated_at``); ``None`` when
    the script is missing."""
    try:
        data: Any = json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    if isinstance(data, dict):
        data = dict(data)
        for key in _SCRIPT_ITEM_LISTS:
            if isinstance(data.get(key), list):
                data[key] = [
                    {k: v for k, v in item.items() if k not in _MEDIA_ITEM_FIELDS} if isinstance(item, dict) else item
                    for item in data[key]
                ]
        if isinstance(data.get("metadata"), dict):
            data["metadata"] = {k: v for k, v in data["metadata"].items() if k != "updated_at"}
    return content_fingerprint_of_data(data)


__all__ = [
    "OwnerBlocked",
    "Sessions",
    "current_run",
    "current_subject",
    "outcome",
    "required_outcome",
    "required_receipt",
    "route_for",
    "same_policy",
    "script_revision",
    "stage_receipt",
    "start_command",
    "step_intent",
    "usage_receipt",
]
