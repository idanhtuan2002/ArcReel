"""An automatic provenance projection cannot commit without its owner transaction guard."""

import pytest

from r2.automation.authorization import automation_principal
from r2.contracts.narrative_lifecycle import NarrativeDecisionRetryAuthenticationEvidence
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from tests.factories import make_revision_acceptance_command
from tests.unit.r2.automation.test_owner_authorization_contracts import auto_wire
from tests.unit.r2.narrative_lifecycle.test_authority_kernel import SCOPE, _FakeRepository, _FakeUnitOfWork

PRINCIPAL = automation_principal("run-1")


class ProjectionOnlyAuthority:
    async def authorize_initial_decision(self, principal, command):
        from r2.contracts.narrative_lifecycle import NarrativeAutomationDecisionAuthorizationV1
        from r2.narrative_lifecycle.automation import automatic_authorization_fingerprints

        scope_fingerprint, command_fingerprint = automatic_authorization_fingerprints(command)
        return NarrativeAutomationDecisionAuthorizationV1(
            **{
                **auto_wire(),
                "user_id": command.work_scope.user_id,
                "project_name": command.work_scope.project_name,
                "decision_id": command.decision_id,
                "stable_subject_fingerprint": scope_fingerprint,
                "decision_command_fingerprint": command_fingerprint,
            }
        )

    async def authenticate_exact_retry(
        self, principal, decision_id, scope
    ) -> NarrativeDecisionRetryAuthenticationEvidence:
        from r2.contracts.narrative_lifecycle import NarrativeAutomationRetryAuthenticationV1

        return NarrativeAutomationRetryAuthenticationV1(
            retry_authentication_ref="anra:v1:" + "d" * 64,
            user_id=scope.user_id,
            project_name=scope.project_name,
            actor_id=PRINCIPAL,
            authority_role="RUN_AUTOMATION",
            decision_id=decision_id,
            authenticated_at=auto_wire()["authenticated_at"],
            authenticated_via=auto_wire()["authenticated_via"],
        )

    async def authenticate_scoped_showrunner(self, principal, subject_id, scope):
        return await self.authenticate_exact_retry(principal, subject_id, scope)


class GuardedAuthority(ProjectionOnlyAuthority):
    def __init__(self, events, deny=False):
        self.events = events
        self.deny = deny
        self.guarded_uows = []

    async def require_current_in_owner(self, unit_of_work, command):
        self.guarded_uows.append(unit_of_work)
        self.events.append("guard")
        if self.deny:
            raise NarrativeDecisionAuthorizationError("revoked")


class ObservedUow(_FakeUnitOfWork):
    def __init__(self, repo, events):
        super().__init__(repo)
        self.events = events

    async def commit(self):
        self.events.append("commit")
        await super().commit()


def command():
    return make_revision_acceptance_command(
        decision_id="decision-1", work_scope=SCOPE, action="ACCEPT", actor_id=PRINCIPAL
    )


async def test_automatic_projection_without_owner_guard_cannot_commit():
    uow = ObservedUow(_FakeRepository(), [])
    kernel = AuthorityKernel(lambda: uow, ProjectionOnlyAuthority())
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await kernel.run(command(), authenticated_principal=PRINCIPAL)
    assert not uow.committed


async def test_revoked_automatic_authority_cannot_commit():
    events = []
    uow = ObservedUow(_FakeRepository(), events)
    authority = GuardedAuthority(events, deny=True)
    kernel = AuthorityKernel(lambda: uow, authority)
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await kernel.run(command(), authenticated_principal=PRINCIPAL)
    assert not uow.committed
    assert authority.guarded_uows == [uow]


async def test_new_and_replayed_automatic_decisions_revalidate_in_the_owning_uow():
    events = []
    uow = ObservedUow(_FakeRepository(), events)
    authority = GuardedAuthority(events)
    kernel = AuthorityKernel(lambda: uow, authority)
    first = await kernel.run(command(), authenticated_principal=PRINCIPAL)
    replay = await kernel.run(command(), authenticated_principal=PRINCIPAL)
    assert first == replay
    assert events == ["guard", "commit", "guard", "commit"]
    assert authority.guarded_uows == [uow, uow]


async def test_human_retry_projection_cannot_bypass_guard_for_stored_automatic_decision():
    from r2.contracts.narrative_lifecycle import NarrativeDecisionRetryAuthentication

    class HumanRetry(ProjectionOnlyAuthority):
        async def authenticate_exact_retry(self, principal, decision_id, scope):
            return NarrativeDecisionRetryAuthentication(
                retry_authentication_ref="human-retry",
                user_id=scope.user_id,
                project_name=scope.project_name,
                actor_id=PRINCIPAL,
                authority_role="HUMAN_SHOWRUNNER",
                decision_id=decision_id,
                authenticated_at=auto_wire()["authenticated_at"],
                authenticated_via="human-test",
            )

    authority = HumanRetry()
    repo = _FakeRepository()
    repo.seed_decision("decision-1", generation=1)
    incoming = command()
    projection = await authority.authorize_initial_decision(PRINCIPAL, incoming)
    repo.decisions["decision-1"] = (incoming, projection, 1)
    uow = ObservedUow(repo, [])
    kernel = AuthorityKernel(lambda: uow, authority)
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await kernel.run(incoming, authenticated_principal=PRINCIPAL)
    assert not uow.committed


@pytest.mark.parametrize("tamper", ["actor", "scope_fingerprint", "command_fingerprint"])
async def test_automatic_projection_must_bind_exact_canonical_owner_command(tamper):
    class ForgedProjection(GuardedAuthority):
        async def authorize_initial_decision(self, principal, command):
            projection = await super().authorize_initial_decision(principal, command)
            if tamper == "scope_fingerprint":
                projection = projection.model_copy(update={"stable_subject_fingerprint": "nss:wrong"})
            elif tamper == "command_fingerprint":
                projection = projection.model_copy(update={"decision_command_fingerprint": "ndc:wrong"})
            return projection

    incoming = command()
    if tamper == "actor":
        incoming = incoming.model_copy(update={"actor_id": "other-actor"})
    uow = ObservedUow(_FakeRepository(), [])
    authority = ForgedProjection([])
    kernel = AuthorityKernel(lambda: uow, authority)
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await kernel.run(incoming, authenticated_principal=PRINCIPAL)
    assert not uow.committed


async def test_automatic_decision_port_does_not_implicitly_enable_canon_handoff():
    from r2.narrative_lifecycle.acceptance import CanonHandoffAdmissionCommand, NarrativeAcceptanceService
    from tests.factories import make_canon_commit_approval

    def forbidden_uow():
        raise AssertionError("unsupported automatic handoff opened an owner transaction")

    service = NarrativeAcceptanceService(forbidden_uow, GuardedAuthority([]))
    request = CanonHandoffAdmissionCommand(
        admission_id="admit-1",
        work_scope=SCOPE,
        compilation_attempt_id="attempt-1",
        generation=0,
        compilation_result_id="result-1",
    )
    approval = make_canon_commit_approval(user_id=SCOPE.user_id, project_name=SCOPE.project_name, approved_by=PRINCIPAL)
    with pytest.raises(NarrativeDecisionAuthorizationError, match="AUTOMATIC_CANON_HANDOFF_NOT_DELEGATED"):
        await service.admit_canon_handoff(request, authenticated_principal=PRINCIPAL, canon_commit_approval=approval)
