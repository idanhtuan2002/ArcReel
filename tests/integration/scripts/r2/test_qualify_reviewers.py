"""Reviewer qualification over a labeled corpus with a scripted reviewer; labels never reach the reviewer."""

from __future__ import annotations

import json
from pathlib import Path

from r2.automation.assessment import ModelAssessment
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ModelRoute, QualificationCase
from scripts.r2.qualify_reviewers import cannot_qualify, qualify

ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-9",
    model_id="vl",
    model_identity="vl-7b",
    config_digest="sha256:" + "1" * 64,
    local=True,
    paid=False,
    currency="USD",
    max_cost_per_call=None,
)
GOOD = dict.fromkeys(("story", "visual", "audio", "continuity", "pacing"), 4)


class Reviewer:
    """Accepts a final unless its bytes mark it defective; it never sees the manifest labels."""

    def __init__(self, *, miss_defects: int = 0) -> None:
        self.seen: list[str] = []
        self.miss_defects = miss_defects

    async def assess(self, *, route, evidence):
        data = evidence.final_path.read_bytes()
        self.seen.append(evidence.narration_text)
        defect = data.startswith(b"defect")
        if defect and self.miss_defects:
            self.miss_defects -= 1
            defect = False
        return ModelAssessment.model_validate(
            {
                "reviewer_route_digest": "sha256:" + "2" * 64,
                "model_identity": route.model_identity,
                "prompt_digest": "sha256:" + "3" * 64,
                "subject_digest": evidence.subject_digest,
                "evidence_digest": "sha256:" + "4" * 64,
                "outcome": "COMPLETED",
                "language": "vi",
                "scores": {**GOOD, "visual": 2} if defect else GOOD,
            }
        )


def _corpus(root: Path) -> Path:
    cases = []
    for split in ("CALIBRATION", "HOLDOUT"):
        for label in ("CLEAN", "CRITICAL_DEFECT"):
            for index in range(10):
                case_id = f"{split}-{label}-{index}"
                prefix = b"defect" if label == "CRITICAL_DEFECT" else b"clean"
                (root / f"{case_id}.mp4").write_bytes(prefix + case_id.encode())
                (root / f"{case_id}.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
                (root / f"{case_id}.txt").write_text("Lời kể.", encoding="utf-8")
                cases.append(
                    {
                        "case_id": case_id,
                        "split": split,
                        "label": label,
                        "final": f"{case_id}.mp4",
                        "subtitles": f"{case_id}.srt",
                        "narration": f"{case_id}.txt",
                    }
                )
    manifest = root / "corpus.json"
    manifest.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return manifest


async def _run(tmp_path: Path, reviewer: Reviewer):
    return await qualify(
        corpus=_corpus(tmp_path),
        route=ROUTE,
        evaluator=reviewer,
        output=tmp_path / "receipts",
        profile_digest="sha256:" + "a" * 64,
        launch_profile_id="fiction_narration_vi_v1",
        language="vi",
    )


async def test_a_reviewer_that_rejects_every_defect_qualifies_with_receipts(tmp_path: Path):
    reviewer = Reviewer()
    record = await _run(tmp_path, reviewer)

    assert reviewer_is_qualified(record)
    assert len(record.cases) == 40
    assert all((tmp_path / "receipts" / case.receipt_ref).is_file() for case in record.cases)
    assert not any("CRITICAL_DEFECT" in text for text in reviewer.seen)


async def test_a_single_accepted_defect_fails_qualification(tmp_path: Path):
    record = await _run(tmp_path, Reviewer(miss_defects=1))

    assert not reviewer_is_qualified(record)


class SubtitleReviewer(Reviewer):
    """Rejects a final whose subtitles are marked defective; the final bytes alone cannot tell the cases apart."""

    async def assess(self, *, route, evidence):
        review = await super().assess(route=route, evidence=evidence)
        defect = "defect" in evidence.subtitle_path.read_text(encoding="utf-8")
        return review.model_copy(update={"scores": {**GOOD, "audio": 2} if defect else GOOD})


async def test_a_subtitle_only_defect_of_a_clean_final_is_its_own_case(tmp_path: Path):
    manifest = _corpus(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case["label"] == "CRITICAL_DEFECT":
            case["final"] = case["final"].replace("CRITICAL_DEFECT", "CLEAN")
            (tmp_path / case["subtitles"]).write_text("1\n00:00:00,000 --> 00:00:01,000\ndefect\n", encoding="utf-8")
    manifest.write_text(json.dumps(data), encoding="utf-8")

    record = await qualify(
        corpus=manifest,
        route=ROUTE,
        evaluator=SubtitleReviewer(),
        output=tmp_path / "receipts",
        profile_digest="sha256:" + "a" * 64,
        launch_profile_id="fiction_narration_vi_v1",
        language="vi",
    )

    assert len({case.case_digest for case in record.cases}) == 40
    assert reviewer_is_qualified(record)


async def test_stop_early_ends_at_the_first_answer_that_rules_the_route_out(tmp_path: Path):
    reviewer = Reviewer(miss_defects=1)

    record = await qualify(
        corpus=_corpus(tmp_path),
        route=ROUTE,
        evaluator=reviewer,
        output=tmp_path / "receipts",
        profile_digest="sha256:" + "a" * 64,
        launch_profile_id="fiction_narration_vi_v1",
        language="vi",
        stop_early=True,
    )

    assert not reviewer_is_qualified(record)
    assert len(record.cases) == 11
    assert record.cases[-1].label == "CRITICAL_DEFECT"
    assert record.cases[-1].accepted


def test_too_many_rejected_clean_cases_rule_a_route_out():
    def case(index: int, accepted: bool) -> QualificationCase:
        return QualificationCase(
            split="HOLDOUT",
            label="CLEAN",
            accepted=accepted,
            case_digest="sha256:" + f"{index:064x}",
            receipt_ref=f"r{index}",
            receipt_digest="sha256:" + f"{index:064x}",
        )

    assert not cannot_qualify([case(0, False), case(1, False)], {"HOLDOUT": 10})
    assert cannot_qualify([case(0, False), case(1, False), case(2, False)], {"HOLDOUT": 10})
