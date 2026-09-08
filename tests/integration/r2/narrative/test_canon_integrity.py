"""Executable Canon integrity checker over valid and intentionally corrupted fixtures."""

from __future__ import annotations

from lib.db.canon_uow import canon_projection_uow_factory
from r2.narrative.canon_state import empty_canon_content
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative.integrity import CanonIntegrityChecker, CanonIntegrityReport
from tests.integration.r2.narrative._canon_authority import (
    PROJECT,
    USER,
    Factory,
    authority_snapshot,
    commit_version,
    corrupt_version_hash_version,
    main_branch,
    seed_main_two_versions,
    seed_pinned_child,
    set_branch_head,
    set_branch_parent_branch,
    set_delta_committed_version,
    set_version_content_hash,
    set_version_number,
    set_version_parent,
)


async def run_checker(factory: Factory) -> CanonIntegrityReport:
    async with canon_projection_uow_factory(factory)() as uow:
        return await CanonIntegrityChecker(uow.repository).check_scope(project_name=PROJECT, user_id=USER)


def rule_ids(report: CanonIntegrityReport) -> list[str]:
    return [finding.rule_id for finding in report.findings]


async def test_valid_scope_passes_every_integrity_rule(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    report = await run_checker(session_factory)
    assert report.ok is True
    assert report.findings == ()


async def test_cross_branch_head_pointer_fails_closed(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await set_branch_head(session_factory, "story", "main-v1")
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_HEAD_BRANCH_MISMATCH"]


async def test_missing_and_cross_scope_head_yield_the_same_rule(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    foreign = main_branch(branch_id="other-main", user_id="user-b", project_name="project-b")
    await commit_version(
        session_factory,
        branch=foreign,
        base_content=empty_canon_content(),
        base_version_id=None,
        add_entity_id="stranger",
        version_id="foreign-v1",
        version_number=1,
        parent_version_id=None,
        delta_id="foreign-delta-1",
        approval_ref="foreign-approval-1",
        insert_branch=True,
    )

    await set_branch_head(session_factory, "main", "ghost")
    missing = rule_ids(await run_checker(session_factory))

    await set_branch_head(session_factory, "main", "foreign-v1")
    cross_scope = rule_ids(await run_checker(session_factory))

    assert missing == ["M5A_HEAD_MISSING_OR_OUT_OF_SCOPE"]
    assert cross_scope == ["M5A_HEAD_MISSING_OR_OUT_OF_SCOPE"]


async def test_null_head_with_local_versions_is_reported(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await set_branch_head(session_factory, "main", None)
    report = await run_checker(session_factory)
    assert "M5A_HEAD_NOT_LATEST" in rule_ids(report)


async def test_head_not_pointing_at_the_latest_version_is_reported(session_factory: Factory) -> None:
    await seed_main_two_versions(session_factory)
    await set_branch_head(session_factory, "main", "main-v1")
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_HEAD_NOT_LATEST"]


async def test_version_numbering_gap_is_reported(session_factory: Factory) -> None:
    await seed_main_two_versions(session_factory)
    await set_version_number(session_factory, "main-v2", 3)
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_VERSION_GAP"]


async def test_pinned_parent_on_the_wrong_branch_is_reported(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await set_branch_parent_branch(session_factory, "story", "not-the-parent")
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_PARENT_BRANCH_MISMATCH"]


async def test_local_parent_out_of_scope_is_reported(session_factory: Factory) -> None:
    await seed_main_two_versions(session_factory)
    await set_version_parent(session_factory, "main-v2", "ghost-parent")
    report = await run_checker(session_factory)
    assert {"M5A_PARENT_MISSING_OR_OUT_OF_SCOPE", "M5A_VERSION_PARENT_MISMATCH"} <= set(rule_ids(report))


async def test_delta_version_linkage_mismatch_is_reported(session_factory: Factory) -> None:
    await seed_main_two_versions(session_factory)
    await set_delta_committed_version(session_factory, "delta-main-2", "some-other-version")
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_DELTA_LINK_MISMATCH"]


async def test_unsupported_hash_selector_is_reported(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await corrupt_version_hash_version(session_factory, "main-v1")
    report = await run_checker(session_factory)
    assert "M5A_HASH_VERSION_UNSUPPORTED" in rule_ids(report)
    assert "M5A_AUTHORITATIVE_HASH_MISMATCH" not in rule_ids(report)


async def test_authoritative_hash_mismatch_is_reported(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await set_version_content_hash(session_factory, "main-v1", compute_canon_content_hash(empty_canon_content()))
    report = await run_checker(session_factory)
    assert rule_ids(report) == ["M5A_AUTHORITATIVE_HASH_MISMATCH"]


async def test_checker_is_deterministic_and_leaves_rows_untouched(session_factory: Factory) -> None:
    await seed_pinned_child(session_factory)
    await set_version_content_hash(session_factory, "main-v1", "not-a-real-hash")
    before = await authority_snapshot(session_factory)

    first = rule_ids(await run_checker(session_factory))
    second = rule_ids(await run_checker(session_factory))

    assert first == second
    assert await authority_snapshot(session_factory) == before
