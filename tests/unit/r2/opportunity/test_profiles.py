"""Receipt-first profile publication admits one exact bounded Human authorization."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from r2.contracts.opportunity import (
    CommandContext,
    CustodianAuthorizationLease,
    OpportunityCohortProfilePayload,
    OpportunityIdentityRead,
    OpportunityReadPage,
    PublishOpportunityCohortProfile,
)
from r2.opportunity.digests import digest_profile_publication_subject
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.profiles import OpportunityProfileNotFoundError, OpportunityProfileService
from tests.unit.r2.contracts.test_opportunity import profile_payload

ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
COMMAND = "019a0000-0000-7000-8000-000000000010"
H = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 16, tzinfo=UTC)


class ProfileMemoryStore:
    """A transaction port substitute; real locks and SQL are tested on PostgreSQL."""

    def __init__(self):
        self.profiles, self.heads, self.receipts = {}, {}, {}
        self.events = []
        self.now = NOW
        self.policy = ("WESTERN_GENERIC", "1", H)
        self.in_transaction = False
        self.fail_enter = False
        self.lose_ack = False
        self.log = []

    @asynccontextmanager
    async def transaction(self):
        if self.fail_enter:
            raise RuntimeError("crash after authorization")
        snapshot = (dict(self.profiles), dict(self.heads), dict(self.receipts), list(self.events))
        self.in_transaction = True
        self.log.append("begin")
        try:
            yield self
        except BaseException:
            self.profiles, self.heads, self.receipts, self.events = snapshot
            raise
        else:
            if self.lose_ack:
                self.lose_ack = False
                raise ConnectionError("lost commit acknowledgement")
        finally:
            self.in_transaction = False

    async def lock_command_key(self, *, context, operation):
        assert self.in_transaction
        self.log.append("guard")

    async def get_command_receipt(self, *, context, operation, request_digest):
        self.log.append("receipt")
        value = self.receipts.get((context.user_id, context.actor_id, operation, context.command_id))
        if value is not None and (
            value.profile.project_name != context.project_name or value.request_digest != request_digest
        ):
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        return value

    async def database_time(self):
        return self.now

    async def creative_policy_identity(self, *, user_id, project_name):
        self.log.append("policy")
        return self.policy

    async def get_exact(self, *, user_id, project_name, profile_id, revision):
        return self.profiles.get((user_id, project_name, profile_id, revision))

    async def get_head_for_update(self, *, user_id, project_name, profile_id):
        self.log.append("head")
        return self.heads.get((user_id, project_name, profile_id))

    async def list_heads(self, *, user_id, project_name, after_id, limit):
        selected = sorted(
            (identity, head)
            for (owner, project, identity), head in self.heads.items()
            if (owner, project) == (user_id, project_name) and (after_id is None or identity > after_id)
        )
        return tuple(
            self.profiles[(user_id, project_name, identity, head.current_revision)]
            for identity, head in selected[:limit]
        )

    async def stage_profile(self, profile):
        self.profiles[(profile.user_id, profile.project_name, profile.profile_id, profile.revision)] = profile

    async def stage_head(self, *, user_id, project_name, head, expected_head_version):
        old = self.heads.get((user_id, project_name, head.profile_id))
        if (None if old is None else old.head_version) != expected_head_version:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        self.heads[(user_id, project_name, head.profile_id)] = head

    async def stage_event(self, *, profile, committed_at):
        self.events.append((profile.profile_id, profile.revision, profile.profile_digest))

    async def stage_command_receipt(self, *, context, operation, receipt):
        self.receipts[(context.user_id, context.actor_id, operation, context.command_id)] = receipt


class ProfileCustodianFixture:
    def __init__(self, store):
        self.store = store
        self.calls = 0
        self.leases = {}
        self.override = {}
        self.after_authorization = None
        self.failure_code = None

    async def authorize_publication(self, command_id, subject):
        assert not self.store.in_transaction
        self.calls += 1
        if self.failure_code is not None:
            raise OpportunityError(self.failure_code)
        digest = digest_profile_publication_subject(subject)
        lease = self.leases.get(command_id)
        if lease is not None:
            if lease.subject_digest != digest or self.store.now > lease.admit_not_after:
                raise OpportunityError(StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED)
        else:
            lease = CustodianAuthorizationLease(
                authorization_id=OTHER,
                command_id=command_id,
                authorized=True,
                subject_digest=digest,
                custodian_policy_id="arcreel.showrunner-grant",
                custodian_policy_version="governance.showrunner_grant_event.v1",
                custodian_evidence_digest=H,
                issued_at=self.store.now,
                admit_not_after=self.store.now + timedelta(seconds=30),
            )
            self.leases[command_id] = lease
        if self.after_authorization:
            self.after_authorization()
        return lease.model_copy(update=self.override)


def publication(
    *,
    command_id=COMMAND,
    profile_id=ID,
    parent=None,
    head=None,
    user_id="u1",
    project_name="show-a",
    actor_id="human-a",
    payload=None,
):
    return PublishOpportunityCohortProfile(
        context=CommandContext(command_id=command_id, user_id=user_id, project_name=project_name, actor_id=actor_id),
        profile_id=profile_id,
        parent_revision=parent,
        expected_head_version=head,
        payload=OpportunityCohortProfilePayload.model_validate(profile_payload()) if payload is None else payload,
    )


def service_fixture(*, user_id="u1", project_name="show-a", actor_id="human-a"):
    store = ProfileMemoryStore()
    custodian = ProfileCustodianFixture(store)
    service = OpportunityProfileService(
        store=store, custodian=custodian, user_id=user_id, project_name=project_name, actor_id=actor_id
    )
    return service, store, custodian


async def test_genesis_append_and_scoped_history_have_exact_receipt_bindings():
    service, store, custodian = service_fixture()
    first = await service.publish_cohort_profile(publication())
    second = await service.publish_cohort_profile(publication(command_id=OTHER, parent=1, head=1))
    assert (first.profile.created_by, first.profile.user_id, second.head.current_revision) == ("human-a", "u1", 2)
    assert first.profile.custodian_authorization_id == custodian.leases[COMMAND].authorization_id
    assert (
        await service.get_cohort_profile(
            OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=ID, revision=1)
        )
        == first.profile
    )
    listed = await service.list_cohort_profiles(
        OpportunityReadPage(user_id="u1", project_name="show-a", after_id=None, limit=10)
    )
    assert listed == (second.profile,)
    assert len(store.events) == len(store.receipts) == 2
    assert store.log[:3] == ["receipt", "begin", "guard"]


@pytest.mark.parametrize(
    ("field", "value"), [("actor_id", "model"), ("user_id", "foreign-owner"), ("project_name", "foreign-project")]
)
async def test_command_scope_and_principal_cannot_override_authenticated_identity(field, value):
    service, store, custodian = service_fixture()
    with pytest.raises(OpportunityError) as denied:
        await service.publish_cohort_profile(publication(**{field: value}))
    assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert custodian.calls == 0
    assert not store.events


async def test_completed_replay_precedes_policy_currentness_and_custodian_calls():
    service, store, custodian = service_fixture()
    original = await service.publish_cohort_profile(publication())
    await service.publish_cohort_profile(publication(command_id=OTHER, parent=1, head=1))
    store.policy = ("CN_SHORT_DRAMA_SHUANGWEN", "2", "sha256:" + "b" * 64)
    store.now += timedelta(days=1)
    replay = await service.publish_cohort_profile(publication())
    assert replay.model_dump_json() == original.model_dump_json()
    assert custodian.calls == 2
    assert len(store.events) == 2


async def test_changed_replay_and_cross_project_uuid_reuse_never_disclose_the_prior_receipt():
    service, store, custodian = service_fixture()
    await service.publish_cohort_profile(publication())
    changed = publication(profile_id=OTHER)
    with pytest.raises(OpportunityError) as conflict:
        await service.publish_cohort_profile(changed)
    assert conflict.value.code is StopCode.M9_COMMAND_REPLAY_CONFLICT
    other = OpportunityProfileService(
        store=store, custodian=custodian, user_id="u1", project_name="show-b", actor_id="human-a"
    )
    with pytest.raises(OpportunityError) as foreign:
        await other.publish_cohort_profile(publication(project_name="show-b"))
    assert str(foreign.value) == "M9_COMMAND_REPLAY_CONFLICT"
    assert custodian.calls == 1
    assert len(store.events) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"authorized": False},
        {"command_id": OTHER},
        {"subject_digest": H},
        {"authorization_id": "model-checkpoint"},
        {"custodian_policy_id": "model-authority"},
        {"custodian_policy_version": "2"},
        {"custodian_evidence_digest": "not-a-digest"},
        {"admit_not_after": NOW + timedelta(seconds=31)},
        {"issued_at": NOW + timedelta(seconds=1)},
    ],
)
async def test_mismatched_or_unbounded_lease_never_creates_authority(override):
    service, store, custodian = service_fixture()
    custodian.override = override
    with pytest.raises(OpportunityError) as denied:
        await service.publish_cohort_profile(publication())
    assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
    assert not store.profiles
    assert not store.receipts
    assert not store.events


@pytest.mark.parametrize(
    ("offset", "allowed"), [(timedelta(seconds=30), True), (timedelta(seconds=30, microseconds=1), False)]
)
async def test_database_admission_deadline_is_inclusive_and_never_renewed(offset, allowed):
    service, store, custodian = service_fixture()
    custodian.after_authorization = lambda: setattr(store, "now", NOW + offset)
    if allowed:
        receipt = await service.publish_cohort_profile(publication())
        assert receipt.profile.custodian_admitted_at == NOW + offset
    else:
        with pytest.raises(OpportunityError) as denied:
            await service.publish_cohort_profile(publication())
        assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
        assert not store.events


@pytest.mark.parametrize("expired", [False, True])
async def test_crash_after_authorization_reuses_one_lease_or_refuses_an_expired_retry(expired):
    service, store, custodian = service_fixture()
    store.fail_enter = True
    with pytest.raises(RuntimeError, match="crash after authorization"):
        await service.publish_cohort_profile(publication())
    original = custodian.leases[COMMAND]
    store.fail_enter = False
    store.now += timedelta(seconds=31 if expired else 1)
    if expired:
        with pytest.raises(OpportunityError) as denied:
            await service.publish_cohort_profile(publication())
        assert denied.value.code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED
        assert not store.events
    else:
        receipt = await service.publish_cohort_profile(publication())
        assert receipt.profile.custodian_authorization_id == original.authorization_id
        assert len(store.events) == 1
    assert custodian.leases[COMMAND] == original


async def test_lost_commit_acknowledgement_reconciles_from_receipt_without_reauthorization():
    service, store, custodian = service_fixture()
    store.lose_ack = True
    with pytest.raises(ConnectionError, match="lost commit"):
        await service.publish_cohort_profile(publication())
    original = next(iter(store.receipts.values()))
    store.now += timedelta(days=1)
    replay = await service.publish_cohort_profile(publication())
    assert replay.model_dump_json() == original.model_dump_json()
    assert custodian.calls == 1
    assert len(store.events) == 1


async def test_policy_pack_and_sibling_cohort_corpus_cannot_cross_server_resolved_lineage():
    service, store, custodian = service_fixture()
    custodian.after_authorization = lambda: setattr(store, "policy", ("WESTERN_GENERIC", "1", "sha256:" + "b" * 64))
    with pytest.raises(OpportunityError) as changed:
        await service.publish_cohort_profile(publication())
    assert changed.value.code is StopCode.M9_COHORT_LEAKAGE
    assert not store.events
    store.policy = ("CN_SHORT_DRAMA_SHUANGWEN", "1", H)
    custodian.after_authorization = None
    with pytest.raises(OpportunityError) as sibling:
        await service.publish_cohort_profile(publication(command_id=OTHER))
    assert sibling.value.code is StopCode.M9_COHORT_LEAKAGE
    assert not store.profiles


async def test_stale_genesis_append_and_unknown_history_fail_before_new_writes():
    service, store, _ = service_fixture()
    await service.publish_cohort_profile(publication())
    with pytest.raises(OpportunityError) as stale:
        await service.publish_cohort_profile(publication(command_id=OTHER))
    assert stale.value.code is StopCode.M9_STALE_HEAD
    with pytest.raises(OpportunityError) as missing:
        await service.publish_cohort_profile(
            publication(command_id="019a0000-0000-7000-8000-000000000011", parent=2, head=2)
        )
    assert missing.value.code is StopCode.M9_STALE_HEAD
    for project, identity in (("show-b", ID), ("show-a", OTHER)):
        with pytest.raises(OpportunityProfileNotFoundError):
            await service.get_cohort_profile(
                OpportunityIdentityRead(user_id="u1", project_name=project, identity=identity)
            )
    assert len(store.events) == 1


async def test_replay_rejects_hash_consistent_creator_that_is_the_owner_instead_of_the_principal():
    from r2.opportunity.digests import digest_cohort_profile, digest_command_result
    from r2.opportunity.profiles import OPERATION

    service, store, custodian = service_fixture()
    original = await service.publish_cohort_profile(publication())
    changed_profile = original.profile.model_copy(update={"created_by": "u1"})
    changed_profile = changed_profile.model_copy(update={"profile_digest": digest_cohort_profile(changed_profile)})
    changed = original.model_copy(update={"profile": changed_profile})
    changed = changed.model_copy(
        update={"result_digest": digest_command_result(OPERATION, changed.request_digest, changed)}
    )
    store.receipts[next(iter(store.receipts))] = changed
    with pytest.raises(OpportunityError) as mismatched:
        await service.publish_cohort_profile(publication())
    assert mismatched.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING
    assert custodian.calls == 1
    assert len(store.events) == 1


@pytest.mark.parametrize("fault", ["profile-owner", "head-id"])
async def test_read_boundary_does_not_return_hash_valid_foreign_scope_or_head(fault):
    from r2.opportunity.digests import digest_cohort_profile

    service, store, _ = service_fixture()
    receipt = await service.publish_cohort_profile(publication())
    if fault == "profile-owner":
        foreign = receipt.profile.model_copy(update={"user_id": "default"})
        foreign = foreign.model_copy(update={"profile_digest": digest_cohort_profile(foreign)})
        store.profiles[("u1", "show-a", ID, 1)] = foreign
    else:
        store.heads[("u1", "show-a", ID)] = receipt.head.model_copy(update={"profile_id": OTHER})
    with pytest.raises(OpportunityProfileNotFoundError):
        await service.get_cohort_profile(OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=ID))


async def test_list_boundary_refuses_hash_valid_foreign_profile_from_storage():
    from r2.opportunity.digests import digest_cohort_profile

    service, store, _ = service_fixture()
    receipt = await service.publish_cohort_profile(publication())
    foreign = receipt.profile.model_copy(update={"project_name": "foreign-project"})
    foreign = foreign.model_copy(update={"profile_digest": digest_cohort_profile(foreign)})
    store.profiles[("u1", "show-a", ID, 1)] = foreign
    with pytest.raises(OpportunityError) as mismatch:
        await service.list_cohort_profiles(OpportunityReadPage(user_id="u1", project_name="show-a", after_id=None))
    assert mismatch.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING
