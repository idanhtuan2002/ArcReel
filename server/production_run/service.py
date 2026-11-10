"""User commands on production runs: Start, Pause/Resume/Cancel, mode change and semi checkpoint review.

Identity comes from the interactive session only. Start, Resume, mode change and review require the actor's
current Showrunner grant; Pause and Cancel only stop work, so any interactive session of the run's user may issue
them. Each command fences the controller lease of the run it changes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import (
    ProductionRunConflict,
    ProductionRunRepository,
    StaleProductionRunError,
    first_stage,
)
from r2.automation.identity import digest_value, policy_digest
from r2.contracts.automation import (
    AutomationMode,
    AutomationOperation,
    Checkpoint,
    GrantRequest,
    OwnerReceipt,
    ReviewApproval,
    ReviewCommand,
    RunCommand,
    RunPolicy,
    RunScope,
    RunSnapshot,
    RunStage,
    RunStatus,
)
from r2.contracts.autopilot import AutopilotDelegation, FilmAutopilot, StoryAutopilot, autopilot_command_prefix
from server.auth import get_current_interactive_user
from server.production_run.ports import InputWitness, PolicyResolver, PreflightCheck
from server.services.automation_grants import AutomationGrantCustodian
from server.services.governance_startup import GovernanceStartupUnavailable
from server.story_authoring.variant_profiles import PROFILES

_TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.FAILED_QUALITY, RunStatus.CANCELLED}
_ACTIVE = {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_TASK}
_RESUMABLE = {
    RunStatus.PAUSED,
    RunStatus.BLOCKED_CONFIGURATION,
    RunStatus.BLOCKED_RESOURCE,
    RunStatus.BLOCKED_BUDGET,
    RunStatus.BLOCKED_UNKNOWN,
    RunStatus.BLOCKED_INPUT_CHANGED,
}
REVIEW_OWNER = "production-review"


def covering_later_stages(granted: frozenset[AutomationOperation]) -> frozenset[AutomationOperation]:
    """A grant issued before a stage existed covers it on renewal when it covers the stages around it: ``ADAPTATION``
    (ADR-0114) sits between ``EPISODE_PLAN`` and ``SCRIPT_PLAN``, so a run started before it can resume past it."""
    if {AutomationOperation.EPISODE_PLAN, AutomationOperation.SCRIPT_PLAN} <= granted:
        return granted | {AutomationOperation.ADAPTATION}
    return granted


#: Checks a story-only run (ADR-0124: it ends at the handoff) does not reach: media routes and their qualification,
#: the voice, the image judge and the quality profile its film would be judged by. Disk and GPU room still apply,
#: since a local writer uses them.
_FILM_ONLY_PREFLIGHT = frozenset(
    {
        "MEDIA_ROUTE_NOT_QUALIFIED",
        "DRAMA_ROUTE_NOT_QUALIFIED",
        "IMAGE_JUDGE_NOT_QUALIFIED",
        "LAUNCH_PROFILE_NOT_QUALIFIED",
        "LAUNCH_QUALIFICATION_CHANGED",
        "MISSING_PUBLISHED_PROFILE",
        "PROFILE_INTEGRITY_INVALID",
        "QUALITY_PROFILE_CHANGED",
        "PROFILE_REQUIRES_HUMAN",
        "PROFILE_MODEL_ASSESSMENT_INCOMPLETE",
        "MISSING_VOICE",
    }
)


class ProductionRunRefused(Exception):
    def __init__(self, code: str, status: int = 409, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code, self.status, self.reasons = code, status, reasons


class ProductionActivation(BaseModel):
    """Whether this host may start or resume automatic production; reads stay available either way."""

    model_config = ConfigDict(frozen=True)

    enabled: bool
    reason: str | None = None


RELEASE_GATE_PENDING = ProductionActivation(enabled=False, reason="RELEASE_GATE_PENDING")


def policy_for_mode(policy: RunPolicy, mode: AutomationMode) -> RunPolicy:
    """The same frozen policy with ``mode`` and that mode's default checkpoints."""
    return RunPolicy.model_validate({**policy.model_dump(mode="python"), "mode": mode, "checkpoints": None})


def _changed(run: RunSnapshot, **changes: object) -> RunSnapshot:
    return RunSnapshot.model_validate(
        {
            **run.model_dump(mode="python"),
            "version": run.version + 1,
            "fencing_epoch": run.fencing_epoch + 1,
            **changes,
        }
    )


async def _always_has_story(_project_name: str) -> bool:
    return True


class ProductionRunService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        custodian: AutomationGrantCustodian,
        policies: PolicyResolver,
        witness: InputWitness,
        preflight: PreflightCheck,
        activation: ProductionActivation = RELEASE_GATE_PENDING,
        grant_ttl_seconds: int = 86_400,
        on_change: Callable[[], None] | None = None,
        has_story: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._custodian = custodian
        self._policies = policies
        self._witness = witness
        self._preflight = preflight
        self.activation = activation
        self._grant_ttl = timedelta(seconds=grant_ttl_seconds)
        self._on_change = on_change or (lambda: None)
        self._has_story = has_story or _always_has_story

    # Reads ---------------------------------------------------------------------------------------------------

    async def list(self, *, user_id: str, project_name: str) -> list[RunSnapshot]:
        async with self._sessions() as session:
            return await ProductionRunRepository(session).list_for_project(user_id=user_id, project_name=project_name)

    async def get(self, *, user_id: str, project_name: str, run_id: str) -> RunSnapshot:
        async with self._sessions() as session:
            run = await ProductionRunRepository(session).get(user_id=user_id, project_name=project_name, run_id=run_id)
        if run is None:
            raise ProductionRunRefused("RUN_NOT_FOUND", 404)
        return run

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]:
        """The session factory runs are read and written through."""
        return self._sessions

    async def start_offer(self, *, user_id: str, project_name: str) -> dict[str, object]:
        """The digests a Start command must carry; nothing is resolved while activation is disabled."""
        if not self.activation.enabled:
            return {"enabled": False, "reason": self.activation.reason}
        try:
            resolved = {
                mode: await self._policies.resolve(user_id=user_id, project_name=project_name, mode=mode)
                for mode in AutomationMode
            }
        except ProductionRunRefused as refused:
            # A project without (valid) automation settings cannot start yet; its setup stays reachable.
            return {"enabled": False, "reason": refused.code, "reasons": list(refused.reasons)}
        return {
            "enabled": True,
            "input_digest": await self._witness.digest(user_id=user_id, project_name=project_name),
            "policy_digests": {mode.value: policy_digest(policy) for mode, policy in resolved.items()},
            "max_target_episodes": resolved[AutomationMode.AUTO].max_target_episodes,
        }

    async def readiness(self, *, user_id: str, project_name: str) -> dict[str, object]:
        """Whether a Start would pass preflight now, with the reasons it would not and the policy it would freeze."""
        try:
            policy = await self._policies.resolve(user_id=user_id, project_name=project_name, mode=AutomationMode.AUTO)
        except ProductionRunRefused as refused:
            return {"ready": False, "reasons": [refused.code, *refused.reasons], "routes": [], "limits": None}
        report = await self._preflight.check(user_id=user_id, project_name=project_name, policy=policy)
        return {
            "ready": report.dispatch_allowed,
            "reasons": list(report.blocking_reasons),
            "launch_profile_id": policy.launch_profile_id,
            "quality_gate": policy.quality_gate,
            "local_only": policy.local_only,
            "routes": [
                {
                    "role": route.role,
                    "provider_id": route.provider_id,
                    "model_id": route.model_id,
                    "model_identity": route.model_identity,
                    "local": route.local,
                    "paid": route.paid,
                    "max_cost_per_call": route.max_cost_per_call,
                }
                for route in policy.routes
            ],
            "limits": {
                "currency": policy.currency,
                "max_cost_minor_units": policy.max_cost_minor_units,
                "max_model_calls": policy.max_model_calls,
                "max_tasks": policy.max_tasks,
                "max_runtime_seconds": policy.max_runtime_seconds,
                "max_target_episodes": policy.max_target_episodes,
            },
        }

    # Commands ------------------------------------------------------------------------------------------------

    def _require_activated(self) -> None:
        if not self.activation.enabled:
            raise ProductionRunRefused(
                "AUTOMATIC_PRODUCTION_NOT_ACTIVATED", 503, (self.activation.reason or "NOT_ACTIVATED",)
            )

    async def _require_preflight(
        self, *, user_id: str, project_name: str, policy: RunPolicy, story_only: bool = False
    ) -> None:
        report = await self._preflight.check(user_id=user_id, project_name=project_name, policy=policy)
        reasons = tuple(
            reason for reason in report.blocking_reasons if not (story_only and reason in _FILM_ONLY_PREFLIGHT)
        )
        if reasons:
            raise ProductionRunRefused("PREFLIGHT_BLOCKED", 409, reasons)

    async def _grant_request(
        self,
        run: RunSnapshot,
        *,
        issuer_id: str,
        command_id: str,
        parent_expiry: datetime,
        operations: frozenset[AutomationOperation],
        ttl: timedelta | None | Literal["default"] = "default",
    ) -> GrantRequest:
        return GrantRequest(
            user_id=run.user_id,
            project_name=run.project_name,
            run_id=run.run_id,
            issuer_id=issuer_id,
            command_id=command_id,
            expected_run_version=run.version,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            operations=operations,
            expires_at=parent_expiry
            if ttl is None
            else min(datetime.now(UTC) + (self._grant_ttl if ttl == "default" else ttl), parent_expiry),
        )

    async def start(self, *, interactive_token: str | None, command: RunCommand) -> RunSnapshot:
        command = RunCommand.model_validate(command)
        if command.action != "START":
            raise ProductionRunRefused("INVALID_COMMAND", 422)
        self._require_activated()
        await self._interactive(interactive_token, command.user_id)
        async with self._sessions() as session, session.begin():
            replay = await ProductionRunRepository(session).start_replay(command=command)
        if replay is None:
            policy = await self._policies.resolve(
                user_id=command.user_id, project_name=command.project_name, mode=command.mode
            )
            if policy_digest(policy) != command.policy_digest:
                raise ProductionRunRefused("POLICY_MOVED")
            if len(set(command.targets)) != len(command.targets) or len(command.targets) > policy.max_target_episodes:
                raise ProductionRunRefused("TARGETS_OVER_LIMIT", 422, (str(policy.max_target_episodes),))
            if command.story_source in {"project", "continue"} and not await self._has_story(command.project_name):
                raise ProductionRunRefused("PROJECT_SOURCE_MISSING", 409)
            if command.source_project is not None:
                # A variant copies another project's story: its starter must be that project's Showrunner too.
                await self.require_showrunner(
                    interactive_token=interactive_token, user_id=command.user_id, project_name=command.source_project
                )
                if not await self._has_story(command.source_project):
                    raise ProductionRunRefused("PRIOR_STORY_MISSING", 409)
            if command.variant_profile is not None and command.variant_profile not in PROFILES:
                raise ProductionRunRefused("VARIANT_PROFILE_UNKNOWN", 422)
            current_input = await self._witness.digest(user_id=command.user_id, project_name=command.project_name)
            if current_input != command.expected_input_digest:
                raise ProductionRunRefused("INPUT_MOVED")
            await self._require_preflight(
                user_id=command.user_id,
                project_name=command.project_name,
                policy=policy,
                story_only=command.end_stage == "HANDOFF",
            )
        else:
            policy = replay.policy
        await self._custodian.activate()
        async with self._sessions() as session, session.begin():
            issuer_id, parent_expiry = await self._custodian.require_issuer_locked(
                session,
                interactive_token=interactive_token,
                user_id=command.user_id,
                project_name=command.project_name,
            )
            run = await ProductionRunRepository(session).create(command=command, policy=policy)
            scope = RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)
            grant = await AutomationGrantRepository(session).head(scope)
            if grant is None:
                request = await self._grant_request(
                    run,
                    issuer_id=issuer_id,
                    command_id=command.command_id,
                    parent_expiry=parent_expiry,
                    operations=frozenset(AutomationOperation),
                )
                await self._custodian.issue_locked(session, interactive_token=interactive_token, request=request)
            elif grant.start_command_id != command.command_id:
                raise ProductionRunRefused("COMMAND_REPLAY_CONFLICT")
        self._on_change()
        return run

    async def resolve_policy(self, *, user_id: str, project_name: str, mode: AutomationMode) -> RunPolicy:
        return await self._policies.resolve(user_id=user_id, project_name=project_name, mode=mode)

    async def input_digest(self, *, user_id: str, project_name: str) -> str:
        return await self._witness.digest(user_id=user_id, project_name=project_name)

    async def has_story(self, project_name: str) -> bool:
        return await self._has_story(project_name)

    async def set_autopilot(
        self,
        *,
        interactive_token: str | None,
        user_id: str,
        project_name: str,
        command_id: str,
        enabled: bool,
        kind: Literal["story", "film"],
        mode: AutomationMode,
        story: StoryAutopilot | None = None,
        film: FilmAutopilot | None = None,
    ) -> AutopilotDelegation | None:
        """ADR-0124: record the Showrunner's decision to turn the project's autopilot on (freezing the policy of
        ``mode``) or off."""
        self._require_activated()
        await self._interactive(interactive_token, user_id)
        policy = await self.resolve_policy(user_id=user_id, project_name=project_name, mode=mode)
        await self._custodian.activate()
        try:
            async with self._sessions() as session, session.begin():
                delegation = await self._custodian.set_autopilot_locked(
                    session,
                    interactive_token=interactive_token,
                    user_id=user_id,
                    project_name=project_name,
                    command_id=command_id,
                    enabled=enabled,
                    kind=kind,
                    mode=mode,
                    policy_digest=policy_digest(policy),
                    story=story,
                    film=film,
                )
        except PermissionError as error:
            raise ProductionRunRefused(str(error), 403) from None
        except IntegrityError:
            raise ProductionRunRefused("AUTOPILOT_CHANGED_CONCURRENTLY", 409) from None
        self._on_change()
        return delegation

    async def start_delegated(self, *, delegation: AutopilotDelegation, command: RunCommand) -> RunSnapshot:
        """ADR-0124: start (or replay) a run of the autopilot under its locked, enabled delegation, without a session.
        Everything an interactive start checks is checked, and the policy must be the one frozen at enable."""
        command = RunCommand.model_validate(command)
        delegation = AutopilotDelegation.model_validate(delegation)
        if (
            command.action != "START"
            or (command.user_id, command.project_name) != (delegation.user_id, delegation.project_name)
            or command.mode != delegation.mode
            or command.source_project is not None
            or not command.command_id.startswith(autopilot_command_prefix(delegation))
        ):
            raise ProductionRunRefused("INVALID_COMMAND", 422)
        self._require_activated()
        async with self._sessions() as session, session.begin():
            replay = await ProductionRunRepository(session).start_replay(command=command)
        if replay is None:
            policy = await self.resolve_policy(
                user_id=command.user_id, project_name=command.project_name, mode=command.mode
            )
            if policy_digest(policy) != command.policy_digest or command.policy_digest != delegation.policy_digest:
                raise ProductionRunRefused("POLICY_MOVED")
            if len(set(command.targets)) != len(command.targets) or len(command.targets) > policy.max_target_episodes:
                raise ProductionRunRefused("TARGETS_OVER_LIMIT", 422, (str(policy.max_target_episodes),))
            if command.story_source in {"project", "continue"} and not await self._has_story(command.project_name):
                raise ProductionRunRefused("PROJECT_SOURCE_MISSING", 409)
            current_input = await self._witness.digest(user_id=command.user_id, project_name=command.project_name)
            if current_input != command.expected_input_digest:
                raise ProductionRunRefused("INPUT_MOVED")
            await self._require_preflight(
                user_id=command.user_id,
                project_name=command.project_name,
                policy=policy,
                story_only=command.end_stage == "HANDOFF",
            )
        else:
            policy = replay.policy
        await self._custodian.activate()
        try:
            async with self._sessions() as session, session.begin():
                parent_expiry = await self._custodian.require_delegation_locked(session, delegation=delegation)
                run = await ProductionRunRepository(session).create(command=command, policy=policy)
                scope = RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)
                grant = await AutomationGrantRepository(session).head(scope)
                if grant is None:
                    # The child grant lives as long as its parent; the delegation, not a session, bounds it.
                    request = await self._grant_request(
                        run,
                        issuer_id=delegation.issuer_id,
                        command_id=command.command_id,
                        parent_expiry=parent_expiry,
                        operations=frozenset(AutomationOperation),
                        ttl=None,
                    )
                    await self._custodian.issue_delegated_locked(session, delegation=delegation, request=request)
                elif grant.start_command_id != command.command_id:
                    raise ProductionRunRefused("COMMAND_REPLAY_CONFLICT")
        except PermissionError as error:
            raise ProductionRunRefused(str(error), 403) from None
        self._on_change()
        return run

    async def require_showrunner(self, *, interactive_token: str | None, user_id: str, project_name: str) -> None:
        """Refuse an actor without the project's current Showrunner grant (setup and qualification changes)."""
        await self._custodian.activate()
        async with self._sessions() as session, session.begin():
            await self._custodian.require_issuer_locked(
                session, interactive_token=interactive_token, user_id=user_id, project_name=project_name
            )

    async def control(self, *, interactive_token: str | None, command: RunCommand) -> RunSnapshot:
        command = RunCommand.model_validate(command)
        if command.action == "START" or command.run_id is None:
            raise ProductionRunRefused("INVALID_COMMAND", 422)
        scope = RunScope(user_id=command.user_id, project_name=command.project_name, run_id=command.run_id)
        await self._interactive(interactive_token, command.user_id)
        if command.action in {"PAUSE", "CANCEL"}:
            async with self._sessions() as session, session.begin():
                repository = ProductionRunRepository(session)
                run = await repository.locked(scope)
                updated = self._stop(run, command)
                if updated is not run:
                    run = await repository.apply_command(expected=run, updated=updated)
            self._on_change()
            return run

        self._require_activated()
        async with self._sessions() as session:
            observed = await ProductionRunRepository(session).get(**scope.model_dump())
        if observed is None:
            raise ProductionRunRefused("RUN_NOT_FOUND", 404)
        target_policy = observed.policy
        if command.action == "MODE":
            target_policy = policy_for_mode(observed.policy, command.mode)
        if policy_digest(target_policy) != command.policy_digest:
            raise ProductionRunRefused("POLICY_MOVED")
        rebind = (
            observed.status is RunStatus.BLOCKED_INPUT_CHANGED
            and command.expected_input_digest != observed.input_digest
        )
        if command.action == "RESUME":
            # Without a rebind the controller itself blocks on moved input at its next tick.
            if rebind and command.expected_input_digest != await self._witness.digest(
                user_id=command.user_id, project_name=command.project_name
            ):
                raise ProductionRunRefused("INPUT_MOVED")
            await self._require_preflight(
                user_id=command.user_id,
                project_name=command.project_name,
                policy=target_policy,
                story_only=observed.end_stage is RunStage.HANDOFF,
            )
        await self._custodian.activate()
        async with self._sessions() as session, session.begin():
            issuer_id, parent_expiry = await self._custodian.require_issuer_locked(
                session, interactive_token=interactive_token, user_id=command.user_id, project_name=command.project_name
            )
            repository = ProductionRunRepository(session)
            run = await repository.locked(scope)
            if command.action == "RESUME":
                start = await repository.start_command(scope)
                updated = self._resume(run, command, rebind=rebind, restart=first_stage(start))
            else:
                updated = await self._mode(repository, run, command, target_policy)
            if updated is run:
                return run
            run = await repository.apply_command(expected=run, updated=updated, policy=target_policy)
            grant = await AutomationGrantRepository(session).head(scope, lock=True)
            if grant is None:
                raise ProductionRunRefused("AUTOMATION_GRANT_UNAVAILABLE", 403)
            request = await self._grant_request(
                run,
                issuer_id=issuer_id,
                command_id=command.command_id,
                parent_expiry=parent_expiry,
                operations=covering_later_stages(grant.operations),
            )
            await self._custodian.renew_locked(session, interactive_token=interactive_token, request=request)
        self._on_change()
        return run

    async def review(self, *, interactive_token: str | None, command: ReviewCommand) -> RunSnapshot:
        command = ReviewCommand.model_validate(command)
        self._require_activated()
        await self._interactive(interactive_token, command.user_id)
        await self._custodian.activate()
        scope = RunScope(user_id=command.user_id, project_name=command.project_name, run_id=command.run_id)
        async with self._sessions() as session, session.begin():
            issuer_id, _expiry = await self._custodian.require_issuer_locked(
                session, interactive_token=interactive_token, user_id=command.user_id, project_name=command.project_name
            )
            repository = ProductionRunRepository(session)
            run = await repository.locked(scope)
            receipt = OwnerReceipt(
                owner=REVIEW_OWNER,
                receipt_ref=command.command_id,
                digest=digest_value("r2.production-review-decision.v1", command.model_dump(mode="json")),
            )
            if any(a.receipt == receipt for a in run.review_approvals):
                return run
            pending = run.pending_review
            if (
                run.status is not RunStatus.WAITING_REVIEW
                or pending is None
                or run.version != command.expected_version
                or (pending.checkpoint, pending.binding_digest) != (command.checkpoint, command.binding_digest)
            ):
                raise ProductionRunRefused("STALE_PRODUCTION_RUN")
            if command.decision == "REWORK":
                if command.checkpoint is not Checkpoint.FINAL_FILM:
                    raise ProductionRunRefused("REWORK_NOT_AVAILABLE", 422)
                # The final goes back to MEDIA as a new generation: media the Showrunner replaced in the project
                # is picked up, missing media is made, and the new final needs its own review. The policy's final
                # evaluation limit still bounds how often QUALITY runs.
                updated = _changed(
                    run,
                    status=RunStatus.RUNNING,
                    stage=RunStage.MEDIA,
                    generation=run.generation + 1,
                    pending_review=None,
                    reason=None,
                    completed_targets=(),
                )
            elif command.decision == "APPROVE":
                approval = ReviewApproval(
                    checkpoint=command.checkpoint,
                    binding_digest=command.binding_digest,
                    actor_id=issuer_id,
                    receipt=receipt,
                )
                updated = _changed(
                    run,
                    status=RunStatus.RUNNING,
                    pending_review=None,
                    reason=None,
                    review_approvals=(*run.review_approvals, approval),
                )
            else:
                updated = _changed(run, status=RunStatus.FAILED_QUALITY, pending_review=None, reason="REVIEW_REJECTED")
            run = await repository.apply_command(expected=run, updated=updated)
        self._on_change()
        return run

    # Command rules -------------------------------------------------------------------------------------------

    @staticmethod
    async def _interactive(token: str | None, user_id: str) -> None:
        try:
            actor = await get_current_interactive_user(token)
        except HTTPException:
            raise ProductionRunRefused("INTERACTIVE_SESSION_REQUIRED", 401) from None
        if actor.id != user_id:
            raise ProductionRunRefused("INTERACTIVE_SESSION_REQUIRED", 403)

    @staticmethod
    def _bound(run: RunSnapshot, command: RunCommand) -> None:
        if (command.expected_input_digest, command.policy_digest) != (run.input_digest, policy_digest(run.policy)):
            raise ProductionRunRefused("STALE_PRODUCTION_RUN")

    def _stop(self, run: RunSnapshot, command: RunCommand) -> RunSnapshot:
        """Pause/Cancel accept any version the user has seen; scanner claims move the version meanwhile."""
        self._bound(run, command)
        if command.expected_version > run.version:
            raise ProductionRunRefused("STALE_PRODUCTION_RUN")
        target = RunStatus.PAUSED if command.action == "PAUSE" else RunStatus.CANCELLED
        if run.status is target:
            return run
        if run.status in _TERMINAL:
            raise ProductionRunRefused("RUN_FINISHED")
        reason = None if target is RunStatus.PAUSED else "CANCELLED_BY_USER"
        return _changed(run, status=target, pending_review=None, reason=reason)

    def _resume(
        self, run: RunSnapshot, command: RunCommand, *, rebind: bool, restart: RunStage = RunStage.BRIEF
    ) -> RunSnapshot:
        if run.status in _ACTIVE and (command.expected_input_digest, command.policy_digest) == (
            run.input_digest,
            policy_digest(run.policy),
        ):
            return run
        if run.status not in _RESUMABLE:
            raise ProductionRunRefused("RUN_NOT_RESUMABLE")
        if run.version != command.expected_version or command.policy_digest != policy_digest(run.policy):
            raise ProductionRunRefused("STALE_PRODUCTION_RUN")
        if not rebind:
            self._bound(run, command)
            return _changed(run, status=RunStatus.RUNNING, reason=None, pending_review=None)
        if run.status is not RunStatus.BLOCKED_INPUT_CHANGED:
            raise ProductionRunRefused("STALE_PRODUCTION_RUN")
        # A new external input starts a new lineage: earlier outputs are kept but no longer current.
        return _changed(
            run,
            status=RunStatus.RUNNING,
            reason=None,
            pending_review=None,
            input_digest=command.expected_input_digest,
            generation=run.generation + 1,
            stage=restart,
            completed_targets=(),
        )

    @staticmethod
    async def _mode(
        repository: ProductionRunRepository, run: RunSnapshot, command: RunCommand, policy: RunPolicy
    ) -> RunSnapshot:
        """Mode changes only at a stage boundary of a stopped run, keeping its status."""
        if run.policy == policy:
            return run
        if run.status not in _RESUMABLE:
            raise ProductionRunRefused("MODE_CHANGE_REQUIRES_PAUSE")
        if run.version != command.expected_version or command.expected_input_digest != run.input_digest:
            raise ProductionRunRefused("STALE_PRODUCTION_RUN")
        if await repository.current_step(run=run) is not None:
            raise ProductionRunRefused("MODE_CHANGE_REQUIRES_STAGE_BOUNDARY")
        return _changed(run, policy=policy)


def refusal(error: Exception) -> tuple[int, dict[str, object]]:
    """HTTP status and body for a refused command; never includes tokens or provider configuration."""
    if isinstance(error, ProductionRunRefused):
        return error.status, {"code": error.code, "reasons": list(error.reasons)}
    if isinstance(error, GovernanceStartupUnavailable):
        return 503, {"code": "GOVERNANCE_UNAVAILABLE", "reasons": []}
    if isinstance(error, StaleProductionRunError):
        return 409, {"code": "STALE_PRODUCTION_RUN", "reasons": []}
    if isinstance(error, ProductionRunConflict):
        return 409, {"code": str(error), "reasons": []}
    return 403, {"code": "NOT_AUTHORIZED", "reasons": [str(error)]}


__all__ = [
    "RELEASE_GATE_PENDING",
    "ProductionActivation",
    "ProductionRunRefused",
    "ProductionRunService",
    "policy_for_mode",
    "refusal",
]
