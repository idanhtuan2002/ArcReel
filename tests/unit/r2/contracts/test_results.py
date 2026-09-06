from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import (
    ApprovedMaster,
    CandidateSelectionStatus,
    GenerationCandidate,
    GenerationLifecycleStatus,
    QualityFinding,
    QualityReport,
    ReviewerType,
)


def _candidate(**overrides):
    data = dict(
        id="CAND-1",
        target_ref="SH042",
        content_fingerprint="a" * 64,
        execution_fingerprint="b" * 64,
        provider_execution_ref="job:123",
        output_asset_ref="asset:generated-1",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    data.update(overrides)
    return GenerationCandidate(**data)


def test_generation_candidate_separates_lifecycle_and_selection():
    item = _candidate()
    assert item.lifecycle_state is GenerationLifecycleStatus.GENERATED
    assert item.selection_state is CandidateSelectionStatus.UNREVIEWED


def test_failed_generation_cannot_be_selected():
    with pytest.raises(ValidationError, match="FAILED candidate cannot be SELECTED"):
        _candidate(
            lifecycle_state=GenerationLifecycleStatus.FAILED,
            selection_state=CandidateSelectionStatus.SELECTED,
        )


def test_selected_candidate_must_be_generated():
    selected = _candidate(selection_state=CandidateSelectionStatus.SELECTED)
    assert selected.lifecycle_state is GenerationLifecycleStatus.GENERATED


def test_approved_master_is_explicit_not_latest_generation():
    master = ApprovedMaster(
        id="MASTER-SH042",
        target_ref="SH042",
        selected_candidate_id="CAND-1",
        approval_record="approval:77",
        selected_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
        selected_by="showrunner:1",
    )
    assert master.selected_candidate_id == "CAND-1"


def test_quality_report_score_is_bounded_and_finding_planes_are_consistent():
    report = QualityReport(
        id="QR-1",
        target_ref="CAND-1",
        checks=["identity", "continuity"],
        score=0.95,
        blocking_findings=[
            QualityFinding(
                code="IDENTITY_DRIFT",
                message="face mismatch",
                blocking=True,
            )
        ],
        advisory_findings=[
            QualityFinding(code="MINOR", message="tiny drift", blocking=False)
        ],
        reviewer_type=ReviewerType.AGENT,
        created_at=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc),
    )
    assert report.score == 0.95

    with pytest.raises(ValidationError):
        QualityReport(**{**report.model_dump(), "score": 1.5})

    with pytest.raises(ValidationError, match="blocking_findings"):
        QualityReport(
            **{
                **report.model_dump(),
                "blocking_findings": [
                    {"code": "WRONG", "message": "wrong plane", "blocking": False}
                ],
            }
        )

    with pytest.raises(ValidationError, match="advisory_findings"):
        QualityReport(
            **{
                **report.model_dump(),
                "advisory_findings": [
                    {"code": "WRONG", "message": "wrong plane", "blocking": True}
                ],
            }
        )


def test_result_datetimes_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        ApprovedMaster(
            id="MASTER-SH043",
            target_ref="SH043",
            selected_candidate_id="CAND-2",
            approval_record="approval:78",
            selected_at=datetime(2026, 9, 6, 10, 0),
            selected_by="showrunner:1",
        )
