"""A descriptive field holding a model's reasoning, schema scaffolding or broken bytes is refused; prose is not judged.

The corrupted values are DramaClaw's observed corruption (tests/test_identity_planner_appearance_validation.py at
b299bfd); the reasoning openings are the leaks seen on our own routes."""

from __future__ import annotations

import pytest

from lib.output_hygiene import leak_reason

SCHEMA = ("appearance_details", "face_description", "age_group", "body_type")

DRAMACLAW_OBSERVED_CORRUPTION = [
    "�body_type",
    "/* empty */",
    "proportbody_typeemonia",
    "焐body_typeملاحظة",
    " بقدرbody_type_",
    "proptobody_type​",
    "♇body_type‌",
    (
        "𝔭body_type判定ing: empty for same age. Yes. Count: Let's check length of "
        "appearance_details.\n\n正常服装描述\n\nThat's about 50-60 characters. Perfect."
    ),
    "@returnsbody_type letztlich",
    "pensãobody_type}\r\n\r\n",
]


@pytest.mark.parametrize("value", DRAMACLAW_OBSERVED_CORRUPTION)
def test_dramaclaw_observed_corruption_is_refused(value: str):
    assert leak_reason(value, schema_fields=SCHEMA) is not None


@pytest.mark.parametrize(
    "value",
    [
        "Let us reason step by step before returning the final clothing description",
        "* Input: a Vietnamese story about a ferryman. Output: a title.",
        "Người dùng yêu cầu đặt tiêu đề cho tập 2, tôi sẽ chọn",
        "用户要求为第二集起标题，让我先分析一下",
        "<think>the title should be short</think> Chuyến đò cuối",
        '```json\n{"title": "Chuyến đò cuối"}\n```',
    ],
)
def test_reasoning_and_scaffolding_are_refused(value: str):
    assert leak_reason(value) is not None


@pytest.mark.parametrize(
    "value",
    [
        "Chuyến đò cuối cùng",
        "Ông lão sáu mươi tám tuổi, da sạm nắng, áo bà ba bạc màu, tay chai sần vì chèo đò.",
        "Let's go home, Ann said.",  # ordinary speech is not reasoning
        "Bến sông lúc chạng vạng, nước đục phù sa, cọc tre nghiêng, một con đò gỗ mục.",
        "最后的一趟渡河",
        "",
    ],
)
def test_clean_descriptions_pass(value: str):
    assert leak_reason(value, schema_fields=SCHEMA) is None
