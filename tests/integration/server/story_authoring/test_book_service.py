"""A book through the story service (ADR-0116): a book brief, its first part committed and handed to video, then a
continuation of the project that becomes the book's next part, and a plain continuation once the book is done."""

from __future__ import annotations

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
    assert following.limits.generate_calls_max < brief.limits.generate_calls_max  # no book plan to write

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
