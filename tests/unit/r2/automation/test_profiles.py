"""Launch metadata and reviewer calibration prerequisites are independent of runtime authority."""

import pytest


def test_launch_profiles_pin_output_and_candidate_media_routes():
    from r2.automation.profiles import resolve_launch_profile

    narration = resolve_launch_profile("fiction_narration_vi_v1")
    drama = resolve_launch_profile("fiction_drama_vi_v1")
    assert narration.language == "vi"
    assert (narration.width, narration.height, narration.video_codec, narration.audio_codec) == (
        576,
        1024,
        "h264",
        "aac",
    )
    assert narration.target_duration_seconds == 45
    assert narration.image_route == ("custom-3", "flux2-klein-4b-gguf")
    assert narration.video_route == ("custom-3", "still-clip-local")
    assert narration.audio_route == ("custom-2", "vieneu-tts-v3-turbo")
    assert narration.requires_lip_sync is False
    assert drama.requires_lip_sync is True
    assert drama.support_status == "CANDIDATE"


@pytest.mark.parametrize("identity", ["unknown", "../fiction_narration_vi_v1", "*", ""])
def test_registry_refuses_unregistered_profile(identity):
    from r2.automation.profiles import resolve_launch_profile

    with pytest.raises(ValueError, match="UNSUPPORTED_LAUNCH_PROFILE"):
        resolve_launch_profile(identity)


def test_qualification_requires_disjoint_calibration_holdout_and_critical_negatives():
    from r2.automation.profiles import reviewer_is_qualified
    from r2.contracts.automation import ReviewerQualification

    cases = [
        {
            "split": split,
            "label": label,
            "accepted": label == "CLEAN",
            "case_digest": "sha256:" + f"{i:064x}",
            "receipt_ref": f"case-{i}",
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
    record = ReviewerQualification(
        profile_digest="sha256:" + "a" * 64,
        launch_profile_id="fiction_narration_vi_v1",
        language="vi",
        provider_id="local",
        model_id="assessor-a",
        model_identity="assessor-a@weights-v1",
        config_digest="sha256:" + "a" * 64,
        prompt_digest="sha256:" + "b" * 64,
        cases=cases,
    )
    assert reviewer_is_qualified(record)
    bad = list(cases)
    bad[-1] = {**bad[-1], "accepted": True}
    assert not reviewer_is_qualified(record.model_copy(update={"cases": tuple(bad)}))
    assert not reviewer_is_qualified(record.model_copy(update={"cases": tuple(cases[:20])}))
    duplicate = list(cases)
    duplicate[-1] = {**duplicate[-1], "case_digest": cases[0]["case_digest"]}
    assert not reviewer_is_qualified(record.model_copy(update={"cases": tuple(duplicate)}))
