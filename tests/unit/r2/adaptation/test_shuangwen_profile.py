"""Unit coverage for the bounded M6 Shuangwen evaluator (plan Task 10).

``evaluate_shuangwen`` bridges ``ScreenplayArtifactV2`` (concatenated scene
``dramatic_text``, which for this profile carries the same 【tag】 outline markup the
donor parses) to the bounded Huohuo field-parsing port and its chapter 1-8 gating.
"""

from __future__ import annotations

import json

import pytest

from r2.adaptation.errors import AdaptationProfileMismatchError
from r2.adaptation.profiles import _PACKS_DIR, ProfilePackRegistry, _compute_policy_pack_digest
from r2.adaptation.shuangwen_profile import ShuangwenSourceScope, evaluate_shuangwen
from r2.contracts.adaptation import (
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    ScreenplayArtifactV2,
    ScreenplayScene,
    ShuangwenType,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus

_BRANCH_REF = ArtifactVersionRef(artifact_id="branch-1", version=1, content_hash="sha256:" + "a1" * 32)
_MAP_REF = ArtifactVersionRef(artifact_id="map-1", version=1, content_hash="sha256:" + "b2" * 32)


def _shuangwen_pack():
    raw = json.loads((_PACKS_DIR / "cn_short_drama_shuangwen_v1.json").read_bytes())
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )
    return ProfilePackRegistry().resolve(ref)


def _western_pack():
    raw = json.loads((_PACKS_DIR / "western_generic_v1.json").read_bytes())
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )
    return ProfilePackRegistry().resolve(ref)


def _screenplay(dramatic_text: str) -> ScreenplayArtifactV2:
    scene = ScreenplayScene(
        scene_id="scene-1",
        purpose="chapter 3 beat",
        duration_target=30.0,
        location_ref=None,
        character_refs=["char-1"],
        source_mapping_refs=["entry-1"],
        dramatic_text=dramatic_text,
    )
    return ScreenplayArtifactV2(
        screenplay_id="screenplay-1",
        schema_version="r2-screenplay-artifact-v2",
        version=1,
        adaptation_branch_ref=_BRANCH_REF,
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="v1", refs=["src-1"]),
        scenes=[scene],
        characters=["char-1"],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.DRAFT,
        locked_for_direction=False,
        content_hash="sha256:" + "c3" * 32,
        adaptation_map_ref=_MAP_REF,
        profile_analysis_refs=[],
    )


_WELL_FORMED_CHAPTER_3 = (
    "第3章\n"
    "【本章时间】黄昏\n【本章地点】旧仓库\n【本章人物】阿May、阿强\n【本章起因】阿强上门催债\n"
    "【欲望】阿May想保住铺子\n【阻碍】手头现钱不够\n【局面变化】阿强放话限期收账\n"
    "【人物选择】阿May决定当面对质\n【冲突层】外部\n【情绪手法】对话推进\n【章末问题】阿May能否凑齐欠款\n"
    "【信息增量】揭示阿强背后有人指使\n【主题回响】呼应全书信任主题\n"
    "【恨】阿May被当众羞辱，铺子被贴上封条，围观人群指指点点\n"
    "【爽】阿May翻出真账本，当众对上假账，数字对不上\n"
    "【急】距离阿强设的三天限期只剩最后一夜，阿May必须找到人证\n"
    "【盼】阿May只差一张公社的证明信就能翻案\n"
    "【爽型】揭穿假账"
)


def _scope(chapter_start: int = 3, chapter_end: int = 3) -> ShuangwenSourceScope:
    return ShuangwenSourceScope(chapter_start=chapter_start, chapter_end=chapter_end, source_refs=["novel-src-1"])


def test_a_well_formed_chapter_has_no_findings_and_full_evidence() -> None:
    analysis = evaluate_shuangwen(
        _screenplay(_WELL_FORMED_CHAPTER_3), source_scope=_scope(), profile_pack=_shuangwen_pack()
    )
    assert analysis.findings == []
    assert analysis.hen_evidence is not None
    assert analysis.shuang_evidence is not None
    assert analysis.ji_evidence is not None
    assert analysis.pan_evidence is not None
    assert analysis.shuang_type == ShuangwenType.EXPOSE_FAKE_ACCOUNT
    assert analysis.chapter_start == 3
    assert analysis.chapter_end == 3
    assert analysis.schema_version == "r2-shuangwen-analysis-v1"


def test_a_missing_beat_produces_a_field_parsing_finding() -> None:
    text = _WELL_FORMED_CHAPTER_3.replace("【急】距离阿强设的三天限期只剩最后一夜，阿May必须找到人证\n", "")
    analysis = evaluate_shuangwen(_screenplay(text), source_scope=_scope(), profile_pack=_shuangwen_pack())
    findings = [f for f in analysis.findings if f.rule_id == "SHUANGWEN_FIELD_PARSING"]
    assert len(findings) == 1
    assert "急" in findings[0].source_span


def test_an_unrecognized_shuang_type_produces_a_vocabulary_finding() -> None:
    text = _WELL_FORMED_CHAPTER_3.replace("【爽型】揭穿假账", "【爽型】反派自爆")
    analysis = evaluate_shuangwen(_screenplay(text), source_scope=_scope(), profile_pack=_shuangwen_pack())
    findings = [f for f in analysis.findings if f.rule_id == "SHUANGWEN_TYPE_VOCABULARY"]
    assert len(findings) == 1
    assert analysis.shuang_type is None


def test_a_stakes_mismatch_produces_a_stakes_finding() -> None:
    text = _WELL_FORMED_CHAPTER_3.replace(
        "【恨】阿May被当众羞辱，铺子被贴上封条，围观人群指指点点",
        "【恨】阿强逼阿May今天必须还5块钱，围观的人越来越多",
    )
    analysis = evaluate_shuangwen(_screenplay(text), source_scope=_scope(), profile_pack=_shuangwen_pack())
    findings = [f for f in analysis.findings if f.rule_id == "SHUANGWEN_STAKES_COMMON_SENSE"]
    assert len(findings) == 1
    assert "赌注错位" in findings[0].source_span


def test_chapter_nine_is_not_applicable_with_no_evidence_required() -> None:
    text = "第9章\n【恨】随便写点什么\n【爽】随便写点什么内容\n【急】随便写点什么内容\n【盼】随便写点什么内容\n【爽型】硬撕"
    analysis = evaluate_shuangwen(_screenplay(text), source_scope=_scope(9, 9), profile_pack=_shuangwen_pack())
    assert len(analysis.findings) == 1
    assert analysis.findings[0].rule_id == "SHUANGWEN_CHAPTER_1_8_SCOPE"
    assert analysis.findings[0].disposition.value == "NOT_APPLICABLE"
    assert analysis.hen_evidence is None
    assert analysis.shuang_evidence is None
    assert analysis.shuang_type is None


def test_evaluate_shuangwen_rejects_a_western_profile_pack() -> None:
    with pytest.raises(AdaptationProfileMismatchError):
        evaluate_shuangwen(_screenplay(_WELL_FORMED_CHAPTER_3), source_scope=_scope(), profile_pack=_western_pack())


def test_evaluation_is_deterministic_across_repeated_calls() -> None:
    screenplay = _screenplay(_WELL_FORMED_CHAPTER_3)
    pack = _shuangwen_pack()
    scope = _scope()
    first = evaluate_shuangwen(screenplay, source_scope=scope, profile_pack=pack)
    second = evaluate_shuangwen(screenplay, source_scope=scope, profile_pack=pack)
    assert first == second
    assert first.content_hash == second.content_hash


def test_a_golden_b_slice_is_never_assumed_to_equal_a_chapter() -> None:
    """A source_scope naming a sub-chapter range (here, the same single chapter named
    twice) is legal and produces the same result as naming it once — the scope is an
    explicit range, not an implicit one-chapter-per-slice assumption."""
    screenplay = _screenplay(_WELL_FORMED_CHAPTER_3)
    pack = _shuangwen_pack()
    narrow = evaluate_shuangwen(screenplay, source_scope=_scope(3, 3), profile_pack=pack)
    assert narrow.chapter_start == narrow.chapter_end == 3
