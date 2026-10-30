"""Caller-owned child grant transactions; owner services establish parent authority first."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.automation_grant import AutomationDecisionModel, AutomationGrantEventModel, AutomationGrantHeadModel
from lib.db.models.production_run import ProductionStepModel
from r2.automation.authorization import authorization_subject_digest, automation_principal
from r2.automation.identity import derive_step_identity
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationAuthorizationV1,
    AutomationGrant,
    DispatchIntent,
    RunScope,
)


class AutomationGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def head(self, scope: RunScope, *, lock: bool = False) -> AutomationGrant | None:
        stmt = select(AutomationGrantHeadModel).where(
            AutomationGrantHeadModel.user_id == scope.user_id,
            AutomationGrantHeadModel.project_name == scope.project_name,
            AutomationGrantHeadModel.run_id == scope.run_id,
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        head = (await self.session.execute(stmt)).scalar_one_or_none()
        if head is None:
            return None
        row = await self.session.get(
            AutomationGrantEventModel,
            (scope.user_id, scope.project_name, scope.run_id, head.version),
            populate_existing=True,
        )
        if row is None:
            raise PermissionError("AUTOMATION_GRANT_UNAVAILABLE")
        grant = AutomationGrant.model_validate_json(row.grant_json)
        if (grant.user_id, grant.project_name, grant.run_id, grant.version, grant.grant_id) != (
            head.user_id,
            head.project_name,
            head.run_id,
            head.version,
            head.grant_id,
        ) or grant.principal != automation_principal(grant.run_id):
            raise PermissionError("AUTOMATION_GRANT_INTEGRITY_FAILED")
        return grant

    async def append(self, grant: AutomationGrant, *, previous: AutomationGrant | None) -> None:
        grant = AutomationGrant.model_validate(grant)
        key = (grant.user_id, grant.project_name, grant.run_id)
        head = await self.session.get(AutomationGrantHeadModel, key)
        if previous is None:
            if head is not None or grant.version != 1 or grant.state != "ACTIVE":
                raise PermissionError("AUTOMATION_GRANT_CONFLICT")
        elif (
            head is None
            or head.version != previous.version
            or grant.version != previous.version + 1
            or grant != previous.model_copy(update={"version": grant.version, "state": "REVOKED"})
        ):
            raise PermissionError("AUTOMATION_GRANT_CONFLICT")
        self.session.add(
            AutomationGrantEventModel(
                user_id=grant.user_id,
                project_name=grant.project_name,
                run_id=grant.run_id,
                grant_id=grant.grant_id,
                version=grant.version,
                grant_json=grant.model_dump_json(),
            )
        )
        await self.session.flush()
        if head is None:
            self.session.add(
                AutomationGrantHeadModel(
                    user_id=grant.user_id,
                    project_name=grant.project_name,
                    run_id=grant.run_id,
                    grant_id=grant.grant_id,
                    version=grant.version,
                )
            )
        else:
            head.version = grant.version
        await self.session.flush()

    async def require_intent(self, subject: AuthorizationSubject) -> None:
        row = await self.session.get(ProductionStepModel, subject.command_id, populate_existing=True)
        if row is None:
            raise PermissionError("AUTOMATION_INTENT_UNAVAILABLE")
        intent = DispatchIntent.model_validate_json(row.intent_json)
        identity = intent.identity
        rebuilt = derive_step_identity(**identity.model_dump(exclude={"command_id", "task_id"}))
        if (
            identity != rebuilt
            or (
                intent.scope.user_id,
                intent.scope.project_name,
                intent.scope.run_id,
                identity.command_id,
                identity.stage.value,
                identity.generation,
                identity.input_digest,
                identity.policy_digest,
            )
            != (
                subject.user_id,
                subject.project_name,
                subject.run_id,
                subject.command_id,
                subject.operation.value,
                subject.generation,
                subject.input_digest,
                subject.policy_digest,
            )
            or (
                row.user_id,
                row.project_name,
                row.run_id,
                row.command_id,
                row.stage,
                row.generation,
                row.input_digest,
                row.policy_digest,
                row.unit_key,
                row.repair_index,
            )
            != (
                intent.scope.user_id,
                intent.scope.project_name,
                intent.scope.run_id,
                identity.command_id,
                identity.stage.value,
                identity.generation,
                identity.input_digest,
                identity.policy_digest,
                identity.unit_key,
                identity.repair_index,
            )
        ):
            raise PermissionError("AUTOMATION_INTENT_SCOPE_MISMATCH")

    async def record(self, authorization: AutomationAuthorizationV1) -> AutomationAuthorizationV1:
        subject = authorization.subject
        key = (subject.user_id, subject.project_name, subject.run_id, subject.command_id)
        row = await self.session.get(AutomationDecisionModel, key)
        if row is not None:
            stored = AutomationAuthorizationV1.model_validate_json(row.authorization_json)
            if (
                stored.subject != subject
                or stored.request_digest != authorization_subject_digest(subject)
                or (stored.principal, stored.parent_sequence, stored.parent_event_digest)
                != (authorization.principal, authorization.parent_sequence, authorization.parent_event_digest)
                or (row.grant_id, row.grant_version) != (subject.grant_id, subject.grant_version)
            ):
                raise PermissionError("AUTOMATION_COMMAND_REPLAY_CONFLICT")
            return stored
        self.session.add(
            AutomationDecisionModel(
                user_id=subject.user_id,
                project_name=subject.project_name,
                run_id=subject.run_id,
                command_id=subject.command_id,
                grant_id=subject.grant_id,
                grant_version=subject.grant_version,
                authorization_json=authorization.model_dump_json(),
            )
        )
        await self.session.flush()
        return authorization
