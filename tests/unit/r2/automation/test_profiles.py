"""Launch metadata and reviewer calibration prerequisites are independent of runtime authority."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from r2.automation import profiles
from r2.automation.identity import digest_value, policy_digest
from r2.automation.profiles import ImageSelection, image_judge_is_qualified
from r2.contracts.automation import RunPolicy
from r2.contracts.common import ensure_json_value


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


def _judged(policy_data: dict, **changes) -> dict:
    return {
        **policy_data,
        "image_candidates": 2,
        "image_judge_identity": "ollama/judge@sha256:" + "2" * 64,
        "image_judge_prompt_digest": "sha256:" + "3" * 64,
        **changes,
    }


def test_a_policy_at_the_later_defaults_keeps_its_earlier_digest(policy_data):
    policy = RunPolicy.model_validate(policy_data)
    body = policy.model_dump(mode="json")
    body["checkpoints"] = []
    for field in ("image_candidates", "image_judge_identity", "image_judge_prompt_digest"):
        body.pop(field)

    assert policy_digest(policy) == digest_value("r2.production-policy.v1", ensure_json_value(body))
    assert policy_digest(RunPolicy.model_validate(_judged(policy_data))) != policy_digest(policy)


def test_storyboard_candidates_need_exactly_one_pinned_judge(policy_data):
    assert RunPolicy.model_validate(_judged(policy_data)).image_candidates == 2
    with pytest.raises(ValidationError):
        RunPolicy.model_validate(_judged(policy_data, image_judge_identity=None))
    with pytest.raises(ValidationError):
        RunPolicy.model_validate({**policy_data, "image_judge_identity": "ollama/judge@sha256:" + "2" * 64})


def test_an_image_judge_qualifies_only_through_its_pinned_evidence_file(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "REPOSITORY_ROOT", tmp_path)
    evidence = {"qualified": True, "model_identity": "ollama/judge", "prompt_digest": "sha256:" + "3" * 64}
    data = json.dumps(evidence).encode()
    (tmp_path / "evidence.json").write_bytes(data)
    selection = ImageSelection(
        candidates=2,
        judge_model_identity="ollama/judge",
        judge_prompt_digest="sha256:" + "3" * 64,
        qualification_evidence="evidence.json",
        qualification_digest="sha256:" + hashlib.sha256(data).hexdigest(),
    )

    assert image_judge_is_qualified(selection) is True
    assert image_judge_is_qualified(selection.model_copy(update={"judge_model_identity": "other"})) is False
    assert (
        image_judge_is_qualified(selection.model_copy(update={"qualification_digest": "sha256:" + "0" * 64})) is False
    )
    assert image_judge_is_qualified(selection.model_copy(update={"qualification_evidence": "../outside.json"})) is False
    (tmp_path / "evidence.json").write_bytes(json.dumps({**evidence, "qualified": False}).encode())
    assert image_judge_is_qualified(selection) is False
