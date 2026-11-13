"""Preflight reads prerequisite snapshots without submitting production work."""

from datetime import UTC, datetime

import pytest

from tests.integration.lib.db.repositories.test_production_runs import policy
from tests.unit.r2.contracts.test_quality import draft_data
from tests.unit.r2.quality.test_quality_profiles import publication_request, publish


def complete_snapshot():
    from r2.automation.profiles import route_digest
    from r2.contracts.automation import LaunchQualification, ModelRoute, PreflightSnapshot, ReviewerQualification

    routes = tuple(
        ModelRoute(
            role=role,
            provider_id={"image": "custom-3", "video": "custom-3", "audio": "custom-2"}.get(role, "local"),
            model_id={
                "image": "flux2-klein-4b-gguf",
                "video": "still-clip-local",
                "audio": "vieneu-tts-v3-turbo",
            }.get(role, role),
            model_identity=role,
            config_digest="sha256:" + f"{i + 1:064x}",
            local=True,
            paid=False,
            currency="USD",
            max_cost_per_call=0,
        )
        for i, role in enumerate(("writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio"))
    )
    qualifications = []
    for route in routes[2:4]:
        cases = [
            {
                "split": split,
                "label": label,
                "accepted": label == "CLEAN",
                "case_digest": "sha256:" + f"{i:064x}",
                "receipt_ref": f"{route.role}-case-{i}",
                "receipt_digest": "sha256:" + f"{i + 100:064x}",
            }
            for i, (split, label) in enumerate(
                [
                    (split, label)
                    for split in ("CALIBRATION", "HOLDOUT")
                    for label in ("CLEAN", "CRITICAL_DEFECT")
                    for _ in range(10)
                ]
            )
        ]
        qualifications.append(
            ReviewerQualification(
                profile_digest="sha256:" + "a" * 64,
                launch_profile_id="fiction_narration_vi_v1",
                language="vi",
                provider_id=route.provider_id,
                model_id=route.model_id,
                model_identity=route.model_identity,
                config_digest=route.config_digest,
                prompt_digest="sha256:" + "d" * 64,
                cases=cases,
            )
        )
    draft = draft_data()
    for requirement in draft["policy"]["assessment_requirements"]:
        for slot in requirement["slots"]:
            if slot["assessor_class"] == "HUMAN":
                slot["assessor_class"] = "MODEL"
                slot["required_independence_groups"] = 2
        model_slots = [slot for slot in requirement["slots"] if slot["assessor_class"] == "MODEL"]
        if model_slots:
            requirement["slots"] = [
                {**model_slots[0], "slot_id": "reviewer-a"},
                {**model_slots[0], "slot_id": "reviewer-b"},
            ]
            requirement["minimum_satisfied_slots"] = 2
    published = publish(publication_request(**draft))
    qualifications = [
        record.model_copy(update={"profile_digest": published.profile_digest}) for record in qualifications
    ]
    frozen = policy().model_copy(
        update={
            "profile_id": published.profile_id,
            "profile_digest": published.profile_digest,
            "routes": routes,
            "route_digests": tuple(map(route_digest, routes)),
        }
    )
    snapshot = PreflightSnapshot(
        user_id=published.user_id,
        project_name=published.project_name,
        input_digest="sha256:" + "c" * 64,
        content_mode="fiction_narration",
        generation_mode="storyboard",
        language="vi",
        routes=routes,
        profile=published,
        qualifications=qualifications,
        launch_qualification=LaunchQualification(
            owner="launch-qualification",
            receipt_ref="qualified-launch",
            digest="sha256:" + "e" * 64,
            user_id=published.user_id,
            project_name=published.project_name,
            launch_profile_id="fiction_narration_vi_v1",
            profile_digest=published.profile_digest,
            route_digests=frozen.route_digests,
            required_disk_bytes=2 * 1024**3,
            required_gpu_bytes=7 * 1024**3,
        ),
        voice_available=True,
        disk_free_bytes=20 * 1024**3,
        required_disk_bytes=2 * 1024**3,
        gpu_free_bytes=8 * 1024**3,
        required_gpu_bytes=7 * 1024**3,
        checked_at=datetime.now(UTC),
    )
    return frozen, snapshot


class SnapshotReader:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.provider_submit_count = 0

    async def read(self, *, user_id, project_name, policy):
        return self.snapshot


def test_fixture_uses_complete_independent_reviewer_corpora():
    frozen, snapshot = complete_snapshot()
    assert len(snapshot.qualifications) == 2
    assert len(snapshot.qualifications[0].cases) == 40
    assert len(frozen.routes) == 7


async def test_missing_qualified_reviewer_refuses_before_dispatch():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    reader = SnapshotReader(snapshot.model_copy(update={"qualifications": snapshot.qualifications[:1]}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert report.dispatch_allowed is False
    assert "MISSING_QUALIFIED_REVIEWER" in report.blocking_reasons
    assert reader.provider_submit_count == 0


async def test_exact_complete_prerequisites_allow_admission_check_only():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    reader = SnapshotReader(snapshot)
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert report.dispatch_allowed
    assert report.input_digest == snapshot.input_digest
    assert reader.provider_submit_count == 0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("content_mode", "advertisement", "UNSUPPORTED_CONTENT_MODE"),
        ("generation_mode", "reference_video", "UNSUPPORTED_GENERATION_MODE"),
        ("language", "en", "UNSUPPORTED_LANGUAGE"),
        ("voice_available", False, "MISSING_VOICE"),
        ("disk_free_bytes", 1, "INSUFFICIENT_DISK"),
        ("gpu_free_bytes", 1, "INSUFFICIENT_GPU"),
        ("required_gpu_bytes", 0, "RESOURCE_ENVELOPE_UNKNOWN"),
        ("profile", None, "MISSING_PUBLISHED_PROFILE"),
        ("user_id", "other", "PREFLIGHT_SCOPE_MISMATCH"),
    ],
)
async def test_missing_prerequisites_never_dispatch(field, value, reason):
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    reader = SnapshotReader(snapshot.model_copy(update={field: value}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert reason in report.blocking_reasons
    assert reader.provider_submit_count == 0


async def test_changed_model_config_cannot_silently_use_frozen_policy():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    routes = (snapshot.routes[0].model_copy(update={"config_digest": "sha256:" + "f" * 64}), *snapshot.routes[1:])
    reader = SnapshotReader(snapshot.model_copy(update={"routes": routes}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert "MODEL_CONFIG_CHANGED" in report.blocking_reasons
    assert reader.provider_submit_count == 0


def freeze_routes(frozen, snapshot, routes):
    from r2.automation.profiles import route_digest

    return (
        frozen.model_copy(update={"routes": routes, "route_digests": tuple(map(route_digest, routes))}),
        snapshot.model_copy(update={"routes": routes}),
    )


@pytest.mark.parametrize("kind", ["cloud", "paid", "alias", "media"])
async def test_frozen_policy_still_cannot_admit_unqualified_or_unbounded_routes(kind):
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    routes = list(snapshot.routes)
    if kind == "cloud":
        routes[0] = routes[0].model_copy(update={"local": False})
        frozen = frozen.model_copy(update={"local_only": True})
        expected = "CLOUD_ROUTE_FORBIDDEN"
    elif kind == "paid":
        routes[0] = routes[0].model_copy(update={"paid": True, "max_cost_per_call": None})
        expected = "UNBOUNDED_PAID_ROUTE"
    elif kind == "alias":
        routes[3] = routes[3].model_copy(update={"model_identity": routes[2].model_identity})
        expected = "REVIEWER_INDEPENDENCE_MISSING"
    else:
        routes[5] = routes[5].model_copy(update={"model_id": "unsupported-video"})
        expected = "MEDIA_ROUTE_NOT_QUALIFIED"
    frozen, snapshot = freeze_routes(frozen, snapshot, tuple(routes))
    reader = SnapshotReader(snapshot)
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert expected in report.blocking_reasons
    assert reader.provider_submit_count == 0


@pytest.mark.parametrize("kind", ["cloud", "paid", "alias"])
async def test_a_fallback_route_is_held_to_the_rules_of_the_routes_it_replaces(kind):
    """ADR-0139: a writer fallback is bounded like any route and never one of the run's reviewers."""
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    writer = next(route for route in snapshot.routes if route.role == "writer")
    reviewer = next(route for route in snapshot.routes if route.role == "reviewer_a")
    spare = writer.model_copy(update={"model_id": "spare-writer", "model_identity": "spare-writer"})
    if kind == "cloud":
        spare = spare.model_copy(update={"local": False})
        frozen = frozen.model_copy(update={"local_only": True})
        expected = "CLOUD_ROUTE_FORBIDDEN"
    elif kind == "paid":
        spare = spare.model_copy(update={"paid": True, "max_cost_per_call": None})
        expected = "UNBOUNDED_PAID_ROUTE"
    else:
        spare = spare.model_copy(update={"model_identity": reviewer.model_identity})
        expected = "REVIEWER_INDEPENDENCE_MISSING"
    clean = await ProductionPreflight(SnapshotReader(snapshot)).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    report = await ProductionPreflight(SnapshotReader(snapshot)).check(
        user_id=snapshot.user_id,
        project_name=snapshot.project_name,
        policy=frozen.model_copy(update={"fallback_routes": (spare,)}),
    )
    assert expected not in clean.blocking_reasons
    assert expected in report.blocking_reasons


async def test_a_media_route_outside_the_profile_is_admitted_by_its_passed_probe_only():
    from r2.automation.profiles import route_digest
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    routes = list(snapshot.routes)
    routes[5] = routes[5].model_copy(update={"provider_id": "custom-42", "model_id": "cloud-video-model"})
    frozen, snapshot = freeze_routes(frozen, snapshot, tuple(routes))
    probed = snapshot.model_copy(update={"media_route_probes": frozenset({route_digest(routes[5])})})
    report = await ProductionPreflight(SnapshotReader(probed)).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert "MEDIA_ROUTE_NOT_QUALIFIED" not in report.blocking_reasons
    other = snapshot.model_copy(update={"media_route_probes": frozenset({"sha256:" + "e" * 64})})
    report = await ProductionPreflight(SnapshotReader(other)).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert "MEDIA_ROUTE_NOT_QUALIFIED" in report.blocking_reasons


async def test_corrupt_profile_is_reported_as_blocking_instead_of_trusted():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    corrupted = snapshot.profile.model_copy(update={"profile_digest": "sha256:" + "f" * 64})
    reader = SnapshotReader(snapshot.model_copy(update={"profile": corrupted}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert "PROFILE_INTEGRITY_INVALID" in report.blocking_reasons
    assert reader.provider_submit_count == 0


async def test_drama_remains_blocked_without_qualified_audio_driven_route():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    frozen = frozen.model_copy(update={"launch_profile_id": "fiction_drama_vi_v1"})
    reader = SnapshotReader(snapshot.model_copy(update={"content_mode": "fiction_drama"}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert "DRAMA_ROUTE_NOT_QUALIFIED" in report.blocking_reasons
    assert reader.provider_submit_count == 0


async def test_qualification_for_another_published_profile_cannot_admit_run():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    foreign = tuple(
        record.model_copy(update={"profile_digest": "sha256:" + "f" * 64}) for record in snapshot.qualifications
    )
    reader = SnapshotReader(snapshot.model_copy(update={"qualifications": foreign}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert "MISSING_QUALIFIED_REVIEWER" in report.blocking_reasons


async def test_model_qualification_alone_does_not_qualify_launch_media_route():
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    reader = SnapshotReader(snapshot.model_copy(update={"launch_qualification": None}))
    report = await ProductionPreflight(reader).check(
        user_id=snapshot.user_id, project_name=snapshot.project_name, policy=frozen
    )
    assert not report.dispatch_allowed
    assert "LAUNCH_PROFILE_NOT_QUALIFIED" in report.blocking_reasons


async def test_storyboard_candidates_need_the_launch_profiles_pinned_qualified_judge(monkeypatch):
    from r2.automation import profiles
    from server.production_run import preflight
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    judge = next(route for route in frozen.routes if route.role == "reviewer_a")
    selecting = frozen.model_copy(
        update={
            "image_candidates": 2,
            "image_judge_identity": judge.model_identity,
            "image_judge_prompt_digest": "sha256:" + "3" * 64,
        }
    )
    launch = profiles.resolve_launch_profile(frozen.launch_profile_id)

    async def check(policy, selection, qualified):
        pinned = launch.model_copy(update={"image_selection": selection})
        monkeypatch.setattr(preflight, "resolve_launch_profile", lambda _profile_id: pinned)
        monkeypatch.setattr(preflight, "image_judge_is_qualified", lambda _selection: qualified)
        report = await ProductionPreflight(SnapshotReader(snapshot)).check(
            user_id=snapshot.user_id, project_name=snapshot.project_name, policy=policy
        )
        return "IMAGE_JUDGE_NOT_QUALIFIED" in report.blocking_reasons

    selection = profiles.ImageSelection(
        candidates=2,
        judge_model_identity=judge.model_identity,
        judge_prompt_digest="sha256:" + "3" * 64,
        qualification_evidence="docs/evidence.json",
        qualification_digest="sha256:" + "4" * 64,
    )
    assert await check(selecting, selection, True) is False
    assert await check(selecting, selection, False) is True
    assert await check(selecting, None, True) is True
    assert await check(selecting, selection.model_copy(update={"judge_model_identity": "other"}), True) is True
    assert await check(frozen, None, False) is False


async def test_the_face_identity_judge_needs_no_reviewer_route_but_its_server(monkeypatch):
    from lib.face_identity import FACE_JUDGE_IDENTITY, FACE_JUDGE_RULE_DIGEST
    from r2.automation import profiles
    from server.production_run import preflight
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    selecting = frozen.model_copy(
        update={
            "image_candidates": 2,
            "image_judge_identity": FACE_JUDGE_IDENTITY,
            "image_judge_prompt_digest": FACE_JUDGE_RULE_DIGEST,
        }
    )
    selection = profiles.ImageSelection(
        candidates=2,
        judge_model_identity=FACE_JUDGE_IDENTITY,
        judge_prompt_digest=FACE_JUDGE_RULE_DIGEST,
        qualification_evidence="docs/evidence.json",
        qualification_digest="sha256:" + "4" * 64,
    )
    pinned = profiles.resolve_launch_profile(frozen.launch_profile_id).model_copy(update={"image_selection": selection})
    monkeypatch.setattr(preflight, "resolve_launch_profile", lambda _profile_id: pinned)
    monkeypatch.setattr(preflight, "image_judge_is_qualified", lambda _selection: True)

    async def blocked() -> bool:
        report = await ProductionPreflight(SnapshotReader(snapshot)).check(
            user_id=snapshot.user_id, project_name=snapshot.project_name, policy=selecting
        )
        return "IMAGE_JUDGE_NOT_QUALIFIED" in report.blocking_reasons

    monkeypatch.setenv("ARCREEL_FACE_ID_URL", "http://127.0.0.1:8003")
    assert await blocked() is False
    monkeypatch.delenv("ARCREEL_FACE_ID_URL")
    assert await blocked() is True


async def test_a_continuity_judge_needs_the_launch_profiles_pinned_qualified_judge(monkeypatch):
    from r2.automation import profiles
    from server.production_run import preflight
    from server.production_run.preflight import ProductionPreflight

    frozen, snapshot = complete_snapshot()
    judge = next(route for route in frozen.routes if route.role == "reviewer_a")
    judged = frozen.model_copy(
        update={
            "continuity_judge_identity": judge.model_identity,
            "continuity_judge_prompt_digest": "sha256:" + "3" * 64,
        }
    )
    launch = profiles.resolve_launch_profile(frozen.launch_profile_id)

    async def blocked(policy, check, qualified):
        pinned = launch.model_copy(update={"continuity": check})
        monkeypatch.setattr(preflight, "resolve_launch_profile", lambda _profile_id: pinned)
        monkeypatch.setattr(preflight, "continuity_judge_is_qualified", lambda _check: qualified)
        report = await ProductionPreflight(SnapshotReader(snapshot)).check(
            user_id=snapshot.user_id, project_name=snapshot.project_name, policy=policy
        )
        return "CONTINUITY_JUDGE_NOT_QUALIFIED" in report.blocking_reasons

    check = profiles.ContinuityCheck(
        judge_model_identity=judge.model_identity,
        judge_prompt_digest="sha256:" + "3" * 64,
        qualification_evidence="docs/evidence.json",
        qualification_digest="sha256:" + "4" * 64,
    )
    assert await blocked(judged, check, True) is False
    assert await blocked(judged, check, False) is True
    assert await blocked(judged, None, True) is True
    assert await blocked(judged, check.model_copy(update={"judge_model_identity": "other"}), True) is True
    assert await blocked(frozen, None, False) is False
