"""Documentary narration from a sourced fact pack (ADR-0162)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from lib.documentary import DocumentaryError, make_documentary
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

PARA_1 = (
    "Cầu Long Biên được khởi công năm 1898 và hoàn thành năm 1902, do một công ty Pháp thi công, dài khoảng "
    "1.682 mét qua sông Hồng."
)
PARA_2 = (
    "Trong chiến tranh, cây cầu bị ném bom nhiều lần nhưng vẫn được sửa chữa để tiếp tục sử dụng cho đường sắt và "
    "người đi bộ, xe máy."
)
PARA_3 = (
    "Ngày nay cầu là một biểu tượng của Hà Nội; nhiều đề xuất bảo tồn đã được đưa ra nhưng tương lai của cây cầu vẫn "
    "đang được bàn luận."
)


async def fetch(url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
    assert url == "https://vi.wikipedia.org/w/api.php"
    if params.get("list") == "search":
        return {"query": {"search": [{"title": "Cầu Long Biên"}]}}
    extract = f"{PARA_1}\n\n== Chiến tranh ==\n{PARA_2}\n\n== Ngày nay ==\n{PARA_3}"
    return {
        "query": {
            "pages": {"1": {"title": "Cầu Long Biên", "fullurl": "https://vi.wikipedia.org/wiki/x", "extract": extract}}
        }
    }


def _result(body: dict) -> TextGenerationResult:
    return TextGenerationResult(text=json.dumps(body, ensure_ascii=False), model="m", provider="p")


CLAIMS = {
    "claims": [
        {"statement": "Cầu khởi công năm 1898.", "evidence_id": "E1", "quote": "khởi công năm 1898"},
        {"statement": "Cầu hoàn thành năm 1902.", "evidence_id": "E1", "quote": "hoàn thành năm 1902"},
        {"statement": "Cầu bị ném bom nhiều lần.", "evidence_id": "E2", "quote": "bị ném bom nhiều lần"},
        {"statement": "Cầu là biểu tượng Hà Nội.", "evidence_id": "E3", "quote": "một biểu tượng của Hà Nội"},
        {"statement": "Cầu dài 3 km.", "evidence_id": "E1", "quote": "dài 3 km"},
    ],
    "uncertainties": ["tương lai của cây cầu"],
}


def _draft(cited: list[list[str]]) -> dict:
    return {
        "title": "Cây cầu trăm tuổi",
        "hook": "Vì sao một cây cầu sắt hơn trăm năm vẫn đứng giữa Hà Nội?",
        "chapters": [
            {
                "title": "Ra đời",
                "paragraphs": [{"text": "Năm 1898, công trường mở ra trên sông Hồng.", "claims": cited[0]}],
            },
            {
                "title": "Chiến tranh",
                "paragraphs": [{"text": "Bom rơi xuống nhiều lần, cây cầu vẫn đứng.", "claims": cited[1]}],
            },
        ],
    }


def test_claims_are_verified_against_their_evidence_and_every_paragraph_cites_one():
    answers = [_result(CLAIMS), _result(_draft([[], ["C3"]])), _result(_draft([["C1", "C2"], ["C3"]]))]
    prompts: list[TextGenerationRequest] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        prompts.append(request)
        return answers.pop(0)

    doc = asyncio.run(make_documentary("cầu Long Biên", language="vi", fetch=fetch, generate=generate))

    assert [c.statement for c in doc.ledger.claims] == [
        "Cầu khởi công năm 1898.",
        "Cầu hoàn thành năm 1902.",
        "Cầu bị ném bom nhiều lần.",
        "Cầu là biểu tượng Hà Nội.",
    ]
    assert all(c.status.value == "VERIFIED" for c in doc.ledger.claims)
    assert "cites no claim" in prompts[2].prompt
    assert doc.manuscript.startswith("# Cây cầu trăm tuổi\n\nVì sao")
    assert "## Chiến tranh" in doc.manuscript
    assert "https://vi.wikipedia.org/wiki/x" in doc.citations
    assert doc.research_pack.uncertainties == ["tương lai của cây cầu"]
    assert [e.locator for e in doc.evidence] == [
        "Cầu Long Biên § Lead",
        "Cầu Long Biên § Chiến tranh",
        "Cầu Long Biên § Ngày nay",
    ]


def test_a_topic_with_too_few_verified_claims_is_refused():
    async def generate(_request: TextGenerationRequest) -> TextGenerationResult:
        return _result(
            {"claims": [{"statement": "Câu này sai hoàn toàn.", "evidence_id": "E1", "quote": "không có trong nguồn"}]}
        )

    with pytest.raises(DocumentaryError, match="TOO_FEW_VERIFIED_CLAIMS"):
        asyncio.run(make_documentary("cầu Long Biên", language="vi", fetch=fetch, generate=generate))


def test_a_form_shapes_the_narration_prompt_and_an_unknown_form_is_refused():
    answers = [_result(CLAIMS), _result(_draft([["C1", "C2"], ["C3"]]))]
    prompts: list[TextGenerationRequest] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        prompts.append(request)
        return answers.pop(0)

    doc = asyncio.run(make_documentary("cầu Long Biên", language="vi", fetch=fetch, generate=generate, form="top_list"))
    assert "A countdown list" in prompts[1].prompt
    assert doc.research_pack.provenance["form"] == "top_list"
    with pytest.raises(DocumentaryError, match="UNKNOWN_FORM"):
        asyncio.run(make_documentary("x", language="vi", fetch=fetch, generate=generate, form="poem"))
