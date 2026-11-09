"""A book through the story service (ADR-0116): a book brief, its first part committed and handed to video, then a
continuation of the project that becomes the book's next part, and a plain continuation once the book is done."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from lib.db.models.canon import CanonBranchModel
from lib.project_manager import ProjectManager
from server.story_authoring.book import BookSpec
from server.story_authoring.driver import run_call_bound
from server.story_authoring.runtime import RunPhase
from server.story_authoring.service import StoryAuthoringService, StoryRunRef
from tests.integration.server.story_authoring.test_book_driver import BookModel
from tests.integration.server.story_authoring.test_executor import _provider
from tests.integration.server.story_authoring.test_service import (
    MODEL,
    PROJECT,
    SPONSOR,
    USER,
    Factory,
    _execute,
    _greenlight,
    _service,
    _upload,
)

SPEC = BookSpec(chapters=6, part_chapters=3)


async def _run_and_hand_off(
    service: StoryAuthoringService, factory: Factory, projects: ProjectManager, ref: StoryRunRef, command: str
) -> str:
    assert (await _execute(factory, ref, projects, BookModel()))["phase"] == "READY_FOR_APPROVAL"
    _, state = await service.get(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    offered = service.offered(PROJECT, state)
    assert offered is not None
    committed = await service.approve(
        user_id=USER,
        project_name=PROJECT,
        run_id=ref.run_id,
        principal=SPONSOR,
        manifest_digest_seen=offered["manifest_digest"],
        accepted_exceptions=offered["exceptions_offered"],
    )
    assert committed.phase is RunPhase.COMMITTED, committed.block_reason
    upload, _ = _upload(projects)
    record = await service.send_to_video(
        user_id=USER,
        project_name=PROJECT,
        run_id=ref.run_id,
        principal=SPONSOR,
        command_id=command,
        load_project=lambda: projects.load_project(PROJECT),
        upload=upload,
    )
    assert record.path is not None
    return record.path


async def test_a_continuation_of_a_book_project_writes_its_next_part_until_the_book_is_done(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    provider_id = await _provider(concurrent_session_factory)
    brief = await service.draft_brief(
        idea="Một người con về làng bán căn nhà của cha.",
        genre="đời thường",
        provider_id=provider_id,
        model_id=MODEL,
        book=SPEC,
    )
    assert brief.book is not None
    assert (brief.book.part, brief.book.state_digest, brief.prior) == (1, None, None)
    assert brief.limits.chapters == 3
    assert brief.limits.generate_calls_max == run_call_bound(3, book=brief.book)
    assert await service.book_progress(PROJECT) is None

    decision = await _greenlight(concurrent_session_factory, brief.digest())
    ref = await service.start(
        user_id=USER, project_name=PROJECT, principal=SPONSOR, brief=brief, gate_a_decision_id=decision
    )
    first_path = await _run_and_hand_off(service, concurrent_session_factory, projects, ref, "cmd-00000001")

    progress = await service.book_progress(PROJECT)
    assert progress is not None
    assert (progress.spec, progress.parts_done) == (SPEC, 1)

    following = await service.draft_brief(
        idea="Phần tiếp theo.",
        genre="đời thường",
        provider_id=provider_id,
        model_id=MODEL,
        project_name=PROJECT,
        prior_mode="continuation",
    )
    assert following.prior is None
    assert following.book is not None
    assert (following.book.part, following.book.state_digest) == (2, progress.state_digest)
    # No book plan to write; as the last part it may rewrite its final scene for open hooks.
    assert following.limits.generate_calls_max == run_call_bound(3, book=following.book)

    decision = await _greenlight(concurrent_session_factory, following.digest())
    ref = await service.start(
        user_id=USER, project_name=PROJECT, principal=SPONSOR, brief=following, gate_a_decision_id=decision
    )
    second_path = await _run_and_hand_off(service, concurrent_session_factory, projects, ref, "cmd-00000002")
    assert second_path > first_path  # the second part sorts after the first among the project's sources

    async with concurrent_session_factory() as session:
        branches = (
            await session.execute(select(CanonBranchModel).where(CanonBranchModel.project_name == PROJECT))
        ).scalars()
        kinds = sorted((b.branch_type, b.parent_branch_id is not None) for b in branches)
    assert kinds == [("MAIN", False), ("NARRATIVE_BRANCH", True)]  # the second story branches from the first

    done = await service.book_progress(PROJECT)
    assert done is not None
    assert done.parts_done == 2
    after = await service.draft_brief(
        idea="Viết tiếp.",
        genre="đời thường",
        provider_id=provider_id,
        model_id=MODEL,
        project_name=PROJECT,
        prior_mode="continuation",
    )
    assert (after.book, after.prior is not None) == (None, True)


async def test_a_story_whose_main_canon_was_taken_first_is_rebased_on_retry_and_commits_as_a_branch(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    provider_id = await _provider(concurrent_session_factory)
    refs = []
    for idea in ("Một người con về làng.", "Một người lái đò già."):
        brief = await service.draft_brief(idea=idea, genre="đời thường", provider_id=provider_id, model_id=MODEL)
        decision = await _greenlight(concurrent_session_factory, brief.digest())
        refs.append(
            await service.start(
                user_id=USER, project_name=PROJECT, principal=SPONSOR, brief=brief, gate_a_decision_id=decision
            )
        )
    for ref in refs:  # both record no Canon parent: neither has committed yet
        assert (await _execute(concurrent_session_factory, ref, projects, BookModel()))["phase"] == "READY_FOR_APPROVAL"

    async def approve(ref: StoryRunRef) -> RunPhase:
        _, state = await service.get(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
        offered = service.offered(PROJECT, state)
        assert offered is not None
        done = await service.approve(
            user_id=USER,
            project_name=PROJECT,
            run_id=ref.run_id,
            principal=SPONSOR,
            manifest_digest_seen=offered["manifest_digest"],
            accepted_exceptions=offered["exceptions_offered"],
        )
        return done.phase

    assert await approve(refs[0]) is RunPhase.COMMITTED
    assert await approve(refs[1]) is RunPhase.COMMIT_BLOCKED
    _, blocked = await service.get(user_id=USER, project_name=PROJECT, run_id=refs[1].run_id)
    assert "CANON_BASE_MOVED" in (blocked.block_reason or "")

    retried = await service.retry(user_id=USER, project_name=PROJECT, run_id=refs[1].run_id, principal=SPONSOR)
    assert retried.phase is RunPhase.RUNNING
    rerun = BookModel()
    assert (await _execute(concurrent_session_factory, refs[1], projects, rerun))["phase"] == "READY_FOR_APPROVAL"
    assert rerun.calls["working_title"] == 0  # planning is kept; only the scenes are written again on the new Canon
    assert rerun.calls["prose"] > 0
    assert await approve(refs[1]) is RunPhase.COMMITTED
    async with concurrent_session_factory() as session:
        branches = (
            await session.execute(select(CanonBranchModel).where(CanonBranchModel.project_name == PROJECT))
        ).scalars()
        kinds = sorted((b.branch_type, b.parent_branch_id is not None) for b in branches)
    assert kinds == [("MAIN", False), ("NARRATIVE_BRANCH", True)]


async def test_a_main_canon_still_being_created_by_another_run_blocks_the_commit_for_a_rebase(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    service = _service(concurrent_session_factory, grants, projects)
    provider_id = await _provider(concurrent_session_factory)
    brief = await service.draft_brief(
        idea="Một người lái đò già.", genre="đời thường", provider_id=provider_id, model_id=MODEL
    )
    decision = await _greenlight(concurrent_session_factory, brief.digest())
    ref = await service.start(
        user_id=USER, project_name=PROJECT, principal=SPONSOR, brief=brief, gate_a_decision_id=decision
    )
    assert (await _execute(concurrent_session_factory, ref, projects, BookModel()))["phase"] == "READY_FOR_APPROVAL"
    async with concurrent_session_factory() as session:  # another run created MAIN and has not committed it yet
        session.add(
            CanonBranchModel(
                branch_id="story-other-canon",
                user_id=USER,
                project_name=PROJECT,
                branch_type="MAIN",
                parent_branch_id=None,
                parent_version_id=None,
                head_version_id=None,
                created_at=datetime.now(UTC),
                created_by="run:other",
            )
        )
        await session.commit()
    _, state = await service.get(user_id=USER, project_name=PROJECT, run_id=ref.run_id)
    offered = service.offered(PROJECT, state)
    assert offered is not None

    blocked = await service.approve(
        user_id=USER,
        project_name=PROJECT,
        run_id=ref.run_id,
        principal=SPONSOR,
        manifest_digest_seen=offered["manifest_digest"],
        accepted_exceptions=offered["exceptions_offered"],
    )

    assert blocked.phase is RunPhase.COMMIT_BLOCKED
    assert "CANON_BASE_MOVED" in (blocked.block_reason or "")
    retried = await service.retry(user_id=USER, project_name=PROJECT, run_id=ref.run_id, principal=SPONSOR)
    assert retried.phase is RunPhase.RUNNING


async def test_a_brief_carries_the_projects_content_safety_level(
    concurrent_session_factory: Factory, grants, projects: ProjectManager
):
    import json as _json

    service = _service(concurrent_session_factory, grants, projects)
    provider_id = await _provider(concurrent_session_factory)
    path = projects.get_project_path(PROJECT) / "project.json"
    draft = {"idea": "Một người lái đò.", "genre": "đời thường", "provider_id": provider_id, "model_id": MODEL}

    plain = await service.draft_brief(**draft, project_name=PROJECT)
    data = _json.loads(path.read_text(encoding="utf-8"))
    path.write_text(_json.dumps({**data, "content_safety": "mature"}), encoding="utf-8")
    mature = await service.draft_brief(**draft, project_name=PROJECT)

    assert plain.content_safety == "standard"
    assert "content_safety" not in plain.model_dump(mode="json")
    assert mature.content_safety == "mature"
    assert mature.digest() != plain.digest()
